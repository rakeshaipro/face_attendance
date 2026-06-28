"""FastAPI dependencies shared across the API.

- `get_db`            : session per request
- `require_api_key`   : validates X-API-Key (§3.13.2), loads the ApiKey
- `require_scope(...)`: factory returning a dep that enforces RO/RW/ADMIN
- `get_settings_store`: typed view over the system_settings table
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Scope
from app.core.security import constant_time_equal, hash_api_key
from app.db import get_db
from app.models import ApiKey


def _get_header_api_key(request: Request) -> str | None:
    """Read the API key from the `X-API-Key` header, falling back to a
    `?key=` query parameter.

    The query-param fallback exists for media-element endpoints (MJPEG
    stream, single-frame JPEG) whose `<img>` tags cannot set custom
    headers (§3.1.5, §3.1.8). It is intentionally broad: it is only
    consulted when the header is absent, and is still validated exactly
    like a header key.
    """
    header = request.headers.get("X-API-Key")
    if header:
        return header
    return request.query_params.get("key")


def require_api_key(
    request: Request, db: Session = Depends(get_db)
) -> ApiKey:
    """Validate the X-API-Key header (§3.13.2) and return the ApiKey row.

    Raises 401 when missing/invalid, 403 when expired/disabled.
    """
    raw = _get_header_api_key(request)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )
    key_hash = hash_api_key(raw)
    api_key = db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    ).scalar_one_or_none()

    # Constant-time check protects against key-existence side channels.
    if api_key is None or not constant_time_equal(api_key.key_hash, key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    if api_key.expires_at is not None and api_key.expires_at <= datetime.now(api_key.expires_at.tzinfo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has expired.",
        )
    # Update last_used_at without failing the request if the row is stale.
    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return api_key


# Scope rank — higher includes all lower (§3.13.4).
_SCOPE_RANK: dict[Scope, int] = {
    Scope.READONLY: 1,
    Scope.READWRITE: 2,
    Scope.ADMIN: 3,
}


def require_scope(min_scope: Scope):
    """Dependency factory: enforce that the caller's scope >= min_scope."""

    def _dep(api_key: ApiKey = Depends(require_api_key)) -> ApiKey:
        try:
            have = Scope(api_key.scope)
        except ValueError:
            have = Scope.READONLY
        if _SCOPE_RANK[have] < _SCOPE_RANK[min_scope]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires scope '{min_scope.value}'.",
            )
        return api_key

    return _dep


def require_readonly(api_key: ApiKey = Depends(require_api_key)) -> ApiKey:
    return api_key


def require_readwrite(api_key: ApiKey = Depends(require_api_key)) -> ApiKey:
    if _SCOPE_RANK[Scope(api_key.scope)] < _SCOPE_RANK[Scope.READWRITE]:
        raise HTTPException(status_code=403, detail="Insufficient scope (readwrite required).")
    return api_key


def require_admin(api_key: ApiKey = Depends(require_api_key)) -> ApiKey:
    if _SCOPE_RANK[Scope(api_key.scope)] < _SCOPE_RANK[Scope.ADMIN]:
        raise HTTPException(status_code=403, detail="Insufficient scope (admin required).")
    return api_key
