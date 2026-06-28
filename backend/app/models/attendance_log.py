"""Attendance log records (SRS §3.5, §5.1).

This is the single write-event of the system (§3.5.1). Records are
written to the DB before any webhook is dispatched (§6.2.1).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SyncStatus
from app.models.base import Base


class AttendanceLog(Base):
    __tablename__ = "attendance_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    location_name: Mapped[str] = mapped_column(String(160), nullable=False)

    employee_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Name stored at detection time, not looked up later (§3.5.2).
    employee_name: Mapped[str] = mapped_column(String(160), nullable=False)

    # Detection timestamp in the configured server timezone (§3.5.2).
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    sync_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SyncStatus.PENDING.value, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
