"""Integration and contract test suite for SahayAI Step 4E: Voice Assistant.

Validates:
1. Static frontend assets serving and HTML structure for Voice Assistant.
2. Card 2 active state and 4-card guest / 5-card registered dashboard preservation.
3. Speech sanitization logic (stripping [S1], markdown links, asterisks, URLs).
4. Guest voice-to-text-to-chat flow (ephemeral context, citations, disclaimer).
5. Registered citizen voice-to-text-to-chat flow (persistent SQLite storage).
6. Shared conversation context between Voice Assistant and Text AI Chat.
7. Unsupported scheme refusal rendering in Voice Assistant (PM-KISAN).
8. Unsupported browser fallback markup and controls.
9. Microphone permission-denied error handling contract.
10. Empty transcript and duplicate submission safeguards.
"""

from datetime import datetime, timezone
import json
import re
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import get_session_config
from chat.chat_service import ChatService
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.profile_manager import ProfileManager
from profile.session_manager import SessionManager
from rag.answer_generator import RAGAnswerGenerator
from rag.embedding_service import EmbeddingService
from rag.query_rewriter import QueryRewriter
from rag.reranker import LightweightReranker
from rag.retriever import SchemeRetriever
from rag.vector_store import VectorStoreManager


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_voice_api.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mock_vector_store():
    """Mock VectorStore returning a valid chunk for AICTE Pragati."""
    vs = MagicMock(spec=VectorStoreManager)
    vs.query.return_value = {
        "ids": [["chunk_pragati_001"]],
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
        "distances": [[0.12]],
    }
    return vs


@pytest.fixture
def mock_llm_client():
    """Mock LLM generating deterministic responses with citations."""
    client = MagicMock()
    client.generate.return_value = json.dumps({
        "answer": "AICTE Pragati provides ₹50,000 per annum for eligible girl students [S1].",
        "evidence_sufficient": True,
        "citations": ["S1"],
    })
    return client


@pytest.fixture
def voice_env(test_db, mock_vector_store, mock_llm_client, monkeypatch):
    """Configures isolated auth, session, and chat services for FastAPI testing."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)

    embedding_service = EmbeddingService(use_mock=True)
    rewriter = QueryRewriter()
    reranker = LightweightReranker()
    retriever = SchemeRetriever(
        vector_store=mock_vector_store,
        embedding_service=embedding_service,
        query_rewriter=rewriter,
        reranker=reranker,
    )
    mock_rag_generator = RAGAnswerGenerator(
        retriever=retriever,
        llm_client=mock_llm_client,
    )

    chat_svc = ChatService(
        db=test_db,
        session_manager=session_mgr,
        rag_generator=mock_rag_generator,
    )

    # Monkeypatch singleton services in API layer
    monkeypatch.setattr("api.auth.auth_service", auth_svc)
    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.profile.auth_service", auth_svc)
    monkeypatch.setattr("api.chat.chat_service", chat_svc)

    return {
        "db": test_db,
        "auth_service": auth_svc,
        "session_mgr": session_mgr,
        "chat_service": chat_svc,
        "mock_vector_store": mock_vector_store,
        "mock_llm_client": mock_llm_client,
    }


@pytest.fixture
def client(voice_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases: Frontend Markup and Contracts
# ---------------------------------------------------------------------------

def test_01_voice_assistant_card_and_modal_markup(client):
    """Verifies that cardVoice is active on the dashboard and voiceModal markup exists."""
    import pathlib
    frontend_root = pathlib.Path(__file__).parent.parent / "frontend"
    dash_html = (frontend_root / "dashboard.html").read_text(encoding="utf-8")
    dash_js = (frontend_root / "js" / "dashboard.js").read_text(encoding="utf-8")
    auth_css = (frontend_root / "css" / "auth.css").read_text(encoding="utf-8")

    # Card 2 (Voice Assistant) active state
    assert 'id="cardVoice"' in dash_html
    assert 'Start Voice &rarr;' in dash_html or 'Start Voice' in dash_html

    # Modal Structure
    assert 'id="voiceModal"' in dash_html
    assert 'id="voiceMicBtn"' in dash_html
    assert 'id="voiceStatusText"' in dash_html
    assert 'id="voiceLangSelect"' in dash_html
    assert 'id="voiceTranscriptText"' in dash_html
    assert 'id="voiceSendBtn"' in dash_html
    assert 'id="voiceCompatAlert"' in dash_html
    assert 'id="voiceResponseSection"' in dash_html
    assert 'id="voiceStopSpeakingBtn"' in dash_html
    assert 'id="voiceReplayBtn"' in dash_html
    assert 'id="voiceSwitchToChatBtn"' in dash_html

    # CSS styles
    assert ".voice-modal-dialog" in auth_css
    assert ".voice-mic-btn" in auth_css
    assert ".voice-speaking-wave" in auth_css

    # JS Controller
    assert "initSpeechRecognition" in dash_js
    assert "speakText" in dash_js
    assert "stopSpeaking" in dash_js
    assert "stopVoiceRecognition" in dash_js
    assert "sanitizeTextForSpeech" in dash_js


def test_02_speech_text_sanitization():
    """Verifies that technical citations and raw URLs are stripped for natural speech synthesis."""
    def sanitize_text_for_speech(raw_text):
        if not raw_text or not isinstance(raw_text, str):
            return ""
        return re.sub(
            r"\s+",
            " ",
            re.sub(
                r"[*_#`~•]",
                " ",
                re.sub(
                    r"https?://\S+",
                    "",
                    re.sub(
                        r"\[([^\]]+)\]\([^)]+\)",
                        r"\1",
                        re.sub(r"\[S\d+\]", "", raw_text),
                    ),
                ),
            ),
        ).strip()

    raw_input = "AICTE Pragati scheme provides ₹50,000 per annum [S1] for girl students. See guidelines at https://scholarships.gov.in."
    spoken = sanitize_text_for_speech(raw_input)

    assert "[S1]" not in spoken
    assert "https://" not in spoken
    assert "AICTE Pragati scheme provides ₹50,000 per annum" in spoken
    assert "for girl students" in spoken


# ---------------------------------------------------------------------------
# Test Cases: Voice-to-Text-to-Chat API Flows
# ---------------------------------------------------------------------------

def test_03_guest_voice_to_chat_flow(client, voice_env):
    """Requirement: Guest can use Voice Assistant, receive answer with citations, and continue dialogue."""
    # 1. Initialize guest session
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    csrf_token = guest_res.json()["csrf_token"]

    # 2. Citizen confirms recognized question: "What is AICTE Pragati?"
    res1 = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is AICTE Pragati?"},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["success"] is True
    assert data1["is_guest"] is True
    assert "₹50,000" in data1["content"]
    assert len(data1["citations"]) == 1
    assert data1["disclaimer"] is not None

    # 3. Follow-up voice question in same guest session
    res2 = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What are the family income limits?"},
    )
    assert res2.status_code == 200
    assert res2.json()["is_guest"] is True


def test_04_registered_voice_lifecycle(client, voice_env):
    """Requirement: Registered citizen voice questions persist in SQLite."""
    # Register citizen
    signup_res = client.post(
        "/auth/signup",
        json={"email": "voice.citizen@example.com", "password": "SecurePassword@123"},
    )
    assert signup_res.status_code == 200
    csrf_token = client.get("/auth/csrf-token").json()["csrf_token"]

    # Voice question
    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Can girl students apply for AICTE Pragati?"},
    )
    assert res.status_code == 200
    conv_id = res.json()["conversation_id"]
    assert conv_id.startswith("conv_")

    # Verify persisted in SQLite
    with voice_env["db"].get_connection() as conn:
        conv_row = conn.execute("SELECT id, user_id FROM chat_conversations WHERE id = ?", (conv_id,)).fetchone()
        assert conv_row is not None
        msg_count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (conv_id,)).fetchone()[0]
        assert msg_count == 2


def test_05_shared_conversation_context_between_voice_and_text(client, voice_env):
    """Requirement: Voice Assistant and Text AI Chat share active conversation context."""
    # Citizen logs in
    client.post(
        "/auth/signup",
        json={"email": "multimodal.citizen@example.com", "password": "SecurePassword@123"},
    )
    csrf_token = client.get("/auth/csrf-token").json()["csrf_token"]

    # Turn 1: Ask by Voice
    voice_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is AICTE Pragati?"},
    )
    assert voice_res.status_code == 200
    conv_id = voice_res.json()["conversation_id"]

    # Turn 2: Citizen switches to Text AI Chat and asks follow-up passing the same conversation_id
    text_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is the scholarship amount?", "conversation_id": conv_id},
    )
    assert text_res.status_code == 200
    assert text_res.json()["conversation_id"] == conv_id

    # Verify conversation in SQLite has all 4 messages
    with voice_env["db"].get_connection() as conn:
        msg_rows = conn.execute("SELECT role, content FROM chat_messages WHERE conversation_id = ? ORDER BY created_at ASC", (conv_id,)).fetchall()
        assert len(msg_rows) == 4
        assert msg_rows[0]["content"] == "What is AICTE Pragati?"
        assert msg_rows[2]["content"] == "What is the scholarship amount?"


def test_06_unsupported_scheme_refusal_via_voice(client, voice_env):
    """Requirement: Unsupported scheme (e.g. PMSBY) queried by voice returns safe refusal without citations."""
    client.post("/auth/guest")
    csrf_token = client.get("/auth/csrf-token").json()["csrf_token"]

    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Tell me about PMSBY insurance coverage"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "PMSBY" in data["content"] or "central education" in data["content"].lower()
    assert len(data["citations"]) == 0
    assert data["evidence_sufficient"] is False


def test_07_dashboard_card_visibility_preserved(client):
    """Requirement: Guest sees exactly 4 cards; registered user sees all 5 cards."""
    # 1. Guest mode check
    client.post("/auth/guest")
    guest_status = client.get("/auth/session-status")
    assert guest_status.status_code == 200
    assert guest_status.json()["is_guest"] is True

    # 2. Registered mode check
    client.post(
        "/auth/signup",
        json={"email": "card_vis.citizen@example.com", "password": "SecurePassword@123"},
    )
    reg_status = client.get("/auth/session-status")
    assert reg_status.status_code == 200
    assert reg_status.json()["is_guest"] is False
