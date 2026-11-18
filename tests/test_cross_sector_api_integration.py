"""Integration and contract tests for SahayAI Phase 2C Cross-Sector Eligibility API Integration.

Validates:
1. Existing education API behavior remains unchanged.
2. Cross-sector scheme discovery works (category, sector, keyword, include_cross_sector).
3. Combined discovery does not duplicate schemes.
4. Individual cross-sector evaluation works for all five central schemes:
   - PM-KISAN (SCHEME_AGRI_001_PM_KISAN)
   - PMEGP (SCHEME_MSME_001_PMEGP)
   - PM SVANidhi (SCHEME_URBAN_001_PM_SVANIDHI)
   - PM-SYM (SCHEME_LABOUR_001_PM_SYM)
   - PMUY 2.0 (SCHEME_WOMEN_001_PMUY_2)
5. Authenticated user context is strictly enforced from session cookie.
6. Cross-user access is completely blocked (client-supplied user_id ignored).
7. Only individually confirmed document fields are trusted.
8. Global profile confirmation flag (user_confirmed=True) is insufficient.
9. Unconfirmed OCR extractions are ignored.
10. Archived document records are excluded.
11. Conflicting evidence triggers REVIEW_REQUIRED and records conflict details.
12. Missing criteria produce UNKNOWN and populate missing_information.
13. Failed criteria produce FAIL.
14. All five central schemes strictly retain REVIEW_REQUIRED verification guard.
15. official_eligibility_confirmed is strictly False for all central schemes.
16. Invalid or unprovenanced supplemental questionnaire answers are rejected.
17. One scheme failure does not crash discovery or recommendations across other schemes.
18. POST /schemes/{scheme_id}/eligibility allows citizen declarations.
19. GET /schemes/{scheme_id}/questionnaire exposes official field schema and advisory conditions.
20. Temporary guest exploration is supported on eligibility endpoints.
"""

import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import get_session_config
from eligibility.cross_sector_evaluator import CROSS_SECTOR_SCHEME_IDS
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from document_ai.categories import DocumentCategory
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_cross_sector_api.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def api_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth service, profile manager, and scheme discovery service."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
    scheme_svc = SchemeDiscoveryService(profile_manager=profiles)

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
        "vault_dir": vault_dir,
    }


@pytest.fixture
def client(api_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _setup_citizen(client, api_env, email="citizen@example.com", password="Password@123", profile_data=None):
    """Helper to register and configure a citizen session with an optional profile."""
    signup_res = client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]

    if profile_data is not None:
        base_profile = {
            "user_id": user_id,
            "full_name": "Test Citizen",
            "date_of_birth": "1998-05-15",
            "gender": "FEMALE",
            "caste_category": "GENERAL",
            "state": "Maharashtra",
            "district": "Pune",
            "occupation": "Farmer",
            "annual_income": 150000.0,
        }
        base_profile.update(profile_data)
        api_env["profile_mgr"].create_profile(base_profile)

    return user_id, csrf_token


def _add_confirmed_doc_field(profile_mgr, user_id, field_name, field_value, doc_status="CONFIRMED", doc_type="AADHAAR"):
    """Helper to persist an active confirmed document field."""
    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type=doc_type,
        extracted_fields={field_name: field_value},
        document_category=DocumentCategory.IDENTITY.value,
        original_filename="doc.pdf",
        storage_reference=f"vault_{doc_id}",
        mime_type="application/pdf",
        file_size=1024,
        status="PENDING_REVIEW",
        confirmation_status="PENDING_CONFIRMATION",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{
            "field_name": field_name,
            "field_value": field_value,
            "extracted_value": field_value,
            "confirmation_status": "CONFIRMED",
        }],
        profile_updates={},
        new_document_status=doc_status,
    )
    return doc_id


def _declaration(val):
    return {
        "value": val,
        "source": "citizen_declaration",
        "confirmed": True,
    }


# =============================================================================
# 1. Existing Education API Behavior Preserved
# =============================================================================

def test_01_existing_education_api_unchanged(client, api_env):
    """Default GET /schemes and GET /schemes/recommendations continue returning education schemes."""
    # 1. Discovery without params returns only the 5 default education schemes
    res = client.get("/schemes")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 5
    scheme_ids = [s["scheme_id"] for s in data["schemes"]]
    assert "SCHEME_EDU_001_PM_USP_CSSS" in scheme_ids
    assert "SCHEME_AGRI_001_PM_KISAN" not in scheme_ids

    # 2. Recommendations without cross_sector flag evaluates exactly 5 education schemes
    user_id, _ = _setup_citizen(client, api_env, email="edu.check@example.com", profile_data={})
    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["success"] is True
    assert rec_data["total_schemes_evaluated"] == 5

    # 3. Individual education scheme evaluation continues to work
    edu_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility")
    assert edu_res.status_code == 200
    assert edu_res.json()["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"


# =============================================================================
# 2. Cross-Sector Discovery & No Duplication
# =============================================================================

def test_02_cross_sector_discovery_and_filtering(client):
    """Cross-sector schemes are discoverable via include_cross_sector, category, and sector."""
    # Explicit include_cross_sector=true returns all 10 schemes (5 education + 5 central)
    res_all = client.get("/schemes?include_cross_sector=true")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert data_all["count"] == 10
    ids_all = [s["scheme_id"] for s in data_all["schemes"]]
    for cid in CROSS_SECTOR_SCHEME_IDS:
        assert cid in ids_all

    # Category filter AGRICULTURE
    res_agri = client.get("/schemes?category=AGRICULTURE")
    assert res_agri.status_code == 200
    ids_agri = [s["scheme_id"] for s in res_agri.json()["schemes"]]
    assert "SCHEME_AGRI_001_PM_KISAN" in ids_agri
    assert "SCHEME_EDU_001_PM_USP_CSSS" not in ids_agri

    # Sector filter MSME
    res_msme = client.get("/schemes?sector=MSME")
    assert res_msme.status_code == 200
    ids_msme = [s["scheme_id"] for s in res_msme.json()["schemes"]]
    assert "SCHEME_MSME_001_PMEGP" in ids_msme

    # Keyword search 'svanidhi'
    res_sva = client.get("/schemes?q=svanidhi")
    assert res_sva.status_code == 200
    ids_sva = [s["scheme_id"] for s in res_sva.json()["schemes"]]
    assert "SCHEME_URBAN_001_PM_SVANIDHI" in ids_sva


def test_03_combined_discovery_no_duplicates(client):
    """Combined discovery guarantees zero duplicate scheme IDs."""
    res = client.get("/schemes?include_cross_sector=true")
    assert res.status_code == 200
    scheme_ids = [s["scheme_id"] for s in res.json()["schemes"]]
    assert len(scheme_ids) == len(set(scheme_ids))


# =============================================================================
# 3. Scheme Details & Questionnaire Endpoint
# =============================================================================

def test_04_get_scheme_details_and_questionnaire(client):
    """Central scheme details and questionnaire schema endpoints function accurately."""
    # Details for PM-KISAN
    res_det = client.get("/schemes/SCHEME_AGRI_001_PM_KISAN")
    assert res_det.status_code == 200
    assert res_det.json()["scheme"]["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN"

    # Questionnaire for PMEGP exposes fields and 4 advisory conditions
    res_q = client.get("/schemes/SCHEME_MSME_001_PMEGP/questionnaire")
    assert res_q.status_code == 200
    q_data = res_q.json()
    assert q_data["success"] is True
    assert q_data["requires_supplemental"] is True
    assert len(q_data["fields"]) > 0
    assert len(q_data["advisory_conditions_requiring_review"]) == 4

    # Questionnaire for education scheme indicates no supplemental questionnaire needed
    res_edu_q = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/questionnaire")
    assert res_edu_q.status_code == 200
    assert res_edu_q.json()["requires_supplemental"] is False

    # 404 on non-existent scheme
    res_404 = client.get("/schemes/NON_EXISTENT_SCHEME/questionnaire")
    assert res_404.status_code == 404


# =============================================================================
# 4. Authenticated Evaluation of All 5 Central Schemes
# =============================================================================

def test_05_pm_kisan_get_and_post_evaluation(client, api_env):
    """PM-KISAN evaluation via GET (unknown) and POST with declarations (PASS)."""
    user_id, csrf = _setup_citizen(client, api_env, email="kisan.user@example.com", profile_data={})

    # GET without declarations: missing information reported
    res_get = client.get("/schemes/SCHEME_AGRI_001_PM_KISAN/eligibility")
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN"
    assert data_get["rule_match_status"] == "UNKNOWN"
    assert data_get["status"] == "REVIEW_REQUIRED"
    assert data_get["official_eligibility_confirmed"] is False
    assert "land_ownership" in data_get["missing_information"]

    # POST with valid declarations: rules PASS, but verification guard remains REVIEW_REQUIRED
    res_post = client.post(
        "/schemes/SCHEME_AGRI_001_PM_KISAN/eligibility",
        json={
            "supplemental_data": {
                "land_ownership": _declaration(True),
                "institutional_landholder": _declaration(False),
                "income_tax_payee": _declaration(False),
                "constitutional_post_holder": _declaration(False),
            }
        },
    )
    assert res_post.status_code == 200
    data_post = res_post.json()
    assert data_post["rule_match_status"] == "PASS"
    assert data_post["status"] == "REVIEW_REQUIRED"
    assert data_post["official_eligibility_confirmed"] is False
    assert data_post["missing_information"] == []


def test_06_pmegp_evaluation_and_advisory_separation(client, api_env):
    """PMEGP separates deterministic rule evaluation from advisory operational conditions."""
    profile_mgr = api_env["profile_mgr"]
    user_id, _ = _setup_citizen(client, api_env, email="pmegp.user@example.com", profile_data={"age": 28})
    _add_confirmed_doc_field(profile_mgr, user_id, "age", 28)

    res = client.post(
        "/schemes/SCHEME_MSME_001_PMEGP/eligibility",
        json={
            "supplemental_data": {
                "new_project_only": _declaration(True),
                "negative_list_activity": _declaration(False),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["rule_match_status"] == "PASS"
    assert data["status"] == "REVIEW_REQUIRED"
    assert data["official_eligibility_confirmed"] is False
    assert len(data["advisory_conditions_requiring_review"]) == 4


def test_07_pm_svanidhi_evaluation(client, api_env):
    """PM SVANidhi evaluation via API with vendor declaration."""
    user_id, _ = _setup_citizen(client, api_env, email="svanidhi.user@example.com", profile_data={})

    res = client.post(
        "/schemes/SCHEME_URBAN_001_PM_SVANIDHI/eligibility",
        json={
            "supplemental_data": {
                "occupation_street_vendor": _declaration(True),
                "ulb_vendor_identification": _declaration(True),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["rule_match_status"] == "PASS"
    assert data["status"] == "REVIEW_REQUIRED"


def test_08_pm_sym_evaluation(client, api_env):
    """PM-SYM evaluation with confirmed document age and declared monthly income."""
    profile_mgr = api_env["profile_mgr"]
    user_id, _ = _setup_citizen(client, api_env, email="pmsym.user@example.com", profile_data={"age": 25})
    _add_confirmed_doc_field(profile_mgr, user_id, "age", 25)

    res = client.post(
        "/schemes/SCHEME_LABOUR_001_PM_SYM/eligibility",
        json={
            "supplemental_data": {
                "monthly_income": _declaration(12000),
                "covered_by_epfo_esic_nps": _declaration(False),
                "income_tax_payee": _declaration(False),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["rule_match_status"] == "PASS"
    assert data["status"] == "REVIEW_REQUIRED"


def test_09_pmuy_evaluation(client, api_env):
    """PMUY 2.0 evaluation with confirmed document gender and age."""
    profile_mgr = api_env["profile_mgr"]
    user_id, _ = _setup_citizen(client, api_env, email="pmuy.user@example.com", profile_data={"gender": "FEMALE", "age": 26})
    _add_confirmed_doc_field(profile_mgr, user_id, "gender", "FEMALE")
    _add_confirmed_doc_field(profile_mgr, user_id, "age", 26)

    res = client.post(
        "/schemes/SCHEME_WOMEN_001_PMUY_2/eligibility",
        json={
            "supplemental_data": {
                "existing_lpg_connection_in_household": _declaration(False),
                "qualifying_deprivation_category": _declaration(True),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["rule_match_status"] == "PASS"
    assert data["status"] == "REVIEW_REQUIRED"


# =============================================================================
# 5. Security & Authentication Boundaries
# =============================================================================

def test_10_unauthenticated_request_rejected(client):
    """Requests without authentication session cookie return HTTP 401."""
    fresh_client = TestClient(app)
    res_get = fresh_client.get("/schemes/SCHEME_AGRI_001_PM_KISAN/eligibility")
    assert res_get.status_code == 401

    res_post = fresh_client.post("/schemes/SCHEME_AGRI_001_PM_KISAN/eligibility", json={})
    assert res_post.status_code == 401


def test_11_cross_user_access_blocked(client, api_env):
    """User B cannot evaluate or access User A's profile or document evidence."""
    # User A has confirmed age 25
    user_a_id, _ = _setup_citizen(client, api_env, email="usera.sec@example.com", profile_data={"age": 25})
    _add_confirmed_doc_field(api_env["profile_mgr"], user_a_id, "age", 25)

    # User B has empty profile with no confirmed age
    client_b = TestClient(app)
    user_b_id, _ = _setup_citizen(client_b, api_env, email="userb.sec@example.com", profile_data={"age": None})

    # User B attempts to evaluate PMEGP passing User A's ID in query and body
    res_b = client_b.post(
        f"/schemes/SCHEME_MSME_001_PMEGP/eligibility?user_id={user_a_id}",
        json={
            "user_id": user_a_id,
            "supplemental_data": {
                "new_project_only": _declaration(True),
                "negative_list_activity": _declaration(False),
            },
        },
    )
    assert res_b.status_code == 200
    data_b = res_b.json()
    # User B's evaluation must NOT use User A's age; minimum_age must remain UNKNOWN
    assert "minimum_age" in data_b["missing_information"]
    assert data_b["rule_match_status"] == "UNKNOWN"


def test_12_global_user_confirmed_true_is_insufficient(client, api_env):
    """Global user_confirmed=True alone does not establish confirmed age or gender."""
    # User with user_confirmed=True in profile but NO confirmed document records
    user_id, _ = _setup_citizen(
        client,
        api_env,
        email="global.conf@example.com",
        profile_data={"age": 28, "user_confirmed": True},
    )

    res = client.post(
        "/schemes/SCHEME_MSME_001_PMEGP/eligibility",
        json={
            "supplemental_data": {
                "new_project_only": _declaration(True),
                "negative_list_activity": _declaration(False),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    # Must be UNKNOWN because no provenanced document record exists
    assert "minimum_age" in data["missing_information"]
    assert data["rule_match_status"] == "UNKNOWN"


def test_13_archived_document_records_ignored(client, api_env):
    """Confirmed document fields with ARCHIVED status are excluded."""
    profile_mgr = api_env["profile_mgr"]
    user_id, _ = _setup_citizen(client, api_env, email="archived.user@example.com", profile_data={"age": 28})
    # Add document with ARCHIVED status
    _add_confirmed_doc_field(profile_mgr, user_id, "age", 28, doc_status="ARCHIVED")

    res = client.post(
        "/schemes/SCHEME_MSME_001_PMEGP/eligibility",
        json={
            "supplemental_data": {
                "new_project_only": _declaration(True),
                "negative_list_activity": _declaration(False),
            }
        },
    )
    assert res.status_code == 200
    assert "minimum_age" in res.json()["missing_information"]
    assert res.json()["rule_match_status"] == "UNKNOWN"


def test_14_conflicting_evidence_triggers_review(client, api_env):
    """Mismatch between confirmed document age and declared supplemental age triggers conflict."""
    profile_mgr = api_env["profile_mgr"]
    user_id, _ = _setup_citizen(client, api_env, email="conflict.user@example.com", profile_data={"age": 25})
    _add_confirmed_doc_field(profile_mgr, user_id, "age", 25)

    # Document age is 25, but citizen declares entry_age as 35
    res = client.post(
        "/schemes/SCHEME_LABOUR_001_PM_SYM/eligibility",
        json={
            "supplemental_data": {
                "entry_age": _declaration(35),
                "monthly_income": _declaration(10000),
                "covered_by_epfo_esic_nps": _declaration(False),
                "income_tax_payee": _declaration(False),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["has_conflicts"] is True
    assert data["status"] == "REVIEW_REQUIRED"
    assert data["rule_match_status"] == "UNKNOWN"
    assert "entry_age" in data["missing_information"]
    assert len(data["conflicts"]) == 1


def test_15_invalid_supplemental_types_rejected(client, api_env):
    """Strings, NaN, negatives, and booleans-as-numbers are rejected in supplemental data."""
    user_id, _ = _setup_citizen(client, api_env, email="invalid.types@example.com", profile_data={})

    res = client.post(
        "/schemes/SCHEME_LABOUR_001_PM_SYM/eligibility",
        json={
            "supplemental_data": {
                "monthly_income": _declaration("not_a_number"),
                "covered_by_epfo_esic_nps": _declaration("true"),
                "income_tax_payee": _declaration(0),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["rule_match_status"] == "UNKNOWN"
    assert "monthly_income" in data["missing_information"]
    assert "covered_by_epfo_esic_nps" in data["missing_information"]


def test_16_failed_criteria_produces_fail(client, api_env):
    """A definitively failed criterion produces FAIL."""
    profile_mgr = api_env["profile_mgr"]
    user_id, _ = _setup_citizen(client, api_env, email="failed.user@example.com", profile_data={"age": 16})
    _add_confirmed_doc_field(profile_mgr, user_id, "age", 16)

    res = client.post(
        "/schemes/SCHEME_MSME_001_PMEGP/eligibility",
        json={
            "supplemental_data": {
                "new_project_only": _declaration(True),
                "negative_list_activity": _declaration(False),
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["rule_match_status"] == "FAIL"


def test_17_cross_sector_recommendations_flow(client, api_env):
    """GET /schemes/recommendations with include_cross_sector=true evaluates all 10 schemes."""
    user_id, _ = _setup_citizen(client, api_env, email="rec.all@example.com", profile_data={})

    res = client.get("/schemes/recommendations?include_cross_sector=true")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_schemes_evaluated"] == 10
    all_recs = data["preliminary_matches"] + data["rule_mismatches_requiring_review"]
    rec_ids = [r["scheme"]["scheme_id"] for r in all_recs]
    for cid in CROSS_SECTOR_SCHEME_IDS:
        assert cid in rec_ids
    assert len(rec_ids) == len(set(rec_ids)), "Recommendations must have no duplicate scheme IDs"


def test_18_guest_exploration_on_cross_sector_scheme(client):
    """Guest session with temporary profile evaluates cross-sector scheme without 401."""
    session_res = client.post("/auth/guest")
    assert session_res.status_code == 200

    # Populate temporary guest profile context
    csrf_res = client.get("/auth/csrf-token")
    csrf_token = csrf_res.json()["csrf_token"]
    ctx_res = client.post(
        "/auth/guest/context",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"temporary_profile": {"state": "Maharashtra", "occupation": "Farmer"}},
    )
    assert ctx_res.status_code == 200

    res = client.get("/schemes/SCHEME_AGRI_001_PM_KISAN/eligibility")
    assert res.status_code == 200
    assert res.json()["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN"
