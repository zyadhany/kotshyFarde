"""
app/domain/codeforces/base.py
─────────────────────────────
Shared base class for all Codeforces-specific task checkers.
Houses common parsing / validation helpers that subclasses inherit.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.domain.base_task import BaseTask
from app.services.codeforces_api import parse_problem_id, verify_handle

logger = logging.getLogger(__name__)


class CodeforcesBaseTask(BaseTask):
    """Intermediate ABC for Codeforces tasks.

    Provides shared utilities; concrete checkers (Sheet / Contest) implement
    the remaining abstract methods.
    """

    @staticmethod
    def validate_handle(handle: str | None) -> bool:
        """Check that a CF handle is non-empty and resolves to a real account."""
        if not handle:
            logger.warning("No Codeforces handle provided.")
            return False
        return verify_handle(handle)

    @staticmethod
    def split_problem(problem_str: str) -> tuple[int, str]:
        """Convenience wrapper around ``parse_problem_id``."""
        return parse_problem_id(problem_str)

    # ── Serialisation stubs (enforced on subclasses) ──────────

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeforcesBaseTask":
        raise NotImplementedError

    def check(self, student, student_task, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
