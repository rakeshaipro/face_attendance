"""Stub routers for the remaining endpoint groups (SRS §4.6).

Each returns HTTP 501 Not Implemented with the standard envelope. The
business logic lands in later slices.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.response import fail
from app.api.deps import require_admin, require_readonly  # noqa: F401
from fastapi.responses import JSONResponse


def _stub(name: str) -> APIRouter:
    router = APIRouter()

    @router.get("", include_in_schema=False)
    @router.post("", include_in_schema=False)
    @router.get("/{item_id}", include_in_schema=False)
    @router.put("/{item_id}", include_in_schema=False)
    @router.delete("/{item_id}", include_in_schema=False)
    def _not_implemented() -> JSONResponse:
        return JSONResponse(status_code=501, content=fail(f"{name} not implemented in this phase."))

    return router
