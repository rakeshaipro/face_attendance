"""Batch sync to the HRMS (SRS §3.7).

Secondary delivery mechanism for recovering from HRMS outages. The primary
path is the webhook system (§3.6). Batch sends records in chunks to a
separate batch URL, signing each request with HMAC like a webhook.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import SyncStatus
from app.core.security import hmac_sha256_hex
from app.core.settings_store import get_int, get_value
from app.models import AttendanceLog

logger = logging.getLogger(__name__)


def status_counts(db: Session) -> dict[str, int]:
    """Return pending/sent/failed/manual/total counts (§3.7.8)."""
    counts = {s: 0 for s in ("pending", "sent", "failed", "manual")}
    rows = db.execute(
        select(AttendanceLog.sync_status).where(AttendanceLog.is_manual.is_(False))
    ).scalars().all()
    for s in rows:
        counts[s] = counts.get(s, 0) + 1
    counts["manual"] = db.execute(
        select(AttendanceLog).where(AttendanceLog.is_manual.is_(True))
    ).scalars().all().__len__()
    counts["total"] = sum(counts.values())
    return counts


def _collect(
    db: Session,
    *,
    statuses: list[str],
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int | None,
) -> list[AttendanceLog]:
    stmt = select(AttendanceLog).where(AttendanceLog.sync_status.in_(statuses))
    if date_from:
        stmt = stmt.where(AttendanceLog.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceLog.timestamp <= date_to)
    stmt = stmt.order_by(AttendanceLog.timestamp.asc())
    if limit:
        stmt = stmt.limit(limit)
    return db.execute(stmt).scalars().all()


def _record_payload(log: AttendanceLog, machine: dict) -> dict:
    return {
        "log_id": log.id,
        "employee_id": log.employee_id,
        "name": log.employee_name,
        "confidence": log.confidence,
        "timestamp": log.timestamp.isoformat(),
        "snapshot_url": f"/api/v1/attendance/{log.id}/snapshot" if log.snapshot_available else None,
        "machine": machine,
    }


async def send_batch(
    db: Session,
    *,
    statuses: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Send pending/failed (or any status) records in batches to the batch URL.

    Returns {attempted, delivered, failed, batches, error}.
    On 2xx for a batch, marks those records `sent`. On failure, leaves
    their status unchanged so they're retried next time (§6.2.4).
    """
    if statuses is None:
        statuses = [SyncStatus.PENDING.value, SyncStatus.FAILED.value]

    batch_url = get_value(db, "sync.batch_url")
    if not batch_url:
        return {"attempted": 0, "delivered": 0, "failed": 0, "batches": 0, "error": "sync.batch_url not configured"}

    batch_size = max(1, get_int(db, "sync.batch_size"))
    machine = {
        "id": get_value(db, "device.machine_id"),
        "name": get_value(db, "device.location_name"),
        "timezone": get_value(db, "device.timezone"),
    }

    all_rows = _collect(db, statuses=statuses, date_from=date_from, date_to=date_to, limit=None)
    attempted = len(all_rows)
    delivered = failed = batches = 0
    error: str | None = None

    timeout = httpx.Timeout(30.0)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            for i in range(0, attempted, batch_size):
                chunk = all_rows[i : i + batch_size]
                payload = {"records": [_record_payload(r, machine) for r in chunk]}
                import json

                raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "X-Batch-Size": str(len(chunk)),
                }
                # HMAC with a fixed batch secret (reuses the first webhook's
                # secret if present, else the configured batch_url's userinfo).
                from app.models import Webhook

                wh = db.execute(select(Webhook).limit(1)).scalar_one_or_none()
                if wh and wh.secret_encrypted:
                    from app.core.crypto import decrypt

                    secret = decrypt(wh.secret_encrypted)
                    headers["X-Signature"] = f"sha256={hmac_sha256_hex(secret, raw)}"

                try:
                    resp = await client.post(batch_url, content=raw, headers=headers)
                    if 200 <= resp.status_code < 300:
                        for r in chunk:
                            r.sync_status = SyncStatus.SENT.value
                        delivered += len(chunk)
                    else:
                        failed += len(chunk)
                        error = f"batch HTTP {resp.status_code}"
                except Exception as exc:
                    failed += len(chunk)
                    error = str(exc) or "batch send error"
                batches += 1
        db.commit()
    except Exception as exc:
        error = str(exc) or "batch client error"

    return {
        "attempted": attempted,
        "delivered": delivered,
        "failed": failed,
        "batches": batches,
        "error": error,
    }
