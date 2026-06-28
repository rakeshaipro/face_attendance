"""Settings group — single bulk endpoint for every runtime-configurable
setting (SRS §6.4).

The previous `/api/v1/settings` route was a 501 stub; this replaces it
with a real implementation that backs the Device and System editors.

  GET  /api/v1/settings        every setting, grouped + masked  (§6.4.1)
  PUT  /api/v1/settings        batch update with per-key validation (§6.4.2)

Sensitive values (credentials) are never returned. The Device page
also keeps the dedicated /device/camera endpoint for the password-aware
camera-credentials form; both paths share the same underlying KV.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readonly
from app.core.settings_store import get_all_grouped, get_camera_auth_url, set_many
from app.db import get_db
from app.engine.service import service
from app.models import ApiKey
from app.schemas.common import Envelope
from app.schemas.settings import (
    SettingItem,
    SettingsList,
    SettingsUpdateBody,
    SettingUpdateResult,
    SettingsUpdateResultList,
)

router = APIRouter(prefix="/settings", tags=["settings"])


# Keys that, when written, must hot-swap the live engine / stream.
# The actual refresh happens after commit so the DB write is durable
# before the engine picks up the new values.
_HOT_RELOAD_KEYS = {
    "device.camera_url",
    "device.camera_username",
    "device.camera_password",
    "engine.read_fps",
    "engine.detect_fps",
    "engine.similarity_threshold",
    "engine.cooldown_seconds",
    "engine.min_face_ratio",
}


@router.get("", response_model=Envelope[SettingsList])
def list_settings(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[SettingsList]:
    """Return every known setting, grouped by card, sensitive values
    masked (presence only)."""
    return Envelope(data=SettingsList(items=[SettingItem(**row) for row in get_all_grouped(db)]))


@router.put("", response_model=Envelope[SettingsUpdateResultList])
def update_settings(
    body: SettingsUpdateBody,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> Envelope[SettingsUpdateResultList]:
    """Apply a batch of updates. Returns per-key ok/error so the
    frontend can highlight the failing rows. Settings are committed
    one at a time so a single bad key doesn't roll back the rest."""
    raw_items = [item.model_dump() for item in body.items]
    results = set_many(db, raw_items)

    # Hot-swap live engine / stream state if any of the keys we care
    # about were touched. Camera URL is the only one that needs an
    # explicit refresh call; the engine picks up its own thresholds
    # on the next 5s tick.
    touched = {body.items[i].key for i, r in enumerate(results) if r["ok"]}
    if touched & _HOT_RELOAD_KEYS:
        service.set_camera_url(get_camera_auth_url(db))
        # Force the engine to refresh its cached settings on the next
        # _refresh_settings tick by resetting the TTL marker.
        service.invalidate_settings()

    return Envelope(
        data=SettingsUpdateResultList(
            items=[SettingUpdateResult(**r) for r in results]
        )
    )
