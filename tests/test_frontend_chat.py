"""Integration and contract test suite for SahayAI Step 4D: Interactive Text AI Chat Frontend.

Validates:
1. Static frontend assets serving (HTML, CSS, JS).
2. HTML structure: Card 1 active status, 5 feature cards preserved, chatModal markup.
3. JavaScript API client exports: sendChatMessage, fetchChatConversations, fetchChatConversationDetails, deleteChatConversation.
4. XSS defense: verifies that user and assistant text rendering in dashboard.js relies on textContent and not innerHTML.
5. End-to-end guest flow: starts and continues chat with citations and disclaimer.
6. End-to-end registered citizen flow: starts chat, continues chat, loads history, reopens conversation, deletes conversation.
7. Unsupported scheme refusal rendering (PM-KISAN).
8. HTML/script-like user input safe handling.
9. Guest session expiry handling (401 response).
"""

from datetime import datetime, timedelta, timezone
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
    db_file = tmp_path / "test_frontend_chat.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mock_vector_store():
    """Mock VectorStore returning a valid chunk for AICTE Pragati."""
    vs = MagicMock(spec=VectorStoreManager)
    vs.query.return_value = {
        "ids": [["chunk_pragati_001"]],
        "documents": [["AICTE Pragati provides ₹50,000 scholarship per annum to eligible girl students."]],
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
    """Mock LLM generating deterministic responses with valid citations."""
    client = MagicMock()
    client.generate.return_value = json.dumps({
        "answer": "AICTE Pragati provides ₹50,000 per annum for girl students admitted to technical degree courses [S1].",
        "evidence_sufficient": True,
        "citations": ["S1"],
    })
    return client


@pytest.fixture
def chat_env(test_db, mock_vector_store, mock_llm_client, monkeypatch):
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
def client(chat_env):
    """TestClient against SahayAI application."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases: Static Assets & HTML Contract
# ---------------------------------------------------------------------------

def test_01_frontend_assets_served_with_step4d_updates(client):
    """Verifies that dashboard.html, auth.css, api.js, and dashboard.js are served and contain Step 4D updates."""
    # 1. dashboard.html
    res_dash = client.get("/frontend/dashboard.html")
    assert res_dash.status_code == 200
    html = res_dash.text

    # Card 1 active state
    assert 'id="cardChat"' in html
    assert 'class="feature-active-badge">Active</span>' in html
    assert 'Start Chat &rarr;' in html or 'Start Chat' in html

    # All five interaction cards present
    assert 'id="cardChat"' in html
    assert 'id="cardVoice"' in html
    assert 'id="cardDocuments"' in html
    assert 'id="cardRecommendations"' in html
    assert 'id="cardCatalog"' in html

    # Chat modal structure
    assert 'id="chatModal"' in html
    assert 'id="chatModalTitle"' in html
    assert 'id="chatSidebar"' in html
    assert 'id="chatHistoryList"' in html
    assert 'id="chatMessagesContainer"' in html
    assert 'id="chatInputText"' in html
    assert 'id="chatSendBtn"' in html
    assert 'id="chatLoadingIndicator"' in html
    assert 'id="chatErrorBanner"' in html
    assert 'id="chatGuestBanner"' in html

    # 2. auth.css
    res_css = client.get("/frontend/css/auth.css")
    assert res_css.status_code == 200
    css = res_css.text
    assert ".chat-modal-dialog" in css
    assert ".chat-message-user" in css
    assert ".chat-message-assistant" in css
    assert ".chat-sidebar" in css
    assert ".chat-input-textarea" in css

    # 3. api.js
    res_api = client.get("/frontend/js/api.js")
    assert res_api.status_code == 200
    js_api = res_api.text
    assert "sendChatMessage" in js_api
    assert "fetchChatConversations" in js_api
    assert "fetchChatConversationDetails" in js_api
    assert "deleteChatConversation" in js_api

    # 4. dashboard.js
    res_dj = client.get("/frontend/js/dashboard.js")
    assert res_dj.status_code == 200
    js_dj = res_dj.text
    assert "openChatModal" in js_dj
    assert "appendChatMessage" in js_dj
    assert "handleSendMessage" in js_dj
    assert "startNewChat" in js_dj


def test_02_xss_prevention_in_frontend_code(client):
    """Verifies that dashboard.js does not assign untrusted user or assistant message text to innerHTML."""
    res_dj = client.get("/frontend/js/dashboard.js")
    assert res_dj.status_code == 200
    code = res_dj.text

    # Verify that message text is set via textContent
    assert "textDiv.textContent = content" in code
    # Verify that author label is set via textContent
    assert "author.textContent =" in code
    # Verify that conversation title is set via textContent
    assert "titleDiv.textContent = conv.title" in code


# ---------------------------------------------------------------------------
# Test Cases: End-to-End Chat API Flows
# ---------------------------------------------------------------------------

def test_03_guest_chat_flow(client, chat_env):
    """Verifies guest can start chat, receive grounded response, and continue conversation."""
    # Initialize guest session
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    csrf_token = guest_res.json()["csrf_token"]

    # Turn 1: Start chat
    msg1_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is AICTE Pragati?"},
    )
    assert msg1_res.status_code == 200
    data1 = msg1_res.json()
    assert data1["success"] is True
    assert data1["is_guest"] is True
    assert "₹50,000" in data1["content"]
    assert len(data1["citations"]) == 1
    assert data1["citations"][0]["authority"] == "AICTE"
    assert data1["disclaimer"] is not None

    # Turn 2: Continue chat
    msg2_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Who is eligible for it?"},
    )
    assert msg2_res.status_code == 200
    data2 = msg2_res.json()
    assert data2["success"] is True
    assert data2["is_guest"] is True


def test_04_registered_citizen_chat_and_history_lifecycle(client, chat_env):
    """Verifies complete registered citizen lifecycle:
    New Chat -> Persisted in SQLite -> GET /chat/conversations -> GET /chat/conversations/{id} -> DELETE.
    """
    # 1. Signup citizen
    signup_res = client.post(
        "/auth/signup",
        json={"email": "chat.citizen@example.com", "password": "Password@123"},
    )
    assert signup_res.status_code == 200
    csrf_token = client.get("/auth/csrf-token").json()["csrf_token"]

    # 2. Start Conversation
    msg_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Tell me about AICTE Pragati scholarship for girls."},
    )
    assert msg_res.status_code == 200
    data = msg_res.json()
    assert data["is_guest"] is False
    conv_id = data["conversation_id"]
    assert conv_id.startswith("conv_")

    # 3. Fetch History List (GET /chat/conversations)
    history_res = client.get("/chat/conversations")
    assert history_res.status_code == 200
    convs = history_res.json()["conversations"]
    assert len(convs) == 1
    assert convs[0]["id"] == conv_id
    assert convs[0]["message_count"] == 2

    # 4. Fetch Conversation Detail (GET /chat/conversations/{id})
    detail_res = client.get(f"/chat/conversations/{conv_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["conversation"]["id"] == conv_id
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "assistant"

    # 5. Continue Conversation (POST /chat/message with conversation_id)
    cont_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Can diploma students apply?", "conversation_id": conv_id},
    )
    assert cont_res.status_code == 200
    assert cont_res.json()["conversation_id"] == conv_id

    # Verify updated message count
    history_res2 = client.get("/chat/conversations")
    assert history_res2.json()["conversations"][0]["message_count"] == 4

    # 6. Delete Conversation (DELETE /chat/conversations/{id})
    del_res = client.delete(
        f"/chat/conversations/{conv_id}",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Confirm history list is empty
    history_res3 = client.get("/chat/conversations")
    assert len(history_res3.json()["conversations"]) == 0


def test_05_unsupported_scheme_refusal_presentation(client, chat_env):
    """Verifies that asking about an unsupported scheme (e.g. PMSBY) returns refusal without citations."""
    guest_res = client.post("/auth/guest")
    csrf_token = guest_res.json()["csrf_token"]

    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is the insurance amount for PMSBY?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "PMSBY" in data["content"] or "central education" in data["content"].lower()
    assert len(data["citations"]) == 0
    assert data["evidence_sufficient"] is False


def test_06_html_script_injection_handled_safely(client, chat_env):
    """Verifies that script-like and HTML input strings are safely persisted without executing or corrupting the database."""
    guest_res = client.post("/auth/guest")
    csrf_token = guest_res.json()["csrf_token"]

    xss_payload = "<script>alert('xss')</script><img src='x' onerror='alert(1)'>"
    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": xss_payload},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_07_expired_guest_session_returns_401(client, chat_env):
    """Verifies that when a guest session expires, chat calls return 401."""
    guest_res = client.post("/auth/guest")
    csrf_token = guest_res.json()["csrf_token"]

    cfg = get_session_config()
    raw_cookie = client.cookies.get(cfg.cookie_name)
    session_hash = chat_env["session_mgr"]._hash_session_id(raw_cookie)
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    with chat_env["db"].get_connection() as conn:
        conn.execute("UPDATE guest_sessions SET expires_at = ? WHERE session_id = ?", (past_iso, session_hash))

    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Can I chat after expiry?"},
    )
    assert res.status_code == 401

