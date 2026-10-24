"""
app/api/students.py
───────────────────
CRUD endpoints for Student management (mapped to the User model).
Prefix: /students
Tags: ["Students"]
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.api.deps import require_coach
from app.api.users import create_user, delete_user, get_user, list_users, reset_password, update_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/api/students", tags=["Students"], dependencies=[Depends(require_coach)])


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_student_endpoint(
    student_in: UserCreate,
    session: Session = Depends(get_session),
) -> User:
    """Create a new student (user) with optional platform handles."""
    if not student_in.role:
        student_in.role = "student"
    return create_user(user_in=student_in, session=session)


@router.get("/", response_model=List[UserRead])
def list_students_endpoint(
    session: Session = Depends(get_session),
) -> List[User]:
    """Retrieve a list of all students."""
    return list_users(role="student", session=session)


@router.get("/{student_id}", response_model=UserRead)
def get_student_endpoint(
    student_id: int,
    session: Session = Depends(get_session),
) -> User:
    """Retrieve a single student by ID."""
    return get_user(user_id=student_id, session=session)


@router.put("/{student_id}", response_model=UserRead)
def update_student_endpoint(
    student_id: int,
    student_in: UserUpdate,
    session: Session = Depends(get_session),
) -> User:
    """Update an existing student's details (partial update supported)."""
    return update_user(user_id=student_id, user_in=student_in, session=session)


@router.delete("/{student_id}", status_code=status.HTTP_200_OK)
def delete_student_endpoint(
    student_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Remove a student and their associated assignments from the database."""
    return delete_user(user_id=student_id, session=session)


@router.post("/{student_id}/reset-password", status_code=status.HTTP_200_OK)
def reset_student_password_endpoint(
    student_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_coach),
) -> dict:
    """Reset a student's password to the default password (coach only)."""
    return reset_password(user_id=student_id, session=session, current_user=current_user)

