"""
app/schemas/assignment.py
─────────────────────────
Schemas for StudentTask (Assignment) creation, update, and response serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.task import TaskRead


class AssignmentCreate(BaseModel):
    student_id: int
    task_id: int
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None


class AssignmentRead(BaseModel):
    id: int
    student_id: int
    task_id: int
    start_date: datetime
    deadline: datetime
    status: str
    checker_result: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AssignmentBatchCreate(BaseModel):
    task_id: int
    student_ids: List[int]
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None


class AssignmentBatchResponse(BaseModel):
    success: bool
    assigned_count: int
    assignments: List[AssignmentRead]


class AssignmentUpdate(BaseModel):
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    status: Optional[str] = None
    checker_result: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None



class AssignmentWithTaskRead(AssignmentRead):
    task: Optional[TaskRead] = None
