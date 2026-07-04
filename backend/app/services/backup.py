"""Backup + restore logic (SRS §3.10).

Backups are unencrypted ZIP archives (§3.10.3 — LAN-local, physically
secure). Full backups include a pg_dump + snapshots + enrollment images;
database-only backups include just the pg_dump.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import BACKUP_DIR, ENROLLMENT_DIR, SNAPSHOT_DIR, settings
from app.core.settings_store import get_int, get_value, set_value
from app.models import Backup

logger = logging.getLogger(__name__)

DB_FILENAME = "face_attendance.sql"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _backup_filename(kind: str) -> str:
    return f"backup_{_timestamp()}_{kind}.zip"


def _run_pg_dump(dest: Path) -> None:
    """Run pg_dump against the configured database URL to produce a plain SQL file."""
    url = settings.database_url
    # Parse postgresql://user:pass@host:port/dbname
    # Strip the "postgresql://" or "postgresql+psycopg2://" prefix.
    clean = url.split("://", 1)[1]
    userpass, rest = clean.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport, dbname = rest.rsplit("/", 1)
    env = {**os.environ, "PGPASSWORD": password}
    subprocess.run(
        ["pg_dump", "--host", hostport.split(":")[0], "--port", hostport.split(":")[1],
         "--username", user, "--dbname", dbname, "--format=plain",
         "--no-owner", "--no-privileges", "--file", str(dest)],
        check=True, env=env, capture_output=True,
    )


def _add_dir_to_zip(zf: zipfile.ZipFile, src: Path, arcname: str) -> int:
    """Recursively add a directory tree to the ZIP. Returns file count."""
    if not src.exists():
        return 0
    count = 0
    for path in sorted(src.rglob("*")):
        if path.is_file():
            zf.write(path, str(Path(arcname) / path.relative_to(src)))
            count += 1
    return count


def create_backup(db: Session, *, kind: str, origin: str = "manual") -> Backup:
    """Create a backup ZIP and record its row.

    kind: "full" (pg_dump + snapshots + enrollment) or "database" (dump only).
    origin: "manual" or "scheduled".
    """
    if kind not in ("full", "database"):
        raise ValueError("kind must be 'full' or 'database'")

    filename = _backup_filename(kind)
    path = BACKUP_DIR / filename
    image_count = 0

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Use pg_dump for a consistent plain-text SQL backup.
        dump_tmp = BACKUP_DIR / f".{DB_FILENAME}.tmp"
        try:
            _run_pg_dump(dump_tmp)
            zf.write(dump_tmp, DB_FILENAME)
        finally:
            dump_tmp.unlink(missing_ok=True)

        if kind == "full":
            image_count += _add_dir_to_zip(zf, SNAPSHOT_DIR, Path("snapshots"))
            image_count += _add_dir_to_zip(zf, ENROLLMENT_DIR, Path("enrollment"))

    size = path.stat().st_size
    row = Backup(
        # Unique even when multiple backups are created in the same second.
        id=f"{filename.rsplit('.', 1)[0]}_{uuid.uuid4().hex[:6]}",
        kind=kind,
        filename=filename,
        size_bytes=size,
        origin=origin,
        is_scheduled=(origin == "scheduled"),
        note=f"{image_count} images" if kind == "full" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_backups(db: Session) -> list[Backup]:
    return db.execute(select(Backup).order_by(Backup.created_at.desc())).scalars().all()


def get_backup_path(db: Session, backup_id: str) -> Path | None:
    row = db.get(Backup, backup_id)
    if row is None:
        return None
    return BACKUP_DIR / row.filename


def delete_backup(db: Session, backup_id: str) -> bool:
    row = db.get(Backup, backup_id)
    if row is None:
        return False
    (BACKUP_DIR / row.filename).unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    return True


def validate_backup_zip(zip_path: Path) -> tuple[bool, str]:
    """Check that a ZIP is a valid backup from this system (§3.10.7).

    Returns (ok, message). Validates: it's a ZIP, contains the SQL dump file,
    and that the dump is non-empty.
    """
    if not zipfile.is_zipfile(zip_path):
        return False, "File is not a ZIP archive."
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if DB_FILENAME not in names:
            return False, f"Backup ZIP does not contain {DB_FILENAME}."
        # Verify the dump file is non-empty.
        info = zf.getinfo(DB_FILENAME)
        if info.file_size == 0:
            return False, "Database dump file is empty."
    return True, "ok"


def restore_backup(zip_path: Path, *, confirm: bool) -> tuple[bool, str, str | None]:
    """Validate + restore a backup ZIP (§3.10.7).

    Returns (ok, message, kind). Requires confirm=True; stops the engine,
    restores the pg_dump SQL (+ images for full), restarts.
    """
    if not confirm:
        return False, "Confirmation required (confirm=true) — current data will be overwritten.", None

    ok, msg = validate_backup_zip(zip_path)
    if not ok:
        return False, msg, None

    # Determine kind from ZIP contents.
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        kind = "full" if any(n.startswith("snapshots/") for n in names) else "database"

    # Stop the engine so it releases DB handles.
    from app.engine.service import service
    service.stop()

    # Dispose the SQLAlchemy engine pool.
    from app.db import engine as db_engine
    db_engine.dispose()

    try:
        # Drop and recreate the schema, then pipe the dump into psql.
        dump_tmp = BACKUP_DIR / f".restore_{DB_FILENAME}.tmp"
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(DB_FILENAME) as src, open(dump_tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)

        _run_psql_restore(dump_tmp, clean=True)
        dump_tmp.unlink(missing_ok=True)

        if kind == "full":
            with zipfile.ZipFile(zip_path) as zf:
                _extract_tree(zf, "snapshots", SNAPSHOT_DIR)
                _extract_tree(zf, "enrollment", ENROLLMENT_DIR)
    except Exception as exc:
        dump_tmp.unlink(missing_ok=True)
        raise exc
    finally:
        # Restart the engine.
        try:
            from app.db import SessionLocal
            with SessionLocal() as db:
                camera_url = get_value(db, "device.camera_url")
            service.start(camera_url)
        except Exception:
            logger.exception("engine failed to restart after restore")

    return True, f"Restored {kind} backup; engine restarted.", kind


def _run_psql_restore(sql_file: Path, *, clean: bool = False) -> None:
    """Pipe a pg_dump SQL file into psql. If clean=True, drops existing tables first."""
    url = settings.database_url
    clean_url = url.split("://", 1)[1]
    userpass, rest = clean_url.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport, dbname = rest.rsplit("/", 1)
    env = {**os.environ, "PGPASSWORD": password}

    if clean:
        # Terminate other connections and drop public schema, then recreate.
        subprocess.run(
            ["psql", "--host", hostport.split(":")[0], "--port", hostport.split(":")[1],
             "--username", user, "--dbname", dbname, "-c",
             "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
            check=True, env=env, capture_output=True,
        )

    with open(sql_file, "r") as f:
        subprocess.run(
            ["psql", "--host", hostport.split(":")[0], "--port", hostport.split(":")[1],
             "--username", user, "--dbname", dbname, "--set", "ON_ERROR_STOP=1",
             "--file", str(sql_file)],
            check=True, env=env, capture_output=True, stdin=f,
        )


def _extract_tree(zf: zipfile.ZipFile, arcname: str, dest: Path) -> None:
    """Extract a directory tree from the ZIP, clearing the destination first."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        if info.filename.startswith(f"{arcname}/") and not info.is_dir():
            rel = info.filename[len(arcname) + 1:]
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def prune_scheduled(db: Session) -> int:
    """Delete oldest scheduled backups beyond max_scheduled (§3.10.9).

    Returns the number deleted.
    """
    max_keep = max(1, get_int(db, "backup.max_scheduled"))
    rows = (
        db.execute(
            select(Backup).where(Backup.is_scheduled.is_(True)).order_by(Backup.created_at.desc())
        )
        .scalars()
        .all()
    )
    if len(rows) <= max_keep:
        return 0
    deleted = 0
    for row in rows[max_keep:]:
        (BACKUP_DIR / row.filename).unlink(missing_ok=True)
        db.delete(row)
        deleted += 1
    db.commit()
    return deleted


def get_schedule_config(db: Session) -> dict:
    return {
        "enabled": _as_bool(get_value(db, "backup.schedule_enabled")),
        "frequency": get_value(db, "backup.schedule_frequency") or "daily",
        "time": get_value(db, "backup.schedule_time") or "02:00",
        "max_scheduled": max(1, get_int(db, "backup.max_scheduled")),
    }


def update_schedule_config(db: Session, config: dict) -> dict:
    set_value(db, "backup.schedule_enabled", str(config["enabled"]).lower())
    set_value(db, "backup.schedule_frequency", config.get("frequency", "daily"))
    set_value(db, "backup.schedule_time", config.get("time", "02:00"))
    set_value(db, "backup.max_scheduled", str(config.get("max_scheduled", 14)))
    return get_schedule_config(db)


def _as_bool(s: str) -> bool:
    return (s or "").strip().lower() in {"1", "true", "yes", "on"}
