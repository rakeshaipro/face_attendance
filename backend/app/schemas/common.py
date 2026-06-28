"""Common Pydantic schemas: response envelope (§4.3) and pagination (§4.5)."""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Standard response envelope (SRS §4.3)."""

    success: bool = True
    data: T | None = None
    error: str | None = None


class ErrorResponse(BaseModel):
    success: bool = Field(default=False)
    data: None = Field(default=None)
    error: str


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
