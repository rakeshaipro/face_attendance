"""Sync group (SRS §3.7).

Endpoints
  GET    /sync/status    sync-status counts          §3.7.8
  POST   /sync/batch     manual batch send           §3.7.3
  POST   /sync/resend    re-send sent by date range  §3.7.9
  GET    /sync/config    auto-sync config
  PUT    /sync/config    update auto-sync config     §3.7.10
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readonly, require_readwrite
from app.core.enums import SyncStatus
from app.core.settings_store import get_bool, get_int, get_value, set_value
from app.db import get_db
from app.models import ApiKey
from app.schemas.common import Envelope
from app.schemas.sync import BatchBody, BatchResult, SyncConfig, SyncCounts
from app.services.audit import write_audit
from app.services.sync import send_batch, status_counts
from app.workers import scheduler as scheduler_worker

router = APIRouter(prefix="/sync", tags=["sync"])

AUTOSYNC_JOB_ID = "sync-autosync"


def _counts(db: Session) -> SyncCounts:
    c = status_counts(db)
    return SyncCounts(**c)


# --- §3.7.8 status ------------------------------------------------------
@router.get("/status", response_model=Envelope[SyncCounts])
def get_status(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[SyncCounts]:
    return Envelope(data=_counts(db))


# --- §3.7.3 manual batch ----------------------------------------------
@router.post("/batch", response_model=Envelope[BatchResult])
async def manual_batch(
    body: BatchBody | None = None,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[BatchResult]:
    statuses = (body.only_status if body and body.only_status else None) or [
        SyncStatus.PENDING.value,
        SyncStatus.FAILED.value,
    ]
    date_from = datetime.fromisoformat(body.date_from) if body and body.date_from else None
    date_to = datetime.fromisoformat(body.date_to) if body and body.date_to else None
    result = await send_batch(db, statuses=statuses, date_from=date_from, date_to=date_to)
    write_audit(
        db, action="sync.batch", source="api", actor=api_key.label,
        new_value=result, commit=True,
    )
    return Envelope(data=BatchResult(**result))


# --- §3.7.9 resend already-sent ----------------------------------------
@router.post("/resend", response_model=Envelope[BatchResult])
async def resend(
    body: BatchBody | None = None,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[BatchResult]:
    statuses = (body.only_status if body and body.only_status else None) or [SyncStatus.SENT.value]
    date_from = datetime.fromisoformat(body.date_from) if body and body.date_from else None
    date_to = datetime.fromisoformat(body.date_to) if body and body.date_to else None
    result = await send_batch(db, statuses=statuses, date_from=date_from, date_to=date_to)
    write_audit(
        db, action="sync.resend", source="api", actor=api_key.label,
        new_value=result, commit=True,
    )
    return Envelope(data=BatchResult(**result))


# --- config (§3.7.10) --------------------------------------------------
@router.get("/config", response_model=Envelope[SyncConfig])
def get_config(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[SyncConfig]:
    return Envelope(
        data=SyncConfig(
            auto_enabled=get_bool(db, "sync.auto_enabled"),
            auto_interval_seconds=get_int(db, "sync.auto_interval_seconds"),
            batch_size=get_int(db, "sync.batch_size"),
            batch_url=get_value(db, "sync.batch_url"),
        )
    )


@router.put("/config", response_model=Envelope[SyncConfig])
def update_config(
    body: SyncConfig,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[SyncConfig]:
    set_value(db, "sync.auto_enabled", str(body.auto_enabled).lower())
    set_value(db, "sync.auto_interval_seconds", str(body.auto_interval_seconds))
    set_value(db, "sync.batch_size", str(body.batch_size))
    set_value(db, "sync.batch_url", body.batch_url)
    _reschedule_autosync(db)
    write_audit(
        db, action="sync.config", source="api", actor=api_key.label,
        new_value=body.model_dump(), commit=True,
    )
    return Envelope(
        data=SyncConfig(
            auto_enabled=body.auto_enabled,
            auto_interval_seconds=body.auto_interval_seconds,
            batch_size=body.batch_size,
            batch_url=body.batch_url,
        )
    )


# --- APScheduler integration ------------------------------------------
def register_autosync(db: Session) -> None:
    """Called from lifespan to register the auto-sync job if enabled."""
    _reschedule_autosync(db)


def _reschedule_autosync(db: Session) -> None:
    sch = scheduler_worker.get_scheduler()
    existing = sch.get_job(AUTOSYNC_JOB_ID)
    if existing is not None:
        sch.remove_job(AUTOSYNC_JOB_ID)

    if not get_bool(db, "sync.auto_enabled"):
        return

    interval = max(30, get_int(db, "sync.auto_interval_seconds"))

    def _run_auto_sync() -> None:  # pragma: no cover - exercised via integration
        import asyncio

        async def _go():
            with __import__("app.db", fromlist=["SessionLocal"]).SessionLocal() as session:
                await send_batch(
                    session,
                    statuses=[SyncStatus.PENDING.value, SyncStatus.FAILED.value],
                    date_from=None,
                    date_to=None,
                )

        try:
            asyncio.get_event_loop().create_task(_go())
        except RuntimeError:
            asyncio.run(_go())

    from apscheduler.triggers.interval import IntervalTrigger

    sch.add_job(
        _run_auto_sync,
        trigger=IntervalTrigger(seconds=interval),
        id=AUTOSYNC_JOB_ID,
        replace_existing=True,
    )
