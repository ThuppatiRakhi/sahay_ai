/**
 * SahayAI - Login Form Controller
 *
 * Authenticates citizen credentials via POST /auth/login, acquires CSRF token,
 * handles loading/error states, and redirects to dashboard or profile creation.
 */

document.addEventListener("DOMContentLoaded", () => {
    const loginForm = document.getElementById("loginForm");
    const identifierInput = document.getElementById("identifier");
    const passwordInput = document.getElementById("password");
    const submitBtn = document.getElementById("submitBtn");
    const alertBox = document.getElementById("alertBox");
    const cardGuestBtn = document.getElementById("cardGuestBtn");
    const navGuestBtn = document.getElementById("navGuestBtn");

    async function handleGuestContinue(btn) {
        hideAlert();
        if (btn) {
            btn.disabled = true;
            btn.textContent = t("login.guestStarting", {}, "Starting Guest Session...");
        }

        try {
            const res = await apiFetch("/auth/guest", { method: "POST" });
            if (res.ok && res.data && res.data.success) {
                showAlert(t("login.guestSuccess", {}, "Guest session started! Loading dashboard..."), "success");
                // Clear any leftover local storage from prior session
                localStorage.removeItem("sahay_user_name");
                localStorage.removeItem("sahay_profile_status");
                localStorage.removeItem("sahay_applied_count");
                localStorage.removeItem("sahay_eligible_count");

                await getCsrfToken();

                setTimeout(() => {
                    window.location.href = "dashboard.html";
                }, 400);
            } else {
                showAlert(res.error || t("login.guestFailed", {}, "Failed to initialize guest session. Please try again."));
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = t("login.guestBtn", {}, "Continue as Guest →");
                }
            }
        } catch (err) {
            console.error("Guest initialization error:", err);
            showAlert(t("login.guestFailed", {}, "Failed to initialize guest session. Please try again."));
            if (btn) {
                btn.disabled = false;
                btn.textContent = t("login.guestBtn", {}, "Continue as Guest →");
            }
        }
    }

    if (cardGuestBtn) {
        cardGuestBtn.addEventListener("click", () => handleGuestContinue(cardGuestBtn));
    }
    if (navGuestBtn) {
        navGuestBtn.addEventListener("click", () => handleGuestContinue(navGuestBtn));
    }

    // Toggle password visibility
    document.querySelectorAll(".toggle-password-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-target");
            const input = document.getElementById(targetId);
            if (!input) return;

            const t = (k, p, d) => (typeof I18n !== 'undefined' ? I18n.t(k, p, d) : d);
            if (input.type === "password") {
                input.type = "text";
                btn.textContent = t("login.hidePassword", {}, "Hide");
            } else {
                input.type = "password";
                btn.textContent = t("login.showPassword", {}, "Show");
            }
        });
    });

    const t = (k, p, d) => (typeof I18n !== 'undefined' ? I18n.t(k, p, d) : d);

    function showAlert(message, type = "error") {
        alertBox.className = `alert-box visible ${type}`;
        alertBox.textContent = message;
    }

    function hideAlert() {
        alertBox.className = "alert-box";
        alertBox.textContent = "";
    }

    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideAlert();

        const identifier = identifierInput.value.trim();
        const password = passwordInput.value;

        if (!identifier) {
            showAlert(t("login.errorEmptyIdentifier", {}, "Please enter your registered email address or mobile number."));
            identifierInput.focus();
            return;
        }

        if (!password) {
            showAlert(t("login.errorEmptyPassword", {}, "Please enter your password."));
            passwordInput.focus();
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = t("login.submitting", {}, "Signing In...");

        try {
            const result = await apiFetch("/auth/login", {
                method: "POST",
                body: JSON.stringify({
                    identifier,
                    password,
                }),
            });

            if (!result.ok) {
                showAlert(result.error || t("login.loginFailed", {}, "Login failed. Please verify your credentials and try again."));
                submitBtn.disabled = false;
                submitBtn.textContent = t("login.submitBtn", {}, "Sign In");
                return;
            }

            showAlert(t("login.loginSuccess", {}, "Login successful! Loading your dashboard..."), "success");

            // Obtain CSRF token for the authenticated session
            await getCsrfToken();

            // Check if profile creation is required
            const profileRequired = result.data && result.data.profile_required;
            setTimeout(() => {
                if (profileRequired) {
                    window.location.href = "profile.html";
                } else {
                    window.location.href = "dashboard.html";
                }
            }, 600);

        } catch (err) {
            console.error("Login submission failure:", err);
            showAlert(t("login.unexpectedError", {}, "An unexpected error occurred during sign-in. Please try again."));
            submitBtn.disabled = false;
            submitBtn.textContent = t("login.submitBtn", {}, "Sign In");
        }
    });
});

