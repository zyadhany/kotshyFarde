"""
app/schemas
───────────
Pydantic / SQLModel schemas for request bodies and API responses.
"""

from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
    AssignmentWithTaskRead,
)

__all__ = [
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "TaskCreate",
    "TaskRead",
    "TaskUpdate",
    "AssignmentCreate",
    "AssignmentRead",
    "AssignmentUpdate",
    "AssignmentWithTaskRead",
]
