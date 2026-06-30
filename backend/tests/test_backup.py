"""Tests for /api/v1/backup (SRS §3.10)."""
from __future__ import annotations

import io
import zipfile


def test_create_database_backup(client, admin_headers):
    r = client.post("/api/v1/backup", headers=admin_headers, json={"kind": "database"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["kind"] == "database"
    assert data["filename"].endswith(".zip")
    assert data["size_bytes"] > 0
    assert data["origin"] == "manual"


def test_create_full_backup_includes_images(client, admin_headers):
    # Seed a snapshot image so the full backup has something to include.
    from app.config import SNAPSHOT_DIR
    (SNAPSHOT_DIR / "20260101").mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / "20260101" / "test.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

    r = client.post("/api/v1/backup", headers=admin_headers, json={"kind": "full"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["kind"] == "full"

    # Download + verify ZIP contents include the DB and the snapshot tree.
    dl = client.get(f"/api/v1/backup/{data['id']}", headers=admin_headers)
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    names = zf.namelist()
    assert "face_attendance.db" in names
    assert any(n.startswith("snapshots/") for n in names)

    # cleanup
    (SNAPSHOT_DIR / "20260101" / "test.jpg").unlink(missing_ok=True)


def test_list_and_delete(client, admin_headers):
    create = client.post("/api/v1/backup", headers=admin_headers, json={"kind": "database"})
    bid = create.json()["data"]["id"]

    listed = client.get("/api/v1/backup", headers=admin_headers).json()["data"]
    assert any(b["id"] == bid for b in listed)

    deleted = client.delete(f"/api/v1/backup/{bid}", headers=admin_headers)
    assert deleted.status_code == 200
    listed2 = client.get("/api/v1/backup", headers=admin_headers).json()["data"]
    assert all(b["id"] != bid for b in listed2)


def test_restore_requires_confirm(client, admin_headers):
    # Create a valid backup, then try to restore without confirm.
    create = client.post("/api/v1/backup", headers=admin_headers, json={"kind": "database"})
    bid = create.json()["data"]["id"]
    dl = client.get(f"/api/v1/backup/{bid}", headers=admin_headers)

    r = client.post(
        "/api/v1/backup/restore?confirm=false",
        headers=admin_headers,
        files={"file": ("b.zip", io.BytesIO(dl.content), "application/zip")},
    )
    assert r.status_code == 400


def test_restore_valid_zip_overwrites_db(client, admin_headers):
    # Seed a marker row that proves the DB gets replaced.
    from app.db import SessionLocal
    from app.models import SystemSetting

    try:
        with SessionLocal() as db:
            db.add(SystemSetting(key="__restore_marker__", value="BEFORE"))
            db.commit()

        create = client.post("/api/v1/backup", headers=admin_headers, json={"kind": "database"})
        bid = create.json()["data"]["id"]

        # Add the marker AFTER the backup so the backup doesn't contain it.
        with SessionLocal() as db:
            db.add(SystemSetting(key="__restore_marker2__", value="AFTER"))
            db.commit()

        dl = client.get(f"/api/v1/backup/{bid}", headers=admin_headers)

        r = client.post(
            "/api/v1/backup/restore?confirm=true",
            headers=admin_headers,
            files={"file": ("b.zip", io.BytesIO(dl.content), "application/zip")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["restored"] is True

        # The post-backup marker should be gone (DB was overwritten by the
        # backup, which predates it). Read directly via sqlite3 to bypass
        # any pool/page caching that might linger in the SQLAlchemy engine.
        import sqlite3 as _sqlite3
        _con = _sqlite3.connect("data/face_attendance.db")
        try:
            gone = _con.execute(
                "SELECT 1 FROM system_settings WHERE key = ?", ("__restore_marker2__",)
            ).fetchone()
            assert gone is None, f"post-restore marker should be gone, found row: {gone}"
        finally:
            _con.close()
    finally:
        # Clean up the BEFORE marker so the test is idempotent across runs.
        from app.db import SessionLocal as _SL
        with _SL() as _db:
            _db.execute(
                SystemSetting.__table__.delete().where(
                    SystemSetting.key.in_(("__restore_marker__", "__restore_marker2__"))
                )
            )
            _db.commit()


def test_restore_invalid_zip_rejected(client, admin_headers):
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("not_a_db.txt", "garbage")
    fake.seek(0)
    r = client.post(
        "/api/v1/backup/restore?confirm=true",
        headers=admin_headers,
        files={"file": ("b.zip", fake, "application/zip")},
    )
    assert r.status_code == 400


def test_schedule_config_roundtrip(client, admin_headers):
    r = client.put(
        "/api/v1/backup/schedule",
        headers=admin_headers,
        json={"enabled": True, "frequency": "weekly", "time": "03:30", "max_scheduled": 7},
    )
    assert r.status_code == 200
    got = client.get("/api/v1/backup/schedule", headers=admin_headers).json()["data"]
    assert got["enabled"] is True
    assert got["frequency"] == "weekly"
    assert got["time"] == "03:30"
    assert got["max_scheduled"] == 7

    from app.workers import scheduler as scheduler_worker
    assert scheduler_worker.get_scheduler().get_job("backup-scheduled") is not None

    # Disable → jobs removed.
    client.put(
        "/api/v1/backup/schedule",
        headers=admin_headers,
        json={"enabled": False, "frequency": "weekly", "time": "03:30", "max_scheduled": 7},
    )
    assert scheduler_worker.get_scheduler().get_job("backup-scheduled") is None


def test_prune_scheduled(client, admin_headers):
    from app.db import SessionLocal
    from app.services import backup as backup_svc
    from app.core.settings_store import set_value

    with SessionLocal() as db:
        set_value(db, "backup.max_scheduled", "2")
        # Create 4 scheduled backups (older first by sleeping isn't reliable;
        # create_backup uses utcnow so they're ordered by creation time).
        for _ in range(4):
            backup_svc.create_backup(db, kind="database", origin="scheduled")
        n = backup_svc.prune_scheduled(db)
        assert n == 2
        remaining = backup_svc.list_backups(db)
        scheduled = [b for b in remaining if b.is_scheduled]
        # Only the 2 newest scheduled backups remain.
        recent_scheduled = [b for b in scheduled if b.origin == "scheduled"]
        assert len(recent_scheduled) <= 2
