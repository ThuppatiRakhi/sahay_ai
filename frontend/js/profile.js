/**
 * SahayAI - Citizen Profile Setup Controller
 *
 * Checks authentication, acquires CSRF token, validates demographic inputs,
 * and submits the profile via POST /profile/me.
 */

document.addEventListener("DOMContentLoaded", async () => {
    const profileForm = document.getElementById("profileForm");
    const fullNameInput = document.getElementById("fullName");
    const dobInput = document.getElementById("dob");
    const genderSelect = document.getElementById("gender");
    const casteSelect = document.getElementById("casteCategory");
    const stateInput = document.getElementById("state");
    const districtInput = document.getElementById("district");
    const incomeInput = document.getElementById("annualIncome");
    const occupationInput = document.getElementById("occupation");
    const isBplCheckbox = document.getElementById("isBpl");
    const submitBtn = document.getElementById("submitBtn");
    const alertBox = document.getElementById("alertBox");

    function showAlert(message, type = "error") {
        alertBox.className = `alert-box visible ${type}`;
        alertBox.textContent = message;
    }

    function hideAlert() {
        alertBox.className = "alert-box";
        alertBox.textContent = "";
    }

    // Set maximum selectable date of birth to today
    const todayIso = new Date().toISOString().split("T")[0];
    dobInput.max = todayIso;

    // Check existing authentication & profile status
    try {
        const statusRes = await apiFetch("/auth/session-status");
        if (statusRes.ok && statusRes.data) {
            if (statusRes.data.is_guest) {
                // Guests do not have persistent database profiles; keep them on dashboard
                window.location.href = "dashboard.html";
                return;
            }
            if (!statusRes.data.authenticated) {
                window.location.href = "login.html";
                return;
            }
        }

        const checkRes = await apiFetch("/profile/me");
        if (checkRes.ok && checkRes.data && checkRes.data.profile) {
            // Citizen already completed profile setup
            window.location.href = "dashboard.html";
            return;
        }

        if (checkRes.status === 401) {
            // Not authenticated, redirect to login
            window.location.href = "login.html";
            return;
        }

        // Pre-fetch CSRF token for the active session
        await getCsrfToken();
    } catch (err) {
        console.warn("Session check error on profile setup:", err);
    }

    const t = (k, p, d) => (typeof I18n !== 'undefined' ? I18n.t(k, p, d) : d);

    profileForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideAlert();

        const fullName = fullNameInput.value.trim();
        const dob = dobInput.value.trim();
        const gender = genderSelect.value;
        const casteCategory = casteSelect.value;
        const state = stateInput.value.trim();
        const district = districtInput.value.trim();
        const annualIncomeStr = incomeInput.value.trim();
        const occupation = occupationInput.value.trim();
        const isBpl = isBplCheckbox.checked;

        // Client-side validations
        if (!fullName || fullName.length < 2) {
            showAlert(t("profile.errorFullName", {}, "Please enter your full legal name (at least 2 characters)."));
            fullNameInput.focus();
            return;
        }

        if (!dob) {
            showAlert(t("profile.errorDob", {}, "Please select your date of birth."));
            dobInput.focus();
            return;
        }

        const dobDate = new Date(dob);
        const now = new Date();
        if (dobDate > now) {
            showAlert(t("profile.errorFutureDob", {}, "Date of birth cannot be in the future."));
            dobInput.focus();
            return;
        }

        if (!gender) {
            showAlert(t("profile.errorGender", {}, "Please select your gender."));
            genderSelect.focus();
            return;
        }

        if (!casteCategory) {
            showAlert(t("profile.errorCaste", {}, "Please select your caste category."));
            casteSelect.focus();
            return;
        }

        if (!state || state.length < 2) {
            showAlert(t("profile.errorState", {}, "Please enter your state of residence."));
            stateInput.focus();
            return;
        }

        if (!district || district.length < 2) {
            showAlert(t("profile.errorDistrict", {}, "Please enter your district."));
            districtInput.focus();
            return;
        }

        if (!annualIncomeStr) {
            showAlert(t("profile.errorIncome", {}, "Please enter your annual family income."));
            incomeInput.focus();
            return;
        }

        const annualIncome = parseFloat(annualIncomeStr);
        if (isNaN(annualIncome) || annualIncome < 0) {
            showAlert(t("profile.errorIncome", {}, "Annual family income must be a valid non-negative number."));
            incomeInput.focus();
            return;
        }

        if (!occupation || occupation.length < 2) {
            showAlert(t("profile.errorOccupation", {}, "Please enter your primary occupation."));
            occupationInput.focus();
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = t("profile.submitting", {}, "Saving Profile...");

        try {
            const profilePayload = {
                full_name: fullName,
                date_of_birth: dob,
                gender: gender,
                state: state,
                district: district,
                annual_income: annualIncome,
                occupation: occupation,
                caste_category: casteCategory,
                is_bpl: isBpl,
            };

            const result = await apiFetch("/profile/me", {
                method: "POST",
                body: JSON.stringify(profilePayload),
            });

            if (!result.ok) {
                if (result.status === 409) {
                    showAlert("A profile already exists for your account. Redirecting to dashboard...", "info");
                    setTimeout(() => { window.location.href = "dashboard.html"; }, 1000);
                    return;
                }

                if (result.status === 401) {
                    showAlert("Your session has expired. Please log in again.");
                    setTimeout(() => { window.location.href = "login.html"; }, 1200);
                    return;
                }

                showAlert(result.error || t("profile.profileFailed", {}, "Failed to save profile. Please check the fields and try again."));
                submitBtn.disabled = false;
                submitBtn.textContent = t("profile.submitBtn", {}, "Save Profile & Continue to Dashboard");
                return;
            }

            showAlert(t("profile.profileSuccess", {}, "Profile saved successfully! Redirecting to your dashboard..."), "success");

            setTimeout(() => {
                window.location.href = "dashboard.html";
            }, 800);

        } catch (err) {
            console.error("Profile submission error:", err);
            showAlert("An unexpected error occurred while saving profile. Please try again.");
            submitBtn.disabled = false;
            submitBtn.textContent = t("profile.submitBtn", {}, "Save Profile & Continue to Dashboard");
        }
    });
});

