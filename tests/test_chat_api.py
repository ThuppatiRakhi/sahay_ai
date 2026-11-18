"""Integration and contract test suite for SahayAI Chat Backend APIs and Persistence (Step 4C).

Validates:
1. Guest starts a conversation (POST /chat/message) with ephemeral context and no persistent rows.
2. Guest continues a conversation, maintaining rolling context in guest_sessions.context_json.
3. Registered citizen creates a conversation and retrieves list (GET /chat/conversations).
4. Registered citizen continues previous conversation (POST /chat/message with conversation_id).
5. User A cannot access User B's conversation (IDOR defense: returns 404).
6. User A cannot delete User B's conversation (returns 404).
7. Guest cannot access registered-user history endpoints (returns 403).
8. Expired guest session cannot continue conversation (returns 401).
9. Guest rolling conversation context is bounded to 10 messages (5 turns) in chronological order.
10. Unsupported scheme query (e.g. PM-KISAN) returns structured refusal without vector store query.
11. Invalid / unverified citations are flagged safely without application error.
12. CSRF protection is strictly enforced for mutating chat endpoints (POST /chat/message, DELETE /chat/conversations/{id}).
13. Registered citizen can delete their own conversation with cascading cleanup of messages.
"""

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import MagicMock, patch
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
    db_file = tmp_path / "test_chat_api.db"
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
    """Mock LLM generating deterministic responses with valid citations."""
    client = MagicMock()
    client.generate.return_value = json.dumps({
        "answer": "AICTE Pragati provides ₹50,000 per annum to eligible girl students admitted to technical degree courses [S1].",
        "evidence_sufficient": True,
        "citations": ["S1"],
    })
    return client


@pytest.fixture
def mock_rag_generator(mock_vector_store, mock_llm_client):
    """Constructs a RAGAnswerGenerator with mocked embeddings and vector store."""
    embedding_service = EmbeddingService(use_mock=True)
    rewriter = QueryRewriter()
    reranker = LightweightReranker()
    retriever = SchemeRetriever(
        vector_store=mock_vector_store,
        embedding_service=embedding_service,
        query_rewriter=rewriter,
        reranker=reranker,
    )
    return RAGAnswerGenerator(
        retriever=retriever,
        llm_client=mock_llm_client,
    )


@pytest.fixture
def chat_env(test_db, mock_rag_generator, monkeypatch):
    """Configures isolated auth, session, and chat services for FastAPI testing."""
    accounts = AccountManager(db=test_db)
    profiles = ProfileManager(db=test_db)
    auth_svc = AuthService(account_manager=accounts, profile_manager=profiles)
    session_mgr = SessionManager(db=test_db)
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
        "mock_vector_store": mock_rag_generator.retriever.vector_store,
        "mock_llm_client": mock_rag_generator.llm_client,
    }


@pytest.fixture
def client(chat_env):
    """TestClient against SahayAI application with isolated chat environment."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def init_guest_session(client):
    """Initializes a guest session and returns session cookies and CSRF token."""
    res = client.post("/auth/guest")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["is_guest"] is True
    guest_id = data["guest_id"]
    csrf_token = data["csrf_token"]
    return guest_id, csrf_token


def signup_and_login_citizen(client, email="citizen@example.com", password="Password@123"):
    """Registers and logs in a citizen, returning user_id and CSRF token."""
    signup_res = client.post(
        "/auth/signup",
        json={"email": email, "password": password},
    )
    assert signup_res.status_code == 200
    user_id = signup_res.json()["user"]["user_id"]

    csrf_res = client.get("/auth/csrf-token")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]
    return user_id, csrf_token


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_01_guest_starts_conversation(client, chat_env):
    """Requirement 1: Guest starts a conversation, receiving grounded RAG guidance.
    
    Verifies:
    - 200 response with answer, citations, disclaimer, and is_guest=True.
    - Zero rows created in persistent SQLite chat tables (chat_conversations, chat_messages).
    - Ephemeral rolling context stored in guest_sessions.context_json.
    """
    guest_id, csrf_token = init_guest_session(client)

    response = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is the eligibility for AICTE Pragati?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["is_guest"] is True
    assert data["conversation_id"] == f"guest_{guest_id}"
    assert "₹50,000" in data["content"]
    assert len(data["citations"]) == 1
    assert data["citations"][0]["authority"] == "AICTE"
    assert data["disclaimer"] is not None

    # Verify zero rows in persistent chat tables
    with chat_env["db"].get_connection() as conn:
        conv_count = conn.execute("SELECT COUNT(*) FROM chat_conversations").fetchone()[0]
        msg_count = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        assert conv_count == 0
        assert msg_count == 0

    # Verify ephemeral context updated in guest_sessions
    cfg = get_session_config()
    raw_cookie = client.cookies.get(cfg.cookie_name)
    guest_record = chat_env["session_mgr"].get_guest_session(raw_cookie)
    assert guest_record is not None
    chat_hist = guest_record.get("context", {}).get("chat_history", [])
    assert len(chat_hist) == 2
    assert chat_hist[0]["role"] == "user"
    assert chat_hist[0]["content"] == "What is the eligibility for AICTE Pragati?"
    assert chat_hist[1]["role"] == "assistant"
    assert "₹50,000" in chat_hist[1]["content"]


def test_02_guest_continues_conversation(client, chat_env):
    """Requirement 2: Guest continues an existing conversation across multiple turns.
    
    Verifies:
    - Prior turns are retained in guest_sessions.context_json.
    - Conversation history is fed to the RAG pipeline.
    """
    guest_id, csrf_token = init_guest_session(client)

    # First turn
    res1 = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is AICTE Pragati?"},
    )
    assert res1.status_code == 200

    # Second turn
    res2 = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is the scholarship amount?"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["conversation_id"] == f"guest_{guest_id}"

    # Verify context has 4 messages (2 user, 2 assistant)
    cfg = get_session_config()
    raw_cookie = client.cookies.get(cfg.cookie_name)
    guest_record = chat_env["session_mgr"].get_guest_session(raw_cookie)
    chat_hist = guest_record.get("context", {}).get("chat_history", [])
    assert len(chat_hist) == 4
    assert [m["role"] for m in chat_hist] == ["user", "assistant", "user", "assistant"]


def test_03_registered_user_creates_and_lists_conversations(client, chat_env):
    """Requirement 3: Registered citizen creates a conversation persisted in SQLite.
    
    Verifies:
    - POST /chat/message persists conversation and messages.
    - GET /chat/conversations returns the conversation overview with message_count.
    """
    user_id, csrf_token = signup_and_login_citizen(client, email="citizen3@example.com")

    # Start new conversation
    prompt = "Tell me about the eligibility for AICTE Pragati scholarship scheme."
    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": prompt},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["is_guest"] is False
    conv_id = data["conversation_id"]
    assert conv_id.startswith("conv_")

    # Verify SQLite persistence
    with chat_env["db"].get_connection() as conn:
        conv_row = conn.execute(
            "SELECT id, user_id, title FROM chat_conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
        assert conv_row is not None
        assert conv_row["user_id"] == user_id
        assert "AICTE Pragati" in conv_row["title"]

        msg_rows = conn.execute(
            "SELECT role, content FROM chat_messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv_id,),
        ).fetchall()
        assert len(msg_rows) == 2
        assert msg_rows[0]["role"] == "user"
        assert msg_rows[0]["content"] == prompt
        assert msg_rows[1]["role"] == "assistant"

    # Verify GET /chat/conversations
    list_res = client.get("/chat/conversations")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["success"] is True
    assert len(list_data["conversations"]) == 1
    item = list_data["conversations"][0]
    assert item["id"] == conv_id
    assert item["message_count"] == 2
    assert item["created_at"] is not None
    assert item["updated_at"] is not None


def test_04_registered_user_continues_previous_conversation(client, chat_env):
    """Requirement 4: Registered citizen continues an existing conversation.
    
    Verifies:
    - Passing conversation_id appends new turns to the existing conversation.
    - GET /chat/conversations/{id} returns all messages chronologically.
    """
    user_id, csrf_token = signup_and_login_citizen(client, email="citizen4@example.com")

    # Turn 1
    res1 = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is AICTE Pragati?"},
    )
    assert res1.status_code == 200
    conv_id = res1.json()["conversation_id"]

    # Turn 2 continuing the conversation
    res2 = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What documents are required?", "conversation_id": conv_id},
    )
    assert res2.status_code == 200
    assert res2.json()["conversation_id"] == conv_id

    # Retrieve full conversation
    detail_res = client.get(f"/chat/conversations/{conv_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["success"] is True
    assert detail_data["conversation"]["id"] == conv_id
    messages = detail_data["messages"]
    assert len(messages) == 4
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "What is AICTE Pragati?"
    assert messages[2]["content"] == "What documents are required?"
    assert len(messages[1]["citations"]) == 1


def test_05_idor_protection_user_cannot_access_other_users_conversation(client, chat_env):
    """Requirement 5: User A cannot read or continue User B's conversation (IDOR defense).
    
    Verifies:
    - Access attempts return HTTP 404 Not Found without leaking existence.
    """
    # Create User A's conversation
    _, csrf_a = signup_and_login_citizen(client, email="user_a@example.com")
    res_a = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_a},
        json={"message": "Private conversation of User A"},
    )
    conv_a = res_a.json()["conversation_id"]

    # Register and log in User B
    _, csrf_b = signup_and_login_citizen(client, email="user_b@example.com")

    # User B attempts to read User A's conversation
    read_res = client.get(f"/chat/conversations/{conv_a}")
    assert read_res.status_code == 404
    assert "not found" in read_res.json()["detail"].lower()

    # User B attempts to post to User A's conversation
    post_res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_b},
        json={"message": "Unauthorized post attempt", "conversation_id": conv_a},
    )
    assert post_res.status_code == 404
    assert "not found" in post_res.json()["detail"].lower()


def test_06_idor_protection_user_cannot_delete_other_users_conversation(client, chat_env):
    """Requirement 6: User B cannot delete User A's conversation.
    
    Verifies:
    - DELETE returns HTTP 404 Not Found.
    - User A's conversation remains fully intact in SQLite.
    """
    # Create User A's conversation
    _, csrf_a = signup_and_login_citizen(client, email="user_a_del@example.com")
    res_a = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_a},
        json={"message": "Confidential scheme inquiries for User A"},
    )
    conv_a = res_a.json()["conversation_id"]

    # Switch to User B
    _, csrf_b = signup_and_login_citizen(client, email="user_b_del@example.com")

    # User B attempts to delete User A's conversation
    del_res = client.delete(
        f"/chat/conversations/{conv_a}",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_b},
    )
    assert del_res.status_code == 404

    # Verify conversation and messages still exist in database
    with chat_env["db"].get_connection() as conn:
        conv_row = conn.execute("SELECT id FROM chat_conversations WHERE id = ?", (conv_a,)).fetchone()
        assert conv_row is not None
        msg_count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (conv_a,)).fetchone()[0]
        assert msg_count == 2


def test_07_guest_cannot_access_registered_history_endpoints(client):
    """Requirement 7: Anonymous guests are blocked from registered-user conversation history.
    
    Verifies:
    - GET /chat/conversations returns HTTP 403 Forbidden.
    - GET /chat/conversations/{id} returns HTTP 403 Forbidden.
    - DELETE /chat/conversations/{id} returns HTTP 403 Forbidden.
    """
    _, csrf_token = init_guest_session(client)

    # List conversations
    res_list = client.get("/chat/conversations")
    assert res_list.status_code == 403
    assert "registered account feature" in res_list.json()["detail"].lower()

    # Detail view
    res_detail = client.get("/chat/conversations/conv_any123456")
    assert res_detail.status_code == 403
    assert "registered account feature" in res_detail.json()["detail"].lower()

    # Delete
    res_del = client.delete(
        "/chat/conversations/conv_any123456",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert res_del.status_code == 403
    assert "registered account feature" in res_del.json()["detail"].lower()


def test_08_expired_guest_session_cannot_continue_conversation(client, chat_env):
    """Requirement 8: Expired guest session is rejected with HTTP 401 Unauthorized."""
    _, csrf_token = init_guest_session(client)

    # Force expiration of the guest session in SQLite
    cfg = get_session_config()
    raw_cookie = client.cookies.get(cfg.cookie_name)
    session_hash = chat_env["session_mgr"]._hash_session_id(raw_cookie)
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    with chat_env["db"].get_connection() as conn:
        conn.execute("UPDATE guest_sessions SET expires_at = ? WHERE session_id = ?", (past_iso, session_hash))

    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Can I continue after my session expired?"},
    )
    assert res.status_code == 401


def test_09_guest_rolling_history_bounded_and_ordered(client, chat_env):
    """Requirement 9: Guest rolling conversation context is capped at 10 messages (5 turns).
    
    Verifies:
    - Oldest messages are purged when limit is exceeded.
    - Exactly 10 messages remain, ordered chronologically.
    """
    _, csrf_token = init_guest_session(client)

    # Post 7 user messages (would be 14 messages total)
    for i in range(1, 8):
        res = client.post(
            "/chat/message",
            headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
            json={"message": f"Question number {i} regarding AICTE Pragati"},
        )
        assert res.status_code == 200

    cfg = get_session_config()
    raw_cookie = client.cookies.get(cfg.cookie_name)
    guest_record = chat_env["session_mgr"].get_guest_session(raw_cookie)
    chat_hist = guest_record.get("context", {}).get("chat_history", [])

    # Must be bounded to exactly 10 messages (5 turns)
    assert len(chat_hist) == 10

    # Oldest retained message should be Question 3 (Questions 1 and 2 purged)
    first_retained_user_msg = chat_hist[0]["content"]
    assert "Question number 3" in first_retained_user_msg

    # Newest retained message should be Question 7
    last_user_msg = chat_hist[-2]["content"]
    assert "Question number 7" in last_user_msg


def test_10_unsupported_scheme_refusal_without_vector_store_query(client, chat_env):
    """Requirement 10: Explicit unsupported schemes (PMSBY) return safe refusal.
    
    Verifies:
    - Pre-retrieval refusal is returned.
    - Vector store query is NOT performed.
    - Citations are empty.
    """
    _, csrf_token = init_guest_session(client)

    # Reset vector store call count
    chat_env["mock_vector_store"].query.reset_mock()

    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Can a person get insurance under PMSBY?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "PMSBY" in data["content"] or "central education" in data["content"].lower()
    assert len(data["citations"]) == 0
    assert data["evidence_sufficient"] is False

    # Vector store query should NOT have been invoked
    chat_env["mock_vector_store"].query.assert_not_called()


def test_11_invalid_citation_handled_safely(client, chat_env):
    """Requirement 11: LLM-fabricated citations are flagged by validation and handled safely.
    
    Verifies:
    - System does not crash.
    - Citation validation metadata reports invalid citations.
    """
    _, csrf_token = init_guest_session(client)

    # Force mock LLM to cite non-existent chunk [S99]
    chat_env["mock_llm_client"].generate.return_value = json.dumps({
        "answer": "This answer contains a fabricated citation [S99].",
        "evidence_sufficient": True,
        "citations": ["S99"],
    })

    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "What is AICTE Pragati?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    # Citation validation should flag the invented citation
    val = data.get("citation_validation", {})
    assert val.get("is_valid") is False or len(val.get("invalid_citations", [])) > 0


def test_12_csrf_protection_on_mutating_chat_endpoints(client, chat_env):
    """Requirement 12: CSRF protection is enforced on mutating requests.
    
    Verifies:
    - Missing CSRF header returns HTTP 403 Forbidden.
    - Invalid CSRF token returns HTTP 403 Forbidden.
    - Untrusted Origin returns HTTP 403 Forbidden.
    """
    _, csrf_token = init_guest_session(client)

    # 1. Missing CSRF header
    res_no_csrf = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500"},
        json={"message": "Hello"},
    )
    assert res_no_csrf.status_code == 403
    assert "csrf" in res_no_csrf.json()["detail"].lower()

    # 2. Tampered CSRF token
    res_bad_csrf = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": "tampered_token_value"},
        json={"message": "Hello"},
    )
    assert res_bad_csrf.status_code == 403

    # 3. Untrusted origin
    res_bad_origin = client.post(
        "/chat/message",
        headers={"Origin": "https://malicious-site.com", "X-CSRF-Token": csrf_token},
        json={"message": "Hello"},
    )
    assert res_bad_origin.status_code == 403


def test_13_registered_user_deletes_own_conversation(client, chat_env):
    """Requirement 13: Registered user can delete their conversation with cascade message cleanup.
    
    Verifies:
    - DELETE /chat/conversations/{id} returns 200.
    - Both conversation record and all message records are deleted from SQLite.
    - GET /chat/conversations confirms the conversation is gone.
    """
    user_id, csrf_token = signup_and_login_citizen(client, email="citizen_del@example.com")

    # Create conversation
    res = client.post(
        "/chat/message",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
        json={"message": "Scheme query to be deleted."},
    )
    assert res.status_code == 200
    conv_id = res.json()["conversation_id"]

    # Delete the conversation
    del_res = client.delete(
        f"/chat/conversations/{conv_id}",
        headers={"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token},
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Verify SQLite deletion
    with chat_env["db"].get_connection() as conn:
        conv_row = conn.execute("SELECT id FROM chat_conversations WHERE id = ?", (conv_id,)).fetchone()
        assert conv_row is None
        msg_count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (conv_id,)).fetchone()[0]
        assert msg_count == 0

    # Verify conversation list is empty
    list_res = client.get("/chat/conversations")
    assert list_res.status_code == 200
    assert len(list_res.json()["conversations"]) == 0

