"""End-to-end tests for the webhook dispatcher (SRS §3.6).

Drives the real event bus → async subscriber → worker → httpx (mocked) →
DB chain. Validates §3.6: matching subscriptions, HMAC + header set,
retry/backoff, sync_status transitions, max-retries → failed.

These are asyncio tests (pytest-asyncio, auto mode).
"""
from __future__ import annotations

import json
import uuid

import httpx

from app.core.crypto import encrypt
from app.core.enums import EVENT_EMPLOYEE_DETECTED, SyncStatus
from app.db import SessionLocal
from app.events import bus
from app.models import AttendanceLog, Employee, Webhook


def _subscribe(db, *, events=("employee.detected",), secret="k", enabled=True, max_retries=3) -> str:
    wid = uuid.uuid4().hex
    db.add(
        Webhook(
            id=wid,
            target_url="https://hook.example/x",
            events=",".join(events),
            secret_encrypted=encrypt(secret) if secret else None,
            is_enabled=enabled,
            max_retries=max_retries,
            timeout_ms=2000,
        )
    )
    db.commit()
    return wid


def _delete_subscription(wid: str | None) -> None:
    if wid is None:
        return
    with SessionLocal() as db:
        row = db.get(Webhook, wid)
        if row is not None:
            db.delete(row)
            db.commit()


def _make_enrolled_employee(db) -> str:
    eid = uuid.uuid4().hex
    db.add(Employee(id=eid, employee_id=f"O-{eid[:6]}", name="Alice", is_enrolled=True))
    db.commit()
    return eid


def _make_log(db, employee_id: str) -> str:
    from datetime import datetime, timezone

    log_id = uuid.uuid4().hex
    db.add(
        AttendanceLog(
            id=log_id,
            machine_id="M1",
            location_name="Door",
            employee_id=employee_id,
            employee_name="Alice",
            timestamp=datetime.now(timezone.utc),
            confidence=0.9,
            snapshot_available=False,
            sync_status=SyncStatus.PENDING.value,
        )
    )
    db.commit()
    return log_id


async def _drain(dispatcher, timeout=3.0) -> None:
    """Wait for the worker to process all queued jobs."""
    import asyncio

    # Give the worker time to spin up + process; poll the queue + last activity.
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)
        if dispatcher._queue is None:
            break
        if dispatcher._queue.empty():
            # Queue momentarily empty — give a brief grace for a retry enqueue.
            await asyncio.sleep(0.1)
            if dispatcher._queue.empty():
                break


async def _setup_dispatcher(monkeypatch, transport) -> "WebhookDispatcher":  # type: ignore[name-defined]
    """Start the real dispatcher on this event loop with a mocked transport."""
    import asyncio

    from app.services.webhook_queue import dispatcher
    import app.services.webhooks as wh
    import app.services.webhook_queue as wq

    # Zero retry backoff (negative so the worker never defers) — fast retries.
    # Patch BOTH bindings: webhooks (used by tests) AND webhook_queue (used by
    # the worker, which imported the name locally).
    monkeypatch.setattr(wh, "retry_delay_for", lambda attempt: -1)
    monkeypatch.setattr(wq, "retry_delay_for", lambda attempt: -1)

    # Isolation: wipe any subscriptions left by other tests so only this
    # test's explicit subscriptions match events.
    with SessionLocal() as db:
        for row in db.query(Webhook).all():
            db.delete(row)
        db.commit()

    bus.set_loop(asyncio.get_event_loop())
    dispatcher.set_transport(transport)
    dispatcher.start()
    return dispatcher


async def _stop(dispatcher) -> None:
    await dispatcher.stop()
    dispatcher.set_transport(None)


async def test_successful_delivery_marks_sent(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    dispatcher = await _setup_dispatcher(monkeypatch, httpx.MockTransport(handler))
    wid = None
    try:
        with SessionLocal() as db:
            wid = _subscribe(db)  # a matching webhook subscription
            emp_id = _make_enrolled_employee(db)
            log_id = _make_log(db, emp_id)
        bus.publish(
            EVENT_EMPLOYEE_DETECTED,
            {
                "log_id": log_id,
                "employee_id": "O-1",
                "name": "Alice",
                "confidence": 0.9,
                "machine": {"id": "M1", "name": "Door", "timezone": "UTC"},
                "timestamp": "2026-01-01T00:00:00+00:00",
                "snapshot_url": "/api/v1/attendance/x/snapshot",
            },
        )
        await _drain(dispatcher)
        with SessionLocal() as db:
            assert db.get(AttendanceLog, log_id).sync_status == SyncStatus.SENT.value
    finally:
        _delete_subscription(wid)
        await _stop(dispatcher)

    assert captured["body"]["event"] == "employee.detected"
    assert captured["headers"]["x-signature"].startswith("sha256=")
    assert captured["headers"]["x-webhook-id"]
    assert captured["headers"]["x-delivery-id"]


async def test_non_2xx_retries_then_marks_failed(monkeypatch):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500, text="server error")

    dispatcher = await _setup_dispatcher(monkeypatch, httpx.MockTransport(handler))
    wid = None
    try:
        with SessionLocal() as db:
            wid = _subscribe(db, max_retries=2)  # 1 initial + 2 retries = 3 attempts
            emp_id = _make_enrolled_employee(db)
            log_id = _make_log(db, emp_id)
        bus.publish(
            EVENT_EMPLOYEE_DETECTED,
            {"log_id": log_id, "employee_id": "O", "name": "A", "confidence": 0.5, "machine": {}, "timestamp": "t", "snapshot_url": None},
        )
        await _drain(dispatcher, timeout=8.0)
        with SessionLocal() as db:
            log = db.get(AttendanceLog, log_id)
            # Count deliveries scoped to THIS log + THIS test's subscription.
            from app.models import WebhookDelivery
            dels = db.query(WebhookDelivery).filter(
                WebhookDelivery.attendance_log_id == log_id,
                WebhookDelivery.webhook_id == wid,
            ).all()
            attempts = len(dels)
            assert log.sync_status == SyncStatus.FAILED.value
    finally:
        _delete_subscription(wid)
        await _stop(dispatcher)
    # One initial + max_retries (2) retries = 3 attempts for this subscription.
    assert attempts == 3


async def test_disabled_webhook_skipped(monkeypatch):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200)

    dispatcher = await _setup_dispatcher(monkeypatch, httpx.MockTransport(handler))
    wid = None
    try:
        with SessionLocal() as db:
            wid = _subscribe(db, enabled=False)
            emp_id = _make_enrolled_employee(db)
            log_id = _make_log(db, emp_id)
        bus.publish(
            EVENT_EMPLOYEE_DETECTED,
            {"log_id": log_id, "employee_id": "O", "name": "A", "confidence": 0.5, "machine": {}, "timestamp": "t", "snapshot_url": None},
        )
        await _drain(dispatcher)
        with SessionLocal() as db:
            assert db.get(AttendanceLog, log_id).sync_status == SyncStatus.PENDING.value
    finally:
        _delete_subscription(wid)
        await _stop(dispatcher)
    assert call_count["n"] == 0


async def test_event_filter_excludes_non_subscribed(monkeypatch):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200)

    dispatcher = await _setup_dispatcher(monkeypatch, httpx.MockTransport(handler))
    wid = None
    try:
        with SessionLocal() as db:
            wid = _subscribe(db, events=("device.camera_offline",))
            emp_id = _make_enrolled_employee(db)
            log_id = _make_log(db, emp_id)
        bus.publish(
            EVENT_EMPLOYEE_DETECTED,
            {"log_id": log_id, "employee_id": "O", "name": "A", "confidence": 0.5, "machine": {}, "timestamp": "t", "snapshot_url": None},
        )
        await _drain(dispatcher)
    finally:
        _delete_subscription(wid)
        await _stop(dispatcher)
    assert call_count["n"] == 0
