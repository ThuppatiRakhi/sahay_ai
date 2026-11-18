"""Chat service for multi-turn conversation persistence and RAG orchestration."""

from datetime import datetime, timezone
import json
import logging
import secrets
from typing import Any, Dict, List, Optional

from chat.conversational_handler import ConversationalHandler
from chat.intent_router import IntentRouter, IntentType
from profile.database import Database
from profile.session_manager import SessionManager
from rag.answer_generator import RAGAnswerGenerator
from rag.query_rewriter import normalize_language_code, normalize_language_name

logger = logging.getLogger(__name__)

MAX_GUEST_HISTORY_MESSAGES = 10
MAX_RAG_HISTORY_MESSAGES = 6


class ChatService:
    """Manages conversations and message persistence for registered and anonymous users."""

    def __init__(
        self,
        db: Optional[Database] = None,
        session_manager: Optional[SessionManager] = None,
        rag_generator: Optional[RAGAnswerGenerator] = None,
        intent_router: Optional[IntentRouter] = None,
        conversational_handler: Optional[ConversationalHandler] = None,
    ):
        self.db = db or Database()
        self.session_manager = session_manager or SessionManager(db=self.db)
        self._rag_generator = rag_generator
        self._intent_router = intent_router
        self._conversational_handler = conversational_handler

    @property
    def intent_router(self) -> IntentRouter:
        """Lazily initialize IntentRouter if not injected."""
        if self._intent_router is None:
            self._intent_router = IntentRouter()
        return self._intent_router

    @property
    def conversational_handler(self) -> ConversationalHandler:
        """Lazily initialize ConversationalHandler if not injected."""
        if self._conversational_handler is None:
            llm = getattr(self.rag_generator, "llm_client", None)
            self._conversational_handler = ConversationalHandler(llm_client=llm)
        return self._conversational_handler

    @property
    def rag_generator(self) -> RAGAnswerGenerator:
        """Lazily initialize RAG generator if not injected."""
        if self._rag_generator is None:
            from rag.embedding_service import EmbeddingService
            from rag.indexer import load_chunks
            from rag.query_rewriter import QueryRewriter
            from rag.reranker import LightweightReranker
            from rag.retriever import SchemeRetriever
            from rag.vector_store import VectorStoreManager

            vs = VectorStoreManager()
            emb = EmbeddingService()
            retriever = SchemeRetriever(
                vector_store=vs,
                embedding_service=emb,
                query_rewriter=QueryRewriter(),
                reranker=LightweightReranker(),
            )
            self._rag_generator = RAGAnswerGenerator(retriever=retriever)
        return self._rag_generator

    def _process_message_intent(
        self,
        clean_msg: str,
        bounded_history: List[Dict[str, Any]],
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Routes message through IntentRouter and returns structured response."""
        decision = self.intent_router.route(
            clean_msg,
            conversation_history=bounded_history,
            preferred_language=language,
        )

        target_lang_code = decision.detected_language or normalize_language_code(language)
        target_lang_name = normalize_language_name(target_lang_code)

        if decision.intent == IntentType.GENERAL_CONVERSATION:
            conv_res = self.conversational_handler.generate_response(
                query=clean_msg,
                conversation_history=bounded_history,
                target_language=target_lang_name,
            )
            return {
                "answer": conv_res["answer"],
                "sources": [],
                "disclaimer": None,
                "insufficient_evidence": False,
                "citation_validation": {
                    "valid": True,
                    "used_citations": [],
                    "invalid_citations": [],
                    "undeclared_citations": [],
                    "unused_citations": [],
                    "malformed_citations": [],
                },
                "intent": decision.intent.value,
                "language": target_lang_code,
            }

        if decision.intent == IntentType.AMBIGUOUS:
            clarif_res = self.conversational_handler.generate_clarification(
                query=clean_msg,
                language=target_lang_code,
                prompt=decision.clarification_prompt,
            )
            return {
                "answer": clarif_res["answer"],
                "sources": [],
                "disclaimer": None,
                "insufficient_evidence": False,
                "citation_validation": {
                    "valid": True,
                    "used_citations": [],
                    "invalid_citations": [],
                    "undeclared_citations": [],
                    "unused_citations": [],
                    "malformed_citations": [],
                },
                "intent": decision.intent.value,
                "language": target_lang_code,
            }

        # Otherwise, SCHEME_INQUIRY
        effective_scheme_id = decision.detected_scheme_id
        if not effective_scheme_id and len(decision.candidate_scheme_ids) == 1:
            effective_scheme_id = decision.candidate_scheme_ids[0]

        rag_res = self.rag_generator.answer(
            query=clean_msg,
            scheme_id=effective_scheme_id,
            language=target_lang_name,
            conversation_history=bounded_history,
        )
        rag_res["intent"] = decision.intent.value
        rag_res["language"] = target_lang_code
        return rag_res

    def post_message(
        self,
        session_context: Dict[str, Any],
        message: str,
        raw_session_id: str,
        conversation_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Processes a chat message, routes intent, and persists history.

        Args:
            session_context: Authenticated or guest session dictionary.
            message: User prompt string.
            raw_session_id: Raw session cookie value for guest context updates.
            conversation_id: Optional ID of conversation to continue.
            language: Optional target response language preference.

        Returns:
            Dictionary with conversation_id, message_id, answer, citations, disclaimer.

        Raises:
            ValueError: If conversation_id is not found or unauthorized, or input invalid.
        """
        clean_msg = message.strip()
        if not clean_msg:
            raise ValueError("Message cannot be empty.")

        now_iso = datetime.now(timezone.utc).isoformat()
        is_guest = session_context.get("is_guest", False)

        # -------------------------------------------------------------------
        # 1. Anonymous Guest Interaction (Ephemeral Storage in context_json)
        # -------------------------------------------------------------------
        if is_guest:
            guest_id = session_context.get("guest_id", "anonymous")
            guest_conv_id = f"guest_{guest_id}"

            # Retrieve active guest session context
            guest_session = self.session_manager.validate_guest_session(raw_session_id)
            if not guest_session:
                raise ValueError("Active guest session is invalid, expired, or revoked.")

            context = guest_session.get("context", {})
            chat_history: List[Dict[str, Any]] = context.get("chat_history", [])

            # Prepare bounded history for context resolution
            bounded_rag_history = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in chat_history[-MAX_RAG_HISTORY_MESSAGES:]
            ]

            # Route intent and generate response with language preference
            proc_result = self._process_message_intent(clean_msg, bounded_rag_history, language=language)

            # Build message entries
            user_msg_id = f"msg_{secrets.token_hex(12)}"
            asst_msg_id = f"msg_{secrets.token_hex(12)}"

            user_entry = {
                "id": user_msg_id,
                "role": "user",
                "content": clean_msg,
                "created_at": now_iso,
            }
            asst_entry = {
                "id": asst_msg_id,
                "role": "assistant",
                "content": proc_result["answer"],
                "citations": proc_result.get("sources", []),
                "disclaimer": proc_result.get("disclaimer"),
                "created_at": now_iso,
            }

            chat_history.append(user_entry)
            chat_history.append(asst_entry)

            # Prevent unbounded growth: keep last 10 messages (5 turns)
            context["chat_history"] = chat_history[-MAX_GUEST_HISTORY_MESSAGES:]

            # Persist updated ephemeral context
            self.session_manager.update_guest_context(raw_session_id, context)

            return {
                "conversation_id": guest_conv_id,
                "message_id": asst_msg_id,
                "role": "assistant",
                "content": proc_result["answer"],
                "citations": proc_result.get("sources", []),
                "disclaimer": proc_result.get("disclaimer"),
                "evidence_sufficient": not proc_result.get("insufficient_evidence", False),
                "citation_validation": proc_result.get("citation_validation", {}),
                "created_at": now_iso,
                "is_guest": True,
                "intent": proc_result.get("intent", "scheme_inquiry"),
                "language": proc_result.get("language", "en"),
            }

        # -------------------------------------------------------------------
        # 2. Registered Citizen Interaction (Persistent SQLite Storage)
        # -------------------------------------------------------------------
        user_id = session_context.get("user_id")
        if not user_id:
            raise ValueError("Authenticated user_id missing from session.")

        with self.db.get_connection() as conn:
            # A. Resolve or create conversation
            if conversation_id:
                conv_row = conn.execute(
                    "SELECT id, title, created_at FROM chat_conversations WHERE id = ? AND user_id = ?",
                    (conversation_id, user_id),
                ).fetchone()

                if not conv_row:
                    raise ValueError(f"Conversation '{conversation_id}' not found or access denied.")
                conv_id = conversation_id
            else:
                conv_id = f"conv_{secrets.token_hex(12)}"
                # Generate citizen-friendly title from the first question
                title = clean_msg[:47] + "..." if len(clean_msg) > 50 else clean_msg
                conn.execute(
                    """
                    INSERT INTO chat_conversations (id, user_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (conv_id, user_id, title, now_iso, now_iso),
                )

            # B. Load prior message history for conversational context
            history_rows = conn.execute(
                """
                SELECT role, content FROM chat_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conv_id,),
            ).fetchall()

            bounded_rag_history = [
                {"role": r["role"], "content": r["content"]}
                for r in history_rows[-MAX_RAG_HISTORY_MESSAGES:]
            ]

            # C. Save citizen message
            user_msg_id = f"msg_{secrets.token_hex(12)}"
            conn.execute(
                """
                INSERT INTO chat_messages (id, conversation_id, role, content, citations_json, created_at)
                VALUES (?, ?, 'user', ?, '[]', ?)
                """,
                (user_msg_id, conv_id, clean_msg, now_iso),
            )

            # D. Route intent and generate response with language preference
            proc_result = self._process_message_intent(clean_msg, bounded_rag_history, language=language)

            # E. Save assistant message and citations
            asst_msg_id = f"msg_{secrets.token_hex(12)}"
            citations_json = json.dumps(proc_result.get("sources", []))
            conn.execute(
                """
                INSERT INTO chat_messages (id, conversation_id, role, content, citations_json, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?)
                """,
                (asst_msg_id, conv_id, proc_result["answer"], citations_json, now_iso),
            )

            # F. Update conversation updated_at timestamp
            conn.execute(
                "UPDATE chat_conversations SET updated_at = ? WHERE id = ?",
                (now_iso, conv_id),
            )

        return {
            "conversation_id": conv_id,
            "message_id": asst_msg_id,
            "role": "assistant",
            "content": proc_result["answer"],
            "citations": proc_result.get("sources", []),
            "disclaimer": proc_result.get("disclaimer"),
            "evidence_sufficient": not proc_result.get("insufficient_evidence", False),
            "citation_validation": proc_result.get("citation_validation", {}),
            "created_at": now_iso,
            "is_guest": False,
            "intent": proc_result.get("intent", "scheme_inquiry"),
            "language": proc_result.get("language", "en"),
        }

    def get_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves list of conversations owned by the authenticated citizen.

        Args:
            user_id: Authenticated citizen user ID.

        Returns:
            List of conversation overview dicts sorted by updated_at descending.
        """
        query = """
            SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) as message_count
            FROM chat_conversations c
            LEFT JOIN chat_messages m ON c.id = m.conversation_id
            WHERE c.user_id = ?
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """
        with self.db.get_connection() as conn:
            rows = conn.execute(query, (user_id,)).fetchall()
            return [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "message_count": int(r["message_count"]),
                }
                for r in rows
            ]

    def get_conversation(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """Retrieves conversation details and chronological messages with strict ownership check.

        Args:
            user_id: Authenticated citizen user ID.
            conversation_id: Target conversation ID.

        Returns:
            Dict containing conversation overview and list of messages.

        Raises:
            ValueError: If conversation is not found or not owned by user.
        """
        with self.db.get_connection() as conn:
            conv_row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM chat_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()

            if not conv_row:
                raise ValueError(f"Conversation '{conversation_id}' not found or access denied.")

            msg_rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, citations_json, created_at
                FROM chat_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()

            messages = []
            for r in msg_rows:
                try:
                    citations = json.loads(r["citations_json"] or "[]")
                except Exception:
                    citations = []
                messages.append({
                    "id": r["id"],
                    "conversation_id": r["conversation_id"],
                    "role": r["role"],
                    "content": r["content"],
                    "citations": citations,
                    "created_at": r["created_at"],
                })

            return {
                "conversation": {
                    "id": conv_row["id"],
                    "title": conv_row["title"],
                    "created_at": conv_row["created_at"],
                    "updated_at": conv_row["updated_at"],
                },
                "messages": messages,
            }

    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        """Deletes a conversation and its messages with ownership verification.

        Args:
            user_id: Authenticated citizen user ID.
            conversation_id: Target conversation ID.

        Returns:
            True if deleted successfully.

        Raises:
            ValueError: If conversation is not found or not owned by user.
        """
        with self.db.get_connection() as conn:
            conv_row = conn.execute(
                "SELECT id FROM chat_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()

            if not conv_row:
                raise ValueError(f"Conversation '{conversation_id}' not found or access denied.")

            conn.execute(
                "DELETE FROM chat_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            return True
