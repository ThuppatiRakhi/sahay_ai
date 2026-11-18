"""tests/test_live_multilingual_llm.py — Real Live Groq LLM & Retrieval Test Suite for SahayAI Phase 1.

Executes real LLM calls against the configured Groq API key and model (openai/gpt-oss-120b).
Tests at least:
- English questions
- Telugu-script questions
- Hindi-script questions
- Romanized Telugu (Tenglish) questions
- Romanized Hindi (Hinglish) questions
- Mixed-language questions
- Multi-turn language switching
- Scholarship RAG responses in Telugu and Hindi with citations and official name preservation
"""

import os
import re
import time
import pytest
from dotenv import load_dotenv

from chat.chat_service import ChatService
from chat.conversational_handler import ConversationalHandler
from profile.database import Database
from profile.session_manager import SessionManager
from rag.answer_generator import RAGAnswerGenerator
from rag.embedding_service import EmbeddingService
from rag.llm_client import GroqLLMClient
from rag.query_rewriter import QueryRewriter
from rag.reranker import LightweightReranker
from rag.retriever import SchemeRetriever
from rag.vector_store import VectorStoreManager

load_dotenv()
pytestmark = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not configured in .env"
)


@pytest.fixture(scope="module")
def real_chat_service():
    """Initializes a real ChatService backed by real ChromaDB and real Groq LLM."""
    db = Database()
    session_manager = SessionManager(db=db)
    vs = VectorStoreManager()
    emb = EmbeddingService()
    rewriter = QueryRewriter()
    reranker = LightweightReranker()
    retriever = SchemeRetriever(
        vector_store=vs,
        embedding_service=emb,
        query_rewriter=rewriter,
        reranker=reranker,
    )
    llm = GroqLLMClient()
    rag_gen = RAGAnswerGenerator(retriever=retriever, llm_client=llm)
    conv_h = ConversationalHandler(llm_client=llm)
    return ChatService(
        db=db,
        session_manager=session_manager,
        rag_generator=rag_gen,
        conversational_handler=conv_h,
    )


@pytest.fixture(scope="function")
def guest_session(real_chat_service):
    """Provides a fresh guest session for each live test."""
    sess = real_chat_service.session_manager.create_guest_session()
    return {
        "session_id": sess["session_id"],
        "context": {"is_guest": True, "guest_id": sess["guest_id"]},
    }


# ---------------------------------------------------------------------------
# 1. Real LLM: English General & Scholarship Queries
# ---------------------------------------------------------------------------
def test_real_llm_english_general_and_rag(real_chat_service, guest_session):
    """Real LLM test: English queries return English answers and RAG citations."""
    ctx = guest_session["context"]
    sid = guest_session["session_id"]

    res = real_chat_service.post_message(ctx, "What is SahayAI?", sid)
    assert res["language"] == "en"
    assert "SahayAI" in res["content"]
    assert bool(re.search(r"[a-zA-Z]", res["content"]))

    time.sleep(2)
    res_rag = real_chat_service.post_message(ctx, "What is AICTE Pragati scholarship?", sid)
    assert res_rag["language"] == "en"
    assert res_rag["intent"] == "scheme_inquiry"
    assert len(res_rag["citations"]) >= 1
    assert "AICTE Pragati" in res_rag["content"]


# ---------------------------------------------------------------------------
# 2. Real LLM: Telugu Script Queries
# ---------------------------------------------------------------------------
def test_real_llm_telugu_script_general_and_rag(real_chat_service, guest_session):
    """Real LLM test: Telugu-script queries return Telugu-script answers and preserve citations."""
    ctx = guest_session["context"]
    sid = guest_session["session_id"]

    time.sleep(2)
    res = real_chat_service.post_message(ctx, "నమస్కారం! మీరు ఎవరు?", sid)
    assert res["language"] == "te"
    # Content must contain authentic Telugu Unicode script
    assert bool(re.search(r"[\u0C00-\u0C7F]", res["content"]))

    time.sleep(2)
    res_rag = real_chat_service.post_message(ctx, "AICTE ప్రగతి స్కాలర్షిప్ అర్హతలు ఏమిటి?", sid)
    assert res_rag["language"] == "te"
    assert res_rag["intent"] == "scheme_inquiry"
    assert bool(re.search(r"[\u0C00-\u0C7F]", res_rag["content"]))
    assert len(res_rag["citations"]) >= 1
    # Canonical scheme name must not be distorted into broken Telugu translation
    assert ("AICTE" in res_rag["content"] and "Pragati" in res_rag["content"]) or "ప్రగతి" in res_rag["content"] or "AICTE Pragati" in res_rag["content"]


# ---------------------------------------------------------------------------
# 3. Real LLM: Hindi Script Queries
# ---------------------------------------------------------------------------
def test_real_llm_hindi_script_general_and_rag(real_chat_service, guest_session):
    """Real LLM test: Hindi-script queries return Devanagari Hindi answers and preserve citations."""
    ctx = guest_session["context"]
    sid = guest_session["session_id"]

    time.sleep(2)
    res = real_chat_service.post_message(ctx, "नमस्ते! आप कौन हैं?", sid)
    assert res["language"] == "hi"
    assert bool(re.search(r"[\u0900-\u097F]", res["content"]))

    time.sleep(2)
    res_rag = real_chat_service.post_message(ctx, "AICTE प्रगति छात्रवृत्ति की पात्रता क्या है?", sid)
    assert res_rag["language"] == "hi"
    assert res_rag["intent"] == "scheme_inquiry"
    assert bool(re.search(r"[\u0900-\u097F]", res_rag["content"]))
    assert len(res_rag["citations"]) >= 1
    assert ("AICTE" in res_rag["content"] and "Pragati" in res_rag["content"]) or "प्रगति" in res_rag["content"] or "AICTE Pragati" in res_rag["content"]


# ---------------------------------------------------------------------------
# 4. Real LLM: Romanized Telugu (Tenglish) Queries
# ---------------------------------------------------------------------------
def test_real_llm_romanized_telugu(real_chat_service, guest_session):
    """Real LLM test: Romanized Telugu (e.g., 'naaku scholarship kavali') yields authentic Telugu script."""
    ctx = guest_session["context"]
    sid = guest_session["session_id"]

    time.sleep(2)
    res = real_chat_service.post_message(ctx, "naaku scholarship kavali, schemes gurinchi cheppandi", sid)
    assert res["language"] == "te"
    assert bool(re.search(r"[\u0C00-\u0C7F]", res["content"]))


# ---------------------------------------------------------------------------
# 5. Real LLM: Romanized Hindi (Hinglish) Queries
# ---------------------------------------------------------------------------
def test_real_llm_romanized_hindi(real_chat_service, guest_session):
    """Real LLM test: Romanized Hindi (e.g., 'mujhe scholarship chahiye') yields authentic Hindi script."""
    ctx = guest_session["context"]
    sid = guest_session["session_id"]

    time.sleep(2)
    res = real_chat_service.post_message(ctx, "mujhe scholarship chahiye, kya eligibility hai?", sid)
    assert res["language"] == "hi"
    assert bool(re.search(r"[\u0900-\u097F]", res["content"]))


# ---------------------------------------------------------------------------
# 6. Real LLM: Multi-Turn Language Switching
# ---------------------------------------------------------------------------
def test_real_llm_multiturn_language_switching(real_chat_service):
    """Real LLM test: Switching languages dynamically across turns."""
    sess = real_chat_service.session_manager.create_guest_session()
    sid = sess["session_id"]
    ctx = {"is_guest": True, "guest_id": sess["guest_id"]}

    # Turn 1: English
    time.sleep(2)
    t1 = real_chat_service.post_message(ctx, "Tell me about PM-USP CSSS scholarship", sid)
    assert t1["language"] == "en"
    assert bool(re.search(r"[a-zA-Z]", t1["content"]))

    # Turn 2: Switch to Telugu
    time.sleep(2)
    t2 = real_chat_service.post_message(ctx, "దీనికి ఎంత మొత్తం వస్తుంది?", sid)
    assert t2["language"] == "te"
    assert bool(re.search(r"[\u0C00-\u0C7F]", t2["content"]))

    # Turn 3: Switch to Hindi
    time.sleep(2)
    t3 = real_chat_service.post_message(ctx, "आवेदन कैसे करना है?", sid)
    assert t3["language"] == "hi"
    assert bool(re.search(r"[\u0900-\u097F]", t3["content"]))

    # Turn 4: Explicit switch back to English
    time.sleep(2)
    t4 = real_chat_service.post_message(ctx, "Can you explain the last date in English?", sid)
    assert t4["language"] == "en"
    assert bool(re.search(r"[a-zA-Z]", t4["content"]))

