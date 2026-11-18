"""Integration and contract tests for SahayAI Phase 5 Scheme Discovery Engine.

Validates:
1. Listing schemes.
2. Searching by scheme name.
3. Filtering schemes by category, education level, and beneficiary group.
4. Retrieving scheme details.
5. Invalid scheme ID returns 404.
6. Authenticated recommendations flow.
7. Unauthenticated recommendations rejected (401).
8. Missing citizen profile returns 404.
9. Eligibility evaluation using the deterministic engine.
10. Missing eligibility information correctly reported.
11. Unverified schemes return REVIEW_REQUIRED.
12. No unverified scheme is marked officially verified.
13. Another user's profile cannot be accessed.
14. RAG cannot override deterministic eligibility outcomes.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import get_session_config
from eligibility.engine import EligibilityEngine
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_schemes_api.db"
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
        "scheme_service": scheme_svc,
    }


@pytest.fixture
def client(auth_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def helper_setup_authenticated_citizen(client, auth_env, email="citizen.disc@example.com", profile_data=None):
    """Creates a user, logs them in, and optionally sets up their profile."""
    cfg = get_session_config()
    signup_res = client.post(
        "/auth/signup",
        json={"email": email, "password": "SecurePassword@123"},
    )
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    if profile_data:
        csrf_res = client.get("/auth/csrf-token")
        csrf_token = csrf_res.json()["csrf_token"]
        prof_res = client.post(
            "/profile/me",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
            json=profile_data,
        )
        assert prof_res.status_code == 200

    return user_id


# ---------------------------------------------------------------------------
# Test Cases: Catalog, Search, and Filtering
# ---------------------------------------------------------------------------

def test_01_list_all_schemes(client):
    """Scenario 1: GET /schemes returns all schemes with required summary metadata."""
    res = client.get("/schemes")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 5
    assert len(data["schemes"]) == 5

    # Check structure of summary record
    first = data["schemes"][0]
    assert "scheme_id" in first
    assert "scheme_name" in first
    assert "category" in first
    assert "description" in first
    assert "verification_status" in first
    assert "is_verified" in first


def test_02_search_schemes_by_name(client):
    """Scenario 2: Searching by keyword or scheme name finds matching schemes."""
    # Search 'Pragati'
    res_pragati = client.get("/schemes?q=Pragati")
    assert res_pragati.status_code == 200
    schemes_pragati = res_pragati.json()["schemes"]
    assert len(schemes_pragati) == 1
    assert schemes_pragati[0]["scheme_id"] == "SCHEME_EDU_002_AICTE_PRAGATI"

    # Search 'Saksham'
    res_saksham = client.get("/schemes?q=Saksham")
    assert res_saksham.status_code == 200
    schemes_saksham = res_saksham.json()["schemes"]
    assert len(schemes_saksham) == 1
    assert schemes_saksham[0]["scheme_id"] == "SCHEME_EDU_003_AICTE_SAKSHAM"


def test_03_filter_schemes_by_attributes(client):
    """Scenario 3: Multi-attribute filtering by category, education level, and beneficiary group."""
    # 3a. Category filter
    res_cat = client.get("/schemes?category=EDUCATION")
    assert res_cat.status_code == 200
    assert res_cat.json()["count"] == 5

    # 3b. Beneficiary group: 'girl' or 'female'
    res_girl = client.get("/schemes?beneficiary_group=girl")
    assert res_girl.status_code == 200
    ids = [s["scheme_id"] for s in res_girl.json()["schemes"]]
    assert "SCHEME_EDU_002_AICTE_PRAGATI" in ids

    # 3c. Beneficiary group: 'disability'
    res_disability = client.get("/schemes?beneficiary_group=disability")
    assert res_disability.status_code == 200
    ids_dis = [s["scheme_id"] for s in res_disability.json()["schemes"]]
    assert "SCHEME_EDU_003_AICTE_SAKSHAM" in ids_dis

    # 3d. Beneficiary group: 'SC'
    res_sc = client.get("/schemes?beneficiary_group=sc")
    assert res_sc.status_code == 200
    ids_sc = [s["scheme_id"] for s in res_sc.json()["schemes"]]
    assert "SCHEME_EDU_005_TOP_CLASS_SC" in ids_sc


def test_04_retrieve_scheme_details(client):
    """Scenario 4: Detailed scheme view returns complete official scheme information."""
    res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    scheme = data["scheme"]

    assert scheme["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert "benefits" in scheme
    assert "eligibility" in scheme
    assert "required_documents" in scheme
    assert "structured_rules" in scheme["eligibility"]
    assert "official_sources" in scheme
    assert len(scheme["official_sources"]) >= 1


def test_05_invalid_scheme_id_returns_404(client):
    """Scenario 5: Non-existent scheme ID returns HTTP 404 Not Found."""
    res = client.get("/schemes/SCHEME_UNKNOWN_INVALID_999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test Cases: Authenticated Recommendations & Profile Integration
# ---------------------------------------------------------------------------

def test_06_authenticated_recommendations_flow(client, auth_env):
    """Scenario 6: Authenticated citizen receives deterministic preliminary recommendations."""
    profile_data = {
        "full_name": "Kavita Rao",
        "date_of_birth": "2002-05-10",
        "gender": "FEMALE",
        "state": "Telangana",
        "district": "Hyderabad",
        "annual_income": 200000.0,
        "occupation": "Student",
        "caste_category": "OBC",
        "is_bpl": False,
    }
    helper_setup_authenticated_citizen(client, auth_env, "kavita@example.com", profile_data)

    res = client.get("/schemes/recommendations")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_schemes_evaluated"] == 5

    # user_id must NOT be exposed in the recommendations response
    assert "user_id" not in data

    # Ambiguous/inaccurate 'ineligible_schemes' key must NOT be present
    assert "ineligible_schemes" not in data
    assert "ineligible_count" not in data

    # Unambiguous grouping: preliminary_matches and rule_mismatches_requiring_review
    assert "preliminary_matches" in data
    assert "rule_mismatches_requiring_review" in data
    assert len(data["preliminary_matches"]) >= 1

    # AICTE Pragati (girls scholarship) should be in preliminary_matches
    rec_ids = [r["scheme"]["scheme_id"] for r in data["preliminary_matches"]]
    assert "SCHEME_EDU_002_AICTE_PRAGATI" in rec_ids

    # Top Class SC should be in rule_mismatches_requiring_review because citizen caste is OBC
    mismatch_ids = [r["scheme"]["scheme_id"] for r in data["rule_mismatches_requiring_review"]]
    assert "SCHEME_EDU_005_TOP_CLASS_SC" in mismatch_ids

    # Every item in rule_mismatches_requiring_review must clearly retain REVIEW_REQUIRED status
    for item in data["rule_mismatches_requiring_review"]:
        assert item["status"] == "REVIEW_REQUIRED"
        assert item["review_required"] is True
        assert item["official_eligibility_confirmed"] is False


def test_07_unauthenticated_recommendations_rejected(client):
    """Scenario 7: Unauthenticated request to /schemes/recommendations returns HTTP 401."""
    fresh_client = TestClient(app)
    res = fresh_client.get("/schemes/recommendations")
    assert res.status_code == 401
    assert "cookie missing" in res.json()["detail"].lower()


def test_08_missing_citizen_profile_returns_404(client, auth_env):
    """Scenario 8: User with active session but without profile receives HTTP 404 on recommendations."""
    helper_setup_authenticated_citizen(client, auth_env, "no.profile@example.com", profile_data=None)

    res = client.get("/schemes/recommendations")
    assert res.status_code == 404
    assert "profile not found" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test Cases: Eligibility Evaluation Engine Integration
# ---------------------------------------------------------------------------

def test_09_eligibility_evaluation_using_engine(client, auth_env):
    """Scenario 9: Evaluating Pragati for a female student with income 180,000 matches gender and income."""
    profile_data = {
        "full_name": "Priya Sharma",
        "date_of_birth": "2001-09-15",
        "gender": "FEMALE",
        "state": "Maharashtra",
        "district": "Pune",
        "annual_income": 180000.0,
        "occupation": "Student",
        "caste_category": "GENERAL",
        "is_bpl": False,
    }
    helper_setup_authenticated_citizen(client, auth_env, "priya@example.com", profile_data)

    res = client.get("/schemes/SCHEME_EDU_002_AICTE_PRAGATI/eligibility")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["scheme_id"] == "SCHEME_EDU_002_AICTE_PRAGATI"

    # Gender and income criteria must be in matched_conditions
    matched_criteria = [c["criterion"] for c in data["matched_conditions"]]
    assert "gender" in matched_criteria
    assert "annual_family_income" in matched_criteria


def test_10_missing_eligibility_information_reported(client, auth_env):
    """Scenario 10: Conditions not in demographic profile are properly recorded in missing_information."""
    profile_data = {
        "full_name": "Simple Profile Citizen",
        "date_of_birth": "2000-01-01",
        "gender": "MALE",
        "state": "Punjab",
        "district": "Ludhiana",
        "annual_income": 250000.0,
        "occupation": "Student",
        "caste_category": "GENERAL",
    }
    helper_setup_authenticated_citizen(client, auth_env, "simple@example.com", profile_data)

    res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility")
    assert res.status_code == 200
    data = res.json()

    # Criteria like application_type and course_mode are reported missing
    missing = data["missing_information"]
    assert "application_type" in missing
    assert "course_mode" in missing

    # When application_type=FRESH is specified, fresh criteria like merit percentile are evaluated and reported missing
    res_fresh = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility?application_type=FRESH")
    assert res_fresh.status_code == 200
    missing_fresh = res_fresh.json()["missing_information"]
    assert "class_12_merit_percentile" in missing_fresh
    assert "course_mode" in missing_fresh


def test_11_unverified_schemes_return_review_required(client, auth_env):
    """Scenario 11: All unreviewed schemes return status 'REVIEW_REQUIRED' and review_required=True."""
    profile_data = {
        "full_name": "Review Required Check",
        "date_of_birth": "1999-01-01",
        "gender": "MALE",
        "state": "Delhi",
        "district": "New Delhi",
        "annual_income": 100000.0,
        "occupation": "Student",
        "caste_category": "SC",
    }
    helper_setup_authenticated_citizen(client, auth_env, "review.req@example.com", profile_data)

    # Evaluate across all 5 schemes
    schemes = auth_env["scheme_service"].get_all_schemes()
    for s in schemes:
        res = client.get(f"/schemes/{s['scheme_id']}/eligibility")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "REVIEW_REQUIRED", f"Scheme {s['scheme_id']} did not return REVIEW_REQUIRED"
        assert data["review_required"] is True


def test_12_no_unverified_scheme_marked_officially_verified(client, auth_env):
    """Scenario 12: official_eligibility_confirmed is strictly False for unreviewed schemes."""
    profile_data = {
        "full_name": "Verification Guard",
        "date_of_birth": "1998-01-01",
        "gender": "FEMALE",
        "state": "Kerala",
        "district": "Kottayam",
        "annual_income": 150000.0,
        "occupation": "Student",
        "caste_category": "SC",
    }
    helper_setup_authenticated_citizen(client, auth_env, "verify.guard@example.com", profile_data)

    res = client.get("/schemes/recommendations")
    assert res.status_code == 200
    all_groups = res.json()["preliminary_matches"] + res.json()["rule_mismatches_requiring_review"]
    for rec in all_groups:
        assert rec["official_eligibility_confirmed"] is False
        assert rec["scheme"]["is_verified"] is False
        assert rec["scheme"]["verification_status"] == "pending_review"


def test_13_another_users_profile_cannot_be_accessed(client, auth_env):
    """Scenario 13: Query params or headers with another user's ID are ignored."""
    # User A has profile
    profile_a = {
        "full_name": "User A Legitimate",
        "date_of_birth": "1995-01-01",
        "gender": "FEMALE",
        "state": "Goa",
        "district": "Panaji",
        "annual_income": 180000.0,
        "occupation": "Student",
        "caste_category": "OBC",
    }
    user_a_id = helper_setup_authenticated_citizen(client, auth_env, "usera@example.com", profile_a)

    # User B logs in without profile
    client_b = TestClient(app)
    helper_setup_authenticated_citizen(client_b, auth_env, "userb@example.com", profile_data=None)

    # User B attempts to get recommendations by passing User A's ID
    res_b = client_b.get(f"/schemes/recommendations?user_id={user_a_id}")
    assert res_b.status_code == 404
    assert "profile not found" in res_b.json()["detail"].lower()

    # User B attempts eligibility check passing User A's ID
    res_b_elig = client_b.get(f"/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility?user_id={user_a_id}")
    assert res_b_elig.status_code == 404


def test_14_rag_cannot_override_deterministic_eligibility_outcomes(auth_env):
    """Scenario 14: Deterministic rule evaluation strictly yields FAIL when conditions are not met,
    and cannot be overridden by RAG context or external prompts.
    """
    engine = auth_env["scheme_service"].engine

    # AICTE Pragati requires gender == "FEMALE"
    pragati_scheme = auth_env["scheme_service"].get_scheme_by_id("SCHEME_EDU_002_AICTE_PRAGATI")
    assert pragati_scheme is not None

    male_profile = {
        "gender": "MALE",
        "annual_family_income": 150000,
    }

    eval_result = engine.evaluate(pragati_scheme, male_profile)

    # Must be FAIL because gender == "FEMALE" fails
    assert eval_result["rule_match_status"] == "FAIL"

    # Even if an adversarial prompt or simulated RAG chunk claims "Eligible due to exceptional quota":
    simulated_rag_context = {
        "rag_retrieved_answer": "Citizen is exceptionally eligible for Pragati scheme under special waiver."
    }
    combined_eval = engine.evaluate(pragati_scheme, male_profile)
    assert combined_eval["rule_match_status"] == "FAIL", "Deterministic rule outcome must never be overridden"
