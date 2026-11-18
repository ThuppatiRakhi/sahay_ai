"""Authentication and session security foundation for SahayAI API.

Provides:
- Server-side session configuration with environment variable validation.
- FastAPI dependency `get_current_active_user` for cookie-based authentication.
- Secure HttpOnly cookie setters and clearers with environment-aware flags.
- CSRF origin and token validation helpers for state-changing requests.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import Cookie, HTTPException, Request, Response, status

from profile.database import Database
from profile.session_manager import SessionManager

logger = logging.getLogger(__name__)

# Default trusted origins for local development
DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5501",
    "http://localhost:5501",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]


@dataclass
class SessionConfig:
    """Session and cookie security settings loaded from environment."""

    app_env: str
    cookie_name: str
    csrf_cookie_name: str
    ttl_seconds: int
    cookie_secure: bool
    cookie_samesite: str
    secret_key: str

    @classmethod
    def from_env(cls) -> "SessionConfig":
        """Load session configuration from environment variables."""
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        cookie_name = os.getenv("SESSION_COOKIE_NAME", "sahay_session").strip()
        csrf_cookie_name = os.getenv("CSRF_COOKIE_NAME", "sahay_csrf").strip()

        try:
            ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
        except ValueError:
            ttl_seconds = 86400

        # In production, cookies MUST be secure (HTTPS only).
        # In development/testing, default to False unless explicitly enabled.
        secure_env = os.getenv("SESSION_COOKIE_SECURE", "").strip().lower()
        if secure_env in ("true", "1", "yes"):
            cookie_secure = True
        elif secure_env in ("false", "0", "no"):
            cookie_secure = False
        else:
            cookie_secure = (app_env == "production")

        cookie_samesite = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
        if cookie_samesite not in ("lax", "strict", "none"):
            cookie_samesite = "lax"

        secret_key = os.getenv("SESSION_SECRET_KEY", "").strip()

        # In development/testing, auto-generate a transient key if none provided
        if not secret_key and app_env != "production":
            secret_key = secrets.token_hex(32)

        config = cls(
            app_env=app_env,
            cookie_name=cookie_name,
            csrf_cookie_name=csrf_cookie_name,
            ttl_seconds=ttl_seconds,
            cookie_secure=cookie_secure,
            cookie_samesite=cookie_samesite,
            secret_key=secret_key,
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Validate production configuration to prevent insecure deployments."""
        if self.app_env == "production":
            if not self.cookie_secure:
                raise RuntimeError(
                    "Insecure configuration: SESSION_COOKIE_SECURE must be True in production."
                )
            insecure_placeholders = ("change_me", "placeholder", "default_secret", "replace_me")
            if (
                not self.secret_key
                or len(self.secret_key) < 32
                or any(ph in self.secret_key.lower() for ph in insecure_placeholders)
            ):
                raise RuntimeError(
                    "Insecure configuration: SESSION_SECRET_KEY must be a cryptographically secure "
                    "random secret of at least 32 characters in production."
                )


_config_instance: Optional[SessionConfig] = None


def get_session_config() -> SessionConfig:
    """Retrieve or initialize the active SessionConfig singleton."""
    global _config_instance
    if _config_instance is None:
        _config_instance = SessionConfig.from_env()
    return _config_instance


def reset_session_config() -> None:
    """Reset cached config (primarily for unit tests switching environments)."""
    global _config_instance
    _config_instance = None


def set_session_cookie(
    response: Response,
    session_id: str,
    ttl_seconds: Optional[int] = None,
    config: Optional[SessionConfig] = None,
) -> None:
    """Attach an HttpOnly, environment-appropriate session cookie to a FastAPI Response.

    Args:
        response: FastAPI Response object.
        session_id: The random session identifier.
        ttl_seconds: Optional custom max_age in seconds.
        config: Optional SessionConfig instance.
    """
    cfg = config or get_session_config()
    max_age = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else cfg.ttl_seconds

    response.set_cookie(
        key=cfg.cookie_name,
        value=session_id,
        max_age=max_age,
        expires=max_age,
        path="/",
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
    )


def clear_session_cookie(
    response: Response,
    config: Optional[SessionConfig] = None,
) -> None:
    """Invalidate and remove the session cookie from the client browser.

    Args:
        response: FastAPI Response object.
        config: Optional SessionConfig instance.
    """
    cfg = config or get_session_config()
    response.delete_cookie(
        key=cfg.cookie_name,
        path="/",
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
    )


def set_csrf_cookie(
    response: Response,
    session_id: str,
    ttl_seconds: Optional[int] = None,
    config: Optional[SessionConfig] = None,
) -> str:
    """Attach a client-readable CSRF token cookie to a FastAPI Response.

    Security properties:
    - HttpOnly=False: Intentionally readable by client-side JavaScript so frontend
      code can read this value and include it in the 'X-CSRF-Token' request header.
    - Secure=cookie_secure: Enforces HTTPS transmission in production.
    - SameSite=cookie_samesite: Matches session cookie SameSite policy (lax by default).
    - Value: Stateless HMAC-SHA256 digest of raw session_id with SESSION_SECRET_KEY.
      The raw session ID is NEVER exposed; only the derived token is set.

    Returns:
        The generated CSRF token string.
    """
    cfg = config or get_session_config()
    max_age = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else cfg.ttl_seconds
    csrf_token = generate_csrf_token(session_id, config=cfg)

    response.set_cookie(
        key=cfg.csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        expires=max_age,
        path="/",
        httponly=False,  # Client JS reads this cookie
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
    )
    return csrf_token


def clear_csrf_cookie(
    response: Response,
    config: Optional[SessionConfig] = None,
) -> None:
    """Remove the CSRF token cookie from the client browser."""
    cfg = config or get_session_config()
    response.delete_cookie(
        key=cfg.csrf_cookie_name,
        path="/",
        httponly=False,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
    )


def generate_csrf_token(session_id: str, config: Optional[SessionConfig] = None) -> str:
    """Generate a stateless, HMAC-SHA256 CSRF token tied to the session ID."""
    cfg = config or get_session_config()
    secret_bytes = cfg.secret_key.encode("utf-8")
    return hmac.new(secret_bytes, session_id.encode("utf-8"), hashlib.sha256).hexdigest()


def validate_csrf_token(session_id: str, token: str, config: Optional[SessionConfig] = None) -> bool:
    """Validate a CSRF token against the session ID in constant time."""
    if not token or not session_id:
        return False
    expected = generate_csrf_token(session_id, config=config)
    return hmac.compare_digest(expected, token)


def verify_csrf_origin(
    request: Request,
    allowed_origins: Optional[List[str]] = None,
) -> None:
    """Validate Origin/Referer headers on state-changing HTTP requests.

    Protects against Cross-Site Request Forgery (CSRF) for cookie-authenticated endpoints.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    origins = allowed_origins or DEFAULT_ALLOWED_ORIGINS

    # 1. Check Origin header
    origin = request.headers.get("origin")
    if origin:
        if origin in origins:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"CSRF protection: request origin '{origin}' is not authorized.",
        )

    # 2. Check Referer header if Origin is absent
    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}"
        if referer_origin in origins:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"CSRF protection: request referer '{referer_origin}' is not authorized.",
        )

    # In development, missing Origin/Referer from local scripts/curl is permitted
    cfg = get_session_config()
    if cfg.app_env == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF protection: Origin or Referer header required for state-changing requests.",
        )


def enforce_csrf_protection(request: Request) -> None:
    """FastAPI dependency to strictly enforce CSRF origin and token validation.

    Rules:
    - Safe methods (GET, HEAD, OPTIONS): Permitted without CSRF check.
    - State-changing methods (POST, PUT, DELETE, PATCH):
      1. Origin or Referer header must match authorized frontend origins.
      2. If a session cookie is present:
         a. The session must be active, unexpired and unrevoked in SQLite.
            Expired or revoked sessions are rejected with HTTP 401.
         b. An 'X-CSRF-Token' header is mandatory.
         c. The CSRF token must match the HMAC-SHA256 digest of the active session token
            using constant-time comparison (hmac.compare_digest).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # 1. Enforce Origin/Referer check
    verify_csrf_origin(request)

    # 2. If cookie-authenticated, validate session and enforce CSRF token header
    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)
    if session_id:
        # Verify the session is still active and valid in the database (registered or guest)
        session_mgr = SessionManager()
        session = session_mgr.validate_session(session_id) or session_mgr.validate_guest_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication session is invalid, expired, or revoked.",
            )

        csrf_token = request.headers.get("x-csrf-token")
        if not csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing from request headers (X-CSRF-Token).",
            )
        if not validate_csrf_token(session_id, csrf_token, config=cfg):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token validation failed: token is invalid or does not match active session.",
            )


async def get_current_active_user(
    request: Request,
) -> Dict[str, Any]:
    """FastAPI dependency: Resolves the authenticated, active user from the session cookie.

    Steps:
    1. Reads session ID from the configured HttpOnly cookie.
    2. Validates session existence, expiration, and revocation status in SQLite.
    3. Retrieves the user account from the `users` table.
    4. Enforces that account_status is strictly 'ACTIVE'.
    5. Returns public user record (without password_hash).

    Never accepts or trusts any user ID passed in request headers, query params, or body.

    Raises:
        HTTPException(401): If cookie is missing, invalid, expired, revoked, or account is disabled.
    """
    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication session cookie missing. Please sign in.",
        )

    # Retrieve session manager (using default database)
    session_mgr = SessionManager()
    session = session_mgr.validate_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired or revoked authentication session.",
        )

    # Fetch user account from database using server-side session user_id
    user_id = session["user_id"]
    with session_mgr.db.get_connection() as conn:
        user_row = conn.execute(
            """
            SELECT user_id, email, phone, account_status, created_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user account not found.",
        )

    if user_row["account_status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or disabled.",
        )

    return {
        "user_id": user_row["user_id"],
        "email": user_row["email"],
        "phone": user_row["phone"],
        "account_status": user_row["account_status"],
        "created_at": user_row["created_at"],
    }


async def get_current_session_or_guest(
    request: Request,
) -> Dict[str, Any]:
    """FastAPI dependency: Resolves active session for either registered user or temporary guest.

    Returns:
        For registered user:
            {"is_guest": False, "user_id": str, "email": Optional[str], "session": dict}
        For temporary guest:
            {"is_guest": True, "guest_id": str, "session": dict, "context": dict}

    Raises:
        HTTPException(401): If session cookie is missing, expired, revoked, or invalid.
    """
    cfg = get_session_config()
    session_id = request.cookies.get(cfg.cookie_name)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session cookie missing. Please sign in or continue as guest.",
        )

    session_mgr = SessionManager()

    # 1. Check if registered user session
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
                "is_guest": False,
                "user_id": user_row["user_id"],
                "email": user_row["email"],
                "phone": user_row["phone"],
                "session": user_session,
            }

    # 2. Check if temporary guest session
    guest_session = session_mgr.validate_guest_session(session_id)
    if guest_session:
        return {
            "is_guest": True,
            "guest_id": guest_session["guest_id"],
            "session": guest_session,
            "context": guest_session.get("context", {}),
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid, expired or revoked session.",
    )


async def get_optional_session_context(
    request: Request,
) -> Optional[Dict[str, Any]]:
    """FastAPI dependency: Resolves active session if present; returns None if absent/expired.

    Never raises 401. Ideal for public scheme browsing with optional personalization.
    """
    try:
        return await get_current_session_or_guest(request)
    except HTTPException:
        return None

