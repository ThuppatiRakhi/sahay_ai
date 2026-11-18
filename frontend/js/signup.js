/**
 * SahayAI - Signup Form Controller
 *
 * Handles citizen registration, validation, password visibility toggles,
 * error handling, and redirection to profile creation upon success.
 */

document.addEventListener("DOMContentLoaded", () => {
    const signupForm = document.getElementById("signupForm");
    const emailInput = document.getElementById("email");
    const phoneInput = document.getElementById("phone");
    const passwordInput = document.getElementById("password");
    const confirmPasswordInput = document.getElementById("confirmPassword");
    const submitBtn = document.getElementById("submitBtn");
    const alertBox = document.getElementById("alertBox");
    const navGuestBtn = document.getElementById("navGuestBtn");

    if (navGuestBtn) {
        navGuestBtn.addEventListener("click", async () => {
            navGuestBtn.disabled = true;
            navGuestBtn.textContent = "Starting Guest Session...";
            try {
                const res = await apiFetch("/auth/guest", { method: "POST" });
                if (res.ok && res.data && res.data.success) {
                    localStorage.removeItem("sahay_user_name");
                    localStorage.removeItem("sahay_profile_status");
                    localStorage.removeItem("sahay_applied_count");
                    localStorage.removeItem("sahay_eligible_count");
                    await getCsrfToken();
                    window.location.href = "dashboard.html";
                } else {
                    showAlert(res.error || "Failed to initialize guest session. Please try again.");
                    navGuestBtn.disabled = false;
                    navGuestBtn.textContent = "Continue as Guest";
                }
            } catch (err) {
                console.error("Guest session error:", err);
                showAlert("Failed to initialize guest session. Please try again.");
                navGuestBtn.disabled = false;
                navGuestBtn.textContent = "Continue as Guest";
            }
        });
    }

    const t = (k, p, d) => (typeof I18n !== 'undefined' ? I18n.t(k, p, d) : d);

    // Show/Hide password toggle handlers
    document.querySelectorAll(".toggle-password-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-target");
            const input = document.getElementById(targetId);
            if (!input) return;

            if (input.type === "password") {
                input.type = "text";
                btn.textContent = t("login.hidePassword", {}, "Hide");
            } else {
                input.type = "password";
                btn.textContent = t("login.showPassword", {}, "Show");
            }
        });
    });

    function showAlert(message, type = "error") {
        alertBox.className = `alert-box visible ${type}`;
        alertBox.textContent = message;
    }

    function hideAlert() {
        alertBox.className = "alert-box";
        alertBox.textContent = "";
    }

    signupForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideAlert();

        const email = emailInput.value.trim();
        const phone = phoneInput.value.trim();
        const password = passwordInput.value;
        const confirmPassword = confirmPasswordInput.value;

        // Client-side validations
        if (!email && !phone) {
            showAlert(t("signup.errorEmptyContact", {}, "Please provide either an email address or mobile phone number."));
            emailInput.focus();
            return;
        }

        if (email) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(email)) {
                showAlert(t("signup.errorInvalidEmail", {}, "Please enter a valid email address (e.g. name@example.com)."));
                emailInput.focus();
                return;
            }
        }

        if (phone) {
            const cleanPhone = phone.replace(/[\s-]/g, "");
            const phoneRegex = /^\+?[1-9]\d{6,14}$/;
            if (!phoneRegex.test(cleanPhone)) {
                showAlert(t("signup.errorInvalidPhone", {}, "Please enter a valid phone number (e.g. 9876543210)."));
                phoneInput.focus();
                return;
            }
        }

        if (!password || password.length < 8) {
            showAlert(t("signup.errorPasswordLength", {}, "Password must be at least 8 characters in length."));
            passwordInput.focus();
            return;
        }

        if (password !== confirmPassword) {
            showAlert(t("signup.errorPasswordMismatch", {}, "Passwords do not match. Please re-enter to confirm."));
            confirmPasswordInput.focus();
            return;
        }

        // Disable button during processing
        submitBtn.disabled = true;
        submitBtn.textContent = t("signup.submitting", {}, "Creating Account...");

        try {
            const result = await apiFetch("/auth/signup", {
                method: "POST",
                body: JSON.stringify({
                    email: email || null,
                    phone: phone || null,
                    password: password,
                }),
            });

            if (!result.ok) {
                showAlert(result.error || t("signup.signupFailed", {}, "Registration failed. Please check your details and try again."));
                submitBtn.disabled = false;
                submitBtn.textContent = t("signup.submitBtn", {}, "Create Account & Continue");
                return;
            }

            showAlert(t("signup.signupSuccess", {}, "Account created successfully! Loading profile setup..."), "success");

            // Obtain CSRF token for the newly established session
            await getCsrfToken();

            // Next step from backend contract is CREATE_PROFILE
            setTimeout(() => {
                window.location.href = "profile.html";
            }, 800);

        } catch (err) {
            console.error("Signup submission failure:", err);
            showAlert(t("signup.unexpectedError", {}, "An unexpected network or server error occurred. Please try again."));
            submitBtn.disabled = false;
            submitBtn.textContent = t("signup.submitBtn", {}, "Create Account & Continue");
        }
    });
});
