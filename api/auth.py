"""Authentication API routes for SahayAI."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from api.security import (
    clear_csrf_cookie,
    clear_session_cookie,
    enforce_csrf_protection,
    generate_csrf_token,
    get_current_session_or_guest,
    get_session_config,
    set_csrf_cookie,
    set_session_cookie,
)
from profile.auth_service import AuthService
from profile.session_manager import SessionManager


router = APIRouter(prefix="/auth", tags=["Authentication"])

auth_service = AuthService()


class SignupRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class GuestContextUpdateRequest(BaseModel):
    temporary_profile: Optional[Dict[str, Any]] = None
    conversation_state: Optional[Dict[str, Any]] = None


@router.post("/signup")
def signup(request: SignupRequest, response: Response):
    """Register a new citizen account and initialize an authenticated session.

    Security properties:
    - Scrypt password hashing is preserved in AccountManager.
    - Duplicate email/phone registrations are rejected with HTTP 409 Conflict.
    - Creates a server-side session record in SQLite upon successful registration.
    - Sets an HttpOnly, SameSite, Secure (in production) session cookie.
    - The raw session ID is NEVER returned in the JSON response body.
    - Client can subsequently call GET /auth/csrf-token with the session cookie.
    """
    try:
        result = auth_service.signup(
            email=request.email,
            phone=request.phone,
            password=request.password,
        )

        user = result.get("user")
        if user and user.get("user_id"):
            session_mgr = SessionManager()
            session = session_mgr.create_session(user_id=user["user_id"])
            set_session_cookie(response, session["session_id"])

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


@router.post("/login")
def login(request: LoginRequest, response: Response):
    """Authenticate citizen credentials and issue a new authenticated session.

    Security properties:
    - Validates credentials via AuthService and scrypt hash verification.
    - Rejects invalid credentials with HTTP 401 Unauthorized.
    - Rejects inactive or disabled accounts with HTTP 401 Unauthorized.
    - Creates exactly one new server-side session in SQLite.
    - Sets an HttpOnly, SameSite, Secure (in production) session cookie.
    - The raw session ID is NEVER returned in the JSON response body.
    - Preserves profile_required and next_step flow indicators.
    """
    result = auth_service.login(
        identifier=request.identifier,
        password=request.password,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/phone or password.",
        )

    user = result.get("user")
    if not user or user.get("account_status") != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled or inactive.",
        )

    session_mgr = SessionManager()
    session = session_mgr.create_session(user_id=user["user_id"])
    set_session_cookie(response, session["session_id"])

    return result


@router.post("/guest")
def initialize_guest_session(request: Request, response: Response):
    """Initialize a temporary, privacy-preserving guest session.

    Guarantees:
    - No compulsory account creation.
    - Generates 256-bit cryptographically secure session identifier.
    - Only SHA-256 hash stored in SQLite guest_sessions table.
    - Sets HttpOnly, SameSite, Secure (in prod) cookie.
    - Issues client-readable CSRF token cookie for protected state-changing calls.
    - Raw session ID is NEVER returned in response body.
    - Never creates a record in registered users or persistent profiles.
    """
    cfg = get_session_config()
    session_mgr = SessionManager()

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    session = session_mgr.create_guest_session(
        ip_address=ip_address,
        user_agent=user_agent,
    )

    set_session_cookie(response, session["session_id"], config=cfg)
    csrf_token = set_csrf_cookie(response, session["session_id"], config=cfg)

    return {
        "success": True,
        "is_guest": True,
        "guest_id": session["guest_id"],
        "csrf_token": csrf_token,
        "expires_at": session["expires_at"],
        "message": "Guest session initialized successfully.",
        "next_step": "DASHBOARD",
    }


@router.get("/session-status")
def get_session_status(request: Request, response: Response):
    """Retrieve the authentication and guest status of the current browser session."""
    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)

    if not session_id:
        return {
            "success": True,
            "authenticated": False,
            "is_guest": False,
        }

    session_mgr = SessionManager()

    # 1. Registered user session check
    user_session = session_mgr.validate_session(session_id)
    if user_session:
        user_id = user_session["user_id"]
        with session_mgr.db.get_connection() as conn:
            user_row = conn.execute(
                "SELECT user_id, email, phone, account_status FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if user_row and user_row["account_status"] == "ACTIVE":
            return {
                "success": True,
                "authenticated": True,
                "is_guest": False,
                "user_id": user_row["user_id"],
                "email": user_row["email"],
                "phone": user_row["phone"],
                "expires_at": user_session["expires_at"],
            }

    # 2. Temporary guest session check
    guest_session = session_mgr.validate_guest_session(session_id)
    if guest_session:
        return {
            "success": True,
            "authenticated": True,
            "is_guest": True,
            "guest_id": guest_session["guest_id"],
            "expires_at": guest_session["expires_at"],
            "context": guest_session.get("context", {}),
        }

    # The session cookie was provided but is invalid, revoked, or expired: clear cookies
    clear_session_cookie(response, config=cfg)
    clear_csrf_cookie(response, config=cfg)

    return {
        "success": True,
        "authenticated": False,
        "is_guest": False,
    }


@router.get("/guest/context")
def get_guest_context(
    current_session: dict = Depends(get_current_session_or_guest),
):
    """Retrieve the temporary session context (preliminary demographic details, etc.) for a guest."""
    if not current_session.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current session is not a guest session.",
        )

    return {
        "success": True,
        "guest_id": current_session["guest_id"],
        "context": current_session.get("context", {}),
    }


@router.post("/guest/context")
def update_guest_context(
    body: GuestContextUpdateRequest,
    request: Request,
    current_session: dict = Depends(get_current_session_or_guest),
    _csrf=Depends(enforce_csrf_protection),
):
    """Update temporary in-session citizen information for preliminary eligibility checks.

    Security & Privacy properties:
    - Strictly bound to active guest session (isolated from other guests).
    - Data is stored in SQLite guest_sessions.context_json (NOT persistent profiles table).
    - Enforces 64KB payload size limit to prevent memory/storage exhaustion.
    - Automatically purged when guest session expires or is revoked.
    """
    if not current_session.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current session is not a guest session.",
        )

    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)

    existing_context = current_session.get("context", {})
    if body.temporary_profile is not None:
        # Sanitize allowed profile fields
        allowed_fields = {
            "full_name", "age", "date_of_birth", "gender", "state", "district",
            "annual_income", "annual_family_income", "occupation", "caste_category",
            "social_category", "is_bpl", "class_12_merit_percentile",
            "pursuing_regular_course", "course_mode", "application_type"
        }
        sanitized_profile = {
            k: v for k, v in body.temporary_profile.items() if k in allowed_fields
        }
        existing_context["temporary_profile"] = sanitized_profile

    if body.conversation_state is not None:
        existing_context["conversation_state"] = body.conversation_state

    session_mgr = SessionManager()
    try:
        session_mgr.update_guest_context(session_id, existing_context)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return {
        "success": True,
        "guest_id": current_session["guest_id"],
        "message": "Temporary guest context updated.",
        "context": existing_context,
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    _csrf=Depends(enforce_csrf_protection),
):
    """Log out the current session (registered citizen or guest) and clear cookies.

    Security properties:
    - Enforces CSRF protection.
    - Requires an active, unexpired session cookie.
    - Revokes user_session or guest_session in SQLite.
    - Clears both 'sahay_session' and 'sahay_csrf' cookies.
    """
    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication session cookie missing. Please sign in.",
        )

    session_mgr = SessionManager()

    # Attempt registered session revocation
    user_session = session_mgr.validate_session(session_id)
    if user_session:
        session_mgr.revoke_session(session_id)
    else:
        # Attempt guest session revocation
        guest_session = session_mgr.validate_guest_session(session_id)
        if guest_session:
            session_mgr.revoke_guest_session(session_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication session is invalid, expired, or revoked.",
            )

    clear_session_cookie(response, config=cfg)
    clear_csrf_cookie(response, config=cfg)

    return {
        "success": True,
        "message": "Successfully logged out.",
    }


@router.get("/csrf-token")
def get_csrf_token_endpoint(request: Request, response: Response):
    """Safely issues a separate CSRF token for the active session (registered or guest).

    Security properties:
    - The raw session ID is NEVER sent to JavaScript.
    - Sets a separate, client-readable cookie ('sahay_csrf') with HttpOnly=False
      so browser scripts can read and attach it as the 'X-CSRF-Token' header.
    - The primary session cookie ('sahay_session') remains strictly HttpOnly=True.
    - Returns the derived CSRF token in the JSON body.
    - Rejects missing, invalid, expired or revoked sessions with HTTP 401.
    """
    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Active session required to obtain a CSRF token.",
        )

    session_mgr = SessionManager()
    session = session_mgr.validate_session(session_id) or session_mgr.validate_guest_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication session is invalid, expired, or revoked.",
        )

    csrf_token = set_csrf_cookie(response, session_id, config=cfg)

    return {
        "success": True,
        "csrf_token": csrf_token,
    }
