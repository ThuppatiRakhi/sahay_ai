"""Automatic Document Classification Module for SahayAI Intelligent OCR.

Identifies Indian welfare and academic document types using document content,
multilingual keywords, structural layout markers, and numerical patterns,
independent of client-supplied filenames or pre-selected categories.
"""

from dataclasses import dataclass
import logging
import re
from typing import Dict, List, Optional, Tuple

from .schemas import DocumentType, DocumentTypeRegistry

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Outcome of document classification."""
    document_type: str
    confidence: float
    is_low_confidence: bool
    matched_signals: List[str]
    candidate_scores: Dict[str, float]
    suggested_alternatives: List[str]


class DocumentClassifier:
    """Content- and layout-aware document classifier for Indian welfare and academic documents."""

    # Confidence threshold below which manual user confirmation of document type is recommended
    CONFIDENCE_THRESHOLD = 0.45
    HIGH_CONFIDENCE_THRESHOLD = 0.70

    # High-signal pattern rules per document type
    # Each entry: (regex_or_keyword_pattern, weight, is_primary)
    _SIGNALS = {
        DocumentType.MARKSHEET_10TH.value: [
            (r"(?:SECONDARY\s+SCHOOL\s+CERTIFICATE|SECONDARY\s+SCHOOL\s+EXAMINATION|HIGH\s+SCHOOL\s+CERTIFICATE|HIGH\s+SCHOOL\s+EXAMINATION|HIGH\s+SCHOOL|CLASS\s*(?:X\b|10\b)|10TH\s+(?:STANDARD|CLASS|PASS|EXAM)|MATRICULATION|MATRIC\b|AISSE\b|S\.?\s*S\.?\s*C\.?|(?:\b|\bPASSED)SSC(?:EXAMINATION|\b))", 3.5),
            (r"(?:BOARD\s+OF\s+SECONDARY\s+EDUCATION|STATE\s+BOARD\s+OF\s+SECONDARY|SECONDARY\s+EDUCATION\s+BOARD|CENTRAL\s+BOARD\s+OF\s+SECONDARY\s+EDUCATION|CBSE|ICSE|HEADMASTER|HEADMISTRESS|SECONDARY\s+SCHOOL)", 2.5),
            (r"(?:MEMORANDUM\s*OF\s*MARKS|STATEMENT\s+OF\s+MARKS|MARKSHEET|GRADE\s+SHEET|REPORT\s+CARD|ACADEMIC\s+RECORD)", 1.5),
            (r"(?:CUMULATIVE\s+GRADE\s+POINT\s+AVERAGE|CGPA|GPA|MARKS\s+OBTAINED|MAXIMUM\s+MARKS|TOTAL\s+MARKS|GRAND\s+TOTAL)", 1.5),
            (r"(?:ROLL\s*(?:NO\.?|NUMBER)|HALL\s*TICKET|REGISTRATION\s*(?:NO\.?|NUMBER)|REGD\s*NUMBER)", 1.2),
            (r"(?:RESULT\s*:\s*PASS|PASSED|QUALIFIED|GRADE\s*:\s*[A-D][1-2]?|[A-D]\s*GRADE)", 1.0),
        ],
        DocumentType.MARKSHEET_12TH.value: [
            (r"(?:HIGHER\s+SECONDARY|SENIOR\s+SECONDARY|SENIOR\s+SCHOOL|HSC\b|INTERMED[I1L]ATE|10\s*\+\s*2|CLASS\s*(?:XII|12\b)|12TH\s+(?:STANDARD|CLASS|PASS|EXAM)|PRE[- ]UNIVERSITY|PUC\b|AISSCE\b|JUNIOR\s+COLLEGE)", 3.5),
            (r"(?:BOARD\s*OF\s*INTERMEDIATE|HIGHER\s+SECONDARY\s+BOARD|COUNCIL\s+FOR\s+THE\s+INDIAN\s+SCHOOL|CISCE|ISC\b)", 2.5),
            (r"(?:MEMORANDUM\s*OF\s*MARKS|STATEMENT\s+OF\s+MARKS|MARKSHEET|GRADE\s+SHEET|ACADEMIC\s+RECORD)", 1.5),
            (r"(?:SUB\s*CODE|SUBJECT|THEORY|PRACTICAL|MAX\s*MARKS|OBT\s*MARKS|TOTAL\s*MARKS|GRAND\s*TOTAL)", 1.2),
            (r"(?:ROLL\s*(?:NO\.?|NUMBER)|HALL\s*TICKET|REGISTRATION\s*(?:NO\.?|NUMBER)|REGD\s*NUMBER)", 1.2),
            (r"(?:RESULT\s*:\s*PASS|PASSED|QUALIFIED|GRADE\s*:\s*[A-D][1-2]?|[A-D]\s*GRADE)", 1.0),
        ],
        DocumentType.DEGREE_CERTIFICATE.value: [
            (r"\b(?:DEGREE\s+CERTIFICATE|PROVISIONAL\s+CERTIFICATE|CONVOCATION|UNDER\s+THE\s+SEAL\s+OF\s+THE\s+UNIVERSITY|ADMITTED\s+TO\s+THE\s+DEGREE)\b", 3.5),
            (r"\b(?:BACHELOR\s+OF|MASTER\s+OF|B\.?\s*TECH|B\.?\s*E|B\.?\s*SC|B\.?\s*COM|B\.?\s*A|M\.?\s*TECH|M\.?\s*SC|M\.?\s*B\.?\s*A|M\.?\s*C\.?\s*A|DIPLOMA\s+IN)\b", 3.0),
            (r"\b(?:UNIVERSITY|INSTITUTE\s+OF\s+TECHNOLOGY|FACULTY\s+OF|DEPARTMENT\s+OF)\b", 1.8),
            (r"\b(?:CUMULATIVE\s+GRADE|CREDITS\s+COMPLETED|SEMESTER|DIVISION|FIRST\s+CLASS\s+WITH\s+DISTINCTION)\b", 1.5),
        ],
        DocumentType.BONAFIDE_CERTIFICATE.value: [
            (r"\b(?:BONAFIDE\s+CERTIFICATE|STUDY\s+CERTIFICATE|CONDUCT\s+CERTIFICATE|STUDY\s+AND\s+CONDUCT)\b", 3.5),
            (r"\b(?:IS\s+A\s+BONAFIDE\s+STUDENT|STUDYING\s+IN|BONAFIDE\s+STUDENT|DURING\s+THE\s+ACADEMIC\s+YEAR)\b", 3.0),
            (r"\b(?:HEAD\s+OF\s+THE\s+INSTITUTION|PRINCIPAL|DIRECTOR|DEAN)\b", 1.5),
        ],
        DocumentType.AADHAAR_CARD.value: [
            (r"\b(UNIQUE\s+IDENTIFICATION\s+AUTHORITY\s+OF\s+INDIA|UIDAI|MERA\s+AADHAAR|AADHAAR)\b", 3.5),
            (r"\b(GOVERNMENT\s+OF\s+INDIA|भारत\s+सरकार)\b", 1.0),
            (r"\b(DOB\s*:\s*\d{2}[-/]\d{2}[-/]\d{4}|YEAR\s+OF\s+BIRTH|जन्म\s+तिथि)\b", 1.5),
            (r"\b(GENDER|MALE|FEMALE|TRANSGENDER|पुरुष|महिला)\b", 1.2),
            (r"\b(\d{4}\s+\d{4}\s+\d{4})\b", 2.0),
            (r"\b(VID\s*:\s*\d{16})\b", 1.5),
        ],
        DocumentType.INCOME_CERTIFICATE.value: [
            (r"\b(INCOME\s+CERTIFICATE|आय\s+प्रमाण\s+पत्र|CERTIFICATE\s+OF\s+INCOME)\b", 3.5),
            (r"\b(ANNUAL\s+(?:FAMILY\s+)?INCOME|TOTAL\s+FAMILY\s+INCOME|वार्षिक\s+आय)\b", 2.5),
            (r"\b(OFFICE\s+OF\s+THE\s+TAHSILDAR|TAHSILDAR|MANDAL\s+REVENUE\s+OFFICER|TALUK|REVENUE\s+DEPARTMENT|SUB[- ]DIVISIONAL\s+MAGISTRATE)\b", 2.0),
            (r"\b(?:RS\.?|INR|₹)\s*[0-9,]+\b", 1.5),
            (r"\b(CERTIFIED\s+THAT\s+THE\s+ANNUAL|VALID\s+FOR\s+THE\s+YEAR|FINANCIAL\s+YEAR)\b", 1.5),
        ],
        DocumentType.CASTE_CERTIFICATE.value: [
            (r"\b(CASTE\s+CERTIFICATE|COMMUNITY\s+CERTIFICATE|जाति\s+प्रमाण\s+पत्र|CERTIFICATE\s+OF\s+CASTE)\b", 3.5),
            (r"\b(SCHEDULED\s+CASTE|SCHEDULED\s+TRIBE|OTHER\s+BACKWARD\s+CLASS|OBC|SC\b|ST\b|SEBC|EWS)\b", 2.5),
            (r"\b(BELONGS\s+TO\s+THE|COMMUNITY\s+SPECIFIED|RECOGNIZED\s+AS\s+A|CONSTITUTION\s+ORDER)\b", 2.0),
            (r"\b(TAHSILDAR|REVENUE\s+DIVISIONAL\s+OFFICER|DISTRICT\s+MAGISTRATE|SUB[- ]DIVISIONAL\s+OFFICER)\b", 1.5),
        ],
        DocumentType.RESIDENCE_CERTIFICATE.value: [
            (r"\b(RESIDENCE\s+CERTIFICATE|DOMICILE\s+CERTIFICATE|NATIVITY\s+CERTIFICATE|निवास\s+प्रमाण\s+पत्र|स्थानीय\s+निवास)\b", 3.5),
            (r"\b(ORDINARILY\s+RESIDES|PERMANENT\s+RESIDENT|BONAFIDE\s+RESIDENT\s+OF|RESIDING\s+AT)\b", 2.5),
            (r"\b(VILLAGE|MANDAL|TEHSIL|DISTRICT|STATE\s+OF)\b", 1.2),
            (r"\b(TAHSILDAR|REVENUE\s+OFFICER|EXECUTIVE\s+MAGISTRATE|SUB[- ]DIVISIONAL\s+MAGISTRATE)\b", 1.5),
        ],
        DocumentType.BANK_PASSBOOK.value: [
            (r"\b(PASSBOOK|SAVINGS\s+BANK|BANK\s+ACCOUNT|STATEMENT\s+OF\s+ACCOUNT)\b", 3.0),
            (r"\b(IFSC|IFSC\s*CODE|MICR|MICR\s*CODE)\b", 2.5),
            (r"\b(ACCOUNT\s*(?:NO|NUMBER)|A/C\s*NO|CUSTOMER\s*ID|CIF\s*NO)\b", 2.5),
            (r"\b(STATE\s+BANK\s+OF\s+INDIA|SBI|PUNJAB\s+NATIONAL\s+BANK|BANK\s+OF\s+BARODA|CANARA\s+BANK|HDFC\s+BANK|ICICI\s+BANK|AXIS\s+BANK|UNION\s+BANK|INDIAN\s+BANK)\b", 2.0),
            (r"\b(BRANCH\s*(?:NAME|CODE)?|SAVINGS\s+ACCOUNT|BALANCE)\b", 1.5),
        ],
        DocumentType.FEES_RECEIPT.value: [
            (r"\b(FEE\s+RECEIPT|FEES\s+RECEIPT|TUITION\s+FEE|PAYMENT\s+RECEIPT|RECEIPT\s+VOUCHER)\b", 3.5),
            (r"\b(RECEIPT\s*(?:NO|NUMBER)|VOUCHER\s*NO|TRANSACTION\s*(?:ID|NO))\b", 2.0),
            (r"\b(ACADEMIC\s+YEAR|SEMESTER|TERM\s+FEE|ADMISSION\s+FEE|EXAM\s+FEE)\b", 2.0),
            (r"\b(AMOUNT\s+PAID|TOTAL\s+PAID|PAID\s+AMOUNT|PAYMENT\s+MODE|CASH|ONLINE|DEMAND\s+DRAFT)\b", 1.8),
            (r"\b(COLLEGE|INSTITUTE|UNIVERSITY|POLYTECHNIC|SCHOOL)\b", 1.2),
        ],
        DocumentType.PAN_CARD.value: [
            (r"\b(INCOME\s+TAX\s+DEPARTMENT|PERMANENT\s+ACCOUNT\s+NUMBER|PAN\s+CARD)\b", 3.5),
            (r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", 3.0),
            (r"\b(GOVT\.\s+OF\s+INDIA|FATHER'?S\s+NAME)\b", 1.2),
        ],
        DocumentType.DISABILITY_CERTIFICATE.value: [
            (r"(?:DISABILITY\s+CERTIFICATE|UNIQUE\s+DISABILITY\s+ID|UDID|PERSONS\s+WITH\s+DISABILITIES)", 3.5),
            (r"(?:PERCENTAGE\s+OF\s+DISABILITY|DEGREE\s+OF\s+DISABILITY|DISABILITY\s+PERCENTAGE)", 2.8),
            (r"(?:MEDICAL\s+BOARD|MEDICAL\s+AUTHORITY|CHIEF\s+MEDICAL\s+OFFICER|CIVIL\s+SURGEON)", 2.0),
            (r"(?:LOCOMOTOR|VISUAL\s+IMPAIRMENT|HEARING\s+IMPAIRMENT|MENTAL\s+ILLNESS|BLINDNESS|AUTISM)", 1.8),
        ],
        DocumentType.RATION_CARD.value: [
            (r"(?:FOOD\s+SECURITY\s+CARD|RATION\s+CARD|CIVIL\s+SUPPLIES|CONSUMER\s+AFFAIRS)", 3.5),
            (r"(?:FAIR\s+PRICE\s+SHOP|FPS|BPL\s+CARD|ANTYODAYA|AAY\b|WHITE\s+CARD|FAMILY\s+HEAD)", 2.5),
            (r"(?:NUMBER\s+OF\s+UNITS|LPG\s+CONNECTION|SUBSIDIZED\s+COMMODITIES)", 1.5),
        ],
    }

    # Disambiguation penalties
    _PENALTIES = {
        DocumentType.MARKSHEET_10TH.value: [
            (r"(?:HIGHER\s+SECONDARY|SENIOR\s+SECONDARY|CLASS\s*(?:XII|12\b)|12TH\b|HSC\b|INTERMEDIATE|10\s*\+\s*2|PRE[- ]UNIVERSITY|PUC\b|AISSCE\b|DEGREE\s+CERTIFICATE|BACHELOR)", 4.5),
        ],
        DocumentType.MARKSHEET_12TH.value: [
            (r"(?:SECONDARY\s+SCHOOL\s+CERTIFICATE|HIGH\s+SCHOOL|CLASS\s*(?:X\b|10\b)|10TH\s+(?:STANDARD|CLASS)|MATRICULATION|S\.?\s*S\.?\s*C\.?|(?:\b|\bPASSED)SSC(?:EXAMINATION|\b))", 5.0),
            (r"(?:DEGREE\s+CERTIFICATE|BACHELOR\s+OF|BONAFIDE\s+CERTIFICATE)", 4.0),
        ],
        DocumentType.AADHAAR_CARD.value: [
            (r"\b(MARKSHEET|INCOME\s+CERTIFICATE|PASSBOOK|FEES\s+RECEIPT|PERMANENT\s+ACCOUNT\s+NUMBER)\b", 2.0),
        ],
        DocumentType.BANK_PASSBOOK.value: [
            (r"\b(MARKSHEET|INCOME\s+CERTIFICATE|CASTE\s+CERTIFICATE|AADHAAR)\b", 2.5),
        ]
    }

    def classify(
        self,
        text: str,
        hint_category: Optional[str] = None,
        hint_type: Optional[str] = None,
    ) -> ClassificationResult:
        """Classify document text into one of the supported DocumentTypes.

        Args:
            text: Raw extracted OCR text.
            hint_category: Optional client-selected category (e.g. 'ACADEMIC').
            hint_type: Optional client-selected document type (e.g. 'marksheet_12th').

        Returns:
            ClassificationResult containing detected type, confidence, and candidate scores.
        """
        if not text or not text.strip():
            return ClassificationResult(
                document_type=DocumentType.UNKNOWN.value,
                confidence=0.0,
                is_low_confidence=True,
                matched_signals=[],
                candidate_scores={},
                suggested_alternatives=[],
            )

        upper_text = text.upper()
        scores: Dict[str, float] = {}
        matched_signals_per_type: Dict[str, List[str]] = {}

        # 1. Compute positive signal scores
        for doc_type, signal_rules in self._SIGNALS.items():
            type_score = 0.0
            type_signals = []
            for pattern, weight in signal_rules:
                matches = re.findall(pattern, upper_text, re.IGNORECASE)
                if matches:
                    type_score += weight * min(len(matches), 3)  # capped frequency weighting
                    # Record snippet
                    first_match = matches[0]
                    if isinstance(first_match, tuple):
                        first_match = first_match[0]
                    type_signals.append(str(first_match).strip())

            # 2. Apply negative penalties
            if doc_type in self._PENALTIES:
                has_12th_keywords = bool(re.search(r"(?:HIGHER\s+SECONDARY|SENIOR\s+SECONDARY|INTERMEDIATE|10\s*\+\s*2|CLASS\s*(?:XII|12\b)|12TH\b|HSC\b)", upper_text))
                for pen_pattern, pen_weight in self._PENALTIES[doc_type]:
                    if doc_type == DocumentType.MARKSHEET_12TH.value and has_12th_keywords:
                        continue
                    if re.search(pen_pattern, upper_text, re.IGNORECASE):
                        type_score = max(0.0, type_score - pen_weight)

            scores[doc_type] = type_score
            matched_signals_per_type[doc_type] = type_signals

        # 3. Soft tiebreaker with user-provided hints if scores are close
        if hint_type:
            norm_hint = DocumentTypeRegistry.normalize_type(hint_type)
            if norm_hint in scores:
                scores[norm_hint] += 0.8  # Slight boost if user explicitly selected this
        elif hint_category:
            norm_cat = hint_category.strip().upper()
            for doc_t, schema in DocumentTypeRegistry.get_all_schemas().items():
                if schema.category.upper() == norm_cat and doc_t in scores:
                    scores[doc_t] += 0.4

        # 4. Rank candidates
        sorted_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_type, top_raw_score = sorted_candidates[0] if sorted_candidates else (DocumentType.UNKNOWN.value, 0.0)

        # Convert raw score into a normalized confidence (0.0 - 1.0)
        # Typically scores >= 5.0 denote very high confidence
        normalized_conf = min(1.0, round(top_raw_score / 6.5, 2))

        # Check for ambiguity: if top and second score are close
        alternatives = []
        if len(sorted_candidates) > 1 and sorted_candidates[1][1] > 2.0:
            second_type, second_score = sorted_candidates[1]
            if (top_raw_score - second_score) < 1.5:
                # Ambiguous classification
                alternatives.append(second_type)
                # Slightly attenuate confidence due to competition
                normalized_conf = max(0.35, round(normalized_conf * 0.85, 2))

        is_low = (normalized_conf < self.CONFIDENCE_THRESHOLD) or (top_raw_score < 2.0)
        detected_type = top_type if not is_low else DocumentType.UNKNOWN.value

        # If detected_type is UNKNOWN but top candidate had some score, suggest top candidate
        if is_low and top_raw_score > 0.0 and top_type != DocumentType.UNKNOWN.value:
            alternatives.insert(0, top_type)

        logger.info(
            "Document classified: %s (conf=%.2f, raw=%.1f, low_conf=%s) | top signals: %s",
            detected_type,
            normalized_conf,
            top_raw_score,
            is_low,
            matched_signals_per_type.get(top_type, [])[:3],
        )

        return ClassificationResult(
            document_type=detected_type,
            confidence=normalized_conf,
            is_low_confidence=is_low,
            matched_signals=matched_signals_per_type.get(top_type, []),
            candidate_scores={k: round(v, 2) for k, v in sorted_candidates if v > 0},
            suggested_alternatives=alternatives,
        )
