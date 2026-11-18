"""Tests for SahayAI Step 5.4B.1: Integration Verification and Upload Policy.

Covers:
1. Exact upload limit enforcement:
   - PDF: <= 10 MB (10,485,760 bytes) accepted; > 10 MB (10,485,761 bytes) rejected with 413.
   - Images (PNG, JPEG, WEBP): <= 5 MB (5,242,880 bytes) accepted; > 5 MB (5,242,881 bytes) rejected with 413.
2. Temporary file cleanup guarantees on failed uploads.
3. Replace endpoint upload limit enforcement.
4. Category normalization & alias consistency (APPLICATION_ASSISTANCE, APPLICATION_ASSETS -> APPLICATION_ASSET).
5. Deletion API contracts: hard_delete=false (archive), hard_delete=true (permanent cascade), purge=true alias.
6. Encryption claims audit: no unsupported "AES-256" claims in frontend/locales.
7. Frontend static HTML, JS limits, and localization parity for limit strings.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient

from api.documents import (
    ALLOWED_EXTENSIONS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_PDF_SIZE_BYTES,
    TEMP_UPLOAD_DIR,
    get_max_upload_size,
)
from api.main import app
from document_ai.categories import (
    DocumentCategory,
    VALID_DOCUMENT_CATEGORIES,
    normalize_document_category,
    get_category_for_type,
)
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
LOCALES_DIR = os.path.join(FRONTEND_DIR, "locales")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_upload_policy.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def app_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth service, profile manager, and vault directory."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
        "vault_dir": vault_dir,
    }


@pytest.fixture
def client(app_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _init_guest(client):
    res = client.post("/auth/guest")
    assert res.status_code == 200
    data = res.json()
    return data["guest_id"], data["csrf_token"]


def _init_citizen(client, email="policy_citizen@example.com", password="Password@123"):
    signup_res = client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]

    client.post(
        "/profile/me",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={
            "full_name": "Policy Citizen",
            "date_of_birth": "2000-01-01",
            "gender": "FEMALE",
            "caste_category": "GENERAL",
            "state": "Telangana",
            "district": "Hyderabad",
            "annual_income": 120000.0,
            "occupation": "Student",
            "is_bpl": False,
        },
    )
    return user_id, csrf_token


def _get_real_sample_pdf():
    p = Path("data/sample_documents/sample_synthetic_income_cert.pdf")
    if p.exists():
        return p.read_bytes()
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 1\n0000000000 65535 f \ntrailer<</Size 1/Root 1 0 R>>\nstartxref\n34\n%%EOF\n"


def _get_real_sample_png():
    p = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if p.exists():
        return p.read_bytes()
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


# ---------------------------------------------------------------------------
# 1. Standardized Upload Limits Tests (PDF: 10 MB, Images: 5 MB)
# ---------------------------------------------------------------------------

class TestStandardizedUploadLimits:
    """Tests file size limits: below, exactly at, and above each limit."""

    def test_constants_match_exact_specification(self):
        """Verify byte constants match 10 MB for PDF and 5 MB for images."""
        assert MAX_PDF_SIZE_BYTES == 10 * 1024 * 1024
        assert MAX_PDF_SIZE_BYTES == 10_485_760
        assert MAX_IMAGE_SIZE_BYTES == 5 * 1024 * 1024
        assert MAX_IMAGE_SIZE_BYTES == 5_242_880

        assert get_max_upload_size(".pdf") == 10 * 1024 * 1024
        assert get_max_upload_size(".png") == 5 * 1024 * 1024
        assert get_max_upload_size(".jpg") == 5 * 1024 * 1024
        assert get_max_upload_size(".jpeg") == 5 * 1024 * 1024
        assert get_max_upload_size(".webp") == 5 * 1024 * 1024

    def test_pdf_below_limit_accepted(self, client):
        """A valid PDF well below 10 MB is accepted."""
        _, csrf = _init_guest(client)
        content = _get_real_sample_pdf()

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("sample.pdf", content, "application/pdf")},
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

    def test_pdf_exactly_at_10mb_accepted_by_size_gate(self, client):
        """A PDF file of exactly 10,485,760 bytes passes the size gate (not 413)."""
        _, csrf = _init_guest(client)
        base = _get_real_sample_pdf()
        target_size = 10 * 1024 * 1024  # 10,485,760 bytes
        pad_needed = target_size - len(base)
        assert pad_needed > 0
        # Pad with trailing comment characters after %%EOF
        padded_pdf = base + (b"% padding\n" + b"%" + b"X" * (pad_needed - 11))
        assert len(padded_pdf) == target_size

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("exact_10mb.pdf", padded_pdf, "application/pdf")},
        )
        # Crucial check: Size gate must NOT reject with 413
        assert res.status_code != 413
        assert res.status_code in (200, 400, 422)

    def test_pdf_above_10mb_rejected_with_413(self, client):
        """A PDF file of 10,485,761 bytes (10 MB + 1 byte) is rejected with 413."""
        _, csrf = _init_guest(client)
        files_before = set(os.listdir(TEMP_UPLOAD_DIR))

        header = b"%PDF-1.4\n"
        oversized_pdf = header + b"X" * (10 * 1024 * 1024 - len(header) + 1)
        assert len(oversized_pdf) == 10 * 1024 * 1024 + 1

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("oversized.pdf", oversized_pdf, "application/pdf")},
        )
        assert res.status_code == 413
        detail = res.json()["detail"]
        assert "exceeds the 10 MB limit for PDF" in detail

        # Temporary file must be cleaned up
        assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before

    def test_png_below_limit_accepted(self, client):
        """A valid PNG below 5 MB is accepted."""
        _, csrf = _init_guest(client)
        content = _get_real_sample_png()

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("sample.png", content, "image/png")},
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

    def test_png_exactly_at_5mb_passes_size_gate(self, client):
        """A PNG file of exactly 5,242,880 bytes passes the size gate (not 413)."""
        _, csrf = _init_guest(client)
        target_size = 5 * 1024 * 1024  # 5,242,880 bytes
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (target_size - 8)
        assert len(payload) == target_size

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("exact_5mb.png", payload, "image/png")},
        )
        assert res.status_code != 413

    def test_png_above_5mb_rejected_with_413(self, client):
        """A PNG file of 5,242,881 bytes (5 MB + 1 byte) is rejected with 413."""
        _, csrf = _init_guest(client)
        files_before = set(os.listdir(TEMP_UPLOAD_DIR))

        oversized_png = b"\x89PNG\r\n\x1a\n" + b"P" * (5 * 1024 * 1024 - 8 + 1)
        assert len(oversized_png) == 5 * 1024 * 1024 + 1

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("oversized.png", oversized_png, "image/png")},
        )
        assert res.status_code == 413
        detail = res.json()["detail"]
        assert "exceeds the 5 MB limit for PNG" in detail
        assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before

    def test_jpeg_limits(self, client):
        """JPEG: exactly 5 MB passes size gate, 5 MB + 1 byte rejected with 413."""
        _, csrf = _init_guest(client)
        files_before = set(os.listdir(TEMP_UPLOAD_DIR))

        # Exactly 5 MB
        exact_5mb = b"\xff\xd8\xff" + b"J" * (5 * 1024 * 1024 - 3)
        res_ok = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("exact_5mb.jpg", exact_5mb, "image/jpeg")},
        )
        assert res_ok.status_code != 413

        # Above 5 MB by 1 byte
        oversized = b"\xff\xd8\xff" + b"J" * (5 * 1024 * 1024 - 3 + 1)
        res_fail = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("oversized.jpg", oversized, "image/jpeg")},
        )
        assert res_fail.status_code == 413
        assert "exceeds the 5 MB limit for JPG" in res_fail.json()["detail"]
        assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before

    def test_webp_limits(self, client):
        """WEBP: exactly 5 MB passes size gate, 5 MB + 1 byte rejected with 413."""
        _, csrf = _init_guest(client)
        files_before = set(os.listdir(TEMP_UPLOAD_DIR))

        header = b"RIFF\x00\x00\x00\x00WEBP"
        exact_5mb = header + b"W" * (5 * 1024 * 1024 - len(header))
        res_ok = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("exact_5mb.webp", exact_5mb, "image/webp")},
        )
        assert res_ok.status_code != 413

        oversized = header + b"W" * (5 * 1024 * 1024 - len(header) + 1)
        res_fail = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("oversized.webp", oversized, "image/webp")},
        )
        assert res_fail.status_code == 413
        assert "exceeds the 5 MB limit for WEBP" in res_fail.json()["detail"]
        assert set(os.listdir(TEMP_UPLOAD_DIR)) == files_before

    def test_replace_endpoint_enforces_upload_limits(self, client):
        """Document replacement enforces 10 MB for PDF and 5 MB for images."""
        _, csrf = _init_citizen(client)
        content = _get_real_sample_png()

        upload_res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("doc.png", content, "image/png")},
        )
        assert upload_res.status_code == 200
        doc_id = upload_res.json()["document_id"]

        # 1. Replace with 10.1 MB PDF -> 413
        big_pdf = b"%PDF-1.4\n" + b"X" * (10 * 1024 * 1024 + 10)
        res_pdf = client.post(
            f"/documents/{doc_id}/replace",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("replace_big.pdf", big_pdf, "application/pdf")},
        )
        assert res_pdf.status_code == 413
        assert "exceeds the 10 MB limit for PDF" in res_pdf.json()["detail"]

        # 2. Replace with 5.1 MB PNG -> 413
        big_png = b"\x89PNG\r\n\x1a\n" + b"P" * (5 * 1024 * 1024 + 10)
        res_png = client.post(
            f"/documents/{doc_id}/replace",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("replace_big.png", big_png, "image/png")},
        )
        assert res_png.status_code == 413
        assert "exceeds the 5 MB limit for PNG" in res_png.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Category Normalization & Aliases (Requirement 5)
# ---------------------------------------------------------------------------

class TestCategoryConsistency:
    """Verifies backend categories accept standard enums and aliases."""

    def test_application_asset_aliases(self):
        """APPLICATION_ASSISTANCE and APPLICATION_ASSETS normalize to APPLICATION_ASSET."""
        assert normalize_document_category("APPLICATION_ASSET") == "APPLICATION_ASSET"
        assert normalize_document_category("APPLICATION_ASSISTANCE") == "APPLICATION_ASSET"
        assert normalize_document_category("APPLICATION_ASSETS") == "APPLICATION_ASSET"
        assert normalize_document_category("application-assistance") == "APPLICATION_ASSET"
        assert normalize_document_category("application asset") == "APPLICATION_ASSET"

    def test_all_standard_categories_valid(self):
        """Ensure all DocumentCategory enum members are valid."""
        for cat in DocumentCategory:
            assert normalize_document_category(cat.value) == cat.value

    def test_upload_with_application_assistance_alias_persists_correctly(self, client):
        """Uploading with category 'APPLICATION_ASSISTANCE' normalizes to 'APPLICATION_ASSET'."""
        _, csrf = _init_citizen(client, email="asset_citizen@example.com")
        content = _get_real_sample_png()

        res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            data={"document_category": "APPLICATION_ASSISTANCE", "document_type": "passport_photo"},
            files={"file": ("photo.png", content, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["document_category"] == "APPLICATION_ASSET"

        doc_id = data["document_id"]
        meta_res = client.get(f"/documents/{doc_id}")
        assert meta_res.status_code == 200
        assert meta_res.json()["document"]["document_category"] == "APPLICATION_ASSET"


# ---------------------------------------------------------------------------
# 3. Deletion Behavior & Cascade Policy (Requirement 3)
# ---------------------------------------------------------------------------

class TestDeletionBehavior:
    """Verifies archive vs permanent deletion contracts."""

    def test_archive_preserves_metadata_and_confirmed_fields(self, client, app_env):
        """DELETE with hard_delete=false archives document and keeps confirmation history."""
        user_id, csrf = _init_citizen(client, email="archive_test@example.com")
        content = _get_real_sample_png()

        upload_res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("doc_to_archive.png", content, "image/png")},
        )
        assert upload_res.status_code == 200
        doc_id = upload_res.json()["document_id"]

        # Confirm a field
        confirm_res = client.post(
            f"/documents/{doc_id}/confirm",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            json={
                "confirmations": [
                    {"field_name": "gender", "confirmed_value": "FEMALE", "confirmed": True, "allow_overwrite": True}
                ]
            },
        )
        assert confirm_res.status_code == 200

        # Archive (hard_delete=false)
        del_res = client.delete(
            f"/documents/{doc_id}?hard_delete=false",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
        )
        assert del_res.status_code == 200
        assert del_res.json()["hard_deleted"] is False

        # Excluded from default list
        list_active = client.get("/documents")
        active_ids = [d["document_id"] for d in list_active.json()["documents"]]
        assert doc_id not in active_ids

        # Included when include_archived=true
        list_archived = client.get("/documents?include_archived=true")
        all_ids = [d["document_id"] for d in list_archived.json()["documents"]]
        assert doc_id in all_ids

        # Metadata row still exists in database with status='ARCHIVED'
        with app_env["db"].get_connection() as conn:
            row = conn.execute("SELECT status FROM document_metadata WHERE document_id = ?", (doc_id,)).fetchone()
            assert row is not None
            assert row["status"] == "ARCHIVED"

            # Confirmation history preserved
            cf_row = conn.execute("SELECT * FROM confirmed_document_fields WHERE document_id = ?", (doc_id,)).fetchone()
            assert cf_row is not None
            assert cf_row["field_name"] == "gender"

    def test_permanent_deletion_cascades_and_removes_file(self, client, app_env):
        """DELETE with hard_delete=true cascades and unlinks encrypted vault file."""
        user_id, csrf = _init_citizen(client, email="purge_test@example.com")
        content = _get_real_sample_png()

        upload_res = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("doc_to_purge.png", content, "image/png")},
        )
        assert upload_res.status_code == 200
        doc_id = upload_res.json()["document_id"]

        # Confirm a field
        client.post(
            f"/documents/{doc_id}/confirm",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            json={
                "confirmations": [
                    {"field_name": "state", "confirmed_value": "Telangana", "confirmed": True, "allow_overwrite": True}
                ]
            },
        )

        # Retrieve vault reference
        with app_env["db"].get_connection() as conn:
            row = conn.execute("SELECT storage_reference FROM document_metadata WHERE document_id = ?", (doc_id,)).fetchone()
            storage_ref = row["storage_reference"]
            vault_file = app_env["vault_dir"] / storage_ref
            assert vault_file.exists()

        # Permanent deletion via hard_delete=true
        del_res = client.delete(
            f"/documents/{doc_id}?hard_delete=true",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
        )
        assert del_res.status_code == 200
        assert del_res.json()["hard_deleted"] is True

        # Document completely removed from DB
        with app_env["db"].get_connection() as conn:
            assert conn.execute("SELECT * FROM document_metadata WHERE document_id = ?", (doc_id,)).fetchone() is None
            # Cascade removes confirmation history
            assert conn.execute("SELECT * FROM confirmed_document_fields WHERE document_id = ?", (doc_id,)).fetchone() is None

        # Encrypted file unlinked from disk
        assert not vault_file.exists()

    def test_purge_query_parameter_alias(self, client):
        """DELETE with purge=true or purge=false query parameter works identically."""
        user_id, csrf = _init_citizen(client, email="purge_alias@example.com")
        content = _get_real_sample_png()

        # Test purge=false (archive)
        up1 = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("alias1.png", content, "image/png")},
        )
        doc_id1 = up1.json()["document_id"]
        res_arch = client.delete(
            f"/documents/{doc_id1}?purge=false",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
        )
        assert res_arch.status_code == 200
        assert res_arch.json()["hard_deleted"] is False

        # Test purge=true (hard delete)
        up2 = client.post(
            "/documents/upload",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
            files={"file": ("alias2.png", content, "image/png")},
        )
        doc_id2 = up2.json()["document_id"]
        res_del = client.delete(
            f"/documents/{doc_id2}?purge=true",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
        )
        assert res_del.status_code == 200
        assert res_del.json()["hard_deleted"] is True


# ---------------------------------------------------------------------------
# 4. Encryption Claims Verification (Requirement 4)
# ---------------------------------------------------------------------------

class TestEncryptionClaimsAudit:
    """Verifies that no unsupported 'AES-256' claims exist in frontend or user texts."""

    def test_no_aes256_claims_in_frontend_or_locales(self):
        """Neither dashboard.html, js files, nor locale files make unsupported AES-256 claims."""
        for root, _, files in os.walk(FRONTEND_DIR):
            for fname in files:
                if fname.endswith((".html", ".js", ".json")):
                    fpath = os.path.join(root, fname)
                    with open(fpath, "r", encoding="utf-8") as f:
                        text = f.read()
                    assert "AES-256" not in text, f"Found unsupported 'AES-256' claim in {fpath}"
                    assert "aes-256" not in text.lower() or "venv" in fpath, f"Found lowercase 'aes-256' in {fpath}"


# ---------------------------------------------------------------------------
# 5. Frontend Structure, UI Limits, and Localization Parity
# ---------------------------------------------------------------------------

class TestFrontendLimitsAndLocalization:
    """Verifies upload limits in HTML, JS and localization files."""

    def test_dashboard_html_contains_limit_pills(self):
        """dashboard.html displays explicit PDF and Image limit pills beside upload controls."""
        html_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'data-i18n="documents.limitPdf"' in html
        assert 'data-i18n="documents.limitImages"' in html
        assert "PDF (Max: 10 MB)" in html
        assert "Images (JPG/PNG/WEBP): up to 5 MB" in html

    def test_localization_parity_for_upload_limit_keys(self):
        """English, Telugu, and Hindi contain identical limit and error keys."""
        locales = {}
        for lang in ("en", "te", "hi"):
            p = os.path.join(LOCALES_DIR, f"{lang}.json")
            with open(p, "r", encoding="utf-8") as f:
                locales[lang] = json.load(f)

        keys_to_verify = [
            "dropzoneHint",
            "limitPdf",
            "limitImages",
            "errFileSize",
            "errPdfSize",
            "errImageSize",
            "catApplicationAsset",
            "catApplicationAssistance",
        ]

        for k in keys_to_verify:
            for lang in ("en", "te", "hi"):
                val = locales[lang].get("documents", {}).get(k)
                assert val, f"Missing key 'documents.{k}' in {lang}.json"
                assert len(val.strip()) > 0
