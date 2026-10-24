"""
app/api/tasks.py
────────────────
CRUD endpoints for Task management.
Prefix: /tasks
Tags: ["Tasks"]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, delete, select

from app.api.deps import require_coach
from app.core.database import get_session
from app.domain.factory import TaskFactory
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["Tasks"], dependencies=[Depends(require_coach)])


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


@router.post("/{task_id}/check-all", status_code=status.HTTP_200_OK)
def check_all_task_assignments(
    task_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Re-check all student assignments for a task (coach only)."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found.",
        )

    assignments = list(
        session.exec(select(StudentTask).where(StudentTask.task_id == task_id)).all()
    )
    if not assignments:
        return {
            "message": "No students are currently enrolled in this task.",
            "checked_count": 0,
            "results": [],
        }

    try:
        checker = TaskFactory.create(task.task_type, task.config)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task configuration: {exc}",
        )

    results = []
    for a in assignments:
        student = session.get(User, a.student_id)
        if not student:
            continue

        try:
            result = checker.check(student, a, session=session)
            new_status = result.get("status", "pending")
            a.status = new_status
            if new_status in ("completed", "late") and not a.completed_at:
                a.completed_at = datetime.now(timezone.utc)

            details = result.get("details", {})
            solved_count = details.get("solved_count", len(details.get("solved", [])))
            missing_problems = details.get("unsolved", details.get("missing_problems", []))

            checker_output = {
                "status": new_status,
                "after_deadline": result.get("after_deadline", False),
                "solved_count": solved_count,
                "missing_problems": missing_problems,
                "last_checked": datetime.now(timezone.utc).isoformat(),
                **details,
            }
            checker_output["solved_count"] = solved_count
            checker_output["missing_problems"] = missing_problems
            checker_output["last_checked"] = datetime.now(timezone.utc).isoformat()

            a.checker_result = checker_output
            session.add(a)
            results.append({
                "student_id": student.id,
                "username": student.username,
                "status": new_status,
                "solved_count": solved_count,
            })
        except Exception as exc:
            logger.warning("Error rechecking assignment %s for student %s: %s", a.id, student.username, exc)
            results.append({
                "student_id": student.id,
                "username": student.username,
                "error": str(exc),
            })

    session.commit()
    return {
        "message": f"Successfully rechecked {len(results)} enrolled student(s).",
        "checked_count": len(results),
        "results": results,
    }
