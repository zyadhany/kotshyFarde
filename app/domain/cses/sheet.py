"""
app/domain/cses/sheet.py
────────────────────────
Domain checker for **CSES_SHEET** tasks — a curated list of CSES Problem Set tasks
that a student must solve (at least ``min_solved_count``).
Supports incremental diff checking and dynamic problem metadata resolution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.cses.base import CSESBaseTask
from app.models.student_task import StudentTask
from app.models.user import User
from app.services import cses_api

logger = logging.getLogger(__name__)


class CSESSheetTask(CSESBaseTask):
    """Domain checker for a CSES Problem Set sheet assignment."""

    task_type: str = "CSES_SHEET"
    TASK_TYPE: str = "CSES_SHEET"

    def __init__(self, problems: List[str | int], min_solved_count: Optional[int] = None) -> None:
        self.problems = [str(p).strip() for p in problems if str(p).strip()]
        self.min_solved_count = (
            int(min_solved_count)
            if min_solved_count is not None
            else len(self.problems)
        )
        self.min_solved = self.min_solved_count

    # ── Serialisation ─────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problems": self.problems,
            "min_solved_count": self.min_solved_count,
            "min_solved": self.min_solved_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CSESSheetTask":
        problems = data.get("problems", [])
        raw_min = data.get("min_solved_count", data.get("min_solved"))
        min_solved = int(raw_min) if raw_min is not None else None
        return cls(problems=problems, min_solved_count=min_solved)

    # ── Problem Metadata Helper ───────────────────────────────

    def get_problems_metadata(self) -> List[Dict[str, Any]]:
        """Return enriched metadata for all sheet problems (ID, Name, and URL)."""
        metadata = cses_api.get_problems_metadata(self.problems)
        enriched: List[Dict[str, Any]] = []
        for pid in self.problems:
            item = metadata.get(
                pid,
                {
                    "id": pid,
                    "name": f"CSES #{pid}",
                    "url": self.build_problem_url(pid),
                },
            )
            enriched.append(item)
        return enriched

    # ── Verification ──────────────────────────────────────────

    def check(
        self,
        student: User,
        student_task: Optional[StudentTask] = None,
        session: Any = None,
        previous_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Verify student solved tasks on CSES.

        Supports incremental diff checking using previous checker_result:
        - Reads previously solved tasks.
        - Only checks tasks that were not solved previously.
        - If all problems are already solved, skips network requests entirely.
        """
        cses_id = getattr(student, "cses_id", None)
        if not cses_id or not str(cses_id).strip():
            logger.warning("Student %s has no CSES ID configured.", getattr(student, "username", "Unknown"))
            return {
                "status": "failed",
                "after_deadline": False,
                "details": {
                    "error": "Student has no CSES ID configured.",
                    "solved": [],
                    "unsolved": list(self.problems),
                    "solved_count": 0,
                    "required": self.min_solved_count,
                    "last_checked_at": datetime.now(timezone.utc).isoformat(),
                    "problems": {
                        p: {
                            "id": p,
                            "name": cses_api.get_problem_name(p),
                            "solved": False,
                            "url": self.build_problem_url(p),
                        }
                        for p in self.problems
                    },
                },
            }

        # 1. Determine previously solved problems
        if previous_result is None and student_task is not None:
            previous_result = getattr(student_task, "checker_result", None)

        prev_details = (previous_result or {})
        prev_solved_list = prev_details.get("solved", []) or prev_details.get("solved_problems", []) or []
        previously_solved: set[str] = set(str(p).strip() for p in prev_solved_list if str(p).strip())

        # Also inspect previous problems dictionary if present
        for pid, pdata in (prev_details.get("problems", {}) or {}).items():
            if isinstance(pdata, dict) and pdata.get("solved") is True:
                previously_solved.add(str(pid).strip())

        # 2. Determine unsolved problems that still require checking
        unsolved_to_check = [p for p in self.problems if p not in previously_solved]

        now_iso = datetime.now(timezone.utc).isoformat()

        # 3. Fast path: If all problems are already solved, return immediately without network calls
        if not unsolved_to_check and len(self.problems) > 0:
            logger.info("Student %s already solved all %d tasks; skipping network call.", student.username, len(self.problems))
            problems_map = {}
            for p in self.problems:
                problems_map[p] = {
                    "id": p,
                    "name": cses_api.get_problem_name(p),
                    "solved": True,
                    "url": self.build_problem_url(p),
                }

            return {
                "status": "completed",
                "after_deadline": prev_details.get("after_deadline", False),
                "details": {
                    "solved": list(self.problems),
                    "unsolved": [],
                    "solved_count": len(self.problems),
                    "required": self.min_solved_count,
                    "last_checked_at": now_iso,
                    "problems": problems_map,
                },
            }

        # 4. Perform check for remaining problems
        try:
            check_res = cses_api.check_user_solved_problems(student, unsolved_to_check)
            newly_solved = set(check_res.get("solved", []))
        except Exception as exc:
            logger.error("Error checking CSES tasks for user %s: %s", student.username, exc)
            return {
                "status": "failed",
                "after_deadline": False,
                "details": {
                    "error": f"CSES check failed: {exc}",
                    "solved": list(previously_solved),
                    "unsolved": unsolved_to_check,
                    "solved_count": len(previously_solved),
                    "required": self.min_solved_count,
                    "last_checked_at": now_iso,
                },
            }

        # 5. Merge results
        all_solved = [p for p in self.problems if p in previously_solved or p in newly_solved]
        remaining_unsolved = [p for p in self.problems if p not in all_solved]
        solved_count = len(all_solved)

        # 6. Status calculation
        if solved_count >= self.min_solved_count:
            status = "completed"
        elif solved_count > 0:
            status = "in_progress"
        else:
            status = "pending"

        # 7. Build detailed problem breakdown map
        problems_map = {}
        for p in self.problems:
            is_solved = p in all_solved
            problems_map[p] = {
                "id": p,
                "name": cses_api.get_problem_name(p),
                "solved": is_solved,
                "url": self.build_problem_url(p),
            }

        return {
            "status": status,
            "after_deadline": False,
            "details": {
                "solved": all_solved,
                "unsolved": remaining_unsolved,
                "solved_count": solved_count,
                "required": self.min_solved_count,
                "last_checked_at": now_iso,
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
        """Generate problem list with cohort solve statistics for CSES_SHEET."""
        total_assigned = len(assignments)
        sheet_problems = []

        active_student_id = kwargs.get("target_student_id")
        current_user = kwargs.get("current_user")
        if active_student_id is None and current_user:
            active_student_id = current_user.id

        user_solved_set: set[str] = set()
        if active_student_id:
            user_a = next((a for a in assignments if a.student_id == active_student_id), None)
            if user_a:
                res = user_a.checker_result or {}
                for p_code in (res.get("solved", []) or []) + (res.get("solved_problems", []) or []):
                    user_solved_set.add(str(p_code).strip())
                for p_code, p_info in (res.get("problems", {}) or {}).items():
                    if isinstance(p_info, dict) and p_info.get("solved") is True:
                        user_solved_set.add(str(p_code).strip())

        for prob in self.problems:
            pid = str(prob).strip()
            name = cses_api.get_problem_name(pid)
            url = self.build_problem_url(pid)

            solved_for_prob = 0
            for a in assignments:
                res = a.checker_result or {}
                prob_info = res.get("problems", {}).get(pid, {})
                if (
                    prob_info.get("solved") is True
                    or pid in res.get("solved", [])
                    or pid in res.get("solved_problems", [])
                ):
                    solved_for_prob += 1

            solve_pct = (
                round((solved_for_prob / total_assigned) * 100) if total_assigned > 0 else 0
            )

            sheet_problems.append({
                "code": pid,
                "id": pid,
                "name": name,
                "link": url,
                "url": url,
                "solved_count": solved_for_prob,
                "total_assigned": total_assigned,
                "solve_pct": solve_pct,
                "user_solved": pid in user_solved_set,
            })

        return {
            "sheet_problems": sheet_problems,
            "min_solved_required": self.min_solved_count,
        }
