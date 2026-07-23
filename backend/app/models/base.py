"""Shared ORM mixins and the re-exported Base.

All concrete models live in their own module and import `Base` from here.
Keeping a single `Base` (defined in app.db) lets Alembic autogenerate the
full schema in one migration.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base  # noqa: F401  (re-exported for convenience)


def _uuid() -> str:
    return uuid.uuid4().hex


class TimestampMixin:
    """Provides created_at / updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class PkMixin:
    """String primary key (UUID hex). IDs are strings throughout the API
    per the SRS data dictionary (§5.1, §5.2 — `id: String`)."""

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
