
"""Account registration and authentication for SahayAI."""

from datetime import datetime, timezone
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import uuid
from typing import Any, Dict, Optional

from .database import Database

logger = logging.getLogger(__name__)

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


class AccountManager:
    """Handles secure user registration and login."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    @staticmethod
    def _normalize_email(email: Optional[str]) -> Optional[str]:
        if email is None:
            return None

        email = email.strip().lower()
        if not email:
            return None

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Enter a valid email address.")

        return email

    @staticmethod
    def _normalize_phone(phone: Optional[str]) -> Optional[str]:
        if phone is None:
            return None

        phone = phone.strip()
        if not phone:
            return None

        # Permit spaces and hyphens in user input.
        phone = re.sub(r"[\s-]", "", phone)

        if not re.fullmatch(r"\+?[1-9]\d{6,14}", phone):
            raise ValueError("Enter a valid phone number with country code if needed.")

        return phone

    @staticmethod
    def _hash_password(password: str) -> str:
        if not isinstance(password, str) or len(password) < 8:
            raise ValueError("Password must contain at least 8 characters.")

        salt = secrets.token_bytes(16)

        password_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=SCRYPT_DKLEN,
        )

        return (
            f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
            f"{salt.hex()}${password_hash.hex()}"
        )

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        try:
            algorithm, n, r, p, salt_hex, hash_hex = stored_hash.split("$")

            if algorithm != "scrypt":
                return False

            salt = bytes.fromhex(salt_hex)
            expected_hash = bytes.fromhex(hash_hex)

            actual_hash = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(expected_hash),
            )

            return hmac.compare_digest(actual_hash, expected_hash)

        except (ValueError, TypeError, MemoryError):
            return False

    @staticmethod
    def _public_user(row: sqlite3.Row) -> Dict[str, Any]:
        """Return account details without exposing the password hash."""
        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "phone": row["phone"],
            "account_status": row["account_status"],
            "created_at": row["created_at"],
        }

    def register_user(
        self,
        password: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register an account using email, phone, or both."""

        email = self._normalize_email(email)
        phone = self._normalize_phone(phone)

        if not email and not phone:
            raise ValueError("Provide an email address or phone number.")

        password_hash = self._hash_password(password)

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        query = """
            INSERT INTO users (
                user_id, email, phone, password_hash,
                account_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)
        """

        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    query,
                    (user_id, email, phone, password_hash, now, now),
                )

                row = conn.execute(
                    "SELECT * FROM users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

            logger.info("Registered SahayAI account: %s", user_id)
            return self._public_user(row)

        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()

            if "email" in message:
                raise ValueError("This email address is already registered.") from exc

            if "phone" in message:
                raise ValueError("This phone number is already registered.") from exc

            raise ValueError("Account could not be registered.") from exc

    def login_user(
        self,
        identifier: str,
        password: str,
    ) -> Optional[Dict[str, Any]]:
        """Authenticate using either registered email or phone.

        Returns None when credentials are invalid or account is disabled.
        """

        if not isinstance(identifier, str) or not identifier.strip():
            return None

        if not isinstance(password, str) or not password:
            return None

        identifier = identifier.strip()

        if "@" in identifier:
            identifier = self._normalize_email(identifier)
        else:
            try:
                identifier = self._normalize_phone(identifier)
            except ValueError:
                return None

        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM users
                WHERE email = ? COLLATE NOCASE OR phone = ?
                """,
                (identifier, identifier),
            ).fetchone()

        if not row:
            return None

        if row["account_status"] != "ACTIVE":
            return None

        if not self._verify_password(password, row["password_hash"]):
            return None

        logger.info("Successful SahayAI login: %s", row["user_id"])
        return self._public_user(row)
