"""Webhook subscriptions and delivery attempts (SRS §3.6)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Comma-separated event types subscribed to (§3.6.3).
    events: Mapped[str] = mapped_column(Text, nullable=False)
    # HMAC secret, encrypted at rest with the app Fernet key.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded custom HTTP headers (§3.6.1).
    custom_headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    webhook_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which log/event this delivery carries (nullable for non-detection events).
    attendance_log_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # Unique per delivery attempt (§3.6.6 — X-Delivery-ID).
    delivery_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ok | retrying | failed
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="retrying")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
