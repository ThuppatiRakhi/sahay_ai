"""SahayAI Voice & Multilingual Text-to-Speech (TTS) Service.

Supports:
1. Telugu (te-IN) voice playback
2. Hindi (hi-IN) voice playback
3. English (en-IN) voice playback

Architecture:
- Provider-based design with pluggable engines:
  - GoogleFreeTTSProvider: Zero-cost, zero-credential web TTS engine using Google's public translate_tts endpoint.
  - GoogleCloudTTSProvider: Enterprise Google Cloud Text-to-Speech integration (Neural2 / Standard voice families).
  - MockTTSProvider: Deterministic synthetic audio generator for offline and unit test environments.
- Pre-processing pipeline:
  - Strips Markdown delimiters, code blocks, raw URLs, table pipes, and citation tokens ([S1], [S2])
    so speech flows naturally without spelling out punctuation or markup syntax.
  - Smart sentence chunking respects speech boundaries without truncating words.
  - MPEG-1 Layer 3 frame concatenation for long responses.
- In-memory audio caching with TTL & LRU eviction to prevent duplicate network calls.
- Privacy-first logging: never logs citizen names, PII, or raw prompt text.
"""

from abc import ABC, abstractmethod
import base64
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 1500
CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_CACHE_ENTRIES = 128


# ---------------------------------------------------------------------------
# Text Pre-processing & Sanitization for Natural Speech
# ---------------------------------------------------------------------------

def clean_text_for_speech(raw_text: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Sanitizes raw LLM output into natural spoken text.

    Removes:
    - Fenced code blocks (```...```) and inline code (`...`)
    - Markdown headers (#, ##, ###)
    - Bold and italic delimiters (**, *, __, _)
    - Citation brackets ([S1], [S2], [S1, S2])
    - Markdown links [text](url) -> text
    - Raw URLs (https://...)
    - Markdown table structures (| col | col | and |---|---|)
    - Horizontal rules (---, ***, ___)
    - Repetitive bullet symbols (•, -, *, ✓, ✔) -> natural pause
    """
    if not raw_text or not isinstance(raw_text, str):
        return ""

    text = raw_text

    # 1. Remove code blocks completely
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`\n]+`", " ", text)

    # 2. Convert markdown links: [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # 3. Remove raw URLs
    text = re.sub(r"https?://\S+", " ", text)

    # 4. Remove citation brackets: [S1], [S2], [S1, S2]
    text = re.sub(r"\[S\d+(?:\s*,\s*S\d+)*\]", " ", text)

    # 5. Remove markdown table separator lines: | --- | --- |
    text = re.sub(r"\|[\s\-:|]+\|", " ", text)

    # 6. Replace table pipes with commas/spaces for fluid reading
    text = re.sub(r"\|", ", ", text)

    # 7. Remove horizontal rules
    text = re.sub(r"^(\-{3,}|\*{3,}|_{3,})$", " ", text, flags=re.MULTILINE)

    # 8. Remove markdown headers: #, ##, ###
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 9. Remove bold / italic formatting tokens: ***, **, *, __, _
    text = re.sub(r"(\*{1,3}|_{1,3})([^\*_]+)\1", r"\2", text)

    # 10. Replace bullet points with period / pause
    text = re.sub(r"^\s*([-*•+✓✔→►]|\d+[.)\-])\s+", ". ", text, flags=re.MULTILINE)

    # 11. Normalize duplicate punctuation and whitespace
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([.,?!;।])\s*([.,?!;।])+", r"\1", text)
    text = text.strip()

    # 12. Length capping with boundary-safe truncation
    if len(text) > max_chars:
        # Truncate at nearest sentence or clause ending before max_chars
        truncated = text[:max_chars]
        last_punct = max(
            truncated.rfind(". "),
            truncated.rfind("? "),
            truncated.rfind("! "),
            truncated.rfind("। "),
            truncated.rfind(", "),
        )
        if last_punct > max_chars // 2:
            text = truncated[: last_punct + 1]
        else:
            text = truncated.rsplit(" ", 1)[0] + "..."

    return text.strip()


def normalize_tts_language(lang: Optional[str]) -> str:
    """Normalizes various language representations to ISO 639-1 / BCP-47 codes."""
    if not lang or not isinstance(lang, str):
        return "en-IN"

    clean = lang.strip().lower().replace("_", "-")
    if clean.startswith("te") or "telugu" in clean:
        return "te-IN"
    if clean.startswith("hi") or "hindi" in clean:
        return "hi-IN"
    return "en-IN"


def split_text_into_tts_chunks(text: str, max_chunk_size: int = 180) -> List[str]:
    """Splits text into speech-friendly segments without truncating words or Indic conjuncts."""
    if not text:
        return []

    if len(text) <= max_chunk_size:
        return [text]

    chunks: List[str] = []
    # Split primarily by sentence terminators (. ? ! । newline)
    sentences = re.split(r"([.?!।\n]+)", text)
    current = ""

    for segment in sentences:
        if not segment:
            continue
        if len(current) + len(segment) <= max_chunk_size:
            current += segment
        else:
            if current.strip():
                chunks.append(current.strip())
                current = ""

            # If an individual segment is still longer than max_chunk_size, split by clause commas or spaces
            if len(segment) > max_chunk_size:
                sub_parts = re.split(r"([,;:,\s]+)", segment)
                sub_cur = ""
                for sp in sub_parts:
                    if len(sub_cur) + len(sp) <= max_chunk_size:
                        sub_cur += sp
                    else:
                        if sub_cur.strip():
                            chunks.append(sub_cur.strip())
                        sub_cur = sp
                if sub_cur.strip():
                    current = sub_cur
            else:
                current = segment

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# TTS Provider Abstract Base Class
# ---------------------------------------------------------------------------

class TTSProvider(ABC):
    """Abstract base class for speech synthesis providers."""

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Synthesizes text to binary audio bytes (MP3 format)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the provider is configured and available."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifies provider name in telemetry and diagnostic logs."""
        pass


# ---------------------------------------------------------------------------
# Google Free TTS Provider (Zero-Cost, Zero-Credential Fallback)
# ---------------------------------------------------------------------------

class GoogleFreeTTSProvider(TTSProvider):
    """Zero-credential multilingual TTS using Google's public translate_tts endpoint.

    Supported Languages:
    - Telugu: 'te'
    - Hindi: 'hi'
    - English: 'en'

    Features:
    - Splits long Indic and English text into sentence chunks.
    - Concatenates MPEG-1 Layer 3 frames into a single seamless audio stream.
    - Requires zero API keys, subscriptions, or credit card configurations.
    """

    BASE_URL = "https://translate.google.com/translate_tts"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return "google_free"

    def is_available(self) -> bool:
        return True

    def _lang_code(self, language: str) -> str:
        normalized = normalize_tts_language(language)
        if normalized.startswith("te"):
            return "te"
        if normalized.startswith("hi"):
            return "hi"
        return "en"

    def _fetch_single_chunk(self, chunk: str, lang_code: str) -> bytes:
        params = urllib.parse.urlencode({
            "ie": "UTF-8",
            "q": chunk,
            "tl": lang_code,
            "client": "tw-ob",
        })
        url = f"{self.BASE_URL}?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.USER_AGENT},
        )

        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = resp.read()
                        if data and len(data) > 0:
                            return data
            except Exception as e:
                if attempt == 1:
                    logger.warning("GoogleFreeTTS fetch failed on retry for lang=%s: %s", lang_code, e)
                    raise
                time.sleep(0.15)

        raise RuntimeError(f"GoogleFreeTTS failed to synthesize chunk for lang={lang_code}")

    def synthesize(self, text: str, language: str) -> bytes:
        import concurrent.futures

        lang_code = self._lang_code(language)
        chunks = split_text_into_tts_chunks(text, max_chunk_size=180)

        if not chunks:
            raise ValueError("No valid text provided for speech synthesis.")

        # Optimize for speed: parallelize chunk fetching via ThreadPoolExecutor
        if len(chunks) == 1:
            audio_parts = [self._fetch_single_chunk(chunks[0], lang_code)]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as executor:
                future_to_idx = {
                    executor.submit(self._fetch_single_chunk, chunk, lang_code): i
                    for i, chunk in enumerate(chunks)
                }
                parts_dict = {}
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        parts_dict[idx] = future.result()
                    except Exception as e:
                        logger.error("Failed to synthesize chunk %d/%d: %s", idx + 1, len(chunks), e)

                # Assemble in original chunk order
                audio_parts = [parts_dict[i] for i in range(len(chunks)) if i in parts_dict]

        if not audio_parts:
            raise RuntimeError("Empty audio stream generated.")

        # Concatenate MPEG frame chunks
        combined = b"".join(audio_parts)
        return combined


# ---------------------------------------------------------------------------
# Google Cloud Text-to-Speech Provider (Enterprise Option)
# ---------------------------------------------------------------------------

class GoogleCloudTTSProvider(TTSProvider):
    """Enterprise Google Cloud Text-to-Speech API integration.

    Voice Configurations:
    - Telugu: te-IN-Standard-A (Female), te-IN-Standard-B (Male)
    - Hindi: hi-IN-Neural2-A (Female), hi-IN-Neural2-B (Male), hi-IN-Wavenet-A
    - English: en-IN-Neural2-A (Female), en-IN-Standard-A

    Credentials:
    - Configured via GCP_TTS_API_KEY or GOOGLE_APPLICATION_CREDENTIALS.
    """

    ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GCP_TTS_API_KEY")

    @property
    def provider_name(self) -> str:
        return "google_cloud"

    def is_available(self) -> bool:
        if self.api_key:
            return True
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            return True
        return False

    def _select_voice(self, language: str) -> Tuple[str, str]:
        normalized = normalize_tts_language(language)
        if normalized.startswith("te"):
            return "te-IN", "te-IN-Standard-A"
        if normalized.startswith("hi"):
            return "hi-IN", "hi-IN-Neural2-A"
        return "en-IN", "en-IN-Neural2-A"

    def synthesize(self, text: str, language: str) -> bytes:
        if not self.is_available():
            raise RuntimeError(
                "GoogleCloudTTSProvider is not configured. "
                "Set GCP_TTS_API_KEY or GOOGLE_APPLICATION_CREDENTIALS to enable."
            )

        lang_code, voice_name = self._select_voice(language)
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": lang_code, "name": voice_name},
            "audioConfig": {"audioEncoding": "MP3"},
        }

        url = f"{self.ENDPOINT}?key={self.api_key}"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status != 200:
                raise RuntimeError(f"GCP TTS returned HTTP {resp.status}")
            resp_json = json.loads(resp.read().decode("utf-8"))
            audio_b64 = resp_json.get("audioContent")
            if not audio_b64:
                raise RuntimeError("No audioContent in GCP TTS response")
            return base64.b64decode(audio_b64)


# ---------------------------------------------------------------------------
# Mock TTS Provider (for Testing & Offline Environments)
# ---------------------------------------------------------------------------

class MockTTSProvider(TTSProvider):
    """Produces valid synthetic MP3 frames for offline and unit test verification."""

    # Standard MPEG-1 Layer 3 Sync Header: 0xFF 0xFB 0x90 0x64
    MOCK_MP3_FRAME = (
        b"\xff\xfb\x90\x64" +
        b"\x00" * 414 +
        b"\xff\xfb\x90\x64" +
        b"\x00" * 414
    )

    @property
    def provider_name(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return True

    def synthesize(self, text: str, language: str) -> bytes:
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        # Return valid MP3 frame repeated proportional to character length
        repeat_count = max(1, min(len(text) // 20, 20))
        return self.MOCK_MP3_FRAME * repeat_count


# ---------------------------------------------------------------------------
# Central TTS Service with In-Memory Caching & Provider Dispatch
# ---------------------------------------------------------------------------

class TTSService:
    """Central service managing text sanitization, caching, and provider synthesis."""

    def __init__(
        self,
        provider: Optional[TTSProvider] = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ):
        self.max_chars = int(os.getenv("TTS_MAX_CHAR_LIMIT", str(max_chars)))
        self._cache: Dict[str, Tuple[bytes, float]] = {}
        self.provider = provider or self._resolve_default_provider()

    def _resolve_default_provider(self) -> TTSProvider:
        pref = os.getenv("TTS_PROVIDER", "auto").strip().lower()

        if pref == "mock":
            logger.info("TTSService initialized with MockTTSProvider")
            return MockTTSProvider()

        if pref == "google_cloud":
            cloud_provider = GoogleCloudTTSProvider()
            if cloud_provider.is_available():
                logger.info("TTSService initialized with GoogleCloudTTSProvider")
                return cloud_provider
            logger.warning(
                "TTS_PROVIDER=google_cloud requested but credentials missing. Falling back to GoogleFreeTTSProvider."
            )

        if pref == "auto":
            cloud_provider = GoogleCloudTTSProvider()
            if cloud_provider.is_available():
                logger.info("TTSService auto-selected GoogleCloudTTSProvider")
                return cloud_provider

        # Default standard: GoogleFreeTTSProvider
        logger.info("TTSService initialized with GoogleFreeTTSProvider (free multilingual Indic)")
        return GoogleFreeTTSProvider()

    def _compute_cache_key(self, text: str, lang: str) -> str:
        content = f"{lang.lower()}::{text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _cleanup_expired_cache(self) -> None:
        now = time.time()
        expired_keys = [
            k for k, (_, ts) in self._cache.items()
            if now - ts > CACHE_TTL_SECONDS
        ]
        for k in expired_keys:
            self._cache.pop(k, None)

        # LRU trim if cache exceeds max size
        if len(self._cache) > MAX_CACHE_ENTRIES:
            sorted_items = sorted(self._cache.items(), key=lambda item: item[1][1])
            excess = len(self._cache) - MAX_CACHE_ENTRIES
            for k, _ in sorted_items[:excess]:
                self._cache.pop(k, None)

    def synthesize(self, raw_text: str, language: str = "en-IN") -> Tuple[bytes, str]:
        """Sanitizes text, checks cache, and delegates to active TTS provider.

        Returns:
            Tuple of (audio_bytes: bytes, media_type: str = 'audio/mpeg')
        """
        if not raw_text or not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("Text cannot be empty.")

        norm_lang = normalize_tts_language(language)
        cleaned = clean_text_for_speech(raw_text, max_chars=self.max_chars)
        if not cleaned:
            raise ValueError("Text contains no speakable characters after sanitization.")

        # Cache check
        cache_key = self._compute_cache_key(cleaned, norm_lang)
        now = time.time()

        if cache_key in self._cache:
            cached_audio, ts = self._cache[cache_key]
            if now - ts <= CACHE_TTL_SECONDS:
                logger.debug("TTS Cache Hit: lang=%s, audio_size=%d", norm_lang, len(cached_audio))
                return cached_audio, "audio/mpeg"

        start_time = time.time()
        try:
            audio_bytes = self.provider.synthesize(cleaned, norm_lang)
        except Exception as err:
            logger.error("TTS Synthesis Error (provider=%s, lang=%s): %s", self.provider.provider_name, norm_lang, err)
            raise

        elapsed = time.time() - start_time
        logger.info(
            "TTS Synthesis Success: provider=%s, lang=%s, chars=%d, audio_bytes=%d, latency=%.2fs",
            self.provider.provider_name,
            norm_lang,
            len(cleaned),
            len(audio_bytes),
            elapsed,
        )

        # Store in cache
        self._cleanup_expired_cache()
        self._cache[cache_key] = (audio_bytes, now)

        return audio_bytes, "audio/mpeg"

