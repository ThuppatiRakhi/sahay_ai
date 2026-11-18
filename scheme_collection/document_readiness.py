"""Document Readiness Evaluation and Evidence Extraction for SahayAI (Step 5.4C).

Evaluates citizen document readiness against official government scholarship scheme
requirements, determines document applicability, detects profile discrepancies,
and produces deterministic readiness indicators without LLM hallucinations.
"""

from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class DocumentReadinessStatus(str, Enum):
    """Exact 6 document readiness statuses for scholarship schemes."""
    AVAILABLE_AND_CONFIRMED = "AVAILABLE_AND_CONFIRMED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    MISSING = "MISSING"
    CONFLICTING = "CONFLICTING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REQUIREMENT_NOT_ESTABLISHED = "REQUIREMENT_NOT_ESTABLISHED"


# Standardized keywords for document requirement matching
REQUIREMENT_MATCHING_RULES = {
    "aadhaar": {
        "categories": {"IDENTITY"},
        "types": {"AADHAAR_CARD", "AADHAAR"},
        "keywords": ["aadhaar", "uidai", "uid"],
    },
    "pan": {
        "categories": {"IDENTITY"},
        "types": {"PAN_CARD", "PAN"},
        "keywords": ["pan", "pan card", "income tax department"],
    },
    "income": {
        "categories": {"INCOME"},
        "types": {"INCOME_CERTIFICATE", "SALARY_SLIP", "ITR_ACKNOWLEDGEMENT", "FORM_16"},
        "keywords": ["income", "revenue", "tahsildar", "sdm", "salary"],
    },
    "marksheet_12": {
        "categories": {"ACADEMIC"},
        "types": {"MARKSHEET_12TH"},
        "keywords": ["12th", "class 12", "intermediate", "hsc", "10+2"],
    },
    "marksheet_10": {
        "categories": {"ACADEMIC"},
        "types": {"MARKSHEET_10TH"},
        "keywords": ["10th", "class 10", "ssc", "matriculation"],
    },
    "marksheet_renewal": {
        "categories": {"ACADEMIC"},
        "types": {"MARKSHEET_SEMESTER"},
        "keywords": ["previous year", "semester", "promotion", "annual exam"],
    },
    "admission_bonafide": {
        "categories": {"ACADEMIC"},
        "types": {"BONAFIDE_CERTIFICATE", "ADMISSION_LETTER", "FEES_RECEIPT"},
        "keywords": ["bonafide", "admission", "allotment", "cap", "fee receipt", "dean"],
    },
    "entrance_scorecard": {
        "categories": {"ACADEMIC"},
        "types": {"ENTRANCE_SCORECARD", "RANK_LETTER"},
        "keywords": ["entrance", "scorecard", "rank", "jee", "neet", "cat", "clat"],
    },
    "bank": {
        "categories": {"BANK"},
        "types": {"BANK_PASSBOOK", "CANCELLED_CHEQUE", "BANK_STATEMENT"},
        "keywords": ["bank", "passbook", "cheque", "statement", "dbt"],
    },
    "caste_sc": {
        "categories": {"CATEGORY_CERTIFICATE"},
        "types": {"SC_CERTIFICATE", "CASTE_CERTIFICATE", "COMMUNITY_CERTIFICATE"},
        "keywords": ["sc certificate", "scheduled caste", "caste certificate", "community certificate"],
    },
    "caste_general": {
        "categories": {"CATEGORY_CERTIFICATE"},
        "types": {"CASTE_CERTIFICATE", "COMMUNITY_CERTIFICATE", "SC_CERTIFICATE", "ST_CERTIFICATE", "OBC_CERTIFICATE", "EWS_CERTIFICATE"},
        "keywords": ["caste", "community", "category certificate", "reservation"],
    },
    "disability": {
        "categories": {"DISABILITY"},
        "types": {"DISABILITY_CERTIFICATE", "UDID_CARD"},
        "keywords": ["disability", "udid", "pwd", "specially-abled", "medical authority"],
    },
    "special_orphan": {
        "categories": {"SPECIAL_CATEGORY"},
        "types": {"ORPHAN_CERTIFICATE", "DEATH_CERTIFICATE"},
        "keywords": ["orphan", "death certificate", "cwc"],
    },
    "special_martyr": {
        "categories": {"SPECIAL_CATEGORY"},
        "types": {"DEFENCE_PERSONNEL_CERTIFICATE"},
        "keywords": ["martyr", "shaheed", "defence", "cpmf", "soldier"],
    },
    "special_covid": {
        "categories": {"SPECIAL_CATEGORY"},
        "types": {"SPECIAL_CATEGORY_OTHER"},
        "keywords": ["covid", "corona"],
    },
    "declaration_proforma": {
        "categories": {"SPECIAL_CATEGORY", "APPLICATION_ASSET", "OTHER"},
        "types": {"PARENT_DECLARATION", "ANNEXURE_III", "APPLICATION_ASSET_OTHER"},
        "keywords": ["declaration", "proforma", "annexure", "parent declaration"],
    },
}


def _classify_requirement(doc_name: str, cond: str) -> str:
    """Classify a scheme required document into a matching rule key."""
    d_low = doc_name.lower()
    c_low = cond.lower()

    # Specific banking keywords MUST take precedence over Aadhaar keywords
    # because requirements like 'Bank Passbook / Statement (Aadhaar-seeded)' contain 'aadhaar'.
    if "bank" in d_low or "passbook" in d_low or "cheque" in d_low or "account statement" in d_low:
        return "bank"
    if "pan card" in d_low or (d_low.startswith("pan") and "card" in d_low) or d_low == "pan":
        return "pan"
    if "aadhaar" in d_low or "uidai" in d_low or "uid" in d_low:
        return "aadhaar"
    if "income" in d_low:
        return "income"
    if "sc caste" in d_low:
        return "caste_sc"
    if "caste" in d_low or "category" in d_low:
        return "caste_general"
    if "disability" in d_low or "udid" in d_low:
        return "disability"
    if "class 12" in d_low or "12th" in d_low:
        return "marksheet_12"
    if "class 10" in d_low or "10th" in d_low:
        return "marksheet_10"
    if "previous year" in d_low or "renewal" in c_low or "promotion" in d_low:
        return "marksheet_renewal"
    if "entrance" in d_low or "scorecard" in d_low or "rank" in d_low:
        return "entrance_scorecard"
    if "bonafide" in d_low or "admission" in d_low or "allotment" in d_low or "fee receipt" in d_low:
        return "admission_bonafide"
    if "orphan" in d_low or "both parents" in d_low:
        return "special_orphan"
    if "martyr" in d_low or "shaheed" in d_low:
        return "special_martyr"
    if "covid" in d_low:
        return "special_covid"
    if "declaration" in d_low or "proforma" in d_low or "annexure" in d_low:
        return "declaration_proforma"
    if "qualifying" in d_low:
        return "marksheet_12"

    return "general"


def check_document_applicability(
    doc_req: Dict[str, Any],
    profile: Dict[str, Any],
    application_type: Optional[str] = None,
) -> Tuple[bool, Optional[DocumentReadinessStatus]]:
    """Determine whether a scheme required document is applicable to the citizen.

    Returns:
        (is_applicable, status_if_not_applicable)
    """
    req_type = str(doc_req.get("requirement_type") or doc_req.get("mandatory_or_optional") or "MANDATORY").upper()
    cond = str(doc_req.get("applicable_condition") or "")
    cond_low = cond.lower()
    app_type = (application_type or profile.get("application_type") or "").upper() or None

    # 1. Fresh vs Renewal Mode Applicability
    if "renewal" in cond_low:
        if app_type == "FRESH":
            return False, DocumentReadinessStatus.NOT_APPLICABLE
        if app_type == "RENEWAL":
            return True, None
        # Mode not established
        return False, DocumentReadinessStatus.REQUIREMENT_NOT_ESTABLISHED

    if "fresh" in cond_low:
        if app_type == "RENEWAL":
            return False, DocumentReadinessStatus.NOT_APPLICABLE
        if app_type == "FRESH":
            return True, None

    # 2. Caste / Social Category Quota Applicability
    if req_type == "CONDITIONAL" and any(k in cond_low for k in ["sc/st/obc", "quota", "sc/st/obc/ews"]):
        profile_cat = (profile.get("caste_category") or profile.get("social_category") or "").strip().upper()
        if not profile_cat:
            return False, DocumentReadinessStatus.REQUIREMENT_NOT_ESTABLISHED
        if profile_cat in ("GENERAL", "GEN", "OPEN", "OC", "UNRESERVED"):
            return False, DocumentReadinessStatus.NOT_APPLICABLE
        if profile_cat in ("SC", "ST", "OBC", "EWS"):
            return True, None

    # 3. Disability Quota Applicability
    if req_type == "CONDITIONAL" and any(k in cond_low for k in ["pwd", "disability"]):
        disability_pct = profile.get("disability_percentage")
        is_pwd = profile.get("is_disabled") or (disability_pct is not None and float(disability_pct) >= 40)
        if is_pwd:
            return True, None
        # Optional quota document for non-disabled applicants is NOT_APPLICABLE
        return False, DocumentReadinessStatus.NOT_APPLICABLE

    # 4. Special Beneficiary Categories (e.g. AICTE Swanath)
    if "category 1" in cond_low or "orphan" in cond_low:
        ben_cat = str(profile.get("beneficiary_category") or "").upper()
        if not ben_cat:
            return False, DocumentReadinessStatus.REQUIREMENT_NOT_ESTABLISHED
        if "ORPHAN" in ben_cat:
            return True, None
        return False, DocumentReadinessStatus.NOT_APPLICABLE

    if "category 2" in cond_low or "covid" in cond_low:
        ben_cat = str(profile.get("beneficiary_category") or "").upper()
        if not ben_cat:
            return False, DocumentReadinessStatus.REQUIREMENT_NOT_ESTABLISHED
        if "COVID" in ben_cat:
            return True, None
        return False, DocumentReadinessStatus.NOT_APPLICABLE

    if "category 3" in cond_low or "martyr" in cond_low or "shaheed" in cond_low:
        ben_cat = str(profile.get("beneficiary_category") or "").upper()
        if not ben_cat:
            return False, DocumentReadinessStatus.REQUIREMENT_NOT_ESTABLISHED
        if any(k in ben_cat for k in ["MARTYR", "SHAHEED", "DEFENCE"]):
            return True, None
        return False, DocumentReadinessStatus.NOT_APPLICABLE

    if "category 4" in cond_low or "illness" in cond_low or "accident" in cond_low:
        ben_cat = str(profile.get("beneficiary_category") or "").upper()
        if not ben_cat:
            return False, DocumentReadinessStatus.REQUIREMENT_NOT_ESTABLISHED
        if any(k in ben_cat for k in ["ILLNESS", "ACCIDENT", "CRITICAL"]):
            return True, None
        return False, DocumentReadinessStatus.NOT_APPLICABLE

    # Default: Mandatory documents for all applicants are applicable
    return True, None


def match_user_documents_to_requirement(
    doc_req: Dict[str, Any],
    user_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Match active citizen documents to a required scheme document specification.

    Excludes soft-deleted/archived documents (status == 'ARCHIVED').
    """
    rule_key = _classify_requirement(
        doc_name=doc_req.get("document_name", ""),
        cond=doc_req.get("applicable_condition", ""),
    )
    rule_spec = REQUIREMENT_MATCHING_RULES.get(rule_key, {})

    matches = []
    for doc in user_documents:
        # Strictly ignore archived documents
        if doc.get("status") == "ARCHIVED":
            continue

        doc_cat = str(doc.get("document_category") or "").upper()
        # Priority: confirmed_document_type -> selected_document_type -> document_type
        doc_type = str(
            doc.get("confirmed_document_type")
            or doc.get("selected_document_type")
            or doc.get("document_type")
            or ""
        ).upper()
        doc_fname = str(doc.get("original_filename") or "").lower()

        # Strict Isolation for Aadhaar: ONLY explicit Aadhaar document types match.
        # Filename or generic IDENTITY category must NEVER allow PAN, UNKNOWN, or other docs to match.
        if rule_key == "aadhaar":
            if doc_type in rule_spec.get("types", {"AADHAAR_CARD", "AADHAAR"}):
                matches.append(doc)
            continue

        # Strict Isolation for Bank: ONLY explicit bank document types match.
        # PAN, Aadhaar, UNKNOWN, or other docs must NEVER satisfy bank proof.
        if rule_key == "bank":
            if doc_type in rule_spec.get("types", {"BANK_PASSBOOK", "CANCELLED_CHEQUE", "BANK_STATEMENT"}):
                matches.append(doc)
            elif doc_cat == "BANK" and doc_type not in ("PAN", "PAN_CARD", "AADHAAR_CARD", "AADHAAR", "UNKNOWN", "OTHER", ""):
                matches.append(doc)
            continue

        # Strict Isolation for PAN: ONLY explicit PAN document types match.
        if rule_key == "pan":
            if doc_type in rule_spec.get("types", {"PAN_CARD", "PAN"}):
                matches.append(doc)
            continue

        # General direct match by explicit document_type or category
        if rule_spec:
            if doc_type in rule_spec.get("types", set()):
                matches.append(doc)
                continue
            if doc_cat in rule_spec.get("categories", set()):
                # Do not allow UNKNOWN or conflicting doc_types to match via category
                if doc_type in ("UNKNOWN", "OTHER", ""):
                    continue
                # If rule specifies keywords, verify keyword relevance
                keywords = rule_spec.get("keywords", [])
                if any(k in doc_fname for k in keywords) or any(k in doc_type.lower() for k in keywords):
                    matches.append(doc)
                    continue
                # If category matches and no conflicting keyword required
                if not keywords or rule_key in ("income", "disability"):
                    matches.append(doc)
                    continue

        # Fallback keyword matching on filename (only for specific non-identity/non-bank documents)
        if rule_key not in ("aadhaar", "bank", "pan") and doc_type not in ("PAN", "PAN_CARD", "AADHAAR_CARD", "AADHAAR", "UNKNOWN", "OTHER", ""):
            d_name_tokens = [t for t in doc_req.get("document_name", "").lower().split() if len(t) > 3]
            if any(t in doc_fname for t in d_name_tokens):
                matches.append(doc)

    return matches


def detect_document_conflicts(
    doc_req: Dict[str, Any],
    confirmed_doc: Dict[str, Any],
    profile: Dict[str, Any],
    active_confirmed_fields: Dict[str, Any],
) -> Optional[str]:
    """Detect whether confirmed document values conflict with citizen profile entries."""
    rule_key = _classify_requirement(
        doc_name=doc_req.get("document_name", ""),
        cond=doc_req.get("applicable_condition", ""),
    )

    # 0. Document Metadata & User Selection Integrity
    selected_type = str(confirmed_doc.get("selected_document_type") or "").strip().upper()
    detected_type = str(confirmed_doc.get("detected_document_type") or "").strip().upper()
    if selected_type and detected_type and selected_type != detected_type and detected_type not in ("UNKNOWN", "OTHER"):
        return (
            f"Metadata mismatch detected: User-selected document type '{selected_type}' "
            f"conflicts with system-detected type '{detected_type}'. Manual review required."
        )

    doc_type_val = str(
        confirmed_doc.get("confirmed_document_type")
        or confirmed_doc.get("selected_document_type")
        or confirmed_doc.get("document_type")
        or ""
    ).strip().upper()
    doc_fname = str(confirmed_doc.get("original_filename") or "").lower()

    # Mismatch: Document type is Aadhaar, but filename explicitly indicates PAN
    if doc_type_val in ("AADHAAR_CARD", "AADHAAR") and any(p in doc_fname for p in ["pan_card", "pan-card", "pancard", "pan."]):
        return (
            f"Discrepancy detected: Document type is '{doc_type_val}' "
            f"while filename '{confirmed_doc.get('original_filename')}' indicates a PAN document. Manual review required."
        )

    # Mismatch: Document type is PAN, but filename explicitly indicates Aadhaar
    if doc_type_val in ("PAN", "PAN_CARD") and any(a in doc_fname for a in ["aadhaar", "uidai"]):
        return (
            f"Discrepancy detected: Document type is '{doc_type_val}' "
            f"while filename '{confirmed_doc.get('original_filename')}' indicates an Aadhaar document. Manual review required."
        )

    # 1. Income Conflict
    if rule_key == "income":
        conf_income_item = active_confirmed_fields.get("annual_income") or active_confirmed_fields.get("annual_family_income")
        if conf_income_item:
            try:
                conf_val = float(conf_income_item["value"])
                prof_val = profile.get("annual_income")
                if prof_val is None:
                    prof_val = profile.get("annual_family_income")

                if prof_val is not None:
                    float_prof_val = float(prof_val)
                    if abs(float_prof_val - conf_val) > 0.01:
                        return (
                            f"Discrepancy detected: Profile annual income is ₹{float_prof_val:,.0f} "
                            f"while confirmed document indicates ₹{conf_val:,.0f}."
                        )
            except (ValueError, TypeError):
                pass

    # 2. Caste / Social Category Conflict
    if rule_key in ("caste_sc", "caste_general"):
        conf_caste_item = active_confirmed_fields.get("caste_category") or active_confirmed_fields.get("social_category")
        if conf_caste_item:
            conf_caste = str(conf_caste_item["value"]).strip().upper()
            prof_caste = str(profile.get("caste_category") or profile.get("social_category") or "").strip().upper()

            if prof_caste and conf_caste and prof_caste != conf_caste:
                return (
                    f"Discrepancy detected: Profile social category is '{profile.get('caste_category')}' "
                    f"while confirmed document indicates '{conf_caste_item['value']}'."
                )

    # 3. Gender Conflict
    if rule_key == "aadhaar":
        conf_gender_item = active_confirmed_fields.get("gender")
        if conf_gender_item:
            conf_gender = str(conf_gender_item["value"]).strip().upper()
            prof_gender = str(profile.get("gender") or "").strip().upper()

            if prof_gender and conf_gender and prof_gender != conf_gender:
                return (
                    f"Discrepancy detected: Profile gender is '{profile.get('gender')}' "
                    f"while confirmed document indicates '{conf_gender_item['value']}'."
                )

    return None


def evaluate_scheme_document_readiness(
    scheme: Dict[str, Any],
    user_documents: List[Dict[str, Any]],
    profile: Dict[str, Any],
    active_confirmed_fields: Dict[str, Any],
    application_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate complete document readiness for a given scheme against citizen documents.

    Guarantees:
    - Never uses unreviewed OCR or unconfirmed document values.
    - Excludes archived documents completely.
    - Accurately classifies into the 6 exact DocumentReadinessStatus states.
    - Computes readiness score, confirmed count, and actionable review links.
    """
    required_docs = scheme.get("required_documents", [])
    evaluated_docs = []

    applicable_count = 0
    confirmed_count = 0
    pending_count = 0
    missing_count = 0
    conflicting_count = 0

    for doc_req in required_docs:
        doc_name = doc_req.get("document_name", "Required Document")
        req_type = str(doc_req.get("requirement_type") or doc_req.get("mandatory_or_optional") or "MANDATORY").upper()
        cond = doc_req.get("applicable_condition", "")

        # Step 1: Check Applicability
        is_applicable, status_not_app = check_document_applicability(
            doc_req=doc_req,
            profile=profile,
            application_type=application_type,
        )

        if not is_applicable:
            evaluated_docs.append({
                "document_name": doc_name,
                "requirement_type": req_type,
                "applicable_condition": cond,
                "status": status_not_app.value if status_not_app else DocumentReadinessStatus.NOT_APPLICABLE.value,
                "matched_document_id": None,
                "matched_document_name": None,
                "matched_document_type": None,
                "matched_document_category": None,
                "explanation": (
                    "Not applicable based on current application profile or criteria."
                    if status_not_app == DocumentReadinessStatus.NOT_APPLICABLE
                    else "Applicability condition cannot be determined from profile."
                ),
                "action_required": None,
                "action_document_id": None,
                "evidence_snippet": None,
            })
            continue

        applicable_count += 1

        # Step 2: Match active documents
        matches = match_user_documents_to_requirement(doc_req, user_documents)

        if not matches:
            missing_count += 1
            evaluated_docs.append({
                "document_name": doc_name,
                "requirement_type": req_type,
                "applicable_condition": cond,
                "status": DocumentReadinessStatus.MISSING.value,
                "matched_document_id": None,
                "matched_document_name": None,
                "matched_document_type": None,
                "matched_document_category": None,
                "explanation": "Document not uploaded to your document library.",
                "action_required": "UPLOAD_REQUIRED",
                "action_document_id": None,
                "evidence_snippet": None,
            })
            continue

        # Step 3: Check confirmation & conflict status among matched documents
        confirmed_matches = [
            m for m in matches
            if m.get("confirmation_status") == "CONFIRMED" or m.get("status") == "CONFIRMED"
        ]
        pending_matches = [
            m for m in matches
            if m.get("confirmation_status") == "PENDING_CONFIRMATION" or m.get("status") in ("PENDING_REVIEW", "PENDING_CONFIRMATION", "PROCESSED")
        ]

        if confirmed_matches:
            primary_match = confirmed_matches[0]
            conflict_msg = detect_document_conflicts(
                doc_req=doc_req,
                confirmed_doc=primary_match,
                profile=profile,
                active_confirmed_fields=active_confirmed_fields,
            )

            if conflict_msg:
                conflicting_count += 1
                evaluated_docs.append({
                    "document_name": doc_name,
                    "requirement_type": req_type,
                    "applicable_condition": cond,
                    "status": DocumentReadinessStatus.CONFLICTING.value,
                    "matched_document_id": primary_match.get("document_id"),
                    "matched_document_name": primary_match.get("original_filename"),
                    "matched_document_type": primary_match.get("document_type"),
                    "matched_document_category": primary_match.get("document_category"),
                    "explanation": conflict_msg,
                    "action_required": "RESOLVE_CONFLICT",
                    "action_document_id": primary_match.get("document_id"),
                    "evidence_snippet": None,
                })
            else:
                confirmed_count += 1
                evaluated_docs.append({
                    "document_name": doc_name,
                    "requirement_type": req_type,
                    "applicable_condition": cond,
                    "status": DocumentReadinessStatus.AVAILABLE_AND_CONFIRMED.value,
                    "matched_document_id": primary_match.get("document_id"),
                    "matched_document_name": primary_match.get("original_filename"),
                    "matched_document_type": primary_match.get("document_type"),
                    "matched_document_category": primary_match.get("document_category"),
                    "explanation": "Document uploaded and confirmed by citizen.",
                    "action_required": None,
                    "action_document_id": None,
                    "evidence_snippet": f"Confirmed from {primary_match.get('original_filename', primary_match.get('document_type'))}",
                })
        elif pending_matches:
            pending_count += 1
            primary_pending = pending_matches[0]
            evaluated_docs.append({
                "document_name": doc_name,
                "requirement_type": req_type,
                "applicable_condition": cond,
                "status": DocumentReadinessStatus.PENDING_CONFIRMATION.value,
                "matched_document_id": primary_pending.get("document_id"),
                "matched_document_name": primary_pending.get("original_filename"),
                "matched_document_type": primary_pending.get("document_type"),
                "matched_document_category": primary_pending.get("document_category"),
                "explanation": "Document uploaded but OCR extraction pending citizen review.",
                "action_required": "REVIEW_PENDING",
                "action_document_id": primary_pending.get("document_id"),
                "evidence_snippet": None,
            })
        else:
            missing_count += 1
            evaluated_docs.append({
                "document_name": doc_name,
                "requirement_type": req_type,
                "applicable_condition": cond,
                "status": DocumentReadinessStatus.MISSING.value,
                "matched_document_id": None,
                "matched_document_name": None,
                "matched_document_type": None,
                "matched_document_category": None,
                "explanation": "Document not uploaded to your document library.",
                "action_required": "UPLOAD_REQUIRED",
                "action_document_id": None,
                "evidence_snippet": None,
            })

    is_ready = (confirmed_count == applicable_count) and (applicable_count > 0) and (conflicting_count == 0)

    if is_ready:
        status_badge = "READY"
    elif conflicting_count > 0:
        status_badge = "CONFLICT"
    elif pending_count > 0:
        status_badge = "PENDING_REVIEW"
    else:
        status_badge = "INCOMPLETE"

    readiness_percentage = round((confirmed_count / applicable_count * 100), 1) if applicable_count > 0 else 0.0

    return {
        "scheme_id": scheme.get("scheme_id"),
        "total_required": applicable_count,
        "confirmed_count": confirmed_count,
        "pending_count": pending_count,
        "missing_count": missing_count,
        "conflicting_count": conflicting_count,
        "is_ready": is_ready,
        "readiness_percentage": readiness_percentage,
        "status_badge": status_badge,
        "documents": evaluated_docs,
    }


def extract_confirmed_field_evidence(
    scheme: Dict[str, Any],
    active_confirmed_fields: Dict[str, Any],
    profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract verifiable evidence chips supporting the scheme based on confirmed documents."""
    evidence_chips = []

    # 1. Confirmed Annual Income
    inc_item = active_confirmed_fields.get("annual_income") or active_confirmed_fields.get("annual_family_income")
    if inc_item:
        try:
            val_num = float(inc_item["value"])
            formatted_val = f"₹{val_num:,.0f}"
        except (ValueError, TypeError):
            formatted_val = str(inc_item["value"])

        evidence_chips.append({
            "criterion": "annual_family_income",
            "label": "Confirmed Income",
            "value": formatted_val,
            "document_type": inc_item.get("document_type", "INCOME_CERTIFICATE"),
            "document_id": inc_item.get("document_id"),
            "status": "CONFIRMED",
        })

    # 2. Confirmed Social Category / Caste
    caste_item = active_confirmed_fields.get("caste_category") or active_confirmed_fields.get("social_category")
    if caste_item:
        evidence_chips.append({
            "criterion": "social_category",
            "label": "Confirmed Category",
            "value": str(caste_item["value"]).upper(),
            "document_type": caste_item.get("document_type", "CASTE_CERTIFICATE"),
            "document_id": caste_item.get("document_id"),
            "status": "CONFIRMED",
        })

    # 3. Confirmed Gender
    gender_item = active_confirmed_fields.get("gender")
    if gender_item:
        evidence_chips.append({
            "criterion": "gender",
            "label": "Confirmed Gender",
            "value": str(gender_item["value"]).title(),
            "document_type": gender_item.get("document_type", "AADHAAR_CARD"),
            "document_id": gender_item.get("document_id"),
            "status": "CONFIRMED",
        })

    # 4. Confirmed Class 12 Percentage / Merit
    marks_item = (
        active_confirmed_fields.get("twelfth_percentage")
        or active_confirmed_fields.get("class_12_merit_percentile")
        or active_confirmed_fields.get("class_12_minimum_marks_percentage")
    )
    if marks_item:
        evidence_chips.append({
            "criterion": "class_12_merit_percentile",
            "label": "Confirmed Class 12 Merit",
            "value": f"{marks_item['value']}%",
            "document_type": marks_item.get("document_type", "MARKSHEET_12TH"),
            "document_id": marks_item.get("document_id"),
            "status": "CONFIRMED",
        })

    return evidence_chips

