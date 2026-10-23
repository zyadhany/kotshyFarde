"""
app/schemas/user.py
───────────────────
Schemas for User creation, update, authentication, and response serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    username: str
    email: str
    role: str = "student"  # "coach" or "student"
    is_active: bool = True
    phone_number: Optional[str] = None
    cf_handle: Optional[str] = None
    vjudge_handle: Optional[str] = None
    atcoder_handle: Optional[str] = None
    cses_id: Optional[str] = None
    linkedin_url: Optional[str] = None
    description: Optional[str] = None


class UserCreate(UserBase):
    password: Optional[str] = None
    hashed_password: Optional[str] = None
    password_hash: Optional[str] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    hashed_password: Optional[str] = None
    password_hash: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    phone_number: Optional[str] = None
    cf_handle: Optional[str] = None
    vjudge_handle: Optional[str] = None
    atcoder_handle: Optional[str] = None
    cses_id: Optional[str] = None
    linkedin_url: Optional[str] = None
    description: Optional[str] = None


class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class LoginResponse(BaseModel):
    success: bool = True
    username: str
    role: str
    redirect_url: str
    access_token: str
