"""Attendance group (SRS §3.5).

Endpoints
  GET    /attendance                query logs (filters + pagination)  §3.5.4
  GET    /attendance/today          today's detections                 §3.5.5
  POST   /attendance/manual         manually create a record           §3.5.6
  PUT    /attendance/{id}           edit timestamp/notes               §3.5.7
  DELETE /attendance/{id}           delete (admin, requires reason)    §3.5.8
  GET    /attendance/{id}/snapshot  download JPEG snapshot             §3.5.9
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readonly, require_readwrite
from app.config import SNAPSHOT_DIR
from app.core.enums import SyncStatus
from app.core.settings_store import get_value
from app.db import get_db
from app.models import ApiKey, AttendanceLog, Employee
from app.schemas.attendance import (
    AttendanceLogOut,
    DeleteResult,
    EditLogBody,
    ManualEntryBody,
)
from app.schemas.common import Envelope, PaginatedData
from app.services.attendance import resolve_employee
from app.services.audit import write_audit

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _get_log_or_404(db: Session, log_id: str) -> AttendanceLog:
    row = db.execute(select(AttendanceLog).where(AttendanceLog.id == log_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Attendance log not found.")
    return row


def _apply_filters(stmt, employee_id: str | None, date_from, date_to):
    if employee_id:
        stmt = stmt.where(
            or_(AttendanceLog.employee_id == employee_id, AttendanceLog.employee_name == employee_id)
        )
    if date_from:
        stmt = stmt.where(AttendanceLog.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceLog.timestamp <= date_to)
    return stmt


# --- §3.5.4 query --------------------------------------------------------
@router.get("", response_model=Envelope[PaginatedData[AttendanceLogOut]])
def list_logs(
    employee_id: str | None = None,
    date: str | None = None,           # YYYY-MM-DD single-day filter
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PaginatedData[AttendanceLogOut]]:
    # Single-day convenience filter (§3.9.2/§3.9.3 style).
    if date and not (date_from or date_to):
        d = datetime.fromisoformat(date).date()
        date_from = datetime.combine(d, time.min, tzinfo=timezone.utc)
        date_to = datetime.combine(d, time.max, tzinfo=timezone.utc)

    from sqlalchemy import func

    stmt = select(AttendanceLog)
    stmt = _apply_filters(stmt, employee_id, date_from, date_to)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(AttendanceLog.timestamp.desc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[AttendanceLogOut](
            items=[AttendanceLogOut.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


# --- §3.5.5 today --------------------------------------------------------
@router.get("/today", response_model=Envelope[PaginatedData[AttendanceLogOut]])
def today_logs(
    employee_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)
    stmt = _apply_filters(select(AttendanceLog), employee_id, start, end)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(AttendanceLog.timestamp.asc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[AttendanceLogOut](
            items=[AttendanceLogOut.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


# --- §3.5.6 manual entry -------------------------------------------------
@router.post("/manual", response_model=Envelope[AttendanceLogOut], status_code=status.HTTP_201_CREATED)
def manual_entry(
    body: ManualEntryBody,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[AttendanceLogOut]:
    try:
        emp = resolve_employee(db, body.employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    mid = get_value(db, "device.machine_id")
    loc = get_value(db, "device.location_name")
    row = AttendanceLog(
        id=uuid.uuid4().hex,
        machine_id=mid,
        location_name=loc,
        employee_id=emp.id,
        employee_name=emp.name,
        timestamp=body.timestamp,
        confidence=0.0,
        snapshot_path=None,
        snapshot_available=False,
        is_manual=True,
        manual_reason=body.reason,
        sync_status=SyncStatus.MANUAL.value,  # §3.7.1 — not sent via webhook
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # Manual records do NOT fire employee.detected (§3.5.6).
    write_audit(
        db, action="attendance.manual", affected_id=row.id, source="api",
        actor=api_key.label, new_value={"employee_id": emp.employee_id, "reason": body.reason, "note": body.note},
        commit=True,
    )
    return Envelope(data=AttendanceLogOut.model_validate(row))


# --- §3.5.7 edit ---------------------------------------------------------
@router.put("/{log_id}", response_model=Envelope[AttendanceLogOut])
def edit_log(
    log_id: str,
    body: EditLogBody,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[AttendanceLogOut]:
    row = _get_log_or_404(db, log_id)
    old = {"timestamp": row.timestamp.isoformat()}
    if body.timestamp is not None:
        row.timestamp = body.timestamp
    if body.note is not None:
        # Append to manual_reason if present, else store as audit note only.
        row.manual_reason = body.note
    db.commit()
    db.refresh(row)
    write_audit(
        db, action="attendance.edit", affected_id=row.id, source="api",
        actor=api_key.label, old_value=old, new_value={"timestamp": row.timestamp.isoformat(), "note": body.note},
        commit=True,
    )
    return Envelope(data=AttendanceLogOut.model_validate(row))


# --- §3.5.8 delete (admin) ----------------------------------------------
@router.delete("/{log_id}", response_model=Envelope[DeleteResult])
def delete_log(
    log_id: str,
    reason: str = Query(..., description="Mandatory reason (audit)."),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[DeleteResult]:
    row = _get_log_or_404(db, log_id)
    snapshot = {"id": row.id, "employee_id": row.employee_id, "timestamp": row.timestamp.isoformat()}
    # Best-effort snapshot file removal.
    if row.snapshot_path:
        (SNAPSHOT_DIR / row.snapshot_path).unlink(missing_ok=True)
    db.delete(row)
    write_audit(
        db, action="attendance.delete", affected_id=row.id, source="api",
        actor=api_key.label, old_value=snapshot, note=reason, commit=True,
    )
    return Envelope(data=DeleteResult(deleted=log_id))


# --- §3.5.9 snapshot download -------------------------------------------
@router.get("/{log_id}/snapshot")
def snapshot(
    log_id: str,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    row = _get_log_or_404(db, log_id)
    if not row.snapshot_available or not row.snapshot_path:
        raise HTTPException(status_code=404, detail="Snapshot not available (purged or manual record).")
    path = SNAPSHOT_DIR / row.snapshot_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Snapshot file missing.")
    return FileResponse(str(path), media_type="image/jpeg", filename=f"{log_id}.jpg")
