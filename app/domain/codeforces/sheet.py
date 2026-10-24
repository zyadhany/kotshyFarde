"""
app/domain/codeforces/sheet.py
──────────────────────────────
Checker for **CF_SHEET** tasks — a curated list of Codeforces problems
that a student must solve (at least ``min_solved_count``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from app.domain.codeforces.base import CodeforcesBaseTask
from app.models.student_task import StudentTask
from app.models.user import User
from app.services.codeforces_api import (
    get_problem_solve_status,
    get_user_submissions,
    parse_problem_id,
)

logger = logging.getLogger(__name__)


class CodeforcesSheetTask(CodeforcesBaseTask):
    """Domain checker for a problem-sheet assignment."""

    task_type: str = "CF_SHEET"

    def __init__(self, problems: List[str], min_solved_count: int) -> None:
        self.problems = problems
        self.min_solved_count = min_solved_count

    # ── Serialisation ─────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problems": self.problems,
            "min_solved_count": self.min_solved_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeforcesSheetTask":
        return cls(
            problems=data["problems"],
            min_solved_count=int(data.get("min_solved_count", len(data["problems"]))),
        )

    # ── Verification ──────────────────────────────────────────

    def check(self, student: User, student_task: StudentTask, **kwargs: Any) -> Dict[str, Any]:
        """Evaluate how many sheet problems the student solved.

        Checks whether the student solved at least min_solved_count problems.
        Does not filter by start_date; if deadline is provided, checks if
        solutions occurred before or after deadline and returns an after_deadline bool.
        """
        handle = student.cf_handle
        if not handle:
            return {
                "status": "failed",
                "after_deadline": False,
                "details": {"error": "  Student has no Codeforces handle configured."},
            }

        deadline = getattr(student_task, "deadline", None)
        submissions = get_user_submissions(handle)

        # Pre-index accepted submissions into dict for O(1) lookups per problem: O(N + P)
        ok_by_problem: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
        for sub in submissions:
            if sub.get("verdict") != "OK":
                continue
            prob = sub.get("problem", {})
            cid = prob.get("contestId")
            idx = prob.get("index")
            if cid is not None and idx:
                key = (cid, str(idx).upper())
                if key not in ok_by_problem:
                    ok_by_problem[key] = []
                ok_by_problem[key].append(sub)

        solved: List[str] = []
        unsolved: List[str] = []
        solved_after_deadline: List[str] = []
        problems_map: Dict[str, Any] = {}

        for prob_str in self.problems:
            try:
                contest_id, index = parse_problem_id(prob_str)
            except ValueError as exc:
                logger.warning("Skipping invalid problem id %r: %s", prob_str, exc)
                unsolved.append(prob_str)
                problems_map[prob_str] = {"solved": False, "after_deadline": False, "error": str(exc)}
                continue

            ok_subs = ok_by_problem.get((contest_id, index.upper()), [])
            if not ok_subs:
                prob_info = {
                    "solved": False,
                    "after_deadline": False,
                    "solved_at": None,
                }
            else:
                earliest_sec = min(s.get("creationTimeSeconds", 0) for s in ok_subs)
                solved_time = datetime.fromtimestamp(earliest_sec, tz=timezone.utc)
                after_deadline = False
                if deadline is not None:
                    d = deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=timezone.utc)
                    has_ontime_solve = any(
                        datetime.fromtimestamp(s.get("creationTimeSeconds", 0), tz=timezone.utc) <= d
                        for s in ok_subs
                    )
                    after_deadline = not has_ontime_solve

                prob_info = {
                    "solved": True,
                    "after_deadline": after_deadline,
                    "solved_at": solved_time.isoformat(),
                }

            problems_map[prob_str] = prob_info

            if prob_info["solved"]:
                solved.append(prob_str)
                if prob_info["after_deadline"]:
                    solved_after_deadline.append(prob_str)
            else:
                unsolved.append(prob_str)

        solved_count = len(solved)
        required = self.min_solved_count

        on_time_solved_count = solved_count - len(solved_after_deadline)
        is_after_deadline = len(solved_after_deadline) > 0

        if solved_count >= required:
            status = "late" if on_time_solved_count < required else "completed"
        elif solved_count > 0:
            status = "in_progress"
        else:
            status = "pending"

        return {
            "status": status,
            "after_deadline": is_after_deadline,
            "details": {
                "solved": solved,
                "unsolved": unsolved,
                "solved_count": solved_count,
                "required": required,
                "after_deadline": is_after_deadline,
                "solved_after_deadline": solved_after_deadline,
                "problems": problems_map,
            },
        }

    # ── Page Rendering ────────────────────────────────────────

    def get_render_data(
        self,
        task: Any,
        assignments: List[StudentTask],
        student_map: Dict[int, User],
        session: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate problem list with cohort solve statistics for CF_SHEET."""
        import re

        total_assigned = len(assignments)
        sheet_problems = []

        active_student_id = kwargs.get("target_student_id")
        current_user = kwargs.get("current_user")
        if active_student_id is None and current_user:
            active_student_id = current_user.id

        user_solved_set = set()
        if active_student_id:
            user_a = next((a for a in assignments if a.student_id == active_student_id), None)
            if user_a:
                res = user_a.checker_result or {}
                for p_code in (res.get("solved", []) or []) + (res.get("solved_problems", []) or []):
                    user_solved_set.add(str(p_code).strip().upper())
                for p_code, p_info in (res.get("problems", {}) or {}).items():
                    if isinstance(p_info, dict) and p_info.get("solved") is True:
                        user_solved_set.add(str(p_code).strip().upper())

        for prob in self.problems:
            solved_for_prob = 0
            for a in assignments:
                res = a.checker_result or {}
                prob_info = res.get("problems", {}).get(prob, {})
                if (
                    prob_info.get("solved") is True
                    or prob in res.get("solved", [])
                    or prob in res.get("solved_problems", [])
                ):
                    solved_for_prob += 1

            solve_pct = (
                round((solved_for_prob / total_assigned) * 100) if total_assigned > 0 else 0
            )

            match = re.match(r"^(\d+)([A-Za-z]\d*)$", prob.strip())
            link = (
                f"https://codeforces.com/problemset/problem/{match.group(1)}/{match.group(2)}"
                if match
                else f"https://codeforces.com/problemset?search={prob.strip()}"
            )

            sheet_problems.append({
                "code": prob,
                "link": link,
                "solved_count": solved_for_prob,
                "total_assigned": total_assigned,
                "solve_pct": solve_pct,
                "user_solved": prob.strip().upper() in user_solved_set,
            })

        return {
            "sheet_problems": sheet_problems,
            "min_solved_required": self.min_solved_count,
        }
