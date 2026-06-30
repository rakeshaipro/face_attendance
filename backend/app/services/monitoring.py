"""Monitoring + retention jobs (SRS §3.11, §3.12.3–3.12.6).

Pure service functions that run inside APScheduler jobs. They read their
configuration from the settings store, perform retention purges, fire
storage-low events, and send SMTP alerts. Keeping them free of scheduler
state makes them easy to unit-test.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import BACKUP_DIR, DATA_DIR, DB_PATH, SNAPSHOT_DIR
from app.core.enums import EVENT_CAMERA_OFFLINE, EVENT_STORAGE_LOW
from app.core.settings_store import get_bool, get_int, get_value
from app.events import bus
from app.models import AttendanceLog, SystemLog
from app.services.system_log import write_system_log

logger = logging.getLogger(__name__)

# Minimum free space before we warn regardless of configured threshold (MB).
_MIN_SANE_FREE_MB = 50


def _free_mb(path: Path) -> float:
    """Return free disk space for the volume containing `path` in MB."""
    usage = shutil.disk_usage(path)
    return usage.free / (1024 * 1024)


def check_disk_space(db: Session) -> bool:
    """Fire `device.storage_low` when free space is below threshold.

    Returns True if an alert was fired. The event is published on the bus
    so the webhook dispatcher (already subscribed in Phase 4) can deliver it.
    """
    threshold_mb = max(_MIN_SANE_FREE_MB, get_int(db, "monitor.disk_threshold_mb"))
    free_mb = _free_mb(DATA_DIR)
    if free_mb >= threshold_mb:
        return False

    payload = {
        "free_mb": round(free_mb, 2),
        "threshold_mb": threshold_mb,
        "data_dir": str(DATA_DIR),
        "machine": _machine_info(db),
    }
    bus.publish(EVENT_STORAGE_LOW, payload)
    write_system_log(
        db,
        severity="warning",
        event="monitor.storage_low",
        message=f"Free disk space low: {free_mb:.1f} MB (threshold {threshold_mb} MB)",
        context={"free_mb": round(free_mb, 2), "threshold_mb": threshold_mb},
    )
    return True


def purge_attendance_logs(db: Session) -> int:
    """Delete attendance logs older than retention.logs_days (§3.12.3).

    Returns the number of rows deleted. A retention of 0 means keep forever.
    """
    days = get_int(db, "retention.logs_days")
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = delete(AttendanceLog).where(AttendanceLog.timestamp < cutoff)
    result = db.execute(stmt)
    db.commit()
    deleted = result.rowcount
    if deleted:
        logger.info("purged %d attendance logs older than %s", deleted, cutoff.isoformat())
        write_system_log(
            db,
            event="retention.attendance",
            message=f"Purged {deleted} attendance logs older than {days} days",
            context={"days": days, "cutoff": cutoff.isoformat(), "deleted": deleted},
        )
    return deleted


def purge_snapshots(db: Session) -> int:
    """Delete snapshot images older than retention.snapshots_days (§3.12.4).

    Snapshot folders are named YYYYMMDD under data/snapshots. Returns the
    number of files removed.
    """
    days = get_int(db, "retention.snapshots_days")
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    if not SNAPSHOT_DIR.exists():
        return 0
    for subdir in sorted(SNAPSHOT_DIR.iterdir()):
        if not subdir.is_dir() or len(subdir.name) != 8 or not subdir.name.isdigit():
            continue
        try:
            subdir_date = datetime.strptime(subdir.name, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if subdir_date < cutoff:
            for f in subdir.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)
                    deleted += 1
            subdir.rmdir()
    if deleted:
        logger.info("purged %d snapshot files older than %s", deleted, cutoff.isoformat())
        write_system_log(
            db,
            event="retention.snapshots",
            message=f"Purged {deleted} snapshot files older than {days} days",
            context={"days": days, "cutoff": cutoff.isoformat(), "deleted": deleted},
        )
    return deleted


def purge_system_logs(db: Session) -> int:
    """Delete system log rows older than system.log_retention_days (§3.12.6).

    Returns the number of rows deleted.
    """
    days = get_int(db, "system.log_retention_days")
    if days <= 0:
        return 0
    # SQLite stores timezone-aware datetimes as naive UTC strings. Use a
    # naive UTC cutoff so the ORM evaluator can compare consistently.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    stmt = delete(SystemLog).where(SystemLog.created_at < cutoff)
    result = db.execute(stmt)
    db.commit()
    deleted = result.rowcount
    if deleted:
        logger.info("purged %d system logs older than %s", deleted, cutoff.isoformat())
        # Intentionally do NOT write a system log about deleting system logs —
        # that would create a new row immediately after the purge.
    return deleted


def _machine_info(db: Session) -> dict:
    return {
        "id": get_value(db, "device.machine_id"),
        "name": get_value(db, "device.location_name"),
        "timezone": get_value(db, "device.timezone"),
    }
