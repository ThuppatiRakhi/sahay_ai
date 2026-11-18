"""Integration and security test suite for SahayAI Document Upload API (Step 5.2).

Validates:
1. Valid PNG upload (synthetic Aadhaar) succeeds for guest user (HTTP 200).
2. Valid PDF upload (synthetic Income Certificate) succeeds for registered citizen (HTTP 200).
3. Valid PAN card PNG upload returns masked PAN (HTTP 200).
4. Unsupported file extension (.exe, .txt, .sh) is rejected (HTTP 415).
5. Mismatched magic bytes (disguised file like .png with text or exe) is rejected (HTTP 415).
6. File exceeding 5 MB limit is rejected (HTTP 413).
7. Empty file (0 bytes) is rejected (HTTP 400).
8. Corrupted / malformed image is rejected without stack trace (HTTP 400).
9. Poor quality image failing quality gate is rejected (HTTP 422).
10. Path traversal attempt in filename is safely neutralized.
11. Unauthenticated request without session cookie is rejected (HTTP 401).
12. Request with missing or invalid CSRF token is rejected (HTTP 403).
13. Temporary file cleanup is guaranteed in finally block across all scenarios.
14. No automatic persistence to citizen profiles occurs.
15. PIIVault hardening: Fernet key requirement, fail-closed on missing key, legacy ENC_ decoding, no Base64 fallback.
"""

from io import BytesIO
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.documents import TEMP_UPLOAD_DIR, validate_magic_bytes
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
    db_file = tmp_path / "test_doc_api.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def doc_env(test_db, monkeypatch):
    """Configures isolated auth and session services for FastAPI testing."""
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
def client(doc_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def init_guest(client):
    """Initializes a guest session and returns cookies and CSRF token."""
    res = client.post("/auth/guest")
    assert res.status_code == 200
    data = res.json()
    return data["guest_id"], data["csrf_token"]


def signup_citizen(client, email="doc_citizen@example.com", password="Password@123"):
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_01_guest_uploads_synthetic_aadhaar_png(client):
    """Guest uploads valid synthetic Aadhaar PNG and receives masked result."""
    _, csrf_token = init_guest(client)

    sample_path = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if not sample_path.exists():
        pytest.skip("sample_synthetic_aadhaar.png not found")

    content = sample_path.read_bytes()

    # Verify no leftovers prior
    files_before = set(os.listdir(TEMP_UPLOAD_DIR))

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("sample_synthetic_aadhaar.png", content, "image/png")},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["document_id"].startswith("doc_")
    assert data["detected_document_type"] == "AADHAAR_CARD"
    assert "aadhaar_number" in data["extracted_fields"]
    assert data["extracted_fields"]["aadhaar_number"]["value"] == "XXXX-XXXX-7777"
    assert data["field_confidence"] > 0.0
    assert data["processing_status"] == "SUCCESS"
    assert data["authenticity_disclaimer"] == AUTHENTICITY_DISCLAIMER

    # Temporary file cleanup verification
    files_after = set(os.listdir(TEMP_UPLOAD_DIR))
    assert files_after == files_before


def test_02_registered_citizen_uploads_synthetic_income_pdf(client):
    """Registered citizen uploads synthetic income certificate PDF."""
    _, csrf_token = signup_citizen(client)

    sample_path = Path("data/sample_documents/sample_synthetic_income_cert.pdf")
    if not sample_path.exists():
        pytest.skip("sample_synthetic_income_cert.pdf not found")

    content = sample_path.read_bytes()
    files_before = set(os.listdir(TEMP_UPLOAD_DIR))

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("sample_synthetic_income_cert.pdf", content, "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["detected_document_type"] == "INCOME_CERTIFICATE"
    assert "annual_income" in data["extracted_fields"]
    assert data["extracted_fields"]["annual_income"]["value"] == 150000.0
    assert data["authenticity_disclaimer"] == AUTHENTICITY_DISCLAIMER

    files_after = set(os.listdir(TEMP_UPLOAD_DIR))
    assert files_after == files_before


def test_03_pan_card_extraction(client):
    """Upload synthetic PAN card PNG and verify masking."""
    _, csrf_token = init_guest(client)

    sample_path = Path("data/sample_documents/sample_synthetic_pan.png")
    if not sample_path.exists():
        pytest.skip("sample_synthetic_pan.png not found")

    content = sample_path.read_bytes()

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("sample_synthetic_pan.png", content, "image/png")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["detected_document_type"] == "PAN_CARD"
    assert "pan_number" in data["extracted_fields"]
    assert data["extracted_fields"]["pan_number"]["value"] == "XXXXX1234X"


def test_04_unsupported_file_extension(client):
    """Upload with unsupported extension (.exe, .txt, .sh) is rejected with 415."""
    _, csrf_token = init_guest(client)

    for bad_ext in ["payload.exe", "data.txt", "run.sh", "notes.docx"]:
        response = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
            files={"file": (bad_ext, b"test content bytes", "text/plain")},
        )
        assert response.status_code == 415
        assert "Unsupported file extension" in response.json()["detail"]


def test_05_magic_bytes_mismatch_rejected(client):
    """File named .png but containing plain text or executable bytes is rejected with 415."""
    _, csrf_token = init_guest(client)
    files_before = set(os.listdir(TEMP_UPLOAD_DIR))

    fake_png_data = b"Plain text disguised as PNG image file."

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("disguised.png", fake_png_data, "image/png")},
    )

    assert response.status_code == 415
    assert "File signature does not match" in response.json()["detail"]
    assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before


def test_06_file_exceeding_5mb_rejected(client):
    """File larger than 5 MB is rejected with 413 Payload Too Large."""
    _, csrf_token = init_guest(client)
    files_before = set(os.listdir(TEMP_UPLOAD_DIR))

    # 5.5 MB payload (5.5 * 1024 * 1024 = 5,767,168 bytes)
    # Start with valid PNG magic bytes so it reaches the size check
    oversized_data = b"\x89PNG\r\n\x1a\n" + (b"A" * (5500 * 1024))

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("oversized.png", oversized_data, "image/png")},
    )

    assert response.status_code == 413
    assert "exceeds the 5 MB limit" in response.json()["detail"]
    # Guaranteed cleanup
    assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before


def test_07_empty_file_rejected(client):
    """Empty 0-byte file is rejected with 400 Bad Request."""
    _, csrf_token = init_guest(client)

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("empty.png", b"", "image/png")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_08_corrupted_image_handling(client):
    """Valid PNG header followed by malformed image data is handled safely with 400."""
    _, csrf_token = init_guest(client)
    files_before = set(os.listdir(TEMP_UPLOAD_DIR))

    corrupt_png = b"\x89PNG\r\n\x1a\n" + b"Corrupted garbage data not a real PNG image"

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("corrupt.png", corrupt_png, "image/png")},
    )

    assert response.status_code == 400
    assert "corrupted" in response.json()["detail"].lower()
    assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before


def test_08_b_poor_quality_image_rejected_with_422(client):
    """Low resolution image failing quality gate is rejected with HTTP 422."""
    from PIL import Image

    _, csrf_token = init_guest(client)
    files_before = set(os.listdir(TEMP_UPLOAD_DIR))

    # Create a tiny 100x100 valid PNG image (fails minimum 400x400 gate)
    img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    tiny_png_bytes = buf.getvalue()

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("tiny.png", tiny_png_bytes, "image/png")},
    )

    assert response.status_code == 422
    assert "quality check failed" in response.json()["detail"].lower()
    assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before


def test_09_path_traversal_neutralized(client):
    """Path traversal sequence in filename is ignored; file is stored safely."""
    _, csrf_token = init_guest(client)

    sample_path = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if not sample_path.exists():
        pytest.skip("sample_synthetic_aadhaar.png not found")

    content = sample_path.read_bytes()
    malicious_filename = "../../../../Windows/System32/malicious.png"

    response = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": (malicious_filename, content, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_10_unauthenticated_request_rejected(client):
    """Uploading without an active session cookie returns 401 Unauthorized."""
    response = client.post(
        "/documents/upload",
        files={"file": ("test.png", b"\x89PNG\r\n\x1a\n1234", "image/png")},
    )
    assert response.status_code == 401


def test_11_missing_or_invalid_csrf_token_rejected(client):
    """Uploading with missing or invalid CSRF token returns 403 Forbidden."""
    init_guest(client)  # sets cookie

    # Missing CSRF header
    res_no_csrf = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500"},
        files={"file": ("test.png", b"\x89PNG\r\n\x1a\n1234", "image/png")},
    )
    assert res_no_csrf.status_code == 403

    # Invalid CSRF header
    res_bad_csrf = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": "invalid_csrf_token"},
        files={"file": ("test.png", b"\x89PNG\r\n\x1a\n1234", "image/png")},
    )
    assert res_bad_csrf.status_code == 403


def test_12_no_auto_save_to_citizen_profiles(client, doc_env):
    """Processing a document must NEVER auto-save to citizen profiles."""
    user_id, csrf_token = signup_citizen(client)

    sample_path = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if not sample_path.exists():
        pytest.skip("sample_synthetic_aadhaar.png not found")

    res = client.post(
        "/documents/upload",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        files={"file": ("aadhaar.png", sample_path.read_bytes(), "image/png")},
    )
    assert res.status_code == 200

    # Verify database profile was NOT created / populated
    profile = doc_env["profiles"].get_profile(user_id)
    assert profile is None


def test_13_magic_bytes_validator_unit():
    """Unit test for validate_magic_bytes helper function."""
    assert validate_magic_bytes(b"%PDF-1.4\n") == "pdf"
    assert validate_magic_bytes(b"\x89PNG\r\n\x1a\n\x00") == "png"
    assert validate_magic_bytes(b"\xff\xd8\xff\xe0") == "jpeg"
    assert validate_magic_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8") == "webp"

    assert validate_magic_bytes(b"MZ\x90\x00") is None  # EXE
    assert validate_magic_bytes(b"PK\x03\x04") is None  # ZIP
    assert validate_magic_bytes(b"Hello world") is None  # Text
    assert validate_magic_bytes(b"") is None


def test_14_pii_vault_hardened_security(monkeypatch):
    """Verify PIIVault security hardening.
    
    Checks:
    - Genuine Fernet encryption.
    - Never generates Base64 ENC_ fallback during encryption.
    - Fails closed when key is missing (raises RuntimeError).
    - Rejects invalid keys on init (raises ValueError).
    - Preserves backward compatibility by reading legacy ENC_ records in decrypt.
    """
    from cryptography.fernet import Fernet
    valid_key = Fernet.generate_key().decode()

    # 1. Normal Fernet encryption and decryption
    vault = PIIVault(encryption_key=valid_key)
    assert vault.is_configured is True

    raw_aadhaar = "9999 8888 7777"
    enc = vault.encrypt(raw_aadhaar)
    assert not enc.startswith("ENC_")
    assert raw_aadhaar not in enc
    assert vault.decrypt(enc) == raw_aadhaar

    # 2. Legacy ENC_ backward compatibility
    import base64
    legacy_ciphertext = f"ENC_{base64.b64encode(raw_aadhaar.encode()).decode()}"
    assert vault.decrypt(legacy_ciphertext) == raw_aadhaar

    # 3. Fail closed when key is missing
    monkeypatch.delenv("SAHAY_PII_ENCRYPTION_KEY", raising=False)
    unconfigured_vault = PIIVault(encryption_key=None)
    assert unconfigured_vault.is_configured is False

    with pytest.raises(RuntimeError, match="persistent SAHAY_PII_ENCRYPTION_KEY is not configured"):
        unconfigured_vault.encrypt(raw_aadhaar)

    # Legacy decrypt still works without key for data migration
    assert unconfigured_vault.decrypt(legacy_ciphertext) == raw_aadhaar

    # 4. Invalid key raises ValueError
    with pytest.raises(ValueError, match="Invalid SAHAY_PII_ENCRYPTION_KEY"):
        PIIVault(encryption_key="not-a-valid-fernet-key")
