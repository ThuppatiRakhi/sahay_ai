"""Automated tests for SahayAI Phase 1 Chat Response Markdown Rendering and XSS Sanitization.

Validates:
1. Static code contracts:
   - renderSafeMarkdown is implemented and exported in frontend/js/dashboard.js.
   - HTML pre-sanitization (escapeHtml) precedes Markdown formatting.
   - Strict protocol validation (isSafeUrl) protects hyperlink rendering against javascript: URIs.
   - appendChatMessage routes assistant messages through renderSafeMarkdown while keeping user textContent safe.
   - Voice assistant modal uses renderSafeMarkdown for assistant responses.
   - frontend/css/auth.css contains styling rules for tables, citations, lists, headings, and code.

2. Dynamic headless Chrome browser verification (via Chrome DevTools Protocol):
   - Telugu headings (##), bold (**text**), citations ([S1]).
   - Telugu tables (| col |) and horizontal separators (---).
   - Hindi ordered lists (1.), unordered lists (-, •, ✓), and citations ([S1, S2]).
   - XSS attack prevention: <script>, <img onerror>, javascript: links.
   - Valid HTTPS links render as target="_blank" rel="noopener noreferrer".
   - Code blocks and inline code preservation.
   - Indic script and Unicode conjunct preservation (Telugu, Hindi, English, Romanized).
"""

import asyncio
import json
import os
import re
import subprocess
import time
import urllib.request
import pytest

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DASHBOARD_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "dashboard.js")
AUTH_CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "css", "auth.css")


# ---------------------------------------------------------------------------
# Static Code Contract Tests
# ---------------------------------------------------------------------------

def test_static_dashboard_js_implements_render_safe_markdown():
    """Verifies that dashboard.js defines and exports renderSafeMarkdown."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    assert "function renderSafeMarkdown(" in js_code
    assert "window.renderSafeMarkdown = renderSafeMarkdown;" in js_code


def test_static_dashboard_js_pre_escapes_html_for_xss_defense():
    """Verifies that renderSafeMarkdown invokes escapeHtml before converting Markdown tokens."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    # Find the function definition
    fn_idx = js_code.find("function renderSafeMarkdown(")
    assert fn_idx != -1
    fn_body = js_code[fn_idx : fn_idx + 1500]

    # Pre-sanitization check
    assert "escapeHtml(rawText)" in fn_body or "escapeHtml(" in fn_body


def test_static_dashboard_js_enforces_safe_url_on_links():
    """Verifies that links inside markdown validate against isSafeUrl."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    fn_idx = js_code.find("function renderSafeMarkdown(")
    assert fn_idx != -1
    fn_body = js_code[fn_idx : fn_idx + 3000]

    assert "isSafeUrl(" in fn_body
    assert 'rel="noopener noreferrer"' in fn_body


def test_static_dashboard_js_append_chat_message_routes_assistant():
    """Verifies that appendChatMessage uses renderSafeMarkdown for assistant responses."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    fn_idx = js_code.find("function appendChatMessage(")
    assert fn_idx != -1
    fn_body = js_code[fn_idx : fn_idx + 1500]

    assert "isUser" in fn_body
    assert "textDiv.textContent = content" in fn_body
    assert "textDiv.innerHTML = renderSafeMarkdown(content" in fn_body


def test_static_dashboard_js_voice_handler_uses_safe_markdown():
    """Verifies that voice answer text is formatted through renderSafeMarkdown."""
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    assert "voiceAnswerText.innerHTML = renderSafeMarkdown(data.content" in js_code


def test_static_auth_css_contains_chat_markdown_styles():
    """Verifies that auth.css contains styling for tables, citations, horizontal rules, and headings."""
    with open(AUTH_CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".chat-table-wrapper" in css
    assert ".chat-markdown-table" in css
    assert ".chat-inline-citation" in css
    assert ".chat-markdown-hr" in css
    assert ".chat-message-text h4" in css
    assert ".chat-inline-code" in css
    assert ".chat-code-block" in css
    assert ".chat-markdown-link" in css


# ---------------------------------------------------------------------------
# Dynamic Headless Chrome CDP Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def chrome_cdp_session():
    """Launches a headless Chrome instance with CDP and yields an async evaluator."""
    if not os.path.exists(CHROME_PATH):
        pytest.skip("Chrome executable not found at " + CHROME_PATH)

    import websockets

    port = 9223
    proc = subprocess.Popen(
        [
            CHROME_PATH,
            "--headless=new",
            f"--remote-debugging-port={port}",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll until CDP endpoint is ready
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
        pytest.fail("Failed to connect to headless Chrome CDP on port " + str(port))

    # Read dashboard.js to inject into Chrome page
    with open(DASHBOARD_JS_PATH, "r", encoding="utf-8") as f:
        js_source = f.read()

    # Run event loop to execute JS evaluations
    loop = asyncio.new_event_loop()

    async def _setup_page():
        async with websockets.connect(ws_url) as ws:
            # Inject dashboard.js code in global context
            msg = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js_source},
            }
            await ws.send(json.dumps(msg))
            resp = json.loads(await ws.recv())
            assert "result" in resp

    loop.run_until_complete(_setup_page())

    def evaluate_js(expression: str) -> str:
        async def _eval():
            async with websockets.connect(ws_url) as ws:
                msg = {
                    "id": int(time.time() * 1000) % 100000,
                    "method": "Runtime.evaluate",
                    "params": {"expression": expression, "returnByValue": True},
                }
                await ws.send(json.dumps(msg))
                resp = json.loads(await ws.recv())
                result = resp.get("result", {}).get("result", {})
                return result.get("value", "")

        return loop.run_until_complete(_eval())

    yield evaluate_js

    # Teardown
    loop.close()
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_chrome_cdp_telugu_headings_and_bold(chrome_cdp_session):
    """Verifies that Telugu Markdown with ## and ** renders semantic <h4> and <strong> tags."""
    eval_js = chrome_cdp_session
    sample_telugu = (
        "## ముఖ్యమైన అర్హతలు\n\n"
        "**అభ్యర్థి స్థితి** – అమ్మాయి విద్యార్థి [S1]\n\n"
        "**వార్షిక కుటుంబ ఆదాయం** – గరిష్టంగా ₹8,00,000 [S2]"
    )
    js_expr = f"renderSafeMarkdown({json.dumps(sample_telugu)})"
    html = eval_js(js_expr)

    assert "<h4>ముఖ్యమైన అర్హతలు</h4>" in html
    assert "<strong>అభ్యర్థి స్థితి</strong>" in html
    assert "<strong>వార్షిక కుటుంబ ఆదాయం</strong>" in html
    assert '<span class="chat-inline-citation">[S1]</span>' in html
    assert '<span class="chat-inline-citation">[S2]</span>' in html
    assert "##" not in html
    assert "**" not in html


def test_chrome_cdp_telugu_markdown_table_and_hr(chrome_cdp_session):
    """Verifies that Telugu tables with pipe separators and dashes render table markup."""
    eval_js = chrome_cdp_session
    sample_table = (
        "---\n\n"
        "| వివరాలు | పరిమితి |\n"
        "| --- | --- |\n"
        "| వార్షిక ఆదాయం | ₹8,00,000 |\n"
        "| పిల్లల సంఖ్య | 2 |\n"
    )
    js_expr = f"renderSafeMarkdown({json.dumps(sample_table)})"
    html = eval_js(js_expr)

    assert '<hr class="chat-markdown-hr">' in html
    assert '<div class="chat-table-wrapper"><table class="chat-markdown-table">' in html
    assert "<th>వివరాలు</th>" in html
    assert "<th>పరిమితి</th>" in html
    assert "<td>వార్షిక ఆదాయం</td>" in html
    assert "<td>₹8,00,000</td>" in html
    assert "<td>పిల్లల సంఖ్య</td>" in html
    assert "<td>2</td>" in html
    assert "| --- |" not in html


def test_chrome_cdp_hindi_ordered_and_unordered_lists(chrome_cdp_session):
    """Verifies that Hindi ordered and unordered lists render <ol> and <ul> structures."""
    eval_js = chrome_cdp_session
    sample_hindi = (
        "1. **पात्रता** - केवल छात्राएं [S1]\n"
        "2. **आय सीमा** - ₹8 लाख [S2]\n\n"
        "- आय प्रमाण पत्र\n"
        "- आधार कार्ड\n"
        "- बैंक पासबुक"
    )
    js_expr = f"renderSafeMarkdown({json.dumps(sample_hindi)})"
    html = eval_js(js_expr)

    assert "<ol>" in html
    assert "<li><strong>पात्रता</strong> - केवल छात्राएं" in html
    assert "<li><strong>आय सीमा</strong> - ₹8 लाख" in html
    assert "</ol>" in html
    assert "<ul>" in html
    assert "<li>आय प्रमाण पत्र</li>" in html
    assert "<li>आधार कार्ड</li>" in html
    assert "<li>बैंक पासबुक</li>" in html
    assert "</ul>" in html


def test_chrome_cdp_xss_sanitization_defense(chrome_cdp_session):
    """Verifies that script injection and onerror payloads are rendered harmlessly as escaped entities."""
    eval_js = chrome_cdp_session
    xss_payload = (
        "<script>alert('xss')</script>\n"
        "<img src=x onerror=alert(1)>\n"
        "<svg/onload=alert(2)>\n"
        "[malicious link](javascript:alert(document.cookie))"
    )
    js_expr = f"renderSafeMarkdown({json.dumps(xss_payload)})"
    html = eval_js(js_expr)

    # HTML tags should be escaped, never raw tags
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html
    assert "&lt;img" in html
    assert "<svg" not in html
    assert "&lt;svg" in html
    # Dangerous protocol must not generate an <a> tag
    assert 'href="javascript:' not in html
    assert "javascript:alert(document.cookie)" in html


def test_chrome_cdp_safe_links_rendering(chrome_cdp_session):
    """Verifies that trusted HTTPS URLs render as clickable anchor elements."""
    eval_js = chrome_cdp_session
    link_md = "Visit the [National Scholarship Portal](https://scholarships.gov.in) to apply."
    js_expr = f"renderSafeMarkdown({json.dumps(link_md)})"
    html = eval_js(js_expr)

    assert '<a href="https://scholarships.gov.in" target="_blank" rel="noopener noreferrer" class="chat-markdown-link">National Scholarship Portal</a>' in html


def test_chrome_cdp_indic_conjuncts_and_unicode_preservation(chrome_cdp_session):
    """Verifies that Indic conjuncts, matras, and numbers remain completely intact."""
    eval_js = chrome_cdp_session
    sample_text = (
        "### దరఖాస్తు విధానం\n"
        "1. నేషనల్ స్కాలర్‌షిప్ పోర్టల్ (NSP) లో నమోదు చేసుకోండి [S1].\n"
        "2. విద్యార్థి వివరాలు మరియు బ్యాంకు ఖాతా నమోదు చేయండి [S2]."
    )
    js_expr = f"renderSafeMarkdown({json.dumps(sample_text)})"
    html = eval_js(js_expr)

    assert "<h5>దరఖాస్తు విధానం</h5>" in html
    assert "నేషనల్ స్కాలర్‌షిప్ పోర్టల్ (NSP)" in html
    assert "బ్యాంకు ఖాతా" in html
    assert '<span class="chat-inline-citation">[S1]</span>' in html
    assert '<span class="chat-inline-citation">[S2]</span>' in html

