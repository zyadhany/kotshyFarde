"""
tests/test_cses_task.py
───────────────────────
Unit and integration tests for CSES Problem Set task checking:
- CSES authentication, auto-healing login, and session persistence
- Problem name resolution, bulk warmup, and fallback caching
- Solved tasks extraction, TTL caching, and incremental diff checking
- CSESBaseTask, CSESSheetTask, and TaskFactory polymorphic integration
- API endpoints (/api/tasks/, /api/assignments/{id}/check, /tasks/{id})
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import get_session
from app.domain.cses.base import CSESBaseTask
from tests.conftest import login_as_coach
from app.domain.cses.sheet import CSESSheetTask
from app.domain.factory import TaskFactory
from app.main import app
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User
from app.services import cses_api
from app.services.cses_api import CSESService




@pytest.fixture
def cses_service_instance():
    """Create a fresh isolated CSESService instance for tests."""
    srv = CSESService()
    return srv


# ── 1. CSES Service: Authentication & Auto-Healing ──────────

def test_cses_login_success(cses_service_instance):
    """Verify login fetches CSRF token and verifies session."""
    with patch.object(settings, "CSES_USERNAME", "coach_bot"), \
         patch.object(settings, "CSES_PASSWORD", "secret123"):

        mock_login_html = """
        <html><body>
            <form action="/login" method="post">
                <input type="hidden" name="csrf_token" value="test_token_abc">
                <input type="text" name="nick">
                <input type="password" name="pass">
            </form>
        </body></html>
        """
        mock_auth_html = """
        <html><body>
            <div class="header">
                <a class="account" href="/logout">Logout</a>
            </div>
        </body></html>
        """

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.text = mock_login_html
            return resp

        def mock_post(url, data=None, **kwargs):
            assert data["csrf_token"] == "test_token_abc"
            assert data["nick"] == "coach_bot"
            assert data["pass"] == "secret123"
            resp = MagicMock()
            resp.status_code = 200
            resp.text = mock_auth_html
            return resp

        cses_service_instance.session.get = mock_get
        cses_service_instance.session.post = mock_post

        assert cses_service_instance.login() is True
        assert cses_service_instance._logged_in is True


def test_cses_login_missing_credentials(cses_service_instance):
    """Login should gracefully fail if credentials are not configured."""
    with patch.object(settings, "CSES_USERNAME", ""), \
         patch.object(settings, "CSES_PASSWORD", ""):
        assert cses_service_instance.login() is False


def test_authenticated_get_auto_healing(cses_service_instance):
    """_authenticated_get should detect redirect to /login and auto-heal session."""
    redirect_resp = MagicMock()
    redirect_resp.status_code = 302
    redirect_resp.headers = {"Location": "/login"}
    redirect_resp.text = "Redirecting to /login"

    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.headers = {}
    success_resp.text = "<html><body>User Stats</body></html>"

    call_count = 0

    def mock_get(url, allow_redirects=True, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return redirect_resp
        return success_resp

    cses_service_instance.session.get = mock_get
    cses_service_instance.login = MagicMock(return_value=True)

    resp = cses_service_instance._authenticated_get("https://cses.fi/problemset/user/123/")
    assert resp.status_code == 200
    assert "User Stats" in resp.text
    cses_service_instance.login.assert_called_once()


# ── 2. Problem Name Resolution & Caching ─────────────────────

def test_warmup_problem_names(cses_service_instance):
    """Verify single-request bulk warmup primes the in-memory cache."""
    mock_problemset_html = """
    <html><body>
        <ul>
            <li class="task"><a href="/problemset/task/1068">Weird Algorithm</a></li>
            <li class="task"><a href="/problemset/task/1083">Missing Number</a></li>
            <li class="task"><a href="/problemset/task/1069">Repetitions</a></li>
        </ul>
    </body></html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_problemset_html

    with patch.object(cses_service_instance.session, "get", return_value=mock_resp):
        cses_service_instance.warmup_problem_names()

    assert cses_service_instance.get_problem_name("1068") == "Weird Algorithm"
    assert cses_service_instance.get_problem_name("1083") == "Missing Number"
    assert cses_service_instance.get_problem_name("1069") == "Repetitions"


def test_get_problem_name_fallback(cses_service_instance):
    """Fallback scraping for unlisted or newly added problems."""
    mock_task_html = """
    <html><head><title>CSES - Special Task</title></head><body><h1>Special Task</h1></body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_task_html

    with patch.object(cses_service_instance.session, "get", return_value=mock_resp):
        title = cses_service_instance.get_problem_name("9999")
        assert title == "Special Task"


def test_get_problems_metadata(cses_service_instance):
    """Verify get_problems_metadata returns structured dict."""
    with patch.object(cses_service_instance, "get_problem_name", side_effect=lambda pid, *a, **kw: f"Name {pid}"):
        meta = cses_service_instance.get_problems_metadata(["1068", "1083"])
        assert "1068" in meta
        assert meta["1068"]["name"] == "Name 1068"
        assert meta["1068"]["url"] == "https://cses.fi/problemset/task/1068"
        assert meta["1083"]["url"] == "https://cses.fi/problemset/task/1083"


# ── 3. Solved Tasks Checker & TTL Cache ───────────────────────

def test_get_user_solved_set_and_ttl(cses_service_instance):
    """Verify user solved set extraction from HTML and TTL cache."""
    mock_user_html = """
    <html><body>
        <div class="content">
            <a class="task-score icon full" href="/problemset/task/1068"></a>
            <a href="/problemset/task/1083"><span class="task-score icon full">100</span></a>
            <a href="/problemset/task/1069"><span class="task-score icon zero">0</span></a>
        </div>
    </body></html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_user_html

    with patch.object(cses_service_instance, "_authenticated_get", return_value=mock_resp) as mock_get:
        # First call fetches via network
        solved_1 = cses_service_instance.get_user_solved_set("55555")
        assert solved_1 == {"1068", "1083"}
        mock_get.assert_called_once()

        # Second call returns cached set (no additional network call)
        solved_2 = cses_service_instance.get_user_solved_set("55555")
        assert solved_2 == {"1068", "1083"}
        assert mock_get.call_count == 1

        # Force refresh makes network call
        solved_3 = cses_service_instance.get_user_solved_set("55555", force_refresh=True)
        assert solved_3 == {"1068", "1083"}
        assert mock_get.call_count == 2


def test_check_user_solved_problems(cses_service_instance):
    """Verify check_user_solved_problems partitions solved and unsolved correctly."""
    with patch.object(cses_service_instance, "get_user_solved_set", return_value={"1068", "1083"}):
        user = User(username="test_student", email="s@cf.com", hashed_password="pw", cses_id="55555")
        res = cses_service_instance.check_user_solved_problems(user, ["1068", "1083", "1069"])
        assert res["solved"] == ["1068", "1083"]
        assert res["unsolved"] == ["1069"]


def test_check_user_solved_problems_missing_cses_id(cses_service_instance):
    """Missing CSES ID should return error details without raising unhandled exception."""
    user = User(username="no_cses", email="no@cf.com", hashed_password="pw", cses_id=None)
    res = cses_service_instance.check_user_solved_problems(user, ["1068", "1083"])
    assert res["solved"] == []
    assert res["unsolved"] == ["1068", "1083"]
    assert "error" in res


def test_cses_cache_namespaces_and_clear(cses_service_instance):
    """Verify that CSES caches use the central CacheManager namespaces and can be cleared."""
    from app.core.cache import cache

    # Seed problem names and user solved caches
    cache["cses_problem_names"].set("1068", "Weird Algorithm")
    cache["cses_user_solved"].set("999", ["1068", "1083"])

    assert cache["cses_problem_names"].get("1068") == "Weird Algorithm"
    assert cache["cses_user_solved"].get("999") == ["1068", "1083"]

    # Verify clear_user_solved_cache
    cses_api.clear_user_solved_cache()
    assert cache["cses_user_solved"].get("999") is None
    assert cache["cses_problem_names"].get("1068") == "Weird Algorithm"

    # Verify clear_problem_names_cache
    cses_api.clear_problem_names_cache()
    assert cache["cses_problem_names"].get("1068") is None

    # Verify clear_cses_cache clears both
    cache["cses_problem_names"].set("1068", "Weird Algorithm")
    cache["cses_user_solved"].set("999", ["1068"])
    cses_api.clear_cses_cache()
    assert cache["cses_problem_names"].get("1068") is None
    assert cache["cses_user_solved"].get("999") is None


def test_get_problem_name_bypass_cache(cses_service_instance):
    """Verify use_cache=False bypasses the cache."""
    from app.core.cache import cache

    cache["cses_problem_names"].set("1068", "Cached Title")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><h1>Fresh Scraped Title</h1></body></html>"

    with patch.object(cses_service_instance.session, "get", return_value=mock_resp):
        # With cache: returns cached
        assert cses_service_instance.get_problem_name("1068", use_cache=True) == "Cached Title"
        # Bypassing cache: scrapes fresh title
        assert cses_service_instance.get_problem_name("1068", use_cache=False) == "Fresh Scraped Title"


# ── 4. CSES Domain Layer & TaskFactory ────────────────────────

def test_task_factory_cses_sheet():
    """Verify TaskFactory polymorphic instantiation for CSES_SHEET."""
    config = {"problems": ["1068", "1083", "1069"], "min_solved_count": 2}
    task = TaskFactory.create("CSES_SHEET", config)
    assert isinstance(task, CSESSheetTask)
    assert task.task_type == "CSES_SHEET"
    assert task.problems == ["1068", "1083", "1069"]
    assert task.min_solved_count == 2
    assert task.to_dict()["problems"] == ["1068", "1083", "1069"]


def test_cses_sheet_task_check_completed():
    """Verify check sets status to completed when all problems or min_solved are met."""
    sheet = CSESSheetTask(problems=["1068", "1083"], min_solved_count=2)
    student = User(username="student1", email="s1@cf.com", hashed_password="pw", cses_id="12345")

    with patch("app.services.cses_api.check_user_solved_problems", return_value={"solved": ["1068", "1083"], "unsolved": []}), \
         patch("app.services.cses_api.get_problem_name", side_effect=lambda pid: f"Problem {pid}"):
        result = sheet.check(student)
        assert result["status"] == "completed"
        assert result["details"]["solved_count"] == 2
        assert result["details"]["solved"] == ["1068", "1083"]
        assert result["details"]["unsolved"] == []
        assert "problems" in result["details"]
        assert result["details"]["problems"]["1068"]["solved"] is True


def test_cses_sheet_task_check_in_progress():
    """Verify check sets status to in_progress when partial problems are solved."""
    sheet = CSESSheetTask(problems=["1068", "1083", "1069"], min_solved_count=3)
    student = User(username="student1", email="s1@cf.com", hashed_password="pw", cses_id="12345")

    with patch("app.services.cses_api.check_user_solved_problems", return_value={"solved": ["1068"], "unsolved": ["1083", "1069"]}), \
         patch("app.services.cses_api.get_problem_name", side_effect=lambda pid: f"Problem {pid}"):
        result = sheet.check(student)
        assert result["status"] == "in_progress"
        assert result["details"]["solved_count"] == 1
        assert result["details"]["solved"] == ["1068"]
        assert result["details"]["unsolved"] == ["1083", "1069"]


def test_cses_sheet_task_incremental_diff_checking():
    """Verify incremental diff check skips network when all problems already solved."""
    sheet = CSESSheetTask(problems=["1068", "1083"], min_solved_count=2)
    student = User(username="student1", email="s1@cf.com", hashed_password="pw", cses_id="12345")

    prev_res = {
        "status": "completed",
        "solved": ["1068", "1083"],
        "unsolved": [],
        "solved_count": 2,
    }

    with patch("app.services.cses_api.check_user_solved_problems") as mock_check, \
         patch("app.services.cses_api.get_problem_name", side_effect=lambda pid: f"Problem {pid}"):
        result = sheet.check(student, previous_result=prev_res)
        assert result["status"] == "completed"
        assert result["details"]["solved_count"] == 2
        # Network check should NOT be called at all!
        mock_check.assert_not_called()


def test_cses_sheet_task_partial_incremental_diff_check():
    """Verify incremental check only sends unsolved problems to the checker."""
    sheet = CSESSheetTask(problems=["1068", "1083", "1069"], min_solved_count=2)
    student = User(username="student1", email="s1@cf.com", hashed_password="pw", cses_id="12345")

    prev_res = {
        "status": "in_progress",
        "solved": ["1068"],
        "unsolved": ["1083", "1069"],
        "solved_count": 1,
    }

    # Only remaining unsolved ["1083", "1069"] should be sent
    with patch("app.services.cses_api.check_user_solved_problems", return_value={"solved": ["1083"], "unsolved": ["1069"]}) as mock_check, \
         patch("app.services.cses_api.get_problem_name", side_effect=lambda pid: f"Problem {pid}"):
        result = sheet.check(student, previous_result=prev_res)

        mock_check.assert_called_once_with(student, ["1083", "1069"])
        assert result["status"] == "completed"
        assert result["details"]["solved_count"] == 2
        assert "1068" in result["details"]["solved"]
        assert "1083" in result["details"]["solved"]
        assert result["details"]["unsolved"] == ["1069"]


# ── 5. End-to-End API and Page Rendering Integration ─────────

def test_cses_sheet_api_and_page_rendering(client):
    """End-to-end integration: create CSES task, assign, check, and render page."""
    # 1. Login coach
    login_as_coach(client)

    # 2. Create student with CSES ID
    s_res = client.post(
        "/api/students/",
        json={
            "username": "cses_learner",
            "email": "learner@cses.fi",
            "cf_handle": "learner_cf",
            "cses_id": "77777",
        },
    )
    assert s_res.status_code == 201
    student_id = s_res.json()["id"]

    # 3. Create CSES Sheet Task
    with patch("app.services.cses_api.get_problem_name", side_effect=lambda pid: f"CSES Problem {pid}"):
        t_res = client.post(
            "/api/tasks/",
            json={
                "title": "CSES Introductory Sheet",
                "description": "CSES algorithm problems",
                "task_type": "CSES_SHEET",
                "config": {
                    "problems": ["1068", "1083"],
                    "min_solved_count": 2,
                },
            },
        )
        assert t_res.status_code == 201
        task_id = t_res.json()["id"]

        # 4. Assign to student
        a_res = client.post(
            "/api/assignments/",
            json={"student_id": student_id, "task_id": task_id},
        )
        assert a_res.status_code == 201
        assignment_id = a_res.json()["id"]

        # 5. Check assignment endpoint
        with patch("app.services.cses_api.check_user_solved_problems", return_value={"solved": ["1068", "1083"], "unsolved": []}):
            chk_res = client.post(f"/api/assignments/{assignment_id}/check")
            assert chk_res.status_code == 200
            chk_data = chk_res.json()
            assert chk_data["status"] == "completed"
            assert chk_data["checker_result"]["solved_count"] == 2

        # 6. Check task detail page rendering
        with patch("app.services.cses_api.get_problem_name", side_effect=lambda pid: "Weird Algorithm" if pid == "1068" else "Missing Number"):
            page_res = client.get(f"/tasks/{task_id}")
            assert page_res.status_code == 200
            assert "CSES Introductory Sheet" in page_res.text
            assert "CSES Problem Set" in page_res.text
            assert "#1068" in page_res.text
            assert "Weird Algorithm" in page_res.text
            assert "https://cses.fi/problemset/task/1068" in page_res.text

        # 7. Check student profile rendering displays CSES ID
        profile_res = client.get(f"/students/{student_id}")
        assert profile_res.status_code == 200
        assert "77777" in profile_res.text
        assert "https://cses.fi/user/77777" in profile_res.text
