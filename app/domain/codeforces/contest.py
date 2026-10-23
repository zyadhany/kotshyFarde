"""
app/domain/codeforces/contest.py
────────────────────────────────
Checker for **CF_CONTEST** tasks — verify how many problems a student solved
in a given Codeforces contest.

Supports three access modes:
  • ``public``            — unauthenticated API calls.
  • ``private_managed``   — signed requests via CF_API_KEY / CF_API_SECRET.
  • ``private_restricted``— reserved stub (raises ``NotImplementedError``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.domain.codeforces.base import CodeforcesBaseTask
from app.models.student_task import StudentTask
from app.models.user import User
from app.services.codeforces_api import (
    get_contest_problems,
    get_contest_problems_status,
)

logger = logging.getLogger(__name__)

_VALID_ACCESS_TYPES = {"public", "private_managed", "private_restricted"}


class CodeforcesContestTask(CodeforcesBaseTask):
    """Domain checker for a single-contest assignment."""

    task_type: str = "CF_CONTEST"

    def __init__(
        self,
        contest_id: int,
        min_solved: int,
        access_type: str = "public",
        problems: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        if access_type not in _VALID_ACCESS_TYPES:
            raise ValueError(
                f"Invalid access_type {access_type!r}. "
                f"Must be one of {_VALID_ACCESS_TYPES}"
            )
        self.contest_id = contest_id
        self.min_solved = min_solved
        self.access_type = access_type
        self._problems: Optional[List[Dict[str, str]]] = problems

    # ── Problem List & Generation ─────────────────────────────

    def generate_problems(self) -> List[Dict[str, str]]:
        """Fetch and populate the list containing index and name of all contest problems
        using ``get_contest_problems`` from ``codeforces_api``."""
        use_auth = self.access_type == "private_managed"
        self._problems = get_contest_problems(contest_id=self.contest_id, use_auth=use_auth)
        return self._problems

    # Alias for generate_problems
    fetch_problems = generate_problems

    @property
    def problems(self) -> List[Dict[str, str]]:
        """List containing index and name of all problems in the contest.

        Getter logic:
        - If null (None), generates it using codeforces_api.
        - Otherwise, returns it directly.
        """
        if self._problems is None:
            return self.generate_problems()
        return self._problems

    @problems.setter
    def problems(self, value: Optional[List[Dict[str, str]]]) -> None:
        self._problems = value

    def get_problems(self) -> List[Dict[str, str]]:
        """Getter for contest problems list.

        If null (None), generates it using codeforces_api; otherwise returns it directly.
        """
        if self.problems is None:
            self.generate_problems()
        return self.problems

    # ── Serialisation ─────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "contest_id": self.contest_id,
            "min_solved": self.min_solved,
            "access_type": self.access_type,
        }
        if self._problems is not None:
            data["problems"] = self._problems
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeforcesContestTask":
        return cls(
            contest_id=int(data["contest_id"]),
            min_solved=int(data.get("min_solved", 0)),
            access_type=data.get("access_type", "public"),
            problems=data.get("problems"),
        )

    # ── Verification ──────────────────────────────────────────

    def check(self, student: User, student_task: StudentTask, **kwargs: Any) -> Dict[str, Any]:
        """Query the CF API for the student's contest participation and compare
        against ``min_solved``.

        Returns
        -------
        dict
            ``{"status": ..., "details": {<contest_problems_status>}}``
        """
        handle = student.cf_handle
        if not handle:
            return {
                "status": "failed",
                "details": {"error": "Student has no Codeforces handle configured."},
            }

        # Determine auth requirement
        if self.access_type == "private_restricted":
            raise NotImplementedError(
                "private_restricted access is reserved for a future phase."
            )

        use_auth = self.access_type == "private_managed"

        deadline = getattr(student_task, "deadline", None)
        status_info = get_contest_problems_status(
            handle=handle,
            contest_id=self.contest_id,
            use_auth=use_auth,
            deadline=deadline,
        )

        solved_count = status_info.get("solved_count", 0)
        required = self.min_solved
        after_deadline = status_info.get("after_deadline", False)

        if solved_count >= required:
            status = "late" if after_deadline else "completed"
        elif solved_count > 0:
            status = "in_progress"
        else:
            status = "pending"

        return {
            "status": status,
            "after_deadline": after_deadline,
            "details": status_info,
        }

    # ── Page Rendering ────────────────────────────────────────

    def get_render_data(
        self,
        task: Any,
        assignments: List[StudentTask],
        student_map: Dict[int, User],
        session: Any = None,
        current_user: Optional[User] = None,
        target_student_id: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate problems list and standings matrix for CF_CONTEST."""
        raw_problems = self.problems or []
        # If problems list not in task config or instance, attempt to fetch using CF API
        if not raw_problems and self.contest_id:
            try:
                raw_problems = self.generate_problems()
                if raw_problems and task and hasattr(task, "config") and session:
                    task.config = {**task.config, "problems": raw_problems}
                    session.add(task)
                    session.commit()
                    session.refresh(task)
            except Exception:
                pass

        # If still empty, check student checker results for problem keys
        if not raw_problems:
            discovered_indices = set()
            for a in assignments:
                res = a.checker_result or {}
                for p_idx in res.get("per_problem", {}).keys():
                    discovered_indices.add(p_idx)
                for p_idx in res.get("solved_problems", []):
                    discovered_indices.add(p_idx)
            if discovered_indices:
                raw_problems = [{"index": idx, "name": f"Problem {idx}"} for idx in sorted(discovered_indices)]
            else:
                raw_problems = [{"index": idx, "name": f"Problem {idx}"} for idx in ["A", "B", "C", "D", "E"]]

        # Determine target user for "solved by user" indicator
        active_student_id = target_student_id
        if active_student_id is None and current_user:
            active_student_id = current_user.id

        # Fallback for coach view when only 1 student is enrolled
        if active_student_id is None and len(assignments) == 1:
            active_student_id = assignments[0].student_id

        user_solved_indices: set[str] = set()
        if active_student_id:
            user_assignment = next(
                (a for a in assignments if a.student_id == active_student_id), None
            )
            if user_assignment:
                res = user_assignment.checker_result or {}
                per_prob = res.get("per_problem", {})
                solved_list = res.get("solved_problems", [])
                for p_idx, p_data in per_prob.items():
                    if isinstance(p_data, dict) and p_data.get("solved") is True:
                        user_solved_indices.add(str(p_idx).upper())
                for p_idx in solved_list:
                    user_solved_indices.add(str(p_idx).upper())

        # Normalize problem objects
        normalized_problems = []
        for item in raw_problems:
            if isinstance(item, dict):
                idx = str(item.get("index", "")).upper()
                name = item.get("name") or f"Problem {idx}"
            else:
                idx = str(item).upper()
                name = f"Problem {idx}"
            link = f"https://codeforces.com/contest/{self.contest_id}/problem/{idx}" if self.contest_id else "#"
            normalized_problems.append({
                "index": idx,
                "name": name,
                "link": link,
                "user_solved": idx in user_solved_indices,
            })

        # Calculate solve counts for each problem across all assigned students
        for p in normalized_problems:
            p_idx = p["index"]
            solved_students = 0
            for a in assignments:
                res = a.checker_result or {}
                per_prob = res.get("per_problem", {})
                solved_list = res.get("solved_problems", [])
                if per_prob.get(p_idx, {}).get("solved") is True or p_idx in solved_list:
                    solved_students += 1
            p["solved_count"] = solved_students
            p["total_assigned"] = len(assignments)
            p["solve_pct"] = round((solved_students / len(assignments)) * 100) if assignments else 0

        contest_problems = normalized_problems
        total_cohort_solves = sum(p["solved_count"] for p in contest_problems)

        # Build Standings rows (Student row with each problem column result)
        contest_standings = []
        for a in assignments:
            student = student_map.get(a.student_id)
            if not student:
                continue
            res = a.checker_result or {}
            per_prob = res.get("per_problem", {})
            solved_list = res.get("solved_problems", [])
            solved_count = res.get("solved_count", len(solved_list) if solved_list else 0)

            # Build cell status for each problem in contest_problems
            problem_cells = []
            for p in contest_problems:
                p_idx = p["index"]
                prob_info = per_prob.get(p_idx, {})
                is_solved = prob_info.get("solved") is True or p_idx in solved_list
                attempts = prob_info.get("attempts", 1 if is_solved else 0)
                after_deadline = prob_info.get("after_deadline", False)

                problem_cells.append({
                    "index": p_idx,
                    "solved": is_solved,
                    "attempts": attempts,
                    "after_deadline": after_deadline,
                })

            contest_standings.append({
                "student": student,
                "assignment": a,
                "solved_count": solved_count,
                "problem_cells": problem_cells,
                "is_current_user": bool(current_user and current_user.id == student.id),
                "is_selected_student": bool(active_student_id and active_student_id == student.id),
            })

        # Sort standings: solved_count descending
        contest_standings.sort(key=lambda r: r["solved_count"], reverse=True)
        for rank, row in enumerate(contest_standings, start=1):
            row["rank"] = rank

        return {
            "contest_problems": contest_problems,
            "contest_standings": contest_standings,
            "contest_participants": contest_standings,
            "total_cohort_solves": total_cohort_solves,
            "user_solved_indices": list(user_solved_indices),
            "selected_student_id": active_student_id,
        }
