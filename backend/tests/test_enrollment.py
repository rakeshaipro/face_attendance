"""Tests for the enrollment group (SRS §3.3).

Uses FakeFaceProvider so the protocol logic runs without InsightFace.
"""
from __future__ import annotations

import io
import uuid

import pytest

from tests import fake_provider
from tests.fake_provider import _seed_embedding


def _set_pose(holder, *, yaw=0.0, pitch=0.0, embedding=None):
    holder["provider"] = fake_provider.FakeFaceProvider(yaw=yaw, pitch=pitch, embedding=embedding)


def _step_files(step, yaw, pitch):
    """Build a multipart files dict for a capture/pose-check at a pose."""
    _set_pose(_HOLDER, yaw=yaw, pitch=pitch)
    frame = fake_provider.make_frame()
    return {"file": ("f.jpg", io.BytesIO(fake_provider.jpeg_bytes(frame)), "image/jpeg")}


# Populated by the autouse fixture below.
_HOLDER: dict = {}


@pytest.fixture(autouse=True)
def patch_provider(monkeypatch):
    """Force the app to use a configurable fake provider per test."""
    _HOLDER.clear()
    _HOLDER["provider"] = fake_provider.FakeFaceProvider()

    def _get_provider():
        return _HOLDER["provider"]

    import app.engine.face_provider as fp
    monkeypatch.setattr(fp, "get_provider", _get_provider)
    import app.api.v1.enrollment as enr
    monkeypatch.setattr(enr, "get_provider", _get_provider)
    yield


def _create_employee(client, headers, eid: str | None = None) -> dict:
    if eid is None:
        eid = f"E-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/employees", headers=headers,
                    json={"employee_id": eid, "name": "Enrollee"})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_protocol_returns_seven_steps(client, admin_headers):
    r = client.get("/api/v1/employees/anything/face/protocol", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["steps"]) == 7
    assert data["mandatory_count"] == 5
    step_nums = [s["step"] for s in data["steps"]]
    assert step_nums == [1, 2, 3, 4, 5, 6, 7]


def test_status_initially_unenrolled(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    r = client.get(f"/api/v1/employees/{emp['id']}/face", headers=admin_headers)
    data = r.json()["data"]
    assert data["is_enrolled"] is False
    assert data["capture_count"] == 0


def test_pose_check_accepts_in_range(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    # Step 1 = forward; yaw/pitch near 0.
    files = _step_files(1, yaw=0.0, pitch=0.0)
    r = client.post(f"/api/v1/employees/{emp['id']}/face/pose-check?step=1",
                    headers=admin_headers, files=files)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["face_detected"] is True
    assert data["in_range"] is True


def test_pose_check_rejects_out_of_range(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    # Step 2 needs yaw in [-45,-30]; pass yaw=0 → out of range.
    files = _step_files(2, yaw=0.0, pitch=0.0)
    r = client.post(f"/api/v1/employees/{emp['id']}/face/pose-check?step=2",
                    headers=admin_headers, files=files)
    assert r.json()["data"]["in_range"] is False


def test_capture_saves_embedding_and_image(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    files = _step_files(1, yaw=0.0, pitch=0.0)
    r = client.post(f"/api/v1/employees/{emp['id']}/face/capture?step=1",
                    headers=admin_headers, files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["step"] == 1
    assert data["image_path"].endswith(".jpg")

    status = client.get(f"/api/v1/employees/{emp['id']}/face", headers=admin_headers).json()["data"]
    assert status["capture_count"] == 1
    assert 1 in status["steps_captured"]


def test_capture_upserts_per_step(client, admin_headers):
    """One embedding per step — re-capturing replaces, not adds (§3.3.15)."""
    emp = _create_employee(client, admin_headers)
    for _ in range(2):
        files = _step_files(1, yaw=0.0, pitch=0.0)
        r = client.post(f"/api/v1/employees/{emp['id']}/face/capture?step=1",
                        headers=admin_headers, files=files)
        assert r.status_code == 200
    status = client.get(f"/api/v1/employees/{emp['id']}/face", headers=admin_headers).json()["data"]
    assert status["capture_count"] == 1


def test_finalize_requires_mandatory_captures(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    # Only step 1 captured → finalize must reject.
    files = _step_files(1, yaw=0.0, pitch=0.0)
    client.post(f"/api/v1/employees/{emp['id']}/face/capture?step=1",
                headers=admin_headers, files=files)
    r = client.post(f"/api/v1/employees/{emp['id']}/face/finalize", headers=admin_headers)
    assert r.status_code == 400


def test_finalize_success_with_all_seven(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    poses = [
        (1, 0.0, 0.0),
        (2, -38.0, 0.0),
        (3, 38.0, 0.0),
        (4, 0.0, 28.0),
        (5, 0.0, -28.0),
        (6, -28.0, 20.0),
        (7, 28.0, -20.0),
    ]
    for step, yaw, pitch in poses:
        files = _step_files(step, yaw=yaw, pitch=pitch)
        r = client.post(f"/api/v1/employees/{emp['id']}/face/capture?step={step}",
                        headers=admin_headers, files=files)
        assert r.status_code == 200, r.text

    r = client.post(f"/api/v1/employees/{emp['id']}/face/finalize", headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["is_enrolled"] is True
    assert data["overall_quality"] > 0.0
    assert len(data["captures"]) == 7

    emp_now = client.get(f"/api/v1/employees/{emp['id']}", headers=admin_headers).json()["data"]
    assert emp_now["is_enrolled"] is True


def test_remove_resets_enrollment(client, admin_headers):
    emp = _create_employee(client, admin_headers)
    files = _step_files(1, yaw=0.0, pitch=0.0)
    client.post(f"/api/v1/employees/{emp['id']}/face/capture?step=1",
                headers=admin_headers, files=files)
    r = client.delete(f"/api/v1/employees/{emp['id']}/face", headers=admin_headers)
    assert r.status_code == 200
    status = client.get(f"/api/v1/employees/{emp['id']}/face", headers=admin_headers).json()["data"]
    assert status["capture_count"] == 0


def test_verify_returns_score(client, admin_headers):
    import numpy as np
    from tests.fake_provider import _seed_embedding

    emp = _create_employee(client, admin_headers)
    emb = _seed_embedding(42)
    files = _step_files(1, yaw=0.0, pitch=0.0)
    # Capture with a known embedding.
    _HOLDER["provider"] = fake_provider.FakeFaceProvider(yaw=0.0, pitch=0.0, embedding=emb)
    client.post(f"/api/v1/employees/{emp['id']}/face/capture?step=1",
                headers=admin_headers, files=files)
    # Verify with the SAME embedding → should match strongly.
    _HOLDER["provider"] = fake_provider.FakeFaceProvider(yaw=0.0, pitch=0.0, embedding=emb)
    files = {"file": ("f.jpg", io.BytesIO(fake_provider.jpeg_bytes(fake_provider.make_frame())), "image/jpeg")}
    r = client.post(f"/api/v1/employees/{emp['id']}/face/verify", headers=admin_headers, files=files)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["face_detected"] is True
    assert data["best_score"] is not None
    assert data["matched"] is True  # identical embedding → cosine ~1.0


def test_audit_rows_on_enrollment_actions(client, admin_headers):
    from app.db import SessionLocal
    from app.models import AuditLog

    emp = _create_employee(client, admin_headers)
    files = _step_files(1, yaw=0.0, pitch=0.0)
    client.post(f"/api/v1/employees/{emp['id']}/face/capture?step=1",
                headers=admin_headers, files=files)
    with SessionLocal() as db:
        actions = {r.action for r in db.query(AuditLog).filter(AuditLog.affected_id == emp["id"]).all()}
    assert "enrollment.capture" in actions
