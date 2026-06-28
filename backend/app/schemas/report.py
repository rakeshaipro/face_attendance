"""Schemas for the reports group (SRS §3.9)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReportLogRow(BaseModel):
    """One attendance-log row in a report (§3.9.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    machine_id: str
    location_name: str
    employee_id: str
    employee_name: str
    timestamp: datetime
    confidence: float
    is_manual: bool
    manual_reason: str | None
    sync_status: str
    snapshot_available: bool
    created_at: datetime


class AuditLogOut(BaseModel):
    """One audit entry (§3.9.5)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    affected_id: str | None
    source: str
    actor: str | None
    old_value: str | None
    new_value: str | None
    note: str | None
    created_at: datetime
