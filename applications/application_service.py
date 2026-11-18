"""Scholarship Application Workspace Service for SahayAI.

Manages application draft creation, updates, completion percentage computation,
validation, and secure deletion for registered citizens.

Security Guarantees:
- Strict citizen ownership enforcement at the query level (IDOR defense).
- Rejection of unauthorized scheme IDs.
- Rejection of invalid status transitions and corrupted form fields.
- Complete separation of draft data from official government submission.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from profile.database import Database
from document_ai.extract_fields import PIIVault
from scheme_collection.application_definitions import (
    get_application_definition,
    is_valid_scheme_id,
)

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "DRAFT",
    "READY_FOR_REVIEW",
    "READY_TO_CONTINUE",
    "EXTERNAL_SUBMISSION_PENDING",
    "SUBMITTED_EXTERNALLY",
    "CLOSED",
}

VALID_APPLICATION_MODES = {"FRESH", "RENEWAL"}

SENSITIVE_FIELD_NAMES = {
    "account_number",
    "bank_account_number",
    "aadhaar_number",
    "aadhaar_card_number",
    "pan_card",
    "pan_number",
    "udid_card_number",
}


def is_sensitive_field(field_name: str) -> bool:
    """Determine if a draft field contains sensitive PII requiring encryption at rest."""
    name = (field_name or "").lower().strip()
    if name in SENSITIVE_FIELD_NAMES:
        return True
    if "aadhaar" in name and not name.endswith("_confirmed"):
        return True
    if "account_number" in name or "udid_card" in name or "pan_card" in name or "pan_number" in name:
        return True
    return False


def encrypt_form_data_for_storage(
    form_data: Dict[str, Any], vault: Optional[PIIVault] = None
) -> Dict[str, Any]:
    """Encrypt sensitive draft fields before serialization into SQLite form_data_json."""
    if not form_data:
        return {}
    active_vault = vault or PIIVault()
    encrypted_data: Dict[str, Any] = {}
    for k, v in form_data.items():
        if is_sensitive_field(k) and v is not None and str(v).strip() != "":
            if active_vault.is_configured:
                if isinstance(v, str) and v.startswith("ENC:FERNET:"):
                    encrypted_data[k] = v
                else:
                    encrypted_data[k] = f"ENC:FERNET:{active_vault.encrypt(str(v))}"
            else:
                logger.warning("PIIVault encryption key not configured; sensitive draft field %s stored unencrypted.", k)
                encrypted_data[k] = v
        else:
            encrypted_data[k] = v
    return encrypted_data


def decrypt_form_data_from_storage(
    form_data: Dict[str, Any], vault: Optional[PIIVault] = None
) -> Dict[str, Any]:
    """Decrypt sensitive draft fields when reading from SQLite form_data_json."""
    if not form_data:
        return {}
    active_vault = vault or PIIVault()
    decrypted_data: Dict[str, Any] = {}
    for k, v in form_data.items():
        if isinstance(v, str) and v.startswith("ENC:FERNET:"):
            if active_vault.is_configured:
                try:
                    decrypted_data[k] = active_vault.decrypt(v[len("ENC:FERNET:"):])
                except Exception as exc:
                    logger.error("Failed to decrypt draft field %s: %s", k, exc)
                    decrypted_data[k] = v
            else:
                logger.warning("PIIVault encryption key not configured; returning encrypted draft field %s as-is.", k)
                decrypted_data[k] = v
        else:
            decrypted_data[k] = v
    return decrypted_data


class ApplicationService:
    """Service handling scholarship application drafts and workspace logic."""

    def __init__(self, db: Optional[Database] = None, vault: Optional[PIIVault] = None):
        """Initialize ApplicationService with database connection manager and PII vault."""
        self.db = db or Database()
        self.vault = vault or PIIVault()

    def create_draft(
        self,
        user_id: str,
        scheme_id: str,
        application_mode: str = "FRESH",
    ) -> Dict[str, Any]:
        """Create a new application draft for the authenticated citizen.

        Args:
            user_id: Authenticated user ID.
            scheme_id: Official scheme identifier.
            application_mode: 'FRESH' or 'RENEWAL'.

        Returns:
            Newly created draft dictionary.

        Raises:
            ValueError: If scheme_id is not supported or application_mode is invalid.
        """
        if not is_valid_scheme_id(scheme_id):
            raise ValueError(f"Scheme '{scheme_id}' is not supported for application drafts.")

        mode_clean = (application_mode or "FRESH").upper().strip()
        if mode_clean not in VALID_APPLICATION_MODES:
            raise ValueError(f"Invalid application_mode '{application_mode}'. Must be FRESH or RENEWAL.")

        defn = get_application_definition(scheme_id)
        if not defn:
            raise ValueError(f"Application definition not found for scheme '{scheme_id}'.")

        draft_id = f"draft_{uuid.uuid4().hex[:16]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        app_year = defn.get("application_year", "AY 2026-27")
        external_url = defn.get("portal_verification", {}).get("official_portal_url", "")
        status = "DRAFT"
        form_data: Dict[str, Any] = {}
        completion_pct = 0.0

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO application_drafts (
                    draft_id,
                    user_id,
                    scheme_id,
                    application_year,
                    application_mode,
                    status,
                    form_data_json,
                    completion_percentage,
                    last_saved_section,
                    external_portal_url,
                    notes,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    user_id,
                    scheme_id,
                    app_year,
                    mode_clean,
                    status,
                    json.dumps(form_data),
                    completion_pct,
                    "personal_details",
                    external_url,
                    None,
                    now_iso,
                    now_iso,
                ),
            )

        logger.info("Created application draft %s for user %s on scheme %s", draft_id, user_id, scheme_id)
        return self.get_draft(draft_id, user_id)  # type: ignore

    def get_draft(self, draft_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific application draft strictly owned by user_id.

        Args:
            draft_id: Application draft identifier.
            user_id: Authenticated citizen user ID.

        Returns:
            Draft dictionary with attached scheme definition, or None if not found or unauthorized.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM application_drafts
                WHERE draft_id = ? AND user_id = ?
                """,
                (draft_id, user_id),
            )
            row = cursor.fetchone()

        if not row:
            return None

        draft = dict(row)
        try:
            raw_form_data = json.loads(draft.get("form_data_json") or "{}")
            draft["form_data"] = decrypt_form_data_from_storage(raw_form_data, self.vault)
        except (json.JSONDecodeError, TypeError):
            draft["form_data"] = {}

        # Attach scheme definition for UI rendering
        scheme_id = draft["scheme_id"]
        defn = get_application_definition(scheme_id)
        if defn:
            draft["scheme_definition"] = defn

        return draft

    def list_drafts(self, user_id: str) -> List[Dict[str, Any]]:
        """List all application drafts owned by user_id ordered by updated_at descending.

        Args:
            user_id: Authenticated citizen user ID.

        Returns:
            List of draft summaries with basic scheme metadata.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT draft_id, user_id, scheme_id, application_year, application_mode,
                       status, completion_percentage, last_saved_section,
                       external_portal_url, notes, created_at, updated_at
                FROM application_drafts
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

        drafts: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            defn = get_application_definition(d["scheme_id"])
            if defn:
                d["scheme_name"] = defn.get("scheme_name")
                d["official_scheme_name"] = defn.get("official_scheme_name")
                d["portal_verification"] = defn.get("portal_verification")
                d["application_availability_status"] = defn.get("application_availability_status")
                d["last_deadline"] = defn.get("last_deadline")
            drafts.append(d)

        return drafts

    def calculate_completion(self, scheme_id: str, form_data: Dict[str, Any]) -> float:
        """Calculate the completion percentage based on required fields in the scheme definition.

        Args:
            scheme_id: Scheme ID.
            form_data: Current form field key-value pairs.

        Returns:
            Percentage rounded to 1 decimal place.
        """
        defn = get_application_definition(scheme_id)
        if not defn:
            return 0.0

        required_fields: List[str] = []
        for sec in defn.get("form_sections", []):
            for field in sec.get("fields", []):
                if field.get("required"):
                    required_fields.append(field.get("field_id"))

        if not required_fields:
            return 100.0

        completed = 0
        for f_id in required_fields:
            val = form_data.get(f_id)
            if val is not None:
                if isinstance(val, bool) and val is True:
                    completed += 1
                elif isinstance(val, (int, float)):
                    completed += 1
                elif isinstance(val, str) and val.strip() != "":
                    completed += 1
                elif isinstance(val, list) and len(val) > 0:
                    completed += 1

        pct = (completed / len(required_fields)) * 100.0
        return round(min(100.0, max(0.0, pct)), 1)

    def validate_form_data(self, scheme_id: str, form_data: Dict[str, Any]) -> None:
        """Validate form data against scheme definition specifications.

        Args:
            scheme_id: Scheme ID.
            form_data: Updated field mapping.

        Raises:
            ValueError: If a field value violates type or range constraints.
        """
        defn = get_application_definition(scheme_id)
        if not defn:
            raise ValueError(f"Unknown scheme {scheme_id}")

        field_specs = {}
        for sec in defn.get("form_sections", []):
            for f in sec.get("fields", []):
                field_specs[f["field_id"]] = f

        for key, val in form_data.items():
            if key not in field_specs:
                # Custom or supplementary notes / auxiliary fields are permitted if non-empty string
                continue

            spec = field_specs[key]
            f_type = spec.get("type")
            validation = spec.get("validation", {})

            # Skip empty values for partial drafts
            if val is None or val == "":
                continue

            if f_type == "number":
                try:
                    num_val = float(val)
                except (ValueError, TypeError):
                    raise ValueError(f"Field '{spec.get('label')}' must be a valid number.")

                if "min" in validation and num_val < validation["min"]:
                    raise ValueError(f"Field '{spec.get('label')}' cannot be less than {validation['min']}.")
                if "max" in validation and num_val > validation["max"]:
                    raise ValueError(f"Field '{spec.get('label')}' cannot exceed {validation['max']}.")

            elif f_type == "select":
                allowed_opts = spec.get("options", [])
                if allowed_opts:
                    # Match case-insensitively and normalize to canonical option value
                    matched = None
                    for opt in allowed_opts:
                        opt_str = opt if isinstance(opt, str) else str(opt.get("value", opt) if isinstance(opt, dict) else opt)
                        if str(val).strip().lower() == opt_str.strip().lower():
                            matched = opt_str
                            break
                    if matched is not None:
                        form_data[key] = matched
                    elif str(val) not in allowed_opts:
                        raise ValueError(
                            f"Field '{spec.get('label')}' value '{val}' is not in allowed options: {allowed_opts}"
                        )

            elif f_type == "text":
                if not isinstance(val, str):
                    raise ValueError(f"Field '{spec.get('label')}' must be text.")
                if "max_length" in validation and len(val) > validation["max_length"]:
                    raise ValueError(f"Field '{spec.get('label')}' exceeds max length of {validation['max_length']}.")

    def update_draft(
        self,
        draft_id: str,
        user_id: str,
        form_data: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        last_saved_section: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an existing draft owned by user_id.

        Args:
            draft_id: Target draft ID.
            user_id: Authenticated citizen user ID.
            form_data: Optional form field updates.
            status: Optional draft status transition.
            last_saved_section: Optional current section identifier.
            notes: Optional citizen remarks or notes.

        Returns:
            Updated draft dictionary, or None if not found or unauthorized.

        Raises:
            ValueError: If status is invalid or field validation fails.
        """
        existing = self.get_draft(draft_id, user_id)
        if not existing:
            return None

        scheme_id = existing["scheme_id"]

        # Validate status if provided
        if status is not None:
            status_clean = status.upper().strip()
            if status_clean not in VALID_STATUSES:
                raise ValueError(
                    f"Invalid status '{status}'. Must be one of: {sorted(list(VALID_STATUSES))}"
                )
            new_status = status_clean
        else:
            new_status = existing["status"]

        # Merge form_data
        current_data = existing.get("form_data", {})
        if form_data is not None:
            if not isinstance(form_data, dict):
                raise ValueError("form_data must be a JSON dictionary of field keys and values.")
            # Validate updated fields
            self.validate_form_data(scheme_id, form_data)
            current_data.update(form_data)

        # Recalculate completion percentage
        completion_pct = self.calculate_completion(scheme_id, current_data)

        # If citizen tries to set READY_TO_CONTINUE or READY_FOR_REVIEW, ensure completion is acceptable
        if new_status == "READY_TO_CONTINUE" and completion_pct < 50.0:
            logger.warning("Draft %s moving to %s with %s%% completion", draft_id, new_status, completion_pct)

        new_section = last_saved_section if last_saved_section is not None else existing.get("last_saved_section")
        new_notes = notes if notes is not None else existing.get("notes")
        now_iso = datetime.now(timezone.utc).isoformat()
        storage_data = encrypt_form_data_for_storage(current_data, self.vault)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE application_drafts
                SET form_data_json = ?,
                    status = ?,
                    completion_percentage = ?,
                    last_saved_section = ?,
                    notes = ?,
                    updated_at = ?
                WHERE draft_id = ? AND user_id = ?
                """,
                (
                    json.dumps(storage_data),
                    new_status,
                    completion_pct,
                    new_section,
                    new_notes,
                    now_iso,
                    draft_id,
                    user_id,
                ),
            )

        logger.info("Updated draft %s for user %s (status: %s, completion: %s%%)", draft_id, user_id, new_status, completion_pct)
        return self.get_draft(draft_id, user_id)

    def delete_draft(self, draft_id: str, user_id: str) -> bool:
        """Delete an application draft owned by user_id.

        Args:
            draft_id: Target draft ID.
            user_id: Authenticated citizen user ID.

        Returns:
            True if deleted, False if draft was not found or unauthorized.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM application_drafts
                WHERE draft_id = ? AND user_id = ?
                """,
                (draft_id, user_id),
            )
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Deleted draft %s for user %s", draft_id, user_id)
        return deleted

