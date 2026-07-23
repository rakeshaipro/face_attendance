"""Schemas for the system-log group (SRS §3.12)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SystemLogOut(BaseModel):
    """One operational log entry (§3.12.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    severity: str
    event: str
    message: str
    context_json: str | None = None
    created_at: datetime
