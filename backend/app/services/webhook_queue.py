"""Webhook dispatcher + async worker (SRS §3.6).

Subscribes to the event bus for the four event types; enqueues each
matching subscription onto an asyncio.Queue; one worker task drains it,
sends via httpx, records the WebhookDelivery row, and flips the
AttendanceLog.sync_status. Retries use the §3.6.9 backoff schedule.

Designed to run inside the FastAPI event loop (started in lifespan).
The DB is the durable fallback: on crash, pending/failed records are
recovered by the Phase-4 batch-sync endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.enums import (
    EVENT_CAMERA_OFFLINE,
    EVENT_CAMERA_ONLINE,
    EVENT_EMPLOYEE_DETECTED,
    EVENT_STORAGE_LOW,
    SyncStatus,
)
from app.core.settings_store import get_value
from app.db import SessionLocal
from app.events import bus
from app.models import AttendanceLog, Webhook, WebhookDelivery
from app.services.webhooks import (
    RETRY_DELAYS,
    build_payload,
    headers_for,
    retry_delay_for,
    send_one,
)

logger = logging.getLogger(__name__)

DETECTION_EVENTS = {
    EVENT_EMPLOYEE_DETECTED,
    EVENT_CAMERA_OFFLINE,
    EVENT_CAMERA_ONLINE,
    EVENT_STORAGE_LOW,
}


@dataclass
class _Job:
    """One delivery attempt scheduled on the queue."""

    webhook_id: str
    event_type: str
    machine: dict
    data: dict
    attendance_log_id: str | None  # None for non-detection events
    delivery_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    attempt: int = 1
    # When this job becomes eligible (monotonic clock seconds). 0 = now.
    run_at: float = 0.0


class WebhookDispatcher:
    """Owns the queue + worker. Module-level singleton started in lifespan."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[_Job] | None = None
        self._worker: asyncio.Task | None = None
        self._running = False
        # Allow tests to inject a mock httpx transport.
        self._transport = None  # type: ignore[assignment]
        # Track our bus listeners so stop() can unsubscribe them (prevents
        # duplicate deliveries across start/stop cycles in tests + reloads).
        self._listener_refs: dict[str, object] = {}
        self._subscribed = False

    @property
    def is_running(self) -> bool:
        return self._running

    def set_transport(self, transport) -> None:  # type: ignore[no-untyped-def]
        """Test hook: inject an httpx transport (e.g. MockTransport)."""
        self._transport = transport

    # --- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._queue = asyncio.Queue()
        for evt in DETECTION_EVENTS:
            bus.subscribe_async(evt, self._on_event)
            self._listener_refs[evt] = self._on_event
        self._subscribed = True
        self._worker = asyncio.create_task(self._run_worker(), name="webhook-worker")
        self._running = True
        logger.info("webhook dispatcher started")

    async def stop(self) -> None:
        self._running = False
        if self._queue is not None:
            # Wake the worker so it can exit.
            await self._queue.put(_Job("__stop__", "", {}, {}, None))  # type: ignore[arg-type]
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker, timeout=5)
            except asyncio.TimeoutError:
                self._worker.cancel()
            self._worker = None
        if self._subscribed:
            # Unsubscribe so a subsequent start() doesn't stack duplicate listeners.
            for evt, ref in self._listener_refs.items():
                bus.unsubscribe_async(evt, ref)  # type: ignore[arg-type]
            self._listener_refs.clear()
            self._subscribed = False
        self._queue = None
        logger.info("webhook dispatcher stopped")

    # --- event-bus callback -------------------------------------------
    async def _on_event(self, event_type: str, payload: dict) -> None:
        """Bus subscriber: enqueue a job per matching subscription."""
        if self._queue is None:
            return
        # The attendance publish always carries these keys.
        data = {k: v for k, v in payload.items() if k != "machine"}
        machine = payload.get("machine", {})
        log_id = payload.get("log_id")
        try:
            with SessionLocal() as db:
                subs = self._matching_subscriptions(db, event_type)
                for sub in subs:
                    await self._queue.put(
                        _Job(
                            webhook_id=sub.id,
                            event_type=event_type,
                            machine=machine,
                            data=data,
                            attendance_log_id=log_id,
                        )
                    )
        except Exception:
            logger.exception("failed to enqueue webhook jobs for %s", event_type)

    def _matching_subscriptions(self, db, event_type: str) -> list[Webhook]:  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        rows = db.execute(
            select(Webhook).where(Webhook.is_enabled.is_(True))
        ).scalars().all()
        return [r for r in rows if event_type in (r.events.split(",") if r.events else [])]

    # --- worker --------------------------------------------------------
    async def _run_worker(self) -> None:
        assert self._queue is not None
        while self._running:
            job = await self._queue.get()
            if job.webhook_id == "__stop__":
                break
            # Honour scheduled run_at (retries with backoff).
            import time

            delay = job.run_at - time.monotonic()
            if delay > 0:
                # Re-queue and yield; coalesces multiple backoffs.
                await self._queue.put(job)
                await asyncio.sleep(min(delay, 0.5))
                continue
            try:
                await self._process_job(job)
            except Exception:
                logger.exception("webhook worker error on delivery %s", job.delivery_id)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: _Job) -> None:
        from app.core.crypto import decrypt

        with SessionLocal() as db:
            sub = db.get(Webhook, job.webhook_id)
            if sub is None or not sub.is_enabled:
                return  # subscription gone or disabled
            secret = decrypt(sub.secret_encrypted) if sub.secret_encrypted else None
            extra_headers = json.loads(sub.custom_headers_json) if sub.custom_headers_json else None

            raw_body, event_id = build_payload(
                job.event_type, job.data, job.machine, event_id=job.delivery_id
            )
            headers = headers_for(
                sub.id, job.event_type, job.delivery_id, raw_body, secret, extra_headers
            )
            result = await send_one(
                sub.target_url,
                raw_body,
                headers,
                timeout_ms=sub.timeout_ms,
                transport=self._transport,
            )

            # Record the delivery attempt.
            # max_retries is the number of RETRIES after the initial attempt,
            # so total attempts = max_retries + 1 (§3.6.9).
            outcome = "ok" if result.ok else ("retrying" if job.attempt <= sub.max_retries else "failed")
            delivery = WebhookDelivery(
                id=uuid.uuid4().hex,
                webhook_id=sub.id,
                attendance_log_id=job.attendance_log_id,
                event_type=job.event_type,
                delivery_id=job.delivery_id,
                attempt=job.attempt,
                status_code=result.status_code,
                response_body=result.response_body,
                latency_ms=result.latency_ms,
                error=result.error,
                outcome=outcome,
            )
            db.add(delivery)

            # Update the log row's sync_status (§3.7.1).
            if job.attendance_log_id and job.event_type == EVENT_EMPLOYEE_DETECTED:
                log = db.get(AttendanceLog, job.attendance_log_id)
                if log is not None:
                    if result.ok:
                        log.sync_status = SyncStatus.SENT.value
                    elif outcome == "failed":
                        log.sync_status = SyncStatus.FAILED.value
                    # else: leave pending — retry coming
            db.commit()

            # Record a system log on permanent delivery failure (§3.12).
            if outcome == "failed":
                from app.services.system_log import write_system_log

                write_system_log(
                    db,
                    severity="error",
                    event="webhook.delivery_failed",
                    message=f"Webhook {sub.id} permanently failed for {job.event_type} after {job.attempt} attempts: {result.error}",
                    context={"webhook_id": sub.id, "delivery_id": job.delivery_id, "status_code": result.status_code},
                    commit=True,
                )

            # Schedule a retry if needed (attempt counter is 1-based; we retry
            # while attempt <= max_retries, so the next attempt is +1).
            if outcome == "retrying":
                import time

                next_attempt = job.attempt + 1
                next_job = _Job(
                    webhook_id=job.webhook_id,
                    event_type=job.event_type,
                    machine=job.machine,
                    data=job.data,
                    attendance_log_id=job.attendance_log_id,
                    delivery_id=job.delivery_id,
                    attempt=next_attempt,
                    run_at=time.monotonic() + retry_delay_for(next_attempt),
                )
                await self._queue.put(next_job)

    # --- manual enqueue (API retry / test) -----------------------------
    async def enqueue_retry(self, webhook_id: str, delivery_id: str) -> bool:
        """Re-enqueue a previously-failed delivery (§3.6.12)."""
        if self._queue is None:
            return False
        with SessionLocal() as db:
            sub = db.get(Webhook, webhook_id)
            d = db.execute(
                WebhookDelivery.__table__.select().where(WebhookDelivery.delivery_id == delivery_id)
            ).first()
            if sub is None or d is None:
                return False
            await self._queue.put(
                _Job(
                    webhook_id=webhook_id,
                    event_type=d.event_type,
                    machine={},
                    data={},  # original payload not retained; dispatcher reuses event_id
                    attendance_log_id=d.attendance_log_id,
                    delivery_id=uuid.uuid4().hex,
                    attempt=d.attempt + 1,
                )
            )
        return True

    async def enqueue_test(self, webhook_id: str) -> bool:
        """Send a synthetic test delivery (§3.6.13)."""
        if self._queue is None:
            return False
        await self._queue.put(
            _Job(
                webhook_id=webhook_id,
                event_type=EVENT_EMPLOYEE_DETECTED,
                machine={"id": "test", "name": "test", "timezone": "UTC"},
                data={"log_id": None, "employee_id": "TEST", "name": "Test delivery", "confidence": 0.0, "snapshot_url": None},
                attendance_log_id=None,
            )
        )
        return True


# Module-level singleton.
dispatcher = WebhookDispatcher()
