"""Tests for SahayAI End-to-End Multilingual Voice Language Consistency.

Covers:
1. Selected locale reaching the backend (/chat/message).
2. Selected response language being included in the LLM instructions.
3. Telugu selection enforcing Telugu responses (and never Hindi or English).
4. Hindi selection enforcing Hindi responses (and never Telugu).
5. English selection enforcing English responses.
6. Mixed-language queries (Romanized Telugu, Tenglish, Hinglish) respecting selected language.
7. Language switching between consecutive turns in the same session.
8. Text-to-Speech voice matching and refusal to silently fallback to English for Indic languages.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from api.main import app
from chat.conversational_handler import (
    ConversationalHandler,
    get_conversational_system_prompt,
)
from chat.intent_router import IntentRouter, IntentType
from chat.chat_service import ChatService
from profile.database import Database
from profile.session_manager import SessionManager
from rag.answer_generator import RAGAnswerGenerator
from rag.embedding_service import EmbeddingService
from rag.query_rewriter import (
    QueryRewriter,
    normalize_language_code,
    normalize_language_name,
)
from rag.reranker import LightweightReranker
from rag.retriever import SchemeRetriever
from rag.vector_store import VectorStoreManager


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_multilingual_voice.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mock_vector_store():
    vs = MagicMock(spec=VectorStoreManager)
    vs.query.return_value = {
        "ids": [["chunk_001"]],
        "documents": [["AICTE Pragati scheme provides ₹50,000 per annum to girl students in technical degree courses."]],
        "metadatas": [[{
            "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
            "document_id": "doc_001",
            "document_name": "AICTE Pragati Guidelines",
            "authority": "AICTE",
            "page_number": 2,
            "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_G.pdf",
            "citation_reference": "[AICTE Pragati Guidelines, Page 2]",
            "academic_year": "AY 2026-27",
        }]],
        "distances": [[0.12]],
    }
    return vs


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.generate.return_value = "నమస్కారం! నేను సహాయ్ ఏఐ. నేను మీకు ఎలా సహాయపడగలను?"
    return client


@pytest.fixture
def voice_env(test_db, mock_vector_store, mock_llm_client, monkeypatch):
    """Configures test environment with active guest session and mocked LLM."""
    session_manager = SessionManager(db=test_db)
    from profile.account_manager import AccountManager
    from profile.profile_manager import ProfileManager
    from profile.auth_service import AuthService
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)

    embedding_service = EmbeddingService(use_mock=True)
    rewriter = QueryRewriter()
    reranker = LightweightReranker()
    retriever = SchemeRetriever(
        vector_store=mock_vector_store,
        embedding_service=embedding_service,
        query_rewriter=rewriter,
        reranker=reranker,
    )
    rag_generator = RAGAnswerGenerator(
        retriever=retriever,
        llm_client=mock_llm_client,
    )
    conv_handler = ConversationalHandler(llm_client=mock_llm_client)

    test_chat_service = ChatService(
        db=test_db,
        session_manager=session_manager,
        rag_generator=rag_generator,
        conversational_handler=conv_handler,
    )

    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_manager)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_manager)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.chat.chat_service", test_chat_service)

    client = TestClient(app)
    # Initialize guest session via endpoint to obtain authenticated cookie and csrf_token
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    guest_json = guest_res.json()
    csrf_token = guest_json["csrf_token"]

    return {
        "client": client,
        "csrf_token": csrf_token,
        "mock_llm": mock_llm_client,
        "mock_vector_store": mock_vector_store,
        "chat_service": test_chat_service,
    }


# ===========================================================================
# 1. Selected Locale Reaching the Backend API
# ===========================================================================

class TestBackendLanguageIngestion:
    """Verifies that preferred_language flows from request to response."""

    def test_selected_locale_telugu_reaches_backend(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]

        res = client.post(
            "/chat/message",
            json={
                "message": "Ela unnaru?",
                "language": "te-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["language"] == "te"

    def test_selected_locale_hindi_reaches_backend(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]

        res = client.post(
            "/chat/message",
            json={
                "message": "Kaise ho aap?",
                "language": "hi-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["language"] == "hi"

    def test_selected_locale_english_reaches_backend(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]

        res = client.post(
            "/chat/message",
            json={
                "message": "How are you doing?",
                "language": "en-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["language"] == "en"


# ===========================================================================
# 2. Selected Language Instructions in LLM Prompts
# ===========================================================================

class TestLLMLanguageInstructions:
    """Verifies that the LLM is explicitly instructed in the user's selected language."""

    def test_telugu_selection_includes_strict_telugu_prompt(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        client.post(
            "/chat/message",
            json={
                "message": "What is recursion?",
                "language": "te-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        mock_llm.generate.assert_called_once()
        call_kwargs = mock_llm.generate.call_args[1]
        messages = call_kwargs["messages"]
        system_msg = messages[0]["content"]

        assert "Telugu script (తెలుగు)" in system_msg
        assert "Do NOT respond in English or Hindi" in system_msg

    def test_hindi_selection_includes_strict_hindi_prompt(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        client.post(
            "/chat/message",
            json={
                "message": "What is photosynthesis?",
                "language": "hi-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        mock_llm.generate.assert_called_once()
        call_kwargs = mock_llm.generate.call_args[1]
        messages = call_kwargs["messages"]
        system_msg = messages[0]["content"]

        assert "Hindi using Devanagari script (हिन्दी)" in system_msg
        assert "Do NOT respond in English or Telugu" in system_msg

    def test_english_selection_includes_strict_english_prompt(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        client.post(
            "/chat/message",
            json={
                "message": "Explain binary search",
                "language": "en-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        mock_llm.generate.assert_called_once()
        call_kwargs = mock_llm.generate.call_args[1]
        messages = call_kwargs["messages"]
        system_msg = messages[0]["content"]

        assert "Respond in clear, natural, and helpful English" in system_msg
        assert "Do NOT respond in Hindi or Telugu" in system_msg

    def test_scheme_rag_query_includes_telugu_instruction(self, voice_env):
        """Verifies scheme RAG generation receives Telugu instruction when te-IN is chosen."""
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        mock_llm.generate.return_value = json.dumps({
            "answer": "ఏఐసీటీఈ ప్రగతి పథకం ద్వారా బాలికలకు సంవత్సరానికి ₹50,000 అందుతుంది [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        client.post(
            "/chat/message",
            json={
                "message": "Tell me about AICTE Pragati scholarship",
                "language": "te-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        mock_llm.generate.assert_called_once()
        call_kwargs = mock_llm.generate.call_args[1]
        messages = call_kwargs["messages"]
        user_prompt = messages[-1]["content"]

        assert "Respond entirely in Telugu using Telugu script" in user_prompt


# ===========================================================================
# 3. Mixed-Language and Romanized Input Tests
# ===========================================================================

class TestMixedLanguageInputHandling:
    """Verifies that Romanized Telugu, Tenglish, and Hinglish respect the selected voice language."""

    @pytest.mark.parametrize("telugu_input", [
        "students ki scholarships unnayaa?",
        "Nenu BTech chaduvutunnanu, scholarship kavali.",
        "నాకు స్కాలర్షిప్ కావాలి.",
        "Ela unnaru?",
    ])
    def test_telugu_selection_with_various_inputs(self, voice_env, telugu_input):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        # Mock valid response
        mock_llm.generate.return_value = json.dumps({
            "answer": "అవును, సాంకేతిక విద్యార్థులకు ఏఐసీటీఈ స్కాలర్‌షిప్‌లు అందుబాటులో ఉన్నాయి [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = client.post(
            "/chat/message",
            json={
                "message": telugu_input,
                "language": "te-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "te"

        # Verify system prompt instructed Telugu, not Hindi or English
        call_kwargs = mock_llm.generate.call_args[1]
        prompt_content = str(call_kwargs["messages"])
        assert "Telugu" in prompt_content or "తెలుగు" in prompt_content

    @pytest.mark.parametrize("hindi_input", [
        "Mujhe BTech ke liye scholarship chahiye.",
        "Main Telangana se hoon.",
    ])
    def test_hindi_selection_with_hinglish_inputs(self, voice_env, hindi_input):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        mock_llm.generate.return_value = json.dumps({
            "answer": "तकनीकी शिक्षा के लिए एआईसीटीई प्रगति और अन्य छात्रवृत्तियां उपलब्ध हैं [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = client.post(
            "/chat/message",
            json={
                "message": hindi_input,
                "language": "hi-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "hi"

        call_kwargs = mock_llm.generate.call_args[1]
        prompt_content = str(call_kwargs["messages"])
        assert "Hindi" in prompt_content or "हिन्दी" in prompt_content

    def test_english_selection_with_plain_english(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]
        mock_llm.generate.reset_mock()

        mock_llm.generate.return_value = json.dumps({
            "answer": "AICTE provides scholarships for engineering students [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = client.post(
            "/chat/message",
            json={
                "message": "I need a scholarship for my engineering studies.",
                "language": "en-IN",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "en"


# ===========================================================================
# 4. Language Switching Between Turns in Consecutive Turns
# ===========================================================================

class TestLanguageSwitchingBetweenTurns:
    """Verifies that changing language on consecutive requests updates instruction dynamically."""

    def test_language_switching_telugu_then_hindi_then_english(self, voice_env):
        client = voice_env["client"]
        csrf_token = voice_env["csrf_token"]
        mock_llm = voice_env["mock_llm"]

        # Turn 1: Telugu selected
        mock_llm.generate.reset_mock()
        res1 = client.post(
            "/chat/message",
            json={"message": "Nenu BTech student", "language": "te-IN"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert res1.json()["language"] == "te"
        call1 = mock_llm.generate.call_args[1]
        assert "Telugu" in str(call1)

        # Turn 2: User switches dropdown to Hindi
        mock_llm.generate.reset_mock()
        res2 = client.post(
            "/chat/message",
            json={"message": "Aur kya eligibility hai?", "language": "hi-IN"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert res2.json()["language"] == "hi"
        call2 = mock_llm.generate.call_args[1]
        assert "Hindi" in str(call2)

        # Turn 3: User switches dropdown to English
        mock_llm.generate.reset_mock()
        res3 = client.post(
            "/chat/message",
            json={"message": "What are the required documents?", "language": "en-IN"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert res3.json()["language"] == "en"
        call3 = mock_llm.generate.call_args[1]
        assert "English" in str(call3)


# ===========================================================================
# 5. Speech Synthesis Voice Matching Unit Verification
# ===========================================================================

class TestSpeechSynthesisVoiceSelectionLogic:
    """Tests the Python implementation of the frontend voice matching algorithm."""

    @staticmethod
    def find_compatible_voice(voices, target_lang):
        """Python mirror of frontend findCompatibleVoice function."""
        if not voices:
            return None

        normalized_target = target_lang.lower().replace("_", "-")
        prefix = normalized_target.split("-")[0]

        # 1. Exact locale match
        for v in voices:
            if v.get("lang", "").lower().replace("_", "-") == normalized_target:
                return v

        # 2. Language prefix match
        for v in voices:
            if v.get("lang", "").lower().replace("_", "-").startswith(prefix):
                return v

        # 3. Name-based keyword match
        name_map = {"te": "telugu", "hi": "hindi", "en": "english"}
        keyword = name_map.get(prefix)
        if keyword:
            for v in voices:
                if keyword in v.get("name", "").lower():
                    return v

        # 4. English regional fallback for English ONLY
        if prefix == "en":
            for v in voices:
                if v.get("lang", "").lower().startswith("en"):
                    return v

        # STRICT: Never fall back to English for Telugu or Hindi!
        return None

    def test_telugu_matched_when_telugu_voice_present(self):
        browser_voices = [
            {"name": "Microsoft David", "lang": "en-US"},
            {"name": "Microsoft Mohan Online - Telugu (India)", "lang": "te-IN"},
            {"name": "Google हिन्दी", "lang": "hi-IN"},
        ]
        matched = self.find_compatible_voice(browser_voices, "te-IN")
        assert matched is not None
        assert matched["lang"] == "te-IN"

    def test_telugu_returns_none_when_no_telugu_voice(self):
        """Ensures NO silent fallback to English when Telugu voice is missing."""
        browser_voices = [
            {"name": "Microsoft David", "lang": "en-US"},
            {"name": "Microsoft Zira", "lang": "en-US"},
            {"name": "Google हिन्दी", "lang": "hi-IN"},
        ]
        matched = self.find_compatible_voice(browser_voices, "te-IN")
        assert matched is None, "Telugu must NOT silently fallback to an English voice!"

    def test_hindi_returns_none_when_no_hindi_voice(self):
        """Ensures NO silent fallback to English when Hindi voice is missing."""
        browser_voices = [
            {"name": "Microsoft David", "lang": "en-US"},
            {"name": "Microsoft Ravi", "lang": "en-IN"},
        ]
        matched = self.find_compatible_voice(browser_voices, "hi-IN")
        assert matched is None, "Hindi must NOT silently fallback to an English voice!"

    def test_english_can_use_other_english_variants(self):
        browser_voices = [
            {"name": "Microsoft David", "lang": "en-US"},
            {"name": "Google UK English Female", "lang": "en-GB"},
        ]
        matched = self.find_compatible_voice(browser_voices, "en-IN")
        assert matched is not None
        assert matched["lang"].startswith("en")
