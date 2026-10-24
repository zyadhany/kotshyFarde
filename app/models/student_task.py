"""
app/models/student_task.py
──────────────────────────
ORM model for the ``student_tasks`` junction table.
Manages per-student scheduling, deadlines, status tracking, and checker
output.  See docs/schema.md §3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


class StudentTask(SQLModel, table=True):
    """Many-to-many association between students and tasks with scheduling metadata."""

    __tablename__ = "student_tasks"
    __table_args__ = (
        UniqueConstraint("student_id", "task_id", name="uq_student_task"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    task_id: int = Field(foreign_key="tasks.id", nullable=False, index=True)

    start_date: datetime = Field(nullable=False)
    deadline: datetime = Field(nullable=False)

    # Workflow state: pending | in_progress | completed | late
    status: str = Field(default="pending", max_length=20)

    # Structured checker output (populated by domain checkers)
    checker_result: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    completed_at: Optional[datetime] = Field(default=None)
