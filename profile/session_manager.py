"""Server-side session management for SahayAI.

Handles cryptographically random session token generation, persistence in SQLite,
session validation, expiration enforcement, and revocation during logout.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re
import secrets
from typing import Any, Dict, List, Optional

from .database import Database

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS = 86400  # 24 hours
MIN_SESSION_ID_LENGTH = 32
MAX_SESSION_ID_LENGTH = 128


class SessionManager:
    """Manages server-side authenticated user sessions."""

    def __init__(
        self,
        db: Optional[Database] = None,
        default_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ):
        """Initialize SessionManager with a database connection.

        Args:
            db: Optional Database instance.
            default_ttl_seconds: Default session lifetime in seconds (default: 86400).
        """
        self.db = db or Database()
        self.default_ttl_seconds = default_ttl_seconds

    @staticmethod
    def _is_valid_session_id_format(session_id: Any) -> bool:
        """Validate that the session ID is a string with expected length and characters."""
        if not isinstance(session_id, str):
            return False
        if not (MIN_SESSION_ID_LENGTH <= len(session_id) <= MAX_SESSION_ID_LENGTH):
            return False
        # Base64url / hex characters only (safe against injection and tampering)
        return bool(re.fullmatch(r"[A-Za-z0-9_-]+", session_id))

    @staticmethod
    def _hash_session_id(session_id: str) -> str:
        """Compute SHA-256 digest of session ID for database storage and lookup.

        Raw session tokens are never stored in SQLite to prevent session hijacking
        in case of database snapshot leaks.
        """
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def create_session(
        self,
        user_id: str,
        ttl_seconds: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and persist a new authenticated session for a user.

        Args:
            user_id: The authenticated user's ID.
            ttl_seconds: Optional custom TTL in seconds. Defaults to default_ttl_seconds.
            ip_address: Optional client IP address for audit logging.
            user_agent: Optional client user-agent string for audit logging.

        Returns:
            Dictionary containing the created session details with raw session_id for the cookie.

        Raises:
            ValueError: If user_id is invalid or user does not exist/is inactive.
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError("A valid user_id is required to create a session.")

        # Verify that the user exists and is active
        with self.db.get_connection() as conn:
            user_row = conn.execute(
                "SELECT user_id, account_status FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if not user_row:
            raise ValueError(f"User account '{user_id}' does not exist.")

        if user_row["account_status"] != "ACTIVE":
            raise ValueError(f"Cannot create session: account '{user_id}' is not ACTIVE.")

        ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self.default_ttl_seconds
        now_dt = datetime.now(timezone.utc)
        expires_dt = now_dt + timedelta(seconds=ttl)

        # Generate cryptographically secure raw session identifier (256 bits of entropy)
        raw_session_id = secrets.token_urlsafe(32)
        session_hash = self._hash_session_id(raw_session_id)

        created_at_iso = now_dt.isoformat()
        expires_at_iso = expires_dt.isoformat()

        session_record = {
            "session_id": session_hash,  # Store SHA-256 digest in database, never raw token
            "user_id": user_id,
            "created_at": created_at_iso,
            "expires_at": expires_at_iso,
            "revoked_at": None,
            "ip_address": ip_address,
            "user_agent": user_agent[:255] if user_agent else None,
        }

        query = """
            INSERT INTO user_sessions (
                session_id, user_id, created_at, expires_at, revoked_at, ip_address, user_agent
            ) VALUES (
                :session_id, :user_id, :created_at, :expires_at, :revoked_at, :ip_address, :user_agent
            )
        """

        with self.db.get_connection() as conn:
            conn.execute(query, session_record)

        # Opportunistic cleanup: roughly 1 in 50 creations cleans up expired sessions
        if secrets.randbelow(50) == 0:
            try:
                self.cleanup_expired_sessions()
            except Exception as exc:
                logger.debug("Opportunistic cleanup error: %s", exc)

        logger.info("Session created for user_id=%s, expires_at=%s", user_id, expires_at_iso)

        return {
            "session_id": raw_session_id,  # Send raw token to caller for HttpOnly cookie
            "user_id": user_id,
            "created_at": created_at_iso,
            "expires_at": expires_at_iso,
            "is_active": True,
        }

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session record by hashing the incoming session token.

        Args:
            session_id: The raw session ID string.

        Returns:
            Dictionary of session fields or None if not found or format is invalid.
        """
        if not self._is_valid_session_id_format(session_id):
            return None

        session_hash = self._hash_session_id(session_id)
        query = "SELECT * FROM user_sessions WHERE session_id = ?"

        with self.db.get_connection() as conn:
            row = conn.execute(query, (session_hash,)).fetchone()

        if not row:
            return None

        return dict(row)

    def validate_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Validate an existing session ID.

        Checks:
        1. Format integrity.
        2. Existence in database.
        3. Revocation status (`revoked_at IS NULL`).
        4. Expiration (`now < expires_at`).

        Args:
            session_id: The session ID string.

        Returns:
            Session record dict if valid, or None if invalid/expired/revoked.
        """
        session = self.get_session(session_id)
        if not session:
            return None

        # Check revocation
        if session.get("revoked_at") is not None:
            logger.debug("Session %s is revoked.", session_id[:8])
            return None

        # Check expiration
        try:
            expires_at = datetime.fromisoformat(session["expires_at"])
            now = datetime.now(timezone.utc)
            if now >= expires_at:
                logger.debug("Session %s has expired.", session_id[:8])
                return None
        except (ValueError, TypeError) as exc:
            logger.warning("Session %s has invalid timestamp: %s", session_id[:8], exc)
            return None

        return session

    def revoke_session(self, session_id: str) -> bool:
        """Revoke a session (logout).

        Args:
            session_id: The raw session ID to invalidate.

        Returns:
            True if an active session was revoked, False otherwise.
        """
        if not self._is_valid_session_id_format(session_id):
            return False

        session_hash = self._hash_session_id(session_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            UPDATE user_sessions
            SET revoked_at = ?
            WHERE session_id = ? AND revoked_at IS NULL
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (now_iso, session_hash))
            revoked = cursor.rowcount > 0

        if revoked:
            logger.info("Session revoked successfully.")
        return revoked

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user (e.g. on password change or security alert).

        Args:
            user_id: The user whose sessions should be invalidated.

        Returns:
            Count of revoked sessions.
        """
        if not user_id:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            UPDATE user_sessions
            SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (now_iso, user_id))
            count = cursor.rowcount

        logger.info("Revoked %d sessions for user_id=%s", count, user_id)
        return count

    def cleanup_expired_sessions(self) -> int:
        """Purge expired and revoked sessions older than their retention window.

        Cleans up both registered user sessions and temporary guest sessions.

        Returns:
            Count of deleted session rows across all session tables.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        user_query = """
            DELETE FROM user_sessions
            WHERE expires_at <= ?
               OR (revoked_at IS NOT NULL AND revoked_at <= ?)
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(user_query, (now_iso, now_iso))
            count_user = cursor.rowcount

        count_guest = self.cleanup_expired_guest_sessions()
        total_cleaned = count_user + count_guest

        logger.info(
            "Cleaned up %d expired/revoked sessions (%d user, %d guest).",
            total_cleaned,
            count_user,
            count_guest,
        )
        return total_cleaned

    # ---------------------------------------------------------------------------
    # Guest Sessions (Phase 7: Temporary & Privacy-Preserving Sessions)
    # ---------------------------------------------------------------------------

    def create_guest_session(
        self,
        ttl_seconds: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create and persist a new temporary guest session.

        Guarantees:
        - Cryptographically random session ID with 256 bits of entropy.
        - Only SHA-256 digest is stored in SQLite (never raw session token).
        - Generates isolated guest_id (never references users or profiles).
        - Supports temporary in-session context (e.g. preliminary eligibility inputs).
        - Guest data never converts automatically to persistent citizen records.

        Args:
            ttl_seconds: Custom lifetime in seconds (defaults to default_ttl_seconds, 24h).
            ip_address: Optional client IP address.
            user_agent: Optional client user agent.
            initial_context: Optional initial in-memory context dictionary.

        Returns:
            Dictionary with raw session_id for HttpOnly cookie, guest_id, and metadata.
        """
        ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self.default_ttl_seconds
        now_dt = datetime.now(timezone.utc)
        expires_dt = now_dt + timedelta(seconds=ttl)

        raw_session_id = f"gst_{secrets.token_urlsafe(32)}"
        session_hash = self._hash_session_id(raw_session_id)
        guest_id = f"guest_{secrets.token_hex(12)}"

        created_at_iso = now_dt.isoformat()
        expires_at_iso = expires_dt.isoformat()
        context_str = json.dumps(initial_context or {})

        record = {
            "session_id": session_hash,
            "guest_id": guest_id,
            "created_at": created_at_iso,
            "expires_at": expires_at_iso,
            "revoked_at": None,
            "last_active_at": created_at_iso,
            "ip_address": ip_address,
            "user_agent": user_agent[:255] if user_agent else None,
            "context_json": context_str,
        }

        query = """
            INSERT INTO guest_sessions (
                session_id, guest_id, created_at, expires_at, revoked_at,
                last_active_at, ip_address, user_agent, context_json
            ) VALUES (
                :session_id, :guest_id, :created_at, :expires_at, :revoked_at,
                :last_active_at, :ip_address, :user_agent, :context_json
            )
        """

        with self.db.get_connection() as conn:
            conn.execute(query, record)

        logger.info("Guest session created: guest_id=%s, expires_at=%s", guest_id, expires_at_iso)

        return {
            "session_id": raw_session_id,
            "guest_id": guest_id,
            "is_guest": True,
            "created_at": created_at_iso,
            "expires_at": expires_at_iso,
            "context": initial_context or {},
        }

    def get_guest_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a guest session record by raw session token.

        Args:
            session_id: Raw session token from cookie.

        Returns:
            Dict of guest session details or None if not found/invalid.
        """
        if not self._is_valid_session_id_format(session_id):
            return None

        session_hash = self._hash_session_id(session_id)
        query = "SELECT * FROM guest_sessions WHERE session_id = ?"

        with self.db.get_connection() as conn:
            row = conn.execute(query, (session_hash,)).fetchone()

        if not row:
            return None

        res = dict(row)
        res["is_guest"] = True
        try:
            res["context"] = json.loads(res.get("context_json") or "{}")
        except Exception:
            res["context"] = {}
        return res

    def validate_guest_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Validate an existing guest session ID.

        Checks format, database presence, revocation, and expiration.
        Updates last_active_at on success.

        Returns:
            Guest session record dict if valid, None otherwise.
        """
        session = self.get_guest_session(session_id)
        if not session:
            return None

        if session.get("revoked_at") is not None:
            logger.debug("Guest session %s is revoked.", session_id[:8])
            return None

        try:
            expires_at = datetime.fromisoformat(session["expires_at"])
            now = datetime.now(timezone.utc)
            if now >= expires_at:
                logger.debug("Guest session %s has expired.", session_id[:8])
                return None
        except (ValueError, TypeError) as exc:
            logger.warning("Guest session %s has invalid timestamp: %s", session_id[:8], exc)
            return None

        # Touch last_active_at
        now_iso = datetime.now(timezone.utc).isoformat()
        session_hash = self._hash_session_id(session_id)
        update_query = "UPDATE guest_sessions SET last_active_at = ? WHERE session_id = ?"

        try:
            with self.db.get_connection() as conn:
                conn.execute(update_query, (now_iso, session_hash))
        except Exception as exc:
            logger.debug("Could not touch guest last_active_at: %s", exc)

        return session

    def update_guest_context(
        self,
        session_id: str,
        context: Dict[str, Any],
        max_bytes: int = 65536,
    ) -> bool:
        """Update temporary session context (e.g. preliminary eligibility inputs).

        Enforces size limits (max 64KB) to prevent storage abuse.

        Args:
            session_id: The raw guest session token.
            context: Context dictionary to persist in session.
            max_bytes: Maximum allowed JSON string size in bytes (default: 64KB).

        Returns:
            True if updated successfully.

        Raises:
            ValueError: If payload exceeds max_bytes or session is invalid.
        """
        session = self.validate_guest_session(session_id)
        if not session:
            raise ValueError("Invalid or expired guest session.")

        context_str = json.dumps(context)
        if len(context_str.encode("utf-8")) > max_bytes:
            raise ValueError(f"Temporary context payload exceeds {max_bytes} bytes limit.")

        session_hash = self._hash_session_id(session_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            UPDATE guest_sessions
            SET context_json = ?, last_active_at = ?
            WHERE session_id = ? AND revoked_at IS NULL
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (context_str, now_iso, session_hash))
            return cursor.rowcount > 0

    def revoke_guest_session(self, session_id: str) -> bool:
        """Revoke a guest session (exit guest mode).

        Args:
            session_id: The raw guest session token.

        Returns:
            True if revoked, False otherwise.
        """
        if not self._is_valid_session_id_format(session_id):
            return False

        session_hash = self._hash_session_id(session_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            UPDATE guest_sessions
            SET revoked_at = ?
            WHERE session_id = ? AND revoked_at IS NULL
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (now_iso, session_hash))
            revoked = cursor.rowcount > 0

        if revoked:
            logger.info("Guest session revoked successfully.")
        return revoked

    def cleanup_expired_guest_sessions(self) -> int:
        """Purge expired and revoked guest sessions from SQLite.

        Returns:
            Count of deleted guest session rows.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            DELETE FROM guest_sessions
            WHERE expires_at <= ?
               OR (revoked_at IS NOT NULL AND revoked_at <= ?)
        """

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (now_iso, now_iso))
            count = cursor.rowcount

        logger.info("Cleaned up %d expired/revoked guest sessions.", count)
        return count

