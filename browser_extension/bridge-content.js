/**
 * SahayAI Extension - Bridge Content Script
 * Runs in an isolated world exclusively on verified SahayAI web application origins.
 *
 * Security Architecture (Explicit Extension-Controlled Consent):
 * 1. Signals to the SahayAI web dashboard that the extension is installed and ready.
 * 2. Listens for notification intent (SAHAY_REQUEST_EXTENSION_AUTH) from the dashboard.
 * 3. A page message ALONE CANNOT AUTHORIZE A GRANT. Receiving a page message only stages
 *    a pending authorization intent in the background service worker.
 * 4. Explicit citizen approval inside the extension's Chrome popup is strictly required.
 * 5. Only after explicit user approval does the background service worker instruct this
 *    bridge script (via chrome.runtime.onMessage) to execute the authenticated grant request.
 * 6. The raw bearer grant token is received exclusively within this isolated execution context
 *    and returned directly to the service worker memory.
 * 7. The raw bearer grant is NEVER transmitted through window.postMessage, page DOM,
 *    cookies, localStorage, or query parameters.
 * 8. The dashboard only receives a safe completion status notification (SAHAY_EXTENSION_AUTH_RESULT).
 */

(function () {
    "use strict";

    const ALLOWED_ORIGINS = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ];

    function isAllowedOrigin(origin) {
        return ALLOWED_ORIGINS.includes(origin);
    }

    // 1. Mark presence in DOM root attribute
    try {
        document.documentElement.setAttribute("data-sahay-extension-installed", "true");
        document.documentElement.setAttribute("data-sahay-extension-version", "1.0.0");
        window.dispatchEvent(new CustomEvent("sahay-extension-ready", { detail: { version: "1.0.0" } }));
    } catch (e) {
        // Ignore restricted contexts
    }

    /**
     * Extracts non-HttpOnly sahay_csrf cookie if present.
     * @returns {string|null}
     */
    function getCsrfCookieValue() {
        try {
            const match = document.cookie.match(/(^|;)\s*sahay_csrf=([^;]+)/);
            return match ? decodeURIComponent(match[2]) : null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Obtains CSRF token either from cookie or from backend /auth/csrf-token endpoint.
     * @returns {Promise<string|null>}
     */
    async function obtainCsrfToken() {
        const cookieToken = getCsrfCookieValue();
        if (cookieToken) return cookieToken;

        try {
            const res = await fetch(`${window.location.origin}/auth/csrf-token`, {
                method: "GET",
                credentials: "include",
                headers: { Accept: "application/json" },
            });
            if (res.ok) {
                const data = await res.json();
                return data?.csrf_token || null;
            }
        } catch (e) {
            // Network or CORS failure
        }
        return null;
    }

    /**
     * Executes backend authorization ONLY after explicit extension popup approval.
     * Raw grant token is returned directly to the extension worker and NEVER posted to window.
     *
     * @param {object} payload
     * @returns {Promise<{success: boolean, grant?: object, error?: string}>}
     */
    async function executeApprovedAuth(payload) {
        try {
            const csrfToken = await obtainCsrfToken();
            if (!csrfToken) {
                return {
                    success: false,
                    error: "Unable to verify session security token (CSRF). Please refresh SahayAI.",
                };
            }

            const authRes = await fetch(`${window.location.origin}/applications/autofill/authorize`, {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-CSRF-Token": csrfToken,
                },
                body: JSON.stringify({
                    scheme_id: payload.schemeId,
                    portal_url: payload.portalUrl || "https://scholarships.gov.in",
                    draft_id: payload.draftId || null,
                }),
            });

            const data = await authRes.json().catch(() => ({}));

            if (!authRes.ok || !data.grant) {
                return {
                    success: false,
                    error: data.detail || `Server error ${authRes.status}`,
                };
            }

            return {
                success: true,
                grant: data.grant,
            };
        } catch (err) {
            return {
                success: false,
                error: "Network error during extension authorization.",
            };
        }
    }

    // 2. Listen for internal directives from trusted extension background service worker
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        if (!message || typeof message !== "object") return false;

        // Verify message sender is the extension itself
        if (sender.id !== chrome.runtime.id) return false;

        if (message.action === "EXECUTE_APPROVED_AUTHORIZATION") {
            // User explicitly approved through the Chrome popup UI.
            // Now and only now, perform authenticated grant request.
            executeApprovedAuth(message.payload)
                .then((result) => {
                    sendResponse(result);
                    if (result && result.success && result.grant) {
                        window.postMessage(
                            {
                                type: "SAHAY_EXTENSION_AUTH_RESULT",
                                success: true,
                                activeSchemeId: result.grant.scheme_id,
                                error: null,
                            },
                            window.location.origin
                        );
                    } else {
                        window.postMessage(
                            {
                                type: "SAHAY_EXTENSION_AUTH_RESULT",
                                success: false,
                                error: result?.error || "Authorization failed.",
                            },
                            window.location.origin
                        );
                    }
                })
                .catch((err) => {
                    sendResponse({ success: false, error: err.message || "Network error." });
                    window.postMessage(
                        {
                            type: "SAHAY_EXTENSION_AUTH_RESULT",
                            success: false,
                            error: "Network error during extension authorization.",
                        },
                        window.location.origin
                    );
                });
            return true; // Keep channel open for async response
        }

        if (message.action === "AUTHORIZATION_DENIED") {
            window.postMessage(
                {
                    type: "SAHAY_EXTENSION_AUTH_RESULT",
                    success: false,
                    error: "Authorization was denied by the citizen in the extension.",
                },
                window.location.origin
            );
            return false;
        }

        return false;
    });

    // 3. Listen for messages from the dashboard
    window.addEventListener("message", (event) => {
        if (!isAllowedOrigin(event.origin) || event.origin !== window.location.origin) {
            return;
        }

        const data = event.data;
        if (!data || typeof data !== "object") return;

        // Health check / status ping
        if (data.type === "SAHAY_CHECK_EXTENSION") {
            chrome.runtime.sendMessage({ action: "GET_CURRENT_GRANT" }, (resp) => {
                const hasActiveGrant = Boolean(resp && resp.grant && !resp.isExpired);
                window.postMessage(
                    {
                        type: "SAHAY_EXTENSION_STATUS",
                        installed: true,
                        connected: hasActiveGrant,
                        activeSchemeId: resp?.grant?.scheme_id || null,
                        version: "1.0.0",
                    },
                    event.origin
                );
            });
            return;
        }

        // Staging Intent: Page message requests authorization staging.
        // A page message CANNOT authorize a grant directly. Explicit extension approval is required!
        if (data.type === "SAHAY_REQUEST_EXTENSION_AUTH") {
            chrome.runtime.sendMessage(
                {
                    action: "STAGE_AUTH_REQUEST",
                    schemeId: data.schemeId,
                    portalUrl: data.portalUrl || "https://scholarships.gov.in",
                    draftId: data.draftId || null,
                },
                (resp) => {
                    const ok = Boolean(resp && resp.success);
                    window.postMessage(
                        {
                            type: "SAHAY_EXTENSION_STATUS",
                            installed: true,
                            connected: false,
                            pendingApproval: ok,
                            activeSchemeId: data.schemeId,
                            message: ok
                                ? "Authorization request staged. Please open the SahayAI extension from your browser toolbar to approve access."
                                : (resp?.error || "Failed to stage extension authorization."),
                        },
                        event.origin
                    );
                }
            );
            return;
        }
    });
})();
