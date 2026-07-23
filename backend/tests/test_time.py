"""Tests for the /api/v1/time group (SRS §3.1.10, §3.1.11).

ntplib is mocked throughout — no real network is exercised.
"""
from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import patch


# --- GET /time ----------------------------------------------------------
def test_get_time_requires_api_key(client):
    r = client.get("/api/v1/time")
    assert r.status_code == 401


def test_get_time_returns_clock_and_config(client, ro_headers):
    r = client.get("/api/v1/time", headers=ro_headers)
    assert r.status_code == 200
    body = r.json()["data"]
    # ISO-8601 UTC timestamp ending with +00:00.
    assert body["server_now_utc"].endswith("+00:00")
    # Defaults seeded in engine/defaults.py.
    assert body["timezone"] == "UTC"
    assert body["ntp_server"] == "pool.ntp.org"
    assert body["uptime_seconds"] >= 0


# --- PUT /time ----------------------------------------------------------
def test_put_time_requires_admin(client, ro_headers):
    r = client.put(
        "/api/v1/time",
        headers=ro_headers,
        json={"timezone": "UTC", "ntp_server": "pool.ntp.org"},
    )
    assert r.status_code == 403


def test_put_time_saves_timezone_and_ntp(client, admin_headers):
    r = client.put(
        "/api/v1/time",
        headers=admin_headers,
        json={"timezone": "Asia/Kolkata", "ntp_server": "time.windows.com"},
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["timezone"] == "Asia/Kolkata"
    assert body["ntp_server"] == "time.windows.com"

    # Round-trip via GET.
    g = client.get("/api/v1/time", headers=admin_headers).json()["data"]
    assert g["timezone"] == "Asia/Kolkata"
    assert g["ntp_server"] == "time.windows.com"


def test_put_time_rejects_unknown_timezone(client, admin_headers):
    r = client.put(
        "/api/v1/time",
        headers=admin_headers,
        json={"timezone": "Not/A_Real_Zone", "ntp_server": "pool.ntp.org"},
    )
    assert r.status_code == 400
    assert "Unknown timezone" in r.json()["error"]


def test_put_time_rejects_empty_timezone(client, admin_headers):
    # Pydantic min_length=1 catches this before our handler runs.
    r = client.put(
        "/api/v1/time",
        headers=admin_headers,
        json={"timezone": "", "ntp_server": "pool.ntp.org"},
    )
    assert r.status_code == 422


def test_put_time_rejects_bad_ntp_hostname(client, admin_headers):
    r = client.put(
        "/api/v1/time",
        headers=admin_headers,
        json={"timezone": "UTC", "ntp_server": "bad server!"},
    )
    assert r.status_code == 400
    assert "NTP server" in r.json()["error"]


def test_put_time_accepts_ipv4_ntp(client, admin_headers):
    r = client.put(
        "/api/v1/time",
        headers=admin_headers,
        json={"timezone": "America/New_York", "ntp_server": "129.6.15.28"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["ntp_server"] == "129.6.15.28"


def test_put_time_writes_audit_and_system_log(client, admin_headers):
    from app.db import SessionLocal
    from app.models import AuditLog, SystemLog

    # Snapshot counts *inside* a session so we read committed state.
    with SessionLocal() as db:
        before_audit = db.query(AuditLog).filter(AuditLog.action == "time.update").count()
        before_log = db.query(SystemLog).filter(SystemLog.event == "time.update").count()

    r = client.put(
        "/api/v1/time",
        headers=admin_headers,
        json={"timezone": "Europe/London", "ntp_server": "pool.ntp.org"},
    )
    assert r.status_code == 200

    with SessionLocal() as db:
        audits = db.query(AuditLog).filter(AuditLog.action == "time.update").all()
        assert len(audits) > before_audit
        last = audits[-1]
        # new_value carries what we just wrote; old_value carries the prior tz.
        assert "Europe/London" in (last.new_value or "")
        assert "pool.ntp.org" in (last.new_value or "")
        # old_value is JSON with a timezone field — just confirm it's present.
        assert "timezone" in (last.old_value or "")

        logs = db.query(SystemLog).filter(SystemLog.event == "time.update").all()
        assert len(logs) > before_log


# --- POST /time/ntp-sync ------------------------------------------------
def test_ntp_sync_requires_admin(client, ro_headers):
    r = client.post("/api/v1/time/ntp-sync", headers=ro_headers)
    assert r.status_code == 403


def test_ntp_sync_success_returns_offset_and_rtt(client, admin_headers):
    fake_stats = SimpleNamespace(offset=0.123, delay=0.0456)  # delay in seconds
    with patch("ntplib.NTPClient.request", return_value=fake_stats):
        r = client.post("/api/v1/time/ntp-sync", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["synchronized"] is True
    assert body["offset_seconds"] == 0.123
    # delay=0.0456s → 45.6 ms
    assert abs(body["rtt_ms"] - 45.6) < 0.01
    assert body["ntp_server"] == "pool.ntp.org"
    assert body["server_now_utc"].endswith("+00:00")


def test_ntp_sync_success_writes_system_log(client, admin_headers):
    from app.db import SessionLocal
    from app.models import SystemLog

    fake_stats = SimpleNamespace(offset=0.05, delay=0.01)
    with patch("ntplib.NTPClient.request", return_value=fake_stats):
        r = client.post("/api/v1/time/ntp-sync", headers=admin_headers)
    assert r.status_code == 200

    with SessionLocal() as db:
        row = (
            db.query(SystemLog)
            .filter(SystemLog.event == "time.ntp_sync_ok")
            .order_by(SystemLog.created_at.desc())
            .first()
        )
        assert row is not None
        assert "pool.ntp.org" in row.message
        assert "offset=" in row.message


def test_ntp_sync_dns_failure_returns_502(client, admin_headers):
    def _raise(*args, **kwargs):
        raise socket.gaierror(8, "getaddrinfo failed", "name not resolved")

    with patch("ntplib.NTPClient.request", side_effect=_raise):
        r = client.post("/api/v1/time/ntp-sync", headers=admin_headers)
    assert r.status_code == 502
    assert "DNS" in r.json()["error"]


def test_ntp_sync_timeout_returns_502(client, admin_headers):
    def _raise(*args, **kwargs):
        raise socket.timeout("timed out")

    with patch("ntplib.NTPClient.request", side_effect=_raise):
        r = client.post("/api/v1/time/ntp-sync", headers=admin_headers)
    assert r.status_code == 502
    assert "timed out" in r.json()["error"].lower()


def test_ntp_sync_failure_writes_warning_system_log(client, admin_headers):
    from app.db import SessionLocal
    from app.models import SystemLog

    with patch("ntplib.NTPClient.request", side_effect=Exception("bad reply")):
        r = client.post("/api/v1/time/ntp-sync", headers=admin_headers)
    assert r.status_code == 502

    with SessionLocal() as db:
        row = (
            db.query(SystemLog)
            .filter(SystemLog.event == "time.ntp_sync_failed")
            .order_by(SystemLog.created_at.desc())
            .first()
        )
        assert row is not None
        assert row.severity == "warning"
        assert "pool.ntp.org" in row.message
