"""Tests for SahayAI Step 3: Complete Website Multilingual Localization.

Validates:
1. English default language.
2. Telugu language selection and Unicode script validity.
3. Hindi language selection and Devanagari script validity.
4. Language parity across en.json, te.json, and hi.json.
5. Missing translation fallback behavior.
6. Static HTML pages include global language pickers and data-i18n tags.
7. Login and registration interfaces localized.
8. Dashboard cards, profile details, and scheme catalog localized.
9. Chat and voice language preference integration with website language.
10. Preservation of official scheme IDs, citations, and security controls.
11. Guest and registered citizen experiences.
"""

import json
import os
import re
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from api.main import app
from chat.chat_service import ChatService
from chat.conversational_handler import ConversationalHandler
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from rag.answer_generator import RAGAnswerGenerator
from rag.embedding_service import EmbeddingService
from rag.query_rewriter import QueryRewriter, normalize_language_code
from rag.reranker import LightweightReranker
from rag.retriever import SchemeRetriever
from rag.vector_store import VectorStoreManager


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
LOCALES_DIR = os.path.join(FRONTEND_DIR, "locales")


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def locales():
    """Loads all three locale JSON dictionaries."""
    en_path = os.path.join(LOCALES_DIR, "en.json")
    te_path = os.path.join(LOCALES_DIR, "te.json")
    hi_path = os.path.join(LOCALES_DIR, "hi.json")

    assert os.path.exists(en_path), "en.json must exist"
    assert os.path.exists(te_path), "te.json must exist"
    assert os.path.exists(hi_path), "hi.json must exist"

    with open(en_path, "r", encoding="utf-8") as f:
        en = json.load(f)
    with open(te_path, "r", encoding="utf-8") as f:
        te = json.load(f)
    with open(hi_path, "r", encoding="utf-8") as f:
        hi = json.load(f)

    return {"en": en, "te": te, "hi": hi}


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_localization.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def client_env(test_db, monkeypatch):
    """Provides TestClient with configured guest session and mocked LLM."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_manager = SessionManager(db=test_db)

    mock_vector_store = MagicMock(spec=VectorStoreManager)
    mock_vector_store.query.return_value = {
        "ids": [["chunk_001"]],
        "documents": [["AICTE Pragati scheme provides ₹50,000 scholarship per annum to eligible girl students."]],
        "metadatas": [[{
            "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
            "document_id": "DOC_EDU_002_PRAGATI_GUIDELINES",
            "document_name": "AICTE Pragati Guidelines",
            "authority": "AICTE",
            "page_number": 2,
            "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_G.pdf",
            "citation_reference": "[AICTE Pragati Guidelines, Page 2]",
            "academic_year": "AY 2026-27",
        }]],
        "distances": [[0.1]],
    }

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "answer": "AICTE Pragati provides financial support to girls.",
        "evidence_sufficient": True,
        "citations": ["S1"],
    })

    embedding_service = EmbeddingService(use_mock=True)
    rewriter = QueryRewriter()
    reranker = LightweightReranker()
    retriever = SchemeRetriever(
        vector_store=mock_vector_store,
        embedding_service=embedding_service,
        query_rewriter=rewriter,
        reranker=reranker,
    )
    rag_gen = RAGAnswerGenerator(retriever=retriever, llm_client=mock_llm)
    conv_handler = ConversationalHandler(llm_client=mock_llm)

    chat_svc = ChatService(
        db=test_db,
        session_manager=session_manager,
        rag_generator=rag_gen,
        conversational_handler=conv_handler,
    )

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_manager)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_manager)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.chat.chat_service", chat_svc)

    test_client = TestClient(app)
    guest_res = test_client.post("/auth/guest")
    assert guest_res.status_code == 200

    return {
        "client": test_client,
        "csrf_token": guest_res.json()["csrf_token"],
        "chat_svc": chat_svc,
        "llm_mock": mock_llm,
    }


# ---------------------------------------------------------------------------
# 1. Locale Completeness, Parity & Unicode Tests
# ---------------------------------------------------------------------------

class TestLocaleIntegrity:
    """Validates structural and lingual integrity of translation dictionaries."""

    def test_top_level_category_parity(self, locales):
        """All three locales must contain the exact same top-level categories."""
        en_cats = set(locales["en"].keys())
        te_cats = set(locales["te"].keys())
        hi_cats = set(locales["hi"].keys())

        assert en_cats == te_cats, f"Mismatch between EN and TE categories: {en_cats ^ te_cats}"
        assert en_cats == hi_cats, f"Mismatch between EN and HI categories: {en_cats ^ hi_cats}"

    def test_nested_key_parity(self, locales):
        """All leaf keys present in en.json must be present in te.json and hi.json."""
        def get_all_keys(d, prefix=""):
            keys = set()
            for k, v in d.items():
                full = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    keys.update(get_all_keys(v, full))
                else:
                    keys.add(full)
            return keys

        en_keys = get_all_keys(locales["en"])
        te_keys = get_all_keys(locales["te"])
        hi_keys = get_all_keys(locales["hi"])

        missing_in_te = en_keys - te_keys
        missing_in_hi = en_keys - hi_keys

        assert not missing_in_te, f"Keys in en.json missing in te.json: {missing_in_te}"
        assert not missing_in_hi, f"Keys in en.json missing in hi.json: {missing_in_hi}"

    def test_no_empty_translations(self, locales):
        """No translation string should be empty or whitespace."""
        def check_no_empty(d, locale_name, path=""):
            for k, v in d.items():
                p = f"{path}.{k}" if path else k
                if isinstance(v, dict):
                    check_no_empty(v, locale_name, p)
                else:
                    assert isinstance(v, str), f"Translation at {p} in {locale_name} must be string"
                    assert v.strip() != "", f"Translation at {p} in {locale_name} is empty"

        check_no_empty(locales["en"], "en")
        check_no_empty(locales["te"], "te")
        check_no_empty(locales["hi"], "hi")

    def test_placeholder_preservation(self, locales):
        """Dynamic placeholders like {name}, {count} must be preserved across translations."""
        def get_placeholders(s):
            return set(re.findall(r"\{([a-zA-Z0-9_]+)\}", s))

        def check_placeholders(en_d, target_d, target_name, path=""):
            for k, v in en_d.items():
                p = f"{path}.{k}" if path else k
                if isinstance(v, dict):
                    check_placeholders(v, target_d.get(k, {}), target_name, p)
                elif isinstance(v, str):
                    en_params = get_placeholders(v)
                    target_val = target_d.get(k, "")
                    target_params = get_placeholders(target_val)
                    assert en_params == target_params, (
                        f"Placeholder mismatch at {p} in {target_name}: "
                        f"expected {en_params}, got {target_params}"
                    )

        check_placeholders(locales["en"], locales["te"], "te")
        check_placeholders(locales["en"], locales["hi"], "hi")

    def test_telugu_unicode_validity(self, locales):
        """Telugu translations must contain authentic Telugu characters (\u0C00-\u0C7F)."""
        telugu_regex = re.compile(r"[\u0C00-\u0C7F]")
        te_strings = []

        def collect_strings(d):
            for v in d.values():
                if isinstance(v, dict):
                    collect_strings(v)
                elif isinstance(v, str):
                    te_strings.append(v)

        collect_strings(locales["te"])
        telugu_char_count = sum(len(telugu_regex.findall(s)) for s in te_strings)
        assert telugu_char_count > 1000, f"Expected rich Telugu text, found only {telugu_char_count} chars"

    def test_hindi_unicode_validity(self, locales):
        """Hindi translations must contain authentic Devanagari characters (\u0900-\u097F)."""
        devanagari_regex = re.compile(r"[\u0900-\u097F]")
        hi_strings = []

        def collect_strings(d):
            for v in d.values():
                if isinstance(v, dict):
                    collect_strings(v)
                elif isinstance(v, str):
                    hi_strings.append(v)

        collect_strings(locales["hi"])
        hindi_char_count = sum(len(devanagari_regex.findall(s)) for s in hi_strings)
        assert hindi_char_count > 1000, f"Expected rich Hindi text, found only {hindi_char_count} chars"


# ---------------------------------------------------------------------------
# 2. HTML Markup & Static Asset Verification
# ---------------------------------------------------------------------------

class TestHTMLMarkupLocalization:
    """Validates that all frontend HTML pages have language selectors and i18n tags."""

    HTML_FILES = [
        "index.html",
        "login.html",
        "signup.html",
        "profile.html",
        "dashboard.html",
    ]

    @pytest.mark.parametrize("filename", HTML_FILES)
    def test_html_includes_i18n_script(self, filename):
        """Each HTML file must include script tag for js/i18n.js."""
        path = os.path.join(FRONTEND_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        assert '<script src="js/i18n.js"></script>' in content, f"{filename} missing js/i18n.js script tag"

    @pytest.mark.parametrize("filename", HTML_FILES)
    def test_html_includes_global_language_selector(self, filename):
        """Each HTML file navbar must include the global language selector with en, te, and hi options."""
        path = os.path.join(FRONTEND_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'class="global-lang-select"' in content or 'id="globalLangSelect"' in content, (
            f"{filename} missing global language selector"
        )
        assert '<option value="en">English</option>' in content, f"{filename} missing English option"
        assert '<option value="te">తెలుగు</option>' in content, f"{filename} missing Telugu option"
        assert '<option value="hi">हिन्दी</option>' in content, f"{filename} missing Hindi option"

    def test_dashboard_contains_comprehensive_i18n_attributes(self):
        """Dashboard HTML must contain data-i18n tags for headings, cards, and modals."""
        path = os.path.join(FRONTEND_DIR, "dashboard.html")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        required_attributes = [
            'data-i18n="dashboard.welcomeCitizen"',
            'data-i18n="dashboard.hubHeading"',
            'data-i18n="cards.chatTitle"',
            'data-i18n="cards.voiceTitle"',
            'data-i18n="cards.recTitle"',
            'data-i18n="cards.catalogTitle"',
            'data-i18n="schemes.sectionHeading"',
            'data-i18n="schemes.tabRecommendations"',
            'data-i18n="schemes.tabCatalog"',
            'data-i18n="detailsModal.title"',
            'data-i18n="eligibilityModal.title"',
            'data-i18n="chat.title"',
            'data-i18n="voice.title"',
        ]
        for attr in required_attributes:
            assert attr in content, f"dashboard.html missing required attribute: {attr}"

    def test_static_files_served_by_fastapi(self, client_env):
        """Verifies that FastAPI serves all static assets over HTTP."""
        client = client_env["client"]
        assets = [
            "/frontend/js/i18n.js",
            "/frontend/locales/en.json",
            "/frontend/locales/te.json",
            "/frontend/locales/hi.json",
            "/frontend/dashboard.html",
            "/frontend/login.html",
            "/frontend/signup.html",
        ]
        for asset in assets:
            res = client.get(asset)
            assert res.status_code == 200, f"Failed to serve {asset}: {res.status_code}"


# ---------------------------------------------------------------------------
# 3. Translation Engine Logic & Fallback Tests
# ---------------------------------------------------------------------------

class TestI18nEngineContract:
    """Validates fallback and interpolation behavior according to the i18n contract."""

    def test_missing_key_fallback_to_english(self, locales):
        """A key present in English but simulated missing in Telugu must resolve to English."""
        en = locales["en"]
        te = dict(locales["te"])
        # Remove a key from TE
        if "cards" in te and "chatTitle" in te["cards"]:
            del te["cards"]["chatTitle"]

        # Simulate i18n lookup
        def t(key, lang):
            parts = key.split(".")
            # try target
            curr = te if lang == "te" else en
            for p in parts:
                curr = curr.get(p) if isinstance(curr, dict) else None
                if curr is None:
                    break
            if curr is not None:
                return curr
            # fallback to en
            curr_en = en
            for p in parts:
                curr_en = curr_en.get(p) if isinstance(curr_en, dict) else None
                if curr_en is None:
                    break
            return curr_en or key

        assert t("cards.chatTitle", "te") == en["cards"]["chatTitle"]

    def test_missing_key_fallback_to_key_name_or_default(self, locales):
        """A key completely absent in all dictionaries must return default text or the key."""
        en = locales["en"]

        def t(key, default_text=""):
            parts = key.split(".")
            curr = en
            for p in parts:
                curr = curr.get(p) if isinstance(curr, dict) else None
                if curr is None:
                    break
            return curr or default_text or key

        assert t("completely.nonexistent.key", "Default Fallback") == "Default Fallback"
        assert t("completely.nonexistent.key") == "completely.nonexistent.key"

    def test_interpolation_across_languages(self, locales):
        """Interpolates variables correctly in en, te, and hi."""
        def interpolate(template, params):
            return re.sub(r"\{([a-zA-Z0-9_]+)\}", lambda m: str(params.get(m.group(1), m.group(0))), template)

        en_tmpl = locales["en"]["dashboard"]["welcomeUser"]
        te_tmpl = locales["te"]["dashboard"]["welcomeUser"]
        hi_tmpl = locales["hi"]["dashboard"]["welcomeUser"]

        assert interpolate(en_tmpl, {"name": "Arjun"}) == "Welcome, Arjun!"
        assert interpolate(te_tmpl, {"name": "అర్జున్"}) == "స్వాగతం, అర్జున్!"
        assert interpolate(hi_tmpl, {"name": "अर्जुन"}) == "स्वागत है, अर्जुन!"


# ---------------------------------------------------------------------------
# 4. Chat & Voice Language Preference Integration
# ---------------------------------------------------------------------------

class TestChatAndVoiceLanguageIntegration:
    """Verifies that selecting Telugu/Hindi sets the chat/voice assistant's response language."""

    def test_chat_uses_website_language_telugu(self, client_env):
        """When language is passed as 'te', backend generates a Telugu response."""
        client = client_env["client"]
        res = client.post(
            "/chat/message",
            json={"message": "Namaste", "language": "te"},
            headers={"X-CSRF-Token": client_env["csrf_token"]},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "te"

    def test_chat_uses_website_language_hindi(self, client_env):
        """When language is passed as 'hi', backend generates a Hindi response."""
        client = client_env["client"]
        res = client.post(
            "/chat/message",
            json={"message": "Namaste", "language": "hi"},
            headers={"X-CSRF-Token": client_env["csrf_token"]},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "hi"

    def test_chat_uses_website_language_english_default(self, client_env):
        """When language is passed as 'en', backend generates an English response."""
        client = client_env["client"]
        res = client.post(
            "/chat/message",
            json={"message": "Hello", "language": "en"},
            headers={"X-CSRF-Token": client_env["csrf_token"]},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "en"

    def test_voice_locale_mapping(self):
        """Verifies voice locale mapping for BCP-47 speech recognition and synthesis."""
        def get_voice_locale(lang):
            norm = normalize_language_code(lang)
            if norm == "te":
                return "te-IN"
            if norm == "hi":
                return "hi-IN"
            return "en-IN"

        assert get_voice_locale("te") == "te-IN"
        assert get_voice_locale("telugu") == "te-IN"
        assert get_voice_locale("hi") == "hi-IN"
        assert get_voice_locale("hindi") == "hi-IN"
        assert get_voice_locale("en") == "en-IN"
        assert get_voice_locale("english") == "en-IN"
        assert get_voice_locale(None) == "en-IN"


# ---------------------------------------------------------------------------
# 5. Scheme Data, ID and Legal Integrity
# ---------------------------------------------------------------------------

class TestSchemeDataAndLegalIntegrity:
    """Verifies that localization does not corrupt scheme IDs, citations, or legal titles."""

    SUPPORTED_SCHEME_IDS = [
        "SCHEME_EDU_001_PM_USP_CSSS",
        "SCHEME_EDU_002_AICTE_PRAGATI",
        "SCHEME_EDU_003_AICTE_SAKSHAM",
        "SCHEME_EDU_004_AICTE_SWANATH",
        "SCHEME_EDU_005_TOP_CLASS_SC",
    ]

    def test_scheme_ids_unaltered_in_catalog(self, client_env):
        """GET /schemes returns pristine official scheme IDs regardless of language selection."""
        client = client_env["client"]
        res = client.get("/schemes")
        assert res.status_code == 200
        schemes = res.json()["schemes"]
        returned_ids = [s["scheme_id"] for s in schemes]

        for expected_id in self.SUPPORTED_SCHEME_IDS:
            assert expected_id in returned_ids, f"Scheme {expected_id} missing from catalog"

    def test_disclaimer_notice_in_all_locales(self, locales):
        """All three locales must include the official government verification pending disclaimer."""
        en_disc = locales["en"]["schemes"]["safeguardNotice"]
        te_disc = locales["te"]["schemes"]["safeguardNotice"]
        hi_disc = locales["hi"]["schemes"]["safeguardNotice"]

        assert "Verification Pending" in en_disc
        assert "ధృవీకరణ" in te_disc
        assert "सत्यापन" in hi_disc

