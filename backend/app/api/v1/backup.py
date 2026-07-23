"""Backup group (SRS §3.10).

Endpoints
  POST   /backup                manual backup (full or database)     §3.10.1/3.10.2
  GET    /backup                backup history                        §3.10.4
  GET    /backup/{id}           download a backup ZIP                 §3.10.5
  DELETE /backup/{id}           delete a backup                       §3.10.6
  POST   /backup/restore        upload + restore (confirm required)   §3.10.7
  GET    /backup/schedule       schedule config                       §3.10.8/3.10.9
  PUT    /backup/schedule       update schedule + re-register job
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readonly
from app.config import BACKUP_DIR
from app.db import SessionLocal, get_db
from app.models import ApiKey
from app.schemas.backup import (
    BackupCreate,
    BackupOut,
    BackupScheduleConfig,
    RestoreBody,
    RestoreResult,
)
from app.schemas.common import Envelope
from app.services import backup as backup_svc
from app.services.audit import write_audit
from app.services.system_log import write_system_log
from app.workers import scheduler as scheduler_worker

router = APIRouter(prefix="/backup", tags=["backup"])

BACKUP_JOB_ID = "backup-scheduled"
PRUNE_JOB_ID = "backup-prune"


# --- §3.10.1 / §3.10.2 create ------------------------------------------
@router.post("", response_model=Envelope[BackupOut])
def create_backup(
    body: BackupCreate | None = None,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[BackupOut]:
    kind = body.kind if body else "database"
    row = backup_svc.create_backup(db, kind=kind, origin="manual")
    write_system_log(db, event="backup.create", message=f"Manual {kind} backup created: {row.filename}")
    write_audit(db, action="backup.create", source="api", actor=api_key.label,
                new_value={"kind": kind, "filename": row.filename}, commit=True)
    return Envelope(data=BackupOut.model_validate(row))


# --- §3.10.4 history ---------------------------------------------------
@router.get("", response_model=Envelope[list[BackupOut]])
def list_backups(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[list[BackupOut]]:
    rows = backup_svc.list_backups(db)
    return Envelope(data=[BackupOut.model_validate(r) for r in rows])


# --- §3.10.8 / §3.10.9 schedule (declared before {backup_id} routes) --
@router.get("/schedule", response_model=Envelope[BackupScheduleConfig])
def get_schedule(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[BackupScheduleConfig]:
    return Envelope(data=BackupScheduleConfig(**backup_svc.get_schedule_config(db)))


# --- §3.10.7 restore (declared before {backup_id} routes) -------------
@router.post("/restore", response_model=Envelope[RestoreResult])
async def restore_backup(
    confirm: bool = False,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[RestoreResult]:
    # Save the uploaded ZIP to a temp location, validate, then restore.
    tmp = BACKUP_DIR / ".restore_upload.zip"
    with open(tmp, "wb") as f:
        f.write(await file.read())
    try:
        ok, msg, kind = backup_svc.restore_backup(tmp, confirm=confirm)
    finally:
        tmp.unlink(missing_ok=True)

    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    # NB: do NOT reuse the request-scoped `db` here — restore_backup disposed
    # the engine, which invalidates this session's pooled connection. Open a
    # fresh session for the post-restore log writes (mirrors frame_source.py).
    actor = api_key.label if api_key else "api"
    with SessionLocal() as log_db:
        write_system_log(
            log_db,
            event="backup.restore",
            message=f"Restored {kind} backup: {msg}",
            context={"filename": file.filename, "kind": kind},
        )
        write_audit(
            log_db,
            action="backup.restore",
            source="api",
            actor=actor,
            new_value={"kind": kind, "filename": file.filename},
            commit=True,
        )
    return Envelope(data=RestoreResult(restored=True, kind=kind or "unknown", filename=file.filename))


# --- §3.10.5 download --------------------------------------------------
@router.get("/{backup_id}")
def download_backup(
    backup_id: str,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_admin),
):
    path = backup_svc.get_backup_path(db, backup_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Backup not found.")
    return FileResponse(str(path), media_type="application/zip", filename=path.name)


# --- §3.10.6 delete ----------------------------------------------------
@router.delete("/{backup_id}", response_model=Envelope[dict])
def delete_backup(
    backup_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[dict]:
    ok = backup_svc.delete_backup(db, backup_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Backup not found.")
    write_audit(db, action="backup.delete", source="api", actor=api_key.label,
                affected_id=backup_id, commit=True)
    return Envelope(data={"deleted": backup_id})


@router.put("/schedule", response_model=Envelope[BackupScheduleConfig])
def update_schedule(
    body: BackupScheduleConfig,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[BackupScheduleConfig]:
    config = backup_svc.update_schedule_config(db, body.model_dump())
    register_backup_jobs(db)
    write_audit(db, action="backup.schedule", source="api", actor=api_key.label,
                new_value=config, commit=True)
    return Envelope(data=BackupScheduleConfig(**config))


# --- APScheduler integration ------------------------------------------
def register_backup_jobs(db: Session) -> None:
    """Register (or remove) the scheduled-backup + prune jobs based on config."""
    sch = scheduler_worker.get_scheduler()
    for jid in (BACKUP_JOB_ID, PRUNE_JOB_ID):
        existing = sch.get_job(jid)
        if existing is not None:
            sch.remove_job(jid)

    config = backup_svc.get_schedule_config(db)
    if not config["enabled"]:
        return

    # Parse HH:MM into an interval trigger. We use an IntervalTrigger of
    # 24h (daily) or 168h (weekly) anchored to the configured time for
    # simplicity and robustness across DST.
    from apscheduler.triggers.cron import CronTrigger

    hh, mm = (config["time"].split(":") + ["0"])[:2]
    if config["frequency"] == "weekly":
        trigger = CronTrigger(day_of_week="mon", hour=int(hh), minute=int(mm))
    else:
        trigger = CronTrigger(hour=int(hh), minute=int(mm))

    sch.add_job(_scheduled_backup, trigger=trigger, id=BACKUP_JOB_ID, replace_existing=True)
    # Prune runs daily at 03:00 regardless.
    sch.add_job(_prune_job, trigger=CronTrigger(hour=3, minute=0), id=PRUNE_JOB_ID, replace_existing=True)


def _scheduled_backup() -> None:
    """Scheduled job: create a database-only backup (§3.10.8)."""
    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            row = backup_svc.create_backup(db, kind="database", origin="scheduled")
            write_system_log(db, event="backup.scheduled", message=f"Scheduled database backup created: {row.filename}")
            backup_svc.prune_scheduled(db)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("scheduled backup failed")


def _prune_job() -> None:
    """Scheduled job: enforce scheduled-backup retention (§3.10.9)."""
    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            n = backup_svc.prune_scheduled(db)
            if n:
                write_system_log(db, event="backup.prune", message=f"Pruned {n} old scheduled backups")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("backup prune failed")
