"""Domain enums shared across the API, engine, and models."""
from __future__ import annotations

from enum import Enum


class Scope(str, Enum):
    """API key scopes (SRS §3.13.4). Ordered so a higher rank includes
    every lower rank's permissions."""

    READONLY = "readonly"
    READWRITE = "readwrite"
    ADMIN = "admin"


class ServiceState(str, Enum):
    """Recognition service lifecycle states."""

    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class SyncStatus(str, Enum):
    """Sync status of an attendance log record (SRS §3.7.1)."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    MANUAL = "manual"


class LogSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# Webhook event types (SRS §3.6.3 / §3.8.4)
EVENT_EMPLOYEE_DETECTED = "employee.detected"
EVENT_CAMERA_OFFLINE = "device.camera_offline"
EVENT_CAMERA_ONLINE = "device.camera_online"
EVENT_STORAGE_LOW = "device.storage_low"

ALL_EVENTS: tuple[str, ...] = (
    EVENT_EMPLOYEE_DETECTED,
    EVENT_CAMERA_OFFLINE,
    EVENT_CAMERA_ONLINE,
    EVENT_STORAGE_LOW,
)
