"""
app/api/assignments.py
──────────────────────
Endpoints for assigning tasks to students, querying assignments,
and executing domain checkers.
Prefix: /assignments
Tags: ["Assignments"]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.deps import get_current_user, require_coach
from app.core.config import settings
from app.core.database import get_session
from app.domain.factory import TaskFactory
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User
from app.schemas.assignment import (
    AssignmentBatchCreate,
    AssignmentBatchResponse,
    AssignmentCreate,
    AssignmentRead,
    AssignmentWithTaskRead,
)
from app.schemas.task import TaskRead

router = APIRouter(prefix="/api/assignments", tags=["Assignments"])


def _to_with_task_read(assignment: StudentTask, session: Session) -> AssignmentWithTaskRead:
    task = session.get(Task, assignment.task_id)
    return AssignmentWithTaskRead(
        id=assignment.id,  # type: ignore[arg-type]
        student_id=assignment.student_id,
        task_id=assignment.task_id,
        start_date=assignment.start_date,
        deadline=assignment.deadline,
        status=assignment.status,
        checker_result=assignment.checker_result,
        completed_at=assignment.completed_at,
        task=TaskRead.model_validate(task) if task else None,
    )


@router.post("/", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def assign_task(
    assignment_in: AssignmentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_coach),
) -> StudentTask:
    """Assign a task to a student with optional custom start_date and deadline (coach only)."""
    # Verify student exists
    student = session.get(User, assignment_in.student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {assignment_in.student_id} not found.",
        )

    if student.is_coach():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign tasks to a coach account.",
        )

    # Verify task exists
    task = session.get(Task, assignment_in.task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {assignment_in.task_id} not found.",
        )

    # Default rules:
    # 1. start_date defaults to current UTC time
    start_date = assignment_in.start_date
    if start_date is None:
        start_date = datetime.now(timezone.utc)
    elif start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)

    # 2. deadline defaults to DEFAULT_TASK_DEADLINE from config (fallback: 2030-01-01)
    deadline = assignment_in.deadline
    if deadline is None:
        deadline = settings.DEFAULT_TASK_DEADLINE
    elif deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    # Prevent duplicate assignments: return existing assignment (updating dates if supplied)
    existing = session.exec(
        select(StudentTask).where(
            StudentTask.student_id == assignment_in.student_id,
            StudentTask.task_id == assignment_in.task_id,
        )
    ).first()

    if existing:
        if assignment_in.deadline is not None:
            existing.deadline = deadline
        if assignment_in.start_date is not None:
            existing.start_date = start_date
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    assignment = StudentTask(
        student_id=assignment_in.student_id,
        task_id=assignment_in.task_id,
        start_date=start_date,
        deadline=deadline,
        status="pending",
        checker_result={},
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


@router.post("/batch", response_model=AssignmentBatchResponse, status_code=status.HTTP_201_CREATED)
def assign_task_batch(
    batch_in: AssignmentBatchCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_coach),
) -> AssignmentBatchResponse:
    """Batch assign a task to multiple students atomically in a single transaction (coach only)."""
    # 1. Verify task exists
    task = session.get(Task, batch_in.task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {batch_in.task_id} not found.",
        )

    # 2. Resolve default dates
    start_date = batch_in.start_date
    if start_date is None:
        start_date = datetime.now(timezone.utc)
    elif start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)

    deadline = batch_in.deadline
    if deadline is None:
        deadline = settings.DEFAULT_TASK_DEADLINE
    elif deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    # 3. Deduplicate student IDs while preserving order
    unique_student_ids = list(dict.fromkeys(batch_in.student_ids))

    assignments: List[StudentTask] = []
    for sid in unique_student_ids:
        student = session.get(User, sid)
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student with ID {sid} not found.",
            )
        if student.is_coach():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot assign tasks to a coach account (ID {sid}).",
            )

        existing = session.exec(
            select(StudentTask).where(
                StudentTask.student_id == sid,
                StudentTask.task_id == batch_in.task_id,
            )
        ).first()

        if existing:
            if batch_in.deadline is not None:
                existing.deadline = deadline
            if batch_in.start_date is not None:
                existing.start_date = start_date
            session.add(existing)
            assignments.append(existing)
        else:
            assignment = StudentTask(
                student_id=sid,
                task_id=batch_in.task_id,
                start_date=start_date,
                deadline=deadline,
                status="pending",
                checker_result={},
            )
            session.add(assignment)
            assignments.append(assignment)

    session.commit()
    for a in assignments:
        session.refresh(a)

    return AssignmentBatchResponse(
        success=True,
        assigned_count=len(assignments),
        assignments=[AssignmentRead.model_validate(a) for a in assignments],
    )


@router.get("/", response_model=List[AssignmentWithTaskRead])
def list_assignments(
    student_id: Optional[int] = None,
    task_id: Optional[int] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_coach),
) -> List[AssignmentWithTaskRead]:
    """List all student task assignments with optional filtering (coach only)."""
    query = select(StudentTask)
    if student_id is not None:
        query = query.where(StudentTask.student_id == student_id)
    if task_id is not None:
        query = query.where(StudentTask.task_id == task_id)
    if status is not None:
        query = query.where(StudentTask.status == status)

    assignments = session.exec(query.order_by(StudentTask.deadline.asc(), StudentTask.id.desc())).all()
    return [_to_with_task_read(a, session) for a in assignments]


@router.get("/student/{student_id}", response_model=List[AssignmentWithTaskRead])
def get_student_assignments(
    student_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> List[AssignmentWithTaskRead]:
    """Fetch all assignments for a specific student (coach or the assigned student)."""
    if current_user.is_student() and current_user.id != student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only view your own assignments.",
        )

    student = session.get(User, student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {student_id} not found.",
        )

    assignments = session.exec(
        select(StudentTask).where(StudentTask.student_id == student_id)
    ).all()

    return [_to_with_task_read(a, session) for a in assignments]


@router.get("/{assignment_id}", response_model=AssignmentWithTaskRead)
def get_assignment(
    assignment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AssignmentWithTaskRead:
    """Get specific assignment details along with the associated task."""
    assignment = session.get(StudentTask, assignment_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment with ID {assignment_id} not found.",
        )

    if current_user.is_student() and current_user.id != assignment.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only view your own assignments.",
        )

    return _to_with_task_read(assignment, session)


@router.post("/{assignment_id}/check", response_model=AssignmentWithTaskRead)
def check_assignment(
    assignment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AssignmentWithTaskRead:
    """Run the domain checker for an assignment and persist the results (coach or assigned student)."""
    # 1. Fetch assignment
    assignment = session.get(StudentTask, assignment_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment with ID {assignment_id} not found.",
        )

    # Authorization: Students can only run check on their own assignments
    if current_user.is_student() and current_user.id != assignment.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only check your own assignments.",
        )

    # 2. Fetch student
    student = session.get(User, assignment.student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {assignment.student_id} not found.",
        )

    # 3. Fetch task
    task = session.get(Task, assignment.task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {assignment.task_id} not found.",
        )

    # 4. Instantiate domain checker
    try:
        checker = TaskFactory.create(task.task_type, task.config)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task configuration: {exc}",
        )

    # 5. Run checker
    try:
        result = checker.check(student, assignment, session=session)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Checker execution error: {exc}",
        )

    # 6. Extract status and details
    new_status = result.get("status", "pending")
    assignment.status = new_status
    if new_status in ("completed", "late") and not assignment.completed_at:
        assignment.completed_at = datetime.now(timezone.utc)

    details = result.get("details", {})
    solved_count = details.get("solved_count", len(details.get("solved", [])))
    missing_problems = details.get("unsolved", details.get("missing_problems", []))

    # 7. Persist status and checker_result
    checker_output = {
        "status": new_status,
        "after_deadline": result.get("after_deadline", False),
        "solved_count": solved_count,
        "missing_problems": missing_problems,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    # Guarantee consistent fields
    checker_output["solved_count"] = solved_count
    checker_output["missing_problems"] = missing_problems
    checker_output["last_checked"] = datetime.now(timezone.utc).isoformat()

    assignment.checker_result = checker_output
    session.add(assignment)
    session.commit()
    session.refresh(assignment)

    return _to_with_task_read(assignment, session)


@router.delete("/{assignment_id}", status_code=status.HTTP_200_OK)
def delete_assignment(
    assignment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_coach),
) -> dict:
    """Delete a student-task assignment (coach only)."""
    assignment = session.get(StudentTask, assignment_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment with ID {assignment_id} not found.",
        )
    session.delete(assignment)
    session.commit()
    return {"success": True, "message": f"Assignment #{assignment_id} deleted successfully."}
