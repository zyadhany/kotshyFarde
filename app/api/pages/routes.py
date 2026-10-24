"""
app/api/pages/routes.py
───────────────────────
HTML page rendering routes for the high-density, minimalist Kotchy UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_user, require_coach
from app.api.pages.renderers import generate_task_render_data, get_task_sidebar_data
from app.core.config import settings
from app.core.database import get_session
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User

from app.services.codeforces_api import (
    get_rating_class,
    get_rating_color,
    get_rating_title,
    get_user_info,
    get_user_rating,
    prefetch_cf_info,
)

router = APIRouter(tags=["Frontend Pages"])

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.filters["cf_rating_class"] = get_rating_class
templates.env.filters["cf_rating_color"] = get_rating_color
templates.env.filters["cf_rating_title"] = get_rating_title
templates.env.globals["get_cf_rating"] = get_user_rating
templates.env.globals["get_cf_info"] = get_user_info
templates.env.globals["get_rating_class"] = get_rating_class
templates.env.globals["get_rating_title"] = get_rating_title


# ── Dashboard (/) ──────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Coach Command Center: 3 student metrics + active cohort list."""
    if current_user.is_student():
        return RedirectResponse(url="/my-profile", status_code=status.HTTP_303_SEE_OTHER)

    students = [u for u in session.exec(select(User).order_by(User.id)).all() if u.is_student()]
    prefetch_cf_info([s.cf_handle for s in students if s.cf_handle])
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
        "current_user": current_user,
        "active_page": "dashboard",
        "metrics": metrics,
        "cohort_rows": cohort_rows,
    }

    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_redirect() -> RedirectResponse:
    """Redirect /dashboard to root /."""
    return RedirectResponse(url="/", status_code=302)


# ── Students Archive (/students) ──────────────────────────────
@router.get("/students", response_class=HTMLResponse)
@router.get("/students-page", response_class=HTMLResponse)
def students_index_page(
    request: Request,
    current_user: User = Depends(require_coach),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """All students table + Add Student modal (coach only)."""
    students = [u for u in session.exec(select(User).order_by(User.id)).all() if u.is_student()]
    prefetch_cf_info([s.cf_handle for s in students if s.cf_handle])

    context = {
        "request": request,
        "current_user": current_user,
        "active_page": "students",
        "students": students,
    }

    return templates.TemplateResponse(request=request, name="students/index.html", context=context)


# ── Student Detail (/students/{student_id}) ───────────────────
@router.get("/students/{student_id}", response_class=HTMLResponse)
@router.get("/students-page/{student_id}", response_class=HTMLResponse)
def student_detail_page(
    student_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Student profile: metadata and sorted task list (In Progress first)."""
    # Restrict students to only view their own profile
    if current_user.is_student() and current_user.id != student_id:
        return RedirectResponse(url="/my-profile", status_code=status.HTTP_303_SEE_OTHER)

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
            required_count = task.config.get("min_solved", 0)
            if required_count == 0:
                try:
                    from app.domain.codeforces.contest import CodeforcesContestTask
                    c_task = CodeforcesContestTask(contest_id=task.config.get("contest_id"))
                    probs = c_task.get_problems()
                    required_count = len(probs) if probs else 0
                except Exception:
                    required_count = 0

        last_checked = None
        if res.get("last_checked"):
            try:
                dt = datetime.fromisoformat(res["last_checked"])
                last_checked = dt.strftime("%b %d, %H:%M")
            except Exception:
                last_checked = str(res["last_checked"])[:16]

        progress_pct = (
            min(100, int((solved_count / required_count) * 100))
            if required_count > 0
            else 0
        )

        task_items.append({
            "assignment": a,
            "task": task,
            "is_overdue": is_overdue,
            "solved_count": solved_count,
            "required_count": required_count,
            "progress_pct": progress_pct,
            "last_checked": last_checked,
            "is_completed": a.status in ("completed", "late"),
            "deadline_aware": deadline_aware,
        })

    # SORTING RULE: in_progress at top (0), pending after (1), completed at last (2)
    def status_priority(item):
        status = item["assignment"].status
        if status == "in_progress":
            return 0
        elif status == "pending":
            return 1
        elif status in ("completed", "late"):
            return 2
        return 1

    task_items.sort(
        key=lambda x: (
            status_priority(x),
            x["deadline_aware"] or datetime.max.replace(tzinfo=timezone.utc),
            x["assignment"].id,
        )
    )

    in_progress_count = sum(1 for x in task_items if not x["is_completed"])
    completed_count = sum(1 for x in task_items if x["is_completed"])

    cf_info = get_user_info(student.cf_handle) if student.cf_handle else None
    student_rating = cf_info.get("rating") if cf_info else None
    student_max_rating = cf_info.get("maxRating") if cf_info else None
    student_rank = cf_info.get("rank") if cf_info else None
    student_max_rank = cf_info.get("maxRank") if cf_info else None

    context = {
        "request": request,
        "current_user": current_user,
        "active_page": "my_profile" if (current_user.is_student() and current_user.id == student_id) else "students",
        "student": student,
        "cf_info": cf_info,
        "student_rating": student_rating,
        "student_max_rating": student_max_rating,
        "student_rank": student_rank,
        "student_max_rank": student_max_rank,
        "sorted_tasks": task_items,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "all_tasks": all_tasks,
        "default_password": (getattr(settings, "DEFAULT_PASSWORD", None) or "12345678").strip() or "12345678",
    }

    return templates.TemplateResponse(request=request, name="students/detail.html", context=context)


# ── My Profile (/my-profile) ──────────────────────────────────
@router.get("/my-profile", response_class=HTMLResponse)
def my_profile_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Personal student profile and tasks view."""
    return student_detail_page(
        student_id=current_user.id,
        request=request,
        current_user=current_user,
        session=session,
    )


# ── Tasks Archive (/tasks) ────────────────────────────────────
@router.get("/tasks", response_class=HTMLResponse)
@router.get("/tasks-page", response_class=HTMLResponse)
def tasks_index_page(
    request: Request,
    current_user: User = Depends(require_coach),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Task archive + filter by type + Create Task modal (coach only)."""
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
            raw_min = t.config.get("min_solved", 1)
            min_solved = "All" if raw_min == 0 else raw_min

        assigned_count = sum(1 for a in assignments if a.task_id == t.id)

        task_items.append({
            "task": t,
            "problem_count": problem_count,
            "min_solved": min_solved,
            "assigned_count": assigned_count,
        })

    context = {
        "request": request,
        "current_user": current_user,
        "active_page": "tasks",
        "tasks": tasks,
        "task_items": task_items,
        "sheet_count": sheet_count,
        "contest_count": contest_count,
    }

    return templates.TemplateResponse(request=request, name="tasks/index.html", context=context)


# ── Task Detail (/tasks/{task_id}) ────────────────────────────
@router.get("/tasks/{task_id}", response_class=HTMLResponse)
@router.get("/tasks-page/{task_id}", response_class=HTMLResponse)
def task_detail_page(
    task_id: int,
    request: Request,
    student_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """2-Column task page with dynamic render data from domain checker."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )

    all_users = list(session.exec(select(User).order_by(User.username)).all())
    student_map = {s.id: s for s in all_users}
    all_students = [s for s in all_users if s.is_student()]

    assignments = list(
        session.exec(select(StudentTask).where(StudentTask.task_id == task_id)).all()
    )

    # Prefetch Codeforces rating and user info only for relevant users on this page:
    # 1. Students assigned to this task
    # 2. The logged-in current user
    assigned_student_ids = {a.student_id for a in assignments}
    relevant_handles = [
        student_map[sid].cf_handle
        for sid in assigned_student_ids
        if sid in student_map and student_map[sid].cf_handle
    ]
    if current_user.cf_handle and current_user.cf_handle not in relevant_handles:
        relevant_handles.append(current_user.cf_handle)
    prefetch_cf_info(relevant_handles)

    # Restrict student account to only view tasks that are assigned to them
    if current_user.is_student():
        is_assigned = any(a.student_id == current_user.id for a in assignments)
        if not is_assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only view tasks assigned to you.",
            )
        student_id = current_user.id

    # 1. Task-type specific data generated from its corresponding domain class & template map
    type_render_data, type_template = generate_task_render_data(
        task=task,
        assignments=assignments,
        student_map=student_map,
        session=session,
        current_user=current_user,
        target_student_id=student_id,
    )

    # 2. Common sidebar data (in progress vs completed assignments)
    sidebar_data = get_task_sidebar_data(
        task=task,
        assignments=assignments,
        student_map=student_map,
        contest_problems=type_render_data.get("contest_problems"),
    )

    already_assigned_student_ids = {a.student_id for a in assignments}
    unassigned_students = [s for s in all_students if s.id not in already_assigned_student_ids]

    my_assignment_data = None
    if current_user and current_user.is_student():
        for item in sidebar_data.get("in_progress_assignments", []) + sidebar_data.get("completed_assignments", []):
            if item["student"].id == current_user.id:
                my_assignment_data = item
                break
        if not my_assignment_data:
            for a in assignments:
                if a.student_id == current_user.id:
                    my_assignment_data = {
                        "assignment": a,
                        "student": current_user,
                        "solved_count": (a.checker_result or {}).get("solved_count", 0),
                        "required_count": 0,
                    }
                    break
        if my_assignment_data:
            req = my_assignment_data.get("required_count", 1)
            solv = my_assignment_data.get("solved_count", 0)
            my_assignment_data["progress_pct"] = min(100, round((solv / req) * 100)) if req > 0 else (100 if my_assignment_data["assignment"].status in ("completed", "late") else 0)
            dl = my_assignment_data["assignment"].deadline
            if dl:
                my_assignment_data["deadline_iso"] = dl.isoformat() if dl.tzinfo else (dl.isoformat() + "Z")

    context = {
        "request": request,
        "current_user": current_user,
        "active_page": "tasks",
        "task": task,
        "my_assignment_data": my_assignment_data,
        "all_students": all_students,
        "unassigned_students": unassigned_students,
        "student_map": student_map,
        "selected_student_id": student_id,
        "all_students_json": [
            {"id": s.id, "username": s.username, "cf_handle": s.cf_handle or ""}
            for s in all_students
        ],
        "already_assigned_student_ids": already_assigned_student_ids,
        "assigned_students": assignments,
        "type_template": type_template,
        **sidebar_data,
        **type_render_data,
    }

    return templates.TemplateResponse(request=request, name="tasks/detail.html", context=context)


# ── Assignments Archive (/assignments) ────────────────────────
@router.get("/assignments", response_class=HTMLResponse)
@router.get("/assignments-page", response_class=HTMLResponse)
def assignments_index_page(
    request: Request,
    current_user: User = Depends(require_coach),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Coach Command Center for all student-task assignments."""
    all_tasks = list(session.exec(select(Task).order_by(Task.title)).all())
    task_map = {t.id: t for t in all_tasks}

    all_students = [u for u in session.exec(select(User).order_by(User.username)).all() if u.is_student()]
    prefetch_cf_info([s.cf_handle for s in all_students if s.cf_handle])
    student_map = {s.id: s for s in all_students}

    assignments = list(
        session.exec(
            select(StudentTask).order_by(StudentTask.deadline.asc(), StudentTask.id.desc())
        ).all()
    )

    now_utc = datetime.now(timezone.utc)
    assignment_items = []

    total_count = len(assignments)
    completed_count = 0
    in_progress_count = 0
    overdue_count = 0

    for a in assignments:
        student = student_map.get(a.student_id)
        task = task_map.get(a.task_id)
        if not student or not task:
            continue

        deadline_aware = (
            a.deadline.replace(tzinfo=timezone.utc)
            if a.deadline and a.deadline.tzinfo is None
            else a.deadline
        )
        is_completed = a.status in ("completed", "late")
        is_overdue = bool(deadline_aware and now_utc > deadline_aware and not is_completed)

        if is_completed:
            completed_count += 1
        elif is_overdue:
            overdue_count += 1
        else:
            in_progress_count += 1

        res = a.checker_result or {}
        solved_count = res.get("solved_count", 0)

        if task.task_type == "CF_SHEET":
            problem_count = len(task.config.get("problems", []))
            required_count = task.config.get("min_solved_count", problem_count)
        else:
            required_count = task.config.get("min_solved", 1)
            problem_count = 1
            if required_count == 0:
                try:
                    from app.domain.codeforces.contest import CodeforcesContestTask
                    c_task = CodeforcesContestTask(contest_id=task.config.get("contest_id"))
                    probs = c_task.get_problems()
                    required_count = len(probs) if probs else 0
                    problem_count = required_count or 1
                except Exception:
                    required_count = 0

        progress_pct = (
            min(100, round((solved_count / required_count) * 100)) if required_count > 0 else 0
        )

        last_checked = None
        if res.get("last_checked"):
            try:
                dt = datetime.fromisoformat(res["last_checked"])
                last_checked = dt.strftime("%b %d, %H:%M")
            except Exception:
                last_checked = str(res["last_checked"])[:16]

        schedule_badge = ""
        schedule_badge_class = ""
        if deadline_aware:
            diff = deadline_aware - now_utc
            if diff.total_seconds() < 0:
                past_sec = abs(diff.total_seconds())
                if past_sec < 3600:
                    schedule_badge = f"Overdue by {max(1, int(past_sec // 60))}m"
                elif past_sec < 86400:
                    schedule_badge = f"Overdue by {int(past_sec // 3600)}h"
                else:
                    schedule_badge = f"Overdue by {int(past_sec // 86400)}d"
                schedule_badge_class = "bg-rose-50 text-rose-700 border-rose-200"
            else:
                rem_sec = diff.total_seconds()
                if rem_sec < 3600:
                    schedule_badge = f"Due in {max(1, int(rem_sec // 60))}m"
                    schedule_badge_class = "bg-amber-50 text-amber-700 border-amber-200"
                elif rem_sec < 86400:
                    schedule_badge = f"Due in {int(rem_sec // 3600)}h"
                    schedule_badge_class = "bg-amber-50 text-amber-700 border-amber-200"
                else:
                    schedule_badge = f"Due in {int(rem_sec // 86400)}d"
                    schedule_badge_class = "bg-slate-50 text-slate-600 border-slate-200"

        assignment_items.append({
            "assignment": a,
            "student": student,
            "task": task,
            "status": a.status,
            "is_completed": is_completed,
            "is_overdue": is_overdue,
            "solved_count": solved_count,
            "required_count": required_count,
            "problem_count": problem_count,
            "progress_pct": progress_pct,
            "last_checked": last_checked,
            "schedule_badge": schedule_badge,
            "schedule_badge_class": schedule_badge_class,
            "deadline_formatted": deadline_aware.strftime("%Y-%m-%d %H:%M") if deadline_aware else "—",
            "start_date_formatted": a.start_date.strftime("%Y-%m-%d") if a.start_date else "—",
        })

    # Sort priority: Overdue first, then pending/in_progress by deadline ascending, then completed
    def _sort_key(item):
        dl = item["assignment"].deadline or datetime.max.replace(tzinfo=timezone.utc)
        if item["is_overdue"]:
            return (0, dl)
        if not item["is_completed"]:
            return (1, dl)
        return (2, dl)

    assignment_items.sort(key=_sort_key)

    metrics = {
        "total_count": total_count,
        "completed_count": completed_count,
        "in_progress_count": in_progress_count,
        "overdue_count": overdue_count,
        "completion_rate": round((completed_count / total_count) * 100) if total_count > 0 else 0,
    }

    context = {
        "request": request,
        "current_user": current_user,
        "active_page": "assignments",
        "assignment_items": assignment_items,
        "metrics": metrics,
        "tasks": all_tasks,
        "students": all_students,
        "all_students_json": [
            {"id": s.id, "username": s.username, "cf_handle": s.cf_handle or ""}
            for s in all_students
        ],
    }

    return templates.TemplateResponse(request=request, name="assignments/index.html", context=context)
