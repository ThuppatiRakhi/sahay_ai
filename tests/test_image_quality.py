"""Unit tests for OpenCV image quality assessment, corrupt file safety, and threshold checks."""

from pathlib import Path
import tempfile
import numpy as np
import pytest

from document_ai.image_quality import ImageQualityAssessor, QualityAssessmentResult


def test_quality_file_not_found():
    assessor = ImageQualityAssessor()
    with pytest.raises(FileNotFoundError):
        assessor.evaluate_file("non_existent_file.jpg")


def test_quality_on_synthetic_sample():
    sample_path = Path("data/sample_documents/sample_synthetic_aadhaar.png")
    if not sample_path.exists():
        pytest.skip("Synthetic sample image not found.")

    assessor = ImageQualityAssessor(min_width=400, min_height=300)
    result = assessor.evaluate_file(str(sample_path))

    assert isinstance(result, QualityAssessmentResult)
    assert result.width == 800
    assert result.height == 500
    assert result.is_acceptable is True
    assert result.glare_ratio < 0.20
    assert len(result.issues) == 0


def test_quality_low_resolution(tmp_path):
    from PIL import Image

    small_img_path = tmp_path / "tiny.png"
    Image.new("RGB", (150, 150), color=(200, 200, 200)).save(small_img_path)

    assessor = ImageQualityAssessor(min_width=400, min_height=400)
    result = assessor.evaluate_file(str(small_img_path))

    assert result.is_acceptable is False
    assert any("Resolution too low" in issue for issue in result.issues)
    assert len(result.recommendations) > 0


def test_quality_glare_detection(tmp_path):
    from PIL import Image

    glare_img_path = tmp_path / "glare.png"
    Image.new("RGB", (500, 500), color=(255, 255, 255)).save(glare_img_path)

    assessor = ImageQualityAssessor(min_width=400, min_height=400, glare_threshold=0.10)
    result = assessor.evaluate_file(str(glare_img_path))

    assert result.is_acceptable is False
    assert any("glare" in issue.lower() for issue in result.issues)


def test_quality_corrupted_image_handling(tmp_path):
    """Ensure malformed or corrupted image files do not crash the assessment."""
    corrupt_file = tmp_path / "corrupt.png"
    corrupt_file.write_bytes(b"RANDOM_CORRUPT_BYTES_NOT_AN_IMAGE_HEADER")

    assessor = ImageQualityAssessor()
    result = assessor.evaluate_file(str(corrupt_file))

    assert isinstance(result, QualityAssessmentResult)
    assert result.is_acceptable is False
    assert any("corrupt" in issue.lower() for issue in result.issues)
    assert len(result.recommendations) > 0
