"""Schemas for /api/v1/monitoring."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MonitoringStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disk_job_next: str | None = None
    retention_job_next: str | None = None
