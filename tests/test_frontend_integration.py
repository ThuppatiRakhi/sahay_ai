"""Integration and contract tests for SahayAI Phase 4 Frontend Integration.

Validates:
1. Static frontend assets are properly served (HTML, CSS, JS).
2. End-to-end citizen journey from signup -> CSRF token -> profile creation -> dashboard retrieval.
3. Login flow correctly evaluates profile_required flag for navigation.
4. Session persistence on dashboard page refresh.
5. Logout revokes the session in SQLite and clears cookies.
6. Expired/revoked sessions return HTTP 401 triggering redirect to login.html.
7. Mutating requests reject missing or invalid CSRF tokens (HTTP 403).
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import generate_csrf_token, get_session_config
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_frontend_int.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def auth_env(test_db, monkeypatch):
    """Configures isolated auth service, profile manager, and session manager."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.schemes.auth_service", auth_svc)
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
    """TestClient against SahayAI application."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases: Static Assets & Pages
# ---------------------------------------------------------------------------

def test_01_static_frontend_pages_accessible(client):
    """Verifies that all frontend pages are mounted and accessible via FastAPI."""
    pages = [
        "/frontend/index.html",
        "/frontend/signup.html",
        "/frontend/login.html",
        "/frontend/profile.html",
        "/frontend/dashboard.html",
        "/frontend/css/style.css",
        "/frontend/css/auth.css",
        "/frontend/js/api.js",
        "/frontend/js/signup.js",
        "/frontend/js/login.js",
        "/frontend/js/profile.js",
        "/frontend/js/dashboard.js",
    ]

    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Failed to load static asset: {page}"
        assert len(res.content) > 0


# ---------------------------------------------------------------------------
# Test Cases: End-to-End Frontend Flow
# ---------------------------------------------------------------------------

def test_02_complete_citizen_onboarding_journey(client, auth_env):
    """Verifies the complete onboarding journey:
    Signup -> Session Cookie -> GET CSRF -> Check Profile (404) -> Create Profile -> Dashboard (200).
    """
    cfg = get_session_config()

    # Step 1: Signup
    signup_res = client.post(
        "/auth/signup",
        json={"email": "journey.citizen@example.com", "password": "CitizenSecure@123"},
    )
    assert signup_res.status_code == 200
    signup_data = signup_res.json()
    assert signup_data["success"] is True
    assert signup_data["profile_required"] is True
    assert signup_data["next_step"] == "CREATE_PROFILE"

    raw_token = signup_res.cookies.get(cfg.cookie_name)
    assert raw_token is not None

    # Step 2: Acquire CSRF Token
    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_data = csrf_res.json()
    assert csrf_data["success"] is True
    csrf_token = csrf_data["csrf_token"]

    # Step 3: Check Profile before creation (dashboard or profile check) -> returns 404
    check_profile_res = client.get("/profile/me")
    assert check_profile_res.status_code == 404

    # Step 4: Create Citizen Profile
    profile_payload = {
        "full_name": "Ramesh Patel",
        "date_of_birth": "1996-03-21",
        "gender": "MALE",
        "state": "Gujarat",
        "district": "Surat",
        "annual_income": 175000.0,
        "occupation": "Textile Worker",
        "caste_category": "OBC",
        "is_bpl": True,
    }

    create_res = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": csrf_token,
        },
        json=profile_payload,
    )
    assert create_res.status_code == 200
    create_data = create_res.json()
    assert create_data["success"] is True
    assert create_data["next_step"] == "DASHBOARD"
    assert create_data["profile"]["full_name"] == "Ramesh Patel"
    assert create_data["profile"]["is_bpl"] is True

    # Step 5: Dashboard retrieves authenticated profile
    dash_res = client.get("/profile/me")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["success"] is True
    assert dash_data["profile"]["full_name"] == "Ramesh Patel"
    assert dash_data["profile"]["state"] == "Gujarat"

    # Step 6: Dashboard refresh (subsequent call with same session) preserves profile
    refresh_res = client.get("/profile/me")
    assert refresh_res.status_code == 200
    assert refresh_res.json()["profile"]["profile_id"] == create_data["profile"]["profile_id"]


def test_03_login_redirect_behavior(client, auth_env):
    """Verifies that login returns profile_required=True when profile is absent, and False when present."""
    # 1. Signup user without profile
    client.post(
        "/auth/signup",
        json={"email": "login_nav@example.com", "password": "Password123@xyz"},
    )

    # 2. Login -> profile_required must be True
    login_1 = client.post(
        "/auth/login",
        json={"identifier": "login_nav@example.com", "password": "Password123@xyz"},
    )
    assert login_1.status_code == 200
    assert login_1.json()["profile_required"] is True
    assert login_1.json()["next_step"] == "CREATE_PROFILE"

    # 3. Create profile
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Login Nav User",
            "date_of_birth": "1990-01-01",
            "gender": "FEMALE",
            "state": "Maharashtra",
            "district": "Mumbai",
            "annual_income": 350000.0,
            "occupation": "Banker",
            "caste_category": "GENERAL",
        },
    )

    # 4. Login again -> profile_required must now be False, next_step is DASHBOARD
    login_2 = client.post(
        "/auth/login",
        json={"identifier": "login_nav@example.com", "password": "Password123@xyz"},
    )
    assert login_2.status_code == 200
    assert login_2.json()["profile_required"] is False
    assert login_2.json()["next_step"] == "DASHBOARD"


def test_04_logout_and_session_invalidation(client, auth_env):
    """Verifies that logout revokes the session and clears cookies, causing subsequent /profile/me to return 401."""
    cfg = get_session_config()

    client.post(
        "/auth/signup",
        json={"email": "logout.flow@example.com", "password": "Password123@abc"},
    )
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    # Logout
    logout_res = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True

    # Check cookies cleared
    set_cookies = logout_res.headers.get_list("set-cookie")
    assert any("max-age=0" in h.lower() or "expires=" in h.lower() for h in set_cookies if cfg.cookie_name in h)

    # Subsequent call to /profile/me returns 401
    profile_attempt = client.get("/profile/me")
    assert profile_attempt.status_code == 401


def test_05_csrf_security_enforcement(client, auth_env):
    """Verifies that state-changing requests fail with HTTP 403 when CSRF token is invalid or missing."""
    client.post(
        "/auth/signup",
        json={"email": "csrf.guard@example.com", "password": "Password123@def"},
    )

    profile_payload = {
        "full_name": "CSRF Guard User",
        "date_of_birth": "1994-01-01",
        "gender": "OTHER",
        "state": "Delhi",
        "district": "New Delhi",
        "annual_income": 200000.0,
        "occupation": "Writer",
        "caste_category": "GENERAL",
    }

    # Missing X-CSRF-Token header -> 403
    res_missing = client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500"},
        json=profile_payload,
    )
    assert res_missing.status_code == 403

    # Invalid/forged X-CSRF-Token header -> 403
    res_forged = client.post(
        "/profile/me",
        headers={
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": "forged_csrf_hex_value_00000000000000000000000000000000000000",
        },
        json=profile_payload,
    )
    assert res_forged.status_code == 403


# ---------------------------------------------------------------------------
# Test Cases: Phase 6 Scheme Discovery Frontend Integration
# ---------------------------------------------------------------------------

def test_06_dashboard_html_contains_scheme_discovery_components(client):
    """Verifies that dashboard.html includes all required Scheme Discovery markup,
    tabs, filters, modals, and mandatory legal safeguard banners.
    """
    res = client.get("/frontend/dashboard.html")
    assert res.status_code == 200
    html = res.text

    # Scheme discovery section & tabs
    assert 'id="schemes"' in html
    assert 'id="tabRecommendations"' in html
    assert 'id="tabCatalog"' in html

    # Mandatory legal safeguard notice
    assert "Official Government Verification Pending" in html
    assert "preliminary automated rule calculations" in html

    # Filter inputs & controls
    assert 'id="schemeFiltersBar"' in html
    assert 'id="schemeSearchInput"' in html
    assert 'id="categoryFilter"' in html
    assert 'id="educationFilter"' in html
    assert 'id="beneficiaryFilter"' in html
    assert 'id="btnApplyFilters"' in html
    assert 'id="btnResetFilters"' in html
    assert 'id="applicationTypeSelect"' in html
    assert 'id="schemesContainer"' in html

    # Modals & Accessibility Attributes
    assert 'id="schemeDetailsModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="detailsModalTitle"' in html
    assert 'aria-labelledby="eligibilityModalTitle"' in html
    assert 'aria-controls="schemesContainer"' in html
    assert 'aria-label="Close dialog"' in html

    assert 'id="detailsModalTitle"' in html
    assert 'id="detailsModalVerification"' in html
    assert 'id="detailsModalBenefits"' in html
    assert 'id="detailsModalDocuments"' in html

    assert 'id="schemeEligibilityModal"' in html
    assert 'id="eligibilityStatusBanner"' in html
    assert 'id="eligibilitySummaryText"' in html
    assert 'id="eligibilityMissingSection"' in html
    assert 'id="eligibilityMatchedSection"' in html
    assert 'id="eligibilityFailedSection"' in html


def test_07_frontend_scheme_discovery_journey(client, auth_env):
    """Verifies that an authenticated citizen with a completed profile can execute
    the full Scheme Discovery journey:
    1. Query the scheme catalog with filters.
    2. Retrieve complete scheme details.
    3. Retrieve personalized recommendations grouped into preliminary matches & rule mismatches.
    4. Retrieve deterministic eligibility evaluation with condition breakdowns and missing info.
    """
    # 1. Signup & CSRF setup
    client.post(
        "/auth/signup",
        json={"email": "discovery.citizen@example.com", "password": "SecurePassword123!"},
    )
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    # 2. Create profile: Low-income student eligible for PM-USP income condition
    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Priya Sharma",
            "date_of_birth": "2004-05-15",
            "gender": "FEMALE",
            "state": "Uttar Pradesh",
            "district": "Lucknow",
            "annual_income": 180000.0,
            "occupation": "Student",
            "caste_category": "GENERAL",
            "is_bpl": False,
        },
    )

    # 3. Explore Catalog via GET /schemes
    catalog_res = client.get("/schemes?category=EDUCATION")
    assert catalog_res.status_code == 200
    catalog_data = catalog_res.json()
    assert catalog_data["success"] is True
    assert catalog_data["count"] >= 5
    assert all(s["verification_status"] == "pending_review" for s in catalog_data["schemes"])

    # 4. Search filter: search for "pragati"
    search_res = client.get("/schemes?q=pragati")
    assert search_res.status_code == 200
    assert search_res.json()["count"] >= 1
    assert any("PRAGATI" in s["scheme_id"] for s in search_res.json()["schemes"])

    # 5. Retrieve Scheme Details
    details_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS")
    assert details_res.status_code == 200
    scheme = details_res.json()["scheme"]
    assert scheme["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert "benefits" in scheme
    assert "required_documents" in scheme
    assert scheme["verification_status"] == "pending_review"

    # 6. Retrieve Recommendations
    rec_res = client.get("/schemes/recommendations?application_type=FRESH")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["success"] is True
    assert "preliminary_matches" in rec_data
    assert "rule_mismatches_requiring_review" in rec_data
    assert rec_data["total_schemes_evaluated"] >= 5

    # All evaluated records must enforce review_required and unconfirmed official eligibility
    all_recs = rec_data["preliminary_matches"] + rec_data["rule_mismatches_requiring_review"]
    for r in all_recs:
        assert r["status"] == "REVIEW_REQUIRED"
        assert r["official_eligibility_confirmed"] is False

    # 7. Check Detailed Eligibility Evaluation
    elig_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility?application_type=FRESH")
    assert elig_res.status_code == 200
    elig_data = elig_res.json()
    assert elig_data["success"] is True
    assert elig_data["status"] == "REVIEW_REQUIRED"
    assert elig_data["official_eligibility_confirmed"] is False
    assert "matched_conditions" in elig_data
    assert "missing_information" in elig_data
    # Priya has income 180,000 <= 450,000 -> matched condition
    assert any("annual_family_income" in c.get("criterion", "") for c in elig_data["matched_conditions"])
    # Missing information includes class_12_merit_percentile
    assert "class_12_merit_percentile" in elig_data["missing_information"]


def test_08_scheme_recommendations_and_eligibility_require_authentication(client):
    """Verifies that recommendations and eligibility endpoints reject unauthenticated requests with HTTP 401."""
    # Unauthenticated recommendations
    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 401

    # Unauthenticated eligibility evaluation
    elig_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility")
    assert elig_res.status_code == 401


def test_09_unverified_scheme_safeguards_enforced(client, auth_env):
    """Verifies that no unverified scheme can ever return official_eligibility_confirmed=True
    or status='PASS' as its top-level status.
    """
    client.post(
        "/auth/signup",
        json={"email": "safeguard.check@example.com", "password": "SecurePassword123!"},
    )
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Safeguard User",
            "date_of_birth": "2000-01-01",
            "gender": "FEMALE",
            "state": "Delhi",
            "district": "New Delhi",
            "annual_income": 100000.0,
            "occupation": "Student",
            "caste_category": "SC",
            "is_bpl": True,
        },
    )

    # Test all 5 schemes eligibility
    schemes_res = client.get("/schemes")
    schemes = schemes_res.json()["schemes"]

    for s in schemes:
        s_id = s["scheme_id"]
        res = client.get(f"/schemes/{s_id}/eligibility")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "REVIEW_REQUIRED"
        assert data["official_eligibility_confirmed"] is False


def test_10_unified_dashboard_five_interactive_feature_cards(client, auth_env):
    """Verifies Step 2: Unified Dashboard UI.

    Requirements verified:
    1. All five interactive feature cards are prominently defined on initial dashboard load.
    2. Exact user-requested titles and descriptions are present:
       - Text AI Chat: Ask questions and get AI-powered answers.
       - Voice Assistant: Talk to SahayAI using voice.
       - Document Upload & OCR: Upload documents and extract useful information.
       - Profile-Based Scheme Discovery: Discover schemes based on personal information.
       - Direct Scheme Search: Search and explore government schemes.
    3. Unimplemented features (Chat, Voice, Documents) are clearly marked with Coming Soon badges
       and accompanied by an honest status modal.
    4. Direct Scheme Search and Profile-Based Scheme Discovery are marked Active.
    5. Anonymous users see all five cards without a temporary profile requirement.
    6. Registered users see the exact same dashboard and cards while retaining saved profiles.
    7. Secondary login/signup options are accessible.
    """
    import pathlib
    frontend_dir = pathlib.Path(__file__).parent.parent / "frontend"
    dash_html = (frontend_dir / "dashboard.html").read_text(encoding="utf-8")
    dash_js = (frontend_dir / "js" / "dashboard.js").read_text(encoding="utf-8")

    # 1. Markup checks: All five cards present with exact IDs and text
    assert 'id="featuresHubSection"' in dash_html
    assert 'id="fiveFeaturesGrid"' in dash_html

    # Card 1: Text AI Chat
    assert 'id="cardChat"' in dash_html
    assert "Text AI Chat" in dash_html
    assert "Ask questions and get AI-powered answers." in dash_html

    # Card 2: Voice Assistant
    assert 'id="cardVoice"' in dash_html
    assert "Voice Assistant" in dash_html
    assert "Talk to SahayAI using voice." in dash_html

    # Card 3: Document Upload & OCR
    assert 'id="cardDocuments"' in dash_html
    assert "Document Upload &amp; OCR" in dash_html or "Document Upload & OCR" in dash_html
    assert "Upload documents and extract useful information." in dash_html

    # Card 4: Profile-Based Scheme Discovery
    assert 'id="cardRecommendations"' in dash_html
    assert "Profile-Based Scheme Discovery" in dash_html
    assert "Discover schemes based on personal information." in dash_html

    # Card 5: Direct Scheme Search
    assert 'id="cardCatalog"' in dash_html
    assert "Direct Scheme Search" in dash_html
    assert "Search and explore government schemes." in dash_html

    # 2. Honest status modal for unimplemented features
    assert 'id="featureInfoModal"' in dash_html
    assert "Coming Soon" in dash_html
    assert "Development in Progress" in dash_html
    assert "cardChat.addEventListener" in dash_js
    assert "cardVoice.addEventListener" in dash_js
    assert "cardDocuments.addEventListener" in dash_js
    assert "cardRecommendations.addEventListener" in dash_js
    assert "cardCatalog.addEventListener" in dash_js

    # 3. Secondary login/signup options accessible in nav
    assert 'id="navLoginLink"' in dash_html
    assert 'id="navSignupLink"' in dash_html

    # 4. Anonymous user access: visits dashboard, uses Direct Scheme Search immediately
    guest_init = client.post("/auth/guest")
    assert guest_init.status_code == 200

    guest_status = client.get("/auth/session-status")
    assert guest_status.status_code == 200
    assert guest_status.json()["is_guest"] is True

    # Direct Scheme Search works immediately for anonymous user
    catalog_res = client.get("/schemes")
    assert catalog_res.status_code == 200
    assert catalog_res.json()["count"] >= 5

    # 5. Registered citizen access: sees the exact same dashboard and can discover recommendations
    client.post(
        "/auth/signup",
        json={"email": "unified.citizen@example.com", "password": "CitizenPassword123!"},
    )
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]

    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Unified Citizen",
            "date_of_birth": "1999-05-15",
            "gender": "FEMALE",
            "state": "Karnataka",
            "district": "Bengaluru",
            "annual_income": 180000.0,
            "occupation": "Student",
            "caste_category": "GENERAL",
            "is_bpl": False,
        },
    )

    # Registered user retrieves saved profile
    prof_res = client.get("/profile/me")
    assert prof_res.status_code == 200
    assert prof_res.json()["profile"]["full_name"] == "Unified Citizen"

    # Profile-Based Scheme Discovery succeeds for registered citizen
    rec_res = client.get("/schemes/recommendations?application_type=FRESH")
    assert rec_res.status_code == 200
    assert rec_res.json()["success"] is True
    assert "preliminary_matches" in rec_res.json()


def test_15_step2_1_profile_based_discovery_access_control(client, auth_env):
    """Verifies Step 2.1: Correct Profile-Based Discovery Access Control.

    1. All five interactive cards are visible to both anonymous visitors and registered users.
    2. Anonymous user sees Profile-Based Scheme Discovery card as a restricted account feature:
       - Marked with 'Account Feature' badge.
       - Explains: 'Create an account to save your profile and receive personalized scheme recommendations.'
       - Provides optional Sign Up action without automatic redirect or forced registration.
    3. Backend authorization enforcement: Anonymous guest calling GET /schemes/recommendations
       is strictly rejected with HTTP 403 Forbidden.
    4. Registered citizen with saved profile can invoke GET /schemes/recommendations successfully (200).
    5. Anonymous user can still perform optional manual eligibility assessments (GET /schemes/{id}/eligibility).
    6. Both anonymous and registered users can freely browse and search schemes (GET /schemes).
    """
    import pathlib
    frontend_root = pathlib.Path(__file__).parent.parent / "frontend"
    dash_html = (frontend_root / "dashboard.html").read_text(encoding="utf-8")
    dash_js = (frontend_root / "js" / "dashboard.js").read_text(encoding="utf-8")
    auth_css = (frontend_root / "css" / "auth.css").read_text(encoding="utf-8")

    # 1. Structural audit: all 5 feature cards present
    cards = ["cardChat", "cardVoice", "cardDocuments", "cardRecommendations", "cardCatalog"]
    for c_id in cards:
        assert f'id="{c_id}"' in dash_html, f"Feature card {c_id} must be in dashboard.html"

    # 2. Frontend audit: Card 4 restricted account presentation for anonymous users
    assert 'id="accountFeatureModal"' in dash_html, "Dashboard must include accountFeatureModal"
    assert "Account Feature" in dash_html or "Account Feature" in dash_js
    assert "Create an account to save your profile and receive personalized scheme recommendations." in dash_js
    assert "feature-restricted-badge" in auth_css, "auth.css must style .feature-restricted-badge"
    assert "openModal(accountFeatureModal" in dash_js, "dashboard.js must open account modal on restricted card click"
    assert 'href="signup.html"' in dash_html and 'href="signup.html"' in dash_js, "Optional Sign Up links must be present"

    # 3. Guest Mode Setup
    guest_init = client.post("/auth/guest")
    assert guest_init.status_code == 200

    # 4. Backend authorization: Anonymous guest receives HTTP 403 Forbidden on recommendations
    guest_rec = client.get("/schemes/recommendations")
    assert guest_rec.status_code == 403, "Guest must be rejected from profile recommendations with HTTP 403"
    assert "registered citizen account" in guest_rec.json()["detail"].lower()

    # 5. Direct Scheme Search works for anonymous user
    guest_search = client.get("/schemes?q=pm")
    assert guest_search.status_code == 200
    assert guest_search.json()["count"] >= 1

    # 6. Anonymous user can still perform manual eligibility assessment on demand
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]
    client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "temporary_profile": {
                "age": 21,
                "gender": "FEMALE",
                "annual_income": 120000.0,
                "caste_category": "GENERAL",
                "occupation": "Student",
            }
        },
    )
    manual_elig = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility")
    assert manual_elig.status_code == 200
    assert manual_elig.json()["status"] == "REVIEW_REQUIRED"
    assert manual_elig.json()["official_eligibility_confirmed"] is False

    # 7. Registered Citizen Flow
    client.post(
        "/auth/signup",
        json={"email": "verified.citizen.step21@example.com", "password": "SecurePassword@123"},
    )
    reg_csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": reg_csrf},
        json={
            "full_name": "Meera Sen",
            "date_of_birth": "2001-08-20",
            "gender": "FEMALE",
            "state": "Maharashtra",
            "district": "Pune",
            "annual_income": 150000.0,
            "occupation": "Student",
            "caste_category": "GENERAL",
            "is_bpl": False,
        },
    )

    # Registered citizen can invoke profile-based recommendations (HTTP 200)
    reg_rec = client.get("/schemes/recommendations")
    assert reg_rec.status_code == 200
    assert reg_rec.json()["success"] is True
    assert "preliminary_matches" in reg_rec.json()
    assert "rule_mismatches_requiring_review" in reg_rec.json()

    # Registered citizen can also access direct scheme search
    reg_search = client.get("/schemes?q=pm")
    assert reg_search.status_code == 200
    assert reg_search.json()["count"] >= 1


def test_16_step3_direct_government_scheme_search(client, auth_env):
    """Verifies Step 3: Direct Government Scheme Search & Discovery Requirements.

    Tests:
    1. Anonymous scheme search (searches and explores schemes without account).
    2. Registered-user scheme search (searches and explores schemes while logged in).
    3. Search by scheme name, keywords, and multi-token descriptions.
    4. Each available filter (category, education level, beneficiary group).
    5. Clear all filters (reloads full catalog of 5 schemes).
    6. Scheme details view (overview, benefits, education requirements, income limit, documents, steps).
    7. Official application website and source links verification.
    8. Manual eligibility assessment tailored to the selected scheme.
    9. Unverified scheme status display (strictly REVIEW_REQUIRED, official_eligibility_confirmed=False).
    10. Empty results and error handling (non-matching search returns 0 without crashing, invalid ID returns 404).
    """
    import pathlib
    frontend_root = pathlib.Path(__file__).parent.parent / "frontend"
    dash_html = (frontend_root / "dashboard.html").read_text(encoding="utf-8")
    dash_js = (frontend_root / "js" / "dashboard.js").read_text(encoding="utf-8")

    # Frontend structural audits
    assert 'id="schemeSearchInput"' in dash_html, "Search input must exist in dashboard.html"
    assert 'id="categoryFilter"' in dash_html, "Category filter must exist in dashboard.html"
    assert 'id="educationFilter"' in dash_html, "Education filter must exist in dashboard.html"
    assert 'id="beneficiaryFilter"' in dash_html, "Beneficiary filter must exist in dashboard.html"
    assert 'id="btnApplyFilters"' in dash_html, "Apply filters button must exist in dashboard.html"
    assert 'id="btnResetFilters"' in dash_html, "Reset filters button must exist in dashboard.html"
    assert "configureManualAssessmentForm" in dash_js, "Tailored manual assessment form must exist in dashboard.js"
    assert "btnClearSearchFilters" in dash_js, "Clear search filters button must be wired in dashboard.js"

    # 1. Anonymous Scheme Search
    client.post("/auth/guest")
    guest_search_all = client.get("/schemes")
    assert guest_search_all.status_code == 200
    all_schemes = guest_search_all.json()["schemes"]
    assert len(all_schemes) == 5

    # Each scheme card displays required fields
    for s in all_schemes:
        assert s["scheme_id"] is not None
        assert s["scheme_name"] is not None
        assert s["category"] is not None
        assert s["description"] is not None
        assert "application_type" in s
        assert s["verification_status"] == "pending_review"

    # 2. Registered-user Scheme Search
    client.post(
        "/auth/signup",
        json={"email": "direct.searcher@example.com", "password": "Password123!"},
    )
    reg_search_all = client.get("/schemes")
    assert reg_search_all.status_code == 200
    assert reg_search_all.json()["count"] == 5

    # 3. Search by Scheme Name and Keywords
    # Name search
    name_res = client.get("/schemes?q=Pragati")
    assert name_res.status_code == 200
    assert any("pragati" in s["scheme_name"].lower() for s in name_res.json()["schemes"])

    # Keyword search across description & ministry
    keyword_res = client.get("/schemes?q=merit scholarship")
    assert keyword_res.status_code == 200
    assert any("pm-usp" in s["scheme_name"].lower() for s in keyword_res.json()["schemes"])

    multi_token_res = client.get("/schemes?q=technical aicte")
    assert multi_token_res.status_code == 200
    assert multi_token_res.json()["count"] >= 2

    orphan_res = client.get("/schemes?q=orphan")
    assert orphan_res.status_code == 200
    assert any("swanath" in s["scheme_name"].lower() for s in orphan_res.json()["schemes"])

    # 4. Each Available Filter
    # Category filter
    cat_res = client.get("/schemes?category=Education")
    assert cat_res.status_code == 200
    assert cat_res.json()["count"] == 5

    # Education-level filter: Class 12
    edu_12_res = client.get("/schemes?education_level=Class 12")
    assert edu_12_res.status_code == 200
    assert edu_12_res.json()["count"] >= 2

    # Education-level filter: Technical Diploma
    diploma_res = client.get("/schemes?education_level=Technical Diploma")
    assert diploma_res.status_code == 200
    diploma_ids = [s["scheme_id"] for s in diploma_res.json()["schemes"]]
    assert "SCHEME_EDU_002_AICTE_PRAGATI" in diploma_ids
    assert "SCHEME_EDU_003_AICTE_SAKSHAM" in diploma_ids

    # Beneficiary-group filter: Girl Students
    girl_res = client.get("/schemes?beneficiary_group=Girl Students")
    assert girl_res.status_code == 200
    girl_ids = [s["scheme_id"] for s in girl_res.json()["schemes"]]
    assert "SCHEME_EDU_002_AICTE_PRAGATI" in girl_ids

    # Beneficiary-group filter: Persons with Disabilities
    pwd_res = client.get("/schemes?beneficiary_group=Persons with Disabilities")
    assert pwd_res.status_code == 200
    pwd_ids = [s["scheme_id"] for s in pwd_res.json()["schemes"]]
    assert "SCHEME_EDU_003_AICTE_SAKSHAM" in pwd_ids

    # Beneficiary-group filter: SC Students
    sc_res = client.get("/schemes?beneficiary_group=SC Students")
    assert sc_res.status_code == 200
    sc_ids = [s["scheme_id"] for s in sc_res.json()["schemes"]]
    assert "SCHEME_EDU_005_TOP_CLASS_SC" in sc_ids

    # 5. Clear All Filters
    reset_res = client.get("/schemes")
    assert reset_res.status_code == 200
    assert reset_res.json()["count"] == 5

    # 6. Scheme Details View
    detail_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS")
    assert detail_res.status_code == 200
    scheme = detail_res.json()["scheme"]
    assert scheme["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert "benefits" in scheme
    assert "eligibility" in scheme
    assert scheme["eligibility"]["annual_family_income_limit"] == 450000.0
    assert "education_requirement" in scheme["eligibility"]
    assert "course_requirement" in scheme["eligibility"]
    assert "required_documents" in scheme
    assert len(scheme["required_documents"]) >= 1
    assert "application_steps" in scheme
    assert len(scheme["application_steps"]) >= 1

    # 7. Official Links Validation
    assert scheme["application_url"].startswith("https://")
    assert "official_sources" in scheme
    for src in scheme["official_sources"]:
        src_url = src.get("source_url") or src.get("url")
        assert src_url is not None
        assert src_url.startswith("http://") or src_url.startswith("https://")

    # 8. Manual Eligibility Assessment Tailored to Scheme
    # Switch back to guest session
    client.post("/auth/guest")
    csrf_token = client.get("/auth/csrf-token").json()["csrf_token"]

    # Provide tailored criteria for AICTE Pragati (Female, Income <= 8,00,000)
    client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "temporary_profile": {
                "gender": "FEMALE",
                "annual_income": 300000.0,
                "annual_family_income": 300000.0,
                "caste_category": "OBC",
                "occupation": "Student",
            }
        },
    )
    manual_elig_res = client.get("/schemes/SCHEME_EDU_002_AICTE_PRAGATI/eligibility?application_type=FRESH")
    assert manual_elig_res.status_code == 200
    elig_result = manual_elig_res.json()

    # 9. Unverified Scheme Status Display
    assert elig_result["status"] == "REVIEW_REQUIRED"
    assert elig_result["official_eligibility_confirmed"] is False
    assert elig_result["scheme_verification_status"] == "pending_review"

    # 10. Empty Results and Error Handling
    empty_res = client.get("/schemes?q=NonExistentSchemeXYZQuery123")
    assert empty_res.status_code == 200
    assert empty_res.json()["count"] == 0
    assert empty_res.json()["schemes"] == []

    not_found_res = client.get("/schemes/SCHEME_NONEXISTENT_404")
    assert not_found_res.status_code == 404
    assert "not found" in not_found_res.json()["detail"].lower()


def test_17_step4d2_guest_card_visibility(client, auth_env):
    """Verifies Step 4D.2: Hide Profile-Based Discovery for Guest Users.

    Requirements:
    1. Anonymous/Guest users:
       - cardRecommendations is completely hidden (style.display = 'none').
       - Grid switches to 'four-cards-grid' to eliminate layout gaps.
       - Exactly four interactive methods are active and visible (Text AI Chat, Voice, Document OCR, Direct Scheme Search).
       - Recommendations tab (tabRecommendations) is hidden.
       - Guest cannot access recommendations (backend returns HTTP 403).
       - Guest can still freely use Direct Scheme Search and manual eligibility assessment without registration.
    2. Registered users:
       - All five interactive methods are shown (cardRecommendations style.display is restored).
       - Grid restores 'five-cards-grid'.
       - Recommendations tab is visible and profile recommendations work with HTTP 200.
    3. Login/logout cycle correctly updates card visibility.
    """
    import pathlib
    frontend_root = pathlib.Path(__file__).parent.parent / "frontend"
    dash_html = (frontend_root / "dashboard.html").read_text(encoding="utf-8")
    dash_js = (frontend_root / "js" / "dashboard.js").read_text(encoding="utf-8")
    auth_css = (frontend_root / "css" / "auth.css").read_text(encoding="utf-8")

    # A. Static code and style audits
    # 1. Four-cards-grid defined in CSS
    assert ".four-cards-grid" in auth_css
    assert "grid-template-columns: repeat(4, 1fr)" in auth_css

    # 2. Logic in dashboard.js to hide cardRecommendations and switch to four-cards-grid for guests
    assert 'cardRecommendations.style.display = "none"' in dash_js
    assert 'fiveFeaturesGrid.classList.add("four-cards-grid")' in dash_js
    assert 'tabRecommendations.style.display = "none"' in dash_js

    # 3. Logic in dashboard.js to restore cardRecommendations and switch to five-cards-grid for registered users
    assert 'cardRecommendations.style.display = ""' in dash_js
    assert 'fiveFeaturesGrid.classList.add("five-cards-grid")' in dash_js
    assert 'tabRecommendations.style.display = ""' in dash_js

    # B. Dynamic Contract Flow: Guest Mode
    guest_init = client.post("/auth/guest")
    assert guest_init.status_code == 200
    guest_status = client.get("/auth/session-status")
    assert guest_status.status_code == 200
    assert guest_status.json()["is_guest"] is True

    # Guest calling recommendations endpoint receives HTTP 403 Forbidden
    guest_rec = client.get("/schemes/recommendations")
    assert guest_rec.status_code == 403

    # Guest can freely browse and search schemes
    search_res = client.get("/schemes?q=pragati")
    assert search_res.status_code == 200
    assert search_res.json()["count"] >= 1

    # Guest can use manual eligibility assessment without profile creation
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]
    client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "temporary_profile": {
                "gender": "FEMALE",
                "annual_income": 200000.0,
            }
        },
    )
    elig_res = client.get("/schemes/SCHEME_EDU_002_AICTE_PRAGATI/eligibility")
    assert elig_res.status_code == 200
    assert elig_res.json()["status"] == "REVIEW_REQUIRED"

    # C. Dynamic Contract Flow: Registered User Mode
    signup_res = client.post(
        "/auth/signup",
        json={"email": "step4d2.citizen@example.com", "password": "SecurePassword@123"},
    )
    assert signup_res.status_code == 200
    user_csrf = client.get("/auth/csrf-token").json()["csrf_token"]

    # Verify session-status reflects registered citizen (is_guest=False)
    reg_status = client.get("/auth/session-status")
    assert reg_status.status_code == 200
    assert reg_status.json()["is_guest"] is False

    # Create citizen profile
    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": user_csrf},
        json={
            "full_name": "Kavita Rao",
            "date_of_birth": "2000-03-12",
            "gender": "FEMALE",
            "state": "Telangana",
            "district": "Hyderabad",
            "annual_income": 250000.0,
            "occupation": "Student",
            "caste_category": "OBC",
            "is_bpl": False,
        },
    )

    # Registered recommendations succeed (HTTP 200)
    reg_rec = client.get("/schemes/recommendations?application_type=FRESH")
    assert reg_rec.status_code == 200
    assert reg_rec.json()["success"] is True

    # D. Dynamic Contract Flow: Logout Cycle
    logout_res = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": user_csrf},
    )
    assert logout_res.status_code == 200

    # Session status is now unauthenticated
    unauth_status = client.get("/auth/session-status")
    assert unauth_status.status_code == 200
    assert unauth_status.json()["authenticated"] is False





