"""
app/api/users.py
────────────────
CRUD endpoints for User management.
Prefix: /users
Tags: ["Users"]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, delete, select

from app.api.deps import require_coach
from app.core.config import settings
from app.core.database import get_session
from app.core.security import get_password_hash
from app.models.student_task import StudentTask
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(require_coach)])


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    session: Session = Depends(get_session),
) -> User:
    """Create a new user with optional platform handles and role."""
    # Check for duplicate username or email
    existing = session.exec(
        select(User).where(
            (User.username == user_in.username) | (User.email == user_in.email)
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this username or email already exists.",
        )

    user_dict = user_in.model_dump()
    raw_password = user_dict.pop("password", None) or user_dict.pop("password_hash", None)
    provided_hash = user_dict.pop("hashed_password", None)

    default_pwd = (getattr(settings, "DEFAULT_PASSWORD", None) or "12345678").strip() or "12345678"

    if raw_password and not str(raw_password).startswith(("$2b$", "$2a$")):
        final_hash = get_password_hash(str(raw_password))
    elif provided_hash and str(provided_hash).startswith(("$2b$", "$2a$")):
        final_hash = str(provided_hash)
    elif provided_hash:
        final_hash = get_password_hash(str(provided_hash))
    elif raw_password:
        final_hash = str(raw_password)
    else:
        final_hash = get_password_hash(default_pwd)

    user = User(**user_dict, hashed_password=final_hash)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/", response_model=List[UserRead])
def list_users(
    session: Session = Depends(get_session),
) -> List[User]:
    """Retrieve a list of all users."""
    users = session.exec(select(User)).all()
    return list(users)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    session: Session = Depends(get_session),
) -> User:
    """Retrieve a single user by ID."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found.",
        )
    return user


@router.put("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    user_in: UserUpdate,
    session: Session = Depends(get_session),
) -> User:
    """Update an existing user's details (partial update supported)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found.",
        )

    update_data = user_in.model_dump(exclude_unset=True)

    # Check uniqueness if username or email is being changed
    new_username = update_data.get("username")
    new_email = update_data.get("email")
    if new_username or new_email:
        query = select(User).where(col(User.id) != user_id)
        if new_username and new_email:
            query = query.where((User.username == new_username) | (User.email == new_email))
        elif new_username:
            query = query.where(User.username == new_username)
        elif new_email:
            query = query.where(User.email == new_email)

        conflict = session.exec(query).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another user with this username or email already exists.",
            )

    # Handle password updating with hashing
    if "password" in update_data:
        pwd = update_data.pop("password")
        if pwd:
            user.hashed_password = get_password_hash(str(pwd))
    elif "password_hash" in update_data:
        pwd = update_data.pop("password_hash")
        if pwd and not str(pwd).startswith(("$2b$", "$2a$")):
            user.hashed_password = get_password_hash(str(pwd))
        elif pwd:
            user.hashed_password = str(pwd)
    elif "hashed_password" in update_data:
        pwd = update_data.pop("hashed_password")
        if pwd and not str(pwd).startswith(("$2b$", "$2a$")):
            user.hashed_password = get_password_hash(str(pwd))
        elif pwd:
            user.hashed_password = str(pwd)

    for field, value in update_data.items():
        setattr(user, field, value)

    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Remove a user and their associated assignments from the database."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found.",
        )

    # Remove associated assignments to maintain referential integrity
    session.exec(delete(StudentTask).where(StudentTask.student_id == user_id))
    session.delete(user)
    session.commit()
    return {"message": f"User with ID {user_id} deleted successfully."}


@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
def reset_password(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_coach),
) -> dict:
    """Reset a user's password to the configured default password (coach only)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found.",
        )

    default_pwd = (getattr(settings, "DEFAULT_PASSWORD", None) or "12345678").strip() or "12345678"
    user.hashed_password = get_password_hash(default_pwd)
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    session.commit()
    return {
        "success": True,
        "message": f"Password for {user.username} has been reset to default.",
        "default_password": default_pwd,
    }
