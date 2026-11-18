/**
 * SahayAI Extension - Content Script (scholarships.gov.in)
 *
 * Operational and Security Guarantees:
 * 1. Runs strictly on verified National Scholarship Portal (scholarships.gov.in).
 * 2. Never accesses or handles passwords, OTPs, CAPTCHAs, or CSRF tokens.
 * 3. Never auto-clicks "Submit", "Save", or any consequential government portal action.
 * 4. Fills ONLY confirmed fields where status === "POPULATED" and mapping is "VERIFIED".
 * 5. All 20 field mappings are in TEMPLATE_ONLY status awaiting live portal verification.
 *    The autofill button is strictly disabled; manual entry is required.
 * 6. Strictly protects non-empty inputs from silent overwriting (flags as conflict).
 * 7. Dispatches standard 'input', 'change', and 'blur' events for framework compatibility.
 * 8. Provides a live reference checklist of citizen's confirmed values for manual entry.
 * 9. Allows minimizing to a compact floating badge and expanding at any time.
 * 10. Supports single-click Undo to restore pre-autofill field values.
 */

(function () {
    "use strict";

    // Ensure SahayAIPortals helper is available
    const Portals = window.SahayAIPortals || (typeof self !== "undefined" ? self.SahayAIPortals : null);
    if (!Portals) {
        return;
    }

    // Verify origin
    if (!Portals.isVerifiedPortal(window.location.href)) {
        return;
    }

    // Undo History map: element -> originalValue
    const undoHistory = new Map();
    let currentAutofillPackage = null;
    let isPanelOpen = false;

    /**
     * Build and inject the floating assistant UI into the page.
     */
    function injectAssistantUI() {
        if (document.getElementById("sahay-assistant-root")) return;

        const root = document.createElement("div");
        root.id = "sahay-assistant-root";
        root.className = "sahay-assistant-root";

        root.innerHTML = `
            <!-- Floating Launch Pill (Minimized State) -->
            <div class="sahay-launch-pill" id="sahayLaunchPill" title="Open SahayAI Scholarship Assistant">
                <span class="sahay-icon">⚡</span>
                <span>SahayAI Assistant</span>
            </div>

            <!-- Assistant Card (Expanded State) -->
            <div class="sahay-card" id="sahayCard">
                <div class="sahay-header">
                    <div class="sahay-title-wrap">
                        <strong>⚡ SahayAI Assistant</strong>
                        <span class="sahay-badge-status sahay-badge-idle" id="sahayStatusBadge">Checking...</span>
                    </div>
                    <div class="sahay-header-controls">
                        <button type="button" class="sahay-header-btn" id="sahayBtnMinimize" title="Minimize to badge" aria-label="Minimize assistant">&minus;</button>
                        <button type="button" class="sahay-header-btn" id="sahayBtnClose" title="Close assistant" aria-label="Close assistant">&times;</button>
                    </div>
                </div>

                <div class="sahay-body">
                    <!-- Scheme Info Box -->
                    <div class="sahay-scheme-box" id="sahaySchemeBox">
                        <div class="sahay-scheme-title" id="sahaySchemeName">No Active Scheme</div>
                        <div class="sahay-scheme-meta" id="sahayPortalName">National Scholarship Portal (scholarships.gov.in)</div>
                        <div class="sahay-scheme-meta" id="sahayDraftId" style="margin-top: 2px; font-family: monospace;"></div>
                    </div>

                    <!-- Readiness Summary Stats -->
                    <div class="sahay-stats-row" id="sahayStatsRow" style="display: none;">
                        <div class="sahay-stat-card">
                            <span class="sahay-stat-num" id="sahayStatPopulated" style="color: #15803d;">0</span>
                            <span class="sahay-stat-label">Ready</span>
                        </div>
                        <div class="sahay-stat-card">
                            <span class="sahay-stat-num" id="sahayStatConflicts" style="color: #b45309;">0</span>
                            <span class="sahay-stat-label">Conflicts</span>
                        </div>
                        <div class="sahay-stat-card">
                            <span class="sahay-stat-num" id="sahayStatMissing" style="color: #64748b;">0</span>
                            <span class="sahay-stat-label">Missing</span>
                        </div>
                    </div>

                    <!-- Template Only Notice Box -->
                    <div class="sahay-template-notice" id="sahayTemplateNotice">
                        <strong>⚠️ Autofill Disabled (Live Verification Pending)</strong>
                        All 20 field mappings are currently in <code>TEMPLATE_ONLY</code> status awaiting live government portal verification. Automatic population is disabled to prevent inaccurate submissions.
                        <div style="margin-top: 4px; font-weight: 500;">Please complete the form fields manually using your confirmed reference details below.</div>
                    </div>

                    <!-- Manual Reference Checklist Container -->
                    <div class="sahay-ref-container" id="sahayRefContainer">
                        <div class="sahay-ref-header">
                            <span>Confirmed Document Checklist</span>
                            <span style="font-size: 10px; color: #64748b;">Manual Reference</span>
                        </div>
                        <div class="sahay-ref-list" id="sahayRefList">
                            <div style="color: #94a3b8; font-size: 11px; padding: 4px 0;">
                                Connect your scholarship draft from SahayAI to view confirmed field values.
                            </div>
                        </div>
                    </div>

                    <!-- Official Submission Disclaimer -->
                    <div class="sahay-notice-box">
                        <strong>Official Submission Notice:</strong> SahayAI does not submit applications directly to government portals. You must personally review every field, enter OTP/CAPTCHAs, and click Submit.
                    </div>

                    <!-- Action Result Alert -->
                    <div id="sahayResultAlert" style="display: none; padding: 8px 10px; border-radius: 4px; font-size: 11px; margin-bottom: 12px;"></div>

                    <!-- Buttons -->
                    <div class="sahay-actions">
                        <button type="button" class="sahay-btn sahay-btn-primary" id="sahayBtnAutofill" disabled title="All 20 field mappings are in TEMPLATE_ONLY status awaiting live government portal verification.">Autofill Disabled (Manual Entry Required)</button>
                        <button type="button" class="sahay-btn sahay-btn-secondary" id="sahayBtnUndo" style="display: none;">Undo Autofill</button>
                    </div>
                </div>

                <div class="sahay-footer">
                    <span>Connected to <a href="http://127.0.0.1:8000/frontend/dashboard.html" target="_blank" rel="noopener noreferrer">SahayAI Dashboard</a></span>
                </div>
            </div>
        `;

        document.body.appendChild(root);

        // Bind UI Controls
        const pill = document.getElementById("sahayLaunchPill");
        const card = document.getElementById("sahayCard");
        const btnMinimize = document.getElementById("sahayBtnMinimize");
        const btnClose = document.getElementById("sahayBtnClose");
        const btnAutofill = document.getElementById("sahayBtnAutofill");
        const btnUndo = document.getElementById("sahayBtnUndo");

        // Open assistant
        pill.addEventListener("click", () => {
            isPanelOpen = true;
            card.style.display = "block";
            pill.style.display = "none";
            refreshGrantStatus();
        });

        // Minimize assistant to badge
        if (btnMinimize) {
            btnMinimize.addEventListener("click", () => {
                isPanelOpen = false;
                card.style.display = "none";
                pill.style.display = "flex";
            });
        }

        // Close assistant (collapses to floating pill)
        if (btnClose) {
            btnClose.addEventListener("click", () => {
                isPanelOpen = false;
                card.style.display = "none";
                pill.style.display = "flex";
            });
        }

        btnAutofill.addEventListener("click", handleAutofillClick);
        btnUndo.addEventListener("click", handleUndoClick);
    }

    /**
     * Query background service worker for active grant status.
     */
    function refreshGrantStatus() {
        chrome.runtime.sendMessage({ action: "GET_CURRENT_GRANT" }, (response) => {
            const badge = document.getElementById("sahayStatusBadge");
            const schemeNameEl = document.getElementById("sahaySchemeName");
            const draftIdEl = document.getElementById("sahayDraftId");
            const btnAutofill = document.getElementById("sahayBtnAutofill");
            const statsRow = document.getElementById("sahayStatsRow");
            const refList = document.getElementById("sahayRefList");

            if (!badge || !schemeNameEl) return;

            if (response && response.grant && !response.isExpired) {
                badge.className = "sahay-badge-status sahay-badge-connected";
                badge.textContent = "Connected";

                const schemeDef = Portals.SUPPORTED_SCHEMES[response.grant.scheme_id];
                schemeNameEl.textContent = schemeDef ? schemeDef.name : response.grant.scheme_id;
                if (draftIdEl) {
                    draftIdEl.textContent = response.grant.draft_id ? `Draft: ${response.grant.draft_id}` : "";
                }

                // Field mappings remain TEMPLATE_ONLY: keep autofill button disabled
                if (btnAutofill) {
                    btnAutofill.disabled = true;
                    btnAutofill.textContent = "Autofill Disabled (Manual Entry Required)";
                    btnAutofill.title = "All 20 field mappings are in TEMPLATE_ONLY status awaiting live government portal verification.";
                }

                // Fetch package preview to display readiness stats and reference checklist
                fetchPackagePreview(response.grant);
            } else {
                badge.className = "sahay-badge-status sahay-badge-idle";
                badge.textContent = "Not Connected";
                schemeNameEl.textContent = "Open SahayAI to connect draft";
                if (draftIdEl) draftIdEl.textContent = "";

                if (btnAutofill) {
                    btnAutofill.disabled = true;
                    btnAutofill.textContent = "Autofill Disabled (Not Connected)";
                }

                if (statsRow) statsRow.style.display = "none";
                if (refList) {
                    refList.innerHTML = `
                        <div style="color: #94a3b8; font-size: 11px; padding: 4px 0;">
                            Connect your scholarship draft from SahayAI to view confirmed field values.
                        </div>
                    `;
                }
            }
        });
    }

    /**
     * Fetch package preview from background worker and render readiness stats & reference list.
     */
    function fetchPackagePreview(grant) {
        chrome.runtime.sendMessage(
            {
                action: "FETCH_AUTOFILL_PACKAGE",
                scheme_id: grant.scheme_id,
                portal_url: window.location.href,
                draft_id: grant.draft_id,
            },
            (resp) => {
                if (resp && resp.ok && resp.package) {
                    currentAutofillPackage = resp.package;
                    const summary = resp.package.summary || {};

                    const statsRow = document.getElementById("sahayStatsRow");
                    const popEl = document.getElementById("sahayStatPopulated");
                    const confEl = document.getElementById("sahayStatConflicts");
                    const missEl = document.getElementById("sahayStatMissing");

                    if (statsRow && popEl && confEl && missEl) {
                        statsRow.style.display = "grid";
                        popEl.textContent = summary.populated_fields || 0;
                        confEl.textContent = summary.conflict_fields || 0;
                        missEl.textContent = summary.missing_fields || 0;
                    }

                    renderReferenceChecklist(resp.package.fields || {});
                }
            }
        );
    }

    /**
     * Render the confirmed application values for citizen reference during manual portal entry.
     */
    function renderReferenceChecklist(fields) {
        const refList = document.getElementById("sahayRefList");
        if (!refList) return;

        const entries = Object.entries(fields);
        if (entries.length === 0) {
            refList.innerHTML = `<div style="color: #94a3b8; font-size: 11px;">No field data available.</div>`;
            return;
        }

        let html = "";
        for (const [fieldId, fieldSpec] of entries) {
            const mapping = Portals.FIELD_MAPPINGS[fieldId] || {};
            const label = mapping.label || fieldId.replace(/_/g, " ");
            const status = fieldSpec.status || "UNKNOWN";

            let badgeHtml = "";
            let valHtml = "";

            if (status === "POPULATED") {
                badgeHtml = `<span class="sahay-ref-badge sahay-ref-badge-ready">Ready</span>`;
                valHtml = `<span class="sahay-ref-val">${escapeHtml(String(fieldSpec.value || ""))}</span>`;
            } else if (status === "CONFLICT") {
                badgeHtml = `<span class="sahay-ref-badge sahay-ref-badge-conflict">Conflict</span>`;
                valHtml = `<span style="color: #b45309; font-size: 10px;">Review documents</span>`;
            } else {
                badgeHtml = `<span class="sahay-ref-badge sahay-ref-badge-missing">Missing</span>`;
                valHtml = `<span style="color: #94a3b8; font-size: 10px;">Not confirmed</span>`;
            }

            html += `
                <div class="sahay-ref-item">
                    <span class="sahay-ref-label">${escapeHtml(label)}</span>
                    <div class="sahay-ref-val-wrap">
                        ${valHtml}
                        ${badgeHtml}
                    </div>
                </div>
            `;
        }

        refList.innerHTML = html;
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /**
     * Safely populate a form input element and fire standard DOM events.
     */
    function populateElement(element, value) {
        if (!element || Portals.isForbiddenElement(element)) {
            return false;
        }

        const tag = element.tagName.toLowerCase();
        const type = (element.getAttribute("type") || "").toLowerCase();

        // Save original value for Undo
        if (!undoHistory.has(element)) {
            undoHistory.set(element, {
                value: element.value,
                checked: element.checked,
                className: element.className,
            });
        }

        if (tag === "select") {
            const strVal = String(value).trim().toLowerCase();
            let matched = false;
            for (let i = 0; i < element.options.length; i++) {
                const opt = element.options[i];
                if (
                    opt.value.trim().toLowerCase() === strVal ||
                    opt.text.trim().toLowerCase() === strVal
                ) {
                    element.selectedIndex = i;
                    matched = true;
                    break;
                }
            }
            if (!matched && element.options.length > 0) {
                element.value = String(value);
            }
        } else if (type === "checkbox" || type === "radio") {
            element.checked = Boolean(value);
        } else {
            element.value = String(value);
        }

        // Dispatch input and change events for reactive frameworks
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        element.dispatchEvent(new Event("blur", { bubbles: true }));

        element.classList.add("sahay-autofilled-field");
        return true;
    }

    /**
     * Handle autofill button click.
     * Strictly verifies whether any mapping is VERIFIED before populating.
     */
    function handleAutofillClick() {
        const resultAlert = document.getElementById("sahayResultAlert");
        const btnAutofill = document.getElementById("sahayBtnAutofill");
        const btnUndo = document.getElementById("sahayBtnUndo");

        if (!currentAutofillPackage || !currentAutofillPackage.fields) {
            if (resultAlert) {
                resultAlert.style.display = "block";
                resultAlert.style.background = "#fef2f2";
                resultAlert.style.color = "#991b1b";
                resultAlert.textContent = "Autofill package not loaded. Please connect your draft in SahayAI.";
            }
            return;
        }

        btnAutofill.disabled = true;
        btnAutofill.textContent = "Populating...";

        let filledCount = 0;
        let skippedExistingCount = 0;
        let conflictCount = 0;
        let missingCount = 0;
        let skippedTemplateOnlyCount = 0;

        const fields = currentAutofillPackage.fields;

        for (const [fieldId, fieldSpec] of Object.entries(fields)) {
            // Strictly prohibit populating fields whose mapping status is TEMPLATE_ONLY or UNSUPPORTED
            const mapping = Portals.FIELD_MAPPINGS[fieldId];
            if (!mapping || mapping.status !== "VERIFIED") {
                skippedTemplateOnlyCount++;
                continue;
            }

            // Strictly check status
            if (fieldSpec.status === "CONFLICT") {
                conflictCount++;
                const el = Portals.findFieldElement(document, fieldId);
                if (el && !Portals.isForbiddenElement(el)) {
                    el.classList.add("sahay-conflict-field");
                }
                continue;
            }

            if (fieldSpec.status === "MISSING_INFORMATION") {
                missingCount++;
                continue;
            }

            if (fieldSpec.status === "POPULATED" && fieldSpec.value !== null && fieldSpec.value !== undefined) {
                const el = Portals.findFieldElement(document, fieldId);
                if (!el) continue;

                // Check for existing non-empty value (Never overwrite silently!)
                const currentVal = (el.value || "").trim();
                const intendedVal = String(fieldSpec.value).trim();

                if (currentVal !== "" && currentVal.toLowerCase() !== intendedVal.toLowerCase()) {
                    skippedExistingCount++;
                    el.classList.add("sahay-conflict-field");
                    continue;
                }

                const ok = populateElement(el, fieldSpec.value);
                if (ok) filledCount++;
            }
        }

        btnAutofill.disabled = true;
        btnAutofill.textContent = "Autofill Disabled (Manual Entry Required)";

        if (btnUndo) {
            btnUndo.style.display = filledCount > 0 ? "block" : "none";
        }

        if (resultAlert) {
            resultAlert.style.display = "block";
            if (filledCount > 0) {
                resultAlert.style.background = "#f0fdf4";
                resultAlert.style.color = "#166534";
                resultAlert.innerHTML = `
                    <strong>Autofill Completed:</strong>
                    <div>✓ Successfully filled ${filledCount} verified fields.</div>
                    ${skippedTemplateOnlyCount > 0 ? `<div>ℹ️ Skipped ${skippedTemplateOnlyCount} fields (TEMPLATE_ONLY awaiting live portal verification).</div>` : ""}
                    ${skippedExistingCount > 0 ? `<div>⚠️ Skipped ${skippedExistingCount} non-empty fields to prevent overwrite.</div>` : ""}
                    ${conflictCount > 0 ? `<div>⚠️ Flagged ${conflictCount} conflicting fields (review required).</div>` : ""}
                    ${missingCount > 0 ? `<div>ℹ️ ${missingCount} fields left blank (upload documents in SahayAI).</div>` : ""}
                `;
            } else if (skippedTemplateOnlyCount > 0) {
                resultAlert.style.background = "#eff6ff";
                resultAlert.style.color = "#1e40af";
                resultAlert.innerHTML = `
                    <strong>Autofill Status Notice:</strong>
                    <div>ℹ️ All ${skippedTemplateOnlyCount} mapped fields are currently TEMPLATE_ONLY specifications awaiting live portal verification.</div>
                    <div style="margin-top: 4px; font-size: 11px; line-height: 1.4;">
                        To protect submission accuracy, SahayAI refuses automatic population until selectors are confirmed on the live government portal. Please use the reference checklist above to enter details manually.
                    </div>
                `;
            } else {
                resultAlert.style.background = "#fef3c7";
                resultAlert.style.color = "#92400e";
                resultAlert.innerHTML = `
                    <strong>Autofill Notice:</strong>
                    <div>No eligible verified fields found to populate on this page.</div>
                `;
            }
        }
    }

    /**
     * Handle citizen clicking "Undo Autofill".
     */
    function handleUndoClick() {
        const resultAlert = document.getElementById("sahayResultAlert");
        const btnUndo = document.getElementById("sahayBtnUndo");

        let undoneCount = 0;
        undoHistory.forEach((original, el) => {
            if (el && el.parentNode) {
                el.value = original.value;
                el.checked = original.checked;
                el.className = original.className;
                el.classList.remove("sahay-autofilled-field");
                el.classList.remove("sahay-conflict-field");

                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                undoneCount++;
            }
        });

        undoHistory.clear();

        if (btnUndo) btnUndo.style.display = "none";

        if (resultAlert) {
            resultAlert.style.display = "block";
            resultAlert.style.background = "#f8fafc";
            resultAlert.style.color = "#334155";
            resultAlert.textContent = `Reverted ${undoneCount} fields to their pre-autofill values.`;
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", injectAssistantUI);
    } else {
        injectAssistantUI();
    }
})();
