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

from app.core.database import get_session
from app.models.student_task import StudentTask
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


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

    user = User(**user_in.model_dump())
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
