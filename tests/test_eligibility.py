
from eligibility.engine import EligibilityEngine


def test_pending_scheme_returns_review_required():
    engine = EligibilityEngine()

    scheme = {
        "scheme_id": "TEST_001",
        "scheme_name": "Test Scholarship",
        "verification_status": "pending_review",
        "eligibility": {
            "structured_rules": [
                {
                    "criterion": "annual_family_income",
                    "operator": "<=",
                    "required_value": 800000,
                    "logical_group": "ALL_OF",
                    "rule_type": "GENERAL",
                    "verification_status": "pending_review",
                },
                {
                    "criterion": "gender",
                    "operator": "==",
                    "required_value": "FEMALE",
                    "logical_group": "ALL_OF",
                    "rule_type": "GENERAL",
                    "verification_status": "pending_review",
                },
            ]
        },
    }

    profile = {
        "annual_family_income": 500000,
        "gender": "FEMALE",
    }

    result = engine.evaluate(scheme, profile)

    assert result["rule_match_status"] == "PASS"
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["review_required"] is True
    assert result["unverified_rule_count"] == 2
    assert result["official_eligibility_confirmed"] is False


def test_missing_information_returns_unknown():
    engine = EligibilityEngine()

    scheme = {
        "scheme_id": "TEST_002",
        "verification_status": "pending_review",
        "eligibility": {
            "structured_rules": [
                {
                    "criterion": "disability_percentage",
                    "operator": ">=",
                    "required_value": 40,
                    "logical_group": "ALL_OF",
                    "rule_type": "GENERAL",
                    "verification_status": "pending_review",
                }
            ]
        },
    }

    result = engine.evaluate(scheme, {})

    assert result["rule_match_status"] == "UNKNOWN"
    assert result["status"] == "REVIEW_REQUIRED"
    assert "disability_percentage" in result["missing_information"]


def test_fresh_rules_are_not_applied_to_renewal():
    engine = EligibilityEngine()

    scheme = {
        "scheme_id": "TEST_003",
        "verification_status": "pending_review",
        "eligibility": {
            "structured_rules": [
                {
                    "criterion": "class_12_marks",
                    "operator": ">",
                    "required_value": 80,
                    "logical_group": "ALL_OF",
                    "rule_type": "FRESH",
                    "verification_status": "pending_review",
                },
                {
                    "criterion": "renewal_marks",
                    "operator": ">=",
                    "required_value": 50,
                    "logical_group": "ALL_OF",
                    "rule_type": "RENEWAL",
                    "verification_status": "pending_review",
                },
            ]
        },
    }

    profile = {
        "application_type": "RENEWAL",
        "renewal_marks": 65,
    }

    result = engine.evaluate(scheme, profile)

    assert result["rule_match_status"] == "PASS"
    assert result["status"] == "REVIEW_REQUIRED"
    assert len(result["results"]) == 1
    assert result["results"][0]["criterion"] == "renewal_marks"


def test_verified_scheme_returns_pass():
    engine = EligibilityEngine()

    scheme = {
        "scheme_id": "TEST_004",
        "scheme_name": "Verified Test Scholarship",
        "verification_status": "verified",
        "eligibility": {
            "structured_rules": [
                {
                    "criterion": "annual_family_income",
                    "operator": "<=",
                    "required_value": 800000,
                    "logical_group": "ALL_OF",
                    "rule_type": "GENERAL",
                    "verification_status": "verified",
                },
                {
                    "criterion": "gender",
                    "operator": "==",
                    "required_value": "FEMALE",
                    "logical_group": "ALL_OF",
                    "rule_type": "GENERAL",
                    "verification_status": "verified",
                },
            ]
        },
    }

    profile = {
        "annual_family_income": 500000,
        "gender": "FEMALE",
    }

    result = engine.evaluate(scheme, profile)

    assert result["rule_match_status"] == "PASS"
    assert result["status"] == "PASS"
    assert result["review_required"] is False
    assert result["unverified_rule_count"] == 0
    assert result["official_eligibility_confirmed"] is False


def test_failed_rule_returns_fail_for_verified_scheme():
    engine = EligibilityEngine()

    scheme = {
        "scheme_id": "TEST_005",
        "verification_status": "verified",
        "eligibility": {
            "structured_rules": [
                {
                    "criterion": "annual_family_income",
                    "operator": "<=",
                    "required_value": 800000,
                    "logical_group": "ALL_OF",
                    "rule_type": "GENERAL",
                    "verification_status": "verified",
                }
            ]
        },
    }

    profile = {
        "annual_family_income": 1000000,
    }

    result = engine.evaluate(scheme, profile)

    assert result["rule_match_status"] == "FAIL"
    assert result["status"] == "FAIL"
    assert result["review_required"] is False
