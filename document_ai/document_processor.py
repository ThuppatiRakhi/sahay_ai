"""Document processing pipeline for SahayAI.

Coordinates image quality verification, optical character recognition,
intelligent document classification, and privacy-preserving field extraction
into a unified pipeline with robust handling of corrupt or malformed files.
"""

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extract_fields import DocumentFieldExtractor, ExtractedFieldsResult
from .image_quality import ImageQualityAssessor, QualityAssessmentResult
from .ocr import OCREngine, OCRResult

logger = logging.getLogger(__name__)


@dataclass
class DocumentProcessResult:
    """Output contract for end-to-end document processing."""
    success: bool
    document_type: str
    quality: Dict[str, Any]
    ocr_confidence: float
    fields: Dict[str, Any]
    summary: str
    needs_user_confirmation: list
    missing_fields: List[str] = field(default_factory=list)
    unreadable_fields: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    classification_confidence: float = 1.0
    is_low_confidence: bool = False
    suggested_alternatives: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return asdict(self)


class DocumentProcessor:
    """Coordinates image quality gates, OCR, document classification, and field extraction."""

    def __init__(
        self,
        quality_assessor: Optional[ImageQualityAssessor] = None,
        ocr_engine: Optional[OCREngine] = None,
        field_extractor: Optional[DocumentFieldExtractor] = None,
        enforce_quality_gate: bool = True,
    ):
        """Initialize pipeline components.

        Args:
            quality_assessor: Optional ImageQualityAssessor instance.
            ocr_engine: Optional OCREngine instance.
            field_extractor: Optional DocumentFieldExtractor instance.
            enforce_quality_gate: Reject images failing blur/glare/resolution gates.
        """
        self.quality_assessor = quality_assessor or ImageQualityAssessor()
        self.ocr_engine = ocr_engine or OCREngine()
        self.field_extractor = field_extractor or DocumentFieldExtractor()
        self.enforce_quality_gate = enforce_quality_gate

    def process(
        self,
        document_path: str,
        document_type_hint: Optional[str] = None,
        override_type: Optional[str] = None,
    ) -> DocumentProcessResult:
        """Execute quality checks, OCR, classification, and field extraction on a document.

        Args:
            document_path: Path to the image or PDF document.
            document_type_hint: Optional client-provided document type hint.
            override_type: Explicit user selection overriding automatic classification.

        Returns:
            DocumentProcessResult summarizing verification status and extracted fields.
        """
        path = Path(document_path)
        if not path.exists():
            return DocumentProcessResult(
                success=False,
                document_type="UNKNOWN",
                quality={},
                ocr_confidence=0.0,
                fields={},
                summary="Processing aborted: file not found.",
                needs_user_confirmation=[],
                error_message=f"File not found: {document_path}",
            )

        quality_report: Dict[str, Any] = {}
        is_pdf = path.suffix.lower() == ".pdf"

        # 1. Quality Check (for image formats)
        if not is_pdf:
            try:
                quality_res: QualityAssessmentResult = self.quality_assessor.evaluate_file(str(path))
                quality_report = quality_res.to_dict()

                if self.enforce_quality_gate and not quality_res.is_acceptable:
                    issues_summary = "; ".join(quality_res.issues)
                    logger.warning("Document rejected by quality gate: %s", issues_summary)
                    return DocumentProcessResult(
                        success=False,
                        document_type="REJECTED_QUALITY",
                        quality=quality_report,
                        ocr_confidence=0.0,
                        fields={},
                        summary=f"Quality check rejected: {issues_summary}",
                        needs_user_confirmation=[],
                        error_message=f"Document quality gate failed: {issues_summary}",
                    )
            except Exception as q_err:
                logger.error("Quality assessment crashed on %s: %s", path.name, q_err)
                return DocumentProcessResult(
                    success=False,
                    document_type="REJECTED_MALFORMED",
                    quality={"error": str(q_err)},
                    ocr_confidence=0.0,
                    fields={},
                    summary="Document evaluation failed due to corrupted file structure.",
                    needs_user_confirmation=[],
                    error_message=f"Corrupted or unreadable image file: {str(q_err)}",
                )

        # 2. OCR Text Extraction
        try:
            ocr_res: OCRResult = self.ocr_engine.extract_text(str(path))
            if not ocr_res.is_success:
                return DocumentProcessResult(
                    success=False,
                    document_type="OCR_UNAVAILABLE",
                    quality=quality_report,
                    ocr_confidence=0.0,
                    fields={},
                    summary="OCR backend unavailable or failed.",
                    needs_user_confirmation=[],
                    error_message=ocr_res.metadata.get("error", "OCR extraction failed."),
                )
        except Exception as exc:
            logger.error("OCR execution error for %s: %s", path.name, exc)
            return DocumentProcessResult(
                success=False,
                document_type="OCR_ERROR",
                quality=quality_report,
                ocr_confidence=0.0,
                fields={},
                summary="OCR extraction failed.",
                needs_user_confirmation=[],
                error_message=str(exc),
            )

        # 3. Content-Aware Field Extraction tailored to document schema
        extraction: ExtractedFieldsResult = self.field_extractor.extract_fields(
            ocr_res.text,
            document_type=document_type_hint,
            override_type=override_type,
        )

        logger.info(
            "Document processed: %s | Identified: %s (conf: %.2f, low_conf: %s) | Fields: %d | Missing: %s",
            path.name,
            extraction.document_type,
            extraction.classification_confidence,
            extraction.is_low_confidence,
            len(extraction.fields),
            extraction.missing_fields,
        )

        return DocumentProcessResult(
            success=True,
            document_type=extraction.document_type,
            quality=quality_report,
            ocr_confidence=ocr_res.confidence,
            fields=extraction.fields,
            summary=extraction.summary,
            needs_user_confirmation=extraction.needs_user_confirmation,
            missing_fields=extraction.missing_fields,
            unreadable_fields=extraction.unreadable_fields,
            validation_warnings=extraction.validation_warnings,
            classification_confidence=extraction.classification_confidence,
            is_low_confidence=extraction.is_low_confidence,
            suggested_alternatives=extraction.suggested_alternatives,
            error_message=None,
        )
