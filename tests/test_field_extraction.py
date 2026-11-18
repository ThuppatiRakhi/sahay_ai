"""Unit and integration tests for document field extraction, PII protection, and pipeline orchestration."""

from pathlib import Path
import pytest

from document_ai.document_processor import DocumentProcessor
from document_ai.extract_fields import DocumentFieldExtractor, ExtractedFieldsResult, PIIVault, mask_identifier


@pytest.fixture
def extractor():
    return DocumentFieldExtractor()


def test_aadhaar_extraction_default_masking(extractor):
    text = """
    GOVERNMENT OF INDIA
    Unique Identification Authority of India
    Mera Aadhaar, Meri Pehchan
    Name: Ramesh Kumar Sharma
    DOB: 12/05/1988
    Gender: MALE / पुरुष
    9999 8888 7777
    """
    res: ExtractedFieldsResult = extractor.extract_fields(text)
    assert res.document_type == "AADHAAR_CARD"
    assert "aadhaar_number" in res.fields
    aadhaar_field = res.fields["aadhaar_number"]

    # Security check: Complete 12-digit number MUST NOT be in value, display, or evidence
    assert aadhaar_field["value"] == "XXXX-XXXX-7777"
    assert aadhaar_field["masked_display"] == "XXXX-XXXX-7777"
    assert "9999 8888 7777" not in aadhaar_field["evidence"]
    assert "XXXX-XXXX-7777" in aadhaar_field["evidence"]
    assert "9999 8888 7777" not in res.summary

    # Authenticity disclaimer check
    assert "authenticity_disclaimer" in aadhaar_field
    assert res.authenticity_disclaimer is not None


def test_pan_extraction_default_masking(extractor):
    text = """
    INCOME TAX DEPARTMENT
    GOVT. OF INDIA
    Permanent Account Number Card
    ABCDE1234F
    DOB: 15/08/1990
    """
    res: ExtractedFieldsResult = extractor.extract_fields(text)
    assert res.document_type == "PAN_CARD"
    assert "pan_number" in res.fields
    pan_field = res.fields["pan_number"]

    # Security check: Full PAN MUST NOT be in value or evidence
    assert pan_field["value"] == "XXXXX1234X"
    assert pan_field["masked_display"] == "XXXXX1234X"
    assert "ABCDE1234F" not in pan_field["evidence"]
    assert "XXXXX1234X" in pan_field["evidence"]


def test_pii_vault_encryption():
    """Verify authorized encryption and decryption of sensitive identifiers."""
    vault = PIIVault()
    raw_aadhaar = "9999 8888 7777"

    encrypted = vault.encrypt(raw_aadhaar)
    assert encrypted != raw_aadhaar
    assert "9999" not in encrypted

    decrypted = vault.decrypt(encrypted)
    assert decrypted == raw_aadhaar


def test_income_certificate_lakh_parsing(extractor):
    text = """
    GOVERNMENT OF MAHARASHTRA
    OFFICE OF THE TAHSILDAR
    INCOME CERTIFICATE
    Certified annual family income is Rs. 2.5 Lakhs only.
    """
    res: ExtractedFieldsResult = extractor.extract_fields(text)
    assert res.document_type == "INCOME_CERTIFICATE"
    assert "annual_income" in res.fields
    inc_field = res.fields["annual_income"]

    assert inc_field["value"] == 250000.0
    assert inc_field["heuristic_confidence"] >= 0.85
    assert "2.5 Lakhs" in inc_field["evidence"]


def test_multiformat_dob_extraction(extractor):
    text_iso = "DOB: 1994-08-25 Citizen Record"
    res_iso = extractor.extract_fields(text_iso)
    assert "date_of_birth" in res_iso.fields
    assert res_iso.fields["date_of_birth"]["value"] == "1994-08-25"

    text_dash = "DOB: 25-08-1994 Citizen Record"
    res_dash = extractor.extract_fields(text_dash)
    assert "date_of_birth" in res_dash.fields
    assert res_dash.fields["date_of_birth"]["value"] == "25-08-1994"


def test_needs_user_confirmation(extractor):
    # Incomplete Aadhaar card with missing DOB
    text_incomplete = "GOVERNMENT OF INDIA Mera Aadhaar 9999 8888 7777"
    res = extractor.extract_fields(text_incomplete)
    assert "date_of_birth" in res.needs_user_confirmation


def test_document_processor_end_to_end_real():
    """Test full document processor on real synthetic sample without crashing."""
    sample_img = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if not sample_img.exists():
        pytest.skip("Synthetic sample not found.")

    processor = DocumentProcessor(enforce_quality_gate=True)
    res = processor.process(str(sample_img))

    assert res.success is True
    assert res.document_type == "AADHAAR_CARD"
    assert "aadhaar_number" in res.fields
    assert res.fields["aadhaar_number"]["value"] == "XXXX-XXXX-7777"


def test_document_processor_corrupted_image(tmp_path):
    """Test document processor handles corrupted file safely without crashing."""
    corrupt_file = tmp_path / "broken.png"
    corrupt_file.write_bytes(b"NOT_AN_IMAGE_RANDOM_NOISE")

    processor = DocumentProcessor(enforce_quality_gate=True)
    res = processor.process(str(corrupt_file))

    assert res.success is False
    assert res.document_type in ("REJECTED_QUALITY", "REJECTED_MALFORMED")
    assert res.error_message is not None
