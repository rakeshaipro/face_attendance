"""Webhook payload construction, signing, and single-delivery send (SRS §3.6).

These are pure-ish functions: `build_payload` and `sign` are fully pure,
and `send_one` performs one HTTP attempt via httpx and returns the result
without touching the DB. The dispatcher/queue layer records outcomes.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.security import hmac_sha256_hex

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    """Outcome of one HTTP attempt (§3.6.8)."""

    ok: bool                # HTTP 2xx within timeout
    status_code: int | None
    response_body: str | None  # truncated to 500 chars (§3.6.11)
    latency_ms: int | None
    error: str | None
    # Bytes actually sent (for the delivery row's signature calc).
    request_body: bytes


def build_payload(
    event_type: str,
    data: dict,
    machine: dict,
    *,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> tuple[bytes, str]:
    """Build the canonical JSON body for an event (§3.6.4 / §3.6.5).

    Returns (raw_body_bytes, event_id). The raw bytes are what's signed
    and sent — callers must NOT re-serialise.
    """
    eid = event_id or uuid.uuid4().hex
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    body = {
        "event": event_type,
        "id": eid,
        "timestamp": ts,
        "machine": machine,
        "data": data,
    }
    # signature is filled by sign(); left absent here so unsigned payloads
    # are detectable.
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return raw, eid


def sign(raw_body: bytes, secret: str) -> str:
    """Return the X-Signature header value: 'sha256=<hex>' (§3.6.6)."""
    return f"sha256={hmac_sha256_hex(secret, raw_body)}"


def headers_for(
    webhook_id: str,
    event_type: str,
    delivery_id: str,
    raw_body: bytes,
    secret: str | None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Assemble the §3.6.6 header set. Secret omitted → no X-Signature."""
    h = {
        "Content-Type": "application/json",
        "X-Webhook-ID": webhook_id,
        "X-Event": event_type,
        "X-Delivery-ID": delivery_id,
    }
    if secret:
        h["X-Signature"] = sign(raw_body, secret)
    if extra:
        h.update(extra)
    return h


async def send_one(
    url: str,
    raw_body: bytes,
    headers: dict[str, str],
    *,
    timeout_ms: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SendResult:
    """One HTTP POST attempt. Returns SendResult; never raises (errors → result.error)."""
    import time

    started = time.monotonic()
    timeout = httpx.Timeout(max(timeout_ms / 1000.0, 0.5))
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            resp = await client.post(url, content=raw_body, headers=headers)
        latency_ms = int((time.monotonic() - started) * 1000)
        text = (resp.text or "")[:500] or None
        ok = 200 <= resp.status_code < 300
        return SendResult(
            ok=ok,
            status_code=resp.status_code,
            response_body=text,
            latency_ms=latency_ms,
            error=None if ok else f"HTTP {resp.status_code}",
            request_body=raw_body,
        )
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - started) * 1000)
        return SendResult(False, None, None, latency_ms, "timeout", raw_body)
    except Exception as exc:  # connection error, DNS, etc.
        latency_ms = int((time.monotonic() - started) * 1000)
        return SendResult(False, None, None, latency_ms, str(exc) or "request error", raw_body)


# Backoff schedule (§3.6.9): ~5s, 30s, 5min between retries.
RETRY_DELAYS = [5, 30, 300]


def retry_delay_for(attempt: int) -> int:
    """Seconds to wait before the given 1-based retry attempt (§3.6.9)."""
    if attempt <= 0:
        return 0
    idx = min(attempt - 1, len(RETRY_DELAYS) - 1)
    return RETRY_DELAYS[idx]
