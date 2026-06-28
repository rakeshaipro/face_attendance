"""Typed accessor over the `system_settings` KV table.

Reads cache their values per-session; writes go through `set_value` and
invalidate the cache. Values are stored as text (§6.4.1) and coerced on
read.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.engine.defaults import (
    DEFAULTS,
    defaults_dict,
    is_encrypted as _is_encrypted,
    meta as _meta,
    validate as _validate,
)
from app.models import SystemSetting

_CACHE: dict[str, str] = {}
# Backwards-compat alias used by callers that predated defaults.META.
_ENCRYPTED_KEYS = {"device.camera_url", "device.camera_password", "smtp.password_encrypted"}


def _raw(db: Session, key: str) -> str:
    if key in _CACHE:
        return _CACHE[key]
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    value = row.value if row is not None else defaults_dict().get(key, "")
    _CACHE[key] = value
    return value


def get_value(db: Session, key: str) -> str:
    """Return the stored value (decrypting if it's a sensitive key)."""
    raw = _raw(db, key)
    if _is_encrypted(key) and raw:
        try:
            return decrypt(raw)
        except Exception:
            return raw
    return raw


def get_masked(db: Session, key: str) -> str:
    """Return a display-safe version of a sensitive value (§3.1.9, §3.13.9).

    For the camera URL, mask the username and hide the password entirely
    (credentials are stored separately and composed in at read time).
    """
    value = get_value(db, key)
    if key == "device.camera_url":
        user = get_value(db, "device.camera_username")
        if user:
            # value is "<scheme>://<host>/..."; show scheme://***@host/...
            if "://" in value:
                scheme, rest = value.split("://", 1)
                return f"{scheme}://***@{rest}"
            return "***@" + value
        return value
    return value


def get_camera_auth_url(db: Session) -> str:
    """Compose the camera URL with credentials embedded as userinfo.

    Reads the base `device.camera_url` (without creds) plus the
    separately-stored `device.camera_username` / `device.camera_password`,
    and returns a single URL suitable for `cv2.VideoCapture` /
    `requests` / the MJPEG proxy. If no username is set, the base URL is
    returned as-is.

    The username and password are URL-percent-encoded so that special
    characters (e.g. '@' in `password@12`) don't break userinfo parsing.
    """
    from urllib.parse import quote, urlsplit, urlunsplit

    base = get_value(db, "device.camera_url")
    user = get_value(db, "device.camera_username")
    if not user:
        return base
    password = get_value(db, "device.camera_password")
    parts = urlsplit(base)
    userinfo = quote(user, safe="")
    if password:
        userinfo += ":" + quote(password, safe="")
    # Replace any userinfo already present in the base URL.
    return urlunsplit((parts.scheme, f"{userinfo}@{parts.hostname}{(':' + str(parts.port)) if parts.port else ''}", parts.path, parts.query, parts.fragment))


def get_int(db: Session, key: str) -> int:
    try:
        return int(_raw(db, key))
    except (TypeError, ValueError):
        return 0


def get_float(db: Session, key: str) -> float:
    try:
        return float(_raw(db, key))
    except (TypeError, ValueError):
        return 0.0


def get_bool(db: Session, key: str) -> bool:
    return _raw(db, key).strip().lower() in {"1", "true", "yes", "on"}


def set_value(db: Session, key: str, value: str, *, encrypt_value: bool | None = None) -> None:
    if encrypt_value is None:
        encrypt_value = _is_encrypted(key)
    stored = encrypt(value) if (encrypt_value and value) else value
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        row = SystemSetting(key=key, value=stored)
        db.add(row)
    else:
        row.value = stored
    db.commit()
    _CACHE.pop(key, None)


def seed_defaults(db: Session) -> int:
    """Insert any missing default settings. Returns the count seeded."""
    seeded = 0
    for key, value, description in DEFAULTS:
        exists = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
        if exists is not None:
            continue
        stored = encrypt(value) if _is_encrypted(key) and value else value
        db.add(SystemSetting(key=key, value=stored, description=description))
        seeded += 1
    if seeded:
        db.commit()
    _CACHE.clear()
    return seeded


# --- Bulk accessors for the /api/v1/settings endpoint -----------------
def get_all_grouped(db: Session) -> list[dict]:
    """Return every known setting, grouped and masked where sensitive.

    The result is shaped for the frontend: each item carries its
    `key`, current `value` (or `value_set` flag for sensitive keys),
    type, label, help, and grouping metadata. This is the canonical
    payload for the Device and System editors.
    """
    out: list[dict] = []
    for key in defaults_dict():
        m = _meta(key)
        sensitive = bool(m.get("sensitive"))
        if sensitive:
            # Never return the plaintext. `value_set` mirrors the
            # password_set convention used by /device/camera.
            out.append({
                "key": key,
                "value": "",
                "value_set": bool(get_value(db, key)),
                "type": m["type"],
                "group": m.get("group", "system"),
                "subsection": m.get("subsection", "Other"),
                "label": m.get("label", key),
                "help": m.get("help", ""),
                "sensitive": True,
                "min": m.get("min"),
                "max": m.get("max"),
                "step": m.get("step"),
                "choices": m.get("choices"),
            })
        else:
            out.append({
                "key": key,
                "value": get_value(db, key),
                "value_set": False,
                "type": m["type"],
                "group": m.get("group", "system"),
                "subsection": m.get("subsection", "Other"),
                "label": m.get("label", key),
                "help": m.get("help", ""),
                "sensitive": False,
                "min": m.get("min"),
                "max": m.get("max"),
                "step": m.get("step"),
                "choices": m.get("choices"),
            })
    return out


def set_many(db: Session, items: list[dict]) -> list[dict]:
    """Apply a batch of `{key, value, clear?}` writes.

    Returns a list of `{key, ok, error}` entries — one per input item —
    so the caller can show per-field errors. All-OK batches commit once
    at the end; a partial failure leaves earlier writes in place (the
    frontend only needs to red-flag the failing rows).
    """
    results: list[dict] = []
    # Drop unknown keys early.
    valid_keys = set(defaults_dict())
    for item in items:
        key = item.get("key", "")
        if key not in valid_keys:
            results.append({"key": key, "ok": False, "error": "Unknown setting."})
            continue
        if item.get("clear") is True:
            # Treat as a reset to the default value (and clear encryption).
            default_value = defaults_dict().get(key, "")
            set_value(db, key, default_value)
            results.append({"key": key, "ok": True, "error": ""})
            continue
        raw = str(item.get("value", ""))
        ok, err = _validate(key, raw)
        if not ok:
            results.append({"key": key, "ok": False, "error": err})
            continue
        set_value(db, key, raw)
        results.append({"key": key, "ok": True, "error": ""})
    return results
