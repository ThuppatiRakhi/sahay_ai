/**
 * SahayAI - Citizen Dashboard & Government Scheme Discovery Controller
 *
 * Responsibilities:
 * 1. Fetches authenticated citizen profile via GET /profile/me and populates profile card.
 * 2. Manages session expiration (redirect to login) and handles secure citizen logout.
 * 3. Provides Government Scheme Discovery Engine:
 *    - Recommendations view via GET /schemes/recommendations (preliminary matches vs rule mismatches).
 *    - Catalog view via GET /schemes with search & multi-attribute filtering.
 *    - Comprehensive Scheme Details modal via GET /schemes/{scheme_id}.
 *    - Rule-based Eligibility Breakdown modal via GET /schemes/{scheme_id}/eligibility.
 * 4. Strictly displays official verification pending notices on all unreviewed schemes.
 *    Never presents unverified schemes as officially confirmed eligible or ineligible.
 */

// ---------------------------------------------------------------------------
// Security Helpers, Sanitization & Markdown Parser (Top-Level Scope)
// ---------------------------------------------------------------------------
function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Strict URL validation: permits only HTTP/HTTPS protocols to prevent javascript: URI XSS.
 */
function isSafeUrl(url) {
    if (!url || typeof url !== "string") return false;
    try {
        const parsed = new URL(url.trim());
        return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
        return false;
    }
}

/**
 * Safe Markdown Parser for Assistant Responses (Indic & Multilingual Support):
 * 1. Pre-sanitizes input with escapeHtml to prevent XSS (no raw script/html execution).
 * 2. Extracts code blocks and inline code into placeholders.
 * 3. Parses headers (#, ##, ###, ####), horizontal rules (---), tables (| c1 | c2 |),
 *    ordered lists (1.), unordered lists (-, *, •, ✓, etc.), and paragraphs.
 * 4. Parses bold (**text**), italic (*text*), safe links ([label](url)), and
 *    official citations ([S1], [S2], [S1, S2]).
 * 5. Restores code placeholders.
 */
function renderSafeMarkdown(rawText) {
    if (!rawText || typeof rawText !== "string") return "";

    // Step 1: Pre-sanitize all HTML tags & entities
    let sanitized = escapeHtml(rawText);

    // Step 2: Extract code blocks and inline code to prevent markdown formatting inside code
    const codeBlocks = [];
    sanitized = sanitized.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const id = `___CODEBLOCK_${codeBlocks.length}___`;
        codeBlocks.push(`<pre class="chat-code-block"><code>${code.trim()}</code></pre>`);
        return id;
    });

    const inlineCodes = [];
    sanitized = sanitized.replace(/`([^`\n]+)`/g, (match, code) => {
        const id = `___INLINECODE_${inlineCodes.length}___`;
        inlineCodes.push(`<code class="chat-inline-code">${code}</code>`);
        return id;
    });

    // Helper for inline formatting (bold, italic, citations, links)
    function formatInlines(text) {
        if (!text) return "";
        // Safe Links first: [label](url) where url must be http or https
        let out = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, url) => {
            const cleanUrl = url.trim();
            if (isSafeUrl(cleanUrl)) {
                return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer" class="chat-markdown-link">${label}</a>`;
            }
            return `${label} (${cleanUrl})`;
        });

        // Citations: [S1], [S2], [S1, S2], [S1, S3, S5]
        out = out.replace(/\[(S\d+(?:\s*,\s*S\d+)*)\]/g, '<span class="chat-inline-citation">[$1]</span>');

        // Bold + Italic: ***text*** or ___text___
        out = out.replace(/(\*\*\*|___)(.*?)\1/g, '<strong><em>$2</em></strong>');
        // Bold: **text** or __text__
        out = out.replace(/(\*\*|__)(.*?)\1/g, '<strong>$2</strong>');
        // Italic: *text* or _text_
        out = out.replace(/(\*|_)(.*?)\1/g, '<em>$2</em>');

        return out;
    }

    // Step 3: Process lines into block structures (headers, hr, tables, lists, paragraphs)
    const lines = sanitized.split(/\r?\n/);
    const htmlBlocks = [];
    let i = 0;

    while (i < lines.length) {
        const line = lines[i];
        const trimmed = line.trim();

        // Empty line
        if (!trimmed) {
            i++;
            continue;
        }

        // Horizontal Rule (---, ***, ___)
        if (/^(\-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
            htmlBlocks.push('<hr class="chat-markdown-hr">');
            i++;
            continue;
        }

        // Headers: #, ##, ###, ####
        const headerMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
        if (headerMatch) {
            const level = headerMatch[1].length;
            // Map #, ## -> h4, ### -> h5, ####.. -> h6 for neat chat scaling
            const tag = level <= 2 ? "h4" : (level === 3 ? "h5" : "h6");
            htmlBlocks.push(`<${tag}>${formatInlines(headerMatch[2])}</${tag}>`);
            i++;
            continue;
        }

        // Markdown Table: detects | col1 | col2 | followed by separator | --- | --- |
        if (trimmed.startsWith("|") && trimmed.endsWith("|") && i + 1 < lines.length) {
            const nextTrimmed = lines[i + 1].trim();
            if (/^\|[\s\-:|]+\|$/.test(nextTrimmed)) {
                const headerCells = trimmed.slice(1, -1).split("|").map(c => c.trim());
                let tableHtml = '<div class="chat-table-wrapper"><table class="chat-markdown-table"><thead><tr>';
                headerCells.forEach(hc => {
                    tableHtml += `<th>${formatInlines(hc)}</th>`;
                });
                tableHtml += '</tr></thead><tbody>';

                i += 2; // skip header and separator
                while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
                    const rowCells = lines[i].trim().slice(1, -1).split("|").map(c => c.trim());
                    tableHtml += '<tr>';
                    rowCells.forEach(rc => {
                        tableHtml += `<td>${formatInlines(rc)}</td>`;
                    });
                    tableHtml += '</tr>';
                    i++;
                }
                tableHtml += '</tbody></table></div>';
                htmlBlocks.push(tableHtml);
                continue;
            }
        }

        // Ordered List: 1. or 1) or 1 -
        const olMatch = trimmed.match(/^(\d+)[.)\-]\s+(.+)$/);
        if (olMatch) {
            let listHtml = '<ol>';
            while (i < lines.length) {
                const itemMatch = lines[i].trim().match(/^(\d+)[.)\-]\s+(.+)$/);
                if (itemMatch) {
                    listHtml += `<li>${formatInlines(itemMatch[2])}</li>`;
                    i++;
                } else if (!lines[i].trim()) {
                    // Check if next non-empty line continues the list
                    if (i + 1 < lines.length && /^\d+[.)\-]\s+/.test(lines[i + 1].trim())) {
                        i++;
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            listHtml += '</ol>';
            htmlBlocks.push(listHtml);
            continue;
        }

        // Unordered List: -, *, •, +, ✓, ✔, →, ►
        const ulMatch = trimmed.match(/^([-*•+✓✔→►])\s+(.+)$/);
        if (ulMatch) {
            let listHtml = '<ul>';
            while (i < lines.length) {
                const itemMatch = lines[i].trim().match(/^([-*•+✓✔→►])\s+(.+)$/);
                if (itemMatch) {
                    listHtml += `<li>${formatInlines(itemMatch[2])}</li>`;
                    i++;
                } else if (!lines[i].trim()) {
                    if (i + 1 < lines.length && /^[-*•+✓✔→►]\s+/.test(lines[i + 1].trim())) {
                        i++;
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            listHtml += '</ul>';
            htmlBlocks.push(listHtml);
            continue;
        }

        // Paragraph: collect lines until blank line or next block element
        const paraLines = [];
        while (i < lines.length) {
            const cur = lines[i].trim();
            if (!cur) break;
            // Stop if next line is a header, hr, list, or table
            if (/^#{1,6}\s+/.test(cur) ||
                /^(\-{3,}|\*{3,}|_{3,})$/.test(cur) ||
                /^(\d+)[.)\-]\s+/.test(cur) ||
                /^([-*•+✓✔→►])\s+/.test(cur) ||
                (cur.startsWith("|") && cur.endsWith("|") && i + 1 < lines.length && /^\|[\s\-:|]+\|$/.test(lines[i + 1].trim()))) {
                break;
            }
            paraLines.push(formatInlines(cur));
            i++;
        }
        if (paraLines.length > 0) {
            htmlBlocks.push(`<p>${paraLines.join("<br>")}</p>`);
        }
    }

    let result = htmlBlocks.join("\n");

    // Restore inline codes and code blocks
    inlineCodes.forEach((codeHtml, idx) => {
        result = result.replace(`___INLINECODE_${idx}___`, codeHtml);
    });
    codeBlocks.forEach((blockHtml, idx) => {
        result = result.replace(`___CODEBLOCK_${idx}___`, blockHtml);
    });

    return result;
}

window.escapeHtml = escapeHtml;
window.isSafeUrl = isSafeUrl;
window.renderSafeMarkdown = renderSafeMarkdown;

document.addEventListener("DOMContentLoaded", async () => {
    // ---------------------------------------------------------------------------
    // DOM Elements - Profile & Session
    // ---------------------------------------------------------------------------
    const welcomeHeading = document.getElementById("welcomeHeading");
    const navCitizenName = document.getElementById("navCitizenName");
    const dispFullName = document.getElementById("dispFullName");
    const dispUserId = document.getElementById("dispUserId");
    const dispAgeDob = document.getElementById("dispAgeDob");
    const dispGender = document.getElementById("dispGender");
    const dispLocation = document.getElementById("dispLocation");
    const dispIncome = document.getElementById("dispIncome");
    const dispOccupation = document.getElementById("dispOccupation");
    const dispCaste = document.getElementById("dispCaste");
    const dispBpl = document.getElementById("dispBpl");
    const dispConfirmed = document.getElementById("dispConfirmed");
    const logoutBtn = document.getElementById("logoutBtn");
    const alertBox = document.getElementById("alertBox");

    // ---------------------------------------------------------------------------
    // DOM Elements - Scheme Discovery & Tabs
    // ---------------------------------------------------------------------------
    const tabRecommendations = document.getElementById("tabRecommendations");
    const tabCatalog = document.getElementById("tabCatalog");
    const schemeFiltersBar = document.getElementById("schemeFiltersBar");
    const recommendationControls = document.getElementById("recommendationControls");
    const applicationTypeSelect = document.getElementById("applicationTypeSelect");
    const schemeSearchInput = document.getElementById("schemeSearchInput");
    const categoryFilter = document.getElementById("categoryFilter");
    const educationFilter = document.getElementById("educationFilter");
    const beneficiaryFilter = document.getElementById("beneficiaryFilter");
    const btnApplyFilters = document.getElementById("btnApplyFilters");
    const btnResetFilters = document.getElementById("btnResetFilters");
    const schemesAlertBox = document.getElementById("schemesAlertBox");
    const schemesContainer = document.getElementById("schemesContainer");

    // ---------------------------------------------------------------------------
    // DOM Elements - Modals
    // ---------------------------------------------------------------------------
    // Details Modal
    const schemeDetailsModal = document.getElementById("schemeDetailsModal");
    const detailsModalTitle = document.getElementById("detailsModalTitle");
    const detailsModalVerification = document.getElementById("detailsModalVerification");
    const detailsModalDepartment = document.getElementById("detailsModalDepartment");
    const detailsModalCategory = document.getElementById("detailsModalCategory");
    const detailsModalDescription = document.getElementById("detailsModalDescription");
    const detailsModalBenefits = document.getElementById("detailsModalBenefits");
    const detailsModalEligibility = document.getElementById("detailsModalEligibility");
    const detailsModalDocuments = document.getElementById("detailsModalDocuments");
    const detailsModalProcess = document.getElementById("detailsModalProcess");
    const detailsModalLinks = document.getElementById("detailsModalLinks");
    const closeDetailsModalBtn = document.getElementById("closeDetailsModalBtn");
    const detailsCloseBottomBtn = document.getElementById("detailsCloseBottomBtn");
    const detailsCheckEligibilityBtn = document.getElementById("detailsCheckEligibilityBtn");

    // Eligibility Modal
    const schemeEligibilityModal = document.getElementById("schemeEligibilityModal");
    const eligibilityModalTitle = document.getElementById("eligibilityModalTitle");
    const eligibilityStatusBanner = document.getElementById("eligibilityStatusBanner");
    const eligibilitySummaryText = document.getElementById("eligibilitySummaryText");
    const eligibilityMissingSection = document.getElementById("eligibilityMissingSection");
    const eligibilityMissingList = document.getElementById("eligibilityMissingList");
    const eligibilityMatchedSection = document.getElementById("eligibilityMatchedSection");
    const eligibilityMatchedList = document.getElementById("eligibilityMatchedList");
    const eligibilityFailedSection = document.getElementById("eligibilityFailedSection");
    const eligibilityFailedList = document.getElementById("eligibilityFailedList");
    const eligibilityUnknownSection = document.getElementById("eligibilityUnknownSection");
    const eligibilityUnknownList = document.getElementById("eligibilityUnknownList");
    const closeEligibilityModalBtn = document.getElementById("closeEligibilityModalBtn");
    const eligibilityCloseBottomBtn = document.getElementById("eligibilityCloseBottomBtn");

    // Anonymous On-Demand Eligibility Form Elements (Step 1 & Step 3)
    const anonEligibilitySection = document.getElementById("anonEligibilitySection");
    const wrapperAnonIncome = document.getElementById("wrapperAnonIncome");
    const labelAnonIncome = document.getElementById("labelAnonIncome");
    const anonInputIncome = document.getElementById("anonInputIncome");
    const wrapperAnonGender = document.getElementById("wrapperAnonGender");
    const anonInputGender = document.getElementById("anonInputGender");
    const wrapperAnonCaste = document.getElementById("wrapperAnonCaste");
    const anonInputCaste = document.getElementById("anonInputCaste");
    const wrapperAnonDisability = document.getElementById("wrapperAnonDisability");
    const anonInputDisability = document.getElementById("anonInputDisability");
    const wrapperAnonVulnerable = document.getElementById("wrapperAnonVulnerable");
    const anonInputVulnerable = document.getElementById("anonInputVulnerable");
    const wrapperAnonAge = document.getElementById("wrapperAnonAge");
    const anonInputAge = document.getElementById("anonInputAge");
    const btnRunAnonEvaluation = document.getElementById("btnRunAnonEvaluation");
    const btnCancelAnonEvaluation = document.getElementById("btnCancelAnonEvaluation");
    const btnTestManualCriteria = document.getElementById("btnTestManualCriteria");
    const guestNoticeBanner = document.getElementById("guestNoticeBanner");
    const welcomeSubtitle = document.getElementById("welcomeSubtitle");
    const citizenBadge = document.getElementById("citizenBadge");

    // Top Nav Secondary Auth Links
    const navLoginLink = document.getElementById("navLoginLink");
    const navSignupLink = document.getElementById("navSignupLink");
    const navGuestBadge = document.getElementById("navGuestBadge");
    const endGuestSessionBtn = document.getElementById("endGuestSessionBtn");

    // Five Interactive Hub Feature Cards (Step 2)
    const cardChat = document.getElementById("cardChat");
    const cardVoice = document.getElementById("cardVoice");
    const cardDocuments = document.getElementById("cardDocuments");
    const cardRecommendations = document.getElementById("cardRecommendations");
    const cardCatalog = document.getElementById("cardCatalog");

    // Feature Info Modal (Honest Coming Soon for AI Chat, Voice, Document AI)
    const featureInfoModal = document.getElementById("featureInfoModal");
    const featureModalTitle = document.getElementById("featureModalTitle");
    const featureModalIcon = document.getElementById("featureModalIcon");
    const featureModalName = document.getElementById("featureModalName");
    const featureModalDescription = document.getElementById("featureModalDescription");
    const closeFeatureModalBtn = document.getElementById("closeFeatureModalBtn");
    const featureCloseBottomBtn = document.getElementById("featureCloseBottomBtn");
    const featureModalExploreBtn = document.getElementById("featureModalExploreBtn");

    // Account Feature Modal (Restricted feature prompt for anonymous visitors - Step 2.1)
    const accountFeatureModal = document.getElementById("accountFeatureModal");
    const closeAccountModalBtn = document.getElementById("closeAccountModalBtn");
    const accountCloseBottomBtn = document.getElementById("accountCloseBottomBtn");

    // Text AI Chat Modal Elements (Step 4D)
    const chatModal = document.getElementById("chatModal");
    const closeChatModalBtn = document.getElementById("closeChatModalBtn");
    const chatNewBtn = document.getElementById("chatNewBtn");
    const chatModalTitle = document.getElementById("chatModalTitle");
    const chatSessionTypeSubtitle = document.getElementById("chatSessionTypeSubtitle");
    const chatSidebar = document.getElementById("chatSidebar");
    const chatHistoryList = document.getElementById("chatHistoryList");
    const chatGuestBanner = document.getElementById("chatGuestBanner");
    const chatMessagesContainer = document.getElementById("chatMessagesContainer");
    const chatInitialGreeting = document.getElementById("chatInitialGreeting");
    const chatLoadingIndicator = document.getElementById("chatLoadingIndicator");
    const chatErrorBanner = document.getElementById("chatErrorBanner");
    const chatErrorMessage = document.getElementById("chatErrorMessage");
    const chatRetryBtn = document.getElementById("chatRetryBtn");
    const chatForm = document.getElementById("chatForm");
    const chatInputText = document.getElementById("chatInputText");
    const chatSendBtn = document.getElementById("chatSendBtn");
    const chatCharCounter = document.getElementById("chatCharCounter");

    // Voice Assistant Modal Elements (Step 4E)
    const voiceModal = document.getElementById("voiceModal");
    const closeVoiceModalBtn = document.getElementById("closeVoiceModalBtn");
    const voiceCloseBottomBtn = document.getElementById("voiceCloseBottomBtn");
    const voiceNewBtn = document.getElementById("voiceNewBtn");
    const voiceLangSelect = document.getElementById("voiceLangSelect");
    const voiceCompatAlert = document.getElementById("voiceCompatAlert");
    const voiceFallbackToChatBtn = document.getElementById("voiceFallbackToChatBtn");
    const voiceMicBtn = document.getElementById("voiceMicBtn");
    const voiceStatusText = document.getElementById("voiceStatusText");
    const voiceLangHint = document.getElementById("voiceLangHint");
    const voiceTranscriptText = document.getElementById("voiceTranscriptText");
    const voiceClearBtn = document.getElementById("voiceClearBtn");
    const voiceCharCounter = document.getElementById("voiceCharCounter");
    const voiceSendBtn = document.getElementById("voiceSendBtn");
    const voiceLoadingIndicator = document.getElementById("voiceLoadingIndicator");
    const voiceErrorBanner = document.getElementById("voiceErrorBanner");
    const voiceErrorMessage = document.getElementById("voiceErrorMessage");
    const voiceRetryBtn = document.getElementById("voiceRetryBtn");
    const voiceResponseSection = document.getElementById("voiceResponseSection");
    const voiceSpeakingIndicator = document.getElementById("voiceSpeakingIndicator");
    const voiceTtsLoadingIndicator = document.getElementById("voiceTtsLoadingIndicator");
    const voicePlayBtn = document.getElementById("voicePlayBtn");
    const voiceStopSpeakingBtn = document.getElementById("voiceStopSpeakingBtn");
    const voiceReplayBtn = document.getElementById("voiceReplayBtn");
    const voiceAnswerText = document.getElementById("voiceAnswerText");
    const voicePlaybackNotice = document.getElementById("voicePlaybackNotice");
    const voicePlaybackNoticeText = document.getElementById("voicePlaybackNoticeText");
    const voiceEvidenceWarning = document.getElementById("voiceEvidenceWarning");
    const voiceCitationsSection = document.getElementById("voiceCitationsSection");
    const voiceCitationsList = document.getElementById("voiceCitationsList");
    const voiceSwitchToChatBtn = document.getElementById("voiceSwitchToChatBtn");

    // ---------------------------------------------------------------------------
    // DOM Elements - My Documents Library & Modals (Step 5.4B)
    // ---------------------------------------------------------------------------
    const navDocumentsLink = document.getElementById("navDocumentsLink");
    const documentsSection = document.getElementById("documentsSection");
    const docStatTotal = document.getElementById("docStatTotal");
    const docStatConfirmed = document.getElementById("docStatConfirmed");
    const docStatPending = document.getElementById("docStatPending");
    const docStatArchived = document.getElementById("docStatArchived");

    const docSearchInput = document.getElementById("docSearchInput");
    const docCategoryFilter = document.getElementById("docCategoryFilter");
    const docStatusFilter = document.getElementById("docStatusFilter");
    const docIncludeArchivedToggle = document.getElementById("docIncludeArchivedToggle");
    const btnResetDocFilters = document.getElementById("btnResetDocFilters");
    const documentsAlertBox = document.getElementById("documentsAlertBox");
    const documentsGrid = document.getElementById("documentsGrid");

    // Upload Modal Elements
    const documentUploadModal = document.getElementById("documentUploadModal");
    const btnOpenUploadModal = document.getElementById("btnOpenUploadModal");
    const closeDocUploadModalBtn = document.getElementById("closeDocUploadModalBtn");
    const closeDocUploadBottomBtn = document.getElementById("closeDocUploadBottomBtn");
    const docUploadForm = document.getElementById("docUploadForm");
    const docFileInput = document.getElementById("docFileInput");
    const docUploadDropzone = document.getElementById("docUploadDropzone");
    const docSelectedFileName = document.getElementById("docSelectedFileName");
    const docCategorySelect = document.getElementById("docCategorySelect");
    const docTypeSelect = document.getElementById("docTypeSelect");
    const docUploadAlert = document.getElementById("docUploadAlert");
    const docUploadProgress = document.getElementById("docUploadProgress");
    const btnStartUploadSubmit = document.getElementById("btnStartUploadSubmit");
    const docUploadFooter = document.getElementById("docUploadFooter");
    const docUploadResultSection = document.getElementById("docUploadResultSection");
    const docUploadExtractedFields = document.getElementById("docUploadExtractedFields");
    const btnUploadGoToReview = document.getElementById("btnUploadGoToReview");
    const btnUploadDone = document.getElementById("btnUploadDone");

    // Review Modal Elements
    const documentReviewModal = document.getElementById("documentReviewModal");
    const closeDocReviewModalBtn = document.getElementById("closeDocReviewModalBtn");
    const closeDocReviewBottomBtn = document.getElementById("closeDocReviewBottomBtn");
    const docReviewAlert = document.getElementById("docReviewAlert");
    const docReviewLoading = document.getElementById("docReviewLoading");
    const docReviewTableWrap = document.getElementById("docReviewTableWrap");
    const docReviewTableBody = document.getElementById("docReviewTableBody");
    const btnSaveConfirmations = document.getElementById("btnSaveConfirmations");

    // Replace Modal Elements
    const documentReplaceModal = document.getElementById("documentReplaceModal");
    const closeDocReplaceModalBtn = document.getElementById("closeDocReplaceModalBtn");
    const closeDocReplaceBottomBtn = document.getElementById("closeDocReplaceBottomBtn");
    const docReplaceForm = document.getElementById("docReplaceForm");
    const docReplaceTargetInfo = document.getElementById("docReplaceTargetInfo");
    const docReplaceFileInput = document.getElementById("docReplaceFileInput");
    const docReplaceDropzone = document.getElementById("docReplaceDropzone");
    const docReplaceSelectedFileName = document.getElementById("docReplaceSelectedFileName");
    const docReplaceAlert = document.getElementById("docReplaceAlert");
    const docReplaceProgress = document.getElementById("docReplaceProgress");
    const btnConfirmReplaceSubmit = document.getElementById("btnConfirmReplaceSubmit");

    // Delete / Archive Modal Elements
    const documentDeleteModal = document.getElementById("documentDeleteModal");
    const closeDocDeleteModalBtn = document.getElementById("closeDocDeleteModalBtn");
    const btnCancelDeleteModal = document.getElementById("btnCancelDeleteModal");
    const docDeleteTargetInfo = document.getElementById("docDeleteTargetInfo");
    const docDeletePromptText = document.getElementById("docDeletePromptText");
    const docDeleteAlert = document.getElementById("docDeleteAlert");
    const btnArchiveFromDeleteModal = document.getElementById("btnArchiveFromDeleteModal");
    const btnPermanentDeleteFromModal = document.getElementById("btnPermanentDeleteFromModal");

    // Metadata Details Modal Elements
    const documentMetadataModal = document.getElementById("documentMetadataModal");
    const closeDocMetadataModalBtn = document.getElementById("closeDocMetadataModalBtn");
    const closeDocMetadataBottomBtn = document.getElementById("closeDocMetadataBottomBtn");
    const docMetadataFieldsList = document.getElementById("docMetadataFieldsList");
    const docMetadataExtractedTableWrap = document.getElementById("docMetadataExtractedTableWrap");
    const btnMetadataDownloadBtn = document.getElementById("btnMetadataDownloadBtn");
    const btnMetadataReviewBtn = document.getElementById("btnMetadataReviewBtn");

    // Document Library State Variables
    let userDocuments = [];
    let currentReviewDocId = null;
    let currentReplaceDocId = null;
    let currentDeleteDoc = null;
    let currentMetadataDocId = null;
    let isUploadingDocument = false;
    let isReplacingDocument = false;

    // ---------------------------------------------------------------------------
    // DOM Elements & State - Scholarship Application Workspace (Step 5.5A)
    // ---------------------------------------------------------------------------
    const navApplicationsLink = document.getElementById("navApplicationsLink");
    const applicationsSection = document.getElementById("applicationsSection");
    const applicationsAlertBox = document.getElementById("applicationsAlertBox");
    const applicationsGrid = document.getElementById("applicationsGrid");

    const applicationWorkspaceModal = document.getElementById("applicationWorkspaceModal");
    const closeAppWorkspaceModalBtn = document.getElementById("closeAppWorkspaceModalBtn");
    const appWorkspaceStatusBadge = document.getElementById("appWorkspaceStatusBadge");
    const appWorkspaceSchemeName = document.getElementById("appWorkspaceSchemeName");
    const appWorkspaceProgressPct = document.getElementById("appWorkspaceProgressPct");
    const appWorkspaceYearBadge = document.getElementById("appWorkspaceYearBadge");
    const appWorkspaceProgressBar = document.getElementById("appWorkspaceProgressBar");
    const appWorkspaceTabsNav = document.getElementById("appWorkspaceTabsNav");
    const appWorkspaceSectionTitle = document.getElementById("appWorkspaceSectionTitle");
    const appWorkspaceSectionDesc = document.getElementById("appWorkspaceSectionDesc");
    const appWorkspaceForm = document.getElementById("appWorkspaceForm");
    const appWorkspaceFieldsContainer = document.getElementById("appWorkspaceFieldsContainer");
    const appWorkspaceDocsView = document.getElementById("appWorkspaceDocsView");
    const appWorkspaceDocsList = document.getElementById("appWorkspaceDocsList");
    const appWorkspaceReviewPortalBox = document.getElementById("appWorkspaceReviewPortalBox");
    const appWorkspacePortalMeta = document.getElementById("appWorkspacePortalMeta");
    const appWorkspaceAlert = document.getElementById("appWorkspaceAlert");
    const btnWorkspacePrev = document.getElementById("btnWorkspacePrev");
    const btnWorkspaceSave = document.getElementById("btnWorkspaceSave");
    const appWorkspaceSaveStatus = document.getElementById("appWorkspaceSaveStatus");
    const btnWorkspaceNext = document.getElementById("btnWorkspaceNext");
    const btnWorkspaceContinuePortal = document.getElementById("btnWorkspaceContinuePortal");

    const btnAppWorkspaceAutofillPreview = document.getElementById("btnAppWorkspaceAutofillPreview");
    const btnAppWorkspaceAutofillApply = document.getElementById("btnAppWorkspaceAutofillApply");
    const appWorkspaceAutofillDrawer = document.getElementById("appWorkspaceAutofillDrawer");
    const btnCloseAutofillDrawer = document.getElementById("btnCloseAutofillDrawer");
    const appWorkspaceAutofillSummaryBadges = document.getElementById("appWorkspaceAutofillSummaryBadges");
    const appWorkspaceAutofillList = document.getElementById("appWorkspaceAutofillList");

    const externalPortalModal = document.getElementById("externalPortalModal");
    const closeExtPortalModalBtn = document.getElementById("closeExtPortalModalBtn");
    const extPortalTargetUrlWrap = document.getElementById("extPortalTargetUrlWrap");
    const btnCancelExtPortal = document.getElementById("btnCancelExtPortal");
    const btnConfirmExtPortal = document.getElementById("btnConfirmExtPortal");

    const deleteDraftModal = document.getElementById("deleteDraftModal");
    const closeDeleteDraftModalBtn = document.getElementById("closeDeleteDraftModalBtn");
    const btnCancelDeleteDraft = document.getElementById("btnCancelDeleteDraft");
    const btnConfirmDeleteDraft = document.getElementById("btnConfirmDeleteDraft");

    const detailsApplyNowBtn = document.getElementById("detailsApplyNowBtn");

    // Step 5.5C: Extension Integration Elements
    const extensionStatusCard = document.getElementById("extensionStatusCard");
    const extensionStateBadge = document.getElementById("extensionStateBadge");
    const extensionStateDesc = document.getElementById("extensionStateDesc");
    const btnExtensionGuide = document.getElementById("btnExtensionGuide");
    const btnConnectExtension = document.getElementById("btnConnectExtension");
    const extensionGuideModal = document.getElementById("extensionGuideModal");
    const closeExtGuideModalBtn = document.getElementById("closeExtGuideModalBtn");
    const btnCloseExtGuide = document.getElementById("btnCloseExtGuide");

    let extensionState = "NOT_INSTALLED";
    let userApplicationDrafts = [];
    let currentWorkspaceDraft = null;
    let activeWorkspaceSectionIndex = 0;
    let targetDraftIdToDelete = null;
    let pendingExternalPortalUrl = null;

    // Chat & Voice State Variables (Shared context between Voice and Text)
    let activeChatConversationId = null;
    let isSendingChatMessage = false;
    let lastFailedChatPrompt = "";
    let speechRecognitionInstance = null;
    let isListening = false;
    let isSendingVoiceMessage = false;
    let lastSpokenAnswerText = "";
    let lastFailedVoicePrompt = "";
    let lastLoadedRecommendationsData = null;
    let lastLoadedCatalogData = null;
    let currentCitizenProfile = null;
    let userManuallyChangedVoiceLang = false;
    const t = (k, p, d) => (typeof I18n !== 'undefined' ? I18n.t(k, p, d) : (d || k));

    // State Variables
    let isGuestMode = false;
    let guestContextData = {};
    let activeTab = "recommendations"; // "recommendations" or "catalog"
    let currentModalSchemeId = null;
    let modalTriggerElement = null; // Stores element that opened modal for focus restoration

    function formatCurrency(amount) {
        if (amount === null || amount === undefined || isNaN(amount)) return "--";
        return "₹" + Number(amount).toLocaleString("en-IN");
    }

    function findLoadedScheme(schemeId) {
        if (!schemeId) return null;
        if (lastLoadedCatalogData && Array.isArray(lastLoadedCatalogData)) {
            const found = lastLoadedCatalogData.find(s => (s.scheme_id || s.id) === schemeId);
            if (found) return found;
        }
        if (lastLoadedRecommendationsData) {
            const recs = (lastLoadedRecommendationsData.preliminary_matches || []).concat(lastLoadedRecommendationsData.rule_mismatches || []);
            const foundRec = recs.find(item => item && item.scheme && (item.scheme.scheme_id || item.scheme.id) === schemeId);
            if (foundRec) return foundRec.scheme;
        }
        return null;
    }

    function showAlert(message, type = "error") {
        if (!alertBox) return;
        alertBox.className = `alert-box visible ${type}`;
        alertBox.textContent = message;
    }

    function showSchemesAlert(message, type = "error") {
        if (!schemesAlertBox) return;
        schemesAlertBox.className = `alert-box visible ${type}`;
        schemesAlertBox.textContent = message;
    }

    function clearSchemesAlert() {
        if (!schemesAlertBox) return;
        schemesAlertBox.className = "alert-box";
        schemesAlertBox.textContent = "";
    }

    // Attach logout event for registered user
    if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
            logoutBtn.disabled = true;
            logoutBtn.textContent = t("nav.loggingOut", {}, "Logging Out...");
            await logoutCitizen();
        });
    }

    // Attach end guest session event for guest user
    if (endGuestSessionBtn) {
        endGuestSessionBtn.addEventListener("click", async () => {
            endGuestSessionBtn.disabled = true;
            endGuestSessionBtn.textContent = t("nav.endingGuestSession", {}, "Ending Guest Session...");
            await logoutCitizen();
        });
    }

    // ---------------------------------------------------------------------------
    // Modal Helpers & Accessibility (Focus Trapping & Restoration)
    // ---------------------------------------------------------------------------
    function getFocusableElements(container) {
        if (!container) return [];
        return Array.from(
            container.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
        ).filter(el => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement);
    }

    function openModal(modalEl, triggerEl = null) {
        if (!modalEl) return;
        if (triggerEl) {
            modalTriggerElement = triggerEl;
        } else if (document.activeElement && document.activeElement !== document.body) {
            modalTriggerElement = document.activeElement;
        }

        modalEl.classList.add("active");
        document.body.style.overflow = "hidden";

        // Initial focus placement on the first interactive element inside modal
        const focusable = getFocusableElements(modalEl);
        if (focusable.length > 0) {
            setTimeout(() => focusable[0].focus(), 50);
        }
    }

    function closeModal(modalEl) {
        if (!modalEl) return;
        modalEl.classList.remove("active");
        document.body.style.overflow = "";

        // Restore focus to original trigger element when all modals are closed
        const remainingOpenModal = document.querySelector(".modal-overlay.active");
        if (!remainingOpenModal && modalTriggerElement && typeof modalTriggerElement.focus === "function") {
            modalTriggerElement.focus();
            modalTriggerElement = null;
        }
    }

    function closeAllModals() {
        closeModal(schemeDetailsModal);
        closeModal(schemeEligibilityModal);
        closeModal(featureInfoModal);
        closeModal(accountFeatureModal);
        closeModal(chatModal);
        closeModal(voiceModal);
        closeModal(documentUploadModal);
        closeModal(documentReviewModal);
        closeModal(documentReplaceModal);
        closeModal(documentDeleteModal);
        closeModal(documentMetadataModal);
        stopVoiceRecognition();
        stopSpeaking();
    }

    // Close buttons & overlay click handlers
    [closeDetailsModalBtn, detailsCloseBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(schemeDetailsModal));
    });

    [closeEligibilityModalBtn, eligibilityCloseBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(schemeEligibilityModal));
    });

    [closeFeatureModalBtn, featureCloseBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(featureInfoModal));
    });

    [closeAccountModalBtn, accountCloseBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(accountFeatureModal));
    });

    [closeChatModalBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(chatModal));
    });

    [closeVoiceModalBtn, voiceCloseBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => {
            stopVoiceRecognition();
            stopSpeaking();
            closeModal(voiceModal);
        });
    });

    [closeDocUploadModalBtn, closeDocUploadBottomBtn, btnUploadDone].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(documentUploadModal));
    });

    [closeDocReviewModalBtn, closeDocReviewBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(documentReviewModal));
    });

    [closeDocReplaceModalBtn, closeDocReplaceBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(documentReplaceModal));
    });

    [closeDocDeleteModalBtn, btnCancelDeleteModal].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(documentDeleteModal));
    });

    [closeDocMetadataModalBtn, closeDocMetadataBottomBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => closeModal(documentMetadataModal));
    });

    [schemeDetailsModal, schemeEligibilityModal, featureInfoModal, accountFeatureModal, chatModal, voiceModal, documentUploadModal, documentReviewModal, documentReplaceModal, documentDeleteModal, documentMetadataModal].forEach((overlay) => {
        if (overlay) {
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) {
                    stopVoiceRecognition();
                    stopSpeaking();
                    closeModal(overlay);
                }
            });
        }
    });

    // Keyboard handlers: ESC to close, TAB focus trapping
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeAllModals();
            return;
        }

        if (e.key === "Tab") {
            const activeModal = document.querySelector(".modal-overlay.active");
            if (!activeModal) return;

            const focusable = getFocusableElements(activeModal);
            if (focusable.length === 0) {
                e.preventDefault();
                return;
            }

            const firstElement = focusable[0];
            const lastElement = focusable[focusable.length - 1];

            if (e.shiftKey) {
                if (document.activeElement === firstElement || !activeModal.contains(document.activeElement)) {
                    e.preventDefault();
                    lastElement.focus();
                }
            } else {
                if (document.activeElement === lastElement || !activeModal.contains(document.activeElement)) {
                    e.preventDefault();
                    firstElement.focus();
                }
            }
        }
    });

    // Transition from details modal to eligibility modal
    if (detailsCheckEligibilityBtn) {
        detailsCheckEligibilityBtn.addEventListener("click", () => {
            if (currentModalSchemeId) {
                const preservedTrigger = modalTriggerElement;
                closeModal(schemeDetailsModal);
                openDetailedEligibility(
                    currentModalSchemeId,
                    applicationTypeSelect ? applicationTypeSelect.value : "FRESH",
                    preservedTrigger
                );
            }
        });
    }

    if (detailsApplyNowBtn) {
        detailsApplyNowBtn.addEventListener("click", () => {
            if (detailsApplyNowBtn.disabled || detailsApplyNowBtn.getAttribute("data-closed") === "true") {
                showSchemesAlert("Applications for this scheme are currently closed.", "warning");
                return;
            }
            if (currentModalSchemeId) {
                const preservedTrigger = modalTriggerElement;
                closeModal(schemeDetailsModal);
                handleApplyNowClick(currentModalSchemeId, preservedTrigger);
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Five Interactive Hub Feature Cards Handlers (Step 2)
    // ---------------------------------------------------------------------------
    function openFeatureInfoModal(featureName, featureDesc, featureIcon, triggerEl = null) {
        if (!featureInfoModal) return;
        if (featureModalTitle) featureModalTitle.textContent = `${featureName} — Status`;
        if (featureModalName) featureModalName.textContent = featureName;
        if (featureModalDescription) featureModalDescription.textContent = featureDesc;
        if (featureModalIcon) featureModalIcon.textContent = featureIcon;
        openModal(featureInfoModal, triggerEl);
    }

    if (cardChat) {
        cardChat.addEventListener("click", () => {
            openChatModal(cardChat);
        });
        cardChat.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                cardChat.click();
            }
        });
    }

    if (cardVoice) {
        cardVoice.addEventListener("click", () => {
            openVoiceModal(cardVoice);
        });
        cardVoice.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                cardVoice.click();
            }
        });
    }

    if (cardDocuments) {
        cardDocuments.addEventListener("click", () => {
            if (isGuestMode) {
                return;
            }
            window.location.href = "my-documents.html";
        });
        cardDocuments.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                if (!isGuestMode) {
                    cardDocuments.click();
                }
            }
        });
    }

    if (navDocumentsLink) {
        navDocumentsLink.addEventListener("click", (e) => {
            if (!isGuestMode) {
                e.preventDefault();
                window.location.href = "my-documents.html";
            }
        });
    }

    if (cardRecommendations) {
        cardRecommendations.addEventListener("click", () => {
            if (isGuestMode) {
                // Step 4D.2: Card is hidden in guest mode. Fallback safeguard:
                // openModal(accountFeatureModal, cardRecommendations);
                return;
            } else {
                switchTab("recommendations");
                const schemesSection = document.getElementById("schemes");
                if (schemesSection) {
                    schemesSection.scrollIntoView({ behavior: "smooth" });
                }
            }
        });
        cardRecommendations.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                cardRecommendations.click();
            }
        });
    }

    if (cardCatalog) {
        cardCatalog.addEventListener("click", () => {
            switchTab("catalog");
            const schemesSection = document.getElementById("schemes");
            if (schemesSection) {
                schemesSection.scrollIntoView({ behavior: "smooth" });
            }
            if (schemeSearchInput) {
                setTimeout(() => schemeSearchInput.focus(), 300);
            }
        });
        cardCatalog.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                cardCatalog.click();
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Step 4D: Text AI Chat Controller & Rendering Logic
    // ---------------------------------------------------------------------------

    function scrollChatToBottom() {
        if (chatMessagesContainer) {
            chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
        }
    }

    function clearChatError() {
        if (chatErrorBanner) {
            chatErrorBanner.style.display = "none";
        }
        if (chatErrorMessage) {
            chatErrorMessage.textContent = "";
        }
    }

    function showChatError(message, retryable = true) {
        if (!chatErrorBanner || !chatErrorMessage) return;
        chatErrorMessage.textContent = message;
        if (chatRetryBtn) {
            chatRetryBtn.style.display = retryable ? "inline-block" : "none";
        }
        chatErrorBanner.style.display = "flex";
        scrollChatToBottom();
    }

    function resetChatToGreeting() {
        if (!chatMessagesContainer) return;
        chatMessagesContainer.innerHTML = "";
        if (chatInitialGreeting) {
            chatMessagesContainer.appendChild(chatInitialGreeting.cloneNode(true));
        }
        clearChatError();
        scrollChatToBottom();
    }

    function startNewChat() {
        activeChatConversationId = null;
        resetChatToGreeting();
        if (chatHistoryList) {
            const activeItems = chatHistoryList.querySelectorAll(".chat-history-item.active");
            activeItems.forEach(el => el.classList.remove("active"));
        }
        if (chatInputText) {
            chatInputText.value = "";
            chatInputText.focus();
        }
        if (chatCharCounter) {
            chatCharCounter.textContent = "0 / 2000";
        }
        clearChatError();
    }

    async function loadChatHistoryList() {
        if (isGuestMode || !chatHistoryList) return;

        chatHistoryList.innerHTML = `<div class="chat-history-empty" style="color: #64748b;">${t("chat.loadingHistory", {}, "Loading saved conversations...")}</div>`;

        const res = await fetchChatConversations();
        if (!res.ok) {
            chatHistoryList.innerHTML = `<div class="chat-history-empty">${t("chat.loadHistoryError", {}, "Unable to load conversations.")}</div>`;
            return;
        }

        const convs = (res.data && res.data.conversations) || [];
        chatHistoryList.innerHTML = "";

        if (convs.length === 0) {
            chatHistoryList.innerHTML = `<div class="chat-history-empty">${t("chat.emptyHistory", {}, "No previous conversations saved yet. Start a new chat below!")}</div>`;
            return;
        }

        convs.forEach(conv => {
            const item = document.createElement("div");
            item.className = "chat-history-item" + (conv.id === activeChatConversationId ? " active" : "");
            item.setAttribute("role", "listitem");
            item.dataset.convId = conv.id;

            const infoDiv = document.createElement("div");
            infoDiv.className = "chat-history-info";

            const titleDiv = document.createElement("div");
            titleDiv.className = "chat-history-title";
            titleDiv.textContent = conv.title || "Conversation";

            const metaDiv = document.createElement("div");
            metaDiv.className = "chat-history-meta";
            let formattedDate = "";
            try {
                const dt = new Date(conv.updated_at);
                formattedDate = dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
            } catch {
                formattedDate = "";
            }
            metaDiv.textContent = `${formattedDate} • ${conv.message_count || 0} messages`;

            infoDiv.appendChild(titleDiv);
            infoDiv.appendChild(metaDiv);
            item.appendChild(infoDiv);

            const delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className = "chat-history-delete-btn";
            delBtn.title = "Delete conversation";
            delBtn.setAttribute("aria-label", `Delete conversation: ${conv.title || conv.id}`);
            delBtn.textContent = "🗑️";

            delBtn.addEventListener("click", async (e) => {
                e.stopPropagation();
                if (!confirm(`Are you sure you want to delete "${conv.title || "this conversation"}"?`)) {
                    return;
                }
                const delRes = await deleteChatConversation(conv.id);
                if (delRes.ok) {
                    if (activeChatConversationId === conv.id) {
                        startNewChat();
                    }
                    loadChatHistoryList();
                } else {
                    showChatError(delRes.error || "Failed to delete conversation.", false);
                }
            });

            item.appendChild(delBtn);

            item.addEventListener("click", () => {
                openSavedConversation(conv.id);
            });

            chatHistoryList.appendChild(item);
        });
    }

    async function openSavedConversation(conversationId) {
        if (!conversationId) return;
        activeChatConversationId = conversationId;

        // Highlight selected item in sidebar
        if (chatHistoryList) {
            chatHistoryList.querySelectorAll(".chat-history-item").forEach(el => {
                if (el.dataset.convId === conversationId) {
                    el.classList.add("active");
                } else {
                    el.classList.remove("active");
                }
            });
        }

        clearChatError();
        if (chatLoadingIndicator) chatLoadingIndicator.style.display = "flex";

        const res = await fetchChatConversationDetails(conversationId);
        if (chatLoadingIndicator) chatLoadingIndicator.style.display = "none";

        if (!res.ok) {
            showChatError(res.error || "Could not load conversation history.", false);
            return;
        }

        if (chatMessagesContainer) {
            chatMessagesContainer.innerHTML = "";
        }

        const messages = (res.data && res.data.messages) || [];
        messages.forEach(msg => {
            appendChatMessage(
                msg.role,
                msg.content,
                msg.citations || [],
                null,
                true,
                {}
            );
        });

        scrollChatToBottom();
        if (chatInputText) chatInputText.focus();
    }

    function appendChatMessage(
        role,
        content,
        citations = [],
        disclaimer = null,
        evidenceSufficient = true,
        citationValidation = {}
    ) {
        if (!chatMessagesContainer) return;

        const isUser = role === "user";
        const msgWrapper = document.createElement("div");
        msgWrapper.className = `chat-message chat-message-${isUser ? "user" : "assistant"}`;

        const avatar = document.createElement("div");
        avatar.className = "chat-message-avatar";
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = isUser ? "👤" : "🏛️";
        msgWrapper.appendChild(avatar);

        const body = document.createElement("div");
        body.className = "chat-message-body";

        const author = document.createElement("div");
        author.className = "chat-message-author";
        author.textContent = isUser ? "You" : "SahayAI Scheme Assistant";
        body.appendChild(author);

        const textDiv = document.createElement("div");
        textDiv.className = "chat-message-text";
        if (isUser) {
            textDiv.textContent = content || "";
        } else {
            textDiv.innerHTML = renderSafeMarkdown(content || "");
        }
        body.appendChild(textDiv);

        if (!isUser) {
            // Insufficient evidence alert
            if (evidenceSufficient === false) {
                const warnBox = document.createElement("div");
                warnBox.className = "chat-evidence-warning";
                warnBox.textContent = t("chat.evidenceWarning", {}, "⚠️ Preliminary notice: Limited or inconclusive official documentation found for this specific query. Please verify details on the official national portal.");
                body.appendChild(warnBox);
            }

            // Citation validation warning if unverified or fabricated citations detected
            if (citationValidation && citationValidation.is_valid === false) {
                const warnBox = document.createElement("div");
                warnBox.className = "chat-citation-warning";
                warnBox.textContent = "⚠️ Citation alert: Citations could not be mapped to verified official source chunks.";
                body.appendChild(warnBox);
            }

            // Citations presentation
            if (Array.isArray(citations) && citations.length > 0) {
                const citationsSection = document.createElement("div");
                citationsSection.className = "chat-citations-section";

                const citHeader = document.createElement("div");
                citHeader.className = "chat-citations-title";
                citHeader.textContent = t("chat.citationsHeader", {}, "Official Evidence & Sources:");
                citationsSection.appendChild(citHeader);

                citations.forEach((cit, idx) => {
                    const citItem = document.createElement("div");
                    citItem.className = "chat-citation-item";

                    const badge = document.createElement("span");
                    badge.className = "chat-citation-badge";
                    badge.textContent = `[S${idx + 1}] ${cit.authority || "Official"}`;
                    citItem.appendChild(badge);

                    const docLabel = document.createTextNode(
                        ` ${cit.document_name || cit.scheme_id || "Guidelines"}` +
                        (cit.page_number ? ` (Page ${cit.page_number})` : "")
                    );
                    citItem.appendChild(docLabel);

                    // Strictly safe URL check: only render link if protocol is http/https
                    if (cit.source_url && isSafeUrl(cit.source_url)) {
                        const link = document.createElement("a");
                        link.href = cit.source_url;
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        link.className = "chat-citation-link";
                        link.textContent = t("chat.viewSource", {}, "[View Source Document]");
                        citItem.appendChild(document.createTextNode(" "));
                        citItem.appendChild(link);
                    }

                    citationsSection.appendChild(citItem);
                });

                body.appendChild(citationsSection);
            }

            // Official government disclaimer (only show when a valid disclaimer is present)
            if (disclaimer && typeof disclaimer === "string" && disclaimer.trim().length > 0) {
                const discBox = document.createElement("div");
                discBox.className = "chat-disclaimer-box";
                discBox.textContent = t("chat.disclaimer", {}, disclaimer);
                body.appendChild(discBox);
            }
        }

        msgWrapper.appendChild(body);
        chatMessagesContainer.appendChild(msgWrapper);
        scrollChatToBottom();
    }

    async function handleSendMessage() {
        if (isSendingChatMessage || !chatInputText) return;

        const message = chatInputText.value.trim();
        if (!message) return;

        isSendingChatMessage = true;
        lastFailedChatPrompt = message;
        clearChatError();

        // Disable input controls during flight
        if (chatSendBtn) chatSendBtn.disabled = true;
        chatInputText.disabled = true;

        // Render user message immediately
        appendChatMessage("user", message);

        // Reset input field
        chatInputText.value = "";
        if (chatCharCounter) chatCharCounter.textContent = "0 / 2000";

        // Show loading indicator
        if (chatLoadingIndicator) chatLoadingIndicator.style.display = "flex";
        scrollChatToBottom();

        try {
            const activeChatLang = (typeof I18n !== 'undefined' ? I18n.getLanguage() : null);
            const res = await sendChatMessage(message, activeChatConversationId, activeChatLang);

            if (chatLoadingIndicator) chatLoadingIndicator.style.display = "none";

            if (!res.ok) {
                if (res.status === 401) {
                    showChatError("Your session has expired or is invalid. Please log in or refresh your guest session.", false);
                } else {
                    showChatError(res.error || "An error occurred while generating scheme guidance. Please try again.", true);
                }
                return;
            }

            const data = res.data;
            if (!isGuestMode && !activeChatConversationId && data.conversation_id) {
                activeChatConversationId = data.conversation_id;
                loadChatHistoryList();
            }

            appendChatMessage(
                "assistant",
                data.content,
                data.citations || [],
                data.disclaimer,
                data.evidence_sufficient,
                data.citation_validation
            );

        } catch (err) {
            console.error("Chat message error:", err);
            if (chatLoadingIndicator) chatLoadingIndicator.style.display = "none";
            showChatError("Network connection error. Please verify your connection and try again.", true);
        } finally {
            isSendingChatMessage = false;
            if (chatSendBtn) chatSendBtn.disabled = false;
            if (chatInputText) {
                chatInputText.disabled = false;
                chatInputText.focus();
            }
        }
    }

    function openChatModal(triggerEl = null) {
        if (!chatModal) return;

        openModal(chatModal, triggerEl);

        if (isGuestMode) {
            if (chatGuestBanner) chatGuestBanner.style.display = "block";
            if (chatSidebar) chatSidebar.style.display = "none";
            if (chatSessionTypeSubtitle) {
                chatSessionTypeSubtitle.textContent = "Guest Mode • Scheme Assistance";
            }
        } else {
            if (chatGuestBanner) chatGuestBanner.style.display = "none";
            if (chatSidebar) chatSidebar.style.display = "flex";
            if (chatSessionTypeSubtitle) {
                chatSessionTypeSubtitle.textContent = "Saved Conversations • Scheme Assistance";
            }
            loadChatHistoryList();
        }

        clearChatError();
        scrollChatToBottom();
        if (chatInputText) chatInputText.focus();
    }

    // Attach Chat Event Listeners
    if (chatNewBtn) {
        chatNewBtn.addEventListener("click", () => {
            startNewChat();
        });
    }

    if (chatRetryBtn) {
        chatRetryBtn.addEventListener("click", () => {
            if (lastFailedChatPrompt && chatInputText) {
                chatInputText.value = lastFailedChatPrompt;
                clearChatError();
                handleSendMessage();
            }
        });
    }

    if (chatForm) {
        chatForm.addEventListener("submit", (e) => {
            e.preventDefault();
            handleSendMessage();
        });
    }

    if (chatInputText) {
        chatInputText.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
            }
        });

        chatInputText.addEventListener("input", () => {
            if (chatCharCounter) {
                chatCharCounter.textContent = `${chatInputText.value.length} / 2000`;
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Step 4E: Voice Assistant Controller & Speech Logic
    // ---------------------------------------------------------------------------

    /**
     * Cleans up assistant response text for pleasant, natural speech synthesis.
     * Strips citation markers [S1], markdown links, asterisks, bullets, and URLs.
     */
    function sanitizeTextForSpeech(rawText) {
        if (!rawText || typeof rawText !== "string") return "";
        return rawText
            .replace(/\[S\d+\]/g, "")
            .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
            .replace(/https?:\/\/\S+/g, "")
            .replace(/[*_#`~•]/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    /**
     * Initializes native Web Speech Recognition instance if supported by the browser.
     * Handles permissions, recognition events, error states, and live transcription.
     */
    function initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!SpeechRecognition) {
            if (voiceCompatAlert) voiceCompatAlert.style.display = "flex";
            if (voiceStatusText) {
                voiceStatusText.textContent = "Speech recognition is not supported in this browser. Use Text Chat or type below.";
            }
            if (voiceMicBtn) {
                voiceMicBtn.disabled = true;
                voiceMicBtn.style.opacity = "0.5";
                voiceMicBtn.style.cursor = "not-allowed";
                voiceMicBtn.title = "Speech recognition not supported in this browser";
            }
            return null;
        }

        if (voiceCompatAlert) voiceCompatAlert.style.display = "none";
        if (voiceMicBtn) {
            voiceMicBtn.disabled = false;
            voiceMicBtn.style.opacity = "1";
            voiceMicBtn.style.cursor = "pointer";
            voiceMicBtn.title = "Click to start speaking";
        }

        if (speechRecognitionInstance) {
            return speechRecognitionInstance;
        }

        try {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = true;
            recognition.maxAlternatives = 1;
            recognition.lang = voiceLangSelect ? voiceLangSelect.value : "en-IN";

            recognition.onstart = () => {
                isListening = true;
                stopSpeaking();
                clearVoiceError();
                if (voiceMicBtn) voiceMicBtn.classList.add("listening");
                if (voiceStatusText) voiceStatusText.textContent = "Listening... Speak your question now.";
            };

            recognition.onresult = (event) => {
                let interimTranscript = "";
                let finalTranscript = "";

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                const capturedText = finalTranscript || interimTranscript;
                if (capturedText && voiceTranscriptText) {
                    voiceTranscriptText.value = capturedText;
                    updateVoiceCharCounter();
                    if (voiceSendBtn) voiceSendBtn.disabled = false;
                }
            };

            recognition.onerror = (event) => {
                isListening = false;
                if (voiceMicBtn) voiceMicBtn.classList.remove("listening");

                const err = event.error;
                let userFriendlyError = "Speech recognition error. You can edit or type your question below.";

                if (err === "not-allowed" || err === "service-not-allowed") {
                    userFriendlyError = "Microphone access was denied. Please allow microphone permissions in your browser to speak.";
                } else if (err === "no-speech") {
                    userFriendlyError = "No speech was detected. Click the microphone to try again.";
                } else if (err === "network") {
                    userFriendlyError = "Network error during speech recognition. Please verify your connection.";
                } else if (err === "audio-capture") {
                    userFriendlyError = "No microphone was found. Please ensure a microphone is connected.";
                }

                if (voiceStatusText) voiceStatusText.textContent = userFriendlyError;
                showVoiceError(userFriendlyError, false);
            };

            recognition.onend = () => {
                isListening = false;
                if (voiceMicBtn) voiceMicBtn.classList.remove("listening");
                if (voiceTranscriptText && voiceTranscriptText.value.trim().length > 0) {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = "Speech captured! Review your question, edit if needed, and click 'Ask SahayAI'.";
                    }
                } else {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = "Click the microphone to start speaking.";
                    }
                }
            };

            speechRecognitionInstance = recognition;
            return speechRecognitionInstance;

        } catch (err) {
            console.error("Speech recognition initialization error:", err);
            return null;
        }
    }

    function toggleVoiceListening() {
        clearVoiceError();
        stopSpeaking();

        const recognition = initSpeechRecognition();
        if (!recognition) return;

        if (isListening) {
            stopVoiceRecognition();
        } else {
            try {
                recognition.lang = voiceLangSelect ? voiceLangSelect.value : "en-IN";
                recognition.start();
            } catch (err) {
                console.warn("Recognition start failed or already active:", err);
            }
        }
    }

    function stopVoiceRecognition() {
        if (speechRecognitionInstance && isListening) {
            try {
                speechRecognitionInstance.stop();
            } catch (err) {
                console.warn("Recognition stop error:", err);
            }
        }
        isListening = false;
        if (voiceMicBtn) voiceMicBtn.classList.remove("listening");
    }

    // -----------------------------------------------------------------------
    // Text-to-Speech Engine with Explicit Locale & Asynchronous Voice Discovery
    // -----------------------------------------------------------------------
    let cachedBrowserVoices = [];
    let lastSpokenAnswerLang = "en-IN";

    function loadBrowserVoices() {
        if (!("speechSynthesis" in window)) return [];
        try {
            const vList = window.speechSynthesis.getVoices();
            if (vList && vList.length > 0) {
                cachedBrowserVoices = vList;
            }
        } catch (e) {
            console.warn("Unable to get browser voices:", e);
        }
        return cachedBrowserVoices;
    }

    if (typeof window !== "undefined" && "speechSynthesis" in window) {
        loadBrowserVoices();
        window.speechSynthesis.onvoiceschanged = () => {
            loadBrowserVoices();
        };
    }

    /**
     * Finds a compatible voice for the requested locale without silent fallback to English for Indic languages.
     * @param {string} targetLang - e.g. "te-IN", "hi-IN", "en-IN"
     * @returns {SpeechSynthesisVoice|null}
     */
    function findCompatibleVoice(targetLang) {
        const voices = loadBrowserVoices();
        if (!voices || voices.length === 0) {
            return null;
        }

        const normalizedTarget = (targetLang || "en-IN").toLowerCase().replace("_", "-");
        const prefix = normalizedTarget.split("-")[0]; // "te", "hi", "en"

        // 1. Exact locale match (e.g. "te-in")
        let matched = voices.find(v => v.lang && v.lang.toLowerCase().replace("_", "-") === normalizedTarget);
        if (matched) return matched;

        // 2. Language prefix match (e.g. "te", "te-in", "te_in")
        matched = voices.find(v => v.lang && v.lang.toLowerCase().replace("_", "-").startsWith(prefix));
        if (matched) return matched;

        // 3. Name-based match containing language keyword
        const langNames = { "te": "telugu", "hi": "hindi", "en": "english" };
        const keyword = langNames[prefix];
        if (keyword) {
            matched = voices.find(v => v.name && v.name.toLowerCase().includes(keyword));
            if (matched) return matched;
        }

        // 4. For English ONLY: allow other English regional voices (e.g. en-US, en-GB, en-AU)
        if (prefix === "en") {
            matched = voices.find(v => v.lang && v.lang.toLowerCase().startsWith("en"));
            if (matched) return matched;
        }

        // STRICT: Never fall back to an English voice for Telugu or Hindi!
        return null;
    }

    let currentAudioElement = null;
    let lastAudioBlobUrl = null;
    let isTtsGenerating = false;

    /**
     * Pre-unlocks audio playback during synchronous user interaction (click/touch).
     * Prevents modern browser Autoplay policies from rejecting subsequent async Audio.play() calls.
     */
    function preUnlockAudio() {
        if (!currentAudioElement) {
            currentAudioElement = new Audio();
        }
        try {
            // Prime audio element with a tiny silent WAV frame inside direct user gesture
            currentAudioElement.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
            const p = currentAudioElement.play();
            if (p !== undefined) {
                p.catch(() => {});
            }
        } catch (e) {
            console.debug("Audio pre-unlock:", e);
        }
    }

    /**
     * Checks whether browser or backend TTS provides audio synthesis for target locale.
     * With SahayAI Phase 2 TTS integration, English, Telugu, and Hindi are fully supported.
     * @param {string} targetLang - e.g. "te-IN", "hi-IN", "en-IN"
     * @returns {boolean}
     */
    function isVoicePlaybackAvailable(targetLang) {
        const normalized = (targetLang || "en-IN").toLowerCase().replace("_", "-");
        if (normalized.startsWith("te") || normalized.startsWith("hi") || normalized.startsWith("en")) {
            return true;
        }
        if (!("speechSynthesis" in window)) return false;
        return Boolean(findCompatibleVoice(targetLang));
    }

    /**
     * Synthesizes audio via backend TTS fallback when native browser voice is absent.
     * Used for Telugu (which desktop browsers do not bundle) and Hindi when device voice is missing.
     */
    async function speakWithBackendTts(cleanText, normalizedLang, langName) {
        if (isTtsGenerating) return { success: false, spoken: false, reason: "already_generating" };
        isTtsGenerating = true;

        // Reset any playing audio
        if (currentAudioElement) {
            try { currentAudioElement.pause(); currentAudioElement.currentTime = 0; } catch {}
        }
        if ("speechSynthesis" in window) {
            try { window.speechSynthesis.cancel(); } catch {}
        }

        // Show generating indicator and update status
        if (voiceTtsLoadingIndicator) voiceTtsLoadingIndicator.style.display = "inline-flex";
        if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "none";
        if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "none";
        if (voicePlayBtn) voicePlayBtn.style.display = "none";
        if (voiceReplayBtn) {
            voiceReplayBtn.disabled = true;
            voiceReplayBtn.style.opacity = "0.5";
            voiceReplayBtn.style.cursor = "wait";
        }
        if (voiceStatusText) {
            voiceStatusText.textContent = t("voice.generatingAudio", { lang: langName }, `Generating ${langName} audio...`);
        }

        try {
            const res = await synthesizeSpeechAudio(cleanText, normalizedLang);
            if (voiceTtsLoadingIndicator) voiceTtsLoadingIndicator.style.display = "none";
            isTtsGenerating = false;

            if (!res.ok || !res.blob) {
                console.warn("Backend TTS generation failed:", res.error);
                const fallbackMsg = t("voice.playbackUnavailable", { lang: langName }, `${langName} voice playback is temporarily unavailable. The complete text response and official citations are displayed below.`);
                if (voicePlaybackNotice && voicePlaybackNoticeText) {
                    voicePlaybackNoticeText.textContent = fallbackMsg;
                    voicePlaybackNotice.style.display = "flex";
                }
                if (voiceStatusText) voiceStatusText.textContent = fallbackMsg;
                if (voiceReplayBtn) {
                    voiceReplayBtn.style.display = "inline-block";
                    voiceReplayBtn.disabled = false;
                    voiceReplayBtn.style.opacity = "1";
                    voiceReplayBtn.style.cursor = "pointer";
                }
                return { success: false, spoken: false, reason: "backend_failed", error: res.error };
            }

            // Audio blob received successfully
            if (voicePlaybackNotice) voicePlaybackNotice.style.display = "none";

            if (lastAudioBlobUrl) {
                try { URL.revokeObjectURL(lastAudioBlobUrl); } catch {}
            }
            lastAudioBlobUrl = URL.createObjectURL(res.blob);
            if (!currentAudioElement) {
                currentAudioElement = new Audio();
            }
            currentAudioElement.src = lastAudioBlobUrl;

            currentAudioElement.onplay = () => {
                if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "flex";
                if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "inline-block";
                if (voiceReplayBtn) voiceReplayBtn.style.display = "none";
                if (voicePlayBtn) voicePlayBtn.style.display = "none";
                if (voiceStatusText) voiceStatusText.textContent = `Speaking in ${langName}...`;
            };

            currentAudioElement.onended = () => {
                if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "none";
                if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "none";
                if (voicePlayBtn) voicePlayBtn.style.display = "none";
                if (voiceReplayBtn) {
                    voiceReplayBtn.style.display = "inline-block";
                    voiceReplayBtn.disabled = false;
                    voiceReplayBtn.style.opacity = "1";
                    voiceReplayBtn.style.cursor = "pointer";
                }
                if (voiceStatusText) voiceStatusText.textContent = "Answer complete. Click microphone to speak again.";
            };

            currentAudioElement.onerror = (e) => {
                console.warn("HTML5 audio playback error:", e);
                if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "none";
                if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "none";
                if (voicePlayBtn) voicePlayBtn.style.display = "inline-block";
                if (voiceReplayBtn) {
                    voiceReplayBtn.style.display = "inline-block";
                    voiceReplayBtn.disabled = false;
                    voiceReplayBtn.style.opacity = "1";
                }
            };

            const playPromise = currentAudioElement.play();
            if (playPromise !== undefined) {
                playPromise.catch(playErr => {
                    console.warn("Browser autoplay restricted:", playErr);
                    // Autoplay restriction: surface Play button so user can click to hear audio
                    if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "none";
                    if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "none";
                    if (voicePlayBtn) {
                        voicePlayBtn.style.display = "inline-block";
                        voicePlayBtn.title = `Click to play ${langName} audio`;
                    }
                    if (voiceReplayBtn) voiceReplayBtn.style.display = "none";
                    if (voiceStatusText) voiceStatusText.textContent = `Audio ready. Click Play to listen in ${langName}.`;
                });
            }

            return { success: true, spoken: true, langName, source: "backend_tts" };

        } catch (err) {
            console.error("speakWithBackendTts error:", err);
            if (voiceTtsLoadingIndicator) voiceTtsLoadingIndicator.style.display = "none";
            isTtsGenerating = false;
            return { success: false, spoken: false, reason: "error", error: err };
        }
    }

    /**
     * Speaks the assistant answer aloud using hybrid native/backend TTS architecture.
     * 1. Uses genuine native browser voice if available (e.g. English, or Hindi when present).
     * 2. Automatically falls back to backend TTS for Telugu and unsupported native voices.
     * 3. Provides play, stop, and replay controls without duplicate network overhead.
     */
    function speakText(text, lang = "en-IN") {
        stopSpeaking();

        const cleanText = sanitizeTextForSpeech(text);
        if (!cleanText) return { success: false, spoken: false, reason: "empty_text" };

        let normalizedLang = lang;
        if (lang.startsWith("te")) normalizedLang = "te-IN";
        else if (lang.startsWith("hi")) normalizedLang = "hi-IN";
        else if (lang.startsWith("en")) normalizedLang = "en-IN";

        lastSpokenAnswerText = cleanText;
        lastSpokenAnswerLang = normalizedLang;

        const langPrefix = normalizedLang.split("-")[0];
        const langName = langPrefix === "te" ? "Telugu" : langPrefix === "hi" ? "Hindi" : "English";
        const matchedVoice = findCompatibleVoice(normalizedLang);

        // If native voice is not present (or browser lacks Web Speech Synthesis), use backend TTS fallback
        if (!matchedVoice || !("speechSynthesis" in window)) {
            return speakWithBackendTts(cleanText, normalizedLang, langName);
        }

        // Voice is available in browser: clear any previous fallback notice and enable replay button
        if (voicePlaybackNotice) {
            voicePlaybackNotice.style.display = "none";
        }
        if (voiceReplayBtn) {
            voiceReplayBtn.disabled = false;
            voiceReplayBtn.style.opacity = "1";
            voiceReplayBtn.style.cursor = "pointer";
            voiceReplayBtn.title = t("voice.listenAgain", {}, "Read answer aloud again");
        }

        try {
            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = normalizedLang;
            utterance.voice = matchedVoice;

            utterance.onstart = () => {
                if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "flex";
                if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "inline-block";
                if (voiceReplayBtn) voiceReplayBtn.style.display = "none";
                if (voicePlayBtn) voicePlayBtn.style.display = "none";
                if (voiceStatusText) {
                    voiceStatusText.textContent = `Speaking in ${langName}...`;
                }
            };

            utterance.onend = () => {
                if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "none";
                if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "none";
                if (voiceReplayBtn) voiceReplayBtn.style.display = "inline-block";
                if (voicePlayBtn) voicePlayBtn.style.display = "none";
                if (voiceStatusText) {
                    voiceStatusText.textContent = "Answer complete. Click microphone to speak again.";
                }
            };

            utterance.onerror = (e) => {
                console.warn("SpeechSynthesis utterance error, falling back to backend TTS:", e);
                speakWithBackendTts(cleanText, normalizedLang, langName);
            };

            window.speechSynthesis.speak(utterance);
            return { success: true, spoken: true, langName, source: "browser_tts" };

        } catch (err) {
            console.warn("SpeechSynthesis error, falling back to backend TTS:", err);
            return speakWithBackendTts(cleanText, normalizedLang, langName);
        }
    }

    function stopSpeaking() {
        if (currentAudioElement) {
            try {
                currentAudioElement.pause();
                currentAudioElement.currentTime = 0;
            } catch (err) {
                console.warn("Audio pause error:", err);
            }
        }
        if ("speechSynthesis" in window) {
            try {
                window.speechSynthesis.cancel();
            } catch (err) {
                console.warn("SpeechSynthesis cancel error:", err);
            }
        }
        if (voiceSpeakingIndicator) voiceSpeakingIndicator.style.display = "none";
        if (voiceStopSpeakingBtn) voiceStopSpeakingBtn.style.display = "none";
        if (voiceTtsLoadingIndicator) voiceTtsLoadingIndicator.style.display = "none";
        if (voiceReplayBtn) {
            voiceReplayBtn.style.display = "inline-block";
            voiceReplayBtn.disabled = false;
            voiceReplayBtn.style.opacity = "1";
            voiceReplayBtn.style.cursor = "pointer";
        }
    }

    function clearVoiceError() {
        if (voiceErrorBanner) voiceErrorBanner.style.display = "none";
        if (voiceErrorMessage) voiceErrorMessage.textContent = "";
    }

    function showVoiceError(message, retryable = true) {
        if (!voiceErrorBanner || !voiceErrorMessage) return;
        voiceErrorMessage.textContent = message;
        if (voiceRetryBtn) {
            voiceRetryBtn.style.display = retryable ? "inline-block" : "none";
        }
        voiceErrorBanner.style.display = "flex";
    }

    function updateVoiceCharCounter() {
        if (!voiceTranscriptText || !voiceCharCounter) return;
        const len = voiceTranscriptText.value.length;
        voiceCharCounter.textContent = `${len} / 2000`;
        if (voiceSendBtn) {
            voiceSendBtn.disabled = (len === 0 || isSendingVoiceMessage);
        }
    }

    function startNewVoiceSession() {
        stopVoiceRecognition();
        stopSpeaking();
        clearVoiceError();

        // Clear active conversation context to start fresh
        activeChatConversationId = null;

        if (voiceTranscriptText) {
            voiceTranscriptText.value = "";
            updateVoiceCharCounter();
        }
        if (voicePlaybackNotice) {
            voicePlaybackNotice.style.display = "none";
        }
        if (voiceReplayBtn) {
            voiceReplayBtn.disabled = false;
            voiceReplayBtn.style.opacity = "1";
            voiceReplayBtn.style.cursor = "pointer";
        }
        if (voiceResponseSection) {
            voiceResponseSection.style.display = "none";
        }
        if (voiceAnswerText) {
            voiceAnswerText.textContent = "";
        }
        if (voiceStatusText) {
            voiceStatusText.textContent = "Click the microphone to start speaking";
        }

        // Also reset text chat view so text chat stays synchronized
        startNewChat();
    }

    function switchToTextChat() {
        stopVoiceRecognition();
        stopSpeaking();
        closeModal(voiceModal);
        openChatModal(cardChat);
    }

    async function handleSendVoiceQuestion() {
        if (isSendingVoiceMessage || !voiceTranscriptText) return;

        const message = voiceTranscriptText.value.trim();
        if (!message) return;

        // Synchronously prime/unlock audio in user gesture so subsequent playback is permitted
        preUnlockAudio();

        isSendingVoiceMessage = true;
        lastFailedVoicePrompt = message;
        clearVoiceError();
        stopVoiceRecognition();
        stopSpeaking();

        if (voiceSendBtn) voiceSendBtn.disabled = true;
        if (voiceMicBtn) voiceMicBtn.disabled = true;
        if (voiceLoadingIndicator) voiceLoadingIndicator.style.display = "flex";

        const selectedLang = voiceLangSelect ? voiceLangSelect.value : "en-IN";

        try {
            const res = await sendChatMessage(message, activeChatConversationId, selectedLang);

            if (voiceLoadingIndicator) voiceLoadingIndicator.style.display = "none";

            if (!res.ok) {
                if (res.status === 401) {
                    showVoiceError("Your session has expired or is invalid. Please log in or refresh your guest session.", false);
                } else {
                    showVoiceError(res.error || "An error occurred while generating scheme guidance. Please try again.", true);
                }
                return;
            }

            const data = res.data;

            // Preserve active conversation ID for seamless continuity across voice and text
            if (!isGuestMode && !activeChatConversationId && data.conversation_id) {
                activeChatConversationId = data.conversation_id;
                loadChatHistoryList();
            }

            // Display assistant response safely
            if (voiceResponseSection) voiceResponseSection.style.display = "flex";
            if (voiceAnswerText) voiceAnswerText.innerHTML = renderSafeMarkdown(data.content || "");

            // Insufficient evidence notice
            if (voiceEvidenceWarning) {
                voiceEvidenceWarning.style.display = (data.evidence_sufficient === false && data.intent === "scheme_inquiry") ? "block" : "none";
            }

            // Disclaimer notice in voice response
            const voiceDisclaimerBox = document.getElementById("voiceDisclaimerBox");
            if (voiceDisclaimerBox) {
                if (data.disclaimer && typeof data.disclaimer === "string" && data.disclaimer.trim().length > 0) {
                    voiceDisclaimerBox.textContent = data.disclaimer;
                    voiceDisclaimerBox.style.display = "block";
                } else {
                    voiceDisclaimerBox.style.display = "none";
                }
            }

            // Citations rendering (safe DOM builder)
            if (voiceCitationsSection && voiceCitationsList) {
                voiceCitationsList.innerHTML = "";
                const citations = data.citations || [];
                if (citations.length > 0) {
                    citations.forEach((cit, idx) => {
                        const citItem = document.createElement("div");
                        citItem.className = "chat-citation-item";

                        const badge = document.createElement("span");
                        badge.className = "chat-citation-badge";
                        badge.textContent = `[S${idx + 1}] ${cit.authority || "Official"}`;
                        citItem.appendChild(badge);

                        const docLabel = document.createTextNode(
                            ` ${cit.document_name || cit.scheme_id || "Guidelines"}` +
                            (cit.page_number ? ` (Page ${cit.page_number})` : "")
                        );
                        citItem.appendChild(docLabel);

                        if (cit.source_url && isSafeUrl(cit.source_url)) {
                            const link = document.createElement("a");
                            link.href = cit.source_url;
                            link.target = "_blank";
                            link.rel = "noopener noreferrer";
                            link.className = "chat-citation-link";
                            link.textContent = "[View Source Document]";
                            citItem.appendChild(document.createTextNode(" "));
                            citItem.appendChild(link);
                        }

                        voiceCitationsList.appendChild(citItem);
                    });
                    voiceCitationsSection.style.display = "block";
                } else {
                    voiceCitationsSection.style.display = "none";
                }
            }

            // Speak answer aloud with selected language (if compatible TTS voice is available)
            const responseLang = data.language ? (data.language.startsWith("te") ? "te-IN" : data.language.startsWith("hi") ? "hi-IN" : "en-IN") : selectedLang;
            const speakResult = speakText(data.content, responseLang);

            // Only overwrite status if speech could not be generated or text was empty
            if (speakResult && speakResult.spoken === false && speakResult.reason === "empty_text") {
                if (voiceStatusText) {
                    voiceStatusText.textContent = "Answer received! Click the microphone to ask a follow-up question.";
                }
            }

        } catch (err) {
            console.error("Voice send message error:", err);
            if (voiceLoadingIndicator) voiceLoadingIndicator.style.display = "none";
            showVoiceError("Network connection error. Please verify your connection and try again.", true);
        } finally {
            isSendingVoiceMessage = false;
            if (voiceSendBtn) voiceSendBtn.disabled = false;
            if (voiceMicBtn) voiceMicBtn.disabled = false;
        }
    }

    function updateVoiceLanguageHint() {
        if (!voiceLangSelect || !voiceLangHint) return;
        const langName = voiceLangSelect.options[voiceLangSelect.selectedIndex]?.text || "English";
        const selectedVal = voiceLangSelect.value;
        const hasPlayback = isVoicePlaybackAvailable(selectedVal);
        let hint = t("voice.hint", { lang: langName }, `Listening in ${langName}. Click microphone to begin.`);
        if (!hasPlayback && (selectedVal.startsWith("te") || selectedVal.startsWith("hi"))) {
            hint += " " + t("voice.playbackUnsupportedHint", { lang: langName }, `(Note: Speech input supported; audio playback voice unavailable in this browser)`);
        }
        voiceLangHint.textContent = hint;
    }

    function openVoiceModal(triggerEl = null) {
        if (!voiceModal) return;

        openModal(voiceModal, triggerEl);
        stopSpeaking();
        clearVoiceError();

        // Sync voice locale with website language preference if user hasn't manually overridden it
        if (typeof I18n !== 'undefined' && voiceLangSelect && !userManuallyChangedVoiceLang) {
            voiceLangSelect.value = I18n.getVoiceLocale();
        }

        // Check browser speech support
        initSpeechRecognition();

        // Update language hint based on selected language and playback voice availability
        updateVoiceLanguageHint();

        if (voiceStatusText) {
            voiceStatusText.textContent = t("voice.statusIdle", {}, "Click the microphone to start speaking");
        }
    }

    // Attach Voice Event Listeners
    if (voiceMicBtn) {
        voiceMicBtn.addEventListener("click", () => {
            preUnlockAudio();
            toggleVoiceListening();
        });
    }

    if (voiceSendBtn) {
        voiceSendBtn.addEventListener("click", () => {
            handleSendVoiceQuestion();
        });
    }

    if (voiceClearBtn) {
        voiceClearBtn.addEventListener("click", () => {
            if (voiceTranscriptText) {
                voiceTranscriptText.value = "";
                updateVoiceCharCounter();
            }
        });
    }

    if (voiceNewBtn) {
        voiceNewBtn.addEventListener("click", () => {
            startNewVoiceSession();
        });
    }

    if (voicePlayBtn) {
        voicePlayBtn.addEventListener("click", () => {
            preUnlockAudio();
            if (currentAudioElement && lastAudioBlobUrl) {
                currentAudioElement.currentTime = 0;
                currentAudioElement.play().catch(err => {
                    console.warn("Play error:", err);
                    if (lastSpokenAnswerText) {
                        speakText(lastSpokenAnswerText, lastSpokenAnswerLang);
                    }
                });
            } else if (lastSpokenAnswerText) {
                speakText(lastSpokenAnswerText, lastSpokenAnswerLang);
            }
        });
    }

    if (voiceStopSpeakingBtn) {
        voiceStopSpeakingBtn.addEventListener("click", () => {
            stopSpeaking();
        });
    }

    if (voiceReplayBtn) {
        voiceReplayBtn.addEventListener("click", () => {
            preUnlockAudio();
            if (currentAudioElement && lastAudioBlobUrl) {
                currentAudioElement.currentTime = 0;
                currentAudioElement.play().catch(err => {
                    console.warn("Replay error, regenerating:", err);
                    if (lastSpokenAnswerText) {
                        const langToReplay = lastSpokenAnswerLang || (voiceLangSelect ? voiceLangSelect.value : "en-IN");
                        speakText(lastSpokenAnswerText, langToReplay);
                    }
                });
            } else if (lastSpokenAnswerText) {
                const langToReplay = lastSpokenAnswerLang || (voiceLangSelect ? voiceLangSelect.value : "en-IN");
                speakText(lastSpokenAnswerText, langToReplay);
            }
        });
    }

    if (voiceSwitchToChatBtn) {
        voiceSwitchToChatBtn.addEventListener("click", () => {
            switchToTextChat();
        });
    }

    if (voiceFallbackToChatBtn) {
        voiceFallbackToChatBtn.addEventListener("click", () => {
            switchToTextChat();
        });
    }

    if (voiceRetryBtn) {
        voiceRetryBtn.addEventListener("click", () => {
            if (lastFailedVoicePrompt && voiceTranscriptText) {
                voiceTranscriptText.value = lastFailedVoicePrompt;
                clearVoiceError();
                handleSendVoiceQuestion();
            }
        });
    }

    if (voiceLangSelect) {
        voiceLangSelect.addEventListener("change", () => {
            userManuallyChangedVoiceLang = true;
            stopSpeaking();
            const langName = voiceLangSelect.options[voiceLangSelect.selectedIndex]?.text || "English";
            updateVoiceLanguageHint();
            if (voiceStatusText) {
                voiceStatusText.textContent = `Language set to ${langName}. Click microphone to speak.`;
            }
            if (speechRecognitionInstance) {
                speechRecognitionInstance.lang = voiceLangSelect.value;
            }
        });
    }

    if (voiceTranscriptText) {
        voiceTranscriptText.addEventListener("input", () => {
            updateVoiceCharCounter();
        });

        voiceTranscriptText.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSendVoiceQuestion();
            }
        });
    }

    if (featureModalExploreBtn) {
        featureModalExploreBtn.addEventListener("click", () => {
            closeModal(featureInfoModal);
            if (cardCatalog) cardCatalog.click();
        });
    }

    // ---------------------------------------------------------------------------
    // Scheme Discovery: Render Functions & Status Badges Component
    // ---------------------------------------------------------------------------

    /**
     * Unified status badge generator for citizen dashboard scheme cards across both
     * education (schemes.json) and cross-sector (central_schemes.json) schemes.
     * Generates three independent statuses from backend data:
     * 1. Application Status (Applications Open, Applications Closed, Open Year-round, Availability Needs Live Check, Check Quota Availability)
     * 2. Deadline Status (formatted deadline date, Closed: <date>, No Fixed Closing Date, No Fixed Deadline Established; Availability Needs Confirmation, Deadline Not Confirmed)
     * 3. Information Verification Status (Information Verified, Verification Pending)
     */
    function getSchemeStatusBadges(s, item = null) {
        const scheme = s || (item && item.scheme) || {};

        // 1. APPLICATION STATUS
        const rawAppStatus = String(
            scheme.application_status ||
            (item && item.application_status) ||
            scheme.application_availability_status ||
            scheme.deadline_status ||
            (item && item.deadline_status) ||
            ""
        ).toUpperCase().trim();

        let appStatusText = "";
        let appStatusClass = "";

        if (rawAppStatus === "OPEN") {
            appStatusText = t("deadlines.statusOpen", {}, "Applications Open");
            appStatusClass = "badge-app-status badge-app-status-open";
        } else if (rawAppStatus === "CLOSED") {
            appStatusText = t("deadlines.statusClosed", {}, "Applications Closed");
            appStatusClass = "badge-app-status badge-app-status-closed";
        } else if (rawAppStatus === "YEAR_ROUND") {
            appStatusText = t("schemes.statusYearRound", {}, "Open Year-round");
            appStatusClass = "badge-app-status badge-app-status-year-round";
        } else if (rawAppStatus === "NEEDS_LIVE_VERIFICATION") {
            appStatusText = t("schemes.statusNeedsLiveVerification", {}, "Availability Needs Live Check");
            appStatusClass = "badge-app-status badge-app-status-needs-verification";
        } else if (rawAppStatus === "QUOTA_DEPENDENT") {
            appStatusText = t("schemes.statusQuotaDependent", {}, "Check Quota Availability");
            appStatusClass = "badge-app-status badge-app-status-quota";
        } else if (rawAppStatus === "UPCOMING") {
            appStatusText = t("deadlines.badgeUpcoming", {}, "Opening Soon");
            appStatusClass = "badge-app-status badge-app-status-upcoming";
        } else {
            appStatusText = t("schemes.statusNeedsLiveVerification", {}, "Availability Needs Live Check");
            appStatusClass = "badge-app-status badge-app-status-needs-verification";
        }

        const appStatusBadge = `<span class="${appStatusClass}" data-app-status="${escapeHtml(rawAppStatus)}">${escapeHtml(appStatusText)}</span>`;

        // 2. DEADLINE STATUS
        const rawLastDate = (
            (item && item.application_last_date) ||
            scheme.application_last_date ||
            scheme.application_deadline ||
            scheme.last_application_deadline ||
            ""
        );
        const lastDate = (rawLastDate && rawLastDate !== "null" && rawLastDate !== "None" && rawLastDate !== "--") ? String(rawLastDate).trim() : "";

        const dStatus = String(
            (item && item.deadline_status) ||
            scheme.deadline_status ||
            rawAppStatus ||
            ""
        ).toUpperCase().trim();

        const cycle = String(
            (item && item.application_cycle) ||
            scheme.application_cycle ||
            ""
        ).toLowerCase();

        let deadlineText = "";
        let deadlineClass = "";

        if (rawAppStatus === "CLOSED" || dStatus === "CLOSED") {
            // Closed application -> Show historical closing date
            deadlineText = lastDate ? `Closed: ${lastDate}` : "Applications Closed";
            deadlineClass = "badge-deadline-status badge-deadline-closed";
        } else if (lastDate) {
            // Actual deadline -> Show the formatted deadline
            deadlineText = lastDate;
            deadlineClass = "badge-deadline-status badge-deadline-date";
        } else if (
            rawAppStatus === "NEEDS_LIVE_VERIFICATION" ||
            rawAppStatus === "QUOTA_DEPENDENT" ||
            dStatus === "NEEDS_LIVE_VERIFICATION" ||
            dStatus === "QUOTA_DEPENDENT"
        ) {
            // Null deadline with availability requiring confirmation -> No Fixed Deadline Established
            deadlineText = t("deadlines.noFixedDeadlineEstablished", {}, "No Fixed Deadline Established");
            deadlineClass = "badge-deadline-status badge-deadline-needs-confirmation";
        } else if (
            rawAppStatus === "YEAR_ROUND" ||
            dStatus === "YEAR_ROUND" ||
            cycle.includes("continuous") ||
            cycle.includes("year-round")
        ) {
            // Null deadline with a confirmed continuous cycle -> No Fixed Closing Date
            deadlineText = t("deadlines.noFixedClosingDate", {}, "No Fixed Closing Date");
            deadlineClass = "badge-deadline-status badge-deadline-no-fixed";
        } else {
            // Missing or unverified deadline information -> Deadline Not Confirmed
            deadlineText = t("deadlines.deadlineNotConfirmed", {}, "Deadline Not Confirmed");
            deadlineClass = "badge-deadline-status badge-deadline-unconfirmed";
        }

        const deadlineBadge = `<span class="${deadlineClass}">${escapeHtml(deadlineText)}</span>`;

        // 3. INFORMATION VERIFICATION STATUS (Internal review info hidden from citizen-facing cards)
        const isVerified = Boolean(
            scheme.is_verified === true ||
            (item && item.is_verified === true) ||
            String(scheme.verification_status || (item && item.verification_status) || "").toLowerCase() === "verified"
        );

        let verText = "";
        let verClass = "";
        let verificationBadge = "";

        if (isVerified) {
            verText = t("schemes.badgeInformationVerified", {}, "Information Verified");
            verClass = "badge-verification-status badge-verification-verified";
            verificationBadge = `<span class="${verClass}">${escapeHtml(verText)}</span>`;
        } else {
            // Hide internal admin review status from citizen-facing cards
            verText = "";
            verClass = "";
            verificationBadge = "";
        }

        return {
            appStatusText,
            appStatusClass,
            appStatusBadge,
            deadlineText,
            deadlineClass,
            deadlineBadge,
            verText,
            verClass,
            verificationBadge,
        };
    }

    if (typeof window !== "undefined") {
        window.getSchemeStatusBadges = getSchemeStatusBadges;
    }

    /**
     * Renders personalized scheme recommendations grouped into Preliminary Matches
     * and Rule Mismatches Requiring Review.
     */
    function renderRecommendations(data) {
        clearSchemesAlert();
        schemesContainer.innerHTML = "";

        const preliminary = data.preliminary_matches || [];
        const mismatches = data.rule_mismatches_requiring_review || [];

        const confirmedDocBenefitBanner = document.getElementById("confirmedDocBenefitBanner");
        const hasAnyConfirmedEvidence = [...preliminary, ...mismatches].some(
            (it) => (it.confirmed_evidence && it.confirmed_evidence.length > 0) || (it.document_readiness_summary && it.document_readiness_summary.confirmed_count > 0)
        );
        if (confirmedDocBenefitBanner) {
            confirmedDocBenefitBanner.style.display = hasAnyConfirmedEvidence ? "block" : "none";
        }

        if (preliminary.length === 0 && mismatches.length === 0) {
            schemesContainer.innerHTML = `
                <div class="empty-state-notice">
                    <p>${t("schemes.noPreliminaryMatches", {}, "No scheme recommendations could be evaluated at this time.")}</p>
                </div>
            `;
            return;
        }

        let html = "";

        // Section 1: Preliminary Profile Matches
        const preliminaryTitle = t("schemes.preliminaryMatchesTitle", { count: preliminary.length }, `Preliminary Profile Matches (${preliminary.length})`);
        const preliminaryDesc = t("schemes.preliminaryMatchesDesc", {}, "Schemes whose rule conditions are satisfied or require document self-declaration. Official sanction requires human review.");
        const potentialMatchesText = t("schemes.potentialMatchesCount", { count: preliminary.length }, `${preliminary.length} Potential Matches`);

        html += `
            <div style="margin-bottom: 32px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <h3 style="color: #166534; font-size: 18px; margin: 0;">
                            ${escapeHtml(preliminaryTitle)}
                        </h3>
                        <p style="font-size: 13px; color: #64748b; margin-top: 4px;">
                            ${escapeHtml(preliminaryDesc)}
                        </p>
                    </div>
                    <span class="badge-preliminary-match" style="font-size: 12px; padding: 5px 10px;">
                        ${escapeHtml(potentialMatchesText)}
                    </span>
                </div>
        `;

        if (preliminary.length === 0) {
            html += `
                <div class="empty-state-notice" style="padding: 24px; background: #f8fafc; border-radius: 8px;">
                    ${t("schemes.noPreliminaryMatches", {}, "No schemes currently match all criteria for this application mode. Check the rule mismatches below or explore the full catalog.")}
                </div>
            `;
        } else {
            html += '<div class="schemes-cards-list">';
            preliminary.forEach((item) => {
                const s = item.scheme;
                const schemeId = escapeHtml(s.scheme_id);
                const title = escapeHtml(s.current_official_name || s.scheme_name);
                const dept = escapeHtml(s.department || s.responsible_ministry || "Government of India");
                const desc = escapeHtml(s.description || "");
                const cat = escapeHtml(s.category || "General");

                // Dynamic Status Badges metadata
                const statusBadges = getSchemeStatusBadges(s, item);
                const dStatus = item.deadline_status || (s && s.deadline_status) || (s && s.application_status) || "NOT_ANNOUNCED";
                const isClosed = (dStatus === "CLOSED") || (s && s.is_currently_open === false && dStatus !== "YEAR_ROUND" && dStatus !== "NEEDS_LIVE_VERIFICATION" && dStatus !== "QUOTA_DEPENDENT");
                const lastDate = item.application_last_date || (s && s.application_last_date) || "";
                const cycle = item.application_cycle || (s && s.application_cycle) || "AY 2026-27";
                const nextCycle = item.next_cycle_status || (s && s.next_cycle_status);

                let deadlineAdvisoryHtml = "";

                if (dStatus === "OPEN") {
                    const openText = t("deadlines.openAdvisory", { cycle: cycle, date: lastDate }, `Applications for cycle ${cycle} are currently OPEN until ${lastDate}.`);
                    deadlineAdvisoryHtml = `<div class="deadline-advisory-box deadline-advisory-open">${escapeHtml(openText)}</div>`;
                } else if (dStatus === "CLOSED") {
                    let closedText = t("deadlines.closedAdvisory", { cycle: cycle, date: lastDate }, `Note: Student application window for cycle ${cycle} closed on ${lastDate}. Applications are not currently open.`);
                    if (nextCycle && nextCycle !== "NOT_ANNOUNCED") {
                        closedText += ` ${t("deadlines.nextCycle", { status: nextCycle }, `Next Cycle: ${nextCycle}`)}`;
                    }
                    deadlineAdvisoryHtml = `<div class="deadline-advisory-box deadline-advisory-closed">${escapeHtml(closedText)}</div>`;
                } else if (dStatus === "UPCOMING") {
                    const startD = item.application_start_date || (s && s.application_start_date) || "";
                    const upText = t("deadlines.upcomingAdvisory", { cycle: cycle, date: startD }, `Applications for cycle ${cycle} will open on ${startD}.`);
                    deadlineAdvisoryHtml = `<div class="deadline-advisory-box deadline-advisory-upcoming">${escapeHtml(upText)}</div>`;
                } else if (dStatus === "YEAR_ROUND") {
                    deadlineAdvisoryHtml = `<div class="deadline-advisory-box deadline-advisory-open">Continuous application intake throughout the year. No fixed annual closing date.</div>`;
                } else if (dStatus === "NEEDS_LIVE_VERIFICATION") {
                    deadlineAdvisoryHtml = `<div class="deadline-advisory-box deadline-advisory-neutral">Application intake is open on official portal; availability subject to state/district allocations and live verification.</div>`;
                } else if (dStatus === "QUOTA_DEPENDENT") {
                    deadlineAdvisoryHtml = `<div class="deadline-advisory-box deadline-advisory-neutral">Enrollment is active under approved government targets; availability subject to regional quota distribution.</div>`;
                }

                // Document Readiness Badge (only verified/confirmed documents)
                const docSum = item.document_readiness_summary || {};
                let docReadinessBadgeHtml = "";
                if (docSum.total_required !== undefined && docSum.total_required > 0) {
                    if (docSum.is_ready) {
                        docReadinessBadgeHtml = `<span class="badge badge-readiness-complete" title="All required documents confirmed">📋 ${docSum.confirmed_count}/${docSum.total_required} ${t("readiness.docsReady", {}, "Docs Ready")}</span>`;
                    } else if (docSum.conflicting_count > 0) {
                        docReadinessBadgeHtml = `<span class="badge badge-readiness-conflict" title="Document conflicts with profile">⚠️ ${t("readiness.discrepancy", {}, "Doc Conflict")}</span>`;
                    } else {
                        docReadinessBadgeHtml = `<span class="badge badge-readiness-missing" title="Verified documents: ${docSum.confirmed_count || 0} of ${docSum.total_required}">📁 ${docSum.confirmed_count || 0}/${docSum.total_required} ${t("readiness.docs", {}, "Docs")}</span>`;
                    }
                }

                // Confirmed Evidence Chips
                let confirmedEvidenceHtml = "";
                if (item.confirmed_evidence && item.confirmed_evidence.length > 0) {
                    confirmedEvidenceHtml = `
                        <div class="confirmed-evidence-container" style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
                            <span style="font-size: 11px; font-weight: 600; color: #166534;">✓ Active Evidence:</span>
                            ${item.confirmed_evidence.map(e => `
                                <span class="confirmed-evidence-chip" title="${escapeHtml(e.document_type || '')}">
                                    ${escapeHtml(e.label)}: <strong>${escapeHtml(e.value)}</strong>
                                </span>
                            `).join("")}
                        </div>
                    `;
                }

                // Action Link for Pending Review removed: recommendations evaluate and work only with verified documents
                let pendingActionHtml = "";

                // Conflict notes
                let conflictNotesHtml = "";
                if (item.conflict_notes && item.conflict_notes.length > 0) {
                    conflictNotesHtml = `
                        <div style="margin-top: 8px; background: #fef2f2; border-left: 3px solid #ef4444; padding: 6px 10px; font-size: 11px; color: #991b1b; border-radius: 4px;">
                            <strong>⚠️ Document Discrepancy:</strong> ${item.conflict_notes.map(n => escapeHtml(n)).join("<br>")}
                        </div>
                    `;
                }

                let missingNotice = "";
                if (item.missing_information && item.missing_information.length > 0) {
                    const missingList = item.missing_information.map(m => escapeHtml(m.replace(/_/g, " "))).join(", ");
                    missingNotice = `
                        <div style="background: #eff6ff; border-left: 3px solid #3b82f6; padding: 6px 10px; font-size: 11px; color: #1e40af; border-radius: 4px; margin-top: 8px;">
                            <strong>${t("schemes.additionalDetailsNeeded", {}, "Additional details needed:")}</strong> ${missingList}
                        </div>
                    `;
                }

                html += `
                    <div class="scheme-card" data-scheme-id="${schemeId}">
                        <div class="scheme-card-header">
                            <h3>${title}</h3>
                            <div class="scheme-ministry">${dept}</div>
                            <div class="scheme-badges-row">
                                <span class="badge-preliminary-match">${t("schemes.badgePreliminaryMatch", {}, "Preliminary Match")}</span>
                                ${statusBadges.appStatusBadge}
                                ${statusBadges.deadlineBadge}
                                ${statusBadges.verificationBadge}
                                ${docReadinessBadgeHtml}
                                <span class="badge-tag">${cat}</span>
                            </div>
                        </div>

                        <div class="scheme-card-body">
                            <p class="scheme-description">${desc}</p>
                            <div class="scheme-meta-item">
                                <strong>Criteria Evaluated:</strong> ${t("schemes.conditionsMet", { count: item.matched_conditions_count }, `${item.matched_conditions_count} conditions met`)}
                            </div>
                            ${confirmedEvidenceHtml}
                            ${pendingActionHtml}
                            ${conflictNotesHtml}
                            ${deadlineAdvisoryHtml}
                            ${missingNotice}
                        </div>

                        <div class="scheme-card-footer">
                            <button type="button" class="btn-scheme-details btn-view-details" data-id="${schemeId}">
                                ${t("schemes.btnDetails", {}, "Scheme Details")}
                            </button>
                            <button type="button" class="btn-scheme-eligibility btn-view-eligibility" data-id="${schemeId}">
                                ${t("schemes.btnBreakdown", {}, "Rule Breakdown")}
                            </button>
                            ${isClosed ? `
                                <button type="button" class="btn-scheme-apply btn-apply-closed" data-id="${schemeId}" data-closed="true" disabled style="background: #94a3b8; border-color: #94a3b8; color: #ffffff; cursor: not-allowed; opacity: 0.85;" title="${t("deadlines.statusClosed", {}, "Applications Closed")}">
                                    ${t("deadlines.statusClosed", {}, "Applications Closed")}
                                </button>
                            ` : `
                                <button type="button" class="btn-scheme-apply btn-apply-now" data-id="${schemeId}">
                                    ${t("schemes.btnApplyNow", {}, "Apply Now")}
                                </button>
                            `}
                        </div>
                    </div>
                `;
            });
            html += "</div>";
        }
        html += "</div>";

        // Section 2: Rule Mismatches Requiring Review
        const mismatchesTitle = t("schemes.mismatchesTitle", { count: mismatches.length }, `Rule Mismatches Requiring Review (${mismatches.length})`);
        const mismatchesDesc = t("schemes.mismatchesDesc", {}, "One or more rules did not align with your recorded profile. Note: These are automated preliminary checks and not official government rejections.");

        html += `
            <div style="margin-top: 24px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <h3 style="color: #9a3412; font-size: 18px; margin: 0;">
                            ${escapeHtml(mismatchesTitle)}
                        </h3>
                        <p style="font-size: 13px; color: #64748b; margin-top: 4px;">
                            ${escapeHtml(mismatchesDesc)}
                        </p>
                    </div>
                    <span class="badge-rule-mismatch" style="font-size: 12px; padding: 5px 10px;">
                        ${mismatches.length} Mismatch${mismatches.length === 1 ? "" : "es"}
                    </span>
                </div>
        `;

        if (mismatches.length === 0) {
            html += `
                <div class="empty-state-notice" style="padding: 24px; background: #f8fafc; border-radius: 8px;">
                    ${t("schemes.noPreliminaryMatches", {}, "No rule mismatches recorded for this profile.")}
                </div>
            `;
        } else {
            html += '<div class="schemes-cards-list">';
            mismatches.forEach((item) => {
                const s = item.scheme;
                const schemeId = escapeHtml(s.scheme_id);
                const title = escapeHtml(s.current_official_name || s.scheme_name);
                const dept = escapeHtml(s.department || s.responsible_ministry || "Government of India");
                const desc = escapeHtml(s.description || "");
                const cat = escapeHtml(s.category || "General");

                const statusBadges = getSchemeStatusBadges(s, item);
                const dStatus = item.deadline_status || (s && s.deadline_status) || (s && s.application_status) || "NOT_ANNOUNCED";
                const isClosed = (dStatus === "CLOSED") || (s && s.is_currently_open === false && dStatus !== "YEAR_ROUND" && dStatus !== "NEEDS_LIVE_VERIFICATION" && dStatus !== "QUOTA_DEPENDENT");

                // Document Readiness Badge for Mismatch (only verified/confirmed documents)
                const docSum = item.document_readiness_summary || {};
                let docReadinessBadgeHtml = "";
                if (docSum.total_required !== undefined && docSum.total_required > 0) {
                    if (docSum.is_ready) {
                        docReadinessBadgeHtml = `<span class="badge badge-readiness-complete">📋 ${docSum.confirmed_count}/${docSum.total_required} Docs Ready</span>`;
                    } else if (docSum.conflicting_count > 0) {
                        docReadinessBadgeHtml = `<span class="badge badge-readiness-conflict">⚠️ Doc Conflict</span>`;
                    } else {
                        docReadinessBadgeHtml = `<span class="badge badge-readiness-missing">📁 ${docSum.confirmed_count || 0}/${docSum.total_required || 0} Docs</span>`;
                    }
                }

                let conflictNotesHtml = "";
                if (item.conflict_notes && item.conflict_notes.length > 0) {
                    conflictNotesHtml = `
                        <div style="margin-top: 8px; background: #fef2f2; border-left: 3px solid #ef4444; padding: 6px 10px; font-size: 11px; color: #991b1b; border-radius: 4px;">
                            <strong>⚠️ Document Discrepancy:</strong> ${item.conflict_notes.map(n => escapeHtml(n)).join("<br>")}
                        </div>
                    `;
                }

                html += `
                    <div class="scheme-card" data-scheme-id="${schemeId}">
                        <div class="scheme-card-header">
                            <h3>${title}</h3>
                            <div class="scheme-ministry">${dept}</div>
                            <div class="scheme-badges-row">
                                <span class="badge-rule-mismatch">${t("schemes.badgeRuleMismatch", {}, "Rule Review Needed")}</span>
                                ${statusBadges.appStatusBadge}
                                ${statusBadges.deadlineBadge}
                                ${statusBadges.verificationBadge}
                                ${docReadinessBadgeHtml}
                                <span class="badge-tag">${cat}</span>
                            </div>
                        </div>

                        <div class="scheme-card-body">
                            <p class="scheme-description">${desc}</p>
                            <div class="scheme-meta-item" style="color: #c2410c;">
                                <strong>Evaluation Status:</strong> ${item.failed_conditions_count} rule(s) do not match profile
                            </div>
                            ${conflictNotesHtml}
                        </div>

                        <div class="scheme-card-footer">
                            <button type="button" class="btn-scheme-details btn-view-details" data-id="${schemeId}">
                                ${t("schemes.btnDetails", {}, "Scheme Details")}
                            </button>
                            <button type="button" class="btn-scheme-eligibility btn-view-eligibility" data-id="${schemeId}" style="background: #9a3412; border-color: #9a3412;">
                                ${t("schemes.btnMismatches", {}, "View Mismatches")}
                            </button>
                            ${isClosed ? `
                                <button type="button" class="btn-scheme-apply btn-apply-closed" data-id="${schemeId}" data-closed="true" disabled style="background: #94a3b8; border-color: #94a3b8; color: #ffffff; cursor: not-allowed; opacity: 0.85;" title="${t("deadlines.statusClosed", {}, "Applications Closed")}">
                                    ${t("deadlines.statusClosed", {}, "Applications Closed")}
                                </button>
                            ` : `
                                <button type="button" class="btn-scheme-apply btn-apply-now" data-id="${schemeId}">
                                    ${t("schemes.btnApplyNow", {}, "Apply Now")}
                                </button>
                            `}
                        </div>
                    </div>
                `;
            });
            html += "</div>";
        }
        html += "</div>";

        schemesContainer.innerHTML = html;
        attachCardActionListeners();
    }

    /**
     * Renders all schemes from the catalog with search & attribute filters (Step 3).
     */
    function renderCatalog(schemes) {
        clearSchemesAlert();
        schemesContainer.innerHTML = "";

        if (!schemes || schemes.length === 0) {
            schemesContainer.innerHTML = `
                <div class="empty-state-notice" style="padding: 36px 20px; text-align: center;">
                    <div style="font-size: 32px; margin-bottom: 8px;">🔍</div>
                    <p style="font-size: 16px; font-weight: 700; color: #334155; margin-bottom: 6px;">${t("schemes.emptyCatalogTitle", {}, "No Government Schemes Found")}</p>
                    <p style="font-size: 14px; color: #64748b; max-width: 480px; margin: 0 auto 16px auto; line-height: 1.5;">
                        ${t("schemes.emptyCatalogDesc", {}, "No schemes matched your search query or selected filters. Try broadening your keywords or clearing filters.")}
                    </p>
                    <button type="button" id="btnClearSearchFilters" class="btn btn-secondary" style="padding: 8px 16px; font-size: 13px;">
                        ${t("schemes.clearFiltersBtn", {}, "Clear All Filters")}
                    </button>
                </div>
            `;
            const clearBtn = document.getElementById("btnClearSearchFilters");
            if (clearBtn) {
                clearBtn.addEventListener("click", () => {
                    if (btnResetFilters) btnResetFilters.click();
                });
            }
            return;
        }

        let html = '<div class="schemes-cards-list">';
        schemes.forEach((s) => {
            const schemeId = escapeHtml(s.scheme_id);
            const title = escapeHtml(s.current_official_name || s.scheme_name);
            const dept = escapeHtml(s.department || s.responsible_ministry || "Government of India");
            const desc = escapeHtml(s.description || s.scheme_description || "");
            const cat = escapeHtml(s.category || "General");
            const appType = escapeHtml(s.application_type || "Fresh Application");

            const statusBadges = getSchemeStatusBadges(s, null);
            const dStatus = s.deadline_status || s.application_status || "NOT_ANNOUNCED";
            const isClosed = (dStatus === "CLOSED") || (s.is_currently_open === false && dStatus !== "YEAR_ROUND" && dStatus !== "NEEDS_LIVE_VERIFICATION" && dStatus !== "QUOTA_DEPENDENT");
            const lastDate = s.application_last_date || "";
            const cycle = s.application_cycle || "AY 2026-27";

            let deadlineRowHtml = "";

            if (dStatus === "OPEN") {
                deadlineRowHtml = `<div class="deadline-info-row"><strong>${t("deadlines.lastDate", { date: lastDate }, `Last Date: ${lastDate}`)}</strong> <span>(${cycle})</span></div>`;
            } else if (dStatus === "CLOSED") {
                deadlineRowHtml = `<div class="deadline-info-row"><span>${t("deadlines.closedAdvisory", { cycle: cycle, date: lastDate }, `Closed on ${lastDate}`)}</span></div>`;
            } else if (dStatus === "UPCOMING") {
                const startD = s.application_start_date || "";
                deadlineRowHtml = `<div class="deadline-info-row"><span>${t("deadlines.startDate", { date: startD }, `Starts: ${startD}`)}</span></div>`;
            } else if (dStatus === "YEAR_ROUND") {
                deadlineRowHtml = `<div class="deadline-info-row"><strong>Cycle:</strong> <span>Open year-round (No fixed closing date)</span></div>`;
            } else if (dStatus === "NEEDS_LIVE_VERIFICATION") {
                deadlineRowHtml = `<div class="deadline-info-row"><strong>Availability:</strong> <span>Subject to live check & target allocations</span></div>`;
            } else if (dStatus === "QUOTA_DEPENDENT") {
                deadlineRowHtml = `<div class="deadline-info-row"><strong>Availability:</strong> <span>Subject to quota availability</span></div>`;
            }

            let targetText = "";
            if (s.target_beneficiaries && s.target_beneficiaries.length > 0) {
                targetText = escapeHtml(s.target_beneficiaries.join(", "));
            }

            let incomeLimitText = "";
            if (s.max_annual_income) {
                const incomeFormatted = formatCurrency(s.max_annual_income);
                incomeLimitText = `<div class="scheme-meta-item"><strong>${t("schemes.incomeLimit", {}, "Income Limit:")}</strong> ${t("schemes.incomeLimitValue", { amount: incomeFormatted }, `Up to ${incomeFormatted}/yr`)}</div>`;
            }

            html += `
                <div class="scheme-card" data-scheme-id="${schemeId}">
                    <div class="scheme-card-header">
                        <h3>${title}</h3>
                        <div class="scheme-ministry">${dept}</div>
                        <div class="scheme-badges-row">
                            <span class="badge-tag">${cat}</span>
                            ${statusBadges.appStatusBadge}
                            ${statusBadges.deadlineBadge}
                            ${statusBadges.verificationBadge}
                        </div>
                    </div>

                    <div class="scheme-card-body">
                        <p class="scheme-description">${desc}</p>
                        ${deadlineRowHtml}
                        <div class="scheme-meta-grid" style="margin-top: 10px; display: grid; gap: 4px; font-size: 12px; color: #475569;">
                            <div class="scheme-meta-item"><strong>Application Type:</strong> ${appType}</div>
                            ${incomeLimitText}
                            ${targetText ? `<div class="scheme-meta-item"><strong>Beneficiary Group:</strong> ${targetText}</div>` : ""}
                        </div>
                    </div>

                    <div class="scheme-card-footer">
                        <button type="button" class="btn-scheme-details btn-view-details" data-id="${schemeId}">
                            ${t("schemes.btnDetails", {}, "Scheme Details")}
                        </button>
                        <button type="button" class="btn-scheme-eligibility btn-view-eligibility" data-id="${schemeId}">
                            ${t("detailsModal.checkEligibilityBtn", {}, "Check My Eligibility")}
                        </button>
                        ${isClosed ? `
                            <button type="button" class="btn-scheme-apply btn-apply-closed" data-id="${schemeId}" data-closed="true" disabled style="background: #94a3b8; border-color: #94a3b8; color: #ffffff; cursor: not-allowed; opacity: 0.85;" title="${t("deadlines.statusClosed", {}, "Applications Closed")}">
                                ${t("deadlines.statusClosed", {}, "Applications Closed")}
                            </button>
                        ` : `
                            <button type="button" class="btn-scheme-apply btn-apply-now" data-id="${schemeId}">
                                ${t("schemes.btnApplyNow", {}, "Apply Now")}
                            </button>
                        `}
                    </div>
                </div>
            `;
        });
        html += "</div>";

        schemesContainer.innerHTML = html;
        attachCardActionListeners();
    }

    /**
     * Attaches click handlers to dynamically created card action buttons.
     */
    function attachCardActionListeners() {
        const detailBtns = schemesContainer.querySelectorAll(".btn-view-details");
        detailBtns.forEach((btn) => {
            btn.addEventListener("click", () => {
                const schemeId = btn.getAttribute("data-id");
                if (schemeId) openSchemeDetails(schemeId, btn);
            });
        });

        const eligBtns = schemesContainer.querySelectorAll(".btn-view-eligibility");
        eligBtns.forEach((btn) => {
            btn.addEventListener("click", () => {
                const schemeId = btn.getAttribute("data-id");
                if (schemeId) {
                    const appType = applicationTypeSelect ? applicationTypeSelect.value : "FRESH";
                    openDetailedEligibility(schemeId, appType, btn);
                }
            });
        });

        const reviewDocLinks = schemesContainer.querySelectorAll(".action-review-doc-link");
        reviewDocLinks.forEach((link) => {
            link.addEventListener("click", () => {
                const docId = link.getAttribute("data-doc-id");
                if (docId) openReviewModal(docId);
            });
        });

        const applyBtns = schemesContainer.querySelectorAll(".btn-apply-now");
        applyBtns.forEach((btn) => {
            btn.addEventListener("click", () => {
                const schemeId = btn.getAttribute("data-id");
                if (schemeId) handleApplyNowClick(schemeId, btn);
            });
        });
    }

    // ---------------------------------------------------------------------------
    // Scheme Discovery: Data Fetching Controllers
    // ---------------------------------------------------------------------------

    /**
     * Loads personalized scheme recommendations from GET /schemes/recommendations.
     */
    async function loadRecommendations(applicationType = "FRESH") {
        if (isGuestMode) {
            schemesContainer.innerHTML = `
                <div class="empty-state-notice" style="padding: 36px 24px; text-align: center;">
                    <div style="font-size: 32px; margin-bottom: 12px;">🎯</div>
                    <h3 style="font-size: 18px; color: #1e293b; margin-bottom: 8px;">Profile-Based Scheme Discovery</h3>
                    <p style="font-size: 14px; color: #64748b; max-width: 520px; margin: 0 auto 20px auto; line-height: 1.5;">
                        Create an account to save your profile and receive personalized scheme recommendations.
                    </p>
                    <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                        <a href="signup.html" class="btn btn-primary" style="padding: 9px 18px; font-size: 13px; text-decoration: none;">Sign Up</a>
                        <button type="button" id="btnPromptViewCatalog" class="btn btn-secondary" style="padding: 9px 18px; font-size: 13px;">
                            Direct Scheme Search
                        </button>
                    </div>
                </div>
            `;
            const catalogBtn = document.getElementById("btnPromptViewCatalog");
            if (catalogBtn) {
                catalogBtn.addEventListener("click", () => switchTab("catalog"));
            }
            return;
        }

        schemesContainer.innerHTML = '<div class="empty-state-notice">Evaluating personalized scheme recommendations...</div>';
        clearSchemesAlert();

        try {
            const params = new URLSearchParams();
            if (applicationType) params.set("application_type", applicationType);
            params.set("include_cross_sector", "true");
            const response = await apiFetch(`/schemes/recommendations?${params.toString()}`);

            if (!response.ok) {
                if (response.status === 401) {
                    window.location.href = "login.html";
                    return;
                }
                if (response.status === 403) {
                    schemesContainer.innerHTML = `
                        <div class="empty-state-notice" style="padding: 36px 24px; text-align: center;">
                            <div style="font-size: 32px; margin-bottom: 12px;">🎯</div>
                            <h3 style="font-size: 18px; color: #1e293b; margin-bottom: 8px;">Profile-Based Scheme Discovery</h3>
                            <p style="font-size: 14px; color: #64748b; max-width: 520px; margin: 0 auto 20px auto; line-height: 1.5;">
                                Create an account to save your profile and receive personalized scheme recommendations.
                            </p>
                            <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                                <a href="signup.html" class="btn btn-primary" style="padding: 9px 18px; font-size: 13px; text-decoration: none;">Sign Up</a>
                                <button type="button" id="btnPromptViewCatalog403" class="btn btn-secondary" style="padding: 9px 18px; font-size: 13px;">
                                    Direct Scheme Search
                                </button>
                            </div>
                        </div>
                    `;
                    const catalogBtn403 = document.getElementById("btnPromptViewCatalog403");
                    if (catalogBtn403) {
                        catalogBtn403.addEventListener("click", () => switchTab("catalog"));
                    }
                    return;
                }
                if (response.status === 404) {
                    window.location.href = "profile.html";
                    return;
                }
                showSchemesAlert(response.error || "Unable to evaluate recommendations.", "error");
                schemesContainer.innerHTML = '<div class="empty-state-notice">Failed to load recommendations. Please try again.</div>';
                return;
            }

            lastLoadedRecommendationsData = response.data;
            renderRecommendations(response.data);
        } catch (err) {
            console.error("Recommendations fetch error:", err);
            showSchemesAlert("Failed to connect to recommendation engine. Please check backend server.");
            schemesContainer.innerHTML = '<div class="empty-state-notice">Failed to connect to recommendation engine.</div>';
        }
    }

    /**
     * Loads catalog schemes from GET /schemes with search query & attribute filters.
     */
    async function loadCatalog(filters = {}) {
        schemesContainer.innerHTML = '<div class="empty-state-notice">Searching government schemes catalog...</div>';
        clearSchemesAlert();

        const params = new URLSearchParams();
        if (filters.q) params.set("q", filters.q.trim());
        if (filters.category) params.set("category", filters.category.trim());
        if (filters.education_level) params.set("education_level", filters.education_level.trim());
        if (filters.beneficiary_group) params.set("beneficiary_group", filters.beneficiary_group.trim());
        params.set("include_cross_sector", "true");

        const queryString = `?${params.toString()}`;

        try {
            const response = await apiFetch(`/schemes${queryString}`);

            if (!response.ok) {
                showSchemesAlert(response.error || "Unable to retrieve scheme catalog.", "error");
                schemesContainer.innerHTML = '<div class="empty-state-notice">Failed to load schemes catalog. Please try again.</div>';
                return;
            }

            const schemes = response.data && response.data.schemes ? response.data.schemes : [];
            lastLoadedCatalogData = schemes;
            renderCatalog(schemes);
        } catch (err) {
            console.error("Catalog fetch error:", err);
            showSchemesAlert("Failed to connect to scheme discovery service.");
            schemesContainer.innerHTML = '<div class="empty-state-notice">Failed to connect to scheme discovery service.</div>';
        }
    }

    /**
     * Fetches and displays comprehensive scheme information in Details Modal.
     */
    async function openSchemeDetails(schemeId, triggerEl = null) {
        currentModalSchemeId = schemeId;
        openModal(schemeDetailsModal, triggerEl);

        detailsModalTitle.textContent = "Loading Scheme Details...";
        detailsModalVerification.innerHTML = "";
        detailsModalDepartment.textContent = "--";
        detailsModalCategory.textContent = "--";
        detailsModalDescription.textContent = "--";
        detailsModalBenefits.innerHTML = "--";
        if (detailsModalEligibility) detailsModalEligibility.innerHTML = "--";
        detailsModalDocuments.innerHTML = "";
        detailsModalProcess.innerHTML = "--";
        detailsModalLinks.innerHTML = "";

        if (detailsApplyNowBtn) {
            detailsApplyNowBtn.disabled = false;
            detailsApplyNowBtn.removeAttribute("data-closed");
            detailsApplyNowBtn.textContent = t("schemes.btnApplyNow", {}, "Apply Now");
            detailsApplyNowBtn.style.background = "";
            detailsApplyNowBtn.style.borderColor = "";
            detailsApplyNowBtn.style.color = "";
            detailsApplyNowBtn.style.cursor = "";
            detailsApplyNowBtn.style.opacity = "";
            detailsApplyNowBtn.title = "";
        }

        try {
            const response = await apiFetch(`/schemes/${encodeURIComponent(schemeId)}`);

            if (!response.ok) {
                detailsModalTitle.textContent = "Error Loading Details";
                detailsModalDescription.textContent = response.error || "Could not retrieve scheme details.";
                return;
            }

            const scheme = response.data && response.data.scheme ? response.data.scheme : {};
            const title = scheme.current_official_name || scheme.scheme_name || scheme.title || schemeId;
            const dept = scheme.department || scheme.responsible_ministry || "Ministry of Education / Government of India";
            const cat = scheme.category || "General";
            const target = (scheme.target_beneficiaries && scheme.target_beneficiaries.join(", ")) || "Citizens";
            const desc = scheme.scheme_description || scheme.description || "No official description provided.";

            detailsModalTitle.textContent = title;

            // Application Schedule & Deadline Section
            const d = scheme.deadline || {};
            const dStatus = scheme.deadline_status || d.status || "NOT_ANNOUNCED";
            const lastDate = scheme.application_last_date || d.application_last_date || "--";
            const startDate = scheme.application_start_date || d.application_start_date || "--";
            const cycle = scheme.application_cycle || d.application_cycle || "AY 2026-27";
            const instDeadline = scheme.institute_verification_deadline || d.institute_verification_deadline || "--";
            const nodalDeadline = scheme.nodal_verification_deadline || d.nodal_verification_deadline || "--";
            const nextCycle = scheme.next_cycle_status || d.next_cycle_status || "NOT_ANNOUNCED";
            const dSource = scheme.deadline_source || d.deadline_source || "National Scholarship Portal";
            const verifiedAt = scheme.deadline_verified_at || d.deadline_verified_at || "--";

            // Update details modal Apply Now button based on scheme deadline
            if (detailsApplyNowBtn) {
                const isClosed = (dStatus === "CLOSED") || (scheme.is_currently_open === false && dStatus !== "YEAR_ROUND" && dStatus !== "NEEDS_LIVE_VERIFICATION" && dStatus !== "QUOTA_DEPENDENT");
                if (isClosed) {
                    detailsApplyNowBtn.disabled = true;
                    detailsApplyNowBtn.setAttribute("data-closed", "true");
                    detailsApplyNowBtn.textContent = t("deadlines.statusClosed", {}, "Applications Closed");
                    detailsApplyNowBtn.style.background = "#94a3b8";
                    detailsApplyNowBtn.style.borderColor = "#94a3b8";
                    detailsApplyNowBtn.style.color = "#ffffff";
                    detailsApplyNowBtn.style.cursor = "not-allowed";
                    detailsApplyNowBtn.style.opacity = "0.85";
                    detailsApplyNowBtn.title = "Applications for this scheme are currently closed";
                } else {
                    detailsApplyNowBtn.disabled = false;
                    detailsApplyNowBtn.removeAttribute("data-closed");
                    detailsApplyNowBtn.textContent = t("schemes.btnApplyNow", {}, "Apply Now");
                    detailsApplyNowBtn.style.background = "";
                    detailsApplyNowBtn.style.borderColor = "";
                    detailsApplyNowBtn.style.color = "";
                    detailsApplyNowBtn.style.cursor = "";
                    detailsApplyNowBtn.style.opacity = "";
                    detailsApplyNowBtn.title = "";
                }
            }

            let schedBadge = "";
            let displayLastDate = lastDate;

            if (dStatus === "OPEN") {
                schedBadge = `<span class="badge-app-status badge-app-status-open">🟢 ${t("deadlines.statusOpen", {}, "Applications Open")}</span>`;
            } else if (dStatus === "CLOSED") {
                schedBadge = `<span class="badge-app-status badge-app-status-closed">🔴 ${t("deadlines.statusClosed", {}, "Applications Closed")}</span>`;
                displayLastDate = lastDate !== "--" ? `Closed: ${lastDate}` : "Closed";
            } else if (dStatus === "UPCOMING") {
                schedBadge = `<span class="badge-app-status badge-app-status-upcoming">🔵 ${t("deadlines.badgeUpcoming", {}, "Opening Soon")}</span>`;
            } else if (dStatus === "YEAR_ROUND") {
                schedBadge = `<span class="badge-app-status badge-app-status-year-round">${t("schemes.statusYearRound", {}, "Open Year-round")}</span>`;
                displayLastDate = t("deadlines.noFixedClosingDate", {}, "No Fixed Closing Date");
            } else if (dStatus === "NEEDS_LIVE_VERIFICATION") {
                schedBadge = `<span class="badge-app-status badge-app-status-needs-verification">${t("schemes.statusNeedsLiveVerification", {}, "Availability Needs Live Check")}</span>`;
                displayLastDate = t("deadlines.noFixedDeadlineEstablished", {}, "No Fixed Deadline Established");
            } else if (dStatus === "QUOTA_DEPENDENT") {
                schedBadge = `<span class="badge-app-status badge-app-status-quota">${t("schemes.statusQuotaDependent", {}, "Check Quota Availability")}</span>`;
                displayLastDate = t("deadlines.noFixedDeadlineEstablished", {}, "No Fixed Deadline Established");
            } else {
                schedBadge = `<span class="badge-deadline-status badge-deadline-unconfirmed">${t("deadlines.deadlineNotConfirmed", {}, "Deadline Not Confirmed")}</span>`;
                displayLastDate = t("deadlines.deadlineNotConfirmed", {}, "Deadline Not Confirmed");
            }

            const scheduleCardHtml = `
                <div class="deadline-schedule-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
                        <strong style="color: #0f172a; font-size: 13px;">${t("deadlines.scheduleHeading", {}, "Application Schedule & Deadlines")}</strong>
                        ${schedBadge}
                    </div>
                    <div class="deadline-schedule-grid">
                        <div class="deadline-schedule-item">
                            <span class="deadline-schedule-label">${t("deadlines.cycle", { cycle: "" }, "Cycle").replace(":", "")}</span>
                            <span class="deadline-schedule-val">${escapeHtml(cycle)}</span>
                        </div>
                        <div class="deadline-schedule-item">
                            <span class="deadline-schedule-label">${t("deadlines.startDate", { date: "" }, "Opening Date").replace(":", "")}</span>
                            <span class="deadline-schedule-val">${escapeHtml(startDate)}</span>
                        </div>
                        <div class="deadline-schedule-item">
                            <span class="deadline-schedule-label">${t("deadlines.lastDate", { date: "" }, "Student Last Date").replace(":", "")}</span>
                            <span class="deadline-schedule-val">${escapeHtml(displayLastDate)}</span>
                        </div>
                        <div class="deadline-schedule-item">
                            <span class="deadline-schedule-label">${t("deadlines.instituteDeadline", { date: "" }, "Institute Verification").replace(":", "")}</span>
                            <span class="deadline-schedule-val">${escapeHtml(instDeadline)}</span>
                        </div>
                        <div class="deadline-schedule-item">
                            <span class="deadline-schedule-label">${t("deadlines.nodalDeadline", { date: "" }, "Nodal Verification").replace(":", "")}</span>
                            <span class="deadline-schedule-val">${escapeHtml(nodalDeadline)}</span>
                        </div>
                        <div class="deadline-schedule-item">
                            <span class="deadline-schedule-label">${t("deadlines.nextCycle", { status: "" }, "Next Cycle").replace(":", "")}</span>
                            <span class="deadline-schedule-val">${escapeHtml(nextCycle)}</span>
                        </div>
                    </div>
                    <div style="margin-top: 10px; font-size: 11px; color: #64748b; border-top: 1px dashed #cbd5e1; padding-top: 6px;">
                        ${t("deadlines.scheduleSource", { source: escapeHtml(dSource) }, `Source: ${escapeHtml(dSource)}`)} (${t("deadlines.verifiedAsOf", { date: escapeHtml(verifiedAt) }, `Verified: ${escapeHtml(verifiedAt)}`)})
                    </div>
                </div>
            `;

            let verificationNoticeHtml = "";
            if (scheme.is_verified === true) {
                verificationNoticeHtml = `
                    <div style="margin: 0; padding: 10px 14px; background: #ecfdf5; border-left: 3px solid #10b981; font-size: 12px; color: #065f46; border-radius: 4px;">
                        <strong>✓ Information Verified:</strong> Official scheme parameters have been verified against active government gazettes.
                    </div>
                `;
            } else {
                verificationNoticeHtml = `
                    <div style="margin: 0; padding: 10px 14px; background: #f8fafc; border-left: 3px solid #3b82f6; font-size: 12px; color: #334155; border-radius: 4px;">
                        <strong>Official Scheme Record:</strong> Compiled from published government guidelines and official portal notifications.
                    </div>
                `;
            }

            detailsModalVerification.innerHTML = `
                ${scheduleCardHtml}
                ${verificationNoticeHtml}
            `;

            detailsModalDepartment.textContent = dept;
            detailsModalCategory.textContent = `${cat} — Target: ${target}`;
            detailsModalDescription.textContent = desc;

            // Benefits breakdown
            if (scheme.benefits) {
                const b = scheme.benefits;
                let bHtml = `<p><strong>Disbursement:</strong> ${escapeHtml(b.disbursement_frequency || b.payment_frequency || "Direct Benefit Transfer (DBT)")}</p>`;
                if (b.maximum_benefit) {
                    bHtml += `<p><strong>Coverage:</strong> ${escapeHtml(b.maximum_benefit)}</p>`;
                } else if (b.amount_annual) {
                    bHtml += `<p><strong>Financial Assistance:</strong> ${formatCurrency(b.amount_annual)} per annum</p>`;
                }
                detailsModalBenefits.innerHTML = bHtml;
            } else {
                detailsModalBenefits.textContent = "Financial assistance as per official scheme guidelines.";
            }

            // Eligibility Requirements & Criteria breakdown
            if (detailsModalEligibility) {
                let eligHtml = "";
                if (scheme.eligibility) {
                    const e = scheme.eligibility;
                    const items = [];
                    if (e.annual_family_income_limit || e.max_annual_income) {
                        const inc = e.annual_family_income_limit || e.max_annual_income;
                        items.push(`<li><strong>Income Limit:</strong> Up to ${formatCurrency(inc)} / year</li>`);
                    }
                    if (e.education_requirement) {
                        items.push(`<li><strong>Education Requirement:</strong> ${escapeHtml(e.education_requirement)}</li>`);
                    }
                    if (e.course_requirement) {
                        items.push(`<li><strong>Eligible Courses:</strong> ${escapeHtml(e.course_requirement)}</li>`);
                    }
                    if (e.minimum_marks_requirement) {
                        items.push(`<li><strong>Minimum Marks / Percentile:</strong> ${escapeHtml(e.minimum_marks_requirement)}</li>`);
                    }
                    if (e.gender_requirement && e.gender_requirement !== "ALL") {
                        items.push(`<li><strong>Gender:</strong> ${escapeHtml(e.gender_requirement)}</li>`);
                    }
                    if (e.disability_requirement) {
                        items.push(`<li><strong>Disability Criteria:</strong> ${escapeHtml(e.disability_requirement)}</li>`);
                    }
                    if (e.category_requirement && Array.isArray(e.category_requirement)) {
                        items.push(`<li><strong>Eligible Categories:</strong> ${escapeHtml(e.category_requirement.join(", "))}</li>`);
                    }
                    if (scheme.target_beneficiaries && Array.isArray(scheme.target_beneficiaries) && scheme.target_beneficiaries.length > 0) {
                        items.push(`<li><strong>Target Beneficiaries:</strong> ${escapeHtml(scheme.target_beneficiaries.join("; "))}</li>`);
                    }
                    if (e.state_residency_requirement && Array.isArray(e.state_residency_requirement)) {
                        items.push(`<li><strong>Applicable States:</strong> ${escapeHtml(e.state_residency_requirement.join(", "))}</li>`);
                    }
                    if (e.structured_rules && e.structured_rules.length > 0) {
                        e.structured_rules.forEach((r) => {
                            if (r.explanation) {
                                items.push(`<li>${escapeHtml(r.explanation)}</li>`);
                            }
                        });
                    }
                    if (items.length > 0) {
                        eligHtml = `<ul style="margin-left: 20px; font-size: 13px; line-height: 1.6;">${items.join("")}</ul>`;
                    }
                }
                if (!eligHtml) {
                    eligHtml = `<p style="font-size: 13px; color: #475569;">${escapeHtml(scheme.eligibility_criteria || scheme.criteria || "Eligibility criteria as per official ministry guidelines.")}</p>`;
                }
                detailsModalEligibility.innerHTML = eligHtml;
            }

            // Documents required list (DOM constructed for XSS safety)
            detailsModalDocuments.innerHTML = "";
            if (scheme.required_documents && scheme.required_documents.length > 0) {
                scheme.required_documents.forEach((doc) => {
                    const docName = doc.document_name || doc.name || String(doc);
                    const docType = doc.mandatory_or_optional || doc.requirement_type || "MANDATORY";
                    const isMandatory = docType === "MANDATORY";

                    const li = document.createElement("li");
                    li.style.marginBottom = "6px";

                    const strong = document.createElement("strong");
                    strong.textContent = docName;
                    li.appendChild(strong);

                    const badge = document.createElement("span");
                    badge.className = isMandatory ? "badge-preliminary-match" : "badge-tag";
                    badge.style.fontSize = "10px";
                    badge.style.marginLeft = "6px";
                    badge.textContent = isMandatory ? "Mandatory" : "Conditional";
                    li.appendChild(badge);

                    if (doc.applicable_condition) {
                        const conditionSpan = document.createElement("span");
                        conditionSpan.style.color = "#64748b";
                        conditionSpan.textContent = ` (${doc.applicable_condition})`;
                        li.appendChild(conditionSpan);
                    }

                    detailsModalDocuments.appendChild(li);
                });
            } else {
                const li = document.createElement("li");
                li.textContent = "Standard government identification and proof of eligibility documents.";
                detailsModalDocuments.appendChild(li);
            }

            // Application process
            detailsModalProcess.innerHTML = "";
            if (scheme.application_steps && scheme.application_steps.length > 0) {
                const ol = document.createElement("ol");
                ol.style.cssText = "margin-left: 20px; font-size: 13px;";
                scheme.application_steps.forEach((step) => {
                    const li = document.createElement("li");
                    li.style.marginBottom = "4px";
                    li.textContent = step;
                    ol.appendChild(li);
                });
                detailsModalProcess.appendChild(ol);
            } else {
                const p = document.createElement("p");
                p.textContent = scheme.application_process || "Online application through official National or State portals.";
                detailsModalProcess.appendChild(p);
            }

            // Official URLs with strict protocol verification (Step 3)
            detailsModalLinks.innerHTML = "";
            const linksList = [];
            const primaryUrl = scheme.application_url || scheme.official_application_url || scheme.official_url;
            if (isSafeUrl(primaryUrl)) {
                linksList.push({
                    title: `Official Application Portal (${primaryUrl})`,
                    url: primaryUrl,
                });
            }

            if (scheme.official_sources && Array.isArray(scheme.official_sources)) {
                scheme.official_sources.forEach((src) => {
                    const srcUrl = src.source_url || src.url || src.link || src.portal_url;
                    const srcTitle = src.source_title || src.title || src.source_type || "Official Source";
                    if (isSafeUrl(srcUrl) && srcUrl !== primaryUrl && !linksList.some((l) => l.url === srcUrl)) {
                        linksList.push({
                            title: `${srcTitle} (${srcUrl})`,
                            url: srcUrl,
                        });
                    }
                });
            }

            if (linksList.length > 0) {
                const ul = document.createElement("ul");
                ul.style.cssText = "list-style: none; padding: 0; margin: 0;";
                linksList.forEach((item) => {
                    const li = document.createElement("li");
                    li.style.marginBottom = "8px";
                    const link = document.createElement("a");
                    link.href = item.url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.style.cssText = "color: #17458c; font-weight: 600; font-size: 13px; text-decoration: underline;";
                    link.textContent = `${item.title} \u2192`;
                    li.appendChild(link);
                    ul.appendChild(li);
                });
                detailsModalLinks.appendChild(ul);
            }

        } catch (err) {
            console.error("Open details modal error:", err);
            detailsModalTitle.textContent = "Error";
            detailsModalDescription.textContent = "Failed to communicate with scheme registry.";
        }
    }

    /**
     * Tailors the on-demand manual assessment inputs so we ask ONLY for
     * the specific criteria evaluated by the selected scheme (Step 3).
     */
    function configureManualAssessmentForm(schemeId) {
        if (!anonEligibilitySection) return;
        anonEligibilitySection.style.display = "block";

        const wrappers = [
            wrapperAnonIncome,
            wrapperAnonGender,
            wrapperAnonCaste,
            wrapperAnonDisability,
            wrapperAnonVulnerable,
            wrapperAnonAge,
        ];
        wrappers.forEach((w) => { if (w) w.style.display = "none"; });

        if (schemeId === "SCHEME_EDU_001_PM_USP_CSSS") {
            if (wrapperAnonIncome) wrapperAnonIncome.style.display = "block";
            if (labelAnonIncome) labelAnonIncome.textContent = "Annual Family Income (₹) [Scheme Limit: Up to ₹4,50,000]";
        } else if (schemeId === "SCHEME_EDU_002_AICTE_PRAGATI") {
            if (wrapperAnonIncome) wrapperAnonIncome.style.display = "block";
            if (labelAnonIncome) labelAnonIncome.textContent = "Annual Family Income (₹) [Scheme Limit: Up to ₹8,00,000]";
            if (wrapperAnonGender) wrapperAnonGender.style.display = "block";
        } else if (schemeId === "SCHEME_EDU_003_AICTE_SAKSHAM") {
            if (wrapperAnonIncome) wrapperAnonIncome.style.display = "block";
            if (labelAnonIncome) labelAnonIncome.textContent = "Annual Family Income (₹) [Scheme Limit: Up to ₹8,00,000]";
            if (wrapperAnonDisability) wrapperAnonDisability.style.display = "block";
        } else if (schemeId === "SCHEME_EDU_004_AICTE_SWANATH") {
            if (wrapperAnonIncome) wrapperAnonIncome.style.display = "block";
            if (labelAnonIncome) labelAnonIncome.textContent = "Annual Family Income (₹) [Scheme Limit: Up to ₹8,00,000]";
            if (wrapperAnonVulnerable) wrapperAnonVulnerable.style.display = "block";
        } else if (schemeId === "SCHEME_EDU_005_TOP_CLASS_SC") {
            if (wrapperAnonIncome) wrapperAnonIncome.style.display = "block";
            if (labelAnonIncome) labelAnonIncome.textContent = "Annual Family Income (₹) [Scheme Limit: Up to ₹8,00,000]";
            if (wrapperAnonCaste) wrapperAnonCaste.style.display = "block";
        } else {
            if (wrapperAnonIncome) wrapperAnonIncome.style.display = "block";
            if (wrapperAnonAge) wrapperAnonAge.style.display = "block";
        }
    }

    /**
     * Evaluates and displays deterministic rule breakdown in Eligibility Modal.
     */
    async function openDetailedEligibility(schemeId, applicationType = "FRESH", triggerEl = null) {
        currentModalSchemeId = schemeId;
        openModal(schemeEligibilityModal, triggerEl);

        eligibilityStatusBanner.innerHTML = "";
        eligibilitySummaryText.textContent = "";
        eligibilityMissingSection.style.display = "none";
        eligibilityMissingList.innerHTML = "";
        eligibilityMatchedSection.style.display = "none";
        eligibilityMatchedList.innerHTML = "";
        eligibilityFailedSection.style.display = "none";
        eligibilityFailedList.innerHTML = "";
        eligibilityUnknownSection.style.display = "none";
        eligibilityUnknownList.innerHTML = "";

        const docReadinessSection = document.getElementById("eligibilityDocumentsSection");
        const docReadinessList = document.getElementById("eligibilityDocumentsList");
        const docReadinessBadge = document.getElementById("eligibilityDocReadinessBadge");
        if (docReadinessSection) docReadinessSection.style.display = "none";
        if (docReadinessList) docReadinessList.innerHTML = "";

        if (btnCancelAnonEvaluation) {
            btnCancelAnonEvaluation.onclick = () => {
                if (anonEligibilitySection) anonEligibilitySection.style.display = "none";
            };
        }

        const tempProfile = (guestContextData && guestContextData.temporary_profile) || {};
        const hasCriteria = tempProfile && (tempProfile.age || tempProfile.annual_income || tempProfile.annual_family_income || tempProfile.gender || tempProfile.caste_category || tempProfile.disability_percentage);

        if (isGuestMode && !hasCriteria) {
            // Anonymous mode without criteria: Show tailored on-demand optional assessment form
            eligibilityModalTitle.textContent = "Check Eligibility: Optional Self-Assessment";
            configureManualAssessmentForm(schemeId);
            eligibilitySummaryText.innerHTML = `
                <p style="font-size: 13px; color: #475569; margin: 0 0 10px 0;">
                    To evaluate automated rules for this scheme, provide the basic criteria required below. You may also close this dialog at any time.
                </p>
            `;

            if (btnRunAnonEvaluation) {
                btnRunAnonEvaluation.onclick = async () => {
                    const ageVal = anonInputAge && anonInputAge.value ? parseInt(anonInputAge.value, 10) : 20;
                    const incomeVal = anonInputIncome && anonInputIncome.value ? parseFloat(anonInputIncome.value) : null;
                    const genderVal = anonInputGender && anonInputGender.value ? anonInputGender.value : "ALL";
                    const casteVal = anonInputCaste && anonInputCaste.value ? anonInputCaste.value : "GENERAL";
                    const disabilityVal = anonInputDisability && anonInputDisability.value === "YES" ? 40 : 0;
                    const isVulnerable = anonInputVulnerable && anonInputVulnerable.value !== "NONE";

                    const updatedProfile = {
                        full_name: "Anonymous Citizen",
                        age: ageVal,
                        gender: genderVal,
                        annual_income: incomeVal,
                        annual_family_income: incomeVal,
                        caste_category: casteVal,
                        social_category: casteVal,
                        disability_percentage: disabilityVal,
                        vulnerable_category_eligible: isVulnerable,
                        occupation: "Student",
                        pursuing_regular_course: true,
                        course_mode: "REGULAR",
                    };

                    btnRunAnonEvaluation.disabled = true;
                    btnRunAnonEvaluation.textContent = "Evaluating...";

                    try {
                        const updateRes = await apiFetch("/auth/guest/context", {
                            method: "POST",
                            body: JSON.stringify({ temporary_profile: updatedProfile }),
                        });

                        if (updateRes.ok) {
                            guestContextData.temporary_profile = updatedProfile;
                            if (anonEligibilitySection) anonEligibilitySection.style.display = "none";
                            await openDetailedEligibility(schemeId, applicationType, triggerEl);
                        } else {
                            alert(updateRes.error || "Failed to update criteria for evaluation.");
                        }
                    } catch (err) {
                        console.error("Evaluation submission error:", err);
                    } finally {
                        btnRunAnonEvaluation.disabled = false;
                        btnRunAnonEvaluation.textContent = "Evaluate Eligibility";
                    }
                };
            }
            return;
        }

        if (anonEligibilitySection) anonEligibilitySection.style.display = "none";
        eligibilityModalTitle.textContent = "Evaluating Criteria...";
        eligibilitySummaryText.textContent = "Executing deterministic rule evaluation against criteria...";

        try {
            const query = applicationType ? `?application_type=${encodeURIComponent(applicationType)}` : "";
            const response = await apiFetch(`/schemes/${encodeURIComponent(schemeId)}/eligibility${query}`);

            if (!response.ok) {
                if (response.status === 401) {
                    window.location.href = "login.html";
                    return;
                }
                if (response.status === 404 && isGuestMode) {
                    if (anonEligibilitySection) anonEligibilitySection.style.display = "block";
                    eligibilityModalTitle.textContent = "Check Eligibility: Optional Self-Assessment";
                    eligibilitySummaryText.textContent = "Please provide evaluation criteria below to check deterministic rules:";
                    return;
                }
                eligibilityModalTitle.textContent = "Evaluation Error";
                eligibilitySummaryText.textContent = response.error || "Unable to evaluate eligibility rules.";
                return;
            }

            const data = response.data || {};
            const schemeName = data.scheme_name || schemeId;
            const ruleMatch = data.rule_match_status || "UNKNOWN";

            eligibilityModalTitle.textContent = t("eligibilityModal.titleForScheme", { scheme: schemeName }, `Eligibility: ${schemeName}`);

            // Prominent Safeguard Banner
            eligibilityStatusBanner.innerHTML = `
                <div class="unverified-safeguard-banner" style="margin: 0;">
                    ${t("schemes.safeguardNotice", {}, "<strong>Preliminary Profile Evaluation:</strong> Automated rule calculations based on your citizen profile. Official sanction requires administrative review upon application.")}
                </div>
            `;

            // Application Availability Status & Advisory
            const dStatus = data.deadline_status || data.application_status || "NOT_ANNOUNCED";
            const lastDate = data.application_last_date || "";
            const cycle = data.application_cycle || "AY 2026-27";

            let availBadgeHtml = "";
            let availBoxHtml = "";

            if (dStatus === "OPEN") {
                availBadgeHtml = `<span class="badge-deadline-open">🟢 ${t("deadlines.badgeOpen", {}, "Applications Open")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box deadline-advisory-open" style="margin-top: 8px;">${t("deadlines.openAdvisory", { cycle: cycle, date: lastDate }, `Applications for cycle ${cycle} are currently OPEN until ${lastDate}.`)}</div>`;
            } else if (dStatus === "CLOSED") {
                availBadgeHtml = `<span class="badge-deadline-closed">🔴 ${t("deadlines.badgeClosed", {}, "Applications Closed")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box deadline-advisory-closed" style="margin-top: 8px;">${t("deadlines.closedAdvisory", { cycle: cycle, date: lastDate }, `Note: Student application window for cycle ${cycle} closed on ${lastDate}. Applications are not currently open.`)}</div>`;
            } else if (dStatus === "UPCOMING") {
                availBadgeHtml = `<span class="badge-deadline-upcoming">🔵 ${t("deadlines.badgeUpcoming", {}, "Opening Soon")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box deadline-advisory-upcoming" style="margin-top: 8px;">${t("deadlines.upcomingAdvisory", { cycle: cycle, date: lastDate }, `Applications for cycle ${cycle} will open on ${lastDate}.`)}</div>`;
            } else if (dStatus === "YEAR_ROUND") {
                availBadgeHtml = `<span class="badge-app-status badge-app-status-year-round">${t("schemes.statusYearRound", {}, "Open Year-round")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box" style="background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; margin-top: 8px;">${t("deadlines.yearRoundAdvisory", {}, "Continuous application intake throughout the year. No fixed annual closing date.")}</div>`;
            } else if (dStatus === "NEEDS_LIVE_VERIFICATION") {
                availBadgeHtml = `<span class="badge-app-status badge-app-status-needs-verification">${t("schemes.statusNeedsLiveVerification", {}, "Availability Needs Live Check")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box" style="background: #fffbeb; border: 1px solid #fde68a; color: #92400e; margin-top: 8px;">${t("deadlines.needsLiveVerificationAdvisory", {}, "Application intake is open on official portal; availability subject to state/district allocations and live verification.")}</div>`;
            } else if (dStatus === "QUOTA_DEPENDENT") {
                availBadgeHtml = `<span class="badge-app-status badge-app-status-quota">${t("schemes.statusQuotaDependent", {}, "Check Quota Availability")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box" style="background: #faf5ff; border: 1px solid #e9d5ff; color: #6b21a8; margin-top: 8px;">${t("deadlines.quotaDependentAdvisory", {}, "Enrollment is active under approved government targets; availability subject to regional quota distribution.")}</div>`;
            } else {
                availBadgeHtml = `<span class="badge-deadline-neutral">⚪ ${t("deadlines.deadlineNotConfirmed", {}, "Deadline Not Confirmed")}</span>`;
                availBoxHtml = `<div class="deadline-advisory-box" style="background: #f8fafc; border: 1px solid #e2e8f0; margin-top: 8px;">${t("deadlines.notAnnouncedAdvisory", {}, "Application dates for the next cycle have not yet been announced.")}</div>`;
            }

            // Overall Status Summary
            let summaryBadge = "";
            if (ruleMatch === "PASS") {
                summaryBadge = `<span class="badge-preliminary-match" style="font-size: 13px; padding: 4px 10px;">${t("eligibilityModal.badgePass", {}, "PRELIMINARY RULE MATCH")}</span>`;
                eligibilitySummaryText.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 10px; margin-top: 10px; margin-bottom: 6px; flex-wrap: wrap;">
                        ${summaryBadge}
                        ${availBadgeHtml}
                        <strong style="color: #166534;">${t("eligibilityModal.passSummary", {}, "Your profile matches the evaluated automated rules.")}</strong>
                    </div>
                    <p style="font-size: 13px; color: #475569;">${t("eligibilityModal.passDesc", {}, "You appear to meet the key income and demographic criteria evaluated below. Official sanction requires administrative verification by government authorities.")}</p>
                    ${availBoxHtml}
                `;
            } else if (ruleMatch === "FAIL") {
                summaryBadge = `<span class="badge-rule-mismatch" style="font-size: 13px; padding: 4px 10px;">${t("eligibilityModal.badgeFail", {}, "RULE MISMATCH REQUIRING REVIEW")}</span>`;
                eligibilitySummaryText.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 10px; margin-top: 10px; margin-bottom: 6px; flex-wrap: wrap;">
                        ${summaryBadge}
                        ${availBadgeHtml}
                        <strong style="color: #9a3412;">${t("eligibilityModal.failSummary", {}, "One or more conditions did not match your current recorded profile.")}</strong>
                    </div>
                    <p style="font-size: 13px; color: #475569;">${t("eligibilityModal.failDesc", {}, "Automated preliminary check indicates a rule mismatch. You may review the specific criteria below or test custom parameters.")}</p>
                    ${availBoxHtml}
                `;
            } else {
                summaryBadge = `<span class="badge-data-incomplete" style="background: #fef3c7; color: #92400e; border: 1px solid #fde68a; font-size: 13px; padding: 4px 10px; border-radius: 4px; font-weight: 600;">${t("eligibilityModal.badgeUnknown", {}, "INCOMPLETE PROFILE DATA")}</span>`;
                eligibilitySummaryText.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 10px; margin-top: 10px; margin-bottom: 6px; flex-wrap: wrap;">
                        ${summaryBadge}
                        ${availBadgeHtml}
                        <strong style="color: #92400e;">${t("eligibilityModal.unknownSummary", {}, "Additional information is required for complete automated rule evaluation.")}</strong>
                    </div>
                    ${availBoxHtml}
                `;
            }

            // Missing information breakdown (DOM constructed for XSS safety)
            const missing = data.missing_information || [];
            if (missing.length > 0) {
                eligibilityMissingSection.style.display = "block";
                eligibilityMissingList.innerHTML = "";
                missing.forEach((item) => {
                    const li = document.createElement("li");
                    const strong = document.createElement("strong");
                    strong.textContent = item.replace(/_/g, " ");
                    li.appendChild(strong);
                    li.appendChild(document.createTextNode(" (Not recorded in citizen profile)"));
                    eligibilityMissingList.appendChild(li);
                });
            }

            // Satisfied Conditions
            const matched = data.matched_conditions || [];
            if (matched.length > 0) {
                eligibilityMatchedSection.style.display = "block";
                eligibilityMatchedList.innerHTML = matched.map((cond) => `
                    <div class="condition-card condition-pass">
                        <div class="condition-title">\u2713 ${escapeHtml(cond.explanation || cond.criterion)}</div>
                        <div style="font-size: 12px; color: #166534;">
                            Rule: <code>${escapeHtml(cond.criterion)} ${escapeHtml(cond.operator)} ${escapeHtml(cond.required_value)}</code>
                            ${cond.actual_value !== undefined ? ` | Your Profile: <strong>${escapeHtml(cond.actual_value)}</strong>` : ""}
                        </div>
                    </div>
                `).join("");
            }

            // Failed Conditions
            const failed = data.failed_conditions || [];
            if (failed.length > 0) {
                eligibilityFailedSection.style.display = "block";
                eligibilityFailedList.innerHTML = failed.map((cond) => `
                    <div class="condition-card condition-fail">
                        <div class="condition-title">\u2717 ${escapeHtml(cond.explanation || cond.criterion)}</div>
                        <div style="font-size: 12px; color: #9a3412;">
                            Required: <code>${escapeHtml(cond.criterion)} ${escapeHtml(cond.operator)} ${escapeHtml(cond.required_value)}</code>
                            ${cond.actual_value !== undefined ? ` | Your Profile: <strong>${escapeHtml(cond.actual_value)}</strong>` : ""}
                        </div>
                        ${cond.reason ? `<div style="font-size: 12px; margin-top: 4px; font-weight: 500;">Reason: ${escapeHtml(cond.reason)}</div>` : ""}
                    </div>
                `).join("");
            }

            // Unknown / Information Needed Conditions
            const unknown = data.unknown_conditions || [];
            if (unknown.length > 0) {
                eligibilityUnknownSection.style.display = "block";
                eligibilityUnknownList.innerHTML = unknown.map((cond) => `
                    <div class="condition-card condition-unknown">
                        <div class="condition-title">? ${escapeHtml(cond.explanation || cond.criterion)}</div>
                        <div style="font-size: 12px; color: #1e40af;">
                            Evaluation Condition: <code>${escapeHtml(cond.criterion)} ${escapeHtml(cond.operator)} ${escapeHtml(cond.required_value)}</code>
                        </div>
                        ${cond.reason ? `<div style="font-size: 12px; margin-top: 4px;">${escapeHtml(cond.reason)}</div>` : ""}
                    </div>
                `).join("");
            }

            // Document Readiness Breakdown (Step 5.4C)
            if (docReadinessSection && docReadinessList) {
                const docSummary = data.document_readiness_summary || {};
                const docItems = data.document_readiness || [];

                if (docItems.length > 0) {
                    docReadinessSection.style.display = "block";
                    if (docReadinessBadge) {
                        docReadinessBadge.textContent = `${docSummary.confirmed_count || 0}/${docSummary.total_required || docItems.length} Ready`;
                        docReadinessBadge.className = `badge ${docSummary.is_ready ? "badge-readiness-complete" : (docSummary.conflicting_count > 0 ? "badge-readiness-conflict" : "badge-readiness-missing")}`;
                    }

                    docReadinessList.innerHTML = docItems.map(d => {
                        let statusClass = "doc-status-missing";
                        let statusIcon = "❌";
                        let statusLabel = t(`readiness.${d.status}`, {}, d.status.replace(/_/g, " "));

                        if (d.status === "AVAILABLE_AND_CONFIRMED") {
                            statusClass = "doc-status-confirmed";
                            statusIcon = "✅";
                        } else if (d.status === "PENDING_CONFIRMATION") {
                            statusClass = "doc-status-pending";
                            statusIcon = "⏳";
                        } else if (d.status === "CONFLICTING") {
                            statusClass = "doc-status-conflict";
                            statusIcon = "⚠️";
                        } else if (d.status === "NOT_APPLICABLE") {
                            statusClass = "doc-status-na";
                            statusIcon = "⚪";
                        } else if (d.status === "REQUIREMENT_NOT_ESTABLISHED") {
                            statusClass = "doc-status-na";
                            statusIcon = "❔";
                        }

                        let actionHtml = "";
                        if (d.status === "PENDING_CONFIRMATION" && d.action_document_id) {
                            actionHtml = `
                                <div style="margin-top: 6px;">
                                    <button type="button" class="btn btn-sm btn-outline-warning btn-trigger-review" data-doc-id="${escapeHtml(d.action_document_id)}" style="font-size: 11px; padding: 2px 8px; cursor: pointer;">
                                        Review Pending Document &rarr;
                                    </button>
                                </div>
                            `;
                        } else if (d.status === "MISSING") {
                            actionHtml = `
                                <div style="margin-top: 6px;">
                                    <span style="font-size: 11px; color: #dc2626;">Upload required in My Documents</span>
                                </div>
                            `;
                        }

                        return `
                            <div class="readiness-item ${statusClass}" style="padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid #e2e8f0; background: #ffffff;">
                                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
                                    <div>
                                        <div style="font-weight: 600; font-size: 13px; color: #1e293b;">
                                            <span>${statusIcon}</span> ${escapeHtml(d.document_name)}
                                            <span style="font-size: 10px; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: #f1f5f9; color: #64748b; margin-left: 6px;">
                                                ${escapeHtml(d.requirement_type)}
                                            </span>
                                        </div>
                                        <div style="font-size: 12px; color: #475569; margin-top: 2px;">
                                            ${escapeHtml(d.explanation || "")}
                                        </div>
                                    </div>
                                    <span class="badge ${d.status === 'AVAILABLE_AND_CONFIRMED' ? 'badge-readiness-complete' : (d.status === 'PENDING_CONFIRMATION' ? 'badge-readiness-pending' : (d.status === 'CONFLICTING' ? 'badge-readiness-conflict' : 'badge-readiness-missing'))}" style="font-size: 11px; white-space: nowrap;">
                                        ${escapeHtml(statusLabel)}
                                    </span>
                                </div>
                                ${actionHtml}
                            </div>
                        `;
                    }).join("");

                    docReadinessList.querySelectorAll(".btn-trigger-review").forEach(btn => {
                        btn.addEventListener("click", () => {
                            const docId = btn.getAttribute("data-doc-id");
                            if (docId) {
                                closeModal(schemeEligibilityModal);
                                openReviewModal(docId);
                            }
                        });
                    });
                } else {
                    docReadinessSection.style.display = "none";
                }
            }

            // Display manual test criteria action button for registered citizens (Step 3)
            if (btnTestManualCriteria) {
                btnTestManualCriteria.style.display = isGuestMode ? "none" : "inline-block";
                btnTestManualCriteria.onclick = () => {
                    configureManualAssessmentForm(schemeId);
                    if (anonEligibilitySection) {
                        anonEligibilitySection.style.display = "block";
                        anonEligibilitySection.scrollIntoView({ behavior: "smooth" });
                    }
                };
            }

        } catch (err) {
            console.error("Open eligibility modal error:", err);
            eligibilityModalTitle.textContent = "Evaluation Error";
            eligibilitySummaryText.textContent = "Failed to communicate with eligibility evaluation engine.";
        }
    }

    // ---------------------------------------------------------------------------
    // Tabs & Filters Event Wiring
    // ---------------------------------------------------------------------------
    function switchTab(tabName) {
        // Step 4D.2: Prevent guest users from accessing profile-based recommendations through the UI
        if (tabName === "recommendations" && isGuestMode) {
            tabName = "catalog";
        }
        activeTab = tabName;
        clearSchemesAlert();

        if (tabName === "recommendations") {
            tabRecommendations.classList.add("active");
            tabRecommendations.setAttribute("aria-selected", "true");
            tabCatalog.classList.remove("active");
            tabCatalog.setAttribute("aria-selected", "false");

            if (recommendationControls) recommendationControls.style.display = "flex";
            if (schemeFiltersBar) schemeFiltersBar.style.display = "none";

            loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
        } else {
            tabCatalog.classList.add("active");
            tabCatalog.setAttribute("aria-selected", "true");
            tabRecommendations.classList.remove("active");
            tabRecommendations.setAttribute("aria-selected", "false");

            if (recommendationControls) recommendationControls.style.display = "none";
            if (schemeFiltersBar) schemeFiltersBar.style.display = "grid";

            loadCatalog({
                q: schemeSearchInput ? schemeSearchInput.value : "",
                category: categoryFilter ? categoryFilter.value : "",
                education_level: educationFilter ? educationFilter.value : "",
                beneficiary_group: beneficiaryFilter ? beneficiaryFilter.value : "",
            });
        }
    }

    if (tabRecommendations) {
        tabRecommendations.addEventListener("click", () => {
            if (isGuestMode) return;
            switchTab("recommendations");
        });
    }

    if (tabCatalog) {
        tabCatalog.addEventListener("click", () => switchTab("catalog"));
    }

    if (applicationTypeSelect) {
        applicationTypeSelect.addEventListener("change", () => {
            if (activeTab === "recommendations") {
                loadRecommendations(applicationTypeSelect.value);
            }
        });
    }

    const btnRefreshRecommendations = document.getElementById("btnRefreshRecommendations");
    if (btnRefreshRecommendations) {
        btnRefreshRecommendations.addEventListener("click", () => {
            loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
        });
    }

    if (btnApplyFilters) {
        btnApplyFilters.addEventListener("click", () => {
            loadCatalog({
                q: schemeSearchInput ? schemeSearchInput.value : "",
                category: categoryFilter ? categoryFilter.value : "",
                education_level: educationFilter ? educationFilter.value : "",
                beneficiary_group: beneficiaryFilter ? beneficiaryFilter.value : "",
            });
        });
    }

    if (btnResetFilters) {
        btnResetFilters.addEventListener("click", () => {
            if (schemeSearchInput) schemeSearchInput.value = "";
            if (categoryFilter) categoryFilter.value = "";
            if (educationFilter) educationFilter.value = "";
            if (beneficiaryFilter) beneficiaryFilter.value = "";

            loadCatalog({});
        });
    }

    if (schemeSearchInput) {
        schemeSearchInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                btnApplyFilters.click();
            }
        });
    }

    // Auto-apply on filter selection changes for responsive exploration
    [categoryFilter, educationFilter, beneficiaryFilter].forEach((sel) => {
        if (sel) {
            sel.addEventListener("change", () => {
                if (btnApplyFilters) btnApplyFilters.click();
            });
        }
    });

    // ---------------------------------------------------------------------------
    // Step 5.4B: Citizen My Documents Library Controller
    // ---------------------------------------------------------------------------

    function formatFileSize(bytes) {
        if (bytes === null || bytes === undefined || isNaN(bytes)) return "--";
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / (1024 * 1024)).toFixed(2) + " MB";
    }

    function formatDocDate(isoDate) {
        if (!isoDate) return "--";
        try {
            const d = new Date(isoDate);
            if (isNaN(d.getTime())) return isoDate;
            return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
        } catch {
            return isoDate;
        }
    }

    function getCategoryLabel(category) {
        const catMap = {
            "IDENTITY": t("documents.catIdentity", {}, "Identity"),
            "INCOME": t("documents.catIncome", {}, "Income"),
            "CATEGORY_CERTIFICATE": t("documents.catCategoryCert", {}, "Category Certificate"),
            "RESIDENCE": t("documents.catResidence", {}, "Residence"),
            "ACADEMIC": t("documents.catAcademic", {}, "Academic"),
            "BANK": t("documents.catBank", {}, "Bank"),
            "DISABILITY": t("documents.catDisability", {}, "Disability"),
            "SPECIAL_CATEGORY": t("documents.catSpecialCategory", {}, "Special Category"),
            "APPLICATION_ASSET": t("documents.catApplicationAsset", {}, "Application Assets"),
            "APPLICATION_ASSISTANCE": t("documents.catApplicationAsset", {}, "Application Assets"),
            "APPLICATION_ASSETS": t("documents.catApplicationAsset", {}, "Application Assets"),
            "OTHER": t("documents.catOther", {}, "Other"),
        };
        return catMap[category] || category || t("documents.catOther", {}, "Other");
    }

    function getTypeLabel(type) {
        const typeMap = {
            "aadhaar": t("documents.typeAadhaar", {}, "Aadhaar Card"),
            "pan": t("documents.typePan", {}, "PAN Card"),
            "income_certificate": t("documents.typeIncomeCert", {}, "Income Certificate"),
            "caste_certificate": t("documents.typeCasteCert", {}, "Caste / Category Certificate"),
            "residence_certificate": t("documents.typeResidenceCert", {}, "Residence / Domicile Certificate"),
            "marksheet_10th": t("documents.typeMarksheet10", {}, "Class 10 Marksheet"),
            "marksheet_12th": t("documents.typeMarksheet12", {}, "Class 12 Marksheet"),
            "degree_certificate": t("documents.typeDegree", {}, "Degree Certificate / Transcript"),
            "bonafide_certificate": t("documents.typeBonafide", {}, "Bonafide Student Certificate"),
            "bank_passbook": t("documents.typeBankPassbook", {}, "Bank Passbook / Statement"),
            "disability_certificate": t("documents.typeDisabilityCert", {}, "Disability (PwD) Certificate"),
            "ration_card": t("documents.typeRationCard", {}, "Ration / BPL Card"),
            "other": t("documents.typeOther", {}, "Other Document"),
        };
        return typeMap[type] || type || t("documents.typeOther", {}, "Other Document");
    }

    function getCategoryIcon(category, mimeType) {
        if (category === "IDENTITY") return "🪪";
        if (category === "INCOME") return "💰";
        if (category === "CATEGORY_CERTIFICATE") return "📜";
        if (category === "RESIDENCE") return "🏡";
        if (category === "ACADEMIC") return "🎓";
        if (category === "BANK") return "🏦";
        if (category === "DISABILITY") return "♿";
        if (category === "SPECIAL_CATEGORY") return "⭐";
        if (category === "APPLICATION_ASSET" || category === "APPLICATION_ASSISTANCE" || category === "APPLICATION_ASSETS") return "📂";
        if (mimeType && mimeType.includes("pdf")) return "📕";
        return "📄";
    }

    function showDocAlert(message, type = "error") {
        if (!documentsAlertBox) return;
        documentsAlertBox.className = `alert-box visible ${type}`;
        documentsAlertBox.textContent = message;
    }

    function clearDocAlert() {
        if (!documentsAlertBox) return;
        documentsAlertBox.className = "alert-box";
        documentsAlertBox.textContent = "";
    }

    function showModalAlert(box, message, type = "error") {
        if (!box) return;
        box.className = `alert-box visible ${type}`;
        box.textContent = message;
    }

    function clearModalAlert(box) {
        if (!box) return;
        box.className = "alert-box";
        box.textContent = "";
    }

    async function loadUserDocuments() {
        if (isGuestMode || !documentsGrid) return;

        clearDocAlert();
        documentsGrid.innerHTML = `
            <div class="doc-empty-state">
                <span class="chat-spinner" aria-hidden="true"></span>
                <p style="margin-top: 10px; color: #64748b;">${t("documents.loadingDocs", {}, "Loading your documents...")}</p>
            </div>
        `;

        const category = docCategoryFilter ? docCategoryFilter.value : "";
        const includeArchived = docIncludeArchivedToggle ? docIncludeArchivedToggle.checked : false;

        const res = await fetchCitizenDocuments(category || null, includeArchived);
        if (!res.ok) {
            showDocAlert(res.error || t("documents.errorLoading", {}, "Failed to load documents. Please check your connection and retry."));
            documentsGrid.innerHTML = `
                <div class="doc-empty-state">
                    <div class="doc-empty-icon" aria-hidden="true">⚠️</div>
                    <div class="doc-empty-title">${t("common.error", {}, "Error")}</div>
                    <p class="doc-empty-desc">${escapeHtml(res.error || t("documents.errorLoading"))}</p>
                    <button type="button" class="btn btn-primary" id="btnRetryLoadDocs">${t("common.retry", {}, "Retry")}</button>
                </div>
            `;
            const retryBtn = document.getElementById("btnRetryLoadDocs");
            if (retryBtn) retryBtn.addEventListener("click", () => loadUserDocuments());
            return;
        }

        userDocuments = (res.data && res.data.documents) || [];
        updateDocSummaryStats();
        renderPendingDocumentsChecklist();
        renderDocumentsGrid();
    }

    function updateDocSummaryStats() {
        const total = userDocuments.length;
        const confirmed = userDocuments.filter(d => d.confirmation_status === "CONFIRMED").length;
        const pending = userDocuments.filter(d => d.confirmation_status !== "CONFIRMED" && d.status !== "ARCHIVED").length;
        const archived = userDocuments.filter(d => d.status === "ARCHIVED").length;

        if (docStatTotal) docStatTotal.textContent = String(total);
        if (docStatConfirmed) docStatConfirmed.textContent = String(confirmed);
        if (docStatPending) docStatPending.textContent = String(pending);
        if (docStatArchived) docStatArchived.textContent = String(archived);
    }

    function renderDocumentsGrid() {
        if (!documentsGrid) return;
        documentsGrid.innerHTML = "";

        const searchQuery = docSearchInput ? docSearchInput.value.trim().toLowerCase() : "";
        const statusFilter = docStatusFilter ? docStatusFilter.value : "";

        // In-memory multi-attribute filtering
        const filtered = userDocuments.filter(doc => {
            if (searchQuery) {
                const name = (doc.original_filename || "").toLowerCase();
                const type = (doc.document_type || "").toLowerCase();
                const cat = (doc.document_category || "").toLowerCase();
                const typeLabel = getTypeLabel(doc.document_type).toLowerCase();
                const catLabel = getCategoryLabel(doc.document_category).toLowerCase();
                if (!name.includes(searchQuery) && !type.includes(searchQuery) && !cat.includes(searchQuery) && !typeLabel.includes(searchQuery) && !catLabel.includes(searchQuery)) {
                    return false;
                }
            }
            if (statusFilter) {
                if (statusFilter === "ACTIVE" && doc.status !== "ACTIVE") return false;
                if (statusFilter === "CONFIRMED" && doc.confirmation_status !== "CONFIRMED") return false;
                if (statusFilter === "PENDING" && (doc.confirmation_status === "CONFIRMED" || doc.status === "ARCHIVED")) return false;
                if (statusFilter === "ARCHIVED" && doc.status !== "ARCHIVED") return false;
            }
            return true;
        });

        if (filtered.length === 0) {
            const emptyDiv = document.createElement("div");
            emptyDiv.className = "doc-empty-state";

            const iconDiv = document.createElement("div");
            iconDiv.className = "doc-empty-icon";
            iconDiv.setAttribute("aria-hidden", "true");
            iconDiv.textContent = "📄";
            emptyDiv.appendChild(iconDiv);

            const titleDiv = document.createElement("div");
            titleDiv.className = "doc-empty-title";
            titleDiv.textContent = t("documents.emptyTitle", {}, "No Documents Found");
            emptyDiv.appendChild(titleDiv);

            const descP = document.createElement("p");
            descP.className = "doc-empty-desc";
            descP.textContent = t("documents.emptySubtitle", {}, "Upload your identity documents, income certificates, caste certificates, or marksheets to enable one-click scholarship discovery and profile autofill.");
            emptyDiv.appendChild(descP);

            const uploadFirstBtn = document.createElement("button");
            uploadFirstBtn.type = "button";
            uploadFirstBtn.className = "btn btn-primary";
            uploadFirstBtn.textContent = t("documents.emptyUploadBtn", {}, "Upload Your First Document");
            uploadFirstBtn.addEventListener("click", () => openUploadModal());
            emptyDiv.appendChild(uploadFirstBtn);

            documentsGrid.appendChild(emptyDiv);
            return;
        }

        filtered.forEach(doc => {
            const card = document.createElement("div");
            card.className = "document-card" + (doc.status === "ARCHIVED" ? " archived" : "");
            card.setAttribute("role", "listitem");

            // Header
            const header = document.createElement("div");
            header.className = "doc-card-header";

            const titleWrap = document.createElement("div");
            titleWrap.className = "doc-card-title-wrap";

            const icon = document.createElement("span");
            icon.className = "doc-card-icon";
            icon.setAttribute("aria-hidden", "true");
            icon.textContent = getCategoryIcon(doc.document_category, doc.mime_type);
            titleWrap.appendChild(icon);

            const title = document.createElement("h3");
            title.className = "doc-card-title";
            title.textContent = doc.original_filename || getTypeLabel(doc.document_type);
            titleWrap.appendChild(title);
            header.appendChild(titleWrap);
            card.appendChild(header);

            // Badges row
            const badgesRow = document.createElement("div");
            badgesRow.className = "doc-badges-row";

            const catBadge = document.createElement("span");
            catBadge.className = "doc-category-badge";
            catBadge.textContent = getCategoryLabel(doc.document_category);
            badgesRow.appendChild(catBadge);

            const typeBadge = document.createElement("span");
            typeBadge.className = "doc-type-badge";
            typeBadge.textContent = getTypeLabel(doc.document_type);
            badgesRow.appendChild(typeBadge);

            const statusBadge = document.createElement("span");
            if (doc.status === "ARCHIVED") {
                statusBadge.className = "doc-status-badge archived";
                statusBadge.textContent = t("documents.statusArchived", {}, "Archived");
            } else if (doc.confirmation_status === "CONFIRMED") {
                statusBadge.className = "doc-status-badge confirmed";
                statusBadge.textContent = t("documents.statusConfirmed", {}, "Confirmed");
            } else if (doc.confirmation_status === "REJECTED") {
                statusBadge.className = "doc-status-badge rejected";
                statusBadge.textContent = t("documents.statusRejected", {}, "Rejected");
            } else {
                statusBadge.className = "doc-status-badge pending";
                statusBadge.textContent = t("documents.statusPendingReview", {}, "Pending Review");
            }
            badgesRow.appendChild(statusBadge);
            card.appendChild(badgesRow);

            // Metadata rows
            const meta = document.createElement("div");
            meta.className = "doc-card-meta";

            const dateRow = document.createElement("div");
            dateRow.className = "doc-meta-row";
            const dateLabel = document.createElement("span");
            dateLabel.textContent = t("documents.uploadedOn", { date: formatDocDate(doc.created_at) }, `Uploaded: ${formatDocDate(doc.created_at)}`);
            dateRow.appendChild(dateLabel);

            const sizeLabel = document.createElement("span");
            sizeLabel.textContent = formatFileSize(doc.file_size);
            dateRow.appendChild(sizeLabel);
            meta.appendChild(dateRow);
            card.appendChild(meta);

            // Actions bar
            const actions = document.createElement("div");
            actions.className = "doc-card-actions";

            // 1. Review action (if pending and not archived)
            if (doc.confirmation_status !== "CONFIRMED" && doc.status !== "ARCHIVED") {
                const btnReview = document.createElement("button");
                btnReview.type = "button";
                btnReview.className = "doc-btn-action primary";
                btnReview.textContent = "✍️ " + t("documents.actionReview", {}, "Review & Confirm");
                btnReview.addEventListener("click", () => openReviewModal(doc.document_id));
                actions.appendChild(btnReview);
            }

            // 2. Download action
            if (doc.has_original_file) {
                const btnDownload = document.createElement("button");
                btnDownload.type = "button";
                btnDownload.className = "doc-btn-action";
                btnDownload.textContent = "⬇️ " + t("documents.actionDownload", {}, "Download");
                btnDownload.addEventListener("click", () => handleDownloadDocument(doc.document_id, doc.original_filename));
                actions.appendChild(btnDownload);
            }

            // 3. Replace action (if active)
            if (doc.status !== "ARCHIVED") {
                const btnReplace = document.createElement("button");
                btnReplace.type = "button";
                btnReplace.className = "doc-btn-action";
                btnReplace.textContent = "🔄 " + t("documents.actionReplace", {}, "Replace");
                btnReplace.addEventListener("click", () => openReplaceModal(doc));
                actions.appendChild(btnReplace);
            }

            // 4. Details / Metadata action
            const btnDetails = document.createElement("button");
            btnDetails.type = "button";
            btnDetails.className = "doc-btn-action";
            btnDetails.textContent = "ℹ️ " + t("documents.actionDetails", {}, "Details");
            btnDetails.addEventListener("click", () => openMetadataModal(doc.document_id));
            actions.appendChild(btnDetails);

            // 5. Archive action (if active)
            if (doc.status !== "ARCHIVED") {
                const btnArchive = document.createElement("button");
                btnArchive.type = "button";
                btnArchive.className = "doc-btn-action";
                btnArchive.textContent = "📦 " + t("documents.actionArchive", {}, "Archive");
                btnArchive.addEventListener("click", () => handleArchiveDocument(doc.document_id));
                actions.appendChild(btnArchive);
            }

            // 6. Delete action
            const btnDelete = document.createElement("button");
            btnDelete.type = "button";
            btnDelete.className = "doc-btn-action danger";
            btnDelete.textContent = "🗑️ " + t("documents.actionDelete", {}, "Delete");
            btnDelete.addEventListener("click", () => openDeleteModal(doc));
            actions.appendChild(btnDelete);

            card.appendChild(actions);
            documentsGrid.appendChild(card);
        });
    }

    // ---------------------------------------------------------------------------
    // Documents to Upload / Essential Documents Checklist
    // (Automatically removes a document from the checklist once uploaded)
    // ---------------------------------------------------------------------------
    const ESSENTIAL_DOCUMENTS = [
        { type: "aadhaar", altTypes: ["aadhaar", "aadhaar_card"], label: "Aadhaar Card", category: "IDENTITY", icon: "🪪", desc: "UIDAI identity proof & DBT seeding" },
        { type: "marksheet_10th", altTypes: ["marksheet_10th", "marksheet10"], label: "Class 10 Marksheet", category: "ACADEMIC", icon: "🎓", desc: "Secondary education & DOB record" },
        { type: "marksheet_12th", altTypes: ["marksheet_12th", "marksheet12"], label: "Class 12 / Inter Marksheet", category: "ACADEMIC", icon: "🎓", desc: "Senior secondary qualifying marks" },
        { type: "bank_passbook", altTypes: ["bank_passbook", "passbook"], label: "Bank Passbook", category: "BANK", icon: "🏦", desc: "Account number & IFSC for DBT transfer" },
        { type: "income_certificate", altTypes: ["income_certificate", "income"], label: "Income Certificate", category: "INCOME", icon: "🏛️", desc: "Family annual income verification" },
        { type: "caste_certificate", altTypes: ["caste_certificate", "caste"], label: "Caste / Category Certificate", category: "CATEGORY_CERTIFICATE", icon: "📜", desc: "Reservation & welfare quota proof" },
        { type: "pan", altTypes: ["pan", "pan_card"], label: "PAN Card", category: "IDENTITY", icon: "💳", desc: "Financial identity & tax record" },
    ];

    function renderPendingDocumentsChecklist() {
        const pendingListEl = document.getElementById("pendingDocsList");
        const badgeEl = document.getElementById("pendingDocsCounterBadge");
        const modalGuideText = document.getElementById("modalPendingDocsText");

        const uploadedTypes = new Set();
        (userDocuments || []).forEach(d => {
            if (d.status !== "ARCHIVED") {
                const rawType = (d.document_type || "").toLowerCase().trim();
                uploadedTypes.add(rawType);
                if (rawType === "aadhaar_card" || rawType === "aadhaar") {
                    uploadedTypes.add("aadhaar");
                    uploadedTypes.add("aadhaar_card");
                }
                if (rawType === "marksheet_10th" || rawType === "marksheet10") {
                    uploadedTypes.add("marksheet_10th");
                }
                if (rawType === "marksheet_12th" || rawType === "marksheet12") {
                    uploadedTypes.add("marksheet_12th");
                }
                if (rawType === "bank_passbook" || rawType === "passbook") {
                    uploadedTypes.add("bank_passbook");
                }
                if (rawType === "income_certificate" || rawType === "income") {
                    uploadedTypes.add("income_certificate");
                }
                if (rawType === "caste_certificate" || rawType === "caste") {
                    uploadedTypes.add("caste_certificate");
                }
                if (rawType === "pan_card" || rawType === "pan") {
                    uploadedTypes.add("pan");
                    uploadedTypes.add("pan_card");
                }
            }
        });

        const pending = ESSENTIAL_DOCUMENTS.filter(doc => {
            return !doc.altTypes.some(at => uploadedTypes.has(at.toLowerCase()));
        });

        const totalEssential = ESSENTIAL_DOCUMENTS.length;
        const uploadedCount = totalEssential - pending.length;

        if (badgeEl) {
            badgeEl.textContent = `${uploadedCount} of ${totalEssential} Uploaded • ${pending.length} Remaining`;
            badgeEl.style.background = pending.length === 0 ? "#dcfce7" : "#eff6ff";
            badgeEl.style.color = pending.length === 0 ? "#166534" : "#1d4ed8";
            badgeEl.style.borderColor = pending.length === 0 ? "#86efac" : "#bfdbfe";
        }

        if (modalGuideText) {
            if (pending.length === 0) {
                modalGuideText.textContent = "All core documents uploaded! You can still upload updates or additional records.";
            } else {
                modalGuideText.textContent = pending.map(p => p.label).join(", ");
            }
        }

        if (!pendingListEl) return;
        pendingListEl.innerHTML = "";

        if (pending.length === 0) {
            pendingListEl.innerHTML = `
                <div style="grid-column: 1 / -1; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px 18px; color: #166534; display: flex; align-items: center; gap: 12px;">
                    <span style="font-size: 26px;">🎉</span>
                    <div>
                        <strong style="font-size: 14.5px;">All Essential Documents Uploaded &amp; Stored!</strong>
                        <div style="font-size: 12.5px; color: #15803d; margin-top: 2px;">Your digital vault has all primary certificates required for automated scholarship &amp; welfare scheme eligibility evaluation.</div>
                    </div>
                </div>
            `;
            return;
        }

        pending.forEach(doc => {
            const card = document.createElement("div");
            card.style.cssText = "background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px; transition: transform 0.15s, box-shadow 0.15s;";
            card.innerHTML = `
                <div style="display: flex; align-items: center; gap: 10px; min-width: 0;">
                    <span style="font-size: 22px; flex-shrink: 0;">${doc.icon}</span>
                    <div style="min-width: 0;">
                        <div style="font-size: 13.5px; font-weight: 700; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(doc.label)}</div>
                        <div style="font-size: 11px; color: #64748b; margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(doc.desc)}</div>
                    </div>
                </div>
                <button type="button" class="btn btn-sm btn-quick-upload-doc" data-type="${doc.type}" style="white-space: nowrap; font-size: 11.5px; font-weight: 700; padding: 5px 12px; border-radius: 6px; border: 1px solid #2563eb; color: #2563eb; background: #ffffff; cursor: pointer; flex-shrink: 0;">
                    + Upload
                </button>
            `;

            const btn = card.querySelector(".btn-quick-upload-doc");
            if (btn) {
                btn.addEventListener("click", () => {
                    openUploadModal(doc.type);
                });
            }

            pendingListEl.appendChild(card);
        });
    }

    // ---------------------------------------------------------------------------
    // Upload Modal Handling
    // ---------------------------------------------------------------------------

    function openUploadModal(preselectedType = null) {
        if (!documentUploadModal) return;
        if (docUploadForm) {
            docUploadForm.reset();
            docUploadForm.style.display = "block";
        }
        if (docUploadFooter) docUploadFooter.style.display = "flex";
        if (docUploadResultSection) docUploadResultSection.style.display = "none";
        if (docSelectedFileName) {
            docSelectedFileName.style.display = "none";
            docSelectedFileName.textContent = "";
        }
        if (docUploadProgress) docUploadProgress.style.display = "none";
        if (btnStartUploadSubmit) btnStartUploadSubmit.disabled = false;
        clearModalAlert(docUploadAlert);

        if (docTypeSelect) {
            if (preselectedType) {
                docTypeSelect.value = preselectedType;
            } else {
                docTypeSelect.value = "AUTO_DETECT";
            }
        }
        if (docCategorySelect && !preselectedType) {
            docCategorySelect.value = "";
        }

        renderPendingDocumentsChecklist();
        openModal(documentUploadModal, btnOpenUploadModal);
    }

    const MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024;   // 10 MB (10,485,760 bytes)
    const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024;  // 5 MB (5,242,880 bytes)

    function getApplicableMaxFileSize(fileName) {
        if (!fileName) return MAX_IMAGE_SIZE_BYTES;
        const ext = fileName.slice(fileName.lastIndexOf(".")).toLowerCase();
        return ext === ".pdf" ? MAX_PDF_SIZE_BYTES : MAX_IMAGE_SIZE_BYTES;
    }

    function validateSelectedFile(file) {
        if (!file) {
            return {
                valid: false,
                error: t("documents.errNoFile", {}, "Please select a file to upload."),
            };
        }
        const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
        const allowedExts = [".pdf", ".png", ".jpg", ".jpeg", ".webp"];
        if (!allowedExts.includes(ext)) {
            return {
                valid: false,
                error: t("documents.errFileType", {}, "Unsupported file format. Please upload PDF, PNG, JPEG, or WEBP."),
            };
        }
        const maxSize = getApplicableMaxFileSize(file.name);
        if (file.size > maxSize) {
            const isPdf = ext === ".pdf";
            const msgKey = isPdf ? "documents.errPdfSize" : "documents.errImageSize";
            const defaultMsg = isPdf
                ? "PDF file exceeds the 10 MB limit. Please select a smaller document."
                : "Image file exceeds the 5 MB limit. Please select a smaller image.";
            return {
                valid: false,
                error: t(msgKey, {}, defaultMsg),
            };
        }
        return { valid: true };
    }

    function handleFileSelection(file) {
        if (!file) return;
        const validation = validateSelectedFile(file);
        if (!validation.valid) {
            showModalAlert(docUploadAlert, validation.error);
            if (docFileInput) docFileInput.value = "";
            if (docSelectedFileName) {
                docSelectedFileName.style.display = "none";
                docSelectedFileName.textContent = "";
            }
            return;
        }

        clearModalAlert(docUploadAlert);
        if (docSelectedFileName) {
            docSelectedFileName.textContent = `${file.name} (${formatFileSize(file.size)})`;
            docSelectedFileName.style.display = "inline-block";
        }
    }

    if (docFileInput) {
        docFileInput.addEventListener("change", (e) => {
            const file = e.target.files && e.target.files[0];
            handleFileSelection(file);
        });
    }

    if (docUploadDropzone) {
        ["dragenter", "dragover"].forEach(evtName => {
            docUploadDropzone.addEventListener(evtName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                docUploadDropzone.classList.add("dragover");
            });
        });

        ["dragleave", "drop"].forEach(evtName => {
            docUploadDropzone.addEventListener(evtName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                docUploadDropzone.classList.remove("dragover");
            });
        });

        docUploadDropzone.addEventListener("drop", (e) => {
            const dt = e.dataTransfer;
            const files = dt && dt.files;
            if (files && files.length > 0) {
                if (docFileInput) docFileInput.files = files;
                handleFileSelection(files[0]);
            }
        });
    }

    if (btnOpenUploadModal) {
        btnOpenUploadModal.addEventListener("click", () => openUploadModal());
    }

    if (btnStartUploadSubmit) {
        btnStartUploadSubmit.addEventListener("click", async () => {
            if (isUploadingDocument) return;

            const file = docFileInput && docFileInput.files && docFileInput.files[0];
            const validation = validateSelectedFile(file);
            if (!validation.valid) {
                showModalAlert(docUploadAlert, validation.error);
                return;
            }

            isUploadingDocument = true;
            btnStartUploadSubmit.disabled = true;
            if (docUploadProgress) docUploadProgress.style.display = "flex";
            clearModalAlert(docUploadAlert);

            const formData = new FormData();
            formData.append("file", file);
            if (docCategorySelect && docCategorySelect.value) formData.append("document_category", docCategorySelect.value);
            if (docTypeSelect && docTypeSelect.value) formData.append("document_type", docTypeSelect.value);

            const res = await uploadCitizenDocument(formData);

            isUploadingDocument = false;
            btnStartUploadSubmit.disabled = false;
            if (docUploadProgress) docUploadProgress.style.display = "none";

            if (!res.ok) {
                showModalAlert(docUploadAlert, res.error || "Upload failed. Please check file format and try again.");
                return;
            }

            // Refresh document library immediately
            await loadUserDocuments();
            if (!isGuestMode) {
                loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
            }

            // Render post-upload OCR preview
            if (docUploadForm) docUploadForm.style.display = "none";
            if (docUploadFooter) docUploadFooter.style.display = "none";
            if (docUploadResultSection) docUploadResultSection.style.display = "block";

            const resultDoc = res.data || {};

            if (docUploadExtractedFields) {
                renderIntelligentOcrPreview(docUploadExtractedFields, resultDoc, resultDoc.document_id);
            }

            if (btnUploadGoToReview) {
                btnUploadGoToReview.onclick = () => {
                    closeModal(documentUploadModal);
                    openReviewModal(resultDoc.document_id);
                };
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Document-Aware Intelligent OCR Preview Renderer
    // ---------------------------------------------------------------------------
    function renderIntelligentOcrPreview(container, resData, docId) {
        if (!container) return;
        const docType = (resData && (resData.document_type || resData.detected_document_type)) || "UNKNOWN_DOCUMENT";
        const extracted = (resData && resData.extracted_fields) || {};
        const confidence = (resData && resData.classification_confidence !== undefined) ? resData.classification_confidence : (resData && resData.field_confidence ? resData.field_confidence : 0.9);
        const isLowConf = resData && resData.is_low_confidence;
        const warnings = (resData && resData.validation_warnings) || [];

        const typeDisplayNames = {
            "MARKSHEET_12TH": "Class 12 Marksheet (HSC / 10+2)",
            "MARKSHEET_10TH": "Class 10 Marksheet (SSC / Matriculation)",
            "AADHAAR_CARD": "Aadhaar Identity Card",
            "INCOME_CERTIFICATE": "Income Certificate",
            "CASTE_CERTIFICATE": "Caste / Community Certificate",
            "RESIDENCE_CERTIFICATE": "Residence / Domicile Certificate",
            "DOMICILE_CERTIFICATE": "Residence / Domicile Certificate",
            "BANK_PASSBOOK": "Bank Passbook / Statement",
            "FEES_RECEIPT": "Tuition / Institutional Fee Receipt",
            "PAN_CARD": "Permanent Account Number (PAN) Card",
            "UNKNOWN_DOCUMENT": "Document (Type Unverified)",
        };

        const typeName = typeDisplayNames[docType] || docType.replace(/_/g, " ").toUpperCase();
        const confPct = Math.round(confidence * 100);

        let html = `
            <div class="ocr-preview-card" style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                    <div>
                        <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #047857; font-weight: 700;">✨ AI Auto-Identified Document</span>
                        <h4 style="margin: 2px 0 0; color: #1e3a8a; font-size: 15px; font-weight: 700;">${escapeHtml(typeName)}</h4>
                    </div>
                    <div style="text-align: right;">
                        <span class="badge" style="background: ${confPct >= 75 ? '#dcfce7; color: #166534' : (confPct >= 45 ? '#fef3c7; color: #92400e' : '#fee2e2; color: #991b1b')}; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 12px;">
                            ${confPct}% Confidence
                        </span>
                    </div>
                </div>
        `;

        if (isLowConf) {
            html += `
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 10px; margin-bottom: 12px; font-size: 12px; color: #92400e;">
                    <div style="display: flex; gap: 6px; align-items: center; margin-bottom: 6px;">
                        <span>⚠️</span>
                        <strong>Classification Uncertain:</strong> Please verify or choose the correct document type:
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                        <select id="ocrTypeSelector" class="doc-input" style="padding: 4px 8px; font-size: 12px; flex: 1; max-width: 250px;">
                            <option value="MARKSHEET_12TH" ${docType === 'MARKSHEET_12TH' ? 'selected' : ''}>12th Marksheet</option>
                            <option value="MARKSHEET_10TH" ${docType === 'MARKSHEET_10TH' ? 'selected' : ''}>10th Marksheet</option>
                            <option value="AADHAAR_CARD" ${docType === 'AADHAAR_CARD' ? 'selected' : ''}>Aadhaar Card</option>
                            <option value="INCOME_CERTIFICATE" ${docType === 'INCOME_CERTIFICATE' ? 'selected' : ''}>Income Certificate</option>
                            <option value="CASTE_CERTIFICATE" ${docType === 'CASTE_CERTIFICATE' ? 'selected' : ''}>Caste Certificate</option>
                            <option value="RESIDENCE_CERTIFICATE" ${docType === 'RESIDENCE_CERTIFICATE' ? 'selected' : ''}>Residence Certificate</option>
                            <option value="BANK_PASSBOOK" ${docType === 'BANK_PASSBOOK' ? 'selected' : ''}>Bank Passbook</option>
                            <option value="FEES_RECEIPT" ${docType === 'FEES_RECEIPT' ? 'selected' : ''}>Fee Receipt</option>
                            <option value="PAN_CARD" ${docType === 'PAN_CARD' ? 'selected' : ''}>PAN Card</option>
                        </select>
                        <button type="button" class="btn btn-sm btn-secondary" id="btnApplyTypeReclassify" style="padding: 4px 10px; font-size: 12px;">Apply &amp; Re-extract</button>
                    </div>
                </div>
            `;
        }

        if (warnings.length > 0) {
            html += `
                <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; font-size: 12px; color: #991b1b;">
                    <strong>⚠️ Data Validation:</strong> ${escapeHtml(warnings.join(" | "))}
                </div>
            `;
        }

        const getVal = (k) => {
            const item = extracted[k];
            if (item === undefined || item === null) return null;
            if (typeof item === "object" && item.value !== undefined) return item.value;
            return item;
        };

        if (docType === "MARKSHEET_12TH" || docType === "MARKSHEET_10TH") {
            const studentName = getVal("student_name") || "--";
            const rollNo = getVal("roll_number") || "--";
            const board = getVal("board_name") || "--";
            const school = getVal("school_name") || "--";
            const state = getVal("state") || "--";
            const dob = getVal("date_of_birth");
            const year = getVal("examination_year") || "--";
            const totalObt = getVal("total_obtained_marks");
            const maxMarks = getVal("maximum_total_marks");
            const pct = getVal("percentage");
            const resStatus = getVal("result_status") || "PASS";
            const grade = getVal("grade");
            const subMarks = getVal("subject_marks");

            html += `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin-bottom: 12px;">
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">Student Name</span>
                        <div style="font-weight: 700; color: #1e293b; font-size: 13px;">${escapeHtml(studentName)}</div>
                    </div>
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">Roll / Regd No</span>
                        <div style="font-family: monospace; font-weight: 700; color: #1e293b; font-size: 13px;">${escapeHtml(rollNo)}</div>
                    </div>
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">${docType === 'MARKSHEET_12TH' ? 'Junior College / School' : 'School Name'}</span>
                        <div style="font-weight: 600; color: #1e293b; font-size: 13px;">${escapeHtml(school)}</div>
                    </div>
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">Board</span>
                        <div style="font-weight: 600; color: #1e293b; font-size: 13px;">${escapeHtml(board)}</div>
                    </div>
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">State</span>
                        <div style="font-weight: 600; color: #1e293b; font-size: 13px;">${escapeHtml(state)}</div>
                    </div>
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">Exam Year</span>
                        <div style="font-weight: 600; color: #1e293b; font-size: 13px;">${escapeHtml(year)}</div>
                    </div>
                    ${dob ? `
                    <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                        <span style="font-size: 11px; color: #64748b; font-weight: 600;">Date of Birth</span>
                        <div style="font-weight: 600; color: #1e293b; font-size: 13px;">${escapeHtml(dob)}</div>
                    </div>` : ''}
                </div>
            `;

            if (Array.isArray(subMarks) && subMarks.length > 0) {
                html += `
                    <div style="margin-bottom: 12px; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden;">
                        <div style="background: #f1f5f9; padding: 6px 12px; font-weight: 700; font-size: 12px; color: #334155; border-bottom: 1px solid #cbd5e1;">
                            Subject-Wise Marks Table
                        </div>
                        <table style="width: 100%; border-collapse: collapse; font-size: 12px; text-align: left;">
                            <thead style="background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                                <tr>
                                    <th style="padding: 6px 10px;">Subject Name</th>
                                    <th style="padding: 6px 10px; text-align: center;">Max Marks</th>
                                    <th style="padding: 6px 10px; text-align: center;">Marks Obtained</th>
                                    <th style="padding: 6px 10px; text-align: center;">Grade</th>
                                </tr>
                            </thead>
                            <tbody>
                `;
                subMarks.forEach(s => {
                    html += `
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 6px 10px; font-weight: 500;">${escapeHtml(s.subject_name || "--")}</td>
                            <td style="padding: 6px 10px; text-align: center;">${escapeHtml(s.max_marks || 100)}</td>
                            <td style="padding: 6px 10px; text-align: center; font-weight: 700; color: #1e3a8a;">${escapeHtml(s.obtained_marks || "--")}</td>
                            <td style="padding: 6px 10px; text-align: center; color: #64748b;">${escapeHtml(s.grade || "-")}</td>
                        </tr>
                    `;
                });
                html += `
                            </tbody>
                        </table>
                    </div>
                `;
            }

            html += `
                <div style="display: flex; gap: 12px; align-items: center; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 10px 14px; flex-wrap: wrap;">
                    <div>
                        <span style="font-size: 11px; color: #1e40af; font-weight: 600;">Total Marks:</span>
                        <strong style="margin-left: 4px; color: #1e3a8a;">${totalObt !== null ? totalObt : '--'} ${maxMarks ? '/ ' + maxMarks : ''}</strong>
                    </div>
                    ${pct !== null ? `
                    <div>
                        <span style="font-size: 11px; color: #1e40af; font-weight: 600;">Percentage:</span>
                        <strong style="margin-left: 4px; color: #1d4ed8; font-size: 14px;">${pct}%</strong>
                    </div>` : ''}
                    ${grade ? `
                    <div>
                        <span style="font-size: 11px; color: #1e40af; font-weight: 600;">Grade:</span>
                        <strong style="margin-left: 4px; color: #1e3a8a;">${escapeHtml(grade)}</strong>
                    </div>` : ''}
                    <div style="margin-left: auto;">
                        <span class="badge" style="background: #dcfce7; color: #15803d; font-weight: 700; padding: 4px 10px; border-radius: 12px;">
                            ${escapeHtml(resStatus)}
                        </span>
                    </div>
                </div>
            `;
        } else {
            html += `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px;">`;
            const keys = Object.keys(extracted);
            if (keys.length === 0) {
                html += `<p style="color: #64748b; font-size: 13px; grid-column: 1/-1;">No structured fields automatically detected.</p>`;
            } else {
                keys.forEach(k => {
                    const val = getVal(k);
                    if (val !== null && typeof val !== "object") {
                        html += `
                            <div style="background: #fff; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px;">
                                <span style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">${escapeHtml(k.replace(/_/g, ' '))}</span>
                                <div style="font-weight: 600; color: #1e293b; font-size: 13px; font-family: ${k.includes('number') || k.includes('ifsc') ? 'monospace' : 'inherit'};">${escapeHtml(val)}</div>
                            </div>
                        `;
                    }
                });
            }
            html += `</div>`;
        }

        html += `</div>`;
        container.innerHTML = html;

        const btnReclass = container.querySelector("#btnApplyTypeReclassify");
        const selReclass = container.querySelector("#ocrTypeSelector");
        if (btnReclass && selReclass && docId) {
            btnReclass.addEventListener("click", async () => {
                const chosenType = selReclass.value;
                btnReclass.disabled = true;
                btnReclass.textContent = "Re-extracting...";
                try {
                    const reRes = await reclassifyCitizenDocument(docId, chosenType);
                    if (reRes.ok && reRes.data) {
                        renderIntelligentOcrPreview(container, reRes.data, docId);
                    } else {
                        alert(reRes.error || "Failed to re-extract with chosen document type.");
                        btnReclass.disabled = false;
                        btnReclass.textContent = "Apply & Re-extract";
                    }
                } catch (err) {
                    console.error("Reclassify error:", err);
                    btnReclass.disabled = false;
                    btnReclass.textContent = "Apply & Re-extract";
                }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Review & Confirmation Workflow
    // ---------------------------------------------------------------------------

    async function openReviewModal(documentId) {
        if (!documentReviewModal) return;
        currentReviewDocId = documentId;
        clearModalAlert(docReviewAlert);

        if (docReviewLoading) docReviewLoading.style.display = "block";
        if (docReviewTableWrap) docReviewTableWrap.style.display = "none";
        if (docReviewTableBody) docReviewTableBody.innerHTML = "";
        if (btnSaveConfirmations) btnSaveConfirmations.disabled = false;

        openModal(documentReviewModal);

        const res = await fetchDocumentReview(documentId);
        if (docReviewLoading) docReviewLoading.style.display = "none";

        if (!res.ok) {
            showModalAlert(docReviewAlert, res.error || "Unable to retrieve document review details.");
            return;
        }

        const reviewData = res.data || {};
        const extractedFields = reviewData.extracted_fields || {};
        const conflicts = reviewData.existing_profile_conflicts || {};

        if (docReviewTableWrap) docReviewTableWrap.style.display = "block";

        const fieldKeys = Object.keys(extractedFields);
        if (fieldKeys.length === 0) {
            if (docReviewTableBody) {
                docReviewTableBody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: #64748b; padding: 20px;">${t("documents.noExtractedFields", {}, "No extracted fields recorded for this document.")}</td></tr>`;
            }
            return;
        }

        fieldKeys.forEach(fieldKey => {
            const item = extractedFields[fieldKey];
            const rawVal = (item && typeof item === "object" && item.value !== undefined) ? item.value : item;
            const canonicalName = (fieldKey === "annual_family_income") ? "annual_income" : fieldKey;
            const conflict = conflicts[canonicalName];

            const tr = document.createElement("tr");
            tr.setAttribute("data-field-name", canonicalName);

            // Col 1: Field name
            const tdField = document.createElement("td");
            tdField.style.fontWeight = "600";
            tdField.style.color = "#1e3a8a";
            tdField.textContent = canonicalName.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
            tr.appendChild(tdField);

            // Col 2: Extracted Value (Editable input) + Conflict Alert
            const tdValue = document.createElement("td");
            const input = document.createElement("input");
            input.type = "text";
            input.className = "doc-review-field-input";
            input.value = (rawVal !== null && rawVal !== undefined) ? (typeof rawVal === "object" ? JSON.stringify(rawVal) : String(rawVal)) : "";
            tdValue.appendChild(input);

            if (conflict) {
                const conflictBox = document.createElement("div");
                conflictBox.className = "doc-conflict-box";
                conflictBox.textContent = t("documents.conflictNotice", { currentVal: conflict.current_profile_value }, `Discrepancy detected with your existing profile (${conflict.current_profile_value}). Check 'Overwrite' if you want this new value saved.`);

                const overwriteLabel = document.createElement("label");
                overwriteLabel.className = "doc-overwrite-label";

                const overwriteCb = document.createElement("input");
                overwriteCb.type = "checkbox";
                overwriteCb.className = "doc-overwrite-checkbox";

                const overwriteText = document.createElement("span");
                overwriteText.textContent = t("documents.checkOverwrite", {}, "Allow Overwrite");

                overwriteLabel.appendChild(overwriteCb);
                overwriteLabel.appendChild(overwriteText);
                conflictBox.appendChild(overwriteLabel);
                tdValue.appendChild(conflictBox);
            }
            tr.appendChild(tdValue);

            // Col 3: Confirm checkbox
            const tdConfirm = document.createElement("td");
            tdConfirm.style.textAlign = "center";
            tdConfirm.style.verticalAlign = "middle";

            const confirmCb = document.createElement("input");
            confirmCb.type = "checkbox";
            confirmCb.className = "doc-confirm-checkbox";
            confirmCb.checked = true; // Default checked for citizen review convenience
            tdConfirm.appendChild(confirmCb);
            tr.appendChild(tdConfirm);

            if (docReviewTableBody) docReviewTableBody.appendChild(tr);
        });
    }

    if (btnSaveConfirmations) {
        btnSaveConfirmations.addEventListener("click", async () => {
            if (!currentReviewDocId || !docReviewTableBody) return;

            const rows = docReviewTableBody.querySelectorAll("tr");
            const confirmations = [];

            rows.forEach(tr => {
                const fieldName = tr.getAttribute("data-field-name");
                if (!fieldName) return;

                const inputEl = tr.querySelector(".doc-review-field-input");
                const confirmCb = tr.querySelector(".doc-confirm-checkbox");
                const overwriteCb = tr.querySelector(".doc-overwrite-checkbox");

                if (confirmCb && confirmCb.checked) {
                    confirmations.push({
                        field_name: fieldName,
                        value: inputEl ? inputEl.value.trim() : "",
                        confirmed: true,
                        allow_overwrite: overwriteCb ? overwriteCb.checked : false,
                    });
                }
            });

            if (confirmations.length === 0) {
                showModalAlert(docReviewAlert, "Please select at least one field to confirm.", "error");
                return;
            }

            btnSaveConfirmations.disabled = true;
            btnSaveConfirmations.textContent = t("documents.savingConfirmations", {}, "Saving confirmed fields to profile...");
            clearModalAlert(docReviewAlert);

            const res = await confirmDocumentFields(currentReviewDocId, { confirmations });

            btnSaveConfirmations.disabled = false;
            btnSaveConfirmations.textContent = t("documents.btnSaveConfirmations", {}, "Confirm & Save to Profile");

            if (!res.ok) {
                showModalAlert(docReviewAlert, res.error || "Failed to confirm fields. Please check for discrepancies.");
                return;
            }

            showModalAlert(docReviewAlert, t("documents.confirmSuccess", {}, "Fields confirmed and saved to your profile successfully!"), "success");

            // Refresh citizen profile and library
            const profRes = await apiFetch("/profile/me");
            if (profRes.ok && profRes.data && profRes.data.profile) {
                currentCitizenProfile = profRes.data.profile;
                if (dispFullName) dispFullName.textContent = currentCitizenProfile.full_name || "--";
                if (dispIncome && currentCitizenProfile.annual_income !== null) {
                    dispIncome.textContent = `${formatCurrency(currentCitizenProfile.annual_income)} / year`;
                }
            }

            await loadUserDocuments();
            if (!isGuestMode) {
                loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
            }

            setTimeout(() => {
                closeModal(documentReviewModal);
            }, 800);
        });
    }

    // ---------------------------------------------------------------------------
    // Replace Document Workflow
    // ---------------------------------------------------------------------------

    function openReplaceModal(doc) {
        if (!documentReplaceModal) return;
        currentReplaceDocId = doc.document_id;
        clearModalAlert(docReplaceAlert);

        if (docReplaceForm) docReplaceForm.reset();
        if (docReplaceProgress) docReplaceProgress.style.display = "none";
        if (btnConfirmReplaceSubmit) btnConfirmReplaceSubmit.disabled = false;
        if (docReplaceSelectedFileName) {
            docReplaceSelectedFileName.style.display = "none";
            docReplaceSelectedFileName.textContent = "";
        }

        if (docReplaceTargetInfo) {
            docReplaceTargetInfo.innerHTML = `
                <strong>${t("documents.metaFilename", {}, "Original Filename:")}</strong> ${escapeHtml(doc.original_filename || getTypeLabel(doc.document_type))}<br>
                <strong>${t("documents.metaCategory", {}, "Category:")}</strong> ${escapeHtml(getCategoryLabel(doc.document_category))}
            `;
        }

        openModal(documentReplaceModal);
    }

    if (docReplaceFileInput) {
        docReplaceFileInput.addEventListener("change", (e) => {
            const file = e.target.files && e.target.files[0];
            if (file) {
                const validation = validateSelectedFile(file);
                if (!validation.valid) {
                    showModalAlert(docReplaceAlert, validation.error);
                    docReplaceFileInput.value = "";
                    if (docReplaceSelectedFileName) {
                        docReplaceSelectedFileName.style.display = "none";
                        docReplaceSelectedFileName.textContent = "";
                    }
                    return;
                }
                clearModalAlert(docReplaceAlert);
                if (docReplaceSelectedFileName) {
                    docReplaceSelectedFileName.textContent = `${file.name} (${formatFileSize(file.size)})`;
                    docReplaceSelectedFileName.style.display = "inline-block";
                }
            }
        });
    }

    if (btnConfirmReplaceSubmit) {
        btnConfirmReplaceSubmit.addEventListener("click", async () => {
            if (!currentReplaceDocId || isReplacingDocument) return;

            const file = docReplaceFileInput && docReplaceFileInput.files && docReplaceFileInput.files[0];
            const validation = validateSelectedFile(file);
            if (!validation.valid) {
                showModalAlert(docReplaceAlert, validation.error);
                return;
            }

            isReplacingDocument = true;
            btnConfirmReplaceSubmit.disabled = true;
            if (docReplaceProgress) docReplaceProgress.style.display = "flex";
            clearModalAlert(docReplaceAlert);

            const formData = new FormData();
            formData.append("file", file);

            const res = await replaceCitizenDocument(currentReplaceDocId, formData);

            isReplacingDocument = false;
            btnConfirmReplaceSubmit.disabled = false;
            if (docReplaceProgress) docReplaceProgress.style.display = "none";

            if (!res.ok) {
                showModalAlert(docReplaceAlert, res.error || "Document replacement failed. Please verify the file and try again.");
                return;
            }

            await loadUserDocuments();
            if (!isGuestMode) {
                loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
            }
            closeModal(documentReplaceModal);

            // Automatically transition to Review workflow for newly extracted fields
            openReviewModal(currentReplaceDocId);
        });
    }

    // ---------------------------------------------------------------------------
    // Delete & Archive Workflow
    // ---------------------------------------------------------------------------

    function openDeleteModal(doc) {
        if (!documentDeleteModal) return;
        currentDeleteDoc = doc;
        clearModalAlert(docDeleteAlert);

        if (docDeleteTargetInfo) {
            docDeleteTargetInfo.innerHTML = `
                <strong>${t("documents.metaFilename", {}, "Original Filename:")}</strong> ${escapeHtml(doc.original_filename || getTypeLabel(doc.document_type))}<br>
                <strong>${t("documents.metaCategory", {}, "Category:")}</strong> ${escapeHtml(getCategoryLabel(doc.document_category))}
            `;
        }

        if (btnArchiveFromDeleteModal) {
            btnArchiveFromDeleteModal.style.display = (doc.status === "ARCHIVED") ? "none" : "inline-block";
        }

        openModal(documentDeleteModal);
    }

    async function handleArchiveDocument(documentId) {
        const res = await deleteCitizenDocument(documentId, false);
        if (!res.ok) {
            showDocAlert(res.error || "Failed to archive document.");
            return;
        }
        await loadUserDocuments();
    }

    if (btnArchiveFromDeleteModal) {
        btnArchiveFromDeleteModal.addEventListener("click", async () => {
            if (!currentDeleteDoc) return;
            btnArchiveFromDeleteModal.disabled = true;
            const res = await deleteCitizenDocument(currentDeleteDoc.document_id, false);
            btnArchiveFromDeleteModal.disabled = false;

            if (!res.ok) {
                showModalAlert(docDeleteAlert, res.error || "Failed to archive document.");
                return;
            }

            closeModal(documentDeleteModal);
            await loadUserDocuments();
            if (!isGuestMode) {
                loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
            }
        });
    }

    if (btnPermanentDeleteFromModal) {
        btnPermanentDeleteFromModal.addEventListener("click", async () => {
            if (!currentDeleteDoc) return;
            btnPermanentDeleteFromModal.disabled = true;
            const res = await deleteCitizenDocument(currentDeleteDoc.document_id, true);
            btnPermanentDeleteFromModal.disabled = false;

            if (!res.ok) {
                showModalAlert(docDeleteAlert, res.error || "Failed to delete document.");
                return;
            }

            closeModal(documentDeleteModal);
            await loadUserDocuments();
            if (!isGuestMode) {
                loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Download Handling
    // ---------------------------------------------------------------------------

    async function handleDownloadDocument(documentId, filename) {
        const res = await downloadCitizenDocument(documentId, filename || "document.pdf");
        if (!res.ok) {
            showDocAlert(res.error || "Unable to download document.");
        }
    }

    // ---------------------------------------------------------------------------
    // Metadata Details Modal
    // ---------------------------------------------------------------------------

    async function openMetadataModal(documentId) {
        if (!documentMetadataModal) return;
        currentMetadataDocId = documentId;

        if (docMetadataFieldsList) docMetadataFieldsList.innerHTML = `<p style="color: #64748b;">${t("common.loading", {}, "Loading...")}</p>`;
        if (docMetadataExtractedTableWrap) docMetadataExtractedTableWrap.innerHTML = "";
        if (btnMetadataReviewBtn) btnMetadataReviewBtn.style.display = "none";

        openModal(documentMetadataModal);

        const res = await fetchDocumentMetadata(documentId);
        if (!res.ok) {
            if (docMetadataFieldsList) {
                docMetadataFieldsList.innerHTML = `<p style="color: #dc2626;">${escapeHtml(res.error || "Unable to load document metadata.")}</p>`;
            }
            return;
        }

        const doc = res.data && res.data.document;
        if (!doc) return;

        if (docMetadataFieldsList) {
            docMetadataFieldsList.innerHTML = `
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaId", {}, "Document ID:")}</span>
                    <span class="value" style="font-family: monospace; font-size: 12px;">${escapeHtml(doc.document_id)}</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaFilename", {}, "Original Filename:")}</span>
                    <span class="value">${escapeHtml(doc.original_filename || "--")}</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaCategory", {}, "Category:")}</span>
                    <span class="value">${escapeHtml(getCategoryLabel(doc.document_category))}</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaType", {}, "Type:")}</span>
                    <span class="value">${escapeHtml(getTypeLabel(doc.document_type))}</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaSize", {}, "File Size:")}</span>
                    <span class="value">${formatFileSize(doc.file_size)} (${escapeHtml(doc.mime_type || "--")})</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaStatus", {}, "Vault Status:")}</span>
                    <span class="value">${escapeHtml(doc.status)}</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaConfirmation", {}, "Confirmation Status:")}</span>
                    <span class="value">${escapeHtml(doc.confirmation_status)}</span>
                </div>
                <div class="profile-detail-item">
                    <span class="label">${t("documents.metaCreatedAt", {}, "Uploaded At:")}</span>
                    <span class="value">${formatDocDate(doc.created_at)}</span>
                </div>
            `;
        }

        // Extracted & Confirmed fields
        const isConfirmedDoc = (doc.confirmation_status === "CONFIRMED" || doc.status === "CONFIRMED");
        const sectionH4 = docMetadataExtractedTableWrap && docMetadataExtractedTableWrap.parentElement ? docMetadataExtractedTableWrap.parentElement.querySelector("h4") : null;
        if (sectionH4) {
            sectionH4.textContent = isConfirmedDoc ? "Confirmed Document Fields & Metadata (Masked):" : "Extracted Fields (Masked):";
        }

        const extracted = (res.data && (res.data.extracted_fields || (res.data.document && res.data.document.extracted_fields))) || {};
        const entries = Object.entries(extracted);
        if (docMetadataExtractedTableWrap) {
            if (entries.length === 0) {
                docMetadataExtractedTableWrap.innerHTML = `<p style="color: #64748b; font-size: 13px;">${t("documents.noExtractedFields", {}, "No extracted fields recorded for this document.")}</p>`;
            } else {
                let html = '<div class="doc-extracted-fields-list">';
                entries.forEach(([k, v]) => {
                    const rawVal = (v && typeof v === "object" && v.value !== undefined) ? v.value : v;
                    const isConfirmedField = Boolean(
                        (v && typeof v === "object" && v.is_confirmed) ||
                        (res.data && res.data.confirmed_fields && res.data.confirmed_fields[k]) ||
                        isConfirmedDoc
                    );
                    const isCorrected = Boolean(
                        (v && typeof v === "object" && v.is_corrected) ||
                        (res.data && res.data.confirmed_fields && res.data.confirmed_fields[k] && res.data.confirmed_fields[k].is_corrected)
                    );
                    let badgeHtml = "";
                    if (isCorrected) {
                        badgeHtml = `<span style="display: inline-block; background: #ecfdf5; color: #047857; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; border: 1px solid #a7f3d0; margin-left: 8px;">✓ User Corrected</span>`;
                    } else if (isConfirmedField) {
                        badgeHtml = `<span style="display: inline-block; background: #ecfdf5; color: #047857; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; border: 1px solid #a7f3d0; margin-left: 8px;">✓ Confirmed</span>`;
                    }
                    html += `
                        <div class="doc-field-item" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #f1f5f9;">
                            <span class="doc-field-label" style="font-weight: 600; color: #1e293b;">${escapeHtml(k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()))}</span>
                            <span class="doc-field-val" style="color: #0f172a; font-weight: 500;">${escapeHtml(String(rawVal !== undefined && rawVal !== null ? rawVal : "--"))} ${badgeHtml}</span>
                        </div>
                    `;
                });
                html += '</div>';
                docMetadataExtractedTableWrap.innerHTML = html;
            }
        }

        // Download button hook
        if (btnMetadataDownloadBtn) {
            btnMetadataDownloadBtn.onclick = () => {
                handleDownloadDocument(doc.document_id, doc.original_filename);
            };
        }

        // Review button hook
        if (btnMetadataReviewBtn && doc.confirmation_status !== "CONFIRMED" && doc.status !== "ARCHIVED") {
            btnMetadataReviewBtn.style.display = "inline-block";
            btnMetadataReviewBtn.onclick = () => {
                closeModal(documentMetadataModal);
                openReviewModal(doc.document_id);
            };
        }
    }

    // ---------------------------------------------------------------------------
    // Document Filter & Search Event Listeners
    // ---------------------------------------------------------------------------

    let docSearchDebounceTimer = null;
    if (docSearchInput) {
        docSearchInput.addEventListener("input", () => {
            clearTimeout(docSearchDebounceTimer);
            docSearchDebounceTimer = setTimeout(() => {
                renderDocumentsGrid();
            }, 250);
        });
    }

    if (docCategoryFilter) {
        docCategoryFilter.addEventListener("change", () => {
            loadUserDocuments();
        });
    }

    if (docStatusFilter) {
        docStatusFilter.addEventListener("change", () => {
            renderDocumentsGrid();
        });
    }

    if (docIncludeArchivedToggle) {
        docIncludeArchivedToggle.addEventListener("change", () => {
            loadUserDocuments();
        });
    }

    if (btnResetDocFilters) {
        btnResetDocFilters.addEventListener("click", () => {
            if (docSearchInput) docSearchInput.value = "";
            if (docCategoryFilter) docCategoryFilter.value = "";
            if (docStatusFilter) docStatusFilter.value = "";
            if (docIncludeArchivedToggle) docIncludeArchivedToggle.checked = false;
            loadUserDocuments();
        });
    }

    // ===========================================================================
    // Step 5.5A: Scholarship Application Workspace Controllers
    // ===========================================================================

    function showApplicationsAlert(message, type = "error") {
        if (!applicationsAlertBox) return;
        applicationsAlertBox.className = `alert-box ${type === "error" ? "alert-error" : "alert-success"}`;
        applicationsAlertBox.textContent = message;
        applicationsAlertBox.style.display = "block";
    }

    function clearApplicationsAlert() {
        if (!applicationsAlertBox) return;
        applicationsAlertBox.textContent = "";
        applicationsAlertBox.style.display = "none";
    }

    function showWorkspaceAlert(message, type = "error") {
        if (!appWorkspaceAlert) return;
        appWorkspaceAlert.className = `alert-box ${type === "error" ? "alert-error" : "alert-success"}`;
        appWorkspaceAlert.textContent = message;
        appWorkspaceAlert.style.display = "block";
    }

    function clearWorkspaceAlert() {
        if (!appWorkspaceAlert) return;
        appWorkspaceAlert.textContent = "";
        appWorkspaceAlert.style.display = "none";
    }

    async function loadCitizenApplications() {
        if (!applicationsGrid) return;
        clearApplicationsAlert();
        applicationsGrid.innerHTML = `<div class="empty-state-notice" style="grid-column: 1 / -1;">Loading your scholarship application drafts...</div>`;

        try {
            const res = await fetchCitizenApplicationDrafts();
            if (!res.ok) {
                if (res.status === 403) {
                    // Guest session: applications disabled
                    return;
                }
                showApplicationsAlert(res.error || "Failed to load application drafts.");
                applicationsGrid.innerHTML = "";
                return;
            }

            userApplicationDrafts = (res.data && res.data.drafts) || [];
            renderApplicationsGrid();
            checkExtensionPresence();
        } catch (err) {
            console.error("Load applications error:", err);
            showApplicationsAlert("Network error while loading scholarship drafts.");
            applicationsGrid.innerHTML = "";
        }
    }

    function renderApplicationsGrid() {
        if (!applicationsGrid) return;
        clearApplicationsAlert();
        applicationsGrid.innerHTML = "";

        if (userApplicationDrafts.length === 0) {
            applicationsGrid.innerHTML = `
                <div class="empty-state-notice" style="grid-column: 1 / -1; padding: 36px 20px; text-align: center; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 10px;">
                    <div style="font-size: 32px; margin-bottom: 8px;">📝</div>
                    <h3 style="font-size: 16px; color: #334155; margin-bottom: 6px;">${escapeHtml(t("applications.noDraftsTitle", {}, "No Scholarship Drafts Yet"))}</h3>
                    <p style="font-size: 13px; color: #64748b; margin-bottom: 16px; max-width: 520px; margin-left: auto; margin-right: auto;">${escapeHtml(t("applications.noDraftsDesc", {}, "You have not started any scholarship application drafts. Discover recommended scholarships matched to your citizen profile and click Apply Now."))}</p>
                    <a href="#schemes" class="btn btn-primary" style="text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">
                        <span>${escapeHtml(t("applications.btnExploreSchemes", {}, "Explore Scholarships"))}</span> &rarr;
                    </a>
                </div>
            `;
            return;
        }

        userApplicationDrafts.forEach((draft) => {
            const draftId = escapeHtml(draft.draft_id);
            const schemeId = escapeHtml(draft.scheme_id);
            const schemeTitle = escapeHtml(draft.official_scheme_name || draft.scheme_name || schemeId);
            const cycle = escapeHtml(draft.application_year || "AY 2026-27");
            const rawStatus = (draft.status || "DRAFT").toUpperCase();
            const pct = Math.min(100, Math.max(0, draft.completion_percentage || 0));

            const statusClass = `status-${rawStatus.toLowerCase()}`;
            const statusLabelKey = "applications.status" + rawStatus.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join("");
            const statusLabel = t(statusLabelKey, {}, rawStatus.replace(/_/g, " "));

            const updatedDate = draft.updated_at ? new Date(draft.updated_at).toLocaleDateString() : "";

            const card = document.createElement("div");
            card.className = "application-card";
            card.innerHTML = `
                <div>
                    <div class="app-card-header">
                        <h4 class="app-card-title">${schemeTitle}</h4>
                        <span class="badge-draft-status ${statusClass}">${escapeHtml(statusLabel)}</span>
                    </div>
                    <div class="app-card-body">
                        <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                            <span><strong>${escapeHtml(t("applications.draftProgress", {}, "Draft Progress:"))}</strong> ${pct}%</span>
                            <span style="color: #64748b;">${cycle}</span>
                        </div>
                        <div class="app-progress-bar-wrap">
                            <div class="app-progress-bar-fill" style="width: ${pct}%;"></div>
                        </div>
                        <div style="font-size: 11px; color: #64748b; margin-top: 6px;">
                            Last updated: ${updatedDate}
                        </div>
                    </div>
                </div>
                <div class="app-card-footer">
                    <button type="button" class="btn btn-primary btn-resume-draft" data-draft-id="${draftId}" style="font-size: 12px; padding: 6px 12px;">
                        ${escapeHtml(t("applications.btnResumeDraft", {}, "Resume Application"))}
                    </button>
                    <button type="button" class="filter-btn-reset btn-delete-draft" data-draft-id="${draftId}" style="font-size: 12px; padding: 6px 10px; color: #dc2626; border-color: #fca5a5;">
                        ${escapeHtml(t("applications.btnDeleteDraft", {}, "Delete"))}
                    </button>
                </div>
            `;
            applicationsGrid.appendChild(card);
        });

        // Attach action handlers on rendered cards
        applicationsGrid.querySelectorAll(".btn-resume-draft").forEach((btn) => {
            btn.addEventListener("click", () => {
                const draftId = btn.getAttribute("data-draft-id");
                if (draftId) openApplicationWorkspace(draftId, btn);
            });
        });

        applicationsGrid.querySelectorAll(".btn-delete-draft").forEach((btn) => {
            btn.addEventListener("click", () => {
                const draftId = btn.getAttribute("data-draft-id");
                if (draftId) openDeleteDraftModal(draftId, btn);
            });
        });
    }

    async function handleApplyNowClick(schemeId, triggerEl = null) {
        if (triggerEl && (triggerEl.disabled || triggerEl.getAttribute("data-closed") === "true")) {
            showSchemesAlert("Applications for this scheme are currently closed.", "warning");
            return;
        }

        const cachedScheme = findLoadedScheme(schemeId);
        if (cachedScheme) {
            const dStatus = cachedScheme.deadline_status || (cachedScheme.deadline && cachedScheme.deadline.status) || cachedScheme.application_status;
            const isClosed = (dStatus === "CLOSED") || (cachedScheme.is_currently_open === false && dStatus !== "YEAR_ROUND" && dStatus !== "NEEDS_LIVE_VERIFICATION" && dStatus !== "QUOTA_DEPENDENT");
            if (isClosed) {
                showSchemesAlert("Applications for this scheme are currently closed.", "warning");
                return;
            }
        }

        // Canonical official portal application & login URLs for all 10 supported schemes
        const OFFICIAL_SCHEME_LOGIN_URLS = {
            "SCHEME_EDU_001_PM_USP_CSSS": "https://scholarships.gov.in/ApplicationForm/#/login",
            "SCHEME_EDU_002_AICTE_PRAGATI": "https://scholarships.gov.in/ApplicationForm/#/login",
            "SCHEME_EDU_003_AICTE_SAKSHAM": "https://scholarships.gov.in/ApplicationForm/#/login",
            "SCHEME_EDU_004_AICTE_SWANATH": "https://scholarships.gov.in/ApplicationForm/#/login",
            "SCHEME_EDU_005_TOP_CLASS_SC": "https://scholarships.gov.in/ApplicationForm/#/login",
            "SCHEME_AGRI_001_PM_KISAN": "https://pmkisan.gov.in/RegistrationFormNew.aspx",
            "SCHEME_MSME_001_PMEGP": "https://www.kviconline.gov.in/pmegpeportal/jsp/pmegponline.jsp",
            "SCHEME_URBAN_001_PM_SVANIDHI": "https://pmsvanidhi.mohua.gov.in/Home/PreApplication",
            "SCHEME_LABOUR_001_PM_SYM": "https://maandhan.in/shramyogi",
            "SCHEME_WOMEN_001_PMUY_2": "https://www.pmuy.gov.in/ujjwala2.html"
        };

        const targetPortalUrl = OFFICIAL_SCHEME_LOGIN_URLS[schemeId] ||
            (cachedScheme && (cachedScheme.application_url || cachedScheme.official_application_url || cachedScheme.official_url)) ||
            "https://scholarships.gov.in/ApplicationForm/#/login";

        // Safely navigate to official login / application page in a new window/tab
        window.open(targetPortalUrl, "_blank", "noopener,noreferrer");

        // For registered citizen accounts, preserve/keep draft in account under My Applications
        if (!isGuestMode) {
            try {
                const existing = userApplicationDrafts.find(
                    (d) => d.scheme_id === schemeId && d.status !== "CLOSED"
                );
                if (!existing) {
                    const createRes = await createApplicationDraft(schemeId, "FRESH");
                    if (createRes.ok && createRes.data && createRes.data.draft) {
                        userApplicationDrafts.unshift(createRes.data.draft);
                        renderApplicationsGrid();
                    }
                }
            } catch (err) {
                console.warn("Account draft synchronization notice:", err);
            }
        }
    }

    async function openApplicationWorkspace(draftId, triggerEl = null) {
        clearWorkspaceAlert();
        openModal(applicationWorkspaceModal, triggerEl);

        if (appWorkspaceSchemeName) appWorkspaceSchemeName.textContent = "Loading application details...";
        if (appWorkspaceFieldsContainer) appWorkspaceFieldsContainer.innerHTML = '<div class="empty-state-notice">Loading form fields...</div>';

        try {
            const res = await fetchApplicationDraftDetails(draftId);
            if (!res.ok || !res.data || !res.data.draft) {
                showWorkspaceAlert(res.error || "Failed to load application draft.");
                return;
            }

            currentWorkspaceDraft = res.data.draft;
            activeWorkspaceSectionIndex = 0;

            // Automatically autofill verified details into form if draft form_data is currently empty
            if (!currentWorkspaceDraft.form_data || Object.keys(currentWorkspaceDraft.form_data).length === 0) {
                try {
                    const autoRes = await applyDraftAutofill(draftId);
                    if (autoRes.ok && autoRes.data && autoRes.data.draft) {
                        currentWorkspaceDraft = autoRes.data.draft;
                    }
                } catch (autoErr) {
                    console.warn("Auto-applying verified details on open:", autoErr);
                }
            }

            const defn = currentWorkspaceDraft.scheme_definition || {};
            const schemeTitle = defn.official_scheme_name || defn.scheme_name || currentWorkspaceDraft.scheme_id;
            if (appWorkspaceSchemeName) appWorkspaceSchemeName.textContent = schemeTitle;
            if (appWorkspaceYearBadge) appWorkspaceYearBadge.textContent = currentWorkspaceDraft.application_year || "AY 2026-27";

            updateWorkspaceHeader();
            buildWorkspaceTabs();
            renderWorkspaceSection(0);
        } catch (err) {
            console.error("Open workspace error:", err);
            showWorkspaceAlert("Network error while loading application workspace.");
        }
    }

    function updateWorkspaceHeader() {
        if (!currentWorkspaceDraft) return;
        const rawStatus = (currentWorkspaceDraft.status || "DRAFT").toUpperCase();
        const pct = Math.min(100, Math.max(0, currentWorkspaceDraft.completion_percentage || 0));

        if (appWorkspaceStatusBadge) {
            appWorkspaceStatusBadge.className = `badge-draft-status status-${rawStatus.toLowerCase()}`;
            const statusLabelKey = "applications.status" + rawStatus.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join("");
            appWorkspaceStatusBadge.textContent = t(statusLabelKey, {}, rawStatus.replace(/_/g, " "));
        }

        if (appWorkspaceProgressPct) appWorkspaceProgressPct.textContent = `${pct}%`;
        if (appWorkspaceProgressBar) appWorkspaceProgressBar.style.width = `${pct}%`;
    }

    function buildWorkspaceTabs() {
        if (!appWorkspaceTabsNav || !currentWorkspaceDraft) return;
        appWorkspaceTabsNav.innerHTML = "";

        const defn = currentWorkspaceDraft.scheme_definition || {};
        const sections = defn.form_sections || [];

        // 1. Form Sections tabs
        sections.forEach((sec, idx) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = `workspace-tab-btn ${idx === activeWorkspaceSectionIndex ? "active" : ""}`;
            btn.textContent = sec.title;
            btn.setAttribute("data-tab-index", idx);
            btn.addEventListener("click", () => {
                saveWorkspaceDraft(true).then(() => {
                    renderWorkspaceSection(idx);
                });
            });
            appWorkspaceTabsNav.appendChild(btn);
        });

        // 2. Required Documents Checklist tab
        const docsTabIdx = sections.length;
        const docsBtn = document.createElement("button");
        docsBtn.type = "button";
        docsBtn.className = `workspace-tab-btn ${docsTabIdx === activeWorkspaceSectionIndex ? "active" : ""}`;
        docsBtn.textContent = t("applications.requiredDocsChecklist", {}, "Documents Checklist");
        docsBtn.setAttribute("data-tab-index", docsTabIdx);
        docsBtn.addEventListener("click", () => {
            saveWorkspaceDraft(true).then(() => {
                renderWorkspaceSection(docsTabIdx);
            });
        });
        appWorkspaceTabsNav.appendChild(docsBtn);

        // 3. Review & Official Portal tab
        const reviewTabIdx = sections.length + 1;
        const reviewBtn = document.createElement("button");
        reviewBtn.type = "button";
        reviewBtn.className = `workspace-tab-btn ${reviewTabIdx === activeWorkspaceSectionIndex ? "active" : ""}`;
        reviewBtn.textContent = "Review & Portal";
        reviewBtn.setAttribute("data-tab-index", reviewTabIdx);
        reviewBtn.addEventListener("click", () => {
            saveWorkspaceDraft(true).then(() => {
                renderWorkspaceSection(reviewTabIdx);
            });
        });
        appWorkspaceTabsNav.appendChild(reviewBtn);
    }

    function renderWorkspaceSection(index) {
        if (!currentWorkspaceDraft) return;
        clearWorkspaceAlert();
        activeWorkspaceSectionIndex = index;

        const defn = currentWorkspaceDraft.scheme_definition || {};
        const sections = defn.form_sections || [];
        const totalTabs = sections.length + 2;

        // Update Tab active styling
        if (appWorkspaceTabsNav) {
            const tabButtons = appWorkspaceTabsNav.querySelectorAll(".workspace-tab-btn");
            tabButtons.forEach((btn, idx) => {
                btn.classList.toggle("active", idx === index);
            });
        }

        const formData = currentWorkspaceDraft.form_data || {};

        if (index < sections.length) {
            // Form Section Rendering
            const section = sections[index];
            if (appWorkspaceSectionTitle) appWorkspaceSectionTitle.textContent = section.title;
            if (appWorkspaceSectionDesc) appWorkspaceSectionDesc.textContent = section.description || "";

            if (appWorkspaceForm) appWorkspaceForm.style.display = "block";
            if (appWorkspaceDocsView) appWorkspaceDocsView.style.display = "none";
            if (appWorkspaceReviewPortalBox) appWorkspaceReviewPortalBox.style.display = "none";

            renderSectionFields(section.fields || [], formData);

        } else if (index === sections.length) {
            // Required Documents Checklist Rendering
            if (appWorkspaceSectionTitle) appWorkspaceSectionTitle.textContent = t("applications.requiredDocsChecklist", {}, "Required Documents Checklist");
            if (appWorkspaceSectionDesc) appWorkspaceSectionDesc.textContent = "Cross-referenced with verified documents currently stored in your citizen My Documents library.";

            if (appWorkspaceForm) appWorkspaceForm.style.display = "none";
            if (appWorkspaceDocsView) appWorkspaceDocsView.style.display = "block";
            if (appWorkspaceReviewPortalBox) appWorkspaceReviewPortalBox.style.display = "none";

            renderDocumentsChecklist(defn);

        } else {
            // Review & Official Submission Portal Rendering
            if (appWorkspaceSectionTitle) appWorkspaceSectionTitle.textContent = "Review & Official Submission";
            if (appWorkspaceSectionDesc) appWorkspaceSectionDesc.textContent = "Review your draft readiness and proceed to the official government portal for final submission.";

            if (appWorkspaceForm) appWorkspaceForm.style.display = "none";
            if (appWorkspaceDocsView) appWorkspaceDocsView.style.display = "none";
            if (appWorkspaceReviewPortalBox) appWorkspaceReviewPortalBox.style.display = "block";

            renderReviewAndPortalView(defn);
        }

        // Footer buttons update
        if (btnWorkspacePrev) btnWorkspacePrev.style.display = index > 0 ? "inline-block" : "none";
        if (btnWorkspaceNext) btnWorkspaceNext.style.display = index < totalTabs - 1 ? "inline-block" : "none";
        if (btnWorkspaceContinuePortal) {
            btnWorkspaceContinuePortal.style.display = index === totalTabs - 1 ? "inline-block" : "none";
        }
    }

    function renderSectionFields(fields, formData) {
        if (!appWorkspaceFieldsContainer) return;
        appWorkspaceFieldsContainer.innerHTML = "";

        fields.forEach((f) => {
            const fieldId = f.field_id;
            const val = formData[fieldId] !== undefined ? formData[fieldId] : "";

            const wrap = document.createElement("div");
            wrap.className = "workspace-form-field";

            const labelEl = document.createElement("label");
            labelEl.setAttribute("for", `field_${fieldId}`);
            labelEl.innerHTML = `${escapeHtml(f.label)} ${f.required ? '<span style="color: #dc2626;">*</span>' : ""}`;
            wrap.appendChild(labelEl);

            if (f.type === "select") {
                const selectEl = document.createElement("select");
                selectEl.id = `field_${fieldId}`;
                selectEl.className = "workspace-field-input";
                selectEl.innerHTML = '<option value="">-- Select Option --</option>';
                (f.options || []).forEach((opt) => {
                    const optVal = typeof opt === "string" ? opt : opt.value;
                    const optLabel = typeof opt === "string" ? opt : opt.label;
                    const optionEl = document.createElement("option");
                    optionEl.value = optVal;
                    optionEl.textContent = optLabel;
                    if (val !== undefined && val !== null && String(val).trim().toLowerCase() === String(optVal).trim().toLowerCase()) optionEl.selected = true;
                    selectEl.appendChild(optionEl);
                });
                selectEl.addEventListener("change", () => {
                    currentWorkspaceDraft.form_data[fieldId] = selectEl.value;
                });
                wrap.appendChild(selectEl);

            } else if (f.type === "checkbox") {
                const checkWrap = document.createElement("div");
                checkWrap.style.display = "flex";
                checkWrap.style.alignItems = "flex-start";
                checkWrap.style.gap = "8px";
                checkWrap.style.marginTop = "4px";

                const checkboxEl = document.createElement("input");
                checkboxEl.type = "checkbox";
                checkboxEl.id = `field_${fieldId}`;
                checkboxEl.checked = Boolean(val);
                checkboxEl.addEventListener("change", () => {
                    currentWorkspaceDraft.form_data[fieldId] = checkboxEl.checked;
                });

                const checkLabel = document.createElement("label");
                checkLabel.setAttribute("for", `field_${fieldId}`);
                checkLabel.style.fontSize = "13px";
                checkLabel.style.fontWeight = "normal";
                checkLabel.style.cursor = "pointer";
                checkLabel.textContent = f.label;

                checkWrap.appendChild(checkboxEl);
                checkWrap.appendChild(checkLabel);
                wrap.innerHTML = "";
                wrap.appendChild(checkWrap);

            } else {
                const inputEl = document.createElement("input");
                inputEl.type = f.type === "number" ? "number" : (f.type === "date" ? "date" : "text");
                inputEl.id = `field_${fieldId}`;
                inputEl.className = "workspace-field-input";
                inputEl.value = val;
                if (f.placeholder) inputEl.placeholder = f.placeholder;
                if (f.validation) {
                    if (f.validation.min !== undefined) inputEl.min = f.validation.min;
                    if (f.validation.max !== undefined) inputEl.max = f.validation.max;
                }
                inputEl.addEventListener("input", () => {
                    currentWorkspaceDraft.form_data[fieldId] = inputEl.value;
                });
                wrap.appendChild(inputEl);
            }

            if (f.help_text) {
                const helpEl = document.createElement("div");
                helpEl.className = "field-help";
                helpEl.textContent = f.help_text;
                wrap.appendChild(helpEl);
            }

            const errorEl = document.createElement("div");
            errorEl.className = "field-error";
            errorEl.id = `err_${fieldId}`;
            wrap.appendChild(errorEl);

            appWorkspaceFieldsContainer.appendChild(wrap);
        });
    }

    function renderDocumentsChecklist(defn) {
        if (!appWorkspaceDocsList) return;
        appWorkspaceDocsList.innerHTML = "";

        const reqDocs = defn.required_documents || [];
        const optDocs = defn.optional_documents || [];

        const allDocs = [
            ...reqDocs.map(d => ({ ...d, is_mandatory: true })),
            ...optDocs.map(d => ({ ...d, is_mandatory: false })),
        ];

        allDocs.forEach((docItem) => {
            const docName = docItem.document_name;
            const category = docItem.category || "GENERAL";
            const isMandatory = docItem.is_mandatory;

            // Cross-reference with citizen's userDocuments
            const matchInLibrary = (userDocuments || []).find((u) => {
                if (u.status === "ARCHIVED") return false;
                const matchCategory = u.document_category === category;
                const matchName = (u.original_filename || u.document_type || "").toLowerCase().includes(docName.toLowerCase().split(" ")[0]);
                return matchCategory || matchName;
            });

            let badgeHtml = "";
            if (matchInLibrary && (matchInLibrary.confirmation_status === "CONFIRMED" || matchInLibrary.status === "CONFIRMED")) {
                badgeHtml = `<span style="background: #dcfce7; color: #15803d; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700;">✓ Available &amp; Confirmed (${escapeHtml(matchInLibrary.original_filename || matchInLibrary.document_type)})</span>`;
            } else if (matchInLibrary) {
                badgeHtml = `<span style="background: #fef3c7; color: #92400e; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700;">⏳ Uploaded, Pending OCR Confirmation</span>`;
            } else if (isMandatory) {
                badgeHtml = `<span style="background: #fee2e2; color: #991b1b; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700;">📁 Missing from Library</span>`;
            } else {
                badgeHtml = `<span style="background: #f1f5f9; color: #64748b; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 600;">Optional</span>`;
            }

            const itemEl = document.createElement("div");
            itemEl.style.padding = "10px 14px";
            itemEl.style.background = "#ffffff";
            itemEl.style.border = "1px solid #e2e8f0";
            itemEl.style.borderRadius = "6px";
            itemEl.style.display = "flex";
            itemEl.style.justifyContent = "space-between";
            itemEl.style.alignItems = "center";
            itemEl.style.flexWrap = "wrap";
            itemEl.style.gap = "8px";

            itemEl.innerHTML = `
                <div>
                    <div style="font-size: 13px; font-weight: 600; color: #1e293b;">
                        ${escapeHtml(docName)}
                        ${isMandatory ? '<span style="color: #dc2626; font-size: 11px;">(Mandatory)</span>' : '<span style="color: #64748b; font-size: 11px;">(Optional)</span>'}
                    </div>
                    <div style="font-size: 11px; color: #64748b;">Category: ${escapeHtml(category)}</div>
                </div>
                <div>${badgeHtml}</div>
            `;
            appWorkspaceDocsList.appendChild(itemEl);
        });
    }

    function renderReviewAndPortalView(defn) {
        if (!appWorkspacePortalMeta) return;

        const portalInfo = defn.portal_verification || {};
        const portalUrl = portalInfo.official_portal_url || "https://scholarships.gov.in";
        const isVerified = portalInfo.portal_verification_status === "VERIFIED";
        const availStatus = defn.application_availability_status || "CLOSED";
        const deadline = defn.last_deadline || "2026-10-31";

        let portalLinkHtml = "";
        if (isVerified) {
            portalLinkHtml = `
                <div style="margin-top: 8px;">
                    <a href="${escapeHtml(portalUrl)}" target="_blank" rel="noopener noreferrer" style="color: #15803d; font-weight: 700; text-decoration: underline;">
                        ${escapeHtml(portalUrl)} ↗
                    </a>
                </div>
            `;
        } else {
            portalLinkHtml = `
                <div style="margin-top: 8px; color: #64748b; font-style: italic;">
                    Portal status NOT_VERIFIED: External link is disabled.
                </div>
            `;
        }

        appWorkspacePortalMeta.innerHTML = `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-bottom: 12px;">
                <div>
                    <strong>Official Portal:</strong> ${escapeHtml(portalInfo.portal_name || "National Scholarship Portal (NSP)")}
                </div>
                <div>
                    <strong>Portal Verification:</strong>
                    ${isVerified ? '<span style="color: #16a34a; font-weight: 600;">✓ VERIFIED</span>' : '<span style="color: #dc2626; font-weight: 600;">NOT VERIFIED</span>'}
                </div>
                <div>
                    <strong>Application Window:</strong>
                    ${availStatus === "CLOSED" ? `<span style="color: #dc2626; font-weight: 600;">🔴 CLOSED (Closed ${escapeHtml(deadline)})</span>` : `<span style="color: #16a34a; font-weight: 600;">🟢 ${escapeHtml(availStatus)}${deadline ? ` (${escapeHtml(deadline)})` : ''}</span>`}
                </div>
                <div>
                    <strong>Application Mode:</strong> ${escapeHtml(currentWorkspaceDraft.application_mode || "FRESH")}
                </div>
            </div>
            ${portalLinkHtml}
            <div style="margin-top: 14px; padding: 10px 12px; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 12px; color: #475569;">
                <strong>Next Steps:</strong> Review your entered details in each section. Your draft is automatically saved in SahayAI. When ready, click "Continue to Official Portal" to navigate to the official portal for submission.
            </div>
        `;
    }

    async function saveWorkspaceDraft(silent = false) {
        if (!currentWorkspaceDraft) return;
        clearWorkspaceAlert();

        if (appWorkspaceSaveStatus && !silent) {
            appWorkspaceSaveStatus.textContent = "Saving draft...";
        }

        const draftId = currentWorkspaceDraft.draft_id;
        const currentData = currentWorkspaceDraft.form_data || {};

        try {
            const updateRes = await updateApplicationDraft(draftId, {
                form_data: currentData,
            });

            if (!updateRes.ok || !updateRes.data || !updateRes.data.draft) {
                if (!silent) {
                    showWorkspaceAlert(updateRes.error || "Failed to save draft.");
                    if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "";
                }
                return;
            }

            currentWorkspaceDraft = updateRes.data.draft;
            updateWorkspaceHeader();

            // Also update in userApplicationDrafts list
            const idx = userApplicationDrafts.findIndex((d) => d.draft_id === draftId);
            if (idx >= 0) {
                userApplicationDrafts[idx] = { ...userApplicationDrafts[idx], ...currentWorkspaceDraft };
                renderApplicationsGrid();
            }

            if (appWorkspaceSaveStatus && !silent) {
                appWorkspaceSaveStatus.textContent = t("applications.draftSaved", {}, "Draft saved successfully") + " (" + new Date().toLocaleTimeString() + ")";
                setTimeout(() => {
                    if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "";
                }, 3500);
            }
        } catch (err) {
            console.error("Save draft error:", err);
            if (!silent) {
                showWorkspaceAlert("Network error while saving application draft.");
                if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "";
            }
        }
    }

    function handleContinueToPortalClick() {
        if (!currentWorkspaceDraft) return;
        const defn = currentWorkspaceDraft.scheme_definition || {};
        const portalInfo = defn.portal_verification || {};

        if (portalInfo.portal_verification_status !== "VERIFIED") {
            showWorkspaceAlert("Official application portal URL cannot be verified. External submission link is disabled.");
            return;
        }

        pendingExternalPortalUrl = portalInfo.official_portal_url || "https://scholarships.gov.in";
        if (extPortalTargetUrlWrap) {
            extPortalTargetUrlWrap.textContent = pendingExternalPortalUrl;
        }

        openModal(externalPortalModal);
    }

    async function confirmExternalPortalRedirect() {
        closeModal(externalPortalModal);
        if (!currentWorkspaceDraft || !pendingExternalPortalUrl) return;

        // Transition status to READY_TO_CONTINUE
        try {
            const res = await updateApplicationDraft(currentWorkspaceDraft.draft_id, {
                status: "READY_TO_CONTINUE",
            });
            if (res.ok && res.data && res.data.draft) {
                currentWorkspaceDraft = res.data.draft;
                updateWorkspaceHeader();
                const idx = userApplicationDrafts.findIndex((d) => d.draft_id === currentWorkspaceDraft.draft_id);
                if (idx >= 0) {
                    userApplicationDrafts[idx] = { ...userApplicationDrafts[idx], ...currentWorkspaceDraft };
                    renderApplicationsGrid();
                }
            }
        } catch (err) {
            console.warn("Status transition error:", err);
        }

        // If extension is installed, request extension-initiated authorization (isolated world)
        if (extensionState !== "NOT_INSTALLED" && currentWorkspaceDraft) {
            try {
                window.postMessage(
                    {
                        type: "SAHAY_REQUEST_EXTENSION_AUTH",
                        schemeId: currentWorkspaceDraft.scheme_id,
                        portalUrl: pendingExternalPortalUrl || "https://scholarships.gov.in",
                        draftId: currentWorkspaceDraft.draft_id,
                    },
                    window.location.origin
                );
            } catch (e) {
                console.warn("Extension pre-handoff error:", e);
            }
        }

        // Open external portal safely
        window.open(pendingExternalPortalUrl, "_blank", "noopener,noreferrer");
    }

    function openDeleteDraftModal(draftId, triggerEl = null) {
        targetDraftIdToDelete = draftId;
        openModal(deleteDraftModal, triggerEl);
    }

    async function confirmDeleteDraft() {
        if (!targetDraftIdToDelete) return;
        const draftId = targetDraftIdToDelete;
        closeModal(deleteDraftModal);

        try {
            const res = await deleteApplicationDraft(draftId);
            if (!res.ok) {
                showApplicationsAlert(res.error || "Failed to delete application draft.");
                return;
            }

            userApplicationDrafts = userApplicationDrafts.filter((d) => d.draft_id !== draftId);
            renderApplicationsGrid();
            showApplicationsAlert("Application draft deleted successfully.", "success");
        } catch (err) {
            console.error("Delete draft error:", err);
            showApplicationsAlert("Network error while deleting application draft.");
        } finally {
            targetDraftIdToDelete = null;
        }
    }

    // Modal Control Event Listeners (Step 5.5A)
    if (closeAppWorkspaceModalBtn) {
        closeAppWorkspaceModalBtn.addEventListener("click", () => {
            closeModal(applicationWorkspaceModal);
        });
    }

    if (btnWorkspacePrev) {
        btnWorkspacePrev.addEventListener("click", () => {
            if (activeWorkspaceSectionIndex > 0) {
                saveWorkspaceDraft(true).then(() => {
                    renderWorkspaceSection(activeWorkspaceSectionIndex - 1);
                });
            }
        });
    }

    if (btnWorkspaceNext) {
        btnWorkspaceNext.addEventListener("click", () => {
            saveWorkspaceDraft(true).then(() => {
                renderWorkspaceSection(activeWorkspaceSectionIndex + 1);
            });
        });
    }

    if (btnWorkspaceSave) {
        btnWorkspaceSave.addEventListener("click", () => {
            saveWorkspaceDraft(false);
        });
    }

    if (btnWorkspaceContinuePortal) {
        btnWorkspaceContinuePortal.addEventListener("click", () => {
            saveWorkspaceDraft(true).then(() => {
                handleContinueToPortalClick();
            });
        });
    }

    // Step 5.5B: Autofill Handlers - Fill application form with verified details
    async function handleAutofillPreviewClick() {
        // User requested: directly autofill the form with available details instead of showing a separate drawer
        if (appWorkspaceAutofillDrawer) {
            appWorkspaceAutofillDrawer.style.display = "none";
        }
        await handleAutofillApplyClick();
    }

    async function handleAutofillApplyClick() {
        if (!currentWorkspaceDraft) return;
        clearWorkspaceAlert();
        if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "Autofilling form fields...";

        try {
            const res = await applyDraftAutofill(currentWorkspaceDraft.draft_id);
            if (!res.ok || !res.data || !res.data.draft) {
                showWorkspaceAlert(res.error || "Failed to apply autofill fields.", "error");
                if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "";
                return;
            }

            currentWorkspaceDraft = res.data.draft;
            const appliedCount = res.data.applied_fields_count || 0;
            if (appWorkspaceSaveStatus) {
                appWorkspaceSaveStatus.textContent = `Applied ${appliedCount} verified fields!`;
                setTimeout(() => {
                    if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "";
                }, 3500);
            }

            if (appliedCount > 0) {
                showWorkspaceAlert(`✓ Successfully autofilled ${appliedCount} verified fields into the application form from your documents and profile.`, "success");
            } else {
                showWorkspaceAlert("Application form is up to date with your verified documents and profile.", "success");
            }

            updateWorkspaceHeader();
            renderWorkspaceSection(activeWorkspaceSectionIndex);

            if (appWorkspaceAutofillDrawer) {
                appWorkspaceAutofillDrawer.style.display = "none";
            }
        } catch (err) {
            console.error("Autofill apply error:", err);
            showWorkspaceAlert("Network error while applying autofill fields.", "error");
            if (appWorkspaceSaveStatus) appWorkspaceSaveStatus.textContent = "";
        }
    }

    if (btnAppWorkspaceAutofillPreview) {
        btnAppWorkspaceAutofillPreview.addEventListener("click", handleAutofillPreviewClick);
    }

    if (btnAppWorkspaceAutofillApply) {
        btnAppWorkspaceAutofillApply.addEventListener("click", handleAutofillApplyClick);
    }

    if (btnCloseAutofillDrawer) {
        btnCloseAutofillDrawer.addEventListener("click", () => {
            if (appWorkspaceAutofillDrawer) appWorkspaceAutofillDrawer.style.display = "none";
        });
    }

    if (closeExtPortalModalBtn) {
        closeExtPortalModalBtn.addEventListener("click", () => {
            closeModal(externalPortalModal);
        });
    }

    if (btnCancelExtPortal) {
        btnCancelExtPortal.addEventListener("click", () => {
            closeModal(externalPortalModal);
        });
    }

    if (btnConfirmExtPortal) {
        btnConfirmExtPortal.addEventListener("click", () => {
            confirmExternalPortalRedirect();
        });
    }

    if (closeDeleteDraftModalBtn) {
        closeDeleteDraftModalBtn.addEventListener("click", () => {
            closeModal(deleteDraftModal);
            targetDraftIdToDelete = null;
        });
    }

    if (btnCancelDeleteDraft) {
        btnCancelDeleteDraft.addEventListener("click", () => {
            closeModal(deleteDraftModal);
            targetDraftIdToDelete = null;
        });
    }

    if (btnConfirmDeleteDraft) {
        btnConfirmDeleteDraft.addEventListener("click", () => {
            confirmDeleteDraft();
        });
    }

    // ---------------------------------------------------------------------------
    // Step 5.5C: Chrome Extension Integration Logic
    // ---------------------------------------------------------------------------
    function setExtensionState(newState) {
        extensionState = newState;
        if (!extensionStatusCard || !extensionStateBadge || !extensionStateDesc) return;

        if (newState === "CONNECTED") {
            extensionStateBadge.className = "badge";
            extensionStateBadge.style.background = "#dcfce7";
            extensionStateBadge.style.color = "#15803d";
            extensionStateBadge.textContent = t("extension.stateConnected", {}, "Connected & Ready");
            extensionStateDesc.textContent = t("extension.descConnected", {}, "Extension is ready to autofill verified fields on the National Scholarship Portal.");
            if (btnConnectExtension) {
                btnConnectExtension.textContent = t("extension.btnReauthorize", {}, "Re-authorize");
                btnConnectExtension.className = "btn btn-secondary";
            }
        } else if (newState === "INSTALLED_NOT_CONNECTED") {
            extensionStateBadge.className = "badge";
            extensionStateBadge.style.background = "#fef3c7";
            extensionStateBadge.style.color = "#92400e";
            extensionStateBadge.textContent = t("extension.stateInstalled", {}, "Installed - Not Connected");
            extensionStateDesc.textContent = t("extension.descInstalled", {}, "Extension detected. Connect your active scholarship draft to enable autofill.");
            if (btnConnectExtension) {
                btnConnectExtension.textContent = t("extension.btnConnect", {}, "Connect Extension");
                btnConnectExtension.className = "btn btn-primary";
            }
        } else if (newState === "PENDING_APPROVAL") {
            extensionStateBadge.className = "badge";
            extensionStateBadge.style.background = "#eff6ff";
            extensionStateBadge.style.color = "#1d4ed8";
            extensionStateBadge.textContent = "Pending Extension Approval";
            extensionStateDesc.textContent = "Please click the SahayAI extension in your browser toolbar to approve access.";
            if (btnConnectExtension) {
                btnConnectExtension.textContent = "Approve in Toolbar...";
                btnConnectExtension.className = "btn btn-secondary";
            }
        } else if (newState === "ERROR") {
            extensionStateBadge.className = "badge";
            extensionStateBadge.style.background = "#fee2e2";
            extensionStateBadge.style.color = "#991b1b";
            extensionStateBadge.textContent = t("extension.stateError", {}, "Connection Error");
            extensionStateDesc.textContent = t("extension.descError", {}, "Unable to establish extension connection. Please reload the extension.");
            if (btnConnectExtension) {
                btnConnectExtension.textContent = t("extension.btnRetry", {}, "Retry Connection");
                btnConnectExtension.className = "btn btn-secondary";
            }
        } else {
            // NOT_INSTALLED
            extensionStateBadge.className = "badge";
            extensionStateBadge.style.background = "#f1f5f9";
            extensionStateBadge.style.color = "#64748b";
            extensionStateBadge.textContent = t("extension.stateNotInstalled", {}, "Not Installed");
            extensionStateDesc.textContent = t("extension.descNotInstalled", {}, "Install the extension to autofill scholarship application forms on the National Scholarship Portal.");
            if (btnConnectExtension) {
                btnConnectExtension.textContent = t("extension.btnInstall", {}, "Install Extension");
                btnConnectExtension.className = "btn btn-primary";
            }
        }
    }

    function checkExtensionPresence() {
        const hasAttr = document.documentElement.getAttribute("data-sahay-extension-installed") === "true";
        if (hasAttr) {
            setExtensionState("INSTALLED_NOT_CONNECTED");
            // Ping extension for active grant
            window.postMessage({ type: "SAHAY_CHECK_EXTENSION" }, window.location.origin);
        } else {
            setExtensionState("NOT_INSTALLED");
        }
    }

    async function handleConnectExtensionClick() {
        if (extensionState === "NOT_INSTALLED") {
            openModal(extensionGuideModal, btnConnectExtension);
            return;
        }

        // Determine scheme to connect
        let schemeId = "SCHEME_EDU_001_PM_USP_CSSS";
        let draftId = null;

        if (currentWorkspaceDraft) {
            schemeId = currentWorkspaceDraft.scheme_id;
            draftId = currentWorkspaceDraft.draft_id;
        } else if (userApplicationDrafts.length > 0) {
            const activeDraft = userApplicationDrafts.find((d) => d.status !== "CLOSED") || userApplicationDrafts[0];
            schemeId = activeDraft.scheme_id;
            draftId = activeDraft.draft_id;
        }

        if (!draftId) {
            showApplicationsAlert("Please start or open a scholarship application draft before connecting the browser extension.", "info");
            return;
        }

        if (btnConnectExtension) btnConnectExtension.textContent = "Connecting...";

        // Delegate authorization to isolated extension content script (zero bearer token exposure in page JS)
        window.postMessage(
            {
                type: "SAHAY_REQUEST_EXTENSION_AUTH",
                schemeId: schemeId,
                portalUrl: "https://scholarships.gov.in",
                draftId: draftId,
            },
            window.location.origin
        );
    }

    // Bridge message listener
    window.addEventListener("message", (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data;
        if (!data || typeof data !== "object") return;

        if (data.type === "SAHAY_EXTENSION_STATUS" && data.installed) {
            if (data.connected) {
                setExtensionState("CONNECTED");
            } else if (data.pendingApproval) {
                setExtensionState("PENDING_APPROVAL");
                showApplicationsAlert("Authorization request staged. Please click the SahayAI icon in your Chrome toolbar to approve access.", "info");
            } else {
                setExtensionState("INSTALLED_NOT_CONNECTED");
            }
        } else if (data.type === "SAHAY_EXTENSION_AUTH_RESULT") {
            if (data.success) {
                setExtensionState("CONNECTED");
                showApplicationsAlert("SahayAI Extension connected successfully! You may now open the National Scholarship Portal.", "success");
            } else {
                setExtensionState("ERROR");
                showApplicationsAlert(data.error || "Failed to authorize extension grant.");
            }
        }
    });

    window.addEventListener("sahay-extension-ready", () => {
        checkExtensionPresence();
    });

    if (btnExtensionGuide) {
        btnExtensionGuide.addEventListener("click", () => {
            openModal(extensionGuideModal, btnExtensionGuide);
        });
    }

    if (btnConnectExtension) {
        btnConnectExtension.addEventListener("click", handleConnectExtensionClick);
    }

    if (closeExtGuideModalBtn) {
        closeExtGuideModalBtn.addEventListener("click", () => {
            closeModal(extensionGuideModal);
        });
    }

    if (btnCloseExtGuide) {
        btnCloseExtGuide.addEventListener("click", () => {
            closeModal(extensionGuideModal);
        });
    }


    // ---------------------------------------------------------------------------
    // Initial Session Validation & Dual-Mode Dashboard Orchestration (Phase 7)
    // ---------------------------------------------------------------------------
    try {
        // Step 1: Query active session status (handles both registered citizens and guests)
        const statusRes = await apiFetch("/auth/session-status");

        if (!statusRes.ok || !statusRes.data || !statusRes.data.authenticated) {
            // No active session exists
            clearCsrfCache();
            window.location.href = "login.html";
            return;
        }

        const sessionInfo = statusRes.data;

        if (sessionInfo.is_guest) {
            // Mode: Anonymous Guest Session (Step 1 & Step 2 Unified Dashboard)
            isGuestMode = true;
            guestContextData = sessionInfo.context || {};

            if (welcomeHeading) welcomeHeading.textContent = t("dashboard.welcomeCitizen", {}, "Welcome, Citizen!");
            if (welcomeSubtitle) welcomeSubtitle.textContent = t("dashboard.welcomeSubtitleGuest", {}, "Explore government scholarships and welfare schemes. Check eligibility and get AI assistance instantly without registration.");
            if (citizenBadge) {
                citizenBadge.textContent = t("dashboard.badgeGuest", {}, "Guest Mode");
                citizenBadge.className = "citizen-badge badge-guest-mode";
            }
            if (navCitizenName) navCitizenName.style.display = "none";
            if (logoutBtn) logoutBtn.style.display = "none";
            if (navLoginLink) navLoginLink.style.display = "inline-block";
            if (navSignupLink) navSignupLink.style.display = "inline-block";
            if (navGuestBadge) {
                navGuestBadge.style.display = "inline-block";
                navGuestBadge.textContent = t("nav.guestMode", {}, "Guest Mode");
            }
            if (endGuestSessionBtn) {
                endGuestSessionBtn.style.display = "inline-block";
                endGuestSessionBtn.textContent = t("nav.endGuestSession", {}, "End Guest Session");
            }
            if (guestNoticeBanner) {
                guestNoticeBanner.style.display = "block";
                guestNoticeBanner.innerHTML = t("dashboard.guestNoticeText", {}, '<strong>Guest Mode:</strong> You are exploring SahayAI without an account. You can freely browse schemes, view eligibility criteria, and check eligibility on demand. To save a permanent profile, you can <a href="signup.html">Create an Account</a> or <a href="login.html">Log In</a> anytime.');
            }

            // Remove/hide Profile Card for anonymous visitors
            const profileCard = document.getElementById("profileCardSection");
            if (profileCard) profileCard.style.display = "none";

            // Completely hide Documents and Profile-Based Scheme Discovery Cards for anonymous visitors.
            // Do not show a locked card, restricted card, signup prompt or disabled card.
            const cardDocuments = document.getElementById("cardDocuments");
            const cardRecommendations = document.getElementById("cardRecommendations");
            const fiveFeaturesGrid = document.getElementById("fiveFeaturesGrid");
            if (cardDocuments) {
                cardDocuments.style.display = "none";
            }
            if (cardRecommendations) {
                cardRecommendations.style.display = "none";
            }
            if (fiveFeaturesGrid) {
                fiveFeaturesGrid.classList.remove("five-cards-grid", "four-cards-grid");
                fiveFeaturesGrid.classList.add("three-cards-grid");
            }

            // Hide Recommendations Tab for guests to prevent UI access to profile recommendations
            const tabRecommendations = document.getElementById("tabRecommendations");
            if (tabRecommendations) {
                tabRecommendations.style.display = "none";
            }

            // My Documents & Applications: Completely hide navigation link and persistent sections for guests
            if (navDocumentsLink) navDocumentsLink.style.display = "none";
            if (documentsSection) documentsSection.style.display = "none";
            if (navApplicationsLink) navApplicationsLink.style.display = "none";
            if (applicationsSection) applicationsSection.style.display = "none";

            // Profile menu: Hide for guests
            const profileMenuContainer = document.getElementById("profileMenuContainer");
            if (profileMenuContainer) profileMenuContainer.style.display = "none";

            // Default directly to Explore All Schemes catalog
            switchTab("catalog");

        } else {
            // Mode: Registered Citizen Account
            isGuestMode = false;

            // Navigation: Show registered user identity and logout; hide guest-only controls
            if (navCitizenName) navCitizenName.style.display = "inline-block";
            if (logoutBtn) {
                logoutBtn.style.display = "inline-block";
                logoutBtn.textContent = t("nav.logout", {}, "Log Out");
            }
            if (navLoginLink) navLoginLink.style.display = "none";
            if (navSignupLink) navSignupLink.style.display = "none";
            if (navGuestBadge) navGuestBadge.style.display = "none";
            if (endGuestSessionBtn) endGuestSessionBtn.style.display = "none";
            if (guestNoticeBanner) guestNoticeBanner.style.display = "none";

            // Profile menu: Show and init for registered citizens
            const profileMenuContainer = document.getElementById("profileMenuContainer");
            if (profileMenuContainer) profileMenuContainer.style.display = "inline-flex";
            if (window.SahayNav && typeof SahayNav.initProfileDropdown === "function") {
                SahayNav.initProfileDropdown();
            }

            // My Documents & Applications: Show navigation links and persistent sections for registered citizens
            if (navDocumentsLink) navDocumentsLink.style.display = "inline-block";
            if (documentsSection) documentsSection.style.display = "block";
            if (navApplicationsLink) navApplicationsLink.style.display = "inline-block";
            if (applicationsSection) applicationsSection.style.display = "block";

            const cardDocsBadge = document.getElementById("cardDocsBadge");
            const cardDocsDescription = document.getElementById("cardDocsDescription");
            const cardDocsActionLink = document.getElementById("cardDocsActionLink");
            if (cardDocsBadge) {
                cardDocsBadge.className = "feature-active-badge";
                cardDocsBadge.textContent = t("cards.active", {}, "Active");
            }
            if (cardDocsDescription) {
                cardDocsDescription.textContent = t("documents.sectionSubtitle", {}, "Securely store, organize, and reuse your verified documents.");
            }
            if (cardDocsActionLink) {
                cardDocsActionLink.className = "card-action-link primary-action";
                cardDocsActionLink.textContent = t("nav.myDocuments", {}, "My Documents") + " \u2192";
            }

            // Show all five interactive methods for registered citizens (Step 4D.2)
            const cardDocuments = document.getElementById("cardDocuments");
            const cardRecommendations = document.getElementById("cardRecommendations");
            const fiveFeaturesGrid = document.getElementById("fiveFeaturesGrid");
            if (cardDocuments) {
                cardDocuments.style.display = "";
            }
            if (cardRecommendations) {
                cardRecommendations.style.display = "";
            }
            if (fiveFeaturesGrid) {
                fiveFeaturesGrid.classList.remove("three-cards-grid", "four-cards-grid");
                fiveFeaturesGrid.classList.add("five-cards-grid");
            }

            const cardRecBadge = document.getElementById("cardRecBadge");
            const cardRecDescription = document.getElementById("cardRecDescription");
            const cardRecActionLink = document.getElementById("cardRecActionLink");

            if (cardRecBadge) {
                cardRecBadge.className = "feature-active-badge";
                cardRecBadge.textContent = t("cards.active", {}, "Active");
            }
            if (cardRecDescription) {
                cardRecDescription.textContent = t("cards.recDesc", {}, "Discover schemes based on personal information.");
            }
            if (cardRecActionLink) {
                cardRecActionLink.className = "card-action-link primary-action";
                cardRecActionLink.textContent = t("cards.recAction", {}, "View Matches \u2192");
            }

            // Show Recommendations Tab for registered citizens
            const tabRecommendations = document.getElementById("tabRecommendations");
            if (tabRecommendations) {
                tabRecommendations.style.display = "";
            }

            if (navLoginLink) navLoginLink.style.display = "none";
            if (navSignupLink) navSignupLink.style.display = "none";

            const profileCard = document.getElementById("profileCardSection");
            if (profileCard) profileCard.style.display = "block";

            const response = await apiFetch("/profile/me");

            if (!response.ok) {
                if (response.status === 401) {
                    window.location.href = "login.html";
                    return;
                }
                if (response.status === 404) {
                    window.location.href = "profile.html";
                    return;
                }
                showAlert(response.error || "Unable to retrieve your citizen profile.", "error");
                return;
            }

            const profile = response.data && response.data.profile;
            if (!profile) {
                window.location.href = "profile.html";
                return;
            }

            currentCitizenProfile = profile;

            // Populate Registered Profile UI
            if (welcomeHeading) welcomeHeading.textContent = t("dashboard.welcomeUser", { name: profile.full_name }, `Welcome, ${profile.full_name}!`);
            if (welcomeSubtitle) welcomeSubtitle.textContent = t("dashboard.welcomeSubtitleRegistered", {}, "Your SahayAI citizen profile is active. Here is your demographic information for government benefit matching.");
            if (citizenBadge) {
                citizenBadge.textContent = t("dashboard.badgeVerified", {}, "Verified Profile");
                citizenBadge.className = "citizen-badge";
            }
            if (navCitizenName) navCitizenName.textContent = profile.full_name;
            const dropdownCitizenName = document.getElementById("dropdownCitizenName");
            if (dropdownCitizenName) dropdownCitizenName.textContent = profile.full_name || "Citizen";
            const dropdownCitizenId = document.getElementById("dropdownCitizenId");
            if (dropdownCitizenId && profile.user_id) {
                dropdownCitizenId.textContent = "ID: " + profile.user_id;
                dropdownCitizenId.style.display = "block";
            }

            if (dispFullName) dispFullName.textContent = profile.full_name || "--";
            if (dispUserId) dispUserId.textContent = profile.user_id || "--";

            const ageText = profile.age !== null && profile.age !== undefined ? `${profile.age} years` : "--";
            const dobText = profile.date_of_birth ? ` (${profile.date_of_birth})` : "";
            if (dispAgeDob) dispAgeDob.textContent = `${ageText}${dobText}`;

            if (dispGender) dispGender.textContent = profile.gender || "--";
            if (dispLocation) dispLocation.textContent = `${profile.district || "--"}, ${profile.state || "--"}`;

            if (profile.annual_income !== null && profile.annual_income !== undefined) {
                if (dispIncome) dispIncome.textContent = `${formatCurrency(profile.annual_income)} / year`;
            } else {
                if (dispIncome) dispIncome.textContent = "--";
            }

            if (dispOccupation) dispOccupation.textContent = profile.occupation || "--";
            if (dispCaste) dispCaste.textContent = profile.caste_category || "--";
            if (dispBpl) dispBpl.textContent = profile.is_bpl ? "Yes (BPL Card Holder)" : "No";

            if (dispConfirmed) {
                if (profile.user_confirmed) {
                    dispConfirmed.textContent = "Verified Citizen Record";
                    dispConfirmed.style.color = "#15803d";
                } else {
                    dispConfirmed.textContent = "Pending Citizen Confirmation";
                    dispConfirmed.style.color = "#b45309";
                }
            }

            // Initialize Scheme Discovery (default to Recommendations tab)
            switchTab("recommendations");

            // Load Citizen Documents Library & Applications
            await loadUserDocuments();
            if (!isGuestMode) {
                await loadCitizenApplications();
                loadRecommendations(applicationTypeSelect ? applicationTypeSelect.value : "FRESH");
            }
        }

    } catch (err) {
        console.error("Dashboard profile load error:", err);
        showAlert("Failed to connect to the profile service. Please verify server connectivity.");
    }

    // ---------------------------------------------------------------------------
    // Global Language Switch Dynamic Listener
    // ---------------------------------------------------------------------------
    window.addEventListener("sahay:languageChanged", (e) => {
        const lang = e.detail?.language || "en";
        const voiceLocale = e.detail?.voiceLocale || "en-IN";

        // Update Welcome Heading & Subtitle and Navigation
        if (isGuestMode) {
            if (welcomeHeading) welcomeHeading.textContent = t("dashboard.welcomeCitizen", {}, "Welcome, Citizen!");
            if (welcomeSubtitle) welcomeSubtitle.textContent = t("dashboard.welcomeSubtitleGuest", {}, "Explore government scholarships and welfare schemes. Check eligibility and get AI assistance instantly without registration.");
            if (citizenBadge) citizenBadge.textContent = t("dashboard.badgeGuest", {}, "Guest Mode");
            if (navLoginLink) navLoginLink.textContent = t("nav.login", {}, "Log In");
            if (navSignupLink) navSignupLink.textContent = t("nav.signup", {}, "Create Account");
            if (navGuestBadge) navGuestBadge.textContent = t("nav.guestMode", {}, "Guest Mode");
            if (endGuestSessionBtn) {
                endGuestSessionBtn.textContent = t("nav.endGuestSession", {}, "End Guest Session");
                endGuestSessionBtn.style.display = "inline-block";
            }
            if (logoutBtn) logoutBtn.style.display = "none";
            if (navCitizenName) navCitizenName.style.display = "none";
        } else {
            if (logoutBtn) {
                logoutBtn.style.display = "inline-block";
                logoutBtn.textContent = t("nav.logout", {}, "Log Out");
            }
            if (navCitizenName) navCitizenName.style.display = "inline-block";
            if (navLoginLink) navLoginLink.style.display = "none";
            if (navSignupLink) navSignupLink.style.display = "none";
            if (navGuestBadge) navGuestBadge.style.display = "none";
            if (endGuestSessionBtn) endGuestSessionBtn.style.display = "none";

            if (currentCitizenProfile) {
                const name = currentCitizenProfile.full_name || "Citizen";
                if (welcomeHeading) welcomeHeading.textContent = t("dashboard.welcomeUser", { name: name }, `Welcome, ${name}!`);
                if (welcomeSubtitle) welcomeSubtitle.textContent = t("dashboard.welcomeSubtitleRegistered", {}, "Your SahayAI citizen profile is active. Here is your demographic information for government benefit matching.");
                if (citizenBadge) citizenBadge.textContent = t("dashboard.badgeVerified", {}, "Verified Profile");
            }
        }

        // Re-render schemes if loaded
        if (activeTab === "recommendations" && lastLoadedRecommendationsData) {
            renderRecommendations(lastLoadedRecommendationsData);
        } else if (activeTab === "catalog" && lastLoadedCatalogData) {
            renderCatalog(lastLoadedCatalogData);
        }

        // Re-render documents library & applications if registered user
        if (!isGuestMode) {
            updateDocSummaryStats();
            renderDocumentsGrid();
            renderApplicationsGrid();
        }

        // Update Voice default locale if not manually changed
        if (voiceLangSelect && !userManuallyChangedVoiceLang) {
            voiceLangSelect.value = voiceLocale;
            const langName = voiceLangSelect.options[voiceLangSelect.selectedIndex]?.text || "English";
            if (voiceLangHint) {
                voiceLangHint.textContent = t("voice.hint", { lang: langName }, `Listening in ${langName}. Click microphone to begin.`);
            }
            if (voiceStatusText && !isListening) {
                voiceStatusText.textContent = t("voice.statusIdle", {}, "Click the microphone to start speaking");
            }
        }

        // Update Initial Greeting in chat modal if present
        const initialGreetingText = document.getElementById("chatInitialGreetingText");
        if (initialGreetingText) {
            initialGreetingText.textContent = t("chat.initialGreeting");
        }
    });
});
