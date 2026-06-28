"""API keys (SRS §3.13).

Only the SHA-256 hash of the key is stored. The plaintext is shown to
the operator exactly once at creation time.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.core.enums import Scope


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # SHA-256 hex (64 chars) of the plaintext key (§3.13.6).
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Key prefix shown in listings so operators can recognise a key
    # without exposing it (e.g. "fa_abc…").
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=Scope.READONLY.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
