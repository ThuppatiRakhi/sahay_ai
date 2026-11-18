"""Image quality assessment module for SahayAI using OpenCV and Pillow.

Checks image blur (Laplacian variance), brightness, glare (specular reflections),
and minimum resolution thresholds prior to OCR processing with robust error handling
for corrupted or unsupported files.
"""

from dataclasses import asdict, dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QualityAssessmentResult:
    """Detailed evaluation result of an image quality inspection."""
    is_acceptable: bool
    blur_score: float
    brightness_score: float
    glare_ratio: float
    width: int
    height: int
    issues: List[str]
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return asdict(self)


class ImageQualityAssessor:
    """Evaluates image quality metrics using OpenCV for sharpness, brightness, glare, and resolution."""

    def __init__(
        self,
        min_width: int = 400,
        min_height: int = 400,
        blur_threshold: float = 100.0,
        min_brightness: float = 40.0,
        max_brightness: float = 230.0,
        glare_threshold: float = 0.08,
    ):
        """Initialize image quality thresholds.

        Args:
            min_width: Minimum width in pixels.
            min_height: Minimum height in pixels.
            blur_threshold: Minimum Laplacian variance for blur/sharpness.
            min_brightness: Minimum mean pixel brightness (0-255).
            max_brightness: Maximum mean pixel brightness (0-255).
            glare_threshold: Maximum acceptable fraction of overexposed pixels (>= 252).
        """
        self.min_width = min_width
        self.min_height = min_height
        self.blur_threshold = blur_threshold
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.glare_threshold = glare_threshold

    def evaluate_file(self, file_path: str) -> QualityAssessmentResult:
        """Inspect image quality on a local file safely.

        Args:
            file_path: Path to the image file.

        Returns:
            QualityAssessmentResult detailing all quality metric evaluations.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {file_path}")

        try:
            import cv2
            import numpy as np
            from PIL import Image

            img = None
            # Attempt 1: OpenCV native decoding
            try:
                img = cv2.imread(str(path))
            except Exception as cv_err:
                logger.debug("OpenCV imread failed on %s: %s", path.name, cv_err)

            # Attempt 2: Pillow decoding fallback (handles exotic metadata, non-ASCII paths)
            if img is None:
                try:
                    with Image.open(path) as pil_img:
                        pil_img.load()  # Force decode to catch corruption early
                        rgb_img = pil_img.convert("RGB")
                        img = cv2.cvtColor(np.array(rgb_img), cv2.COLOR_RGB2BGR)
                except Exception as pil_err:
                    logger.warning("Pillow could not open image %s: %s", path.name, pil_err)

            # If both decoders failed, image is corrupt or unsupported format
            if img is None or img.size == 0:
                return QualityAssessmentResult(
                    is_acceptable=False,
                    blur_score=0.0,
                    brightness_score=0.0,
                    glare_ratio=0.0,
                    width=0,
                    height=0,
                    issues=["Corrupted or unsupported image file: unable to decode image pixels."],
                    recommendations=["Please upload a valid, undamaged image file (JPEG, PNG, or WEBP)."],
                )

            height, width = img.shape[:2]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 1. Blur check via Laplacian variance
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            blur_score = float(laplacian.var())

            # 2. Brightness check via mean luminance
            brightness_score = float(np.mean(gray))

            # 3. Glare check: proportion of specular flash flare pixels (>= 252)
            glare_pixels = int(np.sum(gray >= 252))
            total_pixels = gray.size
            glare_ratio = float(glare_pixels / total_pixels) if total_pixels > 0 else 0.0

        except Exception as exc:
            logger.error("Unexpected error assessing image %s: %s", path.name, exc)
            return QualityAssessmentResult(
                is_acceptable=False,
                blur_score=0.0,
                brightness_score=0.0,
                glare_ratio=0.0,
                width=0,
                height=0,
                issues=[f"Image assessment failed: {str(exc)}"],
                recommendations=["Please verify that the uploaded file is a valid image."],
            )

        issues: List[str] = []
        recommendations: List[str] = []

        # Check resolution
        if width < self.min_width or height < self.min_height:
            issues.append(f"Resolution too low ({width}x{height}px). Minimum required is {self.min_width}x{self.min_height}px.")
            recommendations.append("Upload a higher-resolution photo or scan of the document.")

        # Check blur
        if blur_score < self.blur_threshold:
            issues.append(f"Image is blurry (sharpness score {blur_score:.1f} < threshold {self.blur_threshold}).")
            recommendations.append("Hold camera steady and ensure document is in focus.")

        # Check lighting / underexposure
        if brightness_score < self.min_brightness:
            issues.append(f"Image is too dark (brightness {brightness_score:.1f} < {self.min_brightness}).")
            recommendations.append("Retake in better ambient daylight or turn on indoor lighting.")
        elif brightness_score > self.max_brightness:
            issues.append(f"Image is overexposed (brightness {brightness_score:.1f} > {self.max_brightness}).")
            recommendations.append("Reduce camera exposure or turn off direct lamp glare.")

        # Check glare
        if glare_ratio > self.glare_threshold:
            issues.append(f"Severe glare detected ({glare_ratio * 100:.1f}% overexposed area).")
            recommendations.append("Avoid camera flash reflections on plastic-laminated cards.")

        is_acceptable = len(issues) == 0

        return QualityAssessmentResult(
            is_acceptable=is_acceptable,
            blur_score=blur_score,
            brightness_score=brightness_score,
            glare_ratio=glare_ratio,
            width=width,
            height=height,
            issues=issues,
            recommendations=recommendations,
        )
