
"""Citizen profile management module for SahayAI.

Handles CRUD operations on user profiles, user-confirmed information updates,
and document metadata persistence with strict PII protection. Provides clean
export interfaces for the separate recommendation engine.
"""

from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import uuid

from .database import Database

logger = logging.getLogger(__name__)


def mask_sensitive_value(key: str, val: Any) -> Any:
    """Mask Aadhaar or PAN values if detected, preserving masked format."""
    if val is None:
        return val
    str_val = str(val).strip()
    norm_key = key.lower().replace("-", "_")
    if "aadhaar" in norm_key:
        clean = re.sub(r"[\s\-_./\\,:~]+", "", str_val)
        if len(clean) == 12 and clean.isdigit():
            return f"XXXX-XXXX-{clean[-4:]}"
        if re.match(r"^XXXX-XXXX-\d{4}$", str_val, re.I) or re.match(r"^XXXXXXXX\d{4}$", str_val, re.I):
            return f"XXXX-XXXX-{clean[-4:]}"
        if len(clean) >= 8 and clean.isdigit():
            return f"XXXX-XXXX-{clean[-4:]}"
    elif "pan" in norm_key:
        clean = re.sub(r"[\s\-_./\\,:~]+", "", str_val).upper()
        if len(clean) == 10 and re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", clean):
            return f"XXXXX{clean[5:9]}X"
        if re.match(r"^XXXXX\d{4}X$", str_val, re.I):
            return str_val.upper()
    return mask_snippet_text(str_val)


def mask_snippet_text(text: str) -> str:
    """Mask Aadhaar and PAN patterns inside text snippets with full OCR variation support.

    Handles:
    - Standard and variably-spaced/punctuated Aadhaar numbers (hyphens, dots, slashes, commas, etc.).
    - Continuous 12-digit Aadhaar numbers.
    - PAN identifiers with optional spaces, hyphens, dots, or slashes between character groups.
    - Ambiguous or malformed sensitive patterns adjacent to identity keywords.
    """
    if not text:
        return ""

    # 1. Separated 12-digit Aadhaar (spaces, hyphens, dots, slashes, commas, colons, tildes)
    masked = re.sub(
        r"(?<!\d)\d{4}[\s\-_./\\,:~]+\d{4}[\s\-_./\\,:~]+(\d{4})(?!\d)",
        r"XXXX-XXXX-\1",
        text,
    )

    # 2. Continuous 12-digit Aadhaar
    masked = re.sub(
        r"(?<!\d)\d{8}(\d{4})(?!\d)",
        r"XXXX-XXXX-\1",
        masked,
    )

    # 3. PAN with optional whitespace, hyphens, dots, slashes, commas between segments
    masked = re.sub(
        r"(?<![A-Za-z0-9])[A-Za-z]{5}[\s\-_./\\,:~]*([0-9]{4})[\s\-_./\\,:~]*[A-Za-z](?![A-Za-z0-9])",
        r"XXXXX\1X",
        masked,
    )

    # 4. Keyword-anchored ambiguous/malformed Aadhaar patterns
    def _mask_ambiguous_aadhaar(m):
        prefix = m.group(1)
        tail = m.group(2)
        if "XXXX-XXXX-" in tail:
            return m.group(0)
        digits = re.sub(r"\D", "", tail)
        if len(digits) >= 8:
            return f"{prefix}: XXXX-XXXX-{digits[-4:]}"
        elif len(digits) >= 4:
            return f"{prefix}: [REDACTED_IDENTIFIER]"
        return m.group(0)

    masked = re.sub(
        r"(?i)\b(aadhaar|uidai|unique identification|mera aadhaar|uid)\s*[:#\-_./]?\s*([0-9\s\-_./\\,:~]{6,24})",
        _mask_ambiguous_aadhaar,
        masked,
    )

    # 5. Keyword-anchored ambiguous/malformed PAN patterns
    def _mask_ambiguous_pan(m):
        prefix = m.group(1)
        tail = m.group(2)
        if "XXXXX" in tail:
            return m.group(0)
        clean = re.sub(r"[\s\-_./\\,:~]", "", tail)
        if len(clean) >= 6:
            return f"{prefix}: [REDACTED_PAN]"
        return m.group(0)

    masked = re.sub(
        r"(?i)\b(pan|permanent account number)\s*[:#\-_./]?\s*([A-Za-z0-9\s\-_./\\,:~]{6,16})",
        _mask_ambiguous_pan,
        masked,
    )

    return masked


def sanitize_extracted_fields_for_storage(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure sensitive identifiers stored in SQLite metadata are masked or encrypted.

    Prevents accidental storage of plaintext Aadhaar or PAN in document metadata.
    """
    clean_fields: Dict[str, Any] = {}

    for key, item in fields.items():
        norm_key = key.lower().replace("-", "_")
        is_sensitive = "aadhaar" in norm_key or "pan" in norm_key

        if isinstance(item, dict):
            clean_item = dict(item)

            if is_sensitive:
                if "masked_display" in clean_item and clean_item["masked_display"]:
                    clean_item["value"] = clean_item["masked_display"]
                elif "value" in clean_item and clean_item["value"] is not None:
                    clean_item["value"] = mask_sensitive_value(key, clean_item["value"])

            # Also mask any evidence strings
            if "evidence" in clean_item and isinstance(clean_item["evidence"], str):
                clean_item["evidence"] = mask_snippet_text(clean_item["evidence"])

            clean_fields[key] = clean_item
        else:
            if is_sensitive:
                clean_fields[key] = mask_sensitive_value(key, item)
            elif isinstance(item, str):
                clean_fields[key] = mask_snippet_text(item)
            else:
                clean_fields[key] = item

    return clean_fields


class ProfileManager:
    """Manages citizen profiles, confirmation states, and associated document records."""

    def __init__(self, db: Optional[Database] = None):
        """Initialize ProfileManager.

        Args:
            db: Optional Database instance. Defaults to default Database.
        """
        self.db = db or Database()

    def create_profile(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new citizen profile and optionally link it to an account.

        Args:
            data: Citizen profile attributes, optionally including user_id.

        Returns:
            Created profile dictionary with assigned ID and timestamps.
        """
        now = datetime.now(timezone.utc).isoformat()
        profile_id = data.get("profile_id") or f"prof_{uuid.uuid4().hex[:10]}"

        profile_record = {
            "profile_id": profile_id,
            "user_id": data.get("user_id"),
            "full_name": data.get("full_name"),
            "date_of_birth": data.get("date_of_birth"),
            "age": data.get("age"),
            "gender": data.get("gender"),
            "state": data.get("state"),
            "district": data.get("district"),
            "annual_income": data.get("annual_income"),
            "occupation": data.get("occupation"),
            "caste_category": data.get("caste_category"),
            "is_bpl": 1 if data.get("is_bpl") else 0,
            "user_confirmed": 1 if data.get("user_confirmed") else 0,
            "metadata_json": json.dumps(
                sanitize_extracted_fields_for_storage(data.get("metadata", {}))
            ),
            "created_at": now,
            "updated_at": now,
        }

        query = """
            INSERT INTO profiles (
                profile_id, user_id, full_name, date_of_birth, age, gender,
                state, district, annual_income, occupation, caste_category,
                is_bpl, user_confirmed, metadata_json, created_at, updated_at
            ) VALUES (
                :profile_id, :user_id, :full_name, :date_of_birth, :age, :gender,
                :state, :district, :annual_income, :occupation, :caste_category,
                :is_bpl, :user_confirmed, :metadata_json, :created_at, :updated_at
            )
        """

        with self.db.get_connection() as conn:
            conn.execute(query, profile_record)

        logger.info("Created citizen profile record: %s", profile_id)

        return self.get_profile(profile_id) or profile_record

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a citizen profile by ID.

        Args:
            profile_id: Identifier of the profile.

        Returns:
            Profile dictionary or None if not found.
        """
        query = "SELECT * FROM profiles WHERE profile_id = ?"

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (profile_id,))
            row = cursor.fetchone()

            if not row:
                return None

            record = dict(row)
            record["is_bpl"] = bool(record["is_bpl"])
            record["user_confirmed"] = bool(record["user_confirmed"])

            if record.get("metadata_json"):
                try:
                    record["metadata"] = json.loads(record["metadata_json"])
                except json.JSONDecodeError:
                    record["metadata"] = {}

            return record

    def get_profile_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the citizen profile linked to an account.

        Args:
            user_id: Account identifier.

        Returns:
            Linked profile dictionary or None if not found.
        """
        if not user_id:
            return None

        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT profile_id FROM profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if not row:
            return None

        return self.get_profile(row["profile_id"])

    def update_profile(
        self,
        profile_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update fields on an existing citizen profile.

        Args:
            profile_id: Identifier of the profile to update.
            updates: Attributes to update.

        Returns:
            Updated profile dictionary or None if not found.
        """
        current = self.get_profile(profile_id)

        if not current:
            return None

        allowed_fields = [
            "full_name",
            "date_of_birth",
            "age",
            "gender",
            "state",
            "district",
            "annual_income",
            "occupation",
            "caste_category",
            "is_bpl",
            "user_confirmed",
        ]

        set_clauses: List[str] = []
        params: Dict[str, Any] = {"profile_id": profile_id}

        for field in allowed_fields:
            if field in updates:
                set_clauses.append(f"{field} = :{field}")
                val = updates[field]

                if field in ("is_bpl", "user_confirmed"):
                    val = 1 if val else 0

                params[field] = val

        if "metadata" in updates:
            set_clauses.append("metadata_json = :metadata_json")
            params["metadata_json"] = json.dumps(
                sanitize_extracted_fields_for_storage(updates["metadata"])
            )

        params["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clauses.append("updated_at = :updated_at")

        query = (
            f"UPDATE profiles SET {', '.join(set_clauses)} "
            "WHERE profile_id = :profile_id"
        )

        with self.db.get_connection() as conn:
            conn.execute(query, params)

        logger.info("Updated citizen profile: %s", profile_id)

        return self.get_profile(profile_id)

    def confirm_profile(
        self,
        profile_id: str,
        confirmed_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Save citizen-confirmed profile details and mark profile as confirmed.

        Args:
            profile_id: Identifier of the profile.
            confirmed_fields: Optional dictionary containing user-edited
                or verified attributes.

        Returns:
            Updated and confirmed profile dictionary.
        """
        updates = dict(confirmed_fields or {})
        updates["user_confirmed"] = True

        logger.info("Citizen confirmed profile data: %s", profile_id)

        return self.update_profile(profile_id, updates)

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a profile and cascade-delete associated document metadata.

        Args:
            profile_id: Profile ID to delete.

        Returns:
            True if profile existed and was deleted.
        """
        query = "DELETE FROM profiles WHERE profile_id = ?"

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (profile_id,))
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(
                "Deleted profile and cascade-deleted document metadata for: %s",
                profile_id,
            )

        return deleted

    def list_profiles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List stored citizen profiles up to limit."""
        query = "SELECT * FROM profiles ORDER BY created_at DESC LIMIT ?"

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (limit,))
            rows = cursor.fetchall()

            results = []

            for row in rows:
                rec = dict(row)
                rec["is_bpl"] = bool(rec["is_bpl"])
                rec["user_confirmed"] = bool(rec["user_confirmed"])
                results.append(rec)

            return results

    def save_document(
        self,
        document_id: str,
        user_id: str,
        document_type: str,
        extracted_fields: Dict[str, Any],
        profile_id: Optional[str] = None,
        file_path: Optional[str] = None,
        status: str = "PENDING_REVIEW",
        document_category: Optional[str] = None,
        original_filename: Optional[str] = None,
        storage_reference: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        confirmation_status: str = "PENDING_CONFIRMATION",
    ) -> str:
        """Store pending document extraction results and metadata for citizen review and confirmation.

        Args:
            document_id: Unique document identifier.
            user_id: Owner citizen user account ID.
            document_type: Category (AADHAAR_CARD, PAN_CARD, INCOME_CERTIFICATE, etc.).
            extracted_fields: Structured extraction results from OCR.
            profile_id: Optional linked citizen profile ID.
            file_path: Optional legacy temporary file path.
            status: Document lifecycle status.
            document_category: DocumentCategory taxonomy value. Auto-derived if None.
            original_filename: Sanitized original uploaded filename.
            storage_reference: Stored encrypted vault filename (no physical paths).
            mime_type: Detected MIME type.
            file_size: Size of original document in bytes.
            confirmation_status: Citizen confirmation status.

        Returns:
            document_id
        """
        from document_ai.categories import get_category_for_type, sanitize_filename
        now = datetime.now(timezone.utc).isoformat()
        sanitized_fields = sanitize_extracted_fields_for_storage(extracted_fields)

        cat = get_category_for_type(document_type, document_category)
        safe_orig_name = sanitize_filename(original_filename) if original_filename else None

        # Ensure temporary file paths are never persisted in document metadata
        clean_file_path = file_path
        if clean_file_path:
            norm_path = os.path.normpath(clean_file_path)
            is_temp = "temp_uploads" in norm_path or "tmp" in norm_path.lower()
            if is_temp or not os.path.exists(clean_file_path):
                clean_file_path = None

        storage_ref = storage_reference or (clean_file_path if clean_file_path and not clean_file_path.startswith("/") and not clean_file_path.startswith("\\") and "\\" not in clean_file_path and "/" not in clean_file_path else None)

        query = """
            INSERT INTO document_metadata (
                document_id, user_id, profile_id, document_category, document_type,
                original_filename, storage_reference, file_path, mime_type, file_size,
                extracted_fields_json, status, confirmation_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                user_id = excluded.user_id,
                profile_id = excluded.profile_id,
                document_category = excluded.document_category,
                document_type = excluded.document_type,
                original_filename = coalesce(excluded.original_filename, document_metadata.original_filename),
                storage_reference = coalesce(excluded.storage_reference, document_metadata.storage_reference),
                file_path = excluded.file_path,
                mime_type = coalesce(excluded.mime_type, document_metadata.mime_type),
                file_size = coalesce(excluded.file_size, document_metadata.file_size),
                extracted_fields_json = excluded.extracted_fields_json,
                status = excluded.status,
                confirmation_status = excluded.confirmation_status,
                updated_at = excluded.updated_at
        """

        with self.db.get_connection() as conn:
            conn.execute(
                query,
                (
                    document_id,
                    user_id,
                    profile_id,
                    cat,
                    document_type,
                    safe_orig_name,
                    storage_ref,
                    clean_file_path,
                    mime_type,
                    file_size,
                    json.dumps(sanitized_fields),
                    status,
                    confirmation_status,
                    now,
                    now,
                ),
            )

        logger.info(
            "Saved document metadata for user %s: doc_id=%s, type=%s, cat=%s, has_vault_ref=%s",
            user_id,
            document_id,
            document_type,
            cat,
            bool(storage_ref),
        )
        return document_id

    def get_document(
        self,
        document_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a document metadata record by document_id with optional user ownership check.

        Args:
            document_id: Identifier of the document.
            user_id: Optional user_id to enforce strict ownership verification.

        Returns:
            Document dictionary with parsed extracted_fields or None.
        """
        if user_id:
            query = "SELECT * FROM document_metadata WHERE document_id = ? AND user_id = ?"
            params = (document_id, user_id)
        else:
            query = "SELECT * FROM document_metadata WHERE document_id = ?"
            params = (document_id,)

        with self.db.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            if not row:
                return None

            doc = dict(row)
            if doc.get("extracted_fields_json"):
                try:
                    doc["extracted_fields"] = json.loads(doc["extracted_fields_json"])
                except json.JSONDecodeError:
                    doc["extracted_fields"] = {}
            else:
                doc["extracted_fields"] = {}

            doc["has_original_file"] = bool(doc.get("storage_reference"))

            return doc

    def get_user_documents(
        self,
        user_id: str,
        category: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve all documents belonging to a user account with optional category filter.

        Args:
            user_id: Account identifier.
            category: Optional document category filter.
            include_archived: If True, includes archived documents.

        Returns:
            List of document metadata dictionaries (physical paths omitted).
        """
        from document_ai.categories import normalize_document_category
        query = "SELECT * FROM document_metadata WHERE user_id = ?"
        params: List[Any] = [user_id]

        if not include_archived:
            query += " AND (status IS NULL OR status != 'ARCHIVED')"

        if category:
            norm_cat = normalize_document_category(category) or category.upper()
            query += " AND document_category = ?"
            params.append(norm_cat)

        query += " ORDER BY created_at DESC"

        with self.db.get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            docs = []
            for row in rows:
                doc = dict(row)
                if doc.get("extracted_fields_json"):
                    try:
                        doc["extracted_fields"] = json.loads(doc["extracted_fields_json"])
                    except json.JSONDecodeError:
                        doc["extracted_fields"] = {}
                else:
                    doc["extracted_fields"] = {}

                doc["has_original_file"] = bool(doc.get("storage_reference"))
                docs.append(doc)
            return docs

    def update_document_status(self, document_id: str, status: str) -> bool:
        """Update status flag on a document metadata record."""
        now = datetime.now(timezone.utc).isoformat()
        query = "UPDATE document_metadata SET status = ?, updated_at = ? WHERE document_id = ?"

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (status, now, document_id))
            return cursor.rowcount > 0

    def delete_document(
        self,
        document_id: str,
        user_id: Optional[str] = None,
        hard_delete: bool = True,
    ) -> bool:
        """Delete or archive a document record with referential integrity and file storage cleanup.

        Args:
            document_id: Unique document ID to delete or archive.
            user_id: Optional owner user ID for strict ownership check.
            hard_delete: If True, physically deletes the row from document_metadata,
                         which cascades (via ON DELETE CASCADE) to remove all associated
                         confirmed_document_fields rows, and unlinks the encrypted vault file.
                         If False, soft-deletes by setting status='ARCHIVED' and updating
                         updated_at, preserving document metadata and confirmation history.

        Returns:
            True if the document existed and was deleted/archived.
        """
        now = datetime.now(timezone.utc).isoformat()
        storage_ref = None

        with self.db.get_connection() as conn:
            # Query existing storage_reference before deletion
            if user_id:
                row = conn.execute(
                    "SELECT storage_reference FROM document_metadata WHERE document_id = ? AND user_id = ?",
                    (document_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT storage_reference FROM document_metadata WHERE document_id = ?",
                    (document_id,),
                ).fetchone()

            if row:
                storage_ref = row["storage_reference"]

            if hard_delete:
                if user_id:
                    cursor = conn.execute(
                        "DELETE FROM document_metadata WHERE document_id = ? AND user_id = ?",
                        (document_id, user_id),
                    )
                else:
                    cursor = conn.execute(
                        "DELETE FROM document_metadata WHERE document_id = ?",
                        (document_id,),
                    )
            else:
                if user_id:
                    cursor = conn.execute(
                        "UPDATE document_metadata SET status = 'ARCHIVED', updated_at = ? WHERE document_id = ? AND user_id = ?",
                        (now, document_id, user_id),
                    )
                else:
                    cursor = conn.execute(
                        "UPDATE document_metadata SET status = 'ARCHIVED', updated_at = ? WHERE document_id = ?",
                        (now, document_id),
                    )

            affected = cursor.rowcount > 0

        if affected:
            if hard_delete and storage_ref:
                try:
                    from document_ai.storage_vault import DocumentStorageVault
                    DocumentStorageVault().delete_file(storage_ref)
                except Exception as del_err:
                    logger.warning("Failed to delete encrypted vault file %s: %s", storage_ref, del_err)

            action = "hard deleted" if hard_delete else "archived"
            logger.info("Document %s was %s (user_id=%s)", document_id, action, user_id)

        return affected

    def save_confirmed_field(
        self,
        user_id: str,
        document_id: str,
        field_name: str,
        field_value: Any,
        extracted_value: Optional[Any] = None,
        is_corrected: bool = False,
        encrypted_value: Optional[str] = None,
        confirmation_status: str = "CONFIRMED",
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Persist an explicitly citizen-confirmed profile field with full audit metadata.

        Guarantees:
        - is_government_verified is strictly FALSE (0).
        - is_confirmed is TRUE (1).
        - Encrypted value stored when provided.
        - Timestamp recorded.
        - Sensitive fields (Aadhaar, PAN) are defensively masked in field_value.
        - Preserves historical records across different documents via (user_id, document_id, field_name).
        """
        now = datetime.now(timezone.utc).isoformat()
        rec_id = f"conf_{uuid.uuid4().hex[:12]}"

        # Defense-in-depth: Ensure sensitive identifiers never store plaintext in field_value
        norm_key = field_name.lower().replace("-", "_")
        if "aadhaar" in norm_key or "pan" in norm_key:
            field_value = mask_sensitive_value(field_name, field_value)
            if extracted_value is not None:
                extracted_value = mask_sensitive_value(field_name, extracted_value)

        str_val = str(field_value) if field_value is not None else ""
        str_ext_val = str(extracted_value) if extracted_value is not None else None

        # Check latest record for this user, document, and field
        check_query = """
            SELECT id, field_value, extracted_value, is_corrected, encrypted_value, confirmed_at
            FROM confirmed_document_fields
            WHERE user_id = :user_id AND document_id = :document_id AND field_name = :field_name
            ORDER BY confirmed_at DESC, rowid DESC LIMIT 1
        """
        check_params = {"user_id": user_id, "document_id": document_id, "field_name": field_name}

        if conn is not None:
            existing = conn.execute(check_query, check_params).fetchone()
        else:
            with self.db.get_connection() as c:
                existing = c.execute(check_query, check_params).fetchone()

        if existing:
            is_identical = (
                str(existing["field_value"]) == str_val
                and (
                    str(existing["extracted_value"]) == str_ext_val
                    if str_ext_val is not None
                    else (existing["extracted_value"] is None or str(existing["extracted_value"]) == "")
                )
                and bool(existing["is_corrected"]) == bool(is_corrected)
                and (
                    existing["encrypted_value"] == encrypted_value
                    or (not existing["encrypted_value"] and not encrypted_value)
                )
            )
            if is_identical:
                # Genuinely identical repeated request: preserve idempotency without creating duplicate row
                upd_query = "UPDATE confirmed_document_fields SET updated_at = :now WHERE id = :id"
                if conn is not None:
                    conn.execute(upd_query, {"now": now, "id": existing["id"]})
                else:
                    with self.db.get_connection() as c:
                        c.execute(upd_query, {"now": now, "id": existing["id"]})

                logger.info(
                    "Idempotent repeated confirmation for user %s: field=%s, doc=%s",
                    user_id,
                    field_name,
                    document_id,
                )
                return {
                    "field_name": field_name,
                    "value": field_value,
                    "field_value": field_value,
                    "extracted_value": extracted_value,
                    "source_document_id": document_id,
                    "is_corrected": bool(is_corrected),
                    "is_confirmed": True,
                    "is_government_verified": False,
                    "confirmation_status": confirmation_status,
                    "has_encrypted_value": bool(encrypted_value),
                    "confirmed_at": existing["confirmed_at"],
                }

        # New confirmation or amendment/correction: append new audit record
        ins_query = """
            INSERT INTO confirmed_document_fields (
                id, user_id, document_id, field_name, field_value, extracted_value,
                is_corrected, is_confirmed, is_government_verified, confirmation_status,
                encrypted_value, confirmed_at, updated_at
            ) VALUES (
                :id, :user_id, :document_id, :field_name, :field_value, :extracted_value,
                :is_corrected, 1, 0, :confirmation_status,
                :encrypted_value, :now, :now
            )
        """

        params = {
            "id": rec_id,
            "user_id": user_id,
            "document_id": document_id,
            "field_name": field_name,
            "field_value": str_val,
            "extracted_value": str_ext_val,
            "is_corrected": 1 if is_corrected else 0,
            "confirmation_status": confirmation_status,
            "encrypted_value": encrypted_value,
            "now": now,
        }

        if conn is not None:
            conn.execute(ins_query, params)
        else:
            with self.db.get_connection() as c:
                c.execute(ins_query, params)

        logger.info(
            "Saved confirmed field for user %s: field=%s, corrected=%s",
            user_id,
            field_name,
            is_corrected,
        )

        return {
            "field_name": field_name,
            "value": field_value,
            "field_value": field_value,
            "extracted_value": extracted_value,
            "source_document_id": document_id,
            "is_corrected": bool(is_corrected),
            "is_confirmed": True,
            "is_government_verified": False,
            "confirmation_status": confirmation_status,
            "has_encrypted_value": bool(encrypted_value),
            "confirmed_at": now,
        }

    def get_confirmed_fields_by_user(
        self,
        user_id: str,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Retrieve confirmed document fields for a citizen.

        Args:
            user_id: Account identifier.
            active_only: If True, returns the latest confirmed record for each field_name.
                         If False, returns all confirmation history.
        """
        if active_only:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY field_name
                            ORDER BY confirmed_at DESC, rowid DESC
                        ) as rn
                        FROM confirmed_document_fields
                        WHERE user_id = ?
                    ) WHERE rn = 1
                )
                ORDER BY confirmed_at DESC
            """
        else:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE user_id = ?
                ORDER BY confirmed_at DESC, rowid DESC
            """

        with self.db.get_connection() as conn:
            rows = conn.execute(query, (user_id,)).fetchall()
            results = []
            for row in rows:
                results.append({
                    "field_name": row["field_name"],
                    "value": row["field_value"],
                    "field_value": row["field_value"],
                    "extracted_value": row["extracted_value"],
                    "source_document_id": row["document_id"],
                    "is_corrected": bool(row["is_corrected"]),
                    "is_confirmed": bool(row["is_confirmed"]),
                    "is_government_verified": False,
                    "confirmation_status": row["confirmation_status"],
                    "has_encrypted_value": bool(row["encrypted_value"]),
                    "confirmed_at": row["confirmed_at"],
                })
            return results

    def get_active_confirmed_fields_with_documents(
        self,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve confirmed fields originating strictly from active, non-archived documents.

        Guarantees:
        - Archived documents are excluded (status != 'ARCHIVED').
        - Only confirmed records (is_confirmed = 1 and document confirmation_status = 'CONFIRMED' or status = 'CONFIRMED').
        - Returns latest confirmed record per field_name.
        - Joins document metadata (document_category, document_type, original_filename).
        """
        query = """
            SELECT c.id, c.user_id, c.document_id, c.field_name, c.field_value, c.extracted_value,
                   c.is_corrected, c.is_confirmed, c.is_government_verified, c.confirmation_status,
                   c.encrypted_value, c.confirmed_at,
                   d.document_category, d.document_type, d.original_filename, d.status as document_status
            FROM confirmed_document_fields c
            JOIN document_metadata d ON c.document_id = d.document_id
            WHERE c.user_id = ?
              AND c.is_confirmed = 1
              AND (d.status IS NULL OR d.status != 'ARCHIVED')
              AND (d.confirmation_status = 'CONFIRMED' OR d.status = 'CONFIRMED')
              AND c.id IN (
                  SELECT id FROM (
                      SELECT c2.id, ROW_NUMBER() OVER (
                          PARTITION BY c2.field_name
                          ORDER BY c2.confirmed_at DESC, c2.rowid DESC
                      ) as rn
                      FROM confirmed_document_fields c2
                      JOIN document_metadata d2 ON c2.document_id = d2.document_id
                      WHERE c2.user_id = ?
                        AND c2.is_confirmed = 1
                        AND (d2.status IS NULL OR d2.status != 'ARCHIVED')
                        AND (d2.confirmation_status = 'CONFIRMED' OR d2.status = 'CONFIRMED')
                  ) WHERE rn = 1
              )
            ORDER BY c.confirmed_at DESC
        """
        with self.db.get_connection() as conn:
            rows = conn.execute(query, (user_id, user_id)).fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "document_id": row["document_id"],
                    "field_name": row["field_name"],
                    "value": row["field_value"],
                    "field_value": row["field_value"],
                    "extracted_value": row["extracted_value"],
                    "source_document_id": row["document_id"],
                    "document_category": row["document_category"],
                    "document_type": row["document_type"],
                    "original_filename": row["original_filename"],
                    "document_status": row["document_status"],
                    "is_corrected": bool(row["is_corrected"]),
                    "is_confirmed": bool(row["is_confirmed"]),
                    "is_government_verified": False,
                    "confirmation_status": row["confirmation_status"],
                    "has_encrypted_value": bool(row["encrypted_value"]),
                    "confirmed_at": row["confirmed_at"],
                })
            return results

    def get_active_confirmed_fields_dict(
        self,
        user_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve active confirmed fields as a dictionary keyed by field_name."""
        fields_list = self.get_active_confirmed_fields_with_documents(user_id)
        return {item["field_name"]: item for item in fields_list}

    def get_confirmed_field(
        self,
        user_id: str,
        field_name: str,
        document_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a specific confirmed field for a citizen (latest by default)."""
        if document_id:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE user_id = ? AND field_name = ? AND document_id = ?
                ORDER BY confirmed_at DESC, rowid DESC LIMIT 1
            """
            params = (user_id, field_name, document_id)
        else:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE user_id = ? AND field_name = ?
                ORDER BY confirmed_at DESC, rowid DESC LIMIT 1
            """
            params = (user_id, field_name)

        with self.db.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            if not row:
                return None
            return {
                "field_name": row["field_name"],
                "value": row["field_value"],
                "field_value": row["field_value"],
                "extracted_value": row["extracted_value"],
                "source_document_id": row["document_id"],
                "is_corrected": bool(row["is_corrected"]),
                "is_confirmed": bool(row["is_confirmed"]),
                "is_government_verified": False,
                "confirmation_status": row["confirmation_status"],
                "has_encrypted_value": bool(row["encrypted_value"]),
                "confirmed_at": row["confirmed_at"],
            }

    def get_confirmed_fields_by_document(
        self,
        document_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve confirmed fields for a specific document_id.

        Returns a dictionary mapping field_name to its confirmed field record.
        """
        if user_id:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE document_id = ? AND user_id = ?
                ORDER BY confirmed_at ASC, rowid ASC
            """
            params = (document_id, user_id)
        else:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE document_id = ?
                ORDER BY confirmed_at ASC, rowid ASC
            """
            params = (document_id,)

        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = {}
            for row in rows:
                results[row["field_name"]] = {
                    "field_name": row["field_name"],
                    "value": row["field_value"],
                    "field_value": row["field_value"],
                    "extracted_value": row["extracted_value"],
                    "source_document_id": row["document_id"],
                    "is_corrected": bool(row["is_corrected"]),
                    "is_confirmed": bool(row["is_confirmed"]),
                    "is_government_verified": False,
                    "confirmation_status": row["confirmation_status"],
                    "has_encrypted_value": bool(row["encrypted_value"]),
                    "confirmed_at": row["confirmed_at"],
                }
            return results

    def get_confirmation_history(
        self,
        user_id: str,
        field_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve full historical audit records of all citizen confirmations.

        Preserves chronological history across multiple documents and updates.
        """
        if field_name:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE user_id = ? AND field_name = ?
                ORDER BY confirmed_at DESC, rowid DESC
            """
            params = (user_id, field_name)
        else:
            query = """
                SELECT field_name, field_value, extracted_value, document_id,
                       is_corrected, is_confirmed, is_government_verified,
                       confirmation_status, encrypted_value, confirmed_at
                FROM confirmed_document_fields
                WHERE user_id = ?
                ORDER BY confirmed_at DESC, rowid DESC
            """
            params = (user_id,)

        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "field_name": row["field_name"],
                    "value": row["field_value"],
                    "field_value": row["field_value"],
                    "extracted_value": row["extracted_value"],
                    "source_document_id": row["document_id"],
                    "is_corrected": bool(row["is_corrected"]),
                    "is_confirmed": bool(row["is_confirmed"]),
                    "is_government_verified": False,
                    "confirmation_status": row["confirmation_status"],
                    "has_encrypted_value": bool(row["encrypted_value"]),
                    "confirmed_at": row["confirmed_at"],
                }
                for row in rows
            ]

    def get_decrypted_confirmed_field(
        self,
        user_id: str,
        field_name: str,
        document_id: Optional[str] = None,
        vault: Optional[Any] = None,
    ) -> Optional[str]:
        """Retrieve and decrypt a sensitive confirmed identifier (Aadhaar, PAN) using PIIVault.

        Fails closed: raises RuntimeError if encryption key is not configured or decryption fails.
        """
        if document_id:
            query = """
                SELECT encrypted_value
                FROM confirmed_document_fields
                WHERE user_id = ? AND field_name = ? AND document_id = ?
                ORDER BY confirmed_at DESC, rowid DESC LIMIT 1
            """
            params = (user_id, field_name, document_id)
        else:
            query = """
                SELECT encrypted_value
                FROM confirmed_document_fields
                WHERE user_id = ? AND field_name = ?
                ORDER BY confirmed_at DESC, rowid DESC LIMIT 1
            """
            params = (user_id, field_name)

        with self.db.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            if not row or not row["encrypted_value"]:
                return None

            ciphertext = row["encrypted_value"]

        from document_ai.extract_fields import PIIVault
        active_vault = vault or PIIVault()
        if not active_vault.is_configured:
            raise RuntimeError(
                f"PIIVault encryption key is not configured. Cannot decrypt '{field_name}'. Failed closed."
            )

        return active_vault.decrypt(ciphertext)

    def confirm_and_persist_transactional(
        self,
        user_id: str,
        document_id: str,
        confirmed_items: List[Dict[str, Any]],
        profile_updates: Dict[str, Any],
        new_document_status: str = "CONFIRMED",
    ) -> Dict[str, Any]:
        """Atomically persist confirmed fields, update profile, and update document status.

        Guarantees:
        - All operations execute in a single SQLite transaction.
        - If any step fails, the entire transaction is rolled back.
        - Zero partial persistence or inconsistent database state.
        """
        now = datetime.now(timezone.utc).isoformat()

        with self.db.get_connection() as conn:
            # 1. Save all confirmed fields in the transaction
            saved_records: Dict[str, Any] = {}
            for item in confirmed_items:
                fname = item["field_name"]
                fval = item["field_value"]
                extracted_val = item.get("extracted_value")
                is_corrected = item.get("is_corrected", False)
                encrypted_val = item.get("encrypted_value")
                confirmation_status = item.get("confirmation_status", "CONFIRMED")

                # Mask sensitive field values defensively
                norm_key = fname.lower().replace("-", "_")
                if "aadhaar" in norm_key or "pan" in norm_key:
                    fval = mask_sensitive_value(fname, fval)
                    if extracted_val is not None:
                        extracted_val = mask_sensitive_value(fname, extracted_val)

                str_val = str(fval) if fval is not None else ""
                str_ext_val = str(extracted_val) if extracted_val is not None else None

                # Check latest record for this user, document, and field
                check_query = """
                    SELECT id, field_value, extracted_value, is_corrected, encrypted_value, confirmed_at
                    FROM confirmed_document_fields
                    WHERE user_id = :user_id AND document_id = :document_id AND field_name = :field_name
                    ORDER BY confirmed_at DESC, rowid DESC LIMIT 1
                """
                check_params = {"user_id": user_id, "document_id": document_id, "field_name": fname}
                existing = conn.execute(check_query, check_params).fetchone()

                if existing:
                    is_identical = (
                        str(existing["field_value"]) == str_val
                        and (
                            str(existing["extracted_value"]) == str_ext_val
                            if str_ext_val is not None
                            else (existing["extracted_value"] is None or str(existing["extracted_value"]) == "")
                        )
                        and bool(existing["is_corrected"]) == bool(is_corrected)
                        and (
                            existing["encrypted_value"] == encrypted_val
                            or (not existing["encrypted_value"] and not encrypted_val)
                        )
                    )
                    if is_identical:
                        # Genuinely identical repeated request: preserve idempotency without creating duplicate row
                        conn.execute(
                            "UPDATE confirmed_document_fields SET updated_at = :now WHERE id = :id",
                            {"now": now, "id": existing["id"]},
                        )
                        saved_records[fname] = {
                            "field_name": fname,
                            "value": fval,
                            "field_value": fval,
                            "extracted_value": extracted_val,
                            "source_document_id": document_id,
                            "is_corrected": bool(is_corrected),
                            "is_confirmed": True,
                            "is_government_verified": False,
                            "confirmation_status": confirmation_status,
                            "has_encrypted_value": bool(encrypted_val),
                            "confirmed_at": existing["confirmed_at"],
                        }
                        continue

                # New confirmation or amendment/correction: append new audit record
                rec_id = f"conf_{uuid.uuid4().hex[:12]}"
                ins_query = """
                    INSERT INTO confirmed_document_fields (
                        id, user_id, document_id, field_name, field_value, extracted_value,
                        is_corrected, is_confirmed, is_government_verified, confirmation_status,
                        encrypted_value, confirmed_at, updated_at
                    ) VALUES (
                        :id, :user_id, :document_id, :field_name, :field_value, :extracted_value,
                        :is_corrected, 1, 0, :confirmation_status,
                        :encrypted_value, :now, :now
                    )
                """
                params = {
                    "id": rec_id,
                    "user_id": user_id,
                    "document_id": document_id,
                    "field_name": fname,
                    "field_value": str_val,
                    "extracted_value": str_ext_val,
                    "is_corrected": 1 if is_corrected else 0,
                    "confirmation_status": confirmation_status,
                    "encrypted_value": encrypted_val,
                    "now": now,
                }
                conn.execute(ins_query, params)
                saved_records[fname] = {
                    "field_name": fname,
                    "value": fval,
                    "field_value": fval,
                    "extracted_value": extracted_val,
                    "source_document_id": document_id,
                    "is_corrected": bool(is_corrected),
                    "is_confirmed": True,
                    "is_government_verified": False,
                    "confirmation_status": confirmation_status,
                    "has_encrypted_value": bool(encrypted_val),
                    "confirmed_at": now,
                }

            # 2. Update or create citizen profile in the same transaction
            saved_profile = None
            if profile_updates:
                p_row = conn.execute("SELECT profile_id FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
                if p_row:
                    profile_id = p_row["profile_id"]
                    allowed_fields = [
                        "full_name", "date_of_birth", "age", "gender", "state", "district",
                        "annual_income", "occupation", "caste_category", "is_bpl", "user_confirmed",
                    ]
                    set_clauses: List[str] = []
                    up_params: Dict[str, Any] = {"profile_id": profile_id}
                    for f in allowed_fields:
                        if f in profile_updates:
                            set_clauses.append(f"{f} = :{f}")
                            val = profile_updates[f]
                            if f in ("is_bpl", "user_confirmed"):
                                val = 1 if val else 0
                            up_params[f] = val

                    if "metadata" in profile_updates:
                        set_clauses.append("metadata_json = :metadata_json")
                        up_params["metadata_json"] = json.dumps(
                            sanitize_extracted_fields_for_storage(profile_updates["metadata"])
                        )

                    up_params["updated_at"] = now
                    set_clauses.append("updated_at = :updated_at")
                    up_query = f"UPDATE profiles SET {', '.join(set_clauses)} WHERE profile_id = :profile_id"
                    conn.execute(up_query, up_params)
                else:
                    profile_id = f"prof_{uuid.uuid4().hex[:10]}"
                    clean_meta = sanitize_extracted_fields_for_storage(profile_updates.get("metadata", {}))
                    p_rec = {
                        "profile_id": profile_id,
                        "user_id": user_id,
                        "full_name": profile_updates.get("full_name"),
                        "date_of_birth": profile_updates.get("date_of_birth"),
                        "age": profile_updates.get("age"),
                        "gender": profile_updates.get("gender"),
                        "state": profile_updates.get("state"),
                        "district": profile_updates.get("district"),
                        "annual_income": profile_updates.get("annual_income"),
                        "occupation": profile_updates.get("occupation"),
                        "caste_category": profile_updates.get("caste_category"),
                        "is_bpl": 1 if profile_updates.get("is_bpl") else 0,
                        "user_confirmed": 1 if profile_updates.get("user_confirmed") else 0,
                        "metadata_json": json.dumps(clean_meta),
                        "created_at": now,
                        "updated_at": now,
                    }
                    in_query = """
                        INSERT INTO profiles (
                            profile_id, user_id, full_name, date_of_birth, age, gender,
                            state, district, annual_income, occupation, caste_category,
                            is_bpl, user_confirmed, metadata_json, created_at, updated_at
                        ) VALUES (
                            :profile_id, :user_id, :full_name, :date_of_birth, :age, :gender,
                            :state, :district, :annual_income, :occupation, :caste_category,
                            :is_bpl, :user_confirmed, :metadata_json, :created_at, :updated_at
                        )
                    """
                    conn.execute(in_query, p_rec)

                prof_row = conn.execute("SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()
                if prof_row:
                    saved_profile = dict(prof_row)
                    saved_profile["is_bpl"] = bool(saved_profile["is_bpl"])
                    saved_profile["user_confirmed"] = bool(saved_profile["user_confirmed"])
            else:
                p_row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
                if p_row:
                    saved_profile = dict(p_row)
                    saved_profile["is_bpl"] = bool(saved_profile["is_bpl"])
                    saved_profile["user_confirmed"] = bool(saved_profile["user_confirmed"])

            # 3. Update document status in the same transaction
            doc_query = "UPDATE document_metadata SET status = ?, confirmation_status = 'CONFIRMED', updated_at = ? WHERE document_id = ?"
            conn.execute(doc_query, (new_document_status, now, document_id))

        return {
            "saved_fields": saved_records,
            "profile": saved_profile,
        }

    def save_document_metadata(
        self,
        profile_id: str,
        document_type: str,
        file_path: str,
        extracted_fields: Dict[str, Any],
        status: str = "PROCESSED",
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> str:
        """Store document metadata with sensitive PII sanitized.

        Args:
            profile_id: Citizen profile ID.
            document_type: Category (AADHAAR_CARD, PAN_CARD, etc.).
            file_path: Path where document is stored.
            extracted_fields: Structured extraction results.
            status: Processing status flag.
            user_id: Optional user account ID.
            document_id: Optional explicit document ID.

        Returns:
            Assigned document_id.
        """
        doc_id = document_id or f"doc_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()

        if not user_id and profile_id:
            with self.db.get_connection() as conn:
                p_row = conn.execute("SELECT user_id FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()
                if p_row and p_row["user_id"]:
                    user_id = p_row["user_id"]

        sanitized_fields = sanitize_extracted_fields_for_storage(
            extracted_fields
        )

        clean_file_path = file_path
        if clean_file_path:
            norm_path = os.path.normpath(clean_file_path)
            is_temp = "temp_uploads" in norm_path or "tmp" in norm_path.lower()
            if is_temp or not os.path.exists(clean_file_path):
                clean_file_path = None

        query = """
            INSERT INTO document_metadata (
                document_id, user_id, profile_id, document_type, file_path,
                extracted_fields_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        with self.db.get_connection() as conn:
            conn.execute(
                query,
                (
                    doc_id,
                    user_id,
                    profile_id,
                    document_type,
                    clean_file_path,
                    json.dumps(sanitized_fields),
                    status,
                    now,
                    now,
                ),
            )

        logger.info(
            "Saved document metadata: %s for profile: %s",
            doc_id,
            profile_id,
        )

        return doc_id

    def get_profile_documents(self, profile_id: str) -> List[Dict[str, Any]]:
        """Retrieve all document metadata records attached to a profile."""
        query = """
            SELECT * FROM document_metadata
            WHERE profile_id = ?
            ORDER BY created_at DESC
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (profile_id,))
            rows = cursor.fetchall()

            docs = []

            for row in rows:
                doc = dict(row)

                if doc.get("extracted_fields_json"):
                    try:
                        doc["extracted_fields"] = json.loads(
                            doc["extracted_fields_json"]
                        )
                    except json.JSONDecodeError:
                        doc["extracted_fields"] = {}

                docs.append(doc)

            return docs

    def get_profile_for_recommendation(
        self,
        profile_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Expose standardized citizen attributes for scheme recommendations.

        Args:
            profile_id: Identifier of the profile.

        Returns:
            Normalized eligibility profile or None if profile does not exist.
        """
        profile = self.get_profile(profile_id)

        if not profile:
            return None

        return {
            "profile_id": profile["profile_id"],
            "age": profile.get("age"),
            "gender": profile.get("gender"),
            "state": profile.get("state"),
            "district": profile.get("district"),
            "annual_income": profile.get("annual_income"),
            "occupation": profile.get("occupation"),
            "caste_category": profile.get("caste_category"),
            "is_bpl": profile.get("is_bpl", False),
            "user_confirmed": profile.get("user_confirmed", False),
        }
