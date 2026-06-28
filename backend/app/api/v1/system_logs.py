"""System logs group (SRS §3.12).

Endpoint
  GET /system/logs   query operational logs (severity, event, date range)  §3.12.2
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_readonly
from app.db import get_db
from app.models import ApiKey, SystemLog
from app.schemas.common import Envelope, PaginatedData
from app.schemas.system_log import SystemLogOut

router = APIRouter(prefix="/system/logs", tags=["system_logs"])


@router.get("", response_model=Envelope[PaginatedData[SystemLogOut]])
def query_system_logs(
    severity: str | None = None,
    event: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PaginatedData[SystemLogOut]]:
    stmt = select(SystemLog)
    if severity:
        stmt = stmt.where(SystemLog.severity == severity)
    if event:
        stmt = stmt.where(SystemLog.event == event)
    if date_from:
        stmt = stmt.where(SystemLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(SystemLog.created_at <= date_to)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(SystemLog.created_at.desc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[SystemLogOut](
            items=[SystemLogOut.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )
