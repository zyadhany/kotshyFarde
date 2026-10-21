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
from typing import Any, Dict

from app.domain.codeforces.base import CodeforcesBaseTask
from app.models.student import Student
from app.models.student_task import StudentTask
from app.services.codeforces_api import get_contest_problems_status

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
    ) -> None:
        if access_type not in _VALID_ACCESS_TYPES:
            raise ValueError(
                f"Invalid access_type {access_type!r}. "
                f"Must be one of {_VALID_ACCESS_TYPES}"
            )
        self.contest_id = contest_id
        self.min_solved = min_solved
        self.access_type = access_type

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

    def check(self, student: Student, student_task: StudentTask, **kwargs: Any) -> Dict[str, Any]:
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
