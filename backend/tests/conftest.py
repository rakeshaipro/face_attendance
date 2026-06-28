"""Pytest fixtures.

- Uses a file-based SQLite (FA_DATABASE_URL) on a stable path.
- Seeds system_settings defaults + an admin + a readonly API key once.
- FA_AUTOSTART_ENGINE=false so no real camera is required.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Configure env BEFORE importing the app.
os.environ.setdefault("FA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("FA_AUTOSTART_ENGINE", "false")
_TMP_DB = Path(__file__).resolve().parent / "_test.db"
os.environ["FA_DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
if _TMP_DB.exists():
    _TMP_DB.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def admin_key() -> str:
    return _KEYS["admin"]


@pytest.fixture(scope="session")
def readonly_key() -> str:
    return _KEYS["readonly"]


@pytest.fixture()
def client() -> TestClient:
    return _CLIENT


@pytest.fixture()
def admin_headers(admin_key) -> dict[str, str]:
    return {"X-API-Key": admin_key}


@pytest.fixture()
def ro_headers(readonly_key) -> dict[str, str]:
    return {"X-API-Key": readonly_key}


# --- Module-level singletons (built once per session) ---------------------
_KEYS: dict[str, str] = {}
_CLIENT: TestClient  # type: ignore[assignment]


def _bootstrap() -> None:
    from app.core.security import generate_api_key, hash_api_key
    from app.db import Base, SessionLocal, engine
    from app.engine.defaults import DEFAULTS
    from app.models import ApiKey, SystemSetting  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    admin_plain = generate_api_key()
    ro_plain = generate_api_key()
    with SessionLocal() as db:
        for key, value, _desc in DEFAULTS:
            db.add(SystemSetting(key=key, value=value))
        db.add(
            ApiKey(
                id="admin-key-id",
                label="Admin",
                key_hash=hash_api_key(admin_plain),
                key_prefix=admin_plain[:8],
                scope="admin",
                is_active=True,
            )
        )
        db.add(
            ApiKey(
                id="ro-key-id",
                label="Reader",
                key_hash=hash_api_key(ro_plain),
                key_prefix=ro_plain[:8],
                scope="readonly",
                is_active=True,
            )
        )
        db.commit()

    _KEYS["admin"] = admin_plain
    _KEYS["readonly"] = ro_plain

    global _CLIENT
    from app.main import app

    _CLIENT = TestClient(app)


_bootstrap()
