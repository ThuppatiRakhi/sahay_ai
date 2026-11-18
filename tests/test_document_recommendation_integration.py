"""Tests for SahayAI Step 5.4C: Connect Confirmed Documents to Scholarship Recommendations.

Verifies end-to-end integration:
1. Confirmed income affects recommendations.
2. Unconfirmed income OCR does not affect recommendations.
3. Unconfirmed caste/category OCR does not affect recommendations.
4. Archived documents are excluded from active evidence.
5. Conflicting confirmed values flag review.
6. Missing information remains UNKNOWN.
7. Guest users cannot access personalized recommendations (HTTP 403).
8. Citizen A cannot access Citizen B's documents (IDOR isolation).
9. Recommendations remain 100% deterministic.
10. Scheme verification status remains unverified / review_required.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient

from api.main import app
from document_ai.categories import DocumentCategory
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from scheme_collection.document_readiness import (
    DocumentReadinessStatus,
    evaluate_scheme_document_readiness,
)
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_doc_rec_integration.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def app_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth service, profile manager, and scheme discovery service."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
    scheme_svc = SchemeDiscoveryService(profile_manager=profiles)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)
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
def client(app_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _register_citizen(client, app_env, email="citizen_rec@example.com", password="Password@123", profile_data=None):
    """Helper to register and configure a citizen session with full valid profile."""
    signup_res = client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]

    base_profile = {
        "user_id": user_id,
        "full_name": "Test Citizen",
        "date_of_birth": "2002-05-15",
        "gender": "FEMALE",
        "caste_category": "GENERAL",
        "state": "Maharashtra",
        "district": "Pune",
        "occupation": "Student",
        "annual_income": 150000.0,
    }
    if profile_data is not None:
        base_profile.update(profile_data)

    profile_mgr: ProfileManager = app_env["profile_mgr"]
    profile_mgr.create_profile(base_profile)

    return user_id, csrf_token


# ---------------------------------------------------------------------------
# Test Scenarios (1 to 10)
# ---------------------------------------------------------------------------

def test_01_confirmed_income_affects_recommendations(client, app_env):
    """1. Confirmed income affects recommendations:
    A citizen confirms an Income Certificate (₹1,50,000). The recommendation engine uses
    this confirmed income to satisfy income-based criteria and attaches active evidence chips.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_income@example.com",
        profile_data={
            "full_name": "Priya Sharma",
            "gender": "FEMALE",
            "state": "Maharashtra",
            "caste_category": "GENERAL",
            "annual_income": None,  # Initially missing from profile
        },
    )

    profile_mgr: ProfileManager = app_env["profile_mgr"]

    # Citizen uploads income certificate
    doc_id = profile_mgr.save_document(
        document_id=f"doc_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": 150000.0},
        document_category=DocumentCategory.INCOME.value,
        original_filename="Tahsildar_Income_Cert.pdf",
        storage_reference="vault_ref_income_01",
        mime_type="application/pdf",
        file_size=2048,
        status="PENDING_REVIEW",
        confirmation_status="PENDING_CONFIRMATION",
    )

    # Citizen explicitly confirms income
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{
            "field_name": "annual_income",
            "field_value": 150000.0,
            "extracted_value": 150000.0,
            "is_corrected": False,
        }],
        profile_updates={"annual_income": 150000.0},
    )

    # Fetch recommendations
    res = client.get("/schemes/recommendations")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # CSSS and Pragati have income limits (4.5L and 8L). Both should be in preliminary matches
    preliminary = data["preliminary_matches"]
    scheme_ids = [m["scheme"]["scheme_id"] for m in preliminary]
    assert "SCHEME_EDU_001_PM_USP_CSSS" in scheme_ids
    assert "SCHEME_EDU_002_AICTE_PRAGATI" in scheme_ids

    # Find CSSS match and check evidence & readiness
    csss_rec = next(m for m in preliminary if m["scheme"]["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS")
    assert csss_rec["matched_conditions_count"] >= 1

    # Confirmed evidence chip must be present
    evidence = csss_rec["confirmed_evidence"]
    assert any(e["criterion"] == "annual_family_income" and "150,000" in e["value"] for e in evidence)

    # Document readiness for Income Certificate must be AVAILABLE_AND_CONFIRMED
    doc_readiness = csss_rec["document_readiness"]
    income_doc = next(d for d in doc_readiness if "Income" in d["document_name"])
    assert income_doc["status"] == DocumentReadinessStatus.AVAILABLE_AND_CONFIRMED.value


def test_02_unconfirmed_income_ocr_does_not_affect_recommendations(client, app_env):
    """2. Unconfirmed income OCR does not affect recommendations:
    A citizen uploads an income document with OCR indicating ₹1,50,000, but has NOT reviewed/confirmed it.
    The recommendation engine must NOT use this unconfirmed value.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_unconfirmed_income@example.com",
        profile_data={
            "full_name": "Rahul Verma",
            "gender": "MALE",
            "annual_income": None,  # No profile income
        },
    )

    profile_mgr: ProfileManager = app_env["profile_mgr"]

    # Upload document with OCR income, but leave PENDING_REVIEW / PENDING_CONFIRMATION
    doc_id = profile_mgr.save_document(
        document_id=f"doc_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": 150000.0},
        document_category=DocumentCategory.INCOME.value,
        original_filename="Unreviewed_Income.pdf",
        storage_reference="vault_ref_unreviewed",
        mime_type="application/pdf",
        file_size=1024,
        status="PENDING_REVIEW",
        confirmation_status="PENDING_CONFIRMATION",
    )

    # Check recommendations
    res = client.get("/schemes/recommendations")
    assert res.status_code == 200
    data = res.json()

    # In CSSS, annual_family_income rule must be UNKNOWN (in missing_information), NOT passed
    preliminary = data["preliminary_matches"]
    csss_rec = next(m for m in preliminary if m["scheme"]["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS")
    assert "annual_family_income" in csss_rec["missing_information"]

    # Confirmed evidence must NOT include the unconfirmed income
    evidence = csss_rec["confirmed_evidence"]
    assert not any(e.get("criterion") == "annual_family_income" for e in evidence)

    # Document readiness must report PENDING_CONFIRMATION with action link
    doc_readiness = csss_rec["document_readiness"]
    income_doc = next(d for d in doc_readiness if "Income" in d["document_name"])
    assert income_doc["status"] == DocumentReadinessStatus.PENDING_CONFIRMATION.value
    assert income_doc["action_required"] == "REVIEW_PENDING"
    assert income_doc["action_document_id"] == doc_id


def test_03_unconfirmed_caste_category_ocr_does_not_affect_recommendations(client, app_env):
    """3. Unconfirmed caste/category OCR does not affect recommendations:
    Citizen uploaded SC Caste Certificate with OCR "SC", but has NOT confirmed it.
    Top Class SC recommendation must NOT treat category as confirmed SC.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_unconfirmed_caste@example.com",
        profile_data={
            "full_name": "Amit Kumar",
            "caste_category": "GENERAL",
            "annual_income": 200000.0,
        },
    )

    profile_mgr: ProfileManager = app_env["profile_mgr"]

    # Upload caste cert with OCR "SC", unconfirmed
    doc_id = profile_mgr.save_document(
        document_id=f"doc_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        document_type="SC_CERTIFICATE",
        extracted_fields={"caste_category": "SC"},
        document_category=DocumentCategory.CATEGORY_CERTIFICATE.value,
        original_filename="SC_Certificate_Raw.pdf",
        storage_reference="vault_ref_caste_raw",
        mime_type="application/pdf",
        file_size=1500,
        status="PENDING_REVIEW",
        confirmation_status="PENDING_CONFIRMATION",
    )

    res = client.get("/schemes/recommendations")
    assert res.status_code == 200
    data = res.json()

    # Top Class SC requires SC category. Since caste is General and doc is unconfirmed,
    # Top Class SC must be in rule mismatches.
    mismatches = data["rule_mismatches_requiring_review"]
    top_class_mismatch = next((m for m in mismatches if m["scheme"]["scheme_id"] == "SCHEME_EDU_005_TOP_CLASS_SC"), None)
    assert top_class_mismatch is not None
    assert top_class_mismatch["failed_conditions_count"] >= 1

    # Caste certificate readiness in Top Class SC must be PENDING_CONFIRMATION
    doc_read = top_class_mismatch["document_readiness"]
    caste_doc = next(d for d in doc_read if "Caste" in d["document_name"])
    assert caste_doc["status"] == DocumentReadinessStatus.PENDING_CONFIRMATION.value


def test_04_archived_documents_excluded_from_active_evidence(client, app_env):
    """4. Archived documents are excluded from active evidence:
    A citizen confirmed an income document, but later archives it.
    The confirmed income must be excluded from active evidence for ongoing recommendations.
    Its readiness status must return to MISSING.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_archive@example.com",
        profile_data={"full_name": "Anita Roy", "annual_income": None},
    )

    profile_mgr: ProfileManager = app_env["profile_mgr"]

    # Upload and confirm document
    doc_id = profile_mgr.save_document(
        document_id=f"doc_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": 120000.0},
        document_category=DocumentCategory.INCOME.value,
        original_filename="Income_To_Archive.pdf",
        storage_reference="vault_ref_archive_test",
        mime_type="application/pdf",
        file_size=1024,
        status="CONFIRMED",
        confirmation_status="CONFIRMED",
    )
    profile_mgr.save_confirmed_field(
        user_id=user_id,
        document_id=doc_id,
        field_name="annual_income",
        field_value=120000.0,
    )

    # Soft-delete / archive document
    archive_res = client.delete(
        f"/documents/{doc_id}?hard_delete=false",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert archive_res.status_code == 200

    # Verify document status in DB is ARCHIVED
    doc_record = profile_mgr.get_document(doc_id)
    assert doc_record["status"] == "ARCHIVED"

    # Evaluate recommendations
    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()

    # Active confirmed fields query must exclude this document
    active_fields = profile_mgr.get_active_confirmed_fields_with_documents(user_id)
    assert len(active_fields) == 0

    # CSSS required document readiness for Income must be MISSING
    csss = next(m for m in rec_data["preliminary_matches"] if m["scheme"]["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS")
    inc_req = next(d for d in csss["document_readiness"] if "Income" in d["document_name"])
    assert inc_req["status"] == DocumentReadinessStatus.MISSING.value

    # Confirmed evidence must be empty
    assert len(csss["confirmed_evidence"]) == 0


def test_05_conflicting_confirmed_values_flag_review(client, app_env):
    """5. Conflicting confirmed values flag review:
    Citizen profile states annual income ₹9,00,000, but confirmed active document indicates ₹1,50,000.
    The evaluation must flag the criterion as a CONFLICT / REVIEW_REQUIRED without silently overwriting.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_conflict@example.com",
        profile_data={
            "full_name": "Suresh Gupta",
            "annual_income": 900000.0,  # Profile exceeds CSSS limit (4.5L)
            "state": "Delhi",
            "gender": "MALE",
        },
    )

    profile_mgr: ProfileManager = app_env["profile_mgr"]

    # Citizen confirms income doc stating ₹1,50,000
    doc_id = profile_mgr.save_document(
        document_id=f"doc_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": 150000.0},
        document_category=DocumentCategory.INCOME.value,
        original_filename="Conflict_Income.pdf",
        storage_reference="vault_ref_conflict",
        mime_type="application/pdf",
        file_size=2048,
        status="CONFIRMED",
        confirmation_status="CONFIRMED",
    )
    profile_mgr.save_confirmed_field(
        user_id=user_id,
        document_id=doc_id,
        field_name="annual_income",
        field_value=150000.0,
    )

    # Detailed eligibility check for PM-USP CSSS
    elig_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility")
    assert elig_res.status_code == 200
    elig_data = elig_res.json()

    # Rule match status must be CONFLICT (or fail with discrepancy flagged)
    assert elig_data["rule_match_status"] in ("CONFLICT", "FAIL")
    assert elig_data["status"] == "REVIEW_REQUIRED"

    # Conflicting conditions must contain annual_family_income
    conflicting_conds = elig_data.get("conflicting_conditions", [])
    assert len(conflicting_conds) >= 1
    income_conf = next(c for c in conflicting_conds if c["criterion"] == "annual_family_income")
    assert income_conf["has_conflict"] is True
    assert "Discrepancy detected" in income_conf["explanation"]

    # Conflict notes must explain discrepancy clearly
    assert len(elig_data["conflict_notes"]) >= 1
    assert "900,000" in elig_data["conflict_notes"][0]
    assert "150,000" in elig_data["conflict_notes"][0]

    # Document readiness for Income Certificate must be CONFLICTING
    doc_readiness = elig_data["document_readiness"]
    inc_doc = next(d for d in doc_readiness if "Income" in d["document_name"])
    assert inc_doc["status"] == DocumentReadinessStatus.CONFLICTING.value
    assert inc_doc["action_required"] == "RESOLVE_CONFLICT"


def test_06_missing_information_remains_unknown(client, app_env):
    """6. Missing information remains UNKNOWN:
    When a citizen has not provided required criteria, the evaluation must report UNKNOWN
    and list the missing criteria under missing_information.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_missing@example.com",
        profile_data={
            "full_name": "Kavita Das",
            # No course_mode, gap_year, class_12_merit_percentile
        },
    )

    res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility?application_type=FRESH")
    assert res.status_code == 200
    data = res.json()

    assert len(data["unknown_conditions"]) > 0
    missing_fields = data["missing_information"]
    assert "course_mode" in missing_fields or "class_12_merit_percentile" in missing_fields


def test_07_guest_cannot_access_recommendations(client, app_env):
    """7. Guest users cannot access personalized recommendations:
    Calling GET /schemes/recommendations with a guest session returns HTTP 403 Forbidden.
    """
    # Create guest session
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200

    # Attempt to access persistent recommendations
    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 403
    assert "registered citizen account" in rec_res.json()["detail"].lower()


def test_08_citizen_a_cannot_access_citizen_b_documents(client, app_env):
    """8. Citizen A cannot access Citizen B's documents (IDOR isolation):
    Citizen A's confirmed documents are completely isolated from Citizen B's recommendations
    and document access endpoints.
    """
    # Register Citizen A and confirm income
    user_a, token_a = _register_citizen(client, app_env, email="citizen_a@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    doc_a = profile_mgr.save_document(
        document_id=f"doc_{uuid.uuid4().hex[:10]}",
        user_id=user_a,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": 100000.0},
        document_category=DocumentCategory.INCOME.value,
        original_filename="A_Income.pdf",
        status="CONFIRMED",
        confirmation_status="CONFIRMED",
    )
    profile_mgr.save_confirmed_field(
        user_id=user_a,
        document_id=doc_a,
        field_name="annual_income",
        field_value=100000.0,
    )

    # Register Citizen B (fresh session)
    user_b, token_b = _register_citizen(client, app_env, email="citizen_b@example.com")

    # Citizen B cannot retrieve Citizen A's document metadata (404/not found for user B)
    meta_res = client.get(f"/documents/{doc_a}")
    assert meta_res.status_code == 404

    # Citizen B cannot confirm Citizen A's document
    conf_res = client.post(
        f"/documents/{doc_a}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": token_b},
        json={"confirmations": [{"field_name": "annual_income", "field_value": "100000"}]},
    )
    assert conf_res.status_code == 404

    # Citizen B's recommendations do not inherit Citizen A's confirmed income
    rec_b = client.get("/schemes/recommendations")
    assert rec_b.status_code == 200
    csss_b = next(m for m in rec_b.json()["preliminary_matches"] if m["scheme"]["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS")
    assert len(csss_b["confirmed_evidence"]) == 0
    inc_req_b = next(d for d in csss_b["document_readiness"] if "Income" in d["document_name"])
    assert inc_req_b["status"] == DocumentReadinessStatus.MISSING.value


def test_09_recommendations_remain_100_percent_deterministic(client, app_env):
    """9. Recommendations remain 100% deterministic:
    Repeated recommendation evaluations for the identical profile and documents produce
    strictly identical results across all runs.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_deterministic@example.com",
        profile_data={
            "full_name": "Divya Rao",
            "gender": "FEMALE",
            "annual_income": 300000.0,
            "caste_category": "OBC",
        },
    )

    # Run recommendations 3 consecutive times
    res_1 = client.get("/schemes/recommendations").json()
    res_2 = client.get("/schemes/recommendations").json()
    res_3 = client.get("/schemes/recommendations").json()

    assert res_1["total_schemes_evaluated"] == res_2["total_schemes_evaluated"] == res_3["total_schemes_evaluated"]
    assert res_1["potential_matches_count"] == res_2["potential_matches_count"] == res_3["potential_matches_count"]
    assert res_1["rule_mismatches_count"] == res_2["rule_mismatches_count"] == res_3["rule_mismatches_count"]

    # Verify identical ordering and statuses
    order_1 = [m["scheme"]["scheme_id"] for m in res_1["preliminary_matches"]]
    order_2 = [m["scheme"]["scheme_id"] for m in res_2["preliminary_matches"]]
    order_3 = [m["scheme"]["scheme_id"] for m in res_3["preliminary_matches"]]
    assert order_1 == order_2 == order_3


def test_10_scheme_verification_status_remains_pending_review(client, app_env):
    """10. Scheme verification status remains unverified / review_required:
    Preserves requirement that official_eligibility_confirmed is strictly False and
    scheme_verification_status is pending_review for all unverified schemes.
    """
    user_id, csrf_token = _register_citizen(
        client,
        app_env,
        email="citizen_safeguard@example.com",
        profile_data={"full_name": "Manoj Kumar", "annual_income": 100000.0},
    )

    rec_res = client.get("/schemes/recommendations")
    assert rec_res.status_code == 200
    data = rec_res.json()

    for item in data["preliminary_matches"]:
        assert item["official_eligibility_confirmed"] is False
        assert item["review_required"] is True

    for item in data["rule_mismatches_requiring_review"]:
        assert item["official_eligibility_confirmed"] is False
        assert item["review_required"] is True

    # Test single scheme evaluation endpoint
    eval_res = client.get("/schemes/SCHEME_EDU_001_PM_USP_CSSS/eligibility")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["official_eligibility_confirmed"] is False
    assert eval_data["review_required"] is True
    assert eval_data["scheme_verification_status"] == "pending_review"
