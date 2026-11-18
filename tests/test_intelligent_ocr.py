"""Automated tests for SahayAI Document-Type-Specific Intelligent OCR.

Verifies:
1. Automatic classification accuracy across all 9 supported document types.
2. 12th marksheet extraction contains academic schema fields (subjects, total, %, roll no,
   student name) and NEVER fabricates or leaks generic DATE OF BIRTH or GENDER.
3. 10th marksheet extraction retains DOB if printed.
4. Marks validation warning checks (sum mismatch & percentage cross-validation).
5. Low confidence classification fallback and reclassification workflow.
6. API endpoint integration: upload, review, reclassify, and confirm.
"""

import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from document_ai.classifier import DocumentClassifier
from document_ai.document_processor import DocumentProcessor
from document_ai.extract_fields import DocumentFieldExtractor
from document_ai.schemas import DocumentType, DocumentTypeRegistry
from api.main import app

client = TestClient(app)

SAMPLE_DIR = Path("data/sample_documents")


class TestIntelligentClassification:
    """Tests for content- and layout-aware document classification."""

    def test_classifier_all_canonical_types(self):
        classifier = DocumentClassifier()

        samples = {
            "CBSE HIGHER SECONDARY EXAMINATION 10+2 CLASS XII MARKSHEET ROLL NO 12345": DocumentType.MARKSHEET_12TH.value,
            "SECONDARY SCHOOL EXAMINATION CLASS X STATEMENT OF MARKS AISSE CBSE ROLL NO 45678": DocumentType.MARKSHEET_10TH.value,
            "GOVERNMENT OF INDIA UNIQUE IDENTIFICATION AUTHORITY OF INDIA UIDAI MERA AADHAAR 4920 1829 3849": DocumentType.AADHAAR_CARD.value,
            "GOVERNMENT OF MAHARASHTRA OFFICE OF TAHSILDAR INCOME CERTIFICATE ANNUAL FAMILY INCOME RS 150000": DocumentType.INCOME_CERTIFICATE.value,
            "OFFICE OF TAHSILDAR CASTE CERTIFICATE SCHEDULED CASTE SC KUNBI COMMUNITY": DocumentType.CASTE_CERTIFICATE.value,
            "RESIDENCE CERTIFICATE DOMICILE CERTIFICATE ORDINARILY RESIDES AT BANGALORE TAHSILDAR": DocumentType.RESIDENCE_CERTIFICATE.value,
            "STATE BANK OF INDIA SAVINGS BANK PASSBOOK ACCOUNT NO 38491029481 IFSC SBIN0001234": DocumentType.BANK_PASSBOOK.value,
            "DELHI TECHNOLOGICAL UNIVERSITY TUITION FEE RECEIPT RECEIPT NO DTU/2024 PAID RS 75000": DocumentType.FEES_RECEIPT.value,
            "INCOME TAX DEPARTMENT GOVT OF INDIA PERMANENT ACCOUNT NUMBER PAN CARD ABCDE1234F": DocumentType.PAN_CARD.value,
        }

        for text, expected_type in samples.items():
            res = classifier.classify(text)
            assert res.document_type == expected_type, f"Expected {expected_type} for text '{text}', got {res.document_type}"
            assert res.confidence >= 0.50

    def test_low_confidence_classification(self):
        classifier = DocumentClassifier()
        ambiguous_text = "This is a random scanned note with some numbers 12345 and text."
        res = classifier.classify(ambiguous_text)
        assert res.is_low_confidence is True
        assert res.confidence < DocumentClassifier.CONFIDENCE_THRESHOLD


class TestDocumentAwareExtraction:
    """Tests for document-type-specific schema field extraction."""

    def test_12th_marksheet_no_dob_no_gender(self):
        """CRITICAL: Ensure 12th marksheet NEVER extracts generic DOB or Gender."""
        doc_path = SAMPLE_DIR / "sample_12th_marksheet.pdf"
        assert doc_path.exists(), f"Missing {doc_path}"

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(str(doc_path))

        assert result.success is True
        assert result.document_type == DocumentType.MARKSHEET_12TH.value
        assert result.classification_confidence >= 0.80

        # Assert generic identity fields are NOT present
        assert "date_of_birth" not in result.fields, "12th marksheet must NOT extract generic date_of_birth"
        assert "gender" not in result.fields, "12th marksheet must NOT extract generic gender"

        # Assert academic schema fields ARE present
        fields = result.fields
        assert "student_name" in fields
        assert fields["student_name"]["value"] == "Aarav Sharma"
        assert "roll_number" in fields
        assert fields["roll_number"]["value"] == "12654321"
        assert "board_name" in fields
        assert "CBSE" in fields["board_name"]["value"] or "CENTRAL" in fields["board_name"]["value"]
        assert "examination_year" in fields
        assert fields["examination_year"]["value"] == 2024
        assert "total_obtained_marks" in fields
        assert float(fields["total_obtained_marks"]["value"]) == 445.0
        assert "percentage" in fields
        assert float(fields["percentage"]["value"]) == 89.0
        assert "result_status" in fields
        assert fields["result_status"]["value"] == "PASS"

        # Assert subject marks table
        assert "subject_marks" in fields
        subjects = fields["subject_marks"]["value"]
        assert isinstance(subjects, list)
        assert len(subjects) == 5
        sub_names = [s["subject_name"].lower() for s in subjects]
        assert any("english" in s for s in sub_names)
        assert any("math" in s for s in sub_names)
        assert any("physics" in s for s in sub_names)

    def test_10th_marksheet_extracts_dob(self):
        """10th marksheet may legitimately serve as proof of birth date in India."""
        doc_path = SAMPLE_DIR / "sample_10th_marksheet.pdf"
        assert doc_path.exists()

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(str(doc_path))

        assert result.success is True
        assert result.document_type == DocumentType.MARKSHEET_10TH.value
        assert "date_of_birth" in result.fields
        assert result.fields["date_of_birth"]["value"] == "15-08-2006"
        assert "gender" not in result.fields, "10th marksheet must NOT extract gender"
        assert "subject_marks" in result.fields
        assert len(result.fields["subject_marks"]["value"]) == 5

    def test_caste_certificate_extraction(self):
        doc_path = SAMPLE_DIR / "sample_caste_certificate.pdf"
        assert doc_path.exists()

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(str(doc_path))

        assert result.success is True
        assert result.document_type == DocumentType.CASTE_CERTIFICATE.value
        fields = result.fields
        assert fields["category"]["value"] == "OBC"
        assert fields["certificate_number"]["value"] == "MH/CASTE/2023/88921"
        assert "Magistrate" in fields["issuing_authority"]["value"]
        assert fields["applicant_name"]["value"] == "Vikram Patil"

    def test_residence_certificate_extraction(self):
        doc_path = SAMPLE_DIR / "sample_residence_certificate.pdf"
        assert doc_path.exists()

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(str(doc_path))

        assert result.success is True
        assert result.document_type == DocumentType.RESIDENCE_CERTIFICATE.value
        fields = result.fields
        assert fields["certificate_number"]["value"] == "KA/DOM/2023/11029"
        assert "GREENWOOD" in fields["residential_address"]["value"].upper()
        assert fields["applicant_name"]["value"] == "Priya Nair"

    def test_bank_passbook_extraction(self):
        doc_path = SAMPLE_DIR / "sample_bank_passbook.png"
        assert doc_path.exists()

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(str(doc_path))

        assert result.success is True
        assert result.document_type == DocumentType.BANK_PASSBOOK.value
        fields = result.fields
        assert fields["ifsc_code"]["value"] == "SBIN0001234"
        assert "account_number" in fields
        assert fields["account_number"]["value"].startswith("XXXXXX")
        assert "State Bank" in fields["bank_name"]["value"]
        assert "Deshmukh" in fields["account_holder_name"]["value"]

    def test_fee_receipt_extraction(self):
        doc_path = SAMPLE_DIR / "sample_fee_receipt.pdf"
        assert doc_path.exists()

        processor = DocumentProcessor(enforce_quality_gate=False)
        result = processor.process(str(doc_path))

        assert result.success is True
        assert result.document_type == DocumentType.FEES_RECEIPT.value
        fields = result.fields
        assert float(fields["fee_amount"]["value"]) == 75000.0
        assert fields["receipt_number"]["value"] == "DTU/2024/REC-48210"
        assert fields["student_name"]["value"] == "Aditya Gupta"

    def test_marksheet_math_validation_warning(self):
        """Test that validation detects discrepancy between subject marks sum and reported total."""
        extractor = DocumentFieldExtractor()
        mismatched_text = """
CENTRAL BOARD OF SECONDARY EDUCATION
CLASS XII EXAMINATION
ROLL NO: 99887766
NAME: TEST STUDENT
SUB CODE  SUBJECT NAME  MAX MARKS  OBTAINED MARKS
041       MATHEMATICS   100        080
042       PHYSICS       100        070
TOTAL MARKS: 200 / 200
PERCENTAGE: 99.00%
RESULT: PASS
"""
        res = extractor.extract_fields(mismatched_text, document_type=DocumentType.MARKSHEET_12TH.value)
        # Sum is 150, but reported total is 200
        assert len(res.validation_warnings) > 0
        assert any("does not match subject sum" in w for w in res.validation_warnings)


class TestDocumentAPIWorkflow:
    """End-to-end API tests for upload, review, reclassification, and confirmation."""

    @pytest.fixture
    def test_client(self):
        c = TestClient(app)
        return c

    def test_api_upload_marksheet_12th_guest(self, test_client):
        # 1. Initialize guest session
        guest_res = test_client.post("/auth/guest")
        assert guest_res.status_code == 200
        csrf_token = guest_res.json()["csrf_token"]

        headers = {
            "Origin": "http://localhost:5500",
            "X-CSRF-Token": csrf_token,
        }

        doc_path = SAMPLE_DIR / "sample_12th_marksheet.pdf"
        with open(doc_path, "rb") as f:
            resp = test_client.post(
                "/documents/upload",
                files={"file": ("sample_12th_marksheet.pdf", f, "application/pdf")},
                data={"document_category": "OTHER", "document_type": "other"},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["document_type"] == DocumentType.MARKSHEET_12TH.value
        assert data["detected_document_type"] == DocumentType.MARKSHEET_12TH.value
        assert "subject_marks" in data["extracted_fields"]
        assert "date_of_birth" not in data["extracted_fields"]
        assert "gender" not in data["extracted_fields"]
        assert data["classification_confidence"] >= 0.80

    def test_api_review_and_confirm_flow(self, test_client):
        # 1. Signup citizen
        email = f"ocr_test_{os.urandom(4).hex()}@example.com"
        signup_res = test_client.post(
            "/auth/signup",
            json={"email": email, "password": "Password@123"},
        )
        assert signup_res.status_code == 200

        csrf_res = test_client.get("/auth/csrf-token")
        csrf_token = csrf_res.json()["csrf_token"]
        headers = {"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token}

        # 2. Upload document as registered user
        doc_path = SAMPLE_DIR / "sample_12th_marksheet.pdf"
        with open(doc_path, "rb") as f:
            up_resp = test_client.post(
                "/documents/upload",
                files={"file": ("sample_12th_marksheet.pdf", f, "application/pdf")},
                headers=headers,
            )
        assert up_resp.status_code == 200
        doc_id = up_resp.json()["document_id"]

        # 3. GET review
        rev_resp = test_client.get(f"/documents/{doc_id}/review")
        assert rev_resp.status_code == 200
        rev_data = rev_resp.json()
        assert rev_data["success"] is True
        assert rev_data["document_type"] == DocumentType.MARKSHEET_12TH.value
        assert "review_fields" in rev_data
        assert "extracted_fields" in rev_data

        # 4. Confirm document fields
        confirm_payload = {
            "confirmations": [
                {"field_name": "student_name", "confirmed_value": "Aarav Sharma", "confirmed": True},
                {"field_name": "roll_number", "confirmed_value": "12654321", "confirmed": True},
                {"field_name": "board_name", "confirmed_value": "CBSE", "confirmed": True},
                {"field_name": "percentage", "confirmed_value": 89.0, "confirmed": True},
            ]
        }
        conf_resp = test_client.post(
            f"/documents/{doc_id}/confirm",
            json=confirm_payload,
            headers=headers,
        )
        assert conf_resp.status_code == 200
        assert conf_resp.json()["success"] is True
        assert len(conf_resp.json()["confirmed_fields"]) == 4

    def test_api_reclassify_flow(self, test_client):
        """Tests citizen-driven reclassification of a vault-stored document."""
        # 1. Signup citizen
        email = f"reclass_test_{os.urandom(4).hex()}@example.com"
        signup_res = test_client.post(
            "/auth/signup",
            json={"email": email, "password": "Password@123"},
        )
        assert signup_res.status_code == 200

        csrf_res = test_client.get("/auth/csrf-token")
        csrf_token = csrf_res.json()["csrf_token"]
        headers = {"Origin": "http://localhost:5500", "X-CSRF-Token": csrf_token}

        # 2. Upload document
        doc_path = SAMPLE_DIR / "sample_12th_marksheet.pdf"
        with open(doc_path, "rb") as f:
            up_resp = test_client.post(
                "/documents/upload",
                files={"file": ("sample_12th_marksheet.pdf", f, "application/pdf")},
                headers=headers,
            )
        assert up_resp.status_code == 200
        doc_id = up_resp.json()["document_id"]
        assert up_resp.json()["document_type"] == DocumentType.MARKSHEET_12TH.value

        # 3. Citizen reclassifies as MARKSHEET_10TH
        reclass_resp = test_client.post(
            f"/documents/{doc_id}/reclassify",
            json={"document_type": "MARKSHEET_10TH"},
            headers=headers,
        )
        assert reclass_resp.status_code == 200
        reclass_data = reclass_resp.json()
        assert reclass_data["success"] is True
        assert reclass_data["document_type"] == DocumentType.MARKSHEET_10TH.value
        assert "review_fields" in reclass_data

        # 4. Verify review endpoint reflects new classification
        rev_resp = test_client.get(f"/documents/{doc_id}/review")
        assert rev_resp.status_code == 200
        assert rev_resp.json()["document_type"] == DocumentType.MARKSHEET_10TH.value

