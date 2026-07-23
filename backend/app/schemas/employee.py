"""Schemas for the employees group (SRS §3.2, §5.2)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmployeeBase(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    """All fields optional; partial update."""
    employee_id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    is_active: bool | None = None


class EmployeeOut(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_blocked: bool
    is_enrolled: bool
    enrolled_at: datetime | None = None
    enrollment_quality: float | None = None
    created_at: datetime
    updated_at: datetime


class BlockedEmployeeOut(BaseModel):
    """Compact view for the blocked-employees list (§3.2.9)."""

    id: str
    employee_id: str
    name: str
    is_blocked: bool


class BulkImportRow(BaseModel):
    row: int
    employee_id: str
    status: str  # "ok" | "error"
    error: str | None = None


class BulkImportResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    rows: list[BulkImportRow]
