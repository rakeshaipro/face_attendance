"""Tests for /api/v1/sync (SRS §3.7) and the batch-send service."""
from __future__ import annotations

import json
import uuid

import httpx

from app.core.enums import SyncStatus
from app.db import SessionLocal
from app.models import AttendanceLog, Employee
from app.core.settings_store import set_value


def _seed_pending_logs(db, n: int, status: str = SyncStatus.PENDING.value) -> list[str]:
    from datetime import datetime, timezone

    emp_id = uuid.uuid4().hex
    db.add(Employee(id=emp_id, employee_id=f"O-{emp_id[:6]}", name="Sync Employee", is_enrolled=True))
    db.commit()
    now = datetime.now(timezone.utc)
    ids = []
    for _ in range(n):
        lid = uuid.uuid4().hex
        db.add(
            AttendanceLog(
                id=lid,
                machine_id="M1",
                location_name="Door",
                employee_id=emp_id,
                employee_name="Sync Employee",
                timestamp=now,
                confidence=0.9,
                snapshot_available=False,
                sync_status=status,
            )
        )
        ids.append(lid)
    db.commit()
    return ids


def test_status_counts(client, admin_headers):
    with SessionLocal() as db:
        _seed_pending_logs(db, 3, status=SyncStatus.PENDING.value)
        _seed_pending_logs(db, 2, status=SyncStatus.SENT.value)
    r = client.get("/api/v1/sync/status", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["pending"] >= 3
    assert data["sent"] >= 2
    assert data["total"] >= 5


def test_batch_unconfigured_returns_error(client, admin_headers):
    # Default sync.batch_url is empty.
    r = client.post("/api/v1/sync/batch", headers=admin_headers, json={})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["attempted"] == 0
    assert data["error"] and "not configured" in data["error"]


def test_batch_send_marks_sent_on_success(client, admin_headers, monkeypatch):
    # Configure a batch URL.
    with SessionLocal() as db:
        set_value(db, "sync.batch_url", "https://hrms.example/batch")
        set_value(db, "sync.batch_size", "2")
        ids = _seed_pending_logs(db, 3)  # 3 pending → 2 batches (2 + 1)

    captured = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"].append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    # Patch httpx.AsyncClient to force the mock transport (the service passes
    # transport=None explicitly, so setdefault won't help — we force-override).
    _orig = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return _orig(*a, **k)

    monkeypatch.setattr("app.services.sync.httpx.AsyncClient", _client)
    try:
        r = client.post("/api/v1/sync/batch", headers=admin_headers, json={})
    finally:
        pass

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    # Counts may include leftover pending records from earlier tests in the
    # shared session DB; the core assertions are delivery success + per-record status.
    assert data["delivered"] == data["attempted"]
    assert data["failed"] == 0
    assert data["batches"] >= 2  # batch_size=2 → at least ceil(3/2)=2

    with SessionLocal() as db:
        for lid in ids:
            assert db.get(AttendanceLog, lid).sync_status == SyncStatus.SENT.value

    # Each batch request carried ≤ batch_size (2) records.
    assert all(len(r["records"]) <= 2 for r in captured["requests"])


def test_batch_failure_leaves_status_unchanged(client, admin_headers, monkeypatch):
    with SessionLocal() as db:
        set_value(db, "sync.batch_url", "https://hrms.example/batch")
        set_value(db, "sync.batch_size", "10")
        ids = _seed_pending_logs(db, 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    _orig = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return _orig(*a, **k)

    monkeypatch.setattr("app.services.sync.httpx.AsyncClient", _client)
    r = client.post("/api/v1/sync/batch", headers=admin_headers, json={})
    data = r.json()["data"]
    assert data["delivered"] == 0
    assert data["failed"] == data["attempted"]  # all attempted records failed
    with SessionLocal() as db:
        for lid in ids:
            assert db.get(AttendanceLog, lid).sync_status == SyncStatus.PENDING.value


def test_resend_includes_sent_records(client, admin_headers, monkeypatch):
    with SessionLocal() as db:
        set_value(db, "sync.batch_url", "https://hrms.example/batch")
        set_value(db, "sync.batch_size", "100")
        sent_ids = _seed_pending_logs(db, 1, status=SyncStatus.SENT.value)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    _orig = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return _orig(*a, **k)

    monkeypatch.setattr("app.services.sync.httpx.AsyncClient", _client)
    r = client.post("/api/v1/sync/resend", headers=admin_headers, json={})
    data = r.json()["data"]
    assert data["attempted"] >= 1  # the sent record was re-included


def test_config_roundtrip(client, admin_headers):
    r = client.put(
        "/api/v1/sync/config",
        headers=admin_headers,
        json={"auto_enabled": True, "auto_interval_seconds": 120, "batch_size": 50, "batch_url": "https://x/b"},
    )
    assert r.status_code == 200
    got = client.get("/api/v1/sync/config", headers=admin_headers).json()["data"]
    assert got["auto_enabled"] is True
    assert got["auto_interval_seconds"] == 120
    assert got["batch_url"] == "https://x/b"

    # Auto-sync job should now be registered.
    from app.workers import scheduler as scheduler_worker

    assert scheduler_worker.get_scheduler().get_job("sync-autosync") is not None

    # Disable → job removed.
    client.put(
        "/api/v1/sync/config",
        headers=admin_headers,
        json={"auto_enabled": False, "auto_interval_seconds": 120, "batch_size": 50, "batch_url": "https://x/b"},
    )
    assert scheduler_worker.get_scheduler().get_job("sync-autosync") is None
