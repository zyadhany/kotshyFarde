"""
app/schemas
───────────
Pydantic / SQLModel schemas for request bodies and API responses.
"""

from app.schemas.student import StudentCreate, StudentRead, StudentUpdate
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
    AssignmentWithTaskRead,
)

__all__ = [
    "StudentCreate",
    "StudentRead",
    "StudentUpdate",
    "TaskCreate",
    "TaskRead",
    "TaskUpdate",
    "AssignmentCreate",
    "AssignmentRead",
    "AssignmentUpdate",
    "AssignmentWithTaskRead",
]
