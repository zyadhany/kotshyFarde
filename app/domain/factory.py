"""
app/domain/factory.py
─────────────────────
``TaskFactory`` — maps ``task_type`` discriminator strings stored in the DB
to the correct domain checker class, then hydrates via ``from_dict(config)``.
"""

from __future__ import annotations

from typing import Any, Dict, Type

from app.domain.base_task import BaseTask
from app.domain.codeforces.contest import CodeforcesContestTask
from app.domain.codeforces.sheet import CodeforcesSheetTask
from app.domain.cses.sheet import CSESSheetTask

# ── Registry ──────────────────────────────────────────────────
_REGISTRY: Dict[str, Type[BaseTask]] = {
    "CF_SHEET": CodeforcesSheetTask,
    "CF_CONTEST": CodeforcesContestTask,
    "CSES_SHEET": CSESSheetTask,
    # Future: "VJUDGE_CONTEST": ..., "MANUAL": ...
}


class TaskFactory:
    """Instantiate the proper domain checker from a stored task record."""

    @staticmethod
    def create(task_type: str, config: Dict[str, Any]) -> BaseTask:
        """Look up *task_type* in the registry and call ``from_dict(config)``.

        Raises
        ------
        ValueError
            If no checker class is registered for the given ``task_type``.
        """
        cls = _REGISTRY.get(task_type)
        if cls is None:
            raise ValueError(
                f"Unknown task_type {task_type!r}. "
                f"Registered types: {sorted(_REGISTRY)}"
            )
        return cls.from_dict(config)
