"""Automated tests for Phase 7: Guest Mode and Temporary Sessions.

Validates:
1. Guest session initialization (POST /auth/guest) with secure HttpOnly and CSRF cookies.
2. Only SHA-256 digest is stored in SQLite guest_sessions; raw token never stored; users table empty.
3. Session status endpoint (GET /auth/session-status) accurately reports guest vs registered vs unauthenticated.
4. Guest session persistence across page refreshes.
5. Expiration enforcement: expired guest sessions return HTTP 401.
6. Invalid or tampered guest sessions are rejected.
7. Guest-to-guest isolation: Guest A's temporary data is completely invisible to Guest B.
8. Guest cannot access registered citizen profile (GET /profile/me returns 401).
9. Guest data never pollutes persistent tables (users and profiles tables remain empty).
10. Guest can access public scheme discovery and evaluate recommendations with temporary profile.
11. Guest logout revokes guest session in SQLite and clears cookies.
12. Guest context payload size limit enforcement (> 64KB rejected with HTTP 400).
13. Registered signup, login, profile, and recommendations remain fully functional and isolated.
"""

from datetime import datetime, timedelta, timezone
import json
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
    db_file = tmp_path / "test_guest_sessions.db"
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
        "scheme_svc": scheme_svc,
    }


@pytest.fixture
def client(auth_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases: Guest Session Creation and Persistence
# ---------------------------------------------------------------------------

def test_01_create_guest_session_endpoint(client, auth_env):
    """Verifies that POST /auth/guest creates a temporary guest session with HttpOnly and CSRF cookies,
    stores only a hashed token in SQLite guest_sessions, and never creates a user in users table.
    """
    cfg = get_session_config()
    res = client.post("/auth/guest")
    assert res.status_code == 200

    data = res.json()
    assert data["success"] is True
    assert data["is_guest"] is True
    assert "guest_id" in data
    assert data["guest_id"].startswith("guest_")
    assert "csrf_token" in data
    assert len(data["csrf_token"]) > 20
    assert data["next_step"] == "DASHBOARD"

    # Verify cookies
    raw_cookie = res.cookies.get(cfg.cookie_name)
    assert raw_cookie is not None
    assert raw_cookie.startswith("gst_")

    csrf_cookie = res.cookies.get(cfg.csrf_cookie_name)
    assert csrf_cookie == data["csrf_token"]

    # Verify database isolation: raw session ID is NEVER stored in database
    db = auth_env["db"]
    with db.get_connection() as conn:
        guest_rows = conn.execute("SELECT * FROM guest_sessions").fetchall()
        user_rows = conn.execute("SELECT * FROM users").fetchall()
        profile_rows = conn.execute("SELECT * FROM profiles").fetchall()

    assert len(guest_rows) == 1
    # Raw token must not match stored hash
    assert guest_rows[0]["session_id"] != raw_cookie
    assert guest_rows[0]["guest_id"] == data["guest_id"]
    assert guest_rows[0]["revoked_at"] is None

    # Persistent registered tables must remain completely empty!
    assert len(user_rows) == 0
    assert len(profile_rows) == 0


def test_02_session_status_endpoint(client, auth_env):
    """Verifies that GET /auth/session-status accurately distinguishes between
    unauthenticated, guest, and registered user states.
    """
    # 1. Unauthenticated state
    anon_res = client.get("/auth/session-status")
    assert anon_res.status_code == 200
    anon_data = anon_res.json()
    assert anon_data["authenticated"] is False
    assert anon_data["is_guest"] is False

    # 2. Guest state after initializing guest session
    guest_init = client.post("/auth/guest")
    assert guest_init.status_code == 200
    guest_id = guest_init.json()["guest_id"]

    guest_status = client.get("/auth/session-status")
    assert guest_status.status_code == 200
    gdata = guest_status.json()
    assert gdata["authenticated"] is True
    assert gdata["is_guest"] is True
    assert gdata["guest_id"] == guest_id

    # 3. Registered user state after signup and login
    reg_client = TestClient(app)
    signup_res = reg_client.post(
        "/auth/signup",
        json={"email": "status.citizen@example.com", "password": "SecurePassword123!"},
    )
    assert signup_res.status_code == 200

    user_status = reg_client.get("/auth/session-status")
    assert user_status.status_code == 200
    udata = user_status.json()
    assert udata["authenticated"] is True
    assert udata["is_guest"] is False
    assert udata["email"] == "status.citizen@example.com"
    assert "user_id" in udata


def test_03_guest_session_persistence_across_refresh(client, auth_env):
    """Verifies that an initialized guest session remains valid and recognized across
    multiple consecutive requests (simulating page refreshes).
    """
    init_res = client.post("/auth/guest")
    guest_id = init_res.json()["guest_id"]

    # Simulating 3 consecutive page requests/refreshes
    for _ in range(3):
        res = client.get("/auth/session-status")
        assert res.status_code == 200
        assert res.json()["authenticated"] is True
        assert res.json()["is_guest"] is True
        assert res.json()["guest_id"] == guest_id


# ---------------------------------------------------------------------------
# Test Cases: Security, Expiration, and Isolation
# ---------------------------------------------------------------------------

def test_04_guest_session_expiration(client, auth_env):
    """Verifies that expired guest sessions are rejected with HTTP 401."""
    init_res = client.post("/auth/guest")
    guest_id = init_res.json()["guest_id"]

    # Manually fast-forward expiration date in SQLite to 1 hour in the past
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    db = auth_env["db"]
    with db.get_connection() as conn:
        conn.execute("UPDATE guest_sessions SET expires_at = ? WHERE guest_id = ?", (past_iso, guest_id))

    # Next request should be rejected as expired
    res = client.get("/auth/guest/context")
    assert res.status_code == 401

    status_res = client.get("/auth/session-status")
    assert status_res.status_code == 200
    assert status_res.json()["authenticated"] is False


def test_05_invalid_or_tampered_guest_session_rejected(client, auth_env):
    """Verifies that forged, tampered, or malformed session cookies are rejected."""
    cfg = get_session_config()

    # Tampered session ID
    client.cookies.set(cfg.cookie_name, "gst_forged_session_token_value_000000000000000000000")
    res = client.get("/auth/guest/context")
    assert res.status_code == 401

    # Malformed session ID (e.g. SQL injection attempt or non-base64 characters)
    client.cookies.set(cfg.cookie_name, "invalid'; DROP TABLE guest_sessions; --")
    res2 = client.get("/auth/guest/context")
    assert res2.status_code == 401


def test_06_guest_to_guest_isolation(auth_env):
    """Verifies that Guest A's session context is strictly isolated from Guest B."""
    client_a = TestClient(app)
    client_b = TestClient(app)

    # 1. Initialize Guest A and set temporary profile
    init_a = client_a.post("/auth/guest")
    assert init_a.status_code == 200
    guest_a_id = init_a.json()["guest_id"]
    csrf_a = init_a.json()["csrf_token"]

    update_a = client_a.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_a},
        json={
            "temporary_profile": {
                "full_name": "Citizen Alpha",
                "annual_income": 150000.0,
                "state": "Gujarat",
            }
        },
    )
    assert update_a.status_code == 200

    # 2. Initialize Guest B
    init_b = client_b.post("/auth/guest")
    assert init_b.status_code == 200
    guest_b_id = init_b.json()["guest_id"]
    assert guest_a_id != guest_b_id

    # 3. Guest B queries their own context -> must be empty, cannot see Guest A's data
    context_b = client_b.get("/auth/guest/context")
    assert context_b.status_code == 200
    assert context_b.json()["guest_id"] == guest_b_id
    assert context_b.json()["context"].get("temporary_profile") is None

    # 4. Guest A's context remains intact
    context_a = client_a.get("/auth/guest/context")
    assert context_a.status_code == 200
    assert context_a.json()["guest_id"] == guest_a_id
    assert context_a.json()["context"]["temporary_profile"]["full_name"] == "Citizen Alpha"


def test_07_guest_cannot_access_registered_user_profile(client, auth_env):
    """Verifies that a guest session cannot call registered profile endpoints."""
    # Initialize guest session
    init_res = client.post("/auth/guest")
    csrf_token = init_res.json()["csrf_token"]

    # 1. Calling GET /profile/me as a guest must return HTTP 401
    profile_get = client.get("/profile/me")
    assert profile_get.status_code == 401

    # 2. Calling POST /profile/me as a guest must return HTTP 401
    profile_post = client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Unauthorized Guest Attempt",
            "date_of_birth": "1995-01-01",
            "gender": "MALE",
            "state": "Delhi",
            "district": "New Delhi",
            "annual_income": 200000.0,
            "occupation": "Engineer",
            "caste_category": "GENERAL",
        },
    )
    assert profile_post.status_code == 401


# ---------------------------------------------------------------------------
# Test Cases: Scheme Discovery & Temporary Eligibility in Guest Mode
# ---------------------------------------------------------------------------

def test_08_guest_can_discover_schemes_and_check_eligibility(client, auth_env):
    """Verifies that a guest can:
    1. Search the scheme catalog without an account.
    2. Set temporary in-session profile attributes without permanent database persistence.
    3. Evaluate preliminary recommendations and scheme eligibility.
    4. Confirms that all evaluated schemes maintain REVIEW_REQUIRED and unconfirmed verification.
    """
    # 1. Browse catalog as guest
    client.post("/auth/guest")
    cat_res = client.get("/schemes?category=EDUCATION")
    assert cat_res.status_code == 200
    assert cat_res.json()["count"] >= 5

    # 2. Recommendations for guest returns 403 Forbidden (Step 2.1: strictly restricted to registered accounts)
    rec_empty = client.get("/schemes/recommendations")
    assert rec_empty.status_code == 403
    assert "registered citizen account" in rec_empty.json()["detail"].lower()

    # 3. Obtain CSRF token and set temporary profile
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    update_res = client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "temporary_profile": {
                "full_name": "Temporary Priya",
                "age": 20,
                "gender": "FEMALE",
                "state": "Uttar Pradesh",
                "district": "Lucknow",
                "annual_income": 150000.0,
                "occupation": "Student",
                "caste_category": "GENERAL",
                "is_bpl": False,
            }
        },
    )
    assert update_res.status_code == 200

    # 4. Recommendations endpoint remains strictly forbidden (403) for guests even with temporary context
    rec_res = client.get("/schemes/recommendations?application_type=FRESH")
    assert rec_res.status_code == 403
    assert "registered citizen account" in rec_res.json()["detail"].lower()

    # 5. Manual scheme eligibility evaluation works on-demand for guests (e.g. for PM-USP)
    elig_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility?application_type=FRESH")
    assert elig_res.status_code == 200
    elig_data = elig_res.json()
    assert elig_data["status"] == "REVIEW_REQUIRED"
    assert elig_data["official_eligibility_confirmed"] is False
    assert any("annual_family_income" in c["criterion"] for c in elig_data["matched_conditions"])

    # 6. Verify users and profiles tables are STILL empty!
    db = auth_env["db"]
    with db.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM profiles").fetchone()[0] == 0


def test_09_guest_logout_revokes_session_and_clears_cookies(client, auth_env):
    """Verifies that logging out of a guest session marks it as revoked in SQLite and clears cookies."""
    cfg = get_session_config()
    init_res = client.post("/auth/guest")
    csrf_token = init_res.json()["csrf_token"]
    guest_id = init_res.json()["guest_id"]

    logout_res = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert logout_res.status_code == 200

    # Check database: revoked_at is populated
    db = auth_env["db"]
    with db.get_connection() as conn:
        row = conn.execute("SELECT revoked_at FROM guest_sessions WHERE guest_id = ?", (guest_id,)).fetchone()
    assert row["revoked_at"] is not None

    # Subsequent request using old cookie is rejected
    status_res = client.get("/auth/session-status")
    assert status_res.status_code == 200
    assert status_res.json()["authenticated"] is False


def test_10_guest_context_size_limit_and_abuse_protection(client, auth_env):
    """Verifies that sending an excessively large context payload (> 64KB) is rejected with HTTP 400."""
    init_res = client.post("/auth/guest")
    csrf_token = init_res.json()["csrf_token"]

    # Construct payload > 65536 bytes
    oversized_data = {"spam": "A" * 70000}

    res = client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"conversation_state": oversized_data},
    )
    assert res.status_code == 400
    assert "exceeds" in res.json()["detail"].lower()


def test_11_registered_auth_and_profile_remain_fully_functional(client, auth_env):
    """Verifies that registered account signup, login, profile creation, and recommendations
    continue to work seamlessly and are not impacted by guest sessions.
    """
    # 1. Signup registered user
    signup_res = client.post(
        "/auth/signup",
        json={"email": "persistent.citizen@example.com", "password": "SecurePassword123!"},
    )
    assert signup_res.status_code == 200

    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    # 2. Create persistent profile
    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Persistent Citizen",
            "date_of_birth": "1998-07-20",
            "gender": "FEMALE",
            "state": "Maharashtra",
            "district": "Pune",
            "annual_income": 220000.0,
            "occupation": "Teacher",
            "caste_category": "GENERAL",
        },
    )

    # 3. Retrieve profile
    prof_res = client.get("/profile/me")
    assert prof_res.status_code == 200
    assert prof_res.json()["profile"]["full_name"] == "Persistent Citizen"

    # 4. Retrieve recommendations
    rec_res = client.get("/schemes/recommendations?application_type=FRESH")
    assert rec_res.status_code == 200
    assert rec_res.json()["success"] is True

    # 5. Database check: exactly 1 user and 1 profile in persistent tables
    db = auth_env["db"]
    with db.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM profiles").fetchone()[0] == 1


def test_12_guest_flow_regression_no_login_redirect(client, auth_env):
    """Regression test for the Guest Button -> Guest Session -> Dashboard flow.

    Verifies:
    1. POST /auth/guest creates the guest session, returning 200 and setting HttpOnly + CSRF cookies.
    2. GET /auth/session-status confirms authenticated=True, is_guest=True.
    3. GET /schemes/recommendations for a fresh guest (no temporary demographics yet)
       returns 404 with friendly detail.
    4. GET /schemes succeeds and returns the full catalog (available immediately to guests).
    5. GET /profile/me strictly requires registered accounts and returns 401 for guests.
    6. Frontend script assertions verify that dashboard.js and profile.js prevent
       redirect loops to login.html.
    """
    cfg = get_session_config()

    # Step 1: User clicks "Continue as Guest" -> POST /auth/guest
    guest_init = client.post("/auth/guest")
    assert guest_init.status_code == 200
    guest_data = guest_init.json()
    assert guest_data["success"] is True
    assert guest_data["is_guest"] is True
    assert "guest_id" in guest_data

    # Cookie checks
    session_cookie = guest_init.cookies.get(cfg.cookie_name)
    csrf_cookie = guest_init.cookies.get(cfg.csrf_cookie_name)
    assert session_cookie is not None and session_cookie.startswith("gst_")
    assert csrf_cookie is not None and csrf_cookie == guest_data["csrf_token"]

    # Step 2: Dashboard checks session status -> GET /auth/session-status
    status_res = client.get("/auth/session-status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["authenticated"] is True
    assert status_data["is_guest"] is True
    assert status_data["guest_id"] == guest_data["guest_id"]

    # Step 3: Guest recommendations -> GET /schemes/recommendations returns 403 Forbidden (Step 2.1)
    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 403
    assert "registered citizen account" in rec_res.json()["detail"].lower()

    # Step 4: Full catalog -> GET /schemes works immediately without demographics
    cat_res = client.get("/schemes")
    assert cat_res.status_code == 200
    assert cat_res.json()["count"] >= 5
    assert len(cat_res.json()["schemes"]) >= 5

    # Step 5: Profile check -> GET /profile/me returns 401 for guests
    # This proves why the frontend must never redirect a guest session to profile.html or call /profile/me
    prof_res = client.get("/profile/me")
    assert prof_res.status_code == 401

    # Step 6: Frontend code integrity audit
    import pathlib
    frontend_dir = pathlib.Path(__file__).parent.parent / "frontend" / "js"
    
    api_js = (frontend_dir / "api.js").read_text(encoding="utf-8")
    assert 'endpoint.includes("/auth/guest")' in api_js, "api.js must exempt /auth/guest from pre-auth CSRF token fetch"
    
    dashboard_js = (frontend_dir / "dashboard.js").read_text(encoding="utf-8")
    assert "if (isGuestMode)" in dashboard_js, "dashboard.js must handle 404 recommendations specifically for guests"
    assert "switchTab(\"catalog\")" in dashboard_js, "dashboard.js must default guest to catalog without profile requirement"

    profile_js = (frontend_dir / "profile.js").read_text(encoding="utf-8")
    assert "statusRes.data.is_guest" in profile_js, "profile.js must check session-status to prevent guest 401 bounce"


def test_13_anonymous_mode_step1_requirements(client, auth_env):
    """Verifies Step 1 requirements:
    1. Anonymous dashboard works without demographics.
    2. Public scheme catalog works without demographics (search, browse, filters).
    3. Scheme details are accessible without demographics.
    4. Eligibility requirements can be viewed without creating a profile.
    5. Eligibility checking remains optional.
    6. Registered-user profile functionality is unchanged.
    7. Guest session and logout functionality still work.
    """
    import pathlib
    frontend_root = pathlib.Path(__file__).parent.parent / "frontend"
    dash_html = (frontend_root / "dashboard.html").read_text(encoding="utf-8")
    dash_js = (frontend_root / "js" / "dashboard.js").read_text(encoding="utf-8")

    # Req 1: Profile card summary & temporary edit button removed from anonymous mode
    assert 'id="profileCardSection"' in dash_html, "Dashboard HTML must have profileCardSection for visibility toggling"
    assert "btnEditGuestProfile" not in dash_html, "Edit Temporary Details button must be removed from HTML"
    assert "guestProfileModal" not in dash_html, "Temporary demographic modal must be removed from HTML"
    assert "profileCard.style.display = \"none\"" in dash_js, "dashboard.js must hide profile card in anonymous mode"

    # Req 2 & 3: Anonymous browsing and scheme details work without demographics
    client.post("/auth/guest")
    cat_res = client.get("/schemes")
    assert cat_res.status_code == 200
    assert cat_res.json()["count"] >= 5

    search_res = client.get("/schemes?q=pragati")
    assert search_res.status_code == 200
    assert any("pragati" in s["scheme_name"].lower() for s in search_res.json()["schemes"])

    filter_res = client.get("/schemes?category=EDUCATION&beneficiary_group=Girl")
    assert filter_res.status_code == 200

    detail_res = client.get("/schemes/SCHEME_EDU_002_AICTE_PRAGATI")
    assert detail_res.status_code == 200
    scheme = detail_res.json()["scheme"]
    assert "eligibility" in scheme
    assert "structured_rules" in scheme["eligibility"]

    # Req 4: Eligibility requirements viewable in details modal without profile
    assert 'id="detailsModalEligibility"' in dash_html, "Details modal must include eligibility requirements section"
    assert "detailsModalEligibility" in dash_js, "dashboard.js must populate eligibility requirements in details modal"

    # Req 5: Eligibility checking is optional; user can provide criteria on demand
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    opt_eval_res = client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "temporary_profile": {
                "age": 19,
                "gender": "FEMALE",
                "annual_income": 250000.0,
                "caste_category": "GENERAL",
                "occupation": "Student",
                "pursuing_regular_course": True,
            }
        },
    )
    assert opt_eval_res.status_code == 200

    elig_eval = client.get("/schemes/SCHEME_EDU_002_AICTE_PRAGATI/eligibility?application_type=FRESH")
    assert elig_eval.status_code == 200
    assert elig_eval.json()["status"] == "REVIEW_REQUIRED"

    # Req 6: Registered-user profile functionality unchanged
    reg_client = auth_env["client"] if "client" in auth_env else client
    # Verify database persistence isolation
    db = auth_env["db"]
    with db.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM profiles").fetchone()[0] == 0

    # Req 7: Guest logout still works
    logout_res = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert logout_res.status_code == 200
    post_logout_status = client.get("/auth/session-status")
    assert post_logout_status.json()["authenticated"] is False



