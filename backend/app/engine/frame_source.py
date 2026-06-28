"""Frame source with reconnect + exponential backoff (§3.4.13).

Supports both MJPEG (the original default) and RTSP (e.g. Dahua
`rtsp://user:pass@host:554/cam/realmonitor?...`). For RTSP we force:

  - TCP transport (vs UDP) via `OPENCV_FFMPEG_CAPTURE_OPTIONS`, which
    avoids the packet-loss artefacts typical of high-bitrate H.264
    mainstream feeds.
  - The FFMPEG backend (`cv2.CAP_FFMPEG`), required for RTSP and more
    robust than the default for MJPEG too.
  - A 1-frame capture buffer (`CAP_PROP_BUFFERSIZE=1`) so the engine
    processes the most recent frame instead of a stale buffered queue —
    critical for live attendance where latency matters.

The env var must be set before the first `cv2.VideoCapture` call, so it
is assigned at import time here.
"""
from __future__ import annotations

import logging
import os
import time

import cv2

from app.core.enums import CameraStatus
from app.events import bus

logger = logging.getLogger(__name__)

# Force TCP transport for RTSP (also harmless for MJPEG). Set once, before
# any VideoCapture is constructed anywhere in the process.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

# Backoff per §3.4.13: start 5s, cap 60s.
_INITIAL_BACKOFF = 5.0
_MAX_BACKOFF = 60.0

# Reconnect delay used by the dedicated capture thread when the stream drops.
_RECONNECT_DELAY = 2.0


def _is_rtsp(url: str) -> bool:
    return url.lower().startswith("rtsp://")


def open_capture(url: str) -> cv2.VideoCapture:
    """Open a VideoCapture configured for the URL's protocol.

    RTSP uses the FFMPEG backend explicitly with a 1-frame buffer; MJPEG
    keeps the default backend (FFMPEG also handles multipart/x-mixed-replace).
    """
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if _is_rtsp(url):
        # TCP transport for RTSP is already requested via the env var above;
        # nothing else cv2-specific to set, but keep this branch explicit
        # for future per-capture options.
        logger.info("opened RTSP capture (TCP, buffersize=1): %s", _mask(url))
    return cap


def _mask(url: str) -> str:
    """Hide credentials in a URL for logging."""
    if "://" in url and "@" in url:
        scheme, rest = url.split("://", 1)
        host = rest.split("@", 1)[1]
        return f"{scheme}://***@{host}"
    return url


class FrameSource:
    """Reads frames from an MJPEG or RTSP URL, reconnecting on loss."""

    def __init__(self, url: str, *, online_event: str = "device.camera_online",
                 offline_event: str = "device.camera_offline") -> None:
        self._url = url
        self._cap: cv2.VideoCapture | None = None
        self._status: CameraStatus = CameraStatus.OFFLINE
        self._online_event = online_event
        self._offline_event = offline_event
        self._backoff = _INITIAL_BACKOFF

    @property
    def status(self) -> CameraStatus:
        return self._status

    @property
    def url(self) -> str:
        return self._url

    def set_url(self, url: str) -> None:
        if url == self._url:
            return
        self._url = url
        self._close()

    def _open(self) -> bool:
        try:
            cap = open_capture(self._url)
        except Exception:
            logger.exception("VideoCapture open failed for %s", _mask(self._url))
            return False
        if not cap.isOpened():
            cap.release()
            return False
        self._cap = cap
        self._set_status(CameraStatus.ONLINE)
        self._backoff = _INITIAL_BACKOFF
        return True

    def _close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _set_status(self, status: CameraStatus) -> None:
        if status == self._status:
            return
        prev = self._status
        self._status = status
        masked = _mask(self._url)
        event = self._online_event if status is CameraStatus.ONLINE else self._offline_event
        bus.publish(event, {"url": masked, "status": status.value})
        # Record an operational system log (§3.12).
        try:
            from app.db import SessionLocal
            from app.services.system_log import write_system_log

            with SessionLocal() as db:
                sev = "info" if status is CameraStatus.ONLINE else "warning"
                write_system_log(
                    db,
                    severity=sev,
                    event=f"camera.{'online' if status is CameraStatus.ONLINE else 'offline'}",
                    message=f"Camera {status.value} (was {prev.value})",
                    context={"url": masked},
                    commit=True,
                )
        except Exception:
            logger.exception("failed to record camera-status system log")

    def read(self) -> "cv2.typing.MatLike | None":
        """Return a frame, or None if no frame is currently available.

        Reconnects automatically on failure. This call blocks up to
        `backoff` seconds during reconnection.
        """
        if self._cap is None and not self._open():
            # camera offline — sleep then retry on next read
            from app.core.shutdown import shutdown_event
            shutdown_event.wait(self._backoff)
            self._backoff = min(self._backoff * 2, _MAX_BACKOFF)
            return None
        ok, frame = self._cap.read()  # type: ignore[union-attr]
        if not ok or frame is None:
            self._close()
            self._set_status(CameraStatus.OFFLINE)
            return None
        return frame

    def release(self) -> None:
        self._close()
        self._status = CameraStatus.OFFLINE
