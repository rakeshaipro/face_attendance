"""Database engine, session factory, declarative Base, and the FastAPI
dependency that yields a session per request.

SQLAlchemy 2.0 sync style. PostgreSQL with pgvector for vector search.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    future=True,
)

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
