"""
app/api/pages/renderers.py
──────────────────────────
Registry mapping task types to templates and helper functions that generate
render data for task detail pages from their corresponding domain classes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from sqlmodel import Session

from app.domain.factory import TaskFactory
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User

logger = logging.getLogger(__name__)

# ── Map task_type to specific template file ───────────────────
TASK_TYPE_TEMPLATE_MAP: Dict[str, str] = {
    "CF_SHEET": "tasks/types/cf_sheet.html",
    "CF_CONTEST": "tasks/types/cf_contest.html",
}

DEFAULT_TASK_TEMPLATE = "tasks/types/default.html"


def generate_task_render_data(
    task: Task,
    assignments: List[StudentTask],
    student_map: Dict[int, User],
    session: Session,
) -> Tuple[Dict[str, Any], str]:
    """Generate template context data and resolve template file for a task type.

    Looks up the corresponding domain checker class via TaskFactory,
    calls its `get_render_data` method, and resolves the template file
    from TASK_TYPE_TEMPLATE_MAP.

    Returns
    -------
    Tuple[Dict[str, Any], str]
        (task_render_data, template_file_path)
    """
    template_file = TASK_TYPE_TEMPLATE_MAP.get(task.task_type, DEFAULT_TASK_TEMPLATE)
    render_data: Dict[str, Any] = {}

    try:
        domain_task = TaskFactory.create(task.task_type, task.config)
        if hasattr(domain_task, "get_render_data"):
            render_data = domain_task.get_render_data(
                task=task,
                assignments=assignments,
                student_map=student_map,
                session=session,
            )
    except ValueError as exc:
        # Custom or unregistered task type (e.g. CSES_SHEET)
        logger.debug("No domain checker registered for task_type %r: %s", task.task_type, exc)
    except Exception as exc:
        logger.warning(
            "Error generating render data for task #%s (type: %s): %s",
            task.id,
            task.task_type,
            exc,
        )

    return render_data, template_file


def get_task_sidebar_data(
    task: Task,
    assignments: List[StudentTask],
    student_map: Dict[int, User],
) -> Dict[str, Any]:
    """Partition assignments into In Progress and Completed for the sidebar."""
    in_progress_assignments = []
    completed_assignments = []

    if task.task_type == "CF_SHEET":
        required_count = task.config.get(
            "min_solved_count", len(task.config.get("problems", []))
        )
    else:
        required_count = task.config.get("min_solved", 1)

    for a in assignments:
        student = student_map.get(a.student_id)
        if not student:
            continue

        res = a.checker_result or {}
        solved_count = res.get("solved_count", 0)

        item = {
            "assignment": a,
            "student": student,
            "solved_count": solved_count,
            "required_count": required_count,
        }

        if a.status in ("completed", "late"):
            completed_assignments.append(item)
        else:
            in_progress_assignments.append(item)

    return {
        "in_progress_assignments": in_progress_assignments,
        "completed_assignments": completed_assignments,
    }
