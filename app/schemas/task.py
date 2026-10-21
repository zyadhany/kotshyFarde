"""
app/schemas/task.py
───────────────────
Schemas for Task creation, update, and response serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class TaskRead(TaskBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
