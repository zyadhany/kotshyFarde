"""
tests/test_api.py
─────────────────
Automated tests for FastAPI endpoints, database persistence, and checker workflow.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.core.config import _parse_deadline, settings
from app.core.database import get_session
from app.main import app
from app.models.student_task import StudentTask
from app.models.task import Task
from app.models.user import User

# In-memory SQLite engine for isolated tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    with Session(test_engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(autouse=True)
def setup_database():
    SQLModel.metadata.create_all(test_engine)
    yield
    SQLModel.metadata.drop_all(test_engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ── Config Tests ──────────────────────────────────────────────
def test_deadline_parser():
    # Valid ISO string
    dt = _parse_deadline("2028-06-15T12:00:00Z")
    assert dt.year == 2028
    assert dt.month == 6

    # Valid date-only string
    dt_date = _parse_deadline("2027-10-31")
    assert dt_date.year == 2027
    assert dt_date.month == 10
    assert dt_date.day == 31

    # Empty / None fallback to 2030-01-01 UTC
    dt_none = _parse_deadline(None)
    assert dt_none == datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    dt_empty = _parse_deadline("   ")
    assert dt_empty == datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # Invalid string fallback
    dt_invalid = _parse_deadline("not-a-valid-date")
    assert dt_invalid == datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ── Health Check & CORS ───────────────────────────────────────
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_headers(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000")
    assert response.headers.get("access-control-allow-credentials") == "true"


# ── Students Router Tests ─────────────────────────────────────
def test_create_and_get_student(client):
    payload = {
        "username": "ahmed_aly",
        "email": "ahmed@example.com",
        "password_hash": "hash123",
        "cf_handle": "ahmed_cf",
        "vjudge_handle": "ahmed_vj",
        "description": "ICPC finalist",
    }
    res = client.post("/students/", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["id"] is not None
    assert data["username"] == "ahmed_aly"
    assert data["cf_handle"] == "ahmed_cf"
    assert data["role"] == "Student"
    student_id = data["id"]

    # Duplicate student fails
    res_dup = client.post("/students/", json=payload)
    assert res_dup.status_code == 400

    # Get single student
    res_get = client.get(f"/students/{student_id}")
    assert res_get.status_code == 200
    assert res_get.json()["email"] == "ahmed@example.com"
    assert res_get.json()["role"] == "Student"

    # Get non-existent student -> 404
    assert client.get("/students/99999").status_code == 404

    # List students
    res_list = client.get("/students/")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1

    # Update student (partial)
    res_put = client.put(f"/students/{student_id}", json={"cf_handle": "new_cf_handle"})
    assert res_put.status_code == 200
    assert res_put.json()["cf_handle"] == "new_cf_handle"
    assert res_put.json()["username"] == "ahmed_aly"

    # Update non-existent student -> 404
    assert client.put("/students/99999", json={"cf_handle": "x"}).status_code == 404

    # Delete non-existent student -> 404
    assert client.delete("/students/99999").status_code == 404

    # Delete student
    res_del = client.delete(f"/students/{student_id}")
    assert res_del.status_code == 200

    # Ensure deleted
    assert client.get(f"/students/{student_id}").status_code == 404


def test_user_model_and_role(client):
    """Verify User model maps to users table and supports role parameter ('Student' or 'coash')."""
    assert User.__tablename__ == "users"

    coach_payload = {
        "username": "coach_ziad",
        "email": "coach@example.com",
        "password_hash": "coachpass",
        "role": "coash",
        "cf_handle": "coach_cf",
    }
    res = client.post("/users/", json=coach_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["role"] == "coash"
    assert data["username"] == "coach_ziad"
    user_id = data["id"]

    # Retrieve user from /users/{id}
    res_get = client.get(f"/users/{user_id}")
    assert res_get.status_code == 200
    assert res_get.json()["role"] == "coash"

    # Update role to Student
    res_put = client.put(f"/users/{user_id}", json={"role": "Student"})
    assert res_put.status_code == 200
    assert res_put.json()["role"] == "Student"

    # Delete user via /users/{id}
    res_del = client.delete(f"/users/{user_id}")
    assert res_del.status_code == 200
    assert client.get(f"/users/{user_id}").status_code == 404


# ── Tasks Router Tests ────────────────────────────────────────
def test_create_and_manage_task(client):
    task_payload = {
        "title": "Dynamic Programming Sheet 1",
        "description": "Solve at least 3 DP problems",
        "task_type": "CF_SHEET",
        "config": {
            "problems": ["455A", "118D", "1061C"],
            "min_solved_count": 2,
        },
    }
    res = client.post("/tasks/", json=task_payload)
    assert res.status_code == 201
    task_data = res.json()
    task_id = task_data["id"]
    assert task_data["task_type"] == "CF_SHEET"
    assert task_data["config"]["min_solved_count"] == 2

    # Get task
    res_get = client.get(f"/tasks/{task_id}")
    assert res_get.status_code == 200
    assert res_get.json()["title"] == "Dynamic Programming Sheet 1"

    # Get non-existent task -> 404
    assert client.get("/tasks/99999").status_code == 404

    # List tasks
    res_list = client.get("/tasks/")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # Update task
    res_put = client.put(f"/tasks/{task_id}", json={"title": "Updated DP Sheet"})
    assert res_put.status_code == 200
    assert res_put.json()["title"] == "Updated DP Sheet"
    assert res_put.json()["task_type"] == "CF_SHEET"

    # Update non-existent task -> 404
    assert client.put("/tasks/99999", json={"title": "Ghost"}).status_code == 404

    # Delete non-existent task -> 404
    assert client.delete("/tasks/99999").status_code == 404

    # Delete task
    res_del = client.delete(f"/tasks/{task_id}")
    assert res_del.status_code == 200

    # Ensure 404
    assert client.get(f"/tasks/{task_id}").status_code == 404


# ── Assignments Router Tests ──────────────────────────────────
def test_assignments_lifecycle_and_check(client):
    # 1. Create a student
    student_res = client.post(
        "/students/",
        json={
            "username": "tourist",
            "email": "tourist@example.com",
            "cf_handle": "tourist",
        },
    )
    student_id = student_res.json()["id"]

    # 2. Create a task
    task_res = client.post(
        "/tasks/",
        json={
            "title": "Warmup Sheet",
            "task_type": "CF_SHEET",
            "config": {
                "problems": ["4A", "71A"],
                "min_solved_count": 2,
            },
        },
    )
    task_id = task_res.json()["id"]

    # Assign to non-existent student -> 404
    bad_student_assign = client.post(
        "/assignments/",
        json={"student_id": 99999, "task_id": task_id},
    )
    assert bad_student_assign.status_code == 404

    # Assign non-existent task -> 404
    bad_task_assign = client.post(
        "/assignments/",
        json={"student_id": student_id, "task_id": 99999},
    )
    assert bad_task_assign.status_code == 404

    # 3. Assign task with default start_date and deadline
    assign_res = client.post(
        "/assignments/",
        json={
            "student_id": student_id,
            "task_id": task_id,
        },
    )
    assert assign_res.status_code == 201
    assign_data = assign_res.json()
    assign_id = assign_data["id"]
    assert assign_data["status"] == "pending"
    assert assign_data["checker_result"] == {}
    assert assign_data["start_date"] is not None
    assert "2030-01-01" in assign_data["deadline"]

    # 4. Get assignment by ID
    get_assign = client.get(f"/assignments/{assign_id}")
    assert get_assign.status_code == 200
    assert get_assign.json()["id"] == assign_id
    assert get_assign.json()["task"]["title"] == "Warmup Sheet"

    # Non-existent assignment -> 404
    assert client.get("/assignments/99999").status_code == 404

    # 5. Get assignments for student
    student_assigns = client.get(f"/assignments/student/{student_id}")
    assert student_assigns.status_code == 200
    assert len(student_assigns.json()) == 1
    assert student_assigns.json()[0]["id"] == assign_id

    # Non-existent student assignments -> 404
    assert client.get("/assignments/student/99999").status_code == 404

    # 6. Test check endpoint with mocked checker result
    mock_checker = MagicMock()
    mock_checker.check.return_value = {
        "status": "completed",
        "after_deadline": False,
        "details": {
            "solved": ["4A", "71A"],
            "unsolved": [],
            "solved_count": 2,
            "required": 2,
            "after_deadline": False,
            "solved_after_deadline": [],
        },
    }

    with patch("app.api.assignments.TaskFactory.create", return_value=mock_checker):
        check_res = client.post(f"/assignments/{assign_id}/check")
        assert check_res.status_code == 200
        checked_data = check_res.json()
        assert checked_data["status"] == "completed"
        assert checked_data["checker_result"]["solved_count"] == 2
        assert checked_data["checker_result"]["missing_problems"] == []
        assert "last_checked" in checked_data["checker_result"]
        assert checked_data["completed_at"] is not None

    # Check persistence in database
    get_after_check = client.get(f"/assignments/{assign_id}")
    assert get_after_check.json()["status"] == "completed"
    assert get_after_check.json()["checker_result"]["solved_count"] == 2

    # Check non-existent assignment check -> 404
    assert client.post("/assignments/99999/check").status_code == 404


def test_assignment_check_invalid_task_type(client):
    # Student
    s_res = client.post("/students/", json={"username": "bob", "email": "bob@example.com"})
    s_id = s_res.json()["id"]

    # Task with unregistered task type
    t_res = client.post("/tasks/", json={"title": "Unknown", "task_type": "UNKNOWN_TYPE", "config": {}})
    t_id = t_res.json()["id"]

    # Assignment
    a_res = client.post("/assignments/", json={"student_id": s_id, "task_id": t_id})
    a_id = a_res.json()["id"]

    # Check -> 400 Bad Request
    res = client.post(f"/assignments/{a_id}/check")
    assert res.status_code == 400


# ── Frontend Pages Tests ──────────────────────────────────────
def test_frontend_pages(client):
    # 1. Seed sample student and task
    s_res = client.post("/students/", json={"username": "alex", "email": "alex@cf.com", "cf_handle": "alex_cf"})
    s_id = s_res.json()["id"]

    t_res = client.post(
        "/tasks/",
        json={"title": "Intro DP", "task_type": "CF_SHEET", "config": {"problems": ["158A", "71A"], "min_solved_count": 1}},
    )
    t_id = t_res.json()["id"]

    client.post("/assignments/", json={"student_id": s_id, "task_id": t_id})

    # Dashboard page (/)
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Coach Command Center" in res_root.text
    assert "Total Students" in res_root.text
    assert "On Track" in res_root.text
    assert "Needs Attention" in res_root.text

    # /dashboard redirects to /
    res_dash = client.get("/dashboard", follow_redirects=False)
    assert res_dash.status_code in (302, 307)
    assert res_dash.headers.get("location") == "/"

    # Students archive page (/students-page)
    res_students = client.get("/students-page")
    assert res_students.status_code == 200
    assert "Students" in res_students.text
    assert "alex" in res_students.text

    # Student detail page (/students-page/{id})
    res_s_detail = client.get(f"/students-page/{s_id}")
    assert res_s_detail.status_code == 200
    assert "alex" in res_s_detail.text
    assert "Intro DP" in res_s_detail.text

    # Tasks archive page (/tasks-page)
    res_tasks = client.get("/tasks-page")
    assert res_tasks.status_code == 200
    assert "Task Archive" in res_tasks.text
    assert "Intro DP" in res_tasks.text

    # Task detail page for CF_SHEET (/tasks-page/{id})
    res_t_detail = client.get(f"/tasks-page/{t_id}")
    assert res_t_detail.status_code == 200
    assert "Intro DP" in res_t_detail.text
    assert "158A" in res_t_detail.text
    assert "Curated Problem Set" in res_t_detail.text
    assert "Assign to Students" in res_t_detail.text

    # Task detail page for CF_CONTEST
    c_res = client.post(
        "/tasks/",
        json={
            "title": "Codeforces Round 950",
            "task_type": "CF_CONTEST",
            "config": {
                "contest_id": 1980,
                "min_solved": 3,
                "problems": [{"index": "A", "name": "Problem A"}, {"index": "B", "name": "Problem B"}],
            },
        },
    )
    c_id = c_res.json()["id"]
    res_c_detail = client.get(f"/tasks-page/{c_id}")
    assert res_c_detail.status_code == 200
    assert "Codeforces Round 950" in res_c_detail.text
    assert "Codeforces Contest Standings" in res_c_detail.text
    assert "Contest Problems" in res_c_detail.text
    assert "Problem A" in res_c_detail.text

    # Task detail page for custom/fallback task type
    custom_res = client.post(
        "/tasks/",
        json={
            "title": "CSES Sheet",
            "task_type": "CSES_SHEET",
            "config": {"sheet_name": "Introductory Problems"},
        },
    )
    custom_id = custom_res.json()["id"]
    res_custom_detail = client.get(f"/tasks-page/{custom_id}")
    assert res_custom_detail.status_code == 200
    assert "CSES Sheet" in res_custom_detail.text
    assert "Task Configuration" in res_custom_detail.text

    # Static CSS and JS assets
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200

    res_js = client.get("/static/js/main.js")
    assert res_js.status_code == 200
    assert "Kotchy" in res_js.text
