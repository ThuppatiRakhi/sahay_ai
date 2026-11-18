"""Document-Type-Specific Extraction Schemas and Field Registry for SahayAI.

Defines schemas, field definitions, metadata mappings, and validation contracts
for all supported Indian welfare and academic document types:
- 10th marksheet (MARKSHEET_10TH)
- 12th marksheet (MARKSHEET_12TH)
- Aadhaar card (AADHAAR_CARD)
- Income certificate (INCOME_CERTIFICATE)
- Caste certificate (CASTE_CERTIFICATE)
- Residence certificate (RESIDENCE_CERTIFICATE / DOMICILE_CERTIFICATE)
- Bank passbook (BANK_PASSBOOK)
- Fee receipt (FEES_RECEIPT)
- PAN card (PAN_CARD)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class DocumentType(str, Enum):
    """Canonical document types supported by SahayAI intelligent OCR."""
    MARKSHEET_12TH = "MARKSHEET_12TH"
    MARKSHEET_10TH = "MARKSHEET_10TH"
    AADHAAR_CARD = "AADHAAR_CARD"
    INCOME_CERTIFICATE = "INCOME_CERTIFICATE"
    CASTE_CERTIFICATE = "CASTE_CERTIFICATE"
    RESIDENCE_CERTIFICATE = "RESIDENCE_CERTIFICATE"
    DOMICILE_CERTIFICATE = "DOMICILE_CERTIFICATE"
    BANK_PASSBOOK = "BANK_PASSBOOK"
    FEES_RECEIPT = "FEES_RECEIPT"
    PAN_CARD = "PAN_CARD"
    DEGREE_CERTIFICATE = "DEGREE_CERTIFICATE"
    BONAFIDE_CERTIFICATE = "BONAFIDE_CERTIFICATE"
    DISABILITY_CERTIFICATE = "DISABILITY_CERTIFICATE"
    RATION_CARD = "RATION_CARD"
    UNKNOWN = "UNKNOWN_DOCUMENT"


@dataclass
class FieldDefinition:
    """Definition of an individual field within a document extraction schema."""
    field_name: str
    label: str
    field_type: str  # 'string', 'number', 'date', 'table', 'masked_id', 'boolean'
    is_required: bool = False
    is_sensitive: bool = False
    maps_to_profile: Optional[str] = None
    description: str = ""
    example: Optional[Any] = None


@dataclass
class DocumentSchema:
    """Schema defining expected fields and extraction rules for a document type."""
    document_type: str
    display_name: str
    category: str
    fields: List[FieldDefinition] = field(default_factory=list)
    description: str = ""

    def get_field_names(self) -> List[str]:
        """Return list of all field names in schema."""
        return [f.field_name for f in self.fields]

    def get_required_field_names(self) -> List[str]:
        """Return list of required field names."""
        return [f.field_name for f in self.fields if f.is_required]

    def get_field(self, field_name: str) -> Optional[FieldDefinition]:
        """Retrieve FieldDefinition by field name."""
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None


# ---------------------------------------------------------------------------
# Schema Definitions
# ---------------------------------------------------------------------------

SCHEMA_MARKSHEET_12TH = DocumentSchema(
    document_type=DocumentType.MARKSHEET_12TH.value,
    display_name="Class 12 Marksheet",
    category="ACADEMIC",
    description="Higher Secondary / Intermediate (10+2) Examination Certificate and Marksheet",
    fields=[
        FieldDefinition("student_name", "Student Name", "string", is_required=True, maps_to_profile="full_name", description="Full name of student as printed on marksheet"),
        FieldDefinition("father_name", "Father's Name", "string", is_required=False, description="Father's name if printed"),
        FieldDefinition("mother_name", "Mother's Name", "string", is_required=False, description="Mother's name if printed"),
        FieldDefinition("board_name", "Board / Council Name", "string", is_required=True, description="Examination board (e.g., CBSE, CISCE, State Board)"),
        FieldDefinition("state", "State", "string", is_required=False, maps_to_profile="state", description="State of the examination board / institution"),
        FieldDefinition("school_name", "School / College Name", "string", is_required=False, description="Name of the educational institution"),
        FieldDefinition("roll_number", "Roll No / Hall Ticket No", "string", is_required=True, description="Examination roll number or hall ticket number"),
        FieldDefinition("examination_year", "Examination Year", "number", is_required=True, description="Year in which the examination was conducted"),
        FieldDefinition("subject_marks", "Subject-Wise Marks Table", "table", is_required=True, description="Structured breakdown of marks obtained per subject"),
        FieldDefinition("total_obtained_marks", "Total Obtained Marks", "number", is_required=True, description="Sum of marks obtained across subjects"),
        FieldDefinition("maximum_total_marks", "Maximum Total Marks", "number", is_required=True, description="Maximum possible aggregate marks"),
        FieldDefinition("percentage", "Aggregate Percentage", "number", is_required=True, description="Overall percentage scored (e.g., 88.5)"),
        FieldDefinition("grade", "Overall Grade / Division", "string", is_required=False, description="Overall grade or division awarded (e.g., A1, First Division)"),
        FieldDefinition("result_status", "Result Status", "string", is_required=True, description="Final outcome: PASS / PASSED / QUALIFIED / FAIL"),
    ]
)

SCHEMA_MARKSHEET_10TH = DocumentSchema(
    document_type=DocumentType.MARKSHEET_10TH.value,
    display_name="Class 10 Marksheet",
    category="ACADEMIC",
    description="Secondary School Examination (10th Standard / Matriculation) Marksheet",
    fields=[
        FieldDefinition("student_name", "Student Name", "string", is_required=True, maps_to_profile="full_name", description="Full name of student as printed on marksheet"),
        FieldDefinition("board_name", "Board Name", "string", is_required=True, description="Examination board name (e.g., CBSE, ICSE, SSC State Board)"),
        FieldDefinition("state", "State", "string", is_required=False, maps_to_profile="state", description="State of the examination board / institution"),
        FieldDefinition("roll_number", "Roll Number", "string", is_required=True, description="Student examination roll number"),
        FieldDefinition("school_name", "School Name", "string", is_required=False, description="Name of the school"),
        FieldDefinition("examination_year", "Examination Year", "number", is_required=True, description="Year of examination completion"),
        FieldDefinition("subject_marks", "Subject-Wise Marks Table", "table", is_required=True, description="Subject marks breakdown"),
        FieldDefinition("total_obtained_marks", "Total Marks", "number", is_required=True, description="Total marks secured"),
        FieldDefinition("maximum_total_marks", "Maximum Total Marks", "number", is_required=False, description="Maximum total marks"),
        FieldDefinition("percentage", "Percentage", "number", is_required=True, description="Percentage of marks scored"),
        FieldDefinition("grade", "Grade", "string", is_required=False, description="Overall letter grade or division"),
        FieldDefinition("result_status", "Result Status", "string", is_required=True, description="Pass or fail status"),
        FieldDefinition("date_of_birth", "Date of Birth (if printed)", "date", is_required=False, maps_to_profile="date_of_birth", description="Birth date printed on 10th certificate"),
    ]
)

SCHEMA_AADHAAR = DocumentSchema(
    document_type=DocumentType.AADHAAR_CARD.value,
    display_name="Aadhaar Card",
    category="IDENTITY",
    description="UIDAI Aadhaar Card / e-Aadhaar National Identity Document",
    fields=[
        FieldDefinition("name", "Full Name", "string", is_required=True, maps_to_profile="full_name", description="Resident's full legal name"),
        FieldDefinition("date_of_birth", "Date of Birth / Year of Birth", "string", is_required=True, maps_to_profile="date_of_birth", description="Date of birth in DD/MM/YYYY format or birth year"),
        FieldDefinition("gender", "Gender", "string", is_required=True, maps_to_profile="gender", description="Gender: MALE, FEMALE, or TRANSGENDER"),
        FieldDefinition("aadhaar_number", "Aadhaar Number (Masked)", "masked_id", is_required=True, is_sensitive=True, maps_to_profile="aadhaar_number", description="Masked 12-digit UID (XXXX-XXXX-1234)"),
    ]
)

SCHEMA_INCOME_CERTIFICATE = DocumentSchema(
    document_type=DocumentType.INCOME_CERTIFICATE.value,
    display_name="Income Certificate",
    category="INCOME",
    description="Official Revenue Authority Certificate of Annual Family Income",
    fields=[
        FieldDefinition("applicant_name", "Applicant / Head of Family Name", "string", is_required=True, maps_to_profile="full_name", description="Name of applicant or head of family"),
        FieldDefinition("annual_income", "Annual Family Income (Rs.)", "number", is_required=True, maps_to_profile="annual_income", description="Certified total annual family income in Indian Rupees"),
        FieldDefinition("certificate_number", "Certificate Number", "string", is_required=True, description="Official revenue certificate dispatch or application number"),
        FieldDefinition("issuing_authority", "Issuing Authority", "string", is_required=True, description="Government officer title (e.g., Tahsildar, Mandal Revenue Officer, SDM)"),
        FieldDefinition("issue_date", "Date of Issue", "date", is_required=True, description="Official date of certificate issuance"),
        FieldDefinition("validity_period", "Validity Period", "string", is_required=False, description="Stated validity period or financial year validity"),
    ]
)

SCHEMA_CASTE_CERTIFICATE = DocumentSchema(
    document_type=DocumentType.CASTE_CERTIFICATE.value,
    display_name="Caste / Community Certificate",
    category="CATEGORY_CERTIFICATE",
    description="Government Caste / Tribe / Community Certificate for Reservation Eligibility",
    fields=[
        FieldDefinition("applicant_name", "Applicant Name", "string", is_required=True, maps_to_profile="full_name", description="Legal name of citizen"),
        FieldDefinition("caste_community", "Caste / Sub-Caste Name", "string", is_required=True, description="Specific caste, sub-caste, or community name"),
        FieldDefinition("caste_category", "Reservation Category", "string", is_required=True, maps_to_profile="caste_category", description="Government category: SC, ST, OBC, EWS, or GENERAL"),
        FieldDefinition("certificate_number", "Certificate Number", "string", is_required=True, description="Unique registration or certificate number"),
        FieldDefinition("issuing_authority", "Issuing Authority", "string", is_required=True, description="Competent authority (e.g., Tahsildar, Revenue Divisional Officer, District Magistrate)"),
        FieldDefinition("issue_date", "Date of Issue", "date", is_required=True, description="Date on which the caste certificate was issued"),
    ]
)

SCHEMA_RESIDENCE_CERTIFICATE = DocumentSchema(
    document_type=DocumentType.RESIDENCE_CERTIFICATE.value,
    display_name="Residence / Domicile Certificate",
    category="RESIDENCE",
    description="Certificate of Permanent Residence, Domicile, or Nativity",
    fields=[
        FieldDefinition("applicant_name", "Applicant Name", "string", is_required=True, maps_to_profile="full_name", description="Full name of resident"),
        FieldDefinition("residential_address", "Residential Address", "string", is_required=True, description="Certified residential address, town/village, district, state"),
        FieldDefinition("certificate_number", "Certificate Number", "string", is_required=True, description="Official registration or application number"),
        FieldDefinition("issuing_authority", "Issuing Authority", "string", is_required=True, description="Revenue officer or executive magistrate title"),
        FieldDefinition("issue_date", "Date of Issue", "date", is_required=True, description="Date of issuance"),
    ]
)

SCHEMA_BANK_PASSBOOK = DocumentSchema(
    document_type=DocumentType.BANK_PASSBOOK.value,
    display_name="Bank Passbook / Statement",
    category="BANK",
    description="First page of Savings Bank Account Passbook or Account Statement Header",
    fields=[
        FieldDefinition("account_holder_name", "Account Holder Name", "string", is_required=True, maps_to_profile="full_name", description="Primary bank account holder's name"),
        FieldDefinition("bank_name", "Bank Name", "string", is_required=True, description="Name of the scheduled commercial or rural bank"),
        FieldDefinition("branch", "Branch Name", "string", is_required=True, description="Bank branch name or location"),
        FieldDefinition("ifsc_code", "IFSC Code", "string", is_required=True, description="11-character Indian Financial System Code (e.g., SBIN0001234)"),
        FieldDefinition("account_number", "Account Number (Masked)", "masked_id", is_required=True, is_sensitive=True, description="Masked bank account number showing only last 4 digits"),
    ]
)

SCHEMA_FEES_RECEIPT = DocumentSchema(
    document_type=DocumentType.FEES_RECEIPT.value,
    display_name="Fee Receipt",
    category="ACADEMIC",
    description="Official Tuition Fee / Admission Payment Receipt from Recognized Institution",
    fields=[
        FieldDefinition("student_name", "Student Name", "string", is_required=True, maps_to_profile="full_name", description="Full name of student as printed on receipt"),
        FieldDefinition("institution_name", "College / Institute Name", "string", is_required=True, description="Name of the school, polytechnic, college, or university"),
        FieldDefinition("academic_year", "Academic Year", "string", is_required=True, description="Academic year (e.g., 2026-2027) or semester"),
        FieldDefinition("fee_amount", "Fee Amount Paid (Rs.)", "number", is_required=True, description="Total numerical amount paid towards fees"),
        FieldDefinition("payment_date", "Payment Date", "date", is_required=True, description="Date on which the payment transaction was completed"),
        FieldDefinition("receipt_number", "Receipt Number", "string", is_required=True, description="Unique institutional fee voucher or transaction receipt number"),
    ]
)

SCHEMA_PAN_CARD = DocumentSchema(
    document_type=DocumentType.PAN_CARD.value,
    display_name="PAN Card",
    category="IDENTITY",
    description="Permanent Account Number Card issued by Income Tax Department",
    fields=[
        FieldDefinition("name", "Full Name", "string", is_required=True, maps_to_profile="full_name", description="Cardholder's name"),
        FieldDefinition("father_name", "Father's Name", "string", is_required=False, description="Father's name"),
        FieldDefinition("date_of_birth", "Date of Birth", "date", is_required=True, maps_to_profile="date_of_birth", description="Birth date in DD/MM/YYYY"),
        FieldDefinition("pan_number", "PAN Number (Masked)", "masked_id", is_required=True, is_sensitive=True, description="Masked 10-character alphanumeric PAN (XXXXX1234X)"),
    ]
)

SCHEMA_DEGREE_CERTIFICATE = DocumentSchema(
    document_type=DocumentType.DEGREE_CERTIFICATE.value,
    display_name="Degree Certificate / Transcript",
    category="ACADEMIC",
    description="University Degree Certificate, Provisional Certificate, or Academic Transcript",
    fields=[
        FieldDefinition("student_name", "Student Name", "string", is_required=True, maps_to_profile="full_name", description="Candidate's full name"),
        FieldDefinition("degree_name", "Degree / Program Name", "string", is_required=True, description="Conferred degree (e.g. B.Tech, B.Sc, B.Com, MBA)"),
        FieldDefinition("university_name", "University / Institution Name", "string", is_required=True, description="Issuing university or institute"),
        FieldDefinition("passing_year", "Passing / Convocation Year", "number", is_required=True, description="Year of graduation or convocation"),
        FieldDefinition("roll_number", "Roll / Registration Number", "string", is_required=False, description="University roll or hall ticket number"),
        FieldDefinition("cgpa_or_percentage", "CGPA / Percentage", "number", is_required=False, description="Final cumulative GPA or percentage"),
        FieldDefinition("division", "Class / Division", "string", is_required=False, description="Division or grade awarded"),
    ]
)

SCHEMA_BONAFIDE_CERTIFICATE = DocumentSchema(
    document_type=DocumentType.BONAFIDE_CERTIFICATE.value,
    display_name="Bonafide Certificate",
    category="ACADEMIC",
    description="Institutional Bonafide Student / Study Certificate",
    fields=[
        FieldDefinition("student_name", "Student Name", "string", is_required=True, maps_to_profile="full_name", description="Enrolled student name"),
        FieldDefinition("institution_name", "Institution Name", "string", is_required=True, description="School, college, or university name"),
        FieldDefinition("course_name", "Course / Program", "string", is_required=False, description="Current course of study"),
        FieldDefinition("academic_year", "Academic Year", "string", is_required=False, description="Enrolled academic session"),
        FieldDefinition("admission_number", "Admission / Roll No", "string", is_required=False, description="College admission or student ID"),
    ]
)

SCHEMA_DISABILITY_CERTIFICATE = DocumentSchema(
    document_type=DocumentType.DISABILITY_CERTIFICATE.value,
    display_name="Disability Certificate (PwD / UDID)",
    category="DISABILITY",
    description="Medical Board Disability Certificate or Unique Disability ID (UDID) Card",
    fields=[
        FieldDefinition("beneficiary_name", "Beneficiary Name", "string", is_required=True, maps_to_profile="full_name", description="Cardholder name"),
        FieldDefinition("udid_number", "UDID / Certificate Number", "string", is_required=True, description="Unique Disability ID or certificate registration number"),
        FieldDefinition("disability_type", "Type of Disability", "string", is_required=True, description="Nature of disability (e.g. Locomotor, Visual, Hearing)"),
        FieldDefinition("disability_percentage", "Disability Percentage", "number", is_required=True, description="Certified percentage of disability"),
        FieldDefinition("issuing_authority", "Medical Authority / Hospital", "string", is_required=False, description="Issuing district medical board or hospital"),
    ]
)

SCHEMA_RATION_CARD = DocumentSchema(
    document_type=DocumentType.RATION_CARD.value,
    display_name="Ration Card / Food Security Card",
    category="INCOME",
    description="State Food Security Card or BPL Ration Card",
    fields=[
        FieldDefinition("head_of_family", "Head of Family", "string", is_required=True, maps_to_profile="full_name", description="Name of family head / cardholder"),
        FieldDefinition("ration_card_number", "Ration Card Number", "string", is_required=True, description="Unique ration / food security card number"),
        FieldDefinition("card_type", "Card Category", "string", is_required=False, description="Card category: BPL, White Card, Antyodaya (AAY), NFSA"),
        FieldDefinition("district", "District", "string", is_required=False, description="Issuing district / mandal"),
    ]
)


class DocumentTypeRegistry:
    """Central registry of all document schemas, field definitions, and normalization mappings."""

    _REGISTRY: Dict[str, DocumentSchema] = {
        DocumentType.MARKSHEET_12TH.value: SCHEMA_MARKSHEET_12TH,
        DocumentType.MARKSHEET_10TH.value: SCHEMA_MARKSHEET_10TH,
        DocumentType.AADHAAR_CARD.value: SCHEMA_AADHAAR,
        DocumentType.INCOME_CERTIFICATE.value: SCHEMA_INCOME_CERTIFICATE,
        DocumentType.CASTE_CERTIFICATE.value: SCHEMA_CASTE_CERTIFICATE,
        DocumentType.RESIDENCE_CERTIFICATE.value: SCHEMA_RESIDENCE_CERTIFICATE,
        DocumentType.DOMICILE_CERTIFICATE.value: SCHEMA_RESIDENCE_CERTIFICATE,
        DocumentType.BANK_PASSBOOK.value: SCHEMA_BANK_PASSBOOK,
        DocumentType.FEES_RECEIPT.value: SCHEMA_FEES_RECEIPT,
        DocumentType.PAN_CARD.value: SCHEMA_PAN_CARD,
        DocumentType.DEGREE_CERTIFICATE.value: SCHEMA_DEGREE_CERTIFICATE,
        DocumentType.BONAFIDE_CERTIFICATE.value: SCHEMA_BONAFIDE_CERTIFICATE,
        DocumentType.DISABILITY_CERTIFICATE.value: SCHEMA_DISABILITY_CERTIFICATE,
        DocumentType.RATION_CARD.value: SCHEMA_RATION_CARD,
    }

    # Normalized aliases to canonical DocumentType
    _ALIAS_MAP: Dict[str, str] = {
        "12TH_MARKSHEET": DocumentType.MARKSHEET_12TH.value,
        "MARKSHEET_12TH": DocumentType.MARKSHEET_12TH.value,
        "MARKSHEET_12": DocumentType.MARKSHEET_12TH.value,
        "12TH": DocumentType.MARKSHEET_12TH.value,
        "HSC": DocumentType.MARKSHEET_12TH.value,
        "INTERMEDIATE": DocumentType.MARKSHEET_12TH.value,

        "10TH_MARKSHEET": DocumentType.MARKSHEET_10TH.value,
        "MARKSHEET_10TH": DocumentType.MARKSHEET_10TH.value,
        "MARKSHEET_10": DocumentType.MARKSHEET_10TH.value,
        "10TH": DocumentType.MARKSHEET_10TH.value,
        "SSC": DocumentType.MARKSHEET_10TH.value,
        "MATRICULATION": DocumentType.MARKSHEET_10TH.value,

        "AADHAAR": DocumentType.AADHAAR_CARD.value,
        "AADHAAR_CARD": DocumentType.AADHAAR_CARD.value,
        "UIDAI": DocumentType.AADHAAR_CARD.value,

        "INCOME_CERTIFICATE": DocumentType.INCOME_CERTIFICATE.value,
        "INCOME": DocumentType.INCOME_CERTIFICATE.value,

        "CASTE_CERTIFICATE": DocumentType.CASTE_CERTIFICATE.value,
        "COMMUNITY_CERTIFICATE": DocumentType.CASTE_CERTIFICATE.value,
        "OBC_CERTIFICATE": DocumentType.CASTE_CERTIFICATE.value,
        "SC_CERTIFICATE": DocumentType.CASTE_CERTIFICATE.value,
        "ST_CERTIFICATE": DocumentType.CASTE_CERTIFICATE.value,

        "RESIDENCE_CERTIFICATE": DocumentType.RESIDENCE_CERTIFICATE.value,
        "DOMICILE_CERTIFICATE": DocumentType.RESIDENCE_CERTIFICATE.value,
        "NATIVITY_CERTIFICATE": DocumentType.RESIDENCE_CERTIFICATE.value,

        "BANK_PASSBOOK": DocumentType.BANK_PASSBOOK.value,
        "PASSBOOK": DocumentType.BANK_PASSBOOK.value,
        "BANK_STATEMENT": DocumentType.BANK_PASSBOOK.value,

        "FEES_RECEIPT": DocumentType.FEES_RECEIPT.value,
        "FEE_RECEIPT": DocumentType.FEES_RECEIPT.value,
        "TUITION_RECEIPT": DocumentType.FEES_RECEIPT.value,

        "PAN": DocumentType.PAN_CARD.value,
        "PAN_CARD": DocumentType.PAN_CARD.value,

        "DEGREE_CERTIFICATE": DocumentType.DEGREE_CERTIFICATE.value,
        "DEGREE": DocumentType.DEGREE_CERTIFICATE.value,
        "TRANSCRIPT": DocumentType.DEGREE_CERTIFICATE.value,
        "PROVISIONAL_CERTIFICATE": DocumentType.DEGREE_CERTIFICATE.value,

        "BONAFIDE_CERTIFICATE": DocumentType.BONAFIDE_CERTIFICATE.value,
        "BONAFIDE": DocumentType.BONAFIDE_CERTIFICATE.value,
        "STUDY_CERTIFICATE": DocumentType.BONAFIDE_CERTIFICATE.value,

        "DISABILITY_CERTIFICATE": DocumentType.DISABILITY_CERTIFICATE.value,
        "UDID": DocumentType.DISABILITY_CERTIFICATE.value,
        "UDID_CARD": DocumentType.DISABILITY_CERTIFICATE.value,
        "PWD_CERTIFICATE": DocumentType.DISABILITY_CERTIFICATE.value,

        "RATION_CARD": DocumentType.RATION_CARD.value,
        "FOOD_SECURITY_CARD": DocumentType.RATION_CARD.value,
        "BPL_CARD": DocumentType.RATION_CARD.value,
    }

    @classmethod
    def normalize_type(cls, raw_type: Optional[str]) -> str:
        """Map raw document type string or alias to canonical DocumentType string."""
        if not raw_type:
            return DocumentType.UNKNOWN.value
        clean = raw_type.strip().upper().replace(" ", "_").replace("-", "_")
        return cls._ALIAS_MAP.get(clean, clean)

    @classmethod
    def get_schema(cls, doc_type: str) -> Optional[DocumentSchema]:
        """Retrieve the DocumentSchema for a canonical or aliased document type."""
        canonical = cls.normalize_type(doc_type)
        return cls._REGISTRY.get(canonical)

    @classmethod
    def get_all_schemas(cls) -> Dict[str, DocumentSchema]:
        """Return dict of all registered schemas."""
        return dict(cls._REGISTRY)

    @classmethod
    def get_supported_types(cls) -> List[str]:
        """Return list of all canonical supported document type names."""
        return [
            DocumentType.MARKSHEET_12TH.value,
            DocumentType.MARKSHEET_10TH.value,
            DocumentType.AADHAAR_CARD.value,
            DocumentType.INCOME_CERTIFICATE.value,
            DocumentType.CASTE_CERTIFICATE.value,
            DocumentType.RESIDENCE_CERTIFICATE.value,
            DocumentType.BANK_PASSBOOK.value,
            DocumentType.FEES_RECEIPT.value,
            DocumentType.PAN_CARD.value,
            DocumentType.DEGREE_CERTIFICATE.value,
            DocumentType.BONAFIDE_CERTIFICATE.value,
            DocumentType.DISABILITY_CERTIFICATE.value,
            DocumentType.RATION_CARD.value,
        ]

    @classmethod
    def get_all_allowed_fields(cls) -> Set[str]:
        """Return set of all field names defined across all registered schemas."""
        fields = set()
        for schema in cls._REGISTRY.values():
            fields.update(schema.get_field_names())
        # Add legacy/profile fields
        fields.update({
            "full_name", "date_of_birth", "age", "gender", "state", "district",
            "annual_income", "annual_family_income", "occupation", "caste_category",
            "is_bpl", "aadhaar_number", "pan_number", "status"
        })
        return fields
