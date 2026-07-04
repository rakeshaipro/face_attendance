"""Pytest fixtures.

- Uses PostgreSQL (FA_DATABASE_URL) with pgvector extension.
- Seeds system_settings defaults + an admin + a readonly API key once.
- FA_AUTOSTART_ENGINE=false so no real camera is required.
"""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Configure env BEFORE importing the app.
os.environ.setdefault("FA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("FA_AUTOSTART_ENGINE", "false")
os.environ.setdefault("FA_DATABASE_URL", "postgresql+psycopg://postgres:q1w2e3r4@localhost:5433/face_attendance_test")


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
    import sqlalchemy as sa

    from app.core.security import generate_api_key, hash_api_key
    from app.db import Base, SessionLocal, engine
    from app.engine.defaults import DEFAULTS
    from app.models import ApiKey, SystemSetting  # noqa: F401

    # Create pgvector extension before creating tables that use Vector type.
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

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
