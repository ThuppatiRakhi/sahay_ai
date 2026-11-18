"""Unit and integration tests for OCR engine, scanned PDF rendering, and PII masking."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw
import pytest

from document_ai.ocr import OCREngine, OCRResult, mask_sensitive_patterns


def test_ocr_engine_init():
    engine = OCREngine(language="eng+hin")
    assert engine.language == "eng+hin"
    assert engine.engine_preference == "auto"


def test_ocr_backend_status():
    """Verify OCR engine inspects real availability rather than assuming success."""
    engine = OCREngine()
    status = engine.get_backend_status()
    assert isinstance(status, dict)
    assert "tesseract_available" in status
    assert "rapidocr_available" in status
    assert "pdf_renderer_available" in status
    assert status["pdf_renderer_available"] is True


def test_ocr_file_not_found():
    engine = OCREngine()
    with pytest.raises(FileNotFoundError):
        engine.extract_text("non_existent_file.pdf")


def test_mask_sensitive_patterns_aadhaar():
    text = "Citizen Aadhaar number is 1234 5678 9012 recorded on file."
    masked = mask_sensitive_patterns(text)
    assert "1234 5678 9012" not in masked
    assert "XXXX-XXXX-9012" in masked


def test_mask_sensitive_patterns_pan():
    text = "Citizen PAN is ABCDE1234F verified by authority."
    masked = mask_sensitive_patterns(text)
    assert "ABCDE1234F" not in masked
    assert "XXXXX1234X" in masked


def test_real_image_ocr_synthetic_aadhaar():
    """Execute real OCR on synthetic Aadhaar specimen."""
    sample_path = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if not sample_path.exists():
        pytest.skip("Synthetic Aadhaar specimen not found.")

    engine = OCREngine()
    if not engine.is_image_ocr_available():
        pytest.skip("No OCR backend installed on host system.")

    result = engine.extract_text(str(sample_path))
    assert result.is_success is True
    assert result.confidence > 0.50
    assert "Aadhaar" in result.text or "Ramesh" in result.text or "9999" in result.text


def test_real_image_ocr_synthetic_pan():
    """Execute real OCR on synthetic PAN specimen."""
    sample_path = Path("data/sample_documents/sample_synthetic_pan.png")
    if not sample_path.exists():
        pytest.skip("Synthetic PAN specimen not found.")

    engine = OCREngine()
    if not engine.is_image_ocr_available():
        pytest.skip("No OCR backend installed on host system.")

    result = engine.extract_text(str(sample_path))
    assert result.is_success is True
    assert result.confidence > 0.50
    assert "ABCDE1234F" in result.text or "PATEL" in result.text


def test_digital_pdf_extraction():
    """Execute real digital PDF extraction."""
    sample_path = Path("data/sample_documents/sample_synthetic_income_cert.pdf")
    if not sample_path.exists():
        pytest.skip("Synthetic income cert PDF not found.")

    engine = OCREngine()
    result = engine.extract_text(str(sample_path))
    assert result.is_success is True
    assert result.is_pdf is True
    assert "INCOME CERTIFICATE" in result.text
    assert "1,50,000" in result.text


def test_scanned_pdf_rendering_and_ocr(tmp_path):
    """Execute real OCR on a rasterized scanned PDF with no text stream."""
    img = Image.new("RGB", (500, 300), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((40, 50), "SCANNED GOVERNMENT DOCUMENT", fill=(0, 0, 0))
    d.text((40, 100), "Applicant: Sunita Patil", fill=(0, 0, 0))
    d.text((40, 150), "DOB: 15/08/1990", fill=(0, 0, 0))

    scanned_pdf_file = tmp_path / "scanned_test.pdf"
    img.save(str(scanned_pdf_file), format="PDF")

    engine = OCREngine()
    result = engine.extract_text(str(scanned_pdf_file))

    assert result.is_success is True
    assert result.is_pdf is True
    assert result.engine_name == "pdfium_scanned_ocr"
    assert "Sunita" in result.text or "Patil" in result.text or "1990" in result.text


def test_corrupted_pdf_handling(tmp_path):
    """Ensure malformed PDF files return a clean failure result instead of an unhandled crash."""
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4 CORRUPTED GARBAGE DATA WITH NO CATALOG")

    engine = OCREngine()
    result = engine.extract_text(str(corrupt_pdf))

    assert result.is_success is False
    assert "error" in result.metadata
    assert "PDF" in result.metadata["error"]


def test_no_backend_installed_error(tmp_path):
    """Ensure structured error message is returned when no OCR backend is available."""
    test_img = tmp_path / "test.png"
    Image.new("RGB", (200, 200), color=(255, 255, 255)).save(test_img)

    engine = OCREngine()
    with patch.object(engine, "_try_rapidocr", return_value=None):
        with patch.object(engine, "_try_tesseract", return_value=None):
            with patch.object(engine, "_try_paddleocr", return_value=None):
                result = engine.extract_text(str(test_img))
                assert result.is_success is False
                assert result.engine_name == "none"
                assert "No functional OCR engine backend" in result.metadata.get("error", "")
