"""
app/domain/cses/base.py
───────────────────────
Shared base class for all CSES-specific task checkers.
Defines common CSES helpers and URL builders.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.domain.base_task import BaseTask

logger = logging.getLogger(__name__)


class CSESBaseTask(BaseTask):
    """Intermediate ABC for CSES tasks."""

    @staticmethod
    def validate_cses_id(cses_id: Optional[str]) -> bool:
        """Verify that a CSES ID is non-empty and valid format."""
        if not cses_id or not str(cses_id).strip():
            logger.warning("No CSES user ID configured.")
            return False
        return True

    @staticmethod
    def build_problem_url(problem_id: str | int) -> str:
        """Construct canonical CSES problem URL."""
        return f"https://cses.fi/problemset/task/{problem_id}"

    @staticmethod
    def build_user_url(cses_id: str | int) -> str:
        """Construct canonical CSES user profile URL."""
        return f"https://cses.fi/user/{cses_id}"

    # ── Serialisation stubs (enforced on concrete subclasses) ──

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CSESBaseTask":
        raise NotImplementedError

    def check(self, student, student_task=None, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
