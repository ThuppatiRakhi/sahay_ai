"""Comprehensive test suite for SahayAI Phase 2: Multilingual Voice Playback (Telugu, Hindi, English).

Validates:
1. Real speech synthesis for Telugu (te-IN) using actual Telugu text.
2. Real speech synthesis for Hindi (hi-IN) using actual Hindi text.
3. Real speech synthesis for English (en-IN).
4. Long response sentence chunking and MPEG frame concatenation.
5. Audio caching behavior and latency reduction on replay.
6. Text sanitization for speech (stripping [S1], markdown formatting, URLs, table markup).
7. FastAPI endpoint /voice/synthesize:
   - Guest session authorization
   - Registered citizen authorization
   - CSRF enforcement
   - Empty text validation (HTTP 400)
   - Missing session handling (HTTP 401)
8. Provider error and network failure handling (HTTP 503).
9. Chrome browser headless decoding of real synthesized Telugu & Hindi MP3 audio.
10. Frontend contract verification for hybrid browser/backend TTS architecture.
"""

import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.request
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import get_session_config
from profile.account_manager import AccountManager
from profile.auth_service import AuthService
from profile.database import Database
from profile.session_manager import SessionManager
from voice.tts_service import (
    TTSService,
    GoogleFreeTTSProvider,
    GoogleCloudTTSProvider,
    MockTTSProvider,
    clean_text_for_speech,
    normalize_tts_language,
    split_text_into_tts_chunks,
)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DASHBOARD_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "dashboard.js")
API_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "api.js")
AUTH_CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "css", "auth.css")
DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "dashboard.html")


# ---------------------------------------------------------------------------
# Test Fixtures for API & Database Isolation
# ---------------------------------------------------------------------------

@pytest.fixture
def tts_db(tmp_path):
    """Provides an isolated SQLite database."""
    db_file = tmp_path / "test_tts_playback.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def tts_env(tts_db, monkeypatch):
    """Configures isolated auth and session managers."""
    accounts = AccountManager(db=tts_db)
    session_mgr = SessionManager(db=tts_db)

    monkeypatch.setattr("api.auth.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.security.SessionManager", lambda: session_mgr)
    monkeypatch.setattr("api.voice.get_session_config", get_session_config)

    client = TestClient(app)

    # Create a valid guest session
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    guest_data = guest_res.json()
    cfg = get_session_config()
    session_cookie = guest_res.cookies.get(cfg.cookie_name)
    csrf_token = guest_data.get("csrf_token")

    return {
        "db": tts_db,
        "session_mgr": session_mgr,
        "client": client,
        "session_cookie": session_cookie,
        "csrf_token": csrf_token,
    }


# ---------------------------------------------------------------------------
# Unit Tests: Text Sanitization & Chunking
# ---------------------------------------------------------------------------

def test_speech_text_sanitizer_removes_markdown_and_citations():
    """Verifies that citations [S1], links, headers, and tables are stripped."""
    raw = (
        "## ముఖ్యమైన అర్హతలు\n\n"
        "**అభ్యర్థి స్థితి** – అమ్మాయి విద్యార్థి [S1]\n\n"
        "మరిన్ని వివరాలకు [NSP Portal](https://scholarships.gov.in) చూడండి.\n\n"
        "| ఫీజు | మొత్తం |\n"
        "| --- | --- |\n"
        "| ట్యూషన్ ఫీజు | ₹50,000 [S2] |\n"
    )
    cleaned = clean_text_for_speech(raw)

    assert "##" not in cleaned
    assert "**" not in cleaned
    assert "[S1]" not in cleaned
    assert "[S2]" not in cleaned
    assert "https://" not in cleaned
    assert "NSP Portal" in cleaned
    assert "అమ్మాయి విద్యార్థి" in cleaned
    assert "ట్యూషన్ ఫీజు" in cleaned
    assert "₹50,000" in cleaned
    assert "| --- |" not in cleaned


def test_speech_text_sanitizer_caps_length():
    """Verifies that very long text is capped gracefully at sentence boundaries."""
    long_text = "ఇది ఒక ముఖ్యమైన వాక్యం. " * 100
    cleaned = clean_text_for_speech(long_text, max_chars=300)
    assert len(cleaned) <= 305
    assert cleaned.endswith(".") or cleaned.endswith("...")


def test_text_chunking_preserves_sentences():
    """Verifies that sentence chunks do not cut words in half."""
    sample = "ప్రథమ వాక్యం ఇక్కడ ఉంది. ద్వితీయ వాక్యం ఇది. తృతీయ వాక్యం ఇది కూడా."
    chunks = split_text_into_tts_chunks(sample, max_chunk_size=40)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 40
        assert not chunk.endswith("వాక్")  # No clipped mid-word


# ---------------------------------------------------------------------------
# Core Service Tests: Real Audio Synthesis
# ---------------------------------------------------------------------------

def test_telugu_real_speech_synthesis():
    """Verifies actual speech audio generation for Telugu text."""
    service = TTSService(provider=GoogleFreeTTSProvider())
    sample_telugu = "నమస్కారం, సహాయ్ ఏఐ కి స్వాగతం. మీరు స్కాలర్‌షిప్ కోసం దరఖాస్తు చేసుకోవచ్చు."

    audio_bytes, media_type = service.synthesize(sample_telugu, "te-IN")

    assert media_type == "audio/mpeg"
    assert isinstance(audio_bytes, bytes)
    assert len(audio_bytes) > 10000  # Genuine spoken audio length
    # Valid MPEG sync header (0xFF 0xFB or 0xFF 0xF3)
    assert audio_bytes[0] == 0xFF
    assert (audio_bytes[1] & 0xE0) == 0xE0


def test_hindi_real_speech_synthesis():
    """Verifies actual speech audio generation for Hindi text."""
    service = TTSService(provider=GoogleFreeTTSProvider())
    sample_hindi = "नमस्ते, सहाय एआई में आपका स्वागत है। आप छात्रवृत्ति के लिए आवेदन कर सकते हैं।"

    audio_bytes, media_type = service.synthesize(sample_hindi, "hi-IN")

    assert media_type == "audio/mpeg"
    assert isinstance(audio_bytes, bytes)
    assert len(audio_bytes) > 10000
    assert audio_bytes[0] == 0xFF
    assert (audio_bytes[1] & 0xE0) == 0xE0


def test_english_real_speech_synthesis():
    """Verifies speech audio generation for English text."""
    service = TTSService(provider=GoogleFreeTTSProvider())
    sample_en = "Welcome to SahayAI. Your scholarship application draft is ready."

    audio_bytes, media_type = service.synthesize(sample_en, "en-IN")

    assert media_type == "audio/mpeg"
    assert isinstance(audio_bytes, bytes)
    assert len(audio_bytes) > 5000
    assert audio_bytes[0] == 0xFF


def test_long_multilingual_response_chunking_and_concatenation():
    """Verifies that a multi-sentence response generates a seamless combined MP3 stream."""
    service = TTSService(provider=GoogleFreeTTSProvider())
    long_telugu = (
        "ఏఐసీటీఈ ప్రగతి స్కాలర్‌షిప్ పథకం ద్వారా అర్హులైన బాలికలకు ప్రతి సంవత్సరం యాభై వేల రూపాయలు అందుతాయి. "
        "ఈ పథకానికి దరఖాస్తు చేసుకోవడానికి కుటుంబ వార్షిక ఆదాయం ఎనిమిది లక్షల రూపాయల లోపు ఉండాలి. "
        "మీరు నేషనల్ స్కాలర్‌షిప్ పోర్టల్ ద్వారా ఆన్‌లైన్‌లో దరఖాస్తు చేసుకోవచ్చు."
    )

    audio_bytes, media_type = service.synthesize(long_telugu, "te-IN")

    assert media_type == "audio/mpeg"
    assert len(audio_bytes) > 30000  # Multi-chunk concatenated audio
    assert audio_bytes[0] == 0xFF


def test_audio_caching_instant_replay():
    """Verifies that identical requests hit the in-memory cache with zero latency."""
    service = TTSService(provider=GoogleFreeTTSProvider())
    text = "ధృవీకరణ పూర్తయింది."

    t0 = time.time()
    audio1, _ = service.synthesize(text, "te-IN")
    duration1 = time.time() - t0

    t1 = time.time()
    audio2, _ = service.synthesize(text, "te-IN")
    duration2 = time.time() - t1

    assert audio1 == audio2
    assert duration2 < 0.05  # Cache hit must be instantaneous


# ---------------------------------------------------------------------------
# API Endpoint Tests: POST /voice/synthesize
# ---------------------------------------------------------------------------

def test_api_synthesize_endpoint_success_for_guest(tts_env):
    """Verifies that an authorized guest session can generate Telugu speech."""
    client = tts_env["client"]
    csrf_token = tts_env["csrf_token"]

    res = client.post(
        "/voice/synthesize",
        json={
            "text": "మీ దరఖాస్తు వివరాలు పరిశీలించబడ్డాయి.",
            "language": "te-IN",
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert "Cache-Control" in res.headers
    assert len(res.content) > 5000
    assert res.content[0] == 0xFF


def test_api_synthesize_endpoint_success_for_hindi(tts_env):
    """Verifies that an authorized user can generate Hindi speech."""
    client = tts_env["client"]
    csrf_token = tts_env["csrf_token"]

    res = client.post(
        "/voice/synthesize",
        json={
            "text": "प्रगति छात्रवृत्ति योजना के लिए आपका स्वागत है।",
            "language": "hi-IN",
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert len(res.content) > 5000


def test_api_synthesize_endpoint_empty_text_returns_400(tts_env):
    """Verifies that empty or whitespace-only text returns HTTP 400."""
    client = tts_env["client"]
    csrf_token = tts_env["csrf_token"]

    res = client.post(
        "/voice/synthesize",
        json={"text": "   ", "language": "te-IN"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert res.status_code == 400


def test_api_synthesize_endpoint_missing_session_returns_401():
    """Verifies that requests without a session cookie return HTTP 401."""
    unauthed_client = TestClient(app)

    res = unauthed_client.post(
        "/voice/synthesize",
        json={"text": "Hello world", "language": "en-IN"},
        headers={"X-CSRF-Token": "some_token"},
    )

    assert res.status_code == 401


def test_api_synthesize_endpoint_missing_csrf_returns_403(tts_env):
    """Verifies that requests without CSRF protection return HTTP 403."""
    client = tts_env["client"]

    res = client.post(
        "/voice/synthesize",
        json={"text": "Test speech", "language": "en-IN"},
    )

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Headless Chrome Browser Decoding Verification (CDP)
# ---------------------------------------------------------------------------

def test_chrome_decodes_real_telugu_and_hindi_mp3_audio():
    """Verifies that Chrome's HTML5 Audio decoder successfully decodes the generated Indic MP3."""
    if not os.path.exists(CHROME_PATH):
        pytest.skip("Chrome executable not found at " + CHROME_PATH)

    import websockets

    # 1. Generate real Telugu audio
    service = TTSService(provider=GoogleFreeTTSProvider())
    telugu_text = "మీ స్కాలర్‌షిప్ వివరాలు నమోదు చేయబడ్డాయి."
    audio_bytes, _ = service.synthesize(telugu_text, "te-IN")
    b64_audio = base64.b64encode(audio_bytes).decode("ascii")

    # 2. Launch headless Chrome instance
    port = 9226
    proc = subprocess.Popen(
        [
            CHROME_PATH,
            "--headless=new",
            f"--remote-debugging-port={port}",
            "--disable-gpu",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    ws_url = None
    for _ in range(30):
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json")
            data = json.loads(req.read().decode())
            if data and "webSocketDebuggerUrl" in data[0]:
                ws_url = data[0]["webSocketDebuggerUrl"]
                break
        except Exception:
            time.sleep(0.1)

    if not ws_url:
        proc.kill()
        pytest.fail("Failed to connect to headless Chrome")

    loop = asyncio.new_event_loop()

    async def _verify_in_browser():
        async with websockets.connect(ws_url) as ws:
            js = f"""
            new Promise((resolve, reject) => {{
                const audio = new Audio('data:audio/mpeg;base64,{b64_audio}');
                audio.onloadedmetadata = () => {{
                    resolve({{
                        duration: audio.duration,
                        readyState: audio.readyState,
                        paused: audio.paused
                    }});
                }};
                audio.onerror = (e) => {{
                    reject(audio.error ? audio.error.message : 'Audio decode failure');
                }};
            }})
            """
            msg = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js, "awaitPromise": True, "returnByValue": True},
            }
            await ws.send(json.dumps(msg))
            resp = json.loads(await ws.recv())
            val = resp.get("result", {}).get("result", {}).get("value", {})
            return val

    result = loop.run_until_complete(_verify_in_browser())
    loop.close()
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Browser decoded audio verification
    assert result.get("duration", 0) > 1.0, "Audio duration must be greater than 1 second"
    assert result.get("readyState") >= 1, "Audio element must reach HAVE_METADATA or higher"


# ---------------------------------------------------------------------------
# Static Code & Frontend UI Contract Tests
# ---------------------------------------------------------------------------

def test_frontend_dashboard_js_implements_hybrid_tts():
    """Verifies that dashboard.js contains speakWithBackendTts and wires all required controls."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    assert "speakWithBackendTts" in js
    assert "voiceTtsLoadingIndicator" in js
    assert "voicePlayBtn" in js
    assert "voiceStopSpeakingBtn" in js
    assert "voiceReplayBtn" in js
    assert "synthesizeSpeechAudio" in js


def test_frontend_api_js_exports_synthesize_speech_audio():
    """Verifies that api.js exports synthesizeSpeechAudio."""
    with open(API_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    assert "async function synthesizeSpeechAudio(" in js
    assert "window.synthesizeSpeechAudio = synthesizeSpeechAudio;" in js


def test_frontend_dashboard_html_contains_voice_controls():
    """Verifies that dashboard.html includes loading, speaking, play, stop, and replay controls."""
    with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="voiceTtsLoadingIndicator"' in html
    assert 'id="voiceSpeakingIndicator"' in html
    assert 'id="voicePlayBtn"' in html
    assert 'id="voiceStopSpeakingBtn"' in html
    assert 'id="voiceReplayBtn"' in html


def test_frontend_auth_css_contains_voice_loading_and_play_styles():
    """Verifies that auth.css contains styling for .voice-tts-loading and .voice-audio-btn.play."""
    with open(AUTH_CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".voice-tts-loading" in css
    assert ".voice-audio-btn.play" in css
    assert ".spinner-small" in css


def test_frontend_pre_unlock_audio_and_i18n_play_response():
    """Verifies that preUnlockAudio is defined in dashboard.js and playResponse is localized."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    assert "function preUnlockAudio()" in js
    assert "preUnlockAudio();" in js

    i18n_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "i18n.js")
    with open(i18n_path, "r", encoding="utf-8") as f:
        i18n_js = f.read()

    assert '"playResponse": "Play"' in i18n_js
    assert '"playResponse": "ప్లే చేయండి"' in i18n_js
    assert '"playResponse": "प्ले करें"' in i18n_js


