"""Tests for SahayAI Profile Icon, My Profile & My Documents Navigation.

Verifies:
1. Static HTML structure across dashboard.html, my-profile.html, and my-documents.html:
   - Profile icon and circular dropdown menu with My Profile, My Documents, and Logout.
   - Citizen Profile Summary moved to my-profile.html with demographic fields and confirmed document records.
   - Document Library moved to my-documents.html with 4 stats, filters, grid, and all 5 modals.
   - Cleaned homepage flow in dashboard.html.
2. Localization consistency across en.json, te.json, hi.json, and i18n.js.
3. JavaScript controller and API integration integrity.
"""

import os
import json
import pytest
from fastapi.testclient import TestClient
from api.main import app

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


# ---------------------------------------------------------------------------
# 1. Dashboard Homepage Navigation & Clean Flow Tests
# ---------------------------------------------------------------------------

class TestDashboardNavigationProfileMenu:
    """Verifies that dashboard.html integrates the profile dropdown and cleans homepage flow."""

    def test_dashboard_profile_icon_and_dropdown_elements(self):
        dash_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'id="profileMenuContainer"' in html, "profileMenuContainer must be present in dashboard.html"
        assert 'id="profileIconBtn"' in html, "profileIconBtn circular button must be in dashboard.html"
        assert 'id="profileDropdownMenu"' in html, "profileDropdownMenu must be in dashboard.html"
        assert 'href="my-profile.html"' in html, "Link to my-profile.html must be in dropdown"
        assert 'href="my-documents.html"' in html, "Link to my-documents.html must be in dropdown"
        assert 'id="dropdownLogoutItem"' in html, "dropdownLogoutItem must be in dropdown"
        assert 'id="dropdownCitizenName"' in html, "dropdownCitizenName header must be in dropdown"

    def test_dashboard_homepage_relocated_sections_clean_flow(self):
        """Profile summary and documents sections must be wrapped so they do not crowd homepage flow."""
        dash_path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'id="homepageCleanRelocatedSections"' in html, "homepageCleanRelocatedSections wrapper must exist"
        assert 'display: none !important;' in html, "wrapper must hide relocated sections from visible homepage flow"

        # Backward compatibility assertions: IDs must remain in DOM for test suite & null safety
        assert 'id="profileCardSection"' in html, "profileCardSection must still exist in DOM"
        assert 'id="documentsSection"' in html, "documentsSection must still exist in DOM"

    def test_dashboard_card_documents_navigates_to_my_documents(self):
        dash_js_path = os.path.join(FRONTEND_DIR, "js", "dashboard.js")
        with open(dash_js_path, "r", encoding="utf-8") as f:
            js = f.read()

        assert 'window.location.href = "my-documents.html"' in js, "cardDocuments click must navigate to my-documents.html"


# ---------------------------------------------------------------------------
# 2. Dedicated "My Profile" Page Tests
# ---------------------------------------------------------------------------

class TestMyProfilePage:
    """Verifies that my-profile.html displays all citizen demographics and confirmed fields."""

    def test_my_profile_html_structure(self):
        profile_path = os.path.join(FRONTEND_DIR, "my-profile.html")
        assert os.path.exists(profile_path), "frontend/my-profile.html must exist"

        with open(profile_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Navbar and dropdown
        assert 'id="profileMenuContainer"' in html
        assert 'id="profileIconBtn"' in html
        assert 'id="profileDropdownMenu"' in html
        assert 'href="dashboard.html"' in html

        # Return to Dashboard Breadcrumb
        assert 'data-i18n="nav.backToDashboard"' in html

        # Citizen Profile Demographic Fields
        assert 'id="profileCardSection"' in html
        assert 'id="dispFullName"' in html
        assert 'id="dispUserId"' in html
        assert 'id="dispAgeDob"' in html
        assert 'id="dispGender"' in html
        assert 'id="dispLocation"' in html
        assert 'id="dispIncome"' in html
        assert 'id="dispOccupation"' in html
        assert 'id="dispCaste"' in html
        assert 'id="dispBpl"' in html
        assert 'id="dispConfirmed"' in html

        # Confirmed Document Records
        assert 'id="confirmedFieldsSection"' in html
        assert 'id="confirmedFieldsContainer"' in html
        assert 'id="confirmedFieldsCountBadge"' in html
        assert "Authenticity Disclaimer" in html

        # Guest Protection Banner
        assert 'id="guestNoticeBanner"' in html

    def test_my_profile_js_controller(self):
        js_path = os.path.join(FRONTEND_DIR, "js", "my-profile.js")
        assert os.path.exists(js_path), "frontend/js/my-profile.js must exist"

        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        assert 'apiFetch("/auth/session-status")' in js
        assert 'apiFetch("/profile/me")' in js
        assert 'apiFetch("/profile/confirmed-document-fields' in js
        assert "SahayNav.initProfileDropdown" in js


# ---------------------------------------------------------------------------
# 3. Dedicated "My Documents" Page Tests
# ---------------------------------------------------------------------------

class TestMyDocumentsPage:
    """Verifies that my-documents.html provides full document management."""

    def test_my_documents_html_structure(self):
        docs_path = os.path.join(FRONTEND_DIR, "my-documents.html")
        assert os.path.exists(docs_path), "frontend/my-documents.html must exist"

        with open(docs_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Navbar & Profile Dropdown
        assert 'id="profileMenuContainer"' in html
        assert 'id="profileIconBtn"' in html
        assert 'id="profileDropdownMenu"' in html
        assert 'data-i18n="nav.backToDashboard"' in html

        # Documents Section Header & Upload Trigger
        assert 'id="documentsSection"' in html
        assert 'id="btnOpenUploadModal"' in html

        # 4 Summary Stats
        assert 'id="docStatTotal"' in html
        assert 'id="docStatConfirmed"' in html
        assert 'id="docStatPending"' in html
        assert 'id="docStatArchived"' in html

        # Search & Filters Toolbar
        assert 'id="docSearchInput"' in html
        assert 'id="docCategoryFilter"' in html
        assert 'id="docStatusFilter"' in html
        assert 'id="docIncludeArchivedToggle"' in html
        assert 'id="btnResetDocFilters"' in html
        assert 'id="documentsGrid"' in html

        # All 5 Document Modals
        modals = [
            "documentUploadModal",
            "documentReviewModal",
            "documentReplaceModal",
            "documentDeleteModal",
            "documentMetadataModal",
        ]
        for m_id in modals:
            assert f'id="{m_id}"' in html, f"Modal {m_id} must be present in my-documents.html"

    def test_my_documents_js_controller(self):
        js_path = os.path.join(FRONTEND_DIR, "js", "my-documents.js")
        assert os.path.exists(js_path), "frontend/js/my-documents.js must exist"

        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        assert "fetchCitizenDocuments" in js
        assert "uploadCitizenDocument" in js
        assert "fetchDocumentReview" in js
        assert "confirmDocumentFields" in js
        assert "replaceCitizenDocument" in js
        assert "deleteCitizenDocument" in js
        assert "downloadCitizenDocument" in js
        assert "fetchDocumentMetadata" in js
        assert "SahayNav.initProfileDropdown" in js


# ---------------------------------------------------------------------------
# 4. Shared Navigation & Dropdown Module Tests
# ---------------------------------------------------------------------------

class TestSharedNavigationScript:
    """Verifies that navigation.js correctly handles profile dropdown logic."""

    def test_navigation_js_implementation(self):
        nav_path = os.path.join(FRONTEND_DIR, "js", "navigation.js")
        assert os.path.exists(nav_path), "frontend/js/navigation.js must exist"

        with open(nav_path, "r", encoding="utf-8") as f:
            js = f.read()

        assert "initProfileDropdown" in js
        assert "Escape" in js, "Escape key handler must be implemented"
        assert "click" in js, "Outside click listener must be implemented"
        assert "aria-expanded" in js, "ARIA state management must be implemented"
        assert "setUserInfo" in js


# ---------------------------------------------------------------------------
# 5. Multilingual Localization Consistency Tests
# ---------------------------------------------------------------------------

class TestProfileMenuLocalization:
    """Verifies that new navigation keys are localized across English, Telugu, and Hindi."""

    @pytest.mark.parametrize("lang_code,expected_profile,expected_back", [
        ("en", "My Profile", "Back to Dashboard"),
        ("te", "నా ప్రొఫైల్", "డ్యాష్‌బోర్డ్‌కు వెళ్ళు"),
        ("hi", "मेरी प्रोफ़ाइल", "डैशबोर्ड पर वापस जाएं"),
    ])
    def test_locale_json_nav_keys(self, lang_code, expected_profile, expected_back):
        locale_path = os.path.join(FRONTEND_DIR, "locales", f"{lang_code}.json")
        with open(locale_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "nav" in data
        assert data["nav"].get("myProfile") == expected_profile
        assert data["nav"].get("backToDashboard") == expected_back

    def test_i18n_fallback_locales_include_new_keys(self):
        i18n_path = os.path.join(FRONTEND_DIR, "js", "i18n.js")
        with open(i18n_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert '"myProfile": "My Profile"' in content
        assert '"myProfile": "నా ప్రొఫైల్"' in content
        assert '"myProfile": "मेरी प्रोफ़ाइल"' in content

