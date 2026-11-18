
"""Authentication workflow for SahayAI."""

import logging
import sqlite3
from typing import Any, Dict, Optional

from .account_manager import AccountManager
from .profile_manager import ProfileManager

logger = logging.getLogger(__name__)


class AuthService:
    """Coordinates account registration, login, and citizen profiles."""

    def __init__(
        self,
        account_manager: Optional[AccountManager] = None,
        profile_manager: Optional[ProfileManager] = None,
    ):
        self.accounts = account_manager or AccountManager()
        self.profiles = profile_manager or ProfileManager(
            db=self.accounts.db
        )

    def signup(
        self,
        password: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new account.

        The citizen profile is created separately after signup.
        """
        user = self.accounts.register_user(
            email=email,
            phone=phone,
            password=password,
        )

        logger.info("Signup completed for account: %s", user["user_id"])

        return {
            "success": True,
            "message": "Account created successfully.",
            "user": user,
            "profile_required": True,
            "next_step": "CREATE_PROFILE",
        }

    def login(
        self,
        identifier: str,
        password: str,
    ) -> Dict[str, Any]:
        """Authenticate a user and retrieve their existing profile."""

        user = self.accounts.login_user(
            identifier=identifier,
            password=password,
        )

        if not user:
            return {
                "success": False,
                "message": "Invalid email/phone or password. Please check your details or sign up.",
                "user": None,
                "profile": None,
                "profile_required": False,
            }

        profile = self.profiles.get_profile_by_user_id(
            user["user_id"]
        )

        logger.info("Login workflow completed for: %s", user["user_id"])

        return {
            "success": True,
            "message": "Login successful.",
            "user": user,
            "profile": profile,
            "profile_required": profile is None,
            "next_step": (
                "CREATE_PROFILE" if profile is None else "DASHBOARD"
            ),
        }

    def create_profile_for_user(
        self,
        user_id: str,
        profile_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create and link a citizen profile to an existing account.

        user_id must come from the authenticated server-side session,
        never directly from an untrusted client request.
        """

        if not user_id:
            raise ValueError("A valid authenticated user is required.")

        # Verify that the account exists and is active.
        with self.accounts.db.get_connection() as conn:
            account = conn.execute(
                """
                SELECT user_id, account_status
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if not account or account["account_status"] != "ACTIVE":
            raise ValueError("Account does not exist or is disabled.")

        # Prevent a second profile for the same account.
        existing_profile = self.profiles.get_profile_by_user_id(user_id)

        if existing_profile:
            raise ValueError("A profile already exists for this account.")

        # Never trust a user_id supplied inside profile_data.
        data = dict(profile_data)
        data["user_id"] = user_id

        try:
            profile = self.profiles.create_profile(data)

        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "Profile could not be created. It may already exist."
            ) from exc

        logger.info(
            "Citizen profile created for account: %s",
            user_id,
        )

        return {
            "success": True,
            "message": "Citizen profile created successfully.",
            "profile": profile,
            "next_step": "DASHBOARD",
        }
