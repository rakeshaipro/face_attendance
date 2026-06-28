"""Schemas for the attendance group (SRS §3.5, §5.1)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttendanceLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    machine_id: str
    location_name: str
    employee_id: str
    employee_name: str
    timestamp: datetime
    confidence: float
    snapshot_path: str | None = None
    snapshot_available: bool
    is_manual: bool
    manual_reason: str | None = None
    sync_status: str
    created_at: datetime


class ManualEntryBody(BaseModel):
    """Body for POST /attendance/manual (§3.5.6)."""

    employee_id: str = Field(..., description="Internal or organisation employee ID.")
    timestamp: datetime
    reason: str = Field(..., min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class EditLogBody(BaseModel):
    """Body for PUT /attendance/{id} (§3.5.7). At least one field required."""

    timestamp: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class DeleteResult(BaseModel):
    deleted: str
