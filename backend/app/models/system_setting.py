"""System settings — key/value store for every configurable value in
the system (SRS §6.4.1). This is the runtime-editable counterpart to
the bootstrap settings that live in environment / .env.

The seed defaults are defined in app.engine.defaults (imported by the
seeding step on app startup).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Stored as text; callers coerce to int/float/bool/str as the key requires.
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
