"""Monitoring + retention API + scheduler registration (SRS §3.11, §3.12).

Exposes a small read-only status endpoint and registers the scheduled
jobs on startup. Retention/monitoring settings are part of the bulk
/api/v1/settings endpoint, so no dedicated write endpoint is needed here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_readonly
from app.db import get_db
from app.models import ApiKey
from app.schemas.common import Envelope
from app.schemas.monitoring import MonitoringStatus
from app.services import monitoring as monitoring_svc
from app.workers import scheduler as scheduler_worker

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

logger = logging.getLogger(__name__)

DISK_JOB_ID = "monitor-disk"
RETENTION_JOB_ID = "retention-daily"


@router.get("/status", response_model=Envelope[MonitoringStatus])
def monitoring_status(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[MonitoringStatus]:
    """Return the next scheduled run times for monitoring/retention jobs."""
    sch = scheduler_worker.get_scheduler()
    disk_job = sch.get_job(DISK_JOB_ID)
    retention_job = sch.get_job(RETENTION_JOB_ID)
    return Envelope(
        data=MonitoringStatus(
            disk_job_next=disk_job.next_run_time.isoformat() if disk_job and disk_job.next_run_time else None,
            retention_job_next=retention_job.next_run_time.isoformat() if retention_job and retention_job.next_run_time else None,
        )
    )


def register_monitoring_jobs() -> None:
    """Register disk-space and retention jobs with APScheduler.

    Called once from FastAPI lifespan after the scheduler has started.
    """
    from apscheduler.triggers.interval import IntervalTrigger

    sch = scheduler_worker.get_scheduler()
    for jid in (DISK_JOB_ID, RETENTION_JOB_ID):
        existing = sch.get_job(jid)
        if existing is not None:
            sch.remove_job(jid)

    # Disk check every 5 minutes (§3.11.2).
    sch.add_job(
        _disk_check_job,
        trigger=IntervalTrigger(minutes=5),
        id=DISK_JOB_ID,
        replace_existing=True,
    )
    # Retention purge once daily at 04:00 (§3.12.3–3.12.6).
    from apscheduler.triggers.cron import CronTrigger

    sch.add_job(
        _retention_job,
        trigger=CronTrigger(hour=4, minute=0),
        id=RETENTION_JOB_ID,
        replace_existing=True,
    )


def _disk_check_job() -> None:
    """Scheduled job: check free disk space and fire storage_low."""
    from app.db import SessionLocal
    from app.services.smtp import send_storage_low_alert

    try:
        with SessionLocal() as db:
            fired = monitoring_svc.check_disk_space(db)
            if fired:
                # Also try SMTP alert if configured.
                free_mb = monitoring_svc._free_mb(monitoring_svc.DATA_DIR)
                threshold_mb = max(monitoring_svc._MIN_SANE_FREE_MB, monitoring_svc.get_int(db, "monitor.disk_threshold_mb"))
                send_storage_low_alert(db, free_mb, threshold_mb)
    except Exception:
        logger.exception("disk check job failed")


def _retention_job() -> None:
    """Scheduled job: purge old attendance logs, snapshots, and system logs."""
    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            monitoring_svc.purge_attendance_logs(db)
            monitoring_svc.purge_snapshots(db)
            monitoring_svc.purge_system_logs(db)
    except Exception:
        logger.exception("retention job failed")
