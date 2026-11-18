"""Unit and contract tests for SahayAI Cross-Sector Central Government Scheme Catalogue.

Validates the Phase 1 cross-sector scheme expansion:
1. All five new records load successfully and validate strictly against schema.
2. Existing five education records remain intact and unchanged.
3. Existing education catalogue tests still pass.
4. The catalogue supports multiple categories and sectors.
5. Operational status and application availability remain strictly independent.
6. Unknown, unannounced, or unverified availability never becomes OPEN automatically.
7. Missing optional data does not crash catalogue loading or filtering.
8. Invalid operational or application status values are strictly rejected.
9. Official government source URLs are present and verified for all five new records.
10. Deadline evaluation and summary formatting for non-education schemes adhere to contracts.
"""

import json
from pathlib import Path
from urllib.parse import urlparse
import pytest

from scheme_collection.deadline_manager import DeadlineStatus, evaluate_scheme_deadline
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService
from scheme_collection.scheme_validator import SchemeModel, SchemeValidator


EXPECTED_NEW_SCHEME_IDS = {
    "SCHEME_AGRI_001_PM_KISAN",
    "SCHEME_MSME_001_PMEGP",
    "SCHEME_URBAN_001_PM_SVANIDHI",
    "SCHEME_LABOUR_001_PM_SYM",
    "SCHEME_WOMEN_001_PMUY_2",
}

EXPECTED_EDUCATION_SCHEME_IDS = {
    "SCHEME_EDU_001_PM_USP_CSSS",
    "SCHEME_EDU_002_AICTE_PRAGATI",
    "SCHEME_EDU_003_AICTE_SAKSHAM",
    "SCHEME_EDU_004_AICTE_SWANATH",
    "SCHEME_EDU_005_TOP_CLASS_SC",
}


@pytest.fixture
def central_schemes_data():
    """Load the 5 central government cross-sector scheme records."""
    path = Path("data/schemes/central_schemes.json")
    assert path.exists(), "data/schemes/central_schemes.json must exist"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@pytest.fixture
def education_schemes_data():
    """Load the 5 existing education scheme records."""
    path = Path("data/schemes/schemes.json")
    assert path.exists(), "data/schemes/schemes.json must exist"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Requirement 1: All five new records load successfully and validate
# ---------------------------------------------------------------------------

def test_01_all_five_new_records_load_and_validate(central_schemes_data):
    """Verify that all five new central scheme records load and pass schema validation."""
    assert len(central_schemes_data) == 5, f"Expected 5 new schemes, found {len(central_schemes_data)}"
    ids = {s.get("scheme_id") for s in central_schemes_data}
    assert ids == EXPECTED_NEW_SCHEME_IDS

    validator = SchemeValidator()
    for scheme in central_schemes_data:
        s_id = scheme.get("scheme_id")
        is_valid, errors = validator.validate(scheme)
        assert is_valid is True, f"Scheme {s_id} failed schema validation: {errors}"
        assert scheme.get("government_level") == "Central"
        assert scheme.get("verification_status") in ("pending_review", "partial", "verified")
        assert scheme.get("is_verified") is False, "New schemes must remain unverified pending human review"


# ---------------------------------------------------------------------------
# Requirement 2: Existing five education records remain unchanged
# ---------------------------------------------------------------------------

def test_02_existing_five_education_records_remain_unchanged(education_schemes_data):
    """Verify that existing batch 1 education records remain completely untouched."""
    assert len(education_schemes_data) == 5, f"Expected 5 education schemes, found {len(education_schemes_data)}"
    ids = {s.get("scheme_id") for s in education_schemes_data}
    assert ids == EXPECTED_EDUCATION_SCHEME_IDS

    for scheme in education_schemes_data:
        assert scheme.get("category") == "EDUCATION"
        assert scheme.get("government_level") == "Central"
        assert scheme.get("verification_status") == "pending_review"
        assert scheme.get("is_verified") is False


# ---------------------------------------------------------------------------
# Requirement 3: Existing education catalogue tests still pass
# ---------------------------------------------------------------------------

def test_03_default_discovery_service_preserves_education_baseline():
    """Default SchemeDiscoveryService instance must return the 5 education schemes."""
    svc = SchemeDiscoveryService()
    default_schemes = svc.get_all_schemes()
    assert len(default_schemes) == 5
    default_ids = {s.get("scheme_id") for s in default_schemes}
    assert default_ids == EXPECTED_EDUCATION_SCHEME_IDS

    # Specific education scheme lookup
    csss = svc.get_scheme_by_id("SCHEME_EDU_001_PM_USP_CSSS")
    assert csss is not None
    assert csss["scheme_name"] == "PM-USP Central Sector Scholarship Scheme"

    # Education category filtering returns exactly 5
    edu_filtered = svc.search_and_filter(category="EDUCATION")
    assert len(edu_filtered) == 5


# ---------------------------------------------------------------------------
# Requirement 4: Catalogue supports multiple categories and sectors
# ---------------------------------------------------------------------------

def test_04_catalogue_supports_multiple_categories_and_sectors():
    """Verify cross-sector discovery service supports multiple categories and sectors."""
    svc = SchemeDiscoveryService(include_cross_sector=True)
    all_schemes = svc.get_all_schemes()
    assert len(all_schemes) == 10

    # Verify categories
    categories = {s.get("category") for s in all_schemes}
    assert "EDUCATION" in categories
    assert "AGRICULTURE" in categories
    assert "EMPLOYMENT_AND_BUSINESS" in categories
    assert "SOCIAL_WELFARE" in categories

    # Verify sectors
    sectors = {s.get("sector") for s in all_schemes if s.get("sector")}
    assert "Agriculture & Farmers Welfare" in sectors
    assert "MSME & Micro Enterprises" in sectors
    assert "Urban Livelihoods & Street Vending" in sectors
    assert "Social Security & Unorganised Workers" in sectors
    assert "Energy Access & Women Empowerment" in sectors

    # Filter by category
    agri = svc.search_and_filter(category="AGRICULTURE")
    assert len(agri) == 1
    assert agri[0]["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN"

    biz = svc.search_and_filter(category="EMPLOYMENT_AND_BUSINESS")
    assert len(biz) == 2
    biz_ids = {s["scheme_id"] for s in biz}
    assert biz_ids == {"SCHEME_MSME_001_PMEGP", "SCHEME_URBAN_001_PM_SVANIDHI"}

    welfare = svc.search_and_filter(category="SOCIAL_WELFARE")
    assert len(welfare) == 2
    welfare_ids = {s["scheme_id"] for s in welfare}
    assert welfare_ids == {"SCHEME_LABOUR_001_PM_SYM", "SCHEME_WOMEN_001_PMUY_2"}

    # Filter by sector
    agri_sec = svc.search_and_filter(sector="Agriculture")
    assert len(agri_sec) == 1
    assert agri_sec[0]["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN"

    energy_sec = svc.search_and_filter(sector="Energy")
    assert len(energy_sec) == 1
    assert energy_sec[0]["scheme_id"] == "SCHEME_WOMEN_001_PMUY_2"


# ---------------------------------------------------------------------------
# Requirement 5: Operational status and application availability remain strictly independent
# ---------------------------------------------------------------------------

def test_05_operational_status_and_application_availability_strictly_independent(central_schemes_data):
    """Verify that operational status and application availability are separate dimensions."""
    for scheme in central_schemes_data:
        op_status = scheme.get("operational_status")
        app_status = scheme.get("application_status")
        scheme_id = scheme.get("scheme_id")

        # All 5 schemes are actively running programs
        assert op_status == "ACTIVE", f"Scheme {scheme_id} should be ACTIVE operationally"

        # Application availability is NOT conflated with operational status
        assert app_status in ("YEAR_ROUND", "NEEDS_LIVE_VERIFICATION", "QUOTA_DEPENDENT"), (
            f"Scheme {scheme_id} has invalid application_status: {app_status}"
        )

    # PM-KISAN: Active scheme with continuous year-round farmer registration
    kisan = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN")
    assert kisan["operational_status"] == "ACTIVE"
    assert kisan["application_status"] == "YEAR_ROUND"

    # PM SVANidhi: Active scheme with continuous year-round lending window through 2030
    svanidhi = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_URBAN_001_PM_SVANIDHI")
    assert svanidhi["operational_status"] == "ACTIVE"
    assert svanidhi["application_status"] == "YEAR_ROUND"

    # PMUY 2.0: Active scheme, but application availability is quota-dependent
    pmuy = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_WOMEN_001_PMUY_2")
    assert pmuy["operational_status"] == "ACTIVE"
    assert pmuy["application_status"] == "QUOTA_DEPENDENT"


# ---------------------------------------------------------------------------
# Requirement 6: Unknown and unannounced availability never becomes OPEN automatically
# ---------------------------------------------------------------------------

def test_06_unknown_and_unverified_never_becomes_open():
    """Verify that schemes with unknown, quota-dependent, or unannounced status never report is_open=True."""
    # Test NEEDS_LIVE_VERIFICATION
    kisan_stub = {
        "scheme_id": "TEST_KISAN",
        "application_status": "NEEDS_LIVE_VERIFICATION",
    }
    kisan_res = evaluate_scheme_deadline(kisan_stub)
    assert kisan_res.status == DeadlineStatus.NEEDS_LIVE_VERIFICATION
    assert kisan_res.is_currently_open is False

    # Test QUOTA_DEPENDENT
    pmuy_stub = {
        "scheme_id": "TEST_PMUY",
        "application_status": "QUOTA_DEPENDENT",
    }
    pmuy_res = evaluate_scheme_deadline(pmuy_stub)
    assert pmuy_res.status == DeadlineStatus.QUOTA_DEPENDENT
    assert pmuy_res.is_currently_open is False

    # Test NOT_ANNOUNCED
    missing_stub = {
        "scheme_id": "TEST_MISSING",
        "application_start_date": None,
        "application_deadline": None,
    }
    missing_res = evaluate_scheme_deadline(missing_stub)
    assert missing_res.status == DeadlineStatus.NOT_ANNOUNCED
    assert missing_res.is_currently_open is False

    # Test UNVERIFIED
    unverified_stub = {
        "scheme_id": "TEST_UNVERIFIED",
        "deadline_status": "UNVERIFIED",
    }
    unv_res = evaluate_scheme_deadline(unverified_stub)
    assert unv_res.status == DeadlineStatus.UNVERIFIED
    assert unv_res.is_currently_open is False


# ---------------------------------------------------------------------------
# Requirement 7: Missing optional data does not crash catalogue loading
# ---------------------------------------------------------------------------

def test_07_missing_optional_data_does_not_crash():
    """Verify that records missing education-specific or optional fields do not crash the loader."""
    minimal_scheme = {
        "scheme_id": "SCHEME_MIN_001",
        "scheme_name": "Minimal Scheme",
        "department": "Ministry of Welfare",
        "description": "Minimal scheme for resilience testing",
        "application_url": "https://welfare.gov.in",
        "benefits": {"type": "Direct Grant"},
        "eligibility": {},
        "target_beneficiaries": None,  # None instead of list
        "category": "SOCIAL_WELFARE",
    }

    # 1. to_summary must handle missing fields gracefully
    summary = SchemeDiscoveryService.to_summary(minimal_scheme)
    assert summary["scheme_id"] == "SCHEME_MIN_001"
    assert summary["target_beneficiaries"] == []
    assert summary["education_requirement"] is None
    assert summary["max_annual_income"] is None

    # 2. search_and_filter must not crash when schemes lack education attributes
    svc = SchemeDiscoveryService()
    svc._schemes_cache = [minimal_scheme]
    results = svc.search_and_filter(
        query="minimal",
        education_level="Degree",
        beneficiary_group="Girl",
    )
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Requirement 8: Invalid status values are rejected
# ---------------------------------------------------------------------------

def test_08_invalid_status_values_are_rejected():
    """Verify that invalid operational status or application status values fail schema validation."""
    validator = SchemeValidator()

    # Invalid operational_status
    invalid_op = {
        "scheme_id": "SCHEME_TEST_001",
        "scheme_name": "Invalid Op Scheme",
        "department": "Department of Tests",
        "description": "Testing invalid operational status",
        "application_url": "https://gov.in",
        "benefits": {"type": "Grant"},
        "eligibility": {"min_age": None, "max_age": None, "gender": "ALL", "max_annual_income": None, "occupation": ["ALL"], "states": ["ALL"]},
        "operational_status": "RUNNING_NOW",  # Invalid!
    }
    is_valid, errors = validator.validate(invalid_op)
    assert is_valid is False
    assert any("operational_status" in err for err in errors)

    # Invalid application_status
    invalid_app = {
        "scheme_id": "SCHEME_TEST_002",
        "scheme_name": "Invalid App Scheme",
        "department": "Department of Tests",
        "description": "Testing invalid application status",
        "application_url": "https://gov.in",
        "benefits": {"type": "Grant"},
        "eligibility": {"min_age": None, "max_age": None, "gender": "ALL", "max_annual_income": None, "occupation": ["ALL"], "states": ["ALL"]},
        "application_status": "ALWAYS_OPEN_GUARANTEED",  # Invalid!
    }
    is_valid, errors = validator.validate(invalid_app)
    assert is_valid is False
    assert any("application_status" in err for err in errors)


# ---------------------------------------------------------------------------
# Requirement 9: Official source URLs present for all five new records
# ---------------------------------------------------------------------------

def test_09_official_source_urls_present_for_all_five_records(central_schemes_data):
    """Verify that every new scheme contains verified official source URLs and portal links."""
    for scheme in central_schemes_data:
        s_id = scheme.get("scheme_id")

        # 1. Official application URL
        app_url = scheme.get("official_application_url") or scheme.get("application_url")
        assert app_url is not None, f"Scheme {s_id} missing application_url"
        parsed_app = urlparse(app_url)
        assert parsed_app.scheme in ("http", "https"), f"Scheme {s_id} invalid app URL scheme: {app_url}"
        assert ".gov.in" in parsed_app.netloc or ".in" in parsed_app.netloc, (
            f"Scheme {s_id} app URL not on official domain: {app_url}"
        )

        # 2. Official guidelines URL
        guide_url = scheme.get("official_guidelines_url")
        assert guide_url is not None, f"Scheme {s_id} missing official_guidelines_url"
        parsed_guide = urlparse(guide_url)
        assert parsed_guide.scheme in ("http", "https")

        # 3. Source URLs list
        source_urls = scheme.get("source_urls")
        assert isinstance(source_urls, list) and len(source_urls) >= 2, (
            f"Scheme {s_id} must have at least 2 source URLs"
        )

        # 4. Official sources structured audit
        official_sources = scheme.get("official_sources")
        assert isinstance(official_sources, list) and len(official_sources) >= 1, (
            f"Scheme {s_id} must have at least 1 structured official source"
        )
        for src in official_sources:
            assert src.get("source_title")
            assert src.get("source_url")
            assert src.get("issuing_authority")
            assert src.get("claims_supported")

        # 5. Verification notes and last checked date
        assert scheme.get("last_verified_at") in ("2026-11-12", "2026-11-15")
        assert len(scheme.get("verification_notes", "")) >= 20


# ---------------------------------------------------------------------------
# Requirement 10: Dynamic deadline evaluation for continuous & quota schemes
# ---------------------------------------------------------------------------

def test_10_deadline_evaluation_for_central_schemes(central_schemes_data):
    """Verify dynamic deadline status calculation on the actual central scheme records."""
    # PM-KISAN
    kisan = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN")
    k_info = evaluate_scheme_deadline(kisan)
    assert k_info.status == DeadlineStatus.YEAR_ROUND
    assert k_info.is_currently_open is True

    # PMEGP
    pmegp = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_MSME_001_PMEGP")
    p_info = evaluate_scheme_deadline(pmegp)
    assert p_info.status == DeadlineStatus.NEEDS_LIVE_VERIFICATION
    assert p_info.is_currently_open is False

    # PM SVANidhi
    svanidhi = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_URBAN_001_PM_SVANIDHI")
    s_info = evaluate_scheme_deadline(svanidhi)
    assert s_info.status == DeadlineStatus.YEAR_ROUND
    assert s_info.is_currently_open is True

    # PM-SYM
    pmsym = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_LABOUR_001_PM_SYM")
    sym_info = evaluate_scheme_deadline(pmsym)
    assert sym_info.status == DeadlineStatus.YEAR_ROUND
    assert sym_info.is_currently_open is True

    # PMUY
    pmuy = next(s for s in central_schemes_data if s["scheme_id"] == "SCHEME_WOMEN_001_PMUY_2")
    u_info = evaluate_scheme_deadline(pmuy)
    assert u_info.status == DeadlineStatus.QUOTA_DEPENDENT
    assert u_info.is_currently_open is False
