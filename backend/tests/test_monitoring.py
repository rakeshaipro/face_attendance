"""Tests for Phase 8 monitoring + retention jobs (SRS §3.11, §3.12.3–3.12.6)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import SNAPSHOT_DIR
from app.core.enums import EVENT_STORAGE_LOW, CameraStatus
from app.db import SessionLocal
from app.models import AttendanceLog, Employee, SystemLog
from app.services import monitoring as monitoring_svc
from sqlalchemy import select


def _set(db, key: str, value: str) -> None:
    from app.core.settings_store import set_value

    set_value(db, key, value)


def _make_employee(db) -> str:
    eid = uuid.uuid4().hex
    db.add(Employee(id=eid, employee_id=f"O-{eid[:6]}", name="Test"))
    db.commit()
    return eid


def _make_attendance_log(db, *, employee_id: str, when: datetime) -> str:
    lid = uuid.uuid4().hex
    db.add(
        AttendanceLog(
            id=lid,
            machine_id="M1",
            location_name="Door",
            employee_id=employee_id,
            employee_name="Test",
            timestamp=when,
            confidence=0.9,
            snapshot_available=False,
        )
    )
    db.commit()
    return lid


def _make_snapshot(date_dir: str, filename: str, content: bytes = b"\xff\xd8fake") -> Path:
    d = SNAPSHOT_DIR / date_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(content)
    return p


class TestDiskSpaceMonitor:
    def test_no_alert_when_free_space_ok(self, client, admin_headers):
        with SessionLocal() as db:
            _set(db, "monitor.disk_threshold_mb", "1")
            fired = monitoring_svc.check_disk_space(db)
        assert fired is False

    def test_alert_fires_when_free_space_low(self, client, admin_headers):
        with SessionLocal() as db:
            _set(db, "monitor.disk_threshold_mb", "999999999")
            fired = monitoring_svc.check_disk_space(db)
        assert fired is True

    def test_alert_publishes_storage_low_event(self, client, admin_headers, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            "app.services.monitoring.bus.publish",
            lambda event, payload: captured.append((event, payload)),
        )
        with SessionLocal() as db:
            _set(db, "monitor.disk_threshold_mb", "999999999")
            monitoring_svc.check_disk_space(db)
        assert any(event == EVENT_STORAGE_LOW for event, _ in captured)


class TestRetentionPurge:
    def test_purge_attendance_logs_respects_retention_days(self, client, admin_headers):
        with SessionLocal() as db:
            _set(db, "retention.logs_days", "7")
            eid = _make_employee(db)
            old = _make_attendance_log(db, employee_id=eid, when=datetime.now(timezone.utc) - timedelta(days=10))
            new = _make_attendance_log(db, employee_id=eid, when=datetime.now(timezone.utc) - timedelta(days=1))
            deleted = monitoring_svc.purge_attendance_logs(db)
            assert deleted == 1
            assert db.get(AttendanceLog, old) is None
            assert db.get(AttendanceLog, new) is not None

    def test_purge_attendance_logs_zero_means_keep_forever(self, client, admin_headers):
        with SessionLocal() as db:
            _set(db, "retention.logs_days", "0")
            eid = _make_employee(db)
            old = _make_attendance_log(db, employee_id=eid, when=datetime.now(timezone.utc) - timedelta(days=365))
            deleted = monitoring_svc.purge_attendance_logs(db)
            assert deleted == 0
            assert db.get(AttendanceLog, old) is not None

    def test_purge_snapshots_deletes_old_date_dirs(self, client, admin_headers):
        # Use a unique old date dir so we don't collide with pre-existing snapshots.
        old_dir_name = "20240101"
        old_file = _make_snapshot(old_dir_name, "a.jpg")
        new_file = _make_snapshot(datetime.now(timezone.utc).strftime("%Y%m%d"), "b.jpg")
        try:
            with SessionLocal() as db:
                _set(db, "retention.snapshots_days", "1")
                deleted = monitoring_svc.purge_snapshots(db)
            assert deleted >= 1
            assert not old_file.exists()
            assert new_file.exists()
        finally:
            old_file.unlink(missing_ok=True)
            new_file.unlink(missing_ok=True)
            try:
                (SNAPSHOT_DIR / old_dir_name).rmdir()
            except FileNotFoundError:
                pass

    def test_purge_system_logs_deletes_old_rows(self, client, admin_headers):
        from app.services.system_log import write_system_log

        with SessionLocal() as db:
            _set(db, "system.log_retention_days", "7")
            old = write_system_log(db, event="old.event", message="old", severity="info")
            old_id = old.id
            # Manually backdate the row.
            db.execute(
                SystemLog.__table__.update()
                .where(SystemLog.id == old_id)
                .values(created_at=datetime.now(timezone.utc) - timedelta(days=10))
            )
            db.commit()
            new = write_system_log(db, event="new.event", message="new", severity="info")
            new_id = new.id
            deleted = monitoring_svc.purge_system_logs(db)
            assert deleted == 1
            # Re-query in a fresh transaction to avoid expired ORM state.
            assert db.execute(select(SystemLog).where(SystemLog.id == old_id)).scalar_one_or_none() is None
            assert db.execute(select(SystemLog).where(SystemLog.id == new_id)).scalar_one_or_none() is not None


class TestMonitoringAPI:
    def test_status_endpoint_requires_auth(self, client):
        assert client.get("/api/v1/monitoring/status").status_code == 401

    def test_status_endpoint_returns_job_times(self, client, admin_headers):
        from app.workers import scheduler as scheduler_worker
        from app.api.v1.monitoring import register_monitoring_jobs

        scheduler_worker.start()
        register_monitoring_jobs()
        try:
            r = client.get("/api/v1/monitoring/status", headers=admin_headers)
            assert r.status_code == 200
            data = r.json()["data"]
            assert "disk_job_next" in data
            assert "retention_job_next" in data
        finally:
            scheduler_worker.shutdown()


class TestCameraOfflineWatcher:
    def test_watcher_sends_alert_when_camera_offline_long_enough(self, monkeypatch):
        from app.engine.service import RecognitionService
        from app.workers import camera_watcher as cw
        from app.workers.camera_watcher import CameraOfflineWatcher

        watcher = CameraOfflineWatcher()
        # Simulate camera offline + last frame long ago by overriding the property getter.
        monkeypatch.setattr(
            RecognitionService,
            "camera_status",
            property(lambda _self: CameraStatus.OFFLINE),
        )
        monkeypatch.setattr(cw.service.stats, "last_frame_at", 1.0)
        sent: dict = {}

        def fake_send(db, minutes):
            sent["minutes"] = minutes
            return True

        monkeypatch.setattr(cw, "send_camera_offline_alert", fake_send)

        with SessionLocal() as db:
            _set(db, "smtp.camera_offline_minutes", "1")

        watcher._tick()
        assert sent.get("minutes") == 1
        assert watcher._alerted is True

    def test_watcher_resets_latch_when_camera_online(self, monkeypatch):
        from app.engine.service import RecognitionService
        from app.workers import camera_watcher as cw
        from app.workers.camera_watcher import CameraOfflineWatcher

        watcher = CameraOfflineWatcher()
        watcher._alerted = True
        monkeypatch.setattr(
            RecognitionService,
            "camera_status",
            property(lambda _self: CameraStatus.ONLINE),
        )
        watcher._tick()
        assert watcher._alerted is False


class TestSMTPService:
    def test_send_alert_disabled_returns_false(self, client):
        with SessionLocal() as db:
            _set(db, "smtp.enabled", "false")
            from app.services.smtp import send_alert

            ok = send_alert(db, subject="X", body="Y")
        assert ok is False

    def test_send_alert_missing_config_returns_false(self, client):
        with SessionLocal() as db:
            _set(db, "smtp.enabled", "true")
            _set(db, "smtp.host", "")
            _set(db, "smtp.from_addr", "")
            _set(db, "smtp.recipients", "")
            from app.services.smtp import send_alert

            ok = send_alert(db, subject="X", body="Y")
        assert ok is False

    def test_send_alert_uses_smtp(self, client, monkeypatch):
        captured: dict = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout=30):
                captured["host"] = host
                captured["port"] = port
                captured["timeout"] = timeout

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                captured["tls"] = True

            def login(self, user, password):
                captured["user"] = user
                captured["password"] = password

            def send_message(self, msg):
                captured["subject"] = msg["Subject"]
                captured["to"] = msg["To"]

        monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

        with SessionLocal() as db:
            _set(db, "smtp.enabled", "true")
            _set(db, "smtp.host", "smtp.example.com")
            _set(db, "smtp.port", "587")
            _set(db, "smtp.username", "user")
            _set(db, "smtp.password_encrypted", "pass")
            _set(db, "smtp.from_addr", "from@example.com")
            _set(db, "smtp.recipients", "a@example.com, b@example.com")
            from app.services.smtp import send_alert

            ok = send_alert(db, subject="Alert", body="Body")

        assert ok is True
        assert captured["host"] == "smtp.example.com"
        assert captured["subject"] == "Alert"
        assert "a@example.com" in captured["to"]

    def test_send_alert_logs_failure(self, client, admin_headers, monkeypatch):
        monkeypatch.setattr("smtplib.SMTP", lambda *args, **kwargs: (_ for _ in ()).throw(Exception("boom")))

        with SessionLocal() as db:
            _set(db, "smtp.enabled", "true")
            _set(db, "smtp.host", "smtp.example.com")
            _set(db, "smtp.port", "587")
            _set(db, "smtp.from_addr", "from@example.com")
            _set(db, "smtp.recipients", "a@example.com")
            from app.services.smtp import send_alert

            ok = send_alert(db, subject="Alert", body="Body")
        assert ok is False

        # A system log should record the failure.
        r = client.get("/api/v1/system/logs?event=smtp.failed", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["data"]["total"] >= 1
