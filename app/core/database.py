"""
app/core/database.py
────────────────────
Database engine creation, session management, and table initialisation.
Supports both SQLite (local dev) and PostgreSQL (production) via DATABASE_URL.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

# ── Engine ────────────────────────────────────────────────────
_connect_args: dict = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=_connect_args,
)


# ── Session helper ────────────────────────────────────────────
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session for FastAPI dependencies.

    Commits on successful completion, rolls back on unhandled exception,
    and always closes the session.
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


session_scope = contextmanager(get_session)


# ── Table creation ───────────────────────────────────────────
def init_db(target_engine=None) -> None:
    """Create all tables defined by SQLModel metadata."""
    eng = target_engine or engine
    SQLModel.metadata.create_all(eng)




