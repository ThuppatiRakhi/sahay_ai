"""Document AI Package for SahayAI.

Provides computer vision, OCR extraction, image quality assessment,
privacy-preserving PII encryption/masking, and document field extraction.
"""

from .document_processor import DocumentProcessResult, DocumentProcessor
from .extract_fields import DocumentFieldExtractor, ExtractedFieldsResult, PIIVault, mask_identifier
from .image_quality import ImageQualityAssessor, QualityAssessmentResult
from .ocr import OCREngine, OCRResult, mask_sensitive_patterns

__all__ = [
    "DocumentProcessResult",
    "DocumentProcessor",
    "DocumentFieldExtractor",
    "ExtractedFieldsResult",
    "ImageQualityAssessor",
    "OCREngine",
    "OCRResult",
    "PIIVault",
    "mask_identifier",
    "mask_sensitive_patterns",
]
