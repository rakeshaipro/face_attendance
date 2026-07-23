"""Audit log — every administrative action (SRS §3.5.7, §3.5.8, §3.9.5).

Records manual log entries, log edits/deletions with reasons, employee
record changes, enrollment changes, settings changes, and API key actions.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Which record was touched (e.g. attendance log id, employee id).
    affected_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # "dashboard" or "api" (§3.9.5).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="dashboard")
    # Identity of the actor (API key label or "admin").
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)

    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False, index=True
    )
