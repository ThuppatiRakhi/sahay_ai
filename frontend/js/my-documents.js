/**
 * SahayAI - Dedicated Citizen Documents Page Controller
 * Handles document library grid, multi-attribute filtering, stats, upload modal,
 * review/confirmation, replacement, archival, permanent deletion, and metadata viewing.
 */

document.addEventListener("DOMContentLoaded", async function () {
    "use strict";

    // ---------------------------------------------------------------------------
    // DOM References
    // ---------------------------------------------------------------------------
    const documentsSection = document.getElementById("documentsSection");
    const documentsAlertBox = document.getElementById("documentsAlertBox");
    const guestNoticeBanner = document.getElementById("guestNoticeBanner");
    const documentsGrid = document.getElementById("documentsGrid");

    const docStatTotal = document.getElementById("docStatTotal");
    const docStatConfirmed = document.getElementById("docStatConfirmed");
    const docStatPending = document.getElementById("docStatPending");
    const docStatArchived = document.getElementById("docStatArchived");

    const docSearchInput = document.getElementById("docSearchInput");
    const docCategoryFilter = document.getElementById("docCategoryFilter");
    const docStatusFilter = document.getElementById("docStatusFilter");
    const docIncludeArchivedToggle = document.getElementById("docIncludeArchivedToggle");
    const btnResetDocFilters = document.getElementById("btnResetDocFilters");

    const btnOpenUploadModal = document.getElementById("btnOpenUploadModal");
    const documentUploadModal = document.getElementById("documentUploadModal");
    const closeDocUploadModalBtn = document.getElementById("closeDocUploadModalBtn");
    const closeDocUploadBottomBtn = document.getElementById("closeDocUploadBottomBtn");
    const docUploadForm = document.getElementById("docUploadForm");
    const docUploadDropzone = document.getElementById("docUploadDropzone");
    const docFileInput = document.getElementById("docFileInput");
    const docCategorySelect = document.getElementById("docCategorySelect");
    const docTypeSelect = document.getElementById("docTypeSelect");
    const docSelectedFileName = document.getElementById("docSelectedFileName");
    const docUploadAlert = document.getElementById("docUploadAlert");
    const docUploadProgress = document.getElementById("docUploadProgress");
    const docUploadResultSection = document.getElementById("docUploadResultSection");
    const docUploadExtractedFields = document.getElementById("docUploadExtractedFields");
    const btnUploadGoToReview = document.getElementById("btnUploadGoToReview");
    const btnUploadDone = document.getElementById("btnUploadDone");
    const docUploadFooter = document.getElementById("docUploadFooter");
    const btnStartUploadSubmit = document.getElementById("btnStartUploadSubmit");

    const documentReviewModal = document.getElementById("documentReviewModal");
    const closeDocReviewModalBtn = document.getElementById("closeDocReviewModalBtn");
    const closeDocReviewBottomBtn = document.getElementById("closeDocReviewBottomBtn");
    const docReviewAlert = document.getElementById("docReviewAlert");
    const docReviewLoading = document.getElementById("docReviewLoading");
    const docReviewTableWrap = document.getElementById("docReviewTableWrap");
    const docReviewTableBody = document.getElementById("docReviewTableBody");
    const btnSaveConfirmations = document.getElementById("btnSaveConfirmations");

    const documentReplaceModal = document.getElementById("documentReplaceModal");
    const closeDocReplaceModalBtn = document.getElementById("closeDocReplaceModalBtn");
    const closeDocReplaceBottomBtn = document.getElementById("closeDocReplaceBottomBtn");
    const docReplaceForm = document.getElementById("docReplaceForm");
    const docReplaceTargetInfo = document.getElementById("docReplaceTargetInfo");
    const docReplaceDropzone = document.getElementById("docReplaceDropzone");
    const docReplaceFileInput = document.getElementById("docReplaceFileInput");
    const docReplaceSelectedFileName = document.getElementById("docReplaceSelectedFileName");
    const docReplaceAlert = document.getElementById("docReplaceAlert");
    const docReplaceProgress = document.getElementById("docReplaceProgress");
    const btnConfirmReplaceSubmit = document.getElementById("btnConfirmReplaceSubmit");

    const documentDeleteModal = document.getElementById("documentDeleteModal");
    const closeDocDeleteModalBtn = document.getElementById("closeDocDeleteModalBtn");
    const btnCancelDeleteModal = document.getElementById("btnCancelDeleteModal");
    const docDeleteTargetInfo = document.getElementById("docDeleteTargetInfo");
    const docDeleteAlert = document.getElementById("docDeleteAlert");
    const btnArchiveFromDeleteModal = document.getElementById("btnArchiveFromDeleteModal");
    const btnPermanentDeleteFromModal = document.getElementById("btnPermanentDeleteFromModal");

    const documentMetadataModal = document.getElementById("documentMetadataModal");
    const closeDocMetadataModalBtn = document.getElementById("closeDocMetadataModalBtn");
    const closeDocMetadataBottomBtn = document.getElementById("closeDocMetadataBottomBtn");
    const docMetadataFieldsList = document.getElementById("docMetadataFieldsList");
    const docMetadataExtractedTableWrap = document.getElementById("docMetadataExtractedTableWrap");
    const btnMetadataDownloadBtn = document.getElementById("btnMetadataDownloadBtn");
    const btnMetadataReviewBtn = document.getElementById("btnMetadataReviewBtn");

    const profileMenuContainer = document.getElementById("profileMenuContainer");
    const navCitizenName = document.getElementById("navCitizenName");
    const logoutBtn = document.getElementById("logoutBtn");
    const navLoginLink = document.getElementById("navLoginLink");
    const navSignupLink = document.getElementById("navSignupLink");
    const navGuestBadge = document.getElementById("navGuestBadge");
    const endGuestSessionBtn = document.getElementById("endGuestSessionBtn");
    const dropdownCitizenName = document.getElementById("dropdownCitizenName");
    const dropdownCitizenId = document.getElementById("dropdownCitizenId");

    // State
    let userDocuments = [];
    let isUploadingDocument = false;
    let isReplacingDocument = false;
    let isSavingConfirmations = false;
    let activeReviewDocId = null;
    let activeReplaceDoc = null;
    let activeDeleteDoc = null;
    let activeMetadataDocId = null;
    let selectedUploadFile = null;
    let selectedReplaceFile = null;

    const MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024;
    const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024;

    function t(key, params, fallback) {
        if (window.I18n && typeof I18n.t === "function") {
            return I18n.t(key, params, fallback);
        }
        return fallback || key;
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
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
        try {
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
        } catch (e) {
            console.warn("Failed to render pending documents checklist:", e);
        }
    }

    function showDocAlert(msg, isError) {
        if (!documentsAlertBox) return;
        documentsAlertBox.textContent = msg;
        documentsAlertBox.className = isError ? "alert-box alert-error" : "alert-box alert-success";
        documentsAlertBox.style.display = "block";
    }

    function clearDocAlert() {
        if (!documentsAlertBox) return;
        documentsAlertBox.textContent = "";
        documentsAlertBox.style.display = "none";
    }

    function showModalAlert(box, msg, isError) {
        if (!box) return;
        box.textContent = msg;
        box.className = isError ? "alert-box alert-error" : "alert-box alert-success";
        box.style.display = "block";
    }

    function clearModalAlert(box) {
        if (!box) return;
        box.textContent = "";
        box.style.display = "none";
    }

    // Modal Helpers
    let lastActiveElement = null;
    function openModal(modal, triggerEl) {
        if (!modal) return;
        lastActiveElement = triggerEl || document.activeElement;
        modal.classList.add("active");
        modal.classList.add("show");
        const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (focusable.length) focusable[0].focus();
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove("active");
        modal.classList.remove("show");
        if (lastActiveElement && typeof lastActiveElement.focus === "function") {
            lastActiveElement.focus();
        }
    }

    function closeAllModals() {
        closeModal(documentUploadModal);
        closeModal(documentReviewModal);
        closeModal(documentReplaceModal);
        closeModal(documentDeleteModal);
        closeModal(documentMetadataModal);
    }

    // Close on backdrop click
    [documentUploadModal, documentReviewModal, documentReplaceModal, documentDeleteModal, documentMetadataModal].forEach(modal => {
        if (!modal) return;
        modal.addEventListener("click", (e) => {
            if (e.target === modal) closeModal(modal);
        });
    });

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" || e.keyCode === 27) {
            closeAllModals();
        }
    });

    // Wire close buttons
    if (closeDocUploadModalBtn) closeDocUploadModalBtn.addEventListener("click", () => closeModal(documentUploadModal));
    if (closeDocUploadBottomBtn) closeDocUploadBottomBtn.addEventListener("click", () => closeModal(documentUploadModal));
    if (closeDocReviewModalBtn) closeDocReviewModalBtn.addEventListener("click", () => closeModal(documentReviewModal));
    if (closeDocReviewBottomBtn) closeDocReviewBottomBtn.addEventListener("click", () => closeModal(documentReviewModal));
    if (closeDocReplaceModalBtn) closeDocReplaceModalBtn.addEventListener("click", () => closeModal(documentReplaceModal));
    if (closeDocReplaceBottomBtn) closeDocReplaceBottomBtn.addEventListener("click", () => closeModal(documentReplaceModal));
    if (closeDocDeleteModalBtn) closeDocDeleteModalBtn.addEventListener("click", () => closeModal(documentDeleteModal));
    if (btnCancelDeleteModal) btnCancelDeleteModal.addEventListener("click", () => closeModal(documentDeleteModal));
    if (closeDocMetadataModalBtn) closeDocMetadataModalBtn.addEventListener("click", () => closeModal(documentMetadataModal));
    if (closeDocMetadataBottomBtn) closeDocMetadataBottomBtn.addEventListener("click", () => closeModal(documentMetadataModal));

    // ---------------------------------------------------------------------------
    // Category & Type Helpers
    // ---------------------------------------------------------------------------
    function getCategoryLabel(cat) {
        const map = {
            IDENTITY: "Identity",
            INCOME: "Income",
            CATEGORY_CERTIFICATE: "Category Certificate",
            RESIDENCE: "Residence",
            ACADEMIC: "Academic",
            BANK: "Bank",
            DISABILITY: "Disability",
            SPECIAL_CATEGORY: "Special Category",
            APPLICATION_ASSET: "Application Asset",
            OTHER: "Other"
        };
        return map[cat] || cat || "General";
    }

    function getTypeLabel(type) {
        if (!type) return "Document";
        return type.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
    }

    function getCategoryIcon(cat, mime) {
        if (mime === "application/pdf") return "📄";
        if (cat === "IDENTITY") return "🪪";
        if (cat === "INCOME") return "💰";
        if (cat === "CATEGORY_CERTIFICATE") return "📜";
        if (cat === "RESIDENCE") return "🏠";
        if (cat === "ACADEMIC") return "🎓";
        if (cat === "BANK") return "🏦";
        if (cat === "DISABILITY") return "♿";
        return "📁";
    }

    function formatFileSize(bytes) {
        if (!bytes || bytes === 0) return "0 B";
        const k = 1024;
        const sizes = ["B", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
    }

    function formatDocDate(isoStr) {
        if (!isoStr) return "--";
        try {
            return new Date(isoStr).toLocaleDateString();
        } catch {
            return isoStr;
        }
    }

    // ---------------------------------------------------------------------------
    // Navigation & Dropdown Setup
    // ---------------------------------------------------------------------------
    if (window.SahayNav && typeof SahayNav.initProfileDropdown === "function") {
        SahayNav.initProfileDropdown();
    }

    if (logoutBtn) {
        logoutBtn.addEventListener("click", async function (e) {
            e.preventDefault();
            if (typeof logoutCitizen === "function") {
                await logoutCitizen();
            } else {
                try {
                    await fetch("/auth/logout", { method: "POST", credentials: "include" });
                } catch (err) {
                    console.error("Logout error:", err);
                }
                window.location.href = "login.html";
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Session Verification & Data Load
    // ---------------------------------------------------------------------------
    try {
        const sessionRes = await apiFetch("/auth/session-status");
        if (!sessionRes.ok || !sessionRes.data || !sessionRes.data.authenticated) {
            window.location.href = "login.html";
            return;
        }

        const session = sessionRes.data;
        if (session.is_guest) {
            if (guestNoticeBanner) guestNoticeBanner.style.display = "block";
            if (documentsSection) documentsSection.style.display = "none";
            if (profileMenuContainer) profileMenuContainer.style.display = "none";
            if (navLoginLink) navLoginLink.style.display = "inline-block";
            if (navSignupLink) navSignupLink.style.display = "inline-block";
            if (navGuestBadge) navGuestBadge.style.display = "inline-block";
            if (endGuestSessionBtn) endGuestSessionBtn.style.display = "inline-block";
            return;
        }

        // Registered Citizen
        if (profileMenuContainer) profileMenuContainer.style.display = "inline-flex";
        if (navLoginLink) navLoginLink.style.display = "none";
        if (navSignupLink) navSignupLink.style.display = "none";
        if (navGuestBadge) navGuestBadge.style.display = "none";
        if (endGuestSessionBtn) endGuestSessionBtn.style.display = "none";
        if (guestNoticeBanner) guestNoticeBanner.style.display = "none";
        if (documentsSection) documentsSection.style.display = "block";

        // Fetch citizen profile for dropdown
        const profRes = await apiFetch("/profile/me");
        if (profRes.ok && profRes.data && profRes.data.profile) {
            const p = profRes.data.profile;
            if (navCitizenName) navCitizenName.textContent = p.full_name || "Citizen";
            if (dropdownCitizenName) dropdownCitizenName.textContent = p.full_name || "Citizen";
            if (dropdownCitizenId && p.user_id) {
                dropdownCitizenId.textContent = "ID: " + p.user_id;
                dropdownCitizenId.style.display = "block";
            }
        }

        await loadUserDocuments();

    } catch (err) {
        console.error("Document page load error:", err);
        showDocAlert("Failed to connect to document services. Please refresh.", true);
    }

    // ---------------------------------------------------------------------------
    // Fetch & Render Documents
    // ---------------------------------------------------------------------------
    async function loadUserDocuments() {
        if (!documentsGrid) return;
        clearDocAlert();

        documentsGrid.innerHTML = `
            <div class="doc-empty-state">
                <span class="chat-spinner" aria-hidden="true"></span>
                <p style="margin-top: 10px; color: #64748b;">Loading your documents from secure vault...</p>
            </div>
        `;

        const category = docCategoryFilter ? docCategoryFilter.value : "";
        const includeArchived = docIncludeArchivedToggle ? docIncludeArchivedToggle.checked : false;

        const res = await fetchCitizenDocuments(category || null, includeArchived);
        if (!res.ok) {
            showDocAlert(res.error || "Failed to load documents from vault.", true);
            documentsGrid.innerHTML = `
                <div class="doc-empty-state">
                    <div class="doc-empty-icon" aria-hidden="true">⚠️</div>
                    <div class="doc-empty-title">Error Loading Documents</div>
                    <p class="doc-empty-desc">${escapeHtml(res.error || "Please verify your network connection and retry.")}</p>
                    <button type="button" class="btn btn-primary" id="btnRetryLoadDocs">Retry</button>
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
            titleDiv.textContent = "No Documents Found";
            emptyDiv.appendChild(titleDiv);

            const descP = document.createElement("p");
            descP.className = "doc-empty-desc";
            descP.textContent = "Upload your identity documents, income certificates, caste certificates, or marksheets to enable one-click scholarship discovery and profile autofill.";
            emptyDiv.appendChild(descP);

            const uploadFirstBtn = document.createElement("button");
            uploadFirstBtn.type = "button";
            uploadFirstBtn.className = "btn btn-primary";
            uploadFirstBtn.textContent = "+ Upload Your First Document";
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
                statusBadge.textContent = "Archived";
            } else if (doc.confirmation_status === "CONFIRMED") {
                statusBadge.className = "doc-status-badge confirmed";
                statusBadge.textContent = "Confirmed";
            } else if (doc.confirmation_status === "REJECTED") {
                statusBadge.className = "doc-status-badge rejected";
                statusBadge.textContent = "Rejected";
            } else {
                statusBadge.className = "doc-status-badge pending";
                statusBadge.textContent = "Pending Review";
            }
            badgesRow.appendChild(statusBadge);
            card.appendChild(badgesRow);

            // Metadata row
            const meta = document.createElement("div");
            meta.className = "doc-card-meta";

            const dateRow = document.createElement("div");
            dateRow.className = "doc-meta-row";
            const dateLabel = document.createElement("span");
            dateLabel.textContent = `Uploaded: ${formatDocDate(doc.created_at)}`;
            dateRow.appendChild(dateLabel);

            const sizeLabel = document.createElement("span");
            sizeLabel.textContent = formatFileSize(doc.file_size);
            dateRow.appendChild(sizeLabel);
            meta.appendChild(dateRow);
            card.appendChild(meta);

            // Actions bar
            const actions = document.createElement("div");
            actions.className = "doc-card-actions";

            // 1. Review action
            if (doc.confirmation_status !== "CONFIRMED" && doc.status !== "ARCHIVED") {
                const btnReview = document.createElement("button");
                btnReview.type = "button";
                btnReview.className = "doc-btn-action primary";
                btnReview.textContent = "✍️ Review & Confirm";
                btnReview.addEventListener("click", () => openReviewModal(doc.document_id));
                actions.appendChild(btnReview);
            }

            // 2. Download action
            if (doc.has_original_file) {
                const btnDownload = document.createElement("button");
                btnDownload.type = "button";
                btnDownload.className = "doc-btn-action";
                btnDownload.textContent = "⬇️ Download";
                btnDownload.addEventListener("click", () => handleDownloadDocument(doc.document_id, doc.original_filename));
                actions.appendChild(btnDownload);
            }

            // 3. Replace action
            if (doc.status !== "ARCHIVED") {
                const btnReplace = document.createElement("button");
                btnReplace.type = "button";
                btnReplace.className = "doc-btn-action";
                btnReplace.textContent = "🔄 Replace";
                btnReplace.addEventListener("click", () => openReplaceModal(doc));
                actions.appendChild(btnReplace);
            }

            // 4. Details / Metadata action
            const btnDetails = document.createElement("button");
            btnDetails.type = "button";
            btnDetails.className = "doc-btn-action";
            btnDetails.textContent = "ℹ️ Details";
            btnDetails.addEventListener("click", () => openMetadataModal(doc.document_id));
            actions.appendChild(btnDetails);

            // 5. Archive action
            if (doc.status !== "ARCHIVED") {
                const btnArchive = document.createElement("button");
                btnArchive.type = "button";
                btnArchive.className = "doc-btn-action";
                btnArchive.textContent = "📦 Archive";
                btnArchive.addEventListener("click", () => handleArchiveDocument(doc.document_id));
                actions.appendChild(btnArchive);
            }

            // 6. Delete action
            const btnDelete = document.createElement("button");
            btnDelete.type = "button";
            btnDelete.className = "doc-btn-action danger";
            btnDelete.textContent = "🗑️ Delete";
            btnDelete.addEventListener("click", () => openDeleteModal(doc));
            actions.appendChild(btnDelete);

            card.appendChild(actions);
            documentsGrid.appendChild(card);
        });
    }

    // Filters event listeners
    if (docSearchInput) {
        docSearchInput.addEventListener("input", () => renderDocumentsGrid());
    }
    if (docCategoryFilter) {
        docCategoryFilter.addEventListener("change", () => loadUserDocuments());
    }
    if (docStatusFilter) {
        docStatusFilter.addEventListener("change", () => renderDocumentsGrid());
    }
    if (docIncludeArchivedToggle) {
        docIncludeArchivedToggle.addEventListener("change", () => loadUserDocuments());
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
        selectedUploadFile = null;

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

    if (btnOpenUploadModal) {
        btnOpenUploadModal.addEventListener("click", () => openUploadModal());
    }

    if (docUploadDropzone && docFileInput) {
        docUploadDropzone.addEventListener("click", (e) => {
            if (e.target !== docFileInput) {
                docFileInput.click();
            }
        });
        docUploadDropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            docUploadDropzone.classList.add("dragover");
        });
        docUploadDropzone.addEventListener("dragleave", () => {
            docUploadDropzone.classList.remove("dragover");
        });
        docUploadDropzone.addEventListener("drop", (e) => {
            e.preventDefault();
            docUploadDropzone.classList.remove("dragover");
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                handleUploadFileSelected(e.dataTransfer.files[0]);
            }
        });
        docFileInput.addEventListener("change", () => {
            if (docFileInput.files && docFileInput.files[0]) {
                handleUploadFileSelected(docFileInput.files[0]);
            }
        });
    }

    function handleUploadFileSelected(file) {
        clearModalAlert(docUploadAlert);
        const ext = file.name.split(".").pop().toLowerCase();
        const isPdf = ext === "pdf";
        const isImg = ["png", "jpg", "jpeg", "webp"].includes(ext);

        if (!isPdf && !isImg) {
            showModalAlert(docUploadAlert, "Unsupported file format. Please upload PDF, PNG, JPG, JPEG, or WEBP.", true);
            return;
        }

        if (isPdf && file.size > MAX_PDF_SIZE_BYTES) {
            showModalAlert(docUploadAlert, `PDF file exceeds maximum allowed size of 10 MB (${formatFileSize(file.size)}).`, true);
            return;
        }

        if (isImg && file.size > MAX_IMAGE_SIZE_BYTES) {
            showModalAlert(docUploadAlert, `Image file exceeds maximum allowed size of 5 MB (${formatFileSize(file.size)}).`, true);
            return;
        }

        selectedUploadFile = file;
        if (docSelectedFileName) {
            docSelectedFileName.textContent = `Selected: ${file.name} (${formatFileSize(file.size)})`;
            docSelectedFileName.style.display = "inline-block";
        }
    }

    if (btnStartUploadSubmit) {
        btnStartUploadSubmit.addEventListener("click", async () => {
            if (isUploadingDocument) return;
            if (!selectedUploadFile) {
                showModalAlert(docUploadAlert, "Please select a document file to upload.", true);
                return;
            }

            const category = docCategorySelect ? docCategorySelect.value : "";
            const docType = docTypeSelect ? docTypeSelect.value : "AUTO_DETECT";

            isUploadingDocument = true;
            btnStartUploadSubmit.disabled = true;
            if (docUploadProgress) docUploadProgress.style.display = "flex";
            clearModalAlert(docUploadAlert);

            const formData = new FormData();
            formData.append("file", selectedUploadFile);
            if (category) {
                formData.append("document_category", category);
            }
            if (docType) {
                formData.append("document_type", docType);
            }

            try {
                const res = await uploadCitizenDocument(formData);
                if (!res.ok) {
                    showModalAlert(docUploadAlert, res.error || "Document upload failed.", true);
                    return;
                }

                // Upload & OCR succeeded
                if (docUploadForm) docUploadForm.style.display = "none";
                if (docUploadFooter) docUploadFooter.style.display = "none";
                if (docUploadResultSection) docUploadResultSection.style.display = "block";

                const newDocId = (res.data && res.data.document_id) || (res.data && res.data.document && res.data.document.document_id);

                if (docUploadExtractedFields) {
                    renderIntelligentOcrPreview(docUploadExtractedFields, res.data, newDocId);
                }

                if (btnUploadGoToReview) {
                    btnUploadGoToReview.onclick = () => {
                        closeModal(documentUploadModal);
                        if (newDocId) openReviewModal(newDocId);
                    };
                }

                if (btnUploadDone) {
                    btnUploadDone.onclick = () => {
                        closeModal(documentUploadModal);
                        loadUserDocuments();
                    };
                }

                showDocAlert(`Document '${selectedUploadFile.name}' uploaded successfully to vault.`, false);
                await loadUserDocuments();

            } catch (err) {
                console.error("Upload handler error:", err);
                showModalAlert(docUploadAlert, "An unexpected upload error occurred. Please try again.", true);
            } finally {
                isUploadingDocument = false;
                if (btnStartUploadSubmit) btnStartUploadSubmit.disabled = false;
                if (docUploadProgress) docUploadProgress.style.display = "none";
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
                        showDocAlert("Document reclassified and fields extracted successfully.", false);
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
    // Review & Confirmation Modal Handling
    // ---------------------------------------------------------------------------
    async function openReviewModal(docId) {
        if (!documentReviewModal || !docId) return;
        activeReviewDocId = docId;
        clearModalAlert(docReviewAlert);
        if (docReviewLoading) docReviewLoading.style.display = "block";
        if (docReviewTableWrap) docReviewTableWrap.style.display = "none";
        if (docReviewTableBody) docReviewTableBody.innerHTML = "";
        if (btnSaveConfirmations) btnSaveConfirmations.disabled = false;

        openModal(documentReviewModal);

        try {
            const res = await fetchDocumentReview(docId);
            if (!res.ok) {
                showModalAlert(docReviewAlert, res.error || "Failed to load document review data.", true);
                if (docReviewLoading) docReviewLoading.style.display = "none";
                return;
            }

            const data = res.data || {};
            let fields = data.review_fields || [];
            if (fields.length === 0 && data.extracted_fields) {
                // Construct review_fields fallback from extracted_fields dict
                fields = Object.entries(data.extracted_fields).map(([k, v]) => ({
                    field_name: k,
                    label: k.replace(/_/g, ' ').toUpperCase(),
                    extracted_value: (v && typeof v === 'object' && v.value !== undefined) ? v.value : v,
                    is_confirmed: false,
                }));
            }

            if (docReviewLoading) docReviewLoading.style.display = "none";

            if (fields.length === 0) {
                if (docReviewTableBody) {
                    docReviewTableBody.innerHTML = `<tr><td colspan="3" style="text-align: center; padding: 20px; color: #64748b;">No extracted fields available for this document.</td></tr>`;
                }
                if (docReviewTableWrap) docReviewTableWrap.style.display = "block";
                return;
            }

            let rowsHtml = "";
            fields.forEach((f, idx) => {
                const fieldName = escapeHtml(f.field_name || "");
                const label = escapeHtml(f.label || f.field_name.replace(/_/g, ' ').toUpperCase());
                let val = f.extracted_value;
                if (val === undefined || val === null) val = "";
                if (typeof val === "object") {
                    val = JSON.stringify(val);
                }
                const valStr = escapeHtml(String(val));
                const isConfirmed = f.is_confirmed;

                rowsHtml += `
                    <tr>
                        <td style="font-weight: 600; color: #1e293b;">
                            <label for="reviewFieldVal_${idx}">${label}</label>
                            <input type="hidden" name="field_name_${idx}" value="${fieldName}">
                        </td>
                        <td>
                            <input type="text" id="reviewFieldVal_${idx}" class="doc-input" value="${valStr}" style="width: 100%; font-family: monospace;">
                        </td>
                        <td style="text-align: center;">
                            <input type="checkbox" id="reviewConfirmCheck_${idx}" ${isConfirmed ? "checked" : "checked"} style="transform: scale(1.2); cursor: pointer;">
                        </td>
                    </tr>
                `;
            });

            if (docReviewTableBody) docReviewTableBody.innerHTML = rowsHtml;
            if (docReviewTableWrap) docReviewTableWrap.style.display = "block";

        } catch (err) {
            console.error("Review load error:", err);
            showModalAlert(docReviewAlert, "Failed to load review data. Please try again.", true);
            if (docReviewLoading) docReviewLoading.style.display = "none";
        }
    }

    if (btnSaveConfirmations) {
        btnSaveConfirmations.addEventListener("click", async () => {
            if (isSavingConfirmations || !activeReviewDocId) return;

            const rows = docReviewTableBody ? docReviewTableBody.querySelectorAll("tr") : [];
            const confirmations = [];

            rows.forEach((row, idx) => {
                const nameInput = row.querySelector(`input[name="field_name_${idx}"]`);
                const valInput = row.querySelector(`#reviewFieldVal_${idx}`);
                const checkInput = row.querySelector(`#reviewConfirmCheck_${idx}`);

                if (nameInput && valInput && checkInput && checkInput.checked) {
                    confirmations.push({
                        field_name: nameInput.value,
                        confirmed_value: valInput.value.trim(),
                        confirm: true
                    });
                }
            });

            if (confirmations.length === 0) {
                showModalAlert(docReviewAlert, "Please select at least one field to confirm.", true);
                return;
            }

            isSavingConfirmations = true;
            btnSaveConfirmations.disabled = true;
            clearModalAlert(docReviewAlert);

            try {
                const res = await confirmDocumentFields(activeReviewDocId, { confirmations });
                if (!res.ok) {
                    showModalAlert(docReviewAlert, res.error || "Confirmation failed.", true);
                    return;
                }

                showDocAlert("Document fields confirmed and linked to your profile.", false);
                closeModal(documentReviewModal);
                await loadUserDocuments();

            } catch (err) {
                console.error("Confirmation error:", err);
                showModalAlert(docReviewAlert, "Error saving field confirmations.", true);
            } finally {
                isSavingConfirmations = false;
                if (btnSaveConfirmations) btnSaveConfirmations.disabled = false;
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Replace Modal Handling
    // ---------------------------------------------------------------------------
    function openReplaceModal(doc) {
        if (!documentReplaceModal || !doc) return;
        activeReplaceDoc = doc;
        selectedReplaceFile = null;
        clearModalAlert(docReplaceAlert);
        if (docReplaceForm) docReplaceForm.reset();
        if (docReplaceProgress) docReplaceProgress.style.display = "none";
        if (docReplaceSelectedFileName) {
            docReplaceSelectedFileName.style.display = "none";
            docReplaceSelectedFileName.textContent = "";
        }
        if (docReplaceTargetInfo) {
            docReplaceTargetInfo.innerHTML = `<strong>Replacing:</strong> ${escapeHtml(doc.original_filename)} (${getCategoryLabel(doc.document_category)})`;
        }
        if (btnConfirmReplaceSubmit) btnConfirmReplaceSubmit.disabled = false;

        openModal(documentReplaceModal);
    }

    if (docReplaceDropzone && docReplaceFileInput) {
        docReplaceDropzone.addEventListener("click", () => docReplaceFileInput.click());
        docReplaceDropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            docReplaceDropzone.classList.add("dragover");
        });
        docReplaceDropzone.addEventListener("dragleave", () => {
            docReplaceDropzone.classList.remove("dragover");
        });
        docReplaceDropzone.addEventListener("drop", (e) => {
            e.preventDefault();
            docReplaceDropzone.classList.remove("dragover");
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                handleReplaceFileSelected(e.dataTransfer.files[0]);
            }
        });
        docReplaceFileInput.addEventListener("change", () => {
            if (docReplaceFileInput.files && docReplaceFileInput.files[0]) {
                handleReplaceFileSelected(docReplaceFileInput.files[0]);
            }
        });
    }

    function handleReplaceFileSelected(file) {
        clearModalAlert(docReplaceAlert);
        const ext = file.name.split(".").pop().toLowerCase();
        const isPdf = ext === "pdf";
        const isImg = ["png", "jpg", "jpeg", "webp"].includes(ext);

        if (!isPdf && !isImg) {
            showModalAlert(docReplaceAlert, "Unsupported file format. Please upload PDF, PNG, JPG, JPEG, or WEBP.", true);
            return;
        }

        if (isPdf && file.size > MAX_PDF_SIZE_BYTES) {
            showModalAlert(docReplaceAlert, `PDF file exceeds maximum allowed size of 10 MB.`, true);
            return;
        }

        if (isImg && file.size > MAX_IMAGE_SIZE_BYTES) {
            showModalAlert(docReplaceAlert, `Image file exceeds maximum allowed size of 5 MB.`, true);
            return;
        }

        selectedReplaceFile = file;
        if (docReplaceSelectedFileName) {
            docReplaceSelectedFileName.textContent = `Selected replacement: ${file.name} (${formatFileSize(file.size)})`;
            docReplaceSelectedFileName.style.display = "inline-block";
        }
    }

    if (btnConfirmReplaceSubmit) {
        btnConfirmReplaceSubmit.addEventListener("click", async () => {
            if (isReplacingDocument || !activeReplaceDoc) return;
            if (!selectedReplaceFile) {
                showModalAlert(docReplaceAlert, "Please select a replacement file to upload.", true);
                return;
            }

            isReplacingDocument = true;
            btnConfirmReplaceSubmit.disabled = true;
            if (docReplaceProgress) docReplaceProgress.style.display = "flex";
            clearModalAlert(docReplaceAlert);

            const formData = new FormData();
            formData.append("file", selectedReplaceFile);

            try {
                const res = await replaceCitizenDocument(activeReplaceDoc.document_id, formData);
                if (!res.ok) {
                    showModalAlert(docReplaceAlert, res.error || "Replacement failed.", true);
                    return;
                }

                showDocAlert(`Document replaced with '${selectedReplaceFile.name}'. OCR re-extraction completed.`, false);
                closeModal(documentReplaceModal);
                await loadUserDocuments();

            } catch (err) {
                console.error("Replace handler error:", err);
                showModalAlert(docReplaceAlert, "An unexpected error occurred during replacement.", true);
            } finally {
                isReplacingDocument = false;
                if (btnConfirmReplaceSubmit) btnConfirmReplaceSubmit.disabled = false;
                if (docReplaceProgress) docReplaceProgress.style.display = "none";
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Delete & Archive Modal Handling
    // ---------------------------------------------------------------------------
    function openDeleteModal(doc) {
        if (!documentDeleteModal || !doc) return;
        activeDeleteDoc = doc;
        clearModalAlert(docDeleteAlert);
        if (docDeleteTargetInfo) {
            docDeleteTargetInfo.innerHTML = `<strong>Document:</strong> ${escapeHtml(doc.original_filename)} (${getCategoryLabel(doc.document_category)})`;
        }
        openModal(documentDeleteModal);
    }

    async function handleArchiveDocument(docId) {
        if (!confirm("Are you sure you want to archive this document? It will be hidden from default views but preserved.")) return;
        try {
            const res = await deleteCitizenDocument(docId, false);
            if (!res.ok) {
                showDocAlert(res.error || "Failed to archive document.", true);
                return;
            }
            showDocAlert("Document archived successfully.", false);
            await loadUserDocuments();
        } catch (err) {
            console.error("Archive error:", err);
            showDocAlert("Failed to archive document.", true);
        }
    }

    if (btnArchiveFromDeleteModal) {
        btnArchiveFromDeleteModal.addEventListener("click", async () => {
            if (!activeDeleteDoc) return;
            try {
                const res = await deleteCitizenDocument(activeDeleteDoc.document_id, false);
                if (!res.ok) {
                    showModalAlert(docDeleteAlert, res.error || "Archive failed.", true);
                    return;
                }
                showDocAlert("Document archived successfully.", false);
                closeModal(documentDeleteModal);
                await loadUserDocuments();
            } catch (err) {
                showModalAlert(docDeleteAlert, "Failed to archive document.", true);
            }
        });
    }

    if (btnPermanentDeleteFromModal) {
        btnPermanentDeleteFromModal.addEventListener("click", async () => {
            if (!activeDeleteDoc) return;
            try {
                const res = await deleteCitizenDocument(activeDeleteDoc.document_id, true);
                if (!res.ok) {
                    showModalAlert(docDeleteAlert, res.error || "Deletion failed.", true);
                    return;
                }
                showDocAlert("Document permanently deleted from vault.", false);
                closeModal(documentDeleteModal);
                await loadUserDocuments();
            } catch (err) {
                showModalAlert(docDeleteAlert, "Failed to delete document.", true);
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Download Handling
    // ---------------------------------------------------------------------------
    async function handleDownloadDocument(docId, filename) {
        if (!docId) return;
        try {
            const res = await downloadCitizenDocument(docId, filename);
            if (!res.ok) {
                showDocAlert(res.error || "Failed to download document.", true);
            }
        } catch (err) {
            console.error("Download error:", err);
            showDocAlert("Download failed. Please check network connection.", true);
        }
    }

    // ---------------------------------------------------------------------------
    // Metadata Modal Handling
    // ---------------------------------------------------------------------------
    async function openMetadataModal(docId) {
        if (!documentMetadataModal || !docId) return;
        activeMetadataDocId = docId;
        if (docMetadataFieldsList) docMetadataFieldsList.innerHTML = `<span class="chat-spinner"></span> Loading metadata...`;
        if (docMetadataExtractedTableWrap) docMetadataExtractedTableWrap.innerHTML = "";
        openModal(documentMetadataModal);

        try {
            const res = await fetchDocumentMetadata(docId);
            if (!res.ok) {
                if (docMetadataFieldsList) docMetadataFieldsList.innerHTML = `<p style="color: #dc2626;">Failed to load metadata.</p>`;
                return;
            }

            const doc = (res.data && res.data.document) || {};
            const extracted = (res.data && (res.data.extracted_fields || (res.data.document && res.data.document.extracted_fields))) || {};

            if (docMetadataFieldsList) {
                docMetadataFieldsList.innerHTML = `
                    <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; font-size: 13px;">
                        <div><strong>Filename:</strong> <span style="font-family: monospace;">${escapeHtml(doc.original_filename)}</span></div>
                        <div><strong>Category:</strong> ${getCategoryLabel(doc.document_category)}</div>
                        <div><strong>Type:</strong> ${getTypeLabel(doc.document_type)}</div>
                        <div><strong>Status:</strong> ${escapeHtml(doc.status)}</div>
                        <div><strong>Confirmation:</strong> ${escapeHtml(doc.confirmation_status)}</div>
                        <div><strong>Size:</strong> ${formatFileSize(doc.file_size)}</div>
                        <div><strong>Encrypted Storage:</strong> <span style="color: #15803d; font-weight: 600;">Active (Encrypted Vault)</span></div>
                        <div><strong>Uploaded:</strong> ${formatDocDate(doc.created_at)}</div>
                    </div>
                `;
            }

            if (docMetadataExtractedTableWrap) {
                const isConfirmedDoc = (doc.confirmation_status === "CONFIRMED" || doc.status === "CONFIRMED");
                const sectionH4 = docMetadataExtractedTableWrap.parentElement ? docMetadataExtractedTableWrap.parentElement.querySelector("h4") : null;
                if (sectionH4) {
                    sectionH4.textContent = isConfirmedDoc ? "Confirmed Document Fields & Metadata (Masked):" : "Extracted Fields (Masked):";
                }

                const keys = Object.keys(extracted);
                if (keys.length === 0) {
                    docMetadataExtractedTableWrap.innerHTML = "<p style='color: #64748b; font-size: 13px;'>No extracted fields recorded.</p>";
                } else {
                    const fieldLabels = {
                        "student_name": "Student Name",
                        "father_name": "Father's Name",
                        "mother_name": "Mother's Name",
                        "roll_number": "Roll No / Hall Ticket No",
                        "board_name": "Board / Council Name",
                        "state": "State",
                        "school_name": (doc.document_type === "MARKSHEET_12TH" ? "Junior College / School" : "School / College Name"),
                        "examination_year": "Examination Year",
                        "total_obtained_marks": "Total Obtained Marks",
                        "maximum_total_marks": "Maximum Total Marks",
                        "percentage": "Aggregate Percentage (%)",
                        "grade": "Overall Grade / Division",
                        "result_status": "Result Status",
                        "name": "Full Name",
                        "date_of_birth": "Date of Birth",
                        "gender": "Gender",
                        "aadhaar_number": "Aadhaar Number",
                        "pan_number": "PAN Number",
                        "annual_income": "Annual Family Income",
                        "annual_family_income": "Annual Family Income",
                        "certificate_number": "Certificate Number",
                        "caste_category": "Caste / Category",
                        "sub_caste": "Sub-Caste / Community",
                        "account_number": "Account Number",
                        "ifsc_code": "IFSC Code",
                        "bank_name": "Bank Name",
                        "branch": "Branch Name",
                        "account_holder_name": "Account Holder Name",
                        "institution_name": "Institution Name",
                        "amount_paid": "Amount Paid",
                        "receipt_number": "Receipt Number",
                    };

                    let html = `<table style="width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 8px;">
                        <thead>
                            <tr style="background: #f8fafc; border-bottom: 1px solid #e2e8f0; text-align: left;">
                                <th style="padding: 7px 10px; font-weight: 700; color: #475569;">Field Name</th>
                                <th style="padding: 7px 10px; font-weight: 700; color: #475569;">${isConfirmedDoc ? "Confirmed Value" : "Extracted Value"}</th>
                                <th style="padding: 7px 10px; font-weight: 700; color: #475569; width: 140px;">Status</th>
                            </tr>
                        </thead>
                        <tbody>`;
                    keys.forEach(k => {
                        const item = extracted[k];
                        let val = (item && typeof item === "object" && item.value !== undefined) ? item.value : item;
                        if (val === undefined || val === null || val === "") val = "--";
                        if (typeof val === "object") {
                            try { val = JSON.stringify(val); } catch { val = String(val); }
                        }
                        const isConfirmedField = Boolean(
                            (item && typeof item === "object" && item.is_confirmed) ||
                            (res.data && res.data.confirmed_fields && res.data.confirmed_fields[k]) ||
                            isConfirmedDoc
                        );
                        const isCorrected = Boolean(
                            (item && typeof item === "object" && item.is_corrected) ||
                            (res.data && res.data.confirmed_fields && res.data.confirmed_fields[k] && res.data.confirmed_fields[k].is_corrected)
                        );

                        let badgeHtml = "";
                        if (isCorrected) {
                            badgeHtml = `<span style="display: inline-block; background: #ecfdf5; color: #047857; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; border: 1px solid #a7f3d0;">✓ User Corrected</span>`;
                        } else if (isConfirmedField) {
                            badgeHtml = `<span style="display: inline-block; background: #ecfdf5; color: #047857; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; border: 1px solid #a7f3d0;">✓ Confirmed</span>`;
                        } else {
                            badgeHtml = `<span style="display: inline-block; background: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; border: 1px solid #fde68a;">Pending Review</span>`;
                        }

                        const label = fieldLabels[k] || k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                        const isMono = k.includes("number") || k.includes("ifsc") || k.includes("marks") || k.includes("year") || k.includes("percentage");
                        html += `<tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 7px 10px; font-weight: 600; color: #1e293b; width: 35%;">${escapeHtml(label)}</td>
                            <td style="padding: 7px 10px; color: #0f172a; ${isMono ? 'font-family: monospace; font-weight: 600;' : ''}">${escapeHtml(String(val))}</td>
                            <td style="padding: 7px 10px;">${badgeHtml}</td>
                        </tr>`;
                    });
                    html += "</tbody></table>";
                    docMetadataExtractedTableWrap.innerHTML = html;
                }
            }

            if (btnMetadataDownloadBtn) {
                btnMetadataDownloadBtn.onclick = () => handleDownloadDocument(doc.document_id, doc.original_filename);
            }

            if (btnMetadataReviewBtn) {
                if (doc.confirmation_status !== "CONFIRMED" && doc.status !== "ARCHIVED") {
                    btnMetadataReviewBtn.style.display = "inline-block";
                    btnMetadataReviewBtn.onclick = () => {
                        closeModal(documentMetadataModal);
                        openReviewModal(doc.document_id);
                    };
                } else {
                    btnMetadataReviewBtn.style.display = "none";
                }
            }

        } catch (err) {
            console.error("Metadata load error:", err);
            if (docMetadataFieldsList) docMetadataFieldsList.innerHTML = `<p style="color: #dc2626;">Failed to load metadata.</p>`;
        }
    }
});

