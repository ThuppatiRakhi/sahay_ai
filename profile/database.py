
"""Database layer for SahayAI accounts, citizen profiles, and documents.

Supports safe, repeatable SQLite schema initialization and migration
of existing profile databases.
"""

from contextlib import contextmanager
import logging
from pathlib import Path
import sqlite3
from typing import Generator, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/sahay_ai.db"


class Database:
    """Manages SQLite connections and SahayAI database schemas."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the database.

        Args:
            db_path: Database file path. Defaults to data/sahay_ai.db.
        """
        self.db_path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional SQLite connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        # Enable foreign key enforcement for every connection.
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create tables and safely migrate existing databases."""

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. User accounts table.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT COLLATE NOCASE UNIQUE,
                    phone TEXT UNIQUE,
                    password_hash TEXT NOT NULL,
                    account_status TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (account_status IN ('ACTIVE', 'DISABLED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,

                    CHECK (
                        (email IS NOT NULL AND length(trim(email)) > 0)
                        OR
                        (phone IS NOT NULL AND length(trim(phone)) > 0)
                    ),

                    CHECK (length(trim(password_hash)) > 0)
                )
                """
            )

            # 2. Citizen profiles table.
            # Existing profile columns are preserved.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    profile_id TEXT PRIMARY KEY,
                    full_name TEXT,
                    date_of_birth TEXT,
                    age INTEGER,
                    gender TEXT,
                    state TEXT,
                    district TEXT,
                    annual_income REAL,
                    occupation TEXT,
                    caste_category TEXT,
                    is_bpl INTEGER DEFAULT 0,
                    user_confirmed INTEGER DEFAULT 0,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # 3. Migrate existing profiles by adding user_id only
            # when the column does not already exist.
            profile_columns = {
                row["name"]
                for row in cursor.execute(
                    "PRAGMA table_info(profiles)"
                ).fetchall()
            }

            if "user_id" not in profile_columns:
                cursor.execute(
                    """
                    ALTER TABLE profiles
                    ADD COLUMN user_id TEXT
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
                    """
                )
                logger.info(
                    "Database migration: added user_id to profiles"
                )

            # One account can own at most one citizen profile.
            # Multiple existing unlinked profiles remain valid.
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_profiles_user_id_unique
                ON profiles(user_id)
                WHERE user_id IS NOT NULL
                """
            )

            # 4. Document metadata table.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS document_metadata (
                    document_id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
                    profile_id TEXT REFERENCES profiles(profile_id) ON DELETE CASCADE,
                    document_category TEXT DEFAULT 'OTHER',
                    document_type TEXT NOT NULL,
                    original_filename TEXT,
                    storage_reference TEXT,
                    file_path TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    extracted_fields_json TEXT,
                    status TEXT DEFAULT 'PENDING_REVIEW',
                    confirmation_status TEXT DEFAULT 'PENDING_CONFIRMATION',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Migrate document_metadata if needed (make profile_id nullable and add user_id / updated_at)
            doc_col_info = {
                row["name"]: dict(row)
                for row in cursor.execute("PRAGMA table_info(document_metadata)").fetchall()
            }
            if "user_id" not in doc_col_info or doc_col_info.get("profile_id", {}).get("notnull") == 1:
                cursor.execute("PRAGMA foreign_keys = OFF")
                cursor.execute(
                    """
                    CREATE TABLE document_metadata_v2 (
                        document_id TEXT PRIMARY KEY,
                        user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
                        profile_id TEXT REFERENCES profiles(profile_id) ON DELETE CASCADE,
                        document_category TEXT DEFAULT 'OTHER',
                        document_type TEXT NOT NULL,
                        original_filename TEXT,
                        storage_reference TEXT,
                        file_path TEXT,
                        mime_type TEXT,
                        file_size INTEGER,
                        extracted_fields_json TEXT,
                        status TEXT DEFAULT 'PENDING_REVIEW',
                        confirmation_status TEXT DEFAULT 'PENDING_CONFIRMATION',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                existing_cols = [
                    c for c in ["document_id", "profile_id", "document_type", "file_path", "extracted_fields_json", "status", "created_at"]
                    if c in doc_col_info
                ]
                if existing_cols:
                    cursor.execute(
                        f"""
                        INSERT INTO document_metadata_v2 ({", ".join(existing_cols)}, updated_at)
                        SELECT {", ".join(existing_cols)}, created_at FROM document_metadata
                        """
                    )
                cursor.execute("DROP TABLE document_metadata")
                cursor.execute("ALTER TABLE document_metadata_v2 RENAME TO document_metadata")
                cursor.execute("PRAGMA foreign_keys = ON")
                logger.info("Database migration: updated document_metadata schema with user_id and nullable profile_id.")

            # Step 5.4A migration: Add document library columns if missing
            doc_cols_now = {
                row["name"]
                for row in cursor.execute("PRAGMA table_info(document_metadata)").fetchall()
            }
            if "document_category" not in doc_cols_now:
                cursor.execute("ALTER TABLE document_metadata ADD COLUMN document_category TEXT DEFAULT 'OTHER'")
            if "original_filename" not in doc_cols_now:
                cursor.execute("ALTER TABLE document_metadata ADD COLUMN original_filename TEXT")
            if "storage_reference" not in doc_cols_now:
                cursor.execute("ALTER TABLE document_metadata ADD COLUMN storage_reference TEXT")
            if "mime_type" not in doc_cols_now:
                cursor.execute("ALTER TABLE document_metadata ADD COLUMN mime_type TEXT")
            if "file_size" not in doc_cols_now:
                cursor.execute("ALTER TABLE document_metadata ADD COLUMN file_size INTEGER")
            if "confirmation_status" not in doc_cols_now:
                cursor.execute("ALTER TABLE document_metadata ADD COLUMN confirmation_status TEXT DEFAULT 'PENDING_CONFIRMATION'")

            # 4B. Confirmed document fields table (Step 5.3A, 5.3A.1, 5.3A.2 & 5.3A.3)
            # Check if confirmed_document_fields table exists and needs migration to append-only and foreign key on document_id
            table_sql_row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='confirmed_document_fields'"
            ).fetchone()
            if table_sql_row:
                fks = cursor.execute("PRAGMA foreign_key_list(confirmed_document_fields)").fetchall()
                has_doc_fk = any(
                    row["table"] == "document_metadata"
                    and row["from"] == "document_id"
                    and row["to"] == "document_id"
                    and (row["on_delete"] or "").upper() == "CASCADE"
                    for row in fks
                )
                has_unique = "UNIQUE(" in (table_sql_row["sql"] or "").replace(" ", "")

                if not has_doc_fk or has_unique:
                    cursor.execute("PRAGMA foreign_keys = OFF")

                    # Synthesize archived document stubs for any pre-existing orphaned records
                    # so referential integrity is immediately satisfied without dropping audit records.
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO document_metadata (
                            document_id, user_id, document_type, status, created_at, updated_at
                        )
                        SELECT DISTINCT
                            c.document_id,
                            CASE WHEN u.user_id IS NOT NULL THEN c.user_id ELSE NULL END,
                            'ARCHIVED_AUDIT',
                            'ARCHIVED',
                            c.confirmed_at,
                            c.updated_at
                        FROM confirmed_document_fields c
                        LEFT JOIN users u ON c.user_id = u.user_id
                        LEFT JOIN document_metadata d ON c.document_id = d.document_id
                        WHERE d.document_id IS NULL
                        """
                    )

                    cursor.execute(
                        """
                        CREATE TABLE confirmed_document_fields_v4 (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                            document_id TEXT NOT NULL REFERENCES document_metadata(document_id) ON DELETE CASCADE,
                            field_name TEXT NOT NULL,
                            field_value TEXT NOT NULL,
                            extracted_value TEXT,
                            is_corrected INTEGER NOT NULL DEFAULT 0,
                            is_confirmed INTEGER NOT NULL DEFAULT 1,
                            is_government_verified INTEGER NOT NULL DEFAULT 0,
                            confirmation_status TEXT NOT NULL DEFAULT 'CONFIRMED',
                            encrypted_value TEXT,
                            confirmed_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )

                    existing_cols = [
                        row["name"]
                        for row in cursor.execute("PRAGMA table_info(confirmed_document_fields)").fetchall()
                    ]
                    target_cols = [
                        "id", "user_id", "document_id", "field_name", "field_value", "extracted_value",
                        "is_corrected", "is_confirmed", "is_government_verified", "confirmation_status",
                        "encrypted_value", "confirmed_at", "updated_at"
                    ]
                    common_cols = [c for c in target_cols if c in existing_cols]

                    cursor.execute(
                        f"""
                        INSERT INTO confirmed_document_fields_v4 ({", ".join(common_cols)})
                        SELECT {", ".join(common_cols)}
                        FROM confirmed_document_fields
                        """
                    )
                    cursor.execute("DROP TABLE confirmed_document_fields")
                    cursor.execute("ALTER TABLE confirmed_document_fields_v4 RENAME TO confirmed_document_fields")
                    cursor.execute("PRAGMA foreign_keys = ON")
                    logger.info(
                        "Database migration: restored ON DELETE CASCADE foreign key on confirmed_document_fields(document_id)."
                    )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmed_document_fields (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES document_metadata(document_id) ON DELETE CASCADE,
                    field_name TEXT NOT NULL,
                    field_value TEXT NOT NULL,
                    extracted_value TEXT,
                    is_corrected INTEGER NOT NULL DEFAULT 0,
                    is_confirmed INTEGER NOT NULL DEFAULT 1,
                    is_government_verified INTEGER NOT NULL DEFAULT 0,
                    confirmation_status TEXT NOT NULL DEFAULT 'CONFIRMED',
                    encrypted_value TEXT,
                    confirmed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # 5. User sessions table for server-side cookie authentication.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    ip_address TEXT,
                    user_agent TEXT
                )
                """
            )

            # Useful indexes for account, profile, and session lookups.
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_users_account_status
                ON users(account_status)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_documents_profile_id
                ON document_metadata(profile_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_documents_user_id
                ON document_metadata(user_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_documents_category
                ON document_metadata(user_id, document_category)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_documents_status
                ON document_metadata(user_id, status)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_confirmed_fields_user_id
                ON confirmed_document_fields(user_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_confirmed_fields_document_id
                ON confirmed_document_fields(document_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_confirmed_fields_user_field
                ON confirmed_document_fields(user_id, field_name, confirmed_at DESC)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_confirmed_fields_doc_lookup
                ON confirmed_document_fields(user_id, document_id, field_name, confirmed_at DESC)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_sessions_user_id
                ON user_sessions(user_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_sessions_expires_at
                ON user_sessions(expires_at)
                """
            )

            # 6. Guest sessions table for temporary, privacy-preserving interactions (Phase 7).
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS guest_sessions (
                    session_id TEXT PRIMARY KEY,
                    guest_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    last_active_at TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    context_json TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_guest_sessions_guest_id
                ON guest_sessions(guest_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_guest_sessions_expires_at
                ON guest_sessions(expires_at)
                """
            )

            # 7. Chat conversations table for registered users (Phase 4C).
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_chat_conversations_user_id
                ON chat_conversations(user_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_chat_conversations_updated_at
                ON chat_conversations(updated_at)
                """
            )

            # 8. Chat messages table for registered users (Phase 4C).
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    citations_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_chat_messages_conversation_id
                ON chat_messages(conversation_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_chat_messages_created_at
                ON chat_messages(created_at)
                """
            )

            # 9. Scholarship Application Drafts table (Step 5.5A).
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS application_drafts (
                    draft_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    scheme_id TEXT NOT NULL,
                    application_year TEXT NOT NULL,
                    application_mode TEXT NOT NULL DEFAULT 'FRESH'
                        CHECK (application_mode IN ('FRESH', 'RENEWAL')),
                    status TEXT NOT NULL DEFAULT 'DRAFT'
                        CHECK (status IN (
                            'DRAFT',
                            'READY_FOR_REVIEW',
                            'READY_TO_CONTINUE',
                            'EXTERNAL_SUBMISSION_PENDING',
                            'SUBMITTED_EXTERNALLY',
                            'CLOSED'
                        )),
                    form_data_json TEXT NOT NULL DEFAULT '{}',
                    completion_percentage REAL NOT NULL DEFAULT 0.0,
                    last_saved_section TEXT,
                    external_portal_url TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_app_drafts_user_id
                ON application_drafts(user_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_app_drafts_scheme_id
                ON application_drafts(scheme_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_app_drafts_user_scheme
                ON application_drafts(user_id, scheme_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_app_drafts_status
                ON application_drafts(user_id, status)
                """
            )

            # 10. Extension Autofill Grants table (Step 5.5B).
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS autofill_grants (
                    grant_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    scheme_id TEXT NOT NULL,
                    draft_id TEXT REFERENCES application_drafts(draft_id) ON DELETE CASCADE,
                    portal_url TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'extension:autofill',
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_autofill_grants_token
                ON autofill_grants(token_hash)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_autofill_grants_user
                ON autofill_grants(user_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_autofill_grants_expires
                ON autofill_grants(expires_at)
                """
            )

            logger.info(
                "SahayAI database schema initialized successfully at %s",
                self.db_path,
            )
