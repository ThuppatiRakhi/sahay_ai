"""Application definitions and structured form templates for SahayAI scholarship assistance.

Covers the five officially registered scholarship schemes:
1. SCHEME_EDU_001_PM_USP_CSSS (PM-USP Central Sector Scholarship Scheme)
2. SCHEME_EDU_002_AICTE_PRAGATI (AICTE Pragati Scholarship for Girls)
3. SCHEME_EDU_003_AICTE_SAKSHAM (AICTE Saksham Scholarship for Specially-Abled Students)
4. SCHEME_EDU_004_AICTE_SWANATH (AICTE Swanath Scholarship Scheme)
5. SCHEME_EDU_005_TOP_CLASS_SC (Top Class Education Scheme for SC Students)

Security & Integrity Guarantees:
- SahayAI acts solely as a citizen draft preparation and readiness assistant.
- SahayAI does NOT directly submit applications to government portals.
- Form templates are marked TEMPLATE_REQUIRES_VERIFICATION to signify that dynamic
  institutional fields must be verified against the official National Scholarship Portal (NSP).
- All portal URLs are strictly verified or marked NOT_VERIFIED.
"""

from typing import Any, Dict, List, Optional

SUPPORTED_SCHEME_IDS = {
    "SCHEME_EDU_001_PM_USP_CSSS",
    "SCHEME_EDU_002_AICTE_PRAGATI",
    "SCHEME_EDU_003_AICTE_SAKSHAM",
    "SCHEME_EDU_004_AICTE_SWANATH",
    "SCHEME_EDU_005_TOP_CLASS_SC",
    "SCHEME_AGRI_001_PM_KISAN",
    "SCHEME_MSME_001_PMEGP",
    "SCHEME_URBAN_001_PM_SVANIDHI",
    "SCHEME_LABOUR_001_PM_SYM",
    "SCHEME_WOMEN_001_PMUY_2",
}

# Standard common form sections across scholarship schemes
def _build_common_sections() -> List[Dict[str, Any]]:
    return [
        {
            "section_id": "personal_details",
            "title": "Personal Details",
            "description": "Basic demographic and identification details required for scholarship registration.",
            "fields": [
                {
                    "field_id": "applicant_name",
                    "label": "Full Name (as per Aadhaar/Class 10)",
                    "type": "text",
                    "required": True,
                    "placeholder": "Enter your full name",
                    "validation": {"min_length": 2, "max_length": 150},
                },
                {
                    "field_id": "date_of_birth",
                    "label": "Date of Birth",
                    "type": "date",
                    "required": True,
                    "placeholder": "YYYY-MM-DD",
                    "validation": {"format": "YYYY-MM-DD"},
                },
                {
                    "field_id": "gender",
                    "label": "Gender",
                    "type": "select",
                    "required": True,
                    "options": ["Female", "Male", "Other"],
                },
                {
                    "field_id": "caste_category",
                    "label": "Caste / Social Category",
                    "type": "select",
                    "required": True,
                    "options": ["General", "OBC", "SC", "ST", "EWS"],
                },
                {
                    "field_id": "mobile_number",
                    "label": "Mobile Number (Aadhaar linked)",
                    "type": "text",
                    "required": True,
                    "placeholder": "10-digit mobile number",
                    "validation": {"pattern": r"^[6-9]\d{9}$"},
                },
                {
                    "field_id": "email_address",
                    "label": "Email Address",
                    "type": "text",
                    "required": True,
                    "placeholder": "applicant@example.com",
                    "validation": {"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
                },
                {
                    "field_id": "state_residence",
                    "label": "State of Domicile",
                    "type": "text",
                    "required": True,
                    "placeholder": "e.g. Telangana, Maharashtra",
                },
                {
                    "field_id": "district_residence",
                    "label": "District of Domicile",
                    "type": "text",
                    "required": True,
                    "placeholder": "e.g. Hyderabad, Pune",
                },
                {
                    "field_id": "religion",
                    "label": "Religion / Community",
                    "type": "select",
                    "required": False,
                    "options": ["Hindu", "Muslim", "Christian", "Sikh", "Buddhist", "Jain", "Parsi", "Other"],
                },
                {
                    "field_id": "permanent_address",
                    "label": "Permanent Address (House/Flat No, Street, Village)",
                    "type": "text",
                    "required": False,
                    "placeholder": "Enter full permanent residential address",
                },
                {
                    "field_id": "pincode",
                    "label": "Postal PIN Code",
                    "type": "number",
                    "required": False,
                    "placeholder": "6-digit PIN code",
                    "validation": {"min": 100000, "max": 999999},
                },
                {
                    "field_id": "marital_status",
                    "label": "Marital Status",
                    "type": "select",
                    "required": False,
                    "options": ["Unmarried", "Married", "Divorced", "Widowed"],
                },
            ],
        },
        {
            "section_id": "family_income_details",
            "title": "Family & Income Details",
            "description": "Parental income and occupation details verified against Revenue Income Certificate.",
            "fields": [
                {
                    "field_id": "father_name",
                    "label": "Father's / Guardian's Full Name",
                    "type": "text",
                    "required": True,
                    "placeholder": "Enter father or guardian name",
                },
                {
                    "field_id": "mother_name",
                    "label": "Mother's Full Name",
                    "type": "text",
                    "required": True,
                    "placeholder": "Enter mother name",
                },
                {
                    "field_id": "annual_family_income",
                    "label": "Gross Annual Family Income (INR)",
                    "type": "number",
                    "required": True,
                    "placeholder": "e.g. 250000",
                    "validation": {"min": 0, "max": 5000000},
                },
                {
                    "field_id": "income_certificate_number",
                    "label": "Income Certificate Barcode / Number",
                    "type": "text",
                    "required": False,
                    "placeholder": "Certificate number issued by Tahsildar/SDM",
                },
                {
                    "field_id": "father_profession",
                    "label": "Father's / Guardian's Occupation",
                    "type": "select",
                    "required": False,
                    "options": ["Agriculture / Farming", "Self-Employed / Business", "Private Sector Service", "Government Service", "Daily Wage Earner", "Retired / Other"],
                },
                {
                    "field_id": "mother_profession",
                    "label": "Mother's Occupation",
                    "type": "select",
                    "required": False,
                    "options": ["Homemaker", "Agriculture / Farming", "Self-Employed / Business", "Private Sector Service", "Government Service", "Daily Wage Earner", "Other"],
                },
            ],
        },
        {
            "section_id": "bank_dbt_details",
            "title": "Bank & DBT Details",
            "description": "Direct Benefit Transfer (DBT) requires an individual savings account seeded with Aadhaar.",
            "fields": [
                {
                    "field_id": "bank_name",
                    "label": "Bank Name",
                    "type": "text",
                    "required": True,
                    "placeholder": "e.g. State Bank of India",
                },
                {
                    "field_id": "account_number",
                    "label": "Bank Account Number",
                    "type": "text",
                    "required": True,
                    "placeholder": "Enter individual account number",
                    "validation": {"pattern": r"^\d{9,18}$"},
                },
                {
                    "field_id": "ifsc_code",
                    "label": "IFSC Code",
                    "type": "text",
                    "required": True,
                    "placeholder": "e.g. SBIN0001234",
                    "validation": {"pattern": r"^[A-Z]{4}0[A-Z0-9]{6}$"},
                },
                {
                    "field_id": "aadhaar_seeded_confirmed",
                    "label": "My Bank Account is Active and Seeded with Aadhaar for DBT",
                    "type": "checkbox",
                    "required": True,
                },
            ],
        },
        {
            "section_id": "declarations",
            "title": "Review & Declarations",
            "description": "Mandatory citizen declarations required under Central Sector and AICTE guidelines.",
            "fields": [
                {
                    "field_id": "declaration_no_concurrent",
                    "label": "I declare that I am not receiving any other scholarship, stipend, or financial assistance from Central/State Government.",
                    "type": "checkbox",
                    "required": True,
                },
                {
                    "field_id": "declaration_information_true",
                    "label": "I declare that all details entered in this draft are genuine and verifiable against official certificates.",
                    "type": "checkbox",
                    "required": True,
                },
            ],
        },
    ]


SCHEME_APPLICATION_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # 1. PM-USP CSSS
    "SCHEME_EDU_001_PM_USP_CSSS": {
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "scheme_name": "PM-USP Central Sector Scholarship Scheme",
        "official_scheme_name": "Central Sector Scheme of Scholarship for College and University Students (PM-USP CSSS)",
        "responsible_ministry": "Ministry of Education",
        "responsible_department": "Department of Higher Education",
        "application_year": "AY 2026-27",
        "current_application_cycle": "AY 2026-27",
        "application_availability_status": "CLOSED",
        "last_deadline": "2026-10-31",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "National Scholarship Portal (NSP)",
            "official_portal_url": "https://scholarships.gov.in/ApplicationForm/#/login",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Official portal designated by Ministry of Education for PM-USP Central Sector Scheme student applications.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Prepare and review your draft application details inside SahayAI.\n"
            "2. Ensure gross annual family income does not exceed Rs. 4,50,000.\n"
            "3. Ensure your Class 12 score is above the 80th percentile for your respective State Board and stream.\n"
            "4. Verify that your bank account is active and seeded with Aadhaar in NPCI mapper.\n"
            "5. When the National Scholarship Portal opens, register using your One-Time Registration (OTR) / Aadhaar at scholarships.gov.in.\n"
            "6. Submit the final application and provide printed confirmation with required documents to your college/university nodal officer for institutional verification."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Class 12 Marksheet (proving > 80th percentile)", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Annual Family Income Certificate (<= Rs. 4,50,000)", "mandatory": True, "category": "INCOME"},
            {"document_name": "College Admission Proof / Bonafide Certificate", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bank Passbook (Aadhaar-seeded)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Caste / Category Certificate (for SC/ST/OBC/EWS)", "mandatory": False, "category": "CATEGORY_CERTIFICATE"},
            {"document_name": "Disability Certificate (>= 40% benchmark)", "mandatory": False, "category": "DISABILITY"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "academic_details",
                "title": "Academic Details (Higher Education)",
                "description": "Details of enrolled degree course and Class 12 qualifying examination.",
                "fields": [
                    {
                        "field_id": "institution_name",
                        "label": "Enrolled College / University Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "Name of UGC/AICTE recognized institution",
                    },
                    {
                        "field_id": "course_name",
                        "label": "Degree Course Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. B.Tech Computer Science, B.Sc Mathematics, B.A. Economics",
                    },
                    {
                        "field_id": "course_type",
                        "label": "Course Mode",
                        "type": "select",
                        "required": True,
                        "options": ["Regular Full-Time", "Distance/Correspondence (Ineligible)"],
                    },
                    {
                        "field_id": "current_academic_year",
                        "label": "Current Academic Year / Semester",
                        "type": "select",
                        "required": True,
                        "options": ["1st Year / Semester 1", "2nd Year", "3rd Year", "4th Year", "5th Year"],
                    },
                    {
                        "field_id": "class_12_board_name",
                        "label": "Class 12 Examination Board",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. CBSE, CISCE, Telangana State Board",
                    },
                    {
                        "field_id": "class_12_roll_no",
                        "label": "Class 12 Roll Number / Hall Ticket",
                        "type": "text",
                        "required": True,
                        "placeholder": "Enter Class 12 roll number",
                    },
                    {
                        "field_id": "class_12_passing_year",
                        "label": "Class 12 Passing Year",
                        "type": "number",
                        "required": True,
                        "placeholder": "2026",
                        "validation": {"min": 2020, "max": 2027},
                    },
                    {
                        "field_id": "class_12_percentile_or_marks",
                        "label": "Class 12 Percentile Score",
                        "type": "number",
                        "required": True,
                        "placeholder": "e.g. 84.5",
                        "validation": {"min": 0, "max": 100},
                        "help_text": "Must be greater than the 80th percentile cutoff of your examination board.",
                    },
                    {
                        "field_id": "institution_aishe_code",
                        "label": "Institution AISHE / College Code",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. C-12345 or U-0123",
                    },
                    {
                        "field_id": "day_scholar_hosteller",
                        "label": "Day Scholar / Hosteller",
                        "type": "select",
                        "required": False,
                        "options": ["Day Scholar", "Hosteller"],
                    },
                    {
                        "field_id": "class_10_board_name",
                        "label": "Class 10 Examination Board",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. CBSE, ICSE, State Board",
                    },
                    {
                        "field_id": "class_10_roll_no",
                        "label": "Class 10 Roll Number / Hall Ticket",
                        "type": "text",
                        "required": False,
                        "placeholder": "Enter Class 10 roll number",
                    },
                    {
                        "field_id": "class_10_passing_year",
                        "label": "Class 10 Passing Year",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 2024",
                        "validation": {"min": 2010, "max": 2030},
                    },
                    {
                        "field_id": "class_10_percentage",
                        "label": "Class 10 Aggregate Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 88.5",
                        "validation": {"min": 0, "max": 100},
                    },
                ],
            },
            _build_common_sections()[1],  # family_income_details
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },

    # 2. AICTE PRAGATI
    "SCHEME_EDU_002_AICTE_PRAGATI": {
        "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "scheme_name": "AICTE Pragati Scholarship for Girls",
        "official_scheme_name": "AICTE Pragati Scholarship Scheme for Girl Students (Technical Degree & Diploma)",
        "responsible_ministry": "Ministry of Education",
        "responsible_department": "All India Council for Technical Education (AICTE)",
        "application_year": "AY 2026-27",
        "current_application_cycle": "AY 2026-27",
        "application_availability_status": "OPEN",
        "last_deadline": "2026-11-30",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "National Scholarship Portal (NSP)",
            "official_portal_url": "https://scholarships.gov.in/ApplicationForm/#/login",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "AICTE officially mandates online application through the National Scholarship Portal (NSP). Reference: aicte-india.org/schemes/students-development-schemes/pragati.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Female students admitted to first year of Degree/Diploma or second year via lateral entry in AICTE-approved institutions.\n"
            "2. Maximum two girl children per family are eligible.\n"
            "3. Total family income from all sources must not exceed Rs. 8 Lakh per annum.\n"
            "4. Centralized admission counseling allotment letter is mandatory.\n"
            "5. Apply online on NSP (scholarships.gov.in) and submit institutional verification proforma (Annexure-II & III)."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Qualifying Marksheet (Class 10 for Diploma / Class 12 for Degree)", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Annual Family Income Certificate (<= Rs. 8 Lakh)", "mandatory": True, "category": "INCOME"},
            {"document_name": "Centralized Admission Allotment Letter (CAP)", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bonafide Certificate from Head of AICTE Institution", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Parent / Guardian Declaration Proforma (Annexure-III for max 2 girls)", "mandatory": True, "category": "SPECIAL_CATEGORY"},
            {"document_name": "Bank Passbook (Aadhaar-seeded)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Caste / Category Certificate", "mandatory": False, "category": "CATEGORY_CERTIFICATE"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "academic_details",
                "title": "Technical Education & Admission Details",
                "description": "Details of AICTE-approved technical program and centralized admission allotment.",
                "fields": [
                    {
                        "field_id": "aicte_institution_name",
                        "label": "AICTE-Approved Institution Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "Name of AICTE approved college/polytechnic",
                    },
                    {
                        "field_id": "course_level",
                        "label": "Course Level",
                        "type": "select",
                        "required": True,
                        "options": ["Technical Degree (B.Tech/B.E./B.Pharm/etc.)", "Technical Diploma (Polytechnic)"],
                    },
                    {
                        "field_id": "admission_type",
                        "label": "Admission Category",
                        "type": "select",
                        "required": True,
                        "options": ["First Year (Centralized Counseling)", "Second Year Lateral Entry (via Diploma/B.Sc.)"],
                    },
                    {
                        "field_id": "cap_allotment_number",
                        "label": "Centralized Counseling / CAP Allotment Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "Enter allotment letter reference number",
                    },
                    {
                        "field_id": "tuition_fee_paid",
                        "label": "Tuition Fee Paid (INR)",
                        "type": "number",
                        "required": True,
                        "placeholder": "Amount paid as per fee receipt",
                    },
                    {
                        "field_id": "course_name",
                        "label": "Degree / Diploma Specialization / Branch",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. B.Tech Computer Science, Diploma Mechanical",
                    },
                    {
                        "field_id": "current_academic_year",
                        "label": "Current Academic Year / Semester",
                        "type": "select",
                        "required": False,
                        "options": ["1st Year / Semester 1", "2nd Year Lateral Entry"],
                    },
                    {
                        "field_id": "aicte_approval_code",
                        "label": "AICTE Permanent Institute ID / AISHE Code",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. 1-12345678",
                    },
                    {
                        "field_id": "day_scholar_hosteller",
                        "label": "Day Scholar / Hosteller",
                        "type": "select",
                        "required": False,
                        "options": ["Day Scholar", "Hosteller"],
                    },
                    {
                        "field_id": "class_10_percentage",
                        "label": "Class 10 Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 85.0",
                        "validation": {"min": 0, "max": 100},
                    },
                    {
                        "field_id": "class_12_or_diploma_percentage",
                        "label": "Class 12 / Qualifying Exam Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 82.5",
                        "validation": {"min": 0, "max": 100},
                    },
                ],
            },
            {
                "section_id": "pragati_eligibility_details",
                "title": "Family Demographics (Pragati Specific)",
                "description": "Declaration of girl child count in family under AICTE guidelines.",
                "fields": [
                    {
                        "field_id": "girl_child_count_in_family",
                        "label": "Number of Girl Children in Family (including applicant)",
                        "type": "select",
                        "required": True,
                        "options": ["1 (Single Girl Child)", "2 (Two Girl Children)", "3 or More (Only max 2 eligible)"],
                    },
                    {
                        "field_id": "annexure_iii_signed",
                        "label": "Parent/Guardian signed Annexure-III declaration format",
                        "type": "checkbox",
                        "required": True,
                    },
                    {
                        "field_id": "single_girl_child",
                        "label": "Is Applicant the Only Girl Child in the Family?",
                        "type": "select",
                        "required": False,
                        "options": ["Yes - Single Girl Child", "No - Two Girl Children in Family"],
                    },
                ],
            },
            _build_common_sections()[1],  # family_income_details
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },

    # 3. AICTE SAKSHAM
    "SCHEME_EDU_003_AICTE_SAKSHAM": {
        "scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "scheme_name": "AICTE Saksham Scholarship for Specially-Abled Students",
        "official_scheme_name": "AICTE Saksham Scholarship Scheme for Specially-Abled Students (Technical Degree & Diploma)",
        "responsible_ministry": "Ministry of Education",
        "responsible_department": "All India Council for Technical Education (AICTE)",
        "application_year": "AY 2026-27",
        "current_application_cycle": "AY 2026-27",
        "application_availability_status": "OPEN",
        "last_deadline": "2026-11-30",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "National Scholarship Portal (NSP)",
            "official_portal_url": "https://scholarships.gov.in/ApplicationForm/#/login",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Designated on National Scholarship Portal under AICTE Saksham Scholarship Schemes.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Specially-abled students with benchmark disability not less than 40% admitted to 1st year Degree/Diploma or 2nd year lateral entry in AICTE-approved institutions.\n"
            "2. Total family income must not exceed Rs. 8 Lakh per annum.\n"
            "3. Disability Certificate issued by competent medical authority or UDID card is mandatory.\n"
            "4. Centralized admission allotment is mandatory.\n"
            "5. Submit draft on NSP and verify through your enrolled technical institution."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Disability Certificate (>= 40% issued by Medical Board / UDID Card)", "mandatory": True, "category": "DISABILITY"},
            {"document_name": "Qualifying Marksheet (Class 10/12)", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Annual Family Income Certificate (<= Rs. 8 Lakh)", "mandatory": True, "category": "INCOME"},
            {"document_name": "Centralized Admission Allotment Letter (CAP)", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bonafide Certificate from AICTE Institution Head", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bank Passbook (Aadhaar-seeded)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Caste / Category Certificate", "mandatory": False, "category": "CATEGORY_CERTIFICATE"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "disability_details",
                "title": "Disability & UDID Information",
                "description": "Benchmark disability details as per Rights of Persons with Disabilities Act (RPwD Act 2016).",
                "fields": [
                    {
                        "field_id": "disability_type",
                        "label": "Type of Benchmark Disability",
                        "type": "select",
                        "required": True,
                        "options": [
                            "Locomotor Disability",
                            "Visual Impairment (Blindness / Low Vision)",
                            "Hearing Impairment (Deaf / Hard of Hearing)",
                            "Speech and Language Disability",
                            "Intellectual Disability",
                            "Mental Illness",
                            "Multiple Disabilities",
                            "Other Benchmark Disability",
                        ],
                    },
                    {
                        "field_id": "disability_percentage",
                        "label": "Disability Percentage (%)",
                        "type": "number",
                        "required": True,
                        "placeholder": "Must be >= 40",
                        "validation": {"min": 40, "max": 100},
                        "help_text": "Must be 40% or higher as certified by competent medical board.",
                    },
                    {
                        "field_id": "udid_card_number",
                        "label": "UDID Card Number / Medical Certificate Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "Enter UDID number or certificate reference",
                    },
                    {
                        "field_id": "competent_medical_authority",
                        "label": "Issuing Medical Authority Designation",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. Chief Medical Officer, District Medical Board",
                    },
                    {
                        "field_id": "disability_certificate_issue_date",
                        "label": "Disability Certificate / UDID Issue Date",
                        "type": "date",
                        "required": False,
                        "placeholder": "YYYY-MM-DD",
                    },
                ],
            },
            {
                "section_id": "academic_details",
                "title": "Technical Education & Admission Details",
                "description": "Details of AICTE-approved technical program and admission allotment.",
                "fields": [
                    {
                        "field_id": "aicte_institution_name",
                        "label": "AICTE Institution Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "Name of AICTE approved institution",
                    },
                    {
                        "field_id": "course_level",
                        "label": "Course Level",
                        "type": "select",
                        "required": True,
                        "options": ["Technical Degree (B.Tech/B.E./B.Pharm/etc.)", "Technical Diploma (Polytechnic)"],
                    },
                    {
                        "field_id": "admission_type",
                        "label": "Admission Mode",
                        "type": "select",
                        "required": True,
                        "options": ["First Year (Centralized Counseling)", "Second Year Lateral Entry"],
                    },
                    {
                        "field_id": "cap_allotment_number",
                        "label": "Centralized Counseling / CAP Allotment Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "Enter allotment reference",
                    },
                    {
                        "field_id": "course_name",
                        "label": "Degree / Diploma Specialization / Branch",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. B.Tech Computer Science, Diploma Civil",
                    },
                    {
                        "field_id": "current_academic_year",
                        "label": "Current Academic Year / Semester",
                        "type": "select",
                        "required": False,
                        "options": ["1st Year / Semester 1", "2nd Year Lateral Entry"],
                    },
                    {
                        "field_id": "aicte_approval_code",
                        "label": "AICTE Permanent Institute ID / AISHE Code",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. 1-12345678",
                    },
                    {
                        "field_id": "day_scholar_hosteller",
                        "label": "Day Scholar / Hosteller",
                        "type": "select",
                        "required": False,
                        "options": ["Day Scholar", "Hosteller"],
                    },
                    {
                        "field_id": "class_10_percentage",
                        "label": "Class 10 Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 75.0",
                        "validation": {"min": 0, "max": 100},
                    },
                    {
                        "field_id": "class_12_or_diploma_percentage",
                        "label": "Class 12 / Qualifying Exam Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 72.0",
                        "validation": {"min": 0, "max": 100},
                    },
                ],
            },
            _build_common_sections()[1],  # family_income_details
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },

    # 4. AICTE SWANATH
    "SCHEME_EDU_004_AICTE_SWANATH": {
        "scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "scheme_name": "AICTE Swanath Scholarship Scheme",
        "official_scheme_name": "AICTE Swanath Scholarship Scheme for Orphans, Wards of COVID-19 Deceased & Wards of Martyrs",
        "responsible_ministry": "Ministry of Education",
        "responsible_department": "All India Council for Technical Education (AICTE)",
        "application_year": "AY 2026-27",
        "current_application_cycle": "AY 2026-27",
        "application_availability_status": "OPEN",
        "last_deadline": "2026-11-30",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "National Scholarship Portal (NSP)",
            "official_portal_url": "https://scholarships.gov.in/ApplicationForm/#/login",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Applications hosted on National Scholarship Portal (NSP) under AICTE Swanath scheme guidelines.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Students pursuing degree/diploma in AICTE-approved institutions falling under: (a) Orphans, (b) Either or both parents died due to COVID-19, or (c) Wards of Armed Forces / Central Paramilitary Forces martyred in action.\n"
            "2. Family income limit: Gross income must not exceed Rs. 8 Lakh per annum (except orphans where income certificate is not required).\n"
            "3. Enclose relevant death/martyr/orphan certificate issued by competent authority.\n"
            "4. Centralized admission is required.\n"
            "5. Submit on NSP and obtain institutional certification."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Orphan Certificate / Death Certificates of Parents / Shaheed Certificate", "mandatory": True, "category": "SPECIAL_CATEGORY"},
            {"document_name": "Centralized Admission Allotment Letter", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bonafide Certificate from AICTE Institution Head", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bank Passbook (Aadhaar-seeded)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Annual Family Income Certificate (<= Rs. 8 Lakh; exempted for orphans)", "mandatory": False, "category": "INCOME"},
            {"document_name": "Qualifying Marksheet", "mandatory": False, "category": "ACADEMIC"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "swanath_category_details",
                "title": "Swanath Eligibility Category",
                "description": "Select the qualifying criterion under AICTE Swanath guidelines.",
                "fields": [
                    {
                        "field_id": "swanath_criterion",
                        "label": "Qualifying Beneficiary Category",
                        "type": "select",
                        "required": True,
                        "options": [
                            "Orphan (Both parents deceased)",
                            "Both Parents or Surviving Parent died due to COVID-19",
                            "Ward of Armed Forces / Central Paramilitary Personnel Martyred in Action (Shaheed)",
                        ],
                    },
                    {
                        "field_id": "supporting_certificate_details",
                        "label": "Supporting Certificate / Issuing Authority Details",
                        "type": "text",
                        "required": True,
                        "placeholder": "Certificate number and issuing authority (e.g. Defense/CWC/Municipal)",
                    },
                    {
                        "field_id": "guardian_name",
                        "label": "Guardian / Legal Custodian Full Name",
                        "type": "text",
                        "required": False,
                        "placeholder": "Name of guardian or institution warden",
                    },
                    {
                        "field_id": "guardian_relation",
                        "label": "Relationship with Guardian",
                        "type": "select",
                        "required": False,
                        "options": ["Grandparent", "Uncle / Aunt", "Elder Sibling", "Child Care Institution Authority", "Other Legal Guardian"],
                    },
                    {
                        "field_id": "deceased_parent_name",
                        "label": "Name of Deceased Parent / Armed Forces Martyr",
                        "type": "text",
                        "required": False,
                        "placeholder": "Parent or martyr full name",
                    },
                ],
            },
            {
                "section_id": "academic_details",
                "title": "Technical Course Details",
                "description": "Details of enrolled AICTE technical course.",
                "fields": [
                    {
                        "field_id": "aicte_institution_name",
                        "label": "AICTE Institution Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "Name of AICTE approved institution",
                    },
                    {
                        "field_id": "course_level",
                        "label": "Course Level",
                        "type": "select",
                        "required": True,
                        "options": ["Technical Degree (B.Tech/B.E./B.Pharm/etc.)", "Technical Diploma (Polytechnic)"],
                    },
                    {
                        "field_id": "current_year",
                        "label": "Current Academic Year",
                        "type": "select",
                        "required": True,
                        "options": ["1st Year", "2nd Year", "3rd Year", "4th Year"],
                    },
                    {
                        "field_id": "course_name",
                        "label": "Degree / Diploma Specialization / Branch",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. B.Tech Computer Science, Diploma Mechanical",
                    },
                    {
                        "field_id": "aicte_approval_code",
                        "label": "AICTE Permanent Institute ID / AISHE Code",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. 1-12345678",
                    },
                    {
                        "field_id": "day_scholar_hosteller",
                        "label": "Day Scholar / Hosteller",
                        "type": "select",
                        "required": False,
                        "options": ["Day Scholar", "Hosteller"],
                    },
                    {
                        "field_id": "class_10_percentage",
                        "label": "Class 10 Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 80.0",
                        "validation": {"min": 0, "max": 100},
                    },
                    {
                        "field_id": "class_12_or_diploma_percentage",
                        "label": "Class 12 / Qualifying Exam Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 78.5",
                        "validation": {"min": 0, "max": 100},
                    },
                ],
            },
            _build_common_sections()[1],  # family_income_details
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },

    # 5. TOP CLASS SC
    "SCHEME_EDU_005_TOP_CLASS_SC": {
        "scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC",
        "scheme_name": "Top Class Education Scheme for SC Students",
        "official_scheme_name": "Central Sector Scholarship Scheme of Top Class Education for SC Students",
        "responsible_ministry": "Ministry of Social Justice and Empowerment",
        "responsible_department": "Department of Social Justice and Empowerment",
        "application_year": "AY 2026-27",
        "current_application_cycle": "AY 2026-27",
        "application_availability_status": "OPEN",
        "last_deadline": "2026-11-30",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "National Scholarship Portal (NSP)",
            "official_portal_url": "https://scholarships.gov.in/ApplicationForm/#/login",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Applications processed exclusively through National Scholarship Portal under Ministry of Social Justice & Empowerment guidelines.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Scheduled Caste (SC) students who have secured admission into notified premier institutions (IITs, IIMs, NITs, AIIMS, NLUs, etc.).\n"
            "2. Gross annual family income must not exceed Rs. 8 Lakh per annum.\n"
            "3. Enclose valid SC Caste Certificate issued by competent revenue authority (Tahsildar/Collector/SDM).\n"
            "4. Full tuition fee and non-refundable charges are reimbursed directly to the institution or student via DBT.\n"
            "5. Apply online on NSP (scholarships.gov.in) and notify the Dean/Registrar of your notified premier institute."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "SC Caste Certificate (Competent Revenue Authority)", "mandatory": True, "category": "CATEGORY_CERTIFICATE"},
            {"document_name": "Annual Family Income Certificate (<= Rs. 8 Lakh)", "mandatory": True, "category": "INCOME"},
            {"document_name": "Admission Letter and Fee Receipt from Notified Premier Institution", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Class 12 Marksheet (Min 60% Marks)", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Class 10 Marksheet", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bank Passbook (Aadhaar-seeded)", "mandatory": True, "category": "BANK"},
            {"document_name": "Bonafide Certificate from Institution Head / Dean", "mandatory": True, "category": "ACADEMIC"},
        ],
        "optional_documents": [
            {"document_name": "Entrance Exam Scorecard (e.g. JEE Adv / NEET / CAT / CLAT)", "mandatory": False, "category": "ACADEMIC"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "premier_institute_details",
                "title": "Notified Premier Institution & Course Details",
                "description": "Details of admission into empanelled premier institutions (IITs, NITs, IIMs, etc.).",
                "fields": [
                    {
                        "field_id": "premier_institution_name",
                        "label": "Notified Premier Institution Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. IIT Bombay, IIM Ahmedabad, NALSAR Hyderabad",
                    },
                    {
                        "field_id": "course_enrolled",
                        "label": "Course / Degree Program Enrolled",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. B.Tech Computer Science, MBA, B.A. LL.B (Hons)",
                    },
                    {
                        "field_id": "national_entrance_exam",
                        "label": "Competitive Entrance Examination",
                        "type": "select",
                        "required": True,
                        "options": ["JEE Advanced", "JEE Main", "NEET UG", "CAT", "CLAT", "Other National Exam"],
                    },
                    {
                        "field_id": "entrance_rank_or_score",
                        "label": "All India Rank / Percentile Score",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. AIR 1420",
                    },
                    {
                        "field_id": "total_annual_tuition_fee",
                        "label": "Annual Tuition & Non-Refundable Fee (INR)",
                        "type": "number",
                        "required": True,
                        "placeholder": "e.g. 215000",
                    },
                    {
                        "field_id": "current_academic_year",
                        "label": "Current Academic Year / Semester",
                        "type": "select",
                        "required": False,
                        "options": ["1st Year", "2nd Year", "3rd Year", "4th Year", "5th Year"],
                    },
                    {
                        "field_id": "day_scholar_hosteller",
                        "label": "Day Scholar / Hosteller",
                        "type": "select",
                        "required": False,
                        "options": ["Hosteller", "Day Scholar"],
                    },
                    {
                        "field_id": "caste_certificate_number",
                        "label": "SC Caste Certificate Number / Barcode",
                        "type": "text",
                        "required": False,
                        "placeholder": "Certificate number issued by Tahsildar/SDM",
                    },
                    {
                        "field_id": "caste_certificate_issuing_authority",
                        "label": "Caste Certificate Issuing Authority",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. Tehsildar / Sub-Divisional Magistrate",
                    },
                    {
                        "field_id": "caste_certificate_issue_date",
                        "label": "Caste Certificate Issue Date",
                        "type": "date",
                        "required": False,
                        "placeholder": "YYYY-MM-DD",
                    },
                    {
                        "field_id": "class_10_percentage",
                        "label": "Class 10 Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 85.0",
                        "validation": {"min": 0, "max": 100},
                    },
                    {
                        "field_id": "class_12_percentage",
                        "label": "Class 12 Percentage (%)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 82.5",
                        "validation": {"min": 0, "max": 100},
                    },
                ],
            },
            _build_common_sections()[1],  # family_income_details
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },
    "SCHEME_AGRI_001_PM_KISAN": {
        "scheme_id": "SCHEME_AGRI_001_PM_KISAN",
        "scheme_name": "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)",
        "responsible_ministry": "Ministry of Agriculture and Farmers Welfare",
        "official_portal_url": "https://pmkisan.gov.in/RegistrationFormNew.aspx",
        "current_application_cycle": "Continuous Year-Round Registration / Triannual DBT",
        "application_availability_status": "OPEN",
        "last_deadline": "Year-Round (Continuous)",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "PM-KISAN Portal",
            "official_portal_url": "https://pmkisan.gov.in/RegistrationFormNew.aspx",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "New Farmer Registration hosted on official PM-KISAN portal (pmkisan.gov.in).",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Small and marginal landholding farmer families with cultivable land in official land records.\n"
            "2. Mandatory Aadhaar e-KYC and NPCI-mapped active bank account.\n"
            "3. Enter Land Registration ID, Khata/Khesra number, and land area.\n"
            "4. Apply online via PM-KISAN portal or CSC."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Land Ownership Record (ROR / Khatauni)", "mandatory": True, "category": "LAND_REVENUE"},
            {"document_name": "Bank Passbook (NPCI/DBT linked)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Kisan Credit Card (KCC) Document", "mandatory": False, "category": "FINANCIAL"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "land_details",
                "title": "Land Ownership & Cultivation Details",
                "description": "State land records and cultivable land ownership details.",
                "fields": [
                    {
                        "field_id": "land_registration_id",
                        "label": "State Land Registration ID / Land Record ID",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. LR-2024-98472",
                    },
                    {
                        "field_id": "khata_number",
                        "label": "Khata / Survey Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Khata No. 142/A",
                    },
                    {
                        "field_id": "khasra_number",
                        "label": "Khasra / Dag Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. 89/1, 90/2",
                    },
                    {
                        "field_id": "cultivable_area_hectares",
                        "label": "Total Cultivable Land Area (in Hectares)",
                        "type": "number",
                        "required": True,
                        "placeholder": "e.g. 1.25",
                    },
                    {
                        "field_id": "land_ownership_type",
                        "label": "Ownership Type",
                        "type": "select",
                        "required": False,
                        "options": ["Single / Sole Owner", "Joint / Ancestral"],
                    },
                    {
                        "field_id": "land_transfer_date",
                        "label": "Date of Land Record Transfer / Mutation",
                        "type": "date",
                        "required": False,
                        "placeholder": "YYYY-MM-DD",
                    },
                ],
            },
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },
    "SCHEME_MSME_001_PMEGP": {
        "scheme_id": "SCHEME_MSME_001_PMEGP",
        "scheme_name": "Prime Minister's Employment Generation Programme (PMEGP)",
        "responsible_ministry": "Ministry of Micro, Small and Medium Enterprises",
        "official_portal_url": "https://www.kviconline.gov.in/pmegpeportal/jsp/pmegponline.jsp",
        "current_application_cycle": "FY 2026-27 Ongoing",
        "application_availability_status": "OPEN",
        "last_deadline": "Year-Round (Continuous)",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "KVIC PMEGP e-Portal",
            "official_portal_url": "https://www.kviconline.gov.in/pmegpeportal/jsp/pmegponline.jsp",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Individual and enterprise applications hosted on official KVIC online portal.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Individuals above 18 years for setting up new micro-enterprises in manufacturing or service sector.\n"
            "2. Subsidy: 15% to 35% margin money subsidy depending on category and area (rural/urban).\n"
            "3. Submit Detailed Project Report (DPR) along with qualification certificates.\n"
            "4. Apply online via KVIC e-Portal."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Detailed Project Report (DPR)", "mandatory": True, "category": "BUSINESS_PROJECT"},
            {"document_name": "Highest Educational Qualification Marksheet", "mandatory": True, "category": "ACADEMIC"},
            {"document_name": "Bank Account Details (Financing Bank)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Caste / Special Category Certificate", "mandatory": False, "category": "CATEGORY_CERTIFICATE"},
            {"document_name": "EDP Training Certificate", "mandatory": False, "category": "TRAINING"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "project_details",
                "title": "Project & Enterprise Details",
                "description": "Details of the proposed micro-enterprise and financial outlay.",
                "fields": [
                    {
                        "field_id": "activity_type",
                        "label": "Industry / Activity Type",
                        "type": "select",
                        "required": True,
                        "options": ["Manufacturing", "Service", "Trading"],
                    },
                    {
                        "field_id": "industry_sector",
                        "label": "Line of Activity / Proposed Industry",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Food Processing, Agro-Based Products, Tailoring",
                    },
                    {
                        "field_id": "project_cost_total",
                        "label": "Total Estimated Project Cost (INR)",
                        "type": "number",
                        "required": True,
                        "placeholder": "e.g. 500000",
                    },
                    {
                        "field_id": "capital_expenditure",
                        "label": "Capital Expenditure Requirement (INR)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 350000",
                    },
                    {
                        "field_id": "working_capital",
                        "label": "Working Capital Requirement (INR)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 150000",
                    },
                    {
                        "field_id": "edp_training_completed",
                        "label": "Entrepreneurship Development Programme (EDP) Status",
                        "type": "select",
                        "required": False,
                        "options": ["Completed", "Not Yet Completed", "Undergoing"],
                    },
                    {
                        "field_id": "proposed_employment_generation",
                        "label": "Proposed Direct Employment (Persons)",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 4",
                    },
                ],
            },
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },
    "SCHEME_URBAN_001_PM_SVANIDHI": {
        "scheme_id": "SCHEME_URBAN_001_PM_SVANIDHI",
        "scheme_name": "PM Street Vendor's AtmaNirbhar Nidhi (PM SVANidhi)",
        "responsible_ministry": "Ministry of Housing and Urban Affairs",
        "official_portal_url": "https://pmsvanidhi.mohua.gov.in/Home/PreApplication",
        "current_application_cycle": "FY 2026-27 Ongoing",
        "application_availability_status": "OPEN",
        "last_deadline": "Year-Round (Continuous)",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "PM SVANidhi Portal",
            "official_portal_url": "https://pmsvanidhi.mohua.gov.in/Home/PreApplication",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Vendor pre-application hosted on official MoHUA PM SVANidhi portal.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Urban street vendors vending on or before March 24, 2020.\n"
            "2. Working capital loan: 1st tranche Rs. 10,000, 2nd tranche Rs. 20,000, 3rd tranche Rs. 50,000.\n"
            "3. 7% interest subsidy on timely repayment and cashback up to Rs. 1,200/year on digital transactions.\n"
            "4. Apply online via PM SVANidhi portal or municipal ULB office."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Certificate of Vending (CoV) / Letter of Recommendation (LoR)", "mandatory": True, "category": "OCCUPATION"},
            {"document_name": "Bank Account Passbook / Statement", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Voter Identity Card", "mandatory": False, "category": "IDENTITY"},
            {"document_name": "UPI QR Code Merchant Receipt", "mandatory": False, "category": "FINANCIAL"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "vending_details",
                "title": "Vending Activity & Location Details",
                "description": "Details regarding vending location, municipal registration, and loan tranche.",
                "fields": [
                    {
                        "field_id": "vending_activity",
                        "label": "Nature of Vending Activity",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Vegetables/Fruits, Street Food, Snacks, Apparel",
                    },
                    {
                        "field_id": "vending_zone",
                        "label": "Vending Location / Market Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Main Market, Station Road",
                    },
                    {
                        "field_id": "urban_local_body",
                        "label": "Urban Local Body (Municipality/Corporation)",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Greater Hyderabad Municipal Corporation",
                    },
                    {
                        "field_id": "cov_or_lor_number",
                        "label": "Certificate of Vending (CoV) / LoR Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. COV-1204928",
                    },
                    {
                        "field_id": "loan_tranche",
                        "label": "Loan Tranche Applied For",
                        "type": "select",
                        "required": False,
                        "options": ["1st Tranche (Rs. 10,000)", "2nd Tranche (Rs. 20,000)", "3rd Tranche (Rs. 50,000)"],
                    },
                    {
                        "field_id": "digital_transaction_active",
                        "label": "Active Digital Payment Acceptance (UPI / QR Code)",
                        "type": "select",
                        "required": False,
                        "options": ["Yes (Active UPI QR)", "No (Cash Only)"],
                    },
                ],
            },
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },
    "SCHEME_LABOUR_001_PM_SYM": {
        "scheme_id": "SCHEME_LABOUR_001_PM_SYM",
        "scheme_name": "Pradhan Mantri Shram Yogi Maandhan (PM-SYM)",
        "responsible_ministry": "Ministry of Labour and Employment",
        "official_portal_url": "https://maandhan.in/shramyogi",
        "current_application_cycle": "Continuous Enrollment",
        "application_availability_status": "OPEN",
        "last_deadline": "Year-Round (Continuous)",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "MaanDhan Labour Welfare Portal",
            "official_portal_url": "https://maandhan.in/shramyogi",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "Self-enrollment and CSC registration on official MaanDhan portal.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Unorganized workers aged 18 to 40 years with monthly income <= Rs. 15,000.\n"
            "2. Not covered under EPFO / ESIC / NPS or income tax payee.\n"
            "3. Assured monthly pension of Rs. 3,000 after reaching 60 years of age.\n"
            "4. Enclose Aadhaar and savings bank account with auto-debit consent."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Savings Bank Passbook / Jan Dhan Account with Auto-Debit Mandate", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "e-Shram Card / 12-digit UAN Number", "mandatory": False, "category": "IDENTITY"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "unorganized_worker_details",
                "title": "Unorganized Worker & Pension Details",
                "description": "Occupation category, e-Shram details, and nominee information for pension.",
                "fields": [
                    {
                        "field_id": "unorganized_occupation_category",
                        "label": "Unorganized Worker Occupation",
                        "type": "select",
                        "required": True,
                        "options": [
                            "Construction Worker",
                            "Domestic Worker / Housemaid",
                            "Street Vendor / Hawker",
                            "Agricultural Labourer",
                            "Rickshaw / Auto Driver",
                            "Beedi / Handloom Worker",
                            "Mid-Day Meal Worker",
                            "Other Unorganized Occupation",
                        ],
                    },
                    {
                        "field_id": "eshram_uan_number",
                        "label": "e-Shram 12-digit UAN Number (if registered)",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. 1234 5678 9012",
                    },
                    {
                        "field_id": "monthly_income_declared",
                        "label": "Declared Monthly Income (INR, must be <= 15000)",
                        "type": "number",
                        "required": True,
                        "placeholder": "e.g. 11000",
                    },
                    {
                        "field_id": "nominee_name",
                        "label": "Nominee Full Name",
                        "type": "text",
                        "required": False,
                        "placeholder": "e.g. Spouse / Dependent Name",
                    },
                    {
                        "field_id": "nominee_relationship",
                        "label": "Relationship with Nominee",
                        "type": "select",
                        "required": False,
                        "options": ["Spouse", "Son", "Daughter", "Mother", "Father", "Other"],
                    },
                    {
                        "field_id": "nominee_dob",
                        "label": "Nominee Date of Birth",
                        "type": "date",
                        "required": False,
                        "placeholder": "YYYY-MM-DD",
                    },
                ],
            },
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },
    "SCHEME_WOMEN_001_PMUY_2": {
        "scheme_id": "SCHEME_WOMEN_001_PMUY_2",
        "scheme_name": "Pradhan Mantri Ujjwala Yojana 2.0 (PMUY)",
        "responsible_ministry": "Ministry of Petroleum and Natural Gas",
        "official_portal_url": "https://www.pmuy.gov.in/ujjwala2.html",
        "current_application_cycle": "FY 2026-27 Ongoing",
        "application_availability_status": "OPEN",
        "last_deadline": "Year-Round (Continuous)",
        "specification_status": "TEMPLATE_REQUIRES_VERIFICATION",
        "last_reviewed_date": "2026-11-02",
        "portal_verification": {
            "portal_name": "PMUY Official Portal",
            "official_portal_url": "https://www.pmuy.gov.in/ujjwala2.html",
            "portal_verification_status": "VERIFIED",
            "verification_evidence": "LPG connection application hosted on official MoPNG PMUY portal.",
            "is_active_link": True,
        },
        "application_instructions": (
            "1. Eligible: Adult woman from poor/deprived household without existing LPG connection in family.\n"
            "2. Deposit-free LPG connection with free first cylinder refill and gas stove.\n"
            "3. Submit Ration Card / State Family ID and Aadhaar cards of all adult family members.\n"
            "4. Apply online or at the nearest LPG dealership (Indane, Bharatgas, HP Gas)."
        ),
        "required_documents": [
            {"document_name": "Aadhaar Card of Adult Female Head", "mandatory": True, "category": "IDENTITY"},
            {"document_name": "Ration Card / Family Composition Document", "mandatory": True, "category": "FAMILY_DOCUMENT"},
            {"document_name": "Bank Account Passbook (Aadhaar linked)", "mandatory": True, "category": "BANK"},
        ],
        "optional_documents": [
            {"document_name": "Supplementary Address Proof (if different from Ration Card)", "mandatory": False, "category": "ADDRESS_PROOF"},
        ],
        "form_sections": [
            _build_common_sections()[0],  # personal_details
            {
                "section_id": "lpg_connection_details",
                "title": "LPG Connection & Distributor Preference",
                "description": "Choice of Oil Marketing Company (OMC) distributor and cylinder option.",
                "fields": [
                    {
                        "field_id": "omc_distributor_choice",
                        "label": "Preferred Oil Marketing Company (OMC)",
                        "type": "select",
                        "required": True,
                        "options": ["Indane (Indian Oil)", "Bharatgas (BPCL)", "HP Gas (HPCL)"],
                    },
                    {
                        "field_id": "distributor_name",
                        "label": "Name of Nearest LPG Distributor",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Sri Balaji Gas Agency",
                    },
                    {
                        "field_id": "ration_card_number",
                        "label": "Ration Card / Food Security Card Number",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. FSC-98472918",
                    },
                    {
                        "field_id": "family_adult_members_count",
                        "label": "Number of Adult Family Members",
                        "type": "number",
                        "required": False,
                        "placeholder": "e.g. 3",
                    },
                    {
                        "field_id": "cylinder_type_choice",
                        "label": "Cylinder Package Option",
                        "type": "select",
                        "required": False,
                        "options": ["14.2 kg Single Cylinder", "5 kg Single Cylinder", "5 kg Double Cylinder (DBC)"],
                    },
                    {
                        "field_id": "stove_loan_requested",
                        "label": "Opt for Loan for Stove and First Refill",
                        "type": "select",
                        "required": False,
                        "options": ["Yes (Zero Upfront Cost / Loan)", "No (Pay at Delivery)"],
                    },
                ],
            },
            _build_common_sections()[2],  # bank_dbt_details
            _build_common_sections()[3],  # declarations
        ],
    },

}


def is_valid_scheme_id(scheme_id: str) -> bool:
    """Check if the given scheme ID is one of the five supported schemes."""
    return scheme_id in SUPPORTED_SCHEME_IDS


def get_application_definition(scheme_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve structured application definition for a supported scheme.

    Returns None if scheme_id is not recognized.
    """
    if not is_valid_scheme_id(scheme_id):
        return None
    return SCHEME_APPLICATION_DEFINITIONS.get(scheme_id)


def get_all_application_definitions() -> Dict[str, Dict[str, Any]]:
    """Retrieve application definitions for all five supported schemes."""
    return SCHEME_APPLICATION_DEFINITIONS.copy()

