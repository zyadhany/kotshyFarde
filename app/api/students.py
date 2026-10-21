"""
app/api/students.py
───────────────────
CRUD endpoints for Student management.
Prefix: /students
Tags: ["Students"]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, delete, select

from app.core.database import get_session
from app.models.student import Student
from app.models.student_task import StudentTask
from app.schemas.student import StudentCreate, StudentRead, StudentUpdate

router = APIRouter(prefix="/students", tags=["Students"])


@router.post("/", response_model=StudentRead, status_code=status.HTTP_201_CREATED)
def create_student(
    student_in: StudentCreate,
    session: Session = Depends(get_session),
) -> Student:
    """Create a new student with optional platform handles."""
    # Check for duplicate username or email
    existing = session.exec(
        select(Student).where(
            (Student.username == student_in.username) | (Student.email == student_in.email)
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student with this username or email already exists.",
        )

    student = Student(**student_in.model_dump())
    session.add(student)
    session.commit()
    session.refresh(student)
    return student


@router.get("/", response_model=List[StudentRead])
def list_students(
    session: Session = Depends(get_session),
) -> List[Student]:
    """Retrieve a list of all students."""
    students = session.exec(select(Student)).all()
    return list(students)


@router.get("/{student_id}", response_model=StudentRead)
def get_student(
    student_id: int,
    session: Session = Depends(get_session),
) -> Student:
    """Retrieve a single student by ID."""
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {student_id} not found.",
        )
    return student


@router.put("/{student_id}", response_model=StudentRead)
def update_student(
    student_id: int,
    student_in: StudentUpdate,
    session: Session = Depends(get_session),
) -> Student:
    """Update an existing student's details (partial update supported)."""
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {student_id} not found.",
        )

    update_data = student_in.model_dump(exclude_unset=True)

    # Check uniqueness if username or email is being changed
    new_username = update_data.get("username")
    new_email = update_data.get("email")
    if new_username or new_email:
        query = select(Student).where(col(Student.id) != student_id)
        if new_username and new_email:
            query = query.where((Student.username == new_username) | (Student.email == new_email))
        elif new_username:
            query = query.where(Student.username == new_username)
        elif new_email:
            query = query.where(Student.email == new_email)

        conflict = session.exec(query).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another student with this username or email already exists.",
            )

    for field, value in update_data.items():
        setattr(student, field, value)

    student.updated_at = datetime.now(timezone.utc)
    session.add(student)
    session.commit()
    session.refresh(student)
    return student


@router.delete("/{student_id}", status_code=status.HTTP_200_OK)
def delete_student(
    student_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Remove a student and their associated assignments from the database."""
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {student_id} not found.",
        )

    # Remove associated assignments to maintain referential integrity
    session.exec(delete(StudentTask).where(StudentTask.student_id == student_id))
    session.delete(student)
    session.commit()
    return {"message": f"Student with ID {student_id} deleted successfully."}
