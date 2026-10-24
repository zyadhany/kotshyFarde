"""
tests/test_contest_task.py
──────────────────────────
Unit tests for Codeforces contest problem list generation and getter behavior
in CodeforcesContestTask and codeforces_api.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.domain.codeforces.contest import CodeforcesContestTask
from app.services.codeforces_api import get_contest_problems


# ── Service Tests ─────────────────────────────────────────────

def test_get_contest_problems_success():
    """Verify get_contest_problems extracts index and name correctly."""
    mock_standings = {
        "problems": [
            {"contestId": 1878, "index": "A", "name": "How Much Does Daytona Cost?", "type": "PROGRAMMING"},
            {"contestId": 1878, "index": "B", "name": "Aleksa and Stack", "type": "PROGRAMMING"},
            {"contestId": 1878, "index": "C", "name": "Vasilije in Cacak", "type": "PROGRAMMING"},
        ]
    }
    with patch("app.services.codeforces_api._request", return_value=mock_standings) as mock_req:
        problems = get_contest_problems(1878, use_auth=False)
        mock_req.assert_called_once_with(
            "contest.standings",
            {"contestId": "1878"},
            use_auth=False,
        )
        assert len(problems) == 3
        assert problems[0] == {"index": "A", "name": "How Much Does Daytona Cost?"}
        assert problems[1] == {"index": "B", "name": "Aleksa and Stack"}
        assert problems[2] == {"index": "C", "name": "Vasilije in Cacak"}


def test_get_contest_problems_handles_api_error():
    """Verify get_contest_problems returns empty list gracefully on error."""
    with patch("app.services.codeforces_api._request", side_effect=RuntimeError("Contest not found")):
        problems = get_contest_problems(999999)
        assert problems == []


def test_get_contest_problems_in_memory_caching():
    """Verify get_contest_problems caches results across repeated calls."""
    from app.services.codeforces_api import clear_contest_problems_cache

    clear_contest_problems_cache()
    mock_standings = {
        "problems": [
            {"contestId": 9991, "index": "A", "name": "Problem Alpha", "type": "PROGRAMMING"},
        ]
    }
    with patch("app.services.codeforces_api._request", return_value=mock_standings) as mock_req:
        res1 = get_contest_problems(9991, use_auth=False)
        assert len(res1) == 1
        assert mock_req.call_count == 1

        # Second call: must return from in-memory cache without calling _request
        res2 = get_contest_problems(9991, use_auth=False)
        assert res2 == res1
        assert mock_req.call_count == 1

    clear_contest_problems_cache()



# ── Domain Task Tests ─────────────────────────────────────────

def test_contest_task_direct_problem_getter_from_service():
    """Verify that get_problems(), problems property, and generate_problems()
    directly retrieve problems from codeforces_api."""
    task = CodeforcesContestTask(contest_id=1234, min_solved=2, access_type="public")

    mock_problems = [
        {"index": "A", "name": "Problem Alpha"},
        {"index": "B", "name": "Problem Beta"},
    ]

    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=mock_problems) as mock_get:
        # 1. get_problems calls codeforces_api directly
        first_result = task.get_problems()
        assert first_result == mock_problems
        mock_get.assert_called_with(contest_id=1234, use_auth=False)

        # 2. Accessing via .problems property also delegates directly
        property_result = task.problems
        assert property_result == mock_problems

        # 3. generate_problems also delegates directly
        assert task.generate_problems() == mock_problems


def test_contest_task_serialization_lean_without_storing_problems():
    """Verify to_dict does not store problems list, and from_dict hydrates cleanly."""
    task = CodeforcesContestTask(contest_id=100, min_solved=2, access_type="public")

    serialized = task.to_dict()
    assert serialized == {
        "contest_id": 100,
        "min_solved": 2,
        "access_type": "public",
    }
    assert "problems" not in serialized

    # from_dict hydrates properly even if legacy data contained problems
    legacy_data = {
        "contest_id": 100,
        "min_solved": 2,
        "access_type": "public",
        "problems": [{"index": "A", "name": "Legacy"}],
    }
    hydrated = CodeforcesContestTask.from_dict(legacy_data)
    assert hydrated.contest_id == 100
    assert hydrated.min_solved == 2
    assert hydrated.access_type == "public"
    assert not hasattr(hydrated, "_problems")


def test_contest_task_check_min_solved_zero_uses_problem_count():
    """When min_solved is 0, the check method requires solving all problems from get_problems()."""
    from app.models.user import User
    from app.models.student_task import StudentTask

    student = User(username="testuser", email="test@kotchy.dev", hashed_password="pw", cf_handle="tourist")
    student_task = StudentTask(task_id=1, student_id=1)

    problems = [
        {"index": "A", "name": "Problem A"},
        {"index": "B", "name": "Problem B"},
        {"index": "C", "name": "Problem C"},
    ]
    task = CodeforcesContestTask(contest_id=1000, min_solved=0)

    with patch.object(task, "get_problems", return_value=problems):
        # 1. Solved all 3 problems -> completed
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {"solved_count": 3, "after_deadline": False}
            res = task.check(student, student_task)
            assert res["status"] == "completed"

        # 2. Solved 2 problems out of 3 -> in_progress
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {"solved_count": 2, "after_deadline": False}
            res = task.check(student, student_task)
            assert res["status"] == "in_progress"

        # 3. Solved 0 problems -> pending
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {"solved_count": 0, "after_deadline": False}
            res = task.check(student, student_task)
            assert res["status"] == "pending"

        # 4. Solved all 3 after deadline -> late
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {"solved_count": 3, "after_deadline": True}
            res = task.check(student, student_task)
            assert res["status"] == "late"


def test_contest_task_get_render_data_uses_get_problems():
    """Verify get_render_data uses get_problems directly."""
    task_obj = MagicMock()
    task_obj.config = {"contest_id": 1234}
    task = CodeforcesContestTask(contest_id=1234, min_solved=1)

    mock_problems = [{"index": "A", "name": "Problem Alpha"}]
    with patch.object(task, "get_problems", return_value=mock_problems) as mock_gp:
        data = task.get_render_data(task=task_obj, assignments=[], student_map={})
        mock_gp.assert_called_once()
        assert len(data["contest_problems"]) == 1
        assert data["contest_problems"][0]["index"] == "A"


def test_contest_task_check_min_solved_zero_fallback_to_status_info():
    """When min_solved is 0 and get_problems() is empty, check falls back to status_info total_problems."""
    from app.models.user import User
    from app.models.student_task import StudentTask

    student = User(username="testuser", email="test@kotchy.dev", hashed_password="pw", cf_handle="tourist")
    student_task = StudentTask(task_id=1, student_id=1)

    task = CodeforcesContestTask(contest_id=2000, min_solved=0)

    # get_problems fails / returns empty list
    with patch.object(task, "get_problems", return_value=[]):
        # 1. Fallback to status_info["total_problems"] = 4, solved 4 -> completed
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {
                "total_problems": 4,
                "solved_count": 4,
                "after_deadline": False,
            }
            res = task.check(student, student_task)
            assert res["status"] == "completed"

        # 2. Fallback to status_info["total_problems"] = 4, solved 2 -> in_progress
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {
                "total_problems": 4,
                "solved_count": 2,
                "after_deadline": False,
            }
            res = task.check(student, student_task)
            assert res["status"] == "in_progress"

        # 3. total_problems is None, fallback to len(per_problem) = 3
        with patch("app.domain.codeforces.contest.get_contest_problems_status") as mock_status:
            mock_status.return_value = {
                "total_problems": None,
                "per_problem": {"A": {}, "B": {}, "C": {}},
                "solved_count": 3,
                "after_deadline": False,
            }
            res = task.check(student, student_task)
            assert res["status"] == "completed"


def test_contest_task_render_data_wrong_answer_highlight():
    """Verify that problems with unsuccessful attempts (wrong answer) are identified and marked."""
    from app.models.user import User
    from app.models.student_task import StudentTask

    student = User(id=42, username="wa_student", email="wa@example.com", hashed_password="pw", role="student")
    task_obj = MagicMock()
    task_obj.config = {"contest_id": 1234}
    task = CodeforcesContestTask(contest_id=1234, min_solved=2)

    assignment = StudentTask(id=101, task_id=1, student_id=42, status="in_progress")
    assignment.checker_result = {
        "contest_id": 1234,
        "solved_count": 1,
        "solved_problems": ["A"],
        "per_problem": {
            "A": {"solved": True, "attempts": 2, "after_deadline": False},
            "B": {"solved": False, "attempts": 3, "after_deadline": False},
        },
    }

    mock_problems = [
        {"index": "A", "name": "Problem Alpha"},
        {"index": "B", "name": "Problem Beta"},
        {"index": "C", "name": "Problem Gamma"},
    ]

    with patch.object(task, "get_problems", return_value=mock_problems):
        data = task.get_render_data(
            task=task_obj,
            assignments=[assignment],
            student_map={42: student},
            current_user=student,
        )

        probs = {p["index"]: p for p in data["contest_problems"]}

        # Problem A: Solved
        assert probs["A"]["user_solved"] is True
        assert probs["A"]["user_attempted_unsolved"] is False
        assert probs["A"]["user_attempts"] == 2

        # Problem B: Wrong Answer (attempted 3 times, not solved)
        assert probs["B"]["user_solved"] is False
        assert probs["B"]["user_attempted_unsolved"] is True
        assert probs["B"]["user_wrong_answer"] is True
        assert probs["B"]["user_attempts"] == 3

        # Problem C: Unattempted
        assert probs["C"]["user_solved"] is False
        assert probs["C"]["user_attempted_unsolved"] is False
        assert probs["C"]["user_attempts"] == 0

        # Return dict summaries
        assert "A" in data["user_solved_indices"]
        assert "B" in data["user_wrong_answer_indices"]


def test_contest_task_page_hide_solved_problems_checkbox_rendered():
    """Verify that contest task page renders 'Hide solved problems' checkbox and data-solved attributes."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import init_db, engine
    from app.models.user import User
    from app.core.security import get_password_hash
    from sqlmodel import Session, select
    import uuid

    init_db()
    with Session(engine) as session:
        coach = session.exec(select(User).where(User.username == "coach")).first()
        if not coach:
            coach = User(
                username="coach",
                email="coach@example.com",
                hashed_password=get_password_hash("12345678"),
                role="coach",
                is_active=True,
            )
            session.add(coach)
            session.commit()

    client = TestClient(app)

    # Login as coach
    login_res = client.post("/api/auth/login", json={"username_or_email": "coach", "password": "12345678"})
    assert login_res.status_code == 200

    uniq = str(uuid.uuid4())[:8]
    # Create contest task
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": f"Hide Solved Contest {uniq}",
            "task_type": "CF_CONTEST",
            "config": {"contest_id": 9999, "min_solved": 1, "access_type": "public"},
        },
    )
    assert t_res.status_code == 201
    task_id = t_res.json()["id"]

    mock_problems = [
        {"index": "A", "name": "Problem Alpha"},
        {"index": "B", "name": "Problem Beta"},
    ]

    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=mock_problems):
        page = client.get(f"/tasks/{task_id}")
        assert page.status_code == 200

        # Checkbox for hiding solved problems must be rendered
        assert 'id="hide-solved-problems-checkbox"' in page.text
        assert "Hide solved problems" in page.text

        # Solved empty state row must be present
        assert 'id="all-problems-solved-message"' in page.text

        # Problem rows have data-solved attribute
        assert 'data-solved=' in page.text





