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


@pytest.fixture(autouse=True)
def setup_database(monkeypatch):
    monkeypatch.setattr("app.main.init_db", lambda: None)
    SQLModel.metadata.create_all(test_engine)
    app.dependency_overrides[get_session] = override_get_session
    with Session(test_engine) as session:
        from app.core.security import get_password_hash
        default_coach = User(
            username="coach",
            email="coach@kotchy.dev",
            hashed_password=get_password_hash("adminpassword"),
            role="coach",
            is_active=True,
        )
        session.add(default_coach)
        session.commit()
    yield
    SQLModel.metadata.drop_all(test_engine)
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login_as_coach(client, username="coach", password="adminpassword"):
    """Helper to authenticate the test client as coach."""
    res = client.post("/api/auth/login", json={"username_or_email": username, "password": password})
    assert res.status_code == 200
    return res


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
    login_as_coach(client)
    payload = {
        "username": "ahmed_aly",
        "email": "ahmed@example.com",
        "password_hash": "hash123",
        "cf_handle": "ahmed_cf",
        "vjudge_handle": "ahmed_vj",
        "description": "ICPC finalist",
    }
    res = client.post("/api/students/", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["id"] is not None
    assert data["username"] == "ahmed_aly"
    assert data["cf_handle"] == "ahmed_cf"
    assert data["role"].lower() == "student"
    student_id = data["id"]

    # Duplicate student fails
    res_dup = client.post("/api/students/", json=payload)
    assert res_dup.status_code == 400

    # Get single student
    res_get = client.get(f"/api/students/{student_id}")
    assert res_get.status_code == 200
    assert res_get.json()["email"] == "ahmed@example.com"
    assert res_get.json()["role"].lower() == "student"

    # Get non-existent student -> 404
    assert client.get("/api/students/99999").status_code == 404

    # List students
    res_list = client.get("/api/students/")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # Update student (partial)
    res_put = client.put(f"/api/students/{student_id}", json={"cf_handle": "new_cf_handle"})
    assert res_put.status_code == 200
    assert res_put.json()["cf_handle"] == "new_cf_handle"
    assert res_put.json()["username"] == "ahmed_aly"

    # Update non-existent student -> 404
    assert client.put("/api/students/99999", json={"cf_handle": "x"}).status_code == 404

    # Delete non-existent student -> 404
    assert client.delete("/api/students/99999").status_code == 404

    # Delete student
    res_del = client.delete(f"/api/students/{student_id}")
    assert res_del.status_code == 200

    # Ensure deleted
    assert client.get(f"/api/students/{student_id}").status_code == 404


def test_user_model_and_role(client):
    """Verify User model maps to users table and supports role parameter ('Student' or 'coash')."""
    assert User.__tablename__ == "users"
    login_as_coach(client)

    coach_payload = {
        "username": "coach_ziad",
        "email": "coach@example.com",
        "password_hash": "coachpass",
        "role": "coash",
        "cf_handle": "coach_cf",
    }
    res = client.post("/api/users/", json=coach_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["role"] == "coash"
    assert data["username"] == "coach_ziad"
    user_id = data["id"]

    # Retrieve user from /api/users/{id}
    res_get = client.get(f"/api/users/{user_id}")
    assert res_get.status_code == 200
    assert res_get.json()["role"] == "coash"

    # Update role to Student
    res_put = client.put(f"/api/users/{user_id}", json={"role": "Student"})
    assert res_put.status_code == 200
    assert res_put.json()["role"] == "Student"

    # Delete user via /api/users/{id}
    res_del = client.delete(f"/api/users/{user_id}")
    assert res_del.status_code == 200
    assert client.get(f"/api/users/{user_id}").status_code == 404


# ── Tasks Router Tests ────────────────────────────────────────
def test_create_and_manage_task(client):
    login_as_coach(client)
    task_payload = {
        "title": "Dynamic Programming Sheet 1",
        "description": "Solve at least 3 DP problems",
        "task_type": "CF_SHEET",
        "config": {
            "problems": ["455A", "118D", "1061C"],
            "min_solved_count": 2,
        },
    }
    res = client.post("/api/tasks/", json=task_payload)
    assert res.status_code == 201
    task_data = res.json()
    task_id = task_data["id"]
    assert task_data["task_type"] == "CF_SHEET"
    assert task_data["config"]["min_solved_count"] == 2

    # Get task
    res_get = client.get(f"/api/tasks/{task_id}")
    assert res_get.status_code == 200
    assert res_get.json()["title"] == "Dynamic Programming Sheet 1"

    # Get non-existent task -> 404
    assert client.get("/api/tasks/99999").status_code == 404

    # List tasks
    res_list = client.get("/api/tasks/")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # Update task
    res_put = client.put(f"/api/tasks/{task_id}", json={"title": "Updated DP Sheet"})
    assert res_put.status_code == 200
    assert res_put.json()["title"] == "Updated DP Sheet"
    assert res_put.json()["task_type"] == "CF_SHEET"

    # Update non-existent task -> 404
    assert client.put("/api/tasks/99999", json={"title": "Ghost"}).status_code == 404

    # Delete non-existent task -> 404
    assert client.delete("/api/tasks/99999").status_code == 404

    # Delete task
    res_del = client.delete(f"/api/tasks/{task_id}")
    assert res_del.status_code == 200

    # Ensure 404
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


# ── Assignments Router Tests ──────────────────────────────────
def test_assignments_lifecycle_and_check(client):
    login_as_coach(client)
    # 1. Create a student
    student_res = client.post(
        "/api/students/",
        json={
            "username": "tourist",
            "email": "tourist@example.com",
            "cf_handle": "tourist",
        },
    )
    student_id = student_res.json()["id"]

    # 2. Create a task
    task_res = client.post(
        "/api/tasks/",
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
        "/api/assignments/",
        json={"student_id": 99999, "task_id": task_id},
    )
    assert bad_student_assign.status_code == 404

    # Assign non-existent task -> 404
    bad_task_assign = client.post(
        "/api/assignments/",
        json={"student_id": student_id, "task_id": 99999},
    )
    assert bad_task_assign.status_code == 404

    # 3. Assign task with default start_date and deadline
    assign_res = client.post(
        "/api/assignments/",
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
    get_assign = client.get(f"/api/assignments/{assign_id}")
    assert get_assign.status_code == 200
    assert get_assign.json()["id"] == assign_id
    assert get_assign.json()["task"]["title"] == "Warmup Sheet"

    # Non-existent assignment -> 404
    assert client.get("/api/assignments/99999").status_code == 404

    # 5. Get assignments for student
    student_assigns = client.get(f"/api/assignments/student/{student_id}")
    assert student_assigns.status_code == 200
    assert len(student_assigns.json()) == 1
    assert student_assigns.json()[0]["id"] == assign_id

    # Non-existent student assignments -> 404
    assert client.get("/api/assignments/student/99999").status_code == 404

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
        check_res = client.post(f"/api/assignments/{assign_id}/check")
        assert check_res.status_code == 200
        checked_data = check_res.json()
        assert checked_data["status"] == "completed"
        assert checked_data["checker_result"]["solved_count"] == 2
        assert checked_data["checker_result"]["missing_problems"] == []
        assert "last_checked" in checked_data["checker_result"]
        assert checked_data["completed_at"] is not None

    # Check persistence in database
    get_after_check = client.get(f"/api/assignments/{assign_id}")
    assert get_after_check.json()["status"] == "completed"
    assert get_after_check.json()["checker_result"]["solved_count"] == 2

    # Check non-existent assignment check -> 404
    assert client.post("/api/assignments/99999/check").status_code == 404


def test_assignment_check_invalid_task_type(client):
    login_as_coach(client)
    # Student
    s_res = client.post("/api/students/", json={"username": "bob", "email": "bob@example.com"})
    s_id = s_res.json()["id"]

    # Task with unregistered task type
    t_res = client.post("/api/tasks/", json={"title": "Unknown", "task_type": "UNKNOWN_TYPE", "config": {}})
    t_id = t_res.json()["id"]

    # Assignment
    a_res = client.post("/api/assignments/", json={"student_id": s_id, "task_id": t_id})
    a_id = a_res.json()["id"]

    # Check -> 400 Bad Request
    res = client.post(f"/api/assignments/{a_id}/check")
    assert res.status_code == 400


def test_duplicate_assignment_idempotency_and_coach_assignment_prevention(client):
    """Re-assigning a task to the same student must be idempotent (no duplicate rows),
    and assigning a task to a coach account must be rejected with 400 Bad Request."""
    login_as_coach(client)
    # 1. Create a student and a coach
    s_res = client.post("/api/students/", json={"username": "idempotent_student", "email": "idem@kotchy.dev"})
    s_id = s_res.json()["id"]

    c_res = client.post("/api/users/", json={"username": "sub_coach", "email": "subcoach@kotchy.dev", "password": "pass", "role": "coach"})
    c_id = c_res.json()["id"]

    # 2. Create a task
    t_res = client.post(
        "/api/tasks/",
        json={"title": "Idempotent Task", "task_type": "CF_SHEET", "config": {"problems": ["4A"]}},
    )
    t_id = t_res.json()["id"]

    # 3. Cannot assign task to a coach account
    assign_coach = client.post("/api/assignments/", json={"student_id": c_id, "task_id": t_id})
    assert assign_coach.status_code == 400
    assert "Cannot assign tasks to a coach account" in assign_coach.json()["detail"]

    # 4. First assignment to student -> 201 Created
    assign_1 = client.post(
        "/api/assignments/",
        json={"student_id": s_id, "task_id": t_id, "deadline": "2029-01-01T00:00:00Z"},
    )
    assert assign_1.status_code == 201
    assign_id = assign_1.json()["id"]

    # 5. Second assignment with new deadline -> Idempotent, updates deadline and returns existing ID
    assign_2 = client.post(
        "/api/assignments/",
        json={"student_id": s_id, "task_id": t_id, "deadline": "2031-12-31T00:00:00Z"},
    )
    assert assign_2.status_code == 201
    assert assign_2.json()["id"] == assign_id
    assert "2031-12-31" in assign_2.json()["deadline"]

    # 6. Verify database only has exactly 1 row for this pair
    with Session(test_engine) as session:
        from sqlmodel import select
        rows = list(
            session.exec(
                select(StudentTask).where(
                    StudentTask.student_id == s_id,
                    StudentTask.task_id == t_id,
                )
            ).all()
        )
        assert len(rows) == 1
        assert "2031" in str(rows[0].deadline)


def test_coaches_excluded_from_student_views(client):
    """Coaches should not be listed as students on dashboard, students page, or task assignment modal."""
    login_as_coach(client)
    # Create coach and student
    client.post("/api/users/", json={"username": "super_coach_metric", "email": "scm@kotchy.dev", "password": "pass", "role": "coach"})
    s_res = client.post("/api/students/", json={"username": "real_student_metric", "email": "rsm@kotchy.dev"})
    s_id = s_res.json()["id"]

    t_res = client.post("/api/tasks/", json={"title": "Metric Task", "task_type": "CF_SHEET", "config": {}})
    t_id = t_res.json()["id"]

    # 1. Students archive (/students) shows real student but not coaches
    res_students = client.get("/students")
    assert res_students.status_code == 200
    assert "real_student_metric" in res_students.text
    # "super_coach_metric" is not in student table rows
    assert "super_coach_metric" not in res_students.text

    # 2. Task detail page (/tasks/{id}) only lists real student in assignment picker
    res_task = client.get(f"/tasks/{t_id}")
    assert res_task.status_code == 200
    assert "real_student_metric" in res_task.text
    assert "super_coach_metric" not in res_task.text


# ── Frontend Pages Tests ──────────────────────────────────────
def test_frontend_pages(client):
    # Authenticate as coach first
    login_as_coach(client)

    # 1. Seed sample student and task
    s_res = client.post("/api/students/", json={"username": "alex", "email": "alex@cf.com", "cf_handle": "alex_cf"})
    s_id = s_res.json()["id"]

    t_res = client.post(
        "/api/tasks/",
        json={"title": "Intro DP", "task_type": "CF_SHEET", "config": {"problems": ["158A", "71A"], "min_solved_count": 1}},
    )
    t_id = t_res.json()["id"]

    client.post("/api/assignments/", json={"student_id": s_id, "task_id": t_id})

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

    # Students archive page (/students and legacy /students-page)
    res_students = client.get("/students")
    assert res_students.status_code == 200
    assert "Students" in res_students.text
    assert "alex" in res_students.text
    assert client.get("/students-page").status_code == 200

    # Student detail page (/students/{id} and legacy /students-page/{id})
    res_s_detail = client.get(f"/students/{s_id}")
    assert res_s_detail.status_code == 200
    assert "alex" in res_s_detail.text
    assert "Intro DP" in res_s_detail.text
    assert client.get(f"/students-page/{s_id}").status_code == 200

    # Tasks archive page (/tasks and legacy /tasks-page)
    res_tasks = client.get("/tasks")
    assert res_tasks.status_code == 200
    assert "Task Archive" in res_tasks.text
    assert "Intro DP" in res_tasks.text
    assert client.get("/tasks-page").status_code == 200

    # Task detail page for CF_SHEET (/tasks/{id} and legacy /tasks-page/{id})
    res_t_detail = client.get(f"/tasks/{t_id}")
    assert res_t_detail.status_code == 200
    assert "Intro DP" in res_t_detail.text
    assert "158A" in res_t_detail.text
    assert "Curated Problem Set" in res_t_detail.text
    assert "Assign to Students" in res_t_detail.text
    assert client.get(f"/tasks-page/{t_id}").status_code == 200

    # Task detail page for CF_CONTEST
    c_res = client.post(
        "/api/tasks/",
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
    with patch(
        "app.domain.codeforces.contest.get_contest_problems",
        return_value=[{"index": "A", "name": "Problem A"}, {"index": "B", "name": "Problem B"}],
    ):
        res_c_detail = client.get(f"/tasks/{c_id}")
        assert res_c_detail.status_code == 200
        assert "Codeforces Round 950" in res_c_detail.text
        assert "Codeforces Contest Standings" in res_c_detail.text
        assert "Contest Problems" in res_c_detail.text
        assert "Problem A" in res_c_detail.text
        assert client.get(f"/tasks-page/{c_id}").status_code == 200

    # Task detail page for custom/fallback task type
    custom_res = client.post(
        "/api/tasks/",
        json={
            "title": "Custom Task",
            "task_type": "CUSTOM_TASK",
            "config": {"sheet_name": "Introductory Problems"},
        },
    )
    custom_id = custom_res.json()["id"]
    res_custom_detail = client.get(f"/tasks/{custom_id}")
    assert res_custom_detail.status_code == 200
    assert "Custom Task" in res_custom_detail.text
    assert "Task Configuration" in res_custom_detail.text
    assert client.get(f"/tasks-page/{custom_id}").status_code == 200

    # Static CSS and JS assets
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200

    res_js = client.get("/static/js/main.js")
    assert res_js.status_code == 200
    assert "Kotchy" in res_js.text


# ── Authentication & Access Control Tests ──────────────────────
def test_login_page_renders(client):
    res = client.get("/login")
    assert res.status_code == 200
    assert "Sign in to Kotchy" in res.text
    assert "Username or Email" in res.text
    assert "Password" in res.text
    assert "Sign In" in res.text


def test_unauthenticated_page_redirects(client):
    """Unauthenticated page visits should 303-redirect to /login."""
    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code == 303
    assert res_root.headers.get("location") == "/login"

    res_students = client.get("/students", follow_redirects=False)
    assert res_students.status_code == 303
    assert res_students.headers.get("location") == "/login?next=/students"
    assert client.get("/students-page", follow_redirects=False).status_code == 303

    res_tasks = client.get("/tasks", follow_redirects=False)
    assert res_tasks.status_code == 303
    assert res_tasks.headers.get("location") == "/login?next=/tasks"
    assert client.get("/tasks-page", follow_redirects=False).status_code == 303

    res_my_profile = client.get("/my-profile", follow_redirects=False)
    assert res_my_profile.status_code == 303
    assert res_my_profile.headers.get("location") == "/login?next=/my-profile"


def test_login_api_coach_and_cookie(client):
    login_as_coach(client)
    client.post(
        "/api/users/",
        json={"username": "super_coach", "email": "super_coach@kotchy.dev", "password": "coachpassword", "role": "coach"},
    )
    # Login via JSON
    res = client.post(
        "/api/auth/login",
        json={"username_or_email": "super_coach", "password": "coachpassword"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["username"] == "super_coach"
    assert data["role"] == "coach"
    assert data["redirect_url"] == "/"
    assert "access_token" in data
    assert "access_token" in client.cookies

    # Visiting /login when already logged in as coach redirects to /
    res_login_page = client.get("/login", follow_redirects=False)
    assert res_login_page.status_code == 303
    assert res_login_page.headers.get("location") == "/"


def test_login_api_student_and_cookie(client):
    login_as_coach(client)
    client.post(
        "/api/users/",
        json={"username": "cp_student", "email": "cp@kotchy.dev", "password": "studentpass", "role": "student"},
    )
    res = client.post(
        "/api/auth/login",
        json={"username_or_email": "cp_student", "password": "studentpass"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["username"] == "cp_student"
    assert data["role"] == "student"
    assert data["redirect_url"] == "/my-profile"
    assert "access_token" in client.cookies

    # Visiting /login when already logged in as student redirects to /my-profile
    res_login_page = client.get("/login", follow_redirects=False)
    assert res_login_page.status_code == 303
    assert res_login_page.headers.get("location") == "/my-profile"


def test_login_invalid_credentials_and_deactivated(client):
    login_as_coach(client)
    client.post(
        "/api/users/",
        json={"username": "active_user", "email": "active@kotchy.dev", "password": "correct_pass", "role": "student"},
    )

    # Wrong password -> 400
    res_wrong = client.post(
        "/api/auth/login",
        json={"username_or_email": "active_user", "password": "wrong_password"},
    )
    assert res_wrong.status_code == 400
    assert "Invalid credentials" in res_wrong.json()["detail"]

    # Non-existent user -> 400
    res_missing = client.post(
        "/api/auth/login",
        json={"username_or_email": "ghost_user", "password": "any"},
    )
    assert res_missing.status_code == 400

    # Deactivated user -> 403
    d_res = client.post(
        "/api/users/",
        json={"username": "deactivated_user", "email": "deact@kotchy.dev", "password": "pass", "role": "student"},
    )
    d_id = d_res.json()["id"]
    client.put(f"/api/users/{d_id}", json={"is_active": False})

    res_deact = client.post(
        "/api/auth/login",
        json={"username_or_email": "deactivated_user", "password": "pass"},
    )
    assert res_deact.status_code == 403
    assert "deactivated" in res_deact.json()["detail"].lower()


def test_logout_lifecycle(client):
    login_as_coach(client)
    client.post(
        "/api/users/",
        json={"username": "logout_coach", "email": "logout@kotchy.dev", "password": "adminpass", "role": "coach"},
    )
    client.post(
        "/api/auth/login",
        json={"username_or_email": "logout_coach", "password": "adminpass"},
    )
    assert "access_token" in client.cookies

    # GET /logout clears cookie and redirects to /login
    res = client.get("/logout", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers.get("location") == "/login"
    assert client.cookies.get("access_token") is None

    # POST /logout also works
    client.post(
        "/api/auth/login",
        json={"username_or_email": "logout_coach", "password": "adminpass"},
    )
    res_post = client.post("/logout", follow_redirects=False)
    assert res_post.status_code == 303
    assert client.cookies.get("access_token") is None


def test_student_role_access_restrictions(client):
    login_as_coach(client)
    # Create coach and 2 students
    c_res = client.post(
        "/api/users/",
        json={"username": "big_coach", "email": "big@kotchy.dev", "password": "coachpass", "role": "coach"},
    )
    s1_res = client.post(
        "/api/users/",
        json={"username": "student_one", "email": "s1@kotchy.dev", "password": "s1pass", "role": "student"},
    )
    s2_res = client.post(
        "/api/users/",
        json={"username": "student_two", "email": "s2@kotchy.dev", "password": "s2pass", "role": "student"},
    )
    s1_id = s1_res.json()["id"]
    s2_id = s2_res.json()["id"]

    # Login as student_one
    client.post(
        "/api/auth/login",
        json={"username_or_email": "student_one", "password": "s1pass"},
    )

    # Student accessing / is redirected to /my-profile
    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code == 303
    assert res_root.headers.get("location") == "/my-profile"

    # Student accessing coach-only /students or /students-page is forbidden (403)
    assert client.get("/students").status_code == 403
    assert client.get("/students-page").status_code == 403

    # Student accessing coach-only /tasks or /tasks-page is forbidden (403)
    assert client.get("/tasks").status_code == 403
    assert client.get("/tasks-page").status_code == 403

    # Student accessing /my-profile gets their own profile
    res_my_profile = client.get("/my-profile")
    assert res_my_profile.status_code == 200
    assert "student_one" in res_my_profile.text
    # Administrative button "+ Assign Task" is hidden for students
    assert "+ Assign Task" not in res_my_profile.text
    assert "← Back to Students" not in res_my_profile.text

    # Student attempting to view another student's detail is redirected to /my-profile
    res_other = client.get(f"/students/{s2_id}", follow_redirects=False)
    assert res_other.status_code == 303
    assert res_other.headers.get("location") == "/my-profile"
    assert client.get(f"/students-page/{s2_id}", follow_redirects=False).status_code == 303


def test_coach_account_exists():
    from app.core.security import verify_password

    with Session(test_engine) as session:
        from sqlmodel import select
        coach = session.exec(select(User).where(User.username == "coach")).first()
        assert coach is not None
        assert coach.email == "coach@kotchy.dev"
        assert coach.role == "coach"
        assert coach.is_active is True
        assert verify_password("adminpassword", coach.hashed_password)


def test_create_account_with_default_password(client):
    """When an account is created without password, it defaults to settings.DEFAULT_PASSWORD."""
    login_as_coach(client)
    # Create student without password
    res = client.post("/api/students/", json={"username": "nopass_student", "email": "nopass@kotchy.dev"})
    assert res.status_code == 201

    default_pwd = settings.DEFAULT_PASSWORD or "12345678"

    # Login with default password must succeed
    login_res = client.post(
        "/api/auth/login",
        json={"username_or_email": "nopass_student", "password": default_pwd},
    )
    assert login_res.status_code == 200
    assert login_res.json()["success"] is True


def test_reset_password_endpoint(client):
    """Coach can reset a user password to default; student cannot."""
    login_as_coach(client)
    # Create coach and student
    client.post(
        "/api/users/",
        json={"username": "super_coach_reset", "email": "scr@kotchy.dev", "password": "coachpass", "role": "coach"},
    )
    s_res = client.post(
        "/api/users/",
        json={"username": "user_to_reset", "email": "utr@kotchy.dev", "password": "custompass999", "role": "student"},
    )
    user_id = s_res.json()["id"]

    # Student cannot reset password (unauthenticated -> 401, student auth -> 403)
    client.get("/logout")
    res_unauth = client.post(f"/api/users/{user_id}/reset-password")
    assert res_unauth.status_code == 401

    # Login as student
    client.post("/api/auth/login", json={"username_or_email": "user_to_reset", "password": "custompass999"})
    res_student_forbidden = client.post(f"/api/users/{user_id}/reset-password")
    assert res_student_forbidden.status_code == 403

    # Login as coach
    client.post("/api/auth/login", json={"username_or_email": "super_coach_reset", "password": "coachpass"})

    # Reset student password
    res_reset = client.post(f"/api/users/{user_id}/reset-password")
    assert res_reset.status_code == 200
    assert res_reset.json()["success"] is True
    default_pwd = res_reset.json()["default_password"]

    # Student can now login with default password
    res_new_login = client.post(
        "/api/auth/login",
        json={"username_or_email": "user_to_reset", "password": default_pwd},
    )
    assert res_new_login.status_code == 200


def test_coach_edit_student_data_and_ui(client):
    """Coach can edit all student profile data and see the edit modal in UI."""
    login_as_coach(client)
    client.post(
        "/api/users/",
        json={"username": "editor_coach", "email": "ec@kotchy.dev", "password": "coachpass", "role": "coach"},
    )
    s_res = client.post(
        "/api/users/",
        json={"username": "editable_student", "email": "es@kotchy.dev", "password": "pass", "role": "student"},
    )
    s_id = s_res.json()["id"]

    # Login as coach
    client.post("/api/auth/login", json={"username_or_email": "editor_coach", "password": "coachpass"})

    # Edit student data
    update_payload = {
        "username": "edited_student_name",
        "email": "edited_email@kotchy.dev",
        "phone_number": "+201012345678",
        "cf_handle": "edited_cf",
        "vjudge_handle": "edited_vj",
        "atcoder_handle": "edited_atc",
        "cses_id": "99999",
        "linkedin_url": "https://linkedin.com/in/edited",
        "description": "Updated ICPC candidate notes",
    }
    put_res = client.put(f"/api/users/{s_id}", json=update_payload)
    assert put_res.status_code == 200
    data = put_res.json()
    assert data["username"] == "edited_student_name"
    assert data["phone_number"] == "+201012345678"
    assert data["cf_handle"] == "edited_cf"
    assert data["description"] == "Updated ICPC candidate notes"

    # Profile view as coach contains Edit Profile and edit-student-modal
    page_res = client.get(f"/students/{s_id}")
    assert page_res.status_code == 200
    assert "Edit Profile" in page_res.text
    assert "edit-student-modal" in page_res.text
    assert "Reset Account Password" in page_res.text
    assert client.get(f"/students-page/{s_id}").status_code == 200

    # Student viewing personal profile sees Edit Profile and edit-student-modal, but not coach controls
    client.post("/api/auth/login", json={"username_or_email": "edited_student_name", "password": "pass"})
    my_page = client.get("/my-profile")
    assert my_page.status_code == 200
    assert "Edit Profile" in my_page.text
    assert "edit-student-modal" in my_page.text
    assert "Reset Account Password" not in my_page.text

    # Student updates own profile via /api/auth/profile
    self_edit_res = client.put(
        "/api/auth/profile",
        json={
            "username": "self_edited_student",
            "email": "self_edited@kotchy.dev",
            "phone_number": "+201199999999",
            "cf_handle": "self_cf",
            "role": "coach",  # Attempting privilege escalation
        },
    )
    assert self_edit_res.status_code == 200
    self_data = self_edit_res.json()
    assert self_data["username"] == "self_edited_student"
    assert self_data["email"] == "self_edited@kotchy.dev"
    assert self_data["phone_number"] == "+201199999999"
    assert self_data["role"] == "student"  # Role remained student


def test_contest_task_page_no_direct_link_and_green_solved_problem(client):
    """Contest task page removes Direct Link column and highlights user solved problems in green."""
    login_as_coach(client)
    # Create coach and student
    coach_res = client.post(
        "/api/users/",
        json={"username": "c_coach", "email": "cc@kotchy.dev", "password": "pass", "role": "coach"},
    )
    student_res = client.post(
        "/api/users/",
        json={"username": "c_solver", "email": "cs@kotchy.dev", "password": "pass", "role": "student"},
    )
    student_id = student_res.json()["id"]

    # Create CF_CONTEST task
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "Educational CF Contest 100",
            "task_type": "CF_CONTEST",
            "config": {
                "contest_id": 2000,
                "min_solved": 2,
                "problems": [
                    {"index": "A", "name": "Array Sorting"},
                    {"index": "B", "name": "Binary Search"},
                ],
            },
        },
    )
    task_id = t_res.json()["id"]

    # Assign task to student
    a_res = client.post(
        "/api/assignments/",
        json={"student_id": student_id, "task_id": task_id},
    )
    assign_id = a_res.json()["id"]

    with Session(test_engine) as session:
        assignment = session.get(StudentTask, assign_id)
        assignment.checker_result = {
            "solved_count": 1,
            "solved_problems": ["A"],
            "per_problem": {
                "A": {"solved": True, "attempts": 1},
                "B": {"solved": False, "attempts": 2},
            },
        }
        session.add(assignment)
        session.commit()

    # Login as student
    client.post("/api/auth/login", json={"username_or_email": "c_solver", "password": "pass"})
    with patch(
        "app.domain.codeforces.contest.get_contest_problems",
        return_value=[
            {"index": "A", "name": "Array Sorting"},
            {"index": "B", "name": "Binary Search"},
        ],
    ):
        page_res = client.get(f"/tasks/{task_id}")
        assert page_res.status_code == 200
        html = page_res.text

    # 1. Direct Link column header and cells are removed
    assert "<th class=\"py-2.5 px-4 text-right w-28\">Direct Link</th>" not in html
    assert "Direct Link" not in html

    # 2. Problem A is solved by user -> shows green row styling and anchor
    assert "border-l-emerald-500" in html
    assert "is-solved" in html
    assert "Array Sorting" in html
    assert "bg-emerald-600 text-white" not in html

    # 3. Standings tab problem A cell is green
    assert "bg-emerald-100" in html


# ── High Security & Access Restriction Tests ──────────────────
def test_unauthenticated_api_access_blocked(client):
    """Unauthenticated access to any administrative API endpoint must return 401 Unauthorized."""
    endpoints = [
        ("POST", "/api/tasks/", {"title": "Hack", "task_type": "CF_SHEET", "config": {}}),
        ("GET", "/api/tasks/", None),
        ("GET", "/api/tasks/1", None),
        ("PUT", "/api/tasks/1", {"title": "Hack"}),
        ("DELETE", "/api/tasks/1", None),
        ("POST", "/api/students/", {"username": "hack", "email": "hack@kotchy.dev"}),
        ("GET", "/api/students/", None),
        ("GET", "/api/students/1", None),
        ("PUT", "/api/students/1", {"username": "hack"}),
        ("DELETE", "/api/students/1", None),
        ("POST", "/api/users/", {"username": "hack", "email": "hack@kotchy.dev"}),
        ("GET", "/api/users/", None),
        ("GET", "/api/users/1", None),
        ("PUT", "/api/users/1", {"username": "hack"}),
        ("DELETE", "/api/users/1", None),
        ("POST", "/api/assignments/", {"student_id": 1, "task_id": 1}),
        ("GET", "/api/assignments/1", None),
        ("GET", "/api/assignments/student/1", None),
        ("POST", "/api/assignments/1/check", None),
    ]

    for method, url, json_data in endpoints:
        if method == "POST":
            res = client.post(url, json=json_data)
        elif method == "GET":
            res = client.get(url)
        elif method == "PUT":
            res = client.put(url, json=json_data)
        elif method == "DELETE":
            res = client.delete(url)
        assert res.status_code == 401, f"{method} {url} returned {res.status_code}, expected 401"


def test_student_cannot_access_coach_apis(client):
    """A student account must not be able to edit, create, or delete any task, user, or assignment."""
    login_as_coach(client)
    # Create student
    s_res = client.post("/api/users/", json={"username": "restricted_student", "email": "rs@kotchy.dev", "password": "pass", "role": "student"})
    assert s_res.status_code == 201

    # Login as student
    login_res = client.post("/api/auth/login", json={"username_or_email": "restricted_student", "password": "pass"})
    assert login_res.status_code == 200

    coach_only_endpoints = [
        ("POST", "/api/tasks/", {"title": "Hack Task", "task_type": "CF_SHEET", "config": {}}),
        ("GET", "/api/tasks/", None),
        ("GET", "/api/tasks/1", None),
        ("PUT", "/api/tasks/1", {"title": "Modified"}),
        ("DELETE", "/api/tasks/1", None),
        ("POST", "/api/students/", {"username": "new_student", "email": "ns@kotchy.dev"}),
        ("GET", "/api/students/", None),
        ("GET", "/api/students/1", None),
        ("PUT", "/api/students/1", {"username": "hacked"}),
        ("DELETE", "/api/students/1", None),
        ("POST", "/api/users/", {"username": "new_user", "email": "nu@kotchy.dev"}),
        ("GET", "/api/users/", None),
        ("GET", "/api/users/1", None),
        ("PUT", "/api/users/1", {"username": "hacked"}),
        ("DELETE", "/api/users/1", None),
        ("POST", "/api/assignments/", {"student_id": 1, "task_id": 1}),
        ("GET", "/tasks", None),
        ("GET", "/tasks-page", None),
    ]

    for method, url, json_data in coach_only_endpoints:
        if method == "POST":
            res = client.post(url, json=json_data)
        elif method == "GET":
            res = client.get(url)
        elif method == "PUT":
            res = client.put(url, json=json_data)
        elif method == "DELETE":
            res = client.delete(url)
        assert res.status_code == 403, f"{method} {url} returned {res.status_code}, expected 403"


def test_student_assignment_isolation_and_check(client):
    """Students can only view and check their own assigned tasks, not other students' tasks."""
    login_as_coach(client)

    # 1. Create two students
    s1_res = client.post("/api/users/", json={"username": "alice", "email": "alice@kotchy.dev", "password": "pass", "role": "student"})
    s2_res = client.post("/api/users/", json={"username": "bob_secure", "email": "bob_sec@kotchy.dev", "password": "pass", "role": "student"})
    alice_id = s1_res.json()["id"]
    bob_id = s2_res.json()["id"]

    # 2. Create two tasks
    t1_res = client.post("/api/tasks/", json={"title": "Alice Task", "task_type": "CF_SHEET", "config": {"problems": ["4A"]}})
    t2_res = client.post("/api/tasks/", json={"title": "Bob Task", "task_type": "CF_SHEET", "config": {"problems": ["71A"]}})
    t1_id = t1_res.json()["id"]
    t2_id = t2_res.json()["id"]

    # 3. Assign Task 1 to Alice, Task 2 to Bob
    a1_res = client.post("/api/assignments/", json={"student_id": alice_id, "task_id": t1_id})
    a2_res = client.post("/api/assignments/", json={"student_id": bob_id, "task_id": t2_id})
    alice_assign_id = a1_res.json()["id"]
    bob_assign_id = a2_res.json()["id"]

    # 4. Login as Alice
    client.post("/api/auth/login", json={"username_or_email": "alice", "password": "pass"})

    # Alice CANNOT view Bob's task detail page
    bob_page_res = client.get(f"/tasks/{t2_id}")
    assert bob_page_res.status_code == 403
    assert client.get(f"/tasks-page/{t2_id}").status_code == 403

    # Alice CANNOT view Bob's assignment API
    bob_assign_res = client.get(f"/api/assignments/{bob_assign_id}")
    assert bob_assign_res.status_code == 403

    # Alice CANNOT view Bob's assignments list API
    bob_list_res = client.get(f"/api/assignments/student/{bob_id}")
    assert bob_list_res.status_code == 403

    # Alice CANNOT check Bob's assignment
    bob_check_res = client.post(f"/api/assignments/{bob_assign_id}/check")
    assert bob_check_res.status_code == 403

    # Alice CAN view her own assigned task page
    alice_page_res = client.get(f"/tasks/{t1_id}")
    assert alice_page_res.status_code == 200
    assert "Alice Task" in alice_page_res.text
    # Delete button is not present for Alice
    assert "Delete" not in alice_page_res.text
    assert client.get(f"/tasks-page/{t1_id}").status_code == 200

    # Alice CAN view her own assignment details API
    alice_get_assign = client.get(f"/api/assignments/{alice_assign_id}")
    assert alice_get_assign.status_code == 200

    # Alice CAN view her own assignments list API
    alice_get_list = client.get(f"/api/assignments/student/{alice_id}")
    assert alice_get_list.status_code == 200

    # Alice CAN run check on her own assignment
    mock_checker = MagicMock()
    mock_checker.check.return_value = {
        "status": "completed",
        "after_deadline": False,
        "details": {"solved": ["4A"], "solved_count": 1, "missing_problems": []},
    }
    with patch("app.api.assignments.TaskFactory.create", return_value=mock_checker):
        alice_check_res = client.post(f"/api/assignments/{alice_assign_id}/check")
        assert alice_check_res.status_code == 200
        assert alice_check_res.json()["status"] == "completed"


def test_batch_assignment_api_lifecycle(client):
    """Test POST /api/assignments/batch atomic multi-student assignment."""
    from datetime import datetime, timedelta, timezone

    # 1. Coach logs in
    login_as_coach(client)

    # 2. Create task
    task_res = client.post(
        "/api/tasks/",
        json={
            "title": "Batch Test Task",
            "task_type": "CF_SHEET",
            "config": {"problems": ["158A", "4C"], "min_solved_count": 1},
        },
    )
    assert task_res.status_code == 201
    task_id = task_res.json()["id"]

    # 3. Create 3 students
    s1 = client.post("/api/students/", json={"username": "batch_s1", "email": "bs1@test.com", "password": "pass"}).json()["id"]
    s2 = client.post("/api/students/", json={"username": "batch_s2", "email": "bs2@test.com", "password": "pass"}).json()["id"]
    s3 = client.post("/api/students/", json={"username": "batch_s3", "email": "bs3@test.com", "password": "pass"}).json()["id"]

    # 4. Batch assign with deduplicated IDs
    start = datetime.now(timezone.utc).isoformat()
    dl = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    batch_res = client.post(
        "/api/assignments/batch",
        json={
            "task_id": task_id,
            "student_ids": [s1, s2, s3, s1],  # s1 duplicated
            "start_date": start,
            "deadline": dl,
        },
    )
    assert batch_res.status_code == 201
    data = batch_res.json()
    assert data["success"] is True
    assert data["assigned_count"] == 3
    assert len(data["assignments"]) == 3

    # 5. Idempotent re-run updates schedule without duplicate records
    new_dl = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    re_batch = client.post(
        "/api/assignments/batch",
        json={
            "task_id": task_id,
            "student_ids": [s1, s2],
            "deadline": new_dl,
        },
    )
    assert re_batch.status_code == 201
    assert re_batch.json()["assigned_count"] == 2

    # Verify no duplicates created
    s1_assignments = client.get(f"/api/assignments/student/{s1}").json()
    assert len([a for a in s1_assignments if a["task_id"] == task_id]) == 1

    # 6. Reject coach assignment in batch
    coach_res = client.post(
        "/api/users/",
        json={"username": "batch_test_coach", "email": "btc@test.com", "role": "coach"},
    )
    assert coach_res.status_code == 201
    coach_id = coach_res.json()["id"]

    coach_batch = client.post(
        "/api/assignments/batch",
        json={
            "task_id": task_id,
            "student_ids": [s1, coach_id],
        },
    )
    assert coach_batch.status_code == 400
    assert "Cannot assign tasks to a coach account" in coach_batch.json()["detail"]

    # 7. Non-existent student returns 404
    missing_batch = client.post(
        "/api/assignments/batch",
        json={
            "task_id": task_id,
            "student_ids": [999999],
        },
    )
    assert missing_batch.status_code == 404

    # 8. Student accounts cannot call batch assign
    client.post("/api/auth/logout")
    login_res = client.post("/api/auth/login", json={"username_or_email": "batch_s1", "password": "pass"})
    assert login_res.status_code == 200
    forbidden_batch = client.post(
        "/api/assignments/batch",
        json={"task_id": task_id, "student_ids": [s2]},
    )
    assert forbidden_batch.status_code == 403


def test_codeforces_sheet_task_check_preindexed():
    """Verify CodeforcesSheetTask.check O(N+P) pre-indexing logic."""
    from datetime import datetime, timezone
    from app.domain.codeforces.sheet import CodeforcesSheetTask
    from app.models.student_task import StudentTask
    from app.models.user import User

    student = User(id=10, username="cf_hero", email="hero@test.com", cf_handle="HeroCF")
    deadline = datetime(2026, 6, 1, tzinfo=timezone.utc)
    st = StudentTask(id=1, student_id=10, task_id=1, deadline=deadline)

    sheet = CodeforcesSheetTask(problems=["158A", "4C", "71A"], min_solved_count=2)

    fake_submissions = [
        # 158A solved ON TIME
        {
            "verdict": "OK",
            "problem": {"contestId": 158, "index": "A"},
            "creationTimeSeconds": int(datetime(2026, 5, 10, tzinfo=timezone.utc).timestamp()),
        },
        # 4C solved AFTER DEADLINE
        {
            "verdict": "OK",
            "problem": {"contestId": 4, "index": "C"},
            "creationTimeSeconds": int(datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp()),
        },
        # 71A has WRONG_ANSWER only
        {
            "verdict": "WRONG_ANSWER",
            "problem": {"contestId": 71, "index": "A"},
            "creationTimeSeconds": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
        },
    ]

    with patch("app.domain.codeforces.sheet.get_user_submissions", return_value=fake_submissions):
        result = sheet.check(student, st)

    assert result["status"] == "late"  # 2 solved >= min 2, but 1 was after deadline
    assert result["after_deadline"] is True
    details = result["details"]
    assert details["solved_count"] == 2
    assert "158A" in details["solved"]
    assert "4C" in details["solved"]
    assert "71A" in details["unsolved"]
    assert "4C" in details["solved_after_deadline"]
    assert details["problems"]["158A"]["solved"] is True
    assert details["problems"]["158A"]["after_deadline"] is False
    assert details["problems"]["4C"]["solved"] is True
    assert details["problems"]["4C"]["after_deadline"] is True
    assert details["problems"]["71A"]["solved"] is False


def test_user_submissions_caching_and_clear():
    """Verify Codeforces API user submissions cache with TTL and clear."""
    from app.services.codeforces_api import (
        clear_user_submissions_cache,
        get_user_submissions,
    )

    clear_user_submissions_cache()

    sample_subs = [{"id": 1, "verdict": "OK", "problem": {"contestId": 1, "index": "A"}}]

    with patch("app.services.codeforces_api._request", return_value=sample_subs) as mock_req:
        # First call fetches from API and caches
        subs1 = get_user_submissions("tourist")
        assert subs1 == sample_subs
        assert mock_req.call_count == 1

        # Second call returns cached data without calling API
        subs2 = get_user_submissions("tourist")
        assert subs2 == sample_subs
        assert mock_req.call_count == 1

        # Clear cache and verify subsequent call hits API
        clear_user_submissions_cache()
        subs3 = get_user_submissions("tourist")
        assert subs3 == sample_subs
        assert mock_req.call_count == 2


def test_assignments_page_coach_access_and_rendering(client):
    """Test /assignments and /assignments-page access control and rendering."""
    # 1. Unauthenticated redirect
    res_unauth = client.get("/assignments", follow_redirects=False)
    assert res_unauth.status_code == 303
    assert res_unauth.headers.get("location") == "/login?next=/assignments"
    assert client.get("/assignments-page", follow_redirects=False).status_code == 303

    # 2. Coach access
    login_as_coach(client)
    res_coach = client.get("/assignments")
    assert res_coach.status_code == 200
    assert "Assignments Command Center" in res_coach.text
    assert "Total Assignments" in res_coach.text
    assert client.get("/assignments-page").status_code == 200

    # 3. Student access restricted
    client.post("/api/auth/logout")
    client.post(
        "/api/students/",
        json={"username": "assign_student", "email": "as@test.com", "password": "pass"},
    )
    login_res = client.post("/api/auth/login", json={"username_or_email": "assign_student", "password": "pass"})
    assert login_res.status_code == 200

    res_student = client.get("/assignments", follow_redirects=False)
    assert res_student.status_code in (403, 303)


def test_assignments_api_list_and_delete(client):
    """Test GET /api/assignments/ and DELETE /api/assignments/{id} APIs."""
    login_as_coach(client)

    # Create task & student
    task_res = client.post(
        "/api/tasks/",
        json={
            "title": "Assignment Test Task",
            "task_type": "CF_SHEET",
            "config": {"problems": ["1A", "2A"], "min_solved_count": 1},
        },
    )
    task_id = task_res.json()["id"]

    student_res = client.post(
        "/api/students/",
        json={"username": "assign_del_student", "email": "ads@test.com", "password": "pass"},
    )
    student_id = student_res.json()["id"]

    # Assign student
    assign_res = client.post(
        "/api/assignments/",
        json={"task_id": task_id, "student_id": student_id},
    )
    assert assign_res.status_code == 201
    assign_id = assign_res.json()["id"]

    # Coach can list all assignments
    list_res = client.get("/api/assignments/")
    assert list_res.status_code == 200
    all_assigns = list_res.json()
    assert any(a["id"] == assign_id for a in all_assigns)

    # Filter by task_id and student_id
    filter_res = client.get(f"/api/assignments/?task_id={task_id}&student_id={student_id}")
    assert filter_res.status_code == 200
    assert len(filter_res.json()) >= 1

    # Student cannot call GET /api/assignments/
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username_or_email": "assign_del_student", "password": "pass"})
    assert client.get("/api/assignments/").status_code == 403
    assert client.delete(f"/api/assignments/{assign_id}").status_code == 403

    # Coach can delete assignment
    client.post("/api/auth/logout")
    login_as_coach(client)
    del_res = client.delete(f"/api/assignments/{assign_id}")
    assert del_res.status_code == 200

    # Verify deleted
    get_res = client.get(f"/api/assignments/{assign_id}")
    assert get_res.status_code == 404


def test_student_page_coach_remove_assignment_button_and_isolation(client):
    """Test that coach sees the 'Remove' assignment button on student profile page,
    can delete the assignment, and student does NOT see the button on /my-profile."""
    login_as_coach(client)

    # 1. Create a task and a student
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "DP Practice Sheet",
            "task_type": "CF_SHEET",
            "config": {"problems": ["100A", "100B"], "min_solved_count": 2},
        },
    )
    task_id = t_res.json()["id"]

    s_res = client.post(
        "/api/students/",
        json={"username": "profile_student", "email": "ps@test.com", "password": "studentpassword"},
    )
    student_id = s_res.json()["id"]

    # 2. Assign task to student
    a_res = client.post("/api/assignments/", json={"task_id": task_id, "student_id": student_id})
    assert a_res.status_code == 201
    assign_id = a_res.json()["id"]

    # 3. Coach views /students/{student_id} -> Sees assignment, Run Check, and Remove button
    coach_view = client.get(f"/students/{student_id}")
    assert coach_view.status_code == 200
    assert "DP Practice Sheet" in coach_view.text
    assert f'id="assignment-row-{assign_id}"' in coach_view.text
    assert "delete-assignment-btn" in coach_view.text
    assert f'data-delete-id="{assign_id}"' in coach_view.text
    assert "Remove" in coach_view.text

    # 4. Student logs in and views /my-profile -> Sees task but NO delete-assignment-btn or Remove button
    client.post("/api/auth/logout")
    login_s = client.post("/api/auth/login", json={"username_or_email": "profile_student", "password": "studentpassword"})
    assert login_s.status_code == 200

    student_view = client.get("/my-profile")
    assert student_view.status_code == 200
    assert "DP Practice Sheet" in student_view.text
    assert "Run Check" in student_view.text
    # Ensure coach-only remove button is NOT present in student's profile view
    assert "delete-assignment-btn" not in student_view.text
    assert "data-delete-id" not in student_view.text
    assert "title=\"Remove assignment for this student\"" not in student_view.text

    # 5. Student cannot invoke DELETE /api/assignments/{assign_id}
    del_forbidden = client.delete(f"/api/assignments/{assign_id}")
    assert del_forbidden.status_code == 403

    # 6. Coach logs back in and deletes the assignment
    client.post("/api/auth/logout")
    login_as_coach(client)

    del_success = client.delete(f"/api/assignments/{assign_id}")
    assert del_success.status_code == 200
    assert del_success.json()["success"] is True

    # 7. Coach re-visits /students/{student_id} -> Task is gone, shows empty state
    coach_view_after = client.get(f"/students/{student_id}")
    assert coach_view_after.status_code == 200
    assert f'id="assignment-row-{assign_id}"' not in coach_view_after.text
    assert "No tasks assigned to this student yet." in coach_view_after.text


def test_task_view_cohort_checkboxes_only_show_unenrolled_and_unenroll_button(client):
    """Test that task view checkboxes only display un-enrolled students,
    and enrolled students have an X unenroll button that removes the assignment."""
    login_as_coach(client)

    # 1. Create a task and two students
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "Greedy Algorithms",
            "task_type": "CF_SHEET",
            "config": {"problems": ["158B", "4C"], "min_solved_count": 1},
        },
    )
    task_id = t_res.json()["id"]

    s1_res = client.post(
        "/api/students/",
        json={"username": "student_alpha", "email": "alpha@test.com", "password": "pass"},
    )
    s1_id = s1_res.json()["id"]

    s2_res = client.post(
        "/api/students/",
        json={"username": "student_beta", "email": "beta@test.com", "password": "pass"},
    )
    s2_id = s2_res.json()["id"]

    # 2. Before any enrollment, both alpha and beta appear in the checkboxes list
    task_page_1 = client.get(f"/tasks/{task_id}")
    assert task_page_1.status_code == 200
    assert "student_alpha" in task_page_1.text
    assert "student_beta" in task_page_1.text
    assert f'value="{s1_id}"' in task_page_1.text
    assert f'value="{s2_id}"' in task_page_1.text
    assert "No students in progress." in task_page_1.text

    # 3. Enroll student_alpha into the task
    assign_res = client.post("/api/assignments/", json={"task_id": task_id, "student_id": s1_id})
    assert assign_res.status_code == 201
    assign_id = assign_res.json()["id"]

    # 4. View task page again:
    # - student_alpha is enrolled: MUST NOT be in the checkbox list, but MUST appear in Enrolled Students with an unenroll X button
    # - student_beta is un-enrolled: MUST be in the checkbox list
    task_page_2 = client.get(f"/tasks/{task_id}")
    assert task_page_2.status_code == 200

    # student_beta is still available in checkboxes
    assert f'value="{s2_id}"' in task_page_2.text
    # student_alpha is no longer in checkboxes
    assert f'value="{s1_id}"' not in task_page_2.text

    # student_alpha is in Enrolled Students with X unenroll button
    assert f'id="assignment-row-{assign_id}"' in task_page_2.text
    assert f'data-delete-id="{assign_id}"' in task_page_2.text
    assert f'data-delete-label="student_alpha"' in task_page_2.text
    assert f'title="Unenroll student_alpha from task"' in task_page_2.text

    # 5. Enroll student_beta as well
    assign_res_2 = client.post("/api/assignments/", json={"task_id": task_id, "student_id": s2_id})
    assert assign_res_2.status_code == 201

    # 6. Now that all students are enrolled, checkbox list displays message indicating all enrolled
    task_page_3 = client.get(f"/tasks/{task_id}")
    assert task_page_3.status_code == 200
    assert "All cohort students are already enrolled" in task_page_3.text
    assert f'value="{s1_id}"' not in task_page_3.text
    assert f'value="{s2_id}"' not in task_page_3.text

    # 7. Unenroll student_alpha using the DELETE API (as the X button does)
    del_res = client.delete(f"/api/assignments/{assign_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 8. View task page after unenrollment:
    # student_alpha is back in the checkbox list!
    task_page_4 = client.get(f"/tasks/{task_id}")
    assert task_page_4.status_code == 200
    assert f'value="{s1_id}"' in task_page_4.text
    assert f'id="assignment-row-{assign_id}"' not in task_page_4.text


def test_coach_edit_task_and_recheck_all_enrolled_students(client):
    """Test that coach can edit a contest task and recheck all enrolled students at once."""
    login_as_coach(client)

    # 1. Create a CF_CONTEST task
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "Initial Contest Title",
            "description": "Initial Description",
            "task_type": "CF_CONTEST",
            "config": {"contest_id": 1900, "min_solved": 2, "access_type": "public"},
        },
    )
    assert t_res.status_code == 201
    task_id = t_res.json()["id"]

    # 2. Create 2 students and assign them
    s1 = client.post("/api/students/", json={"username": "recheck_s1", "email": "rc1@test.com", "password": "pass", "cf_handle": "h1"}).json()["id"]
    s2 = client.post("/api/students/", json={"username": "recheck_s2", "email": "rc2@test.com", "password": "pass", "cf_handle": "h2"}).json()["id"]

    client.post("/api/assignments/", json={"task_id": task_id, "student_id": s1})
    client.post("/api/assignments/", json={"task_id": task_id, "student_id": s2})

    # 3. Coach visits /tasks/{task_id} -> verifies Edit button, modal, and Recheck All button
    with patch(
        "app.domain.codeforces.contest.get_contest_problems",
        return_value=[{"index": "A", "name": "Problem A"}],
    ):
        page = client.get(f"/tasks/{task_id}")
        assert page.status_code == 200
        assert "Initial Contest Title" in page.text
        assert "Edit" in page.text
        assert 'id="edit-task-modal"' in page.text
        assert "Recheck All" in page.text
        assert f'data-recheck-task-id="{task_id}"' in page.text

    # 4. Coach edits task via PUT /api/tasks/{task_id}
    edit_res = client.put(
        f"/api/tasks/{task_id}",
        json={
            "title": "Updated Contest Title",
            "description": "Updated Contest Description",
            "config": {"contest_id": 1910, "min_solved": 3, "access_type": "private_managed"},
        },
    )
    assert edit_res.status_code == 200
    updated_data = edit_res.json()
    assert updated_data["title"] == "Updated Contest Title"
    assert updated_data["description"] == "Updated Contest Description"
    assert updated_data["config"]["contest_id"] == 1910
    assert updated_data["config"]["min_solved"] == 3
    assert updated_data["config"]["access_type"] == "private_managed"

    # 5. Coach rechecks all enrolled students via POST /api/tasks/{task_id}/check-all
    mock_status_result = {
        "contest_id": 1910,
        "total_problems": 5,
        "solved_count": 3,
        "solved_problems": ["A", "B", "C"],
        "after_deadline": False,
        "per_problem": {"A": {"solved": True}, "B": {"solved": True}, "C": {"solved": True}},
    }
    with patch("app.domain.codeforces.contest.get_contest_problems_status", return_value=mock_status_result):
        recheck_res = client.post(f"/api/tasks/{task_id}/check-all")
        assert recheck_res.status_code == 200
        data = recheck_res.json()
        assert data["checked_count"] == 2
        assert len(data["results"]) == 2
        assert all(r["status"] == "completed" for r in data["results"])

    # 6. Verify assignment status updated in DB
    assigns = client.get(f"/api/assignments/?task_id={task_id}").json()
    assert len(assigns) == 2
    assert all(a["status"] == "completed" for a in assigns)
    assert all(a["checker_result"]["solved_count"] == 3 for a in assigns)

    # 7. Student account cannot call check-all -> 403 Forbidden
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username_or_email": "recheck_s1", "password": "pass"})
    forbidden_recheck = client.post(f"/api/tasks/{task_id}/check-all")
    assert forbidden_recheck.status_code == 403


def test_contest_task_min_solved_zero_create_update_and_render(client: TestClient):
    """Verify contest task can be created and updated with min_solved = 0 (whole contest)."""
    login_as_coach(client)

    # 1. Create contest task with min_solved = 0
    create_res = client.post(
        "/api/tasks/",
        json={
            "title": "Full Contest Zero Min",
            "description": "Requires solving whole contest",
            "task_type": "CF_CONTEST",
            "config": {"contest_id": 1999, "min_solved": 0, "access_type": "public"},
        },
    )
    assert create_res.status_code == 201
    task = create_res.json()
    task_id = task["id"]
    assert task["config"]["min_solved"] == 0

    # 2. View /tasks page as coach -> should display min: All
    tasks_page = client.get("/tasks")
    assert tasks_page.status_code == 200
    assert "Full Contest Zero Min" in tasks_page.text
    assert "(min: All)" in tasks_page.text

    # 3. View /tasks/{task_id} detail page with mocked problems
    mock_problems = [
        {"index": "A", "name": "Problem A"},
        {"index": "B", "name": "Problem B"},
        {"index": "C", "name": "Problem C"},
    ]
    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=mock_problems):
        detail_page = client.get(f"/tasks/{task_id}")
        assert detail_page.status_code == 200
        assert "All (3)" in detail_page.text

    # 4. Update task min_solved to 0 explicitly
    update_res = client.put(
        f"/api/tasks/{task_id}",
        json={
            "title": "Full Contest Zero Min Updated",
            "config": {"contest_id": 1999, "min_solved": 0, "access_type": "public"},
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["config"]["min_solved"] == 0


def test_student_view_task_header_recheck_and_progress_bar(client: TestClient):
    """Test student view on task detail page: top-right recheck button & completion progress bar."""
    # 1. Coach creates task & student
    login_as_coach(client)
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "Student Target Task",
            "task_type": "CF_SHEET",
            "config": {"problems": ["158A", "71A", "4C"], "min_solved_count": 3},
        },
    )
    assert t_res.status_code == 201
    task_id = t_res.json()["id"]

    s_res = client.post(
        "/api/students/",
        json={"username": "topright_student", "email": "trs@test.com", "password": "pass", "cf_handle": "trs_handle"},
    )
    assert s_res.status_code == 201
    student_id = s_res.json()["id"]

    a_res = client.post("/api/assignments/", json={"task_id": task_id, "student_id": student_id})
    assert a_res.status_code == 201
    assign_id = a_res.json()["id"]

    # 2. Student logs in and views /tasks/{task_id}
    client.post("/api/auth/logout")
    login_res = client.post("/api/auth/login", json={"username_or_email": "topright_student", "password": "pass"})
    assert login_res.status_code == 200

    page = client.get(f"/tasks/{task_id}")
    assert page.status_code == 200
    # Top-right check button must be present for student
    assert "Recheck Submissions" in page.text
    assert f'data-check-id="{assign_id}"' in page.text
    # Progress bar and percentage must be present
    assert "0% Completed" in page.text
    assert "0/3 Solved" in page.text
    # Coach actions (Edit, Delete, Recheck All) must NOT be present
    assert "Edit Task" not in page.text
    assert "Recheck All" not in page.text


def test_student_contest_view_wrong_answer_red_highlight(client: TestClient):
    """Test that in contest task view, unsuccessful attempts (wrong answer) are shown in red."""
    # 1. Coach creates CF_CONTEST task & student
    login_as_coach(client)
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "Red WA Contest",
            "task_type": "CF_CONTEST",
            "config": {"contest_id": 1800, "min_solved": 2, "access_type": "public"},
        },
    )
    assert t_res.status_code == 201
    task_id = t_res.json()["id"]

    s_res = client.post(
        "/api/students/",
        json={"username": "contest_wa_student", "email": "wa_s@test.com", "password": "pass", "cf_handle": "wa_hero"},
    )
    assert s_res.status_code == 201
    student_id = s_res.json()["id"]

    a_res = client.post("/api/assignments/", json={"task_id": task_id, "student_id": student_id})
    assert a_res.status_code == 201
    assign_id = a_res.json()["id"]

    # 2. Update assignment checker_result to have 1 solved (A) and 1 wrong answer (B)
    with Session(test_engine) as session:
        from app.models.student_task import StudentTask
        st = session.get(StudentTask, assign_id)
        assert st is not None
        st.status = "in_progress"
        st.checker_result = {
            "contest_id": 1800,
            "solved_count": 1,
            "solved_problems": ["A"],
            "after_deadline": False,
            "per_problem": {
                "A": {"solved": True, "attempts": 1, "after_deadline": False},
                "B": {"solved": False, "attempts": 2, "after_deadline": False},
            },
        }
        session.commit()

    # 3. Student logs in and visits contest task page
    client.post("/api/auth/logout")
    login_res = client.post("/api/auth/login", json={"username_or_email": "contest_wa_student", "password": "pass"})
    assert login_res.status_code == 200

    mock_problems = [
        {"index": "A", "name": "Problem Alpha"},
        {"index": "B", "name": "Problem Beta"},
        {"index": "C", "name": "Problem Gamma"},
    ]

    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=mock_problems):
        page = client.get(f"/tasks/{task_id}")
        assert page.status_code == 200

        # Solved Problem A must be green (light stripe by default, bold on hover, no Solved badge text)
        assert "bg-emerald-50" in page.text
        assert "border-l-emerald-300" in page.text
        assert "group-hover:border-l-emerald-500" in page.text
        assert "bg-emerald-600" not in page.text

        # Wrong Answer Problem B must be highlighted in red (light stripe by default, bold on hover, no Attempted badge text)
        assert "bg-rose-50" in page.text
        assert "border-l-rose-300" in page.text
        assert "group-hover:border-l-rose-500" in page.text
        assert "bg-rose-600" not in page.text

        # The words "Wrong Answer", "Solved", and "Attempted" must not appear next to the problems
        assert "Wrong Answer" not in page.text

        # Student task header must show the deadline countdown timer
        assert "student-deadline-timer" in page.text
        assert "data-deadline=" in page.text
        assert "Time Left:" in page.text


def test_student_task_view_deadline_timer(client):
    """Verify that student task view renders the deadline timer at top right with UTC ISO deadline."""
    # 1. Coach creates task & student
    login_as_coach(client)
    t_res = client.post(
        "/api/tasks/",
        json={
            "title": "Timer Test Contest",
            "task_type": "CF_CONTEST",
            "config": {"contest_id": 1900, "min_solved": 1, "access_type": "public"},
        },
    )
    assert t_res.status_code == 201
    task_id = t_res.json()["id"]

    s_res = client.post(
        "/api/students/",
        json={"username": "timer_student", "email": "timer_s@test.com", "password": "pass", "cf_handle": "timer_cf"},
    )
    assert s_res.status_code == 201
    student_id = s_res.json()["id"]

    # 2. Assign with explicit deadline 48 hours from now
    from datetime import datetime, timedelta, timezone
    target_dl = datetime.now(timezone.utc) + timedelta(days=2)
    a_res = client.post(
        "/api/assignments/",
        json={
            "task_id": task_id,
            "student_id": student_id,
            "deadline": target_dl.isoformat(),
        },
    )
    assert a_res.status_code == 201

    # 3. Coach view should NOT show student-deadline-timer
    coach_page = client.get(f"/tasks/{task_id}")
    assert coach_page.status_code == 200
    assert "student-deadline-timer" not in coach_page.text

    # 4. Student logs in and views task
    client.post("/api/auth/logout")
    login_res = client.post("/api/auth/login", json={"username_or_email": "timer_student", "password": "pass"})
    assert login_res.status_code == 200

    with patch("app.domain.codeforces.contest.get_contest_problems", return_value=[{"index": "A", "name": "Problem A"}]):
        student_page = client.get(f"/tasks/{task_id}")
        assert student_page.status_code == 200
        assert "student-deadline-timer" in student_page.text
        assert "Time Left:" in student_page.text
        assert "data-deadline=" in student_page.text
        assert "Recheck Submissions" in student_page.text


def test_profile_tasks_sorting_order(client: TestClient):
    """Verify that tasks in student profile are sorted: in_progress top, pending after, completed last."""
    login_as_coach(client)

    # 1. Create a student
    s_res = client.post(
        "/api/students/",
        json={"username": "sort_student", "email": "sort_s@test.com", "password": "pass"},
    )
    student_id = s_res.json()["id"]

    # 2. Create 3 tasks
    t1 = client.post("/api/tasks/", json={"title": "Task InProgress", "task_type": "CF_SHEET", "config": {"problems": ["1A"]}}).json()["id"]
    t2 = client.post("/api/tasks/", json={"title": "Task Pending", "task_type": "CF_SHEET", "config": {"problems": ["2A"]}}).json()["id"]
    t3 = client.post("/api/tasks/", json={"title": "Task Completed", "task_type": "CF_SHEET", "config": {"problems": ["3A"]}}).json()["id"]

    # 3. Assign tasks to student
    a1 = client.post("/api/assignments/", json={"task_id": t1, "student_id": student_id}).json()["id"]
    a2 = client.post("/api/assignments/", json={"task_id": t2, "student_id": student_id}).json()["id"]
    a3 = client.post("/api/assignments/", json={"task_id": t3, "student_id": student_id}).json()["id"]

    # Set statuses directly: a1 -> in_progress, a2 -> pending, a3 -> completed
    from sqlmodel import Session
    from app.models.student_task import StudentTask
    with Session(test_engine) as db:
        st1 = db.get(StudentTask, a1)
        st1.status = "in_progress"
        st2 = db.get(StudentTask, a2)
        st2.status = "pending"
        st3 = db.get(StudentTask, a3)
        st3.status = "completed"
        db.commit()

    # 4. View /students/{id} as coach
    page = client.get(f"/students/{student_id}")
    assert page.status_code == 200
    pos_in_prog = page.text.find(f'id="assignment-row-{a1}"')
    pos_pending = page.text.find(f'id="assignment-row-{a2}"')
    pos_completed = page.text.find(f'id="assignment-row-{a3}"')

    assert pos_in_prog != -1 and pos_pending != -1 and pos_completed != -1
    assert pos_in_prog < pos_pending < pos_completed


def test_profile_progress_bar_only_for_in_progress(client):
    """Verify that only in-progress tasks show the progress bar and percentage."""
    # 1. Create coach & student
    login_as_coach(client)
    res = client.post("/api/students/", json={
        "username": "prog_bar_student",
        "email": "prog_bar_student@test.com",
        "password": "password123",
    })
    student_id = res.json()["id"]

    # 2. Create tasks with 2 problems each
    t_in_prog = client.post("/api/tasks/", json={
        "title": "Task In Progress Bar",
        "task_type": "CF_SHEET",
        "config": {"problems": ["1A", "1B"]}
    }).json()["id"]
    t_pending = client.post("/api/tasks/", json={
        "title": "Task Pending Bar",
        "task_type": "CF_SHEET",
        "config": {"problems": ["2A", "2B"]}
    }).json()["id"]
    t_completed = client.post("/api/tasks/", json={
        "title": "Task Completed Bar",
        "task_type": "CF_SHEET",
        "config": {"problems": ["3A", "3B"]}
    }).json()["id"]

    # 3. Assign tasks
    a_prog = client.post("/api/assignments/", json={"task_id": t_in_prog, "student_id": student_id}).json()["id"]
    a_pend = client.post("/api/assignments/", json={"task_id": t_pending, "student_id": student_id}).json()["id"]
    a_comp = client.post("/api/assignments/", json={"task_id": t_completed, "student_id": student_id}).json()["id"]

    # 4. Set statuses and checker_result:
    # a_prog: in_progress with 1/2 solved (50%)
    # a_pend: pending with 0/2 solved
    # a_comp: completed with 2/2 solved
    with Session(test_engine) as db:
        st_prog = db.get(StudentTask, a_prog)
        st_prog.status = "in_progress"
        st_prog.checker_result = {"solved_count": 1}

        st_pend = db.get(StudentTask, a_pend)
        st_pend.status = "pending"
        st_pend.checker_result = {"solved_count": 0}

        st_comp = db.get(StudentTask, a_comp)
        st_comp.status = "completed"
        st_comp.checker_result = {"solved_count": 2}

        db.commit()

    # 5. Fetch student detail page
    page = client.get(f"/students/{student_id}")
    assert page.status_code == 200

    pos_prog = page.text.find(f'id="assignment-row-{a_prog}"')
    pos_pend = page.text.find(f'id="assignment-row-{a_pend}"')
    pos_comp = page.text.find(f'id="assignment-row-{a_comp}"')
    assert pos_prog != -1 and pos_pend != -1 and pos_comp != -1

    row_prog_html = page.text[pos_prog:pos_pend]
    row_pend_html = page.text[pos_pend:pos_comp]
    row_comp_html = page.text[pos_comp:pos_comp + 1500]

    # In-progress row MUST have the percentage (50%) and the progress bar
    assert "50%" in row_prog_html
    assert 'style="width: 50%;"' in row_prog_html
    assert "Progress" in row_prog_html

    # Pending row MUST NOT have progress bar or percentage bar
    assert 'style="width:' not in row_pend_html
    assert "Progress Bar" not in row_pend_html

    # Completed row MUST NOT have progress bar or percentage bar
    assert 'style="width:' not in row_comp_html
    assert "Progress Bar" not in row_comp_html

