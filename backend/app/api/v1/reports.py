"""Reports group (SRS §3.9) — read-only.

Reporting is limited to querying and exporting raw log data (§3.9.1);
no computed fields (hours, late/early, IN/OUT) — those are the HRMS's job.

Endpoints
  GET /reports/logs            query logs (filters + pagination)   §3.9.2
  GET /reports/logs/daily      single-day view                     §3.9.3
  GET /reports/logs/export     CSV or XLSX export                  §3.9.4
  GET /reports/audit           audit log query                     §3.9.5
  GET /reports/audit/export    audit CSV
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_readonly
from app.db import get_db
from app.models import ApiKey, AttendanceLog, AuditLog
from app.schemas.common import Envelope, PaginatedData
from app.schemas.report import AuditLogOut, ReportLogRow

router = APIRouter(prefix="/reports", tags=["reports"])

LOG_EXPORT_COLUMNS = [
    "log_id", "machine_id", "location_name", "employee_id", "employee_name",
    "timestamp", "confidence", "is_manual", "manual_reason",
    "sync_status", "snapshot_available", "created_at",
]

AUDIT_EXPORT_COLUMNS = [
    "id", "action", "affected_id", "source", "actor",
    "old_value", "new_value", "note", "created_at",
]


def _apply_log_filters(stmt, employee_id: str | None, date_from, date_to):
    if employee_id:
        stmt = stmt.where(
            or_(AttendanceLog.employee_id == employee_id, AttendanceLog.employee_name == employee_id)
        )
    if date_from:
        stmt = stmt.where(AttendanceLog.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceLog.timestamp <= date_to)
    return stmt


# --- §3.9.2 query logs --------------------------------------------------
@router.get("/logs", response_model=Envelope[PaginatedData[ReportLogRow]])
def query_logs(
    employee_id: str | None = None,
    date: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PaginatedData[ReportLogRow]]:
    if date and not (date_from or date_to):
        d = datetime.fromisoformat(date).date()
        date_from = datetime.combine(d, time.min, tzinfo=timezone.utc)
        date_to = datetime.combine(d, time.max, tzinfo=timezone.utc)

    stmt = _apply_log_filters(select(AttendanceLog), employee_id, date_from, date_to)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(AttendanceLog.timestamp.desc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[ReportLogRow](
            items=[ReportLogRow.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


# --- §3.9.3 daily view --------------------------------------------------
@router.get("/logs/daily", response_model=Envelope[PaginatedData[ReportLogRow]])
def daily_view(
    date: str | None = None,
    employee_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    target = datetime.fromisoformat(date).date() if date else datetime.now(timezone.utc).date()
    start = datetime.combine(target, time.min, tzinfo=timezone.utc)
    end = datetime.combine(target, time.max, tzinfo=timezone.utc)
    stmt = _apply_log_filters(select(AttendanceLog), employee_id, start, end)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(AttendanceLog.timestamp.asc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[ReportLogRow](
            items=[ReportLogRow.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


# --- §3.9.4 export ------------------------------------------------------
def _log_row_to_tuple(r: AttendanceLog) -> tuple:
    return (
        r.id, r.machine_id, r.location_name, r.employee_id, r.employee_name,
        r.timestamp.isoformat(), r.confidence, int(r.is_manual), r.manual_reason or "",
        r.sync_status, int(r.snapshot_available), r.created_at.isoformat(),
    )


@router.get("/logs/export")
def export_logs(
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    employee_id: str | None = None,
    date: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    if date and not (date_from or date_to):
        d = datetime.fromisoformat(date).date()
        date_from = datetime.combine(d, time.min, tzinfo=timezone.utc)
        date_to = datetime.combine(d, time.max, tzinfo=timezone.utc)

    stmt = _apply_log_filters(select(AttendanceLog), employee_id, date_from, date_to)
    rows = db.execute(stmt.order_by(AttendanceLog.timestamp.asc())).scalars().all()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d")

    if format == "xlsx":
        return _logs_xlsx_response(rows, filename=f"attendance_logs_{suffix}.xlsx")
    return _logs_csv_response(rows, filename=f"attendance_logs_{suffix}.csv")


def _logs_csv_response(rows, *, filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(LOG_EXPORT_COLUMNS)
    for r in rows:
        w.writerow(_log_row_to_tuple(r))
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _logs_xlsx_response(rows, *, filename: str) -> StreamingResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance Logs"
    ws.append(LOG_EXPORT_COLUMNS)
    for r in rows:
        ws.append(list(_log_row_to_tuple(r)))
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- §3.9.5 audit log ---------------------------------------------------
def _apply_audit_filters(stmt, action, source, actor, affected_id, date_from, date_to):
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if source:
        stmt = stmt.where(AuditLog.source == source)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if affected_id:
        stmt = stmt.where(AuditLog.affected_id == affected_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    return stmt


@router.get("/audit", response_model=Envelope[PaginatedData[AuditLogOut]])
def query_audit(
    action: str | None = None,
    source: str | None = None,
    actor: str | None = None,
    affected_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PaginatedData[AuditLogOut]]:
    stmt = _apply_audit_filters(select(AuditLog), action, source, actor, affected_id, date_from, date_to)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[AuditLogOut](
            items=[AuditLogOut.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


@router.get("/audit/export")
def export_audit(
    action: str | None = None,
    source: str | None = None,
    actor: str | None = None,
    affected_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> StreamingResponse:
    stmt = _apply_audit_filters(select(AuditLog), action, source, actor, affected_id, date_from, date_to)
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc())).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(AUDIT_EXPORT_COLUMNS)
    for r in rows:
        w.writerow([
            r.id, r.action, r.affected_id or "", r.source, r.actor or "",
            r.old_value or "", r.new_value or "", r.note or "", r.created_at.isoformat(),
        ])
    buf.seek(0)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_log_{suffix}.csv"'},
    )
