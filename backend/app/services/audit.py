"""Audit-log helper (SRS §3.9.5).

Every administrative mutation routes through `write_audit` so the audit
table stays the single source of truth for "who changed what, when".
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    db: Session,
    *,
    action: str,
    affected_id: str | None = None,
    source: str = "dashboard",
    actor: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    note: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """Append an audit row. `old_value`/`new_value` are JSON-encoded."""
    import json

    def _serialise(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v, default=str)
        except (TypeError, ValueError):
            return str(v)

    row = AuditLog(
        id=uuid.uuid4().hex,
        action=action,
        affected_id=affected_id,
        source=source,
        actor=actor,
        old_value=_serialise(old_value),
        new_value=_serialise(new_value),
        note=note,
    )
    db.add(row)
    if commit:
        db.commit()
    return row
