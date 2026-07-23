"""Tests for /api/v1/webhooks (SRS §3.6) and the webhook service primitives."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.webhooks import build_payload, headers_for, sign


def _headers():
    return {"X-API-Key": _ADMIN_KEY} if _ADMIN_KEY else {}


# Populated by conftest at module bootstrap.
_ADMIN_KEY = ""


def test_build_payload_shape():
    raw, eid = build_payload(
        "employee.detected",
        {"log_id": "abc", "employee_id": "E1", "name": "Alice", "confidence": 0.9, "snapshot_url": "/x"},
        {"id": "M1", "name": "Door 1", "timezone": "UTC"},
        event_id="evt-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    import json

    body = json.loads(raw)
    assert body["event"] == "employee.detected"
    assert body["id"] == "evt-1"
    assert body["machine"]["id"] == "M1"
    assert body["data"]["employee_id"] == "E1"
    assert eid == "evt-1"


def test_sign_and_headers():
    raw, _ = build_payload("x", {}, {}, event_id="e")
    sig = sign(raw, "topsecret")
    assert sig.startswith("sha256=")
    h = headers_for("wh1", "x", "d1", raw, "topsecret", extra={"X-Tenant": "acme"})
    assert h["X-Signature"] == sig
    assert h["X-Webhook-ID"] == "wh1"
    assert h["X-Event"] == "x"
    assert h["X-Delivery-ID"] == "d1"
    assert h["X-Tenant"] == "acme"

    # HMAC is verifiable.
    import hmac as _hmac
    import hashlib

    expected = _hmac.new(b"topsecret", raw, hashlib.sha256).hexdigest()
    assert sig.split("=", 1)[1] == expected


def test_headers_without_secret_omit_signature():
    raw, _ = build_payload("x", {}, {})
    h = headers_for("wh", "x", "d", raw, None)
    assert "X-Signature" not in h


# --- API CRUD -------------------------------------------------------------
def test_create_and_list(client, admin_headers):
    r = client.post(
        "/api/v1/webhooks",
        headers=admin_headers,
        json={
            "target_url": "https://example.com/hook",
            "events": ["employee.detected"],
            "secret": "shh",
            "max_retries": 2,
            "timeout_ms": 3000,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["target_url"] == "https://example.com/hook"
    assert data["events"] == ["employee.detected"]
    assert data["has_secret"] is True
    assert "secret" not in data  # never returned plaintext (§3.13.9)

    # Secret is encrypted at rest.
    from app.db import SessionLocal
    from app.models import Webhook

    with SessionLocal() as db:
        row = db.get(Webhook, data["id"])
        assert row.secret_encrypted != "shh"
        assert row.secret_encrypted  # non-empty
        # Clean up so this subscription doesn't leak into dispatcher tests.
        db.delete(row)
        db.commit()

    listed = client.get("/api/v1/webhooks", headers=admin_headers).json()["data"]
    assert all(w["id"] != data["id"] for w in listed)


def test_update_and_delete(client, admin_headers):
    wid = client.post(
        "/api/v1/webhooks",
        headers=admin_headers,
        json={"target_url": "https://x.io/h", "events": ["employee.detected"]},
    ).json()["data"]["id"]

    upd = client.put(
        f"/api/v1/webhooks/{wid}",
        headers=admin_headers,
        json={"target_url": "https://y.io/h", "events": ["employee.detected", "device.camera_offline"], "is_enabled": False},
    )
    assert upd.status_code == 200
    data = upd.json()["data"]
    assert data["target_url"] == "https://y.io/h"
    assert "device.camera_offline" in data["events"]
    assert data["is_enabled"] is False

    # Delete requires admin.
    assert client.delete(f"/api/v1/webhooks/{wid}", headers=admin_headers).status_code == 200


def test_delete_requires_admin(client, ro_headers, admin_headers):
    wid = client.post(
        "/api/v1/webhooks", headers=admin_headers,
        json={"target_url": "https://x.io/h", "events": ["employee.detected"]},
    ).json()["data"]["id"]
    assert client.delete(f"/api/v1/webhooks/{wid}", headers=ro_headers).status_code == 403
    # cleanup
    client.delete(f"/api/v1/webhooks/{wid}", headers=admin_headers)


def test_test_delivery_with_mock(client, admin_headers, monkeypatch):
    """Synthetic test delivery hits a mocked transport and records a row."""
    wid = client.post(
        "/api/v1/webhooks", headers=admin_headers,
        json={"target_url": "https://hook.example/x", "events": ["employee.detected"], "secret": "k"},
    ).json()["data"]["id"]

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    # The test endpoint calls send_one(..., transport=None) explicitly, so
    # patching the constructor won't override it. Patch send_one itself to
    # inject the mock transport. The route imports send_one at call time.
    import app.services.webhooks as wh

    orig_send = wh.send_one

    async def send_with_mock(url, raw_body, headers, *, timeout_ms, transport=None):
        return await orig_send(url, raw_body, headers, timeout_ms=timeout_ms, transport=transport if transport is not None else transport)

    # Wrap so any caller gets the mock unless they pass one.
    captured_transport = transport

    async def patched_send(url, raw_body, headers, *, timeout_ms, transport=None):
        return await orig_send(url, raw_body, headers, timeout_ms=timeout_ms, transport=captured_transport)

    wh.send_one = patched_send  # type: ignore[assignment]
    try:
        r = client.post(f"/api/v1/webhooks/{wid}/test", headers=admin_headers)
    finally:
        wh.send_one = orig_send  # type: ignore[assignment]

    assert r.status_code == 200, r.text
    out = r.json()["data"]
    assert out["ok"] is True
    assert out["status_code"] == 200
    assert captured["url"] == "https://hook.example/x"
    assert captured["headers"]["x-signature"].startswith("sha256=")

    deliveries = client.get(f"/api/v1/webhooks/{wid}/deliveries", headers=admin_headers).json()["data"]
    assert deliveries["total"] >= 1


def test_deliveries_pagination(client, admin_headers):
    wid = client.post(
        "/api/v1/webhooks", headers=admin_headers,
        json={"target_url": "https://x.io/h", "events": ["employee.detected"]},
    ).json()["data"]["id"]
    r = client.get(f"/api/v1/webhooks/{wid}/deliveries?limit=10", headers=admin_headers)
    assert r.status_code == 200
    assert "total" in r.json()["data"]
