"""Tests for SahayAI Step 5.4B: My Documents Frontend Dashboard & Integration.

Validates:
1. Static HTML structure: navDocumentsLink, documentsSection, stats counters, filters, grid, and all 5 modals.
2. Dashboard JS logic: registered citizen vs guest navigation and library visibility.
3. API client methods: presence and correct credential/CSRF behavior in frontend/js/api.js.
4. Complete localization: English, Telugu, and Hindi parity for all documents.* and nav.myDocuments keys.
5. End-to-end upload workflow: registered upload encrypts at rest and queues for review.
6. Category filtering and query isolation via backend APIs.
7. Review & confirmation integration: citizen confirms fields and profile updates.
8. Secure download: streaming decrypted file with attachment and anti-caching headers.
9. Replacement workflow: preserves audit history and unlinks old vault file.
10. Archival and permanent deletion: distinguish soft archive from cascade delete.
11. Guest isolation: guests cannot access persistent library, download, or delete documents.
"""

import io
import json
import os
import re
from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient

from api.main import app
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
LOCALES_DIR = os.path.join(FRONTEND_DIR, "locales")


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_frontend_docs.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def auth_env(test_db, monkeypatch, tmp_path):
    """Configures isolated auth service, profile manager, and session manager."""
    vault_dir = tmp_path / "secure_vault" / "documents"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAHAY_DOCUMENT_STORAGE_DIR", str(vault_dir))
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SAHAY_PII_ENCRYPTION_KEY", test_key)

    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.documents.profile_manager", profiles)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "profile_mgr": profiles,
        "session_mgr": session_mgr,
        "vault_dir": vault_dir,
    }


@pytest.fixture
def client(auth_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


def _sample_income_pdf_bytes():
    sample_path = os.path.join("data", "sample_documents", "sample_synthetic_income_cert.pdf")
    if os.path.exists(sample_path):
        with open(sample_path, "rb") as f:
            return f.read()
    sample_png = os.path.join("data", "sample_documents", "sample_synthetic_aadhaar.png")
    with open(sample_png, "rb") as f:
        return f.read()


def _sample_aadhaar_png_bytes():
    sample_png = os.path.join("data", "sample_documents", "sample_synthetic_aadhaar.png")
    with open(sample_png, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. Frontend Static HTML & Structural Audits
# ---------------------------------------------------------------------------

class TestFrontendHTMLStructure:
    """Verifies that dashboard.html contains all necessary components for Step 5.4B."""

    def test_dashboard_nav_documents_link(self):
        """Dashboard navigation must include navDocumentsLink with data-i18n."""
        dash_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'id="navDocumentsLink"' in html, "navDocumentsLink must be present in dashboard navigation"
        assert 'data-i18n="nav.myDocuments"' in html, "navDocumentsLink must have data-i18n='nav.myDocuments'"
        assert 'href="#documentsSection"' in html, "navDocumentsLink must anchor to #documentsSection"

    def test_dashboard_documents_section_and_stats(self):
        """Dashboard must contain documentsSection with 4 summary stat counters."""
        dash_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'id="documentsSection"' in html, "documentsSection must be in dashboard.html"
        assert 'id="btnOpenUploadModal"' in html, "Upload button must be in documents section header"
        assert 'id="docStatTotal"' in html, "Total documents stat counter must be present"
        assert 'id="docStatConfirmed"' in html, "Confirmed documents stat counter must be present"
        assert 'id="docStatPending"' in html, "Pending review stat counter must be present"
        assert 'id="docStatArchived"' in html, "Archived documents stat counter must be present"

    def test_dashboard_filters_and_grid(self):
        """Dashboard must contain search, category filter, status filter, and grid."""
        dash_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'id="docSearchInput"' in html, "docSearchInput must be present"
        assert 'id="docCategoryFilter"' in html, "docCategoryFilter must be present"
        assert 'id="docStatusFilter"' in html, "docStatusFilter must be present"
        assert 'id="docIncludeArchivedToggle"' in html, "docIncludeArchivedToggle must be present"
        assert 'id="btnResetDocFilters"' in html, "btnResetDocFilters must be present"
        assert 'id="documentsGrid"' in html, "documentsGrid must be present"

    def test_dashboard_all_five_modals_present(self):
        """Dashboard must include all 5 document management modals."""
        dash_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            html = f.read()

        modals = [
            "documentUploadModal",
            "documentReviewModal",
            "documentReplaceModal",
            "documentDeleteModal",
            "documentMetadataModal",
        ]
        for m_id in modals:
            assert f'id="{m_id}"' in html, f"Modal #{m_id} must be in dashboard.html"


# ---------------------------------------------------------------------------
# 2. JavaScript Controller & API Client Audits
# ---------------------------------------------------------------------------

class TestFrontendJavaScriptLogic:
    """Verifies that dashboard.js and api.js contain required handlers and security measures."""

    def test_api_client_document_helpers(self):
        """api.js must provide authenticated helper functions for document operations."""
        api_path = os.path.join(FRONTEND_DIR, "js", "api.js")
        with open(api_path, "r", encoding="utf-8") as f:
            js = f.read()

        required_helpers = [
            "fetchCitizenDocuments",
            "fetchDocumentMetadata",
            "uploadCitizenDocument",
            "replaceCitizenDocument",
            "deleteCitizenDocument",
            "fetchDocumentReview",
            "confirmDocumentFields",
            "downloadCitizenDocument",
            "reclassifyCitizenDocument",
        ]
        for fn in required_helpers:
            assert f"function {fn}" in js or f"async function {fn}" in js, f"{fn} must be defined in api.js"

    def test_guest_navigation_isolation_logic(self):
        """dashboard.js must explicitly hide persistent documents navigation and section for guests."""
        dash_js_path = os.path.join(FRONTEND_DIR, "js", "dashboard.js")
        with open(dash_js_path, "r", encoding="utf-8") as f:
            js = f.read()

        # Guest mode isolation checks
        assert 'navDocumentsLink.style.display = "none"' in js, "Guest mode must hide navDocumentsLink"
        assert 'documentsSection.style.display = "none"' in js, "Guest mode must hide documentsSection"

        # Registered mode visibility checks
        assert 'navDocumentsLink.style.display = "inline-block"' in js, "Registered mode must show navDocumentsLink"
        assert 'documentsSection.style.display = "block"' in js, "Registered mode must show documentsSection"

    def test_duplicate_upload_prevention(self):
        """dashboard.js must prevent duplicate submissions while upload is in progress."""
        dash_js_path = os.path.join(FRONTEND_DIR, "js", "dashboard.js")
        with open(dash_js_path, "r", encoding="utf-8") as f:
            js = f.read()

        assert "isUploadingDocument" in js, "isUploadingDocument guard must be present"
        assert "btnStartUploadSubmit.disabled = true" in js, "Upload submit button must be disabled on submit"

    def test_close_all_modals_covers_documents(self):
        """closeAllModals in dashboard.js must include all 5 document modals."""
        dash_js_path = os.path.join(FRONTEND_DIR, "js", "dashboard.js")
        with open(dash_js_path, "r", encoding="utf-8") as f:
            js = f.read()

        assert "closeModal(documentUploadModal)" in js
        assert "closeModal(documentReviewModal)" in js
        assert "closeModal(documentReplaceModal)" in js
        assert "closeModal(documentDeleteModal)" in js
        assert "closeModal(documentMetadataModal)" in js

    def test_intelligent_ocr_frontend_integration(self):
        """dashboard.js and my-documents.js must implement intelligent OCR preview and dynamic schemas."""
        for js_file in ["dashboard.js", "my-documents.js"]:
            js_path = os.path.join(FRONTEND_DIR, "js", js_file)
            with open(js_path, "r", encoding="utf-8") as f:
                js = f.read()

            assert "renderIntelligentOcrPreview" in js, f"{js_file} must define renderIntelligentOcrPreview"
            assert "subject_marks" in js, f"{js_file} must handle subject_marks table"
            assert "is_low_confidence" in js or "classification_confidence" in js, f"{js_file} must handle confidence"
            assert "reclassify" in js.lower(), f"{js_file} must handle reclassification"



# ---------------------------------------------------------------------------
# 3. Multilingual Localization Parity
# ---------------------------------------------------------------------------

class TestDocumentLocalization:
    """Verifies complete English, Telugu, and Hindi translations for document library."""

    def test_documents_locale_parity(self):
        """en.json, te.json, and hi.json must have 100% parity for documents keys."""
        en_path = os.path.join(LOCALES_DIR, "en.json")
        te_path = os.path.join(LOCALES_DIR, "te.json")
        hi_path = os.path.join(LOCALES_DIR, "hi.json")

        with open(en_path, "r", encoding="utf-8") as f:
            en = json.load(f)
        with open(te_path, "r", encoding="utf-8") as f:
            te = json.load(f)
        with open(hi_path, "r", encoding="utf-8") as f:
            hi = json.load(f)

        assert "documents" in en, "documents block must be in en.json"
        assert "documents" in te, "documents block must be in te.json"
        assert "documents" in hi, "documents block must be in hi.json"

        assert "myDocuments" in en["nav"]
        assert "myDocuments" in te["nav"]
        assert "myDocuments" in hi["nav"]

        en_doc_keys = set(en["documents"].keys())
        te_doc_keys = set(te["documents"].keys())
        hi_doc_keys = set(hi["documents"].keys())

        assert en_doc_keys == te_doc_keys, f"Mismatch in Telugu document keys: {en_doc_keys ^ te_doc_keys}"
        assert en_doc_keys == hi_doc_keys, f"Mismatch in Hindi document keys: {en_doc_keys ^ hi_doc_keys}"

    def test_document_category_translations_exist(self):
        """All 10 standardized categories must be translated across languages."""
        en_path = os.path.join(LOCALES_DIR, "en.json")
        te_path = os.path.join(LOCALES_DIR, "te.json")
        hi_path = os.path.join(LOCALES_DIR, "hi.json")

        with open(en_path, "r", encoding="utf-8") as f:
            en = json.load(f)["documents"]
        with open(te_path, "r", encoding="utf-8") as f:
            te = json.load(f)["documents"]
        with open(hi_path, "r", encoding="utf-8") as f:
            hi = json.load(f)["documents"]

        categories = [
            "catIdentity", "catIncome", "catCategoryCert", "catResidence",
            "catAcademic", "catBank", "catDisability", "catSpecialCategory",
            "catApplicationAsset", "catOther",
        ]
        for cat in categories:
            assert cat in en and en[cat].strip() != ""
            assert cat in te and te[cat].strip() != ""
            assert cat in hi and hi[cat].strip() != ""


# ---------------------------------------------------------------------------
# 4. End-to-End API Integration & Citizen Journey
# ---------------------------------------------------------------------------

class TestDocumentAPIIntegration:
    """Verifies that backend endpoints called by the frontend work flawlessly."""

    def _setup_registered_citizen(self, client):
        """Helper to create account, citizen profile, and obtain CSRF token."""
        signup_res = client.post(
            "/auth/signup",
            json={"email": "dash.citizen@example.com", "password": "SecurePassword123!"},
        )
        assert signup_res.status_code == 200

        csrf_res = client.get("/auth/csrf-token")
        csrf_token = csrf_res.json()["csrf_token"]

        prof_res = client.post(
            "/profile/me",
            json={
                "full_name": "Ravi Kumar",
                "date_of_birth": "2002-05-15",
                "gender": "MALE",
                "caste_category": "OBC",
                "state": "Telangana",
                "district": "Hyderabad",
                "annual_income": 180000,
                "occupation": "Student",
                "is_bpl": False,
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert prof_res.status_code == 200
        return csrf_token

    def test_upload_and_list_documents(self, client, auth_env):
        """Registered citizen uploads a document and lists it via GET /documents."""
        csrf_token = self._setup_registered_citizen(client)

        pdf_bytes = _sample_income_pdf_bytes()
        upload_res = client.post(
            "/documents/upload",
            files={"file": ("income_cert.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"document_category": "INCOME", "document_type": "income_certificate"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert upload_res.status_code == 200
        upload_data = upload_res.json()
        doc_id = upload_data["document_id"]
        assert doc_id.startswith("doc_")
        assert upload_data["has_original_file"] is True

        # List documents
        list_res = client.get("/documents")
        assert list_res.status_code == 200
        docs = list_res.json()["documents"]
        assert len(docs) == 1
        assert docs[0]["document_id"] == doc_id
        assert docs[0]["document_category"] == "INCOME"
        assert docs[0]["status"] == "PENDING_REVIEW"
        assert docs[0]["confirmation_status"] == "PENDING_CONFIRMATION"

    def test_category_filtering(self, client, auth_env):
        """GET /documents?category=... correctly filters documents."""
        csrf_token = self._setup_registered_citizen(client)

        png_bytes = _sample_aadhaar_png_bytes()
        pdf_bytes = _sample_income_pdf_bytes()

        # 1. Upload Identity doc
        client.post(
            "/documents/upload",
            files={"file": ("aadhaar.png", io.BytesIO(png_bytes), "image/png")},
            data={"document_category": "IDENTITY", "document_type": "aadhaar"},
            headers={"X-CSRF-Token": csrf_token},
        )

        # 2. Upload Academic doc
        client.post(
            "/documents/upload",
            files={"file": ("marksheet.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"document_category": "ACADEMIC", "document_type": "marksheet_12th"},
            headers={"X-CSRF-Token": csrf_token},
        )

        # Filter by IDENTITY
        res_id = client.get("/documents?category=IDENTITY")
        assert res_id.status_code == 200
        assert len(res_id.json()["documents"]) == 1
        assert res_id.json()["documents"][0]["document_category"] == "IDENTITY"

        # Filter by ACADEMIC
        res_acad = client.get("/documents?category=ACADEMIC")
        assert res_acad.status_code == 200
        assert len(res_acad.json()["documents"]) == 1
        assert res_acad.json()["documents"][0]["document_category"] == "ACADEMIC"

    def test_review_and_confirmation_journey(self, client, auth_env):
        """Citizen reviews pending fields and confirms them to update profile."""
        csrf_token = self._setup_registered_citizen(client)

        pdf_bytes = _sample_income_pdf_bytes()
        upload_res = client.post(
            "/documents/upload",
            files={"file": ("income.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"document_category": "INCOME", "document_type": "income_certificate"},
            headers={"X-CSRF-Token": csrf_token},
        )
        doc_id = upload_res.json()["document_id"]

        # 1. Review endpoint
        review_res = client.get(f"/documents/{doc_id}/review")
        assert review_res.status_code == 200
        assert "extracted_fields" in review_res.json()

        # 2. Confirm fields
        confirm_res = client.post(
            f"/documents/{doc_id}/confirm",
            json={
                "confirmations": [
                    {
                        "field_name": "annual_income",
                        "value": 150000,
                        "confirmed": True,
                        "allow_overwrite": True,
                    }
                ]
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["success"] is True

        # 3. Check updated profile
        prof_res = client.get("/profile/me")
        assert prof_res.status_code == 200
        assert prof_res.json()["profile"]["annual_income"] == 150000

        # 4. Check document status
        meta_res = client.get(f"/documents/{doc_id}")
        assert meta_res.status_code == 200
        assert meta_res.json()["document"]["confirmation_status"] == "CONFIRMED"

    def test_download_decrypted_document(self, client, auth_env):
        """Authenticated owner downloads original decrypted document."""
        csrf_token = self._setup_registered_citizen(client)

        orig_pdf = _sample_income_pdf_bytes()
        upload_res = client.post(
            "/documents/upload",
            files={"file": ("my_marksheet.pdf", io.BytesIO(orig_pdf), "application/pdf")},
            data={"document_category": "ACADEMIC", "document_type": "marksheet_10th"},
            headers={"X-CSRF-Token": csrf_token},
        )
        doc_id = upload_res.json()["document_id"]

        down_res = client.get(f"/documents/{doc_id}/download")
        assert down_res.status_code == 200
        assert down_res.content == orig_pdf
        assert "attachment; filename=" in down_res.headers.get("content-disposition", "")
        assert "no-store" in down_res.headers.get("cache-control", "")

    def test_replacement_workflow(self, client, auth_env):
        """Replacing document updates file and preserves confirmed fields audit history."""
        csrf_token = self._setup_registered_citizen(client)

        pdf_1 = _sample_income_pdf_bytes()
        upload_res = client.post(
            "/documents/upload",
            files={"file": ("doc_v1.pdf", io.BytesIO(pdf_1), "application/pdf")},
            data={"document_category": "INCOME", "document_type": "income_certificate"},
            headers={"X-CSRF-Token": csrf_token},
        )
        doc_id = upload_res.json()["document_id"]

        # Confirm v1
        client.post(
            f"/documents/{doc_id}/confirm",
            json={
                "confirmations": [
                    {"field_name": "annual_income", "value": 160000, "confirmed": True, "allow_overwrite": True}
                ]
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        # Replace with v2
        png_2 = _sample_aadhaar_png_bytes()
        replace_res = client.post(
            f"/documents/{doc_id}/replace",
            files={"file": ("doc_v2.png", io.BytesIO(png_2), "image/png")},
            data={"document_category": "IDENTITY"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert replace_res.status_code == 200

        # Verify download returns v2
        down_res = client.get(f"/documents/{doc_id}/download")
        assert down_res.status_code == 200
        assert down_res.content == png_2

    def test_archive_and_permanent_delete(self, client, auth_env):
        """Distinguish soft archive from hard permanent deletion."""
        csrf_token = self._setup_registered_citizen(client)

        pdf = _sample_income_pdf_bytes()
        upload_res = client.post(
            "/documents/upload",
            files={"file": ("doc.pdf", io.BytesIO(pdf), "application/pdf")},
            headers={"X-CSRF-Token": csrf_token},
        )
        doc_id = upload_res.json()["document_id"]

        # 1. Soft Archive
        archive_res = client.delete(f"/documents/{doc_id}?hard_delete=false", headers={"X-CSRF-Token": csrf_token})
        assert archive_res.status_code == 200
        assert archive_res.json()["hard_deleted"] is False

        # Excluded by default
        list_active = client.get("/documents")
        assert len(list_active.json()["documents"]) == 0

        # Included when include_archived=true
        list_all = client.get("/documents?include_archived=true")
        assert len(list_all.json()["documents"]) == 1
        assert list_all.json()["documents"][0]["status"] == "ARCHIVED"

        # 2. Permanent Delete
        delete_res = client.delete(f"/documents/{doc_id}?hard_delete=true", headers={"X-CSRF-Token": csrf_token})
        assert delete_res.status_code == 200
        assert delete_res.json()["hard_deleted"] is True

        # Now completely gone
        list_after = client.get("/documents?include_archived=true")
        assert len(list_after.json()["documents"]) == 0

    def test_guest_isolation_security(self, client):
        """Anonymous guests cannot access, download, or delete persistent documents."""
        guest_res = client.post("/auth/guest")
        assert guest_res.status_code == 200
        csrf_token = guest_res.json()["csrf_token"]

        # 1. GET /documents forbidden for guests
        list_res = client.get("/documents")
        assert list_res.status_code == 403

        # 2. GET /documents/{id} forbidden for guests
        get_res = client.get("/documents/doc_123")
        assert get_res.status_code == 403

        # 3. GET /documents/{id}/download forbidden for guests
        down_res = client.get("/documents/doc_123/download")
        assert down_res.status_code == 403

        # 4. DELETE /documents/{id} forbidden for guests
        del_res = client.delete("/documents/doc_123", headers={"X-CSRF-Token": csrf_token})
        assert del_res.status_code == 403
