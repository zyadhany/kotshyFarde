"""
tests/test_codeforces_rating.py
───────────────────────────────
Unit tests for Codeforces user rating and user info retrieval, caching,
and profile rendering with Codeforces rank colors.
"""

from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from app.core.cache import cache
from app.core.config import settings
from app.core.database import engine
from app.models.user import User
from app.services.codeforces_api import (
    CodeforcesService,
    clear_user_ratings_cache,
    codeforces_service,
    get_rating_class,
    get_rating_color,
    get_rating_title,
    get_user_info,
    get_user_rating,
    prefetch_cf_info,
    verify_handle,
)
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from app.core.database import get_session
from app.main import app

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    with Session(test_engine) as session:
        yield session


@pytest.fixture(autouse=True)
def setup_isolated_db(monkeypatch):
    monkeypatch.setattr("app.main.init_db", lambda: None)
    SQLModel.metadata.create_all(test_engine)
    app.dependency_overrides[get_session] = override_get_session
    with Session(test_engine) as session:
        from app.core.security import get_password_hash
        coach = User(
            username="coach",
            email="coach@kotshy.dev",
            hashed_password=get_password_hash("adminpassword"),
            role="coach",
            is_active=True,
        )
        session.add(coach)
        session.commit()
    yield
    SQLModel.metadata.drop_all(test_engine)
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_user_ratings_cache()
    yield
    clear_user_ratings_cache()


def test_get_user_rating_fetches_and_caches():
    mock_cf_response = [
        {
            "handle": "tourist",
            "rating": 3900,
            "maxRating": 4009,
            "rank": "legendary grandmaster",
            "maxRank": "tourist",
        }
    ]

    with patch("app.services.codeforces_api._request", return_value=mock_cf_response) as mock_req:
        rating = get_user_rating("tourist")
        assert rating == 3900
        assert mock_req.call_count == 1

        # Check that it's cached in user_ratings
        cached_rating = cache["user_ratings"].get("tourist")
        assert cached_rating == 3900

        # Check remaining TTL is <= settings.CF_RATING_CACHE_LIFETIME (3600s)
        ttl = cache["user_ratings"].get_ttl("tourist")
        assert ttl is not None
        assert 3500 <= ttl <= 3600

        # Second call must hit cache and NOT invoke _request
        second_rating = get_user_rating("tourist")
        assert second_rating == 3900
        assert mock_req.call_count == 1


def test_get_user_rating_case_insensitive():
    mock_cf_response = [{"handle": "tourist", "rating": 3900}]

    with patch("app.services.codeforces_api._request", return_value=mock_cf_response) as mock_req:
        r1 = get_user_rating("Tourist")
        r2 = get_user_rating("TOURIST")
        assert r1 == 3900
        assert r2 == 3900
        assert mock_req.call_count == 1


def test_get_user_rating_unrated_user():
    # Brand new users have no "rating" key in user.info
    mock_cf_response = [{"handle": "newbie_user", "rank": "unrated"}]

    with patch("app.services.codeforces_api._request", return_value=mock_cf_response):
        rating = get_user_rating("newbie_user")
        assert rating is None


def test_get_user_rating_handles_error():
    with patch("app.services.codeforces_api._request", side_effect=RuntimeError("User not found")):
        rating = get_user_rating("nonexistent_user_999")
        assert rating is None


def test_get_user_info_caches_both_info_and_rating():
    mock_cf_response = [
        {
            "handle": "Petr",
            "rating": 3000,
            "maxRating": 3100,
            "rank": "international grandmaster",
        }
    ]

    with patch("app.services.codeforces_api._request", return_value=mock_cf_response) as mock_req:
        info = get_user_info("Petr")
        assert info is not None
        assert info["rating"] == 3000
        assert info["maxRating"] == 3100
        assert mock_req.call_count == 1

        # Both user_info and user_ratings are populated
        assert cache["user_info"].get("petr") == mock_cf_response[0]
        assert cache["user_ratings"].get("petr") == 3000

        # Calling get_user_rating now serves directly from cache without API call
        rating = get_user_rating("petr")
        assert rating == 3000
        assert mock_req.call_count == 1


def test_verify_handle_uses_user_info():
    with patch("app.services.codeforces_api._request", return_value=[{"handle": "tourist", "rating": 3900}]):
        assert verify_handle("tourist") is True

    with patch("app.services.codeforces_api._request", side_effect=RuntimeError("handle not found")):
        assert verify_handle("invalid_handle_xyz") is False


def test_settings_cache_lifetimes():
    assert settings.CF_RATING_CACHE_LIFETIME == 3600
    assert settings.CF_SUBMISSIONS_CACHE_LIFETIME == 30


def test_rating_thresholds_and_styling():
    """Verify Codeforces rating style mappings (Pupil: green, Expert: blue, etc.)."""
    # Unrated
    assert get_rating_class(None) == "cf-user-unrated"
    assert get_rating_title(None) == "Unrated"

    # Newbie (< 1200): Gray
    assert get_rating_class(1000) == "cf-user-newbie"
    assert get_rating_color(1000) == "#808080"
    assert get_rating_title(1000) == "Newbie"

    # Pupil (1200 - 1399): Green
    assert get_rating_class(1250) == "cf-user-pupil"
    assert get_rating_color(1250) == "#008000"
    assert get_rating_title(1250) == "Pupil"

    # Specialist (1400 - 1599): Cyan
    assert get_rating_class(1500) == "cf-user-specialist"
    assert get_rating_color(1500) == "#03a89e"
    assert get_rating_title(1500) == "Specialist"

    # Expert (1600 - 1899): Blue
    assert get_rating_class(1750) == "cf-user-expert"
    assert get_rating_color(1750) == "#0000ff"
    assert get_rating_title(1750) == "Expert"

    # Candidate Master (1900 - 2099): Purple
    assert get_rating_class(2000) == "cf-user-candidate-master"
    assert get_rating_color(2000) == "#aa00aa"

    # Master / International Master (2100 - 2399): Orange
    assert get_rating_class(2200) == "cf-user-master"
    assert get_rating_color(2200) == "#ff8c00"

    # Grandmaster (2400+): Red
    assert get_rating_class(2500) == "cf-user-grandmaster"
    assert get_rating_color(2500) == "#ff0000"

    # Legendary Grandmaster (3000+)
    assert get_rating_class(3500) == "cf-user-legendary"
    assert get_rating_color(3500) == "#ff0000"


def test_prefetch_cf_info_batches_multiple_handles():
    mock_batch_res = [
        {"handle": "user_a", "rating": 1300, "maxRating": 1350, "rank": "pupil"},
        {"handle": "user_b", "rating": 1700, "maxRating": 1750, "rank": "expert"},
    ]

    with patch("app.services.codeforces_api._request", return_value=mock_batch_res) as mock_req:
        res = prefetch_cf_info(["user_a", "user_b"])
        assert "user_a" in res
        assert "user_b" in res
        assert res["user_a"]["rating"] == 1300
        assert res["user_b"]["rating"] == 1700
        assert mock_req.call_count == 1

        # Values are now cached in cache["user_ratings"]
        assert cache["user_ratings"].get("user_a") == 1300
        assert cache["user_ratings"].get("user_b") == 1700


def test_user_model_rating_properties():
    # User with no cf_handle
    u_none = User(username="unrated_u", email="u@test.com", hashed_password="pw", cf_handle=None)
    assert u_none.get_cf_rating() is None
    assert u_none.cf_rating_class == "cf-user-unrated"

    # User with cf_handle
    u_expert = User(username="expert_coder", email="e@test.com", hashed_password="pw", cf_handle="expert_coder")
    with patch("app.services.codeforces_api._request", return_value=[{"handle": "expert_coder", "rating": 1650, "maxRating": 1720, "rank": "expert"}]):
        assert u_expert.get_cf_rating() == 1650
        assert u_expert.cf_rating_class == "cf-user-expert"
        assert u_expert.cf_rating_color == "#0000ff"
        assert u_expert.cf_rating_title == "Expert"


def test_student_profile_renders_current_and_max_rating():
    """Verify that student profile displays username with CF rank styling, current rating, and max rating."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Login as coach
    login_res = client.post("/api/auth/login", json={"username_or_email": "coach", "password": "adminpassword"})
    assert login_res.status_code == 200

    mock_cf_profile = [
        {
            "handle": "pupil_cf",
            "rating": 1280,
            "maxRating": 1390,
            "rank": "pupil",
            "maxRank": "pupil",
        }
    ]

    import uuid
    uniq = str(uuid.uuid4())[:8]

    with patch("app.services.codeforces_api._request", return_value=mock_cf_profile):
        # Create a pupil student
        s_res = client.post(
            "/api/students/",
            json={"username": f"pupil_{uniq}", "email": f"pupil_{uniq}@test.com", "password": "pass", "cf_handle": "pupil_cf"},
        )
        assert s_res.status_code == 201
        student_id = s_res.json()["id"]

        page = client.get(f"/students/{student_id}")
        assert page.status_code == 200

        # Username styled with pupil class (green)
        assert "cf-user-pupil" in page.text
        assert f"pupil_{uniq}" in page.text

        # Shows current rate
        assert "1280" in page.text
        # Shows max rate
        assert "1390" in page.text
        # Shows rating label
        assert "Rating:" in page.text
        assert "Max:" in page.text


def test_user_cf_title_photo_normalization():
    """Verify that titlePhoto URL is normalized from userpic.codeforces.org to codeforces.com/userpic."""
    # 1. Full URL with userpic.codeforces.org
    raw_1 = "https://userpic.codeforces.org/2817810/title/1b956a5bf70207e3.jpg"
    assert User._normalize_cf_photo_url(raw_1) == "https://codeforces.com/userpic/2817810/title/1b956a5bf70207e3.jpg"

    # 2. Protocol-relative URL
    raw_2 = "//userpic.codeforces.org/no-title.jpg"
    assert User._normalize_cf_photo_url(raw_2) == "https://codeforces.com/userpic/no-title.jpg"

    # 3. Path-only URL
    raw_3 = "/userpic/no-title.jpg"
    assert User._normalize_cf_photo_url(raw_3) == "https://codeforces.com/userpic/no-title.jpg"

    # 4. None / empty
    assert User._normalize_cf_photo_url(None) is None
    assert User._normalize_cf_photo_url("") is None

    # Test on User instance with mock
    u = User(username="phototest", email="photo@test.com", hashed_password="pw", cf_handle="phototest")
    mock_data = {
        "handle": "phototest",
        "titlePhoto": "https://userpic.codeforces.org/123/title/abc.jpg",
        "avatar": "https://userpic.codeforces.org/123/avatar/def.jpg",
    }
    with patch("app.services.codeforces_api._request", return_value=[mock_data]):
        assert u.cf_title_photo == "https://codeforces.com/userpic/123/title/abc.jpg"
        assert u.cf_avatar_url == "https://codeforces.com/userpic/123/avatar/def.jpg"


def test_codeforces_service_class_instance_and_context_manager():
    """Verify that CodeforcesService can be instantiated directly, used as a context manager,
    re-uses HTTP connections, and provides identical helper methods."""
    custom_service = CodeforcesService(
        base_url="https://codeforces.com/api",
        min_request_interval=0.01,
        timeout=10.0,
        api_key="dummy_key",
        api_secret="dummy_secret",
    )
    assert custom_service.base_url == "https://codeforces.com/api"
    assert custom_service.min_request_interval == 0.01
    assert custom_service.timeout == 10.0

    # Test static helper methods on class and instance
    assert custom_service.get_rating_class(1550) == "cf-user-specialist"
    assert CodeforcesService.get_rating_class(1950) == "cf-user-candidate-master"
    assert custom_service.parse_problem_id("158A") == (158, "A")
    assert custom_service.standardize_verdict("OK") == "ACCEPTED"

    # Test context manager and client cleanup
    with custom_service as s:
        client = s.client
        assert client is not None
        assert not client.is_closed

    # After exit, client should be closed
    assert custom_service._client is None

    # Test singleton instance availability
    assert isinstance(codeforces_service, CodeforcesService)
