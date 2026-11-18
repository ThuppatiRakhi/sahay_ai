"""Scheme Discovery Service for SahayAI.

Provides maintainable browsing, search, multi-attribute filtering,
detailed inspection, and deterministic eligibility evaluation for
official government welfare and scholarship schemes.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from eligibility.engine import EligibilityEngine
from scheme_collection.deadline_manager import (
    DeadlineInfo,
    DeadlineStatus,
    evaluate_scheme_deadline,
)
from scheme_collection.document_readiness import (
    evaluate_scheme_document_readiness,
    extract_confirmed_field_evidence,
)

logger = logging.getLogger(__name__)

DEFAULT_SCHEMES_FILE = "data/schemes/schemes.json"
CENTRAL_SCHEMES_FILE = "data/schemes/central_schemes.json"


class SchemeDiscoveryService:
    """Manages government scheme discovery, filtering, and eligibility assessment across sectors."""

    def __init__(
        self,
        schemes_file: Union[str, Path, List[Union[str, Path]]] = DEFAULT_SCHEMES_FILE,
        eligibility_engine: Optional[EligibilityEngine] = None,
        profile_manager: Optional[Any] = None,
        include_cross_sector: bool = False,
        extra_scheme_files: Optional[List[Union[str, Path]]] = None,
    ):
        if isinstance(schemes_file, list):
            self.schemes_files = [Path(f) for f in schemes_file]
        else:
            self.schemes_files = [Path(schemes_file)]
        self.schemes_file = self.schemes_files[0] if self.schemes_files else Path(DEFAULT_SCHEMES_FILE)
        self.engine = eligibility_engine or EligibilityEngine()
        self.profile_manager = profile_manager
        self.include_cross_sector = include_cross_sector
        if extra_scheme_files:
            for extra in extra_scheme_files:
                p = Path(extra)
                if p not in self.schemes_files:
                    self.schemes_files.append(p)
        if include_cross_sector:
            central_p = Path(CENTRAL_SCHEMES_FILE)
            if central_p not in self.schemes_files and central_p.exists():
                self.schemes_files.append(central_p)
        self._schemes_cache: Optional[List[Dict[str, Any]]] = None

    def _load_schemes(self, force_all: bool = False) -> List[Dict[str, Any]]:
        """Load schemes from the JSON registry."""
        if not force_all and self._schemes_cache is not None:
            return self._schemes_cache

        files_to_load = list(self.schemes_files)
        if force_all:
            central_p = Path(CENTRAL_SCHEMES_FILE)
            if central_p.exists() and central_p not in files_to_load:
                files_to_load.append(central_p)

        merged: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        for s_file in files_to_load:
            if not s_file.exists():
                logger.warning("Schemes registry file not found: %s", s_file)
                continue
            try:
                with open(s_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for scheme in data:
                            if isinstance(scheme, dict):
                                s_id = scheme.get("scheme_id")
                                if s_id and s_id not in seen_ids:
                                    seen_ids.add(s_id)
                                    merged.append(scheme)
                                elif not s_id:
                                    merged.append(scheme)
                    else:
                        logger.error("Invalid scheme registry format in %s: expected list", s_file)
            except Exception as exc:
                logger.error("Failed to load schemes file %s: %s", s_file, exc)

        if not force_all:
            self._schemes_cache = merged
        return merged

    def reload(self) -> None:
        """Clear cache and reload schemes from disk."""
        self._schemes_cache = None
        self._load_schemes()

    def get_all_schemes(self) -> List[Dict[str, Any]]:
        """Retrieve all registered schemes for this service instance."""
        return self._load_schemes()

    def load_all_schemes(self) -> List[Dict[str, Any]]:
        """Retrieve all registered schemes across all catalogues and sectors."""
        return self._load_schemes(force_all=True)

    def load_central_schemes(self) -> List[Dict[str, Any]]:
        """Retrieve specifically the central government cross-sector schemes."""
        central_p = Path(CENTRAL_SCHEMES_FILE)
        if not central_p.exists():
            return []
        try:
            with open(central_p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Failed to load central schemes file: %s", exc)
            return []

    def load_education_schemes(self) -> List[Dict[str, Any]]:
        """Retrieve specifically the core education schemes."""
        edu_p = Path(DEFAULT_SCHEMES_FILE)
        if not edu_p.exists():
            return []
        try:
            with open(edu_p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Failed to load education schemes file: %s", exc)
            return []

    def get_scheme_by_id(self, scheme_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single scheme by its unique identifier.

        Args:
            scheme_id: Canonical scheme ID (e.g. 'SCHEME_EDU_001_PM_USP_CSSS', 'SCHEME_AGRI_001_PM_KISAN').

        Returns:
            Scheme dictionary or None if not found.
        """
        if not scheme_id or not isinstance(scheme_id, str):
            return None

        clean_id = scheme_id.strip()
        # 1. Look in active registry
        for scheme in self._load_schemes():
            if scheme.get("scheme_id") == clean_id:
                res = dict(scheme)
                d_info = evaluate_scheme_deadline(res)
                res["deadline"] = d_info.to_dict()
                res["deadline_status"] = d_info.status.value
                res["is_currently_open"] = d_info.is_currently_open
                res["next_cycle_status"] = d_info.next_cycle_status
                return res

        # 2. Check central schemes if not already loaded in active registry
        central_p = Path(CENTRAL_SCHEMES_FILE)
        if central_p.exists() and central_p not in self.schemes_files:
            for scheme in self.load_central_schemes():
                if scheme.get("scheme_id") == clean_id:
                    res = dict(scheme)
                    d_info = evaluate_scheme_deadline(res)
                    res["deadline"] = d_info.to_dict()
                    res["deadline_status"] = d_info.status.value
                    res["is_currently_open"] = d_info.is_currently_open
                    res["next_cycle_status"] = d_info.next_cycle_status
                    return res

        return None

    @staticmethod
    def to_summary(scheme: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a full scheme record into a concise discovery summary with dynamic deadline status."""
        eligibility = scheme.get("eligibility", {}) if isinstance(scheme.get("eligibility"), dict) else {}
        structured_rules = eligibility.get("structured_rules", []) if isinstance(eligibility.get("structured_rules"), list) else []
        rule_types = {r.get("rule_type") for r in structured_rules if isinstance(r, dict) and r.get("rule_type")}
        if "FRESH" in rule_types and "RENEWAL" in rule_types:
            app_type = "Fresh & Renewal"
        elif "FRESH" in rule_types:
            app_type = "Fresh Application"
        elif "RENEWAL" in rule_types:
            app_type = "Renewal Application"
        else:
            app_type = scheme.get("application_type") or "Fresh / Direct"

        d_info = evaluate_scheme_deadline(scheme)

        # Beneficiaries formatted safely
        raw_ben = scheme.get("target_beneficiaries")
        if isinstance(raw_ben, list):
            target_ben = [str(b) for b in raw_ben]
        elif isinstance(raw_ben, str):
            target_ben = [raw_ben]
        else:
            target_ben = []

        return {
            "scheme_id": scheme.get("scheme_id"),
            "scheme_name": scheme.get("scheme_name"),
            "official_name": scheme.get("official_name") or scheme.get("current_official_name"),
            "current_official_name": scheme.get("current_official_name") or scheme.get("official_name"),
            "category": scheme.get("category"),
            "sector": scheme.get("sector"),
            "department": scheme.get("department") or scheme.get("responsible_department"),
            "responsible_ministry": scheme.get("responsible_ministry") or scheme.get("ministry"),
            "ministry": scheme.get("ministry") or scheme.get("responsible_ministry"),
            "implementing_agency": scheme.get("implementing_agency"),
            "description": scheme.get("description") or scheme.get("scheme_description"),
            "target_beneficiaries": target_ben,
            "application_type": app_type,
            "application_status": scheme.get("application_status"),
            "application_availability_status": scheme.get("application_availability_status") or scheme.get("application_status"),
            "scheme_status": scheme.get("scheme_status") or scheme.get("operational_status"),
            "operational_status": scheme.get("operational_status") or scheme.get("scheme_operational_status") or scheme.get("scheme_status"),
            "scheme_operational_status": scheme.get("scheme_operational_status") or scheme.get("operational_status"),
            "application_url": scheme.get("application_url") or scheme.get("official_application_url"),
            "official_application_url": scheme.get("official_application_url") or scheme.get("application_url"),
            "official_guidelines_url": scheme.get("official_guidelines_url"),
            "source_portal": scheme.get("source_portal"),
            "source_urls": scheme.get("source_urls") or [],
            "verification_status": scheme.get("verification_status", "pending_review"),
            "eligibility_verification_status": scheme.get("eligibility_verification_status") or scheme.get("verification_status", "pending_review"),
            "is_verified": bool(scheme.get("is_verified", False)),
            "max_annual_income": eligibility.get("annual_family_income_limit") or eligibility.get("max_annual_income"),
            "gender_requirement": eligibility.get("gender") or eligibility.get("gender_requirement"),
            "education_requirement": eligibility.get("education_requirement"),
            # Dynamic deadline availability attributes
            "deadline_status": d_info.status.value,
            "is_currently_open": d_info.is_currently_open,
            "application_start_date": d_info.application_start_date,
            "application_last_date": d_info.application_last_date,
            "application_cycle": d_info.application_cycle,
            "deadline_source": d_info.deadline_source,
            "deadline_verified_at": d_info.deadline_verified_at,
            "next_cycle_status": d_info.next_cycle_status,
            "days_remaining": d_info.days_remaining,
            "deadline_explanation": d_info.explanation,
            "deadline_details": d_info.to_dict(),
        }

    def search_and_filter(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        education_level: Optional[str] = None,
        beneficiary_group: Optional[str] = None,
        sector: Optional[str] = None,
        include_cross_sector: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search and filter government schemes across categories and sectors.

        Args:
            query: Free-text search matching name, description, ministry, or keywords.
            category: Filter by scheme category (e.g. 'EDUCATION', 'AGRICULTURE', 'EMPLOYMENT_AND_BUSINESS', 'SOCIAL_WELFARE').
            education_level: Filter by education criteria (e.g. 'Degree', 'Diploma', 'Class 12').
            beneficiary_group: Filter by target group (e.g. 'Girl', 'Disability', 'SC', 'Orphan', 'Farmer', 'Vendor', 'Woman').
            sector: Filter by specific focus sector (e.g. 'Agriculture', 'MSME', 'Urban Livelihoods', 'Social Security', 'Energy').
            include_cross_sector: Explicitly include cross-sector central schemes even without attribute filters.

        Returns:
            List of matching scheme summary dictionaries.
        """
        # Determine whether to search across all catalogues
        should_include_all = (
            include_cross_sector
            or self.include_cross_sector
            or (sector is not None and sector.strip() != "")
            or (category is not None and category.strip().upper() not in ("", "EDUCATION"))
            or (query is not None and any(term in query.lower() for term in ["kisan", "pm-kisan", "pmegp", "svanidhi", "vaandhan", "maandhan", "ujjwala", "farmer", "vendor", "unorganised"]))
            or (beneficiary_group is not None and any(term in beneficiary_group.lower() for term in ["farmer", "kisan", "vendor", "hawker", "worker", "unorganised", "entrepreneur", "artisan"]))
        )

        schemes = self._load_schemes(force_all=should_include_all)
        results: List[Dict[str, Any]] = []

        q_clean = query.strip().lower() if query else None
        cat_clean = category.strip().upper() if category else None
        edu_clean = education_level.strip().lower() if education_level else None
        ben_clean = beneficiary_group.strip().lower() if beneficiary_group else None
        sec_clean = sector.strip().lower() if sector else None

        for scheme in schemes:
            # 1. Category Filter
            if cat_clean:
                scheme_cat = str(scheme.get("category") or "").upper()
                if cat_clean not in scheme_cat:
                    continue

            # 2. Sector Filter
            if sec_clean:
                scheme_sec = str(scheme.get("sector") or "").lower()
                if sec_clean not in scheme_sec:
                    continue

            # 3. Education Level Filter
            if edu_clean:
                eligibility = scheme.get("eligibility", {}) if isinstance(scheme.get("eligibility"), dict) else {}
                edu_req = str(eligibility.get("education_requirement") or "").lower()
                course_req = str(eligibility.get("course_requirement") or "").lower()
                raw_target = scheme.get("target_beneficiaries", [])
                target_str = " ".join([str(t) for t in raw_target]).lower() if isinstance(raw_target, list) else str(raw_target or "").lower()
                combined_edu = f"{edu_req} {course_req} {target_str}"

                if "class 12" in edu_clean or "12th" in edu_clean or "10+2" in edu_clean:
                    if "class 12" not in combined_edu and "12th" not in combined_edu:
                        continue
                elif "diploma" in edu_clean:
                    if "diploma" not in combined_edu or "strictly ineligible" in course_req:
                        continue
                elif "degree" in edu_clean or "graduate" in edu_clean:
                    if "degree" not in combined_edu and "graduate" not in combined_edu:
                        continue
                else:
                    if edu_clean not in combined_edu:
                        continue

            # 4. Beneficiary Group Filter
            if ben_clean:
                eligibility = scheme.get("eligibility", {}) if isinstance(scheme.get("eligibility"), dict) else {}
                raw_target = scheme.get("target_beneficiaries", [])
                target_str = " ".join([str(t) for t in raw_target]).lower() if isinstance(raw_target, list) else str(raw_target or "").lower()
                gender_req = str(eligibility.get("gender_requirement") or eligibility.get("gender") or "").lower()
                disability_req = str(eligibility.get("disability_requirement") or "").lower()
                raw_caste = eligibility.get("category_requirement", [])
                caste_req = " ".join([str(c) for c in raw_caste]).lower() if isinstance(raw_caste, list) else str(raw_caste or "").lower()
                occupation_req = " ".join([str(o) for o in eligibility.get("occupation", [])]).lower() if isinstance(eligibility.get("occupation"), list) else str(eligibility.get("occupation") or "").lower()
                combined_ben = f"{target_str} {gender_req} {disability_req} {caste_req} {occupation_req}"

                matched_ben = False
                if ben_clean in combined_ben:
                    matched_ben = True
                else:
                    pwd_terms = ["disability", "disabilities", "pwd", "specially-abled", "specially abled"]
                    if any(t in ben_clean for t in pwd_terms):
                        matched_ben = any(t in combined_ben for t in ["disability", "specially-abled", "pwd", "benchmark disabilities"])
                    elif "sc" in ben_clean.split() or "scheduled caste" in ben_clean:
                        matched_ben = "sc" in combined_ben or "scheduled caste" in combined_ben
                    elif any(t in ben_clean for t in ["girl", "female", "women", "woman"]):
                        matched_ben = any(t in combined_ben for t in ["girl", "female", "women", "woman"])
                    elif any(t in ben_clean for t in ["farmer", "kisan", "cultivator"]):
                        matched_ben = any(t in combined_ben for t in ["farmer", "kisan", "cultivator"])
                    elif any(t in ben_clean for t in ["vendor", "hawker", "street"]):
                        matched_ben = any(t in combined_ben for t in ["vendor", "hawker", "street"])
                    elif any(t in ben_clean for t in ["unorganised", "worker", "labour"]):
                        matched_ben = any(t in combined_ben for t in ["unorganised", "worker", "labour"])
                    elif any(t in ben_clean for t in ["orphan", "martyr", "ward"]):
                        matched_ben = any(t in combined_ben for t in ["orphan", "martyr", "covid"])
                    else:
                        tokens = [tok for tok in ben_clean.split() if tok not in {"students", "with", "and", "or", "for", "the"}]
                        matched_ben = any(tok in combined_ben for tok in tokens) if tokens else False

                if not matched_ben:
                    continue

            # 5. Free-text Query Search (names, descriptions, keywords, departments, requirements)
            if q_clean:
                eligibility = scheme.get("eligibility", {}) if isinstance(scheme.get("eligibility"), dict) else {}
                raw_target = scheme.get("target_beneficiaries", [])
                target_str = " ".join([str(t) for t in raw_target]) if isinstance(raw_target, list) else str(raw_target or "")
                raw_caste = eligibility.get("category_requirement", [])
                caste_str = " ".join([str(c) for c in raw_caste]) if isinstance(raw_caste, list) else str(raw_caste or "")

                searchable_parts = [
                    str(scheme.get("scheme_id") or ""),
                    str(scheme.get("scheme_name") or ""),
                    str(scheme.get("official_name") or ""),
                    str(scheme.get("current_official_name") or ""),
                    str(scheme.get("category") or ""),
                    str(scheme.get("sector") or ""),
                    str(scheme.get("description") or ""),
                    str(scheme.get("scheme_description") or ""),
                    str(scheme.get("department") or ""),
                    str(scheme.get("responsible_department") or ""),
                    str(scheme.get("ministry") or ""),
                    str(scheme.get("responsible_ministry") or ""),
                    str(scheme.get("implementing_agency") or ""),
                    target_str,
                    str(eligibility.get("education_requirement") or ""),
                    str(eligibility.get("course_requirement") or ""),
                    caste_str,
                    str(eligibility.get("gender_requirement") or eligibility.get("gender") or ""),
                    str(eligibility.get("disability_requirement") or ""),
                    str(scheme.get("benefits", {}).get("type") or ""),
                    str(scheme.get("source_portal") or ""),
                    str(scheme.get("application_url") or ""),
                ]
                searchable_text = " ".join(searchable_parts).lower()
                q_tokens = [tok for tok in q_clean.replace("-", " ").replace("/", " ").split() if tok]

                if q_clean not in searchable_text and not (q_tokens and all(tok in searchable_text for tok in q_tokens)):
                    continue

            results.append(self.to_summary(scheme))

        return results

    def _prepare_eval_profile(
        self,
        profile: Dict[str, Any],
        active_confirmed_fields: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        """Maps citizen profile fields to structured eligibility rule criteria,
        integrating active citizen-confirmed document evidence and detecting conflicts.

        Returns:
            (eval_profile, provenance_map, conflicts_list)
        """
        eval_profile = dict(profile)
        provenance: Dict[str, Any] = {}
        conflicts: List[Dict[str, Any]] = []

        if active_confirmed_fields:
            # 1. Confirmed Income Integration & Conflict Detection
            inc_item = active_confirmed_fields.get("annual_income") or active_confirmed_fields.get("annual_family_income")
            if inc_item and inc_item.get("value") is not None:
                try:
                    conf_income = float(inc_item["value"])
                    prof_income = profile.get("annual_income") if profile.get("annual_income") is not None else profile.get("annual_family_income")
                    if prof_income is not None:
                        float_prof_inc = float(prof_income)
                        if abs(float_prof_inc - conf_income) > 0.01:
                            conflicts.append({
                                "criterion": "annual_family_income",
                                "profile_value": prof_income,
                                "confirmed_value": conf_income,
                                "reason": (
                                    f"Discrepancy detected: Profile annual income is ₹{float_prof_inc:,.0f} "
                                    f"while active confirmed document indicates ₹{conf_income:,.0f}."
                                ),
                            })
                        else:
                            eval_profile["annual_family_income"] = conf_income
                            eval_profile["annual_income"] = conf_income
                            provenance["annual_family_income"] = "CONFIRMED_DOCUMENT"
                    else:
                        eval_profile["annual_family_income"] = conf_income
                        eval_profile["annual_income"] = conf_income
                        provenance["annual_family_income"] = "CONFIRMED_DOCUMENT"
                except (ValueError, TypeError):
                    pass

            # 2. Confirmed Social Category / Caste Integration & Conflict Detection
            caste_item = active_confirmed_fields.get("caste_category") or active_confirmed_fields.get("social_category")
            if caste_item and caste_item.get("value") is not None:
                conf_caste = str(caste_item["value"]).strip()
                prof_caste = str(profile.get("caste_category") or profile.get("social_category") or "").strip()
                if prof_caste:
                    if prof_caste.upper() != conf_caste.upper():
                        conflicts.append({
                            "criterion": "social_category",
                            "profile_value": profile.get("caste_category") or profile.get("social_category"),
                            "confirmed_value": conf_caste,
                            "reason": (
                                f"Discrepancy detected: Profile category is '{prof_caste}' "
                                f"while active confirmed document indicates '{conf_caste}'."
                            ),
                        })
                    else:
                        eval_profile["social_category"] = conf_caste
                        eval_profile["caste_category"] = conf_caste
                        provenance["social_category"] = "CONFIRMED_DOCUMENT"
                else:
                    eval_profile["social_category"] = conf_caste
                    eval_profile["caste_category"] = conf_caste
                    provenance["social_category"] = "CONFIRMED_DOCUMENT"

            # 3. Confirmed Gender Integration & Conflict Detection
            gender_item = active_confirmed_fields.get("gender")
            if gender_item and gender_item.get("value") is not None:
                conf_gender = str(gender_item["value"]).strip()
                prof_gender = str(profile.get("gender") or "").strip()
                if prof_gender:
                    if prof_gender.upper() != conf_gender.upper():
                        conflicts.append({
                            "criterion": "gender",
                            "profile_value": prof_gender,
                            "confirmed_value": conf_gender,
                            "reason": (
                                f"Discrepancy detected: Profile gender is '{prof_gender}' "
                                f"while active confirmed document indicates '{conf_gender}'."
                            ),
                        })
                    else:
                        eval_profile["gender"] = conf_gender
                        provenance["gender"] = "CONFIRMED_DOCUMENT"
                else:
                    eval_profile["gender"] = conf_gender
                    provenance["gender"] = "CONFIRMED_DOCUMENT"

            # 4. Confirmed Academic Marks Integration
            marks_item = (
                active_confirmed_fields.get("twelfth_percentage")
                or active_confirmed_fields.get("class_12_merit_percentile")
                or active_confirmed_fields.get("class_12_minimum_marks_percentage")
            )
            if marks_item and marks_item.get("value") is not None:
                try:
                    pct_val = float(marks_item["value"])
                    eval_profile["class_12_merit_percentile"] = pct_val
                    eval_profile["class_12_minimum_marks_percentage"] = pct_val
                    eval_profile["twelfth_percentage"] = pct_val
                    provenance["class_12_merit_percentile"] = "CONFIRMED_DOCUMENT"
                except (ValueError, TypeError):
                    pass

            # 5. Confirmed Disability Status Integration
            dis_item = active_confirmed_fields.get("disability_percentage") or active_confirmed_fields.get("is_disabled")
            if dis_item and dis_item.get("value") is not None:
                try:
                    dis_val = float(dis_item["value"])
                    eval_profile["disability_percentage"] = dis_val
                    eval_profile["is_disabled"] = dis_val >= 40.0
                    provenance["disability_percentage"] = "CONFIRMED_DOCUMENT"
                except (ValueError, TypeError):
                    eval_profile["is_disabled"] = True
                    provenance["is_disabled"] = "CONFIRMED_DOCUMENT"

        # Baseline mappings if not set
        if "annual_income" in eval_profile and "annual_family_income" not in eval_profile:
            eval_profile["annual_family_income"] = eval_profile["annual_income"]

        if "caste_category" in eval_profile and "social_category" not in eval_profile:
            eval_profile["social_category"] = eval_profile["caste_category"]

        return eval_profile, provenance, conflicts

    def evaluate_scheme_for_profile(
        self,
        scheme_id: str,
        profile: Dict[str, Any],
        application_type: Optional[str] = None,
        user_id: Optional[str] = None,
        profile_manager: Optional[Any] = None,
        active_confirmed_fields: Optional[Dict[str, Any]] = None,
        user_documents: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evaluate a citizen profile against a scheme using the deterministic engine.

        Guarantees:
        - Evaluation is 100% deterministic (no probabilistic LLM decisions).
        - Respects unverified scheme status ('REVIEW_REQUIRED').
        - Never sets official_eligibility_confirmed to True for unreviewed schemes.
        - Partitions rule evaluations into matched, failed, conflicting, and unknown conditions.
        - Only uses citizen-confirmed values from active non-archived documents.
        """
        scheme = self.get_scheme_by_id(scheme_id)
        if not scheme:
            return None

        # Resolve active confirmed fields and user documents if user_id is provided
        if user_id and active_confirmed_fields is None:
            pm = profile_manager or self.profile_manager
            if pm is None:
                from profile.profile_manager import ProfileManager
                pm = ProfileManager()
            active_confirmed_fields = pm.get_active_confirmed_fields_dict(user_id)
            if user_documents is None:
                user_documents = pm.get_user_documents(user_id, include_archived=False)

        eval_profile, provenance, conflicts = self._prepare_eval_profile(profile, active_confirmed_fields)
        eval_result = self.engine.evaluate(
            scheme=scheme,
            profile=eval_profile,
            application_type=application_type,
        )

        conflict_criteria = {c["criterion"]: c for c in conflicts}
        matched_conditions = []
        failed_conditions = []
        unknown_conditions = []
        conflicting_conditions = []

        for r in eval_result.get("results", []):
            criterion = r.get("criterion")
            if criterion in conflict_criteria:
                conflict_info = conflict_criteria[criterion]
                item = {
                    "criterion": criterion,
                    "status": "CONFLICT",
                    "required_value": r.get("required_value"),
                    "actual_value": conflict_info.get("profile_value"),
                    "confirmed_document_value": conflict_info.get("confirmed_value"),
                    "operator": r.get("operator"),
                    "explanation": conflict_info["reason"],
                    "source_reference": r.get("source_reference"),
                    "reason": conflict_info["reason"],
                    "has_conflict": True,
                }
                conflicting_conditions.append(item)
                failed_conditions.append(item)
                continue

            item = {
                "criterion": criterion,
                "status": r.get("status"),
                "required_value": r.get("required_value"),
                "actual_value": r.get("actual_value"),
                "operator": r.get("operator"),
                "explanation": r.get("explanation"),
                "source_reference": r.get("source_reference"),
                "reason": r.get("reason"),
            }
            if r.get("status") == "PASS":
                matched_conditions.append(item)
            elif r.get("status") == "FAIL":
                failed_conditions.append(item)
            else:
                unknown_conditions.append(item)

        d_info = evaluate_scheme_deadline(scheme)

        # Document Readiness Evaluation
        doc_readiness = evaluate_scheme_document_readiness(
            scheme=scheme,
            user_documents=user_documents or [],
            profile=profile,
            active_confirmed_fields=active_confirmed_fields or {},
            application_type=application_type,
        )

        confirmed_evidence = extract_confirmed_field_evidence(
            scheme=scheme,
            active_confirmed_fields=active_confirmed_fields or {},
            profile=profile,
        )

        final_rule_match_status = "CONFLICT" if conflicting_conditions else eval_result.get("rule_match_status")
        final_status = "REVIEW_REQUIRED" if (conflicting_conditions or eval_result.get("review_required", True)) else final_rule_match_status

        return {
            "scheme_id": scheme.get("scheme_id"),
            "scheme_name": scheme.get("scheme_name"),
            "status": final_status,
            "rule_match_status": final_rule_match_status,
            "review_required": True,
            "unverified_rule_count": eval_result.get("unverified_rule_count", 0),
            "scheme_verification_status": scheme.get("verification_status", "pending_review"),
            "official_eligibility_confirmed": False,
            "matched_conditions": matched_conditions,
            "failed_conditions": failed_conditions,
            "conflicting_conditions": conflicting_conditions,
            "unknown_conditions": unknown_conditions,
            "missing_information": eval_result.get("missing_information", []),
            "document_readiness": doc_readiness["documents"],
            "document_readiness_summary": doc_readiness,
            "confirmed_evidence": confirmed_evidence,
            "conflict_notes": [c["reason"] for c in conflicts],
            # Availability & Deadline Distinction
            "deadline_status": d_info.status.value,
            "is_currently_open": d_info.is_currently_open,
            "application_last_date": d_info.application_last_date,
            "application_cycle": d_info.application_cycle,
            "next_cycle_status": d_info.next_cycle_status,
            "deadline_details": d_info.to_dict(),
        }

    def get_recommendations_for_profile(
        self,
        profile: Dict[str, Any],
        application_type: Optional[str] = None,
        user_id: Optional[str] = None,
        profile_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Evaluate all schemes for a citizen profile, separating potential matches from ineligible ones.

        Prioritizes schemes currently accepting applications and distinguishes eligibility
        from application availability without marking closed schemes as immediately applicable.
        Incorporates citizen-confirmed active documents to inform match confidence and document readiness.
        """
        schemes = self._load_schemes()
        preliminary_matches = []
        rule_mismatches = []

        active_confirmed_fields: Dict[str, Any] = {}
        user_documents: List[Dict[str, Any]] = []

        if user_id:
            pm = profile_manager or self.profile_manager
            if pm is None:
                from profile.profile_manager import ProfileManager
                pm = ProfileManager()
            active_confirmed_fields = pm.get_active_confirmed_fields_dict(user_id)
            user_documents = pm.get_user_documents(user_id, include_archived=False)

        for scheme in schemes:
            eval_res = self.evaluate_scheme_for_profile(
                scheme_id=scheme["scheme_id"],
                profile=profile,
                application_type=application_type,
                user_id=user_id,
                profile_manager=profile_manager,
                active_confirmed_fields=active_confirmed_fields,
                user_documents=user_documents,
            )
            if not eval_res:
                continue

            summary = self.to_summary(scheme)
            d_info = evaluate_scheme_deadline(scheme)

            record = {
                "scheme": summary,
                "status": eval_res["status"],
                "rule_match_status": eval_res["rule_match_status"],
                "review_required": eval_res["review_required"],
                "official_eligibility_confirmed": False,
                "matched_conditions_count": len(eval_res["matched_conditions"]),
                "failed_conditions_count": len(eval_res["failed_conditions"]),
                "conflicting_conditions_count": len(eval_res.get("conflicting_conditions", [])),
                "missing_information": eval_res["missing_information"],
                "document_readiness_summary": eval_res["document_readiness_summary"],
                "document_readiness": eval_res["document_readiness"],
                "confirmed_evidence": eval_res["confirmed_evidence"],
                "conflict_notes": eval_res.get("conflict_notes", []),
                # Dynamic deadline availability attributes
                "deadline_status": d_info.status.value,
                "is_currently_open": d_info.is_currently_open,
                "application_last_date": d_info.application_last_date,
                "application_cycle": d_info.application_cycle,
                "next_cycle_status": d_info.next_cycle_status,
                "deadline_details": d_info.to_dict(),
            }

            if eval_res["rule_match_status"] in ("FAIL", "CONFLICT") or eval_res.get("conflicting_conditions"):
                rule_mismatches.append(record)
            else:
                preliminary_matches.append(record)

        # Sort recommendations:
        # 1. Prioritize schemes currently accepting applications (is_currently_open == True)
        # 2. Prioritize schemes with complete document readiness (is_ready == True)
        # 3. Status priority: OPEN (0) > UPCOMING (1) > NOT_ANNOUNCED (2) > UNVERIFIED (3) > CLOSED (4)
        # 4. Confirmed document count (descending)
        # 5. Matched conditions count (descending)
        def _sort_key(rec):
            status = rec.get("deadline_status")
            status_order = {
                "OPEN": 0,
                "UPCOMING": 1,
                "NOT_ANNOUNCED": 2,
                "UNVERIFIED": 3,
                "CLOSED": 4,
            }.get(status, 5)
            open_rank = 0 if rec.get("is_currently_open") else 1
            doc_sum = rec.get("document_readiness_summary") or {}
            doc_ready_rank = 0 if doc_sum.get("is_ready") else 1
            confirmed_docs = -doc_sum.get("confirmed_count", 0)
            matched_count = -rec.get("matched_conditions_count", 0)
            return (open_rank, doc_ready_rank, status_order, confirmed_docs, matched_count)

        preliminary_matches.sort(key=_sort_key)

        open_matches = [m for m in preliminary_matches if m.get("is_currently_open")]
        closed_matches = [m for m in preliminary_matches if not m.get("is_currently_open")]

        return {
            "total_schemes_evaluated": len(schemes),
            "potential_matches_count": len(preliminary_matches),
            "rule_mismatches_count": len(rule_mismatches),
            "open_matches_count": len(open_matches),
            "closed_matches_count": len(closed_matches),
            "preliminary_matches": preliminary_matches,
            "rule_mismatches_requiring_review": rule_mismatches,
            "recommendations": preliminary_matches,
        }

