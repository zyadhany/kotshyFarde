"""
app/api/pages/routes.py
───────────────────────
HTML page rendering routes for the high-density, minimalist Kotchy UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.pages.renderers import generate_task_render_data, get_task_sidebar_data
from app.core.database import get_session
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User

router = APIRouter(tags=["Frontend Pages"])

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ── Dashboard (/) ──────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Coach Command Center: 3 student metrics + active cohort list."""
    students = list(session.exec(select(User).order_by(User.id)).all())
    assignments = list(session.exec(select(StudentTask)).all())

    total_students = len(students)
    on_track_students = 0
    needs_attention_students = 0

    cohort_rows = []
    now_utc = datetime.now(timezone.utc)

    for s in students:
        s_assignments = [a for a in assignments if a.student_id == s.id]
        total_assigned = len(s_assignments)
        completed_count = sum(1 for a in s_assignments if a.status in ("completed", "late"))
        pending_count = total_assigned - completed_count

        # Check for any overdue assignment
        has_overdue = any(
            a.status not in ("completed", "late") and a.deadline and (
                (a.deadline.replace(tzinfo=timezone.utc) if a.deadline.tzinfo is None else a.deadline) < now_utc
            )
            for a in s_assignments
        )

        # On Track: all assigned tasks completed (or total_assigned == 0) and not overdue
        if pending_count == 0 and not has_overdue:
            on_track_students += 1
        else:
            needs_attention_students += 1

        progress_pct = (
            round((completed_count / total_assigned) * 100) if total_assigned > 0 else 0
        )

        # Find latest pending assignment for the quick-check button
        latest_pending = next(
            (a.id for a in s_assignments if a.status not in ("completed", "late")),
            s_assignments[0].id if s_assignments else None,
        )

        cohort_rows.append({
            "student": s,
            "total_assigned": total_assigned,
            "completed_count": completed_count,
            "pending_count": pending_count,
            "progress_pct": progress_pct,
            "has_overdue": has_overdue,
            "latest_pending_assignment_id": latest_pending,
        })

    # Sort cohort: students needing attention first, then by username
    cohort_rows.sort(key=lambda r: (0 if r["pending_count"] > 0 else 1, r["student"].username.lower()))

    on_track_pct = (
        round((on_track_students / total_students) * 100) if total_students > 0 else 0
    )
    needs_attention_pct = (
        round((needs_attention_students / total_students) * 100) if total_students > 0 else 0
    )

    metrics = {
        "total_students": total_students,
        "on_track_students": on_track_students,
        "on_track_pct": on_track_pct,
        "needs_attention_students": needs_attention_students,
        "needs_attention_pct": needs_attention_pct,
    }

    context = {
        "request": request,
        "active_page": "dashboard",
        "metrics": metrics,
        "cohort_rows": cohort_rows,
    }

    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_redirect() -> RedirectResponse:
    """Redirect /dashboard to root /."""
    return RedirectResponse(url="/", status_code=302)


# ── Students Archive (/students-page) ──────────────────────────
@router.get("/students-page", response_class=HTMLResponse)
def students_index_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """All students table + Add Student modal."""
    students = list(session.exec(select(User).order_by(User.id)).all())

    context = {
        "request": request,
        "active_page": "students",
        "students": students,
    }

    return templates.TemplateResponse(request=request, name="students/index.html", context=context)


# ── Student Detail (/students-page/{student_id}) ───────────────
@router.get("/students-page/{student_id}", response_class=HTMLResponse)
def student_detail_page(
    student_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Student profile: metadata and sorted task list (In Progress first)."""
    student = session.get(User, student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student #{student_id} not found.",
        )

    all_tasks = list(session.exec(select(Task).order_by(Task.title)).all())
    task_map = {t.id: t for t in all_tasks}

    assignments = list(
        session.exec(
            select(StudentTask).where(StudentTask.student_id == student_id)
        ).all()
    )

    now_utc = datetime.now(timezone.utc)
    task_items = []

    for a in assignments:
        task = task_map.get(a.task_id)
        if not task:
            continue

        deadline_aware = (
            a.deadline.replace(tzinfo=timezone.utc)
            if a.deadline and a.deadline.tzinfo is None
            else a.deadline
        )
        is_overdue = bool(
            deadline_aware and now_utc > deadline_aware and a.status not in ("completed", "late")
        )

        res = a.checker_result or {}
        solved_count = res.get("solved_count", 0)

        # Required count
        if task.task_type == "CF_SHEET":
            required_count = task.config.get("min_solved_count", len(task.config.get("problems", [])))
        else:
            required_count = task.config.get("min_solved", 1)

        last_checked = None
        if res.get("last_checked"):
            try:
                dt = datetime.fromisoformat(res["last_checked"])
                last_checked = dt.strftime("%b %d, %H:%M")
            except Exception:
                last_checked = str(res["last_checked"])[:16]

        task_items.append({
            "assignment": a,
            "task": task,
            "is_overdue": is_overdue,
            "solved_count": solved_count,
            "required_count": required_count,
            "last_checked": last_checked,
            "is_completed": a.status in ("completed", "late"),
        })

    # SORTING RULE: In Progress / Pending tasks at top, Completed tasks at bottom
    task_items.sort(
        key=lambda x: (
            1 if x["is_completed"] else 0,
            x["assignment"].deadline or datetime.max.replace(tzinfo=timezone.utc),
        )
    )

    in_progress_count = sum(1 for x in task_items if not x["is_completed"])
    completed_count = sum(1 for x in task_items if x["is_completed"])

    context = {
        "request": request,
        "active_page": "students",
        "student": student,
        "sorted_tasks": task_items,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "all_tasks": all_tasks,
    }

    return templates.TemplateResponse(request=request, name="students/detail.html", context=context)


# ── Tasks Archive (/tasks-page) ────────────────────────────────
@router.get("/tasks-page", response_class=HTMLResponse)
def tasks_index_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Task archive + filter by type + Create Task modal."""
    tasks = list(session.exec(select(Task).order_by(Task.id)).all())
    assignments = list(session.exec(select(StudentTask)).all())

    task_items = []
    sheet_count = 0
    contest_count = 0

    for t in tasks:
        if t.task_type == "CF_SHEET":
            sheet_count += 1
            problem_count = len(t.config.get("problems", []))
            min_solved = t.config.get("min_solved_count", problem_count)
        else:
            contest_count += 1
            problem_count = 1
            min_solved = t.config.get("min_solved", 1)

        assigned_count = sum(1 for a in assignments if a.task_id == t.id)

        task_items.append({
            "task": t,
            "problem_count": problem_count,
            "min_solved": min_solved,
            "assigned_count": assigned_count,
        })

    context = {
        "request": request,
        "active_page": "tasks",
        "tasks": tasks,
        "task_items": task_items,
        "sheet_count": sheet_count,
        "contest_count": contest_count,
    }

    return templates.TemplateResponse(request=request, name="tasks/index.html", context=context)


# ── Task Detail (/tasks-page/{task_id}) ────────────────────────
@router.get("/tasks-page/{task_id}", response_class=HTMLResponse)
def task_detail_page(
    task_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """2-Column task page with dynamic render data from domain checker."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )

    all_students = list(session.exec(select(User).order_by(User.username)).all())
    student_map = {s.id: s for s in all_students}

    assignments = list(
        session.exec(select(StudentTask).where(StudentTask.task_id == task_id)).all()
    )

    # 1. Common sidebar data (in progress vs completed assignments)
    sidebar_data = get_task_sidebar_data(task, assignments, student_map)

    # 2. Task-type specific data generated from its corresponding domain class & template map
    type_render_data, type_template = generate_task_render_data(
        task=task,
        assignments=assignments,
        student_map=student_map,
        session=session,
    )

    context = {
        "request": request,
        "active_page": "tasks",
        "task": task,
        "all_students": all_students,
        "all_students_json": [
            {"id": s.id, "username": s.username, "cf_handle": s.cf_handle or ""}
            for s in all_students
        ],
        "already_assigned_student_ids": {a.student_id for a in assignments},
        "assigned_students": assignments,
        "type_template": type_template,
        **sidebar_data,
        **type_render_data,
    }

    return templates.TemplateResponse(request=request, name="tasks/detail.html", context=context)
