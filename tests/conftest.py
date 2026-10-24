"""
tests/conftest.py
─────────────────
Shared fixtures for all pytest suites:
- In-memory SQLite engine
- Dependency override for get_session
- Seeded default coach user
- TestClient fixture
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.core.database import get_session
from app.core.security import get_password_hash
from app.main import app
from app.models.user import User

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
    """Helper to authenticate test client as coach."""
    res = client.post("/api/auth/login", json={"username_or_email": username, "password": password})
    assert res.status_code == 200
    return res
