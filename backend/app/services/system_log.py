"""System-log helper (SRS §3.12).

Operational events (service start/stop, camera connect/disconnect,
webhook failures, backup events, errors) route through `write_system_log`
so the system_logs table is the operational counterpart to the audit log
(which records administrative actions, §3.9.5).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import LogSeverity
from app.models import SystemLog

logger = logging.getLogger(__name__)


def write_system_log(
    db: Session,
    *,
    severity: str | LogSeverity = LogSeverity.INFO,
    event: str,
    message: str,
    context: dict[str, Any] | None = None,
    commit: bool = True,
) -> SystemLog:
    """Append a system-log row (§3.12).

    `severity` is one of info/warning/error (§3.12.2). `event` is a short
    stable code (e.g. "engine.start", "camera.offline"). `context` is an
    optional dict stored as JSON.
    """
    sev = severity.value if isinstance(severity, LogSeverity) else severity
    row = SystemLog(
        id=uuid.uuid4().hex,
        severity=sev,
        event=event,
        message=message,
        context_json=json.dumps(context, default=str) if context else None,
    )
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    # Mirror to the Python logger so operators see it in stdout too.
    log_fn = logger.info if sev == LogSeverity.INFO.value else (
        logger.warning if sev == LogSeverity.WARNING.value else logger.error
    )
    log_fn("[%s] %s", event, message)
    return row
