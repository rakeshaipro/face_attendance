"""System (operational) logs (SRS §3.12).

Distinct from attendance logs. Records service starts/stops, camera
connect/disconnect, webhook delivery failures, enrollment events,
settings changes, and errors. Fixed 90-day retention (§3.12.6).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import LogSeverity
from app.models.base import Base


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LogSeverity.INFO.value, index=True
    )
    # Short stable code, e.g. "engine.start", "camera.offline".
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional structured context as JSON.
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False, index=True
    )
