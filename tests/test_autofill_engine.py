"""Unit and integration test suite for SahayAI Step 5.5B:
Secure Autofill Engine and Chrome Extension Integration Foundation.

Verifies:
1. Short-lived (5-minute) scoped grant token generation.
2. Token expiry rejection (HTTP 401).
3. Scope and portal URL binding (official portal verification scholarships.gov.in).
4. Token hashing at rest (raw token is never persisted in SQLite).
5. Pure deterministic mapping across all five scholarship schemes.
6. Exclusion of unconfirmed OCR extraction fields.
7. Exclusion of fields from archived or deleted documents.
8. Conflict detection between profile and confirmed documents (MANDATORY_REVIEW).
9. Conflict preservation: Existing draft values are never silently overwritten.
10. Missing information reporting with actionable guidance.
11. Field-level provenance tracking on all resolved fields.
12. Encryption at rest for sensitive draft form data (Aadhaar, bank account, PAN, UDID).
13. Authorization endpoint security (registered citizens only, CSRF enforced).
14. Bearer token authentication on /applications/autofill/populate without session cookies.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import uuid
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from api.main import app
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from applications.application_service import ApplicationService
from applications.autofill_service import AutofillService
from document_ai.extract_fields import PIIVault
from scheme_collection.application_definitions import (
    SCHEME_APPLICATION_DEFINITIONS,
    get_application_definition,
)

AUTHORIZED_ORIGIN = "http://localhost:5500"


@pytest.fixture
def test_db(tmp_path):
    """Provides a fresh isolated SQLite database instance."""
    db_file = tmp_path / "sahay_autofill_test.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def app_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth, profile, application, autofill, and vault services."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
    vault = PIIVault(encryption_key=test_key)
    app_svc = ApplicationService(db=test_db, vault=vault)
    autofill_svc = AutofillService(db=test_db, profile_manager=profiles, app_service=app_svc, vault=vault)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)
    monkeypatch.setattr("api.applications.app_service", app_svc)
    monkeypatch.setattr("api.applications.autofill_service", autofill_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
        "app_service": app_svc,
        "autofill_service": autofill_svc,
        "vault": vault,
    }


@pytest.fixture
def client(app_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _register_citizen(client, email="citizen_autofill@example.com", password="Password@123"):
    """Helper to register and configure a citizen session with CSRF token."""
    signup_res = client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf = csrf_res.json()["csrf_token"]
    return user_id, csrf


# -----------------------------------------------------------------------------
# Test 01: Token Generation
# -----------------------------------------------------------------------------

def test_01_token_generation(client, app_env):
    """Test 01: Valid 5-min scoped grant token generation with user_id, scheme_id, draft_id, portal_url, scope."""
    user_id, csrf = _register_citizen(client, email="token_gen@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    grant = data["grant"]

    assert grant["grant_token"].startswith("sahay_atf_")
    assert grant["token_type"] == "Bearer"
    assert grant["expires_in_seconds"] == 300
    assert grant["scope"] == "extension:autofill"
    assert grant["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert grant["portal_url"] == "https://scholarships.gov.in"
    assert grant["draft_id"] == draft_id

    expires_at = datetime.fromisoformat(grant["expires_at"])
    now = datetime.now(timezone.utc)
    diff = (expires_at - now).total_seconds()
    assert 280 <= diff <= 310


# -----------------------------------------------------------------------------
# Test 02: Token Expiry Rejection
# -----------------------------------------------------------------------------

def test_02_token_expiry_rejection(client, app_env):
    """Test 02: Expired extension grant token is rejected with HTTP 401."""
    user_id, csrf = _register_citizen(client, email="token_expiry@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    # Authorize a valid token
    auth_res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert auth_res.status_code == 200
    grant_token = auth_res.json()["grant"]["grant_token"]

    # Manually backdate the grant expiry in database
    token_hash = hashlib.sha256(grant_token.encode("utf-8")).hexdigest()
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    db: Database = app_env["db"]
    with db.get_connection() as conn:
        conn.cursor().execute("UPDATE autofill_grants SET expires_at = ? WHERE token_hash = ?", (past_iso, token_hash))

    # Attempt to populate using the expired bearer token
    pop_res = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Authorization": f"Bearer {grant_token}"},
    )
    assert pop_res.status_code == 401
    assert "expired" in pop_res.json()["detail"].lower()


# -----------------------------------------------------------------------------
# Test 03: Scope and Portal Binding Rejection
# -----------------------------------------------------------------------------

def test_03_scope_and_portal_binding_rejection(client, app_env):
    """Test 03: Untrusted portal URLs or mismatched schemes are rejected."""
    user_id, csrf = _register_citizen(client, email="scope_bind@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    # 1. Authorize with untrusted portal URL must be rejected
    untrusted_res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://malicious-scholarship-phish.com",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert untrusted_res.status_code in (400, 422)
    assert "untrusted" in untrusted_res.json()["detail"].lower()

    # 2. Authorize a valid token for scheme 001
    valid_res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert valid_res.status_code == 200
    grant_token = valid_res.json()["grant"]["grant_token"]

    # 3. Extension calls populate with different scheme (SCHEME_EDU_002_AICTE_PRAGATI)
    mismatch_res = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Authorization": f"Bearer {grant_token}"},
    )
    assert mismatch_res.status_code == 401
    assert "unauthorized" in mismatch_res.json()["detail"].lower()


# -----------------------------------------------------------------------------
# Test 04: Token Hashing at Rest
# -----------------------------------------------------------------------------

def test_04_token_hashing_at_rest(client, app_env):
    """Test 04: Raw extension tokens are never stored in plaintext within SQLite."""
    user_id, csrf = _register_citizen(client, email="token_hash@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    auth_res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert auth_res.status_code == 200
    raw_token = auth_res.json()["grant"]["grant_token"]
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    db: Database = app_env["db"]
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT grant_id, token_hash, user_id, draft_id FROM autofill_grants WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()

    assert len(rows) == 1
    row = dict(rows[0])
    assert row["token_hash"] == expected_hash
    assert row["draft_id"] == draft_id
    assert raw_token not in json.dumps(row)


# -----------------------------------------------------------------------------
# Test 05: Deterministic Mapping Across All Five Schemes
# -----------------------------------------------------------------------------

def test_05_deterministic_mapping_all_five_schemes(client, app_env):
    """Test 05: Pure deterministic mapping is verified for all 5 official scholarship schemes."""
    user_id, csrf = _register_citizen(client, email="schemes_mapping@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    # Setup Profile
    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Kavita Rao",
        "date_of_birth": "2005-04-12",
        "gender": "FEMALE",
        "state": "Telangana",
        "district": "Hyderabad",
        "caste_category": "SC",
        "annual_income": 180000.0,
        "user_confirmed": True,
    })

    # Add confirmed documents for various schemes
    doc1 = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc1,
        user_id=user_id,
        document_type="BANK_PASSBOOK",
        extracted_fields={"bank_name": "State Bank of India", "ifsc_code": "SBIN0001234"},
        document_category="BANK",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc1,
        confirmed_items=[
            {"field_name": "bank_name", "field_value": "State Bank of India"},
            {"field_name": "ifsc_code", "field_value": "SBIN0001234"},
            {"field_name": "account_number", "field_value": "998877665544"},
        ],
        profile_updates={},
    )

    doc2 = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc2,
        user_id=user_id,
        document_type="MARKSHEET_12",
        extracted_fields={"class_12_roll_no": "TS123456", "class_12_passing_year": "2024"},
        document_category="ACADEMIC",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc2,
        confirmed_items=[
            {"field_name": "class_12_roll_no", "field_value": "TS123456"},
            {"field_name": "class_12_passing_year", "field_value": 2024},
            {"field_name": "class_12_board_name", "field_value": "Telangana State Board"},
            {"field_name": "institution_name", "field_value": "Hyderabad City College"},
        ],
        profile_updates={},
    )

    # Add AICTE & Disability docs
    doc3 = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc3,
        user_id=user_id,
        document_type="DISABILITY_CERTIFICATE",
        extracted_fields={"udid_card_number": "TG12345678901234"},
        document_category="DISABILITY",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc3,
        confirmed_items=[
            {"field_name": "disability_type", "field_value": "Locomotor Disability"},
            {"field_name": "disability_percentage", "field_value": 55},
            {"field_name": "udid_card_number", "field_value": "TG12345678901234"},
        ],
        profile_updates={},
    )

    target_schemes = [
        "SCHEME_EDU_001_PM_USP_CSSS",
        "SCHEME_EDU_002_AICTE_PRAGATI",
        "SCHEME_EDU_003_AICTE_SAKSHAM",
        "SCHEME_EDU_004_AICTE_SWANATH",
        "SCHEME_EDU_005_TOP_CLASS_SC",
    ]

    for sid in target_schemes:
        pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id=sid)
        assert pkg["scheme_id"] == sid
        assert "fields" in pkg
        fields = pkg["fields"]

        # Common attributes mapped deterministically
        assert fields["applicant_name"]["value"] == "Kavita Rao"
        assert fields["applicant_name"]["status"] == "POPULATED"
        assert fields["gender"]["value"] == "FEMALE"
        assert fields["bank_name"]["value"] == "State Bank of India"
        assert fields["ifsc_code"]["value"] == "SBIN0001234"
        assert fields["account_number"]["value"] == "998877665544"

        # Scheme-specific field assertions
        if sid == "SCHEME_EDU_001_PM_USP_CSSS":
            assert fields["class_12_roll_no"]["value"] == "TS123456"
            assert str(fields["class_12_passing_year"]["value"]) == "2024"
            assert fields["institution_name"]["value"] == "Hyderabad City College"

        elif sid == "SCHEME_EDU_003_AICTE_SAKSHAM":
            assert fields["disability_type"]["value"] == "Locomotor Disability"
            assert str(fields["disability_percentage"]["value"]) == "55"
            assert fields["udid_card_number"]["value"] == "TG12345678901234"


# -----------------------------------------------------------------------------
# Test 06: Unconfirmed OCR Extraction Fields Rejection
# -----------------------------------------------------------------------------

def test_06_unconfirmed_ocr_rejection(client, app_env):
    """Test 06: Unconfirmed OCR extraction values are strictly excluded from autofill."""
    user_id, csrf = _register_citizen(client, email="unconfirmed_ocr@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    # Save document with OCR extraction but NEVER confirm
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"income_certificate_number": "INC/99999/2026", "annual_income": "140000"},
        document_category="INCOME",
    )

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    fields = pkg["fields"]

    # income_certificate_number must NOT be populated from unconfirmed OCR
    assert fields["income_certificate_number"]["status"] == "MISSING_INFORMATION"
    assert fields["income_certificate_number"]["value"] is None
    assert fields["income_certificate_number"]["confidence"] == 0.0


# -----------------------------------------------------------------------------
# Test 07: Archived and Deleted Documents Rejection
# -----------------------------------------------------------------------------

def test_07_archived_and_deleted_doc_rejection(client, app_env):
    """Test 07: Fields originating from archived or soft-deleted documents are strictly excluded."""
    user_id, csrf = _register_citizen(client, email="archived_doc@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="BANK_PASSBOOK",
        extracted_fields={"bank_name": "Punjab National Bank"},
        document_category="BANK",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{"field_name": "bank_name", "field_value": "Punjab National Bank"}],
        profile_updates={},
    )

    # Initial check: bank_name is populated
    pkg1 = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    assert pkg1["fields"]["bank_name"]["value"] == "Punjab National Bank"

    # Now soft-delete/archive the document
    profile_mgr.delete_document(doc_id, user_id, hard_delete=False)

    # Next check: bank_name from archived document must be excluded
    pkg2 = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    assert pkg2["fields"]["bank_name"]["status"] == "MISSING_INFORMATION"
    assert pkg2["fields"]["bank_name"]["value"] is None


# -----------------------------------------------------------------------------
# Test 08: Conflict Handling (Profile vs Confirmed Document)
# -----------------------------------------------------------------------------

def test_08_conflict_handling_profile_vs_document(client, app_env):
    """Test 08: Profile vs document value mismatch flagged as CONFLICT and MANDATORY_REVIEW."""
    user_id, csrf = _register_citizen(client, email="conflict_prof_doc@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    # Profile says annual income is 250000
    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Conflict Citizen",
        "annual_income": 250000.0,
        "user_confirmed": True,
    })

    # Confirmed Income Certificate says annual income is 150000
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": "150000"},
        document_category="INCOME",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{"field_name": "annual_income", "field_value": 150000.0}],
        profile_updates={},
    )

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    income_field = pkg["fields"]["annual_family_income"]

    assert income_field["status"] == "CONFLICT"
    assert income_field["has_conflict"] is True
    assert income_field["review_requirement"] == "MANDATORY_REVIEW"
    assert len(income_field["competing_sources"]) >= 2

    source_types = [s["source_type"] for s in income_field["competing_sources"]]
    assert "CONFIRMED_DOCUMENT" in source_types
    assert "CITIZEN_PROFILE" in source_types


# -----------------------------------------------------------------------------
# Test 09: Conflict Handling (Draft vs Confirmed Data - No Silent Overwrites)
# -----------------------------------------------------------------------------

def test_09_conflict_handling_draft_vs_confirmed(client, app_env):
    """Test 09: Existing draft values are preserved and never silently overwritten by autofill."""
    user_id, csrf = _register_citizen(client, email="draft_conflict@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    app_svc: ApplicationService = app_env["app_service"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    # Citizen manually entered applicant_name in draft
    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]
    app_svc.update_draft(
        draft_id=draft_id,
        user_id=user_id,
        form_data={"applicant_name": "Citizen Custom Manually Entered Name"},
    )

    # Confirmed Aadhaar document has different name
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="AADHAAR",
        extracted_fields={"name": "Aadhaar Official Name"},
        document_category="IDENTITY",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{"field_name": "name", "field_value": "Aadhaar Official Name"}],
        profile_updates={},
    )

    pkg = autofill_svc.generate_autofill_package(
        user_id=user_id,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        draft_id=draft_id,
    )
    name_field = pkg["fields"]["applicant_name"]

    assert name_field["status"] == "CONFLICT"
    assert name_field["has_conflict"] is True
    assert name_field["review_requirement"] == "MANDATORY_REVIEW"
    # User's manually entered draft value is preserved as provisional
    assert name_field["value"] == "Citizen Custom Manually Entered Name"

    # Both competing values present
    values_in_sources = [str(s["value"]) for s in name_field["competing_sources"]]
    assert "Citizen Custom Manually Entered Name" in values_in_sources
    assert "Aadhaar Official Name" in values_in_sources


# -----------------------------------------------------------------------------
# Test 10: Missing Information Reporting
# -----------------------------------------------------------------------------

def test_10_missing_information_reporting(client, app_env):
    """Test 10: Missing fields are reported with clear reasons and actionable remedies."""
    user_id, csrf = _register_citizen(client, email="missing_info@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    acct_field = pkg["fields"]["account_number"]

    assert acct_field["status"] == "MISSING_INFORMATION"
    assert acct_field["value"] is None
    assert acct_field["has_conflict"] is False
    assert acct_field["review_requirement"] == "MANUAL_ENTRY_REQUIRED"
    assert "Bank account number is required" in acct_field["missing_reason"]
    assert "Bank Passbook" in acct_field["suggested_remedy"]


# -----------------------------------------------------------------------------
# Test 11: Field-Level Provenance Tracking
# -----------------------------------------------------------------------------

def test_11_field_level_provenance(client, app_env):
    """Test 11: All resolved fields contain full provenance metadata."""
    user_id, csrf = _register_citizen(client, email="provenance@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="COMMUNITY_CERTIFICATE",
        extracted_fields={"caste_category": "OBC"},
        document_category="CATEGORY_CERTIFICATE",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{"field_name": "caste_category", "field_value": "OBC"}],
        profile_updates={},
    )

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    caste_field = pkg["fields"]["caste_category"]

    assert caste_field["status"] == "POPULATED"
    src = caste_field["source"]
    assert src["source_type"] == "CONFIRMED_DOCUMENT"
    assert src["document_id"] == doc_id
    assert src["document_category"] == "CATEGORY_CERTIFICATE"
    assert src["source_field_name"] == "caste_category"
    assert src["citizen_confirmation_status"] == "CONFIRMED"
    assert src["confirmed_at"] is not None


# -----------------------------------------------------------------------------
# Test 12: Encryption at Rest for Sensitive Draft Form Data
# -----------------------------------------------------------------------------

def test_12_encryption_at_rest_for_draft_pii(client, app_env):
    """Test 12: Sensitive fields (Aadhaar, bank account, PAN, UDID) are encrypted in SQLite form_data_json."""
    user_id, csrf = _register_citizen(client, email="draft_encryption@example.com")
    app_svc: ApplicationService = app_env["app_service"]
    db: Database = app_env["db"]

    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    plain_account = "98765432109876"
    plain_aadhaar = "889977665544"

    # Save sensitive draft data
    app_svc.update_draft(
        draft_id=draft_id,
        user_id=user_id,
        form_data={
            "account_number": plain_account,
            "aadhaar_number": plain_aadhaar,
            "bank_name": "State Bank of India",
        },
    )

    # 1. Directly inspect SQLite database storage at rest
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT form_data_json FROM application_drafts WHERE draft_id = ?", (draft_id,))
        raw_json_str = cursor.fetchone()["form_data_json"]

    # Verify sensitive plain values NEVER appear anywhere in SQLite database JSON
    assert plain_account not in raw_json_str
    assert plain_aadhaar not in raw_json_str

    # Verify ciphertexts are present
    raw_storage_data = json.loads(raw_json_str)
    assert raw_storage_data["account_number"].startswith("ENC:FERNET:")
    assert raw_storage_data["aadhaar_number"].startswith("ENC:FERNET:")
    # Non-sensitive fields stored normal
    assert raw_storage_data["bank_name"] == "State Bank of India"

    # 2. Transparent decryption on retrieval for authenticated citizen
    fetched = app_svc.get_draft(draft_id=draft_id, user_id=user_id)
    assert fetched["form_data"]["account_number"] == plain_account
    assert fetched["form_data"]["aadhaar_number"] == plain_aadhaar
    assert fetched["form_data"]["bank_name"] == "State Bank of India"


# -----------------------------------------------------------------------------
# Test 13: Extension Authorization Endpoint Security
# -----------------------------------------------------------------------------

def test_13_extension_authorization_security(client, app_env):
    """Test 13: /applications/autofill/authorize rejects guests (403) and enforces CSRF protection."""
    # 1. Unauthenticated / Guest request is rejected
    res1 = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": "draft_dummy_12345",
        },
    )
    assert res1.status_code in (401, 403)

    # 2. Logged-in citizen without CSRF token is rejected
    user_id, csrf = _register_citizen(client, email="csrf_check@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    res2 = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Origin": AUTHORIZED_ORIGIN},  # missing X-CSRF-Token
    )
    assert res2.status_code == 403


# -----------------------------------------------------------------------------
# Test 14: Extension Populate with Bearer Token (No Session Cookie Needed)
# -----------------------------------------------------------------------------

def test_14_extension_populate_bearer_token(client, app_env):
    """Test 14: /applications/autofill/populate works with Bearer token without needing session cookies."""
    user_id, csrf = _register_citizen(client, email="bearer_populate@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    # Set up some confirmed data
    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Bearer Test Citizen",
        "gender": "MALE",
        "state": "Andhra Pradesh",
        "district": "Visakhapatnam",
        "user_confirmed": True,
    })

    # Obtain extension grant token
    auth_res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert auth_res.status_code == 200
    grant_token = auth_res.json()["grant"]["grant_token"]

    # Use a new unauthenticated client without session cookies
    unauthenticated_client = TestClient(app)

    pop_res = unauthenticated_client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Authorization": f"Bearer {grant_token}"},
    )
    assert pop_res.status_code == 200
    data = pop_res.json()
    assert data["success"] is True
    assert data["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert data["package"]["fields"]["applicant_name"]["value"] == "Bearer Test Citizen"

    # Verify used_at was updated in DB
    db: Database = app_env["db"]
    token_hash = hashlib.sha256(grant_token.encode("utf-8")).hexdigest()
    with db.get_connection() as conn:
        row = conn.cursor().execute("SELECT used_at FROM autofill_grants WHERE token_hash = ?", (token_hash,)).fetchone()
    assert row["used_at"] is not None
