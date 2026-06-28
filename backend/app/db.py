"""Database engine, session factory, declarative Base, and the FastAPI
dependency that yields a session per request.

SQLAlchemy 2.0 sync style. SQLite is used per SRS §5 / §3.10.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# `check_same_thread=False` is required because the recognition engine
# runs on its own background thread and shares the engine. Write access
# is serialised through the GIL for small SQLite transactions.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    future=True,
)


# Enable SQLite foreign-key enforcement so ONDELETE CASCADE works
# (§3.2.6 — deleting an employee removes their embeddings + logs).
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a session, close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
