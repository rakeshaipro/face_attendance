"""Default values for every runtime-configurable setting (SRS §6.4.1).

Seeded into the `system_settings` table on first run and whenever a key
is missing. Keys are deliberately namespaced with dots.

`META` is the single source of truth for UI grouping, type, valid
range, and whether a key is sensitive (stored encrypted). The bulk
`/api/v1/settings` API uses `META` to drive both reads and writes —
adding a new runtime setting should be a one-line change here.
"""
from __future__ import annotations

from typing import Any, Literal

# (key, default value, human description)
DEFAULTS: list[tuple[str, str, str]] = [
    # --- Device identity (§3.1.1, §3.1.2) ---------------------------
    ("device.machine_id", "SITE-DEFAULT-01", "Unique identifier for this installation"),
    ("device.location_name", "Unconfigured Location", "Human-readable location name"),
    ("device.timezone", "UTC", "IANA timezone for all timestamps"),
    # --- Camera (§3.1.3) -------------------------------------------
    (
        "device.camera_url",
        "rtsp://192.168.1.111:554/cam/realmonitor?channel=1&subtype=0",
        "RTSP stream URL of the Dahua IP camera (without embedded credentials)",
    ),
    ("device.camera_username", "admin", "Camera RTSP/HTTP username"),
    ("device.camera_password", "", "Camera RTSP/HTTP password (encrypted)"),
    ("device.ntp_server", "pool.ntp.org", "NTP server address for clock sync"),
    # --- Recognition engine (§3.4) ---------------------------------
    # Tuned against ArcFace buffalo_l + the reference IP-camera demo
    # (face_attendance_kimi). Cosine similarity for genuine matches under
    # real door-camera lighting/pose is typically 0.40–0.85; impostors stay
    # below ~0.35. Default 0.45 maximises true-positive rate; false
    # positives are controlled by match_margin + match_confirm_window.
    ("engine.read_fps", "10", "Frame read rate (frames/sec)"),
    ("engine.detect_fps", "5", "Face detection rate (frames/sec)"),
    ("engine.similarity_threshold", "0.45", "Cosine similarity match threshold (0.35–0.95)"),
    ("engine.cooldown_seconds", "60", "Per-employee cooldown window in seconds (0–3600)"),
    ("engine.min_face_ratio", "0.08", "Minimum face width as fraction of frame width"),
    ("engine.min_det_score", "0.50", "Minimum RetinaFace detection confidence to keep (0.0–1.0)"),
    ("engine.detect_width", "0", "Downscale frame width for detection in px (0 = full resolution)"),
    ("engine.match_confirm_window", "2", "Consecutive same-match frames required before logging (1 = no smoothing)"),
    ("engine.match_margin", "0.10", "Min gap between best and 2nd-best *different* employee (0 = off)"),
    # --- Enrollment (§3.3) -----------------------------------------
    # Stricter than recognition: bad gallery embeddings poison every future
    # match. Enrollment det_score 0.60 mirrors the reference demo.
    ("enroll.quality_threshold", "0.40", "Minimum face quality score to accept a capture"),
    ("enroll.min_overall_quality", "0.50", "Minimum overall enrollment quality rating"),
    ("enroll.min_det_score", "0.60", "Minimum RetinaFace detection confidence for enrollment captures"),
    # --- Retention (§3.12.3, §3.12.4) ------------------------------
    ("retention.logs_days", "365", "Attendance log retention in days (0 = forever)"),
    ("retention.snapshots_days", "90", "Snapshot image retention in days"),
    # --- Storage monitoring (§3.11.2) ------------------------------
    ("monitor.disk_threshold_mb", "500", "Free-disk threshold in MB for storage_low alerts"),
    # --- Batch sync (§3.7.6, §3.7.10) ------------------------------
    ("sync.batch_size", "100", "Max records per batch sync request"),
    ("sync.auto_enabled", "false", "Enable periodic automatic batch sync"),
    ("sync.auto_interval_seconds", "300", "Auto-sync interval in seconds"),
    ("sync.batch_url", "", "HRMS bulk endpoint URL"),
    # --- SMTP alerts (§3.11.4) -------------------------------------
    ("smtp.enabled", "false", "Enable SMTP email alerts"),
    ("smtp.host", "", "SMTP server host"),
    ("smtp.port", "587", "SMTP server port"),
    ("smtp.username", "", "SMTP username"),
    ("smtp.password_encrypted", "", "SMTP password (encrypted)"),
    ("smtp.from_addr", "", "From: address"),
    ("smtp.recipients", "", "Comma-separated recipient list"),
    ("smtp.camera_offline_minutes", "5", "Minutes offline before a camera email alert"),
    # --- Backup schedule (§3.10.8, §3.10.9) ------------------------
    ("backup.schedule_enabled", "false", "Enable scheduled automatic backups"),
    ("backup.schedule_frequency", "daily", "daily | weekly"),
    ("backup.schedule_time", "02:00", "HH:MM local time for scheduled backups"),
    ("backup.max_scheduled", "14", "Max scheduled backup files to retain"),
    # --- System (§3.12.6) ------------------------------------------
    ("system.log_retention_days", "90", "System log retention (fixed 90 days)"),
]


def defaults_dict() -> dict[str, str]:
    return {k: v for k, v, _ in DEFAULTS}


# --- Metadata: grouping, type, validation, sensitivity -----------------
# group      : which top-level page hosts the editor (device | system)
# subsection : label of the card within the page
# type       : str | int | float | bool | enum
# sensitive  : True if value is stored encrypted (credentials, etc.)
# min / max  : inclusive bounds for numeric types
# choices    : allowed values for "enum"
# label      : human-readable field name shown in the UI
# help       : extra helper text shown beneath the input
SettingType = Literal["str", "int", "float", "bool", "enum"]

META: dict[str, dict[str, Any]] = {
    "device.machine_id":      {"group": "device", "subsection": "Identity",     "type": "str",  "label": "Machine ID",      "help": "Unique identifier for this installation."},
    "device.location_name":   {"group": "device", "subsection": "Identity",     "type": "str",  "label": "Location",        "help": "Human-readable location name."},
    "device.timezone":        {"group": "device", "subsection": "Identity",     "type": "str",  "label": "Timezone",        "help": "IANA timezone, e.g. UTC, Asia/Kolkata."},
    "device.ntp_server":      {"group": "device", "subsection": "Identity",     "type": "str",  "label": "NTP server",      "help": "Used for periodic clock synchronisation."},
    "device.camera_url":      {"group": "device", "subsection": "Camera",       "type": "str",  "label": "Camera stream URL", "help": "RTSP URL without embedded credentials."},
    "device.camera_username": {"group": "device", "subsection": "Camera",       "type": "str",  "label": "Camera username", "help": "Used for HTTP basic auth on the stream."},
    "device.camera_password": {"group": "device", "subsection": "Camera",       "type": "str",  "sensitive": True, "label": "Camera password", "help": "Leave blank to keep the current value."},
    "engine.read_fps":        {"group": "device", "subsection": "Recognition",  "type": "int",  "min": 1, "max": 30, "label": "Read FPS",        "help": "Frames read per second from the camera."},
    "engine.detect_fps":      {"group": "device", "subsection": "Recognition",  "type": "int",  "min": 1, "max": 30, "label": "Detect FPS",      "help": "Face detections per second."},
    "engine.similarity_threshold": {"group": "device", "subsection": "Recognition", "type": "float", "min": 0.35, "max": 0.95, "step": 0.01, "label": "Similarity threshold", "help": "Cosine similarity required for a match. ArcFace sweet spot is ~0.40–0.50; higher = fewer false accepts, more misses."},
    "engine.cooldown_seconds": {"group": "device", "subsection": "Recognition", "type": "int", "min": 0, "max": 3600, "label": "Cooldown (s)", "help": "Per-employee cooldown window in seconds (0–3600)."},
    "engine.min_face_ratio":   {"group": "device", "subsection": "Recognition", "type": "float", "min": 0.01, "max": 0.50, "step": 0.01, "label": "Min face ratio", "help": "Minimum face width as fraction of frame width. Lower catches distant faces; too low hurts embedding quality."},
    "engine.min_det_score":        {"group": "device", "subsection": "Recognition", "type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "label": "Min detection score", "help": "RetinaFace detection confidence below which a face is discarded (helps reject ghost detections)."},
    "engine.detect_width":         {"group": "device", "subsection": "Recognition", "type": "int", "min": 0, "max": 3840, "label": "Detect width (px)", "help": "Downscale frames to this width before face detection (0 = full resolution). Lower = faster CPU, worse on small/distant faces."},
    "engine.match_confirm_window": {"group": "device", "subsection": "Recognition", "type": "int", "min": 1, "max": 10, "label": "Match confirm window", "help": "Consecutive above-threshold matches of the same employee required before logging (1 = log on first match). 2–3 cuts transient false positives."},
    "engine.match_margin":         {"group": "device", "subsection": "Recognition", "type": "float", "min": 0.0, "max": 0.50, "step": 0.01, "label": "Match margin", "help": "Reject when best match is within this cosine gap of a different employee (0 = disable). Prevents look-alike mis-punches."},

    "enroll.quality_threshold":     {"group": "system", "subsection": "Enrollment", "type": "float", "min": 0.0, "max": 1.0, "step": 0.01, "label": "Per-capture quality", "help": "Minimum face quality score to accept a capture. Higher = sharper, better-lit enrollments."},
    "enroll.min_overall_quality":   {"group": "system", "subsection": "Enrollment", "type": "float", "min": 0.0, "max": 1.0, "step": 0.01, "label": "Overall quality",    "help": "Minimum overall enrollment quality rating."},
    "enroll.min_det_score":         {"group": "system", "subsection": "Enrollment", "type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "label": "Enrollment det. score", "help": "Stricter RetinaFace floor used only during enrollment (ghost faces must not enter the gallery)."},

    "retention.logs_days":      {"group": "system", "subsection": "Retention", "type": "int", "min": 0, "max": 3650, "label": "Attendance log retention (days)", "help": "0 = keep forever."},
    "retention.snapshots_days": {"group": "system", "subsection": "Retention", "type": "int", "min": 0, "max": 3650, "label": "Snapshot retention (days)",       "help": "How long snapshot images are kept."},

    "monitor.disk_threshold_mb": {"group": "system", "subsection": "Storage", "type": "int", "min": 50, "max": 100000, "label": "Free-disk threshold (MB)", "help": "storage_low alert fires below this."},

    "sync.batch_size":            {"group": "system", "subsection": "Sync", "type": "int",  "min": 1, "max": 1000, "label": "Batch size", "help": "Max records per batch request."},
    "sync.auto_enabled":          {"group": "system", "subsection": "Sync", "type": "bool", "label": "Auto-sync enabled", "help": "Periodically push attendance to the HRMS."},
    "sync.auto_interval_seconds": {"group": "system", "subsection": "Sync", "type": "int",  "min": 30, "max": 86400, "label": "Auto-sync interval (s)", "help": "Seconds between auto-sync runs."},
    "sync.batch_url":             {"group": "system", "subsection": "Sync", "type": "str",  "label": "HRMS endpoint", "help": "URL of the HRMS bulk endpoint."},

    "smtp.enabled":               {"group": "system", "subsection": "Email alerts", "type": "bool", "label": "Enable SMTP", "help": "Send alerts via email."},
    "smtp.host":                  {"group": "system", "subsection": "Email alerts", "type": "str",  "label": "SMTP host", "help": "SMTP server hostname."},
    "smtp.port":                  {"group": "system", "subsection": "Email alerts", "type": "int",  "min": 1, "max": 65535, "label": "SMTP port", "help": "Usually 25, 465 or 587."},
    "smtp.username":              {"group": "system", "subsection": "Email alerts", "type": "str",  "label": "SMTP username", "help": "Leave blank if the server does not require auth."},
    "smtp.password_encrypted":    {"group": "system", "subsection": "Email alerts", "type": "str",  "sensitive": True, "label": "SMTP password", "help": "Leave blank to keep the current value."},
    "smtp.from_addr":             {"group": "system", "subsection": "Email alerts", "type": "str",  "label": "From address", "help": "e.g. alerts@example.com."},
    "smtp.recipients":            {"group": "system", "subsection": "Email alerts", "type": "str",  "label": "Recipients", "help": "Comma-separated list of email addresses."},
    "smtp.camera_offline_minutes":{"group": "system", "subsection": "Email alerts", "type": "int",  "min": 1, "max": 1440, "label": "Camera-offline alert (min)", "help": "Minutes the camera must be offline before an alert is sent."},

    "backup.schedule_enabled":    {"group": "system", "subsection": "Backups", "type": "bool", "label": "Scheduled backups", "help": "Run automatic backups on a schedule."},
    "backup.schedule_frequency":  {"group": "system", "subsection": "Backups", "type": "enum", "choices": ["daily", "weekly"], "label": "Frequency", "help": "How often to run the scheduled backup."},
    "backup.schedule_time":       {"group": "system", "subsection": "Backups", "type": "str",  "label": "Schedule time (HH:MM)", "help": "Local time of day to run the backup."},
    "backup.max_scheduled":       {"group": "system", "subsection": "Backups", "type": "int",  "min": 1, "max": 365, "label": "Max scheduled backups retained", "help": "Older scheduled backups are pruned."},

    "system.log_retention_days":  {"group": "system", "subsection": "System", "type": "int", "min": 1, "max": 3650, "label": "System log retention (days)", "help": "How long system log rows are kept."},
}

# Keys that have always been stored encrypted on disk. Mirrors the
# previous hard-coded set in settings_store.
_ENCRYPTED_KEYS: set[str] = {k for k, v in META.items() if v.get("sensitive")}


def is_encrypted(key: str) -> bool:
    return key in _ENCRYPTED_KEYS


def meta(key: str) -> dict[str, Any]:
    """Return the metadata for `key`, or a permissive default."""
    return META.get(key, {"group": "system", "subsection": "Other", "type": "str", "label": key})


def coerce(key: str, raw: str) -> Any:
    """Coerce the string `raw` to the type declared in META. Raises
    ValueError on bad input."""
    m = meta(key)
    t: str = m["type"]
    if t == "str":
        return raw
    if t == "int":
        if raw.strip() == "":
            raise ValueError("must be an integer")
        return int(raw)
    if t == "float":
        if raw.strip() == "":
            raise ValueError("must be a number")
        return float(raw)
    if t == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if t == "enum":
        if raw not in m.get("choices", []):
            raise ValueError(f"must be one of: {', '.join(m.get('choices', []))}")
        return raw
    raise ValueError(f"unknown type {t!r}")


def validate(key: str, raw: str) -> tuple[bool, str]:
    """Validate a raw string against META. Returns (ok, error_message)."""
    m = meta(key)
    t: str = m["type"]
    try:
        if t == "int":
            v = int(raw)
        elif t == "float":
            v = float(raw)
        elif t == "bool":
            v = raw.strip().lower() in {"1", "true", "yes", "on"}
        elif t == "enum":
            if raw not in m.get("choices", []):
                return False, f"Must be one of: {', '.join(m.get('choices', []))}."
            return True, ""
        else:
            return True, ""
    except (TypeError, ValueError):
        if t in {"int", "float"}:
            return False, "Must be a number."
        return False, "Invalid value."

    if "min" in m and v < m["min"]:
        return False, f"Must be ≥ {m['min']}."
    if "max" in m and v > m["max"]:
        return False, f"Must be ≤ {m['max']}."
    return True, ""
