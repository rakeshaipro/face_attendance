"""FastAPI application factory and lifespan.

On startup:
  - create tables if no migration has run (dev convenience; production
    uses `alembic upgrade head`)
  - seed system_settings defaults (§6.4.1)
  - capture the event loop for the event bus
  - start the recognition engine (unless FA_AUTOSTART_ENGINE=false)
  - start the APScheduler

On shutdown: stop engine + scheduler.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.router import api_router, root_router
from app.config import settings, ENROLLMENT_DIR
from app.core.response import fail
from app.core.settings_store import get_camera_auth_url, seed_defaults
from app.db import SessionLocal
from app.engine.service import service
from app.events import bus
from app.services.webhook_queue import dispatcher as webhook_dispatcher
from app.workers import scheduler as scheduler_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("face_attendance")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.shutdown import install_shutdown_handlers, set_shutdown
    install_shutdown_handlers()

    db = SessionLocal()
    try:
        seed_defaults(db)
        from app.services.system_log import write_system_log
        write_system_log(db, event="app.startup", message=f"Face Attendance backend {__version__} starting")
    finally:
        db.close()

    bus.set_loop(asyncio.get_running_loop())

    if settings.autostart_engine:
        db = SessionLocal()
        try:
            camera_url = get_camera_auth_url(db)
        finally:
            db.close()
        try:
            service.start(camera_url)
        except Exception:
            logger.exception("engine failed to start; continuing")

    scheduler_worker.start()

    # Webhook dispatcher (§3.6): subscribes to event bus, drains deliveries.
    webhook_dispatcher.start()

    # Auto-sync job (§3.7.10): periodic batch send when enabled.
    with SessionLocal() as db:
        from app.api.v1.sync import register_autosync
        register_autosync(db)

    # Scheduled backups (§3.10.8) + retention prune (§3.10.9).
    from app.api.v1.backup import register_backup_jobs
    with SessionLocal() as db:
        register_backup_jobs(db)

    # Phase 8: monitoring jobs (§3.11) + retention (§3.12.3–3.12.6).
    from app.api.v1.monitoring import register_monitoring_jobs
    register_monitoring_jobs()

    from app.workers.camera_watcher import watcher as camera_offline_watcher
    camera_offline_watcher.start()

    logger.info("Face Attendance backend %s started", __version__)
    try:
        yield
    finally:
        set_shutdown()
        with SessionLocal() as db:
            from app.services.system_log import write_system_log
            write_system_log(db, event="app.shutdown", message="Face Attendance backend stopping")
        await webhook_dispatcher.stop()
        camera_offline_watcher.stop()
        service.stop()
        scheduler_worker.shutdown()
        bus.set_loop(None)
        logger.info("Face Attendance backend stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Face Recognition Attendance System",
        version=__version__,
        description="Backend API for the IP-camera-based face attendance system.",
        lifespan=lifespan,
    )

    # CORS for the admin dashboard (Phase 9). Origins come from FA_CORS_ORIGINS.
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(root_router)
    app.include_router(api_router)

    app.mount("/media/enrollment", StaticFiles(directory=str(ENROLLMENT_DIR)), name="enrollment-media")

    @app.exception_handler(HTTPException)
    async def http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        # Normalise FastAPI's {"detail": ...} into the app's standard envelope
        # (SRS §4.3) so clients always read `error` from the response. Without
        # this, capture/pose-check failures (HTTPException(400, detail=...))
        # would return {"detail": "..."} and the real message would be lost.
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=fail(detail))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception")
        return JSONResponse(status_code=500, content=fail("Internal server error."))

    return app


app = create_app()
