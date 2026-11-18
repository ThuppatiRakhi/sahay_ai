"""Unit and integration tests for citizen profile management, SQLite cascade deletion, and PII storage."""

import json
import pytest

from profile.database import Database
from profile.profile_manager import ProfileManager


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_sahay.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def profile_mgr(temp_db):
    return ProfileManager(db=temp_db)


def test_sqlite_foreign_keys_enabled(temp_db):
    """Verify PRAGMA foreign_keys = ON is strictly active on connections."""
    with temp_db.get_connection() as conn:
        row = conn.execute("PRAGMA foreign_keys;").fetchone()
        assert row[0] == 1, "SQLite foreign keys must be enabled (PRAGMA foreign_keys = 1)."


def test_create_and_get_profile(profile_mgr):
    data = {
        "full_name": "Aarav Sharma",
        "date_of_birth": "1992-04-10",
        "age": 32,
        "gender": "MALE",
        "state": "Maharashtra",
        "district": "Pune",
        "annual_income": 150000.0,
        "occupation": "Farmer",
        "caste_category": "OBC",
        "is_bpl": True,
    }
    created = profile_mgr.create_profile(data)
    assert created["profile_id"] is not None
    assert created["full_name"] == "Aarav Sharma"
    assert created["user_confirmed"] is False

    fetched = profile_mgr.get_profile(created["profile_id"])
    assert fetched is not None
    assert fetched["age"] == 32
    assert fetched["is_bpl"] is True
    assert fetched["district"] == "Pune"


def test_update_profile(profile_mgr):
    data = {"full_name": "Sunita Patil", "age": 28, "gender": "FEMALE"}
    created = profile_mgr.create_profile(data)

    updated = profile_mgr.update_profile(
        created["profile_id"],
        {"annual_income": 180000.0, "state": "Karnataka"},
    )
    assert updated["annual_income"] == 180000.0
    assert updated["state"] == "Karnataka"


def test_confirm_profile(profile_mgr):
    data = {"full_name": "Kiran Rao", "age": 45, "state": "Telangana"}
    created = profile_mgr.create_profile(data)
    assert created["user_confirmed"] is False

    confirmed = profile_mgr.confirm_profile(
        created["profile_id"],
        {"annual_income": 95000.0, "occupation": "Weaver"},
    )
    assert confirmed["user_confirmed"] is True
    assert confirmed["annual_income"] == 95000.0
    assert confirmed["occupation"] == "Weaver"


def test_cascade_deletion(profile_mgr, temp_db):
    """Ensure deleting a profile cascade-deletes all associated document metadata."""
    p = profile_mgr.create_profile({"full_name": "Rajesh Kumar"})
    pid = p["profile_id"]

    doc_id = profile_mgr.save_document_metadata(
        profile_id=pid,
        document_type="AADHAAR_CARD",
        file_path="data/sample_documents/sample_synthetic_aadhaar.png",
        extracted_fields={"masked_aadhaar": "XXXX-XXXX-7777"},
    )

    docs_before = profile_mgr.get_profile_documents(pid)
    assert len(docs_before) == 1

    # Delete profile
    deleted = profile_mgr.delete_profile(pid)
    assert deleted is True

    # Assert document_metadata rows were cascade-deleted
    docs_after = profile_mgr.get_profile_documents(pid)
    assert len(docs_after) == 0

    with temp_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM document_metadata WHERE profile_id = ?", (pid,)).fetchone()[0]
        assert count == 0, "No orphaned document metadata rows should remain after profile deletion."


def test_pii_sanitization_in_storage(profile_mgr):
    """Ensure raw unmasked Aadhaar or PAN is sanitized before SQLite storage."""
    p = profile_mgr.create_profile({"full_name": "Meera Bai"})
    pid = p["profile_id"]

    # Passing raw 12-digit number should be automatically masked in storage
    doc_id = profile_mgr.save_document_metadata(
        profile_id=pid,
        document_type="AADHAAR_CARD",
        file_path="dummy.png",
        extracted_fields={
            "aadhaar_number": {"value": "9999 8888 7777", "masked_display": "XXXX-XXXX-7777"}
        },
    )

    docs = profile_mgr.get_profile_documents(pid)
    stored_val = docs[0]["extracted_fields"]["aadhaar_number"]["value"]
    assert stored_val == "XXXX-XXXX-7777"
    assert "9999" not in stored_val


def test_get_profile_for_recommendation(profile_mgr):
    data = {
        "full_name": "Meera Bai",
        "age": 38,
        "gender": "FEMALE",
        "state": "Rajasthan",
        "district": "Jaipur",
        "annual_income": 80000.0,
        "occupation": "Artisan",
        "caste_category": "SC",
        "is_bpl": True,
        "user_confirmed": True,
    }
    created = profile_mgr.create_profile(data)

    rec_data = profile_mgr.get_profile_for_recommendation(created["profile_id"])
    assert rec_data is not None
    assert rec_data["age"] == 38
    assert rec_data["gender"] == "FEMALE"
    assert rec_data["state"] == "Rajasthan"
    assert rec_data["annual_income"] == 80000.0
    assert rec_data["is_bpl"] is True
    assert rec_data["user_confirmed"] is True
    assert "metadata_json" not in rec_data
    assert not hasattr(profile_mgr, "match_schemes")
