"""Unit and integration tests for Phase 1.1 Security Review and Hardening.

Covers:
1. Raw session ID is never stored in SQLite (only SHA-256 hash).
2. Valid session works.
3. Invalid session is rejected.
4. Expired session is rejected.
5. Revoked session is rejected.
6. Inactive account is rejected.
7. Unauthorized origin is rejected.
8. Missing CSRF token is rejected where required.
9. Invalid CSRF token is rejected.
10. Valid CSRF token is accepted.
11. Production secret validation works.
12. Production insecure cookies are rejected.
13. Expired-session cleanup works (explicit and opportunistic).
14. Session ID tampering and malformed input safety.
15. Missing session cookie handling on protected endpoints.
16. Cookie attachment and removal (HttpOnly, SameSite, Secure flags).
17. Safe GET/HEAD/OPTIONS requests are exempt from CSRF checks.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from api.security import (
    SessionConfig,
    clear_session_cookie,
    enforce_csrf_protection,
    generate_csrf_token,
    get_current_active_user,
    get_session_config,
    reset_session_config,
    set_session_cookie,
    validate_csrf_token,
    verify_csrf_origin,
)
from profile.account_manager import AccountManager
from profile.database import Database
from profile.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    """Provides an isolated SQLite database for security tests."""
    db_file = tmp_path / "test_session_security.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def account_mgr(temp_db):
    return AccountManager(db=temp_db)


@pytest.fixture
def session_mgr(temp_db):
    return SessionManager(db=temp_db)


@pytest.fixture
def active_user(account_mgr):
    """Creates a standard active user for testing."""
    return account_mgr.register_user(
        email="citizen.test@example.com",
        password="SecurePassword@123",
        phone="9876543210",
    )


@pytest.fixture
def disabled_user(account_mgr, temp_db):
    """Creates a user whose account_status is DISABLED."""
    user = account_mgr.register_user(
        email="disabled.user@example.com",
        password="SecurePassword@123",
    )
    with temp_db.get_connection() as conn:
        conn.execute(
            "UPDATE users SET account_status = 'DISABLED' WHERE user_id = ?",
            (user["user_id"],),
        )
    return user


# ---------------------------------------------------------------------------
# Test Cases: Session Storage Security & Lifecycle
# ---------------------------------------------------------------------------

class TestSessionStorageSecurity:
    """Tests confirming session hashing, storage security, and lifecycle."""

    def test_01_raw_session_id_never_stored_in_database(self, session_mgr, active_user, temp_db):
        """Item 1: Raw session ID is NEVER stored in SQLite; only SHA-256 hash is saved."""
        user_id = active_user["user_id"]
        session = session_mgr.create_session(user_id=user_id)
        raw_token = session["session_id"]

        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        # Query raw SQLite database records directly
        with temp_db.get_connection() as conn:
            rows = conn.execute("SELECT session_id, user_id FROM user_sessions").fetchall()

        assert len(rows) == 1
        stored_id = rows[0]["session_id"]

        # 1. The stored value must be the SHA-256 hash
        assert stored_id == expected_hash
        # 2. The raw session ID must strictly NOT equal the stored value
        assert stored_id != raw_token
        # 3. Direct lookup by raw token in SQLite yields 0 records
        with temp_db.get_connection() as conn:
            direct_lookup = conn.execute(
                "SELECT * FROM user_sessions WHERE session_id = ?",
                (raw_token,),
            ).fetchone()
        assert direct_lookup is None, "Raw session token found in database! It must be hashed."

    def test_02_valid_session_works(self, session_mgr, active_user):
        """Item 2: Valid, unexpired, unrevoked session successfully validates."""
        user_id = active_user["user_id"]
        session = session_mgr.create_session(user_id=user_id)

        validated = session_mgr.validate_session(session["session_id"])
        assert validated is not None
        assert validated["user_id"] == user_id
        assert validated["revoked_at"] is None

    def test_03_invalid_session_rejected(self, session_mgr):
        """Item 3: Non-existent or unknown session ID returns None."""
        assert session_mgr.validate_session("unknown_session_id_that_does_not_exist_in_db") is None

    def test_04_expired_session_rejected(self, session_mgr, active_user, temp_db):
        """Item 4: Session with past expiration timestamp is rejected."""
        user_id = active_user["user_id"]
        session = session_mgr.create_session(user_id=user_id, ttl_seconds=3600)
        raw_id = session["session_id"]
        session_hash = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()

        # Backdate expiration to the past in SQLite
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with temp_db.get_connection() as conn:
            conn.execute(
                "UPDATE user_sessions SET expires_at = ? WHERE session_id = ?",
                (past_iso, session_hash),
            )

        assert session_mgr.validate_session(raw_id) is None

    def test_05_revoked_session_rejected(self, session_mgr, active_user):
        """Item 5: Revoked session (logout) is immediately invalidated."""
        user_id = active_user["user_id"]
        session = session_mgr.create_session(user_id=user_id)
        raw_id = session["session_id"]

        assert session_mgr.validate_session(raw_id) is not None

        # Revoke session
        revoked = session_mgr.revoke_session(raw_id)
        assert revoked is True

        # Second revoke returns False (already revoked)
        assert session_mgr.revoke_session(raw_id) is False

        # Must no longer validate
        assert session_mgr.validate_session(raw_id) is None

    def test_06_inactive_account_rejected_at_session_creation(self, session_mgr, disabled_user):
        """Item 6a: Cannot create session for an account with status != ACTIVE."""
        with pytest.raises(ValueError, match="not ACTIVE"):
            session_mgr.create_session(user_id=disabled_user["user_id"])

    def test_13_expired_session_cleanup_works(self, session_mgr, active_user, temp_db):
        """Item 13: Cleanup removes expired and revoked sessions while retaining active ones."""
        user_id = active_user["user_id"]

        # 1. Active session
        s_active = session_mgr.create_session(user_id=user_id, ttl_seconds=3600)

        # 2. Expired session
        s_expired = session_mgr.create_session(user_id=user_id, ttl_seconds=3600)
        hash_expired = hashlib.sha256(s_expired["session_id"].encode("utf-8")).hexdigest()
        past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with temp_db.get_connection() as conn:
            conn.execute(
                "UPDATE user_sessions SET expires_at = ? WHERE session_id = ?",
                (past_iso, hash_expired),
            )

        # 3. Revoked session
        s_revoked = session_mgr.create_session(user_id=user_id, ttl_seconds=3600)
        session_mgr.revoke_session(s_revoked["session_id"])

        # Execute cleanup
        deleted_count = session_mgr.cleanup_expired_sessions()
        assert deleted_count >= 2

        # Active session must remain valid
        assert session_mgr.get_session(s_active["session_id"]) is not None
        # Expired and revoked must be purged
        assert session_mgr.get_session(s_expired["session_id"]) is None
        assert session_mgr.get_session(s_revoked["session_id"]) is None

    def test_session_id_tampering(self, session_mgr, active_user):
        """Session ID tampering and malformed input are safely rejected."""
        session = session_mgr.create_session(user_id=active_user["user_id"])
        valid_id = session["session_id"]

        tampered_cases = [
            valid_id + "_extra",
            valid_id[:-5],
            "'; DROP TABLE user_sessions; --",
            "../../../etc/passwd",
            "<script>alert(1)</script>",
            " ",
            "",
            None,
        ]

        for bad_id in tampered_cases:
            assert session_mgr.validate_session(bad_id) is None
            assert session_mgr.get_session(bad_id) is None


# ---------------------------------------------------------------------------
# Test Cases: Production Environment Validation
# ---------------------------------------------------------------------------

class TestProductionConfigurationValidation:
    """Items 11 & 12: Production secret and security flags validation."""

    def test_11_production_secret_validation_works(self, monkeypatch):
        """Item 11: In production, missing or weak SESSION_SECRET_KEY raises RuntimeError."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        monkeypatch.setenv("SESSION_SECRET_KEY", "")

        reset_session_config()
        with pytest.raises(RuntimeError, match="SESSION_SECRET_KEY must be a cryptographically secure"):
            SessionConfig.from_env()

        # Weak/short secret
        monkeypatch.setenv("SESSION_SECRET_KEY", "short_secret_under_32_chars")
        with pytest.raises(RuntimeError, match="at least 32 characters"):
            SessionConfig.from_env()

        # Known placeholder secret
        monkeypatch.setenv("SESSION_SECRET_KEY", "change_me_production_placeholder_key_32chars")
        with pytest.raises(RuntimeError, match="cryptographically secure"):
            SessionConfig.from_env()

        # Valid strong secret passes
        monkeypatch.setenv("SESSION_SECRET_KEY", "this_is_a_sufficiently_long_production_secret_32chars!")
        valid_cfg = SessionConfig.from_env()
        assert valid_cfg.app_env == "production"
        assert valid_cfg.cookie_secure is True

    def test_12_production_insecure_cookies_rejected(self, monkeypatch):
        """Item 12: In production, SESSION_COOKIE_SECURE=false is strictly rejected."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
        monkeypatch.setenv("SESSION_SECRET_KEY", "this_is_a_sufficiently_long_production_secret_32chars!")

        with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE must be True in production"):
            SessionConfig.from_env()

        reset_session_config()


# ---------------------------------------------------------------------------
# Test Cases: CSRF Protection & FastAPI Cookie Integration
# ---------------------------------------------------------------------------

class TestCSRFProtectionAndFastAPIDependencies:
    """Items 7, 8, 9, 10: CSRF protection, origin validation, and cookie handling."""

    @pytest.fixture
    def test_app(self, session_mgr):
        """Constructs a test FastAPI application with CSRF and auth dependencies."""
        app = FastAPI()

        @app.get("/safe-get")
        def safe_get_route(request: Request, _csrf=Depends(enforce_csrf_protection)):
            return {"status": "safe_get_ok"}

        @app.post("/protected-action")
        def protected_action_route(
            request: Request,
            user: dict = Depends(get_current_active_user),
            _csrf=Depends(enforce_csrf_protection),
        ):
            return {"status": "action_successful", "user_id": user["user_id"]}

        @app.post("/public-state-change")
        def public_state_change_route(
            request: Request,
            _csrf=Depends(enforce_csrf_protection),
        ):
            return {"status": "public_ok"}

        @app.post("/set-cookie")
        def set_cookie_route(response: Response, session_id: str):
            set_session_cookie(response, session_id)
            return {"status": "cookie_set"}

        @app.post("/clear-cookie")
        def clear_cookie_route(response: Response):
            clear_session_cookie(response)
            return {"status": "cookie_cleared"}

        # Include auth router to test /auth/csrf-token
        from api.auth import router as auth_router
        app.include_router(auth_router)

        return app

    def test_06b_inactive_account_rejected_by_dependency(
        self, test_app, session_mgr, active_user, temp_db, monkeypatch
    ):
        """Item 6b: Valid session for a user whose account is DISABLED returns HTTP 401."""
        monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        cfg = get_session_config()

        # Disable the user account after session creation
        with temp_db.get_connection() as conn:
            conn.execute(
                "UPDATE users SET account_status = 'DISABLED' WHERE user_id = ?",
                (active_user["user_id"],),
            )

        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, session["session_id"])
        csrf_token = generate_csrf_token(session["session_id"])

        res = client.post(
            "/protected-action",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        )
        assert res.status_code == 401
        assert "inactive or disabled" in res.json()["detail"].lower()

    def test_07_unauthorized_origin_rejected(self, test_app):
        """Item 7: State-changing requests from unauthorized origins are rejected with HTTP 403."""
        client = TestClient(test_app)
        res = client.post(
            "/public-state-change",
            headers={"Origin": "http://malicious-attacker.com"},
        )
        assert res.status_code == 403
        assert "not authorized" in res.json()["detail"].lower()

    def test_08_missing_csrf_token_rejected_where_required(
        self, test_app, session_mgr, active_user, monkeypatch
    ):
        """Item 8: Cookie-authenticated state-changing request without CSRF token returns HTTP 403."""
        monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        cfg = get_session_config()

        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, session["session_id"])

        # POST without X-CSRF-Token header
        res = client.post(
            "/protected-action",
            headers={"Origin": "http://localhost:5500"},
        )
        assert res.status_code == 403
        assert "csrf token missing" in res.json()["detail"].lower()

    def test_09_invalid_csrf_token_rejected(
        self, test_app, session_mgr, active_user, monkeypatch
    ):
        """Item 9: Cookie-authenticated state-changing request with invalid CSRF token returns HTTP 403."""
        monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        cfg = get_session_config()

        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, session["session_id"])

        # POST with wrong/forged CSRF token
        res = client.post(
            "/protected-action",
            headers={
                "Origin": "http://localhost:5500",
                "X-CSRF-Token": "invalid_forged_csrf_token_hex_value",
            },
        )
        assert res.status_code == 403
        assert "csrf token validation failed" in res.json()["detail"].lower()

    def test_10_valid_csrf_token_accepted(
        self, test_app, session_mgr, active_user, monkeypatch
    ):
        """Item 10: Cookie-authenticated state-changing request with valid CSRF token succeeds (HTTP 200)."""
        monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        cfg = get_session_config()
        csrf_token = generate_csrf_token(session["session_id"])

        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, session["session_id"])

        res = client.post(
            "/protected-action",
            headers={
                "Origin": "http://localhost:5500",
                "X-CSRF-Token": csrf_token,
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "action_successful"
        assert res.json()["user_id"] == active_user["user_id"]

    def test_safe_get_csrf_exempt(self, test_app):
        """Safe methods (GET, HEAD, OPTIONS) are exempt from CSRF token requirements."""
        client = TestClient(test_app)
        res = client.get("/safe-get")
        assert res.status_code == 200
        assert res.json()["status"] == "safe_get_ok"

    def test_missing_session_cookie(self, test_app):
        """Protected endpoint returns HTTP 401 if session cookie is absent."""
        client = TestClient(test_app)
        res = client.post(
            "/protected-action",
            headers={"Origin": "http://localhost:5500"},
        )
        assert res.status_code == 401
        assert "cookie missing" in res.json()["detail"].lower()

    def test_cookie_flags_set_and_clear(self, test_app):
        """Set-Cookie includes HttpOnly, SameSite, and correct path; clear removes cookie."""
        client = TestClient(test_app)
        res = client.post("/set-cookie?session_id=test_raw_session_id_token_value_1234567890123456")
        assert res.status_code == 200

        cookie_header = res.headers.get("set-cookie")
        assert cookie_header is not None
        assert "httponly" in cookie_header.lower()
        assert "samesite=lax" in cookie_header.lower()
        assert "path=/" in cookie_header.lower()

        # Clear cookie
        res_clear = client.post("/clear-cookie")
        assert res_clear.status_code == 200
        clear_header = res_clear.headers.get("set-cookie")
        assert clear_header is not None
        assert "max-age=0" in clear_header.lower() or "expires=" in clear_header.lower()

    def test_csrf_token_endpoint_with_valid_session(
        self, test_app, session_mgr, active_user, monkeypatch
    ):
        """GET /auth/csrf-token returns 200, issues client-readable CSRF cookie and token, keeps session HttpOnly."""
        monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        raw_session_id = session["session_id"]
        cfg = get_session_config()

        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, raw_session_id)

        res = client.get("/auth/csrf-token")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        csrf_token = data["csrf_token"]
        assert isinstance(csrf_token, str)
        assert len(csrf_token) == 64  # SHA-256 HMAC hex digest

        # Verify CSRF token matches deterministic HMAC of raw_session_id
        expected_token = generate_csrf_token(raw_session_id)
        assert csrf_token == expected_token

        # Verify raw session ID is NOT leaked in CSRF token or JSON response
        assert raw_session_id not in csrf_token
        assert raw_session_id not in str(data)

        # Check Set-Cookie headers for sahay_csrf
        set_cookie_headers = res.headers.get_list("set-cookie")
        assert len(set_cookie_headers) > 0
        csrf_cookie_hdr = None
        for hdr in set_cookie_headers:
            if cfg.csrf_cookie_name in hdr:
                csrf_cookie_hdr = hdr
                break
        assert csrf_cookie_hdr is not None, f"Cookie {cfg.csrf_cookie_name} not found in headers"
        # The CSRF cookie must NOT be HttpOnly so JavaScript can read it
        assert "httponly" not in csrf_cookie_hdr.lower()
        assert "samesite=lax" in csrf_cookie_hdr.lower()
        assert "path=/" in csrf_cookie_hdr.lower()

    def test_csrf_token_endpoint_missing_session(self, test_app):
        """GET /auth/csrf-token without active session cookie returns HTTP 401."""
        client = TestClient(test_app)
        res = client.get("/auth/csrf-token")
        assert res.status_code == 401
        assert "active session required" in res.json()["detail"].lower()

    def test_csrf_token_endpoint_expired_or_revoked_session(
        self, test_app, session_mgr, active_user, temp_db, monkeypatch
    ):
        """GET /auth/csrf-token with expired or revoked session returns HTTP 401."""
        monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)

        # 1. Expired session
        session = session_mgr.create_session(user_id=active_user["user_id"])
        raw_id = session["session_id"]
        session_hash = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        with temp_db.get_connection() as conn:
            conn.execute("UPDATE user_sessions SET expires_at = ? WHERE session_id = ?", (past_iso, session_hash))

        cfg = get_session_config()
        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, raw_id)

        res = client.get("/auth/csrf-token")
        assert res.status_code == 401
        assert "invalid, expired, or revoked" in res.json()["detail"].lower()

        # 2. Revoked session
        revoked_session = session_mgr.create_session(user_id=active_user["user_id"])
        session_mgr.revoke_session(revoked_session["session_id"])

        client.cookies.set(cfg.cookie_name, revoked_session["session_id"])
        res2 = client.get("/auth/csrf-token")
        assert res2.status_code == 401
        assert "invalid, expired, or revoked" in res2.json()["detail"].lower()

    def test_enforce_csrf_rejects_expired_session(
        self, test_app, session_mgr, active_user, temp_db, monkeypatch
    ):
        """enforce_csrf_protection rejects requests with expired session cookies (HTTP 401)."""
        monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        raw_id = session["session_id"]
        csrf_token = generate_csrf_token(raw_id)
        session_hash = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()

        # Backdate expiration
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with temp_db.get_connection() as conn:
            conn.execute("UPDATE user_sessions SET expires_at = ? WHERE session_id = ?", (past_iso, session_hash))

        cfg = get_session_config()
        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, raw_id)

        # Target endpoint protected strictly by enforce_csrf_protection
        res = client.post(
            "/public-state-change",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        )
        assert res.status_code == 401
        assert "expired" in res.json()["detail"].lower()

    def test_enforce_csrf_rejects_untrusted_origin_even_with_valid_token(
        self, test_app, session_mgr, active_user, monkeypatch
    ):
        """State-changing request from unauthorized Origin is rejected (HTTP 403) despite valid CSRF token."""
        monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

        session = session_mgr.create_session(user_id=active_user["user_id"])
        csrf_token = generate_csrf_token(session["session_id"])
        cfg = get_session_config()

        client = TestClient(test_app)
        client.cookies.set(cfg.cookie_name, session["session_id"])

        res = client.post(
            "/protected-action",
            headers={
                "Origin": "http://evil-attacker.example.com",
                "X-CSRF-Token": csrf_token,
            },
        )
        assert res.status_code == 403
        assert "not authorized" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test Cases: Startup Lifespan Non-blocking Maintenance
# ---------------------------------------------------------------------------

class TestLifespanStartupMaintenance:
    """Tests confirming startup session cleanup is non-blocking and fault-tolerant."""

    @pytest.mark.anyio
    async def test_lifespan_cleans_sessions_via_thread(self, monkeypatch):
        """Lifespan cleans expired sessions using asyncio.to_thread without blocking event loop."""
        import asyncio
        from api.main import lifespan

        called = {"thread_ran": False}

        def mock_cleanup():
            called["thread_ran"] = True
            return 3

        class MockSessionManager:
            def cleanup_expired_sessions(self):
                return mock_cleanup()

        monkeypatch.setattr("profile.session_manager.SessionManager", MockSessionManager)

        dummy_app = FastAPI()
        async with lifespan(dummy_app):
            assert called["thread_ran"] is True

    @pytest.mark.anyio
    async def test_lifespan_gracefully_handles_transient_database_error(self, monkeypatch, caplog):
        """Lifespan catches database errors during startup cleanup and logs a warning without crashing."""
        import logging
        from api.main import lifespan

        def mock_failing_cleanup():
            raise RuntimeError("Simulated SQLite lock error during startup cleanup")

        class MockFailingSessionManager:
            def cleanup_expired_sessions(self):
                return mock_failing_cleanup()

        monkeypatch.setattr("profile.session_manager.SessionManager", MockFailingSessionManager)

        dummy_app = FastAPI()
        with caplog.at_level(logging.WARNING):
            # Lifespan must NOT raise RuntimeError
            async with lifespan(dummy_app):
                pass

        assert any("startup session cleanup encountered error" in record.message.lower() for record in caplog.records)
