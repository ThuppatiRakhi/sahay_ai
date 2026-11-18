/**
 * SahayAI Extension - Supported Portals and Field Mappings
 *
 * Security and Integrity Rules:
 * 1. Strictly restricted to verified official portals (https://scholarships.gov.in).
 * 2. Field selectors are categorized as:
 *    - VERIFIED: Tested and confirmed on active portal forms.
 *    - TEMPLATE_ONLY: Standard portal field selectors pending live confirmation.
 *    - UNSUPPORTED: Security/declaration fields that MUST NEVER be autofilled.
 * 3. Security-sensitive fields (passwords, OTPs, CAPTCHAs, declarations) are strictly blocked.
 */

(function (root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = factory();
    } else {
        root.SahayAIPortals = factory();
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // Verified official government portal origins
    const VERIFIED_PORTAL_HOSTS = ["scholarships.gov.in"];

    // Supported Scholarship Scheme Identifiers
    const SUPPORTED_SCHEMES = {
        "SCHEME_EDU_001_PM_USP_CSSS": {
            name: "PM-USP Central Sector Scheme of Scholarship (CSSS)",
            officialPortalUrl: "https://scholarships.gov.in/ApplicationForm/#/login",
            formIdentifierKeywords: ["csss", "pm-usp", "central sector", "higher education"],
        },
        "SCHEME_EDU_002_AICTE_PRAGATI": {
            name: "AICTE Pragati Scholarship for Girl Students",
            officialPortalUrl: "https://scholarships.gov.in/ApplicationForm/#/login",
            formIdentifierKeywords: ["pragati", "aicte", "girl student"],
        },
        "SCHEME_EDU_003_AICTE_SAKSHAM": {
            name: "AICTE Saksham Scholarship for Specially-Abled Students",
            officialPortalUrl: "https://scholarships.gov.in/ApplicationForm/#/login",
            formIdentifierKeywords: ["saksham", "aicte", "divyang", "disability"],
        },
        "SCHEME_EDU_004_AICTE_SWANATH": {
            name: "AICTE Swanath Scholarship Scheme",
            officialPortalUrl: "https://scholarships.gov.in/ApplicationForm/#/login",
            formIdentifierKeywords: ["swanath", "aicte", "orphan", "covid"],
        },
        "SCHEME_EDU_005_TOP_CLASS_SC": {
            name: "Top Class Education Scheme for SC Students",
            officialPortalUrl: "https://scholarships.gov.in/ApplicationForm/#/login",
            formIdentifierKeywords: ["top class", "sc students", "social justice"],
        },
        "SCHEME_AGRI_001_PM_KISAN": {
            name: "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)",
            officialPortalUrl: "https://pmkisan.gov.in/RegistrationFormNew.aspx",
            formIdentifierKeywords: ["pmkisan", "kisan", "farmer"],
        },
        "SCHEME_MSME_001_PMEGP": {
            name: "Prime Minister Employment Generation Programme (PMEGP)",
            officialPortalUrl: "https://www.kviconline.gov.in/pmegpeportal/jsp/pmegponline.jsp",
            formIdentifierKeywords: ["pmegp", "kvic", "employment", "msme"],
        },
        "SCHEME_URBAN_001_PM_SVANIDHI": {
            name: "PM Street Vendor's AtmaNirbhar Nidhi (PM SVANidhi)",
            officialPortalUrl: "https://pmsvanidhi.mohua.gov.in/Home/PreApplication",
            formIdentifierKeywords: ["svanidhi", "street vendor", "urban"],
        },
        "SCHEME_LABOUR_001_PM_SYM": {
            name: "Pradhan Mantri Shram Yogi Maandhan (PM-SYM)",
            officialPortalUrl: "https://maandhan.in/shramyogi",
            formIdentifierKeywords: ["shram yogi", "maandhan", "pension"],
        },
        "SCHEME_WOMEN_001_PMUY_2": {
            name: "Pradhan Mantri Ujjwala Yojana 2.0 (PMUY)",
            officialPortalUrl: "https://www.pmuy.gov.in/ujjwala2.html",
            formIdentifierKeywords: ["ujjwala", "pmuy", "lpg"],
        },
    };

    // Strictly blocked security and sensitive selectors (NEVER TOUCHED)
    const FORBIDDEN_SELECTORS = [
        "input[type='password']",
        "input[name*='password' i]",
        "input[id*='password' i]",
        "input[name*='otp' i]",
        "input[id*='otp' i]",
        "input[name*='captcha' i]",
        "input[id*='captcha' i]",
        "input[name*='securityCode' i]",
        "input[id*='securityCode' i]",
        "#txtCaptcha",
        "#txtOtp",
        "#user_password",
        "input[name='csrf_token']",
    ];

    /**
     * Standard field mapping definitions for National Scholarship Portal forms.
     * Each mapping indicates its status: VERIFIED, TEMPLATE_ONLY, or UNSUPPORTED.
     */
    const FIELD_MAPPINGS = {
        applicant_name: {
            fieldId: "applicant_name",
            label: "Applicant Full Name",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#studentName",
                "#txtStudentName",
                "#applicantName",
                "input[name='studentName']",
                "input[name='applicantName']",
                "input[name='txtName']",
                "#txtName",
            ],
        },
        date_of_birth: {
            fieldId: "date_of_birth",
            label: "Date of Birth",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#dob",
                "#txtDOB",
                "#dateOfBirth",
                "input[name='dob']",
                "input[name='txtDOB']",
                "input[name='dateOfBirth']",
            ],
        },
        gender: {
            fieldId: "gender",
            label: "Gender",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#ddlGender",
                "#gender",
                "select[name='gender']",
                "select[name='ddlGender']",
                "input[name='gender']",
            ],
        },
        caste_category: {
            fieldId: "caste_category",
            label: "Community / Caste Category",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#ddlCategory",
                "#casteCategory",
                "#community",
                "select[name='category']",
                "select[name='ddlCategory']",
                "select[name='caste']",
            ],
        },
        mobile_number: {
            fieldId: "mobile_number",
            label: "Mobile Number",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#mobileNo",
                "#txtMobile",
                "#phone",
                "input[name='mobile']",
                "input[name='mobileNo']",
                "input[name='txtMobile']",
            ],
        },
        email_address: {
            fieldId: "email_address",
            label: "Email Address",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#email",
                "#txtEmail",
                "#emailId",
                "input[name='email']",
                "input[name='emailId']",
                "input[name='txtEmail']",
            ],
        },
        state_residence: {
            fieldId: "state_residence",
            label: "Domicile State",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#ddlState",
                "#domicileState",
                "#state",
                "select[name='state']",
                "select[name='ddlState']",
                "select[name='domicileState']",
            ],
        },
        district_residence: {
            fieldId: "district_residence",
            label: "District of Residence",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#ddlDistrict",
                "#district",
                "select[name='district']",
                "select[name='ddlDistrict']",
            ],
        },
        father_name: {
            fieldId: "father_name",
            label: "Father's Name",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#fatherName",
                "#txtFatherName",
                "input[name='fatherName']",
                "input[name='txtFather']",
            ],
        },
        mother_name: {
            fieldId: "mother_name",
            label: "Mother's Name",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#motherName",
                "#txtMotherName",
                "input[name='motherName']",
                "input[name='txtMother']",
            ],
        },
        annual_family_income: {
            fieldId: "annual_family_income",
            label: "Annual Family Income",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#annualIncome",
                "#txtAnnualIncome",
                "#familyIncome",
                "input[name='annualIncome']",
                "input[name='familyIncome']",
            ],
        },
        income_certificate_number: {
            fieldId: "income_certificate_number",
            label: "Income Certificate Registration Number",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#incomeCertNo",
                "#txtIncomeCertNo",
                "input[name='incomeCertNo']",
                "input[name='incomeCertificateNo']",
            ],
        },
        bank_name: {
            fieldId: "bank_name",
            label: "Bank Name",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#bankName",
                "#ddlBank",
                "select[name='bankName']",
                "input[name='bankName']",
                "select[name='ddlBank']",
            ],
        },
        account_number: {
            fieldId: "account_number",
            label: "Bank Account Number",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#bankAccountNo",
                "#txtAccountNo",
                "#accountNo",
                "input[name='bankAccountNo']",
                "input[name='accountNo']",
                "input[name='txtAccountNo']",
            ],
        },
        ifsc_code: {
            fieldId: "ifsc_code",
            label: "IFSC Code",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#ifscCode",
                "#txtIFSC",
                "#ifsc",
                "input[name='ifscCode']",
                "input[name='ifsc']",
                "input[name='txtIFSC']",
            ],
        },
        institution_name: {
            fieldId: "institution_name",
            label: "Institution / College Name",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#institutionName",
                "#ddlInstitute",
                "select[name='institution']",
                "input[name='institutionName']",
            ],
        },
        class_12_roll_no: {
            fieldId: "class_12_roll_no",
            label: "Class 12 Roll Number",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#class12RollNo",
                "#txtRollNo12",
                "input[name='class12RollNo']",
                "input[name='rollNo12']",
            ],
        },
        class_12_passing_year: {
            fieldId: "class_12_passing_year",
            label: "Class 12 Passing Year",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#class12PassingYear",
                "#passingYear12",
                "select[name='passingYear12']",
                "input[name='passingYear12']",
            ],
        },
        udid_card_number: {
            fieldId: "udid_card_number",
            label: "UDID Card Number",
            status: "TEMPLATE_ONLY",
            selectors: [
                "#udidNo",
                "#txtUDID",
                "input[name='udidNo']",
                "input[name='udidCardNo']",
            ],
        },
        declaration_no_concurrent: {
            fieldId: "declaration_no_concurrent",
            label: "Concurrent Scholarship Declaration",
            status: "UNSUPPORTED",
            selectors: [],
            reason: "Declarations must be reviewed and affirmed manually by the citizen.",
        },
        declaration_information_true: {
            fieldId: "declaration_information_true",
            label: "Information Truthfulness Declaration",
            status: "UNSUPPORTED",
            selectors: [],
            reason: "Truthfulness declarations require manual citizen sign-off.",
        },
    };

    /**
     * Check if a given URL is a verified government portal.
     * @param {string} urlString
     * @returns {boolean}
     */
    function isVerifiedPortal(urlString) {
        if (!urlString) return false;
        try {
            const parsed = new URL(urlString);
            const host = parsed.hostname.toLowerCase();
            return (
                VERIFIED_PORTAL_HOSTS.includes(host) ||
                host.endsWith(".scholarships.gov.in")
            );
        } catch (e) {
            return false;
        }
    }

    /**
     * Check whether an element matches any forbidden security selector.
     * @param {Element} element
     * @returns {boolean}
     */
    function isForbiddenElement(element) {
        if (!element) return true;
        for (const sel of FORBIDDEN_SELECTORS) {
            try {
                if (element.matches && element.matches(sel)) return true;
            } catch (e) {
                // Ignore selector syntax issues in older mock environments
            }
        }
        const type = (element.getAttribute("type") || "").toLowerCase();
        if (type === "password") return true;

        const name = (element.getAttribute("name") || "").toLowerCase();
        const id = (element.getAttribute("id") || "").toLowerCase();
        const sensitiveTokens = ["password", "otp", "captcha", "securitycode", "token"];
        for (const token of sensitiveTokens) {
            if (name.includes(token) || id.includes(token)) return true;
        }
        return false;
    }

    /**
     * Find a DOM input matching a field's selectors within a given root document or form.
     * Note: Only fields with status === "VERIFIED" are eligible to be located for autofilling.
     * TEMPLATE_ONLY and UNSUPPORTED fields return null to strictly prohibit population.
     * @param {Document|Element} rootEl
     * @param {string} fieldId
     * @returns {Element|null}
     */
    function findFieldElement(rootEl, fieldId) {
        const spec = FIELD_MAPPINGS[fieldId];
        // Enforce strict check: ONLY VERIFIED mappings may ever return an element for autofill
        if (!spec || spec.status !== "VERIFIED" || !spec.selectors) {
            return null;
        }

        for (const sel of spec.selectors) {
            try {
                const el = rootEl.querySelector(sel);
                if (el && !isForbiddenElement(el)) {
                    return el;
                }
            } catch (e) {
                // Ignore unsupported selector quirks
            }
        }
        return null;
    }

    /**
     * Check if a field mapping has been verified against live government forms.
     * @param {string} fieldId
     * @returns {boolean}
     */
    function isVerifiedField(fieldId) {
        const spec = FIELD_MAPPINGS[fieldId];
        return Boolean(spec && spec.status === "VERIFIED");
    }

    return {
        VERIFIED_PORTAL_HOSTS,
        SUPPORTED_SCHEMES,
        FORBIDDEN_SELECTORS,
        FIELD_MAPPINGS,
        isVerifiedPortal,
        isForbiddenElement,
        findFieldElement,
        isVerifiedField,
    };
});

