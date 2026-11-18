# SahayAI Scholarship Assistant – Chrome Extension (Manifest V3)

The **SahayAI Scholarship Assistant** is a secure, privacy-first browser extension designed to assist Indian citizens applying for scholarships on the official [National Scholarship Portal (NSP)](https://scholarships.gov.in).

---

## 1. Key Principles & Security Guarantees

1. **Assisted Autofill Only**: SahayAI **never** submits applications automatically. Citizens personally handle login, OTPs, CAPTCHAs, and the final "Submit" button.
2. **Zero Credential Access**: The extension **never** reads, stores, or interacts with password, OTP, CAPTCHA, or secret fields.
3. **Restricted Portal Origin**: Active form autofill is strictly limited to verified official portal origins (`https://scholarships.gov.in/*`).
4. **Pure Deterministic Data**: Only fields explicitly confirmed by the citizen in their SahayAI document library or verified profile are filled. Unconfirmed OCR, conflicting values, and missing fields are strictly excluded.
5. **No Silent Overwrites**: If a form input already contains a value, SahayAI does not overwrite it silently.
6. **One-Click Undo**: The extension maintains pre-autofill state in memory so citizens can revert all changes at any time.
7. **Short-Lived Scoped Grants**: No session cookies or permanent personal tokens are ever exposed to the extension. The extension communicates with SahayAI using 5-minute grant tokens (`sahay_atf_...`) hashed with SHA-256 at rest.

---

## 2. Directory Structure

```
browser_extension/
├── manifest.json            # Chrome Manifest V3 configuration
├── background.js           # Service worker managing in-memory grants & API communication
├── content.js              # Floating assistant UI & safe field filler for scholarships.gov.in
├── bridge-content.js       # Secure handoff script running on SahayAI web origins
├── popup.html              # Extension toolbar popup interface
├── popup.js                # Toolbar popup logic & portal detection
├── styles.css              # Scoped CSS for the floating assistant panel
├── supported-portals.js    # Verified scheme definitions, field selectors, and security filters
├── icons/                  # 16px, 48px, 128px extension icons
└── README.md               # Architecture and local installation instructions
```

---

## 3. Supported Scholarship Schemes

| Scheme Identifier | Official Scheme Name | Verified Portal |
|---|---|---|
| `SCHEME_EDU_001_PM_USP_CSSS` | PM-USP Central Sector Scheme of Scholarship for College and University Students | `https://scholarships.gov.in` |
| `SCHEME_EDU_002_AICTE_PRAGATI` | AICTE Pragati Scholarship for Girl Students | `https://scholarships.gov.in` |
| `SCHEME_EDU_003_AICTE_SAKSHAM` | AICTE Saksham Scholarship for Specially-Abled Students | `https://scholarships.gov.in` |
| `SCHEME_EDU_004_AICTE_SWANATH` | AICTE Swanath Scholarship Scheme | `https://scholarships.gov.in` |
| `SCHEME_EDU_005_TOP_CLASS_SC` | Top Class Education Scheme for SC Students | `https://scholarships.gov.in` |

---

## 4. Local Developer Installation Instructions

To test the extension locally in Google Chrome or any Chromium-compatible browser (Edge, Brave):

1. **Open Extension Management**:
   Navigate to `chrome://extensions/` in your browser.
2. **Enable Developer Mode**:
   Toggle the **Developer mode** switch in the top-right corner.
3. **Load Unpacked Extension**:
   Click the **Load unpacked** button in the top-left toolbar.
4. **Select Folder**:
   Browse to and select the `browser_extension` folder in this repository:
   `Sahay_ai/browser_extension`
5. **Verify Installation**:
   Confirm that **SahayAI Scholarship Assistant** appears in your extensions list with version `1.0.0` and errors count `0`.

---

## 5. End-to-End Workflow Testing

1. Start the SahayAI backend server (`uvicorn api.main:app --port 8000`).
2. Open the citizen dashboard at `http://localhost:5500/frontend/dashboard.html` (or `http://localhost:8000/frontend/dashboard.html`).
3. Log in with a registered citizen account.
4. In the **My Documents** section, ensure you have confirmed identity, bank, or income documents.
5. In the **My Scholarship Applications** section, open or create an application draft (e.g. `PM-USP CSSS`).
6. Click **Continue to Official Portal** (or use the extension connection banner).
7. SahayAI issues a one-time 5-minute grant to the extension.
8. When navigating to `https://scholarships.gov.in`, the **⚡ SahayAI Autofill** floating assistant appears in the bottom right corner.
9. Click the pill to view readiness stats (`Ready`, `Conflicts`, `Missing`).
10. Click **Autofill Form Fields** to populate eligible fields.
11. Review the green-highlighted inputs on the form. Use **Undo Autofill** if you wish to revert.

---

## 6. Chrome Web Store Publication Checklist

Before submitting to the official Chrome Web Store:
- [ ] Ensure HTTPS is enforced for the SahayAI backend production API URL.
- [ ] Remove localhost development origins from `host_permissions` and `content_scripts`.
- [ ] Complete single-purpose description and privacy policy disclosures.
- [ ] Provide a demo video demonstrating citizen-initiated autofill and manual portal submission.

