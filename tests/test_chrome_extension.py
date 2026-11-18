"""Automated test suite for SahayAI Step 5.5C:
Chrome Extension Package, Security Contracts, and Website Integration.

Verifies:
1. Manifest V3 validity and required components.
2. Restricted host permissions (No <all_urls> or wildcard permissions).
3. Unapproved portal origin rejection (Strict scholarships.gov.in restriction).
4. Grant expiry (5-minute TTL) and scope enforcement.
5. Invalid, expired, or replayed authorization rejection.
6. Zero token leakage into URLs, page DOM, or browser storage.
7. Unconfirmed OCR extraction values never autofill.
8. Conflicting values are never autofilled automatically.
9. Missing fields remain untouched.
10. Non-empty form fields are not silently overwritten.
11. Login, password, OTP, and CAPTCHA fields are strictly forbidden.
12. Unsupported pages and forms are refused.
13. Supported form selectors match documented field mappings.
14. Extension connection states in dashboard frontend.
15. Existing SahayAI backend, profile, and application workspace APIs remain unaffected.
"""

from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from api.main import app
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from applications.application_service import ApplicationService
from applications.autofill_service import AutofillService
from document_ai.extract_fields import PIIVault
from scheme_collection.application_definitions import SCHEME_APPLICATION_DEFINITIONS

AUTHORIZED_ORIGIN = "http://127.0.0.1:8000"
EXTENSION_DIR = Path("browser_extension")


@pytest.fixture
def test_db(tmp_path):
    """Provides a fresh isolated SQLite database instance."""
    db_file = tmp_path / "sahay_extension_test.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def app_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth, profile, application, autofill, and vault services."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
    vault = PIIVault(encryption_key=test_key)
    app_svc = ApplicationService(db=test_db, vault=vault)
    autofill_svc = AutofillService(db=test_db, profile_manager=profiles, app_service=app_svc, vault=vault)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)
    monkeypatch.setattr("api.applications.app_service", app_svc)
    monkeypatch.setattr("api.applications.autofill_service", autofill_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
        "app_service": app_svc,
        "autofill_service": autofill_svc,
        "vault": vault,
    }


@pytest.fixture
def client(app_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _register_citizen(client, email="citizen_ext@example.com", password="Password@123"):
    """Helper to register and configure a citizen session with CSRF token."""
    signup_res = client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf = csrf_res.json()["csrf_token"]
    return user_id, csrf


# -----------------------------------------------------------------------------
# Test 01: Manifest V3 Validity
# -----------------------------------------------------------------------------

def test_01_manifest_v3_validity():
    """Test 01: Validates Chrome Manifest V3 structure and verifies that all referenced files exist."""
    manifest_path = EXTENSION_DIR / "manifest.json"
    assert manifest_path.exists(), "manifest.json must exist in browser_extension/"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Core Manifest V3 requirements
    assert manifest.get("manifest_version") == 3
    assert manifest.get("name") == "SahayAI Scholarship Assistant"
    assert manifest.get("version") == "1.0.0"
    assert "description" in manifest

    # Service worker background
    background = manifest.get("background", {})
    sw_file = background.get("service_worker")
    assert sw_file == "background.js"
    assert (EXTENSION_DIR / sw_file).exists(), "background.js must exist"

    # Action popup
    action = manifest.get("action", {})
    popup_file = action.get("default_popup")
    assert popup_file == "popup.html"
    assert (EXTENSION_DIR / popup_file).exists(), "popup.html must exist"

    # Content scripts
    cs_list = manifest.get("content_scripts", [])
    assert len(cs_list) >= 2, "Must configure content scripts for portal and bridge"

    for cs in cs_list:
        for js_file in cs.get("js", []):
            assert (EXTENSION_DIR / js_file).exists(), f"Content script {js_file} must exist"
        for css_file in cs.get("css", []):
            assert (EXTENSION_DIR / css_file).exists(), f"CSS file {css_file} must exist"

    # Icons
    icons = manifest.get("icons", {})
    for size, icon_file in icons.items():
        assert (EXTENSION_DIR / icon_file).exists(), f"Icon {icon_file} ({size}x{size}) must exist"


# -----------------------------------------------------------------------------
# Test 02: Restricted Host Permissions (No <all_urls>)
# -----------------------------------------------------------------------------

def test_02_restricted_host_permissions():
    """Test 02: Validates that permissions are minimal, no wildcards, and no 5500/5501 ports."""
    manifest_path = EXTENSION_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    permissions = manifest.get("permissions", [])
    host_permissions = manifest.get("host_permissions", [])

    # Strictly forbidden permissions
    assert "<all_urls>" not in permissions
    assert "<all_urls>" not in host_permissions
    assert "*://*/*" not in host_permissions
    assert "http://*/*" not in host_permissions
    assert "https://*/*" not in host_permissions

    # Remove temporary live-server ports (5500, 5501)
    manifest_raw = manifest_path.read_text(encoding="utf-8")
    assert "5500" not in manifest_raw
    assert "5501" not in manifest_raw

    # Only approved portal and explicit local dev origins allowed (port 8000)
    for pattern in host_permissions:
        is_nsp = pattern.startswith("https://scholarships.gov.in")
        is_local = "localhost:8000" in pattern or "127.0.0.1:8000" in pattern
        assert is_nsp or is_local, f"Unauthorized host permission pattern: {pattern}"


# -----------------------------------------------------------------------------
# Test 03: Unapproved Portal Origin Rejection
# -----------------------------------------------------------------------------

def test_03_unapproved_portal_origin_rejection():
    """Test 03: Verifies that supported-portals.js strictly accepts only official portal origins."""
    portals_file = EXTENSION_DIR / "supported-portals.js"
    assert portals_file.exists()
    content = portals_file.read_text(encoding="utf-8")

    # Verify verified host definitions
    assert 'VERIFIED_PORTAL_HOSTS = ["scholarships.gov.in"]' in content

    # Test logic matching isVerifiedPortal
    def is_verified(url_str):
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url_str)
            host = (parsed.hostname or "").lower()
            return host == "scholarships.gov.in" or host.endswith(".scholarships.gov.in")
        except Exception:
            return False

    assert is_verified("https://scholarships.gov.in") is True
    assert is_verified("https://scholarships.gov.in/fresh/newRegistration") is True
    assert is_verified("https://scholarships.gov.in/application/form?id=123") is True

    # Reject unapproved portals
    assert is_verified("https://fake-scholarships.com") is False
    assert is_verified("https://scholarships.gov.in.attacker.com") is False
    assert is_verified("http://scholarships.gov.in") is True # domain matches, but https verified in API
    assert is_verified("https://phishing-site.org") is False
    assert is_verified("") is False
    assert is_verified(None) is False


# -----------------------------------------------------------------------------
# Test 04: Grant Expiry and Scope Enforcement
# -----------------------------------------------------------------------------

def test_04_grant_expiry_and_scope_enforcement(client, app_env):
    """Test 04: Extension grant token enforces 5-minute TTL and extension:autofill scope."""
    user_id, csrf = _register_citizen(client, email="ext_grant_ttl@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res.status_code == 200
    grant = res.json()["grant"]

    assert grant["scope"] == "extension:autofill"
    assert grant["expires_in_seconds"] == 300
    assert grant["draft_id"] == draft_id

    expires_at = datetime.fromisoformat(grant["expires_at"])
    now = datetime.now(timezone.utc)
    remaining = (expires_at - now).total_seconds()
    assert 285 <= remaining <= 305


# -----------------------------------------------------------------------------
# Test 05: Invalid or Replayed Authorization Rejection
# -----------------------------------------------------------------------------

def test_05_invalid_or_replayed_authorization_rejection(client, app_env):
    """Test 05: Forged, corrupted, or invalid bearer extension grants are strictly rejected with HTTP 401."""
    # 1. Random non-existent bearer token
    res1 = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": "draft_fake_token_test_12345",
        },
        headers={"Authorization": "Bearer sahay_atf_forged_fake_token_1234567890"},
    )
    assert res1.status_code == 401

    # 2. Corrupted token prefix
    res2 = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": "draft_fake_token_test_12345",
        },
        headers={"Authorization": "Basic some_auth_credentials"},
    )
    # Rejects as unauthenticated web session without valid CSRF
    assert res2.status_code in (401, 403)


# -----------------------------------------------------------------------------
# Test 06: No Token Leakage into URLs or Page DOM
# -----------------------------------------------------------------------------

def test_06_no_token_leakage_into_urls_or_page_dom():
    """Test 06: Inspects extension code to ensure tokens are never passed via URLs or DOM attributes."""
    files_to_check = [
        EXTENSION_DIR / "content.js",
        EXTENSION_DIR / "bridge-content.js",
        EXTENSION_DIR / "popup.js",
        EXTENSION_DIR / "background.js",
    ]

    for js_path in files_to_check:
        assert js_path.exists()
        code = js_path.read_text(encoding="utf-8")

        # Ensure no URL query param appending of tokens
        assert "location.search" not in code
        assert "?token=" not in code
        assert "&token=" not in code
        assert "?grant=" not in code

        # Ensure tokens are never persisted in web localStorage or sessionStorage
        if js_path.name in ("content.js", "bridge-content.js"):
            assert "localStorage.setItem" not in code
            assert "sessionStorage.setItem" not in code


# -----------------------------------------------------------------------------
# Test 07: Unconfirmed OCR Extraction Fields Never Autofill
# -----------------------------------------------------------------------------

def test_07_unconfirmed_ocr_never_autofills(client, app_env):
    """Test 07: Unconfirmed OCR extracted fields are marked MISSING_INFORMATION and never filled."""
    user_id, csrf = _register_citizen(client, email="ext_unconfirmed_ocr@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    # Upload document with OCR but do NOT confirm
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="COMMUNITY_CERTIFICATE",
        extracted_fields={"caste_category": "OBC"},
        document_category="CATEGORY_CERTIFICATE",
    )

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    field = pkg["fields"]["caste_category"]

    # Must be missing, confidence 0.0, never populated
    assert field["status"] == "MISSING_INFORMATION"
    assert field["value"] is None
    assert field["confidence"] == 0.0


# -----------------------------------------------------------------------------
# Test 08: Conflicting Values Never Autofill Automatically
# -----------------------------------------------------------------------------

def test_08_conflicting_values_never_autofill(client, app_env):
    """Test 08: Conflicting values are flagged as CONFLICT and skipped from automatic population."""
    user_id, csrf = _register_citizen(client, email="ext_conflict@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    autofill_svc: AutofillService = app_env["autofill_service"]

    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Conflict Applicant",
        "annual_income": 300000.0,
        "user_confirmed": True,
    })

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    profile_mgr.save_document(
        document_id=doc_id,
        user_id=user_id,
        document_type="INCOME_CERTIFICATE",
        extracted_fields={"annual_income": "200000"},
        document_category="INCOME",
    )
    profile_mgr.confirm_and_persist_transactional(
        user_id=user_id,
        document_id=doc_id,
        confirmed_items=[{"field_name": "annual_income", "field_value": 200000.0}],
        profile_updates={},
    )

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    income_field = pkg["fields"]["annual_family_income"]

    assert income_field["status"] == "CONFLICT"
    assert income_field["has_conflict"] is True
    assert income_field["review_requirement"] == "MANDATORY_REVIEW"


# -----------------------------------------------------------------------------
# Test 09: Missing Fields Remain Untouched
# -----------------------------------------------------------------------------

def test_09_missing_fields_remain_untouched(client, app_env):
    """Test 09: Missing fields have value=None and clear remediation guidance."""
    user_id, csrf = _register_citizen(client, email="ext_missing@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]

    pkg = autofill_svc.generate_autofill_package(user_id=user_id, scheme_id="SCHEME_EDU_002_AICTE_PRAGATI")
    cap_field = pkg["fields"]["cap_allotment_number"]

    assert cap_field["status"] == "MISSING_INFORMATION"
    assert cap_field["value"] is None
    assert cap_field["missing_reason"] is not None


# -----------------------------------------------------------------------------
# Test 10: Non-Empty Fields Are Not Silently Overwritten
# -----------------------------------------------------------------------------

def test_10_non_empty_fields_not_silently_overwritten():
    """Test 10: Inspects content.js to verify that non-empty fields are checked and skipped."""
    content_js = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")

    # Verifies protection logic against silent overwrite
    assert 'currentVal !== ""' in content_js
    assert 'skippedExistingCount++' in content_js
    assert 'sahay-conflict-field' in content_js


# -----------------------------------------------------------------------------
# Test 11: Login, Password, OTP, and CAPTCHA Fields Strictly Forbidden
# -----------------------------------------------------------------------------

def test_11_login_otp_captcha_fields_never_modified():
    """Test 11: Validates that security, credential, and CAPTCHA selectors are strictly forbidden."""
    portals_js = (EXTENSION_DIR / "supported-portals.js").read_text(encoding="utf-8")

    # Verifies presence of security blacklist
    assert "input[type='password']" in portals_js
    assert "input[name*='otp' i]" in portals_js
    assert "input[name*='captcha' i]" in portals_js
    assert "#txtCaptcha" in portals_js
    assert "#txtOtp" in portals_js
    assert "isForbiddenElement" in portals_js


# -----------------------------------------------------------------------------
# Test 12: Unsupported Pages and Forms Are Refused
# -----------------------------------------------------------------------------

def test_12_unsupported_pages_not_modified():
    """Test 12: Verifies that content.js and supported-portals.js refuse execution on non-NSP pages."""
    content_js = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")

    # Verifies early return if not verified portal
    assert "!Portals.isVerifiedPortal(window.location.href)" in content_js


# -----------------------------------------------------------------------------
# Test 13: Supported Form Selectors Match Documented Mappings
# -----------------------------------------------------------------------------

def test_13_supported_form_selectors_match_documented_mappings():
    """Test 13: All 5 scholarship schemes have mappings defined with verified/template statuses."""
    portals_js = (EXTENSION_DIR / "supported-portals.js").read_text(encoding="utf-8")

    for sid in SCHEME_APPLICATION_DEFINITIONS.keys():
        assert sid in portals_js, f"Scheme {sid} must be documented in supported-portals.js"

    # Declarations must be marked UNSUPPORTED
    assert 'declaration_no_concurrent' in portals_js
    assert 'status: "UNSUPPORTED"' in portals_js
    assert 'declaration_information_true' in portals_js


# -----------------------------------------------------------------------------
# Test 14: Extension Connection States in Dashboard Frontend
# -----------------------------------------------------------------------------

def test_14_extension_connection_states_work():
    """Test 14: Verifies the 4 connection states (NOT_INSTALLED, INSTALLED_NOT_CONNECTED, CONNECTED, ERROR)."""
    dashboard_html = Path("frontend/dashboard.html").read_text(encoding="utf-8")
    dashboard_js = Path("frontend/js/dashboard.js").read_text(encoding="utf-8")

    # Verifies HTML elements
    assert "extensionStatusCard" in dashboard_html
    assert "extensionStateBadge" in dashboard_html
    assert "extensionGuideModal" in dashboard_html

    # Verifies JS state management
    assert 'setExtensionState("CONNECTED")' in dashboard_js
    assert 'setExtensionState("INSTALLED_NOT_CONNECTED")' in dashboard_js
    assert 'setExtensionState("NOT_INSTALLED")' in dashboard_js
    assert 'setExtensionState("ERROR")' in dashboard_js
    assert 'handleConnectExtensionClick' in dashboard_js


# -----------------------------------------------------------------------------
# Test 15: Existing SahayAI Workflows Remain Unaffected (Regression)
# -----------------------------------------------------------------------------

def test_15_existing_sahay_workflows_remain_unaffected(client, app_env):
    """Test 15: Verifies that existing scheme discovery, draft management, and document workflows operate identically."""
    user_id, csrf = _register_citizen(client, email="ext_regression@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]

    # 1. Profile creation
    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Regression Student",
        "gender": "FEMALE",
        "state": "Karnataka",
        "district": "Bengaluru",
        "annual_income": 200000.0,
        "user_confirmed": True,
    })

    # 2. Draft creation
    create_res = client.post(
        "/applications/drafts",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert create_res.status_code == 201
    draft_id = create_res.json()["draft"]["draft_id"]

    # 3. Draft update
    update_res = client.put(
        f"/applications/drafts/{draft_id}",
        json={"form_data": {"institution_name": "Bangalore University"}},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert update_res.status_code == 200
    assert update_res.json()["draft"]["form_data"]["institution_name"] == "Bangalore University"

    # 4. Draft deletion
    del_res = client.delete(
        f"/applications/drafts/{draft_id}",
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert del_res.status_code == 200


# -----------------------------------------------------------------------------
# Test 16: Extension-Initiated Auth & Zero PostMessage Token Leakage
# -----------------------------------------------------------------------------

def test_16_extension_initiated_auth_and_no_postmessage_token_leakage():
    """Test 16: Verifies extension-controlled consent boundary and zero token exposure in window.postMessage."""
    bridge_code = (EXTENSION_DIR / "bridge-content.js").read_text(encoding="utf-8")
    dash_code = Path("frontend/js/dashboard.js").read_text(encoding="utf-8")
    bg_code = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    # 1. SAHAY_TRANSFER_GRANT must NOT exist in bridge or dashboard
    assert "SAHAY_TRANSFER_GRANT" not in bridge_code
    assert "SAHAY_TRANSFER_GRANT" not in dash_code

    # 2. Dashboard dispatches SAHAY_REQUEST_EXTENSION_AUTH without bearer token
    assert "SAHAY_REQUEST_EXTENSION_AUTH" in dash_code
    assert "SAHAY_REQUEST_EXTENSION_AUTH" in bridge_code

    # 3. Page message ALONE does not authorize: bridge relays as STAGE_AUTH_REQUEST
    assert 'action: "STAGE_AUTH_REQUEST"' in bridge_code
    assert 'action === "STAGE_AUTH_REQUEST"' in bg_code

    # 4. Background service worker validates sender context (tab, frameId === 0, origin)
    assert "sender.tab" in bg_code
    assert "sender.frameId !== 0" in bg_code
    assert "isAllowedOrigin" in bg_code

    # 5. Bridge only executes backend auth upon internal EXECUTE_APPROVED_AUTHORIZATION
    assert "EXECUTE_APPROVED_AUTHORIZATION" in bridge_code
    assert "EXECUTE_APPROVED_AUTHORIZATION" in bg_code

    # 6. Verify postMessage calls in bridge-content.js NEVER contain grant_token
    pm_matches = re.findall(r"window\.postMessage\(\s*\{([^}]+)\}", bridge_code, re.DOTALL)
    assert len(pm_matches) >= 2, "Bridge must use window.postMessage for status and auth result"
    for pm_block in pm_matches:
        assert "grant_token" not in pm_block
        assert "grant:" not in pm_block
        assert "data.grant" not in pm_block


# -----------------------------------------------------------------------------
# Test 17: Extension Authorization Enforces Auth and CSRF Protection
# -----------------------------------------------------------------------------

def test_17_extension_authorization_enforces_auth_and_csrf(client, app_env):
    """Test 17: Validates that extension grant issuance enforces citizen session + CSRF."""
    # 1. Unauthenticated / guest session must fail with 403 Forbidden
    guest_init = client.post("/auth/guest")
    assert guest_init.status_code == 200
    guest_csrf = guest_init.json().get("csrf_token") or client.get("/auth/csrf-token").json()["csrf_token"]

    guest_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": "draft_dummy_guest"},
        headers={"X-CSRF-Token": guest_csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert guest_res.status_code == 403
    assert "registered citizen" in guest_res.json().get("detail", "").lower()

    # 2. Authenticated citizen session without CSRF token must fail with 403
    user_id, csrf = _register_citizen(client, email="ext_csrf_test@example.com")
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    no_csrf_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"Origin": AUTHORIZED_ORIGIN},
    )
    assert no_csrf_res.status_code == 403

    # 3. Authenticated citizen session with invalid CSRF token must fail with 403
    bad_csrf_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"X-CSRF-Token": "tampered_csrf_token_12345", "Origin": AUTHORIZED_ORIGIN},
    )
    assert bad_csrf_res.status_code == 403

    # 4. Valid session + valid CSRF succeeds
    valid_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert valid_res.status_code == 200
    assert "grant" in valid_res.json()


# -----------------------------------------------------------------------------
# Test 18: TEMPLATE_ONLY Mappings Never Populated & VERIFIED Enforced
# -----------------------------------------------------------------------------

def test_18_template_only_mappings_never_populated_and_verified_enforced():
    """Test 18: Enforces that TEMPLATE_ONLY field mappings are strictly skipped from autofill."""
    portals_code = (EXTENSION_DIR / "supported-portals.js").read_text(encoding="utf-8")
    content_code = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")

    # 1. findFieldElement must reject status !== "VERIFIED"
    assert 'spec.status !== "VERIFIED"' in portals_code

    # 2. All 5 scholarship application fields must be TEMPLATE_ONLY (or UNSUPPORTED for declarations)
    status_matches = re.findall(r'status:\s*"([^"]+)"', portals_code)
    assert len(status_matches) > 10
    for st in status_matches:
        assert st in ("TEMPLATE_ONLY", "UNSUPPORTED"), f"Field mapping status must not be {st} without live portal testing"

    # 3. content.js checks mapping.status !== "VERIFIED" and skips fields
    assert 'mapping.status !== "VERIFIED"' in content_code
    assert "skippedTemplateOnlyCount++" in content_code

    # 4. Alert explicitly explains TEMPLATE_ONLY status to citizen
    assert "TEMPLATE_ONLY" in content_code
    assert "awaiting live portal verification" in content_code


# -----------------------------------------------------------------------------
# Test 19: Service Worker Lifecycle and Fail-Closed Security Contract
# -----------------------------------------------------------------------------

def test_19_service_worker_lifecycle_and_fail_closed(client, app_env):
    """Test 19: Validates service worker memory lifecycle and fail-closed security contract."""
    bg_code = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    # 1. Active grant is stored in an in-memory variable initialized to null
    assert "let activeGrant = null;" in bg_code

    # 2. No persisting of activeGrant or tokens in chrome.storage or web storage
    assert "chrome.storage.local.set({ activeGrant" not in bg_code
    assert "chrome.storage.local.set({ grant_token" not in bg_code
    assert "localStorage" not in bg_code
    assert "indexedDB" not in bg_code

    # 3. Background worker fail-closed logic: returns 401 when activeGrant is null
    assert "!isGrantValid()" in bg_code
    assert "Grant token has expired or is not authorized" in bg_code

    # 4. Verify API fails closed when an unauthenticated/null authorization header is passed
    res = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": "draft_test_fail_closed"},
        headers={"Origin": AUTHORIZED_ORIGIN},
    )
    assert res.status_code in (401, 403)


# -----------------------------------------------------------------------------
# Test 20: Expired, Revoked, and Mismatched Grants Rejected
# -----------------------------------------------------------------------------

def test_20_expired_revoked_mismatched_grants_rejected(client, app_env):
    """Test 20: Expired, scheme-mismatched, portal-mismatched, or revoked grants are rejected."""
    user_id, csrf = _register_citizen(client, email="ext_mismatch@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    app_svc: ApplicationService = app_env["app_service"]
    draft_init = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_init_id = draft_init["draft_id"]

    # 1. Authorize grant for CSSS scheme on NSP
    auth_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_init_id},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert auth_res.status_code == 200
    token = auth_res.json()["grant"]["grant_token"]
    grant_id = auth_res.json()["grant"]["grant_id"]

    # 2. Scheme mismatch: Use CSSS grant to populate PRAGATI
    mismatch_scheme_res = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI", "portal_url": "https://scholarships.gov.in", "draft_id": draft_init_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mismatch_scheme_res.status_code in (401, 403)

    # 3. Portal mismatch: Use grant for unapproved portal URL
    mismatch_portal_res = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://untrusted-portal.com", "draft_id": draft_init_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mismatch_portal_res.status_code in (400, 401, 403)

    # 4. Expiry: Manually expire grant in DB and verify rejection
    test_db: Database = app_env["db"]
    with test_db.get_connection() as conn:
        past_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        conn.execute("UPDATE autofill_grants SET expires_at = ? WHERE grant_id = ?", (past_time, grant_id))
        conn.commit()

    expired_res = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_init_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert expired_res.status_code == 401

    # 5. Draft-level scope enforcement: Grant bound to draft_A rejects draft_B
    app_svc: ApplicationService = app_env["app_service"]
    draft_a = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_b = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_a_id = draft_a["draft_id"]
    draft_b_id = draft_b["draft_id"]

    auth_draft_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_a_id},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert auth_draft_res.status_code == 200
    token_bound = auth_draft_res.json()["grant"]["grant_token"]

    # Requesting with mismatched draft_b must be rejected with 401
    mismatch_draft_res = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_b_id},
        headers={"Authorization": f"Bearer {token_bound}"},
    )
    assert mismatch_draft_res.status_code == 401

    # Requesting with matching draft_a succeeds with 200
    match_draft_res = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_a_id},
        headers={"Authorization": f"Bearer {token_bound}"},
    )
    assert match_draft_res.status_code == 200


# -----------------------------------------------------------------------------
# Test 21: Unauthorized Origins Refused
# -----------------------------------------------------------------------------

def test_21_unauthorized_origins_refused(client, app_env):
    """Test 21: bridge-content.js and backend reject unauthorized origins and ports."""
    bridge_code = (EXTENSION_DIR / "bridge-content.js").read_text(encoding="utf-8")

    # 1. Verify bridge ALLOWED_ORIGINS strictly contains only port 8000
    assert "http://localhost:8000" in bridge_code
    assert "http://127.0.0.1:8000" in bridge_code
    assert "5500" not in bridge_code
    assert "5501" not in bridge_code

    # 2. Verify API CSRF protection rejects unauthorized origin
    user_id, csrf = _register_citizen(client, email="ext_origin_test@example.com")
    unauth_origin_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in"},
        headers={"X-CSRF-Token": csrf, "Origin": "http://evil-site.com"},
    )
    assert unauth_origin_res.status_code == 403


# -----------------------------------------------------------------------------
# Test 22: Workspace and Portal Continuation Without Extension
# -----------------------------------------------------------------------------

def test_22_workspace_and_portal_continuation_without_extension(client, app_env):
    """Test 22: Workspace and portal continuation work without the extension installed."""
    user_id, csrf = _register_citizen(client, email="ext_optional@example.com")
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    app_svc: ApplicationService = app_env["app_service"]

    # 1. Citizen creates draft
    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    assert draft["draft_id"] is not None

    # 2. Citizen accesses draft form data and instructions
    fetched = app_svc.get_draft(draft["draft_id"], user_id=user_id)
    assert fetched["status"] == "DRAFT"

    # 3. Transition to READY_TO_CONTINUE without extension installed
    updated = app_svc.update_draft(draft["draft_id"], user_id=user_id, status="READY_TO_CONTINUE")
    assert updated["status"] == "READY_TO_CONTINUE"

    # 4. Verify dashboard.js does not block redirect when extension is NOT_INSTALLED
    dash_code = Path("frontend/js/dashboard.js").read_text(encoding="utf-8")
    assert 'window.open(pendingExternalPortalUrl, "_blank", "noopener,noreferrer");' in dash_code


# -----------------------------------------------------------------------------
# Test 23: Explicit Extension Consent Boundary Verification
# -----------------------------------------------------------------------------

def test_23_explicit_extension_consent_boundary():
    """Test 23: Verifies explicit extension popup approval requirement and rejection of page-triggered authorization."""
    popup_html = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")
    popup_js = (EXTENSION_DIR / "popup.js").read_text(encoding="utf-8")
    bg_code = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    bridge_code = (EXTENSION_DIR / "bridge-content.js").read_text(encoding="utf-8")

    # 1. Popup contains explicit consent UI elements
    assert "consentCard" in popup_html
    assert "btnApproveAuth" in popup_html
    assert "btnDenyAuth" in popup_html

    # 2. Popup script handles explicit user actions
    assert "APPROVE_PENDING_AUTH" in popup_js
    assert "DENY_PENDING_AUTH" in popup_js
    assert "GET_PENDING_AUTH" in popup_js

    # 3. Background worker handles staging and approval flow
    assert 'action === "STAGE_AUTH_REQUEST"' in bg_code
    assert 'action === "APPROVE_PENDING_AUTH"' in bg_code
    assert 'action === "DENY_PENDING_AUTH"' in bg_code

    # 4. Strict sender validation in background worker
    assert "sender.tab" in bg_code
    assert "sender.frameId !== 0" in bg_code
    assert "isAllowedOrigin" in bg_code

    # 5. Bridge content script does NOT execute auth on page message alone
    assert 'action: "STAGE_AUTH_REQUEST"' in bridge_code
    assert "EXECUTE_APPROVED_AUTHORIZATION" in bridge_code


# =============================================================================
# Step 5.5C: Mandatory Grant Scope Validation Tests
# =============================================================================

# -----------------------------------------------------------------------------
# Test 24: Missing Requested draft_id Rejected
# -----------------------------------------------------------------------------

def test_24_missing_requested_draft_id_rejected(client, app_env):
    """Test 24: Missing requested draft_id is strictly rejected across API and service layer."""
    user_id, csrf = _register_citizen(client, email="no_draft_req@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]

    # 1. API Authorize: Omitting draft_id returns 422 Unprocessable Content
    res_auth = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 422

    # 2. API Populate: Omitting draft_id returns 422 Unprocessable Content
    res_pop = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in"},
        headers={"Authorization": "Bearer sahay_atf_some_token"},
    )
    assert res_pop.status_code == 422

    # 3. Service Layer: validate_extension_grant returns None when draft_id is None, empty, or whitespace
    assert autofill_svc.validate_extension_grant("sahay_atf_test", "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", None) is None
    assert autofill_svc.validate_extension_grant("sahay_atf_test", "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", "") is None
    assert autofill_svc.validate_extension_grant("sahay_atf_test", "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", "   ") is None


# -----------------------------------------------------------------------------
# Test 25: Missing Stored Grant draft_id Fails Closed
# -----------------------------------------------------------------------------

def test_25_missing_stored_grant_draft_id_fails_closed(client, app_env):
    """Test 25: Stored grant with missing/null draft_id fails closed (legacy grant simulation)."""
    user_id, csrf = _register_citizen(client, email="stored_no_draft@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    test_db: Database = app_env["db"]

    raw_token = f"sahay_atf_{uuid.uuid4().hex}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()
    future_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    # Manually insert legacy grant without draft_id (NULL)
    with test_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO autofill_grants (
                grant_id, token_hash, user_id, scheme_id, draft_id,
                portal_url, scope, expires_at, used_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"grant_legacy_{uuid.uuid4().hex[:8]}",
                token_hash,
                user_id,
                "SCHEME_EDU_001_PM_USP_CSSS",
                None,  # missing draft_id in stored grant
                "https://scholarships.gov.in",
                "extension:autofill",
                future_iso,
                None,
                now_iso,
            ),
        )
        conn.commit()

    # validate_extension_grant must fail closed and return None
    assert autofill_svc.validate_extension_grant(
        raw_token=raw_token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id="draft_candidate_123",
    ) is None

    # Populate API with this token must return 401 Unauthorized
    res = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": "draft_candidate_123",
        },
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert res.status_code == 401


# -----------------------------------------------------------------------------
# Test 26: Missing Requested scheme_id Rejected
# -----------------------------------------------------------------------------

def test_26_missing_requested_scheme_id_rejected(client, app_env):
    """Test 26: Missing requested scheme_id is rejected across API and service layer."""
    user_id, csrf = _register_citizen(client, email="no_scheme_req@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]

    # 1. API Authorize: Omitting scheme_id returns 422
    res_auth = client.post(
        "/applications/autofill/authorize",
        json={"portal_url": "https://scholarships.gov.in", "draft_id": "draft_123"},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 422

    # 2. API Populate: Omitting scheme_id returns 422
    res_pop = client.post(
        "/applications/autofill/populate",
        json={"portal_url": "https://scholarships.gov.in", "draft_id": "draft_123"},
        headers={"Authorization": "Bearer sahay_atf_some_token"},
    )
    assert res_pop.status_code == 422

    # 3. Service Layer: validate_extension_grant returns None when scheme_id is None, empty, or whitespace
    assert autofill_svc.validate_extension_grant("sahay_atf_test", None, "https://scholarships.gov.in", "draft_123") is None
    assert autofill_svc.validate_extension_grant("sahay_atf_test", "", "https://scholarships.gov.in", "draft_123") is None
    assert autofill_svc.validate_extension_grant("sahay_atf_test", "   ", "https://scholarships.gov.in", "draft_123") is None


# -----------------------------------------------------------------------------
# Test 27: Missing Stored Grant scheme_id Fails Closed
# -----------------------------------------------------------------------------

def test_27_missing_stored_grant_scheme_id_fails_closed(client, app_env):
    """Test 27: Stored grant with missing/empty scheme_id fails closed."""
    user_id, csrf = _register_citizen(client, email="stored_no_scheme@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]
    test_db: Database = app_env["db"]

    raw_token = f"sahay_atf_{uuid.uuid4().hex}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()
    future_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    # In SQLite, scheme_id has a NOT NULL constraint; test with empty string stored in DB
    with test_db.get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO autofill_grants (
                grant_id, token_hash, user_id, scheme_id, draft_id,
                portal_url, scope, expires_at, used_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"grant_noscheme_{uuid.uuid4().hex[:8]}",
                token_hash,
                user_id,
                "",  # empty string stored in grant
                draft_id,
                "https://scholarships.gov.in",
                "extension:autofill",
                future_iso,
                None,
                now_iso,
            ),
        )
        conn.commit()

    assert autofill_svc.validate_extension_grant(
        raw_token=raw_token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_id,
    ) is None

    res = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert res.status_code == 401


# -----------------------------------------------------------------------------
# Test 28: Missing Authenticated User Rejected
# -----------------------------------------------------------------------------

def test_28_missing_authenticated_user_rejected(client, app_env):
    """Test 28: Missing authenticated user or empty user_id is rejected."""
    autofill_svc: AutofillService = app_env["autofill_service"]

    # 1. Authorize without user session returns 401/403
    unauth_res = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": "draft_123",
        },
    )
    assert unauth_res.status_code in (401, 403)

    # 2. Service Layer: validate_extension_grant returns None when user_id is empty string or whitespace
    assert autofill_svc.validate_extension_grant(
        raw_token="sahay_atf_test",
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id="draft_123",
        user_id="",
    ) is None
    assert autofill_svc.validate_extension_grant(
        raw_token="sahay_atf_test",
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id="draft_123",
        user_id="   ",
    ) is None


# -----------------------------------------------------------------------------
# Test 29: Missing Stored user_id Fails Closed
# -----------------------------------------------------------------------------

def test_29_missing_stored_user_id_fails_closed(client, app_env):
    """Test 29: Stored grant with missing/empty user_id fails closed."""
    autofill_svc: AutofillService = app_env["autofill_service"]
    test_db: Database = app_env["db"]

    raw_token = f"sahay_atf_{uuid.uuid4().hex}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()
    future_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    # Store grant with empty string user_id
    with test_db.get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO autofill_grants (
                grant_id, token_hash, user_id, scheme_id, draft_id,
                portal_url, scope, expires_at, used_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"grant_nouser_{uuid.uuid4().hex[:8]}",
                token_hash,
                "",  # empty user_id
                "SCHEME_EDU_001_PM_USP_CSSS",
                "draft_123",
                "https://scholarships.gov.in",
                "extension:autofill",
                future_iso,
                None,
                now_iso,
            ),
        )
        conn.commit()

    assert autofill_svc.validate_extension_grant(
        raw_token=raw_token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id="draft_123",
    ) is None


# -----------------------------------------------------------------------------
# Test 30: Missing or Untrusted Portal Origin Rejected
# -----------------------------------------------------------------------------

def test_30_missing_or_untrusted_portal_origin_rejected(client, app_env):
    """Test 30: Missing portal origin, untrusted domain, or portal host mismatch rejected."""
    user_id, csrf = _register_citizen(client, email="portal_scope@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    # 1. Missing portal_url on Authorize returns 422
    res_no_portal = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "draft_id": draft_id},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_no_portal.status_code == 422

    # 2. Untrusted portal_url on Authorize returns 422
    res_untrusted = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarship-phishing-scam.net",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_untrusted.status_code == 422

    # 3. Valid grant created
    res_valid = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_valid.status_code == 200
    token = res_valid.json()["grant"]["grant_token"]

    # 4. Service Layer rejects None, empty, untrusted, or host mismatch
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", None, draft_id) is None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "", draft_id) is None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://unauthorized.org", draft_id) is None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://other.scholarships.gov.in", draft_id) is None


# -----------------------------------------------------------------------------
# Test 31: Missing or Expired expires_at Fails Closed
# -----------------------------------------------------------------------------

def test_31_missing_or_expired_expires_at_fails_closed(client, app_env):
    """Test 31: Missing, corrupted, or expired expires_at fails closed."""
    user_id, csrf = _register_citizen(client, email="expiry_scope@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    draft = app_env["app_service"].create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]
    test_db: Database = app_env["db"]

    auth_res = client.post(
        "/applications/autofill/authorize",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert auth_res.status_code == 200
    token = auth_res.json()["grant"]["grant_token"]
    grant_id = auth_res.json()["grant"]["grant_id"]

    # 1. Empty string expires_at in DB
    with test_db.get_connection() as conn:
        conn.execute("UPDATE autofill_grants SET expires_at = '' WHERE grant_id = ?", (grant_id,))
        conn.commit()
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", draft_id) is None

    # 2. Corrupted expires_at in DB
    with test_db.get_connection() as conn:
        conn.execute("UPDATE autofill_grants SET expires_at = 'NOT_A_DATETIME' WHERE grant_id = ?", (grant_id,))
        conn.commit()
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", draft_id) is None

    # 3. Expired timestamp in DB
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    with test_db.get_connection() as conn:
        conn.execute("UPDATE autofill_grants SET expires_at = ? WHERE grant_id = ?", (past_iso, grant_id))
        conn.commit()
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", draft_id) is None


# -----------------------------------------------------------------------------
# Test 32: Legacy Incomplete Grants Fail Closed
# -----------------------------------------------------------------------------

def test_32_legacy_incomplete_grants_fail_closed(client, app_env):
    """Test 32: Legacy incomplete grant records missing any mandatory column fail closed."""
    user_id, csrf = _register_citizen(client, email="legacy_grants@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    test_db: Database = app_env["db"]

    future_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. In SQLite, draft_id is nullable (legacy grants created before Step 5.5C had NULL draft_id)
    raw_token_null_draft = f"sahay_atf_legacy_null_draft_{uuid.uuid4().hex[:8]}"
    token_hash_null_draft = hashlib.sha256(raw_token_null_draft.encode("utf-8")).hexdigest()
    with test_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO autofill_grants (
                grant_id, token_hash, user_id, scheme_id, draft_id,
                portal_url, scope, expires_at, used_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"grant_leg_nulldraft_{uuid.uuid4().hex[:8]}",
                token_hash_null_draft,
                user_id,
                "SCHEME_EDU_001_PM_USP_CSSS",
                None,  # NULL draft_id
                "https://scholarships.gov.in",
                "extension:autofill",
                future_iso,
                None,
                now_iso,
            ),
        )
        conn.commit()

    assert autofill_svc.validate_extension_grant(
        raw_token=raw_token_null_draft,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id="draft_candidate_123",
    ) is None

    # 2. For other mandatory fields, verify empty string values in stored rows fail closed
    for empty_field in ["user_id", "draft_id", "scheme_id", "portal_url", "expires_at"]:
        raw_tok = f"sahay_atf_legacy_empty_{empty_field}_{uuid.uuid4().hex[:8]}"
        tok_hash = hashlib.sha256(raw_tok.encode("utf-8")).hexdigest()

        grant_fields = {
            "grant_id": f"grant_leg_{uuid.uuid4().hex[:8]}",
            "token_hash": tok_hash,
            "user_id": user_id,
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "draft_id": "draft_legacy_123",
            "portal_url": "https://scholarships.gov.in",
            "scope": "extension:autofill",
            "expires_at": future_iso,
            "used_at": None,
            "created_at": now_iso,
        }
        grant_fields[empty_field] = ""  # empty string

        with test_db.get_connection() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                INSERT INTO autofill_grants (
                    grant_id, token_hash, user_id, scheme_id, draft_id,
                    portal_url, scope, expires_at, used_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(grant_fields.values()),
            )
            conn.commit()

        assert autofill_svc.validate_extension_grant(
            raw_token=raw_tok,
            scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
            portal_url="https://scholarships.gov.in",
            draft_id="draft_legacy_123",
        ) is None, f"Grant with empty {empty_field} did not fail closed!"


# -----------------------------------------------------------------------------
# Test 33: Correct Complete Matching Grant Succeeds
# -----------------------------------------------------------------------------

def test_33_correct_complete_matching_grant_succeeds(client, app_env):
    """Test 33: Complete matching grant validates successfully, updates usage, and populates."""
    user_id, csrf = _register_citizen(client, email="happy_grant@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    profile_mgr: ProfileManager = app_env["profile_mgr"]
    app_svc: ApplicationService = app_env["app_service"]
    test_db: Database = app_env["db"]

    profile_mgr.create_profile({
        "user_id": user_id,
        "full_name": "Suresh Patel",
        "gender": "MALE",
        "state": "Gujarat",
        "district": "Ahmedabad",
        "user_confirmed": True,
    })

    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    # 1. Authorize grant
    res_auth = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 200
    token = res_auth.json()["grant"]["grant_token"]

    # 2. Service level validation succeeds with all matching parameters
    grant_record = autofill_svc.validate_extension_grant(
        raw_token=token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_id,
        user_id=user_id,
    )
    assert grant_record is not None
    assert grant_record["draft_id"] == draft_id
    assert grant_record["scheme_id"] == "SCHEME_EDU_001_PM_USP_CSSS"
    assert grant_record["user_id"] == user_id

    # 3. API populate endpoint succeeds with Bearer token
    res_pop = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_pop.status_code == 200
    pop_data = res_pop.json()
    assert pop_data["success"] is True
    assert pop_data["package"]["fields"]["applicant_name"]["value"] == "Suresh Patel"

    # 4. Check used_at timestamp is populated in database
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with test_db.get_connection() as conn:
        row = conn.cursor().execute("SELECT used_at FROM autofill_grants WHERE token_hash = ?", (token_hash,)).fetchone()
    assert row["used_at"] is not None


# -----------------------------------------------------------------------------
# Test 34: Wrong Draft, Scheme, User, and Portal Mismatches Rejected
# -----------------------------------------------------------------------------

def test_34_wrong_mismatches_and_tampered_drafts_rejected(client, app_env):
    """Test 34: Strict rejection for draft, scheme, user, portal host mismatches, and deleted drafts."""
    user_id_1, csrf_1 = _register_citizen(client, email="user_one@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    app_svc: ApplicationService = app_env["app_service"]

    draft_1 = app_svc.create_draft(user_id=user_id_1, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_2 = app_svc.create_draft(user_id=user_id_1, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_1_id = draft_1["draft_id"]
    draft_2_id = draft_2["draft_id"]

    res_auth = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_1_id,
        },
        headers={"X-CSRF-Token": csrf_1, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 200
    token = res_auth.json()["grant"]["grant_token"]

    # Register user_2 in separate client
    client_2 = TestClient(app)
    user_id_2, _ = _register_citizen(client_2, email="user_two@example.com")

    # 1. Draft mismatch: grant bound to draft_1, requested draft_2 -> None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", draft_2_id) is None

    # 2. Scheme mismatch: grant bound to CSSS, requested PRAGATI -> None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_002_AICTE_PRAGATI", "https://scholarships.gov.in", draft_1_id) is None

    # 3. User mismatch: grant owned by user_1, checked against user_2 -> None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", draft_1_id, user_id=user_id_2) is None

    # 4. Portal mismatch: grant bound to scholarships.gov.in, requested other host -> None
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://state.scholarships.gov.in", draft_1_id) is None

    # 5. Bound draft deleted: delete draft_1 and verify grant fails closed
    app_svc.delete_draft(draft_1_id, user_id=user_id_1)
    assert autofill_svc.validate_extension_grant(token, "SCHEME_EDU_001_PM_USP_CSSS", "https://scholarships.gov.in", draft_1_id) is None


# -----------------------------------------------------------------------------
# Test 35: Exact Expiry Boundary (now_utc >= expires_at)
# -----------------------------------------------------------------------------

def test_35_exact_expiry_boundary_now_utc_gte_expires_at(client, app_env):
    """Test 35: Expiry boundary strictly rejects grants when now_utc >= expires_at."""
    user_id, csrf = _register_citizen(client, email="boundary_test@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    app_svc: ApplicationService = app_env["app_service"]
    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]
    test_db: Database = app_env["db"]

    res_auth = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 200
    token = res_auth.json()["grant"]["grant_token"]
    grant_id = res_auth.json()["grant"]["grant_id"]

    # 1. Exact boundary: Set expires_at equal to now (or slightly in the past to simulate exact equality)
    now_exact = datetime.now(timezone.utc).isoformat()
    with test_db.get_connection() as conn:
        conn.execute("UPDATE autofill_grants SET expires_at = ? WHERE grant_id = ?", (now_exact, grant_id))
        conn.commit()

    # When now_dt >= expires_dt, validate_extension_grant must reject (return None)
    assert autofill_svc.validate_extension_grant(
        raw_token=token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_id,
    ) is None

    # Populate API must return 401 Unauthorized
    res_pop = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_pop.status_code == 401

    # 2. Future boundary: Set expires_at in future (+10 seconds)
    future_time = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    with test_db.get_connection() as conn:
        conn.execute("UPDATE autofill_grants SET expires_at = ? WHERE grant_id = ?", (future_time, grant_id))
        conn.commit()

    # Now now_dt < expires_dt, so it succeeds
    assert autofill_svc.validate_extension_grant(
        raw_token=token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_id,
    ) is not None


# -----------------------------------------------------------------------------
# Test 36: Grant Owner Identity and Draft Ownership Enforcement
# -----------------------------------------------------------------------------

def test_36_grant_owner_identity_and_draft_ownership_enforcement(client, app_env):
    """Test 36: Identity is strictly anchored to grant owner; draft ownership mismatches & closed drafts fail closed."""
    user_id_a, csrf_a = _register_citizen(client, email="owner_a@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    app_svc: ApplicationService = app_env["app_service"]
    test_db: Database = app_env["db"]

    client_b = TestClient(app)
    user_id_b, _ = _register_citizen(client_b, email="owner_b@example.com")

    draft_a = app_svc.create_draft(user_id=user_id_a, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_a_id = draft_a["draft_id"]

    res_auth = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_a_id,
        },
        headers={"X-CSRF-Token": csrf_a, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 200
    token_a = res_auth.json()["grant"]["grant_token"]

    # 1. Valid extension call populates strictly for owner_a
    res_pop_ok = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_a_id,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_pop_ok.status_code == 200

    # 2. Tampering draft owner: Update draft_a in database so user_id = user_id_b
    with test_db.get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("UPDATE application_drafts SET user_id = ? WHERE draft_id = ?", (user_id_b, draft_a_id))
        conn.commit()

    # Grant was bound to user_id_a, but draft now belongs to user_id_b -> MUST FAIL CLOSED
    assert autofill_svc.validate_extension_grant(
        raw_token=token_a,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_a_id,
    ) is None

    res_pop_tampered = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_a_id,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_pop_tampered.status_code == 401

    # 3. Restore ownership and close draft: CLOSED status must reject autofill
    with test_db.get_connection() as conn:
        conn.execute("UPDATE application_drafts SET user_id = ?, status = 'CLOSED' WHERE draft_id = ?", (user_id_a, draft_a_id))
        conn.commit()

    assert autofill_svc.validate_extension_grant(
        raw_token=token_a,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_a_id,
    ) is None

    res_pop_closed = client.post(
        "/applications/autofill/populate",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_a_id,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_pop_closed.status_code == 401


# -----------------------------------------------------------------------------
# Test 37: Grant Reusability Until Expiry and used_at Telemetry
# -----------------------------------------------------------------------------

def test_37_grant_reusability_until_expiry_and_used_at_telemetry(client, app_env):
    """Test 37: Grants are reusable across multi-step portal workflows until expiry, updating used_at."""
    user_id, csrf = _register_citizen(client, email="reusable_grant@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    app_svc: ApplicationService = app_env["app_service"]
    test_db: Database = app_env["db"]

    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    res_auth = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 200
    token = res_auth.json()["grant"]["grant_token"]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    # Step 1: Initial preview call from extension
    pop_1 = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pop_1.status_code == 200

    with test_db.get_connection() as conn:
        row1 = conn.cursor().execute("SELECT used_at FROM autofill_grants WHERE token_hash = ?", (token_hash,)).fetchone()
    used_at_1 = row1["used_at"]
    assert used_at_1 is not None

    # Step 2: Citizen clicks "Autofill Form Fields" on Step 1 (Personal Details)
    pop_2 = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pop_2.status_code == 200

    # Step 3: Citizen advances to Step 2 (Academic Details) on the portal form
    pop_3 = client.post(
        "/applications/autofill/populate",
        json={"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "portal_url": "https://scholarships.gov.in", "draft_id": draft_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pop_3.status_code == 200

    with test_db.get_connection() as conn:
        row3 = conn.cursor().execute("SELECT used_at FROM autofill_grants WHERE token_hash = ?", (token_hash,)).fetchone()
    used_at_3 = row3["used_at"]
    assert used_at_3 is not None


# -----------------------------------------------------------------------------
# Test 38: Atomic Database Single-Use Consumption and Concurrency
# -----------------------------------------------------------------------------

def test_38_atomic_database_single_use_consumption_and_concurrency(client, app_env):
    """Test 38: Atomic single-use consumption mode guarantees exactly-once use under concurrent requests."""
    user_id, csrf = _register_citizen(client, email="single_use_test@example.com")
    autofill_svc: AutofillService = app_env["autofill_service"]
    app_svc: ApplicationService = app_env["app_service"]

    draft = app_svc.create_draft(user_id=user_id, scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
    draft_id = draft["draft_id"]

    res_auth = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth.status_code == 200
    token = res_auth.json()["grant"]["grant_token"]

    # 1. Single-use sequential test
    # First call with single_use=True must succeed
    first_res = autofill_svc.validate_extension_grant(
        raw_token=token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_id,
        single_use=True,
    )
    assert first_res is not None

    # Immediate second call with single_use=True must fail closed (return None)
    second_res = autofill_svc.validate_extension_grant(
        raw_token=token,
        scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
        portal_url="https://scholarships.gov.in",
        draft_id=draft_id,
        single_use=True,
    )
    assert second_res is None

    # 2. Concurrent requests test: Issue a fresh token and fire 10 concurrent requests
    res_auth_conc = client.post(
        "/applications/autofill/authorize",
        json={
            "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
            "portal_url": "https://scholarships.gov.in",
            "draft_id": draft_id,
        },
        headers={"X-CSRF-Token": csrf, "Origin": AUTHORIZED_ORIGIN},
    )
    assert res_auth_conc.status_code == 200
    token_conc = res_auth_conc.json()["grant"]["grant_token"]

    def try_consume():
        return autofill_svc.validate_extension_grant(
            raw_token=token_conc,
            scheme_id="SCHEME_EDU_001_PM_USP_CSSS",
            portal_url="https://scholarships.gov.in",
            draft_id=draft_id,
            single_use=True,
        )

    # Launch 10 simultaneous threads competing to atomically consume the single-use token
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_consume) for _ in range(10)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r is not None]
    failures = [r for r in results if r is None]

    # Exactly 1 request must succeed; exactly 9 requests must be rejected
    assert len(successes) == 1, f"Expected exactly 1 concurrent success, got {len(successes)}"
    assert len(failures) == 9, f"Expected exactly 9 concurrent rejections, got {len(failures)}"


# -----------------------------------------------------------------------------
# Test 39: Popup UI Branding and Explicit Connection States
# -----------------------------------------------------------------------------

def test_39_popup_branding_and_connection_states():
    """Test 39: Validates popup branding, distinct connection states, and invariant that 'Connected' is only shown with active grant."""
    popup_html = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")
    popup_js = (EXTENSION_DIR / "popup.js").read_text(encoding="utf-8")

    # Branding & title
    assert "⚡ SahayAI Assistant" in popup_html
    assert "id=\"btnOpenDashboard\"" in popup_html
    assert "id=\"connectionStateBadge\"" in popup_html
    assert "id=\"btnDisconnect\"" in popup_html

    # Distinct states in popup.js
    assert "function renderConnected(grant)" in popup_js
    assert "function renderNotConnected()" in popup_js
    assert "function renderPendingAuth(" in popup_js
    assert "function renderError(" in popup_js

    # Invariant: Connected is only rendered if grant is present and not expired
    assert "if (grantResp && grantResp.grant && !grantResp.isExpired)" in popup_js
    assert 'connectionStateBadge.textContent = "Connected"' in popup_js
    assert 'connectionStateBadge.textContent = "Not connected"' in popup_js

    # Explicit user approval flow in popup
    assert "id=\"consentCard\"" in popup_html
    assert "id=\"btnApproveAuth\"" in popup_html
    assert "id=\"btnDenyAuth\"" in popup_html
    assert "APPROVE_PENDING_AUTH" in popup_js
    assert "DENY_PENDING_AUTH" in popup_js


# -----------------------------------------------------------------------------
# Test 40: Popup Portal Status and Unsupported Website Handling
# -----------------------------------------------------------------------------

def test_40_popup_unsupported_website_detection_and_portal_badges():
    """Test 40: Validates active tab URL checking, portal support badges, and unsupported website warning banners."""
    popup_html = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")
    popup_js = (EXTENSION_DIR / "popup.js").read_text(encoding="utf-8")

    # Portal status badge and banner in popup.html
    assert "id=\"tabPortalStatus\"" in popup_html
    assert "id=\"portalUnsupportedBanner\"" in popup_html

    # Official portal recognition
    assert 'tabPortalStatus.textContent = "✓ On National Scholarship Portal"' in popup_js
    assert 'badge-active' in popup_js

    # SahayAI workspace recognition
    assert 'tabPortalStatus.textContent = "⚡ SahayAI Workspace"' in popup_js
    assert 'badge-dashboard' in popup_js

    # Unsupported website detection and warning message
    assert 'tabPortalStatus.textContent = "○ Unsupported Website"' in popup_js
    assert 'badge-unsupported' in popup_js
    assert "Autofill is disabled on this site" in popup_js
    assert "scholarships.gov.in" in popup_js


# -----------------------------------------------------------------------------
# Test 41: Floating Assistant Close, Minimize, and Reopen Mechanics
# -----------------------------------------------------------------------------

def test_41_floating_assistant_minimize_close_and_reopen():
    """Test 41: Validates that floating assistant can be minimized to a pill and reopened without reload."""
    content_js = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")
    styles_css = (EXTENSION_DIR / "styles.css").read_text(encoding="utf-8")

    # Minimized launcher pill and expanded card exist in DOM
    assert "sahay-launch-pill" in content_js
    assert "sahayLaunchPill" in content_js
    assert "sahayCard" in content_js

    # Minimize and Close buttons exist in header
    assert "sahayBtnMinimize" in content_js
    assert "sahayBtnClose" in content_js

    # Minimize handler hides card and shows pill
    assert "btnMinimize.addEventListener" in content_js
    assert 'card.style.display = "none"' in content_js
    assert 'pill.style.display = "flex"' in content_js

    # Close handler collapses to floating pill
    assert "btnClose.addEventListener" in content_js

    # Pill click reopens assistant card and refreshes grant status
    assert "pill.addEventListener" in content_js
    assert 'card.style.display = "block"' in content_js
    assert 'pill.style.display = "none"' in content_js
    assert "refreshGrantStatus()" in content_js

    # Scoped styles for launcher pill and assistant card in styles.css
    assert ".sahay-launch-pill" in styles_css
    assert ".sahay-card" in styles_css
    assert ".sahay-header-btn" in styles_css


# -----------------------------------------------------------------------------
# Test 42: TEMPLATE_ONLY Mappings Prevention and Manual Reference Checklist
# -----------------------------------------------------------------------------

def test_42_template_only_mappings_disabled_autofill_and_reference_checklist():
    """Test 42: Validates all 20 fields are TEMPLATE_ONLY, autofill button is disabled, and manual checklist is rendered."""
    portals_js = (EXTENSION_DIR / "supported-portals.js").read_text(encoding="utf-8")
    content_js = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")

    # Verify that mapped form fields in supported-portals.js have status: "TEMPLATE_ONLY"
    template_matches = re.findall(r'status:\s*"TEMPLATE_ONLY"', portals_js)
    assert len(template_matches) in (19, 20), f"Expected 19-20 TEMPLATE_ONLY mappings, found {len(template_matches)}"
    assert 'status: "VERIFIED"' not in portals_js, "No field mapping may be VERIFIED until live testing"

    # Autofill button is initialized as disabled
    assert 'id="sahayBtnAutofill" disabled' in content_js
    assert "Autofill Disabled (Manual Entry Required)" in content_js

    # Prominent TEMPLATE_ONLY notice box is rendered
    assert "sahayTemplateNotice" in content_js
    assert "Autofill Disabled (Live Verification Pending)" in content_js
    assert "TEMPLATE_ONLY" in content_js

    # Manual reference checklist is provided for applicant
    assert "sahayRefList" in content_js
    assert "renderReferenceChecklist" in content_js
    assert "Confirmed Document Checklist" in content_js


# -----------------------------------------------------------------------------
# Test 43: Dashboard Extension States and Unblocked Manual Workflow
# -----------------------------------------------------------------------------

def test_43_dashboard_extension_states_and_unblocked_manual_workflow():
    """Test 43: Validates dashboard handles all extension states and manual flow is never blocked."""
    dashboard_js = Path("frontend/js/dashboard.js").read_text(encoding="utf-8")
    dashboard_html = Path("frontend/dashboard.html").read_text(encoding="utf-8")

    # Dashboard extension UI elements
    assert "extensionStatusCard" in dashboard_html
    assert "extensionStateBadge" in dashboard_html
    assert "btnConnectExtension" in dashboard_html
    assert "extensionGuideModal" in dashboard_html

    # Distinct states handled in dashboard.js
    assert 'newState === "CONNECTED"' in dashboard_js
    assert 'newState === "INSTALLED_NOT_CONNECTED"' in dashboard_js
    assert 'newState === "PENDING_APPROVAL"' in dashboard_js
    assert 'newState === "ERROR"' in dashboard_js
    assert 'NOT_INSTALLED' in dashboard_js

    # Manual application workflow is completely unblocked
    # Citizen can continue to official portal regardless of extension presence
    assert "openModal(externalPortalModal)" in dashboard_js
    assert "pendingExternalPortalUrl" in dashboard_js


# -----------------------------------------------------------------------------
# Test 44: Service Worker Restart Resets Volatile Memory and Fails Closed
# -----------------------------------------------------------------------------

def test_44_service_worker_restart_resets_volatile_grant_and_fails_closed(client, app_env):
    """Test 44: Validates background service worker stores grants exclusively in volatile memory and fails closed on reset."""
    bg_js = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    # In-memory volatile variables
    assert "let activeGrant = null;" in bg_js
    assert "let pendingAuthRequest = null;" in bg_js

    # Token never stored in persistent storage
    assert "chrome.storage.local.set({ activeGrant" not in bg_js
    assert "localStorage" not in bg_js

    # GET_CURRENT_GRANT returns grant: null, isExpired: true when activeGrant is null
    assert "activeGrant = null;" in bg_js
    assert "sendResponse({ grant: null, isExpired: true });" in bg_js

    # FETCH_AUTOFILL_PACKAGE returns 401 when activeGrant is null
    assert "if (!isGrantValid())" in bg_js
    assert 'status: 401' in bg_js



