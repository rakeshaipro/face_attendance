"""Schemas for the sync group (SRS §3.7)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SyncCounts(BaseModel):
    """GET /sync/status (§3.7.8)."""

    pending: int
    sent: int
    failed: int
    manual: int
    total: int


class BatchResult(BaseModel):
    """POST /sync/batch and /sync/resend result (§3.7.3, §3.7.9)."""

    attempted: int
    delivered: int
    failed: int
    batches: int
    error: str | None = None


class BatchBody(BaseModel):
    """Optional body for batch / resend endpoints."""

    date_from: str | None = None
    date_to: str | None = None
    only_status: list[str] | None = Field(
        default=None,
        description="Filter by sync status. Default for /batch: pending+failed. Default for /resend: sent.",
    )


class SyncConfig(BaseModel):
    auto_enabled: bool
    auto_interval_seconds: int
    batch_size: int
    batch_url: str
