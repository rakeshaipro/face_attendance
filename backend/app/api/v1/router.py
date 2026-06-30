"""Top-level v1 router. Mounts /health (unauthenticated, mounted at root)
and every /api/v1 group. The device, employees, enrollment, and
attendance groups are fully implemented; the others are stubs returning 501.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    attendance,
    backup,
    device,
    employees,
    enrollment,
    health,
    monitoring,
    reports,
    settings as settings_api,
    sync,
    system_logs,
    time,
    webhooks,
)
from app.config import settings

api_router = APIRouter(prefix=settings.api_prefix)

# Fully implemented in this phase.
api_router.include_router(device.router, tags=["device"])
api_router.include_router(employees.router, tags=["employees"])
api_router.include_router(enrollment.router, tags=["enrollment"])
api_router.include_router(attendance.router, tags=["attendance"])
api_router.include_router(webhooks.router, tags=["webhooks"])
api_router.include_router(sync.router, tags=["sync"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(settings_api.router, tags=["settings"])
api_router.include_router(backup.router, tags=["backup"])
api_router.include_router(system_logs.router, tags=["system_logs"])
api_router.include_router(time.router, tags=["time"])
api_router.include_router(monitoring.router, tags=["monitoring"])

# No remaining stubs — every /api/v1 group from §4.6 is implemented.

# /health is mounted at root (no /api/v1 prefix) and is unauthenticated.
root_router = APIRouter()
root_router.include_router(health.router)
