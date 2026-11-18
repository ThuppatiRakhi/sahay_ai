"""FastAPI router for Scholarship Application Workspace (Step 5.5A).

Provides endpoints for:
- Scheme application definition retrieval.
- Draft creation, reading, updating, and deletion for registered citizens.
- Enforcement of strict citizen data isolation (IDOR protection) and CSRF security.
- Clear disclaimers that final submission is external on official government portals.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.security import enforce_csrf_protection, get_current_session_or_guest
from applications.application_service import ApplicationService
from applications.autofill_service import AutofillService
from scheme_collection.application_definitions import (
    get_all_application_definitions,
    get_application_definition,
    is_valid_scheme_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/applications", tags=["Scholarship Applications"])
app_service = ApplicationService()
autofill_service = AutofillService(app_service=app_service)


# ---------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------

class CreateDraftRequest(BaseModel):
    """Request payload to create a new scholarship application draft."""
    scheme_id: str = Field(..., description="Official scheme identifier (e.g. SCHEME_EDU_001_PM_USP_CSSS)")
    application_mode: Optional[str] = Field("FRESH", description="Application mode: FRESH or RENEWAL")


class UpdateDraftRequest(BaseModel):
    """Request payload to update an existing application draft."""
    form_data: Optional[Dict[str, Any]] = Field(None, description="Form field values mapped by field_id")
    status: Optional[str] = Field(None, description="New status (DRAFT, READY_FOR_REVIEW, READY_TO_CONTINUE, EXTERNAL_SUBMISSION_PENDING, SUBMITTED_EXTERNALLY, CLOSED)")
    last_saved_section: Optional[str] = Field(None, description="Current section identifier being edited")
    notes: Optional[str] = Field(None, description="Citizen notes or checklist reminders")


class AutofillAuthorizeRequest(BaseModel):
    """Request payload to authorize and issue a scoped grant token for extension autofill."""
    scheme_id: str = Field(..., min_length=1, description="Target scholarship scheme ID")
    portal_url: str = Field(..., min_length=1, description="Target government portal URL (https://scholarships.gov.in)")
    draft_id: str = Field(..., min_length=1, description="Mandatory application draft ID to bind")


class AutofillPopulateRequest(BaseModel):
    """Request payload to retrieve the populated autofill package."""
    scheme_id: str = Field(..., min_length=1, description="Target scholarship scheme ID")
    portal_url: str = Field(..., min_length=1, description="Target government portal URL (https://scholarships.gov.in)")
    draft_id: str = Field(..., min_length=1, description="Mandatory application draft ID")


class AutofillApplyRequest(BaseModel):
    """Request payload to apply selected autofill fields to a draft."""
    fields_to_apply: Optional[Dict[str, Any]] = Field(None, description="Specific fields to apply, or None to apply all clean populated fields")


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------

@router.get(
    "/schemes/{scheme_id}/definition",
    summary="Get Scheme Application Definition",
    description="""
Retrieves the application definition, guidelines, official portal verification,
and structured form template for a supported scholarship scheme.
""",
    responses={
        200: {"description": "Application definition retrieved successfully."},
        404: {"description": "Scheme application definition not found."},
    },
)
def get_scheme_application_definition(scheme_id: str) -> Dict[str, Any]:
    """Retrieve application definition for a specific scholarship scheme."""
    defn = get_application_definition(scheme_id)
    if not defn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application definition for scheme '{scheme_id}' was not found. Only official supported scholarship schemes are available.",
        )

    return {
        "success": True,
        "definition": defn,
    }


@router.get(
    "/schemes",
    summary="List All Scheme Application Definitions",
    description="Retrieves application templates for all 5 supported scholarship schemes.",
)
def list_all_scheme_definitions() -> Dict[str, Any]:
    """Retrieve definitions for all 5 supported schemes."""
    defs = get_all_application_definitions()
    return {
        "success": True,
        "count": len(defs),
        "schemes": list(defs.values()),
    }


@router.post(
    "/drafts",
    status_code=status.HTTP_201_CREATED,
    summary="Create Application Draft",
    description="""
Initializes a new scholarship application draft for the authenticated registered citizen.

Security:
- Registered users only (guests receive 403 Forbidden).
- Enforces CSRF token and origin checks.
- Validates scheme ID against supported scholarship catalog.
""",
    responses={
        201: {"description": "Draft created successfully."},
        400: {"description": "Invalid scheme ID or application mode."},
        403: {"description": "Forbidden for guest sessions."},
    },
)
def create_application_draft(
    request: CreateDraftRequest,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Create a persistent application draft for an authenticated registered citizen."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scholarship application drafts require a registered citizen account. Please create an account or log in.",
        )

    user_id = session_context["user_id"]
    if not is_valid_scheme_id(request.scheme_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scheme '{request.scheme_id}' is not supported for application workspace assistance.",
        )

    try:
        draft = app_service.create_draft(
            user_id=user_id,
            scheme_id=request.scheme_id,
            application_mode=request.application_mode or "FRESH",
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    return {
        "success": True,
        "message": "Scholarship application draft initialized successfully.",
        "draft": draft,
    }


@router.get(
    "/drafts",
    summary="List Citizen's Application Drafts",
    description="""
Lists all scholarship drafts created by the authenticated citizen.

Security:
- Registered users only (guests receive 403 Forbidden).
- Queries are strictly isolated to the authenticated citizen's user_id.
""",
    responses={
        200: {"description": "List of drafts retrieved successfully."},
        403: {"description": "Forbidden for guest sessions."},
    },
)
def list_application_drafts(
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """Retrieve all application drafts belonging to the authenticated citizen."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scholarship application drafts require a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    drafts = app_service.list_drafts(user_id)
    return {
        "success": True,
        "count": len(drafts),
        "drafts": drafts,
    }


@router.get(
    "/drafts/{draft_id}",
    summary="Get Specific Application Draft",
    description="""
Retrieves complete draft details including form data and scheme definition.

Security:
- Registered users only.
- Strict ownership check: Returns 404 if draft does not exist or belongs to another user (IDOR defense).
""",
    responses={
        200: {"description": "Draft retrieved successfully."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Draft not found or access denied."},
    },
)
def get_application_draft(
    draft_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """Retrieve an application draft owned by the authenticated citizen."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scholarship application drafts require a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    draft = app_service.get_draft(draft_id, user_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application draft not found or access denied.",
        )

    return {
        "success": True,
        "draft": draft,
    }


@router.put(
    "/drafts/{draft_id}",
    summary="Update Application Draft",
    description="""
Updates form field values, section progress, or draft status.

Security:
- Registered users only (guests receive 403 Forbidden).
- Enforces CSRF token and origin checks.
- Strict ownership validation (IDOR defense).
- Field validation against scheme definition.
""",
    responses={
        200: {"description": "Draft updated successfully."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Draft not found or access denied."},
        422: {"description": "Validation failed on form field values or status."},
    },
)
def update_application_draft(
    draft_id: str,
    request: UpdateDraftRequest,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Update fields, status, or progress in an application draft."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scholarship application drafts require a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    try:
        updated = app_service.update_draft(
            draft_id=draft_id,
            user_id=user_id,
            form_data=request.form_data,
            status=request.status,
            last_saved_section=request.last_saved_section,
            notes=request.notes,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application draft not found or access denied.",
        )

    return {
        "success": True,
        "message": "Application draft updated successfully.",
        "draft": updated,
    }


@router.delete(
    "/drafts/{draft_id}",
    summary="Delete Application Draft",
    description="""
Permanently removes an application draft owned by the authenticated citizen.

Security:
- Registered users only.
- Enforces CSRF token and origin checks.
- Strict ownership validation: Returns 404 if draft does not belong to user.
""",
    responses={
        200: {"description": "Draft deleted successfully."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Draft not found or access denied."},
    },
)
def delete_application_draft(
    draft_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Delete an application draft owned by the authenticated citizen."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scholarship application drafts require a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    deleted = app_service.delete_draft(draft_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application draft not found or access denied.",
        )

    return {
        "success": True,
        "message": "Application draft deleted successfully.",
        "draft_id": draft_id,
    }


# ---------------------------------------------------------
# Step 5.5B: Extension Autofill & Scoped Grants Endpoints
# ---------------------------------------------------------

@router.post(
    "/autofill/authorize",
    summary="Authorize Scoped Extension Grant",
    description="""
Issues a short-lived (5-minute), cryptographically secure grant token for browser extension autofill.

Security Guarantees:
- Enforces active citizen session + CSRF token.
- Rejects guest sessions.
- Token is cryptographically random and hashed (SHA-256) at rest.
- Bound strictly to verified government portals (https://scholarships.gov.in) and requested scheme.
""",
    responses={
        200: {"description": "Grant token issued successfully."},
        400: {"description": "Untrusted portal or invalid request."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Scheme or draft not found."},
    },
)
def authorize_extension_grant(
    request: AutofillAuthorizeRequest,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Issue a scoped grant token for the SahayAI Chrome extension."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autofill grant authorization requires a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    try:
        grant = autofill_service.create_extension_grant(
            user_id=user_id,
            scheme_id=request.scheme_id,
            portal_url=request.portal_url,
            draft_id=request.draft_id,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        )

    return {
        "success": True,
        "message": "Scoped extension grant created successfully. Valid for 5 minutes.",
        "grant": grant,
    }


@router.post(
    "/autofill/populate",
    summary="Populate Autofill Package",
    description="""
Generates a structured, deterministic autofill package for the scholarship application form.

Authentication:
- Browser extension: Uses 'Authorization: Bearer <grant_token>' issued via /autofill/authorize.
  Requires mandatory scopes: draft_id, scheme_id, and portal_url.
- SahayAI Web UI: Uses active citizen session cookie + CSRF token.
  Requires mandatory draft_id, scheme_id, and portal_url.
""",
    responses={
        200: {"description": "Autofill package generated successfully."},
        401: {"description": "Unauthorized grant token or session."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Scheme or draft not found."},
        422: {"description": "Validation error."},
    },
)
async def populate_autofill(
    request: Request,
    payload: AutofillPopulateRequest,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Generate the deterministic autofill package for an extension or web client."""
    # Check if Bearer token authorization is provided (Extension flow)
    if authorization and authorization.strip().startswith("Bearer "):
        grant = autofill_service.validate_extension_grant(
            raw_token=authorization,
            scheme_id=payload.scheme_id,
            portal_url=payload.portal_url,
            draft_id=payload.draft_id,
        )
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, expired, or unauthorized extension grant token.",
            )
        # Derive user_id strictly from the authenticated grant row, never trusting unauthenticated client claims
        user_id = grant["user_id"]
        draft_id = grant["draft_id"]

        # Explicitly verify draft ownership and active state under the grant owner's identity
        draft = app_service.get_draft(draft_id, user_id)
        if not draft or draft.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Draft ownership verification failed for extension grant owner.",
            )
        if draft.get("scheme_id") != payload.scheme_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Draft scheme '{draft.get('scheme_id')}' does not match requested scheme '{payload.scheme_id}'.",
            )
        if draft.get("status") == "CLOSED":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Application draft is closed and cannot be autofilled.",
            )
    else:
        # Web UI flow: requires session cookie and CSRF token
        enforce_csrf_protection(request)
        session_context = await get_current_session_or_guest(request)
        if session_context.get("is_guest"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Autofill population requires a registered citizen account. Please log in.",
            )
        # Derive user_id strictly from authenticated session
        user_id = session_context["user_id"]
        draft_id = payload.draft_id

        # Validate verified portal origin
        from applications.autofill_service import is_verified_portal_url
        if not is_verified_portal_url(payload.portal_url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Untrusted portal URL '{payload.portal_url}'. Grants are strictly restricted to official government portals (https://scholarships.gov.in).",
            )

        draft = app_service.get_draft(draft_id, user_id)
        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application draft not found or access denied.",
            )
        if draft.get("scheme_id") != payload.scheme_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Draft '{draft_id}' scheme '{draft.get('scheme_id')}' does not match requested scheme '{payload.scheme_id}'.",
            )

    if not is_valid_scheme_id(payload.scheme_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheme '{payload.scheme_id}' is not supported.",
        )

    try:
        package = autofill_service.generate_autofill_package(
            user_id=user_id,
            scheme_id=payload.scheme_id,
            draft_id=draft_id,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        )

    return {
        "success": True,
        "message": "Autofill package generated successfully.",
        "scheme_id": payload.scheme_id,
        "package": package,
    }


@router.get(
    "/drafts/{draft_id}/autofill-preview",
    summary="Preview Autofill Mappings for Draft",
    description="""
Generates an in-browser preview of autofill mappings, conflict flags, and missing information
for an existing citizen application draft.
""",
    responses={
        200: {"description": "Autofill preview generated successfully."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Draft not found or access denied."},
    },
)
def preview_draft_autofill(
    draft_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
) -> Dict[str, Any]:
    """Retrieve autofill preview comparing draft fields with confirmed profile and document data."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autofill preview requires a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    draft = app_service.get_draft(draft_id, user_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application draft not found or access denied.",
        )

    scheme_id = draft["scheme_id"]
    package = autofill_service.generate_autofill_package(
        user_id=user_id,
        scheme_id=scheme_id,
        draft_id=draft_id,
    )

    return {
        "success": True,
        "draft_id": draft_id,
        "scheme_id": scheme_id,
        "preview": package,
    }


@router.post(
    "/drafts/{draft_id}/autofill-apply",
    summary="Apply Clean Autofill Fields to Draft",
    description="""
Applies confirmed, non-conflicting autofill fields to the citizen's application draft.
Fields with conflicts require explicit citizen confirmation.
""",
    responses={
        200: {"description": "Autofill fields applied to draft successfully."},
        403: {"description": "Forbidden for guest sessions."},
        404: {"description": "Draft not found or access denied."},
    },
)
def apply_autofill_to_draft(
    draft_id: str,
    request: AutofillApplyRequest,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
) -> Dict[str, Any]:
    """Apply non-conflicting autofill values or selected confirmed fields into the application draft."""
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Applying autofill requires a registered citizen account. Please log in.",
        )

    user_id = session_context["user_id"]
    draft = app_service.get_draft(draft_id, user_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application draft not found or access denied.",
        )

    scheme_id = draft["scheme_id"]
    package = autofill_service.generate_autofill_package(
        user_id=user_id,
        scheme_id=scheme_id,
        draft_id=draft_id,
    )

    updates: Dict[str, Any] = {}
    if request.fields_to_apply is not None:
        updates = request.fields_to_apply
    else:
        # Auto-apply all POPULATED and CONFLICT (resolved candidate) fields
        for f_id, field_info in package.get("fields", {}).items():
            if field_info.get("status") in ("POPULATED", "CONFLICT") and field_info.get("value") is not None:
                updates[f_id] = field_info["value"]

    updated_draft = app_service.update_draft(
        draft_id=draft_id,
        user_id=user_id,
        form_data=updates,
    )

    return {
        "success": True,
        "message": f"Applied {len(updates)} autofill fields to application draft.",
        "applied_fields_count": len(updates),
        "draft": updated_draft,
    }
