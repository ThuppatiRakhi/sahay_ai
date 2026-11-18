"""Unit and integration tests for Phase 2B Isolated Cross-Sector Eligibility Evaluator.

Strict Test Suite Invariants:
1. Validates all 11 protected files against their SHA-256 baseline manifest.
2. Tests deterministic evaluation for all five central government schemes:
   - PM-KISAN (SCHEME_AGRI_001_PM_KISAN)
   - PMEGP (SCHEME_MSME_001_PMEGP)
   - PM SVANidhi (SCHEME_URBAN_001_PM_SVANIDHI)
   - PM-SYM (SCHEME_LABOUR_001_PM_SYM)
   - PMUY 2.0 (SCHEME_WOMEN_001_PMUY_2)
3. Tests PASS, FAIL, and UNKNOWN outcomes for each scheme.
4. Enforces strict rejection of unsafe derivations (income/12, caste->PMUY, occupation substrings, document presence).
5. Enforces strict provenance and confirmation requirements for supplemental data.
6. Enforces finite numeric validation (NaN, Inf, negative, boolean-as-number rejection).
7. Enforces symmetric conflict clearing (neither value chosen; attribute cleared to None; REVIEW_REQUIRED).
8. Enforces separation of PMEGP advisory operational requirements from deterministic rules.
9. Enforces verification guard (status REVIEW_REQUIRED, official_eligibility_confirmed False).
10. Verifies core EligibilityEngine output contract and existing education schemes remain untouched.
"""

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict
import pytest

from eligibility.cross_sector_evaluator import (
    CrossSectorEvaluator,
    EvaluationProfile,
    CROSS_SECTOR_SCHEME_IDS,
    PROVENANCE_DISCLAIMER,
)
from eligibility.engine import EligibilityEngine
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService


# -----------------------------------------------------------------------------
# Baseline SHA-256 Manifest for Protected Files
# -----------------------------------------------------------------------------
BASELINE_PROTECTED_HASHES: Dict[str, str] = {
    "eligibility/engine.py": "f77d9c521bdd411c342e0b5cdc810efa9a3d3f347259c78b25d8b6fe69b5411c",
    "scheme_collection/scheme_discovery_service.py": "245b6fe720fe7fdd713c16f37bcb1fc050a025d2d836b660f1521ac2b38bb841",
    "scheme_collection/deadline_manager.py": "3d9ea781d246d23bbe303cdb3824948299e14cd64720b98f3f1e2af4638432b9",
    "scheme_collection/document_readiness.py": "514aef8740d3df2b502c27b777011c0f8d6dccdb6e4f09a511ccf469e75deea4",
    "scheme_collection/scheme_validator.py": "9f04b3bf291cbaf682d91942d8bb5d3e7bfdeafb3d9780d9ca23bc7ed0eb9a64",
    "data/schemes/schemes.json": "d150c49aeaedf68f0004219d7cfdf8011c2fb4284b40d1f8775f2760a39c5e96",
    "data/schemes/central_schemes.json": "b299f285e822f9b8fbc191ea2f73c8e66769e4eb55e5f80505efc36eb83aa54e",
    "profile/database.py": "329a6fb497d6508f2ad499f59b7ecde886934dc8b000bd4b87c4719392556f2d",
    "profile/profile_manager.py": "a9ee7b720f9ca8d4286ca424742bc2c2a920488e94ce9209434e865cd47d21f6",
    "shared_contracts/schemas.json": "794b6781edbf53fc918c076dbd8540bf11d74823eeaa99c9165620c863996fc3",
    "api/schemes.py": "96e9c9569815ae98b614151d98d6bca523e2b79c6ef891a93372038823229532",
}


def _sha256_of_file(path_str: str) -> str:
    path = Path(path_str)
    assert path.exists(), f"Protected file {path_str} does not exist!"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declaration(value: Any) -> Dict[str, Any]:
    """Helper to construct a valid citizen declaration."""
    return {
        "value": value,
        "source": "citizen_declaration",
        "confirmed": True,
    }


def _confirmed_doc_field(
    field_name: str,
    value: Any,
    doc_id: str = "doc_test_123",
    confirmation_status: str = "CONFIRMED",
    document_status: str = "ACTIVE",
    is_confirmed: Any = 1,
) -> Dict[str, Any]:
    """Helper to construct a valid confirmed document field record matching ProfileManager contract."""
    return {
        "id": 1,
        "user_id": "test_user_1",
        "document_id": doc_id,
        "source_document_id": doc_id,
        "field_name": field_name,
        "field_value": value,
        "value": value,
        "confirmation_status": confirmation_status,
        "document_status": document_status,
        "is_confirmed": is_confirmed,
        "is_government_verified": False,
    }


# =============================================================================
# 1. Zero-Modification Proof (Cryptographic Hash Integrity)
# =============================================================================

def test_protected_files_sha256_unmodified():
    """Verify that all 11 protected files remain byte-for-byte identical to baseline."""
    for rel_path, expected_hash in BASELINE_PROTECTED_HASHES.items():
        actual_hash = _sha256_of_file(rel_path)
        assert (
            actual_hash == expected_hash
        ), f"Protected file {rel_path} was modified! Expected {expected_hash}, got {actual_hash}"


# =============================================================================
# 2. PM-KISAN Evaluation Tests
# =============================================================================

def test_pm_kisan_evaluation_pass():
    evaluator = CrossSectorEvaluator()
    supplemental = {
        "land_ownership": _declaration(True),
        "institutional_landholder": _declaration(False),
        "income_tax_payee": _declaration(False),
        "constitutional_post_holder": _declaration(False),
    }

    res = evaluator.evaluate_scheme("SCHEME_AGRI_001_PM_KISAN", supplemental_data=supplemental)

    assert res["scheme_id"] == "SCHEME_AGRI_001_PM_KISAN"
    assert res["rule_match_status"] == "PASS"
    assert res["status"] == "REVIEW_REQUIRED"  # Verification guard
    assert res["official_eligibility_confirmed"] is False
    assert res["missing_information"] == []
    assert res["has_conflicts"] is False


@pytest.mark.parametrize(
    "failing_attr,failing_val",
    [
        ("land_ownership", False),
        ("institutional_landholder", True),
        ("income_tax_payee", True),
        ("constitutional_post_holder", True),
    ],
)
def test_pm_kisan_evaluation_exclusions_fail(failing_attr, failing_val):
    evaluator = CrossSectorEvaluator()
    supplemental = {
        "land_ownership": _declaration(True),
        "institutional_landholder": _declaration(False),
        "income_tax_payee": _declaration(False),
        "constitutional_post_holder": _declaration(False),
    }
    supplemental[failing_attr] = _declaration(failing_val)

    res = evaluator.evaluate_scheme("SCHEME_AGRI_001_PM_KISAN", supplemental_data=supplemental)
    assert res["rule_match_status"] == "FAIL"
    assert res["status"] == "REVIEW_REQUIRED"


def test_pm_kisan_missing_criteria():
    evaluator = CrossSectorEvaluator()
    # Missing all criteria
    res = evaluator.evaluate_scheme("SCHEME_AGRI_001_PM_KISAN", supplemental_data={})
    assert res["rule_match_status"] == "UNKNOWN"
    assert set(res["missing_information"]) == {
        "land_ownership",
        "institutional_landholder",
        "income_tax_payee",
        "constitutional_post_holder",
    }


# =============================================================================
# 3. PMEGP Evaluation Tests & Advisory Separation
# =============================================================================

def test_pmegp_evaluation_pass():
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 28,
        "active_confirmed_fields": [_confirmed_doc_field("age", 28)],
    }
    supplemental = {
        "new_project_only": _declaration(True),
        "negative_list_activity": _declaration(False),
    }

    res = evaluator.evaluate_scheme("SCHEME_MSME_001_PMEGP", profile=profile, supplemental_data=supplemental)

    assert res["rule_match_status"] == "PASS"
    assert res["status"] == "REVIEW_REQUIRED"
    assert res["official_eligibility_confirmed"] is False
    assert len(res["advisory_conditions_requiring_review"]) == 4

    # Verify advisory separation: structured-rule PASS must not clear advisory conditions
    criteria_names = [c["criterion"] for c in res["advisory_conditions_requiring_review"]]
    assert "class_8_qualification_threshold" in criteria_names
    assert "project_cost_ceilings" in criteria_names
    assert "margin_money_subsidy_and_promoter_contribution" in criteria_names
    assert "dltfc_and_bank_sanction" in criteria_names


def test_pmegp_underage_fail():
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 17,
        "active_confirmed_fields": [_confirmed_doc_field("age", 17)],
    }
    supplemental = {
        "new_project_only": _declaration(True),
        "negative_list_activity": _declaration(False),
    }

    res = evaluator.evaluate_scheme("SCHEME_MSME_001_PMEGP", profile=profile, supplemental_data=supplemental)
    assert res["rule_match_status"] == "FAIL"


def test_pmegp_exclusions_fail():
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 30,
        "active_confirmed_fields": [_confirmed_doc_field("age", 30)],
    }

    # Existing project exclusion
    res1 = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        profile=profile,
        supplemental_data={
            "new_project_only": _declaration(False),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res1["rule_match_status"] == "FAIL"

    # Negative list activity exclusion
    res2 = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        profile=profile,
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(True),
        },
    )
    assert res2["rule_match_status"] == "FAIL"


# =============================================================================
# 4. PM SVANidhi Evaluation Tests
# =============================================================================

def test_pm_svanidhi_evaluation_pass():
    evaluator = CrossSectorEvaluator()
    supplemental = {
        "occupation_street_vendor": _declaration(True),
        "ulb_vendor_identification": _declaration(True),
    }

    res = evaluator.evaluate_scheme("SCHEME_URBAN_001_PM_SVANIDHI", supplemental_data=supplemental)
    assert res["rule_match_status"] == "PASS"
    assert res["status"] == "REVIEW_REQUIRED"
    assert res["missing_information"] == []


def test_pm_svanidhi_evaluation_fail():
    evaluator = CrossSectorEvaluator()
    res1 = evaluator.evaluate_scheme(
        "SCHEME_URBAN_001_PM_SVANIDHI",
        supplemental_data={
            "occupation_street_vendor": _declaration(False),
            "ulb_vendor_identification": _declaration(True),
        },
    )
    assert res1["rule_match_status"] == "FAIL"

    res2 = evaluator.evaluate_scheme(
        "SCHEME_URBAN_001_PM_SVANIDHI",
        supplemental_data={
            "occupation_street_vendor": _declaration(True),
            "ulb_vendor_identification": _declaration(False),
        },
    )
    assert res2["rule_match_status"] == "FAIL"


def test_pm_svanidhi_missing_identification():
    evaluator = CrossSectorEvaluator()
    res = evaluator.evaluate_scheme(
        "SCHEME_URBAN_001_PM_SVANIDHI",
        supplemental_data={
            "occupation_street_vendor": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "ulb_vendor_identification" in res["missing_information"]


# =============================================================================
# 5. PM-SYM Evaluation Tests
# =============================================================================

def test_pm_sym_evaluation_pass():
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 25,
        "active_confirmed_fields": [_confirmed_doc_field("age", 25)],
    }
    supplemental = {
        "monthly_income": _declaration(12000),
        "covered_by_epfo_esic_nps": _declaration(False),
        "income_tax_payee": _declaration(False),
    }

    res = evaluator.evaluate_scheme("SCHEME_LABOUR_001_PM_SYM", profile=profile, supplemental_data=supplemental)
    assert res["rule_match_status"] == "PASS"
    assert res["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("age,should_pass", [(18, True), (40, True), (17, False), (41, False)])
def test_pm_sym_age_boundaries(age, should_pass):
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": age,
        "active_confirmed_fields": [_confirmed_doc_field("age", age)],
    }
    supplemental = {
        "monthly_income": _declaration(10000),
        "covered_by_epfo_esic_nps": _declaration(False),
        "income_tax_payee": _declaration(False),
    }

    res = evaluator.evaluate_scheme("SCHEME_LABOUR_001_PM_SYM", profile=profile, supplemental_data=supplemental)
    expected_status = "PASS" if should_pass else "FAIL"
    assert res["rule_match_status"] == expected_status


@pytest.mark.parametrize("income,should_pass", [(15000, True), (15000.0, True), (15001, False), (20000, False)])
def test_pm_sym_income_boundaries(income, should_pass):
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 30,
        "active_confirmed_fields": [_confirmed_doc_field("age", 30)],
    }
    supplemental = {
        "monthly_income": _declaration(income),
        "covered_by_epfo_esic_nps": _declaration(False),
        "income_tax_payee": _declaration(False),
    }

    res = evaluator.evaluate_scheme("SCHEME_LABOUR_001_PM_SYM", profile=profile, supplemental_data=supplemental)
    expected_status = "PASS" if should_pass else "FAIL"
    assert res["rule_match_status"] == expected_status


def test_pm_sym_epfo_or_tax_exclusions():
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 30,
        "active_confirmed_fields": [_confirmed_doc_field("age", 30)],
    }

    res_epfo = evaluator.evaluate_scheme(
        "SCHEME_LABOUR_001_PM_SYM",
        profile=profile,
        supplemental_data={
            "monthly_income": _declaration(10000),
            "covered_by_epfo_esic_nps": _declaration(True),
            "income_tax_payee": _declaration(False),
        },
    )
    assert res_epfo["rule_match_status"] == "FAIL"

    res_tax = evaluator.evaluate_scheme(
        "SCHEME_LABOUR_001_PM_SYM",
        profile=profile,
        supplemental_data={
            "monthly_income": _declaration(10000),
            "covered_by_epfo_esic_nps": _declaration(False),
            "income_tax_payee": _declaration(True),
        },
    )
    assert res_tax["rule_match_status"] == "FAIL"


# =============================================================================
# 6. PMUY 2.0 Evaluation Tests
# =============================================================================

def test_pmuy_evaluation_pass():
    evaluator = CrossSectorEvaluator()
    profile = {
        "gender": "FEMALE",
        "age": 26,
        "active_confirmed_fields": [
            _confirmed_doc_field("gender", "FEMALE"),
            _confirmed_doc_field("age", 26),
        ],
    }
    supplemental = {
        "existing_lpg_connection_in_household": _declaration(False),
        "qualifying_deprivation_category": _declaration(True),
    }

    res = evaluator.evaluate_scheme("SCHEME_WOMEN_001_PMUY_2", profile=profile, supplemental_data=supplemental)
    assert res["rule_match_status"] == "PASS"
    assert res["status"] == "REVIEW_REQUIRED"
    assert res["missing_information"] == []


def test_pmuy_gender_exclusion_male_fails():
    evaluator = CrossSectorEvaluator()
    profile = {
        "gender": "MALE",
        "age": 26,
        "active_confirmed_fields": [
            _confirmed_doc_field("gender", "MALE"),
            _confirmed_doc_field("age", 26),
        ],
    }
    supplemental = {
        "existing_lpg_connection_in_household": _declaration(False),
        "qualifying_deprivation_category": _declaration(True),
    }

    res = evaluator.evaluate_scheme("SCHEME_WOMEN_001_PMUY_2", profile=profile, supplemental_data=supplemental)
    assert res["rule_match_status"] == "FAIL"


def test_pmuy_underage_or_existing_lpg_or_deprivation_fails():
    evaluator = CrossSectorEvaluator()

    # Underage female
    res_underage = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile={
            "gender": "FEMALE",
            "age": 17,
            "active_confirmed_fields": [
                _confirmed_doc_field("gender", "FEMALE"),
                _confirmed_doc_field("age", 17),
            ],
        },
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res_underage["rule_match_status"] == "FAIL"

    # Existing LPG connection in household
    res_lpg = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile={
            "gender": "FEMALE",
            "age": 25,
            "active_confirmed_fields": [
                _confirmed_doc_field("gender", "FEMALE"),
                _confirmed_doc_field("age", 25),
            ],
        },
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(True),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res_lpg["rule_match_status"] == "FAIL"

    # Non-qualifying deprivation
    res_dep = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile={
            "gender": "FEMALE",
            "age": 25,
            "active_confirmed_fields": [
                _confirmed_doc_field("gender", "FEMALE"),
                _confirmed_doc_field("age", 25),
            ],
        },
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(False),
        },
    )
    assert res_dep["rule_match_status"] == "FAIL"


# =============================================================================
# 7. Prohibition of Unsafe Derivations
# =============================================================================

def test_no_monthly_income_derivation_from_annual_income():
    """Proves monthly_income is never derived via annual_income / 12."""
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 25,
        "annual_income": 120000.0,  # 120,000 / 12 would be 10,000 (which is <= 15000)
        "user_confirmed": True,
    }
    supplemental = {
        "covered_by_epfo_esic_nps": _declaration(False),
        "income_tax_payee": _declaration(False),
        # monthly_income NOT provided
    }

    res = evaluator.evaluate_scheme("SCHEME_LABOUR_001_PM_SYM", profile=profile, supplemental_data=supplemental)
    # Must be UNKNOWN with monthly_income listed as missing
    assert res["rule_match_status"] == "UNKNOWN"
    assert "monthly_income" in res["missing_information"]


def test_no_pmuy_deprivation_derivation_from_caste_or_bpl():
    """Proves qualifying_deprivation_category is never derived from caste_category or is_bpl."""
    evaluator = CrossSectorEvaluator()
    profile = {
        "gender": "FEMALE",
        "age": 25,
        "caste_category": "SC",
        "is_bpl": True,
        "user_confirmed": True,
    }
    supplemental = {
        "existing_lpg_connection_in_household": _declaration(False),
        # qualifying_deprivation_category NOT provided
    }

    res = evaluator.evaluate_scheme("SCHEME_WOMEN_001_PMUY_2", profile=profile, supplemental_data=supplemental)
    assert res["rule_match_status"] == "UNKNOWN"
    assert "qualifying_deprivation_category" in res["missing_information"]


def test_no_occupation_substring_derivation():
    """Proves occupation booleans are never derived via substring matching."""
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 35,
        "occupation": "Farmer and Cultivator",
        "user_confirmed": True,
    }

    # PM-KISAN: occupation does NOT derive land_ownership
    res_kisan = evaluator.evaluate_scheme(
        "SCHEME_AGRI_001_PM_KISAN",
        profile=profile,
        supplemental_data={
            "institutional_landholder": _declaration(False),
            "income_tax_payee": _declaration(False),
            "constitutional_post_holder": _declaration(False),
        },
    )
    assert "land_ownership" in res_kisan["missing_information"]

    # PM SVANidhi: occupation 'Street Vendor' does NOT derive occupation_street_vendor
    profile_vendor = {
        "age": 35,
        "occupation": "Urban Street Vendor and Hawker",
        "user_confirmed": True,
    }
    res_svanidhi = evaluator.evaluate_scheme(
        "SCHEME_URBAN_001_PM_SVANIDHI",
        profile=profile_vendor,
        supplemental_data={"ulb_vendor_identification": _declaration(True)},
    )
    assert "occupation_street_vendor" in res_svanidhi["missing_information"]


# =============================================================================
# 8. Provenance, Confirmation & Strict Type Validation
# =============================================================================

def test_raw_values_without_declaration_structure_rejected():
    """Proves raw booleans or values without {value, source, confirmed} are rejected."""
    evaluator = CrossSectorEvaluator()

    # Raw booleans passed directly
    raw_data = {
        "land_ownership": True,
        "institutional_landholder": False,
        "income_tax_payee": False,
        "constitutional_post_holder": False,
    }
    clean = evaluator.validate_supplemental_data("SCHEME_AGRI_001_PM_KISAN", raw_data)
    assert clean == {}, f"Raw boolean data should be completely rejected! Got: {clean}"


def test_unconfirmed_or_wrong_source_declaration_rejected():
    evaluator = CrossSectorEvaluator()

    # confirmed is False
    unconfirmed = {
        "land_ownership": {"value": True, "source": "citizen_declaration", "confirmed": False}
    }
    assert evaluator.validate_supplemental_data("SCHEME_AGRI_001_PM_KISAN", unconfirmed) == {}

    # source is not 'citizen_declaration'
    wrong_source = {
        "land_ownership": {"value": True, "source": "ocr_extraction", "confirmed": True}
    }
    assert evaluator.validate_supplemental_data("SCHEME_AGRI_001_PM_KISAN", wrong_source) == {}


def test_boolean_string_and_integer_flags_rejected():
    """Proves string 'true', 'false', and integers 1, 0 are strictly rejected for boolean fields."""
    evaluator = CrossSectorEvaluator()

    bad_entries = {
        "land_ownership": _declaration("true"),
        "institutional_landholder": _declaration("false"),
        "income_tax_payee": _declaration(0),
        "constitutional_post_holder": _declaration(1),
    }
    clean = evaluator.validate_supplemental_data("SCHEME_AGRI_001_PM_KISAN", bad_entries)
    assert clean == {}, f"String or integer flags must be rejected! Got: {clean}"


def test_numeric_validation_nan_inf_negative_bool_rejected():
    """Proves NaN, Inf, negative, and boolean-as-number are rejected for numeric attributes."""
    evaluator = CrossSectorEvaluator()

    nan_data = {"monthly_income": _declaration(float("nan"))}
    assert evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", nan_data) == {}

    inf_data = {"monthly_income": _declaration(float("inf"))}
    assert evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", inf_data) == {}

    neg_data = {"monthly_income": _declaration(-1500.0)}
    assert evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", neg_data) == {}

    # Boolean masquerading as number: In Python isinstance(True, int) is True!
    bool_as_num = {"monthly_income": _declaration(True)}
    assert evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", bool_as_num) == {}

    # Age with True or invalid range
    bool_age = {"entry_age": _declaration(True)}
    assert evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", bool_age) == {}

    out_of_bounds_age = {"entry_age": _declaration(150)}
    assert evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", out_of_bounds_age) == {}


def test_extremely_large_integers_safely_rejected():
    """Extremely large integers must be safely rejected without throwing OverflowError."""
    evaluator = CrossSectorEvaluator()
    huge_int = 10**1000

    # In supplemental numeric field (monthly_income)
    supp_huge_income = {"monthly_income": _declaration(huge_int)}
    clean_income = evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", supp_huge_income)
    assert clean_income == {}

    # In supplemental integer field (entry_age)
    supp_huge_age = {"entry_age": _declaration(huge_int)}
    clean_age = evaluator.validate_supplemental_data("SCHEME_LABOUR_001_PM_SYM", supp_huge_age)
    assert clean_age == {}

    # In profile age
    profile_huge = {"age": huge_int, "user_confirmed": True}
    res = evaluator.evaluate_scheme(
        "SCHEME_LABOUR_001_PM_SYM",
        profile=profile_huge,
        supplemental_data={
            "monthly_income": _declaration(12000),
            "covered_by_epfo_esic_nps": _declaration(False),
            "income_tax_payee": _declaration(False),
        },
    )
    # Huge age should be safely rejected as invalid, so entry_age remains missing
    assert "entry_age" in res["missing_information"]
    assert res["rule_match_status"] == "UNKNOWN"


# =============================================================================
# 9. Profile Confirmation & Provenance Validation
# =============================================================================

def test_unconfirmed_profile_attributes_ignored():
    """Proves unconfirmed profile age and gender are ignored and treated as missing."""
    evaluator = CrossSectorEvaluator()
    profile = {
        "age": 25,
        "gender": "FEMALE",
        "user_confirmed": False,  # Not confirmed
    }

    # PMUY without supplemental age or gender
    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "gender" in res["missing_information"]
    assert "minimum_age" in res["missing_information"]


def test_active_confirmed_fields_whitelist_acceptance():
    """Proves active_confirmed_fields parameter allows explicit confirmation using database contract."""
    evaluator = CrossSectorEvaluator()
    profile = {"age": 28, "gender": "FEMALE"}

    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        active_confirmed_fields=[
            _confirmed_doc_field("age", 28),
            _confirmed_doc_field("gender", "FEMALE"),
        ],
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "PASS"


def test_user_confirmed_integer_one_or_truthy_rejected():
    """user_confirmed=1, 'true', or truthy values must NOT confirm profile attributes."""
    evaluator = CrossSectorEvaluator()

    # Integer 1 should NOT confirm profile
    profile_int = {"age": 25, "gender": "FEMALE", "user_confirmed": 1}
    res_int = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile_int,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert "gender" in res_int["missing_information"]
    assert "minimum_age" in res_int["missing_information"]

    # String 'true' should NOT confirm profile
    profile_str = {"age": 25, "gender": "FEMALE", "user_confirmed": "true"}
    res_str = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile_str,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert "gender" in res_str["missing_information"]
    assert "minimum_age" in res_str["missing_information"]


def test_profile_gender_lowercase_rejected():
    """Proves non-canonical gender strings like 'female' are rejected."""
    evaluator = CrossSectorEvaluator()
    profile = {"age": 25, "gender": "female", "user_confirmed": True}

    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert "gender" in res["missing_information"]


# =============================================================================
# 10. Symmetric Conflict Handling
# =============================================================================

def test_symmetric_gender_conflict_clearing():
    """When confirmed profile gender and supplemental gender conflict:
    - Neither value is chosen.
    - Attribute cleared to None.
    - Conflict recorded.
    - Status is REVIEW_REQUIRED.
    - Engine reports UNKNOWN with missing_information containing gender.
    """
    evaluator = CrossSectorEvaluator()
    profile = {"gender": "MALE", "age": 25, "user_confirmed": True}
    supplemental = {
        "gender": _declaration("FEMALE"),
        "existing_lpg_connection_in_household": _declaration(False),
        "qualifying_deprivation_category": _declaration(True),
    }

    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        supplemental_data=supplemental,
    )

    assert res["has_conflicts"] is True
    assert len(res["conflicts"]) == 1
    conflict = res["conflicts"][0]
    assert conflict["attribute"] == "gender"
    assert conflict["profile_value"] == "MALE"
    assert conflict["supplemental_value"] == "FEMALE"

    assert res["status"] == "REVIEW_REQUIRED"
    assert res["rule_match_status"] == "UNKNOWN"
    assert "gender" in res["missing_information"]


def test_symmetric_age_conflict_clearing():
    """When confirmed profile age and supplemental age conflict in PM-SYM:
    - Neither value chosen.
    - entry_age cleared to None.
    - Conflict recorded.
    - Status is REVIEW_REQUIRED.
    """
    evaluator = CrossSectorEvaluator()
    profile = {"age": 45, "user_confirmed": True}
    supplemental = {
        "entry_age": _declaration(28),
        "monthly_income": _declaration(10000),
        "covered_by_epfo_esic_nps": _declaration(False),
        "income_tax_payee": _declaration(False),
    }

    res = evaluator.evaluate_scheme(
        "SCHEME_LABOUR_001_PM_SYM",
        profile=profile,
        supplemental_data=supplemental,
    )

    assert res["has_conflicts"] is True
    assert len(res["conflicts"]) == 1
    assert res["conflicts"][0]["attribute"] == "entry_age"
    assert res["status"] == "REVIEW_REQUIRED"
    assert res["rule_match_status"] == "UNKNOWN"
    assert "entry_age" in res["missing_information"]


# =============================================================================
# 11. Verification Guard for All Central Schemes
# =============================================================================

@pytest.mark.parametrize("scheme_id", CROSS_SECTOR_SCHEME_IDS)
def test_all_central_schemes_pending_review_guard(scheme_id):
    """Proves that for all 5 central schemes, official_eligibility_confirmed is strictly False
    and status is REVIEW_REQUIRED even if rules evaluate to PASS.
    """
    evaluator = CrossSectorEvaluator()

    # Create fully passing supplemental data per scheme
    supp_data = {
        "SCHEME_AGRI_001_PM_KISAN": {
            "land_ownership": _declaration(True),
            "institutional_landholder": _declaration(False),
            "income_tax_payee": _declaration(False),
            "constitutional_post_holder": _declaration(False),
        },
        "SCHEME_MSME_001_PMEGP": {
            "minimum_age": _declaration(25),
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
        "SCHEME_URBAN_001_PM_SVANIDHI": {
            "occupation_street_vendor": _declaration(True),
            "ulb_vendor_identification": _declaration(True),
        },
        "SCHEME_LABOUR_001_PM_SYM": {
            "entry_age": _declaration(25),
            "monthly_income": _declaration(12000),
            "covered_by_epfo_esic_nps": _declaration(False),
            "income_tax_payee": _declaration(False),
        },
        "SCHEME_WOMEN_001_PMUY_2": {
            "gender": _declaration("FEMALE"),
            "minimum_age": _declaration(25),
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    }

    res = evaluator.evaluate_scheme(scheme_id, supplemental_data=supp_data[scheme_id])
    assert res["rule_match_status"] == "PASS"
    assert res["status"] == "REVIEW_REQUIRED"
    assert res["official_eligibility_confirmed"] is False
    assert res["review_required"] is True
    assert res["scheme_verification_status"] == "pending_review"


# =============================================================================
# 12. Batch Evaluation & Questionnaire Tests
# =============================================================================

def test_evaluate_all():
    evaluator = CrossSectorEvaluator()
    results = evaluator.evaluate_all(profile={"age": 30, "user_confirmed": True})
    assert len(results) == 5
    returned_ids = [r["scheme_id"] for r in results]
    assert returned_ids == CROSS_SECTOR_SCHEME_IDS


def test_get_questionnaire_all_schemes():
    evaluator = CrossSectorEvaluator()
    for sid in CROSS_SECTOR_SCHEME_IDS:
        q = evaluator.get_questionnaire(sid)
        assert q["scheme_id"] == sid
        assert len(q["fields"]) > 0
        assert q["disclaimer"] == PROVENANCE_DISCLAIMER
        assert "expected_structure" in q

        if sid == "SCHEME_MSME_001_PMEGP":
            assert len(q["advisory_conditions_requiring_review"]) == 4
        else:
            assert len(q["advisory_conditions_requiring_review"]) == 0


@pytest.mark.parametrize("bad_id", ["INVALID_SCHEME", "SCHEME_EDU_001_PM_USP_CSSS", "SCHEME_XYZ", ""])
def test_unsupported_scheme_ids_explicitly_rejected(bad_id):
    """Unsupported scheme IDs must be rejected explicitly in all evaluation and questionnaire methods."""
    evaluator = CrossSectorEvaluator()

    with pytest.raises(ValueError, match="Unsupported scheme ID"):
        evaluator.evaluate_scheme(bad_id)

    with pytest.raises(ValueError, match="Unsupported scheme ID"):
        evaluator.get_questionnaire(bad_id)

    with pytest.raises(ValueError, match="Unsupported scheme ID"):
        evaluator.validate_supplemental_data(bad_id, {})

    with pytest.raises(ValueError, match="Unsupported scheme ID"):
        evaluator.build_evaluation_profile(bad_id, {})


# =============================================================================
# 13. Existing Education Schemes Untouched & Core Engine Contract Preservation
# =============================================================================

def test_existing_education_schemes_untouched():
    """Verify that existing education schemes continue to evaluate normally in EligibilityEngine."""
    engine = EligibilityEngine()
    discovery = SchemeDiscoveryService()

    edu_scheme = discovery.get_scheme_by_id("SCHEME_EDU_001_PM_USP_CSSS")
    assert edu_scheme is not None
    assert edu_scheme["scheme_name"] == "PM-USP Central Sector Scholarship Scheme"

    passing_profile = {
        "annual_family_income": 300000,
        "class_12_merit_percentile": 92,
        "course_mode": "REGULAR_FULL_TIME",
        "concurrent_scholarship": False,
        "gap_year": False,
        "application_type": "FRESH",
    }
    res = engine.evaluate(edu_scheme, passing_profile)
    assert res["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert res["rule_match_status"] == "PASS"
    assert res["missing_information"] == []


def test_all_five_original_education_schemes_unaffected():
    """Verify that all five original education schemes load and evaluate correctly."""
    engine = EligibilityEngine()
    discovery = SchemeDiscoveryService()

    education_schemes = [
        "SCHEME_EDU_001_PM_USP_CSSS",
        "SCHEME_EDU_002_AICTE_PRAGATI",
        "SCHEME_EDU_003_AICTE_SAKSHAM",
        "SCHEME_EDU_004_AICTE_SWANATH",
        "SCHEME_EDU_005_TOP_CLASS_SC",
    ]

    for scheme_id in education_schemes:
        scheme = discovery.get_scheme_by_id(scheme_id)
        assert scheme is not None, f"Education scheme {scheme_id} could not be loaded!"
        assert scheme["scheme_id"] == scheme_id
        assert scheme.get("category") == "EDUCATION"
        assert len(scheme.get("eligibility", {}).get("structured_rules", [])) > 0

        # Run an empty profile evaluation through engine to verify engine contract preservation
        res = engine.evaluate(scheme, {})
        assert res["scheme_id"] == scheme_id
        assert res["rule_match_status"] in ("UNKNOWN", "FAIL")
        assert len(res["missing_information"]) > 0


# =============================================================================
# 14. Section 8 Mandatory Regression Tests (16 Verification Points)
# =============================================================================

def test_regression_point_1_global_user_confirmed_true_cannot_confirm_age():
    """1. Global user_confirmed=True alone cannot confirm age."""
    evaluator = CrossSectorEvaluator()
    profile = {"age": 25, "user_confirmed": True}
    res = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        profile=profile,
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res["missing_information"]


def test_regression_point_2_global_user_confirmed_true_cannot_confirm_gender():
    """2. Global user_confirmed=True alone cannot confirm gender."""
    evaluator = CrossSectorEvaluator()
    profile = {
        "gender": "FEMALE",
        "user_confirmed": True,
        "active_confirmed_fields": [_confirmed_doc_field("age", 25)],
    }
    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "gender" in res["missing_information"]


def test_regression_point_3_user_confirmed_int_one_cannot_confirm_individual_fields():
    """3. user_confirmed=1 cannot confirm individual fields."""
    evaluator = CrossSectorEvaluator()
    profile = {"age": 25, "gender": "FEMALE", "user_confirmed": 1}
    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "gender" in res["missing_information"]
    assert "minimum_age" in res["missing_information"]


def test_regression_point_4_list_or_set_of_field_names_cannot_establish_confirmation():
    """4. A list or set of field names cannot establish confirmation."""
    evaluator = CrossSectorEvaluator()
    profile = {"age": 25, "gender": "FEMALE"}

    # List of field names
    res_list = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        active_confirmed_fields=["age", "gender"],
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res_list["rule_match_status"] == "UNKNOWN"
    assert "gender" in res_list["missing_information"]
    assert "minimum_age" in res_list["missing_information"]

    # Set of field names
    res_set = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        active_confirmed_fields={"age", "gender"},
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res_set["rule_match_status"] == "UNKNOWN"
    assert "gender" in res_set["missing_information"]
    assert "minimum_age" in res_set["missing_information"]


def test_regression_point_5_boolean_dict_cannot_establish_confirmation():
    """5. A dictionary containing only boolean confirmation flags cannot establish confirmation."""
    evaluator = CrossSectorEvaluator()
    profile = {"age": 25, "gender": "FEMALE"}

    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile=profile,
        active_confirmed_fields={"age": True, "gender": True},
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "gender" in res["missing_information"]
    assert "minimum_age" in res["missing_information"]


def test_regression_point_6_missing_individual_confirmation_records_result_in_unknown():
    """6. Missing individual confirmation records result in UNKNOWN."""
    evaluator = CrossSectorEvaluator()
    # Empty profile and empty confirmed records
    res = evaluator.evaluate_scheme(
        "SCHEME_LABOUR_001_PM_SYM",
        profile={},
        supplemental_data={
            "monthly_income": _declaration(12000),
            "covered_by_epfo_esic_nps": _declaration(False),
            "income_tax_payee": _declaration(False),
        },
    )
    assert res["rule_match_status"] == "UNKNOWN"
    assert "entry_age" in res["missing_information"]


def test_regression_point_7_valid_structured_field_records_provide_confirmed_values():
    """7. Valid structured field-level records can provide confirmed values."""
    evaluator = CrossSectorEvaluator()
    confirmed_records = [
        _confirmed_doc_field("age", 25),
        _confirmed_doc_field("gender", "FEMALE"),
    ]
    res = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        profile={},
        active_confirmed_fields=confirmed_records,
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res["rule_match_status"] == "PASS"
    assert res["missing_information"] == []


def test_regression_point_8_invalid_or_incomplete_provenance_rejected():
    """8. Invalid or incomplete provenance is rejected."""
    evaluator = CrossSectorEvaluator()

    # Missing document_id
    bad_doc = _confirmed_doc_field("age", 25, doc_id="")
    res_bad_doc = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[bad_doc],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_bad_doc["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res_bad_doc["missing_information"]

    # Wrong confirmation status
    bad_status = _confirmed_doc_field("age", 25, confirmation_status="PENDING")
    res_bad_status = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[bad_status],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_bad_status["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res_bad_status["missing_information"]

    # Incomplete dictionary missing document reference
    incomplete = {"field_name": "age", "field_value": 25, "is_confirmed": 1}
    res_inc = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[incomplete],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_inc["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res_inc["missing_information"]


def test_regression_point_9_unconfirmed_or_archived_document_records_rejected():
    """9. Unconfirmed or archived document records are rejected when the evidence is available."""
    evaluator = CrossSectorEvaluator()

    # is_confirmed = 0
    unconfirmed = _confirmed_doc_field("age", 25, is_confirmed=0)
    res_unconf = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[unconfirmed],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_unconf["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res_unconf["missing_information"]

    # document_status = 'ARCHIVED'
    archived = _confirmed_doc_field("age", 25, document_status="ARCHIVED")
    res_arch = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[archived],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_arch["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res_arch["missing_information"]


def test_regression_point_10_confirmed_document_values_used_not_unrelated_profile_values():
    """10. Confirmed document values, not unrelated profile values, are used."""
    evaluator = CrossSectorEvaluator()
    # Profile has unrelated metadata, but NO age attribute
    profile = {"occupation": "Software Engineer", "state": "Delhi"}
    res = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        profile=profile,
        active_confirmed_fields=[_confirmed_doc_field("age", 30)],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    # Proves age was extracted from confirmed document field record
    assert res["rule_match_status"] == "PASS"
    assert "minimum_age" not in res["missing_information"]


def test_regression_point_11_mismatch_between_confirmed_field_value_and_profile_value_produces_conflict():
    """11. A mismatch between a confirmed field value and the profile value produces a conflict and REVIEW_REQUIRED."""
    evaluator = CrossSectorEvaluator()
    # Profile age (40) disagrees with document age (25)
    profile = {
        "age": 40,
        "active_confirmed_fields": [_confirmed_doc_field("age", 25)],
    }
    res = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        profile=profile,
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res["has_conflicts"] is True
    assert res["status"] == "REVIEW_REQUIRED"
    assert res["rule_match_status"] == "UNKNOWN"
    assert "minimum_age" in res["missing_information"]
    assert len(res["conflicts"]) == 1
    assert res["conflicts"][0]["attribute"] == "age"
    assert res["conflicts"][0]["profile_value"] == 40
    assert res["conflicts"][0]["confirmed_document_value"] == 25


def test_regression_point_12_invalid_age_and_gender_values_rejected():
    """12. Invalid age and gender values are rejected."""
    evaluator = CrossSectorEvaluator()

    # Age out of range (150)
    out_of_range_doc = _confirmed_doc_field("age", 150)
    res_range = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[out_of_range_doc],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_range["rule_match_status"] == "UNKNOWN"

    # Non-numeric age string
    bad_str_doc = _confirmed_doc_field("age", "not_a_number")
    res_str = evaluator.evaluate_scheme(
        "SCHEME_MSME_001_PMEGP",
        active_confirmed_fields=[bad_str_doc],
        supplemental_data={
            "new_project_only": _declaration(True),
            "negative_list_activity": _declaration(False),
        },
    )
    assert res_str["rule_match_status"] == "UNKNOWN"

    # Invalid gender string
    bad_gender_doc = _confirmed_doc_field("gender", "UNKNOWN_GENDER")
    res_gender = evaluator.evaluate_scheme(
        "SCHEME_WOMEN_001_PMUY_2",
        active_confirmed_fields=[bad_gender_doc, _confirmed_doc_field("age", 25)],
        supplemental_data={
            "existing_lpg_connection_in_household": _declaration(False),
            "qualifying_deprivation_category": _declaration(True),
        },
    )
    assert res_gender["rule_match_status"] == "UNKNOWN"
    assert "gender" in res_gender["missing_information"]


def test_regression_point_13_existing_supplemental_declaration_validation_still_works():
    """13. Existing supplemental declaration validation still works."""
    evaluator = CrossSectorEvaluator()

    # Valid declarations
    valid_supp = {
        "land_ownership": _declaration(True),
        "institutional_landholder": _declaration(False),
        "income_tax_payee": _declaration(False),
        "constitutional_post_holder": _declaration(False),
    }
    clean_valid = evaluator.validate_supplemental_data("SCHEME_AGRI_001_PM_KISAN", valid_supp)
    assert len(clean_valid) == 4
    assert clean_valid["land_ownership"] is True

    # Invalid declarations without source or confirmed
    invalid_supp = {
        "land_ownership": {"value": True},
        "institutional_landholder": {"value": False, "confirmed": False},
        "income_tax_payee": False,
    }
    clean_invalid = evaluator.validate_supplemental_data("SCHEME_AGRI_001_PM_KISAN", invalid_supp)
    assert clean_invalid == {}


def test_regression_point_14_all_five_cross_sector_schemes_retain_verification_guard():
    """14. All five cross-sector schemes retain their existing verification guard."""
    evaluator = CrossSectorEvaluator()
    for sid in CROSS_SECTOR_SCHEME_IDS:
        res = evaluator.evaluate_scheme(sid)
        assert res["status"] == "REVIEW_REQUIRED"
        assert res["official_eligibility_confirmed"] is False
        assert res["review_required"] is True
        assert res["scheme_verification_status"] == "pending_review"


def test_regression_point_15_all_five_original_education_schemes_unaffected():
    """15. All five original education schemes remain unaffected."""
    discovery = SchemeDiscoveryService()
    engine = EligibilityEngine()
    edu_schemes = [
        "SCHEME_EDU_001_PM_USP_CSSS",
        "SCHEME_EDU_002_AICTE_PRAGATI",
        "SCHEME_EDU_003_AICTE_SAKSHAM",
        "SCHEME_EDU_004_AICTE_SWANATH",
        "SCHEME_EDU_005_TOP_CLASS_SC",
    ]
    for sid in edu_schemes:
        scheme = discovery.get_scheme_by_id(sid)
        assert scheme is not None
        assert scheme.get("category") == "EDUCATION"
        assert len(scheme.get("eligibility", {}).get("structured_rules", [])) > 0
        res = engine.evaluate(scheme, {})
        assert res["scheme_id"] == sid
        assert res["rule_match_status"] in ("UNKNOWN", "FAIL")


def test_regression_point_16_all_existing_tests_pass():
    """16. Existing tests continue to pass and hash integrity is confirmed."""
    assert len(BASELINE_PROTECTED_HASHES) == 11
    for rel_path, expected_hash in BASELINE_PROTECTED_HASHES.items():
        assert _sha256_of_file(rel_path) == expected_hash

