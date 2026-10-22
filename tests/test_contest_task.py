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


# ── Domain Task Tests ─────────────────────────────────────────

def test_contest_task_lazy_problem_getter():
    """Verify that when problems is null/None, the getter generates it via codeforces_api.
    When already present, returns it directly without calling codeforces_api again."""
    task = CodeforcesContestTask(contest_id=1234, min_solved=2, access_type="public")
    assert task._problems is None

    mock_problems = [
        {"index": "A", "name": "Problem Alpha"},
        {"index": "B", "name": "Problem Beta"},
    ]

    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=mock_problems) as mock_get:
        # First call: _problems is None -> must call generator function
        first_result = task.get_problems()
        assert first_result == mock_problems
        assert mock_get.call_count == 1
        mock_get.assert_called_once_with(contest_id=1234, use_auth=False)

        # Second call: _problems is already populated -> must return directly
        second_result = task.get_problems()
        assert second_result == mock_problems
        assert mock_get.call_count == 1  # Not called again!

        # Accessing via .problems property should also return directly
        property_result = task.problems
        assert property_result == mock_problems
        assert mock_get.call_count == 1  # Still 1 call


def test_contest_task_initialized_with_problems():
    """If problems list is provided during init, getter returns it directly without calling API."""
    existing_problems = [{"index": "A", "name": "Existing Problem"}]
    task = CodeforcesContestTask(contest_id=567, min_solved=1, problems=existing_problems)

    with patch("app.domain.codeforces.contest.get_contest_problems") as mock_get:
        res = task.get_problems()
        assert res == existing_problems
        assert task.problems == existing_problems
        mock_get.assert_not_called()


def test_contest_task_generate_problems_explicit():
    """Calling generate_problems explicitly refetches and updates the internal list."""
    task = CodeforcesContestTask(contest_id=890, min_solved=1)
    new_problems = [{"index": "A", "name": "Newly Generated"}]

    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=new_problems) as mock_get:
        res = task.generate_problems()
        assert res == new_problems
        assert task._problems == new_problems
        assert task.get_problems() == new_problems
        mock_get.assert_called_once_with(contest_id=890, use_auth=False)


def test_contest_task_serialization_roundtrip():
    """Verify to_dict and from_dict preserve problems correctly."""
    problems = [{"index": "A", "name": "Prob A"}, {"index": "B", "name": "Prob B"}]
    task = CodeforcesContestTask(contest_id=100, min_solved=2, access_type="public", problems=problems)

    serialized = task.to_dict()
    assert serialized["contest_id"] == 100
    assert serialized["min_solved"] == 2
    assert serialized["access_type"] == "public"
    assert serialized["problems"] == problems

    hydrated = CodeforcesContestTask.from_dict(serialized)
    assert hydrated.contest_id == 100
    assert hydrated.min_solved == 2
    assert hydrated.access_type == "public"
    assert hydrated._problems == problems

    # Getter returns directly without API call
    with patch("app.domain.codeforces.contest.get_contest_problems") as mock_get:
        assert hydrated.get_problems() == problems
        mock_get.assert_not_called()


def test_contest_task_serialization_when_null():
    """Verify to_dict when problems has not been generated."""
    task = CodeforcesContestTask(contest_id=200, min_solved=1)
    serialized = task.to_dict()
    assert "problems" not in serialized

    hydrated = CodeforcesContestTask.from_dict(serialized)
    assert hydrated._problems is None
