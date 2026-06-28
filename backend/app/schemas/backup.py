"""Schemas for the backup group (SRS §3.10)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BackupCreate(BaseModel):
    kind: str = Field(default="database", pattern="^(full|database)$")


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    filename: str
    size_bytes: int
    origin: str
    is_scheduled: bool
    note: str | None = None
    created_at: datetime


class RestoreBody(BaseModel):
    """POST /backup/restore body (§3.10.7)."""

    confirm: bool = Field(
        default=False,
        description="Must be true to proceed; the current DB will be overwritten.",
    )


class RestoreResult(BaseModel):
    restored: bool
    kind: str
    filename: str | None = None
    error: str | None = None


class BackupScheduleConfig(BaseModel):
    enabled: bool
    frequency: str = Field(default="daily", pattern="^(daily|weekly)$")
    time: str = Field(default="02:00", description="HH:MM local time")
    max_scheduled: int = Field(default=14, ge=1, le=365)
