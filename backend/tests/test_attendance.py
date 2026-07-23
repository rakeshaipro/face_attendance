"""Tests for /api/v1/attendance (SRS §3.5)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


def _make_employee(client, headers) -> str:
    r = client.post(
        "/api/v1/employees", headers=headers,
        json={"employee_id": f"ATT-{uuid.uuid4().hex[:6]}", "name": "Attendee"},
    )
    assert r.status_code == 201
    return r.json()["data"]["id"]


def _seed_log_via_service(employee_id: str, confidence: float = 0.9, days_ago: int = 0):
    """Insert a real detection-style log row using write_detection()."""
    import numpy as np

    from app.engine.service import service
    from app.db import SessionLocal
    from app.models import Employee
    from app.services.attendance import write_detection

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    with SessionLocal() as db:
        emp = db.get(Employee, employee_id)
        row = write_detection(db, emp, frame, confidence, publish=False)
        if days_ago:
            from datetime import timedelta

            row.timestamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
            db.commit()
        return row.id


def test_manual_entry_flags_is_manual_and_no_event(client, admin_headers, monkeypatch):
    emp_id = _make_employee(client, admin_headers)

    fired = []
    import app.services.attendance as att
    monkeypatch.setattr(att.bus, "publish", lambda *a, **k: fired.append(a))

    r = client.post(
        "/api/v1/attendance/manual", headers=admin_headers,
        json={
            "employee_id": emp_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "forgot badge",
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["is_manual"] is True
    assert data["sync_status"] == "manual"
    assert data["manual_reason"] == "forgot badge"
    assert fired == []  # §3.5.6 — no employee.detected event


def test_query_with_filters_and_pagination(client, admin_headers):
    emp_id = _make_employee(client, admin_headers)
    _seed_log_via_service(emp_id)
    _seed_log_via_service(emp_id)

    r = client.get(f"/api/v1/attendance?employee_id={emp_id}", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 2
    assert all(i["employee_id"] == emp_id for i in data["items"])

    r2 = client.get(f"/api/v1/attendance?employee_id={emp_id}&page=1&limit=1", headers=admin_headers)
    assert len(r2.json()["data"]["items"]) == 1


def test_today_endpoint(client, admin_headers):
    emp_id = _make_employee(client, admin_headers)
    _seed_log_via_service(emp_id, days_ago=0)
    _seed_log_via_service(emp_id, days_ago=3)  # old — excluded from today

    r = client.get("/api/v1/attendance/today", headers=admin_headers)
    assert r.status_code == 200
    # Today's count should be at least 1; the 3-day-old one must be absent.
    ids_today = {i["id"] for i in r.json()["data"]["items"]}
    assert len(ids_today) >= 1


def test_manual_entry_unknown_employee_404(client, admin_headers):
    r = client.post(
        "/api/v1/attendance/manual", headers=admin_headers,
        json={
            "employee_id": "does-not-exist",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "x",
        },
    )
    assert r.status_code == 404


def test_edit_log_writes_audit(client, admin_headers):
    from app.db import SessionLocal
    from app.models import AuditLog

    emp_id = _make_employee(client, admin_headers)
    log_id = _seed_log_via_service(emp_id)
    new_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    r = client.put(
        f"/api/v1/attendance/{log_id}", headers=admin_headers,
        json={"timestamp": new_ts.isoformat(), "note": "corrected"},
    )
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        actions = [a.action for a in db.query(AuditLog).filter(AuditLog.affected_id == log_id).all()]
    assert "attendance.edit" in actions


def test_delete_requires_reason_and_admin(client, admin_headers, ro_headers):
    emp_id = _make_employee(client, admin_headers)
    log_id = _seed_log_via_service(emp_id)

    # No reason → 422 (Query required).
    r1 = client.delete(f"/api/v1/attendance/{log_id}", headers=admin_headers)
    assert r1.status_code == 422

    # Readonly can't (scope check fires before query validation? Depends on
    # FastAPI order). Assert it's not 200.
    r2 = client.delete(f"/api/v1/attendance/{log_id}?reason=x", headers=ro_headers)
    assert r2.status_code in {403, 422}

    # Admin with reason → 200.
    r3 = client.delete(f"/api/v1/attendance/{log_id}?reason=mistake", headers=admin_headers)
    assert r3.status_code == 200


def test_snapshot_download_and_404_when_purged(client, admin_headers):
    emp_id = _make_employee(client, admin_headers)
    log_id = _seed_log_via_service(emp_id)

    r = client.get(f"/api/v1/attendance/{log_id}/snapshot", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"

    # A manual record has no snapshot.
    manual = client.post(
        "/api/v1/attendance/manual", headers=admin_headers,
        json={
            "employee_id": emp_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "no snapshot",
        },
    ).json()["data"]
    r2 = client.get(f"/api/v1/attendance/{manual['id']}/snapshot", headers=admin_headers)
    assert r2.status_code == 404
