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
        **kwargs: Any,
    ) -> None:
        if access_type not in _VALID_ACCESS_TYPES:
            raise ValueError(
                f"Invalid access_type {access_type!r}. "
                f"Must be one of {_VALID_ACCESS_TYPES}"
            )
        self.contest_id = contest_id
        self.min_solved = min_solved
        self.access_type = access_type

    # ── Problem List & Generation ─────────────────────────────

    def generate_problems(self) -> List[Dict[str, str]]:
        """Fetch the list containing index and name of all contest problems
        directly from Codeforces service using ``get_contest_problems``."""
        use_auth = self.access_type == "private_managed"
        return get_contest_problems(contest_id=self.contest_id, use_auth=use_auth)

    # Aliases
    fetch_problems = generate_problems
    get_problems = generate_problems

    @property
    def problems(self) -> List[Dict[str, str]]:
        """List containing index and name of all problems in the contest,
        retrieved directly from Codeforces service."""
        return self.get_problems()

    # ── Serialisation ─────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contest_id": self.contest_id,
            "min_solved": self.min_solved,
            "access_type": self.access_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeforcesContestTask":
        return cls(
            contest_id=int(data["contest_id"]),
            min_solved=int(data.get("min_solved", 0)),
            access_type=data.get("access_type", "public"),
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
        if required == 0:
            try:
                problems = self.get_problems()
            except Exception:
                problems = None
            required = len(problems) if problems else 0
            if required == 0:
                required = status_info.get("total_problems") or len(status_info.get("per_problem") or {})
        after_deadline = status_info.get("after_deadline", False)

        if required > 0 and solved_count >= required:
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
        # 1. Resolve which student's solves to highlight
        active_student_id = target_student_id
        if active_student_id is None and current_user and current_user.is_student():
            active_student_id = current_user.id
        elif active_student_id is None and len(assignments) == 1:
            active_student_id = assignments[0].student_id

        # 2. Extract active student's solved and attempted problem indices
        user_solved_indices: set[str] = set()
        user_attempts_map: Dict[str, int] = {}
        if active_student_id:
            user_a = next((a for a in assignments if a.student_id == active_student_id), None)
            if user_a and user_a.checker_result:
                res = user_a.checker_result
                user_solved_indices = {str(p).upper() for p in res.get("solved_problems", [])}
                for p_idx, p_data in res.get("per_problem", {}).items():
                    idx_upper = str(p_idx).upper()
                    if isinstance(p_data, dict):
                        if p_data.get("solved") is True:
                            user_solved_indices.add(idx_upper)
                        attempts = p_data.get("attempts", 0)
                        if attempts > 0:
                            user_attempts_map[idx_upper] = attempts

        # 3. Retrieve or discover problem list
        raw_problems = self.get_problems() or []
        if not raw_problems:
            discovered: set[str] = set()
            for a in assignments:
                res = a.checker_result or {}
                discovered.update(res.get("per_problem", {}).keys())
                discovered.update(res.get("solved_problems", []))
            indices = sorted(discovered) if discovered else ["A", "B", "C", "D", "E"]
            raw_problems = [{"index": idx, "name": f"Problem {idx}"} for idx in indices]

        # 4. Count solves per problem across all assignments
        total_assigned = len(assignments)
        solve_counts: Dict[str, int] = {}
        for a in assignments:
            res = a.checker_result or {}
            solved_set = {str(p).upper() for p in res.get("solved_problems", [])}
            for p_idx, p_data in res.get("per_problem", {}).items():
                if isinstance(p_data, dict) and p_data.get("solved") is True:
                    solved_set.add(str(p_idx).upper())
            for idx in solved_set:
                solve_counts[idx] = solve_counts.get(idx, 0) + 1

        # 5. Build normalized problem objects with solve statistics
        contest_problems: List[Dict[str, Any]] = []
        for item in raw_problems:
            idx = str(item.get("index") if isinstance(item, dict) else item).upper()
            name = (item.get("name") if isinstance(item, dict) else None) or f"Problem {idx}"
            link = f"https://codeforces.com/contest/{self.contest_id}/problem/{idx}" if self.contest_id else "#"
            solves = solve_counts.get(idx, 0)
            is_solved = idx in user_solved_indices
            attempts = user_attempts_map.get(idx, 0)
            is_attempted_unsolved = (not is_solved) and (attempts > 0)

            contest_problems.append({
                "index": idx,
                "name": name,
                "link": link,
                "user_solved": is_solved,
                "user_attempted_unsolved": is_attempted_unsolved,
                "user_wrong_answer": is_attempted_unsolved,
                "user_attempts": attempts,
                "solved_count": solves,
                "total_assigned": total_assigned,
                "solve_pct": round((solves / total_assigned) * 100) if total_assigned else 0,
            })

        # 6. Build standings rows for each assigned student
        contest_standings: List[Dict[str, Any]] = []
        for a in assignments:
            student = student_map.get(a.student_id)
            if not student:
                continue

            res = a.checker_result or {}
            per_prob = {str(k).upper(): v for k, v in (res.get("per_problem") or {}).items()}
            solved_list = {str(p).upper() for p in res.get("solved_problems", [])}
            solved_count = res.get("solved_count", len(solved_list))

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

        # 7. Sort standings by solved_count descending and assign ranks
        contest_standings.sort(key=lambda r: r["solved_count"], reverse=True)
        for rank, row in enumerate(contest_standings, start=1):
            row["rank"] = rank

        return {
            "contest_problems": contest_problems,
            "contest_standings": contest_standings,
            "contest_participants": contest_standings,
            "total_cohort_solves": sum(p["solved_count"] for p in contest_problems),
            "user_solved_indices": list(user_solved_indices),
            "user_wrong_answer_indices": [p["index"] for p in contest_problems if p["user_attempted_unsolved"]],
            "selected_student_id": active_student_id,
        }


