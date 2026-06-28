"""Attendance write + snapshot logic (SRS §3.5).

`write_detection()` is the single write-event of the system (§3.5.1):
it persists the log row AND the snapshot BEFORE returning, so a later
webhook failure can never lose a record (§6.2.1).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SNAPSHOT_DIR
from app.core.enums import EVENT_EMPLOYEE_DETECTED, SyncStatus
from app.core.settings_store import get_value
from app.events import bus
from app.models import AttendanceLog, Employee

logger = logging.getLogger(__name__)


def _snapshot_dir_for(dt: datetime) -> Path:
    """Date-partitioned snapshot dir: data/snapshots/YYYYMMDD/."""
    return SNAPSHOT_DIR / dt.strftime("%Y%m%d")


def _save_snapshot(frame: np.ndarray, log_id: str, dt: datetime) -> str:
    """Save a JPEG snapshot, return the relative path (§3.5.3)."""
    d = _snapshot_dir_for(dt)
    d.mkdir(parents=True, exist_ok=True)
    rel = f"{dt.strftime('%Y%m%d')}/{log_id}.jpg"
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        logger.warning("snapshot encode failed for log %s", log_id)
        return rel
    (SNAPSHOT_DIR / rel).write_bytes(buf.tobytes())
    return rel


def write_detection(
    db: Session,
    employee: Employee,
    frame: np.ndarray,
    confidence: float,
    *,
    machine_id: str | None = None,
    location_name: str | None = None,
    timezone_name: str | None = None,
    publish: bool = True,
) -> AttendanceLog:
    """Persist one detection (§3.5.1, §6.2.1).

    Reads machine identity from the settings store unless overridden
    (useful for tests). Commits before returning.
    """
    now = datetime.now(timezone.utc)
    mid = machine_id or get_value(db, "device.machine_id")
    loc = location_name or get_value(db, "device.location_name")
    log_id = uuid.uuid4().hex

    snapshot_rel = _save_snapshot(frame, log_id, now)
    row = AttendanceLog(
        id=log_id,
        machine_id=mid,
        location_name=loc,
        employee_id=employee.id,
        employee_name=employee.name,  # stored now, not looked up later (§3.5.2)
        timestamp=now,
        confidence=round(float(confidence), 4),
        snapshot_path=snapshot_rel,
        snapshot_available=True,
        is_manual=False,
        sync_status=SyncStatus.PENDING.value,  # §3.7.1
    )
    db.add(row)
    db.commit()  # §6.2.1 — durable before any side effect
    db.refresh(row)

    if publish:
        # Phase 4's webhook dispatcher subscribes to this. Fire-and-forget
        # for real-time streams (§3.8.6).
        bus.publish(
            EVENT_EMPLOYEE_DETECTED,
            {
                "log_id": row.id,
                "employee_id": employee.employee_id,
                "name": employee.name,
                "confidence": row.confidence,
                "machine": {"id": mid, "name": loc, "timezone": timezone_name or "UTC"},
                "timestamp": row.timestamp.isoformat(),
                "snapshot_url": f"/api/v1/attendance/{row.id}/snapshot",
            },
        )
    return row


def resolve_employee(db: Session, employee_id: str) -> Employee:
    """Look up by internal id OR organisation employee_id (§3.2.1)."""
    from sqlalchemy import or_

    emp = db.execute(
        select(Employee).where(or_(Employee.id == employee_id, Employee.employee_id == employee_id))
    ).scalar_one_or_none()
    if emp is None:
        raise ValueError("Employee not found.")
    return emp
