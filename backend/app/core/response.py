"""Response envelope helpers (SRS §4.3).

Every API response (except file downloads) uses the shape:

    { "success": bool, "data": <payload> | null, "error": <str> | null }
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
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


def ok(data: Any = None) -> dict[str, Any]:
    """Build a success envelope dict for direct JSONResponse use."""
    return {"success": True, "data": data, "error": None}


def fail(error: str) -> dict[str, Any]:
    """Build a failure envelope dict for direct JSONResponse use."""
    return {"success": False, "data": None, "error": error}
