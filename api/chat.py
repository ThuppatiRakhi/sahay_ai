"""Chat API routes for SahayAI conversational assistance."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from api.security import (
    enforce_csrf_protection,
    get_current_session_or_guest,
    get_session_config,
)
from chat.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])
chat_service = ChatService()


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="Citizen inquiry prompt")
    conversation_id: Optional[str] = Field(default=None, description="Optional existing conversation ID to continue")
    language: Optional[str] = Field(default=None, description="Preferred response language code (e.g. 'te-IN', 'hi-IN', 'en-IN')")


@router.post("/message")
def post_message(
    payload: ChatMessageRequest,
    request: Request,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
):
    """Submits a user prompt, retrieves grounded RAG guidance, and persists conversational context.

    Security guarantees:
    - Supports both authenticated citizens and anonymous guest sessions.
    - Preserves CSRF origin and token validation on mutating POST requests.
    - Registered user conversations are isolated by user_id in SQLite.
    - Guest sessions store rolling context in guest_sessions.context_json (max 64KB).
    - Rejects unauthorized or guessed conversation IDs with HTTP 404.
    """
    cfg = get_session_config()
    raw_session_id = request.cookies.get(cfg.cookie_name)
    if not raw_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Active session token cookie missing.",
        )

    try:
        response_data = chat_service.post_message(
            session_context=session_context,
            message=payload.message,
            raw_session_id=raw_session_id,
            conversation_id=payload.conversation_id,
            language=payload.language,
        )
        return {
            "success": True,
            **response_data,
        }
    except ValueError as exc:
        err_str = str(exc)
        if "not found" in err_str.lower() or "access denied" in err_str.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_str,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_str,
        )
    except Exception as exc:
        logger.exception("Error processing chat message: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while generating your scheme guidance. Please try again.",
        )


@router.get("/conversations")
def get_conversations(
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
):
    """Retrieves list of past conversations owned by the authenticated citizen.

    Security guarantees:
    - Registered users only.
    - Anonymous guests are rejected with HTTP 403 Forbidden.
    - Returns only conversations belonging strictly to session_context['user_id'].
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Saved conversation history is a registered account feature.",
        )

    user_id = session_context.get("user_id")
    conversations = chat_service.get_conversations(user_id=user_id)
    return {
        "success": True,
        "conversations": conversations,
    }


@router.get("/conversations/{conversation_id}")
def get_conversation_details(
    conversation_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
):
    """Retrieves messages for a specific conversation owned by the authenticated citizen.

    Security guarantees:
    - Registered users only.
    - Verifies ownership strictly: user A cannot access user B's conversation.
    - Rejects unauthorized access with HTTP 404 Not Found without leaking existence.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Saved conversation history is a registered account feature.",
        )

    user_id = session_context.get("user_id")
    try:
        result = chat_service.get_conversation(user_id=user_id, conversation_id=conversation_id)
        return {
            "success": True,
            **result,
        }
    except ValueError as exc:
        err_str = str(exc)
        if "not found" in err_str.lower() or "access denied" in err_str.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_str,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_str,
        )


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
):
    """Deletes a conversation and all its messages for the authenticated citizen.

    Security guarantees:
    - Registered users only.
    - Enforces CSRF token validation on DELETE requests.
    - Strict ownership verification: user A cannot delete user B's conversation.
    - Rejects unauthorized requests with HTTP 404 Not Found.
    """
    if session_context.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Saved conversation history is a registered account feature.",
        )

    user_id = session_context.get("user_id")
    try:
        chat_service.delete_conversation(user_id=user_id, conversation_id=conversation_id)
        return {
            "success": True,
            "message": "Conversation deleted successfully.",
        }
    except ValueError as exc:
        err_str = str(exc)
        if "not found" in err_str.lower() or "access denied" in err_str.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_str,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_str,
        )
