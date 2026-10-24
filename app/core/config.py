"""
app/core/config.py
──────────────────
Centralised, 12-factor configuration loader.
All secrets and tunables are resolved from environment variables (or a local
.env file) so the runtime never depends on hard-coded values.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (two levels up from this file)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)


def _parse_deadline(raw: str | None) -> datetime:
    """Parse an ISO-format deadline string, falling back to 2030-01-01 UTC."""
    if not raw or not raw.strip():
        return datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(raw.strip())
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Settings:
    """Typed, singleton-style accessor for environment configuration."""

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./kotchy.db")

    # ── Codeforces API ────────────────────────────────────────
    CF_API_KEY: str = os.getenv("CF_API_KEY", "")
    CF_API_SECRET: str = os.getenv("CF_API_SECRET", "")

    # ── Task defaults ─────────────────────────────────────────
    DEFAULT_TASK_DEADLINE: datetime = _parse_deadline(os.getenv("DEFAULT_TASK_DEADLINE"))

    # ── Authentication & Security ──────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "kotchy-secret-key-development-icpc-2026")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    DEFAULT_PASSWORD: str = os.getenv("DEFAULT_PASSWORD", "12345678").strip() or "12345678"

    # ── Cache & Lifetimes (seconds) ───────────────────────────
    DEFAULT_CACHE_LIFETIME: int | None = (
        int(os.getenv("DEFAULT_CACHE_LIFETIME"))
        if os.getenv("DEFAULT_CACHE_LIFETIME") and os.getenv("DEFAULT_CACHE_LIFETIME").strip().isdigit()
        else None
    )
    CF_RATING_CACHE_LIFETIME: int = int(os.getenv("CF_RATING_CACHE_LIFETIME", "3600"))
    CF_SUBMISSIONS_CACHE_LIFETIME: int = int(os.getenv("CF_SUBMISSIONS_CACHE_LIFETIME", "30"))
    CF_CONTEST_PROBLEMS_CACHE_LIFETIME: int | None = (
        int(os.getenv("CF_CONTEST_PROBLEMS_CACHE_LIFETIME"))
        if os.getenv("CF_CONTEST_PROBLEMS_CACHE_LIFETIME") and os.getenv("CF_CONTEST_PROBLEMS_CACHE_LIFETIME").strip().isdigit()
        else None
    )

    # ── Debug ─────────────────────────────────────────────────
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")


settings = Settings()
