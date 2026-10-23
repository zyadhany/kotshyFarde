"""
app/models/user.py
──────────────────
ORM model for the ``users`` table.
See docs/schema.md §1 for the full column specification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """Core profile + competitive-programming handles and role for a user."""

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(max_length=50, nullable=False, unique=True, index=True)
    email: str = Field(max_length=100, nullable=False, unique=True, index=True)
    hashed_password: str = Field(max_length=255, nullable=False)
    role: str = Field(default="student", max_length=20, nullable=False)  # "coach" or "student"
    is_active: bool = Field(default=True, nullable=False)

    phone_number: Optional[str] = Field(default=None, max_length=20)

    # ── Platform handles ──────────────────────────────────────
    cf_handle: Optional[str] = Field(default=None, max_length=50, index=True)
    vjudge_handle: Optional[str] = Field(default=None, max_length=50)
    atcoder_handle: Optional[str] = Field(default=None, max_length=50)
    cses_id: Optional[str] = Field(default=None, max_length=50)

    linkedin_url: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)

    # ── Timestamps ────────────────────────────────────────────
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # ── Role Helper Methods ───────────────────────────────────
    def is_coach(self) -> bool:
        """Check if user has coach or administrator privileges."""
        return self.role.strip().lower() in ("coach", "coash", "admin")

    def is_student(self) -> bool:
        """Check if user is a student."""
        return not self.is_coach()

    # ── Backwards Compatibility Alias for password_hash ───────
    @property
    def password_hash(self) -> str:
        return self.hashed_password

    @password_hash.setter
    def password_hash(self, value: str) -> None:
        self.hashed_password = value
