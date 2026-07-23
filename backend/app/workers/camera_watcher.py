"""Camera offline alert watcher (SRS §3.11.4).

The watcher is a tiny background thread that polls the recognition engine's
camera status every minute. If the camera stays offline for longer than the
configured `smtp.camera_offline_minutes`, it emits one email alert (and one
system log) until the camera comes back online.
"""
from __future__ import annotations

import logging
import threading
import time

from app.db import SessionLocal
from app.engine.service import service
from app.services.smtp import send_camera_offline_alert

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60


class CameraOfflineWatcher:
    """Singleton-ish watcher started/stopped by FastAPI lifespan."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._alerted = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._alerted = False
        self._thread = threading.Thread(target=self._run, name="camera-offline-watcher", daemon=True)
        self._thread.start()
        logger.info("camera offline watcher started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("camera offline watcher stopped")

    def _run(self) -> None:
        from app.core.shutdown import shutdown_event

        while not self._stop.is_set() and not shutdown_event.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("camera offline watcher tick failed")
            # Sleep in small chunks so shutdown is responsive.
            for _ in range(_POLL_INTERVAL_SECONDS):
                if self._stop.is_set() or shutdown_event.is_set():
                    break
                time.sleep(1)

    def _tick(self) -> None:
        from app.core.enums import CameraStatus
        from app.core.settings_store import get_int

        if service.camera_status is CameraStatus.ONLINE:
            if self._alerted:
                logger.info("camera back online; resetting offline alert latch")
                self._alerted = False
            return

        with SessionLocal() as db:
            threshold_min = max(1, get_int(db, "smtp.camera_offline_minutes"))

        # The frame_source already logs camera.offline when the transition
        # happens. We use the engine's last_frame_at as a proxy for how long
        # it has been offline. If the engine has never produced a frame, we
        # treat the offline duration as zero and do not alert.
        last_frame = service.stats.last_frame_at
        if last_frame == 0:
            return

        offline_seconds = time.time() - last_frame
        if offline_seconds < threshold_min * 60:
            return

        if self._alerted:
            return

        try:
            with SessionLocal() as db:
                if send_camera_offline_alert(db, threshold_min):
                    self._alerted = True
        except Exception:
            logger.exception("failed to send camera offline alert")


# Module-level singleton.
watcher = CameraOfflineWatcher()
