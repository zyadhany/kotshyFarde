"""
app/schemas/student.py
──────────────────────
Schemas for Student creation, update, and response serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class StudentBase(BaseModel):
    username: str
    email: str
    phone_number: Optional[str] = None
    cf_handle: Optional[str] = None
    vjudge_handle: Optional[str] = None
    atcoder_handle: Optional[str] = None
    cses_id: Optional[str] = None
    linkedin_url: Optional[str] = None
    description: Optional[str] = None


class StudentCreate(StudentBase):
    password_hash: str = "placeholder"


class StudentUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password_hash: Optional[str] = None
    phone_number: Optional[str] = None
    cf_handle: Optional[str] = None
    vjudge_handle: Optional[str] = None
    atcoder_handle: Optional[str] = None
    cses_id: Optional[str] = None
    linkedin_url: Optional[str] = None
    description: Optional[str] = None


class StudentRead(StudentBase):
    id: int
    password_hash: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
