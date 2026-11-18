"""Voice API routes for SahayAI Multilingual Text-to-Speech (TTS) Synthesis."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from api.security import (
    enforce_csrf_protection,
    get_current_session_or_guest,
    get_session_config,
)
from voice.tts_service import TTSService, normalize_tts_language

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice"])
tts_service = TTSService()


class SynthesizeVoiceRequest(BaseModel):
    """Payload for speech synthesis generation."""
    text: str = Field(min_length=1, max_length=3000, description="Response text to synthesize aloud")
    language: Optional[str] = Field(default="en-IN", description="Target locale code: te-IN, hi-IN, or en-IN")


@router.post("/synthesize")
def synthesize_speech(
    payload: SynthesizeVoiceRequest,
    request: Request,
    session_context: Dict[str, Any] = Depends(get_current_session_or_guest),
    _: None = Depends(enforce_csrf_protection),
):
    """Generates audio for scheme explanations in Telugu, Hindi, or English.

    Security & Access Control:
    - Supports both authenticated citizens and anonymous guest sessions.
    - Protected by CSRF origin verification.
    - Sanitizes Markdown, links, and citations before synthesis.
    - Returns streaming MPEG-1 Layer 3 binary audio (audio/mpeg).
    - Caches responses using Cache-Control: private, max-age=3600.
    """
    cfg = get_session_config()
    raw_session_id = request.cookies.get(cfg.cookie_name)
    if not raw_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Active session token cookie missing.",
        )

    raw_text = payload.text.strip()
    if not raw_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speech text cannot be empty.",
        )

    norm_lang = normalize_tts_language(payload.language)

    try:
        audio_bytes, media_type = tts_service.synthesize(raw_text, norm_lang)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        )
    except Exception as err:
        logger.error("TTS Synthesis error for lang=%s: %s", norm_lang, err)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Text-to-speech synthesis service is temporarily unavailable. Please read the text response below.",
        )

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Content-Type": media_type,
            "Cache-Control": "private, max-age=3600",
            "Content-Length": str(len(audio_bytes)),
            "X-Content-Type-Options": "nosniff",
        },
    )

