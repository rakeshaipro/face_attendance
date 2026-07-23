"""APscheduler wiring (SRS §3.7.10, §3.10.8, §3.11.2, §3.12.3).

In this phase the scheduler is started but no jobs are registered —
that arrives with the sync/backup/retention/monitoring slices. Keeping
the singleton here so lifespan can start/stop it cleanly.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)
    return _scheduler


def start() -> None:
    sch = get_scheduler()
    if not sch.running:
        sch.start()
        logger.info("scheduler started")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")
