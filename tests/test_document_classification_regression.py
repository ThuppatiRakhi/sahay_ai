"""Regression tests for Document Classification and Matching Safety (Scheme 1 Bug Fix).

Covers:
1. PAN cannot satisfy Aadhaar through filename matching.
2. PAN cannot satisfy bank proof.
3. Aadhaar with a conflicting PAN filename triggers manual review.
4. Correct Aadhaar document matches Aadhaar requirement.
5. Correct bank passbook matches bank requirement.
6. Aadhaar-seeded bank statement satisfies bank proof only.
7. Unknown document type cannot automatically satisfy Aadhaar.
8. Unknown document type cannot automatically satisfy bank proof.
9. User-confirmed document type is preserved.
10. Conflicting detected metadata does not silently overwrite user selection.
11. Single PAN document cannot satisfy both Aadhaar and bank requirements.
12. Existing valid document matching for marksheets, income, caste and bonafide remains functional.
13. Unconfirmed or archived documents do not become valid confirmed evidence.
14. Requirement classification check: 'Bank Passbook / Statement (Aadhaar-seeded)' classifies as 'bank'.
"""

import pytest
from scheme_collection.document_readiness import (
    DocumentReadinessStatus,
    _classify_requirement,
    match_user_documents_to_requirement,
    evaluate_scheme_document_readiness,
)


def test_01_pan_cannot_satisfy_aadhaar_through_filename_matching():
    """1. PAN cannot satisfy Aadhaar through filename matching (doc_type=PAN, filename=aadhaar_card.pdf)."""
    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }
    pan_doc = {
        "document_id": "doc_pan_with_aadhaar_name",
        "document_type": "PAN",
        "document_category": "IDENTITY",
        "original_filename": "aadhaar_card.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    matches = match_user_documents_to_requirement(aadhaar_req, [pan_doc])
    assert len(matches) == 0


def test_02_pan_cannot_satisfy_bank_proof():
    """2. PAN cannot satisfy bank proof (doc_type=PAN, filename=bank_statement.pdf)."""
    bank_req = {
        "document_name": "Bank Passbook / Statement (Aadhaar-seeded)",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants (must be individual savings account)",
    }
    pan_doc = {
        "document_id": "doc_pan_with_bank_name",
        "document_type": "PAN",
        "document_category": "IDENTITY",
        "original_filename": "bank_statement.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    matches = match_user_documents_to_requirement(bank_req, [pan_doc])
    assert len(matches) == 0


def test_03_aadhaar_with_conflicting_pan_filename_triggers_manual_review():
    """3. Aadhaar with a conflicting PAN filename triggers manual review (status=CONFLICTING)."""
    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }
    conflicting_doc = {
        "document_id": "doc_aadhaar_pan_name",
        "document_type": "AADHAAR_CARD",
        "document_category": "IDENTITY",
        "original_filename": "pan_card.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    scheme = {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "required_documents": [aadhaar_req],
    }
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[conflicting_doc],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    doc_res = readiness["documents"][0]
    assert doc_res["status"] == DocumentReadinessStatus.CONFLICTING.value
    assert doc_res["action_required"] == "RESOLVE_CONFLICT"
    assert "indicates a PAN document" in doc_res["explanation"]
    assert readiness["is_ready"] is False


def test_04_correct_aadhaar_document_matches_aadhaar_requirement():
    """4. Correct Aadhaar document matches Aadhaar requirement."""
    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }
    aadhaar_doc = {
        "document_id": "doc_aadhaar_valid",
        "document_type": "AADHAAR_CARD",
        "document_category": "IDENTITY",
        "original_filename": "aadhaar_card.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    scheme = {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "required_documents": [aadhaar_req],
    }
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[aadhaar_doc],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    doc_res = readiness["documents"][0]
    assert doc_res["status"] == DocumentReadinessStatus.AVAILABLE_AND_CONFIRMED.value
    assert doc_res["matched_document_type"] == "AADHAAR_CARD"
    assert readiness["is_ready"] is True


def test_05_correct_bank_passbook_matches_bank_requirement():
    """5. Correct bank passbook matches bank requirement."""
    bank_req = {
        "document_name": "Bank Passbook / Statement (Aadhaar-seeded)",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants (must be individual savings account)",
    }
    bank_doc = {
        "document_id": "doc_bank_valid",
        "document_type": "BANK_PASSBOOK",
        "document_category": "BANK",
        "original_filename": "bank_statement.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    scheme = {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "required_documents": [bank_req],
    }
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[bank_doc],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    doc_res = readiness["documents"][0]
    assert doc_res["status"] == DocumentReadinessStatus.AVAILABLE_AND_CONFIRMED.value
    assert doc_res["matched_document_type"] == "BANK_PASSBOOK"
    assert readiness["is_ready"] is True


def test_06_aadhaar_seeded_bank_statement_satisfies_bank_proof_only():
    """6. Aadhaar-seeded bank statement satisfies bank proof only, without inferring Aadhaar seeding."""
    bank_req = {
        "document_name": "Bank Passbook / Statement (Aadhaar-seeded)",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants (must be individual savings account)",
    }
    bank_doc = {
        "document_id": "doc_bank_seeded",
        "document_type": "BANK_PASSBOOK",
        "document_category": "BANK",
        "original_filename": "aadhaar_seeded_statement.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    scheme = {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "required_documents": [bank_req],
    }
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[bank_doc],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    doc_res = readiness["documents"][0]
    assert doc_res["status"] == DocumentReadinessStatus.AVAILABLE_AND_CONFIRMED.value
    assert doc_res["evidence_snippet"] == "Confirmed from aadhaar_seeded_statement.pdf"


def test_07_unknown_document_type_cannot_automatically_satisfy_aadhaar():
    """7. Unknown document type cannot automatically satisfy Aadhaar by filename."""
    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }
    unknown_doc = {
        "document_id": "doc_unknown_aadhaar",
        "document_type": "UNKNOWN",
        "document_category": "OTHER",
        "original_filename": "aadhaar_card.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    matches = match_user_documents_to_requirement(aadhaar_req, [unknown_doc])
    assert len(matches) == 0


def test_08_unknown_document_type_cannot_automatically_satisfy_bank_proof():
    """8. Unknown document type cannot automatically satisfy bank proof by filename."""
    bank_req = {
        "document_name": "Bank Passbook / Statement (Aadhaar-seeded)",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants (must be individual savings account)",
    }
    unknown_doc = {
        "document_id": "doc_unknown_bank",
        "document_type": "UNKNOWN",
        "document_category": "OTHER",
        "original_filename": "bank_statement.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    matches = match_user_documents_to_requirement(bank_req, [unknown_doc])
    assert len(matches) == 0


def test_09_user_confirmed_document_type_is_preserved():
    """9. User-confirmed document type is preserved over other fields."""
    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }
    confirmed_doc = {
        "document_id": "doc_confirmed_override",
        "confirmed_document_type": "AADHAAR_CARD",
        "selected_document_type": "OTHER",
        "document_type": "OTHER",
        "document_category": "IDENTITY",
        "original_filename": "my_doc.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    matches = match_user_documents_to_requirement(aadhaar_req, [confirmed_doc])
    assert len(matches) == 1
    assert matches[0]["document_id"] == "doc_confirmed_override"


def test_10_conflicting_detected_metadata_does_not_silently_overwrite_user_selection():
    """10. Conflicting detected metadata preserves user selection but flags conflict for review."""
    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }
    doc_with_ocr_conflict = {
        "document_id": "doc_ocr_mismatch",
        "selected_document_type": "AADHAAR_CARD",
        "detected_document_type": "PAN",
        "document_type": "AADHAAR_CARD",
        "document_category": "IDENTITY",
        "original_filename": "scanned_doc.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    scheme = {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "required_documents": [aadhaar_req],
    }
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[doc_with_ocr_conflict],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    doc_res = readiness["documents"][0]
    # Selected type AADHAAR_CARD was preserved (it matched Aadhaar req)
    assert doc_res["matched_document_type"] == "AADHAAR_CARD"
    # But conflict was flagged
    assert doc_res["status"] == DocumentReadinessStatus.CONFLICTING.value
    assert doc_res["action_required"] == "RESOLVE_CONFLICT"
    assert "conflicts with system-detected type 'PAN'" in doc_res["explanation"]


def test_11_single_pan_document_cannot_satisfy_both_aadhaar_and_bank():
    """11. A user with only a PAN card has both Aadhaar and Bank marked as MISSING."""
    pan_doc = {
        "document_id": "doc_8e391ba456564147",
        "document_type": "PAN",
        "document_category": "IDENTITY",
        "original_filename": "pan_card.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "CONFIRMED",
    }
    scheme = {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "required_documents": [
            {
                "document_name": "Aadhaar Card",
                "requirement_type": "MANDATORY",
                "applicable_condition": "All applicants",
            },
            {
                "document_name": "Bank Passbook / Statement (Aadhaar-seeded)",
                "requirement_type": "MANDATORY",
                "applicable_condition": "All applicants (must be individual savings account)",
            },
        ],
    }
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[pan_doc],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    assert readiness["confirmed_count"] == 0
    assert readiness["missing_count"] == 2
    assert readiness["is_ready"] is False


def test_12_existing_valid_document_matching_remains_functional():
    """12. Existing valid document matching for marksheets, income, caste and bonafide remains functional."""
    user_docs = [
        {
            "document_id": "doc_12th",
            "document_type": "MARKSHEET_12TH",
            "document_category": "ACADEMIC",
            "original_filename": "12th_marksheet.pdf",
            "confirmation_status": "CONFIRMED",
            "status": "CONFIRMED",
        },
        {
            "document_id": "doc_income",
            "document_type": "INCOME_CERTIFICATE",
            "document_category": "INCOME",
            "original_filename": "income_cert.pdf",
            "confirmation_status": "CONFIRMED",
            "status": "CONFIRMED",
        },
        {
            "document_id": "doc_caste",
            "document_type": "SC_CERTIFICATE",
            "document_category": "CATEGORY_CERTIFICATE",
            "original_filename": "sc_caste.pdf",
            "confirmation_status": "CONFIRMED",
            "status": "CONFIRMED",
        },
        {
            "document_id": "doc_bonafide",
            "document_type": "BONAFIDE_CERTIFICATE",
            "document_category": "ACADEMIC",
            "original_filename": "college_bonafide.pdf",
            "confirmation_status": "CONFIRMED",
            "status": "CONFIRMED",
        },
    ]

    req_12th = {"document_name": "Class 12 Marksheet", "applicable_condition": "Fresh"}
    req_income = {"document_name": "Annual Family Income Certificate", "applicable_condition": "All"}
    req_caste = {"document_name": "Caste / Category Certificate", "applicable_condition": "SC quota"}
    req_bonafide = {"document_name": "College Admission Proof / Bonafide Certificate", "applicable_condition": "All"}

    assert len(match_user_documents_to_requirement(req_12th, user_docs)) == 1
    assert len(match_user_documents_to_requirement(req_income, user_docs)) == 1
    assert len(match_user_documents_to_requirement(req_caste, user_docs)) == 1
    assert len(match_user_documents_to_requirement(req_bonafide, user_docs)) == 1


def test_13_unconfirmed_or_archived_documents_do_not_become_confirmed_evidence():
    """13. Archived documents are strictly ignored, and unconfirmed docs remain pending."""
    archived_aadhaar = {
        "document_id": "doc_archived",
        "document_type": "AADHAAR_CARD",
        "document_category": "IDENTITY",
        "original_filename": "old_aadhaar.pdf",
        "confirmation_status": "CONFIRMED",
        "status": "ARCHIVED",
    }
    pending_aadhaar = {
        "document_id": "doc_pending",
        "document_type": "AADHAAR_CARD",
        "document_category": "IDENTITY",
        "original_filename": "pending_aadhaar.pdf",
        "confirmation_status": "PENDING_CONFIRMATION",
        "status": "PENDING_REVIEW",
    }

    aadhaar_req = {
        "document_name": "Aadhaar Card",
        "requirement_type": "MANDATORY",
        "applicable_condition": "All applicants",
    }

    assert len(match_user_documents_to_requirement(aadhaar_req, [archived_aadhaar])) == 0

    scheme = {"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "required_documents": [aadhaar_req]}
    profile = {"application_type": "FRESH"}
    readiness = evaluate_scheme_document_readiness(
        scheme=scheme,
        user_documents=[pending_aadhaar],
        profile=profile,
        active_confirmed_fields={},
        application_type="FRESH",
    )
    assert readiness["confirmed_count"] == 0
    assert readiness["pending_count"] == 1
    assert readiness["is_ready"] is False
    assert readiness["documents"][0]["status"] == DocumentReadinessStatus.PENDING_CONFIRMATION.value


def test_14_bank_passbook_aadhaar_seeded_classified_as_bank():
    """14. Requirement 'Bank Passbook / Statement (Aadhaar-seeded)' is classified as bank, not aadhaar."""
    key = _classify_requirement("Bank Passbook / Statement (Aadhaar-seeded)", "")
    assert key == "bank"
