"""Tests for /api/v1/system/logs + the write_system_log helper (SRS §3.12)."""
from __future__ import annotations


def test_write_and_query(client, admin_headers):
    from app.db import SessionLocal
    from app.services.system_log import write_system_log

    with SessionLocal() as db:
        write_system_log(db, event="test.event", message="hello world", severity="warning")
        write_system_log(db, event="test.other", message="another", severity="error")

    r = client.get("/api/v1/system/logs?limit=10", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 2
    events = {item["event"] for item in data["items"]}
    assert "test.event" in events


def test_filter_by_severity(client, admin_headers):
    from app.db import SessionLocal
    from app.services.system_log import write_system_log

    with SessionLocal() as db:
        write_system_log(db, event="filter.info", message="i", severity="info")
        write_system_log(db, event="filter.error", message="e", severity="error")

    r = client.get("/api/v1/system/logs?severity=error", headers=admin_headers)
    items = r.json()["data"]["items"]
    assert items and all(item["severity"] == "error" for item in items)


def test_filter_by_event(client, admin_headers):
    from app.db import SessionLocal
    from app.services.system_log import write_system_log

    with SessionLocal() as db:
        write_system_log(db, event="unique.event.xyz", message="x")

    r = client.get("/api/v1/system/logs?event=unique.event.xyz", headers=admin_headers)
    data = r.json()["data"]
    assert data["total"] >= 1
    assert all(item["event"] == "unique.event.xyz" for item in data["items"])


def test_pagination(client, admin_headers):
    from app.db import SessionLocal
    from app.services.system_log import write_system_log

    with SessionLocal() as db:
        for i in range(5):
            write_system_log(db, event=f"page.test.{i}", message=f"row {i}")

    r = client.get("/api/v1/system/logs?event=page.test.0&page=1&limit=2", headers=admin_headers)
    assert len(r.json()["data"]["items"]) <= 2


def test_requires_auth(client):
    assert client.get("/api/v1/system/logs").status_code == 401


def test_readonly_allowed(client, ro_headers):
    r = client.get("/api/v1/system/logs", headers=ro_headers)
    assert r.status_code == 200
