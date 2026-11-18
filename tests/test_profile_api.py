"""Integration and security tests for Authenticated Citizen Profile APIs (Phase 3).

Validates:
- POST /profile/me
- GET /profile/me

Covers all 14 required scenarios:
1. Authenticated user can create a profile.
2. Unauthenticated user cannot create a profile.
3. Authenticated user can retrieve their profile.
4. Unauthenticated user cannot retrieve a profile.
5. User cannot create a profile for another user.
6. User cannot retrieve another user's profile.
7. Duplicate profile creation is rejected.
8. Missing required fields are rejected.
9. Invalid field values are rejected.
10. Missing CSRF token is rejected for profile creation.
11. Invalid CSRF token is rejected.
12. Valid CSRF token permits profile creation.
13. Password hashes and session IDs never appear in profile responses.
14. Existing profile records remain accessible.
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import (
    generate_csrf_token,
    get_session_config,
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
    """Provides an isolated SQLite database for profile API tests."""
    db_file = tmp_path / "test_profile_api.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def auth_env(test_db, monkeypatch):
    """Configures isolated auth service, profile manager, and session manager."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    # Patch module singletons across auth, profile, and security modules
    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
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


def helper_create_authenticated_session(client, email="citizen@example.com", password="Password@123"):
    """Registers and authenticates a user, returning user info, raw session token, and CSRF token."""
    cfg = get_session_config()
    res = client.post(
        "/auth/signup",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200
    user_info = res.json()["user"]
    raw_session_id = res.cookies.get(cfg.cookie_name)
    assert raw_session_id is not None

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]

    return {
        "user": user_info,
        "session_id": raw_session_id,
        "csrf_token": csrf_token,
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_01_authenticated_user_can_create_profile(client, auth_env):
    """Scenario 1: Authenticated user with valid session and CSRF token can create a profile."""
    auth_data = helper_create_authenticated_session(client, "user01@example.com")
    cfg = get_session_config()

    profile_payload = {
        "full_name": "Aarav Sharma",
        "date_of_birth": "1994-06-15",
        "gender": "MALE",
        "state": "Maharashtra",
        "district": "Pune",
        "annual_income": 180000.0,
        "occupation": "Farmer",
        "caste_category": "OBC",
        "is_bpl": False,
        "metadata": {"education": "B.Sc Agriculture"},
    }

    res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json=profile_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["next_step"] == "DASHBOARD"

    profile = data["profile"]
    assert profile["full_name"] == "Aarav Sharma"
    assert profile["user_id"] == auth_data["user"]["user_id"]
    assert profile["gender"] == "MALE"
    assert profile["state"] == "Maharashtra"
    assert profile["annual_income"] == 180000.0
    assert profile["age"] >= 30  # Calculated from 1994 DOB
    assert profile["user_confirmed"] is True
    assert profile["metadata"]["education"] == "B.Sc Agriculture"

    # Confirm in database
    db_profile = auth_env["profile_mgr"].get_profile_by_user_id(auth_data["user"]["user_id"])
    assert db_profile is not None
    assert db_profile["full_name"] == "Aarav Sharma"


def test_02_unauthenticated_user_cannot_create_profile(client, auth_env):
    """Scenario 2: Unauthenticated user without session cookie cannot create a profile (HTTP 401)."""
    # Create an independent client without cookies
    fresh_client = TestClient(app)

    profile_payload = {
        "full_name": "Unauthorized User",
        "date_of_birth": "1995-01-01",
        "gender": "FEMALE",
        "state": "Telangana",
        "district": "Hyderabad",
        "annual_income": 200000.0,
        "occupation": "Student",
        "caste_category": "GENERAL",
    }

    res = fresh_client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500"},
        json=profile_payload,
    )
    assert res.status_code == 401
    assert "cookie missing" in res.json()["detail"].lower()


def test_03_authenticated_user_can_retrieve_their_profile(client, auth_env):
    """Scenario 3: Authenticated user can retrieve their previously created profile."""
    auth_data = helper_create_authenticated_session(client, "user03@example.com")

    client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json={
            "full_name": "Meera Bai",
            "date_of_birth": "1990-08-20",
            "gender": "FEMALE",
            "state": "Rajasthan",
            "district": "Jaipur",
            "annual_income": 90000.0,
            "occupation": "Artisan",
            "caste_category": "SC",
            "is_bpl": True,
        },
    )

    get_res = client.get("/profile/me")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["success"] is True
    profile = data["profile"]
    assert profile["full_name"] == "Meera Bai"
    assert profile["district"] == "Jaipur"
    assert profile["is_bpl"] is True
    assert profile["user_id"] == auth_data["user"]["user_id"]


def test_04_unauthenticated_user_cannot_retrieve_profile(client, auth_env):
    """Scenario 4: Unauthenticated request to GET /profile/me returns HTTP 401."""
    fresh_client = TestClient(app)
    res = fresh_client.get("/profile/me")
    assert res.status_code == 401
    assert "cookie missing" in res.json()["detail"].lower()


def test_05_user_cannot_create_profile_for_another_user(client, auth_env):
    """Scenario 5: Client-supplied user_id in body is ignored; server binds strictly to authenticated user."""
    auth_data_a = helper_create_authenticated_session(client, "user_a@example.com")

    # Attacker attempts to pass a spoofed user_id
    spoofed_user_id = "user_victim_999999"
    res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data_a["csrf_token"],
        },
        json={
            "user_id": spoofed_user_id,
            "full_name": "Attacker Impersonator",
            "date_of_birth": "1992-03-10",
            "gender": "MALE",
            "state": "Karnataka",
            "district": "Bengaluru",
            "annual_income": 300000.0,
            "occupation": "Developer",
            "caste_category": "GENERAL",
        },
    )
    assert res.status_code == 200
    created_profile = res.json()["profile"]

    # Must be bound to user_a, NOT the spoofed user_id
    assert created_profile["user_id"] == auth_data_a["user"]["user_id"]
    assert created_profile["user_id"] != spoofed_user_id


def test_06_user_cannot_retrieve_another_users_profile(client, auth_env):
    """Scenario 6: User B cannot retrieve User A's profile via query params or headers."""
    # 1. User A creates profile
    auth_data_a = helper_create_authenticated_session(client, "usera_private@example.com")
    client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data_a["csrf_token"],
        },
        json={
            "full_name": "User A Private",
            "date_of_birth": "1988-12-01",
            "gender": "FEMALE",
            "state": "Kerala",
            "district": "Kochi",
            "annual_income": 400000.0,
            "occupation": "Nurse",
            "caste_category": "OBC",
        },
    )

    # 2. User B signs up
    client_b = TestClient(app)
    auth_data_b = helper_create_authenticated_session(client_b, "userb_snoop@example.com")

    # User B requests their own profile (which does not exist yet) -> 404
    res_b_me = client_b.get("/profile/me")
    assert res_b_me.status_code == 404
    assert "not found" in res_b_me.json()["detail"].lower()

    # User B attempts to inject User A's ID via query parameter
    res_b_tamper = client_b.get(f"/profile/me?user_id={auth_data_a['user']['user_id']}")
    assert res_b_tamper.status_code == 404  # Still 404, parameter completely ignored
    assert "not found" in res_b_tamper.json()["detail"].lower()


def test_07_duplicate_profile_creation_rejected(client, auth_env):
    """Scenario 7: Attempting to create a second profile for the same account returns HTTP 409 Conflict."""
    auth_data = helper_create_authenticated_session(client, "duplicate.prof@example.com")

    profile_payload = {
        "full_name": "Original Name",
        "date_of_birth": "1998-05-10",
        "gender": "MALE",
        "state": "Gujarat",
        "district": "Ahmedabad",
        "annual_income": 120000.0,
        "occupation": "Weaver",
        "caste_category": "OBC",
    }

    # First creation -> 200
    res1 = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json=profile_payload,
    )
    assert res1.status_code == 200

    # Second creation attempt -> 409 Conflict
    res2 = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json=profile_payload,
    )
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


def test_08_missing_required_fields_rejected(client, auth_env):
    """Scenario 8: Missing mandatory demographic fields returns HTTP 422 Unprocessable Entity."""
    auth_data = helper_create_authenticated_session(client, "missing.fields@example.com")

    # Missing state, district, occupation, caste_category, gender
    bad_payload = {
        "full_name": "Incomplete Profile",
        "date_of_birth": "1995-01-01",
    }

    res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json=bad_payload,
    )
    assert res.status_code == 422


def test_09_invalid_field_values_rejected(client, auth_env):
    """Scenario 9: Invalid field values (bad gender, bad caste, negative income, future DOB) return HTTP 422."""
    auth_data = helper_create_authenticated_session(client, "invalid.fields@example.com")

    headers = {
        "Origin": "http://localhost:5500",
        "X-CSRF-Token": auth_data["csrf_token"],
    }

    base_payload = {
        "full_name": "Valid Name",
        "date_of_birth": "1995-01-01",
        "gender": "MALE",
        "state": "Punjab",
        "district": "Amritsar",
        "annual_income": 150000.0,
        "occupation": "Farmer",
        "caste_category": "GENERAL",
    }

    # 9a: Invalid gender
    p_bad_gender = dict(base_payload, gender="ROBOT")
    assert client.post("/profile/me", headers=headers, json=p_bad_gender).status_code == 422

    # 9b: Invalid caste category
    p_bad_caste = dict(base_payload, caste_category="UNKNOWN_CASTE")
    assert client.post("/profile/me", headers=headers, json=p_bad_caste).status_code == 422

    # 9c: Future date of birth
    p_future_dob = dict(base_payload, date_of_birth="2099-01-01")
    assert client.post("/profile/me", headers=headers, json=p_future_dob).status_code == 422

    # 9d: Negative income
    p_neg_income = dict(base_payload, annual_income=-5000.0)
    assert client.post("/profile/me", headers=headers, json=p_neg_income).status_code == 422


def test_10_missing_csrf_token_rejected_for_profile_creation(client, auth_env):
    """Scenario 10: State-changing profile creation without X-CSRF-Token returns HTTP 403 Forbidden."""
    auth_data = helper_create_authenticated_session(client, "no.csrf@example.com")

    profile_payload = {
        "full_name": "No CSRF Citizen",
        "date_of_birth": "1993-04-12",
        "gender": "FEMALE",
        "state": "Assam",
        "district": "Guwahati",
        "annual_income": 160000.0,
        "occupation": "Teacher",
        "caste_category": "GENERAL",
    }

    # Call POST /profile/me WITHOUT X-CSRF-Token
    res = client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500"},
        json=profile_payload,
    )
    assert res.status_code == 403
    assert "csrf token missing" in res.json()["detail"].lower()

    # Verify no profile was created in database
    assert auth_env["profile_mgr"].get_profile_by_user_id(auth_data["user"]["user_id"]) is None


def test_11_invalid_csrf_token_rejected(client, auth_env):
    """Scenario 11: Profile creation with forged/invalid CSRF token returns HTTP 403 Forbidden."""
    auth_data = helper_create_authenticated_session(client, "bad.csrf@example.com")

    profile_payload = {
        "full_name": "Bad CSRF Citizen",
        "date_of_birth": "1993-04-12",
        "gender": "FEMALE",
        "state": "Assam",
        "district": "Guwahati",
        "annual_income": 160000.0,
        "occupation": "Teacher",
        "caste_category": "GENERAL",
    }

    res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": "forged_invalid_hex_token_00000000000000000000000000000000000000",
        },
        json=profile_payload,
    )
    assert res.status_code == 403
    assert "csrf token validation failed" in res.json()["detail"].lower()
    assert auth_env["profile_mgr"].get_profile_by_user_id(auth_data["user"]["user_id"]) is None


def test_12_valid_csrf_token_permits_profile_creation(client, auth_env):
    """Scenario 12: Valid CSRF token permits successful profile creation."""
    auth_data = helper_create_authenticated_session(client, "valid.csrf@example.com")

    res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json={
            "full_name": "Valid CSRF Citizen",
            "date_of_birth": "1996-07-25",
            "gender": "MALE",
            "state": "Madhya Pradesh",
            "district": "Bhopal",
            "annual_income": 220000.0,
            "occupation": "Shopkeeper",
            "caste_category": "OBC",
        },
    )
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_13_password_hashes_and_session_ids_never_appear_in_profile_responses(client, auth_env):
    """Scenario 13: Password hashes, raw tokens, and session secrets are absent from responses."""
    auth_data = helper_create_authenticated_session(client, "secrets.check@example.com")
    raw_token = auth_data["session_id"]

    post_res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": auth_data["csrf_token"],
        },
        json={
            "full_name": "Secret Audit Citizen",
            "date_of_birth": "1991-03-15",
            "gender": "FEMALE",
            "state": "Odisha",
            "district": "Bhubaneswar",
            "annual_income": 140000.0,
            "occupation": "Clerk",
            "caste_category": "SC",
        },
    )
    assert post_res.status_code == 200
    post_str = str(post_res.json()).lower()

    # Assert no secrets in POST response
    assert "password_hash" not in post_str
    assert "scrypt" not in post_str
    assert raw_token.lower() not in post_str
    assert "metadata_json" not in post_res.json()["profile"]

    get_res = client.get("/profile/me")
    assert get_res.status_code == 200
    get_str = str(get_res.json()).lower()

    # Assert no secrets in GET response
    assert "password_hash" not in get_str
    assert "scrypt" not in get_str
    assert raw_token.lower() not in get_str
    assert "metadata_json" not in get_res.json()["profile"]


def test_14_existing_profile_records_remain_accessible(client, auth_env):
    """Scenario 14: Profiles directly provisioned in SQLite or legacy tables remain accessible via GET /profile/me."""
    auth_svc = auth_env["auth_service"]
    profile_mgr = auth_env["profile_mgr"]

    # 1. Register user
    signup_result = auth_svc.signup(
        email="legacy.citizen@example.com",
        password="ValidPassword@123",
    )
    user_id = signup_result["user"]["user_id"]

    # 2. Directly create profile linked to this user
    created = profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Legacy Existing Citizen",
        "date_of_birth": "1985-11-20",
        "age": 41,
        "gender": "MALE",
        "state": "Bihar",
        "district": "Patna",
        "annual_income": 95000.0,
        "occupation": "Carpenter",
        "caste_category": "EWS",
        "is_bpl": True,
        "user_confirmed": True,
    })

    # 3. Log in with client to obtain session cookie
    login_res = client.post(
        "/auth/login",
        json={"identifier": "legacy.citizen@example.com", "password": "ValidPassword@123"},
    )
    assert login_res.status_code == 200
    assert login_res.json()["profile_required"] is False
    assert login_res.json()["next_step"] == "DASHBOARD"

    # 4. Fetch via GET /profile/me
    get_res = client.get("/profile/me")
    assert get_res.status_code == 200
    profile_data = get_res.json()["profile"]
    assert profile_data["profile_id"] == created["profile_id"]
    assert profile_data["full_name"] == "Legacy Existing Citizen"
    assert profile_data["district"] == "Patna"
    assert profile_data["caste_category"] == "EWS"

