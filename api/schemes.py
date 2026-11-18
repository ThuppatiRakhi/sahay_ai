"""Government Scheme Discovery and Eligibility API for SahayAI.

Provides:
- GET /schemes: Search and filter government schemes.
- GET /schemes/recommendations: Preliminary scheme matching for authenticated citizen.
- GET /schemes/{scheme_id}: Comprehensive scheme details.
- GET /schemes/{scheme_id}/eligibility: Deterministic rule evaluation for authenticated citizen.

Security & Integrity:
- Profile access requires a valid, active server-side session cookie ('sahay_session').
- User identity is resolved strictly from the authenticated session (no untrusted user_id parameters).
- Eligibility is determined 100% deterministically by the rule engine (never probabilistic LLM).
- Unreviewed schemes strictly return 'REVIEW_REQUIRED' and 'official_eligibility_confirmed=false'.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.security import get_current_session_or_guest
from eligibility.cross_sector_evaluator import (
    CrossSectorEvaluator,
    CROSS_SECTOR_SCHEME_IDS,
    PROVENANCE_DISCLAIMER,
)
from profile.auth_service import AuthService
from scheme_collection.deadline_manager import evaluate_scheme_deadline
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService

router = APIRouter(prefix="/schemes", tags=["Government Schemes"])

auth_service = AuthService()
scheme_service = SchemeDiscoveryService()


class EvaluationRequest(BaseModel):
    """Request payload for deterministic eligibility evaluation with citizen declarations."""

    supplemental_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional citizen-confirmed supplemental declarations keyed by attribute.",
    )


def _format_cross_sector_evaluation_result(res: Dict[str, Any]) -> Dict[str, Any]:
    """Format CrossSectorEvaluator output into the standard SahayAI eligibility response schema."""
    matched_conditions = []
    failed_conditions = []
    unknown_conditions = []
    for r in res.get("engine_results", []):
        c_item = {
            "criterion": r.get("criterion"),
            "status": r.get("status"),
            "required_value": r.get("required_value"),
            "actual_value": r.get("actual_value"),
            "operator": r.get("operator"),
            "explanation": r.get("explanation"),
            "source_reference": r.get("source_reference"),
            "reason": r.get("reason"),
        }
        if r.get("status") == "PASS":
            matched_conditions.append(c_item)
        elif r.get("status") == "FAIL":
            failed_conditions.append(c_item)
        else:
            unknown_conditions.append(c_item)

    conflicting_conditions = []
    for c in res.get("conflicts", []):
        conflicting_conditions.append({
            "criterion": c.get("attribute"),
            "status": "CONFLICT",
            "profile_value": c.get("profile_value"),
            "confirmed_document_value": c.get("confirmed_document_value"),
            "supplemental_value": c.get("supplemental_value"),
            "reason": c.get("reason"),
            "has_conflict": True,
        })

    deadline = res.get("deadline") or {}
    return {
        "scheme_id": res["scheme_id"],
        "scheme_name": res["scheme_name"],
        "status": res["status"],
        "rule_match_status": res["rule_match_status"],
        "review_required": res["review_required"],
        "official_eligibility_confirmed": res.get("official_eligibility_confirmed", False),
        "matched_conditions": matched_conditions,
        "failed_conditions": failed_conditions,
        "conflicting_conditions": conflicting_conditions,
        "unknown_conditions": unknown_conditions,
        "missing_information": res.get("missing_information", []),
        "advisory_conditions_requiring_review": res.get("advisory_conditions_requiring_review", []),
        "conflicts": res.get("conflicts", []),
        "has_conflicts": res.get("has_conflicts", False),
        "scheme_verification_status": res.get("scheme_verification_status", "pending_review"),
        "provenance_notice": res.get("provenance_notice", PROVENANCE_DISCLAIMER),
        "deadline_status": deadline.get("status"),
        "is_currently_open": deadline.get("is_currently_open"),
        "application_last_date": deadline.get("application_last_date"),
        "application_cycle": deadline.get("application_cycle"),
        "next_cycle_status": deadline.get("next_cycle_status"),
        "deadline_details": deadline,
    }


@router.get(
    "",
    summary="Discover & Filter Government Schemes",
    description="""
Browse, search, and filter the official government schemes catalog.

**Supported Filters**:
- `q`: Search keyword across scheme name, ministry, department, and description.
- `category`: Filter by scheme category (e.g., `EDUCATION`, `AGRICULTURE`).
- `education_level`: Filter by education requirement (e.g., `Degree`, `Diploma`, `Class 12`).
- `beneficiary_group`: Filter by target demographic group (e.g., `Girl`, `Disability`, `SC`, `Farmer`).
- `sector`: Filter by sector (e.g., `Agriculture`, `MSME`, `Urban Livelihoods`).
- `include_cross_sector`: Explicitly include central cross-sector schemes in discovery.
""",
)
def list_schemes(
    q: Optional[str] = Query(None, description="Free-text search keyword"),
    category: Optional[str] = Query(None, description="Category filter (e.g. EDUCATION, AGRICULTURE)"),
    education_level: Optional[str] = Query(None, description="Education level filter (e.g. Degree, Diploma)"),
    beneficiary_group: Optional[str] = Query(None, description="Beneficiary group filter (e.g. Girl, SC, Farmer)"),
    sector: Optional[str] = Query(None, description="Sector filter (e.g. Agriculture, MSME, Urban Livelihoods)"),
    include_cross_sector: bool = Query(False, description="Include central cross-sector schemes in discovery"),
):
    """Retrieve schemes matching search criteria and attribute filters."""
    schemes = scheme_service.search_and_filter(
        query=q,
        category=category,
        education_level=education_level,
        beneficiary_group=beneficiary_group,
        sector=sector,
        include_cross_sector=include_cross_sector,
    )

    return {
        "success": True,
        "count": len(schemes),
        "schemes": schemes,
    }


@router.get(
    "/recommendations",
    summary="Get Citizen Scheme Recommendations",
    description="""
Evaluates all registered schemes against the authenticated citizen's saved profile.

**Authentication & Privacy**:
- Requires active `sahay_session` HttpOnly cookie.
- Strictly resolves profile from authenticated server-side session.
- Returns preliminary matches and unreviewed notices. All existing schemes return `REVIEW_REQUIRED`.
""",
    responses={
        200: {"description": "Citizen scheme recommendations evaluated successfully."},
        401: {"description": "Unauthenticated: Missing or invalid session cookie."},
        403: {"description": "Forbidden: Profile-based recommendations require a registered citizen account with a saved profile."},
        404: {"description": "Not Found: Citizen profile has not yet been created."},
    },
)
def get_recommendations(
    application_type: Optional[str] = Query(None, description="Optional application mode: FRESH or RENEWAL"),
    include_cross_sector: bool = Query(False, description="Include central cross-sector schemes in recommendations"),
    category: Optional[str] = Query(None, description="Optional category filter (e.g. EDUCATION, AGRICULTURE)"),
    current_session: dict = Depends(get_current_session_or_guest),
):
    """Generate deterministic preliminary scheme recommendations for registered citizen accounts."""
    if current_session.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profile-based recommendations require a registered citizen account with a saved profile. Please create an account or log in.",
        )

    user_id = current_session["user_id"]
    profile = auth_service.profiles.get_profile_by_user_id(user_id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Citizen profile not found. Please complete profile creation first.",
        )

    clean_profile = dict(profile)
    clean_profile.pop("metadata_json", None)

    results = scheme_service.get_recommendations_for_profile(
        profile=clean_profile,
        application_type=application_type,
        user_id=user_id,
        profile_manager=auth_service.profiles,
    )

    # Cross-sector evaluation when explicitly requested or when non-education category filter is used
    cat_clean = category.strip().upper() if category else None
    if include_cross_sector or (cat_clean and cat_clean != "EDUCATION"):
        cross_eval = CrossSectorEvaluator(discovery_service=scheme_service)
        confirmed_records = auth_service.profiles.get_active_confirmed_fields_with_documents(user_id)
        central_schemes = scheme_service.load_central_schemes()
        seen_ids = {r["scheme"]["scheme_id"] for r in results["preliminary_matches"]}
        seen_ids.update(r["scheme"]["scheme_id"] for r in results["rule_mismatches_requiring_review"])

        for cs in central_schemes:
            cs_id = cs.get("scheme_id")
            if not cs_id or cs_id in seen_ids:
                continue
            if cat_clean and cat_clean not in str(cs.get("category", "")).upper():
                continue

            cross_res = cross_eval.evaluate_scheme(
                scheme_id=cs_id,
                profile=clean_profile,
                active_confirmed_fields=confirmed_records,
            )
            summary = scheme_service.to_summary(cs)
            deadline = cross_res.get("deadline") or {}

            rec_item = {
                "scheme": summary,
                "status": cross_res["status"],
                "rule_match_status": cross_res["rule_match_status"],
                "review_required": cross_res["review_required"],
                "official_eligibility_confirmed": False,
                "matched_conditions_count": sum(1 for r in cross_res.get("engine_results", []) if r.get("status") == "PASS"),
                "failed_conditions_count": sum(1 for r in cross_res.get("engine_results", []) if r.get("status") == "FAIL"),
                "conflicting_conditions_count": len(cross_res.get("conflicts", [])),
                "missing_information": cross_res.get("missing_information", []),
                "advisory_conditions_requiring_review": cross_res.get("advisory_conditions_requiring_review", []),
                "conflicts": cross_res.get("conflicts", []),
                "conflict_notes": [c.get("reason", "") for c in cross_res.get("conflicts", [])],
                "deadline_status": deadline.get("status", "UNVERIFIED"),
                "is_currently_open": deadline.get("is_currently_open", False),
                "application_last_date": deadline.get("application_last_date"),
                "application_cycle": deadline.get("application_cycle"),
                "next_cycle_status": deadline.get("next_cycle_status"),
                "deadline_details": deadline,
            }

            if cross_res["rule_match_status"] in ("FAIL", "CONFLICT") or cross_res.get("has_conflicts"):
                results["rule_mismatches_requiring_review"].append(rec_item)
            else:
                results["preliminary_matches"].append(rec_item)
            seen_ids.add(cs_id)

        # If category filter was specified, also filter the preliminary matches and mismatches
        if cat_clean:
            results["preliminary_matches"] = [
                m for m in results["preliminary_matches"]
                if cat_clean in str(m["scheme"].get("category", "")).upper()
            ]
            results["rule_mismatches_requiring_review"] = [
                m for m in results["rule_mismatches_requiring_review"]
                if cat_clean in str(m["scheme"].get("category", "")).upper()
            ]

        # Update totals
        open_matches = [m for m in results["preliminary_matches"] if m.get("is_currently_open")]
        closed_matches = [m for m in results["preliminary_matches"] if not m.get("is_currently_open")]
        results["total_schemes_evaluated"] = len(results["preliminary_matches"]) + len(results["rule_mismatches_requiring_review"])
        results["potential_matches_count"] = len(results["preliminary_matches"])
        results["rule_mismatches_count"] = len(results["rule_mismatches_requiring_review"])
        results["open_matches_count"] = len(open_matches)
        results["closed_matches_count"] = len(closed_matches)
        results["recommendations"] = results["preliminary_matches"]

    return {
        "success": True,
        **results,
    }


@router.get(
    "/{scheme_id}/questionnaire",
    summary="Get Supplemental Questionnaire Schema for Scheme",
    description="""
Retrieves the official supplemental questionnaire fields, expected data types,
and advisory conditions for cross-sector schemes requiring citizen declaration.
""",
    responses={
        200: {"description": "Questionnaire schema retrieved successfully."},
        404: {"description": "Scheme ID not found."},
    },
)
def get_scheme_questionnaire(scheme_id: str):
    """Retrieve supplemental questionnaire specification for a scheme."""
    cross_eval = CrossSectorEvaluator(discovery_service=scheme_service)
    if scheme_id not in CROSS_SECTOR_SCHEME_IDS:
        scheme = scheme_service.get_scheme_by_id(scheme_id)
        if not scheme:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheme '{scheme_id}' was not found in the official registry.",
            )
        return {
            "success": True,
            "scheme_id": scheme_id,
            "scheme_name": scheme.get("scheme_name", ""),
            "fields": [],
            "requires_supplemental": False,
            "advisory_conditions_requiring_review": [],
            "disclaimer": PROVENANCE_DISCLAIMER,
        }

    q = cross_eval.get_questionnaire(scheme_id)
    return {
        "success": True,
        "requires_supplemental": True,
        **q,
    }


@router.get(
    "/{scheme_id}",
    summary="Get Scheme Details",
    description="""
Retrieves complete, un-redacted official information for a specific government scheme.
Includes benefits, eligibility criteria, required documents, application process, and source evidence.
""",
    responses={
        200: {"description": "Scheme details retrieved successfully."},
        404: {"description": "Scheme ID not found."},
    },
)
def get_scheme_details(scheme_id: str):
    """Retrieve full official details for a given scheme ID."""
    scheme = scheme_service.get_scheme_by_id(scheme_id)
    if not scheme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheme '{scheme_id}' was not found in the official registry.",
        )

    return {
        "success": True,
        "scheme": scheme,
    }


@router.get(
    "/{scheme_id}/eligibility",
    summary="Evaluate Citizen Eligibility for Scheme",
    description="""
Runs deterministic rule evaluation between the authenticated citizen's saved profile
and the official structured rules of the specified scheme.

**Evaluation Guarantees**:
- Evaluated 100% deterministically by the rule engine.
- Outlines satisfied conditions, failed conditions, and missing information.
- All unreviewed schemes return status `REVIEW_REQUIRED` and `official_eligibility_confirmed=false`.
""",
    responses={
        200: {"description": "Eligibility evaluation completed successfully."},
        401: {"description": "Unauthenticated: Missing or invalid session cookie."},
        404: {"description": "Not Found: Profile or scheme not found."},
    },
)
def evaluate_eligibility(
    scheme_id: str,
    application_type: Optional[str] = Query(None, description="Optional application mode: FRESH or RENEWAL"),
    current_session: dict = Depends(get_current_session_or_guest),
):
    """Perform deterministic eligibility evaluation for a scheme using the current session (registered or guest)."""
    if current_session.get("is_guest"):
        profile = current_session.get("context", {}).get("temporary_profile")
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Temporary guest profile not provided. Please enter demographic details to evaluate eligibility.",
            )
        clean_profile = dict(profile)
        confirmed_fields = None
    else:
        user_id = current_session["user_id"]
        profile = auth_service.profiles.get_profile_by_user_id(user_id)

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Citizen profile not found. Please complete profile creation first.",
            )

        clean_profile = dict(profile)
        clean_profile.pop("metadata_json", None)
        confirmed_fields = auth_service.profiles.get_active_confirmed_fields_with_documents(user_id)

    # Route to CrossSectorEvaluator for central cross-sector schemes
    if scheme_id in CROSS_SECTOR_SCHEME_IDS:
        cross_eval = CrossSectorEvaluator(discovery_service=scheme_service)
        eval_res = cross_eval.evaluate_scheme(
            scheme_id=scheme_id,
            profile=clean_profile,
            active_confirmed_fields=confirmed_fields,
        )
        formatted = _format_cross_sector_evaluation_result(eval_res)
        return {
            "success": True,
            **formatted,
        }

    # Route to core EligibilityEngine via SchemeDiscoveryService for education schemes
    user_id = current_session.get("user_id") if not current_session.get("is_guest") else None
    eval_result = scheme_service.evaluate_scheme_for_profile(
        scheme_id=scheme_id,
        profile=clean_profile,
        application_type=application_type,
        user_id=user_id,
        profile_manager=auth_service.profiles if user_id else None,
    )

    if eval_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheme '{scheme_id}' was not found in the official registry.",
        )

    return {
        "success": True,
        **eval_result,
    }


@router.post(
    "/{scheme_id}/eligibility",
    summary="Evaluate Citizen Eligibility with Supplemental Declarations",
    description="""
Evaluates eligibility deterministically using the authenticated citizen's saved profile,
active confirmed document records, and client-supplied supplemental questionnaire declarations.
""",
    responses={
        200: {"description": "Eligibility evaluation completed successfully."},
        401: {"description": "Unauthenticated: Missing or invalid session cookie."},
        404: {"description": "Not Found: Profile or scheme not found."},
    },
)
def evaluate_eligibility_with_supplemental(
    scheme_id: str,
    body: Optional[EvaluationRequest] = None,
    application_type: Optional[str] = Query(None, description="Optional application mode: FRESH or RENEWAL"),
    current_session: dict = Depends(get_current_session_or_guest),
):
    """Evaluate eligibility incorporating client-declared supplemental questionnaire responses."""
    if current_session.get("is_guest"):
        profile = current_session.get("context", {}).get("temporary_profile")
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Temporary guest profile not provided. Please enter demographic details to evaluate eligibility.",
            )
        clean_profile = dict(profile)
        confirmed_fields = None
    else:
        user_id = current_session["user_id"]
        profile = auth_service.profiles.get_profile_by_user_id(user_id)

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Citizen profile not found. Please complete profile creation first.",
            )

        clean_profile = dict(profile)
        clean_profile.pop("metadata_json", None)
        confirmed_fields = auth_service.profiles.get_active_confirmed_fields_with_documents(user_id)

    supplemental_data = body.supplemental_data if body else None

    # Route to CrossSectorEvaluator for central cross-sector schemes
    if scheme_id in CROSS_SECTOR_SCHEME_IDS:
        cross_eval = CrossSectorEvaluator(discovery_service=scheme_service)
        eval_res = cross_eval.evaluate_scheme(
            scheme_id=scheme_id,
            profile=clean_profile,
            supplemental_data=supplemental_data,
            active_confirmed_fields=confirmed_fields,
        )
        formatted = _format_cross_sector_evaluation_result(eval_res)
        return {
            "success": True,
            **formatted,
        }

    # Route to core EligibilityEngine for education schemes
    user_id = current_session.get("user_id") if not current_session.get("is_guest") else None
    eval_result = scheme_service.evaluate_scheme_for_profile(
        scheme_id=scheme_id,
        profile=clean_profile,
        application_type=application_type,
        user_id=user_id,
        profile_manager=auth_service.profiles if user_id else None,
    )

    if eval_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheme '{scheme_id}' was not found in the official registry.",
        )

    return {
        "success": True,
        **eval_result,
    }

