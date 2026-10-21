from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import os
from pathlib import Path

# Add project root to sys.path so direct invocation (python3 app/main.py) works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_session, init_db
from app.domain.codeforces.sheet import CodeforcesSheetTask
from app.domain.factory import TaskFactory
from app.models.student import Student
from app.models.student_task import StudentTask
from app.models.task import Task

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kotchy")

_SEPARATOR = "═" * 60


def _pretty_json(obj: dict) -> str:
    return json.dumps(obj, indent=2, default=str)


def main() -> None:
    s1 = Student(
        username="zyadhany",
        email="[EMAIL_ADDRESS]",
        password_hash="pbkdf2:sha256:placeholder",
        cf_handle="zyadhany",
        description="Test student seeded for local verification.",
    )
        
    task1 = CodeforcesSheetTask(
        problems=["158A", "71A", "590E"],
        min_solved_count=2,
    )

    st = StudentTask(
        student_id=1,
        task_id=1,
        start_date=datetime.now(timezone.utc) - timedelta(days=30),
        deadline=datetime.now(timezone.utc) + timedelta(days=7),
    )

    ret = task1.check(s1, st)
    print(_pretty_json(ret))
    
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
