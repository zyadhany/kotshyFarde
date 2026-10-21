"""
app/models/task.py
──────────────────
ORM model for the ``tasks`` table.
Uses Single-Table Inheritance via ``task_type`` discriminator and a flexible
JSON ``config`` column.  See docs/schema.md §2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlmodel import Column, Field, SQLModel
from sqlalchemy import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task(SQLModel, table=True):
    """Assignable task definition with pluggable JSON configuration."""

    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=150, nullable=False)
    description: Optional[str] = Field(default=None)

    # Discriminator: CF_SHEET | CF_CONTEST | VJUDGE_CONTEST | MANUAL
    task_type: str = Field(max_length=50, nullable=False)

    # Flexible payload — stored as JSON text in SQLite, native JSONB in PG
    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    created_at: datetime = Field(default_factory=_utcnow)
