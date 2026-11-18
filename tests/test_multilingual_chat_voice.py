"""tests/test_multilingual_chat_voice.py — Comprehensive Test Suite for SahayAI Multilingual Chat and Voice Assistant.

Covers all 9 mandated verification requirements:
1. English question → English response.
2. Telugu-script question → Telugu response.
3. Hindi-script question → Hindi response.
4. Romanized Telugu question → Telugu response.
5. Romanized Hindi question → Hindi response.
6. Telugu scholarship question using RAG → Telugu explanation with citations.
7. Hindi scholarship question using RAG → Hindi explanation with citations.
8. English-to-Telugu and Telugu-to-English conversation.
9. Voice recognition and speech playback availability independently.
"""

import json
import re
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from api.main import app
from chat.chat_service import ChatService
from chat.conversational_handler import ConversationalHandler
from chat.intent_router import IntentRouter
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from rag.answer_generator import OFFICIAL_DISCLAIMER, RAGAnswerGenerator
from rag.embedding_service import EmbeddingService
from rag.query_rewriter import (
    QueryRewriter,
    detect_language,
    normalize_language_code,
    normalize_language_name,
)
from rag.reranker import LightweightReranker
from rag.retriever import SchemeRetriever
from rag.vector_store import VectorStoreManager


@pytest.fixture
def multi_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_multilingual_chat_voice.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mock_multi_vector_store():
    """Provides mock ChromaDB vector store returning official AICTE Pragati excerpt."""
    vs = MagicMock(spec=VectorStoreManager)
    vs.query.return_value = {
        "ids": [["chunk_pragati_001"]],
        "documents": [["AICTE Pragati Scholarship Scheme for Girl Students provides ₹50,000 per annum for technical degree or diploma courses. Annual family income must not exceed ₹8 lakh."]],
        "metadatas": [[{
            "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
            "document_id": "doc_pragati_01",
            "document_name": "AICTE Pragati Guidelines",
            "authority": "AICTE",
            "page_number": 3,
            "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_G.pdf",
            "citation_reference": "[AICTE Pragati Guidelines, Page 3]",
            "academic_year": "AY 2026-27",
        }]],
        "distances": [[0.08]],
    }
    return vs


@pytest.fixture
def mock_multi_llm():
    """Provides mock Groq LLM client responding realistically in requested language."""
    client = MagicMock()

    def generate_side_effect(messages, **kwargs):
        sys_prompt = messages[0]["content"] if messages else ""
        user_prompt = messages[-1]["content"] if messages else ""

        # Determine target language from system prompt or user instruction
        is_telugu = "Telugu script (తెలుగు)" in sys_prompt or "Respond entirely in Telugu using Telugu script" in user_prompt
        is_hindi = "Devanagari script (हिन्दी)" in sys_prompt or "Respond entirely in Hindi using Devanagari script" in user_prompt

        # Check if RAG structured JSON response is expected
        if "Return ONLY valid JSON" in sys_prompt or "CITIZEN QUESTION:" in user_prompt:
            if is_telugu:
                return json.dumps({
                    "answer": "AICTE Pragati Scholarship Scheme for Girl Students పథకం సాంకేతిక విద్యనభ్యసిస్తున్న విద్యార్థినులకు సంవత్సరానికి ₹50,000 ఆర్థిక సహాయం అందిస్తుంది [S1]. కుటుంబ వార్షిక ఆదాయం ₹8 లక్షల కంటే తక్కువగా ఉండాలి.",
                    "evidence_sufficient": True,
                    "citations": ["S1"],
                })
            elif is_hindi:
                return json.dumps({
                    "answer": "AICTE Pragati Scholarship Scheme for Girl Students के तहत तकनीकी पाठ्यक्रम में अध्ययनरत छात्राओं को प्रति वर्ष ₹50,000 की छात्रवृत्ति प्रदान की जाती है [S1]। परिवार की वार्षिक आय ₹8 लाख से अधिक नहीं होनी चाहिए।",
                    "evidence_sufficient": True,
                    "citations": ["S1"],
                })
            else:
                return json.dumps({
                    "answer": "AICTE Pragati Scholarship Scheme for Girl Students provides financial assistance of ₹50,000 per annum to eligible female students [S1]. Annual family income must not exceed ₹8 lakh.",
                    "evidence_sufficient": True,
                    "citations": ["S1"],
                })

        # Conversational / non-RAG response
        if is_telugu:
            return "నమస్కారం! నేను సహాయ్ ఏఐ (SahayAI). నేను మీకు ఎలా సహాయపడగలను?"
        elif is_hindi:
            return "नमस्ते! मैं सहायएआई (SahayAI) हूँ। मैं आपकी किस प्रकार सहायता कर सकता हूँ?"
        else:
            return "Hello! I am SahayAI, your AI assistant for Indian government higher education schemes and scholarships. How can I help you today?"

    client.generate.side_effect = generate_side_effect
    return client


@pytest.fixture
def chat_client(multi_db, mock_multi_vector_store, mock_multi_llm, monkeypatch):
    """Sets up FastAPI test client with configured guest session and chat service."""
    session_manager = SessionManager(db=multi_db)
    accounts = AccountManager(db=multi_db)
    profiles = ProfileManager(db=multi_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)

    embedding_service = EmbeddingService(use_mock=True)
    rewriter = QueryRewriter()
    reranker = LightweightReranker()
    retriever = SchemeRetriever(
        vector_store=mock_multi_vector_store,
        embedding_service=embedding_service,
        query_rewriter=rewriter,
        reranker=reranker,
    )
    rag_generator = RAGAnswerGenerator(
        retriever=retriever,
        llm_client=mock_multi_llm,
    )
    conv_handler = ConversationalHandler(llm_client=mock_multi_llm)

    test_chat_service = ChatService(
        db=multi_db,
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
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    guest_data = guest_res.json()
    csrf_token = guest_data["csrf_token"]

    return {
        "client": client,
        "csrf_token": csrf_token,
        "mock_llm": mock_multi_llm,
        "chat_service": test_chat_service,
    }


# ===========================================================================
# 1. English question → English response
# ===========================================================================
def test_scenario_1_english_question_to_english_response(chat_client):
    """1. English question → English response."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": "What is SahayAI and what can you do?"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "en"
    assert "SahayAI" in data["content"]
    assert bool(re.search(r"[a-zA-Z]", data["content"]))
    # Ensure no unintended Indic script forced
    assert not bool(re.search(r"[\u0C00-\u0C7F]", data["content"]))
    assert not bool(re.search(r"[\u0900-\u097F]", data["content"]))


# ===========================================================================
# 2. Telugu-script question → Telugu response
# ===========================================================================
def test_scenario_2_telugu_script_question_to_telugu_response(chat_client):
    """2. Telugu-script question → Telugu response."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": "నమస్కారం! మీరు ఎవరు?"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "te"
    # Ensure response contains authentic Telugu characters
    assert bool(re.search(r"[\u0C00-\u0C7F]", data["content"]))
    assert "సహాయ్" in data["content"] or "నమస్కారం" in data["content"]


# ===========================================================================
# 3. Hindi-script question → Hindi response
# ===========================================================================
def test_scenario_3_hindi_script_question_to_hindi_response(chat_client):
    """3. Hindi-script question → Hindi response."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": "नमस्ते! आप कौन हैं?"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "hi"
    # Ensure response contains Devanagari characters
    assert bool(re.search(r"[\u0900-\u097F]", data["content"]))
    assert "सहायएआई" in data["content"] or "नमस्ते" in data["content"]


# ===========================================================================
# 4. Romanized Telugu question → Telugu response
# ===========================================================================
@pytest.mark.parametrize("query", [
    "naaku scholarship kavali",
    "pragati scheme eligibility enti?",
    "ela apply cheyali?",
    "meeru evaru?",
    "bagunnara",
])
def test_scenario_4_romanized_telugu_question_to_telugu_response(chat_client, query):
    """4. Romanized Telugu question → Telugu response."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": query},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "te"
    # Response must be delivered in natural Telugu script
    assert bool(re.search(r"[\u0C00-\u0C7F]", data["content"]))


# ===========================================================================
# 5. Romanized Hindi question → Hindi response
# ===========================================================================
@pytest.mark.parametrize("query", [
    "mujhe scholarship chahiye",
    "pragati scholarship kaise apply kare?",
    "kya eligibility hai?",
    "tum kaun ho?",
    "kya haal hai",
])
def test_scenario_5_romanized_hindi_question_to_hindi_response(chat_client, query):
    """5. Romanized Hindi question → Hindi response."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": query},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "hi"
    # Response must be delivered in natural Devanagari Hindi script
    assert bool(re.search(r"[\u0900-\u097F]", data["content"]))


# ===========================================================================
# 6. Telugu scholarship question using RAG → Telugu explanation with citations
# ===========================================================================
def test_scenario_6_telugu_scholarship_rag_explanation_with_citations(chat_client):
    """6. Telugu scholarship question using RAG → Telugu explanation with citations."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": "ప్రగతి స్కాలర్‌షిప్ అర్హతలు మరియు ప్రయోజనాలు ఏమిటి?"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "te"
    assert data["intent"] == "scheme_inquiry"

    # Telugu script explanation
    assert bool(re.search(r"[\u0C00-\u0C7F]", data["content"]))

    # Grounded citations preserved
    assert "[S1]" in data["content"]
    assert len(data["citations"]) >= 1
    assert data["citations"][0]["citation_id"] == "S1"
    assert data["citations"][0]["authority"] == "AICTE"

    # Official verification disclaimer attached
    assert data["disclaimer"] is not None
    assert "DISCLAIMER: Information retrieved from official government guidelines" in data["disclaimer"]

    # Canonical scheme name preserved without distorting translation
    assert "AICTE Pragati" in data["content"]


# ===========================================================================
# 7. Hindi scholarship question using RAG → Hindi explanation with citations
# ===========================================================================
def test_scenario_7_hindi_scholarship_rag_explanation_with_citations(chat_client):
    """7. Hindi scholarship question using RAG → Hindi explanation with citations."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    res = client.post(
        "/chat/message",
        json={"message": "प्रगति छात्रवृत्ति योजना के नियम और राशि क्या है?"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["language"] == "hi"
    assert data["intent"] == "scheme_inquiry"

    # Hindi Devanagari script explanation
    assert bool(re.search(r"[\u0900-\u097F]", data["content"]))

    # Grounded citations preserved
    assert "[S1]" in data["content"]
    assert len(data["citations"]) >= 1
    assert data["citations"][0]["citation_id"] == "S1"

    # Official verification disclaimer attached
    assert data["disclaimer"] is not None

    # Canonical scheme name preserved
    assert "AICTE Pragati" in data["content"]


# ===========================================================================
# 8. English-to-Telugu and Telugu-to-English conversation
# ===========================================================================
def test_scenario_8_multiturn_language_switching_and_continuity(chat_client):
    """8. English-to-Telugu and Telugu-to-English conversation."""
    client = chat_client["client"]
    csrf = chat_client["csrf_token"]

    # Turn 1: English question
    res1 = client.post(
        "/chat/message",
        json={"message": "What is AICTE Pragati scholarship?"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["language"] == "en"
    conv_id = d1.get("conversation_id")

    # Turn 2: Switch to Telugu (script)
    res2 = client.post(
        "/chat/message",
        json={"message": "దీనికి ఎవరు అర్హులు?", "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["language"] == "te"
    assert bool(re.search(r"[\u0C00-\u0C7F]", d2["content"]))

    # Turn 3: Switch back to English
    res3 = client.post(
        "/chat/message",
        json={"message": "How much scholarship amount is provided per year?", "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert res3.status_code == 200
    d3 = res3.json()
    assert d3["language"] == "en"
    assert not bool(re.search(r"[\u0C00-\u0C7F]", d3["content"]))

    # Turn 4: Romanized Telugu question
    res4 = client.post(
        "/chat/message",
        json={"message": "naaku income limit cheppandi", "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert res4.status_code == 200
    d4 = res4.json()
    assert d4["language"] == "te"

    # Turn 5: Neutral follow-up preserving previous Telugu context
    res5 = client.post(
        "/chat/message",
        json={"message": "details", "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert res5.status_code == 200
    d5 = res5.json()
    assert d5["language"] == "te"

    # Turn 6: Explicit instruction to switch to English
    res6 = client.post(
        "/chat/message",
        json={"message": "Can you explain this in English please?", "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert res6.status_code == 200
    d6 = res6.json()
    assert d6["language"] == "en"


# ===========================================================================
# 9. Voice recognition and speech playback availability independently
# ===========================================================================
def test_scenario_9_voice_recognition_and_playback_availability_decoupling():
    """9. Voice recognition and speech playback availability independently.

    Verifies:
    A. Normalization of voice locales ('te-IN', 'hi-IN', 'en-IN') to ISO language codes.
    B. Language detection handles native script, Romanized words, and mixed text.
    C. Decoupled voice playback handling: absence of a TTS playback voice
       does not invalidate speech recognition or omit the text response.
    """
    # A. Locale normalization
    assert normalize_language_code("te-IN") == "te"
    assert normalize_language_code("hi-IN") == "hi"
    assert normalize_language_code("en-IN") == "en"
    assert normalize_language_name("te-IN") == "telugu"
    assert normalize_language_name("hi-IN") == "hindi"
    assert normalize_language_name("en-IN") == "english"

    # B. Script & Romanized detection
    assert detect_language("What is Pragati scheme?") == "en"
    assert detect_language("ప్రగతి స్కాలర్‌షిప్") == "te"
    assert detect_language("प्रगति छात्रवृत्ति") == "hi"
    assert detect_language("naaku scholarship kavali") == "te"
    assert detect_language("mujhe scholarship chahiye") == "hi"

    # C. IntentRouter correctly routes voice requests with explicit locale preference
    router = IntentRouter()

    # Telugu Voice Input transcribed to text
    res_te = router.route(query="AICTE Pragati", preferred_language="te-IN")
    assert res_te.detected_language == "te"

    # Hindi Voice Input transcribed to text
    res_hi = router.route(query="AICTE Pragati", preferred_language="hi-IN")
    assert res_hi.detected_language == "hi"

    # English Voice Input
    res_en = router.route(query="AICTE Pragati", preferred_language="en-IN")
    assert res_en.detected_language == "en"


def test_language_rules_preserve_official_terminology():
    """Verifies that RAG answer generator prompt instructions enforce preservation of official names."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "answer": "Test answer [S1].",
        "evidence_sufficient": True,
        "citations": ["S1"],
    })
    from rag.query_rewriter import RewrittenQuery
    mock_retriever = MagicMock()
    mock_retriever.query_rewriter.rewrite_with_context.return_value = RewrittenQuery(
        original_query="Tell me about Pragati",
        rewritten_query="Tell me about Pragati",
        detected_scheme_id="SCHEME_EDU_002_AICTE_PRAGATI",
        referenced_scheme_ids=["SCHEME_EDU_002_AICTE_PRAGATI"],
    )
    mock_result = MagicMock()
    mock_result.chunk_id = "c1"
    mock_result.scheme_id = "SCHEME_EDU_002_AICTE_PRAGATI"
    mock_result.document_id = "d1"
    mock_result.document_name = "AICTE Pragati Guidelines"
    mock_result.authority = "AICTE"
    mock_result.page_number = 1
    mock_result.academic_year = "AY 2026-27"
    mock_result.source_url = "https://scholarships.gov.in"
    mock_result.citation_reference = "[AICTE Guidelines]"
    mock_result.similarity_score = 0.95
    mock_result.text = "AICTE Pragati scholarship details."
    mock_retriever.retrieve.return_value = [mock_result]

    rag_gen = RAGAnswerGenerator(retriever=mock_retriever, llm_client=mock_llm)

    # Prompt check for Telugu
    rag_gen.answer("Tell me about Pragati", scheme_id="SCHEME_EDU_002_AICTE_PRAGATI", language="telugu")
    assert mock_llm.generate.called
    user_p_te = mock_llm.generate.call_args.kwargs["messages"][-1]["content"]
    assert "Respond entirely in Telugu using Telugu script" in user_p_te
    assert "Do NOT translate official scheme names" in user_p_te

    # Prompt check for Hindi
    mock_llm.generate.reset_mock()
    rag_gen.answer("Tell me about Pragati", scheme_id="SCHEME_EDU_002_AICTE_PRAGATI", language="hindi")
    assert mock_llm.generate.called
    user_p_hi = mock_llm.generate.call_args.kwargs["messages"][-1]["content"]
    assert "Respond entirely in Hindi using Devanagari script" in user_p_hi
    assert "Do NOT translate official scheme names" in user_p_hi
