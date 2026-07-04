"""Recognition service — a background daemon thread (SRS §3.4).

Runs the frame→detect→(match→log→webhook→stream) pipeline. In this slice
it performs frame reading + face detection (proving the InsightFace
provider path end-to-end with the real camera), exposes stats, and
fires camera online/offline events. The embedding→match→log→webhook→
WS/SSE portion is wired in a later slice.

The service is CPU/GPU-bound and runs entirely off the asyncio event
loop. Communication with async land happens through `events.bus`.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import CameraStatus, ServiceState
from app.core.settings_store import get_float, get_int
from app.db import SessionLocal
from app.engine.face_provider import FaceProvider, get_provider
from app.engine.frame_source import FrameSource
from app.engine.matcher import best_match
from app.models import Employee
from app.services.attendance import write_detection
from app.services.cooldown import CooldownTracker

logger = logging.getLogger(__name__)


@dataclass
class _Stats:
    """Rolling operational stats (§3.4.14, §3.11.3)."""

    fps: float = 0.0
    processed_frames: int = 0
    last_faces: int = 0
    # Confidence timestamps from successful detections (later slice).
    detection_times: deque = field(default_factory=lambda: deque(maxlen=2000))
    confidences_24h: deque = field(default_factory=lambda: deque(maxlen=2000))
    last_frame_at: float = 0.0


class RecognitionService:
    """Singleton-ish service driven by a background thread."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()  # set = paused
        self._restart_evt = threading.Event()
        self._state = ServiceState.STOPPED
        self._lock = threading.Lock()
        self._source: FrameSource | None = None
        self._provider: FaceProvider | None = None
        self._stats = _Stats()
        self._camera_url: str | None = None
        # Per-employee cooldown (§3.4.9).
        self._cooldown = CooldownTracker()
        # Hot-reloaded engine settings (§3.4.12) — refreshed on a TTL.
        self._settings_ts: float = 0.0
        self._threshold: float = 0.60
        self._cooldown_seconds: float = 60.0
        self._min_face_ratio: float = 0.10
        # Target frame timing, derived from engine.read_fps / detect_fps.
        self._target_read_dt: float = 1.0 / 10.0
        self._target_detect_dt: float = 1.0 / 5.0

    # --- public state -------------------------------------------------
    @property
    def state(self) -> ServiceState:
        return self._state

    @property
    def camera_status(self) -> CameraStatus:
        return self._source.status if self._source else CameraStatus.OFFLINE

    @property
    def stats(self) -> _Stats:
        return self._stats

    # --- lifecycle (§3.1.6, §3.1.7) ----------------------------------
    def start(self, camera_url: str, *, provider: FaceProvider | None = None) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._camera_url = camera_url
            self._provider = provider or get_provider()
            self._source = FrameSource(camera_url)
            self._stop_evt.clear()
            self._pause_evt.clear()
            self._restart_evt.clear()
            self._state = ServiceState.RUNNING
            self._thread = threading.Thread(
                target=self._run, name="recognition-engine", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._source is not None:
            self._source.release()
            self._source = None
        self._state = ServiceState.STOPPED

    def restart(self) -> None:
        """Restart the recognition loop without restarting the app (§3.1.6)."""
        if self._thread is None:
            return
        self._restart_evt.set()

    def pause(self) -> None:
        self._pause_evt.set()
        if self._state is ServiceState.RUNNING:
            self._state = ServiceState.PAUSED

    def resume(self) -> None:
        self._pause_evt.clear()
        if self._state is ServiceState.PAUSED:
            self._state = ServiceState.RUNNING

    def set_camera_url(self, url: str) -> None:
        """Hot-swap the camera URL (§3.1.3)."""
        self._camera_url = url
        if self._source is not None:
            self._source.set_url(url)

    def capture_frame(self, timeout_s: float = 2.0) -> "cv2.typing.MatLike | None":
        """Grab a single frame on demand (§3.1.8). Does not require the
        engine to be running."""
        if self._source is None and self._camera_url:
            self._source = FrameSource(self._camera_url)
        return self._source.read() if self._source else None

    def invalidate_gallery(self) -> None:
        """No-op retained for backward compatibility (enrollment service calls it)."""
        pass

    # --- main loop ----------------------------------------------------
    def _refresh_settings(self, db: Session) -> None:
        """Hot-reload configurable thresholds without a restart (§3.4.12)."""
        now = time.monotonic()
        if (now - self._settings_ts) < 5.0:
            return
        self._settings_ts = now
        self._threshold = get_float(db, "engine.similarity_threshold")
        self._cooldown_seconds = get_float(db, "engine.cooldown_seconds")
        self._min_face_ratio = get_float(db, "engine.min_face_ratio")
        # Read/detect cadence — guard against zero/invalid values to
        # avoid a division-by-zero busy loop.
        read_fps = max(1, get_int(db, "engine.read_fps"))
        detect_fps = max(1, get_int(db, "engine.detect_fps"))
        self._target_read_dt = 1.0 / float(read_fps)
        self._target_detect_dt = 1.0 / float(detect_fps)

    def invalidate_settings(self) -> None:
        """Force the next frame to re-read settings (used by the bulk
        settings API after a write)."""
        self._settings_ts = 0.0

    def _process_frame(self, frame: np.ndarray) -> int:
        """Run detection → match → filters → write for one frame.

        Returns the number of attendance logs written. Extracted from
        `_run` so it is unit-testable without a camera thread.

        Requires a provider set on the service. Uses its own short-lived
        DB session for any write (§6.2.1).
        """
        if self._provider is None:
            return 0

        db = SessionLocal()
        written = 0
        try:
            # Refresh configurable thresholds FIRST so this frame is filtered
            # against the latest values (§3.4.12) — including min_face_ratio,
            # which gates detection itself.
            self._refresh_settings(db)

            detections = self._provider.detect(
                frame, with_embeddings=True, min_size_ratio=self._min_face_ratio
            )
            self._stats.last_faces = len(detections)
            if not detections:
                return 0

            # Cache employee rows for this frame to avoid re-querying.
            seen: dict[str, Employee | None] = {}
            for det in detections:
                if det.embedding is None:
                    continue
                match = best_match(det.embedding, db)
                if match is None or match.score < self._threshold:
                    # Below threshold — silently discard (§3.4.6, §3.4.8).
                    continue
                emp = seen.get(match.employee_id)
                if emp is None:
                    emp = db.execute(
                        select(Employee).where(Employee.id == match.employee_id)
                    ).scalar_one_or_none()
                    seen[match.employee_id] = emp
                if emp is None or emp.is_blocked:
                    # Blocked employees are silently ignored (§3.2.7).
                    continue
                if self._cooldown.should_suppress(emp.id):
                    # Within cooldown window — suppress (§3.4.9).
                    continue

                write_detection(db, emp, frame, match.score)
                self._cooldown.mark(emp.id, self._cooldown_seconds)
                # Stats (§3.4.14, §3.11.3).
                self._stats.detection_times.append(datetime.now(timezone.utc))
                self._stats.confidences_24h.append(match.score)
                written += 1
        except Exception:
            db.rollback()
            logger.exception("frame processing failed")
        finally:
            db.close()
        return written

    def _run(self) -> None:
        logger.info("recognition engine started, camera=%s", self._camera_url)
        last_read = 0.0
        last_detect = 0.0
        fps_window: deque[float] = deque(maxlen=60)

        # Refresh settings once at startup so the initial FPS targets
        # reflect the stored values rather than the constructor defaults.
        try:
            with SessionLocal() as db:
                self._refresh_settings(db)
        except Exception:
            logger.exception("initial settings refresh failed; using defaults")

        while not self._stop_evt.is_set():
            # honour restart
            if self._restart_evt.is_set():
                self._restart_evt.clear()
                if self._source is not None:
                    self._source.release()
                self._source = FrameSource(self._camera_url) if self._camera_url else None
                logger.info("recognition engine restarted")

            # honour pause (§3.1.7): API/engine keep running, no detection
            if self._pause_evt.is_set():
                self._stop_evt.wait(0.2)
                continue

            now = time.monotonic()
            frame = self._source.read() if self._source else None
            if frame is None:
                continue

            # read-rate throttle
            if (now - last_read) >= self._target_read_dt:
                last_read = now

            # detection-rate throttle
            if (now - last_detect) >= self._target_detect_dt:
                last_detect = now
                self._process_frame(frame)
                self._stats.processed_frames += 1
                self._stats.last_frame_at = time.time()
                fps_window.append(now)
                if len(fps_window) >= 2:
                    dt = fps_window[-1] - fps_window[0]
                    self._stats.fps = round((len(fps_window) - 1) / dt, 2) if dt > 0 else 0.0

        logger.info("recognition engine stopped")


# Module-level singleton — started/stopped by FastAPI lifespan.
service = RecognitionService()
