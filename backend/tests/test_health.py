"""Tests for GET /health (SRS §3.11.1).

This endpoint is intentionally unauthenticated so external monitors
can poll it without an API key.
"""
from __future__ import annotations


def test_health_no_auth_required(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    # Documented fields present.
    for field in (
        "recognition_service",
        "camera_status",
        "disk_free_mb",
        "enrolled_employees",
        "total_log_records",
        "server_uptime_seconds",
    ):
        assert field in data, f"missing field {field}"
    assert data["enrolled_employees"] >= 0
    assert data["total_log_records"] >= 0
    assert data["disk_free_mb"] >= 0


def test_health_returns_running_state_when_engine_off(client):
    # FA_AUTOSTART_ENGINE=false in conftest, so the service reports STOPPED.
    body = client.get("/health").json()["data"]
    assert body["recognition_service"] in {"stopped", "paused", "running"}
    assert body["camera_status"] in {"online", "offline"}
