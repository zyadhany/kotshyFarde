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


# ── Table creation, migration & seeding ───────────────────────
def _migrate_users_schema(target_engine=None) -> None:
    """Ensure users table has hashed_password and is_active columns in SQLite."""
    from sqlalchemy import text
    eng = target_engine or engine

    try:
        with eng.begin() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = {row[1] for row in result.fetchall()}
            if not cols:
                return
            if "password_hash" in cols and "hashed_password" not in cols:
                conn.execute(text("ALTER TABLE users RENAME COLUMN password_hash TO hashed_password"))
            elif "hashed_password" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255) DEFAULT '' NOT NULL"))
            if "is_active" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
    except Exception:
        pass


def seed_default_coach(session: Session) -> None:
    """Seed the default coach account if no coach exists."""
    from sqlmodel import select
    from app.core.security import get_password_hash
    from app.models.user import User

    # Only upgrade if needed (avoid hashing every time on startup)
    users = session.exec(select(User)).all()
    modified = False
    for u in users:
        if not u.hashed_password or not (u.hashed_password.startswith("$2b$") or u.hashed_password.startswith("$2a$")):
            default_pwd = (getattr(settings, "DEFAULT_PASSWORD", None) or "12345678").strip() or "12345678"
            u.hashed_password = get_password_hash(u.hashed_password or default_pwd)
            session.add(u)
            modified = True
    if modified:
        session.commit()

    coach = session.exec(
        select(User).where((User.role == "coach") | (User.role == "coash"))
    ).first()

    if not coach:
        default_coach = User(
            username="coach",
            email="coach@kotchy.dev",
            hashed_password=get_password_hash("adminpassword"),
            role="coach",
            is_active=True,
        )
        session.add(default_coach)
        session.commit()


def init_db(target_engine=None) -> None:
    """Create all tables defined by SQLModel metadata, migrate, and seed coach."""
    eng = target_engine or engine
    SQLModel.metadata.create_all(eng)
    _migrate_users_schema(eng)
    with Session(eng) as session:
        seed_default_coach(session)


