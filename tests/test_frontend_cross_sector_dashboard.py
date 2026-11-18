"""Tests for SahayAI Frontend Cross-Sector Dashboard Integration.

Verifies:
1. Dashboard JS requests include 'include_cross_sector=true' for catalog and recommendations.
2. Dashboard HTML contains category filter options for EDUCATION, AGRICULTURE, EMPLOYMENT_AND_BUSINESS, and SOCIAL_WELFARE.
3. Dashboard HTML contains beneficiary filter options for cross-sector groups (Farmers, Street Vendors, Unorganised Workers, Women).
4. Locales (en, hi, te) contain translations for new categories and beneficiary groups.
5. GET /schemes?include_cross_sector=true returns all 10 schemes with zero duplicates.
6. Category filtering on GET /schemes?include_cross_sector=true isolates appropriate subsets.
7. GET /schemes/recommendations?include_cross_sector=true evaluates all 10 schemes with zero duplicates.
8. GET /schemes/{scheme_id} returns 200 and valid metadata for all 10 schemes.
9. GET /schemes/{scheme_id}/eligibility returns 200 and deterministic evaluation for all 10 schemes.
10. Backward compatibility: GET /schemes and GET /schemes/recommendations default to 5 education schemes.
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app
from eligibility.cross_sector_evaluator import CROSS_SECTOR_SCHEME_IDS
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


EDUCATION_SCHEME_IDS = [
    "SCHEME_EDU_001_PM_USP_CSSS",
    "SCHEME_EDU_002_AICTE_PRAGATI",
    "SCHEME_EDU_003_AICTE_SAKSHAM",
    "SCHEME_EDU_004_AICTE_SWANATH",
    "SCHEME_EDU_005_TOP_CLASS_SC",
]

ALL_TEN_SCHEME_IDS = EDUCATION_SCHEME_IDS + list(CROSS_SECTOR_SCHEME_IDS)


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_frontend_dash.db"
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
# 1. Frontend Structural & Script Audits
# ---------------------------------------------------------------------------

def test_01_dashboard_js_passes_include_cross_sector():
    """Verify that dashboard.js includes 'include_cross_sector=true' in loadCatalog and loadRecommendations."""
    dash_js_path = Path("frontend/js/dashboard.js")
    assert dash_js_path.exists(), "frontend/js/dashboard.js must exist"
    content = dash_js_path.read_text(encoding="utf-8")

    # Catalog call must set include_cross_sector=true
    assert 'params.set("include_cross_sector", "true")' in content, (
        "loadCatalog and/or loadRecommendations must set include_cross_sector to true"
    )
    # Ensure apiFetch(/schemes/recommendations...) includes params with include_cross_sector
    assert "apiFetch(`/schemes/recommendations?${params.toString()}`)" in content


def test_02_dashboard_html_contains_updated_categories_and_beneficiaries():
    """Verify that dashboard.html contains all 4 categories and cross-sector beneficiary groups."""
    dash_html_path = Path("frontend/dashboard.html")
    assert dash_html_path.exists(), "frontend/dashboard.html must exist"
    html = dash_html_path.read_text(encoding="utf-8")

    # Categories
    assert 'value="EDUCATION"' in html
    assert 'value="AGRICULTURE"' in html
    assert 'value="EMPLOYMENT_AND_BUSINESS"' in html
    assert 'value="SOCIAL_WELFARE"' in html

    # Cross-sector beneficiaries
    assert 'value="Farmers"' in html
    assert 'value="Street Vendors"' in html
    assert 'value="Unorganised Workers"' in html
    assert 'value="Women"' in html


def test_03_locales_contain_cross_sector_translations():
    """Verify that en.json, hi.json, and te.json include keys for new categories and beneficiaries."""
    for locale in ["en", "hi", "te"]:
        loc_path = Path(f"frontend/locales/{locale}.json")
        assert loc_path.exists(), f"Locale file {locale}.json must exist"
        data = json.loads(loc_path.read_text(encoding="utf-8"))
        schemes = data.get("schemes", {})

        # Category keys
        assert "catEducation" in schemes, f"catEducation missing in {locale}.json"
        assert "catAgriculture" in schemes, f"catAgriculture missing in {locale}.json"
        assert "catEmployment" in schemes, f"catEmployment missing in {locale}.json"
        assert "catSocialWelfare" in schemes, f"catSocialWelfare missing in {locale}.json"

        # Beneficiary keys
        assert "benFarmers" in schemes, f"benFarmers missing in {locale}.json"
        assert "benVendors" in schemes, f"benVendors missing in {locale}.json"
        assert "benWorkers" in schemes, f"benWorkers missing in {locale}.json"
        assert "benWomen" in schemes, f"benWomen missing in {locale}.json"


# ---------------------------------------------------------------------------
# 2. Scheme Discovery & Recommendation API Verification
# ---------------------------------------------------------------------------

def test_04_catalog_api_returns_all_ten_schemes_without_duplicates(client):
    """GET /schemes?include_cross_sector=true returns all 10 schemes with unique IDs."""
    res = client.get("/schemes?include_cross_sector=true")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    schemes = data["schemes"]
    assert len(schemes) == 10

    scheme_ids = [s["scheme_id"] for s in schemes]
    assert len(scheme_ids) == len(set(scheme_ids)), "Catalog must not contain duplicate scheme IDs"

    for expected_id in ALL_TEN_SCHEME_IDS:
        assert expected_id in scheme_ids, f"Expected scheme {expected_id} missing from catalog"


def test_05_catalog_category_filtering(client):
    """Category filter returns correct subsets when include_cross_sector=true is supplied."""
    category_counts = {
        "EDUCATION": 5,
        "AGRICULTURE": 1,
        "EMPLOYMENT_AND_BUSINESS": 2,
        "SOCIAL_WELFARE": 2,
    }

    for cat, expected_count in category_counts.items():
        res = client.get(f"/schemes?include_cross_sector=true&category={cat}")
        assert res.status_code == 200
        schemes = res.json()["schemes"]
        assert len(schemes) == expected_count, (
            f"Expected {expected_count} schemes for category {cat}, got {len(schemes)}"
        )


def test_06_recommendations_evaluates_all_ten_schemes_without_duplicates(client, auth_env):
    """GET /schemes/recommendations?include_cross_sector=true evaluates all 10 schemes."""
    # Setup registered user with basic profile
    client.post("/auth/signup", json={"email": "dash.rec@example.com", "password": "Password123!"})
    csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/profile/me",
        headers={"X-CSRF-Token": csrf},
        json={
            "full_name": "Ramesh Kumar",
            "date_of_birth": "1998-04-12",
            "gender": "MALE",
            "state": "Uttar Pradesh",
            "district": "Varanasi",
            "annual_income": 120000.0,
            "occupation": "Farmer",
            "caste_category": "OBC",
            "is_bpl": False,
        },
    )

    res = client.get("/schemes/recommendations?include_cross_sector=true&application_type=FRESH")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_schemes_evaluated"] == 10

    all_evaluated = data["preliminary_matches"] + data["rule_mismatches_requiring_review"]
    evaluated_ids = [item["scheme"]["scheme_id"] for item in all_evaluated]
    assert len(evaluated_ids) == 10
    assert len(evaluated_ids) == len(set(evaluated_ids)), "Evaluated recommendations must have no duplicates"

    for sid in ALL_TEN_SCHEME_IDS:
        assert sid in evaluated_ids, f"Scheme {sid} was not evaluated in recommendations"


def test_07_details_and_eligibility_for_all_ten_schemes(client, auth_env):
    """Verifies that details and eligibility endpoints resolve for every scheme."""
    client.post("/auth/signup", json={"email": "dash.detail@example.com", "password": "Password123!"})
    csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/profile/me",
        headers={"X-CSRF-Token": csrf},
        json={
            "full_name": "Anita Devi",
            "date_of_birth": "1990-08-20",
            "gender": "FEMALE",
            "state": "Bihar",
            "district": "Patna",
            "annual_income": 80000.0,
            "occupation": "Self-Employed",
            "caste_category": "SC",
            "is_bpl": True,
        },
    )

    for sid in ALL_TEN_SCHEME_IDS:
        # Details
        d_res = client.get(f"/schemes/{sid}")
        assert d_res.status_code == 200, f"GET /schemes/{sid} failed with {d_res.status_code}"
        assert d_res.json()["scheme"]["scheme_id"] == sid

        # Eligibility
        e_res = client.get(f"/schemes/{sid}/eligibility")
        assert e_res.status_code == 200, f"GET /schemes/{sid}/eligibility failed with {e_res.status_code}"
        assert e_res.json()["success"] is True
        assert "rule_match_status" in e_res.json()
        assert e_res.json()["review_required"] is True
        assert e_res.json()["official_eligibility_confirmed"] is False


def test_08_backward_compatibility_default_queries_remain_five_education_schemes(client, auth_env):
    """Default GET /schemes and GET /schemes/recommendations without flags return only 5 education schemes."""
    # Default catalog
    res_cat = client.get("/schemes")
    assert res_cat.status_code == 200
    assert len(res_cat.json()["schemes"]) == 5
    for s in res_cat.json()["schemes"]:
        assert s["scheme_id"] in EDUCATION_SCHEME_IDS

    # Default recommendations
    client.post("/auth/signup", json={"email": "dash.compat@example.com", "password": "Password123!"})
    csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/profile/me",
        headers={"X-CSRF-Token": csrf},
        json={
            "full_name": "Student A",
            "date_of_birth": "2005-01-01",
            "gender": "MALE",
            "state": "Delhi",
            "district": "New Delhi",
            "annual_income": 100000.0,
            "occupation": "Student",
            "caste_category": "GENERAL",
            "is_bpl": False,
        },
    )

    res_rec = client.get("/schemes/recommendations")
    assert res_rec.status_code == 200
    assert res_rec.json()["total_schemes_evaluated"] == 5
    all_evaluated = res_rec.json()["preliminary_matches"] + res_rec.json()["rule_mismatches_requiring_review"]
    for item in all_evaluated:
        assert item["scheme"]["scheme_id"] in EDUCATION_SCHEME_IDS


# ---------------------------------------------------------------------------
# 3. Three Independent Citizen Dashboard Status Badges Verification
# ---------------------------------------------------------------------------

def simulate_get_scheme_status_badges(scheme, item=None):
    """Python reference mirror of dashboard.js getSchemeStatusBadges component.

    Strictly reflects the three independent statuses:
    1. Application Status (Applications Open, Applications Closed, Open Year-round,
       Availability Needs Live Check, Check Quota Availability)
    2. Deadline Status (formatted deadline date, Closed: <date>, No Fixed Closing Date,
       No Fixed Deadline Established; Availability Needs Confirmation, Deadline Not Confirmed)
    3. Information Verification Status (Information Verified, Verification Pending)
    """
    s = scheme or (item and item.get("scheme")) or {}

    # 1. APPLICATION STATUS
    raw_app_status = str(
        s.get("application_status")
        or (item and item.get("application_status"))
        or s.get("application_availability_status")
        or s.get("deadline_status")
        or (item and item.get("deadline_status"))
        or ""
    ).upper().strip()

    if raw_app_status == "OPEN":
        app_status_text = "Applications Open"
        app_status_class = "badge-app-status badge-app-status-open"
    elif raw_app_status == "CLOSED":
        app_status_text = "Applications Closed"
        app_status_class = "badge-app-status badge-app-status-closed"
    elif raw_app_status == "YEAR_ROUND":
        app_status_text = "Open Year-round"
        app_status_class = "badge-app-status badge-app-status-year-round"
    elif raw_app_status == "NEEDS_LIVE_VERIFICATION":
        app_status_text = "Availability Needs Live Check"
        app_status_class = "badge-app-status badge-app-status-needs-verification"
    elif raw_app_status == "QUOTA_DEPENDENT":
        app_status_text = "Check Quota Availability"
        app_status_class = "badge-app-status badge-app-status-quota"
    elif raw_app_status == "UPCOMING":
        app_status_text = "Opening Soon"
        app_status_class = "badge-app-status badge-app-status-upcoming"
    else:
        app_status_text = "Availability Needs Live Check"
        app_status_class = "badge-app-status badge-app-status-needs-verification"

    # 2. DEADLINE STATUS
    raw_last_date = (
        (item and item.get("application_last_date"))
        or s.get("application_last_date")
        or s.get("application_deadline")
        or s.get("last_application_deadline")
        or ""
    )
    last_date = str(raw_last_date).strip() if raw_last_date and str(raw_last_date).strip() not in ("None", "null", "--") else ""

    d_status = str(
        (item and item.get("deadline_status"))
        or s.get("deadline_status")
        or raw_app_status
        or ""
    ).upper().strip()

    cycle = str(
        (item and item.get("application_cycle"))
        or s.get("application_cycle")
        or ""
    ).lower()

    if raw_app_status == "CLOSED" or d_status == "CLOSED":
        deadline_text = f"Closed: {last_date}" if last_date else "Applications Closed"
        deadline_class = "badge-deadline-status badge-deadline-closed"
    elif last_date:
        deadline_text = last_date
        deadline_class = "badge-deadline-status badge-deadline-date"
    elif (
        raw_app_status in ("NEEDS_LIVE_VERIFICATION", "QUOTA_DEPENDENT")
        or d_status in ("NEEDS_LIVE_VERIFICATION", "QUOTA_DEPENDENT")
    ):
        deadline_text = "No Fixed Deadline Established"
        deadline_class = "badge-deadline-status badge-deadline-needs-confirmation"
    elif (
        raw_app_status == "YEAR_ROUND"
        or d_status == "YEAR_ROUND"
        or "continuous" in cycle
        or "year-round" in cycle
    ):
        deadline_text = "No Fixed Closing Date"
        deadline_class = "badge-deadline-status badge-deadline-no-fixed"
    else:
        deadline_text = "Deadline Not Confirmed"
        deadline_class = "badge-deadline-status badge-deadline-unconfirmed"

    # 3. INFORMATION VERIFICATION STATUS (Internal review info hidden from citizen-facing cards)
    is_verified = bool(
        s.get("is_verified") is True
        or (item and item.get("is_verified") is True)
        or str(s.get("verification_status") or (item and item.get("verification_status")) or "").lower() == "verified"
    )

    if is_verified:
        ver_text = "Information Verified"
        ver_class = "badge-verification-status badge-verification-verified"
    else:
        # Hidden from citizen-facing scheme cards
        ver_text = ""
        ver_class = ""

    return {
        "application_status_text": app_status_text,
        "application_status_class": app_status_class,
        "deadline_status_text": deadline_text,
        "deadline_status_class": deadline_class,
        "verification_status_text": ver_text,
        "verification_status_class": ver_class,
    }


def test_09_frontend_badge_source_code_and_css_audit():
    """Verify dashboard.js and auth.css implement unified status badges."""
    dash_js = Path("frontend/js/dashboard.js").read_text(encoding="utf-8")
    auth_css = Path("frontend/css/auth.css").read_text(encoding="utf-8")

    # 1. Unified component exists in dashboard.js
    assert "function getSchemeStatusBadges" in dash_js
    assert "statusBadges.appStatusBadge" in dash_js
    assert "statusBadges.deadlineBadge" in dash_js
    assert "statusBadges.verificationBadge" in dash_js

    # 2. Both education and cross-sector cards use the SAME component
    assert dash_js.count("getSchemeStatusBadges") >= 4  # Defined, called in preliminary, mismatches, catalog

    # 3. Expected badge text mappings in dashboard.js
    assert "Open Year-round" in dash_js
    assert "Availability Needs Live Check" in dash_js
    assert "Check Quota Availability" in dash_js
    assert "No Fixed Closing Date" in dash_js
    assert "No Fixed Deadline Established" in dash_js
    assert "Deadline Not Confirmed" in dash_js
    assert "Information Verified" in dash_js

    # 4. CSS styling classes in auth.css
    assert ".badge-app-status" in auth_css
    assert ".badge-app-status-open" in auth_css
    assert ".badge-app-status-closed" in auth_css
    assert ".badge-app-status-year-round" in auth_css
    assert ".badge-app-status-needs-verification" in auth_css
    assert ".badge-app-status-quota" in auth_css

    assert ".badge-deadline-status" in auth_css
    assert ".badge-deadline-status.badge-deadline-date" in auth_css
    assert ".badge-deadline-status.badge-deadline-closed" in auth_css
    assert ".badge-deadline-status.badge-deadline-no-fixed" in auth_css
    assert ".badge-deadline-status.badge-deadline-needs-confirmation" in auth_css
    assert ".badge-deadline-status.badge-deadline-unconfirmed" in auth_css

    assert ".badge-verification-status" in auth_css
    assert ".badge-verification-status.badge-verification-verified" in auth_css


def test_10_status_badges_across_all_ten_cards_in_catalog(client):
    """Verify all 10 cards in catalog view produce the exact required status texts and hide internal verification pending."""
    res = client.get("/schemes?include_cross_sector=true")
    assert res.status_code == 200
    schemes = {s["scheme_id"]: s for s in res.json()["schemes"]}
    assert len(schemes) == 10

    # Scheme 1: PM-USP CSSS (CLOSED)
    s1 = simulate_get_scheme_status_badges(schemes["SCHEME_EDU_001_PM_USP_CSSS"])
    assert s1["application_status_text"] == "Applications Closed"
    assert s1["deadline_status_text"] == "Closed: 2026-10-31"
    assert s1["verification_status_text"] == ""

    # Scheme 2: AICTE Pragati (OPEN)
    s2 = simulate_get_scheme_status_badges(schemes["SCHEME_EDU_002_AICTE_PRAGATI"])
    assert s2["application_status_text"] == "Applications Open"
    assert s2["deadline_status_text"] == "2026-11-30"
    assert s2["verification_status_text"] == ""

    # Scheme 3: AICTE Saksham (OPEN)
    s3 = simulate_get_scheme_status_badges(schemes["SCHEME_EDU_003_AICTE_SAKSHAM"])
    assert s3["application_status_text"] == "Applications Open"
    assert s3["deadline_status_text"] == "2026-11-30"
    assert s3["verification_status_text"] == ""

    # Scheme 4: AICTE Swanath (OPEN)
    s4 = simulate_get_scheme_status_badges(schemes["SCHEME_EDU_004_AICTE_SWANATH"])
    assert s4["application_status_text"] == "Applications Open"
    assert s4["deadline_status_text"] == "2026-11-30"
    assert s4["verification_status_text"] == ""

    # Scheme 5: Top Class SC (OPEN)
    s5 = simulate_get_scheme_status_badges(schemes["SCHEME_EDU_005_TOP_CLASS_SC"])
    assert s5["application_status_text"] == "Applications Open"
    assert s5["deadline_status_text"] == "2026-11-30"
    assert s5["verification_status_text"] == ""

    # Scheme 6: PM-KISAN (YEAR_ROUND)
    s6 = simulate_get_scheme_status_badges(schemes["SCHEME_AGRI_001_PM_KISAN"])
    assert s6["application_status_text"] == "Open Year-round"
    assert s6["deadline_status_text"] == "No Fixed Closing Date"
    assert s6["verification_status_text"] == ""

    # Scheme 7: PMEGP (NEEDS_LIVE_VERIFICATION)
    s7 = simulate_get_scheme_status_badges(schemes["SCHEME_MSME_001_PMEGP"])
    assert s7["application_status_text"] == "Availability Needs Live Check"
    assert s7["deadline_status_text"] == "No Fixed Deadline Established"
    assert s7["verification_status_text"] == ""

    # Scheme 8: PM SVANidhi (YEAR_ROUND)
    s8 = simulate_get_scheme_status_badges(schemes["SCHEME_URBAN_001_PM_SVANIDHI"])
    assert s8["application_status_text"] == "Open Year-round"
    assert s8["deadline_status_text"] == "No Fixed Closing Date"
    assert s8["verification_status_text"] == ""

    # Scheme 9: PM-SYM (YEAR_ROUND)
    s9 = simulate_get_scheme_status_badges(schemes["SCHEME_LABOUR_001_PM_SYM"])
    assert s9["application_status_text"] == "Open Year-round"
    assert s9["deadline_status_text"] == "No Fixed Closing Date"
    assert s9["verification_status_text"] == ""

    # Scheme 10: PMUY 2.0 (QUOTA_DEPENDENT)
    s10 = simulate_get_scheme_status_badges(schemes["SCHEME_WOMEN_001_PMUY_2"])
    assert s10["application_status_text"] == "Check Quota Availability"
    assert s10["deadline_status_text"] == "No Fixed Deadline Established"
    assert s10["verification_status_text"] == ""

    # Ensure no card outputs Verification Pending or Dates Pending
    for s_res in [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10]:
        assert s_res["verification_status_text"] != "Verification Pending"
        assert s_res["deadline_status_text"] != "Dates Pending"


def test_11_status_badges_across_all_ten_cards_in_recommendations(client, auth_env):
    """Verify all 10 cards in citizen recommendations produce the exact 3 required status texts."""
    client.post("/auth/signup", json={"email": "dash.badge.test@example.com", "password": "Password123!"})
    csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/profile/me",
        headers={"X-CSRF-Token": csrf},
        json={
            "full_name": "Kavita Devi",
            "date_of_birth": "2002-05-15",
            "gender": "FEMALE",
            "state": "Bihar",
            "district": "Patna",
            "annual_income": 95000.0,
            "occupation": "Student",
            "caste_category": "SC",
            "is_bpl": True,
        },
    )

    res = client.get("/schemes/recommendations?include_cross_sector=true&application_type=FRESH")
    assert res.status_code == 200
    data = res.json()
    all_items = data["preliminary_matches"] + data["rule_mismatches_requiring_review"]
    evaluated_schemes = {it["scheme"]["scheme_id"]: it for it in all_items}
    assert len(evaluated_schemes) == 10

    expected_evaluations = {
        "SCHEME_EDU_001_PM_USP_CSSS": {
            "app_status": "Applications Closed",
            "deadline_status": "Closed: 2026-10-31",
            "verification_status": "",
        },
        "SCHEME_EDU_002_AICTE_PRAGATI": {
            "app_status": "Applications Open",
            "deadline_status": "2026-11-30",
            "verification_status": "",
        },
        "SCHEME_EDU_003_AICTE_SAKSHAM": {
            "app_status": "Applications Open",
            "deadline_status": "2026-11-30",
            "verification_status": "",
        },
        "SCHEME_EDU_004_AICTE_SWANATH": {
            "app_status": "Applications Open",
            "deadline_status": "2026-11-30",
            "verification_status": "",
        },
        "SCHEME_EDU_005_TOP_CLASS_SC": {
            "app_status": "Applications Open",
            "deadline_status": "2026-11-30",
            "verification_status": "",
        },
        "SCHEME_AGRI_001_PM_KISAN": {
            "app_status": "Open Year-round",
            "deadline_status": "No Fixed Closing Date",
            "verification_status": "",
        },
        "SCHEME_MSME_001_PMEGP": {
            "app_status": "Availability Needs Live Check",
            "deadline_status": "No Fixed Deadline Established",
            "verification_status": "",
        },
        "SCHEME_URBAN_001_PM_SVANIDHI": {
            "app_status": "Open Year-round",
            "deadline_status": "No Fixed Closing Date",
            "verification_status": "",
        },
        "SCHEME_LABOUR_001_PM_SYM": {
            "app_status": "Open Year-round",
            "deadline_status": "No Fixed Closing Date",
            "verification_status": "",
        },
        "SCHEME_WOMEN_001_PMUY_2": {
            "app_status": "Check Quota Availability",
            "deadline_status": "No Fixed Deadline Established",
            "verification_status": "",
        },
    }

    for sid, exp in expected_evaluations.items():
        assert sid in evaluated_schemes, f"Scheme {sid} missing from evaluated recommendations"
        it = evaluated_schemes[sid]
        badges = simulate_get_scheme_status_badges(it["scheme"], it)
        assert badges["application_status_text"] == exp["app_status"], (
            f"Scheme {sid}: Expected application status '{exp['app_status']}', got '{badges['application_status_text']}'"
        )
        assert badges["deadline_status_text"] == exp["deadline_status"], (
            f"Scheme {sid}: Expected deadline status '{exp['deadline_status']}', got '{badges['deadline_status_text']}'"
        )
        assert badges["verification_status_text"] == exp["verification_status"], (
            f"Scheme {sid}: Expected verification status '{exp['verification_status']}', got '{badges['verification_status_text']}'"
        )
        assert badges["verification_status_text"] != "Verification Pending"
        assert badges["deadline_status_text"] != "Dates Pending"


def test_12_status_badge_safeguards_and_dynamic_behavior():
    """Verify safeguards: verification pending hidden on citizen cards, open != closed, verified works dynamically."""
    # 1. Scheme that is open but unverified must NOT be closed, and verification pending must be hidden on citizen cards
    sample_open = {
        "scheme_id": "TEST_OPEN",
        "application_status": "OPEN",
        "application_last_date": "2026-11-30",
        "is_verified": False,
        "verification_status": "pending_review",
    }
    b_open = simulate_get_scheme_status_badges(sample_open)
    assert b_open["application_status_text"] == "Applications Open"
    assert b_open["deadline_status_text"] == "2026-11-30"
    assert b_open["verification_status_text"] == ""  # Hidden from citizen cards
    assert b_open["verification_status_text"] != "Verification Pending"
    assert b_open["application_status_text"] != "Applications Closed"

    # 2. Verified scheme must dynamically render 'Information Verified'
    sample_verified = {
        "scheme_id": "TEST_VERIFIED",
        "application_status": "OPEN",
        "application_last_date": "2026-11-30",
        "is_verified": True,
        "verification_status": "verified",
    }
    b_ver = simulate_get_scheme_status_badges(sample_verified)
    assert b_ver["verification_status_text"] == "Information Verified"
    assert b_ver["verification_status_class"] == "badge-verification-status badge-verification-verified"

    # 3. Null deadline with year-round cycle must NEVER render 'Dates Pending'
    sample_year_round = {
        "scheme_id": "TEST_YR",
        "application_status": "YEAR_ROUND",
        "application_deadline": None,
        "application_cycle": "Continuous Year-Round",
    }
    b_yr = simulate_get_scheme_status_badges(sample_year_round)
    assert b_yr["deadline_status_text"] == "No Fixed Closing Date"
    assert b_yr["deadline_status_text"] != "Dates Pending"

    # 4. Null deadline with quota dependency must NEVER render 'Dates Pending'
    sample_quota = {
        "scheme_id": "TEST_QUOTA",
        "application_status": "QUOTA_DEPENDENT",
        "application_deadline": None,
    }
    b_quota = simulate_get_scheme_status_badges(sample_quota)
    assert b_quota["deadline_status_text"] == "No Fixed Deadline Established"
    assert b_quota["deadline_status_text"] != "Dates Pending"


def test_13_prototype_card_actions_and_buttons(client, auth_env):
    """Verify that all major buttons (Details, Rule Breakdown, Apply Now) exist and wire correctly."""
    dash_js = Path("frontend/js/dashboard.js").read_text(encoding="utf-8")

    # 1. Action button selectors are present in card templates
    assert "btn-view-details" in dash_js
    assert "btn-view-eligibility" in dash_js
    assert "btn-apply-now" in dash_js

    # 2. Event listeners attach to all three button classes
    assert 'schemesContainer.querySelectorAll(".btn-view-details")' in dash_js
    assert 'schemesContainer.querySelectorAll(".btn-view-eligibility")' in dash_js
    assert 'schemesContainer.querySelectorAll(".btn-apply-now")' in dash_js

    # 3. Handlers exist in dashboard.js
    assert "function openSchemeDetails" in dash_js
    assert "function openDetailedEligibility" in dash_js
    assert "function handleApplyNowClick" in dash_js

    # 4. Verify endpoints underlying buttons succeed for all 10 schemes
    client.post("/auth/signup", json={"email": "dash.buttons.test@example.com", "password": "Password123!"})
    csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/profile/me",
        headers={"X-CSRF-Token": csrf},
        json={
            "full_name": "Test Citizen",
            "date_of_birth": "1995-01-01",
            "gender": "FEMALE",
            "state": "Uttar Pradesh",
            "district": "Lucknow",
            "annual_income": 60000.0,
            "occupation": "Student",
            "caste_category": "SC",
            "is_bpl": True,
        },
    )

    for sid in ALL_TEN_SCHEME_IDS:
        # Details button endpoint
        res_d = client.get(f"/schemes/{sid}")
        assert res_d.status_code == 200, f"Details endpoint failed for {sid}"
        assert res_d.json()["scheme"]["scheme_id"] == sid

        # Eligibility button endpoint
        res_e = client.get(f"/schemes/{sid}/eligibility")
        assert res_e.status_code == 200, f"Eligibility endpoint failed for {sid}"
        assert res_e.json()["success"] is True



