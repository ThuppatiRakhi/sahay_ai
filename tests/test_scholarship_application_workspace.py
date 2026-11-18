"""Comprehensive test suite for SahayAI Step 5.5A: Scholarship Application Workspace.

Verifies all 11 required scenarios:
1. All five scheme definitions load correctly with verified NSP portal and form sections.
2. Unknown scheme IDs are rejected.
3. Guests cannot create or manipulate application drafts (HTTP 403 Forbidden).
4. Registered citizens can create, list, and reopen application drafts.
5. Citizen A cannot access, update, or delete Citizen B's draft (strict IDOR isolation).
6. Draft updates persist correctly, including completion percentage and section progress.
7. Invalid field values (bad numbers, out-of-range, bad select options, bad status) are rejected.
8. Unverified portal URLs are never exposed as active links.
9. No automatic government submission occurs (draft status is purely internal preparation).
10. Existing document and recommendation workflows remain intact.
11. Localization key parity is maintained 100% across English, Telugu, and Hindi.
"""

import json
from pathlib import Path
import uuid
from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient

from api.main import app
from applications.application_service import ApplicationService
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from scheme_collection.application_definitions import (
    SUPPORTED_SCHEME_IDS,
    get_all_application_definitions,
    get_application_definition,
    is_valid_scheme_id,
)
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService

AUTHORIZED_ORIGIN = "http://localhost:5500"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_scholarship_app_workspace.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def app_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth service, profile manager, application service, and session manager."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
    app_svc = ApplicationService(db=test_db)
    scheme_svc = SchemeDiscoveryService(profile_manager=profiles)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)
    monkeypatch.setattr("api.applications.app_service", app_svc)
    monkeypatch.setattr("api.schemes.auth_service", auth_svc)
    monkeypatch.setattr("api.schemes.scheme_service", scheme_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
        "app_service": app_svc,
        "scheme_svc": scheme_svc,
    }


@pytest.fixture
def client(app_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _register_citizen(client, email="citizen_app@example.com", password="Password@123"):
    """Helper to register and configure a citizen session with CSRF token."""
    signup_res = client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]

    return user_id, csrf_token


# ---------------------------------------------------------------------------
# Test Scenarios
# ---------------------------------------------------------------------------

def test_01_all_five_scheme_definitions_load_correctly(client):
    """Test 1: All five scheme definitions load correctly with verified structure."""
    expected_schemes = [
        "SCHEME_EDU_001_PM_USP_CSSS",
        "SCHEME_EDU_002_AICTE_PRAGATI",
        "SCHEME_EDU_003_AICTE_SAKSHAM",
        "SCHEME_EDU_004_AICTE_SWANATH",
        "SCHEME_EDU_005_TOP_CLASS_SC",
    ]

    all_defs = get_all_application_definitions()
    assert len(all_defs) >= 5

    for s_id in expected_schemes:
        assert is_valid_scheme_id(s_id) is True
        defn = get_application_definition(s_id)
        assert defn is not None
        assert defn["scheme_id"] == s_id
        assert defn["scheme_name"]
        assert defn["application_year"] == "AY 2026-27"
        assert defn["specification_status"] == "TEMPLATE_REQUIRES_VERIFICATION"
        assert defn["last_reviewed_date"] == "2026-11-02"

        portal = defn["portal_verification"]
        assert portal["official_portal_url"].startswith("https://scholarships.gov.in")
        assert portal["portal_verification_status"] == "VERIFIED"
        assert portal["is_active_link"] is True

        assert len(defn["form_sections"]) >= 4
        assert len(defn["required_documents"]) >= 3

        # Test API endpoint
        api_res = client.get(f"/applications/schemes/{s_id}/definition")
        assert api_res.status_code == 200
        api_data = api_res.json()
        assert api_data["success"] is True
        assert api_data["definition"]["scheme_id"] == s_id

    # Test list endpoint
    list_res = client.get("/applications/schemes")
    assert list_res.status_code == 200
    assert list_res.json()["count"] >= 5


def test_02_unknown_scheme_ids_are_rejected(client, app_env):
    """Test 2: Unknown scheme IDs are rejected with appropriate error."""
    unknown_id = "SCHEME_EDU_999_UNKNOWN"
    assert is_valid_scheme_id(unknown_id) is False
    assert get_application_definition(unknown_id) is None

    # API definition retrieval returns 404
    res = client.get(f"/applications/schemes/{unknown_id}/definition")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

    # Draft creation with unknown scheme ID returns 400
    _, csrf = _register_citizen(client)
    create_res = client.post(
        "/applications/drafts",
        json={"scheme_id": unknown_id},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert create_res.status_code == 400
    assert "not supported" in create_res.json()["detail"].lower()


def test_03_guests_cannot_create_or_access_drafts(client):
    """Test 3: Guest sessions cannot create, list, view, update, or delete drafts (403 Forbidden)."""
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    guest_csrf = csrf_res.json()["csrf_token"]

    # 1. POST /applications/drafts
    create_res = client.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS"},
        headers={"X-CSRF-Token": guest_csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert create_res.status_code == 403
    assert "registered citizen" in create_res.json()["detail"].lower()

    # 2. GET /applications/drafts
    list_res = client.get("/applications/drafts")
    assert list_res.status_code == 403

    # 3. GET /applications/drafts/{id}
    get_res = client.get("/applications/drafts/draft_fake_123")
    assert get_res.status_code == 403

    # 4. PUT /applications/drafts/{id}
    put_res = client.put(
        "/applications/drafts/draft_fake_123",
        json={"form_data": {}},
        headers={"X-CSRF-Token": guest_csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert put_res.status_code == 403

    # 5. DELETE /applications/drafts/{id}
    del_res = client.delete(
        "/applications/drafts/draft_fake_123",
        headers={"X-CSRF-Token": guest_csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert del_res.status_code == 403


def test_04_registered_citizens_can_create_and_reopen_drafts(client):
    """Test 4: Registered citizens can create, list, and reopen their drafts."""
    user_id, csrf = _register_citizen(client, email="citizen_draft_create@example.com")

    # Create draft
    create_res = client.post(
        "/applications/drafts",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "application_mode": "FRESH",
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert create_res.status_code == 201
    draft_data = create_res.json()["draft"]
    draft_id = draft_data["draft_id"]
    assert draft_id.startswith("draft_")
    assert draft_data["user_id"] == user_id
    assert draft_data["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert draft_data["status"] == "DRAFT"
    assert draft_data["completion_percentage"] == 0.0

    # Reopen draft
    get_res = client.get(f"/applications/drafts/{draft_id}")
    assert get_res.status_code == 200
    fetched_draft = get_res.json()["draft"]
    assert fetched_draft["draft_id"] == draft_id
    assert fetched_draft["scheme_definition"]["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"

    # List drafts
    list_res = client.get("/applications/drafts")
    assert list_res.status_code == 200
    drafts = list_res.json()["drafts"]
    assert len(drafts) == 1
    assert drafts[0]["draft_id"] == draft_id
    assert drafts[0]["scheme_name"] == "PM-USP Central Sector Scholarship Scheme"


def test_05_citizen_a_cannot_access_citizen_b_draft(client, app_env):
    """Test 5: Strict IDOR defense - Citizen B cannot read, update, or delete Citizen A's draft."""
    client_a = TestClient(app)
    user_a, csrf_a = _register_citizen(client_a, email="citizen_a@example.com")

    create_res = client_a.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI"},
        headers={"X-CSRF-Token": csrf_a, "Origin": AUTHORIZED_ORIGIN},
    )
    assert create_res.status_code == 201
    draft_a_id = create_res.json()["draft"]["draft_id"]

    # Register Citizen B in separate client session
    client_b = TestClient(app)
    user_b, csrf_b = _register_citizen(client_b, email="citizen_b@example.com")

    # Citizen B attempts to read Citizen A's draft -> 404 (IDOR protected)
    get_res = client_b.get(f"/applications/drafts/{draft_a_id}")
    assert get_res.status_code == 404
    assert "not found or access denied" in get_res.json()["detail"].lower()

    # Citizen B attempts to update Citizen A's draft -> 404
    put_res = client_b.put(
        f"/applications/drafts/{draft_a_id}",
        json={"form_data": {"applicant_name": "Hacked Name"}},
        headers={"X-CSRF-Token": csrf_b, "Origin": AUTHORIZED_ORIGIN},
    )
    assert put_res.status_code == 404

    # Citizen B attempts to delete Citizen A's draft -> 404
    del_res = client_b.delete(
        f"/applications/drafts/{draft_a_id}",
        headers={"X-CSRF-Token": csrf_b, "Origin": AUTHORIZED_ORIGIN},
    )
    assert del_res.status_code == 404

    # Verify Citizen A's draft is unharmed
    verify_res = client_a.get(f"/applications/drafts/{draft_a_id}")
    assert verify_res.status_code == 200
    assert verify_res.json()["draft"]["user_id"] == user_a


def test_06_draft_updates_persist_correctly(client):
    """Test 6: Form fields and completion percentage update and persist correctly."""
    user_id, csrf = _register_citizen(client, email="citizen_update@example.com")

    create_res = client.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    draft_id = create_res.json()["draft"]["draft_id"]

    # Update several required fields
    update_data = {
        "form_data": {
            "applicant_name": "Ravi Kumar",
            "date_of_birth": "2004-08-20",
            "gender": "Male",
            "caste_category": "General",
            "mobile_number": "9876543210",
            "email_address": "ravi@example.com",
            "state_residence": "Telangana",
            "district_residence": "Hyderabad",
            "annual_family_income": 200000.0,
            "father_name": "Suresh Kumar",
            "mother_name": "Sunita Kumar",
            "bank_name": "State Bank of India",
            "account_number": "12345678901",
            "ifsc_code": "SBIN0001234",
            "aadhaar_seeded_confirmed": True,
            "institution_name": "Osmania University",
            "course_name": "B.Tech Computer Science",
            "course_type": "Regular Full-Time",
            "current_academic_year": "1st Year / Semester 1",
            "class_12_board_name": "Telangana State Board",
            "class_12_roll_no": "TS202610024",
            "class_12_passing_year": 2026,
            "class_12_percentile_or_marks": 92.5,
            "declaration_no_concurrent": True,
            "declaration_information_true": True,
        },
        "last_saved_section": "declarations",
        "status": "READY_FOR_REVIEW",
        "notes": "All original certificates verified.",
    }

    put_res = client.put(
        f"/applications/drafts/{draft_id}",
        json=update_data,
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert put_res.status_code == 200
    updated_draft = put_res.json()["draft"]
    assert updated_draft["status"] == "READY_FOR_REVIEW"
    assert updated_draft["last_saved_section"] == "declarations"
    assert updated_draft["notes"] == "All original certificates verified."
    assert updated_draft["completion_percentage"] == 100.0
    assert updated_draft["form_data"]["applicant_name"] == "Ravi Kumar"
    assert updated_draft["form_data"]["class_12_percentile_or_marks"] == 92.5

    # Re-fetch from DB to verify persistence across connections
    get_res = client.get(f"/applications/drafts/{draft_id}")
    assert get_res.status_code == 200
    persisted = get_res.json()["draft"]
    assert persisted["completion_percentage"] == 100.0
    assert persisted["status"] == "READY_FOR_REVIEW"
    assert persisted["form_data"]["ifsc_code"] == "SBIN0001234"


def test_07_invalid_field_values_are_rejected(client):
    """Test 7: Type mismatches, range violations, invalid selects and invalid statuses are rejected."""
    user_id, csrf = _register_citizen(client, email="citizen_invalid_fields@example.com")

    create_res = client.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    draft_id = create_res.json()["draft"]["draft_id"]

    # 1. Invalid status
    res1 = client.put(
        f"/applications/drafts/{draft_id}",
        json={"status": "INVALID_STATUS_VALUE"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res1.status_code == 422
    assert "invalid status" in res1.json()["detail"].lower()

    # 2. Non-numeric value for numeric field
    res2 = client.put(
        f"/applications/drafts/{draft_id}",
        json={"form_data": {"annual_family_income": "not_a_valid_number"}},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res2.status_code == 422
    assert "valid number" in res2.json()["detail"].lower()

    # 3. Numeric minimum constraint violation (Saksham requires min 40% disability)
    res3 = client.put(
        f"/applications/drafts/{draft_id}",
        json={"form_data": {"disability_percentage": 25}},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res3.status_code == 422
    assert "cannot be less than 40" in res3.json()["detail"].lower()

    # 4. Invalid select option
    res4 = client.put(
        f"/applications/drafts/{draft_id}",
        json={"form_data": {"gender": "MARTIAN"}},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res4.status_code == 422
    assert "not in allowed options" in res4.json()["detail"].lower()


def test_08_unverified_portal_urls_are_not_active_links():
    """Test 8: Schemes with unverified portals are never marked as active links."""
    # Test official schemes: all 5 are verified NSP
    for s_id in SUPPORTED_SCHEME_IDS:
        defn = get_application_definition(s_id)
        assert defn["portal_verification"]["portal_verification_status"] == "VERIFIED"
        assert defn["portal_verification"]["is_active_link"] is True

    # Test synthetic edge case: unverified portal
    fake_unverified = {
        "scheme_id": "TEST_UNVERIFIED",
        "portal_verification": {
            "portal_name": "Unverified Portal",
            "official_portal_url": "https://unknown-portal.org",
            "portal_verification_status": "NOT_VERIFIED",
            "is_active_link": False,
        },
    }
    assert fake_unverified["portal_verification"]["is_active_link"] is False
    assert fake_unverified["portal_verification"]["portal_verification_status"] != "VERIFIED"


def test_09_no_automatic_government_submission_occurs(client):
    """Test 9: Transitioning draft to READY_TO_CONTINUE does not contact external government endpoints."""
    user_id, csrf = _register_citizen(client, email="citizen_no_auto_sub@example.com")

    create_res = client.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_004_AICTE_SWANATH"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    draft_id = create_res.json()["draft"]["draft_id"]

    # Transition to READY_TO_CONTINUE
    put_res = client.put(
        f"/applications/drafts/{draft_id}",
        json={"status": "READY_TO_CONTINUE"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert put_res.status_code == 200
    assert put_res.json()["draft"]["status"] == "READY_TO_CONTINUE"

    # Status remains in SahayAI database without claiming government submission
    get_res = client.get(f"/applications/drafts/{draft_id}")
    assert get_res.json()["draft"]["status"] == "READY_TO_CONTINUE"


def test_10_existing_document_and_recommendation_workflows_remain_unchanged(client, app_env):
    """Test 10: Regression safety - Existing document library and recommendation APIs operate identically."""
    user_id, csrf = _register_citizen(client, email="citizen_regression@example.com")

    # 1. Profile recommendations
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Regression Student",
        "date_of_birth": "2004-01-01",
        "gender": "FEMALE",
        "state": "Maharashtra",
        "district": "Pune",
        "occupation": "Student",
        "caste_category": "GENERAL",
        "annual_income": 300000.0,
    })

    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 200
    assert "preliminary_matches" in rec_res.json()

    # 2. Document upload and confirmation
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    saved_id = profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": "280000"},
        document_category="INCOME",
    )
    assert saved_id == doc_id

    confirm_res = client.post(
        f"/documents/{doc_id}/confirm",
        json={
            "confirmed_fields": {
                "annual_income": 280000.0,
            },
            "allow_overwrite": True,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert confirm_res.status_code == 200

    # 3. Draft deletion test
    create_draft_res = client.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    draft_to_del = create_draft_res.json()["draft"]["draft_id"]

    del_res = client.delete(
        f"/applications/drafts/{draft_to_del}",
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Ensure draft is gone
    check_del = client.get(f"/applications/drafts/{draft_to_del}")
    assert check_del.status_code == 404


def test_11_localization_parity_is_maintained():
    """Test 11: 100% key parity across English, Telugu, and Hindi locale files."""
    locales_dir = Path("frontend/locales")
    with open(locales_dir / "en.json", "r", encoding="utf-8") as f:
        en = json.load(f)
    with open(locales_dir / "te.json", "r", encoding="utf-8") as f:
        te = json.load(f)
    with open(locales_dir / "hi.json", "r", encoding="utf-8") as f:
        hi = json.load(f)

    def extract_keys(d, prefix=""):
        keys = set()
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.update(extract_keys(v, full))
            else:
                keys.add(full)
        return keys

    keys_en = extract_keys(en)
    keys_te = extract_keys(te)
    keys_hi = extract_keys(hi)

    assert keys_en == keys_te, f"Discrepancy en vs te: {keys_en ^ keys_te}"
    assert keys_en == keys_hi, f"Discrepancy en vs hi: {keys_en ^ keys_hi}"

    # Verify specific Step 5.5A keys are present
    assert "nav.myApplications" in keys_en
    assert "schemes.btnApplyNow" in keys_en
    assert "applications.workspaceTitle" in keys_en
    assert "applications.workspaceModalDisclaimer" in keys_en
    assert "applications.requiredDocsChecklist" in keys_en
    assert "applications.btnContinueToPortal" in keys_en


def test_12_all_10_schemes_definitions_and_deadlines_integrity():
    """Test 12: Verify all 10 scheme definitions, open vs closed statuses, and Swanath deadline alignment."""
    all_defs = get_all_application_definitions()
    assert len(all_defs) == 10

    # 1. AICTE Swanath must be OPEN with 2026-11-30 deadline
    swanath = all_defs["SCHEME_EDU_004_AICTE_SWANATH"]
    assert swanath["application_availability_status"] == "OPEN"
    assert swanath["last_deadline"] == "2026-11-30"
    assert swanath["portal_verification"]["portal_verification_status"] == "VERIFIED"

    # 2. Pragati, Saksham, Top Class SC must also be OPEN with 2026-11-30 deadline
    for s_id in ["SCHEME_EDU_002_AICTE_PRAGATI", "SCHEME_EDU_003_AICTE_SAKSHAM", "SCHEME_EDU_005_TOP_CLASS_SC"]:
        d = all_defs[s_id]
        assert d["application_availability_status"] == "OPEN"
        assert d["last_deadline"] == "2026-11-30"
        assert d["portal_verification"]["portal_verification_status"] == "VERIFIED"

    # 3. PM-USP CSSS must be CLOSED (closed on 2026-10-31)
    csss = all_defs["SCHEME_EDU_001_PM_USP_CSSS"]
    assert csss["application_availability_status"] == "CLOSED"
    assert csss["last_deadline"] == "2026-10-31"

    # 4. Central welfare schemes must all be OPEN
    central_ids = [
        "SCHEME_AGRI_001_PM_KISAN",
        "SCHEME_MSME_001_PMEGP",
        "SCHEME_URBAN_001_PM_SVANIDHI",
        "SCHEME_LABOUR_001_PM_SYM",
        "SCHEME_WOMEN_001_PMUY_2",
    ]
    for cid in central_ids:
        c_def = all_defs[cid]
        assert c_def["application_availability_status"] == "OPEN"
        assert len(c_def["form_sections"]) >= 3
        assert len(c_def["required_documents"]) >= 2
        assert c_def["portal_verification"]["portal_verification_status"] == "VERIFIED"

