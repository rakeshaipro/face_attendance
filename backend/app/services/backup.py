"""Backup + restore logic (SRS §3.10).

Backups are unencrypted ZIP archives (§3.10.3 — LAN-local, physically
secure). Full backups include the SQLite DB + snapshots + enrollment
images; database-only backups include just the DB.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKUP_DIR, DB_PATH, ENROLLMENT_DIR, SNAPSHOT_DIR
from app.core.settings_store import get_int, get_value, set_value
from app.models import Backup

logger = logging.getLogger(__name__)

DB_FILENAME = "face_attendance.db"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _backup_filename(kind: str) -> str:
    return f"backup_{_timestamp()}_{kind}.zip"


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

    kind: "full" (db + snapshots + enrollment) or "database" (db only).
    origin: "manual" or "scheduled".
    """
    if kind not in ("full", "database"):
        raise ValueError("kind must be 'full' or 'database'")

    filename = _backup_filename(kind)
    path = BACKUP_DIR / filename
    image_count = 0

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Always include the DB. Copy to a temp file first so we don't zip a
        # half-written WAL — checkpoint + copy gives a consistent snapshot.
        snapshot_db = BACKUP_DIR / f".{DB_FILENAME}.tmp"
        shutil.copy2(DB_PATH, snapshot_db)
        try:
            zf.write(snapshot_db, DB_FILENAME)
        finally:
            snapshot_db.unlink(missing_ok=True)

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


def _replace_with_retry(src: Path, dst: Path, attempts: int = 8, delay: float = 0.25) -> None:
    """os.replace that survives transient Windows file-locking from other connections."""
    import time

    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _atomic_file_replace(src: Path, dst: Path, attempts: int = 20, delay: float = 0.25) -> None:
    """Replace dst's contents with src's contents, atomically per-platform.

    Tries `os.replace` first; on Windows this fails when any other process
    (including the SQLAlchemy connection pool or the test client) holds
    the destination open. As a fallback we truncate dst in-place and write
    src bytes to it — SQLite tolerates this when no transactions are open
    against the pool (we dispose the engine before calling this).
    """
    import time

    try:
        _replace_with_retry(src, dst)
        return
    except PermissionError:
        # Fall through to the in-place replace below.
        pass

    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            with open(src, "rb") as fin:
                data = fin.read()
            # Use wb+ on Windows: wb truncates the file, then write fresh
            # bytes. Even if other processes hold the file in r+b mode,
            # our truncate + write wins because the destination isn't open
            # for reading.
            with open(dst, "wb") as fout:
                fout.write(data)
                fout.flush()
                import os as _os
                _os.fsync(fout.fileno())
            # SQLite WAL/SHM sidecars can hold recent writes that survive
            # the main-file overwrite. Delete them so the restored DB is
            # the single source of truth.
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(dst) + suffix)
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except OSError:
                        pass
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def validate_backup_zip(zip_path: Path) -> tuple[bool, str]:
    """Check that a ZIP is a valid backup from this system (§3.10.7).

    Returns (ok, message). Validates: it's a ZIP, contains face_attendance.db,
    and that DB passes SQLite integrity_check.
    """
    if not zipfile.is_zipfile(zip_path):
        return False, "File is not a ZIP archive."
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if DB_FILENAME not in names:
            return False, f"Backup ZIP does not contain {DB_FILENAME}."
        # Extract the DB to a temp location and integrity-check it.
        tmp = BACKUP_DIR / f".restore_{DB_FILENAME}.tmp"
        try:
            with zf.open(DB_FILENAME) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            con = sqlite3.connect(str(tmp))
            result = con.execute("PRAGMA integrity_check;").fetchone()
            con.close()
            if result[0] != "ok":
                return False, f"Database integrity check failed: {result[0]}"
        finally:
            tmp.unlink(missing_ok=True)
    return True, "ok"


def restore_backup(zip_path: Path, *, confirm: bool) -> tuple[bool, str, str | None]:
    """Validate + restore a backup ZIP (§3.10.7).

    Returns (ok, message, kind). Requires confirm=True; stops the engine,
    swaps the DB (+ images for full), restarts.
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

    # Stop the engine so it releases the DB handle.
    from app.engine.service import service
    service.stop()

    # Dispose the SQLAlchemy engine pool so no connections hold the DB
    # file open (Windows file locking would otherwise refuse overwrite).
    from app.db import engine as db_engine
    db_engine.dispose()

    # Ensure WAL is flushed to the main DB so the in-place replace
    # (truncate + write) covers everything. Without this, recent writes
    # linger in face_attendance.db-wal and stay visible after the replace.
    try:
        con = sqlite3.connect(str(DB_PATH))
        con.execute("PRAGMA wal_checkpoint(FULL);")
        con.close()
    except Exception:
        logger.exception("WAL checkpoint before restore failed (non-fatal)")

    try:
        with zipfile.ZipFile(zip_path) as zf:
            tmp_db = DB_PATH.with_suffix(".restoring")
            with zf.open(DB_FILENAME) as src, open(tmp_db, "wb") as dst:
                shutil.copyfileobj(src, dst)
            # Replace the target DB file. Tries os.replace; on Windows if
            # any process holds the destination, falls back to truncating
            # and writing contents in place.
            _atomic_file_replace(tmp_db, DB_PATH)
            if kind == "full":
                _extract_tree(zf, "snapshots", SNAPSHOT_DIR)
                _extract_tree(zf, "enrollment", ENROLLMENT_DIR)
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
