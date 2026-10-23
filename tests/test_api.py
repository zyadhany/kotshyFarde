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
def setup_database(monkeypatch):
    monkeypatch.setattr("app.main.init_db", lambda: None)
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        from app.core.database import seed_default_coach
        seed_default_coach(session)
    yield
    SQLModel.metadata.drop_all(test_engine)


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
    res = client.post("/students/", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["id"] is not None
    assert data["username"] == "ahmed_aly"
    assert data["cf_handle"] == "ahmed_cf"
    assert data["role"].lower() == "student"
    student_id = data["id"]

    # Duplicate student fails
    res_dup = client.post("/students/", json=payload)
    assert res_dup.status_code == 400

    # Get single student
    res_get = client.get(f"/students/{student_id}")
    assert res_get.status_code == 200
    assert res_get.json()["email"] == "ahmed@example.com"
    assert res_get.json()["role"].lower() == "student"

    # Get non-existent student -> 404
    assert client.get("/students/99999").status_code == 404

    # List students
    res_list = client.get("/students/")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

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
    login_as_coach(client)

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
    login_as_coach(client)
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
    login_as_coach(client)
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
    # Authenticate as coach first
    login_as_coach(client)

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

    res_students = client.get("/students-page", follow_redirects=False)
    assert res_students.status_code == 303
    assert res_students.headers.get("location") == "/login?next=/students-page"

    res_tasks = client.get("/tasks-page", follow_redirects=False)
    assert res_tasks.status_code == 303
    assert res_tasks.headers.get("location") == "/login?next=/tasks-page"

    res_my_profile = client.get("/my-profile", follow_redirects=False)
    assert res_my_profile.status_code == 303
    assert res_my_profile.headers.get("location") == "/login?next=/my-profile"


def test_login_api_coach_and_cookie(client):
    login_as_coach(client)
    client.post(
        "/users/",
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
        "/users/",
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
        "/users/",
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
        "/users/",
        json={"username": "deactivated_user", "email": "deact@kotchy.dev", "password": "pass", "role": "student"},
    )
    d_id = d_res.json()["id"]
    client.put(f"/users/{d_id}", json={"is_active": False})

    res_deact = client.post(
        "/api/auth/login",
        json={"username_or_email": "deactivated_user", "password": "pass"},
    )
    assert res_deact.status_code == 403
    assert "deactivated" in res_deact.json()["detail"].lower()


def test_logout_lifecycle(client):
    login_as_coach(client)
    client.post(
        "/users/",
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
        "/users/",
        json={"username": "big_coach", "email": "big@kotchy.dev", "password": "coachpass", "role": "coach"},
    )
    s1_res = client.post(
        "/users/",
        json={"username": "student_one", "email": "s1@kotchy.dev", "password": "s1pass", "role": "student"},
    )
    s2_res = client.post(
        "/users/",
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

    # Student accessing coach-only /students-page is forbidden (403)
    res_students = client.get("/students-page")
    assert res_students.status_code == 403

    # Student accessing coach-only /tasks-page is forbidden (403)
    res_tasks = client.get("/tasks-page")
    assert res_tasks.status_code == 403

    # Student accessing /my-profile gets their own profile
    res_my_profile = client.get("/my-profile")
    assert res_my_profile.status_code == 200
    assert "student_one" in res_my_profile.text
    # Administrative button "+ Assign Task" is hidden for students
    assert "+ Assign Task" not in res_my_profile.text
    assert "← Back to Students" not in res_my_profile.text

    # Student attempting to view another student's detail is redirected to /my-profile
    res_other = client.get(f"/students-page/{s2_id}", follow_redirects=False)
    assert res_other.status_code == 303
    assert res_other.headers.get("location") == "/my-profile"


def test_seed_default_coach_creates_account():
    from app.core.database import seed_default_coach
    from app.core.security import verify_password

    with Session(test_engine) as session:
        seed_default_coach(session)

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
    res = client.post("/students/", json={"username": "nopass_student", "email": "nopass@kotchy.dev"})
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
        "/users/",
        json={"username": "super_coach_reset", "email": "scr@kotchy.dev", "password": "coachpass", "role": "coach"},
    )
    s_res = client.post(
        "/users/",
        json={"username": "user_to_reset", "email": "utr@kotchy.dev", "password": "custompass999", "role": "student"},
    )
    user_id = s_res.json()["id"]

    # Student cannot reset password (unauthenticated -> 401, student auth -> 403)
    client.get("/logout")
    res_unauth = client.post(f"/users/{user_id}/reset-password")
    assert res_unauth.status_code == 401

    # Login as student
    client.post("/api/auth/login", json={"username_or_email": "user_to_reset", "password": "custompass999"})
    res_student_forbidden = client.post(f"/users/{user_id}/reset-password")
    assert res_student_forbidden.status_code == 403

    # Login as coach
    client.post("/api/auth/login", json={"username_or_email": "super_coach_reset", "password": "coachpass"})

    # Reset student password
    res_reset = client.post(f"/users/{user_id}/reset-password")
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
        "/users/",
        json={"username": "editor_coach", "email": "ec@kotchy.dev", "password": "coachpass", "role": "coach"},
    )
    s_res = client.post(
        "/users/",
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
    put_res = client.put(f"/users/{s_id}", json=update_payload)
    assert put_res.status_code == 200
    data = put_res.json()
    assert data["username"] == "edited_student_name"
    assert data["phone_number"] == "+201012345678"
    assert data["cf_handle"] == "edited_cf"
    assert data["description"] == "Updated ICPC candidate notes"

    # Profile view as coach contains Edit Profile and edit-student-modal
    page_res = client.get(f"/students-page/{s_id}")
    assert page_res.status_code == 200
    assert "Edit Profile" in page_res.text
    assert "edit-student-modal" in page_res.text
    assert "Reset Account Password" in page_res.text

    # Student viewing personal profile does NOT see Edit Profile or edit-student-modal
    client.post("/api/auth/login", json={"username_or_email": "edited_student_name", "password": "pass"})
    my_page = client.get("/my-profile")
    assert my_page.status_code == 200
    assert "Edit Profile" not in my_page.text
    assert "edit-student-modal" not in my_page.text


def test_contest_task_page_no_direct_link_and_green_solved_problem(client):
    """Contest task page removes Direct Link column and highlights user solved problems in green."""
    login_as_coach(client)
    # Create coach and student
    coach_res = client.post(
        "/users/",
        json={"username": "c_coach", "email": "cc@kotchy.dev", "password": "pass", "role": "coach"},
    )
    student_res = client.post(
        "/users/",
        json={"username": "c_solver", "email": "cs@kotchy.dev", "password": "pass", "role": "student"},
    )
    student_id = student_res.json()["id"]

    # Create CF_CONTEST task
    t_res = client.post(
        "/tasks/",
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
        "/assignments/",
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
    page_res = client.get(f"/tasks-page/{task_id}")
    assert page_res.status_code == 200
    html = page_res.text

    # 1. Direct Link column header and cells are removed
    assert "<th class=\"py-2.5 px-4 text-right w-28\">Direct Link</th>" not in html
    assert "Direct Link" not in html

    # 2. Problem A is solved by user -> shows green styling and Solved badge
    assert "border-l-emerald-500" in html
    assert "bg-emerald-600 text-white" in html
    assert "Array Sorting" in html
    assert "Solved" in html

    # 3. Standings tab problem A cell is green
    assert "bg-emerald-100" in html


# ── High Security & Access Restriction Tests ──────────────────
def test_unauthenticated_api_access_blocked(client):
    """Unauthenticated access to any administrative API endpoint must return 401 Unauthorized."""
    endpoints = [
        ("POST", "/tasks/", {"title": "Hack", "task_type": "CF_SHEET", "config": {}}),
        ("GET", "/tasks/", None),
        ("GET", "/tasks/1", None),
        ("PUT", "/tasks/1", {"title": "Hack"}),
        ("DELETE", "/tasks/1", None),
        ("POST", "/students/", {"username": "hack", "email": "hack@kotchy.dev"}),
        ("GET", "/students/", None),
        ("GET", "/students/1", None),
        ("PUT", "/students/1", {"username": "hack"}),
        ("DELETE", "/students/1", None),
        ("POST", "/users/", {"username": "hack", "email": "hack@kotchy.dev"}),
        ("GET", "/users/", None),
        ("GET", "/users/1", None),
        ("PUT", "/users/1", {"username": "hack"}),
        ("DELETE", "/users/1", None),
        ("POST", "/assignments/", {"student_id": 1, "task_id": 1}),
        ("GET", "/assignments/1", None),
        ("GET", "/assignments/student/1", None),
        ("POST", "/assignments/1/check", None),
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
    s_res = client.post("/users/", json={"username": "restricted_student", "email": "rs@kotchy.dev", "password": "pass", "role": "student"})
    assert s_res.status_code == 201

    # Login as student
    login_res = client.post("/api/auth/login", json={"username_or_email": "restricted_student", "password": "pass"})
    assert login_res.status_code == 200

    coach_only_endpoints = [
        ("POST", "/tasks/", {"title": "Hack Task", "task_type": "CF_SHEET", "config": {}}),
        ("GET", "/tasks/", None),
        ("GET", "/tasks/1", None),
        ("PUT", "/tasks/1", {"title": "Modified"}),
        ("DELETE", "/tasks/1", None),
        ("POST", "/students/", {"username": "new_student", "email": "ns@kotchy.dev"}),
        ("GET", "/students/", None),
        ("GET", "/students/1", None),
        ("PUT", "/students/1", {"username": "hacked"}),
        ("DELETE", "/students/1", None),
        ("POST", "/users/", {"username": "new_user", "email": "nu@kotchy.dev"}),
        ("GET", "/users/", None),
        ("GET", "/users/1", None),
        ("PUT", "/users/1", {"username": "hacked"}),
        ("DELETE", "/users/1", None),
        ("POST", "/assignments/", {"student_id": 1, "task_id": 1}),
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
    s1_res = client.post("/users/", json={"username": "alice", "email": "alice@kotchy.dev", "password": "pass", "role": "student"})
    s2_res = client.post("/users/", json={"username": "bob_secure", "email": "bob_sec@kotchy.dev", "password": "pass", "role": "student"})
    alice_id = s1_res.json()["id"]
    bob_id = s2_res.json()["id"]

    # 2. Create two tasks
    t1_res = client.post("/tasks/", json={"title": "Alice Task", "task_type": "CF_SHEET", "config": {"problems": ["4A"]}})
    t2_res = client.post("/tasks/", json={"title": "Bob Task", "task_type": "CF_SHEET", "config": {"problems": ["71A"]}})
    t1_id = t1_res.json()["id"]
    t2_id = t2_res.json()["id"]

    # 3. Assign Task 1 to Alice, Task 2 to Bob
    a1_res = client.post("/assignments/", json={"student_id": alice_id, "task_id": t1_id})
    a2_res = client.post("/assignments/", json={"student_id": bob_id, "task_id": t2_id})
    alice_assign_id = a1_res.json()["id"]
    bob_assign_id = a2_res.json()["id"]

    # 4. Login as Alice
    client.post("/api/auth/login", json={"username_or_email": "alice", "password": "pass"})

    # Alice CANNOT view Bob's task detail page
    bob_page_res = client.get(f"/tasks-page/{t2_id}")
    assert bob_page_res.status_code == 403

    # Alice CANNOT view Bob's assignment API
    bob_assign_res = client.get(f"/assignments/{bob_assign_id}")
    assert bob_assign_res.status_code == 403

    # Alice CANNOT view Bob's assignments list API
    bob_list_res = client.get(f"/assignments/student/{bob_id}")
    assert bob_list_res.status_code == 403

    # Alice CANNOT check Bob's assignment
    bob_check_res = client.post(f"/assignments/{bob_assign_id}/check")
    assert bob_check_res.status_code == 403

    # Alice CAN view her own assigned task page
    alice_page_res = client.get(f"/tasks-page/{t1_id}")
    assert alice_page_res.status_code == 200
    assert "Alice Task" in alice_page_res.text
    # Delete button is not present for Alice
    assert "Delete" not in alice_page_res.text

    # Alice CAN view her own assignment details API
    alice_get_assign = client.get(f"/assignments/{alice_assign_id}")
    assert alice_get_assign.status_code == 200

    # Alice CAN view her own assignments list API
    alice_get_list = client.get(f"/assignments/student/{alice_id}")
    assert alice_get_list.status_code == 200

    # Alice CAN run check on her own assignment
    mock_checker = MagicMock()
    mock_checker.check.return_value = {
        "status": "completed",
        "after_deadline": False,
        "details": {"solved": ["4A"], "solved_count": 1, "missing_problems": []},
    }
    with patch("app.api.assignments.TaskFactory.create", return_value=mock_checker):
        alice_check_res = client.post(f"/assignments/{alice_assign_id}/check")
        assert alice_check_res.status_code == 200
        assert alice_check_res.json()["status"] == "completed"




