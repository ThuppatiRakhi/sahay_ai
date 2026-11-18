"""Scheme validation logic for SahayAI.

Validates that raw or incoming scheme records adhere to the required schema
and data integrity constraints using Pydantic and JSON Schema Draft 2020-12.
Supports machine-readable eligibility rules, document lists, source evidence audits,
and explicit separation of scheme operational status from application status.
"""

from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from urllib.parse import urlparse
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, model_validator

from shared_contracts import SCHEMA_PATH, get_shared_schemas


class SchemeValidationError(Exception):
    """Raised when a scheme fails structural or data integrity validation."""
    pass


class StructuredRuleModel(BaseModel):
    """Machine-readable structured rule for deterministic eligibility evaluation."""
    criterion: str = Field(..., min_length=2, description="Target attribute name, e.g. 'family_annual_income'")
    operator: str = Field(..., min_length=1, description="Comparison operator, e.g. '<=', '>=', '==', 'IN', 'ANY_OF'")
    required_value: Any = Field(..., description="Value or threshold required for eligibility")
    unit: Optional[str] = Field(None, description="Unit of measurement, e.g. 'INR', 'percentile'")
    explanation: str = Field(..., min_length=5, description="Human-understandable explanation of the rule")
    source_reference: str = Field(..., min_length=3, description="Official guideline clause or reference")
    effective_date: Optional[str] = Field(None, description="Date since when this rule became effective")
    effective_academic_year: Optional[str] = Field(None, description="Effective academic cycle, e.g. 'AY 2026-27'")
    verification_status: Optional[Literal["verified", "partial", "pending_review", "uncertain"]] = "pending_review"
    rule_type: Optional[Literal["FRESH", "RENEWAL", "GENERAL", "CONDITIONAL", "BOTH"]] = "GENERAL"
    logical_group: Optional[Literal["ALL_OF", "ANY_OF", "ONE_OF"]] = "ALL_OF"


class RequiredDocumentModel(BaseModel):
    """Structured representation of a document required for scheme application."""
    document_name: str = Field(..., min_length=2)
    requirement_type: Literal["MANDATORY", "CONDITIONAL", "OPTIONAL", "NOT_SPECIFIED"] = "MANDATORY"
    mandatory_or_optional: Optional[Literal["MANDATORY", "OPTIONAL", "CONDITIONAL", "NOT_SPECIFIED"]] = None
    applicable_condition: Optional[str] = None
    issuing_authority: Optional[str] = None
    source_reference: Optional[str] = None

    @model_validator(mode="after")
    def sync_requirement_type(self) -> "RequiredDocumentModel":
        if self.mandatory_or_optional is None:
            self.mandatory_or_optional = self.requirement_type
        return self


class OfficialSourceModel(BaseModel):
    """Structured record of an official source reference supporting scheme details."""
    source_title: str = Field(..., min_length=3)
    source_url: str = Field(..., min_length=8)
    source_type: str = Field("Guidelines", min_length=2)
    issuing_authority: Optional[str] = None
    publication_date: Optional[str] = None
    applicable_academic_year: Optional[str] = None
    section_or_clause: Optional[str] = None
    date_checked: Optional[str] = None
    claims_supported: Optional[List[str]] = None
    source_publication_date: Optional[str] = None
    last_checked_date: Optional[str] = None


class SchemeEligibilityModel(BaseModel):
    """Pydantic model for scheme eligibility criteria, supporting both legacy and rich rules."""
    min_age: Optional[int] = Field(None, ge=0, le=120)
    max_age: Optional[int] = Field(None, ge=0, le=120)
    gender: Literal["ALL", "MALE", "FEMALE", "TRANSGENDER"] = "ALL"
    max_annual_income: Optional[float] = Field(None, ge=0)
    occupation: List[str] = Field(default_factory=lambda: ["ALL"])
    landholding: Optional[bool] = None
    states: List[str] = Field(default_factory=lambda: ["ALL"])

    # Detailed criteria
    minimum_age: Optional[int] = Field(None, ge=0, le=120)
    maximum_age: Optional[int] = Field(None, ge=0, le=120)
    gender_requirement: Optional[str] = None
    state_residency_requirement: Optional[List[str]] = None
    category_requirement: Optional[List[str]] = None
    annual_family_income_limit: Optional[float] = Field(None, ge=0)
    income_definition: Optional[str] = None
    education_requirement: Optional[str] = None
    minimum_marks_requirement: Optional[Any] = None
    course_requirement: Optional[Any] = None
    institution_requirement: Optional[Any] = None
    disability_requirement: Optional[Any] = None
    occupation_requirement: Optional[List[str]] = None
    land_ownership_requirement: Optional[Any] = None
    family_status_requirement: Optional[str] = None
    other_eligibility_conditions: Optional[List[str]] = None
    exclusions: Optional[List[str]] = None
    renewal_conditions: Optional[Any] = None
    structured_rules: Optional[List[StructuredRuleModel]] = None

    @model_validator(mode="after")
    def validate_age_range(self) -> "SchemeEligibilityModel":
        if self.min_age is not None and self.max_age is not None:
            if self.min_age > self.max_age:
                raise ValueError(f"min_age ({self.min_age}) cannot be greater than max_age ({self.max_age})")
        if self.minimum_age is not None and self.maximum_age is not None:
            if self.minimum_age > self.maximum_age:
                raise ValueError(f"minimum_age ({self.minimum_age}) cannot be greater than maximum_age ({self.maximum_age})")
        return self


class SchemeBenefitsModel(BaseModel):
    """Pydantic model for scheme benefits."""
    type: str = Field(..., min_length=2)
    amount_annual: Optional[float] = Field(None, ge=0)
    disbursement_frequency: Optional[str] = None

    # Detailed benefit attributes
    benefit_type: Optional[str] = None
    financial_assistance_amount: Optional[float] = None
    amount_unit: Optional[str] = None
    payment_frequency: Optional[str] = None
    duration: Optional[str] = None
    maximum_benefit: Optional[Any] = None
    non_financial_benefits: Optional[List[str]] = None
    number_of_installments: Optional[Any] = None
    beneficiary_contribution: Optional[Any] = None


class HumanReviewModel(BaseModel):
    """Pydantic model for scheme human reviewer step."""
    reviewer_id: str = Field(..., min_length=2)
    decision: Literal["APPROVED", "REJECTED", "PENDING_REVIEW"] = "PENDING_REVIEW"
    review_notes: str = Field(..., min_length=3)
    reviewed_at: Optional[str] = None


class SchemeModel(BaseModel):
    """Pydantic model validating complete scheme representation."""
    scheme_id: str = Field(..., min_length=3)
    scheme_name: str = Field(..., min_length=3)
    official_name: Optional[str] = None
    current_official_name: Optional[str] = None
    category: Optional[str] = None
    sector: Optional[str] = None
    government_level: Optional[Literal["Central", "State"]] = None
    state_applicability: Optional[List[str]] = None
    responsible_ministry: Optional[str] = None
    ministry: Optional[str] = None
    responsible_department: Optional[str] = None
    department: str = Field(..., min_length=2)
    implementing_agency: Optional[str] = None
    scheme_description: Optional[str] = None
    description: str = Field(..., min_length=5)
    target_beneficiaries: Optional[Any] = None

    # Distinct separation of operational vs application status
    scheme_status: Literal["ACTIVE", "INACTIVE", "DISCONTINUED", "MERGED", "RENAMED", "UNCERTAIN"] = "ACTIVE"
    operational_status: Literal["ACTIVE", "INACTIVE", "DISCONTINUED", "RENAMED", "UNKNOWN"] = "ACTIVE"
    scheme_operational_status: Optional[Literal["ACTIVE", "INACTIVE", "DISCONTINUED", "RENAMED", "UNKNOWN"]] = None
    application_status: Literal["OPEN", "CLOSED", "NOT_YET_OPEN", "NOT_ANNOUNCED", "YEAR_ROUND", "QUOTA_DEPENDENT", "NEEDS_LIVE_VERIFICATION", "UNKNOWN"] = "NOT_ANNOUNCED"
    application_availability_status: Optional[Literal["OPEN", "CLOSED", "YEAR_ROUND", "UPCOMING", "QUOTA_DEPENDENT", "NOT_ANNOUNCED", "NEEDS_LIVE_VERIFICATION"]] = None
    eligibility_verification_status: Optional[str] = None
    current_application_cycle: Optional[str] = None
    application_start_date: Optional[str] = None
    application_deadline: Optional[str] = None
    last_application_deadline: Optional[str] = None
    student_submission_deadline: Optional[str] = None
    institute_verification_deadline: Optional[str] = None
    nodal_verification_deadline: Optional[str] = None
    next_expected_cycle: Optional[str] = None
    application_status_last_checked: Optional[str] = None
    application_status_evidence: Optional[str] = None
    current_guideline_version: Optional[Any] = None
    historical_guideline_info: Optional[List[Dict[str, Any]]] = None

    launch_year: Optional[int] = None
    source_portal: Optional[str] = None
    eligibility: SchemeEligibilityModel
    benefits: SchemeBenefitsModel
    required_documents: List[Union[str, RequiredDocumentModel]] = Field(default_factory=list)
    application_method: Optional[Literal["Online", "Offline", "Both"]] = None
    official_application_url: Optional[str] = None
    official_guidelines_url: Optional[str] = None
    official_information_url: Optional[str] = None
    application_steps: Optional[List[str]] = None
    renewal_deadline: Optional[str] = None
    application_fee: Optional[Any] = None
    selection_process: Optional[str] = None
    grievance_contact: Optional[str] = None
    helpline_number: Optional[str] = None
    application_tracking_information: Optional[str] = None
    application_url: str = Field(..., min_length=4)
    official_sources: Optional[List[OfficialSourceModel]] = None
    source_urls: Optional[List[str]] = None
    source_evidence_audit: Optional[List[Dict[str, Any]]] = None
    last_checked_date: Optional[str] = None
    last_verified_at: Optional[str] = None
    verification_status: Optional[Literal["verified", "partial", "pending_review", "inactive", "uncertain"]] = "pending_review"
    verification_notes: Optional[str] = None
    conflicting_information: Optional[Any] = None
    human_review_required: Optional[bool] = True
    human_review: Optional[HumanReviewModel] = None
    is_verified: bool = False
    verified_at: Optional[str] = None
    verification_source: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sync_scheme_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            # Sync official_name / current_official_name
            if values.get("official_name") and not values.get("current_official_name"):
                values["current_official_name"] = values["official_name"]
            elif values.get("current_official_name") and not values.get("official_name"):
                values["official_name"] = values["current_official_name"]

            # Sync ministry / responsible_ministry
            if values.get("ministry") and not values.get("responsible_ministry"):
                values["responsible_ministry"] = values["ministry"]
            elif values.get("responsible_ministry") and not values.get("ministry"):
                values["ministry"] = values["responsible_ministry"]

            # Sync operational_status / scheme_operational_status
            if values.get("scheme_operational_status") and not values.get("operational_status"):
                values["operational_status"] = values["scheme_operational_status"]
            elif values.get("operational_status") and not values.get("scheme_operational_status"):
                values["scheme_operational_status"] = values["operational_status"]

            # Sync application_availability_status / application_status
            if values.get("application_availability_status") and not values.get("application_status"):
                values["application_status"] = values["application_availability_status"]
            elif values.get("application_status") and not values.get("application_availability_status"):
                values["application_availability_status"] = values["application_status"]

            # Sync official_guidelines_url / official_information_url
            if values.get("official_guidelines_url") and not values.get("official_information_url"):
                values["official_information_url"] = values["official_guidelines_url"]

            # Sync last_verified_at / last_checked_date
            if values.get("last_verified_at") and not values.get("last_checked_date"):
                values["last_checked_date"] = values["last_verified_at"]
        return values


class SchemeValidator:
    """Validates scheme records against both Pydantic rules and JSON Schema Draft 2020-12."""

    def __init__(self, schema_file: Optional[Path] = None):
        """Initialize validator with JSON schema definitions."""
        self.schema_file = schema_file or SCHEMA_PATH
        with open(self.schema_file, "r", encoding="utf-8") as f:
            full_schemas = json.load(f)

        self.scheme_schema = {
            "$schema": full_schemas.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
            **full_schemas.get("definitions", {}).get("Scheme", {}),
        }
        # In draft 2020-12, provide definitions so $ref to #/definitions/... resolves properly
        if "definitions" not in self.scheme_schema and "definitions" in full_schemas:
            self.scheme_schema["definitions"] = full_schemas["definitions"]

        self.json_validator = Draft202012Validator(self.scheme_schema)

    def validate(self, scheme: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a single scheme record.

        Args:
            scheme: Dictionary containing the scheme data.

        Returns:
            Tuple containing:
                - bool: True if valid, False otherwise.
                - List[str]: List of validation error messages, if any.
        """
        errors: List[str] = []

        if not isinstance(scheme, dict):
            return False, ["Scheme record must be a JSON object (dict)."]

        # 1. JSON Schema validation
        for err in self.json_validator.iter_errors(scheme):
            path = " -> ".join([str(p) for p in err.path]) if err.path else "root"
            errors.append(f"JSON Schema error at [{path}]: {err.message}")

        # 2. Pydantic deep constraint validation
        try:
            SchemeModel(**scheme)
        except Exception as pydantic_err:
            errors.append(f"Pydantic validation error: {str(pydantic_err)}")

        return len(errors) == 0, errors

    def validate_or_raise(self, scheme: Dict[str, Any]) -> SchemeModel:
        """Validate scheme or raise SchemeValidationError on failure."""
        is_valid, errors = self.validate(scheme)
        if not is_valid:
            error_msg = f"Validation failed for scheme '{scheme.get('scheme_id', 'unknown')}': " + "; ".join(errors)
            raise SchemeValidationError(error_msg)
        return SchemeModel(**scheme)

    @staticmethod
    def detect_duplicates(schemes: List[Dict[str, Any]]) -> List[str]:
        """Detect duplicate scheme IDs or scheme names in a batch of schemes."""
        duplicates: List[str] = []
        ids = [s.get("scheme_id") for s in schemes if s.get("scheme_id")]
        names = [s.get("scheme_name") for s in schemes if s.get("scheme_name")]

        id_counts = Counter(ids)
        for s_id, count in id_counts.items():
            if count > 1:
                duplicates.append(f"Duplicate scheme_id found: '{s_id}' occurs {count} times")

        name_counts = Counter(names)
        for s_name, count in name_counts.items():
            if count > 1:
                duplicates.append(f"Duplicate scheme_name found: '{s_name}' occurs {count} times")

        return duplicates

    @staticmethod
    def report_missing_fields(scheme: Dict[str, Any]) -> Dict[str, List[str]]:
        """Report missing, empty, or unknown fields categorized by importance."""
        critical_missing: List[str] = []
        recommended_missing: List[str] = []

        # Critical fields required for all core operations
        for field in ("scheme_id", "scheme_name", "department", "description", "eligibility", "benefits", "application_url"):
            val = scheme.get(field)
            if val is None or (isinstance(val, (str, list, dict)) and len(val) == 0):
                critical_missing.append(field)

        # Recommended fields for full discovery intelligence
        for field in (
            "current_official_name",
            "category",
            "government_level",
            "responsible_ministry",
            "scheme_status",
            "application_status",
            "official_sources",
            "verification_status",
            "last_checked_date",
        ):
            val = scheme.get(field)
            if val is None or (isinstance(val, (str, list, dict)) and len(val) == 0):
                recommended_missing.append(field)

        # Eligibility checks
        elig = scheme.get("eligibility", {})
        if isinstance(elig, dict):
            if not elig.get("structured_rules"):
                recommended_missing.append("eligibility.structured_rules")

        return {
            "critical_missing": critical_missing,
            "recommended_missing": recommended_missing,
        }

    @staticmethod
    def validate_official_sources(scheme: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate that all official sources have valid URLs and official domain types."""
        sources = scheme.get("official_sources")
        if not sources or not isinstance(sources, list):
            return False, ["Missing official_sources array."]

        issues: List[str] = []
        for idx, src in enumerate(sources):
            if not isinstance(src, dict):
                issues.append(f"Source item at index {idx} must be an object.")
                continue
            url = src.get("source_url", "")
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                issues.append(f"Source '{src.get('source_title', idx)}' has invalid URL: '{url}'.")
        return len(issues) == 0, issues

    @staticmethod
    def validate_document_requirements(scheme: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate that documents are explicitly categorized with supported requirement types."""
        docs = scheme.get("required_documents")
        if not docs or not isinstance(docs, list):
            return False, ["Missing or non-array required_documents."]

        allowed_types = {"MANDATORY", "CONDITIONAL", "OPTIONAL", "NOT_SPECIFIED"}
        issues: List[str] = []

        for idx, doc in enumerate(docs):
            if isinstance(doc, str):
                continue  # Legacy string representation accepted
            if isinstance(doc, dict):
                req_type = doc.get("requirement_type") or doc.get("mandatory_or_optional")
                if req_type not in allowed_types:
                    issues.append(f"Document {idx} ({doc.get('document_name')}): invalid requirement type '{req_type}'.")
                if not doc.get("document_name"):
                    issues.append(f"Document {idx} missing document_name.")
            else:
                issues.append(f"Document {idx} must be a string or object.")

        return len(issues) == 0, issues

    @staticmethod
    def validate_structured_rules(scheme: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate structure, operator validity, and condition integrity of eligibility rules."""
        elig = scheme.get("eligibility", {})
        if not isinstance(elig, dict):
            return False, ["Eligibility field is missing or not a dictionary."]

        rules = elig.get("structured_rules")
        if not rules:
            return True, []  # Optional for legacy records

        allowed_operators = {"<=", ">=", "==", "!=", "<", ">", "IN", "NOT_IN", "EQUALS", "CONTAINS", "BETWEEN", "ANY_OF", "ALL_OF"}
        allowed_rule_types = {"FRESH", "RENEWAL", "GENERAL", "CONDITIONAL", "BOTH", None}
        allowed_logical_groups = {"ALL_OF", "ANY_OF", "ONE_OF", None}
        issues: List[str] = []

        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                issues.append(f"Rule at index {idx} must be a dictionary.")
                continue
            op = rule.get("operator", "")
            if op not in allowed_operators:
                issues.append(f"Rule {idx} ({rule.get('criterion')}): unsupported operator '{op}'.")
            if not rule.get("criterion"):
                issues.append(f"Rule {idx} missing criterion.")
            if not rule.get("explanation"):
                issues.append(f"Rule {idx} missing explanation.")
            if not rule.get("source_reference"):
                issues.append(f"Rule {idx} missing source_reference.")
            rtype = rule.get("rule_type")
            if rtype not in allowed_rule_types:
                issues.append(f"Rule {idx} ({rule.get('criterion')}): invalid rule_type '{rtype}'.")
            lgroup = rule.get("logical_group")
            if lgroup not in allowed_logical_groups:
                issues.append(f"Rule {idx} ({rule.get('criterion')}): invalid logical_group '{lgroup}'.")

        return len(issues) == 0, issues
