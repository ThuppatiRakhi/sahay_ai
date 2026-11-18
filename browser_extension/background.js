/**
 * SahayAI Extension - Background Service Worker (Manifest V3)
 *
 * Security Architecture (Explicit Extension Consent & Fail-Closed Memory):
 * 1. Bearer grant tokens are held strictly in service worker volatile memory (short-lived 5-min TTL).
 * 2. Tokens are never exposed to content scripts, page DOM, cookies, URLs, or storage.
 * 3. A page message ALONE CANNOT AUTHORIZE A GRANT. Receiving a page message only stages
 *    a pending intent, which requires explicit user approval through the extension popup.
 * 4. Senders of STAGE_AUTH_REQUEST are strictly validated: sender.tab, top frame (frameId === 0),
 *    and verified SahayAI origins (http://localhost:8000, http://127.0.0.1:8000).
 * 5. Worker suspension or restart resets activeGrant to null and fails closed (HTTP 401).
 * 6. Validates expiry, exact scheme, draft ID, and verified government portal origin.
 * 7. Strictly no logging of personal data or bearer tokens.
 */

// In-memory grant & consent storage (reset on service worker restart)
let activeGrant = null;
let pendingAuthRequest = null;
let defaultApiBaseUrl = "http://127.0.0.1:8000";

const ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
];

function isAllowedOrigin(origin) {
    if (!origin) return false;
    return ALLOWED_ORIGINS.includes(origin) || ALLOWED_ORIGINS.some((allowed) => origin.startsWith(allowed));
}

// Load user-configured API URL from chrome.storage if present
if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["sahayApiBaseUrl"], (res) => {
        if (res && res.sahayApiBaseUrl) {
            defaultApiBaseUrl = res.sahayApiBaseUrl;
        }
    });
}

/**
 * Check if the stored grant is valid and not expired.
 * @returns {boolean}
 */
function isGrantValid() {
    if (!activeGrant || !activeGrant.grant_token || !activeGrant.expires_at) {
        return false;
    }
    try {
        const expiresTime = new Date(activeGrant.expires_at).getTime();
        const now = Date.now();
        return now < expiresTime;
    } catch (e) {
        return false;
    }
}

// Clean up expired grants periodically
setInterval(() => {
    if (activeGrant && !isGrantValid()) {
        activeGrant = null;
    }
    if (pendingAuthRequest && Date.now() - pendingAuthRequest.timestamp > 300000) {
        pendingAuthRequest = null;
    }
}, 30000);

// Message Handler
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message !== "object") return false;

    const action = message.action;

    // 0. Stage intent to authorize (Initiated by dashboard, but DOES NOT grant authorization!)
    if (action === "STAGE_AUTH_REQUEST") {
        // Strict sender validation
        if (!sender || !sender.tab || sender.tab.id === undefined) {
            sendResponse({ success: false, error: "Missing sender tab context." });
            return false;
        }

        // Validate top frame only (reject iframes)
        if (sender.frameId !== 0) {
            sendResponse({ success: false, error: "Authorization intent rejected: must originate from top-level frame." });
            return false;
        }

        // Validate expected SahayAI origin
        const senderOrigin = sender.origin || (sender.url ? new URL(sender.url).origin : null);
        if (!isAllowedOrigin(senderOrigin)) {
            sendResponse({ success: false, error: `Unauthorized sender origin '${senderOrigin}'.` });
            return false;
        }

        const schemeId = message.schemeId;
        const portalUrl = message.portalUrl || "https://scholarships.gov.in";
        const draftId = message.draftId || null;

        if (!schemeId) {
            sendResponse({ success: false, error: "Missing schemeId in authorization intent." });
            return false;
        }

        if (!draftId) {
            sendResponse({ success: false, error: "Missing draftId in authorization intent. An application draft is mandatory." });
            return false;
        }

        pendingAuthRequest = {
            schemeId: schemeId,
            portalUrl: portalUrl,
            draftId: draftId,
            tabId: sender.tab.id,
            origin: senderOrigin,
            timestamp: Date.now(),
        };

        // Visually signal in browser toolbar that user approval is required in extension popup
        if (typeof chrome !== "undefined" && chrome.action && chrome.action.setBadgeText) {
            chrome.action.setBadgeText({ text: "!", tabId: sender.tab.id });
            if (chrome.action.setBadgeBackgroundColor) {
                chrome.action.setBadgeBackgroundColor({ color: "#0f766e", tabId: sender.tab.id });
            }
        }

        sendResponse({ success: true, pending: true });
        return false;
    }

    // 0b. Query pending authorization request (for extension popup consent card)
    if (action === "GET_PENDING_AUTH") {
        if (!pendingAuthRequest) {
            sendResponse({ pendingAuth: null });
            return false;
        }
        if (Date.now() - pendingAuthRequest.timestamp > 300000) {
            pendingAuthRequest = null;
            sendResponse({ pendingAuth: null });
            return false;
        }
        sendResponse({ pendingAuth: pendingAuthRequest });
        return false;
    }

    // 0c. Explicit approval by citizen inside Chrome extension popup
    if (action === "APPROVE_PENDING_AUTH") {
        // Validate sender is the extension itself
        if (!sender || sender.id !== chrome.runtime.id) {
            sendResponse({ success: false, error: "Unauthorized caller." });
            return false;
        }

        if (!pendingAuthRequest) {
            sendResponse({ success: false, error: "No pending authorization request." });
            return false;
        }

        const targetTabId = pendingAuthRequest.tabId;
        const payload = {
            schemeId: pendingAuthRequest.schemeId,
            portalUrl: pendingAuthRequest.portalUrl,
            draftId: pendingAuthRequest.draftId,
        };

        // Instruct bridge-content.js in verified tab to execute authorization
        chrome.tabs.sendMessage(
            targetTabId,
            {
                action: "EXECUTE_APPROVED_AUTHORIZATION",
                payload: payload,
            },
            (response) => {
                if (response && response.success && response.grant) {
                    const grant = response.grant;
                    activeGrant = {
                        grant_id: grant.grant_id,
                        grant_token: grant.grant_token,
                        scheme_id: grant.scheme_id,
                        portal_url: grant.portal_url,
                        draft_id: grant.draft_id || payload.draftId || null,
                        expires_at: grant.expires_at,
                        scope: grant.scope || "extension:autofill",
                    };
                    pendingAuthRequest = null;

                    if (typeof chrome !== "undefined" && chrome.action && chrome.action.setBadgeText) {
                        chrome.action.setBadgeText({ text: "", tabId: targetTabId });
                    }

                    sendResponse({ success: true, grant_id: activeGrant.grant_id });
                } else {
                    sendResponse({ success: false, error: response?.error || "Authorization failed." });
                }
            }
        );
        return true; // Keep channel open for async tabs.sendMessage
    }

    // 0d. Explicit denial by citizen inside Chrome extension popup
    if (action === "DENY_PENDING_AUTH") {
        if (pendingAuthRequest && pendingAuthRequest.tabId) {
            const targetTabId = pendingAuthRequest.tabId;
            if (typeof chrome !== "undefined" && chrome.action && chrome.action.setBadgeText) {
                chrome.action.setBadgeText({ text: "", tabId: targetTabId });
            }
            chrome.tabs.sendMessage(targetTabId, { action: "AUTHORIZATION_DENIED" }, () => {});
        }
        pendingAuthRequest = null;
        sendResponse({ success: true, denied: true });
        return false;
    }

    // 1. Direct store scoped grant (Fallback for direct extension-internal flows)
    if (action === "STORE_GRANT") {
        const grant = message.grant;
        if (!grant || !grant.grant_token || !grant.expires_at || !grant.scheme_id) {
            sendResponse({ success: false, error: "Invalid grant structure" });
            return false;
        }

        // Validate portal URL
        const portalUrl = (grant.portal_url || "").toLowerCase();
        if (!portalUrl.includes("scholarships.gov.in")) {
            sendResponse({ success: false, error: "Untrusted portal URL binding" });
            return false;
        }

        activeGrant = {
            grant_id: grant.grant_id,
            grant_token: grant.grant_token,
            scheme_id: grant.scheme_id,
            portal_url: grant.portal_url,
            draft_id: grant.draft_id || null,
            expires_at: grant.expires_at,
            scope: grant.scope || "extension:autofill",
        };

        sendResponse({ success: true, grant_id: grant.grant_id });
        return false;
    }

    // 2. Query current grant status (metadata only, omitting token)
    if (action === "GET_CURRENT_GRANT") {
        if (!isGrantValid()) {
            activeGrant = null;
            sendResponse({ grant: null, isExpired: true });
            return false;
        }

        // Return non-sensitive metadata only
        sendResponse({
            isExpired: false,
            grant: {
                grant_id: activeGrant.grant_id,
                scheme_id: activeGrant.scheme_id,
                portal_url: activeGrant.portal_url,
                draft_id: activeGrant.draft_id,
                expires_at: activeGrant.expires_at,
                scope: activeGrant.scope,
            },
        });
        return false;
    }

    // 3. Clear grant
    if (action === "CLEAR_GRANT") {
        activeGrant = null;
        pendingAuthRequest = null;
        sendResponse({ success: true });
        return false;
    }

    // 4. Fetch Autofill Package from SahayAI backend API
    if (action === "FETCH_AUTOFILL_PACKAGE") {
        if (!isGrantValid()) {
            activeGrant = null;
            sendResponse({
                ok: false,
                status: 401,
                error: "Grant token has expired or is not authorized. Please initiate autofill from SahayAI dashboard.",
            });
            return false;
        }

        const schemeId = message.scheme_id || activeGrant.scheme_id;
        const portalUrl = message.portal_url || activeGrant.portal_url;
        const draftId = message.draft_id || activeGrant.draft_id;

        if (!schemeId || !portalUrl || !draftId) {
            sendResponse({
                ok: false,
                status: 422,
                error: "Missing mandatory autofill scope parameters (scheme_id, portal_url, draft_id).",
            });
            return false;
        }

        const endpoint = `${defaultApiBaseUrl}/applications/autofill/populate`;

        fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${activeGrant.grant_token}`,
            },
            body: JSON.stringify({
                scheme_id: schemeId,
                portal_url: portalUrl,
                draft_id: draftId,
            }),
        })
            .then(async (res) => {
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    sendResponse({
                        ok: false,
                        status: res.status,
                        error: data.detail || `Server returned error ${res.status}`,
                    });
                } else {
                    sendResponse({
                        ok: true,
                        status: res.status,
                        package: data.package,
                    });
                }
            })
            .catch((err) => {
                sendResponse({
                    ok: false,
                    status: 0,
                    error: `Network error connecting to SahayAI server at ${defaultApiBaseUrl}.`,
                });
            });

        return true; // Keep channel open for async response
    }

    // 5. Settings management
    if (action === "GET_SETTINGS") {
        sendResponse({
            apiBaseUrl: defaultApiBaseUrl,
            hasActiveGrant: isGrantValid(),
            activeGrantScheme: activeGrant?.scheme_id || null,
        });
        return false;
    }

    if (action === "SET_SETTINGS") {
        if (message.apiBaseUrl) {
            defaultApiBaseUrl = message.apiBaseUrl.trim();
            if (chrome.storage && chrome.storage.local) {
                chrome.storage.local.set({ sahayApiBaseUrl: defaultApiBaseUrl });
            }
        }
        sendResponse({ success: true, apiBaseUrl: defaultApiBaseUrl });
        return false;
    }

    return false;
});
