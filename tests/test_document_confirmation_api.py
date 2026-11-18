"""Integration and security test suite for SahayAI Document Confirmation & Persistence API (Step 5.3A).

Validates:
1. Registered citizen can review their own pending document extraction results (GET /documents/{id}/review).
2. Guest users cannot persist document fields or review stored documents (HTTP 403 Forbidden).
3. Citizen can correct an extracted field; confirmation records is_corrected=True.
4. Only explicitly confirmed fields are saved to database and profile.
5. Unconfirmed fields are omitted from persistence.
6. Invalid field names and malformed formats are rejected with HTTP 400.
7. Another user cannot access or confirm a document (strict IDOR protection - HTTP 404).
8. Missing or invalid CSRF token is rejected on mutating confirmation (HTTP 403).
9. Sensitive fields (Aadhaar, PAN) require encryption and fail closed if key is missing/unconfigured.
10. Existing profile values are not silently overwritten without explicit citizen approval (HTTP 409 Conflict).
11. Government verification status remains strictly False (is_government_verified: False).
12. Confirmation timestamps and source document IDs are recorded and retrievable via GET /profile/confirmed-document-fields.
13. Confirmed fields update the citizen profile accessible via GET /profile/me.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app
from document_ai.extract_fields import AUTHENTICITY_DISCLAIMER, PIIVault
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_doc_confirm.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def confirm_env(test_db, monkeypatch):
    """Configures isolated auth, profile, and document services for FastAPI testing."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "session_mgr": session_mgr,
        "profiles": profiles,
    }


@pytest.fixture
def client(confirm_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def init_guest(client):
    """Initializes a guest session and returns cookies and CSRF token."""
    res = client.post("/auth/guest")
    assert res.status_code == 200
    data = res.json()
    return data["guest_id"], data["csrf_token"]


def signup_citizen(client, email="citizen@example.com", password="Password@123"):
    """Registers and logs in a citizen, returning user_id and CSRF token."""
    signup_res = client.post(
        "/auth/signup",
        json={"email": email, "password": password},
    )
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]
    return user_id, csrf_token


def upload_synthetic_doc(client, csrf_token, file_name="sample_synthetic_aadhaar.png", mime="image/png"):
    """Uploads a synthetic document and returns response JSON."""
    sample_path = Path("data/sample_documents") / file_name
    if not sample_path.exists():
        pytest.skip(f"{file_name} not found")

    res = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": (file_name, sample_path.read_bytes(), mime)},
    )
    assert res.status_code == 200
    return res.json()


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_01_registered_user_reviews_own_document(client):
    """Registered citizen reviews their own uploaded document extraction results."""
    user_id, csrf_token = signup_citizen(client, "reviewer@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    response = client.get(
        f"/documents/{doc_id}/review",
        headers={"Origin": "http://localhost:5500"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["document_id"] == doc_id
    assert data["document_type"] == "AADHAAR_CARD"
    assert "extracted_fields" in data
    assert "date_of_birth" in data["extracted_fields"]
    assert "aadhaar_number" in data["extracted_fields"]
    assert data["status"] == "PENDING_REVIEW"
    assert "needs_user_confirmation" in data
    assert data["authenticity_disclaimer"] == AUTHENTICITY_DISCLAIMER


def test_02_guest_cannot_review_or_persist_documents(client):
    """Guest session cannot access document review or confirmation endpoints."""
    # 1. Guest uploads a document
    guest_id, csrf_token = init_guest(client)
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # 2. Guest attempts to review -> 403 Forbidden
    rev_res = client.get(
        f"/documents/{doc_id}/review",
        headers={"Origin": "http://localhost:5500"},
    )
    assert rev_res.status_code == 403
    assert "registered citizen account" in rev_res.json()["detail"]

    # 3. Guest attempts to confirm -> 403 Forbidden
    conf_res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmations": [
                {"field_name": "date_of_birth", "value": "1990-01-01", "confirmed": True}
            ]
        },
    )
    assert conf_res.status_code == 403

    # 4. Guest attempts to view confirmed fields -> 403 Forbidden
    list_res = client.get(
        "/profile/confirmed-document-fields",
        headers={"Origin": "http://localhost:5500"},
    )
    assert list_res.status_code == 403


def test_03_citizen_corrects_extracted_field(client):
    """Citizen can correct inaccurate extracted value, marking is_corrected=True."""
    user_id, csrf_token = signup_citizen(client, "corrector@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # Extracted DOB from synthetic aadhaar is 1988-05-12. Citizen corrects it to 1988-05-15.
    conf_payload = {
        "confirmations": [
            {
                "field_name": "date_of_birth",
                "confirmed_value": "1988-05-15",
                "confirmed": True,
            }
        ]
    }

    res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json=conf_payload,
    )
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    assert "date_of_birth" in data["confirmed_fields"]
    dob_field = data["confirmed_fields"]["date_of_birth"]
    assert dob_field["value"] == "1988-05-15"
    assert dob_field["is_corrected"] is True
    assert dob_field["is_confirmed"] is True
    assert dob_field["is_government_verified"] is False
    assert data["profile"]["date_of_birth"] == "1988-05-15"


def test_04_only_explicitly_confirmed_fields_are_saved(client, confirm_env):
    """Unconfirmed fields are omitted; only confirmed fields are persisted."""
    user_id, csrf_token = signup_citizen(client, "selective@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # Document extracted both date_of_birth and gender and aadhaar_number.
    # Citizen confirms only gender and explicitly sets date_of_birth confirmed=False.
    conf_payload = {
        "confirmations": [
            {
                "field_name": "gender",
                "confirmed_value": "MALE",
                "confirmed": True,
            },
            {
                "field_name": "date_of_birth",
                "confirmed_value": "1988-05-12",
                "confirmed": False,
            },
        ]
    }

    res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json=conf_payload,
    )
    assert res.status_code == 200
    data = res.json()

    assert "gender" in data["confirmed_fields"]
    assert "date_of_birth" not in data["confirmed_fields"]
    assert "date_of_birth" in data["unconfirmed_fields"]

    # Verify database state
    confirmed_db = confirm_env["profiles"].get_confirmed_fields_by_user(user_id)
    saved_field_names = {f["field_name"] for f in confirmed_db}
    assert "gender" in saved_field_names
    assert "date_of_birth" not in saved_field_names

    # Profile should only contain confirmed attributes
    profile = confirm_env["profiles"].get_profile_by_user_id(user_id)
    assert profile["gender"] == "MALE"
    assert profile["date_of_birth"] is None


def test_05_unknown_and_invalid_fields_rejected(client):
    """Unsupported field names and invalid formats are rejected with HTTP 400."""
    user_id, csrf_token = signup_citizen(client, "validation@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # 1. Unsupported field name
    res_bad_name = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"confirmed_fields": {"credit_score": 750}},
    )
    assert res_bad_name.status_code == 400
    assert "Unsupported or unknown field name" in res_bad_name.json()["detail"]

    # 2. Invalid date format
    res_bad_date = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"confirmed_fields": {"date_of_birth": "12-05-1988"}},
    )
    assert res_bad_date.status_code == 400
    assert "YYYY-MM-DD" in res_bad_date.json()["detail"]

    # 3. Future date of birth
    res_future_dob = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"confirmed_fields": {"date_of_birth": "2099-01-01"}},
    )
    assert res_future_dob.status_code == 400
    assert "future" in res_future_dob.json()["detail"]

    # 4. Invalid gender
    res_bad_gender = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"confirmed_fields": {"gender": "ROBOT"}},
    )
    assert res_bad_gender.status_code == 400

    # 5. Negative income
    res_neg_income = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"confirmed_fields": {"annual_income": -5000}},
    )
    assert res_neg_income.status_code == 400


def test_06_idor_defense_another_user_cannot_access_or_confirm(client):
    """User B cannot view or confirm User A's document (returns HTTP 404)."""
    # User A uploads document
    user_a_id, csrf_a = signup_citizen(client, "usera@example.com")
    upload_data = upload_synthetic_doc(client, csrf_a)
    doc_id = upload_data["document_id"]

    # User B logs in
    user_b_id, csrf_b = signup_citizen(client, "userb@example.com")

    # User B attempts to review User A's document
    res_review = client.get(
        f"/documents/{doc_id}/review",
        headers={"Origin": "http://localhost:5500"},
    )
    assert res_review.status_code == 404

    # User B attempts to confirm User A's document
    res_confirm = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_b},
        json={"confirmed_fields": {"date_of_birth": "1988-05-12"}},
    )
    assert res_confirm.status_code == 404


def test_07_csrf_protection_strictly_enforced_on_confirm(client):
    """Mutating confirmation endpoint requires valid X-CSRF-Token."""
    user_id, csrf_token = signup_citizen(client, "csrf_victim@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # Missing CSRF header
    res_no_csrf = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500"},
        json={"confirmed_fields": {"gender": "MALE"}},
    )
    assert res_no_csrf.status_code == 403

    # Invalid CSRF header
    res_bad_csrf = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": "bad_token"},
        json={"confirmed_fields": {"gender": "MALE"}},
    )
    assert res_bad_csrf.status_code == 403


def test_08_existing_profile_values_not_silently_overwritten(client):
    """Differing existing profile value requires explicit allow_overwrite=True; returns 409 Conflict if False."""
    user_id, csrf_token = signup_citizen(client, "overwrite_test@example.com")

    # 1. Citizen creates an initial profile with DOB = 1990-01-01
    init_res = client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Test Citizen",
            "date_of_birth": "1990-01-01",
            "gender": "MALE",
            "state": "Maharashtra",
            "district": "Pune",
            "annual_income": 150000.0,
            "occupation": "Student",
            "caste_category": "GENERAL",
            "is_bpl": False,
        },
    )
    assert init_res.status_code == 200

    # 2. Upload document with extracted DOB = 1988-05-12
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # 3. Check review endpoint flags conflict
    review_res = client.get(
        f"/documents/{doc_id}/review",
        headers={"Origin": "http://localhost:5500"},
    )
    assert review_res.status_code == 200
    conflicts = review_res.json()["existing_profile_conflicts"]
    assert "date_of_birth" in conflicts
    assert conflicts["date_of_birth"]["requires_overwrite_approval"] is True

    # 4. Attempt to confirm differing value without allow_overwrite -> 409 Conflict
    conflict_res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmed_fields": {"date_of_birth": "1988-05-12"},
            "allow_overwrite": False,
        },
    )
    assert conflict_res.status_code == 409
    assert "differs from confirmed value" in conflict_res.json()["detail"]

    # 5. Provide explicit allow_overwrite=True -> succeeds and updates profile
    success_res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmed_fields": {"date_of_birth": "1988-05-12"},
            "allow_overwrite": True,
        },
    )
    assert success_res.status_code == 200
    assert success_res.json()["profile"]["date_of_birth"] == "1988-05-12"


def test_09_pii_encryption_failure_fails_closed(client, monkeypatch):
    """Confirming sensitive identifier fails closed (HTTP 500) if encryption key is unavailable."""
    user_id, csrf_token = signup_citizen(client, "pii_fail@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # Simulate environment where encryption key is unconfigured
    monkeypatch.delenv("SAHAY_PII_ENCRYPTION_KEY", raising=False)

    res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmed_fields": {"aadhaar_number": "9999 8888 7777"}
        },
    )
    assert res.status_code == 500
    assert "PII encryption is required" in res.json()["detail"]


def test_10_government_verification_status_remains_false(client):
    """Government verification status is strictly False across all confirmation artifacts."""
    user_id, csrf_token = signup_citizen(client, "gov_verify@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    res = client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmed_fields": {"gender": "MALE"}
        },
    )
    assert res.status_code == 200
    field_record = res.json()["confirmed_fields"]["gender"]
    assert field_record["is_government_verified"] is False


def test_11_get_confirmed_document_fields_returns_audit_metadata(client):
    """GET /profile/confirmed-document-fields returns all confirmed fields with full audit trail."""
    user_id, csrf_token = signup_citizen(client, "audit_user@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # Confirm fields
    client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmations": [
                {"field_name": "gender", "confirmed_value": "MALE", "confirmed": True},
                {"field_name": "date_of_birth", "confirmed_value": "1988-05-15", "confirmed": True},
            ]
        },
    )

    # Retrieve confirmed fields list
    res = client.get(
        "/profile/confirmed-document-fields",
        headers={"Origin": "http://localhost:5500"},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    assert data["total_confirmed_fields"] == 2
    assert data["authenticity_disclaimer"] == AUTHENTICITY_DISCLAIMER

    field_map = {f["field_name"]: f for f in data["confirmed_fields"]}
    assert "gender" in field_map
    assert "date_of_birth" in field_map

    # Check audit fields
    dob = field_map["date_of_birth"]
    assert dob["field_value"] == "1988-05-15"
    assert dob["source_document_id"] == doc_id
    assert dob["is_confirmed"] is True
    assert dob["is_corrected"] is True  # extracted was 1988-05-12
    assert dob["is_government_verified"] is False
    assert dob["confirmation_status"] == "CONFIRMED"
    assert "confirmed_at" in dob


def test_12_confirmed_fields_reflected_in_profile_me(client):
    """Confirmed document fields are accessible through GET /profile/me."""
    user_id, csrf_token = signup_citizen(client, "profile_me_check@example.com")
    upload_data = upload_synthetic_doc(client, csrf_token)
    doc_id = upload_data["document_id"]

    # Confirm fields before creating profile manually
    client.post(
        f"/documents/{doc_id}/confirm",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "confirmed_fields": {
                "date_of_birth": "1994-08-25",
                "gender": "FEMALE",
            }
        },
    )

    # Retrieve profile
    res = client.get("/profile/me")
    assert res.status_code == 200
    profile = res.json()["profile"]

    assert profile["date_of_birth"] == "1994-08-25"
    assert profile["gender"] == "FEMALE"
    assert profile["age"] >= 30  # calculated automatically
    assert profile["user_confirmed"] is True

