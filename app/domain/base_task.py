"""
app/domain/base_task.py
───────────────────────
Abstract Base Class that every task checker must implement.

The contract enforces:
  • Serialisation  → ``to_dict()`` / ``from_dict()``
  • Verification   → ``check(student, student_task)``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.student import Student
    from app.models.student_task import StudentTask


class BaseTask(ABC):
    """Root of the task-checker hierarchy."""

    # Every concrete subclass MUST set this to its discriminator string.
    task_type: str = ""

    # ── Serialisation ─────────────────────────────────────────

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialise the task's configuration to a JSON-compatible dict."""
        ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseTask":
        """Reconstruct a task instance from a configuration dict."""
        ...

    # ── Verification ──────────────────────────────────────────

    @abstractmethod
    def check(self, student: "Student", student_task: "StudentTask", **kwargs: Any) -> Dict[str, Any]:
        """Run the verification logic for a student assignment.

        Returns
        -------
        dict
            ``{"status": "completed"|"in_progress"|"pending"|"failed", "details": {...}}``
        """
        ...

    # ── Page Rendering ────────────────────────────────────────

    def get_render_data(
        self,
        task: Any,
        assignments: List["StudentTask"],
        student_map: Dict[int, "Student"],
        session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Generate task-type specific template context data for task detail view."""
        return {}
