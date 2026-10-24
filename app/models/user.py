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

    # ── Codeforces Rating & Rank Helpers ──────────────────────
    def get_cf_rating(self) -> Optional[int]:
        """Return the user's cached Codeforces rating."""
        if not self.cf_handle:
            return None
        from app.services.codeforces_api import get_user_rating
        return get_user_rating(self.cf_handle)

    def get_cf_info(self) -> Optional[dict]:
        """Return the user's cached Codeforces profile info."""
        if not self.cf_handle:
            return None
        from app.services.codeforces_api import get_user_info
        return get_user_info(self.cf_handle)

    @property
    def cf_rating(self) -> Optional[int]:
        """Return current Codeforces rating."""
        return self.get_cf_rating()

    @property
    def cf_max_rating(self) -> Optional[int]:
        """Return all-time max Codeforces rating."""
        info = self.get_cf_info()
        return info.get("maxRating") if info else None

    @property
    def cf_rank(self) -> str:
        """Return current Codeforces rank title (e.g. 'Master', 'Pupil')."""
        info = self.get_cf_info()
        if info and info.get("rank"):
            return str(info["rank"]).strip().title()
        from app.services.codeforces_api import get_rating_title
        return get_rating_title(self.cf_rating)

    @property
    def cf_max_rank(self) -> str:
        """Return all-time max Codeforces rank title."""
        info = self.get_cf_info()
        if info and info.get("maxRank"):
            return str(info["maxRank"]).strip().title()
        from app.services.codeforces_api import get_rating_title
        return get_rating_title(self.cf_max_rating or self.cf_rating)

    @property
    def cf_rating_class(self) -> str:
        """Return the Codeforces CSS rating class for the user."""
        from app.services.codeforces_api import get_rating_class
        return get_rating_class(self.get_cf_rating())

    @property
    def cf_max_rating_class(self) -> str:
        """Return the Codeforces CSS rating class for max rating."""
        from app.services.codeforces_api import get_rating_class
        return get_rating_class(self.cf_max_rating or self.get_cf_rating())

    @property
    def cf_rating_color(self) -> str:
        """Return the Codeforces hex color for the user."""
        from app.services.codeforces_api import get_rating_color
        return get_rating_color(self.get_cf_rating())

    @property
    def cf_max_rating_color(self) -> str:
        """Return the Codeforces hex color for max rating."""
        from app.services.codeforces_api import get_rating_color
        return get_rating_color(self.cf_max_rating or self.get_cf_rating())

    @property
    def cf_rating_title(self) -> str:
        """Return the Codeforces rank title for the user."""
        return self.cf_rank

    @property
    def is_legendary(self) -> bool:
        """True if user is Legendary Grandmaster (rating >= 3000)."""
        r = self.get_cf_rating()
        return r is not None and r >= 3000

    @property
    def cf_title_photo(self) -> Optional[str]:
        """Return direct Codeforces title photo URL, normalized for codeforces.com."""
        info = self.get_cf_info()
        if not info:
            return None
        raw_url = info.get("titlePhoto") or info.get("avatar")
        return self._normalize_cf_photo_url(raw_url)

    @property
    def cf_avatar_url(self) -> Optional[str]:
        """Return direct Codeforces avatar URL, normalized for codeforces.com."""
        info = self.get_cf_info()
        if not info:
            return None
        raw_url = info.get("avatar") or info.get("titlePhoto")
        return self._normalize_cf_photo_url(raw_url)

    @staticmethod
    def _normalize_cf_photo_url(url: Optional[str]) -> Optional[str]:
        if not url or not str(url).strip():
            return None
        url = str(url).strip()
        if url.startswith("//"):
            url = f"https:{url}"
        elif url.startswith("/"):
            url = f"https://codeforces.com{url}"
        if "userpic.codeforces.org/" in url:
            url = url.replace("userpic.codeforces.org/", "codeforces.com/userpic/")
        return url

    # ── Backwards Compatibility Alias for password_hash ───────
    @property
    def password_hash(self) -> str:
        return self.hashed_password

    @password_hash.setter
    def password_hash(self, value: str) -> None:
        self.hashed_password = value
