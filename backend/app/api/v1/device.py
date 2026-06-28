"""Device group — the full vertical slice (SRS §3.1, §3.4.14, §3.11.3).

Endpoints:
  GET    /device                       device info                §3.1.9
  GET    /device/camera                camera URL + credentials   §3.1.3
  PUT    /device/camera                update camera URL/creds    §3.1.3
  POST   /device/camera/test           camera reachability test   §3.1.4
  GET    /device/stream                MJPEG proxy                §3.1.5
  GET    /device/frame                 single-frame JPEG capture  §3.1.8
  POST   /device/service/restart       restart engine             §3.1.6
  POST   /device/service/pause         pause engine               §3.1.7
  POST   /device/service/resume        resume engine              §3.1.7
  GET    /device/stats                 engine operational stats   §3.4.14, §3.11.3
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import cv2
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import require_admin, require_readonly
from app.config import settings
from app.core.settings_store import get_camera_auth_url, get_int, get_masked, get_value, set_value
from app.db import get_db
from app.engine.frame_source import open_capture
from app.engine.service import service
from app.models import ApiKey
from app.schemas.common import Envelope
from app.schemas.device import (
    CameraSettings,
    CameraSettingsUpdate,
    CameraTestRequest,
    CameraTestResult,
    DeviceInfo,
    EngineStats,
    ServiceActionResponse,
)

router = APIRouter(prefix="/device", tags=["device"])

_START_TIME = time.monotonic()


def _uptime() -> float:
    return round(time.monotonic() - _START_TIME, 2)


# --- §3.1.9 device info --------------------------------------------------
@router.get("", response_model=Envelope[DeviceInfo])
def device_info(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[DeviceInfo]:
    info = DeviceInfo(
        machine_id=get_value(db, "device.machine_id"),
        location_name=get_value(db, "device.location_name"),
        software_version=__version__,
        server_uptime_seconds=_uptime(),
        timezone=get_value(db, "device.timezone"),
        camera_url_masked=get_masked(db, "device.camera_url"),
        service_state=service.state,
        camera_status=service.camera_status,
    )
    return Envelope(data=info)


# --- §3.1.4 camera test --------------------------------------------------
@router.post("/camera/test", response_model=Envelope[CameraTestResult])
def camera_test(
    body: CameraTestRequest | None = None,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[CameraTestResult]:
    url = (body.url if body and body.url else get_camera_auth_url(db))
    timeout_ms = body.timeout_ms if body else 5000
    started = time.monotonic()
    cap = open_capture(url)
    try:
        # cv2 has no per-call timeout; we rely on a best-effort isOpened()+read().
        reachable = cap.isOpened()
        if not reachable:
            return Envelope(
                data=CameraTestResult(
                    reachable=False, latency_ms=int((time.monotonic() - started) * 1000),
                    error="Could not open stream.",
                )
            )
        ok, frame = cap.read()
        latency_ms = int((time.monotonic() - started) * 1000)
        h, w = (frame.shape[:2] if ok and frame is not None else (None, None))
        return Envelope(
            data=CameraTestResult(
                reachable=ok,
                latency_ms=latency_ms,
                width=w,
                height=h,
                error=None if ok else "Stream opened but no frame returned.",
            )
        )
    finally:
        cap.release()
    # timeout_ms is advisory here; cv2 does not expose a hard socket timeout.


# --- §3.1.3 camera settings ---------------------------------------------
@router.get("/camera", response_model=Envelope[CameraSettings])
def camera_settings_get(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[CameraSettings]:
    """Return the camera URL + username and whether a password is set.

    The password itself is never returned (§3.13.9).
    """
    return Envelope(
        data=CameraSettings(
            camera_url=get_value(db, "device.camera_url"),
            username=get_value(db, "device.camera_username"),
            password_set=bool(get_value(db, "device.camera_password")),
        )
    )


@router.put("/camera", response_model=Envelope[CameraSettings])
def camera_settings_put(
    body: CameraSettingsUpdate,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> Envelope[CameraSettings]:
    """Update the camera URL and/or credentials.

    Only fields present in the body are changed. A blank `password`
    clears any stored password. The composed (with-credentials) URL is
    hot-swapped into the running engine, so changes take effect without
    a restart (§3.1.3, §3.4.12).
    """
    if body.camera_url is not None:
        set_value(db, "device.camera_url", body.camera_url)
    if body.username is not None:
        set_value(db, "device.camera_username", body.username)
    if body.password is not None:
        set_value(db, "device.camera_password", body.password)
    # Hot-swap the live source so the new credentials are picked up.
    service.set_camera_url(get_camera_auth_url(db))
    return Envelope(
        data=CameraSettings(
            camera_url=get_value(db, "device.camera_url"),
            username=get_value(db, "device.camera_username"),
            password_set=bool(get_value(db, "device.camera_password")),
        )
    )


# --- §3.1.5 MJPEG proxy --------------------------------------------------
def _mjpeg_generator(url: str):
    """Stream frames as multipart/x-mixed-replace, reconnecting on loss.

    Uses the FFMPEG backend + 1-frame buffer (see open_capture) so RTSP
    feeds are handled the same way as the recognition engine.
    """
    from app.core.shutdown import shutdown_event

    cap = open_capture(url)
    try:
        while not shutdown_event.is_set():
            if not cap.isOpened():
                # Drop the old handle and reopen; cv2 doesn't always recover.
                cap.release()
                if shutdown_event.wait(1.0):
                    break
                cap = open_capture(url)
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                if shutdown_event.wait(1.0):
                    break
                cap = open_capture(url)
                continue
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
    finally:
        cap.release()


@router.get("/stream")
def stream(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    """Proxy the camera's MJPEG stream so the dashboard doesn't need
    direct camera access (§3.1.5)."""
    url = get_camera_auth_url(db)
    return StreamingResponse(
        _mjpeg_generator(url),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# --- §3.1.8 single-frame capture ----------------------------------------
@router.get("/frame", response_class=Response)
def frame(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    """Return a single JPEG frame from the camera (§3.1.8)."""
    url = get_camera_auth_url(db)
    cap = open_capture(url)
    try:
        ok, mat = cap.read()
    finally:
        cap.release()
    if not ok or mat is None:
        raise HTTPException(status_code=502, detail="Camera frame unavailable.")
    ok, buf = cv2.imencode(".jpg", mat)
    return Response(content=buf.tobytes(), media_type="image/jpeg")


# --- §3.1.6 / §3.1.7 service control ------------------------------------
@router.post("/service/restart", response_model=Envelope[ServiceActionResponse])
def service_restart(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> Envelope[ServiceActionResponse]:
    service.restart()
    return Envelope(data=ServiceActionResponse(service_state=service.state))


@router.post("/service/pause", response_model=Envelope[ServiceActionResponse])
def service_pause(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> Envelope[ServiceActionResponse]:
    service.pause()
    return Envelope(data=ServiceActionResponse(service_state=service.state))


@router.post("/service/resume", response_model=Envelope[ServiceActionResponse])
def service_resume(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> Envelope[ServiceActionResponse]:
    service.resume()
    return Envelope(data=ServiceActionResponse(service_state=service.state))


# --- §3.4.14 / §3.11.3 stats --------------------------------------------
@router.get("/stats", response_model=Envelope[EngineStats])
def stats(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[EngineStats]:
    s = service.stats
    last_frame_dt = datetime.fromtimestamp(s.last_frame_at, tz=timezone.utc) if s.last_frame_at else None
    cutoff_1h = datetime.now(timezone.utc) - timedelta(hours=1)
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    detections_1h = sum(1 for t in s.detection_times if t >= cutoff_1h) if s.detection_times else 0
    detections_24h = sum(1 for t in s.detection_times if t >= cutoff_24h) if s.detection_times else 0
    avg_conf = (
        float(sum(s.confidences_24h) / len(s.confidences_24h))
        if s.confidences_24h
        else None
    )
    return Envelope(
        data=EngineStats(
            service_state=service.state,
            camera_status=service.camera_status,
            fps=s.fps,
            detections_last_hour=detections_1h,
            detections_last_24h=detections_24h,
            avg_confidence_24h=avg_conf,
            last_frame_at=last_frame_dt,
        )
    )
