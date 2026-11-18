/**
 * SahayAI - Dedicated Citizen Profile Page Controller
 * Fetches and displays registered citizen demographics and confirmed document field audits.
 */

document.addEventListener("DOMContentLoaded", async function () {
    "use strict";

    const alertBox = document.getElementById("alertBox");
    const guestNoticeBanner = document.getElementById("guestNoticeBanner");
    const profileCardSection = document.getElementById("profileCardSection");
    const confirmedFieldsSection = document.getElementById("confirmedFieldsSection");
    const confirmedFieldsContainer = document.getElementById("confirmedFieldsContainer");
    const confirmedFieldsCountBadge = document.getElementById("confirmedFieldsCountBadge");

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

    const navCitizenName = document.getElementById("navCitizenName");
    const logoutBtn = document.getElementById("logoutBtn");
    const navLoginLink = document.getElementById("navLoginLink");
    const navSignupLink = document.getElementById("navSignupLink");
    const navGuestBadge = document.getElementById("navGuestBadge");
    const endGuestSessionBtn = document.getElementById("endGuestSessionBtn");
    const profileMenuContainer = document.getElementById("profileMenuContainer");
    const dropdownCitizenName = document.getElementById("dropdownCitizenName");
    const dropdownCitizenId = document.getElementById("dropdownCitizenId");

    function showAlert(msg, isError) {
        if (!alertBox) return;
        alertBox.textContent = msg;
        alertBox.className = isError ? "alert-box alert-error" : "alert-box alert-success";
        alertBox.style.display = "block";
    }

    function clearAlert() {
        if (!alertBox) return;
        alertBox.textContent = "";
        alertBox.style.display = "none";
    }

    function formatCurrency(amount) {
        if (amount === null || amount === undefined || isNaN(amount)) return "--";
        try {
            return new Intl.NumberFormat("en-IN", {
                style: "currency",
                currency: "INR",
                maximumFractionDigits: 0
            }).format(amount);
        } catch {
            return "₹" + Number(amount).toLocaleString("en-IN");
        }
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

    // 1. Initialize Profile Dropdown Menu
    if (window.SahayNav && typeof SahayNav.initProfileDropdown === "function") {
        SahayNav.initProfileDropdown();
    }

    // 2. Wire Standalone Logout Button
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

    // 3. Check Session and Mode
    try {
        const sessionRes = await apiFetch("/auth/session-status");
        if (!sessionRes.ok || !sessionRes.data || !sessionRes.data.authenticated) {
            window.location.href = "login.html";
            return;
        }

        const session = sessionRes.data;
        if (session.is_guest) {
            // Guest mode: Hide registered profile sections, show notice banner
            if (guestNoticeBanner) guestNoticeBanner.style.display = "block";
            if (profileCardSection) profileCardSection.style.display = "none";
            if (confirmedFieldsSection) confirmedFieldsSection.style.display = "none";
            if (profileMenuContainer) profileMenuContainer.style.display = "none";
            if (navLoginLink) navLoginLink.style.display = "inline-block";
            if (navSignupLink) navSignupLink.style.display = "inline-block";
            if (navGuestBadge) navGuestBadge.style.display = "inline-block";
            if (endGuestSessionBtn) endGuestSessionBtn.style.display = "inline-block";
            return;
        }

        // Registered Citizen Mode
        if (profileMenuContainer) profileMenuContainer.style.display = "inline-flex";
        if (navLoginLink) navLoginLink.style.display = "none";
        if (navSignupLink) navSignupLink.style.display = "none";
        if (navGuestBadge) navGuestBadge.style.display = "none";
        if (endGuestSessionBtn) endGuestSessionBtn.style.display = "none";
        if (guestNoticeBanner) guestNoticeBanner.style.display = "none";
        if (profileCardSection) profileCardSection.style.display = "block";
        if (confirmedFieldsSection) confirmedFieldsSection.style.display = "block";

        // 4. Fetch Citizen Profile (/profile/me)
        const profRes = await apiFetch("/profile/me");
        if (!profRes.ok || !profRes.data || !profRes.data.profile) {
            if (profRes.status === 404) {
                // Profile not yet created -> onboarding
                window.location.href = "profile.html";
                return;
            }
            showAlert("Failed to load profile details. Please refresh or try again later.", true);
            return;
        }

        const profile = profRes.data.profile;

        // Populate demographic fields
        if (dispFullName) dispFullName.textContent = profile.full_name || "--";
        if (dispUserId) dispUserId.textContent = profile.user_id || "--";

        const ageText = (profile.age !== null && profile.age !== undefined) ? `${profile.age} years` : "--";
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

        // Populate header identity and dropdown
        if (navCitizenName) navCitizenName.textContent = profile.full_name || "Citizen";
        if (dropdownCitizenName) dropdownCitizenName.textContent = profile.full_name || "Citizen";
        if (dropdownCitizenId && profile.user_id) {
            dropdownCitizenId.textContent = "ID: " + profile.user_id;
            dropdownCitizenId.style.display = "block";
        }

        // 5. Fetch Confirmed Document Records (/profile/confirmed-document-fields)
        await loadConfirmedFields();

    } catch (err) {
        console.error("Profile page load error:", err);
        showAlert("Network or server connection error. Please refresh.", true);
    }

    async function loadConfirmedFields() {
        if (!confirmedFieldsContainer) return;

        try {
            const res = await apiFetch("/profile/confirmed-document-fields?active_only=true");
            if (!res.ok) {
                confirmedFieldsContainer.innerHTML = `
                    <div style="text-align: center; padding: 20px; color: #64748b; font-size: 13px;">
                        Unable to load confirmed document fields at this time.
                    </div>
                `;
                return;
            }

            const items = (res.data && res.data.confirmed_fields) || [];
            if (confirmedFieldsCountBadge) {
                confirmedFieldsCountBadge.textContent = `${items.length} Field${items.length === 1 ? "" : "s"} Confirmed`;
            }

            if (items.length === 0) {
                confirmedFieldsContainer.innerHTML = `
                    <div style="text-align: center; padding: 32px 20px; color: #64748b;">
                        <div style="font-size: 32px; margin-bottom: 8px;">📑</div>
                        <p style="font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 4px;">No Verified Document Records Yet</p>
                        <p style="font-size: 12.5px; margin: 0 0 16px 0;">Upload your identity, income, or caste documents in the Document Hub to extract and confirm verified profile records.</p>
                        <a href="my-documents.html" class="btn btn-secondary" style="font-size: 12.5px; text-decoration: none; padding: 6px 14px;">
                            Go to My Documents
                        </a>
                    </div>
                `;
                return;
            }

            let html = `
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                        <thead>
                            <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0; color: #475569;">
                                <th style="padding: 10px 14px; font-weight: 600;">Attribute</th>
                                <th style="padding: 10px 14px; font-weight: 600;">Confirmed Value</th>
                                <th style="padding: 10px 14px; font-weight: 600;">Status</th>
                                <th style="padding: 10px 14px; font-weight: 600;">Confirmed At</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            items.forEach(item => {
                const fieldName = escapeHtml(item.field_name || "--").replace(/_/g, " ").toUpperCase();
                const confirmedVal = escapeHtml(item.confirmed_value || "--");
                const confirmedDate = item.confirmed_at ? new Date(item.confirmed_at).toLocaleDateString() : "--";
                const isCorrected = item.is_corrected;

                html += `
                    <tr style="border-bottom: 1px solid #f1f5f9;">
                        <td style="padding: 12px 14px; font-weight: 600; color: #1e293b;">${fieldName}</td>
                        <td style="padding: 12px 14px; color: #0f172a; font-family: monospace;">${confirmedVal}</td>
                        <td style="padding: 12px 14px;">
                            <span class="badge" style="background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; font-size: 11px; padding: 2px 8px; border-radius: 4px;">
                                Verified by Citizen ${isCorrected ? "(User Edited)" : "(OCR Match)"}
                            </span>
                        </td>
                        <td style="padding: 12px 14px; color: #64748b; font-size: 12px;">${confirmedDate}</td>
                    </tr>
                `;
            });

            html += `
                        </tbody>
                    </table>
                </div>
            `;

            confirmedFieldsContainer.innerHTML = html;

        } catch (err) {
            console.error("Confirmed fields load error:", err);
            confirmedFieldsContainer.innerHTML = `
                <div style="text-align: center; padding: 20px; color: #64748b; font-size: 13px;">
                    Failed to fetch verified records.
                </div>
            `;
        }
    }
});

