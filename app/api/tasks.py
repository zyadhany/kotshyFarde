"""
app/api/tasks.py
────────────────
CRUD endpoints for Task management.
Prefix: /tasks
Tags: ["Tasks"]
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, delete, select

from app.core.database import get_session
from app.models.student_task import StudentTask
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    task_in: TaskCreate,
    session: Session = Depends(get_session),
) -> Task:
    """Create a new task definition with JSON configuration."""
    task = Task(**task_in.model_dump())
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.get("/", response_model=List[TaskRead])
def list_tasks(
    session: Session = Depends(get_session),
) -> List[Task]:
    """List all available tasks."""
    tasks = session.exec(select(Task)).all()
    return list(tasks)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> Task:
    """Retrieve task details by ID."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found.",
        )
    return task


@router.put("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    task_in: TaskUpdate,
    session: Session = Depends(get_session),
) -> Task:
    """Full/partial update for a task."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found.",
        )

    update_data = task_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_200_OK)
def delete_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Delete a task and its associated assignments from the database."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found.",
        )

    # Remove associated student assignments
    session.exec(delete(StudentTask).where(StudentTask.task_id == task_id))
    session.delete(task)
    session.commit()
    return {"message": f"Task with ID {task_id} deleted successfully."}
