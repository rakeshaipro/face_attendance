"""Schemas for the device group (SRS §3.1, §3.11) and the health check
(§3.11.1).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import CameraStatus, ServiceState


class DeviceInfo(BaseModel):
    """GET /device response (§3.1.9). Camera URL is masked."""

    machine_id: str
    location_name: str
    software_version: str
    server_uptime_seconds: float
    timezone: str
    camera_url_masked: str
    service_state: ServiceState
    camera_status: CameraStatus


class CameraSettings(BaseModel):
    """GET /device/camera response (§3.1.3).

    The camera URL is returned unmasked (admin only). The password is
    never sent back; `password_set` indicates whether one is stored.
    """

    camera_url: str
    username: str
    password_set: bool


class CameraSettingsUpdate(BaseModel):
    """PUT /device/camera body. All fields optional; omitted fields are
    left unchanged. Send `password=""` to clear the stored password."""

    camera_url: str | None = None
    username: str | None = None
    password: str | None = None


class CameraTestRequest(BaseModel):
    """Optional override; if omitted, the configured URL is tested."""

    url: str | None = None
    timeout_ms: int = Field(default=5000, ge=500, le=30000)


class CameraTestResult(BaseModel):
    """POST /device/camera/test response (§3.1.4)."""

    reachable: bool
    latency_ms: int | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


class EngineStats(BaseModel):
    """GET /device/stats response (§3.4.14, §3.11.3)."""

    service_state: ServiceState
    camera_status: CameraStatus
    fps: float
    detections_last_hour: int
    detections_last_24h: int
    avg_confidence_24h: float | None
    last_frame_at: datetime | None = None


class ServiceActionResponse(BaseModel):
    service_state: ServiceState


class HealthSummary(BaseModel):
    """GET /health response (§3.11.1) — unauthenticated."""

    recognition_service: ServiceState
    camera_status: CameraStatus
    disk_free_mb: int
    enrolled_employees: int
    total_log_records: int
    server_uptime_seconds: float
