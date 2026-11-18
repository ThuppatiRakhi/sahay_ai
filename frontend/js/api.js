/**
 * SahayAI - Central API Configuration and HTTP Client
 *
 * Security Principles:
 * 1. Never stores session IDs, passwords, or tokens in localStorage or sessionStorage.
 * 2. Authenticated requests use 'credentials: "include"' so the browser manages
 *    the HttpOnly 'sahay_session' cookie automatically.
 * 3. State-changing requests (POST, PUT, DELETE) obtain and send the 'X-CSRF-Token' header.
 * 4. Error messages are formatted for citizen readability (never exposing internal stack traces).
 */

const API_CONFIG = {
    
    baseUrl: (
        typeof window !== "undefined" && window.SAHAY_API_BASE
    )
        ? window.SAHAY_API_BASE.replace(/\/+$/, "")
        : (
            typeof window !== "undefined" &&
            ["localhost", "127.0.0.1"].includes(window.location.hostname)
        )
            ? "http://127.0.0.1:8000"
            : "https://sahay-ai-ste8.onrender.com",

};

// In-memory cache for CSRF token (isolated from local/sessionStorage)
let inMemoryCsrfToken = null;

/**
 * Extracts non-HttpOnly CSRF cookie if present in document.cookie.
 * @returns {string|null}
 */
function getCsrfCookieValue() {
    if (typeof document === "undefined") return null;
    const match = document.cookie.match(/(^|;)\s*sahay_csrf=([^;]+)/);
    return match ? decodeURIComponent(match[2]) : null;
}

/**
 * Fetches or returns the cached CSRF token for the active session.
 * @param {boolean} forceRefresh - If true, ignores cached values and fetches a fresh token from server.
 * @returns {Promise<string|null>}
 */
async function getCsrfToken(forceRefresh = false) {
    if (!forceRefresh && inMemoryCsrfToken) {
        return inMemoryCsrfToken;
    }

    if (!forceRefresh) {
        const cookieToken = getCsrfCookieValue();
        if (cookieToken) {
            inMemoryCsrfToken = cookieToken;
            return inMemoryCsrfToken;
        }
    }

    try {
        const response = await fetch(`${API_CONFIG.baseUrl}/auth/csrf-token`, {
            method: "GET",
            credentials: "include",
            headers: {
                "Accept": "application/json",
            },
        });

        if (response.ok) {
            const data = await response.json();
            if (data && data.csrf_token) {
                inMemoryCsrfToken = data.csrf_token;
                return inMemoryCsrfToken;
            }
        }
    } catch (err) {
        console.warn("Unable to obtain CSRF token from server:", err);
    }

    return null;
}

/**
 * Clears the in-memory CSRF token upon logout or session invalidation.
 */
function clearCsrfCache() {
    inMemoryCsrfToken = null;
    if (typeof document !== "undefined") {
        document.cookie = "sahay_csrf=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    }
}

/**
 * Formats backend validation and HTTP errors into citizen-friendly text.
 * @param {number} status
 * @param {any} data
 * @returns {string}
 */
function formatErrorMessage(status, data) {
    if (!data) {
        if (status === 401) return "Please sign in to continue.";
        if (status === 403) return "Access denied or session security check failed.";
        if (status === 404) return "Requested resource not found.";
        if (status === 409) return "An account or profile with these details already exists.";
        if (status >= 500) return "Server encountered an error. Please try again later.";
        return "An unexpected network error occurred. Please check your connection.";
    }

    // FastAPI 422 validation error array
    if (Array.isArray(data.detail)) {
        return data.detail.map(e => e.msg || e.message || JSON.stringify(e)).join(". ");
    }

    // String detail
    if (typeof data.detail === "string") {
        return data.detail;
    }

    if (data.message) {
        return data.message;
    }

    return "An unexpected error occurred.";
}

/**
 * Central authenticated fetch wrapper.
 *
 * @param {string} endpoint - API path (e.g., '/auth/login', '/profile/me')
 * @param {object} options - Fetch options (method, headers, body)
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function apiFetch(endpoint, options = {}) {
    const url = endpoint.startsWith("http") ? endpoint : `${API_CONFIG.baseUrl}${endpoint}`;
    const method = (options.method || "GET").toUpperCase();

    const headers = {
        "Accept": "application/json",
        ...(options.headers || {}),
    };

    if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }

    // Attach CSRF token on mutating requests if not pre-auth signup/login/guest initialization
    const isMutating = ["POST", "PUT", "DELETE", "PATCH"].includes(method);
    const isPreAuth = endpoint.includes("/auth/signup") || endpoint.includes("/auth/login") || endpoint.includes("/auth/guest");

    if (isMutating && !isPreAuth) {
        const token = await getCsrfToken();
        if (token) {
            headers["X-CSRF-Token"] = token;
        }
    }

    const config = {
        ...options,
        method,
        headers,
        credentials: "include", // Essential for HttpOnly session cookie handling
    };

    try {
        const response = await fetch(url, config);
        let data = null;

        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            try {
                data = await response.json();
            } catch {
                data = null;
            }
        }

        if (!response.ok) {
            // Automatic retry on CSRF token mismatch, revocation, or expiry
            if (response.status === 403 && data && typeof data.detail === "string" && data.detail.includes("CSRF token") && !options._csrfRetried) {
                console.warn("CSRF token validation failed. Refreshing CSRF token and retrying request...");
                clearCsrfCache();
                const freshToken = await getCsrfToken(true);
                if (freshToken) {
                    const retryHeaders = {
                        ...headers,
                        "X-CSRF-Token": freshToken,
                    };
                    return apiFetch(endpoint, {
                        ...options,
                        headers: retryHeaders,
                        _csrfRetried: true,
                    });
                }
            }

            const errorMsg = formatErrorMessage(response.status, data);
            return {
                ok: false,
                status: response.status,
                data,
                error: errorMsg,
            };
        }

        return {
            ok: true,
            status: response.status,
            data,
            error: null,
        };
    } catch (networkError) {
        console.error("Network or connection error:", networkError);
        return {
            ok: false,
            status: 0,
            data: null,
            error: "Unable to connect to the SahayAI service. Please verify that the backend server is running.",
        };
    }
}

/**
 * Universal logout helper function.
 */
async function logoutCitizen() {
    try {
        await apiFetch("/auth/logout", { method: "POST" });
    } catch (err) {
        console.warn("Logout error:", err);
    } finally {
        clearCsrfCache();
        window.location.href = "login.html";
    }
}

// ---------------------------------------------------------------------------
// Step 4D: Conversational RAG Chat API Helpers
// ---------------------------------------------------------------------------

/**
 * Submits a citizen message to the conversational RAG chat engine.
 *
 * @param {string} message - Citizen inquiry text
 * @param {string|null} conversationId - Optional conversation ID to continue
 * @param {string|null} language - Optional target response language (e.g. 'te-IN', 'hi-IN', 'en-IN')
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function sendChatMessage(message, conversationId = null, language = null) {
    const payload = { message };
    if (conversationId) {
        payload.conversation_id = conversationId;
    }
    const resolvedLanguage = language || (typeof I18n !== 'undefined' ? I18n.getLanguage() : null);
    if (resolvedLanguage) {
        payload.language = resolvedLanguage;
    }
    return apiFetch("/chat/message", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

/**
 * Retrieves the list of past saved conversations for the authenticated citizen.
 * Note: Blocked for guest users (returns 403 Forbidden).
 *
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchChatConversations() {
    return apiFetch("/chat/conversations", {
        method: "GET",
    });
}

/**
 * Retrieves full chronological message history for a specific saved conversation.
 *
 * @param {string} conversationId - Target conversation ID
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchChatConversationDetails(conversationId) {
    return apiFetch(`/chat/conversations/${encodeURIComponent(conversationId)}`, {
        method: "GET",
    });
}

/**
 * Deletes a conversation owned by the authenticated citizen.
 *
 * @param {string} conversationId - Target conversation ID
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function deleteChatConversation(conversationId) {
    return apiFetch(`/chat/conversations/${encodeURIComponent(conversationId)}`, {
        method: "DELETE",
    });
}

// ---------------------------------------------------------------------------
// Step 5.4B: Citizen My Documents Library API Helpers
// ---------------------------------------------------------------------------

/**
 * Retrieves the stored documents list for the authenticated citizen.
 *
 * @param {string|null} category - Optional document category filter
 * @param {boolean} includeArchived - Whether to include soft-deleted / archived documents
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchCitizenDocuments(category = null, includeArchived = false) {
    const params = new URLSearchParams();
    if (category) params.append("category", category);
    if (includeArchived) params.append("include_archived", "true");
    const query = params.toString() ? `?${params.toString()}` : "";
    return apiFetch(`/documents${query}`, { method: "GET" });
}

/**
 * Retrieves metadata and sanitized extracted fields for a specific document.
 *
 * @param {string} documentId - Target document identifier
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchDocumentMetadata(documentId) {
    return apiFetch(`/documents/${encodeURIComponent(documentId)}`, { method: "GET" });
}

/**
 * Uploads a document with automatic magic byte verification, vault encryption, and OCR.
 *
 * @param {FormData|File} formDataOrFile - Multipart form or File object
 * @param {string} [docType] - Document type if File was passed
 * @param {string} [category] - Document category if File was passed
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function uploadCitizenDocument(formDataOrFile, docType = null, category = null) {
    let body = formDataOrFile;
    if (formDataOrFile instanceof File) {
        body = new FormData();
        body.append("file", formDataOrFile);
        if (category) body.append("document_category", category);
        if (docType) body.append("document_type", docType);
    }
    return apiFetch("/documents/upload", {
        method: "POST",
        body: body,
    });
}

/**
 * Replaces an existing document with a new upload and re-triggers OCR extraction.
 *
 * @param {string} documentId - Target document identifier to replace
 * @param {FormData|File} formDataOrFile - Multipart form containing replacement 'file' or File object
 * @param {string} [docType] - Optional document type
 * @param {string} [category] - Optional document category
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function replaceCitizenDocument(documentId, formDataOrFile, docType = null, category = null) {
    let body = formDataOrFile;
    if (formDataOrFile instanceof File) {
        body = new FormData();
        body.append("file", formDataOrFile);
        if (category) body.append("document_category", category);
        if (docType) body.append("document_type", docType);
    }
    return apiFetch(`/documents/${encodeURIComponent(documentId)}/replace`, {
        method: "POST",
        body: body,
    });
}

/**
 * Deletes or archives a document.
 *
 * @param {string} documentId - Target document identifier
 * @param {boolean} hardDelete - If true, permanently deletes encrypted file and cascades; if false, archives
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function deleteCitizenDocument(documentId, hardDelete = true) {
    const query = hardDelete ? "?hard_delete=true" : "?hard_delete=false";
    return apiFetch(`/documents/${encodeURIComponent(documentId)}${query}`, {
        method: "DELETE",
    });
}

/**
 * Retrieves pending document extraction results and profile conflict analysis for citizen review.
 *
 * @param {string} documentId - Target document identifier
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchDocumentReview(documentId) {
    return apiFetch(`/documents/${encodeURIComponent(documentId)}/review`, { method: "GET" });
}

/**
 * Confirms, corrects, and persists document-extracted profile fields.
 *
 * @param {string} documentId - Target document identifier
 * @param {object} payload - Confirmation payload with confirmations list or confirmed_fields dict
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function confirmDocumentFields(documentId, payload) {
    const body = Array.isArray(payload) ? { confirmations: payload } : (payload || {});
    return apiFetch(`/documents/${encodeURIComponent(documentId)}/confirm`, {
        method: "POST",
        body: JSON.stringify(body),
    });
}

/**
 * Reclassifies a document and re-extracts structured fields using target document type schema.
 *
 * @param {string} documentId - Target document identifier
 * @param {string} documentType - New target document type
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function reclassifyCitizenDocument(documentId, documentType) {
    return apiFetch(`/documents/${encodeURIComponent(documentId)}/reclassify`, {
        method: "POST",
        body: JSON.stringify({ document_type: documentType }),
    });
}

/**
 * Securely downloads the original decrypted document in-memory.
 * Triggered programmatically via browser Blob URL and immediately revoked.
 *
 * @param {string} documentId - Target document identifier
 * @param {string} fallbackFilename - Fallback filename if Content-Disposition is absent
 * @returns {Promise<{ok: boolean, error: string|null}>}
 */
async function downloadCitizenDocument(documentId, fallbackFilename = "document.pdf") {
    const url = `${API_CONFIG.baseUrl}/documents/${encodeURIComponent(documentId)}/download`;
    try {
        const response = await fetch(url, {
            method: "GET",
            credentials: "include",
            headers: {
                "Accept": "*/*",
            },
        });

        if (!response.ok) {
            let errorMsg = "Unable to download document.";
            try {
                const errData = await response.json();
                errorMsg = formatErrorMessage(response.status, errData);
            } catch {
                errorMsg = formatErrorMessage(response.status, null);
            }
            return { ok: false, error: errorMsg };
        }

        let downloadFilename = fallbackFilename;
        const disposition = response.headers.get("content-disposition");
        if (disposition) {
            const filenameMatch = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
            if (filenameMatch && filenameMatch[1]) {
                downloadFilename = decodeURIComponent(filenameMatch[1].trim());
            }
        }

        const blob = await response.blob();
        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = downloadFilename;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);

        return { ok: true, error: null };
    } catch (err) {
        console.error("Document download failed:", err);
        return {
            ok: false,
            error: "Network error while downloading document. Please verify connection.",
        };
    }
}

// ---------------------------------------------------------------------------
// Step 5.5A: Scholarship Application Workspace API Helpers
// ---------------------------------------------------------------------------

/**
 * Retrieves the application definition, guidelines, official portal URL, and form sections
 * for a specific scholarship scheme.
 *
 * @param {string} schemeId - Target scheme identifier
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchSchemeApplicationDefinition(schemeId) {
    return apiFetch(`/applications/schemes/${encodeURIComponent(schemeId)}/definition`, {
        method: "GET",
    });
}

/**
 * Retrieves all 5 supported scholarship application definitions.
 *
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchAllSchemeApplicationDefinitions() {
    return apiFetch("/applications/schemes", {
        method: "GET",
    });
}

/**
 * Initializes a new persistent application draft for the authenticated registered citizen.
 *
 * @param {string} schemeId - Target scheme identifier
 * @param {string} applicationMode - 'FRESH' or 'RENEWAL'
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function createApplicationDraft(schemeId, applicationMode = "FRESH") {
    return apiFetch("/applications/drafts", {
        method: "POST",
        body: JSON.stringify({
            scheme_id: schemeId,
            application_mode: applicationMode,
        }),
    });
}

/**
 * Retrieves the list of scholarship application drafts for the authenticated citizen.
 *
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchCitizenApplicationDrafts() {
    return apiFetch("/applications/drafts", {
        method: "GET",
    });
}

/**
 * Retrieves a specific application draft with full form data and attached scheme definition.
 *
 * @param {string} draftId - Target draft identifier
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchApplicationDraftDetails(draftId) {
    return apiFetch(`/applications/drafts/${encodeURIComponent(draftId)}`, {
        method: "GET",
    });
}

/**
 * Updates form field data, section progress, or lifecycle status in an application draft.
 *
 * @param {string} draftId - Target draft identifier
 * @param {object} payload - Fields to update { form_data, status, last_saved_section, notes }
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function updateApplicationDraft(draftId, payload) {
    return apiFetch(`/applications/drafts/${encodeURIComponent(draftId)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
    });
}

/**
 * Deletes an application draft owned by the authenticated citizen.
 *
 * @param {string} draftId - Target draft identifier
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function deleteApplicationDraft(draftId) {
    return apiFetch(`/applications/drafts/${encodeURIComponent(draftId)}`, {
        method: "DELETE",
    });
}

/**
 * Issues a short-lived (5-minute), scoped grant token for browser extension autofill.
 *
 * @param {string} schemeId - Target scholarship scheme ID
 * @param {string} portalUrl - Target government portal URL (https://scholarships.gov.in)
 * @param {string|null} [draftId] - Optional application draft ID
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function authorizeAutofillGrant(schemeId, portalUrl, draftId = null) {
    return apiFetch("/applications/autofill/authorize", {
        method: "POST",
        body: JSON.stringify({
            scheme_id: schemeId,
            portal_url: portalUrl,
            draft_id: draftId,
        }),
    });
}

/**
 * Retrieves the populated autofill package with provenance and conflict flags.
 *
 * @param {string} schemeId - Target scholarship scheme ID
 * @param {string} portalUrl - Target government portal URL
 * @param {string|null} [draftId] - Optional application draft ID
 * @param {string|null} [bearerToken] - Optional extension bearer grant token
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function populateAutofillPackage(schemeId, portalUrl, draftId = null, bearerToken = null) {
    const headers = {};
    if (bearerToken) {
        headers["Authorization"] = `Bearer ${bearerToken}`;
    }
    return apiFetch("/applications/autofill/populate", {
        method: "POST",
        headers,
        body: JSON.stringify({
            scheme_id: schemeId,
            portal_url: portalUrl,
            draft_id: draftId,
        }),
    });
}

/**
 * Retrieves autofill preview comparison for an existing citizen draft.
 *
 * @param {string} draftId - Target application draft ID
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function fetchDraftAutofillPreview(draftId) {
    return apiFetch(`/applications/drafts/${encodeURIComponent(draftId)}/autofill-preview`, {
        method: "GET",
    });
}

/**
 * Applies clean, non-conflicting autofill fields or selected confirmed values into a draft.
 *
 * @param {string} draftId - Target application draft ID
 * @param {object|null} [fieldsToApply] - Optional subset of fields to apply
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 */
async function applyDraftAutofill(draftId, fieldsToApply = null) {
    return apiFetch(`/applications/drafts/${encodeURIComponent(draftId)}/autofill-apply`, {
        method: "POST",
        body: JSON.stringify({
            fields_to_apply: fieldsToApply,
        }),
    });
}

/**
 * Synthesizes speech audio for Telugu, Hindi, or English text via backend TTS fallback.
 *
 * @param {string} text - Response text to speak aloud
 * @param {string} [language="en-IN"] - Locale code (te-IN, hi-IN, en-IN)
 * @returns {Promise<{ok: boolean, status: number, blob: Blob|null, error: string|null}>}
 */
async function synthesizeSpeechAudio(text, language = "en-IN") {
    if (!text || typeof text !== "string" || !text.trim()) {
        return { ok: false, status: 400, blob: null, error: "Text cannot be empty." };
    }

    const url = `${API_CONFIG.baseUrl}/voice/synthesize`;
    const token = await getCsrfToken();
    const headers = {
        "Content-Type": "application/json",
        "Accept": "audio/mpeg, application/json",
    };
    if (token) {
        headers["X-CSRF-Token"] = token;
    }

    try {
        const response = await fetch(url, {
            method: "POST",
            headers,
            credentials: "include",
            body: JSON.stringify({
                text: text.trim(),
                language: language || "en-IN",
            }),
        });

        if (!response.ok) {
            let errorMsg = `Voice generation failed (HTTP ${response.status}).`;
            try {
                const errData = await response.json();
                if (errData && (errData.detail || errData.error)) {
                    errorMsg = errData.detail || errData.error;
                }
            } catch {}
            return { ok: false, status: response.status, blob: null, error: errorMsg };
        }

        const audioBlob = await response.blob();
        return { ok: true, status: response.status, blob: audioBlob, error: null };
    } catch (networkError) {
        console.error("TTS synthesize network error:", networkError);
        return {
            ok: false,
            status: 0,
            blob: null,
            error: "Unable to connect to the speech synthesis service. Please check your connection.",
        };
    }
}
if (typeof window !== "undefined") {
    window.synthesizeSpeechAudio = synthesizeSpeechAudio;
}




