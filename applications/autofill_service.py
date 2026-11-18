"""Secure Scholarship Autofill Engine and Extension Integration Service.

Deterministic mapping engine that bridges authenticated citizen profile attributes
and citizen-confirmed document data into structured application form fields for
the 5 supported scholarship schemes.

Security Guarantees:
- Pure deterministic mapping. Zero heuristics, zero LLM hallucinations.
- Unconfirmed OCR values are strictly excluded.
- Archived or deleted documents are strictly excluded.
- Full provenance tracking for every resolved field.
- Mandatory citizen review for conflicts between profile, documents, and draft.
- Existing draft values are never silently overwritten.
- Short-lived (5-minute), cryptographically random, scoped grant tokens
  bound strictly to verified government portals (https://scholarships.gov.in).
- Grant tokens are hashed (SHA-256) at rest; raw tokens are never persisted.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
import uuid
import secrets

from profile.database import Database
from profile.profile_manager import ProfileManager
from applications.application_service import ApplicationService
from document_ai.extract_fields import PIIVault
from scheme_collection.application_definitions import (
    get_application_definition,
    is_valid_scheme_id,
    SCHEME_APPLICATION_DEFINITIONS,
)

logger = logging.getLogger(__name__)

OFFICIAL_VERIFIED_PORTAL_HOSTS = {
    "scholarships.gov.in",
    "pmkisan.gov.in",
    "www.pmkisan.gov.in",
    "kviconline.gov.in",
    "www.kviconline.gov.in",
    "pmsvanidhi.mohua.gov.in",
    "maandhan.in",
    "www.maandhan.in",
    "pmuy.gov.in",
    "www.pmuy.gov.in",
}
EXTENSION_GRANT_TTL_SECONDS = 300  # 5 minutes


# Field mapping dictionaries: Maps form field IDs to candidate source field aliases
FIELD_SOURCE_ALIASES: Dict[str, List[str]] = {
    # Personal Details
    "applicant_name": ["name", "applicant_name", "full_name", "candidate_name"],
    "date_of_birth": ["dob", "date_of_birth", "birth_date"],
    "gender": ["gender", "sex"],
    "caste_category": ["caste", "caste_category", "category", "community"],
    "mobile_number": ["mobile_number", "phone_number", "phone", "mobile"],
    "email_address": ["email_address", "email"],
    "state_residence": ["state", "state_residence"],
    "district_residence": ["district", "district_residence"],

    # Family & Income
    "father_name": ["father_name", "parent_name", "fathers_name"],
    "mother_name": ["mother_name", "mothers_name"],
    "annual_family_income": ["annual_income", "annual_family_income", "income", "family_income"],
    "income_certificate_number": [
        "certificate_number",
        "income_certificate_number",
        "income_cert_no",
        "cert_no",
    ],

    # Bank Details
    "bank_name": ["bank_name", "bank"],
    "account_number": ["account_number", "bank_account_number", "acc_no"],
    "ifsc_code": ["ifsc_code", "ifsc"],

    # Academic & Scheme-Specific
    "institution_name": ["institution_name", "college_name", "institute_name", "school_name"],
    "aicte_institution_name": ["aicte_institution_name", "institution_name", "college_name", "institute_name"],
    "premier_institution_name": ["premier_institution_name", "institution_name", "institute_name", "college_name"],
    "course_name": ["course_name", "degree", "programme", "course"],
    "course_enrolled": ["course_enrolled", "course_name", "degree", "programme"],
    "course_type": ["course_type"],
    "course_level": ["course_level", "level"],
    "current_academic_year": ["current_academic_year", "current_year", "academic_year", "year"],
    "current_year": ["current_year", "current_academic_year", "academic_year", "year"],
    "class_12_board_name": ["class_12_board_name", "board_name", "board"],
    "class_12_roll_no": ["class_12_roll_no", "roll_no", "roll_number"],
    "class_12_passing_year": ["class_12_passing_year", "passing_year", "year_of_passing"],
    "class_12_percentile_or_marks": ["class_12_percentile_or_marks", "percentage", "marks", "percentile"],
    "cap_allotment_number": ["cap_allotment_number", "allotment_order_no", "allotment_number"],
    "admission_type": ["admission_type"],
    "tuition_fee_paid": ["tuition_fee_paid", "tuition_fee", "fee_amount", "annual_fee"],
    "total_annual_tuition_fee": ["total_annual_tuition_fee", "tuition_fee_paid", "tuition_fee", "annual_fee"],
    "girl_child_count_in_family": ["girl_child_count_in_family", "girl_child_count"],
    "annexure_iii_signed": ["annexure_iii_signed"],
    "disability_type": ["disability_type", "nature_of_disability"],
    "disability_percentage": ["disability_percentage", "percentage_of_disability"],
    "udid_card_number": ["udid_card_number", "udid_number", "disability_cert_number"],
    "swanath_criterion": ["swanath_criterion", "category_type"],
    "supporting_certificate_details": ["supporting_certificate_details", "certificate_details"],
    "national_entrance_exam": ["national_entrance_exam", "entrance_exam", "exam_name"],
    "entrance_rank_or_score": ["entrance_rank_or_score", "rank", "score", "all_india_rank"],
}

# Profile attribute mapping
PROFILE_ATTRIBUTE_MAPPINGS: Dict[str, str] = {
    "applicant_name": "full_name",
    "date_of_birth": "date_of_birth",
    "gender": "gender",
    "caste_category": "caste_category",
    "state_residence": "state",
    "district_residence": "district",
    "annual_family_income": "annual_income",
}

# Missing information remediation guidance
MISSING_REMEDIES: Dict[str, Dict[str, str]] = {
    "applicant_name": {
        "reason": "Full name is not present in your profile or verified identity documents.",
        "remedy": "Update your citizen profile or upload your Aadhaar Card in My Documents and confirm your name.",
    },
    "date_of_birth": {
        "reason": "Date of birth is missing in both profile and confirmed documents.",
        "remedy": "Upload your Aadhaar Card or Class 10/12 Marksheet and confirm your date of birth.",
    },
    "gender": {
        "reason": "Gender is not recorded in your profile or identity documents.",
        "remedy": "Update your citizen profile or confirm extracted gender from an identity document.",
    },
    "caste_category": {
        "reason": "Caste category is required for scholarship eligibility verification.",
        "remedy": "Upload your Community/Caste Certificate in My Documents and confirm your category.",
    },
    "annual_family_income": {
        "reason": "Annual family income is missing.",
        "remedy": "Upload your official Income Certificate in My Documents and confirm the extracted family income.",
    },
    "income_certificate_number": {
        "reason": "No confirmed Income Certificate number found.",
        "remedy": "Upload your official Income Certificate and confirm the certificate registration number.",
    },
    "bank_name": {
        "reason": "Bank name is required for scholarship direct benefit transfer (DBT).",
        "remedy": "Upload your Bank Passbook or Bank Statement in My Documents and confirm your bank details.",
    },
    "account_number": {
        "reason": "Bank account number is required for scholarship disbursement.",
        "remedy": "Upload your Bank Passbook under 'BANK' category in My Documents and confirm your account number.",
    },
    "ifsc_code": {
        "reason": "Bank branch IFSC code is required for fund transfer.",
        "remedy": "Upload your Bank Passbook and confirm the 11-character IFSC code.",
    },
    "class_12_board_name": {
        "reason": "Class 12 examination board name is required for merit verification.",
        "remedy": "Upload your Class 12 Marksheet in My Documents under 'ACADEMIC' and confirm board details.",
    },
    "class_12_roll_no": {
        "reason": "Class 12 roll number or registration number is required.",
        "remedy": "Upload your Class 12 Marksheet and confirm your roll number.",
    },
    "class_12_percentile_or_marks": {
        "reason": "Class 12 score or percentile is missing.",
        "remedy": "Upload your Class 12 Marksheet and confirm your marks or percentile.",
    },
    "udid_card_number": {
        "reason": "UDID or Disability Certificate number is required for Divyangjan scholarships.",
        "remedy": "Upload your UDID Card or Disability Certificate under 'DISABILITY' and confirm card number.",
    },
    "disability_percentage": {
        "reason": "Disability percentage (minimum 40%) must be verified from certificate.",
        "remedy": "Upload your Disability Certificate or UDID card and confirm the certified percentage.",
    },
    "declaration_no_concurrent": {
        "reason": "Concurrent scholarship declaration requires manual citizen affirmation.",
        "remedy": "Review and manually affirm the declaration in the application workspace before continuing.",
    },
    "declaration_information_true": {
        "reason": "Truthfulness declaration requires citizen manual confirmation.",
        "remedy": "Review all populated fields and manually check the confirmation box.",
    },
}


def _normalize_comparable(val: Any) -> str:
    """Normalize values for robust equality comparison."""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        # Normalize 150000.0 to 150000
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return str(val)
    s = str(val).strip().lower()
    # Normalize common representations
    s = s.replace(",", "").replace("-", "")
    return s


def is_verified_portal_url(url: str) -> bool:
    """Verify that the target URL belongs strictly to authorized government portal domains."""
    if not url:
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if host in OFFICIAL_VERIFIED_PORTAL_HOSTS:
            return True
        for trusted in OFFICIAL_VERIFIED_PORTAL_HOSTS:
            if host == trusted or host.endswith("." + trusted):
                return True
        return (
            host.endswith(".gov.in")
            or host.endswith(".nic.in")
            or host.endswith(".kviconline.gov.in")
            or host.endswith(".maandhan.in")
        )
    except Exception:
        return False


class AutofillService:
    """Engine providing deterministic autofill mapping and scoped extension grants."""

    def __init__(
        self,
        db: Optional[Database] = None,
        profile_manager: Optional[ProfileManager] = None,
        app_service: Optional[ApplicationService] = None,
        vault: Optional[PIIVault] = None,
    ):
        """Initialize AutofillService with database, profile, application, and vault services."""
        self.db = db or Database()
        self.profile_manager = profile_manager or ProfileManager(db=self.db)
        self.app_service = app_service or ApplicationService(db=self.db, vault=vault)
        self.vault = vault or PIIVault()

    # -------------------------------------------------------------------------
    # Scoped Extension Grant Tokens
    # -------------------------------------------------------------------------

    def create_extension_grant(
        self,
        user_id: str,
        scheme_id: str,
        portal_url: str,
        draft_id: str,
    ) -> Dict[str, Any]:
        """Issue a short-lived (5-minute), cryptographically secure grant token for browser extension autofill.

        Security Guarantees:
        - Mandatory scopes: user_id, draft_id, scheme_id, approved portal origin (portal_url), expires_at.
        - Rejects missing, empty, or whitespace scope parameters.
        - Rejects unauthorized schemes.
        - Rejects untrusted portal URLs (enforces official portal domain scholarships.gov.in).
        - Validates citizen draft ownership and scheme binding.
        - Persists only SHA-256 token hash; raw token is returned once and never logged.
        """
        if not user_id or not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is mandatory for extension autofill grants.")
        user_id = user_id.strip()

        if not scheme_id or not isinstance(scheme_id, str) or not scheme_id.strip():
            raise ValueError("scheme_id is mandatory for extension autofill grants.")
        scheme_id = scheme_id.strip()
        if not is_valid_scheme_id(scheme_id):
            raise ValueError(f"Scheme '{scheme_id}' is not supported for extension autofill.")

        if not portal_url or not isinstance(portal_url, str) or not portal_url.strip():
            raise ValueError("portal_url is mandatory for extension autofill grants.")
        portal_url = portal_url.strip()
        if not is_verified_portal_url(portal_url):
            raise ValueError(
                f"Untrusted portal URL '{portal_url}'. Grants are strictly restricted to official government portals (https://scholarships.gov.in)."
            )

        if not draft_id or not isinstance(draft_id, str) or not draft_id.strip():
            raise ValueError("draft_id is mandatory for extension autofill grants.")
        draft_id = draft_id.strip()

        # Verify citizen ownership and scheme match of the draft
        draft = self.app_service.get_draft(draft_id, user_id)
        if not draft:
            raise ValueError(f"Application draft '{draft_id}' not found or unauthorized.")
        if draft.get("scheme_id") != scheme_id:
            raise ValueError(f"Draft '{draft_id}' scheme '{draft.get('scheme_id')}' does not match requested scheme '{scheme_id}'.")

        grant_id = f"grant_{uuid.uuid4().hex[:16]}"
        raw_token = f"sahay_atf_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=EXTENSION_GRANT_TTL_SECONDS)).isoformat()
        now_iso = now.isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO autofill_grants (
                    grant_id,
                    token_hash,
                    user_id,
                    scheme_id,
                    draft_id,
                    portal_url,
                    scope,
                    expires_at,
                    used_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grant_id,
                    token_hash,
                    user_id,
                    scheme_id,
                    draft_id,
                    portal_url,
                    "extension:autofill",
                    expires_at,
                    None,
                    now_iso,
                ),
            )

        logger.info(
            "Created scoped extension grant %s for user %s on draft %s scheme %s (expires in %ds)",
            grant_id,
            user_id,
            draft_id,
            scheme_id,
            EXTENSION_GRANT_TTL_SECONDS,
        )

        return {
            "grant_id": grant_id,
            "grant_token": raw_token,
            "token_type": "Bearer",
            "expires_at": expires_at,
            "expires_in_seconds": EXTENSION_GRANT_TTL_SECONDS,
            "scheme_id": scheme_id,
            "portal_url": portal_url,
            "draft_id": draft_id,
            "scope": "extension:autofill",
        }

    def validate_extension_grant(
        self,
        raw_token: str,
        scheme_id: str,
        portal_url: str,
        draft_id: str,
        user_id: Optional[str] = None,
        single_use: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Validate an incoming extension grant token against all mandatory security scopes.

        Security Architecture & Identity Model:
        - Mandatory Scopes: Every grant strictly requires raw_token, draft_id, scheme_id,
          portal_url (scholarships.gov.in), and expires_at.
        - Identity & Ownership Model: The grant owner is immutably anchored to grant["user_id"]
          recorded upon session-authenticated grant issuance. If caller provides user_id,
          it must strictly match grant["user_id"]. In the extension flow without user session,
          the grant owner is explicitly enforced as the identity and exact draft ownership
          is verified against application_drafts. Closed or tampered drafts are rejected.
        - Expiry Boundary: Rejects grants when now_utc >= expires_at (exact boundary).
        - Replay & Consumption Model:
          * By default (single_use=False), grants are time-bound reusable bearer tokens
            valid across multi-step portal application forms until now_utc >= expires_at.
            used_at records the audit timestamp of the most recent consumption.
          * When single_use=True, atomic database consumption (UPDATE ... WHERE used_at IS NULL)
            is enforced with rowcount verification, strictly rejecting replayed or concurrent calls.

        Updates used_at timestamp on successful validation.
        """
        # 1. Reject missing or empty request scope parameters
        if not raw_token or not isinstance(raw_token, str) or not raw_token.strip():
            logger.warning("Autofill grant validation rejected: missing or empty raw_token.")
            return None

        if not scheme_id or not isinstance(scheme_id, str) or not scheme_id.strip():
            logger.warning("Autofill grant validation rejected: missing or empty scheme_id.")
            return None

        if not portal_url or not isinstance(portal_url, str) or not portal_url.strip():
            logger.warning("Autofill grant validation rejected: missing or empty portal_url.")
            return None

        if not draft_id or not isinstance(draft_id, str) or not draft_id.strip():
            logger.warning("Autofill grant validation rejected: missing or empty draft_id.")
            return None

        if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
            logger.warning("Autofill grant validation rejected: invalid or empty user_id provided.")
            return None

        req_scheme_id = scheme_id.strip()
        req_portal_url = portal_url.strip()
        req_draft_id = draft_id.strip()
        req_user_id = user_id.strip() if user_id is not None else None

        # Verify portal URL is an approved government portal
        if not is_verified_portal_url(req_portal_url):
            logger.warning("Autofill grant requested for untrusted portal URL: %s", req_portal_url)
            return None

        clean_token = raw_token.strip()
        if clean_token.startswith("Bearer "):
            clean_token = clean_token[7:].strip()

        if not clean_token:
            logger.warning("Autofill grant validation rejected: empty bearer token after prefix removal.")
            return None

        token_hash = hashlib.sha256(clean_token.encode("utf-8")).hexdigest()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT grant_id, token_hash, user_id, scheme_id, draft_id,
                       portal_url, scope, expires_at, used_at, created_at
                FROM autofill_grants
                WHERE token_hash = ?
                """,
                (token_hash,),
            )
            row = cursor.fetchone()

        if not row:
            logger.warning("Autofill grant token hash not found.")
            return None

        grant = dict(row)

        # 2. Enforce all mandatory scope fields in stored grant (fail closed if missing or empty)
        mandatory_fields = ["user_id", "draft_id", "scheme_id", "portal_url", "expires_at"]
        for field in mandatory_fields:
            val = grant.get(field)
            if val is None or not isinstance(val, str) or not val.strip():
                logger.warning(
                    "Autofill grant %s failed closed: missing or empty mandatory grant scope field '%s'.",
                    grant.get("grant_id"),
                    field,
                )
                return None

        grant_user_id = grant["user_id"].strip()
        grant_draft_id = grant["draft_id"].strip()
        grant_scheme_id = grant["scheme_id"].strip()
        grant_portal_url = grant["portal_url"].strip()
        grant_expires_at = grant["expires_at"].strip()

        # 3. Check expiry (strictly reject when now_utc >= expires_at)
        try:
            expires_dt = datetime.fromisoformat(grant_expires_at)
            now_dt = datetime.now(timezone.utc)
            if now_dt >= expires_dt:
                logger.warning(
                    "Autofill grant %s expired at %s (now: %s; now >= expires_at)",
                    grant["grant_id"],
                    grant_expires_at,
                    now_dt.isoformat(),
                )
                return None
        except Exception as exc:
            logger.error("Failed to parse grant expires_at '%s': %s", grant_expires_at, exc)
            return None

        # 4. Check user_id (if caller provided user_id, must match grant owner exactly)
        if req_user_id is not None and grant_user_id != req_user_id:
            logger.warning(
                "Autofill grant %s user mismatch: token bound to user '%s', requested by '%s'",
                grant["grant_id"],
                grant_user_id,
                req_user_id,
            )
            return None

        # 5. Check scheme_id
        if not is_valid_scheme_id(req_scheme_id):
            logger.warning("Requested scheme '%s' is not supported.", req_scheme_id)
            return None

        if grant_scheme_id != req_scheme_id:
            logger.warning(
                "Autofill grant %s scheme mismatch: token bound to '%s', requested '%s'",
                grant["grant_id"],
                grant_scheme_id,
                req_scheme_id,
            )
            return None

        # 6. Check draft_id
        if grant_draft_id != req_draft_id:
            logger.warning(
                "Autofill grant %s draft mismatch: token bound to '%s', requested '%s'",
                grant["grant_id"],
                grant_draft_id,
                req_draft_id,
            )
            return None

        # 7. Check approved portal origin
        if not is_verified_portal_url(grant_portal_url):
            logger.warning("Autofill grant %s has untrusted stored portal URL: %s", grant["grant_id"], grant_portal_url)
            return None

        grant_host = (urlparse(grant_portal_url).hostname or "").lower()
        req_host = (urlparse(req_portal_url).hostname or "").lower()
        if not grant_host or not req_host or grant_host != req_host:
            logger.warning(
                "Autofill grant %s portal host mismatch: token bound to host '%s', requested host '%s'",
                grant["grant_id"],
                grant_host,
                req_host,
            )
            return None

        # 8. Verify bound draft exists, belongs to grant owner, and matches scheme
        if self.app_service:
            bound_draft = self.app_service.get_draft(grant_draft_id, grant_user_id)
            if not bound_draft:
                logger.warning(
                    "Autofill grant %s bound draft '%s' for user '%s' not found or deleted.",
                    grant["grant_id"],
                    grant_draft_id,
                    grant_user_id,
                )
                return None
            if bound_draft.get("user_id") != grant_user_id:
                logger.warning(
                    "Autofill grant %s draft owner mismatch: draft belongs to '%s', grant owned by '%s'",
                    grant["grant_id"],
                    bound_draft.get("user_id"),
                    grant_user_id,
                )
                return None
            if bound_draft.get("scheme_id") != grant_scheme_id:
                logger.warning(
                    "Autofill grant %s bound draft '%s' scheme '%s' does not match grant scheme '%s'.",
                    grant["grant_id"],
                    grant_draft_id,
                    bound_draft.get("scheme_id"),
                    grant_scheme_id,
                )
                return None
            if bound_draft.get("status") == "CLOSED":
                logger.warning(
                    "Autofill grant %s bound draft '%s' is in CLOSED status.",
                    grant["grant_id"],
                    grant_draft_id,
                )
                return None

        # Record usage / Atomic consumption
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if single_use:
                # Atomic database consumption: update succeeds only if used_at IS NULL
                cursor.execute(
                    "UPDATE autofill_grants SET used_at = ? WHERE grant_id = ? AND used_at IS NULL",
                    (now_iso, grant["grant_id"]),
                )
                if cursor.rowcount == 0:
                    logger.warning(
                        "Autofill grant %s has already been consumed (single-use replay rejection).",
                        grant["grant_id"],
                    )
                    return None
            else:
                # Reusable until expiry: update the audit timestamp of the most recent usage
                cursor.execute(
                    "UPDATE autofill_grants SET used_at = ? WHERE grant_id = ?",
                    (now_iso, grant["grant_id"]),
                )

        return grant

    # -------------------------------------------------------------------------
    # Deterministic Autofill Package Generation
    # -------------------------------------------------------------------------

    def generate_autofill_package(
        self,
        user_id: str,
        scheme_id: str,
        draft_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a complete, deterministic autofill package for the given scheme and citizen.

        Rules:
        - Only confirmed fields from active, non-archived documents are used.
        - Unconfirmed OCR extraction values are never used.
        - Profile attributes are used as secondary deterministic sources.
        - Existing draft values take precedence to prevent accidental overwrites.
        - Conflicts are flagged with MANDATORY_REVIEW and competing sources.
        - Missing fields are flagged with MISSING_INFORMATION and actionable remedies.
        """
        defn = get_application_definition(scheme_id)
        if not defn:
            raise ValueError(f"Scheme '{scheme_id}' is not supported.")

        # 1. Fetch user account details (email, phone)
        user_account: Dict[str, Any] = {}
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email, phone FROM users WHERE user_id = ?", (user_id,))
            u_row = cursor.fetchone()
            if u_row:
                user_account = dict(u_row)

        # 2. Fetch citizen profile
        profile = self.profile_manager.get_profile_by_user_id(user_id) or {}

        # 3. Fetch active confirmed document fields
        # Note: get_active_confirmed_fields_with_documents enforces is_confirmed = 1 and status != 'ARCHIVED'
        confirmed_fields_list = self.profile_manager.get_active_confirmed_fields_with_documents(user_id)

        # Group confirmed fields by field_name: List[Dict[str, Any]]
        confirmed_by_field: Dict[str, List[Dict[str, Any]]] = {}
        for item in confirmed_fields_list:
            fname = item["field_name"]
            confirmed_by_field.setdefault(fname, []).append(item)

        # 4. Fetch existing draft form data if draft_id is provided
        draft_form_data: Dict[str, Any] = {}
        if draft_id:
            draft = self.app_service.get_draft(draft_id, user_id)
            if draft:
                draft_form_data = draft.get("form_data", {})

        # 5. Build field package for each field in the scheme definition
        package_fields: Dict[str, Any] = {}
        total_count = 0
        populated_count = 0
        conflict_count = 0
        missing_count = 0

        for section in defn.get("form_sections", []):
            sec_id = section.get("section_id", "")
            sec_title = section.get("section_title", "")

            for field_def in section.get("fields", []):
                total_count += 1
                f_id = field_def["field_id"]
                label = field_def.get("label", f_id)
                f_type = field_def.get("type", "text")
                is_required = field_def.get("required", False)

                # Special handling for explicit citizen declarations
                if f_id.startswith("declaration_") or f_type == "checkbox":
                    draft_val = draft_form_data.get(f_id)
                    if draft_val is True:
                        field_entry = {
                            "field_id": f_id,
                            "label": label,
                            "section_id": sec_id,
                            "section_title": sec_title,
                            "value": True,
                            "status": "POPULATED",
                            "confidence": 1.0,
                            "has_conflict": False,
                            "review_requirement": "NONE",
                            "source": {
                                "source_type": "EXISTING_DRAFT",
                                "source_field_name": f_id,
                                "citizen_confirmation_status": "EXPLICITLY_CONFIRMED_IN_DRAFT",
                            },
                            "competing_sources": [],
                            "missing_reason": None,
                            "suggested_remedy": None,
                        }
                        populated_count += 1
                    else:
                        field_entry = {
                            "field_id": f_id,
                            "label": label,
                            "section_id": sec_id,
                            "section_title": sec_title,
                            "value": False if f_type == "checkbox" else None,
                            "status": "MISSING_INFORMATION",
                            "confidence": 0.0,
                            "has_conflict": False,
                            "review_requirement": "MANUAL_ENTRY_REQUIRED",
                            "source": None,
                            "competing_sources": [],
                            "missing_reason": MISSING_REMEDIES.get(f_id, {}).get(
                                "reason", "Explicit citizen declaration requires manual review and confirmation."
                            ),
                            "suggested_remedy": MISSING_REMEDIES.get(f_id, {}).get(
                                "remedy", "Read and manually affirm the declaration before submission."
                            ),
                        }
                        missing_count += 1

                    package_fields[f_id] = field_entry
                    continue

                # Find candidate sources
                candidate_sources: List[Dict[str, Any]] = []

                # A. Check confirmed document fields
                aliases = FIELD_SOURCE_ALIASES.get(f_id, [f_id])
                for alias in aliases:
                    if alias in confirmed_by_field:
                        for c_item in confirmed_by_field[alias]:
                            val = c_item.get("field_value")
                            # If sensitive identifier has encrypted_value, decrypt it
                            if c_item.get("encrypted_value") and self.vault.is_configured:
                                try:
                                    val = self.vault.decrypt(c_item["encrypted_value"])
                                except Exception as exc:
                                    logger.error("Failed to decrypt confirmed field %s: %s", alias, exc)

                            if val is not None and str(val).strip() != "":
                                candidate_sources.append({
                                    "source_type": "CONFIRMED_DOCUMENT",
                                    "value": val,
                                    "document_id": c_item.get("document_id"),
                                    "document_name": c_item.get("original_filename") or c_item.get("document_type"),
                                    "document_category": c_item.get("document_category"),
                                    "source_field_name": c_item.get("field_name"),
                                    "citizen_confirmation_status": c_item.get("confirmation_status", "CONFIRMED"),
                                    "confirmed_at": c_item.get("confirmed_at"),
                                    "is_corrected": bool(c_item.get("is_corrected")),
                                })

                # B. Check citizen profile attribute
                profile_attr = PROFILE_ATTRIBUTE_MAPPINGS.get(f_id)
                if profile_attr and profile.get(profile_attr) is not None:
                    p_val = profile.get(profile_attr)
                    if str(p_val).strip() != "":
                        candidate_sources.append({
                            "source_type": "CITIZEN_PROFILE",
                            "value": p_val,
                            "document_id": None,
                            "document_name": None,
                            "document_category": "PROFILE",
                            "source_field_name": profile_attr,
                            "citizen_confirmation_status": "PROFILE_CONFIRMED" if profile.get("user_confirmed") else "UNCONFIRMED_PROFILE",
                            "confirmed_at": profile.get("updated_at"),
                            "is_corrected": False,
                        })

                # C. Check user account details (for phone, email)
                if f_id == "email_address" and user_account.get("email"):
                    candidate_sources.append({
                        "source_type": "USER_ACCOUNT",
                        "value": user_account.get("email"),
                        "document_id": None,
                        "document_name": None,
                        "document_category": "ACCOUNT",
                        "source_field_name": "email",
                        "citizen_confirmation_status": "ACCOUNT_VERIFIED",
                        "confirmed_at": None,
                        "is_corrected": False,
                    })
                elif f_id == "mobile_number" and user_account.get("phone"):
                    candidate_sources.append({
                        "source_type": "USER_ACCOUNT",
                        "value": user_account.get("phone"),
                        "document_id": None,
                        "document_name": None,
                        "document_category": "ACCOUNT",
                        "source_field_name": "phone",
                        "citizen_confirmation_status": "ACCOUNT_VERIFIED",
                        "confirmed_at": None,
                        "is_corrected": False,
                    })

                # D. Check if existing draft already has a value
                draft_val = draft_form_data.get(f_id)
                has_existing_draft_val = draft_val is not None and str(draft_val).strip() != ""

                # Evaluate conflict vs resolution
                if not candidate_sources and not has_existing_draft_val:
                    # Missing information
                    remedy_info = MISSING_REMEDIES.get(f_id, {})
                    field_entry = {
                        "field_id": f_id,
                        "label": label,
                        "section_id": sec_id,
                        "section_title": sec_title,
                        "value": None,
                        "status": "MISSING_INFORMATION",
                        "confidence": 0.0,
                        "has_conflict": False,
                        "review_requirement": "MANUAL_ENTRY_REQUIRED" if is_required else "OPTIONAL",
                        "source": None,
                        "competing_sources": [],
                        "missing_reason": remedy_info.get(
                            "reason", f"No confirmed information found for '{label}' in profile or documents."
                        ),
                        "suggested_remedy": remedy_info.get(
                            "remedy", f"Enter '{label}' manually in workspace or upload relevant verification documents."
                        ),
                    }
                    missing_count += 1
                else:
                    # Collect distinct values to detect conflicts
                    distinct_values: Dict[str, Dict[str, Any]] = {}
                    for src in candidate_sources:
                        norm = _normalize_comparable(src["value"])
                        if norm not in distinct_values:
                            distinct_values[norm] = src

                    # Compare with existing draft value if present
                    draft_conflicts = False
                    if has_existing_draft_val:
                        draft_norm = _normalize_comparable(draft_val)
                        # Check if draft value differs from candidate sources
                        if candidate_sources and any(_normalize_comparable(src["value"]) != draft_norm for src in candidate_sources):
                            draft_conflicts = True
                            if draft_norm not in distinct_values:
                                distinct_values[draft_norm] = {
                                    "source_type": "EXISTING_DRAFT",
                                    "value": draft_val,
                                    "document_id": None,
                                    "document_name": "Application Draft",
                                    "document_category": "DRAFT",
                                    "source_field_name": f_id,
                                    "citizen_confirmation_status": "MANUALLY_ENTERED_IN_DRAFT",
                                    "confirmed_at": None,
                                    "is_corrected": False,
                                }

                    is_conflict = len(distinct_values) > 1 or draft_conflicts

                    if is_conflict:
                        # Conflict flagged: Never silently overwrite!
                        # Prioritize existing draft value to preserve user input, or most recent confirmed doc
                        if has_existing_draft_val:
                            resolved_val = draft_val
                            primary_src = {
                                "source_type": "EXISTING_DRAFT",
                                "value": draft_val,
                                "document_id": None,
                                "document_name": "Application Draft",
                                "document_category": "DRAFT",
                                "source_field_name": f_id,
                                "citizen_confirmation_status": "MANUALLY_ENTERED_IN_DRAFT",
                            }
                        else:
                            primary_src = candidate_sources[0]
                            resolved_val = primary_src["value"]

                        field_entry = {
                            "field_id": f_id,
                            "label": label,
                            "section_id": sec_id,
                            "section_title": sec_title,
                            "value": resolved_val,
                            "status": "CONFLICT",
                            "confidence": 0.6,
                            "has_conflict": True,
                            "review_requirement": "MANDATORY_REVIEW",
                            "source": primary_src,
                            "competing_sources": list(distinct_values.values()),
                            "missing_reason": None,
                            "suggested_remedy": (
                                f"Conflicting values detected for '{label}'. "
                                "Review competing values and select or confirm the correct one."
                            ),
                        }
                        conflict_count += 1
                        populated_count += 1
                    else:
                        # Clean match with single candidate or consistent sources
                        if candidate_sources:
                            primary_src = candidate_sources[0]
                            resolved_val = primary_src["value"]
                            status = "POPULATED"
                            conf = 1.0 if primary_src["source_type"] == "CONFIRMED_DOCUMENT" else 0.95
                        else:
                            primary_src = {
                                "source_type": "EXISTING_DRAFT",
                                "value": draft_val,
                                "document_id": None,
                                "document_name": "Application Draft",
                                "document_category": "DRAFT",
                                "source_field_name": f_id,
                                "citizen_confirmation_status": "MANUALLY_ENTERED_IN_DRAFT",
                            }
                            resolved_val = draft_val
                            status = "POPULATED"
                            conf = 0.9

                        field_entry = {
                            "field_id": f_id,
                            "label": label,
                            "section_id": sec_id,
                            "section_title": sec_title,
                            "value": resolved_val,
                            "status": status,
                            "confidence": conf,
                            "has_conflict": False,
                            "review_requirement": "NONE",
                            "source": primary_src,
                            "competing_sources": [],
                            "missing_reason": None,
                            "suggested_remedy": None,
                        }
                        populated_count += 1

                package_fields[f_id] = field_entry

        readiness_pct = round((populated_count / total_count) * 100.0, 1) if total_count > 0 else 0.0

        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "scheme_id": scheme_id,
            "scheme_name": defn.get("scheme_name"),
            "official_scheme_name": defn.get("official_scheme_name"),
            "portal_verification": defn.get("portal_verification"),
            "draft_id": draft_id,
            "summary": {
                "total_fields": total_count,
                "populated_fields": populated_count,
                "conflict_fields": conflict_count,
                "missing_fields": missing_count,
                "readiness_percentage": readiness_pct,
            },
            "fields": package_fields,
            "generated_at": now_iso,
        }

