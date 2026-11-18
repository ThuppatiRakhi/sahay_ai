"""Citizen profile API routes for SahayAI.

Provides:
- POST /profile/me: Creates and links a citizen profile to the authenticated account.
- GET /profile/me: Retrieves the authenticated citizen's profile.

Security & Ownership Architecture:
- Requires a valid, active server-side session cookie ('sahay_session').
- Enforces CSRF protection ('X-CSRF-Token' header and Origin validation) on mutating requests.
- Identity (user_id) is derived strictly from the server-side session; client-supplied
  user_id fields are rejected or discarded.
- One-profile-per-account database constraint is enforced.
- Password hashes, session IDs, and unmasked PII are never returned in responses.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.security import (
    enforce_csrf_protection,
    get_current_active_user,
    get_current_session_or_guest,
)
from document_ai.extract_fields import AUTHENTICITY_DISCLAIMER
from profile.auth_service import AuthService


router = APIRouter(prefix="/profile", tags=["Citizen Profile"])

auth_service = AuthService()


class ProfileCreateRequest(BaseModel):
    """Pydantic schema for citizen profile creation.

    Only fields supported by the underlying SQLite schema are modeled.
    No unsupported columns (e.g. disability percentage or PWD flags) are invented.
    """
    model_config = ConfigDict(extra="ignore")

    full_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Full legal name of the citizen as registered on official records.",
        examples=["Aarav Sharma"],
    )
    date_of_birth: Optional[str] = Field(
        None,
        description="Date of birth in ISO YYYY-MM-DD format. If provided, age is calculated automatically.",
        examples=["1995-05-15"],
    )
    age: Optional[int] = Field(
        None,
        ge=0,
        le=130,
        description="Age in years. If date_of_birth is provided, age is calculated from date_of_birth.",
        examples=[31],
    )
    gender: str = Field(
        ...,
        description="Gender of the citizen. Allowed values: MALE, FEMALE, TRANSGENDER, OTHER.",
        examples=["MALE"],
    )
    state: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="State of residence in India.",
        examples=["Maharashtra"],
    )
    district: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="District of residence.",
        examples=["Pune"],
    )
    annual_income: Optional[float] = Field(
        None,
        ge=0,
        description="Total annual family income in Indian Rupees (INR).",
        examples=[180000.0],
    )
    annual_family_income: Optional[float] = Field(
        None,
        ge=0,
        description="Alias for annual_income.",
        examples=[180000.0],
    )
    occupation: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Primary occupation (e.g., STUDENT, FARMER, ARTISAN, UNEMPLOYED).",
        examples=["Farmer"],
    )
    caste_category: str = Field(
        ...,
        description="Caste category for welfare benefit mapping: GENERAL, OBC, SC, ST, EWS.",
        examples=["OBC"],
    )
    is_bpl: bool = Field(
        False,
        description="Whether the family holds a Below Poverty Line (BPL) ration card.",
        examples=[False],
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional non-sensitive metadata dictionary for extended criteria.",
        examples=[{}],
    )

    @field_validator("full_name", "state", "district", "occupation")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or only whitespace.")
        return v.strip()

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Gender is required.")
        v_upper = v.strip().upper()
        allowed = {"MALE", "FEMALE", "TRANSGENDER", "OTHER"}
        if v_upper not in allowed:
            raise ValueError(f"Gender must be one of: {', '.join(sorted(allowed))}.")
        return v_upper

    @field_validator("caste_category")
    @classmethod
    def validate_caste(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Caste category is required.")
        v_upper = v.strip().upper()
        allowed = {"GENERAL", "OBC", "SC", "ST", "EWS"}
        if v_upper not in allowed:
            raise ValueError(f"Caste category must be one of: {', '.join(sorted(allowed))}.")
        return v_upper

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        try:
            dob = datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("date_of_birth must be a valid date in YYYY-MM-DD format.")

        today = datetime.now(timezone.utc).date()
        if dob > today:
            raise ValueError("date_of_birth cannot be in the future.")
        if dob < today.replace(year=today.year - 130):
            raise ValueError("date_of_birth indicates an age exceeding 130 years.")
        return v

    @model_validator(mode="after")
    def compute_age_and_resolve_income(self) -> "ProfileCreateRequest":
        today = datetime.now(timezone.utc).date()

        # Date of birth takes precedence for calculating age consistently
        if self.date_of_birth:
            dob = datetime.strptime(self.date_of_birth, "%Y-%m-%d").date()
            calc_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            self.age = calc_age
        elif self.age is None:
            raise ValueError("Either date_of_birth or age must be provided.")
        elif not (0 <= self.age <= 130):
            raise ValueError("age must be between 0 and 130.")

        # Resolve annual_income vs annual_family_income alias
        income = self.annual_income if self.annual_income is not None else self.annual_family_income
        if income is None:
            raise ValueError("annual_income (or annual_family_income) is required.")
        self.annual_income = income

        return self


@router.post(
    "/me",
    summary="Create Citizen Profile",
    description="""
Creates a new citizen profile linked to the authenticated user account.

**Authentication & Security Requirements**:
- **HttpOnly Cookie**: Requires an active, valid `sahay_session` cookie issued via `/auth/login` or `/auth/signup`.
- **CSRF Token**: Requires a valid `X-CSRF-Token` header obtained via `GET /auth/csrf-token`.
- **Trusted Origin**: Mutating request must originate from an authorized frontend host.
- **Ownership**: The profile is strictly bound to the authenticated `user_id` extracted from the server-side session. Any `user_id` supplied in the request body is ignored.
- **One Profile Constraint**: An account can possess at most one citizen profile. Duplicate creations return HTTP 409 Conflict.

*Note for Swagger UI users*: The interactive OpenAPI documentation does not automatically attach HttpOnly session cookies unless same-origin authentication has already been established in your browser.
""",
    responses={
        200: {
            "description": "Citizen profile successfully created.",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Citizen profile created successfully.",
                        "profile": {
                            "profile_id": "prof_a1b2c3d4e5",
                            "user_id": "user_1e1d1f5ea0b5",
                            "full_name": "Aarav Sharma",
                            "date_of_birth": "1995-05-15",
                            "age": 31,
                            "gender": "MALE",
                            "state": "Maharashtra",
                            "district": "Pune",
                            "annual_income": 180000.0,
                            "occupation": "Farmer",
                            "caste_category": "OBC",
                            "is_bpl": False,
                            "user_confirmed": True,
                            "metadata": {},
                            "created_at": "2026-11-09T16:40:00+00:00",
                            "updated_at": "2026-11-09T16:40:00+00:00",
                        },
                        "next_step": "DASHBOARD",
                    }
                }
            },
        },
        401: {"description": "Unauthenticated: Missing, expired, or invalid session cookie."},
        403: {"description": "Forbidden: Missing or invalid CSRF token, or untrusted Origin."},
        409: {"description": "Conflict: A citizen profile already exists for this account."},
        422: {"description": "Validation Error: Missing required fields or invalid demographic formats."},
    },
)
def create_my_profile(
    profile_in: ProfileCreateRequest,
    current_user: dict = Depends(get_current_active_user),
    _csrf=Depends(enforce_csrf_protection),
):
    """Create and link a citizen profile to the currently authenticated account."""
    user_id = current_user["user_id"]

    profile_dict = {
        "full_name": profile_in.full_name,
        "date_of_birth": profile_in.date_of_birth,
        "age": profile_in.age,
        "gender": profile_in.gender,
        "state": profile_in.state,
        "district": profile_in.district,
        "annual_income": profile_in.annual_income,
        "occupation": profile_in.occupation,
        "caste_category": profile_in.caste_category,
        "is_bpl": profile_in.is_bpl,
        "user_confirmed": True,
        "metadata": profile_in.metadata or {},
    }

    try:
        result = auth_service.create_profile_for_user(
            user_id=user_id,
            profile_data=profile_dict,
        )

        profile = dict(result["profile"])
        profile.pop("metadata_json", None)

        return {
            "success": True,
            "message": "Citizen profile created successfully.",
            "profile": profile,
            "next_step": result.get("next_step", "DASHBOARD"),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


@router.get(
    "/me",
    summary="Get Authenticated Citizen Profile",
    description="""
Retrieves the citizen profile belonging to the currently authenticated user.

**Authentication & Ownership**:
- Requires an active `sahay_session` HttpOnly cookie.
- Strictly resolves the user from the server-side session.
- Never accepts a `user_id` query parameter to view another citizen's profile.
- Returns HTTP 404 Not Found if the user has not yet completed profile creation.
- Never exposes sensitive secrets, password hashes, or session tokens.
""",
    responses={
        200: {
            "description": "Citizen profile retrieved successfully.",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "profile": {
                            "profile_id": "prof_a1b2c3d4e5",
                            "user_id": "user_1e1d1f5ea0b5",
                            "full_name": "Aarav Sharma",
                            "date_of_birth": "1995-05-15",
                            "age": 31,
                            "gender": "MALE",
                            "state": "Maharashtra",
                            "district": "Pune",
                            "annual_income": 180000.0,
                            "occupation": "Farmer",
                            "caste_category": "OBC",
                            "is_bpl": False,
                            "user_confirmed": True,
                            "metadata": {},
                            "created_at": "2026-11-09T16:40:00+00:00",
                            "updated_at": "2026-11-09T16:40:00+00:00",
                        },
                    }
                }
            },
        },
        401: {"description": "Unauthenticated: Missing, expired, or invalid session cookie."},
        404: {"description": "Not Found: Profile has not yet been created for this account."},
    },
)
def get_my_profile(
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve the citizen profile linked to the authenticated session."""
    user_id = current_user["user_id"]

    profile = auth_service.profiles.get_profile_by_user_id(user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Citizen profile not found. Please complete profile creation.",
        )

    clean_profile = dict(profile)
    clean_profile.pop("metadata_json", None)

    return {
        "success": True,
        "profile": clean_profile,
    }


@router.get(
    "/confirmed-document-fields",
    summary="Get Confirmed Document Fields",
    description="""
Retrieves all profile fields explicitly confirmed by the authenticated citizen from uploaded documents.

Guarantees:
- Registered citizens only (guests rejected with HTTP 403 Forbidden).
- Unauthenticated requests rejected with HTTP 401 Unauthorized.
- Strict user ownership isolation.
- Detailed audit metadata (field name, confirmed value, original extracted value, is_corrected, is_confirmed=True, is_government_verified=False, source document ID, confirmation timestamp).
- Preserves full audit history; returns active latest confirmed fields by default, or complete history with active_only=false.
- Sensitive PII (Aadhaar, PAN) returned only in masked form; ciphertext is never exposed.
- Authenticity disclaimer included.
""",
)
def get_confirmed_document_fields(
    active_only: bool = True,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """Retrieve all document-extracted fields explicitly confirmed by the citizen."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Viewing confirmed document fields requires a registered citizen account.",
        )

    user_id = session_context["user_id"]
    confirmed_items = auth_service.profiles.get_confirmed_fields_by_user(
        user_id,
        active_only=active_only,
    )

    return {
        "success": True,
        "confirmed_fields": confirmed_items,
        "total_confirmed_fields": len(confirmed_items),
        "authenticity_disclaimer": AUTHENTICITY_DISCLAIMER,
    }

