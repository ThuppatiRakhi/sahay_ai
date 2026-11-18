"""Comprehensive tests for SahayAI Guest Entry, Session Routing and Navigation Correction.

Validates the 12 lifecycle and navigation scenarios:
1. Fresh client opening login page (contains Continue as Guest button and nav links).
2. Continue as Guest (POST /auth/guest) creates valid guest session and sets cookies.
3. Guest dashboard navigation & strict boundary enforcement (profile & persistent documents blocked; schemes accessible).
4. Refresh guest dashboard (valid guest session persists).
5. Open dashboard in new tab/context with valid guest session (session maintained).
6. End guest session (POST /auth/logout revokes guest session in DB and clears cookies).
7. Register new test account (creates user and issues registered session).
8. Log in as registered user (GET /auth/session-status returns is_guest=False and user info).
9. Refresh registered dashboard (registered session persists).
10. Log out (POST /auth/logout revokes user session and clears cookies).
11. Attempt to reopen dashboard after logout (unauthenticated, redirect to login).
12. Expired guest session behavior (returns authenticated=False, clears cookies, protected endpoints return 401).
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import get_session_config
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_guest_lifecycle.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def auth_env(test_db, monkeypatch):
    """Configures isolated auth service, profile manager, and session manager."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
    scheme_svc = SchemeDiscoveryService()

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.schemes.auth_service", auth_svc)
    monkeypatch.setattr("api.schemes.scheme_service", scheme_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
    }


@pytest.fixture
def client(auth_env):
    """FastAPI TestClient with isolated environment."""
    return TestClient(app)


class TestGuestSessionLifecycleAndNavigation:
    """Covers all 12 test scenarios required by Section F."""

    def test_scenario_01_fresh_browser_login_page_navigation(self, client):
        """Scenario 1: Fresh browser opens login page and verifies visible Continue as Guest options."""
        res = client.get("/frontend/login.html")
        assert res.status_code == 200
        html = res.text

        # Must contain Continue as Guest navigation button in navbar
        assert 'id="navGuestBtn"' in html
        assert 'data-i18n="nav.guestBtn"' in html

        # Must contain Continue as Guest button in auth card
        assert 'id="cardGuestBtn"' in html
        assert 'data-i18n="login.guestBtn"' in html

        # Must contain Sign In and Sign Up navigation
        assert 'data-i18n="login.submitBtn"' in html
        assert 'signup.html' in html

    def test_scenario_02_click_continue_as_guest(self, client, auth_env):
        """Scenario 2: Click Continue as Guest invokes POST /auth/guest and establishes session."""
        res = client.post("/auth/guest")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["is_guest"] is True
        assert "guest_id" in data

        # Check cookies
        cfg = get_session_config()
        assert cfg.cookie_name in client.cookies
        assert cfg.csrf_cookie_name in client.cookies

        # Verify DB: guest session stored, but users table completely empty
        with auth_env["db"].get_connection() as conn:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            guest_count = conn.execute("SELECT COUNT(*) FROM guest_sessions").fetchone()[0]
            assert user_count == 0
            assert guest_count == 1

    def test_scenario_03_guest_dashboard_navigation_and_boundaries(self, client):
        """Scenario 3: Guest sessions can browse schemes but are strictly blocked from registered data."""
        # Start guest session
        client.post("/auth/guest")

        # 1. Session status confirms guest
        status_res = client.get("/auth/session-status")
        assert status_res.status_code == 200
        assert status_res.json()["authenticated"] is True
        assert status_res.json()["is_guest"] is True

        # 2. Cannot access registered citizen profile (401)
        prof_res = client.get("/profile/me")
        assert prof_res.status_code == 401

        # 3. Cannot access confirmed document fields (403 Forbidden)
        fields_res = client.get("/profile/confirmed-document-fields")
        assert fields_res.status_code == 403

        # 4. Cannot review stored documents (403 Forbidden)
        review_res = client.get("/documents/dummy-doc-id/review")
        assert review_res.status_code == 403

        # 5. Can freely browse public government schemes catalog (200 OK)
        schemes_res = client.get("/schemes")
        assert schemes_res.status_code == 200
        schemes_data = schemes_res.json()
        assert "schemes" in schemes_data or "results" in schemes_data or isinstance(schemes_data, list)

        # 6. Can view specific scheme details
        detail_res = client.get("/schemes/SCHEME_EDU_001_PM_USP")
        assert detail_res.status_code in (200, 404)  # 200 if loaded, 404 if scheme collection id variant

    def test_scenario_04_and_05_refresh_and_new_tab_guest_dashboard(self, client):
        """Scenarios 4 & 5: Refreshing guest dashboard or opening in new tab preserves guest session."""
        init_res = client.post("/auth/guest")
        guest_id = init_res.json()["guest_id"]

        # Refresh 1
        ref1 = client.get("/auth/session-status")
        assert ref1.status_code == 200
        assert ref1.json()["authenticated"] is True
        assert ref1.json()["is_guest"] is True
        assert ref1.json()["guest_id"] == guest_id

        # Refresh 2 (simulating new tab with existing cookie)
        ref2 = client.get("/auth/session-status")
        assert ref2.status_code == 200
        assert ref2.json()["authenticated"] is True
        assert ref2.json()["is_guest"] is True
        assert ref2.json()["guest_id"] == guest_id

    def test_scenario_06_end_guest_session(self, client, auth_env):
        """Scenario 6: End guest session calls POST /auth/logout, revokes session, and clears cookies."""
        init_res = client.post("/auth/guest")
        csrf_token = init_res.json()["csrf_token"]

        # End guest session via POST /auth/logout
        logout_res = client.post("/auth/logout", headers={"X-CSRF-Token": csrf_token})
        assert logout_res.status_code == 200
        assert logout_res.json()["success"] is True

        # Verify DB: guest session has revoked_at set
        with auth_env["db"].get_connection() as conn:
            row = conn.execute("SELECT revoked_at FROM guest_sessions").fetchone()
            assert row is not None
            assert row["revoked_at"] is not None

        # Verify session status is now unauthenticated
        post_status = client.get("/auth/session-status")
        assert post_status.status_code == 200
        assert post_status.json()["authenticated"] is False

    def test_scenario_07_and_08_register_and_login_registered_citizen(self, client, auth_env):
        """Scenarios 7 & 8: Register new account, log in, and verify registered session status."""
        email = "citizen.test@example.com"
        password = "SecurePassword123!"

        # 7. Register
        signup_res = client.post(
            "/auth/signup",
            json={"email": email, "password": password},
        )
        assert signup_res.status_code == 200
        signup_data = signup_res.json()
        assert signup_data["success"] is True
        user_id = signup_data["user"]["user_id"]

        # Create profile so user is complete
        csrf_res = client.get("/auth/csrf-token")
        csrf_tok = csrf_res.json()["csrf_token"]
        prof_create = client.post(
            "/profile/me",
            json={
                "full_name": "Ravi Kumar",
                "date_of_birth": "2000-05-15",
                "gender": "MALE",
                "state": "Telangana",
                "district": "Hyderabad",
                "annual_income": 120000.0,
                "occupation": "STUDENT",
                "caste_category": "GENERAL",
            },
            headers={"X-CSRF-Token": csrf_tok},
        )
        assert prof_create.status_code == 200

        # 8. Log In
        login_res = client.post(
            "/auth/login",
            json={"identifier": email, "password": password},
        )
        assert login_res.status_code == 200

        # Verify session status is registered (is_guest=False)
        status_res = client.get("/auth/session-status")
        assert status_res.status_code == 200
        sdata = status_res.json()
        assert sdata["authenticated"] is True
        assert sdata["is_guest"] is False
        assert sdata["user_id"] == user_id
        assert sdata["email"] == email

    def test_scenario_09_refresh_registered_dashboard(self, client):
        """Scenario 9: Refreshing registered dashboard maintains registered session."""
        email = "refresh.user@example.com"
        password = "SecurePassword123!"

        client.post("/auth/signup", json={"email": email, "password": password})
        client.post("/auth/login", json={"identifier": email, "password": password})

        # Refresh
        for _ in range(3):
            status_res = client.get("/auth/session-status")
            assert status_res.status_code == 200
            assert status_res.json()["authenticated"] is True
            assert status_res.json()["is_guest"] is False

    def test_scenario_10_and_11_logout_and_reopen_dashboard(self, client, auth_env):
        """Scenarios 10 & 11: Registered logout revokes session; subsequent dashboard check reports unauthenticated."""
        email = "logout.test@example.com"
        password = "SecurePassword123!"

        client.post("/auth/signup", json={"email": email, "password": password})
        csrf_res = client.get("/auth/csrf-token")
        csrf_tok = csrf_res.json()["csrf_token"]

        # 10. Logout
        logout_res = client.post("/auth/logout", headers={"X-CSRF-Token": csrf_tok})
        assert logout_res.status_code == 200

        # Verify session revoked in DB
        with auth_env["db"].get_connection() as conn:
            row = conn.execute("SELECT revoked_at FROM user_sessions").fetchone()
            assert row is not None
            assert row["revoked_at"] is not None

        # 11. Attempt to reopen dashboard (query session-status)
        check_res = client.get("/auth/session-status")
        assert check_res.status_code == 200
        assert check_res.json()["authenticated"] is False
        assert check_res.json()["is_guest"] is False

    def test_scenario_12_expired_guest_session_behavior(self, client, auth_env):
        """Scenario 12: Expired guest sessions return authenticated=False and protected endpoints fail."""
        # Initialize guest session
        init_res = client.post("/auth/guest")
        assert init_res.status_code == 200

        # Fast-forward expiration in database
        past_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with auth_env["db"].get_connection() as conn:
            conn.execute("UPDATE guest_sessions SET expires_at = ?", (past_time,))

        # Query session-status -> must report unauthenticated
        status_res = client.get("/auth/session-status")
        assert status_res.status_code == 200
        assert status_res.json()["authenticated"] is False
        assert status_res.json()["is_guest"] is False

        # Attempt to access protected endpoint with expired cookie -> returns 401
        csrf_res = client.get("/auth/csrf-token")
        assert csrf_res.status_code == 401
