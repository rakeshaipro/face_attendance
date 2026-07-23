"""Schemas for the webhooks group (SRS §3.6)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WebhookCreate(BaseModel):
    target_url: str = Field(..., min_length=1)
    events: list[str] = Field(..., min_length=1)
    secret: str | None = Field(default=None, description="HMAC secret (stored encrypted)")
    custom_headers: dict[str, str] | None = None
    is_enabled: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_ms: int = Field(default=5000, ge=500, le=30000)


class WebhookUpdate(BaseModel):
    target_url: str | None = Field(default=None, min_length=1)
    events: list[str] | None = None
    secret: str | None = None
    custom_headers: dict[str, str] | None = None
    is_enabled: bool | None = None
    max_retries: int | None = Field(default=None, ge=0, le=10)
    timeout_ms: int | None = Field(default=None, ge=500, le=30000)


class WebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_url: str
    events: list[str]
    custom_headers: dict[str, str] | None = None
    is_enabled: bool
    max_retries: int
    timeout_ms: int
    has_secret: bool
    created_at: datetime
    updated_at: datetime


class TestResult(BaseModel):
    """Outcome of a synthetic test delivery (§3.6.13)."""

    ok: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    webhook_id: str
    attendance_log_id: str | None
    event_type: str
    delivery_id: str
    attempt: int
    status_code: int | None
    response_body: str | None
    latency_ms: int | None
    error: str | None
    outcome: str
    created_at: datetime
