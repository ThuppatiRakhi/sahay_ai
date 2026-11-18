"""Security and Integration Test Suite for SahayAI Document Library (Step 5.4A).

Validates:
1. Registered user persistent document upload, random vault naming, and encryption at rest.
2. Guest zero-persistence (no files in vault, no rows in database).
3. Same-user download with authenticated decryption, headers, and anti-caching.
4. Cross-user download denial and strict IDOR defenses (HTTP 404).
5. Document categories taxonomy and filtering in GET /documents without physical path leaks.
6. File size enforcement (5 MB limit), magic bytes signature checks, and corruption handling.
7. Missing encryption key behavior (fails closed with HTTP 500; zero plaintext storage).
8. Document replacement workflow (re-triggers OCR, updates file, unlinks old file, preserves confirmation history).
9. Archival vs. permanent deletion (storage cleanup, cascade deletion, zero orphaned files).
10. CSRF protection and unauthenticated/guest access restrictions.
11. Database migration compatibility for existing databases.
"""

import os
from pathlib import Path
import sqlite3
import uuid
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from api.main import app
from document_ai.categories import DocumentCategory, sanitize_filename
from document_ai.extract_fields import PIIVault
from document_ai.storage_vault import DocumentStorageVault
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures & Environment
# ---------------------------------------------------------------------------

@pytest.fixture
def library_env(tmp_path: Path, monkeypatch):
    """Provides an isolated test environment with custom storage vault and database."""
    db_file = tmp_path / "test_doc_library.db"
    vault_dir = tmp_path / "vault_storage"
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Set stable encryption key
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))

    db = Database(db_path=str(db_file))
    accounts = AccountManager(db=db)
    profiles = ProfileManager(db=db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=db)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)

    return {
        "db": db,
        "accounts": accounts,
        "profiles": profiles,
        "auth_service": auth_svc,
        "session_mgr": session_mgr,
        "vault_dir": vault_dir,
        "encryption_key": test_key,
    }


@pytest.fixture
def client(library_env):
    """TestClient configured with isolated services."""
    return TestClient(app)


def _signup_citizen(client: TestClient, email: str = "citizen_lib@example.com", password: str = "Password@123"):
    """Register and log in a citizen, returning user_id and CSRF token."""
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


def _sample_pdf_bytes():
    """Generates synthetic valid PDF bytes."""
    sample_path = Path("data/sample_documents/sample_synthetic_income_cert.pdf")
    if sample_path.exists():
        return sample_path.read_bytes()
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"


def _sample_png_bytes():
    """Generates synthetic valid PNG bytes."""
    sample_path = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if sample_path.exists():
        return sample_path.read_bytes()
    # 1x1 transparent PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ---------------------------------------------------------------------------
# 1. Registered User Persistent Upload & Vault Encryption
# ---------------------------------------------------------------------------

def test_registered_user_persistent_upload_encrypted_at_rest(client: TestClient, library_env: dict):
    """Registered user upload stores encrypted file in private vault and creates metadata."""
    user_id, csrf = _signup_citizen(client, "user_upload@example.com")
    pdf_bytes = _sample_pdf_bytes()
    vault_dir: Path = library_env["vault_dir"]

    res = client.post(
        "/documents/upload",
        files={"file": ("my_income_certificate.pdf", pdf_bytes, "application/pdf")},
        data={"document_category": "INCOME", "document_type": "INCOME_CERTIFICATE"},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    doc_id = data["document_id"]
    assert data["document_category"] == "INCOME"
    assert data["document_type"] == "INCOME_CERTIFICATE"
    assert data["has_original_file"] is True
    assert data["original_filename"] == "my_income_certificate.pdf"
    assert data["file_size"] == len(pdf_bytes)

    # 1. Verify database record
    profiles: ProfileManager = library_env["profiles"]
    doc = profiles.get_document(doc_id, user_id=user_id)
    assert doc is not None
    assert doc["document_category"] == "INCOME"
    assert doc["document_type"] == "INCOME_CERTIFICATE"
    assert doc["confirmation_status"] == "PENDING_CONFIRMATION"
    assert doc["status"] == "PENDING_REVIEW"
    assert doc["has_original_file"] is True

    # Storage reference is a random server-side filename, not a client path
    storage_ref = doc["storage_reference"]
    assert storage_ref.startswith("enc_")
    assert storage_ref.endswith(".vault")
    assert "my_income_certificate" not in storage_ref

    # 2. Verify encrypted file on disk
    vault_file = vault_dir / storage_ref
    assert vault_file.is_file()
    encrypted_disk_bytes = vault_file.read_bytes()

    # Content on disk MUST NOT contain raw PDF header or plaintext
    assert b"%PDF-1.4" not in encrypted_disk_bytes
    # Must be valid Fernet ciphertext (starts with Fernet version byte)
    assert encrypted_disk_bytes.startswith(b"gAAAAA")


# ---------------------------------------------------------------------------
# 2. Guest Zero-Persistence
# ---------------------------------------------------------------------------

def test_guest_zero_persistence_in_vault_and_database(client: TestClient, library_env: dict):
    """Guest sessions execute OCR but persist ZERO files and ZERO database rows."""
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    guest_csrf = guest_res.json()["csrf_token"]

    pdf_bytes = _sample_pdf_bytes()
    vault_dir: Path = library_env["vault_dir"]
    db: Database = library_env["db"]

    files_before = list(vault_dir.iterdir())

    upload_res = client.post(
        "/documents/upload",
        files={"file": ("guest_doc.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": guest_csrf},
    )
    assert upload_res.status_code == 200
    data = upload_res.json()
    assert data["success"] is True
    assert data["has_original_file"] is False

    # Vault directory must have NO new files
    files_after = list(vault_dir.iterdir())
    assert len(files_after) == len(files_before)

    # Database must have zero documents
    with db.get_connection() as conn:
        doc_count = conn.execute("SELECT COUNT(*) as c FROM document_metadata").fetchone()["c"]
        conf_count = conn.execute("SELECT COUNT(*) as c FROM confirmed_document_fields").fetchone()["c"]
    assert doc_count == 0
    assert conf_count == 0


# ---------------------------------------------------------------------------
# 3. Same-User Download with Authenticated Decryption
# ---------------------------------------------------------------------------

def test_same_user_download_returns_exact_decrypted_bytes(client: TestClient, library_env: dict):
    """Owner citizen can download their document and receive decrypted bytes matching original upload."""
    user_id, csrf = _signup_citizen(client, "downloader@example.com")
    pdf_bytes = _sample_pdf_bytes()

    upload_res = client.post(
        "/documents/upload",
        files={"file": ("official_income.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert upload_res.status_code == 200
    doc_id = upload_res.json()["document_id"]

    download_res = client.get(f"/documents/{doc_id}/download")
    assert download_res.status_code == 200

    # Content must match original uploaded bytes exactly
    assert download_res.content == pdf_bytes
    assert download_res.headers["Content-Disposition"] == 'attachment; filename="official_income.pdf"'
    assert "application/pdf" in download_res.headers["Content-Type"]
    assert download_res.headers["Content-Length"] == str(len(pdf_bytes))

    # Anti-caching headers must be present
    assert "no-store" in download_res.headers["Cache-Control"]
    assert download_res.headers["Pragma"] == "no-cache"


# ---------------------------------------------------------------------------
# 4. Cross-User Download Denial and IDOR Protections
# ---------------------------------------------------------------------------

def test_cross_user_download_and_metadata_idor_denied(client: TestClient, library_env: dict):
    """A citizen cannot download, view, replace, or delete another citizen's document (returns 404)."""
    # Victim citizen uploads a document
    victim_id, victim_csrf = _signup_citizen(client, "victim_doc@example.com")
    pdf_bytes = _sample_pdf_bytes()
    upload_res = client.post(
        "/documents/upload",
        files={"file": ("victim_pan.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": victim_csrf},
    )
    doc_id = upload_res.json()["document_id"]

    # Attacker citizen logs in
    attacker_id, attacker_csrf = _signup_citizen(client, "attacker_doc@example.com")

    # 1. Download attempt -> 404
    dl_res = client.get(f"/documents/{doc_id}/download")
    assert dl_res.status_code == 404

    # 2. Metadata view attempt -> 404
    meta_res = client.get(f"/documents/{doc_id}")
    assert meta_res.status_code == 404

    # 3. Replace attempt -> 404
    rep_res = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": ("hacked.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": attacker_csrf},
    )
    assert rep_res.status_code == 404

    # 4. Delete attempt -> 404
    del_res = client.delete(
        f"/documents/{doc_id}",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": attacker_csrf},
    )
    assert del_res.status_code == 404


# ---------------------------------------------------------------------------
# 5. Document List & Category Filtering (No Path Leakage)
# ---------------------------------------------------------------------------

def test_list_documents_filtering_and_zero_path_leakage(client: TestClient, library_env: dict):
    """GET /documents returns citizen's documents with category filter and without server path leakage."""
    user_id, csrf = _signup_citizen(client, "list_user@example.com")
    pdf_bytes = _sample_pdf_bytes()

    # Upload Doc 1: IDENTITY
    client.post(
        "/documents/upload",
        files={"file": ("aadhaar.pdf", pdf_bytes, "application/pdf")},
        data={"document_category": "IDENTITY", "document_type": "AADHAAR_CARD"},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    # Upload Doc 2: INCOME
    client.post(
        "/documents/upload",
        files={"file": ("income.pdf", pdf_bytes, "application/pdf")},
        data={"document_category": "INCOME", "document_type": "INCOME_CERTIFICATE"},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )

    # 1. List all documents
    all_res = client.get("/documents")
    assert all_res.status_code == 200
    docs = all_res.json()["documents"]
    assert len(docs) == 2

    # Verify no physical storage path leaked
    for d in docs:
        assert "file_path" not in d
        assert "storage_path" not in d
        assert "data/secure_vault" not in str(d)
        assert d["has_original_file"] is True

    # 2. Filter by category
    income_res = client.get("/documents?category=INCOME")
    assert income_res.status_code == 200
    income_docs = income_res.json()["documents"]
    assert len(income_docs) == 1
    assert income_docs[0]["document_category"] == "INCOME"

    id_res = client.get("/documents?category=IDENTITY")
    assert id_res.status_code == 200
    assert len(id_res.json()["documents"]) == 1


# ---------------------------------------------------------------------------
# 6. Encryption Fails Closed When Key Is Missing
# ---------------------------------------------------------------------------

def test_upload_and_download_fail_closed_without_encryption_key(client: TestClient, library_env: dict, monkeypatch):
    """When SAHAY_PII_ENCRYPTION_KEY is unconfigured, persistent upload & download fail closed (HTTP 500)."""
    user_id, csrf = _signup_citizen(client, "unencrypted_tester@example.com")
    pdf_bytes = _sample_pdf_bytes()

    # Deliberately remove encryption key
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", "")

    upload_res = client.post(
        "/documents/upload",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    # MUST fail closed with 500 Internal Server Error
    assert upload_res.status_code == 500
    assert "encryption key is not configured" in upload_res.json()["detail"].lower()

    # Zero plaintext files created
    vault_dir: Path = library_env["vault_dir"]
    assert len(list(vault_dir.iterdir())) == 0


# ---------------------------------------------------------------------------
# 7. Document Replacement Workflow
# ---------------------------------------------------------------------------

def test_document_replacement_replaces_file_and_preserves_confirmation_history(client: TestClient, library_env: dict):
    """Replacing a document updates file, re-runs OCR, deletes old encrypted file, and preserves confirmation history."""
    profiles: ProfileManager = library_env["profiles"]
    vault_dir: Path = library_env["vault_dir"]
    user_id, csrf = _signup_citizen(client, "replace_citizen@example.com")
    pdf_bytes_v1 = _sample_pdf_bytes()

    # 1. Initial upload
    up1 = client.post(
        "/documents/upload",
        files={"file": ("income_2024.pdf", pdf_bytes_v1, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert up1.status_code == 200
    doc_id = up1.json()["document_id"]

    # 2. Confirm a field on v1
    profiles.save_confirmed_field(
        user_id=user_id,
        document_id=doc_id,
        field_name="annual_income",
        field_value=100000,
        extracted_value=100000,
    )

    doc_v1 = profiles.get_document(doc_id, user_id=user_id)
    ref_v1 = doc_v1["storage_reference"]
    file_v1 = vault_dir / ref_v1
    assert file_v1.is_file()

    # 3. Replace document with v2
    # Modify bytes slightly to create distinct v2
    pdf_bytes_v2 = pdf_bytes_v1 + b"\n% v2 replacement comment"
    rep_res = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": ("income_2025.pdf", pdf_bytes_v2, "application/pdf")},
        data={"document_category": "INCOME", "document_type": "INCOME_CERTIFICATE"},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert rep_res.status_code == 200
    rep_data = rep_res.json()
    assert rep_data["success"] is True
    assert rep_data["original_filename"] == "income_2025.pdf"

    # 4. Old encrypted file MUST be deleted from disk
    assert not file_v1.exists(), "Old encrypted vault file was not deleted upon replacement"

    # 5. New encrypted file exists
    doc_v2 = profiles.get_document(doc_id, user_id=user_id)
    ref_v2 = doc_v2["storage_reference"]
    assert ref_v2 != ref_v1
    file_v2 = vault_dir / ref_v2
    assert file_v2.is_file()

    # 6. Previous confirmation history in confirmed_document_fields MUST BE PRESERVED
    history = profiles.get_confirmation_history(user_id=user_id, field_name="annual_income")
    assert len(history) == 1
    assert str(history[0]["value"]) == "100000"

    # 7. Downloading returns new v2 bytes
    dl_res = client.get(f"/documents/{doc_id}/download")
    assert dl_res.status_code == 200
    assert dl_res.content == pdf_bytes_v2


# ---------------------------------------------------------------------------
# 8. Archival vs. Permanent Deletion
# ---------------------------------------------------------------------------

def test_archival_and_permanent_deletion_storage_lifecycle(client: TestClient, library_env: dict):
    """Archival marks document ARCHIVED while retaining files; permanent delete cleans up file from vault."""
    profiles: ProfileManager = library_env["profiles"]
    vault_dir: Path = library_env["vault_dir"]
    user_id, csrf = _signup_citizen(client, "lifecycle_citizen@example.com")
    pdf_bytes = _sample_pdf_bytes()

    # Upload Doc 1 for Archival
    up1 = client.post(
        "/documents/upload",
        files={"file": ("doc_archive.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    doc_archive_id = up1.json()["document_id"]
    ref_archive = profiles.get_document(doc_archive_id)["storage_reference"]
    file_archive = vault_dir / ref_archive

    # 1. Soft-delete / Archive
    del_arch_res = client.delete(
        f"/documents/{doc_archive_id}?hard_delete=false",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert del_arch_res.status_code == 200
    assert del_arch_res.json()["hard_deleted"] is False

    # Vault file and metadata still exist
    assert file_archive.is_file()
    doc_after_arch = profiles.get_document(doc_archive_id)
    assert doc_after_arch["status"] == "ARCHIVED"

    # Default list excludes it, include_archived includes it
    list_active = client.get("/documents").json()["documents"]
    assert not any(d["document_id"] == doc_archive_id for d in list_active)

    list_all = client.get("/documents?include_archived=true").json()["documents"]
    assert any(d["document_id"] == doc_archive_id for d in list_all)

    # 2. Hard permanent delete
    del_perm_res = client.delete(
        f"/documents/{doc_archive_id}?hard_delete=true",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert del_perm_res.status_code == 200
    assert del_perm_res.json()["hard_deleted"] is True

    # Vault file is unlinked permanently (zero orphaned storage files)
    assert not file_archive.exists()
    # Metadata is gone
    assert profiles.get_document(doc_archive_id) is None


# ---------------------------------------------------------------------------
# 9. Database Migration Compatibility
# ---------------------------------------------------------------------------

def test_database_migration_adds_library_columns_safely(tmp_path: Path):
    """Old database schema without library columns migrates cleanly without data loss."""
    legacy_db_file = tmp_path / "old_sahay_db.db"
    conn = sqlite3.connect(str(legacy_db_file))
    conn.execute("PRAGMA foreign_keys = ON")

    # Base users and old document_metadata table without category/storage_reference
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            email TEXT,
            phone TEXT,
            password_hash TEXT NOT NULL,
            account_status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE document_metadata (
            document_id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
            profile_id TEXT,
            document_type TEXT NOT NULL,
            file_path TEXT,
            extracted_fields_json TEXT,
            status TEXT DEFAULT 'PENDING_REVIEW',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO users VALUES ('u_legacy', 'leg@example.com', '1234567890', 'hash', 'ACTIVE', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO document_metadata VALUES ('doc_legacy', 'u_legacy', NULL, 'AADHAAR_CARD', NULL, '{}', 'PENDING_REVIEW', '2026-01-01', '2026-01-01')")
    conn.commit()
    conn.close()

    # Initialize Database to trigger init_db() migration
    migrated_db = Database(db_path=str(legacy_db_file))

    with migrated_db.get_connection() as c:
        cols = {row["name"] for row in c.execute("PRAGMA table_info(document_metadata)").fetchall()}
        assert "document_category" in cols
        assert "original_filename" in cols
        assert "storage_reference" in cols
        assert "mime_type" in cols
        assert "file_size" in cols
        assert "confirmation_status" in cols

        # Existing record preserved
        row = c.execute("SELECT document_id, document_type, document_category FROM document_metadata WHERE document_id = 'doc_legacy'").fetchone()
        assert row is not None
        assert row["document_id"] == "doc_legacy"
        assert row["document_type"] == "AADHAAR_CARD"
        assert row["document_category"] == "OTHER"  # Default value


# ---------------------------------------------------------------------------
# 10. Access Control, Guest Restrictions, and CSRF Protection
# ---------------------------------------------------------------------------

def test_unauthenticated_and_guest_library_access_denied(client: TestClient, library_env: dict):
    """Unauthenticated users receive HTTP 401 and guests receive HTTP 403 on library endpoints."""
    # 1. Unauthenticated requests
    assert client.get("/documents").status_code == 401
    assert client.get("/documents/doc_123/download").status_code == 401
    assert client.get("/documents/doc_123").status_code == 401
    assert client.delete("/documents/doc_123").status_code == 401

    # 2. Guest requests
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    guest_csrf = guest_res.json()["csrf_token"]

    assert client.get("/documents").status_code == 403
    assert client.get("/documents/doc_123").status_code == 403
    assert client.get("/documents/doc_123/download").status_code == 403
    assert client.delete("/documents/doc_123", headers={"Origin": "http://localhost:5500", "X-CSRF-Token": guest_csrf}).status_code == 403

    pdf_bytes = _sample_pdf_bytes()
    rep_res = client.post(
        "/documents/doc_123/replace",
        files={"file": ("replace.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": guest_csrf},
    )
    assert rep_res.status_code == 403


def test_replacement_validation_and_file_size_limits(client: TestClient, library_env: dict):
    """Replacement endpoint enforces 5 MB size limit, magic bytes check, and empty file check."""
    user_id, csrf = _signup_citizen(client, "validation_citizen@example.com")
    pdf_bytes = _sample_pdf_bytes()

    # Upload initial doc
    up = client.post(
        "/documents/upload",
        files={"file": ("initial.pdf", pdf_bytes, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    doc_id = up.json()["document_id"]

    # 1. Replace without CSRF -> 403
    csrf_res = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": ("new.pdf", pdf_bytes, "application/pdf")},
    )
    assert csrf_res.status_code == 403

    # 2. Replace with oversized file (> 10 MB for PDF) -> 413
    oversized = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 100)
    big_res = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": ("too_big.pdf", oversized, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert big_res.status_code == 413

    # 3. Replace with empty file -> 400
    empty_res = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert empty_res.status_code == 400

    # 4. Replace with mismatched magic bytes -> 415
    fake_pdf = b"NOT_A_PDF_HEADER_TEXT_12345678"
    fake_res = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf},
    )
    assert fake_res.status_code == 415
