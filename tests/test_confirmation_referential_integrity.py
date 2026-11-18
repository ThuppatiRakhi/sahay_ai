"""Tests for SahayAI Step 5.3A.3 – Confirmation History Referential Integrity.

Validates:
1. Deleting a document with confirmation history cascades and removes associated rows.
2. Deleting a profile cascades through document_metadata down to confirmed_document_fields.
3. Soft-deletion/archival retains document metadata and full confirmation history.
4. Preventing orphaned confirmation records (rejecting invalid document_id with IntegrityError).
5. Migration of existing databases preserves historical records and restores referential integrity.
6. Foreign-key enforcement (PRAGMA foreign_keys = ON) on all new database connections.
7. API-level document deletion with cascade integrity, IDOR checks, and guest protection.
"""

import os
from pathlib import Path
import sqlite3
import uuid
import pytest
from fastapi.testclient import TestClient

from api.main import app
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path: Path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_referential_integrity.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def integrity_env(test_db: Database, monkeypatch):
    """Configures isolated auth, profile, and document services for testing."""
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
        "accounts": accounts,
        "profiles": profiles,
        "auth_service": auth_svc,
        "session_mgr": session_mgr,
    }


@pytest.fixture
def client(integrity_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _signup_citizen(client: TestClient, email: str = "citizen@example.com", password: str = "Password@123"):
    """Helper to register and authenticate a citizen."""
    res = client.post(
        "/auth/signup",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200
    user_id = res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]
    return user_id, csrf_token


# ---------------------------------------------------------------------------
# 1. Foreign-Key Enforcement on Database Connections
# ---------------------------------------------------------------------------

def test_foreign_key_enforcement_on_new_connections(test_db: Database):
    """PRAGMA foreign_keys = ON is strictly enforced on every opened connection."""
    # Test multiple sequential connection contexts
    for i in range(5):
        with test_db.get_connection() as conn:
            fk_state = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk_state == 1, f"Connection {i} did not have foreign_keys enabled"

    # Verify active schema has declared foreign keys on confirmed_document_fields
    with test_db.get_connection() as conn:
        fks = conn.execute("PRAGMA foreign_key_list(confirmed_document_fields)").fetchall()
        fk_map = {row["table"]: dict(row) for row in fks}

        assert "document_metadata" in fk_map
        assert fk_map["document_metadata"]["from"] == "document_id"
        assert fk_map["document_metadata"]["to"] == "document_id"
        assert fk_map["document_metadata"]["on_delete"].upper() == "CASCADE"

        assert "users" in fk_map
        assert fk_map["users"]["from"] == "user_id"
        assert fk_map["users"]["to"] == "user_id"
        assert fk_map["users"]["on_delete"].upper() == "CASCADE"


# ---------------------------------------------------------------------------
# 2. Preventing Orphaned Confirmation Records
# ---------------------------------------------------------------------------

def test_prevent_orphaned_confirmation_records_via_sql(integrity_env: dict):
    """Direct SQL insertion with a non-existent document_id is rejected by SQLite."""
    db: Database = integrity_env["db"]
    accounts: AccountManager = integrity_env["accounts"]

    user = accounts.register_user(email=f"user_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    user_id = user["user_id"]

    with pytest.raises(sqlite3.IntegrityError):
        with db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO confirmed_document_fields (
                    id, user_id, document_id, field_name, field_value,
                    confirmed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"conf_{uuid.uuid4().hex[:8]}",
                    user_id,
                    "non_existent_document_id",
                    "annual_income",
                    "150000",
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:00:00",
                ),
            )


def test_prevent_orphaned_confirmation_records_via_profile_manager(integrity_env: dict):
    """ProfileManager.save_confirmed_field rejects non-existent document_id."""
    profiles: ProfileManager = integrity_env["profiles"]
    accounts: AccountManager = integrity_env["accounts"]

    user = accounts.register_user(email=f"user_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    user_id = user["user_id"]

    with pytest.raises(sqlite3.IntegrityError):
        profiles.save_confirmed_field(
            user_id=user_id,
            document_id="invalid_doc_99999",
            field_name="annual_income",
            field_value=200000,
        )


def test_prevent_orphaned_confirmation_in_transactional_confirm(integrity_env: dict):
    """confirm_and_persist_transactional fails and rolls back when document_id is invalid."""
    profiles: ProfileManager = integrity_env["profiles"]
    accounts: AccountManager = integrity_env["accounts"]
    db: Database = integrity_env["db"]

    user = accounts.register_user(email=f"user_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    user_id = user["user_id"]

    with pytest.raises(sqlite3.IntegrityError):
        profiles.confirm_and_persist_transactional(
            user_id=user_id,
            document_id="ghost_document_id",
            confirmed_items=[
                {"field_name": "state", "field_value": "Telangana"},
            ],
            profile_updates={"state": "Telangana"},
        )

    # Verify zero confirmed rows exist
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM confirmed_document_fields WHERE user_id = ?", (user_id,)).fetchone()["c"]
    assert count == 0


# ---------------------------------------------------------------------------
# 3. Document Deletion Cascades Confirmation History
# ---------------------------------------------------------------------------

def test_deleting_document_cascades_confirmation_history(integrity_env: dict):
    """Deleting a document from document_metadata automatically cascade-deletes confirmation rows."""
    profiles: ProfileManager = integrity_env["profiles"]
    accounts: AccountManager = integrity_env["accounts"]
    db: Database = integrity_env["db"]

    user = accounts.register_user(email=f"user_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    user_id = user["user_id"]

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    profiles.save_document(doc_id, user_id, "AADHAAR_CARD", {"annual_income": 120000, "state": "Telangana"})

    # Save multiple confirmed fields
    profiles.save_confirmed_field(user_id=user_id, document_id=doc_id, field_name="annual_income", field_value=120000)
    profiles.save_confirmed_field(user_id=user_id, document_id=doc_id, field_name="state", field_value="Telangana")

    # Verify fields exist
    with db.get_connection() as conn:
        rows = conn.execute("SELECT * FROM confirmed_document_fields WHERE document_id = ?", (doc_id,)).fetchall()
        assert len(rows) == 2

    # Hard delete document
    deleted = profiles.delete_document(document_id=doc_id, user_id=user_id, hard_delete=True)
    assert deleted is True

    # Verify document is gone from document_metadata
    assert profiles.get_document(doc_id) is None

    # Verify confirmation history for this document was automatically cascade-deleted
    with db.get_connection() as conn:
        remaining = conn.execute("SELECT * FROM confirmed_document_fields WHERE document_id = ?", (doc_id,)).fetchall()
        assert len(remaining) == 0


def test_deleting_profile_cascades_documents_and_confirmation_history(integrity_env: dict):
    """Deleting a profile cascades through document_metadata down to confirmed_document_fields."""
    profiles: ProfileManager = integrity_env["profiles"]
    accounts: AccountManager = integrity_env["accounts"]
    db: Database = integrity_env["db"]

    user = accounts.register_user(email=f"user_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    user_id = user["user_id"]

    profile = profiles.create_profile({"user_id": user_id, "full_name": "Test Citizen"})
    profile_id = profile["profile_id"]

    doc_id = f"doc_prof_{uuid.uuid4().hex[:6]}"
    profiles.save_document(doc_id, user_id, "PAN_CARD", {"full_name": "Test Citizen"}, profile_id=profile_id)

    profiles.save_confirmed_field(user_id=user_id, document_id=doc_id, field_name="full_name", field_value="Test Citizen")

    # Verify rows exist
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) as c FROM document_metadata WHERE document_id = ?", (doc_id,)).fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) as c FROM confirmed_document_fields WHERE document_id = ?", (doc_id,)).fetchone()["c"] == 1

    # Delete profile
    deleted = profiles.delete_profile(profile_id)
    assert deleted is True

    # Verify multi-level cascade
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) as c FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) as c FROM document_metadata WHERE document_id = ?", (doc_id,)).fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) as c FROM confirmed_document_fields WHERE document_id = ?", (doc_id,)).fetchone()["c"] == 0


# ---------------------------------------------------------------------------
# 4. Soft-Deletion / Archival Retention Policy
# ---------------------------------------------------------------------------

def test_soft_delete_preserves_document_and_confirmation_history(integrity_env: dict):
    """Soft deletion (hard_delete=False) marks document ARCHIVED while retaining confirmation history."""
    profiles: ProfileManager = integrity_env["profiles"]
    accounts: AccountManager = integrity_env["accounts"]
    db: Database = integrity_env["db"]

    user = accounts.register_user(email=f"user_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    user_id = user["user_id"]

    doc_id = f"doc_archive_{uuid.uuid4().hex[:6]}"
    profiles.save_document(doc_id, user_id, "INCOME_CERTIFICATE", {"annual_income": 95000})
    profiles.save_confirmed_field(user_id=user_id, document_id=doc_id, field_name="annual_income", field_value=95000)

    # Soft delete / archive
    archived = profiles.delete_document(document_id=doc_id, user_id=user_id, hard_delete=False)
    assert archived is True

    doc = profiles.get_document(doc_id)
    assert doc is not None
    assert doc["status"] == "ARCHIVED"

    # Confirmed fields are fully retained for audit purposes
    history = profiles.get_confirmation_history(user_id=user_id, field_name="annual_income")
    assert len(history) == 1
    assert str(history[0]["value"]) == "95000"


# ---------------------------------------------------------------------------
# 5. Migration of Existing Databases
# ---------------------------------------------------------------------------

def test_migration_of_existing_database_without_foreign_key(tmp_path: Path):
    """Existing databases without document_metadata FK or with old schema migrate safely with zero data loss."""
    legacy_db_file = tmp_path / "legacy_sahay_ai.db"

    # 1. Create a legacy database manually using raw sqlite3 without the FK and with UNIQUE constraint
    raw_conn = sqlite3.connect(str(legacy_db_file))
    raw_conn.execute("PRAGMA foreign_keys = ON")
    raw_conn.execute("""
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
    raw_conn.execute("""
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
    # Old confirmed_document_fields table lacking foreign key on document_id and having UNIQUE(user_id, field_name)
    raw_conn.execute("""
        CREATE TABLE confirmed_document_fields (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            document_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value TEXT NOT NULL,
            extracted_value TEXT,
            is_corrected INTEGER NOT NULL DEFAULT 0,
            is_confirmed INTEGER NOT NULL DEFAULT 1,
            is_government_verified INTEGER NOT NULL DEFAULT 0,
            confirmation_status TEXT NOT NULL DEFAULT 'CONFIRMED',
            encrypted_value TEXT,
            confirmed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, field_name)
        )
    """)

    # Seed users and documents
    u1 = "user_mig_1"
    doc1 = "doc_mig_1"
    raw_conn.execute("INSERT INTO users VALUES (?, 'u1@example.com', '9876543210', 'hash', 'ACTIVE', '2026-01-01', '2026-01-01')", (u1,))
    raw_conn.execute("INSERT INTO document_metadata VALUES (?, ?, NULL, 'AADHAAR_CARD', NULL, '{}', 'PENDING_REVIEW', '2026-01-01', '2026-01-01')", (doc1, u1))

    # Seed 2 confirmed records: one for valid doc1, one for an orphaned doc (already deleted in legacy system)
    c1 = "conf_mig_1"
    c2 = "conf_mig_orphan"
    raw_conn.execute("""
        INSERT INTO confirmed_document_fields VALUES (
            ?, ?, ?, 'age', '24', '24', 0, 1, 0, 'CONFIRMED', NULL, '2026-01-01T10:00:00', '2026-01-01T10:00:00'
        )
    """, (c1, u1, doc1))
    raw_conn.execute("""
        INSERT INTO confirmed_document_fields VALUES (
            ?, ?, 'orphan_legacy_doc', 'income', '120000', '120000', 0, 1, 0, 'CONFIRMED', NULL, '2026-01-01T11:00:00', '2026-01-01T11:00:00'
        )
    """, (c2, u1))
    raw_conn.commit()
    raw_conn.close()

    # 2. Open via SahayAI Database to execute init_db() migration
    migrated_db = Database(db_path=str(legacy_db_file))

    # 3. Verify all confirmation records survived migration
    with migrated_db.get_connection() as conn:
        rows = conn.execute("SELECT id, document_id, field_name, field_value FROM confirmed_document_fields ORDER BY id").fetchall()
        assert len(rows) == 2
        row_map = {r["id"]: dict(r) for r in rows}

        assert c1 in row_map
        assert row_map[c1]["field_value"] == "24"
        assert row_map[c1]["document_id"] == doc1

        assert c2 in row_map
        assert row_map[c2]["field_value"] == "120000"
        assert row_map[c2]["document_id"] == "orphan_legacy_doc"

        # 4. Verify orphaned document was synthesized into document_metadata to ensure integrity
        orphan_doc = conn.execute("SELECT * FROM document_metadata WHERE document_id = 'orphan_legacy_doc'").fetchone()
        assert orphan_doc is not None
        assert orphan_doc["status"] == "ARCHIVED"

        # 5. Verify PRAGMA foreign_key_check passes cleanly
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(violations) == 0

        # 6. Verify foreign key list has restored ON DELETE CASCADE
        fks = conn.execute("PRAGMA foreign_key_list(confirmed_document_fields)").fetchall()
        doc_fk = next((dict(f) for f in fks if f["table"] == "document_metadata"), None)
        assert doc_fk is not None
        assert doc_fk["from"] == "document_id"
        assert doc_fk["to"] == "document_id"
        assert doc_fk["on_delete"].upper() == "CASCADE"

        # 7. Verify cascade deletion works post-migration
        conn.execute("DELETE FROM document_metadata WHERE document_id = ?", (doc1,))
        remaining_after_del = conn.execute("SELECT id FROM confirmed_document_fields WHERE document_id = ?", (doc1,)).fetchall()
        assert len(remaining_after_del) == 0

        # 8. Verify inserting new invalid document_id is blocked post-migration
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO confirmed_document_fields (
                    id, user_id, document_id, field_name, field_value,
                    confirmed_at, updated_at
                ) VALUES ('conf_new', ?, 'invalid_doc_id', 'state', 'Delhi', 'now', 'now')
                """,
                (u1,),
            )


# ---------------------------------------------------------------------------
# 6. API-Level Document Deletion & Cascade Integrity
# ---------------------------------------------------------------------------

def test_api_delete_document_cascades_confirmation_history(client: TestClient, integrity_env: dict):
    """DELETE /documents/{id} cascades confirmation history and enforces security checks."""
    profiles: ProfileManager = integrity_env["profiles"]
    user_id, csrf_token = _signup_citizen(client, "user_del_api@example.com")

    doc_id = f"doc_api_{uuid.uuid4().hex[:6]}"
    profiles.save_document(doc_id, user_id, "AADHAAR_CARD", {"annual_income": 140000})
    profiles.save_confirmed_field(user_id=user_id, document_id=doc_id, field_name="annual_income", field_value=140000)

    # Confirm field exists before delete
    conf_before = profiles.get_confirmed_fields_by_user(user_id)
    assert len(conf_before) == 1

    # Call DELETE /documents/{doc_id}
    del_res = client.delete(
        f"/documents/{doc_id}",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Document is deleted from metadata
    assert profiles.get_document(doc_id) is None

    # Confirmation history is cascaded away
    conf_after = profiles.get_confirmed_fields_by_user(user_id)
    assert len(conf_after) == 0


def test_api_delete_document_idor_protection(client: TestClient, integrity_env: dict):
    """A citizen cannot delete another citizen's document (returns 404)."""
    profiles: ProfileManager = integrity_env["profiles"]
    accounts: AccountManager = integrity_env["accounts"]

    # Victim user owns the document
    victim = accounts.register_user(email=f"victim_{uuid.uuid4().hex[:6]}@example.com", password="Password@123")
    victim_doc_id = f"doc_victim_{uuid.uuid4().hex[:6]}"
    profiles.save_document(victim_doc_id, victim["user_id"], "PAN_CARD", {})

    # Attacker logs in
    _, attacker_csrf = _signup_citizen(client, "attacker@example.com")

    del_res = client.delete(
        f"/documents/{victim_doc_id}",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": attacker_csrf},
    )
    assert del_res.status_code == 404

    # Victim doc remains intact
    assert profiles.get_document(victim_doc_id) is not None
