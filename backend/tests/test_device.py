"""Tests for the /api/v1/device group (SRS §3.1, §3.4.14, §3.11.3)."""
from __future__ import annotations


def test_device_requires_api_key(client):
    r = client.get("/api/v1/device")
    assert r.status_code == 401
    # §4.3 envelope: HTTPException is normalised into {success, data, error}.
    body = r.json()
    assert body["success"] is False
    assert body["error"]


def test_device_rejects_invalid_key(client):
    r = client.get("/api/v1/device", headers={"X-API-Key": "garbage"})
    assert r.status_code == 401


def test_device_allows_readonly(client, ro_headers):
    r = client.get("/api/v1/device", headers=ro_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    # SRS §3.1.9 fields.
    for field in (
        "machine_id",
        "location_name",
        "software_version",
        "server_uptime_seconds",
        "timezone",
        "camera_url_masked",
        "service_state",
        "camera_status",
    ):
        assert field in data
    # Camera URL must be masked (§3.13.9): default URL has no creds, so it
    # stays as-is — but never contains raw userinfo when one is present.
    assert "://" in data["camera_url_masked"]


def test_service_control_requires_admin(client, ro_headers):
    r = client.post("/api/v1/device/service/pause", headers=ro_headers)
    assert r.status_code == 403


def test_service_pause_resume_admin(client, admin_headers):
    r1 = client.post("/api/v1/device/service/pause", headers=admin_headers)
    assert r1.status_code == 200
    assert r1.json()["data"]["service_state"] in {"paused", "running", "stopped"}

    r2 = client.post("/api/v1/device/service/resume", headers=admin_headers)
    assert r2.status_code == 200

    r3 = client.post("/api/v1/device/service/restart", headers=admin_headers)
    assert r3.status_code == 200


def test_stats_returns_envelope(client, admin_headers):
    r = client.get("/api/v1/device/stats", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    for field in (
        "service_state",
        "camera_status",
        "fps",
        "detections_last_hour",
        "detections_last_24h",
        "avg_confidence_24h",
        "last_frame_at",
    ):
        assert field in data


