"""Optical Character Recognition (OCR) module for SahayAI.

Extracts text from both image (JPG, PNG) and PDF documents. Supports pluggable
OCR engines (Tesseract on Windows/Linux, RapidOCR ONNX, PaddleOCR) and native PDF
digital text extraction with automatic fallback to image OCR for scanned PDFs.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard installation paths for Tesseract on Windows
WINDOWS_TESSERACT_LOCATIONS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


def mask_sensitive_patterns(text: str) -> str:
    """Mask Aadhaar (12-digit) and PAN (10-char) numbers for privacy-safe logging.

    Args:
        text: Input string containing possible identifiers.

    Returns:
        Redacted string with masked identifiers.
    """
    if not text:
        return ""
    # Mask Aadhaar numbers: 1234 5678 9012 -> XXXX-XXXX-9012 or 123456789012 -> XXXXXXXX9012
    masked = re.sub(
        r"\b\d{4}\s\d{4}\s(\d{4})\b",
        r"XXXX-XXXX-\1",
        text,
    )
    masked = re.sub(
        r"\b\d{8}(\d{4})\b",
        r"XXXXXXXX\1",
        masked,
    )
    # Mask PAN numbers: ABCDE1234F -> XXXXX1234X
    masked = re.sub(
        r"\b[A-Z]{5}([0-9]{4})[A-Z]{1}\b",
        r"XXXXX\1X",
        masked,
    )
    return masked


@dataclass
class OCRResult:
    """Encapsulates raw text and extraction metrics from OCR."""
    text: str
    confidence: float
    engine_name: str
    is_pdf: bool
    page_count: int
    metadata: Dict[str, Any]
    is_success: bool = True

    def get_masked_text_for_logging(self) -> str:
        """Return text with sensitive identifiers masked."""
        return mask_sensitive_patterns(self.text)


class OCREngine:
    """Pluggable OCR and document text extraction engine for images and PDFs."""

    def __init__(
        self,
        language: str = "eng+hin",
        engine_preference: str = "auto",
        tesseract_cmd: Optional[str] = None,
    ):
        """Initialize OCR engine.

        Args:
            language: Languages to recognize (e.g. 'eng+hin' or 'en').
            engine_preference: 'auto', 'rapidocr', 'tesseract', or 'paddleocr'.
            tesseract_cmd: Optional path to tesseract binary.
        """
        self.language = language
        self.engine_preference = engine_preference
        self.tesseract_cmd = tesseract_cmd or os.environ.get("TESSERACT_CMD")
        self._resolved_tesseract_path: Optional[str] = None
        self._configure_engines()

    def _find_tesseract_binary(self) -> Optional[str]:
        """Locate Tesseract executable on Windows or POSIX systems."""
        # 1. Explicitly configured path
        if self.tesseract_cmd and Path(self.tesseract_cmd).is_file():
            return str(Path(self.tesseract_cmd).resolve())

        # 2. In system PATH
        path_which = shutil.which("tesseract")
        if path_which:
            return path_which

        # 3. Known standard Windows installation directories
        for loc in WINDOWS_TESSERACT_LOCATIONS:
            if Path(loc).is_file():
                return loc

        return None

    def _configure_engines(self) -> None:
        """Configure detected OCR engine paths."""
        self._resolved_tesseract_path = self._find_tesseract_binary()
        if self._resolved_tesseract_path:
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = self._resolved_tesseract_path
                logger.info("Configured Tesseract binary at: %s", self._resolved_tesseract_path)
            except ImportError:
                pass

    def get_backend_status(self) -> Dict[str, Any]:
        """Check availability of each supported OCR engine.

        Returns:
            Dictionary indicating availability and path details for each backend.
        """
        status: Dict[str, Any] = {
            "tesseract_available": False,
            "tesseract_path": self._resolved_tesseract_path,
            "rapidocr_available": False,
            "paddleocr_available": False,
            "pdf_renderer_available": False,
        }

        # Check Tesseract
        if self._resolved_tesseract_path and Path(self._resolved_tesseract_path).exists():
            status["tesseract_available"] = True

        # Check RapidOCR
        try:
            from rapidocr_onnxruntime import RapidOCR
            status["rapidocr_available"] = True
        except ImportError:
            status["rapidocr_available"] = False

        # Check PaddleOCR
        try:
            from paddleocr import PaddleOCR
            status["paddleocr_available"] = True
        except ImportError:
            status["paddleocr_available"] = False

        # Check pypdfium2 PDF renderer
        try:
            import pypdfium2
            status["pdf_renderer_available"] = True
        except ImportError:
            status["pdf_renderer_available"] = False

        return status

    def is_image_ocr_available(self) -> bool:
        """Check whether at least one operational image OCR engine is ready."""
        status = self.get_backend_status()
        return status["rapidocr_available"] or status["tesseract_available"] or status["paddleocr_available"]

    def extract_text(self, document_path: str) -> OCRResult:
        """Extract text from an image or PDF document.

        Args:
            document_path: Path to the target document.

        Returns:
            OCRResult containing extracted text and confidence scores.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found at: {document_path}")

        # Route by extension
        if path.suffix.lower() == ".pdf":
            return self._extract_from_pdf(path)
        else:
            return self._extract_from_image_file(path)

    def _extract_from_pdf(self, path: Path) -> OCRResult:
        """Extract text from PDF pages, falling back to scanned page OCR if needed."""
        extracted_pages: List[str] = []
        total_pages = 0

        # Attempt digital text extraction first
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            total_pages = len(reader.pages)

            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(page_text.strip())
        except Exception as exc:
            logger.error("Failed to read PDF structure from %s: %s", path.name, exc)
            return OCRResult(
                text="",
                confidence=0.0,
                engine_name="pypdf",
                is_pdf=True,
                page_count=0,
                metadata={"error": f"Invalid or corrupted PDF file: {str(exc)}"},
                is_success=False,
            )

        digital_text = "\n\n".join(extracted_pages).strip()

        # If digital text exists, return it immediately
        if digital_text and len(digital_text) >= 15:
            logger.info("Extracted digital text from PDF %s (%d pages)", path.name, total_pages)
            return OCRResult(
                text=digital_text,
                confidence=0.95,
                engine_name="pypdf_digital",
                is_pdf=True,
                page_count=total_pages,
                metadata={"pages": total_pages, "mode": "digital_text_layer"},
                is_success=True,
            )

        # Scanned PDF detected: Render pages to images and run image OCR
        logger.info("PDF %s contains no digital text layer. Engaging scanned PDF image OCR pipeline.", path.name)
        return self._extract_from_scanned_pdf(path, total_pages)

    def _extract_from_scanned_pdf(self, path: Path, total_pages: int) -> OCRResult:
        """Render scanned PDF pages to images and process with OCR engine."""
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(path))
            total_pages = len(pdf)

            scanned_texts: List[str] = []
            page_confidences: List[float] = []

            for i in range(total_pages):
                page = pdf[i]
                pil_image = page.render(scale=2).to_pil()
                img_res = self._extract_from_pil_image(pil_image)
                if img_res.text.strip():
                    scanned_texts.append(img_res.text.strip())
                    page_confidences.append(img_res.confidence)

            avg_conf = float(sum(page_confidences) / len(page_confidences)) if page_confidences else 0.0
            full_text = "\n\n".join(scanned_texts)

            return OCRResult(
                text=full_text,
                confidence=avg_conf,
                engine_name="pdfium_scanned_ocr",
                is_pdf=True,
                page_count=total_pages,
                metadata={"mode": "rasterized_scanned_pdf", "pages": total_pages},
                is_success=True,
            )
        except Exception as exc:
            logger.error("Scanned PDF OCR failed for %s: %s", path.name, exc)
            return OCRResult(
                text="",
                confidence=0.0,
                engine_name="scanned_pdf_ocr",
                is_pdf=True,
                page_count=total_pages,
                metadata={"error": f"Scanned PDF rendering failed: {str(exc)}"},
                is_success=False,
            )

    def _extract_from_image_file(self, path: Path) -> OCRResult:
        """Extract text from an image file using available OCR engines."""
        from PIL import Image

        try:
            with Image.open(path) as img:
                return self._extract_from_pil_image(img.convert("RGB"))
        except Exception as exc:
            logger.error("Failed to read image %s for OCR: %s", path.name, exc)
            return OCRResult(
                text="",
                confidence=0.0,
                engine_name="none",
                is_pdf=False,
                page_count=1,
                metadata={"error": f"Image file corrupted or unreadable: {str(exc)}"},
                is_success=False,
            )

    def _extract_from_pil_image(self, pil_image) -> OCRResult:
        """Perform OCR on a PIL image object using RapidOCR, Tesseract, or PaddleOCR."""
        # 1. Try RapidOCR (high speed, accurate, pure ONNX, zero external exe needed)
        if self.engine_preference in ("auto", "rapidocr"):
            res = self._try_rapidocr(pil_image)
            if res is not None:
                return res

        # 2. Try Tesseract
        if self.engine_preference in ("auto", "tesseract"):
            res = self._try_tesseract(pil_image)
            if res is not None:
                return res

        # 3. Try PaddleOCR
        if self.engine_preference in ("auto", "paddleocr"):
            res = self._try_paddleocr(pil_image)
            if res is not None:
                return res

        # No backend operational
        error_msg = (
            "No functional OCR engine backend is available. "
            "Please install Tesseract OCR from https://github.com/UB-Mannheim/tesseract/wiki "
            "and set TESSERACT_CMD, or install rapidocr-onnxruntime."
        )
        logger.error(error_msg)
        return OCRResult(
            text="",
            confidence=0.0,
            engine_name="none",
            is_pdf=False,
            page_count=1,
            metadata={"error": error_msg},
            is_success=False,
        )

    def _try_rapidocr(self, pil_image) -> Optional[OCRResult]:
        """Execute OCR using RapidOCR (ONNX)."""
        try:
            from rapidocr_onnxruntime import RapidOCR
            import numpy as np

            engine = RapidOCR()
            img_np = np.array(pil_image)
            result, _ = engine(img_np)

            if not result:
                return OCRResult(
                    text="",
                    confidence=0.0,
                    engine_name="rapidocr",
                    is_pdf=False,
                    page_count=1,
                    metadata={"lines_detected": 0},
                    is_success=True,
                )

            lines: List[str] = []
            confidences: List[float] = []

            for item in result:
                # item structure: [box_coordinates, text, confidence]
                text = str(item[1]).strip()
                conf = float(item[2])
                if text:
                    lines.append(text)
                    confidences.append(conf)

            avg_conf = float(sum(confidences) / len(confidences)) if confidences else 0.0
            return OCRResult(
                text="\n".join(lines),
                confidence=avg_conf,
                engine_name="rapidocr",
                is_pdf=False,
                page_count=1,
                metadata={"lines_detected": len(lines)},
                is_success=True,
            )
        except (ImportError, Exception) as exc:
            logger.debug("RapidOCR execution skipped or failed: %s", exc)
            return None

    def _try_tesseract(self, pil_image) -> Optional[OCRResult]:
        """Execute OCR using Tesseract if binary is available."""
        if not self._resolved_tesseract_path:
            return None

        try:
            import pytesseract

            text = pytesseract.image_to_string(pil_image, lang=self.language)
            data = pytesseract.image_to_data(pil_image, lang=self.language, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data.get("conf", []) if str(c).isdigit() and int(c) >= 0]
            avg_confidence = float(sum(confidences) / len(confidences)) if confidences else 0.0

            return OCRResult(
                text=text.strip(),
                confidence=avg_confidence,
                engine_name="tesseract",
                is_pdf=False,
                page_count=1,
                metadata={"total_tokens": len(confidences), "binary_path": self._resolved_tesseract_path},
                is_success=True,
            )
        except Exception as exc:
            logger.warning("Tesseract execution failed: %s", exc)
            return None

    def _try_paddleocr(self, pil_image) -> Optional[OCRResult]:
        """Execute OCR using PaddleOCR if installed."""
        try:
            from paddleocr import PaddleOCR
            import numpy as np

            ocr = PaddleOCR(use_angle_cls=True, lang="en")
            img_np = np.array(pil_image)
            result = ocr.ocr(img_np, cls=True)

            text_lines: List[str] = []
            confidences: List[float] = []

            if result and result[0]:
                for line in result[0]:
                    text = line[1][0]
                    conf = float(line[1][1])
                    text_lines.append(text)
                    confidences.append(conf)

            avg_conf = float(sum(confidences) / len(confidences)) if confidences else 0.0
            return OCRResult(
                text="\n".join(text_lines),
                confidence=avg_conf,
                engine_name="paddleocr",
                is_pdf=False,
                page_count=1,
                metadata={"lines_detected": len(text_lines)},
                is_success=True,
            )
        except (ImportError, Exception):
            return None
