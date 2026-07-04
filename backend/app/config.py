"""Application configuration loaded from environment / .env.

Operational secrets (encryption key, admin bootstrap key) live here.
All *business* configuration (machine_id, location, camera URL,
thresholds, cooldown, retention, SMTP, ...) is stored in the
`system_settings` table per SRS §6.4.1 and is editable at runtime
without restarting the server.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository layout helpers — resolved relative to this file.
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
ENROLLMENT_DIR = DATA_DIR / "enrollment"
BACKUP_DIR = DATA_DIR / "backups"
MODEL_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "face_attendance.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FA_",
        extra="ignore",
    )

    # --- Host / serving --------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Security --------------------------------------------------------
    # Fernet key used to encrypt camera stream credentials (§3.13.9).
    # Generate one with:  python -m app.cli gen-encryption-key
    encryption_key: SecretStr = Field(default="")

    # --- Database --------------------------------------------------------
    # PostgreSQL with pgvector (Docker). Override with FA_DATABASE_URL.
    # Uses the psycopg v3 driver (psycopg[binary]) for scram-sha-256 auth.
    database_url: str = "postgresql+psycopg://postgres:q1w2e3r4@localhost:5433/face_attendance"

    # --- Recognition engine ---------------------------------------------
    # Whether to autostart the recognition service when the app boots.
    # Disable in tests / when no camera is connected.
    autostart_engine: bool = True

    # --- API -------------------------------------------------------------
    api_prefix: str = "/api/v1"

    # --- CORS ------------------------------------------------------------
    # Comma-separated list of allowed origins for the admin dashboard.
    # The Vite dev server (http://localhost:5173) is allowed by default.
    cors_origins: str = "http://localhost:5173"


settings = Settings()

# Ensure runtime data directories exist (cheap; idempotent).
for _d in (DATA_DIR, SNAPSHOT_DIR, ENROLLMENT_DIR, BACKUP_DIR, MODEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)
