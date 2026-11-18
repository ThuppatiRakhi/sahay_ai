"""Tests for SahayAI Natural Language Understanding and Intelligent Intent Routing.

Covers:
1. Greetings with various spellings & typos in English, Hindi, and Telugu (including Hinglish/Tenglish).
2. Small talk, gratitude, and acknowledgments.
3. General knowledge questions (geography, history, science).
4. Academic & programming questions (recursion, photosynthesis, Python, algorithms).
5. Indirect scholarship discovery based on user circumstances (BTech, female, disabled, orphan, SC, OBC).
6. Typo-tolerant scheme entity matching (prgati, sakshm, swanth, pm usp, top clas sc).
7. Topic switching & context break (scholarship -> recursion -> no citations, no disclaimers).
8. Context-aware follow-ups (Pragati -> "what documents are required?").
9. Unsupported scheme interception (PM-KISAN, PMSBY).
10. Ambiguous message clarification (no vector search, polite natural prompt).
11. Absence of scheme citations and disclaimers on non-scheme responses.
12. Data-driven catalog indexing scalability (adding new schemes without code modification).
13. Vector store query is NOT called for non-scheme queries.
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from chat.conversational_handler import ConversationalHandler
from chat.intent_router import IntentRouter, IntentType
from chat.scheme_catalog_index import SchemeCatalogIndex
from chat.chat_service import ChatService
from profile.database import Database
from profile.session_manager import SessionManager
from rag.answer_generator import RAGAnswerGenerator
from rag.embedding_service import EmbeddingService
from rag.query_rewriter import QueryRewriter
from rag.reranker import LightweightReranker
from rag.retriever import SchemeRetriever
from rag.vector_store import VectorStoreManager


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_sahay_nlu.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mock_vector_store():
    """Mock VectorStore returning a valid chunk for Pragati."""
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
def mock_llm():
    """Mock LLM returning deterministic conversational and RAG responses."""
    client = MagicMock()
    # Default to a general conversational response
    client.generate.return_value = "Hello! I am SahayAI, your digital assistant."
    return client


@pytest.fixture
def catalog_index():
    return SchemeCatalogIndex()


@pytest.fixture
def intent_router(catalog_index):
    return IntentRouter(catalog_index=catalog_index)


@pytest.fixture
def nlu_chat_service(test_db, mock_vector_store, mock_llm, catalog_index, intent_router):
    """Constructs ChatService wired with mocked vector store and controlled LLM."""
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
        llm_client=mock_llm,
    )
    conv_handler = ConversationalHandler(llm_client=mock_llm)
    session_manager = SessionManager(db=test_db)

    return ChatService(
        db=test_db,
        session_manager=session_manager,
        rag_generator=rag_generator,
        intent_router=intent_router,
        conversational_handler=conv_handler,
    )


# ===========================================================================
# 1. Intent Router Unit Tests: Greetings, Small Talk & Gratitude
# ===========================================================================

class TestGreetingsAndSmallTalkRouting:
    """Verifies that natural greetings with typos and various languages route to GENERAL_CONVERSATION."""

    @pytest.mark.parametrize("greeting", [
        "Hello", "hello", "hi", "helo", "hii", "heyyy", "hlo", "hellow",
        "good morning", "good evening", "gud mrng",
        "namaste", "Namaskar", "namaskaram", "pranam", "नमस्ते", "నమస్కారం",
        "kya haal hai", "ela unnaru", "bagunnara",
    ])
    def test_greetings_classified_as_general_conversation(self, intent_router, greeting):
        res = intent_router.route(greeting)
        assert res.intent == IntentType.GENERAL_CONVERSATION
        assert res.confidence >= 0.90
        assert res.detected_scheme_id is None

    @pytest.mark.parametrize("gratitude", [
        "Thank you", "thanks", "thanks a lot", "thx", "ty", "okay got it",
        "dhanyavad", "shukriya", "dhanyavadalu", "धन्यवाद", "ధన్యవాదాలు", "theek hai", "sare",
    ])
    def test_gratitude_classified_as_general_conversation(self, intent_router, gratitude):
        res = intent_router.route(gratitude)
        assert res.intent == IntentType.GENERAL_CONVERSATION
        assert res.confidence >= 0.90

    @pytest.mark.parametrize("small_talk", [
        "Who are you?", "What is your name?", "What can you do?",
        "Tell me a joke", "Are you an AI?", "How are you doing?",
        "tum kaun ho", "meeru evaru", "kaise ho",
    ])
    def test_small_talk_classified_as_general_conversation(self, intent_router, small_talk):
        res = intent_router.route(small_talk)
        assert res.intent == IntentType.GENERAL_CONVERSATION


# ===========================================================================
# 2. General Knowledge & Academic / Programming Questions
# ===========================================================================

class TestGeneralKnowledgeAndAcademics:
    """Verifies general academic and programming queries route to GENERAL_CONVERSATION without ChromaDB."""

    @pytest.mark.parametrize("query", [
        "What is recursion?",
        "Explain photosynthesis in plants",
        "How to reverse a string in Python?",
        "What is binary search algorithm?",
        "Who was APJ Abdul Kalam?",
        "What is the capital of India?",
        "Why is the sky blue?",
        "What is Newton's third law of motion?",
    ])
    def test_academic_queries_classified_as_general(self, intent_router, query):
        res = intent_router.route(query)
        assert res.intent == IntentType.GENERAL_CONVERSATION
        assert res.detected_scheme_id is None


# ===========================================================================
# 3. Typo-Tolerant Scheme Name Recognition
# ===========================================================================

class TestTypoTolerantSchemeRecognition:
    """Verifies scheme inquiries with misspellings confidently resolve to the correct scheme."""

    @pytest.mark.parametrize("query,expected_scheme_id", [
        # Pragati typos
        ("tell me about prgati scolarship", "SCHEME_EDU_002_AICTE_PRAGATI"),
        ("prgti scholarship for girls", "SCHEME_EDU_002_AICTE_PRAGATI"),
        ("aicte prgati eligibility", "SCHEME_EDU_002_AICTE_PRAGATI"),
        # Saksham typos
        ("what is elgibility for sakshm", "SCHEME_EDU_003_AICTE_SAKSHAM"),
        ("aicte sakshm scholarship amount", "SCHEME_EDU_003_AICTE_SAKSHAM"),
        # Swanath typos
        ("swanth scholarship for orphan students", "SCHEME_EDU_004_AICTE_SWANATH"),
        ("aicte swanth scheme details", "SCHEME_EDU_004_AICTE_SWANATH"),
        # CSSS / PM-USP
        ("pm usp csss scholarship criteria", "SCHEME_EDU_001_PM_USP_CSSS"),
        ("pmusp central sector scheme", "SCHEME_EDU_001_PM_USP_CSSS"),
        # Top Class SC typos
        ("top clas education for sc students", "SCHEME_EDU_005_TOP_CLASS_SC"),
        ("top clas sc scholarship", "SCHEME_EDU_005_TOP_CLASS_SC"),
    ])
    def test_scheme_typo_resolution(self, intent_router, query, expected_scheme_id):
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.detected_scheme_id == expected_scheme_id


# ===========================================================================
# 4. Indirect Scheme Discovery & Multilingual Circumstances
# ===========================================================================

class TestIndirectSchemeDiscovery:
    """Verifies discovery questions based on user circumstances extract attributes and find candidate schemes."""

    def test_btech_girl_discovery(self, intent_router):
        query = "I am a BTech girl student. Can I get financial support?"
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.is_discovery is True
        assert "SCHEME_EDU_002_AICTE_PRAGATI" in res.candidate_scheme_ids

    def test_disabled_student_discovery(self, intent_router):
        query = "Are there any scholarships for disabled students in engineering?"
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.is_discovery is True
        assert "SCHEME_EDU_003_AICTE_SAKSHAM" in res.candidate_scheme_ids

    def test_orphan_student_discovery(self, intent_router):
        query = "What help is available for orphan students in technical courses?"
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.is_discovery is True
        assert "SCHEME_EDU_004_AICTE_SWANATH" in res.candidate_scheme_ids

    def test_sc_student_discovery(self, intent_router):
        query = "What scholarship can I apply for? I am an SC student in college."
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.is_discovery is True
        assert "SCHEME_EDU_005_TOP_CLASS_SC" in res.candidate_scheme_ids

    def test_tenglish_girl_discovery(self, intent_router):
        query = "btech ammayilaki emaina scholarships unnaya?"
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.is_discovery is True
        assert "SCHEME_EDU_002_AICTE_PRAGATI" in res.candidate_scheme_ids

    def test_hinglish_technical_scholarship(self, intent_router):
        query = "kya mujhe btech ke liye koi scholarship mil sakti hai?"
        res = intent_router.route(query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.is_discovery is True


# ===========================================================================
# 5. Topic Switching & Context Break
# ===========================================================================

class TestTopicSwitchingAndContextBreak:
    """Verifies that switching from a scheme topic to a general topic resets scheme context."""

    def test_topic_switch_from_pragati_to_recursion(self, intent_router):
        # Prior history discussed AICTE Pragati
        history = [
            {"role": "user", "content": "Tell me about AICTE Pragati scholarship"},
            {"role": "assistant", "content": "AICTE Pragati provides ₹50,000 per annum to girl students."},
        ]

        # User suddenly asks an unrelated programming question
        query = "What is recursion?"
        res = intent_router.route(query, conversation_history=history)

        assert res.intent == IntentType.GENERAL_CONVERSATION
        assert res.detected_scheme_id is None
        assert res.is_followup is False

    def test_topic_switch_from_pragati_to_greeting(self, intent_router):
        history = [
            {"role": "user", "content": "Tell me about AICTE Pragati scholarship"},
            {"role": "assistant", "content": "AICTE Pragati provides ₹50,000 per annum to girl students."},
        ]

        res = intent_router.route("Hello! Good morning", conversation_history=history)
        assert res.intent == IntentType.GENERAL_CONVERSATION
        assert res.detected_scheme_id is None

    def test_followup_continues_pragati_context(self, intent_router):
        history = [
            {"role": "user", "content": "Tell me about AICTE Pragati scholarship"},
            {"role": "assistant", "content": "AICTE Pragati provides ₹50,000 per annum to girl students."},
        ]

        res = intent_router.route("What documents are required?", conversation_history=history)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.detected_scheme_id == "SCHEME_EDU_002_AICTE_PRAGATI"
        assert res.is_followup is True


# ===========================================================================
# 6. Ambiguous Query Interception
# ===========================================================================

class TestAmbiguousQueryInterception:
    """Verifies that short, ambiguous queries without context ask for natural clarification."""

    @pytest.mark.parametrize("vague_query", [
        "tell me more", "details", "help me", "proceed", "what next", "status",
    ])
    def test_vague_query_without_context_classified_as_ambiguous(self, intent_router, vague_query):
        res = intent_router.route(vague_query)
        assert res.intent == IntentType.AMBIGUOUS


# ===========================================================================
# 7. Unsupported Scheme Interception Preservation
# ===========================================================================

class TestUnsupportedSchemeInterceptionPreservation:
    """Verifies unsupported scheme safety intercept is intact."""

    @pytest.mark.parametrize("unsupported_query,expected_code", [
        ("How to apply for PM-KMY?", "PM-KMY"),
        ("What is the benefit under PMSBY?", "PMSBY"),
        ("Tell me about PMAY Gramin", "PMAY"),
    ])
    def test_unsupported_interception(self, intent_router, unsupported_query, expected_code):
        res = intent_router.route(unsupported_query)
        assert res.intent == IntentType.SCHEME_INQUIRY
        assert res.unsupported_scheme is not None
        assert expected_code in res.unsupported_scheme


# ===========================================================================
# 8. End-to-End Chat Service Integration: No ChromaDB for General Queries
# ===========================================================================

class TestChatServiceNLUIntegration:
    """Verifies that ChatService post_message avoids ChromaDB, citations, and disclaimers for general queries."""

    def test_general_question_does_not_call_chromadb_and_has_no_citations(
        self, nlu_chat_service, mock_vector_store, mock_llm
    ):
        mock_llm.generate.return_value = "Recursion is a method where the solution depends on solutions to smaller instances."
        mock_vector_store.query.reset_mock()

        # Initialize guest session in DB
        guest_sess = nlu_chat_service.session_manager.create_guest_session(ip_address="127.0.0.1")
        raw_session_id = guest_sess["session_id"]
        guest_context = {"is_guest": True, "guest_id": guest_sess["guest_id"]}

        result = nlu_chat_service.post_message(
            session_context=guest_context,
            message="What is recursion?",
            raw_session_id=raw_session_id,
        )

        # 1. Vector store must NOT have been queried
        mock_vector_store.query.assert_not_called()

        # 2. Response must have no citations
        assert result["citations"] == []

        # 3. Response must have no government disclaimer
        assert result["disclaimer"] is None

        # 4. Evidence sufficient must be True (no warnings)
        assert result["evidence_sufficient"] is True

        # 5. Intent is general_conversation
        assert result["intent"] == "general_conversation"
        assert "Recursion" in result["content"]

    def test_greeting_does_not_call_chromadb(self, nlu_chat_service, mock_vector_store, mock_llm):
        mock_llm.generate.return_value = "Hello! How can I assist you today?"
        mock_vector_store.query.reset_mock()

        guest_sess = nlu_chat_service.session_manager.create_guest_session(ip_address="127.0.0.1")
        raw_session_id = guest_sess["session_id"]
        guest_context = {"is_guest": True, "guest_id": guest_sess["guest_id"]}

        result = nlu_chat_service.post_message(
            session_context=guest_context,
            message="Hello SahayAI!",
            raw_session_id=raw_session_id,
        )

        mock_vector_store.query.assert_not_called()
        assert result["citations"] == []
        assert result["disclaimer"] is None
        assert result["intent"] == "general_conversation"

    def test_scheme_query_invokes_rag_pipeline(self, nlu_chat_service, mock_vector_store, mock_llm):
        # Configure mock LLM to return valid RAG json with citations
        mock_llm.generate.return_value = json.dumps({
            "answer": "AICTE Pragati scholarship offers financial aid to girl students [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })
        mock_vector_store.query.reset_mock()

        guest_sess = nlu_chat_service.session_manager.create_guest_session(ip_address="127.0.0.1")
        raw_session_id = guest_sess["session_id"]
        guest_context = {"is_guest": True, "guest_id": guest_sess["guest_id"]}

        result = nlu_chat_service.post_message(
            session_context=guest_context,
            message="Tell me about AICTE Pragati scholarship for girls",
            raw_session_id=raw_session_id,
        )

        # Vector store was queried
        mock_vector_store.query.assert_called_once()
        assert len(result["citations"]) > 0
        assert result["disclaimer"] is not None
        assert result["intent"] == "scheme_inquiry"

    def test_ambiguous_message_returns_natural_clarification(self, nlu_chat_service, mock_vector_store):
        mock_vector_store.query.reset_mock()

        guest_sess = nlu_chat_service.session_manager.create_guest_session(ip_address="127.0.0.1")
        raw_session_id = guest_sess["session_id"]
        guest_context = {"is_guest": True, "guest_id": guest_sess["guest_id"]}

        result = nlu_chat_service.post_message(
            session_context=guest_context,
            message="tell me more",
            raw_session_id=raw_session_id,
        )

        mock_vector_store.query.assert_not_called()
        assert result["citations"] == []
        assert result["disclaimer"] is None
        assert result["intent"] == "ambiguous"
        assert "clarify" in result["content"].lower() or "help" in result["content"].lower()


# ===========================================================================
# 9. Data-Driven Scalability Test
# ===========================================================================

class TestDataDrivenCatalogScalability:
    """Verifies that adding a new scheme to the catalog automatically enables recognition without code changes."""

    def test_dynamic_catalog_expansion(self):
        new_scheme_data = [
            {
                "scheme_id": "SCHEME_EDU_099_NATIONAL_APPRENTICE",
                "scheme_name": "National Apprenticeship Training Scheme",
                "current_official_name": "National Apprenticeship Training Scheme for Engineering Graduates",
                "category": "EDUCATION",
                "target_beneficiaries": ["Engineering and Diploma passout students seeking technical apprenticeship"],
                "eligibility": {"education_level": ["Graduation", "Diploma"]},
            }
        ]

        dynamic_index = SchemeCatalogIndex(schemes_data=new_scheme_data)

        # 1. Exact match on new scheme name
        match = dynamic_index.match_scheme_by_name("How do I apply for National Apprenticeship Training Scheme?")
        assert match is not None
        assert match[0] == "SCHEME_EDU_099_NATIONAL_APPRENTICE"

        # 2. Typo-tolerant match on new scheme distinctive keyword ("apprenticeship")
        typo_match = dynamic_index.match_scheme_by_name("Tell me about the apprentceship scheme")
        assert typo_match is not None
        assert typo_match[0] == "SCHEME_EDU_099_NATIONAL_APPRENTICE"
