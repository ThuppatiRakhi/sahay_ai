/**
 * SahayAI Extension - Toolbar Popup Script
 *
 * Requirements:
 * 1. Clear branding and title.
 * 2. Distinct connection statuses: Not connected, Connected, or Error.
 * 3. Never display "Connected" unless the background service worker confirms an active, unexpired grant.
 * 4. Current website and supported-portal status check with clear unsupported messaging.
 * 5. Pending authorization requests with explicit [Approve] and [Deny] actions.
 * 6. Quick action to open SahayAI Dashboard.
 */

document.addEventListener("DOMContentLoaded", () => {
    const tabPortalStatus = document.getElementById("tabPortalStatus");
    const portalUnsupportedBanner = document.getElementById("portalUnsupportedBanner");
    const connectionStateBadge = document.getElementById("connectionStateBadge");
    const connectionText = document.getElementById("connectionText");
    const btnDisconnect = document.getElementById("btnDisconnect");
    const consentCard = document.getElementById("consentCard");
    const consentDetails = document.getElementById("consentDetails");
    const btnApproveAuth = document.getElementById("btnApproveAuth");
    const btnDenyAuth = document.getElementById("btnDenyAuth");
    const toggleSettings = document.getElementById("toggleSettings");
    const settingsPanel = document.getElementById("settingsPanel");
    const apiUrlInput = document.getElementById("apiUrlInput");
    const btnSaveSettings = document.getElementById("btnSaveSettings");

    // 1. Check active tab URL and portal support status
    if (chrome.tabs && chrome.tabs.query) {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (tabs && tabs[0] && tabs[0].url) {
                const url = tabs[0].url;
                if (window.SahayAIPortals && window.SahayAIPortals.isVerifiedPortal(url)) {
                    tabPortalStatus.className = "status-badge badge-active";
                    tabPortalStatus.textContent = "✓ On National Scholarship Portal";
                    if (portalUnsupportedBanner) portalUnsupportedBanner.style.display = "none";
                } else if (url.startsWith("http://localhost:8000") || url.startsWith("http://127.0.0.1:8000")) {
                    tabPortalStatus.className = "status-badge badge-dashboard";
                    tabPortalStatus.textContent = "⚡ SahayAI Workspace";
                    if (portalUnsupportedBanner) portalUnsupportedBanner.style.display = "none";
                } else {
                    tabPortalStatus.className = "status-badge badge-unsupported";
                    tabPortalStatus.textContent = "○ Unsupported Website";
                    if (portalUnsupportedBanner) {
                        portalUnsupportedBanner.style.display = "block";
                        portalUnsupportedBanner.innerHTML = `
                            <strong>Notice:</strong> Autofill is disabled on this site.<br>
                            The SahayAI extension only operates on the official National Scholarship Portal (<code>scholarships.gov.in</code>).
                        `;
                    }
                }
            } else {
                tabPortalStatus.className = "status-badge badge-inactive";
                tabPortalStatus.textContent = "○ Portal Inactive";
                if (portalUnsupportedBanner) portalUnsupportedBanner.style.display = "none";
            }
        });
    }

    // 2. Query Background Service Worker for Connection & Authorization Status
    function refreshStatus() {
        chrome.runtime.sendMessage({ action: "GET_PENDING_AUTH" }, (resp) => {
            if (chrome.runtime.lastError) {
                renderError(chrome.runtime.lastError.message || "Failed to communicate with service worker.");
                return;
            }

            if (resp && resp.pendingAuth) {
                renderPendingAuth(resp.pendingAuth);
                return;
            }

            // No pending authorization; query active grant
            chrome.runtime.sendMessage({ action: "GET_CURRENT_GRANT" }, (grantResp) => {
                if (chrome.runtime.lastError) {
                    renderError(chrome.runtime.lastError.message || "Failed to communicate with service worker.");
                    return;
                }

                // Strictly ensure "Connected" is displayed ONLY when an active, unexpired grant is confirmed
                if (grantResp && grantResp.grant && !grantResp.isExpired) {
                    renderConnected(grantResp.grant);
                } else {
                    renderNotConnected();
                }
            });
        });
    }

    function renderConnected(grant) {
        const schemeDef = window.SahayAIPortals?.SUPPORTED_SCHEMES[grant.scheme_id];
        const schemeName = schemeDef ? schemeDef.name : grant.scheme_id;
        let expiresTime = "5 minutes";
        try {
            expiresTime = new Date(grant.expires_at).toLocaleTimeString();
        } catch (e) {
            expiresTime = grant.expires_at;
        }

        connectionStateBadge.className = "status-badge badge-active";
        connectionStateBadge.textContent = "Connected";

        connectionText.innerHTML = `
            <div style="font-weight: 600; color: #166534;">✓ Connected & Ready</div>
            <div style="margin-top: 4px; font-weight: 500;">${schemeName}</div>
            ${grant.draft_id ? `<div style="font-size: 11px; color: #475569; margin-top: 2px;">Draft: <code>${grant.draft_id}</code></div>` : ""}
            <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Expires at: ${expiresTime}</div>
        `;

        if (btnDisconnect) btnDisconnect.style.display = "block";
        if (consentCard) consentCard.style.display = "none";
    }

    function renderNotConnected() {
        connectionStateBadge.className = "status-badge badge-inactive";
        connectionStateBadge.textContent = "Not connected";

        connectionText.innerHTML = `
            <div style="color: #64748b;">No active autofill grant.</div>
            <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">Open an application draft in SahayAI to connect.</div>
        `;

        if (btnDisconnect) btnDisconnect.style.display = "none";
        if (consentCard) consentCard.style.display = "none";
    }

    function renderPendingAuth(p) {
        const schemeDef = window.SahayAIPortals?.SUPPORTED_SCHEMES[p.schemeId];
        const schemeName = schemeDef ? schemeDef.name : p.schemeId;

        connectionStateBadge.className = "status-badge badge-pending";
        connectionStateBadge.textContent = "Pending Approval";

        connectionText.innerHTML = `
            <div style="color: #1d4ed8; font-weight: 600;">Authorization Requested</div>
            <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Explicit citizen approval required below.</div>
        `;

        if (consentDetails) {
            consentDetails.innerHTML = `
                <div>Scheme: <strong>${schemeName}</strong></div>
                <div style="margin-top: 2px;">Portal: <code>${p.portalUrl}</code></div>
                ${p.draftId ? `<div style="margin-top: 2px;">Draft ID: <code>${p.draftId}</code></div>` : ""}
                <div style="margin-top: 6px; color: #64748b; font-size: 10px; line-height: 1.4;">
                    Your explicit approval is required before the extension can access your confirmed application data.
                </div>
            `;
        }

        if (consentCard) consentCard.style.display = "block";
        if (btnDisconnect) btnDisconnect.style.display = "none";
    }

    function renderError(errorMessage) {
        connectionStateBadge.className = "status-badge badge-error";
        connectionStateBadge.textContent = "Error";

        connectionText.innerHTML = `
            <div style="color: #991b1b; font-weight: 600;">Connection Error</div>
            <div style="font-size: 11px; color: #64748b; margin-top: 2px;">${errorMessage}</div>
        `;

        if (btnDisconnect) btnDisconnect.style.display = "none";
        if (consentCard) consentCard.style.display = "none";
    }

    // Initial check
    refreshStatus();

    // 3. User Consent Handlers (Approve / Deny)
    if (btnApproveAuth) {
        btnApproveAuth.addEventListener("click", () => {
            btnApproveAuth.disabled = true;
            btnApproveAuth.textContent = "Authorizing...";
            chrome.runtime.sendMessage({ action: "APPROVE_PENDING_AUTH" }, () => {
                btnApproveAuth.disabled = false;
                btnApproveAuth.textContent = "Approve";
                if (consentCard) consentCard.style.display = "none";
                refreshStatus();
            });
        });
    }

    if (btnDenyAuth) {
        btnDenyAuth.addEventListener("click", () => {
            chrome.runtime.sendMessage({ action: "DENY_PENDING_AUTH" }, () => {
                if (consentCard) consentCard.style.display = "none";
                refreshStatus();
            });
        });
    }

    // 4. Disconnect / Clear Active Grant
    if (btnDisconnect) {
        btnDisconnect.addEventListener("click", () => {
            chrome.runtime.sendMessage({ action: "CLEAR_GRANT" }, () => {
                refreshStatus();
            });
        });
    }

    // 5. Developer Settings Management
    chrome.runtime.sendMessage({ action: "GET_SETTINGS" }, (resp) => {
        if (resp && resp.apiBaseUrl && apiUrlInput) {
            apiUrlInput.value = resp.apiBaseUrl;
        }
    });

    if (toggleSettings && settingsPanel) {
        toggleSettings.addEventListener("click", () => {
            const isHidden = settingsPanel.style.display === "none" || !settingsPanel.style.display;
            settingsPanel.style.display = isHidden ? "block" : "none";
        });
    }

    if (btnSaveSettings && apiUrlInput) {
        btnSaveSettings.addEventListener("click", () => {
            const val = apiUrlInput.value.trim();
            if (val) {
                chrome.runtime.sendMessage({ action: "SET_SETTINGS", apiBaseUrl: val }, () => {
                    btnSaveSettings.textContent = "Saved!";
                    setTimeout(() => {
                        btnSaveSettings.textContent = "Save URL";
                    }, 1500);
                });
            }
        });
    }
});
