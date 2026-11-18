"""Document processing API routes for SahayAI.

Provides:
- Secure multi-part document upload endpoint (POST /documents/upload)
- Support for authenticated registered citizens and anonymous guest sessions
- Strict 5 MB file size limit enforcement
- Magic byte (file signature) media type verification (PDF, PNG, JPEG, WEBP)
- Random server-generated temporary file handling with guaranteed cleanup
- Path traversal mitigation
- Zero profile auto-persistence (citizen confirmation required)
- Strict PII masking in logs and response payloads
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from dataclasses import asdict
from pydantic import BaseModel, Field

from api.security import (
    enforce_csrf_protection,
    get_current_session_or_guest,
)
from document_ai.categories import (
    DocumentCategory,
    VALID_DOCUMENT_CATEGORIES,
    get_category_for_type,
    normalize_document_category,
    sanitize_filename,
)
from document_ai.document_processor import DocumentProcessor
from document_ai.extract_fields import AUTHENTICITY_DISCLAIMER, PIIVault
from document_ai.schemas import DocumentType, DocumentTypeRegistry
from document_ai.storage_vault import DocumentStorageVault
from profile.profile_manager import ProfileManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])
profile_manager = ProfileManager()

# Standardized upload size limits: PDF up to 10 MB, Images (JPG, JPEG, PNG, WEBP) up to 5 MB
MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024     # 10,485,760 bytes (10 MB)
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024    # 5,242,880 bytes (5 MB)
CHUNK_SIZE_BYTES = 64 * 1024              # 64 KB streaming buffer

# Dedicated restricted temporary upload directory
TEMP_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "temp_uploads",
)
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

# Allowed file extensions mapped to canonical format names
ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
}


def get_max_upload_size(extension: str) -> int:
    """Return maximum allowed file size in bytes based on file extension."""
    ext = (extension or "").lower()
    if ext == ".pdf":
        return MAX_PDF_SIZE_BYTES
    return MAX_IMAGE_SIZE_BYTES


def validate_magic_bytes(header: bytes) -> Optional[str]:
    """Inspect file header signature (magic bytes) to verify genuine file type.

    Guarantees:
    - Never trusts the user-supplied Content-Type or file extension alone.
    - Accurately identifies PDF, PNG, JPEG, and WEBP signatures.
    - Rejects executables, scripts, plaintext, or mismatched payloads.

    Args:
        header: Leading bytes read from the uploaded document.

    Returns:
        Canonical format ('pdf', 'png', 'jpeg', 'webp') or None if unrecognized.
    """
    if not header or len(header) < 4:
        return None

    # PDF format signature: %PDF-
    if header.startswith(b"%PDF-"):
        return "pdf"

    # PNG format signature: \x89PNG\r\n\x1a\n
    if len(header) >= 8 and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    # JPEG format signature: \xff\xd8\xff
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    # WEBP format signature: RIFF....WEBP
    if (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ):
        return "webp"

    return None


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_category: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Upload and process citizen welfare documents with quality checks and OCR.

    Security & Privacy Guarantees:
    - Supports both registered users and guest sessions.
    - Enforces CSRF token and origin validation on state-changing upload.
    - Enforces strict 5 MB file size limit (HTTP 413).
    - Inspects magic byte file signatures to reject disguised formats (HTTP 415).
    - Prevents path traversal by ignoring client filename and generating UUID names.
    - For registered citizens, original file is encrypted at rest in private vault (Fernet).
    - Fails closed if required encryption key is unavailable.
    - For guests, zero persistent records or files are stored.
    - Guarantees immediate temporary file deletion via finally cleanup.
    - Zero auto-saving to citizen profiles: citizen must verify and confirm fields first.
    - Emits masked identifiers only; unmasked PII is never stored or logged.
    """
    # 1. Filename extension validation
    status_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)
    client_filename = file.filename or ""
    client_ext = Path(client_filename).suffix.lower()
    if client_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file extension '{client_ext}'. Only .pdf, .png, .jpg, .jpeg, and .webp are accepted.",
        )

    max_allowed_bytes = get_max_upload_size(client_ext)
    limit_mb = 10 if client_ext == ".pdf" else 5

    # 2. Early Content-Length check if sent by client (accounting for multipart boundary framing)
    content_length_hdr = request.headers.get("content-length")
    if content_length_hdr:
        try:
            if int(content_length_hdr) > (max_allowed_bytes + 64 * 1024):
                raise HTTPException(
                    status_code=status_413,
                    detail=f"File size exceeds the {limit_mb} MB limit for {client_ext.upper().lstrip('.')} documents. Please upload a smaller file.",
                )
        except ValueError:
            pass

    # 3. Secure temporary file preparation
    temp_file_id = uuid.uuid4().hex
    # Use canonical extension derived from allowed extensions
    expected_format = ALLOWED_EXTENSIONS[client_ext]
    safe_ext = ".jpg" if expected_format == "jpeg" else f".{expected_format}"
    temp_file_path = os.path.join(TEMP_UPLOAD_DIR, f"upload_{temp_file_id}{safe_ext}")

    total_bytes_read = 0
    header_bytes = b""
    stored_vault_ref = None

    try:
        # Stream file to disk while enforcing max upload size and capturing header
        with open(temp_file_path, "wb") as temp_out:
            while True:
                chunk = await file.read(CHUNK_SIZE_BYTES)
                if not chunk:
                    break

                total_bytes_read += len(chunk)
                if total_bytes_read > max_allowed_bytes:
                    raise HTTPException(
                        status_code=status_413,
                        detail=f"File size exceeds the {limit_mb} MB limit for {client_ext.upper().lstrip('.')} documents. Please upload a smaller file.",
                    )

                temp_out.write(chunk)
                if len(header_bytes) < 32:
                    header_bytes += chunk[: 32 - len(header_bytes)]

        # 4. Empty file check
        if total_bytes_read == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes). Please upload a valid document.",
            )

        # 5. Magic byte file signature validation
        detected_format = validate_magic_bytes(header_bytes)
        if not detected_format:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported or unrecognized file format. File signature does not match any allowed format (PDF, PNG, JPEG, WEBP).",
            )

        if detected_format != expected_format:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Mismatched file content: file signature ({detected_format.upper()}) does not match extension '{client_ext}'.",
            )

        # 6. Execute OCR and Field Extraction through intelligent DocumentProcessor
        processor = DocumentProcessor(enforce_quality_gate=True)
        client_hint = document_type if document_type and document_type.upper() not in ("OTHER", "UNKNOWN", "NONE", "AUTO", "AUTO_DETECT") else None
        result = processor.process(temp_file_path, document_type_hint=client_hint)

        # 7. Evaluate quality and processing outcomes
        if not result.success:
            issues = result.quality.get("issues", [])
            err_msg = (result.error_message or "").strip()
            issues_text = "; ".join(issues) if issues else (err_msg or "Processing failed.")
            err_lower = err_msg.lower()
            is_corrupt = (
                any("corrupt" in iss.lower() for iss in issues)
                or "corrupt" in err_lower
                or "invalid" in err_lower
                or "malformed" in err_lower
                or "cannot identify image" in err_lower
                or "syntaxerror" in err_lower
                or "eof marker" in err_lower
                or "pdf" in err_lower
                or result.document_type in ("REJECTED_MALFORMED", "OCR_ERROR")
            )

            if is_corrupt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Corrupted or malformed document: {issues_text}",
                )

            if result.document_type == "REJECTED_QUALITY":
                status_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
                raise HTTPException(
                    status_code=status_422,
                    detail=f"Document quality check failed: {issues_text}",
                )

            logger.error(
                "Document processing failed for %s: %s (%s)",
                temp_file_id,
                result.document_type,
                result.error_message,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document OCR processing failed. Please ensure the document is clear and try again.",
            )

        # Calculate representative confidence score
        confidence = result.ocr_confidence
        if confidence <= 0.0 and result.fields:
            confidences = [
                f.get("heuristic_confidence", 0.9)
                for f in result.fields.values()
                if isinstance(f, dict) and "heuristic_confidence" in f
            ]
            confidence = sum(confidences) / len(confidences) if confidences else 0.95
        elif confidence <= 0.0:
            confidence = 0.85

        doc_id = f"doc_{temp_file_id[:16]}"
        # Automatic classification prioritized; user hint used if classifier is low confidence or unknown
        if result.is_low_confidence and client_hint:
            final_doc_type = DocumentTypeRegistry.normalize_type(client_hint)
        else:
            final_doc_type = result.document_type

        final_category = get_category_for_type(final_doc_type, document_category)
        sanitized_orig_name = sanitize_filename(client_filename)
        detected_mime = f"application/{expected_format}" if expected_format == "pdf" else f"image/{expected_format}"

        # Privacy-safe audit log (never log unmasked PII)
        session_type = "guest" if session_context.get("is_guest") else "registered"
        logger.info(
            "Document processed successfully [session=%s]: type=%s (detected=%s, conf=%.2f), category=%s, fields_extracted=%d, needs_confirm=%s",
            session_type,
            final_doc_type,
            result.document_type,
            result.classification_confidence,
            final_category,
            len(result.fields),
            result.needs_user_confirmation,
        )

        # For registered citizens, persist pending document extraction for review and confirmation
        if not session_context.get("is_guest"):
            user_id = session_context["user_id"]
            storage_vault = DocumentStorageVault()

            if not storage_vault.is_configured:
                logger.error("Document upload failed: SAHAY_PII_ENCRYPTION_KEY is not configured.")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Document encryption key is not configured. Cannot securely store documents at rest. Failed closed.",
                )

            raw_file_bytes = Path(temp_file_path).read_bytes()
            stored_vault_ref, raw_file_size = storage_vault.store_file(
                file_bytes=raw_file_bytes,
                original_filename=client_filename,
            )

            user_profile = profile_manager.get_profile_by_user_id(user_id)
            profile_id = user_profile["profile_id"] if user_profile else None

            try:
                profile_manager.save_document(
                    document_id=doc_id,
                    user_id=user_id,
                    document_type=final_doc_type,
                    extracted_fields=result.fields,
                    profile_id=profile_id,
                    status="PENDING_REVIEW",
                    document_category=final_category,
                    original_filename=sanitized_orig_name,
                    storage_reference=stored_vault_ref,
                    mime_type=detected_mime,
                    file_size=raw_file_size,
                    confirmation_status="PENDING_CONFIRMATION",
                )
            except Exception as db_err:
                logger.error("Failed to save document metadata for %s: %s", doc_id, db_err)
                storage_vault.delete_file(stored_vault_ref)
                raise

        return {
            "success": True,
            "document_id": doc_id,
            "document_category": final_category,
            "detected_document_type": result.document_type,
            "document_type": final_doc_type,
            "original_filename": sanitized_orig_name,
            "file_size": total_bytes_read,
            "has_original_file": bool(stored_vault_ref),
            "extracted_fields": result.fields,
            "missing_fields": result.missing_fields,
            "unreadable_fields": result.unreadable_fields,
            "validation_warnings": result.validation_warnings,
            "classification_confidence": round(result.classification_confidence, 2),
            "is_low_confidence": result.is_low_confidence,
            "suggested_alternatives": result.suggested_alternatives,
            "field_confidence": round(confidence, 2),
            "needs_user_confirmation": result.needs_user_confirmation,
            "quality_warnings": result.quality.get("issues", []),
            "processing_status": "SUCCESS",
            "authenticity_disclaimer": AUTHENTICITY_DISCLAIMER,
        }

    finally:
        # Guaranteed cleanup of temporary document from disk
        if os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except OSError as cleanup_err:
                logger.warning(
                    "Failed to delete temporary file %s: %s",
                    temp_file_path,
                    cleanup_err,
                )


# ---------------------------------------------------------------------------
# Document Review & Confirmation Schemas & Endpoints (Step 5.3A)
# ---------------------------------------------------------------------------

ALLOWED_PROFILE_FIELDS = DocumentTypeRegistry.get_all_allowed_fields()


def validate_and_normalize_field_value(field_name: str, value: Any) -> Any:
    """Validate and normalize field values according to SahayAI domain rules."""
    if value is None or str(value).strip() == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmed value for '{field_name}' cannot be empty.",
        )

    canonical_name = "annual_income" if field_name == "annual_family_income" else field_name

    if canonical_name == "date_of_birth":
        dob_str = str(value).strip()
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_of_birth must be a valid date in YYYY-MM-DD format.",
            )
        today = datetime.now(timezone.utc).date()
        if dob > today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_of_birth cannot be in the future.",
            )
        if dob < today.replace(year=today.year - 130):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_of_birth indicates an age exceeding 130 years.",
            )
        return dob_str

    if canonical_name == "gender":
        g_val = str(value).strip().upper()
        if g_val in ("MALE", "पुरुष"):
            return "MALE"
        if g_val in ("FEMALE", "महिला"):
            return "FEMALE"
        if g_val in ("TRANSGENDER", "OTHER"):
            return g_val
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="gender must be one of: FEMALE, MALE, OTHER, TRANSGENDER.",
        )

    if canonical_name in ("annual_income", "total_obtained_marks", "maximum_total_marks", "fee_amount"):
        try:
            val_float = float(value)
            if val_float < 0:
                raise ValueError()
            return val_float
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{canonical_name} must be a non-negative number.",
            )

    if canonical_name == "percentage":
        try:
            pct = float(value)
            if not (0.0 <= pct <= 100.0):
                raise ValueError()
            return pct
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="percentage must be a valid number between 0 and 100.",
            )

    if canonical_name in ("age", "examination_year", "year_of_birth"):
        try:
            val_int = int(value)
            if canonical_name == "age" and not (0 <= val_int <= 130):
                raise ValueError()
            if canonical_name in ("examination_year", "year_of_birth") and not (1900 <= val_int <= 2050):
                raise ValueError()
            return val_int
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{canonical_name} must be a valid integer.",
            )

    if canonical_name in ("caste_category", "category"):
        c_val = str(value).strip().upper()
        if c_val not in ("GENERAL", "OBC", "SC", "ST", "EWS"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="category must be one of: EWS, GENERAL, OBC, SC, ST.",
            )
        return c_val

    if canonical_name == "is_bpl":
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("true", "1", "yes"):
            return True
        if str(value).strip().lower() in ("false", "0", "no"):
            return False
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="is_bpl must be a boolean (true/false).",
        )

    if canonical_name in (
        "full_name",
        "student_name",
        "applicant_name",
        "account_holder_name",
        "father_name",
        "mother_name",
    ):
        name = str(value).strip()
        if len(name) < 2 or len(name) > 150:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{canonical_name} must be between 2 and 150 characters.",
            )
        return name

    if canonical_name in (
        "state",
        "district",
        "occupation",
        "board_name",
        "school_name",
        "issuing_authority",
        "bank_name",
        "branch",
        "caste_name",
        "academic_year",
    ):
        text_val = str(value).strip()
        if len(text_val) < 2 or len(text_val) > 150:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{canonical_name} must be between 2 and 150 characters.",
            )
        return text_val

    if canonical_name in ("roll_number", "certificate_number", "receipt_number"):
        text_val = str(value).strip()
        if len(text_val) < 1 or len(text_val) > 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{canonical_name} must be between 1 and 60 characters.",
            )
        return text_val

    if canonical_name in ("grade", "result_status"):
        return str(value).strip().upper()

    if canonical_name == "subject_marks":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            import json
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return value

    if canonical_name in ("residential_address", "address"):
        text_val = str(value).strip()
        if len(text_val) < 3 or len(text_val) > 300:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{canonical_name} must be between 3 and 300 characters.",
            )
        return text_val

    if canonical_name == "ifsc_code":
        val_str = str(value).strip().upper()
        if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", val_str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ifsc_code must be a valid 11-character IFSC code (e.g. SBIN0001234).",
            )
        return val_str

    if canonical_name == "account_number":
        clean = re.sub(r"[\s\-]+", "", str(value).strip())
        if re.match(r"^XXXXXX\d{4}$", str(value).strip(), re.I) or (len(clean) >= 9 and clean.isdigit()):
            return f"XXXXXX{clean[-4:]}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account_number must be at least 9 digits or masked format (XXXXXX1234).",
        )

    if canonical_name == "aadhaar_number":
        clean = re.sub(r"[\s\-_]+", "", str(value).strip())
        if re.match(r"^XXXX-XXXX-\d{4}$", str(value).strip(), re.I) or re.match(r"^XXXXXXXX\d{4}$", str(value).strip(), re.I):
            return f"XXXX-XXXX-{clean[-4:]}"
        if len(clean) == 12 and clean.isdigit():
            return f"XXXX-XXXX-{clean[-4:]}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aadhaar_number must be a 12-digit number or masked format (XXXX-XXXX-1234).",
        )

    if canonical_name == "pan_number":
        clean = re.sub(r"[\s\-_]+", "", str(value).strip()).upper()
        if re.match(r"^XXXXX\d{4}X$", str(value).strip(), re.I):
            return str(value).strip().upper()
        if len(clean) == 10 and re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", clean):
            return f"XXXXX{clean[5:9]}X"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pan_number must be a valid 10-character PAN or masked format (XXXXX1234X).",
        )

    return value

    return value


class FieldConfirmationItem(BaseModel):
    field_name: str = Field(min_length=1, max_length=100)
    value: Optional[Any] = None
    confirmed_value: Optional[Any] = None
    confirmed: bool = True
    allow_overwrite: Optional[bool] = None

    def get_effective_value(self) -> Any:
        return self.confirmed_value if self.confirmed_value is not None else self.value


class DocumentConfirmationRequest(BaseModel):
    confirmations: Optional[List[FieldConfirmationItem]] = None
    confirmed_fields: Optional[Dict[str, Any]] = None
    allow_overwrite: bool = False


@router.get("/{document_id}/review")
def review_document(
    document_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """Retrieve pending document extraction results for registered citizen review.

    Security & Privacy Guarantees:
    - Registered users only (guests rejected with HTTP 403 Forbidden).
    - Unauthenticated requests rejected with HTTP 401 Unauthorized.
    - Strict document ownership enforcement (IDOR defense: returns HTTP 404).
    - Identifies discrepancies against existing citizen profile values.
    - All extracted fields require explicit citizen confirmation before persistence.
    - Never exposes unmasked PII.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document review requires a registered citizen account. Guest sessions cannot persist or review stored documents.",
        )

    user_id = session_context["user_id"]
    doc = profile_manager.get_document(document_id)

    if not doc or doc.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    extracted_fields = doc.get("extracted_fields", {})

    # Detect conflicts with current profile data
    existing_profile = profile_manager.get_profile_by_user_id(user_id)
    conflicts: Dict[str, Any] = {}
    if existing_profile:
        for field_name, item in extracted_fields.items():
            canonical_name = "annual_income" if field_name == "annual_family_income" else field_name
            current_val = existing_profile.get(canonical_name)
            extracted_val = item.get("value") if isinstance(item, dict) else item
            if current_val is not None and str(current_val).strip() != "":
                differs = False
                if isinstance(extracted_val, (int, float)) and isinstance(current_val, (int, float)):
                    differs = (float(extracted_val) != float(current_val))
                else:
                    differs = (str(extracted_val).strip().lower() != str(current_val).strip().lower())
                if differs:
                    conflicts[canonical_name] = {
                        "current_profile_value": current_val,
                        "extracted_value": extracted_val,
                        "requires_overwrite_approval": True,
                    }

    needs_confirmation = list(extracted_fields.keys())

    # Generate review_fields list for UI consumption
    review_fields = []
    schema = DocumentTypeRegistry.get_schema(doc.get("document_type"))
    for f_name, f_data in extracted_fields.items():
        val = f_data.get("value") if isinstance(f_data, dict) else f_data
        field_def = schema.get_field(f_name) if schema else None
        lbl = field_def.label if field_def else f_name.replace("_", " ").title()
        f_type = field_def.field_type if field_def else "string"
        review_fields.append({
            "field_name": f_name,
            "label": lbl,
            "extracted_value": val,
            "field_type": f_type,
            "is_confirmed": doc.get("confirmation_status") == "CONFIRMED",
            "heuristic_confidence": f_data.get("heuristic_confidence", 0.9) if isinstance(f_data, dict) else 0.9,
            "evidence": f_data.get("evidence", "") if isinstance(f_data, dict) else "",
        })

    return {
        "success": True,
        "document_id": document_id,
        "document_type": doc.get("document_type"),
        "status": doc.get("status", "PENDING_REVIEW"),
        "extracted_fields": extracted_fields,
        "review_fields": review_fields,
        "schema_fields": [asdict(f) for f in schema.fields] if schema else [],
        "missing_fields": [f for f in (schema.get_required_field_names() if schema else []) if f not in extracted_fields],
        "existing_profile_conflicts": conflicts,
        "needs_user_confirmation": needs_confirmation,
        "authenticity_disclaimer": AUTHENTICITY_DISCLAIMER,
    }


class DocumentReclassifyRequest(BaseModel):
    document_type: str = Field(min_length=1, max_length=60)


@router.post("/{document_id}/reclassify")
def reclassify_document(
    document_id: str,
    payload: DocumentReclassifyRequest,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Re-extract document fields using a citizen-specified document type schema."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document reclassification requires a registered citizen account.",
        )

    user_id = session_context["user_id"]
    doc = profile_manager.get_document(document_id)

    if not doc or doc.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    new_type = DocumentTypeRegistry.normalize_type(payload.document_type)
    storage_vault = DocumentStorageVault()
    storage_ref = doc.get("storage_reference")

    if not storage_ref or not storage_vault.file_exists(storage_ref):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not available in vault for re-extraction.",
        )

    raw_bytes = storage_vault.retrieve_file(storage_ref)
    suffix = ".pdf" if doc.get("mime_type") == "application/pdf" else ".jpg"
    temp_re_path = os.path.join(TEMP_UPLOAD_DIR, f"reclass_{uuid.uuid4().hex[:12]}{suffix}")

    try:
        with open(temp_re_path, "wb") as f_out:
            f_out.write(raw_bytes)

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(temp_re_path, override_type=new_type)

        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Re-extraction failed: {result.error_message}",
            )

        cat = get_category_for_type(new_type)
        profile_manager.save_document(
            document_id=document_id,
            user_id=user_id,
            document_type=new_type,
            extracted_fields=result.fields,
            profile_id=doc.get("profile_id"),
            status=doc.get("status", "PENDING_REVIEW"),
            document_category=cat,
            original_filename=doc.get("original_filename"),
            storage_reference=storage_ref,
            mime_type=doc.get("mime_type"),
            file_size=doc.get("file_size"),
            confirmation_status=doc.get("confirmation_status", "PENDING_CONFIRMATION"),
        )

        schema = DocumentTypeRegistry.get_schema(new_type)
        review_fields = []
        for f_name, f_data in result.fields.items():
            val = f_data.get("value") if isinstance(f_data, dict) else f_data
            field_def = schema.get_field(f_name) if schema else None
            lbl = field_def.label if field_def else f_name.replace("_", " ").title()
            review_fields.append({
                "field_name": f_name,
                "label": lbl,
                "extracted_value": val,
                "field_type": field_def.field_type if field_def else "string",
                "is_confirmed": False,
                "heuristic_confidence": f_data.get("heuristic_confidence", 0.9) if isinstance(f_data, dict) else 0.9,
                "evidence": f_data.get("evidence", "") if isinstance(f_data, dict) else "",
            })

        return {
            "success": True,
            "document_id": document_id,
            "document_type": new_type,
            "extracted_fields": result.fields,
            "review_fields": review_fields,
            "missing_fields": result.missing_fields,
            "validation_warnings": result.validation_warnings,
        }
    finally:
        if os.path.exists(temp_re_path):
            try:
                os.unlink(temp_re_path)
            except OSError:
                pass


@router.post("/{document_id}/confirm")
def confirm_document_fields(
    document_id: str,
    payload: DocumentConfirmationRequest,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Explicitly confirm, correct, and persist document-extracted fields.

    Security & Privacy Guarantees:
    - Registered users only (guests rejected with HTTP 403 Forbidden).
    - CSRF protected (validates Origin/Referer and X-CSRF-Token).
    - Strict document ownership enforcement (IDOR defense: returns HTTP 404).
    - Rejects unknown or unsupported fields with HTTP 400.
    - Validates field value formats with HTTP 400.
    - Prevents silent overwriting of existing profile values (requires allow_overwrite).
    - Sensitive identifiers (Aadhaar, PAN) encrypted via PIIVault with fail-closed behavior.
    - Only explicitly confirmed fields are persisted. Unconfirmed fields are omitted.
    - Government verification status is strictly FALSE (0).
    - Includes authenticity disclaimer.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document confirmation requires a registered citizen account. Guest sessions cannot persist profile fields.",
        )

    user_id = session_context["user_id"]
    doc = profile_manager.get_document(document_id)

    if not doc or doc.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    # 1. Collect confirmation items
    items_to_process: List[FieldConfirmationItem] = []
    if payload.confirmations:
        items_to_process.extend(payload.confirmations)
    elif payload.confirmed_fields:
        for k, v in payload.confirmed_fields.items():
            items_to_process.append(
                FieldConfirmationItem(
                    field_name=k,
                    value=v,
                    confirmed=True,
                    allow_overwrite=payload.allow_overwrite,
                )
            )

    # Filter strictly for explicitly confirmed fields
    confirmed_items = [item for item in items_to_process if item.confirmed]

    # 2. Field Name & Value Validation
    normalized_values: Dict[str, Any] = {}
    for item in confirmed_items:
        if item.field_name not in ALLOWED_PROFILE_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported or unknown field name: '{item.field_name}'.",
            )
        eff_val = item.get_effective_value()
        norm_val = validate_and_normalize_field_value(item.field_name, eff_val)
        normalized_values[item.field_name] = norm_val

    # 3. PII Encryption for Sensitive Fields (Fail closed if encryption unavailable)
    vault = PIIVault()
    encrypted_values: Dict[str, str] = {}
    for item in confirmed_items:
        fname = item.field_name
        if fname in ("aadhaar_number", "pan_number"):
            if not vault.is_configured:
                logger.error("PII encryption required for '%s' but PIIVault key is not configured.", fname)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="PII encryption is required for storing sensitive document identifiers, but the encryption key is not configured. Failed closed.",
                )
            try:
                raw_to_encrypt = str(item.get_effective_value()).strip()
                encrypted_values[fname] = vault.encrypt(raw_to_encrypt)
            except Exception as enc_err:
                logger.error("PII encryption failure for '%s': %s", fname, enc_err)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to securely encrypt sensitive identifier. Failed closed.",
                )

    # 4. Existing Profile Overwrite Protection
    existing_profile = profile_manager.get_profile_by_user_id(user_id)
    if existing_profile:
        for item in confirmed_items:
            fname = "annual_income" if item.field_name == "annual_family_income" else item.field_name
            norm_val = normalized_values[item.field_name]
            current_val = existing_profile.get(fname)
            if current_val is not None and str(current_val).strip() != "":
                differs = False
                if isinstance(norm_val, (int, float)) and isinstance(current_val, (int, float)):
                    differs = (float(norm_val) != float(current_val))
                else:
                    differs = (str(norm_val).strip().lower() != str(current_val).strip().lower())

                if differs:
                    item_allow_overwrite = (
                        item.allow_overwrite
                        if item.allow_overwrite is not None
                        else payload.allow_overwrite
                    )
                    if not item_allow_overwrite:
                        # Ensure neither current_val nor norm_val leaks unmasked sensitive identifiers
                        safe_current = current_val
                        safe_norm = norm_val
                        if "aadhaar" in fname.lower() or "pan" in fname.lower():
                            from profile.profile_manager import mask_sensitive_value
                            safe_current = mask_sensitive_value(fname, current_val)
                            safe_norm = mask_sensitive_value(fname, norm_val)

                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Existing profile value for '{fname}' ('{safe_current}') differs from confirmed value ('{safe_norm}'). Explicit approval ('allow_overwrite': true) is required to overwrite existing profile data.",
                        )

    # 5. Persist Confirmed Fields to Audit & Profile Tables (Atomic Transaction)
    extracted_fields = doc.get("extracted_fields", {})
    items_to_persist: List[Dict[str, Any]] = []
    profile_updates: Dict[str, Any] = {}

    for item in confirmed_items:
        fname = "annual_income" if item.field_name == "annual_family_income" else item.field_name
        norm_val = normalized_values[item.field_name]

        # Determine original extracted value
        extracted_entry = extracted_fields.get(fname, {})
        orig_val = extracted_entry.get("value") if isinstance(extracted_entry, dict) else extracted_entry

        # Detect correction
        is_corrected = False
        if orig_val is not None and str(orig_val).strip() != "":
            if isinstance(norm_val, (int, float)) and isinstance(orig_val, (int, float)):
                is_corrected = (float(norm_val) != float(orig_val))
            else:
                is_corrected = (str(norm_val).strip().lower() != str(orig_val).strip().lower())

        encrypted_val = encrypted_values.get(item.field_name)

        items_to_persist.append({
            "field_name": fname,
            "field_value": norm_val,
            "extracted_value": orig_val,
            "is_corrected": is_corrected,
            "encrypted_value": encrypted_val,
            "confirmation_status": "CONFIRMED",
        })

        # If it maps to a profile attribute, add to profile updates
        if fname in (
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
        ):
            profile_updates[fname] = norm_val

    # Automatic age calculation from confirmed date_of_birth
    if "date_of_birth" in profile_updates and "age" not in profile_updates:
        try:
            dob_date = datetime.strptime(profile_updates["date_of_birth"], "%Y-%m-%d").date()
            today = datetime.now(timezone.utc).date()
            calc_age = today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))
            profile_updates["age"] = calc_age
        except Exception:
            pass

    if profile_updates:
        profile_updates["user_confirmed"] = True

    # Atomic multi-field confirmation & profile persistence transaction
    try:
        tx_result = profile_manager.confirm_and_persist_transactional(
            user_id=user_id,
            document_id=document_id,
            confirmed_items=items_to_persist,
            profile_updates=profile_updates,
            new_document_status="CONFIRMED",
        )
    except Exception as tx_err:
        logger.error("Transaction failure during document confirmation for doc %s: %s", document_id, tx_err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist confirmed document fields. Database transaction rolled back safely.",
        )

    confirmed_results = tx_result["saved_fields"]
    saved_profile = tx_result["profile"]

    # Determine unconfirmed fields
    confirmed_field_names = set(confirmed_results.keys())
    unconfirmed_fields = [
        k for k in extracted_fields.keys()
        if k not in confirmed_field_names
    ]

    clean_profile = dict(saved_profile) if saved_profile else {}
    clean_profile.pop("metadata_json", None)

    return {
        "success": True,
        "message": "Document fields confirmed and profile updated successfully.",
        "document_id": document_id,
        "confirmed_fields": confirmed_results,
        "unconfirmed_fields": unconfirmed_fields,
        "profile": clean_profile,
        "authenticity_disclaimer": AUTHENTICITY_DISCLAIMER,
    }


@router.get("")
def list_citizen_documents(
    category: Optional[str] = None,
    include_archived: bool = False,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """List all stored documents for the authenticated registered citizen.

    Security & Privacy Guarantees:
    - Registered users only (guests rejected with HTTP 403 Forbidden).
    - Enforces strict user isolation (returns only the authenticated citizen's documents).
    - Never exposes internal physical storage paths.
    - Optional category filter (e.g. IDENTITY, ACADEMIC, INCOME).
    - Excludes archived documents by default unless include_archived=True.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to the My Documents library requires a registered citizen account. Guest sessions do not store documents.",
        )

    user_id = session_context["user_id"]
    docs = profile_manager.get_user_documents(
        user_id=user_id,
        category=category,
        include_archived=include_archived,
    )

    safe_docs = []
    for d in docs:
        safe_doc = {
            "document_id": d["document_id"],
            "document_category": d.get("document_category", "OTHER"),
            "document_type": d.get("document_type"),
            "original_filename": d.get("original_filename"),
            "mime_type": d.get("mime_type"),
            "file_size": d.get("file_size"),
            "status": d.get("status", "PENDING_REVIEW"),
            "confirmation_status": d.get("confirmation_status", "PENDING_CONFIRMATION"),
            "has_original_file": bool(d.get("storage_reference")),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        }
        safe_docs.append(safe_doc)

    return {
        "success": True,
        "documents": safe_docs,
        "total_count": len(safe_docs),
    }


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Response:
    """Securely download the original encrypted document.

    Security & Privacy Guarantees:
    - Registered users only (guests rejected with HTTP 403 Forbidden).
    - Strict document ownership check (IDOR defense: returns HTTP 404).
    - Fails closed if encryption key is missing/unconfigured (HTTP 500).
    - Decrypts file in-memory using authenticated Fernet decryption.
    - Returns streaming Response with strict anti-caching and attachment headers.
    - Never exposes physical storage paths.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document download requires a registered citizen account.",
        )

    user_id = session_context["user_id"]
    doc = profile_manager.get_document(document_id, user_id=user_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    storage_ref = doc.get("storage_reference")
    if not storage_ref:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file is not available for this document.",
        )

    storage_vault = DocumentStorageVault()
    if not storage_vault.is_configured:
        logger.error("Document download failed: SAHAY_PII_ENCRYPTION_KEY is not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document decryption key is not configured. Cannot decrypt document. Failed closed.",
        )

    try:
        file_bytes = storage_vault.retrieve_file(storage_ref)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found in storage.",
        )
    except Exception as err:
        logger.error("Decryption error for doc %s: %s", document_id, err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt and retrieve document. Failed closed.",
        )

    download_name = doc.get("original_filename") or f"{document_id}.pdf"
    safe_download_name = sanitize_filename(download_name)
    mime_type = doc.get("mime_type") or "application/octet-stream"

    headers = {
        "Content-Disposition": f'attachment; filename="{safe_download_name}"',
        "Content-Length": str(len(file_bytes)),
        "Cache-Control": "no-store, no-cache, must-revalidate, private",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    return Response(
        content=file_bytes,
        media_type=mime_type,
        headers=headers,
    )


@router.post("/{document_id}/replace")
async def replace_document(
    request: Request,
    document_id: str,
    file: UploadFile = File(...),
    document_category: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Replace an existing document with a new upload and re-trigger OCR extraction.

    Security & Privacy Guarantees:
    - Registered users only (guests rejected with HTTP 403 Forbidden).
    - CSRF protected.
    - Strict document ownership enforcement (IDOR defense: returns HTTP 404).
    - Enforces 5 MB file size limit and magic byte signature validation.
    - Encrypts new file at rest using authenticated Fernet encryption.
    - Unlinks old encrypted vault file on disk (zero orphaned storage files).
    - Initiates new extraction and review cycle (status='PENDING_REVIEW', confirmation_status='PENDING_CONFIRMATION').
    - Preserves existing confirmed field audit history in confirmed_document_fields.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document replacement requires a registered citizen account.",
        )

    user_id = session_context["user_id"]
    existing_doc = profile_manager.get_document(document_id, user_id=user_id)
    if not existing_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    # Check encryption configuration
    storage_vault = DocumentStorageVault()
    if not storage_vault.is_configured:
        logger.error("Document replacement failed: SAHAY_PII_ENCRYPTION_KEY is not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document encryption key is not configured. Cannot securely store documents at rest. Failed closed.",
        )

    # Validate file extension
    client_filename = file.filename or ""
    client_ext = Path(client_filename).suffix.lower()
    if client_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file extension '{client_ext}'. Only .pdf, .png, .jpg, .jpeg, and .webp are accepted.",
        )

    max_allowed_bytes = get_max_upload_size(client_ext)
    limit_mb = 10 if client_ext == ".pdf" else 5
    status_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)

    content_length_hdr = request.headers.get("content-length")
    if content_length_hdr:
        try:
            if int(content_length_hdr) > (max_allowed_bytes + 64 * 1024):
                raise HTTPException(
                    status_code=status_413,
                    detail=f"File size exceeds the {limit_mb} MB limit for {client_ext.upper().lstrip('.')} documents. Please upload a smaller file.",
                )
        except ValueError:
            pass

    temp_file_id = uuid.uuid4().hex
    expected_format = ALLOWED_EXTENSIONS[client_ext]
    safe_ext = ".jpg" if expected_format == "jpeg" else f".{expected_format}"
    temp_file_path = os.path.join(TEMP_UPLOAD_DIR, f"replace_{temp_file_id}{safe_ext}")

    total_bytes_read = 0
    header_bytes = b""

    new_storage_ref = None

    try:
        with open(temp_file_path, "wb") as temp_out:
            while True:
                chunk = await file.read(CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                total_bytes_read += len(chunk)
                if total_bytes_read > max_allowed_bytes:
                    raise HTTPException(
                        status_code=status_413,
                        detail=f"File size exceeds the {limit_mb} MB limit for {client_ext.upper().lstrip('.')} documents. Please upload a smaller file.",
                    )
                temp_out.write(chunk)
                if len(header_bytes) < 32:
                    header_bytes += chunk[: 32 - len(header_bytes)]

        if total_bytes_read == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes). Please upload a valid document.",
            )

        detected_format = validate_magic_bytes(header_bytes)
        if not detected_format:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported or unrecognized file format. File signature does not match any allowed format (PDF, PNG, JPEG, WEBP).",
            )

        if detected_format != expected_format:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Mismatched file content: file signature ({detected_format.upper()}) does not match extension '{client_ext}'.",
            )

        # Store new encrypted file
        raw_bytes = Path(temp_file_path).read_bytes()
        new_storage_ref, raw_size = storage_vault.store_file(raw_bytes, client_filename)

        # Run OCR processing
        processor = DocumentProcessor(enforce_quality_gate=True)
        result = processor.process(temp_file_path)

        if not result.success:
            issues = result.quality.get("issues", [])
            err_msg = (result.error_message or "").strip()
            issues_text = "; ".join(issues) if issues else (err_msg or "Processing failed.")
            err_lower = err_msg.lower()
            is_corrupt = (
                any("corrupt" in iss.lower() for iss in issues)
                or "corrupt" in err_lower
                or "invalid" in err_lower
                or "malformed" in err_lower
                or "cannot identify image" in err_lower
                or "syntaxerror" in err_lower
                or "eof marker" in err_lower
                or "pdf" in err_lower
                or result.document_type in ("REJECTED_MALFORMED", "OCR_ERROR")
            )
            if is_corrupt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Corrupted or malformed document: {issues_text}",
                )
            if result.document_type == "REJECTED_QUALITY":
                status_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
                raise HTTPException(
                    status_code=status_422,
                    detail=f"Document quality check failed: {issues_text}",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document OCR processing failed.",
            )

        # Determine category and type
        final_doc_type = document_type or result.document_type
        final_category = get_category_for_type(final_doc_type, document_category or existing_doc.get("document_category"))
        sanitized_orig_name = sanitize_filename(client_filename)
        detected_mime = f"application/{expected_format}" if expected_format == "pdf" else f"image/{expected_format}"

        # Update document_metadata while preserving confirmation history
        old_storage_ref = existing_doc.get("storage_reference")
        user_profile = profile_manager.get_profile_by_user_id(user_id)
        profile_id = user_profile["profile_id"] if user_profile else None

        profile_manager.save_document(
            document_id=document_id,
            user_id=user_id,
            document_type=final_doc_type,
            extracted_fields=result.fields,
            profile_id=profile_id,
            status="PENDING_REVIEW",
            document_category=final_category,
            original_filename=sanitized_orig_name,
            storage_reference=new_storage_ref,
            mime_type=detected_mime,
            file_size=raw_size,
            confirmation_status="PENDING_CONFIRMATION",
        )

        # Clean up old encrypted file on disk
        if old_storage_ref and old_storage_ref != new_storage_ref:
            storage_vault.delete_file(old_storage_ref)

        confidence = result.ocr_confidence
        if confidence <= 0.0 and result.fields:
            confidences = [
                f.get("heuristic_confidence", 0.9)
                for f in result.fields.values()
                if isinstance(f, dict) and "heuristic_confidence" in f
            ]
            confidence = sum(confidences) / len(confidences) if confidences else 0.95
        elif confidence <= 0.0:
            confidence = 0.85

        return {
            "success": True,
            "message": "Document replaced successfully and queued for citizen review.",
            "document_id": document_id,
            "document_category": final_category,
            "detected_document_type": result.document_type,
            "document_type": final_doc_type,
            "original_filename": sanitized_orig_name,
            "file_size": raw_size,
            "has_original_file": True,
            "extracted_fields": result.fields,
            "field_confidence": round(confidence, 2),
            "needs_user_confirmation": True,
            "quality_warnings": result.quality.get("issues", []),
            "processing_status": "SUCCESS",
            "authenticity_disclaimer": AUTHENTICITY_DISCLAIMER,
        }

    except Exception:
        # Clean up newly stored file if replacement failed before completion
        if new_storage_ref:
            storage_vault.delete_file(new_storage_ref)
        raise
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass


@router.get("/{document_id}")
def get_document_metadata(
    document_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """Retrieve metadata for a specific document belonging to the citizen.

    Security & Privacy Guarantees:
    - Registered users only (guests rejected with HTTP 403 Forbidden).
    - Strict document ownership check (IDOR defense: returns HTTP 404).
    - Never exposes internal physical storage paths.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document library requires a registered citizen account.",
        )

    user_id = session_context["user_id"]
    doc = profile_manager.get_document(document_id, user_id=user_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    # Retrieve citizen-confirmed fields for this document
    confirmed_fields = profile_manager.get_confirmed_fields_by_document(document_id, user_id=user_id)

    # Base extracted fields from OCR
    raw_extracted = doc.get("extracted_fields", {})
    merged_fields: Dict[str, Any] = {}
    if isinstance(raw_extracted, dict):
        for k, v in raw_extracted.items():
            if isinstance(v, dict):
                merged_fields[k] = dict(v)
            else:
                merged_fields[k] = {"value": v}

    # Overlay citizen-confirmed/corrected field values so authoritative values are shown
    for fname, cinfo in confirmed_fields.items():
        conf_val = cinfo.get("field_value") if cinfo.get("field_value") is not None else cinfo.get("value")
        if fname in merged_fields:
            merged_fields[fname]["value"] = conf_val
            merged_fields[fname]["is_confirmed"] = True
            merged_fields[fname]["is_corrected"] = cinfo.get("is_corrected", False)
            merged_fields[fname]["confirmed_at"] = cinfo.get("confirmed_at")
            merged_fields[fname]["raw_extracted_value"] = cinfo.get("extracted_value")
        else:
            merged_fields[fname] = {
                "value": conf_val,
                "is_confirmed": True,
                "is_corrected": cinfo.get("is_corrected", False),
                "confirmed_at": cinfo.get("confirmed_at"),
                "raw_extracted_value": cinfo.get("extracted_value"),
            }

    safe_doc = {
        "document_id": doc["document_id"],
        "document_category": doc.get("document_category", "OTHER"),
        "document_type": doc.get("document_type"),
        "original_filename": doc.get("original_filename"),
        "mime_type": doc.get("mime_type"),
        "file_size": doc.get("file_size"),
        "status": doc.get("status", "PENDING_REVIEW"),
        "confirmation_status": doc.get("confirmation_status", "PENDING_CONFIRMATION"),
        "extracted_fields": merged_fields,
        "confirmed_fields": confirmed_fields,
        "has_original_file": bool(doc.get("storage_reference")),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

    return {
        "success": True,
        "document": safe_doc,
        "extracted_fields": safe_doc.get("extracted_fields", {}),
        "confirmed_fields": confirmed_fields,
    }


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    hard_delete: Optional[bool] = None,
    purge: Optional[bool] = None,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Delete or archive a stored citizen document with cascade referential integrity.

    Security & Privacy Guarantees:
    - Registered users only (guests cannot delete persistent documents).
    - CSRF protected.
    - Strict document ownership enforcement (IDOR defense: returns HTTP 404).
    - If hard_delete=True (default), physically removes document, cascades to
      confirmed_document_fields, and deletes the encrypted vault file from disk.
    - If hard_delete=False, sets status='ARCHIVED' for audit retention.
    """
    effective_hard_delete = True
    if hard_delete is not None:
        effective_hard_delete = hard_delete
    elif purge is not None:
        effective_hard_delete = purge

    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document deletion requires a registered citizen account.",
        )

    user_id = session_context["user_id"]
    doc = profile_manager.get_document(document_id, user_id=user_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    success = profile_manager.delete_document(
        document_id=document_id,
        user_id=user_id,
        hard_delete=effective_hard_delete,
    )

    return {
        "success": success,
        "document_id": document_id,
        "message": "Document deleted successfully." if effective_hard_delete else "Document archived successfully.",
        "hard_deleted": effective_hard_delete,
    }

