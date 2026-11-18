"""Document Categories, Types, and Taxonomy for SahayAI Document Library (Step 5.4A).

Defines standardized document categories, supported document types, categorization
heuristics, and filename sanitization for secure citizen document persistence.
"""

from enum import Enum
import os
from pathlib import Path
import re
from typing import Optional, Set


class DocumentCategory(str, Enum):
    """Core document categories for citizen profile and scholarship applications."""
    IDENTITY = "IDENTITY"
    INCOME = "INCOME"
    CATEGORY_CERTIFICATE = "CATEGORY_CERTIFICATE"
    RESIDENCE = "RESIDENCE"
    ACADEMIC = "ACADEMIC"
    BANK = "BANK"
    DISABILITY = "DISABILITY"
    SPECIAL_CATEGORY = "SPECIAL_CATEGORY"
    APPLICATION_ASSET = "APPLICATION_ASSET"
    OTHER = "OTHER"


VALID_DOCUMENT_CATEGORIES: Set[str] = {c.value for c in DocumentCategory}

# Document Types to Category Taxonomy Mapping
TYPE_TO_CATEGORY_MAP = {
    # IDENTITY
    "AADHAAR_CARD": DocumentCategory.IDENTITY.value,
    "PAN_CARD": DocumentCategory.IDENTITY.value,
    "VOTER_ID": DocumentCategory.IDENTITY.value,
    "PASSPORT": DocumentCategory.IDENTITY.value,
    "DRIVING_LICENSE": DocumentCategory.IDENTITY.value,
    "IDENTITY_CARD": DocumentCategory.IDENTITY.value,
    "IDENTITY_OTHER": DocumentCategory.IDENTITY.value,

    # INCOME
    "INCOME_CERTIFICATE": DocumentCategory.INCOME.value,
    "SALARY_SLIP": DocumentCategory.INCOME.value,
    "ITR_ACKNOWLEDGEMENT": DocumentCategory.INCOME.value,
    "FORM_16": DocumentCategory.INCOME.value,
    "INCOME_OTHER": DocumentCategory.INCOME.value,

    # CATEGORY_CERTIFICATE
    "CASTE_CERTIFICATE": DocumentCategory.CATEGORY_CERTIFICATE.value,
    "COMMUNITY_CERTIFICATE": DocumentCategory.CATEGORY_CERTIFICATE.value,
    "OBC_CERTIFICATE": DocumentCategory.CATEGORY_CERTIFICATE.value,
    "SC_CERTIFICATE": DocumentCategory.CATEGORY_CERTIFICATE.value,
    "ST_CERTIFICATE": DocumentCategory.CATEGORY_CERTIFICATE.value,
    "EWS_CERTIFICATE": DocumentCategory.CATEGORY_CERTIFICATE.value,
    "CATEGORY_OTHER": DocumentCategory.CATEGORY_CERTIFICATE.value,

    # RESIDENCE
    "DOMICILE_CERTIFICATE": DocumentCategory.RESIDENCE.value,
    "RESIDENCE_CERTIFICATE": DocumentCategory.RESIDENCE.value,
    "NATIVITY_CERTIFICATE": DocumentCategory.RESIDENCE.value,
    "ELECTRICITY_BILL": DocumentCategory.RESIDENCE.value,
    "RESIDENCE_OTHER": DocumentCategory.RESIDENCE.value,

    # ACADEMIC
    "MARKSHEET_10TH": DocumentCategory.ACADEMIC.value,
    "MARKSHEET_12TH": DocumentCategory.ACADEMIC.value,
    "MARKSHEET_SEMESTER": DocumentCategory.ACADEMIC.value,
    "ADMISSION_LETTER": DocumentCategory.ACADEMIC.value,
    "BONAFIDE_CERTIFICATE": DocumentCategory.ACADEMIC.value,
    "FEES_RECEIPT": DocumentCategory.ACADEMIC.value,
    "TRANSFER_CERTIFICATE": DocumentCategory.ACADEMIC.value,
    "DEGREE_CERTIFICATE": DocumentCategory.ACADEMIC.value,
    "ACADEMIC_OTHER": DocumentCategory.ACADEMIC.value,

    # BANK
    "BANK_PASSBOOK": DocumentCategory.BANK.value,
    "CANCELLED_CHEQUE": DocumentCategory.BANK.value,
    "BANK_STATEMENT": DocumentCategory.BANK.value,
    "BANK_OTHER": DocumentCategory.BANK.value,

    # DISABILITY
    "DISABILITY_CERTIFICATE": DocumentCategory.DISABILITY.value,
    "UDID_CARD": DocumentCategory.DISABILITY.value,
    "DISABILITY_OTHER": DocumentCategory.DISABILITY.value,

    # SPECIAL_CATEGORY
    "ORPHAN_CERTIFICATE": DocumentCategory.SPECIAL_CATEGORY.value,
    "SINGLE_GIRL_CHILD_CERTIFICATE": DocumentCategory.SPECIAL_CATEGORY.value,
    "DEFENCE_PERSONNEL_CERTIFICATE": DocumentCategory.SPECIAL_CATEGORY.value,
    "SPORTS_CERTIFICATE": DocumentCategory.SPECIAL_CATEGORY.value,
    "MINORITY_CERTIFICATE": DocumentCategory.SPECIAL_CATEGORY.value,
    "SPECIAL_CATEGORY_OTHER": DocumentCategory.SPECIAL_CATEGORY.value,

    # APPLICATION_ASSET
    "PASSPORT_PHOTO": DocumentCategory.APPLICATION_ASSET.value,
    "SIGNATURE": DocumentCategory.APPLICATION_ASSET.value,
    "THUMB_IMPRESSION": DocumentCategory.APPLICATION_ASSET.value,
    "APPLICATION_ASSET_OTHER": DocumentCategory.APPLICATION_ASSET.value,
    "APPLICATION_ASSISTANCE": DocumentCategory.APPLICATION_ASSET.value,
    "APPLICATION_ASSET": DocumentCategory.APPLICATION_ASSET.value,
    "APPLICATION_ASSETS": DocumentCategory.APPLICATION_ASSET.value,

    # OTHER
    "RATION_CARD": DocumentCategory.OTHER.value,
    "OTHER_DOCUMENT": DocumentCategory.OTHER.value,
    "UNKNOWN_DOCUMENT": DocumentCategory.OTHER.value,
}


def normalize_document_category(category: Optional[str]) -> Optional[str]:
    """Normalize a document category string or return None if invalid."""
    if not category:
        return None
    cleaned = category.strip().upper().replace(" ", "_").replace("-", "_")
    if cleaned in ("APPLICATION_ASSISTANCE", "APPLICATION_ASSETS", "APPLICATION_ASSET"):
        return DocumentCategory.APPLICATION_ASSET.value
    if cleaned in ("SPECIAL_CATEGORIES", "SPECIAL_CATEGORY"):
        return DocumentCategory.SPECIAL_CATEGORY.value
    if cleaned in ("CATEGORY_CERTIFICATES", "CATEGORY_CERTIFICATE"):
        return DocumentCategory.CATEGORY_CERTIFICATE.value
    return cleaned if cleaned in VALID_DOCUMENT_CATEGORIES else None


def normalize_document_type(doc_type: Optional[str]) -> Optional[str]:
    """Normalize a document type string."""
    if not doc_type:
        return None
    return doc_type.strip().upper().replace(" ", "_").replace("-", "_")


def get_category_for_type(
    document_type: Optional[str],
    explicit_category: Optional[str] = None,
) -> str:
    """Determine the document category from type or explicit category input."""
    # 1. Use valid explicit category if provided
    norm_explicit = normalize_document_category(explicit_category)
    if norm_explicit:
        return norm_explicit

    # 2. Look up type in category mapping
    if document_type:
        norm_type = normalize_document_type(document_type)
        if norm_type in TYPE_TO_CATEGORY_MAP:
            return TYPE_TO_CATEGORY_MAP[norm_type]

        # Substring heuristics for unmapped custom types
        if any(w in norm_type for w in ("AADHAAR", "PAN", "VOTER", "PASSPORT", "IDENTITY")):
            return DocumentCategory.IDENTITY.value
        if any(w in norm_type for w in ("INCOME", "SALARY", "ITR", "FORM16")):
            return DocumentCategory.INCOME.value
        if any(w in norm_type for w in ("CASTE", "COMMUNITY", "OBC", "SC", "ST", "EWS")):
            return DocumentCategory.CATEGORY_CERTIFICATE.value
        if any(w in norm_type for w in ("DOMICILE", "RESIDENCE", "NATIVITY")):
            return DocumentCategory.RESIDENCE.value
        if any(w in norm_type for w in ("MARKSHEET", "ADMISSION", "BONAFIDE", "DEGREE", "ACADEMIC")):
            return DocumentCategory.ACADEMIC.value
        if any(w in norm_type for w in ("BANK", "PASSBOOK", "CHEQUE")):
            return DocumentCategory.BANK.value
        if any(w in norm_type for w in ("DISABILITY", "UDID", "HANDICAP")):
            return DocumentCategory.DISABILITY.value
        if any(w in norm_type for w in ("ORPHAN", "DEFENCE", "SPORTS", "MINORITY")):
            return DocumentCategory.SPECIAL_CATEGORY.value
        if any(w in norm_type for w in ("PHOTO", "SIGNATURE", "THUMB", "ASSET", "ASSISTANCE")):
            return DocumentCategory.APPLICATION_ASSET.value

    # 3. Default fallback
    return DocumentCategory.OTHER.value


def sanitize_filename(filename: Optional[str], default_name: str = "document.pdf") -> str:
    """Sanitize client-provided filename to prevent path traversal and shell injection.

    - Strips directory components and path separators (../, ..\\).
    - Removes null bytes, control characters, and dangerous punctuation.
    - Limits name length to 100 characters while preserving extension.
    - Falls back to default_name if filename is empty or invalid.
    """
    if not filename:
        return default_name

    # Extract bare filename only
    base = os.path.basename(filename.replace("\\", "/"))
    base = base.replace("\x00", "").strip()

    # Split name and extension
    path_obj = Path(base)
    stem = path_obj.stem
    ext = path_obj.suffix.lower()

    # Sanitize stem: allow only alphanumeric, dashes, underscores, and dots
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", stem).strip("._ ")
    safe_stem = re.sub(r"_+", "_", safe_stem)

    if not safe_stem:
        safe_stem = "document"

    # Limit stem length
    safe_stem = safe_stem[:80]

    # Sanitize extension: allow standard extensions only
    safe_ext = ext if ext in (".pdf", ".png", ".jpg", ".jpeg", ".webp") else ".pdf"

    return f"{safe_stem}{safe_ext}"

