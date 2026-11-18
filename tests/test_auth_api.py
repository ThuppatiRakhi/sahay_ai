"""Integration tests for Phase 2: Authentication API Integration.

Validates the end-to-end integration of:
- POST /auth/signup
- POST /auth/login
- POST /auth/logout
- GET /auth/csrf-token

Covers all 13 required scenarios:
1. Successful signup creates a session.
2. Successful login creates a session.
3. Invalid password does not create a session.
4. Duplicate signup does not create a new session.
5. Inactive account cannot log in.
6. Login response never exposes raw session ID.
7. Session cookie has correct security flags.
8. CSRF token can be obtained after login.
9. Logout revokes the session.
10. Logout clears session and CSRF cookies.
11. Revoked sessions cannot access protected endpoints.
12. Logout rejects invalid CSRF tokens.
13. Existing authentication behavior remains compatible.
"""

from datetime import datetime, timezone
import hashlib
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import (
    generate_csrf_token,
    get_session_config,
    reset_session_config,
)
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database for API tests."""
    db_file = tmp_path / "test_auth_api.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def auth_env(test_db, monkeypatch):
    """Configures isolated auth service and session manager for testing."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    # Patch module singletons
    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "account_mgr": accounts,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
    }


@pytest.fixture
def client(auth_env):
    """TestClient against the SahayAI FastAPI application."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_01_successful_signup_creates_session(client, auth_env):
    """Scenario 1: Successful signup creates a server-side session and sets HttpOnly cookie."""
    session_mgr = auth_env["session_mgr"]
    test_db = auth_env["db"]
    cfg = get_session_config()

    res = client.post(
        "/auth/signup",
        json={"email": "new.citizen@example.com", "password": "StrongPassword@123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["next_step"] == "CREATE_PROFILE"
    assert data["profile_required"] is True
    user_id = data["user"]["user_id"]

    # Verify session cookie was attached
    raw_token = res.cookies.get(cfg.cookie_name)
    assert raw_token is not None, "Session cookie missing from signup response"
    assert len(raw_token) >= 32

    # Verify session exists in SQLite and validates
    validated = session_mgr.validate_session(raw_token)
    assert validated is not None
    assert validated["user_id"] == user_id
    assert validated["revoked_at"] is None

    # Verify database stores SHA-256 hash, not the raw token
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with test_db.get_connection() as conn:
        row = conn.execute("SELECT * FROM user_sessions WHERE session_id = ?", (expected_hash,)).fetchone()
    assert row is not None
    assert row["user_id"] == user_id


def test_02_successful_login_creates_session(client, auth_env):
    """Scenario 2: Successful login creates a new server-side session and sets cookie."""
    auth_svc = auth_env["auth_service"]
    session_mgr = auth_env["session_mgr"]
    cfg = get_session_config()

    signup_result = auth_svc.signup(
        email="login.test@example.com",
        password="ValidPassword@123",
    )
    user_id = signup_result["user"]["user_id"]

    res = client.post(
        "/auth/login",
        json={"identifier": "login.test@example.com", "password": "ValidPassword@123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["user"]["user_id"] == user_id

    # Verify cookie and session in DB
    raw_token = res.cookies.get(cfg.cookie_name)
    assert raw_token is not None
    validated = session_mgr.validate_session(raw_token)
    assert validated is not None
    assert validated["user_id"] == user_id


def test_03_invalid_password_does_not_create_session(client, auth_env):
    """Scenario 3: Invalid password fails authentication and creates no session."""
    auth_svc = auth_env["auth_service"]
    test_db = auth_env["db"]
    cfg = get_session_config()

    auth_svc.signup(
        email="login.fail@example.com",
        password="CorrectPassword@123",
    )

    with test_db.get_connection() as conn:
        initial_count = conn.execute("SELECT count(*) as c FROM user_sessions").fetchone()["c"]

    res = client.post(
        "/auth/login",
        json={"identifier": "login.fail@example.com", "password": "WrongPassword@123"},
    )
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()

    # Verify no cookie set
    assert cfg.cookie_name not in res.cookies

    # Verify no session added to database
    with test_db.get_connection() as conn:
        after_count = conn.execute("SELECT count(*) as c FROM user_sessions").fetchone()["c"]
    assert after_count == initial_count


def test_04_duplicate_signup_does_not_create_new_session(client, auth_env):
    """Scenario 4: Duplicate signup returns HTTP 409 and does not create an extra session."""
    auth_svc = auth_env["auth_service"]
    test_db = auth_env["db"]
    cfg = get_session_config()

    auth_svc.signup(
        email="duplicate.test@example.com",
        password="FirstPassword@123",
    )

    with test_db.get_connection() as conn:
        initial_count = conn.execute("SELECT count(*) as c FROM user_sessions").fetchone()["c"]

    res = client.post(
        "/auth/signup",
        json={"email": "duplicate.test@example.com", "password": "SecondPassword@123"},
    )
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"].lower()
    assert cfg.cookie_name not in res.cookies

    with test_db.get_connection() as conn:
        after_count = conn.execute("SELECT count(*) as c FROM user_sessions").fetchone()["c"]
    assert after_count == initial_count


def test_05_inactive_account_cannot_login(client, auth_env):
    """Scenario 5: Disabled user cannot log in and no session is created."""
    auth_svc = auth_env["auth_service"]
    test_db = auth_env["db"]
    cfg = get_session_config()

    signup_result = auth_svc.signup(
        email="disabled.citizen@example.com",
        password="ValidPassword@123",
    )
    user_id = signup_result["user"]["user_id"]

    # Mark account DISABLED in SQLite
    with test_db.get_connection() as conn:
        conn.execute("UPDATE users SET account_status = 'DISABLED' WHERE user_id = ?", (user_id,))
        initial_count = conn.execute("SELECT count(*) as c FROM user_sessions").fetchone()["c"]

    res = client.post(
        "/auth/login",
        json={"identifier": "disabled.citizen@example.com", "password": "ValidPassword@123"},
    )
    assert res.status_code == 401
    assert cfg.cookie_name not in res.cookies

    with test_db.get_connection() as conn:
        after_count = conn.execute("SELECT count(*) as c FROM user_sessions").fetchone()["c"]
    assert after_count == initial_count


def test_06_login_response_never_exposes_raw_session_id(client, auth_env):
    """Scenario 6: Neither signup nor login responses ever expose raw session IDs in JSON."""
    res = client.post(
        "/auth/signup",
        json={"email": "privacy.test@example.com", "password": "PrivacyPassword@123"},
    )
    cfg = get_session_config()
    raw_token = res.cookies.get(cfg.cookie_name)
    assert raw_token is not None

    data_signup = res.json()
    assert raw_token not in str(data_signup)
    assert "session_id" not in data_signup

    res_login = client.post(
        "/auth/login",
        json={"identifier": "privacy.test@example.com", "password": "PrivacyPassword@123"},
    )
    login_token = res_login.cookies.get(cfg.cookie_name)
    assert login_token is not None

    data_login = res_login.json()
    assert login_token not in str(data_login)
    assert "session_id" not in data_login


def test_07_session_cookie_has_correct_security_flags(client, auth_env):
    """Scenario 7: Session cookie has HttpOnly, SameSite=Lax, and Path=/."""
    cfg = get_session_config()

    res = client.post(
        "/auth/signup",
        json={"email": "flags.test@example.com", "password": "ValidPassword@123"},
    )
    assert res.status_code == 200

    set_cookie_headers = res.headers.get_list("set-cookie")
    session_hdr = next((h for h in set_cookie_headers if cfg.cookie_name in h), None)
    assert session_hdr is not None

    assert "httponly" in session_hdr.lower()
    assert "samesite=lax" in session_hdr.lower()
    assert "path=/" in session_hdr.lower()


def test_08_csrf_token_can_be_obtained_after_login(client, auth_env):
    """Scenario 8: GET /auth/csrf-token succeeds after login, providing CSRF token and cookie."""
    auth_svc = auth_env["auth_service"]
    cfg = get_session_config()

    auth_svc.signup(
        email="csrf.citizen@example.com",
        password="ValidPassword@123",
    )

    # 1. Login
    login_res = client.post(
        "/auth/login",
        json={"identifier": "csrf.citizen@example.com", "password": "ValidPassword@123"},
    )
    assert login_res.status_code == 200
    raw_session_id = login_res.cookies.get(cfg.cookie_name)
    assert raw_session_id is not None

    # 2. Request CSRF token using the session cookie
    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_data = csrf_res.json()
    assert csrf_data["success"] is True
    assert "csrf_token" in csrf_data
    token = csrf_data["csrf_token"]
    assert len(token) == 64

    # Verify CSRF cookie is set and accessible (not HttpOnly)
    set_cookie_headers = csrf_res.headers.get_list("set-cookie")
    csrf_cookie_hdr = next((h for h in set_cookie_headers if cfg.csrf_cookie_name in h), None)
    assert csrf_cookie_hdr is not None
    assert "httponly" not in csrf_cookie_hdr.lower()
    assert "path=/" in csrf_cookie_hdr.lower()


def test_09_logout_revokes_the_session(client, auth_env):
    """Scenario 9: POST /auth/logout marks the session as revoked in SQLite."""
    session_mgr = auth_env["session_mgr"]
    test_db = auth_env["db"]
    cfg = get_session_config()

    # 1. Signup and establish session
    signup_res = client.post(
        "/auth/signup",
        json={"email": "logout.citizen@example.com", "password": "ValidPassword@123"},
    )
    raw_token = signup_res.cookies.get(cfg.cookie_name)

    # 2. Get CSRF token
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    # 3. Call logout
    logout_res = client.post(
        "/auth/logout",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True
    assert "logged out" in logout_res.json()["message"].lower()

    # 4. Verify session is revoked in SQLite
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with test_db.get_connection() as conn:
        row = conn.execute("SELECT * FROM user_sessions WHERE session_id = ?", (token_hash,)).fetchone()
    assert row is not None
    assert row["revoked_at"] is not None

    # validate_session must now return None
    assert session_mgr.validate_session(raw_token) is None


def test_10_logout_clears_session_and_csrf_cookies(client, auth_env):
    """Scenario 10: POST /auth/logout clears both session and CSRF cookies."""
    cfg = get_session_config()

    client.post(
        "/auth/signup",
        json={"email": "cookies.logout@example.com", "password": "ValidPassword@123"},
    )
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    logout_res = client.post(
        "/auth/logout",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert logout_res.status_code == 200

    set_cookies = logout_res.headers.get_list("set-cookie")
    session_hdr = next((h for h in set_cookies if cfg.cookie_name in h), None)
    csrf_hdr = next((h for h in set_cookies if cfg.csrf_cookie_name in h), None)

    assert session_hdr is not None, "Expected clear-cookie header for sahay_session"
    assert csrf_hdr is not None, "Expected clear-cookie header for sahay_csrf"

    assert "max-age=0" in session_hdr.lower() or "expires=" in session_hdr.lower()
    assert "max-age=0" in csrf_hdr.lower() or "expires=" in csrf_hdr.lower()


def test_11_revoked_session_cannot_access_protected_endpoints(client, auth_env):
    """Scenario 11: Once revoked, the session cannot obtain a new CSRF token or logout again."""
    cfg = get_session_config()

    client.post(
        "/auth/signup",
        json={"email": "revoked.access@example.com", "password": "ValidPassword@123"},
    )
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    # Logout
    logout_res = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert logout_res.status_code == 200

    # Attempt to use revoked session to get CSRF token
    attempt_csrf = client.get("/auth/csrf-token")
    assert attempt_csrf.status_code == 401

    # Attempt second logout with revoked session
    attempt_logout = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert attempt_logout.status_code == 401


def test_12_logout_rejects_invalid_csrf_tokens(client, auth_env):
    """Scenario 12: Logout strictly enforces CSRF: missing, invalid, or untrusted origin fails."""
    session_mgr = auth_env["session_mgr"]
    cfg = get_session_config()

    client.post(
        "/auth/signup",
        json={"email": "csrf.logout@example.com", "password": "ValidPassword@123"},
    )
    raw_token = client.cookies.get(cfg.cookie_name)

    # 1. Missing CSRF token -> 403 Forbidden
    res_no_token = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500"},
    )
    assert res_no_token.status_code == 403
    assert "csrf token missing" in res_no_token.json()["detail"].lower()

    # Verify session was NOT revoked
    assert session_mgr.validate_session(raw_token) is not None

    # 2. Invalid/forged CSRF token -> 403 Forbidden
    res_bad_token = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": "bad_csrf_token_value_123"},
    )
    assert res_bad_token.status_code == 403
    assert "csrf token validation failed" in res_bad_token.json()["detail"].lower()
    assert session_mgr.validate_session(raw_token) is not None

    # 3. Untrusted Origin -> 403 Forbidden
    valid_csrf = generate_csrf_token(raw_token)
    res_bad_origin = client.post(
        "/auth/logout",
        headers={"Origin": "http://malicious-site.example.com", "X-CSRF-Token": valid_csrf},
    )
    assert res_bad_origin.status_code == 403
    assert "not authorized" in res_bad_origin.json()["detail"].lower()
    assert session_mgr.validate_session(raw_token) is not None


def test_13_existing_authentication_behavior_remains_compatible(client, auth_env):
    """Scenario 13: Backward compatibility for user payload, profile_required, and next_step."""
    auth_svc = auth_env["auth_service"]

    # 1. Signup response payload structure
    signup_res = client.post(
        "/auth/signup",
        json={"email": "compat.citizen@example.com", "password": "ValidPassword@123"},
    )
    assert signup_res.status_code == 200
    data = signup_res.json()
    assert data["message"] == "Account created successfully."
    assert data["profile_required"] is True
    assert data["next_step"] == "CREATE_PROFILE"
    assert "user" in data
    assert data["user"]["email"] == "compat.citizen@example.com"
    assert data["user"]["account_status"] == "ACTIVE"

    # 2. Login response payload structure when profile is absent
    login_res = client.post(
        "/auth/login",
        json={"identifier": "compat.citizen@example.com", "password": "ValidPassword@123"},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["message"] == "Login successful."
    assert login_data["profile_required"] is True
    assert login_data["next_step"] == "CREATE_PROFILE"
    assert login_data["profile"] is None

    # 3. Login response payload structure when citizen profile is present
    user_id = data["user"]["user_id"]
    auth_svc.create_profile_for_user(
        user_id=user_id,
        profile_data={
            "full_name": "Compat Citizen",
            "date_of_birth": "2000-01-01",
            "age": 26,
            "gender": "FEMALE",
            "state": "Telangana",
            "district": "Hyderabad",
            "annual_income": 250000,
            "occupation": "STUDENT",
            "caste_category": "OBC",
            "is_bpl": False,
        },
    )

    login_profile_res = client.post(
        "/auth/login",
        json={"identifier": "compat.citizen@example.com", "password": "ValidPassword@123"},
    )
    assert login_profile_res.status_code == 200
    lp_data = login_profile_res.json()
    assert lp_data["profile_required"] is False
    assert lp_data["next_step"] == "DASHBOARD"
    assert lp_data["profile"]["full_name"] == "Compat Citizen"

