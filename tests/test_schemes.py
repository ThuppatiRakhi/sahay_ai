"""Unit and integration tests for multi-stage scheme verification and collection sources."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from scheme_collection.collect_schemes import (
    LocalFileSchemeSource,
    OfficialAPISchemeSource,
    SchemeCollector,
)
from scheme_collection.scheme_validator import SchemeValidator
from scheme_collection.verify_schemes import SchemeVerifier


@pytest.fixture
def sample_valid_scheme():
    return {
        "scheme_id": "PM_KISAN_001",
        "scheme_name": "Pradhan Mantri Kisan Samman Nidhi",
        "department": "Ministry of Agriculture and Farmers Welfare",
        "description": "Income support scheme providing 6000 per year to eligible farmer families.",
        "source_portal": "https://pmkisan.gov.in",
        "operational_status": "ACTIVE",
        "eligibility": {
            "min_age": 18,
            "max_age": 75,
            "gender": "ALL",
            "max_annual_income": None,
            "occupation": ["Farmer"],
            "landholding": True,
            "states": ["ALL"],
        },
        "benefits": {
            "type": "Direct Benefit Transfer",
            "amount_annual": 6000.0,
            "disbursement_frequency": "Every 4 months",
        },
        "required_documents": ["Aadhaar Card", "Land Record", "Bank Passbook"],
        "application_url": "https://pmkisan.gov.in/registration",
        "human_review": {
            "reviewer_id": "REV_OFFICER_042",
            "decision": "APPROVED",
            "review_notes": "Verified against Ministry Gazette notification and active portal registration.",
            "reviewed_at": "2026-11-01T10:00:00Z",
        },
        "is_verified": False,
    }


def test_scheme_validator_valid(sample_valid_scheme):
    validator = SchemeValidator()
    is_valid, errors = validator.validate(sample_valid_scheme)
    assert is_valid is True, f"Validation errors: {errors}"
    assert len(errors) == 0


def test_scheme_validator_invalid_age_range(sample_valid_scheme):
    validator = SchemeValidator()
    sample_valid_scheme["eligibility"]["min_age"] = 60
    sample_valid_scheme["eligibility"]["max_age"] = 30
    is_valid, errors = validator.validate(sample_valid_scheme)
    assert is_valid is False
    assert any("min_age" in err for err in errors)


def test_multistage_verification_all_passed(sample_valid_scheme):
    """Test full 5-stage verification when all criteria and human review are met."""
    verifier = SchemeVerifier()
    report = verifier.verify_single(sample_valid_scheme)

    assert report.is_fully_verified is True
    assert report.stages["structural_validation"]["passed"] is True
    assert report.stages["source_authenticity"]["passed"] is True
    assert report.stages["operational_status"]["passed"] is True
    assert report.stages["application_url"]["passed"] is True
    assert report.stages["human_review"]["passed"] is True
    assert report.verified_record["is_verified"] is True
    assert report.verified_record["verification_source"] == "pmkisan.gov.in"


def test_verification_fails_without_human_review(sample_valid_scheme):
    """Ensure scheme is never marked verified without explicit human approval."""
    del sample_valid_scheme["human_review"]
    verifier = SchemeVerifier()
    report = verifier.verify_single(sample_valid_scheme)

    assert report.is_fully_verified is False
    assert report.stages["human_review"]["passed"] is False
    assert any("human review" in r.lower() for r in report.failure_reasons)


def test_verification_fails_if_discontinued(sample_valid_scheme):
    """Ensure discontinued schemes cannot be verified as active schemes."""
    sample_valid_scheme["operational_status"] = "DISCONTINUED"
    verifier = SchemeVerifier()
    report = verifier.verify_single(sample_valid_scheme)

    assert report.is_fully_verified is False
    assert report.stages["operational_status"]["passed"] is False
    assert any("discontinued" in r.lower() for r in report.failure_reasons)


def test_verification_rejects_non_official_domain(sample_valid_scheme):
    """Ensure non-government domains fail authenticity check."""
    sample_valid_scheme["application_url"] = "https://untrusted-schemes.com/apply"
    verifier = SchemeVerifier()
    report = verifier.verify_single(sample_valid_scheme)

    assert report.is_fully_verified is False
    assert report.stages["source_authenticity"]["passed"] is False


def test_verification_rejects_unrecognized_department(sample_valid_scheme):
    """Ensure unknown/private entities cannot pass as government departments."""
    sample_valid_scheme["department"] = "Private Welfare Foundation LLC"
    verifier = SchemeVerifier()
    report = verifier.verify_single(sample_valid_scheme)

    assert report.is_fully_verified is False
    assert report.stages["source_authenticity"]["passed"] is False


def test_local_file_source_ingestion(tmp_path, sample_valid_scheme):
    file_path = tmp_path / "raw.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump([sample_valid_scheme], f)

    source = LocalFileSchemeSource(str(file_path))
    schemes = source.fetch_schemes()
    assert len(schemes) == 1
    assert schemes[0]["scheme_id"] == "PM_KISAN_001"


def test_api_source_respects_access_restrictions():
    """Ensure API source respects HTTP 429/403 restrictions and does not attempt bypass."""
    source = OfficialAPISchemeSource("https://api.myscheme.gov.in/schemes")

    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(PermissionError) as exc_info:
            source.fetch_schemes()
        assert "Rate limit" in str(exc_info.value)


def test_research_batch1_schemes_validate_against_schema():
    """Verify that all researched batch 1 schemes strictly validate against the schema."""
    schemes_path = Path("data/schemes/schemes.json")
    assert schemes_path.exists(), "data/schemes/schemes.json must exist"

    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    assert len(schemes) == 5, f"Expected 5 schemes in batch 1, found {len(schemes)}"
    validator = SchemeValidator()

    for scheme in schemes:
        is_valid, errors = validator.validate(scheme)
        assert is_valid is True, f"Scheme {scheme.get('scheme_id')} failed validation: {errors}"
        assert scheme.get("category") == "EDUCATION"
        assert scheme.get("government_level") == "Central"
        assert scheme.get("verification_status") in ("pending_review", "partial", "verified")


def test_research_batch1_no_duplicate_schemes():
    """Verify that no duplicate scheme_id or scheme_name exists in batch 1."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    duplicates = SchemeValidator.detect_duplicates(schemes)
    assert len(duplicates) == 0, f"Found unexpected duplicates: {duplicates}"


def test_research_batch1_structured_rules_integrity():
    """Verify that all structured eligibility rules are structurally sound."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    validator = SchemeValidator()
    for scheme in schemes:
        is_valid, issues = validator.validate_structured_rules(scheme)
        assert is_valid is True, f"Structured rules error in {scheme.get('scheme_id')}: {issues}"
        rules = scheme.get("eligibility", {}).get("structured_rules", [])
        assert len(rules) > 0, f"Scheme {scheme.get('scheme_id')} must have structured rules defined"


def test_research_batch1_official_sources_validity():
    """Verify official sources and portal URL formatting."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    validator = SchemeValidator()
    for scheme in schemes:
        is_valid, issues = validator.validate_official_sources(scheme)
        assert is_valid is True, f"Source validation error in {scheme.get('scheme_id')}: {issues}"
        sources = scheme.get("official_sources", [])
        assert len(sources) >= 1, f"Scheme {scheme.get('scheme_id')} must have at least 1 official source"


def test_research_batch1_unreviewed_schemes_cannot_enter_verified_store(tmp_path):
    """Ensure pending_review records are never written to verified_schemes.json."""
    raw_path = tmp_path / "raw_schemes.json"
    verified_path = tmp_path / "verified_schemes.json"

    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(schemes, f)

    verifier = SchemeVerifier(
        raw_schemes_path=str(raw_path),
        verified_schemes_path=str(verified_path),
    )
    verified_count, rejected_count = verifier.verify_and_save()

    assert verified_count == 0, "No pending_review scheme should be written to verified_schemes.json"
    assert rejected_count == len(schemes)

    with open(verified_path, "r", encoding="utf-8") as f:
        verified_data = json.load(f)
    assert len(verified_data) == 0, "verified_schemes.json must remain empty before human review"


def test_missing_fields_reporting():
    """Test reporting utility for critical and recommended missing fields."""
    incomplete_scheme = {
        "scheme_id": "TEST_001",
        "scheme_name": "Test Scheme",
        "department": "Ministry of Education",
        "description": "Short description",
        "eligibility": {},
        "benefits": {"type": "Direct Benefit Transfer"},
        "application_url": "https://education.gov.in",
    }
    report = SchemeValidator.report_missing_fields(incomplete_scheme)
    assert "eligibility.structured_rules" in report["recommended_missing"]
    assert "official_sources" in report["recommended_missing"]


def test_batch1_separated_status_fields():
    """Verify that scheme operational status and application status are separated."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    valid_scheme_statuses = {"ACTIVE", "INACTIVE", "DISCONTINUED", "MERGED", "RENAMED", "UNCERTAIN"}
    valid_application_statuses = {"OPEN", "CLOSED", "NOT_YET_OPEN", "NOT_ANNOUNCED", "YEAR_ROUND", "UNKNOWN"}

    for scheme in schemes:
        s_status = scheme.get("scheme_status")
        a_status = scheme.get("application_status")
        assert s_status in valid_scheme_statuses, f"Invalid scheme_status '{s_status}' in {scheme.get('scheme_id')}"
        assert a_status in valid_application_statuses, f"Invalid application_status '{a_status}' in {scheme.get('scheme_id')}"
        assert scheme.get("current_application_cycle") is not None
        assert scheme.get("application_status_last_checked") is not None


def test_batch1_document_requirement_types():
    """Verify that all documents are properly categorized as MANDATORY, CONDITIONAL, or OPTIONAL."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    validator = SchemeValidator()
    for scheme in schemes:
        is_valid, issues = validator.validate_document_requirements(scheme)
        assert is_valid is True, f"Document validation error in {scheme.get('scheme_id')}: {issues}"

        docs = scheme.get("required_documents", [])
        mandatory_docs = [d for d in docs if d.get("requirement_type") == "MANDATORY"]
        assert len(mandatory_docs) >= 3, f"Scheme {scheme.get('scheme_id')} must have at least 3 mandatory core documents"


def test_batch1_source_evidence_audit_completeness():
    """Verify that all schemes contain structured source evidence audits."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    for scheme in schemes:
        audit_entries = scheme.get("source_evidence_audit")
        assert audit_entries is not None, f"Scheme {scheme.get('scheme_id')} missing source_evidence_audit"
        assert len(audit_entries) >= 1, f"Scheme {scheme.get('scheme_id')} must contain at least 1 audit entry"
        for entry in audit_entries:
            assert "topic" in entry
            assert "primary_source" in entry
            assert "claim" in entry["primary_source"]
            assert "is_conflict_resolved" in entry


def test_batch1_swanath_conditional_rules_and_documents():
    """Verify AICTE Swanath has ANY_OF grouping and category-specific conditional documents."""
    schemes_path = Path("data/schemes/schemes.json")
    with open(schemes_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    swanath = next((s for s in schemes if s["scheme_id"] == "SCHEME_EDU_004_AICTE_SWANATH"), None)
    assert swanath is not None

    rules = swanath["eligibility"]["structured_rules"]
    cat_rule = next((r for r in rules if r["criterion"] == "beneficiary_category"), None)
    assert cat_rule is not None
    assert cat_rule["operator"] == "ANY_OF"
    assert cat_rule["logical_group"] == "ANY_OF"

    docs = swanath["required_documents"]
    doc_names = [d["document_name"] for d in docs]
    assert any("Orphan" in name for name in doc_names)
    assert any("COVID-19" in name for name in doc_names)
    assert any("Shaheed" in name or "Martyr" in name for name in doc_names)


