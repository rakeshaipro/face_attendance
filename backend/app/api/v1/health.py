"""GET /health — unauthenticated health summary (SRS §3.11.1).

Intentionally requires no API key so external monitors (Uptime Robot,
Zabbix, Nagios) can poll it.
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.db import get_db
from app.engine.service import service
from app.models import AttendanceLog, Employee
from app.schemas.common import Envelope
from app.schemas.device import HealthSummary

router = APIRouter(tags=["health"])

_START_TIME = time.monotonic()


@router.get("/health", response_model=Envelope[HealthSummary])
def health(db: Session = Depends(get_db)) -> Envelope[HealthSummary]:
    disk = shutil.disk_usage(DATA_DIR)
    enrolled = db.execute(
        select(func.count(Employee.id)).where(Employee.is_enrolled.is_(True))
    ).scalar_one()
    total_logs = db.execute(select(func.count(AttendanceLog.id))).scalar_one()
    summary = HealthSummary(
        recognition_service=service.state,
        camera_status=service.camera_status,
        disk_free_mb=int(disk.free / (1024 * 1024)),
        enrolled_employees=int(enrolled),
        total_log_records=int(total_logs),
        server_uptime_seconds=round(time.monotonic() - _START_TIME, 2),
    )
    return Envelope(data=summary)
