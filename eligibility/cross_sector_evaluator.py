"""Isolated Cross-Sector Eligibility Evaluator for SahayAI Phase 2B.

Provides strict, deterministic evaluation for cross-sector government schemes:
1. PM-KISAN (SCHEME_AGRI_001_PM_KISAN)
2. PMEGP (SCHEME_MSME_001_PMEGP)
3. PM SVANidhi (SCHEME_URBAN_001_PM_SVANIDHI)
4. PM-SYM (SCHEME_LABOUR_001_PM_SYM)
5. PMUY 2.0 (SCHEME_WOMEN_001_PMUY_2)

IMPORTANT COMPLIANCE AND ARCHITECTURAL INVARIANTS:
1. ZERO-MODIFICATION POLICY: This is an additive isolated module that consumes
   existing public interfaces (EligibilityEngine, SchemeDiscoveryService,
   evaluate_scheme_deadline) without modifying any existing files.
2. PROVENANCE & AUTHENTICATION DISCLAIMER: Citizen confirmation declarations
   and supplemental questionnaire responses are self-attested statements
   submitted for preliminary screening. They DO NOT constitute cryptographic
   authentication, government database verification, or official eligibility confirmation.
3. CONFLICT POLICY: When a confirmed citizen profile attribute contradicts a
   confirmed supplemental attribute, neither value is selected; the affected
   attribute is cleared to None, the conflict is recorded, and the wrapper status
   is set to REVIEW_REQUIRED.
4. PMEGP ADVISORY SEPARATION: Operational requirements (Class 8 pass for >Rs. 10L/5L
   projects, project ceilings, rural/urban margin money rates) are kept separate
   as advisory review conditions and are not evaluated as engine criteria.
5. VERIFICATION GUARD: All 5 central schemes are pending verification review;
   wrapper status remains REVIEW_REQUIRED and official_eligibility_confirmed
   remains strictly False even when all rules evaluate to PASS.
"""

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from eligibility.engine import EligibilityEngine
from scheme_collection.deadline_manager import evaluate_scheme_deadline
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService

logger = logging.getLogger(__name__)

PROVENANCE_DISCLAIMER = (
    "Citizen declarations are self-attested statements submitted for preliminary "
    "eligibility screening. They do not constitute cryptographic authentication or "
    "official government verification."
)

CROSS_SECTOR_SCHEME_IDS = [
    "SCHEME_AGRI_001_PM_KISAN",
    "SCHEME_MSME_001_PMEGP",
    "SCHEME_URBAN_001_PM_SVANIDHI",
    "SCHEME_LABOUR_001_PM_SYM",
    "SCHEME_WOMEN_001_PMUY_2",
]

# Exact structured rule whitelists extracted from approved central scheme records
SCHEME_CRITERIA_WHITELISTS: Dict[str, Dict[str, str]] = {
    "SCHEME_AGRI_001_PM_KISAN": {
        "land_ownership": "boolean",
        "institutional_landholder": "boolean",
        "income_tax_payee": "boolean",
        "constitutional_post_holder": "boolean",
    },
    "SCHEME_MSME_001_PMEGP": {
        "minimum_age": "integer",
        "new_project_only": "boolean",
        "negative_list_activity": "boolean",
    },
    "SCHEME_URBAN_001_PM_SVANIDHI": {
        "occupation_street_vendor": "boolean",
        "ulb_vendor_identification": "boolean",
    },
    "SCHEME_LABOUR_001_PM_SYM": {
        "entry_age": "integer",
        "monthly_income": "number",
        "covered_by_epfo_esic_nps": "boolean",
        "income_tax_payee": "boolean",
    },
    "SCHEME_WOMEN_001_PMUY_2": {
        "gender": "string",
        "minimum_age": "integer",
        "existing_lpg_connection_in_household": "boolean",
        "qualifying_deprivation_category": "boolean",
    },
}

PMEGP_ADVISORY_CONDITIONS: List[Dict[str, Any]] = [
    {
        "criterion": "class_8_qualification_threshold",
        "title": "Educational Qualification Threshold (Class 8 Pass)",
        "description": (
            "Applicant must possess at least 8th standard pass certificate if project cost "
            "exceeds Rs. 10 Lakh for Manufacturing sector or exceeds Rs. 5 Lakh for "
            "Service/Business sector. Below these limits, no minimum educational qualification is required."
        ),
        "status": "REQUIRES_MANUAL_REVIEW",
        "requires_official_verification": True,
        "source_reference": "PMEGP Revised Guidelines 2022, Section 3.1",
    },
    {
        "criterion": "project_cost_ceilings",
        "title": "Project Cost Limits",
        "description": (
            "Maximum permissible project cost is Rs. 50 Lakh for manufacturing micro-enterprises "
            "and Rs. 20 Lakh for service/business micro-enterprises."
        ),
        "maximum_manufacturing_cost": 5000000.0,
        "maximum_service_cost": 2000000.0,
        "status": "REQUIRES_MANUAL_REVIEW",
        "requires_official_verification": True,
        "source_reference": "PMEGP Revised Guidelines 2022, Section 3.1",
    },
    {
        "criterion": "margin_money_subsidy_and_promoter_contribution",
        "title": "Margin Money Subsidy Slabs and Beneficiary Contribution",
        "description": (
            "Margin money subsidy rate: 15% (Urban General), 25% (Rural General or Urban Special), "
            "or 35% (Rural Special). Beneficiary must contribute 10% (General) or 5% (Special) own equity."
        ),
        "status": "REQUIRES_MANUAL_REVIEW",
        "requires_official_verification": True,
        "source_reference": "PMEGP Revised Guidelines 2022, Section 2.1",
    },
    {
        "criterion": "dltfc_and_bank_sanction",
        "title": "DLTFC Scrutiny, Bank Credit Appraisal and EDP Training",
        "description": (
            "Margin money release is subject to District Level Task Force Committee (DLTFC) recommendation, "
            "commercial bank loan credit appraisal, and mandatory Entrepreneurship Development Programme (EDP) training."
        ),
        "status": "REQUIRES_MANUAL_REVIEW",
        "requires_official_verification": True,
        "source_reference": "PMEGP Revised Guidelines 2022, Section 4",
    },
]


class EvaluationProfile(dict):
    """Normalized profile dictionary for eligibility evaluation.

    Subclasses dict so it can be passed directly to EligibilityEngine.evaluate().
    Carries detected conflicts as an accessible attribute.
    """

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
    ):
        super().__init__(data or {})
        self.conflicts: List[Dict[str, Any]] = conflicts or []


class CrossSectorEvaluator:
    """Evaluates cross-sector government scheme eligibility deterministically.

    Operates strictly in-memory without modifying existing scheme catalogs,
    databases, or the core EligibilityEngine.
    """

    def __init__(
        self,
        discovery_service: Optional[SchemeDiscoveryService] = None,
        engine: Optional[EligibilityEngine] = None,
    ):
        """Initialize the evaluator with reusable services."""
        self.discovery_service = (
            discovery_service
            if discovery_service is not None
            else SchemeDiscoveryService()
        )
        self.engine = engine if engine is not None else EligibilityEngine()

    def validate_supplemental_data(
        self, scheme_id: str, data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Validate citizen-supplied supplemental responses for a scheme.

        Enforces:
        - Whitelist matching per scheme.
        - Rejection of unsupported scheme IDs.
        - Structure: {"value": <val>, "source": "citizen_declaration", "confirmed": True}.
        - Strict type validation:
          - Booleans: must be actual bool (type(v) is bool). Strings ("true", "false")
            and integers (1, 0) are strictly rejected.
          - Numbers: must be finite (not NaN, not Inf), non-negative, and not bool.
            Catches OverflowError on extremely large numbers.
          - Integers: must be int, finite, non-negative, not bool.
          - Strings: must be canonical tokens (e.g. "FEMALE", "MALE", "TRANSGENDER").

        Args:
            scheme_id: Scheme identifier.
            data: Raw supplemental dictionary.

        Returns:
            Dictionary of validated {attribute_name: cleaned_value}.
        """
        if scheme_id not in CROSS_SECTOR_SCHEME_IDS:
            raise ValueError(
                f"Unsupported scheme ID '{scheme_id}'. CrossSectorEvaluator only supports: "
                f"{CROSS_SECTOR_SCHEME_IDS}"
            )

        if not data or not isinstance(data, dict):
            return {}

        whitelist = SCHEME_CRITERIA_WHITELISTS.get(scheme_id)
        if not whitelist:
            return {}

        validated: Dict[str, Any] = {}

        for key, entry in data.items():
            if key not in whitelist:
                continue

            # Must be structured declaration with value, source, confirmed
            if not isinstance(entry, dict):
                continue

            # Source must be citizen_declaration
            if entry.get("source") != "citizen_declaration":
                continue

            # Confirmed must be strictly True (boolean)
            confirmed = entry.get("confirmed")
            if type(confirmed) is not bool or confirmed is not True:
                continue

            val = entry.get("value")
            expected_type = whitelist[key]

            if expected_type == "boolean":
                # Strict bool: reject "true", "false", 1, 0, None
                if type(val) is bool:
                    validated[key] = val

            elif expected_type == "integer":
                # Strict integer: reject bools, strings, floats, NaN, negatives, huge ints
                if (
                    type(val) is int
                    and not isinstance(val, bool)
                    and 0 <= val <= 120
                ):
                    try:
                        if math.isfinite(val):
                            validated[key] = val
                    except (OverflowError, TypeError, ValueError):
                        pass

            elif expected_type == "number":
                # Strict numeric: float or int, not bool, finite, non-negative, catch OverflowError
                if type(val) in (int, float) and not isinstance(val, bool):
                    try:
                        if math.isfinite(val) and val >= 0:
                            validated[key] = val
                    except (OverflowError, TypeError, ValueError):
                        pass

            elif expected_type == "string":
                # Strict string: canonical token matching
                if type(val) is str and val in {"FEMALE", "MALE", "TRANSGENDER"}:
                    validated[key] = val

        return validated

    def build_evaluation_profile(
        self,
        scheme_id: str,
        profile: Optional[Dict[str, Any]] = None,
        supplemental_data: Optional[Dict[str, Any]] = None,
        active_confirmed_fields: Optional[Any] = None,
        return_conflicts: bool = False,
    ) -> Union[EvaluationProfile, Tuple[EvaluationProfile, List[Dict[str, Any]]]]:
        """Construct the in-memory evaluation profile merging confirmed data.

        Applies symmetric conflict clearing:
        - When a confirmed profile attribute conflicts with a confirmed supplemental
          attribute, neither value is selected.
        - The evaluation attribute is cleared to None so that EligibilityEngine
          reports UNKNOWN / missing_information.
        - The conflict is logged in `conflicts`.

        Enforces zero unsafe derivations:
        - Does NOT derive monthly_income from annual_income / 12.
        - Does NOT derive qualifying_deprivation_category from caste or BPL.
        - Does NOT derive occupation booleans from substring matching.
        - Does NOT derive eligibility attributes from document presence.

        Args:
            scheme_id: Scheme identifier.
            profile: Citizen profile dictionary.
            supplemental_data: Citizen-declared supplemental data.
            active_confirmed_fields: Whitelist/set of confirmed profile fields.
            return_conflicts: If True, returns (EvaluationProfile, conflicts).

        Returns:
            EvaluationProfile (dict subclass) with attributes and conflicts.
        """
        if scheme_id not in CROSS_SECTOR_SCHEME_IDS:
            raise ValueError(
                f"Unsupported scheme ID '{scheme_id}'. CrossSectorEvaluator only supports: "
                f"{CROSS_SECTOR_SCHEME_IDS}"
            )

        supp_clean = self.validate_supplemental_data(scheme_id, supplemental_data)
        conflicts: List[Dict[str, Any]] = []
        eval_dict: Dict[str, Any] = {}

        # 1. Validated confirmed document fields (with profile consistency check)
        confirmed_doc_age, profile_age_conflict = self._get_confirmed_age(
            profile, active_confirmed_fields
        )
        if profile_age_conflict:
            conflicts.append(profile_age_conflict)

        confirmed_doc_gender, profile_gender_conflict = self._get_confirmed_gender(
            profile, active_confirmed_fields
        )
        if profile_gender_conflict:
            conflicts.append(profile_gender_conflict)

        # 2. Scheme-specific attribute synthesis and conflict detection
        if scheme_id == "SCHEME_AGRI_001_PM_KISAN":
            # All 4 attributes are supplemental citizen declarations
            for attr in (
                "land_ownership",
                "institutional_landholder",
                "income_tax_payee",
                "constitutional_post_holder",
            ):
                eval_dict[attr] = supp_clean.get(attr)

        elif scheme_id == "SCHEME_MSME_001_PMEGP":
            # minimum_age: can come from confirmed document age or supplemental
            supp_min_age = supp_clean.get("minimum_age")
            if profile_age_conflict:
                eval_dict["minimum_age"] = None
            elif confirmed_doc_age is not None and supp_min_age is not None:
                if confirmed_doc_age != supp_min_age:
                    eval_dict["minimum_age"] = None
                    conflicts.append({
                        "attribute": "minimum_age",
                        "profile_value": confirmed_doc_age,
                        "supplemental_value": supp_min_age,
                        "reason": (
                            f"Confirmed document age ({confirmed_doc_age}) conflicts with "
                            f"confirmed supplemental minimum_age ({supp_min_age})."
                        ),
                    })
                else:
                    eval_dict["minimum_age"] = confirmed_doc_age
            elif confirmed_doc_age is not None:
                eval_dict["minimum_age"] = confirmed_doc_age
            elif supp_min_age is not None:
                # Check if unconfirmed profile has a conflicting age
                if isinstance(profile, dict) and profile.get("age") is not None:
                    raw_prof_age = profile.get("age")
                    parsed_prof_age = self._parse_raw_profile_age(profile)
                    if parsed_prof_age != supp_min_age:
                        eval_dict["minimum_age"] = None
                        conflicts.append({
                            "attribute": "minimum_age",
                            "profile_value": raw_prof_age,
                            "supplemental_value": supp_min_age,
                            "reason": (
                                f"Profile age ({raw_prof_age}) conflicts with "
                                f"confirmed supplemental minimum_age ({supp_min_age})."
                            ),
                        })
                    else:
                        eval_dict["minimum_age"] = supp_min_age
                else:
                    eval_dict["minimum_age"] = supp_min_age
            else:
                eval_dict["minimum_age"] = None

            eval_dict["new_project_only"] = supp_clean.get("new_project_only")
            eval_dict["negative_list_activity"] = supp_clean.get("negative_list_activity")

        elif scheme_id == "SCHEME_URBAN_001_PM_SVANIDHI":
            # All attributes are strictly citizen-confirmed declarations
            eval_dict["occupation_street_vendor"] = supp_clean.get(
                "occupation_street_vendor"
            )
            eval_dict["ulb_vendor_identification"] = supp_clean.get(
                "ulb_vendor_identification"
            )

        elif scheme_id == "SCHEME_LABOUR_001_PM_SYM":
            # entry_age: can come from confirmed document age or supplemental
            supp_entry_age = supp_clean.get("entry_age")
            if profile_age_conflict:
                eval_dict["entry_age"] = None
            elif confirmed_doc_age is not None and supp_entry_age is not None:
                if confirmed_doc_age != supp_entry_age:
                    eval_dict["entry_age"] = None
                    conflicts.append({
                        "attribute": "entry_age",
                        "profile_value": confirmed_doc_age,
                        "supplemental_value": supp_entry_age,
                        "reason": (
                            f"Confirmed document age ({confirmed_doc_age}) conflicts with "
                            f"confirmed supplemental entry_age ({supp_entry_age})."
                        ),
                    })
                else:
                    eval_dict["entry_age"] = confirmed_doc_age
            elif confirmed_doc_age is not None:
                eval_dict["entry_age"] = confirmed_doc_age
            elif supp_entry_age is not None:
                # Check if unconfirmed profile has a conflicting age
                if isinstance(profile, dict) and profile.get("age") is not None:
                    raw_prof_age = profile.get("age")
                    parsed_prof_age = self._parse_raw_profile_age(profile)
                    if parsed_prof_age != supp_entry_age:
                        eval_dict["entry_age"] = None
                        conflicts.append({
                            "attribute": "entry_age",
                            "profile_value": raw_prof_age,
                            "supplemental_value": supp_entry_age,
                            "reason": (
                                f"Profile age ({raw_prof_age}) conflicts with "
                                f"confirmed supplemental entry_age ({supp_entry_age})."
                            ),
                        })
                    else:
                        eval_dict["entry_age"] = supp_entry_age
                else:
                    eval_dict["entry_age"] = supp_entry_age
            else:
                eval_dict["entry_age"] = None

            # monthly_income: NO annual_income / 12 derivation!
            eval_dict["monthly_income"] = supp_clean.get("monthly_income")
            eval_dict["covered_by_epfo_esic_nps"] = supp_clean.get(
                "covered_by_epfo_esic_nps"
            )
            eval_dict["income_tax_payee"] = supp_clean.get("income_tax_payee")

        elif scheme_id == "SCHEME_WOMEN_001_PMUY_2":
            # gender: can come from confirmed document gender or supplemental
            supp_gender = supp_clean.get("gender")
            if profile_gender_conflict:
                eval_dict["gender"] = None
            elif confirmed_doc_gender is not None and supp_gender is not None:
                if confirmed_doc_gender != supp_gender:
                    eval_dict["gender"] = None
                    conflicts.append({
                        "attribute": "gender",
                        "profile_value": confirmed_doc_gender,
                        "supplemental_value": supp_gender,
                        "reason": (
                            f"Confirmed document gender ('{confirmed_doc_gender}') conflicts with "
                            f"confirmed supplemental gender ('{supp_gender}')."
                        ),
                    })
                else:
                    eval_dict["gender"] = confirmed_doc_gender
            elif confirmed_doc_gender is not None:
                eval_dict["gender"] = confirmed_doc_gender
            elif supp_gender is not None:
                # Check if unconfirmed profile has a conflicting gender
                if isinstance(profile, dict) and profile.get("gender") is not None:
                    raw_prof_gender = profile.get("gender")
                    parsed_prof_gender = self._parse_raw_profile_gender(profile)
                    if parsed_prof_gender != supp_gender:
                        eval_dict["gender"] = None
                        conflicts.append({
                            "attribute": "gender",
                            "profile_value": raw_prof_gender,
                            "supplemental_value": supp_gender,
                            "reason": (
                                f"Profile gender ('{raw_prof_gender}') conflicts with "
                                f"confirmed supplemental gender ('{supp_gender}')."
                            ),
                        })
                    else:
                        eval_dict["gender"] = supp_gender
                else:
                    eval_dict["gender"] = supp_gender
            else:
                eval_dict["gender"] = None

            # minimum_age: can come from confirmed document age or supplemental
            supp_min_age = supp_clean.get("minimum_age")
            if profile_age_conflict:
                eval_dict["minimum_age"] = None
            elif confirmed_doc_age is not None and supp_min_age is not None:
                if confirmed_doc_age != supp_min_age:
                    eval_dict["minimum_age"] = None
                    conflicts.append({
                        "attribute": "minimum_age",
                        "profile_value": confirmed_doc_age,
                        "supplemental_value": supp_min_age,
                        "reason": (
                            f"Confirmed document age ({confirmed_doc_age}) conflicts with "
                            f"confirmed supplemental minimum_age ({supp_min_age})."
                        ),
                    })
                else:
                    eval_dict["minimum_age"] = confirmed_doc_age
            elif confirmed_doc_age is not None:
                eval_dict["minimum_age"] = confirmed_doc_age
            elif supp_min_age is not None:
                if isinstance(profile, dict) and profile.get("age") is not None:
                    raw_prof_age = profile.get("age")
                    parsed_prof_age = self._parse_raw_profile_age(profile)
                    if parsed_prof_age != supp_min_age:
                        eval_dict["minimum_age"] = None
                        conflicts.append({
                            "attribute": "minimum_age",
                            "profile_value": raw_prof_age,
                            "supplemental_value": supp_min_age,
                            "reason": (
                                f"Profile age ({raw_prof_age}) conflicts with "
                                f"confirmed supplemental minimum_age ({supp_min_age})."
                            ),
                        })
                    else:
                        eval_dict["minimum_age"] = supp_min_age
                else:
                    eval_dict["minimum_age"] = supp_min_age
            else:
                eval_dict["minimum_age"] = None

            eval_dict["existing_lpg_connection_in_household"] = supp_clean.get(
                "existing_lpg_connection_in_household"
            )
            # qualifying_deprivation_category: NO caste or BPL auto-derivation!
            eval_dict["qualifying_deprivation_category"] = supp_clean.get(
                "qualifying_deprivation_category"
            )

        eval_profile = EvaluationProfile(eval_dict, conflicts)

        if return_conflicts:
            return eval_profile, conflicts
        return eval_profile

    def evaluate_scheme(
        self,
        scheme_id: str,
        profile: Optional[Dict[str, Any]] = None,
        supplemental_data: Optional[Dict[str, Any]] = None,
        active_confirmed_fields: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Evaluate a cross-sector scheme deterministically.

        Reuses `EligibilityEngine.evaluate()` without modifying it.
        Wraps output with deadline status, detected conflicts, and
        PMEGP advisory review conditions.

        Args:
            scheme_id: Scheme identifier.
            profile: Citizen profile dictionary.
            supplemental_data: Citizen-declared supplemental data.
            active_confirmed_fields: Whitelist of confirmed profile fields.

        Returns:
            Structured evaluation result dictionary.
        """
        if scheme_id not in CROSS_SECTOR_SCHEME_IDS:
            raise ValueError(
                f"Unsupported scheme ID '{scheme_id}'. CrossSectorEvaluator only supports: "
                f"{CROSS_SECTOR_SCHEME_IDS}"
            )

        # 1. Fetch scheme record
        scheme = self._load_scheme(scheme_id)
        if not scheme:
            return {
                "scheme_id": scheme_id,
                "scheme_name": "Unknown Scheme",
                "status": "UNKNOWN",
                "rule_match_status": "UNKNOWN",
                "official_eligibility_confirmed": False,
                "review_required": True,
                "conflicts": [],
                "has_conflicts": False,
                "missing_information": ["scheme_record"],
                "advisory_conditions_requiring_review": [],
                "engine_results": [],
                "scheme_verification_status": "unknown",
                "provenance_notice": PROVENANCE_DISCLAIMER,
                "deadline": None,
            }

        # 2. Build normalized evaluation profile & detect conflicts
        eval_profile = self.build_evaluation_profile(
            scheme_id=scheme_id,
            profile=profile,
            supplemental_data=supplemental_data,
            active_confirmed_fields=active_confirmed_fields,
        )
        conflicts = eval_profile.conflicts

        # 3. Delegate to core deterministic EligibilityEngine
        engine_res = self.engine.evaluate(scheme, eval_profile)

        # 4. Status determination preserving engine verification guards
        # Core engine returns REVIEW_REQUIRED for unverified schemes/rules.
        # If any conflicts were detected, wrapper status is strictly REVIEW_REQUIRED.
        has_conflicts = bool(conflicts)
        wrapper_status = (
            "REVIEW_REQUIRED"
            if (has_conflicts or engine_res.get("status") == "REVIEW_REQUIRED")
            else engine_res.get("status", "UNKNOWN")
        )

        # 5. Extract PMEGP advisory conditions requiring review
        advisory_conditions = (
            list(PMEGP_ADVISORY_CONDITIONS)
            if scheme_id == "SCHEME_MSME_001_PMEGP"
            else []
        )

        # 6. Deadline evaluation
        deadline_info = None
        try:
            d_eval = evaluate_scheme_deadline(scheme)
            deadline_info = d_eval.to_dict()
        except Exception as ex:
            logger.debug("Deadline evaluation skipped: %s", ex)

        return {
            "scheme_id": scheme.get("scheme_id", scheme_id),
            "scheme_name": scheme.get("scheme_name", ""),
            "status": wrapper_status,
            "rule_match_status": engine_res.get("rule_match_status", "UNKNOWN"),
            "official_eligibility_confirmed": False,  # Strict safeguard: never True for pending schemes
            "review_required": True,  # Central schemes are pending review
            "conflicts": conflicts,
            "has_conflicts": has_conflicts,
            "missing_information": engine_res.get("missing_information", []),
            "advisory_conditions_requiring_review": advisory_conditions,
            "engine_results": engine_res.get("results", []),
            "scheme_verification_status": scheme.get(
                "verification_status", "pending_review"
            ),
            "provenance_notice": PROVENANCE_DISCLAIMER,
            "deadline": deadline_info,
        }

    def evaluate_all(
        self,
        profile: Optional[Dict[str, Any]] = None,
        supplemental_data_by_scheme: Optional[Dict[str, Dict[str, Any]]] = None,
        active_confirmed_fields: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate all 5 supported cross-sector schemes in order.

        Args:
            profile: Citizen profile dictionary.
            supplemental_data_by_scheme: Dictionary mapping scheme_id -> supplemental_data.
            active_confirmed_fields: Whitelist of confirmed profile fields.

        Returns:
            List of evaluation result dictionaries.
        """
        results = []
        supp_map = supplemental_data_by_scheme or {}

        for scheme_id in CROSS_SECTOR_SCHEME_IDS:
            supp_data = supp_map.get(scheme_id)
            res = self.evaluate_scheme(
                scheme_id=scheme_id,
                profile=profile,
                supplemental_data=supp_data,
                active_confirmed_fields=active_confirmed_fields,
            )
            results.append(res)

        return results

    def get_questionnaire(self, scheme_id: str) -> Dict[str, Any]:
        """Expose the questionnaire schema and guidance for supplemental answers.

        Args:
            scheme_id: Scheme identifier.

        Returns:
            Dictionary containing schema, fields, and advisory instructions.
        """
        if scheme_id not in CROSS_SECTOR_SCHEME_IDS:
            raise ValueError(
                f"Unsupported scheme ID '{scheme_id}'. CrossSectorEvaluator only supports: "
                f"{CROSS_SECTOR_SCHEME_IDS}"
            )

        scheme = self._load_scheme(scheme_id) or {}
        whitelist = SCHEME_CRITERIA_WHITELISTS.get(scheme_id, {})

        fields = []
        for criterion, attr_type in whitelist.items():
            field_def = self._build_field_schema(scheme_id, criterion, attr_type)
            fields.append(field_def)

        advisory_conditions = (
            list(PMEGP_ADVISORY_CONDITIONS)
            if scheme_id == "SCHEME_MSME_001_PMEGP"
            else []
        )

        return {
            "scheme_id": scheme_id,
            "scheme_name": scheme.get("scheme_name", scheme_id),
            "fields": fields,
            "expected_structure": {
                "value": "<typed_attribute_value>",
                "source": "citizen_declaration",
                "confirmed": True,
            },
            "advisory_conditions_requiring_review": advisory_conditions,
            "disclaimer": PROVENANCE_DISCLAIMER,
        }

    # -------------------------------------------------------------------------
    # Private Helper Methods
    # -------------------------------------------------------------------------

    def _load_scheme(self, scheme_id: str) -> Optional[Dict[str, Any]]:
        """Fetch scheme record safely via DiscoveryService or central schemes file."""
        scheme = self.discovery_service.get_scheme_by_id(scheme_id)
        if scheme:
            return scheme

        # Fallback to direct read of data/schemes/central_schemes.json if needed
        central_path = Path("data/schemes/central_schemes.json")
        if central_path.exists():
            try:
                with open(central_path, "r", encoding="utf-8") as f:
                    schemes = json.load(f)
                    for s in schemes:
                        if s.get("scheme_id") == scheme_id:
                            return s
            except Exception as ex:
                logger.warning("Error reading central_schemes.json fallback: %s", ex)
        return None

    @staticmethod
    def _validate_confirmed_field_record(
        record: Any, expected_field_name: str
    ) -> Optional[Dict[str, Any]]:
        """Validate an individual confirmed document field record against the database contract.

        Compatible with ProfileManager.get_active_confirmed_fields_with_documents() output.

        Must satisfy:
        - Must be a dictionary.
        - Matching field_name.
        - Valid non-empty document reference (document_id or source_document_id).
        - Explicit confirmed state: is_confirmed is True or is_confirmed == 1.
        - confirmation_status indicating 'CONFIRMED'.
        - Evidence that source document is active and not archived (document_status != 'ARCHIVED').
        - Non-null field_value or value.
        """
        if not isinstance(record, dict):
            return None

        # 1. Matching field_name
        field_name = record.get("field_name")
        if field_name != expected_field_name:
            return None

        # 2. Valid document reference
        doc_id = record.get("document_id") or record.get("source_document_id")
        if not doc_id or not isinstance(doc_id, str) or not doc_id.strip():
            return None

        # 3. Explicit confirmed state: strict boolean True or integer 1 from SQLite
        is_confirmed = record.get("is_confirmed")
        if is_confirmed is not True and is_confirmed != 1:
            return None

        # 4. confirmation_status must be 'CONFIRMED'
        confirmation_status = record.get("confirmation_status")
        if confirmation_status != "CONFIRMED":
            return None

        # 5. Document status must not be ARCHIVED
        doc_status = record.get("document_status")
        if doc_status is not None:
            if isinstance(doc_status, str) and doc_status.upper() == "ARCHIVED":
                return None

        # 6. Must have field_value or value
        val = record.get("field_value")
        if val is None:
            val = record.get("value")
        if val is None:
            return None

        return {
            "field_name": field_name,
            "field_value": val,
            "document_id": doc_id,
            "confirmation_status": confirmation_status,
            "document_status": doc_status,
            "is_confirmed": True,
        }

    def _extract_confirmed_field_record(
        self,
        field_name: str,
        active_confirmed_fields: Optional[Any] = None,
        profile: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Search active_confirmed_fields and profile for a valid confirmed field record."""
        # 1. Check active_confirmed_fields argument
        if active_confirmed_fields:
            if isinstance(active_confirmed_fields, list):
                for item in active_confirmed_fields:
                    validated = self._validate_confirmed_field_record(item, field_name)
                    if validated:
                        return validated
            elif isinstance(active_confirmed_fields, dict):
                # Dict keyed by field_name: { "age": { ... } }
                item = active_confirmed_fields.get(field_name)
                if isinstance(item, dict):
                    validated = self._validate_confirmed_field_record(item, field_name)
                    if validated:
                        return validated
                # Or dict is a single record dict
                validated = self._validate_confirmed_field_record(active_confirmed_fields, field_name)
                if validated:
                    return validated

        # 2. Check inside profile dictionary
        if isinstance(profile, dict):
            # Check profile["active_confirmed_fields"]
            p_active = profile.get("active_confirmed_fields")
            if p_active:
                if isinstance(p_active, list):
                    for item in p_active:
                        validated = self._validate_confirmed_field_record(item, field_name)
                        if validated:
                            return validated
                elif isinstance(p_active, dict):
                    item = p_active.get(field_name)
                    if isinstance(item, dict):
                        validated = self._validate_confirmed_field_record(item, field_name)
                        if validated:
                            return validated

            # Check profile["confirmed_document_fields"]
            p_docs = profile.get("confirmed_document_fields")
            if p_docs:
                if isinstance(p_docs, list):
                    for item in p_docs:
                        validated = self._validate_confirmed_field_record(item, field_name)
                        if validated:
                            return validated
                elif isinstance(p_docs, dict):
                    item = p_docs.get(field_name)
                    if isinstance(item, dict):
                        validated = self._validate_confirmed_field_record(item, field_name)
                        if validated:
                            return validated

        return None

    def _is_profile_field_confirmed(
        self,
        profile: Optional[Dict[str, Any]],
        field_name: str,
        active_confirmed_fields: Optional[Any] = None,
    ) -> bool:
        """Verify whether an individual profile field is confirmed via reliable document record.

        Strict safety invariant:
        Global user_confirmed flags (True or 1), lists/sets of field names, or bare boolean dictionaries
        NEVER establish confirmation. Only valid provenance-bearing confirmed field records are accepted.
        """
        rec = self._extract_confirmed_field_record(field_name, active_confirmed_fields, profile)
        return rec is not None

    def _get_confirmed_age(
        self,
        profile: Optional[Dict[str, Any]],
        active_confirmed_fields: Optional[Any] = None,
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """Validate and extract confirmed age from individual confirmed field record.

        Enforces:
        - Source value from validated confirmed document record.
        - Strict normalization and numeric validation.
        - If profile["age"] disagrees with confirmed document age:
          reports a conflict, clears evaluation attribute to None.

        Returns:
            Tuple of (confirmed_age, conflict_dict_if_any).
        """
        rec = self._extract_confirmed_field_record("age", active_confirmed_fields, profile)
        if not rec:
            return None, None

        raw_val = rec.get("field_value")

        # Parse and validate confirmed document age
        doc_age: Optional[int] = None
        if type(raw_val) is int and not isinstance(raw_val, bool):
            doc_age = raw_val
        elif isinstance(raw_val, str) and raw_val.strip().isdigit():
            try:
                doc_age = int(raw_val.strip())
            except (ValueError, OverflowError):
                doc_age = None

        if doc_age is None or not (0 <= doc_age <= 120):
            return None, None

        try:
            if not math.isfinite(doc_age):
                return None, None
        except (OverflowError, TypeError, ValueError):
            return None, None

        # Compare with profile["age"] if profile is provided
        if isinstance(profile, dict) and profile.get("age") is not None:
            raw_prof_age = profile.get("age")
            prof_age: Optional[int] = None
            if type(raw_prof_age) is int and not isinstance(raw_prof_age, bool):
                prof_age = raw_prof_age
            elif isinstance(raw_prof_age, str) and raw_prof_age.strip().isdigit():
                try:
                    prof_age = int(raw_prof_age.strip())
                except (ValueError, OverflowError):
                    prof_age = None

            if prof_age is not None and prof_age != doc_age:
                conflict = {
                    "attribute": "age",
                    "profile_value": raw_prof_age,
                    "confirmed_document_value": doc_age,
                    "reason": (
                        f"Profile age ({raw_prof_age}) conflicts with "
                        f"confirmed document age ({doc_age})."
                    ),
                }
                return None, conflict

        return doc_age, None

    def _get_confirmed_gender(
        self,
        profile: Optional[Dict[str, Any]],
        active_confirmed_fields: Optional[Any] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Validate and extract confirmed gender from individual confirmed field record.

        Enforces:
        - Source value from validated confirmed document record.
        - Strict normalization (FEMALE, MALE, TRANSGENDER).
        - If profile["gender"] disagrees with confirmed document gender:
          reports a conflict, clears evaluation attribute to None.

        Returns:
            Tuple of (confirmed_gender, conflict_dict_if_any).
        """
        rec = self._extract_confirmed_field_record("gender", active_confirmed_fields, profile)
        if not rec:
            return None, None

        raw_val = rec.get("field_value")
        if not isinstance(raw_val, str):
            return None, None

        norm_doc_gender = raw_val.strip().upper()
        if norm_doc_gender not in {"FEMALE", "MALE", "TRANSGENDER"}:
            return None, None

        # Compare with profile["gender"] if provided
        if isinstance(profile, dict) and profile.get("gender") is not None:
            raw_prof_gender = profile.get("gender")
            if isinstance(raw_prof_gender, str):
                norm_prof_gender = raw_prof_gender.strip().upper()
                if norm_prof_gender != norm_doc_gender:
                    conflict = {
                        "attribute": "gender",
                        "profile_value": raw_prof_gender,
                        "confirmed_document_value": norm_doc_gender,
                        "reason": (
                            f"Profile gender ('{raw_prof_gender}') conflicts with "
                            f"confirmed document gender ('{norm_doc_gender}')."
                        ),
                    }
                    return None, conflict

        return norm_doc_gender, None

    @staticmethod
    def _parse_raw_profile_age(profile: Optional[Dict[str, Any]]) -> Optional[int]:
        """Safely parse unconfirmed age integer from profile for conflict checking."""
        if not isinstance(profile, dict) or profile.get("age") is None:
            return None
        val = profile.get("age")
        if type(val) is int and not isinstance(val, bool):
            if 0 <= val <= 120:
                return val
        elif isinstance(val, str) and val.strip().isdigit():
            try:
                parsed = int(val.strip())
                if 0 <= parsed <= 120:
                    return parsed
            except (ValueError, OverflowError):
                return None
        return None

    @staticmethod
    def _parse_raw_profile_gender(profile: Optional[Dict[str, Any]]) -> Optional[str]:
        """Safely parse unconfirmed gender string from profile for conflict checking."""
        if not isinstance(profile, dict) or profile.get("gender") is None:
            return None
        val = profile.get("gender")
        if isinstance(val, str):
            norm = val.strip().upper()
            if norm in {"FEMALE", "MALE", "TRANSGENDER"}:
                return norm
        return None

    @staticmethod
    def _build_field_schema(
        scheme_id: str, criterion: str, attr_type: str
    ) -> Dict[str, Any]:
        """Construct a questionnaire field specification."""
        prompts: Dict[str, str] = {
            "land_ownership": "Does your family own cultivable land registered in official land records?",
            "institutional_landholder": "Is the land held by an institution (e.g. religious, corporate, educational)?",
            "income_tax_payee": "Did you or any family member pay Income Tax in the last assessment year?",
            "constitutional_post_holder": "Have you or any family member held a constitutional post (e.g. Minister, MP, MLA)?",
            "minimum_age": "What is the applicant's age in completed years?",
            "new_project_only": "Is this a brand new micro-enterprise project (not expansion of an existing unit)?",
            "negative_list_activity": "Does the project involve prohibited items (tobacco, alcohol, meat, thin plastics)?",
            "occupation_street_vendor": "Are you engaged in street vending or hawking goods or services in urban/peri-urban areas?",
            "ulb_vendor_identification": "Do you possess a Certificate of Vending (CoV), Vendor ID, or Letter of Recommendation from the ULB?",
            "entry_age": "What is the subscriber's age at the time of scheme entry (must be between 18 and 40)?",
            "monthly_income": "What is your total monthly individual income in INR (must not exceed Rs. 15,000)?",
            "covered_by_epfo_esic_nps": "Are you covered under statutory social security schemes like EPFO, ESIC, or NPS?",
            "gender": "What is the applicant's legal gender (MALE, FEMALE, or TRANSGENDER)?",
            "existing_lpg_connection_in_household": "Does anyone in your household already possess an active domestic LPG connection?",
            "qualifying_deprivation_category": "Does your household qualify under deprivation categories (SC, ST, AAY, PMAY-G, or 14-point declaration)?",
        }

        schema: Dict[str, Any] = {
            "criterion": criterion,
            "label": prompts.get(criterion, f"Confirm {criterion}"),
            "type": attr_type,
            "required": True,
            "expected_source": "citizen_declaration",
            "requires_confirmation": True,
        }

        if attr_type == "string" and criterion == "gender":
            schema["allowed_values"] = ["FEMALE", "MALE", "TRANSGENDER"]

        return schema

