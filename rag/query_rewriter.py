"""
rag/query_rewriter.py — Multilingual Query Rewriting Subsystem for SahayAI RAG.

Provides deterministic multilingual scheme entity recognition, domain terminology
normalization, and query enrichment across English, Hindi, and Telugu without
inventing policy conditions or requiring external API calls.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .config import (
    AMBIGUOUS_FOLLOWUP_MESSAGE,
    SUPPORTED_SCHEMES,
    UNSUPPORTED_SCHEME_MESSAGE,
)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RewrittenQuery:
    """Represents the output of the query rewriting pipeline."""

    original_query: str
    rewritten_query: str
    detected_scheme_id: Optional[str] = None
    detected_language: str = "en"
    expanded_terms: List[str] = field(default_factory=list)
    is_rewritten: bool = False
    unsupported_scheme: Optional[str] = None
    is_ambiguous: bool = False
    clarification_message: Optional[str] = None
    resolved_from_context: bool = False
    referenced_scheme_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert rewritten query metadata to dictionary."""
        return {
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "detected_scheme_id": self.detected_scheme_id,
            "detected_language": self.detected_language,
            "expanded_terms": self.expanded_terms,
            "is_rewritten": self.is_rewritten,
            "unsupported_scheme": self.unsupported_scheme,
            "is_ambiguous": self.is_ambiguous,
            "clarification_message": self.clarification_message,
            "resolved_from_context": self.resolved_from_context,
            "referenced_scheme_ids": self.referenced_scheme_ids,
        }


# ---------------------------------------------------------------------------
# Canonical Knowledge Maps (Deterministic, Rule-Based)
# ---------------------------------------------------------------------------

# 1. Scheme Entity Recognition Patterns (English, Hindi, Telugu)
SCHEME_ENTITY_PATTERNS: Dict[str, Dict[str, Any]] = {
    "SCHEME_EDU_001_PM_USP_CSSS": {
        "canonical_name": "PM-USP Central Sector Scheme of Scholarship (CSSS)",
        "canonical_terms": ["PM-USP CSSS", "Central Sector Scheme of Scholarship for College and University Students"],
        "patterns": [
            # English
            r"\bpm[-\s]?usp\b",
            r"\bcsss\b",
            r"\bcentral\s+sector\s+(?:scheme|scholarship)\b",
            r"\bpm\s+uchchatar\s+shiksha\s+protsahan\b",
            # Hindi
            r"पीएम[-\s]?यूएसपी",
            r"सीएसएसएस",
            r"केंद्रीय\s+क्षेत्र\s+छात्रवृत्ति",
            r"सेंट्रल\s+सेक्टर\s+(?:स्कीम|छात्रवृत्ति)",
            r"उच्चतर\s+शिक्षा\s+प्रोत्साहन",
            # Telugu
            r"పీఎం[-\s]?యూఎస్‌పీ",
            r"సిఎస్ఎస్ఎస్",
            r"సెంట్రల్\s+సెక్టార్\s+స్కాలర్‌షిప్",
        ],
    },
    "SCHEME_EDU_002_AICTE_PRAGATI": {
        "canonical_name": "AICTE Pragati Scholarship Scheme for Girl Students",
        "canonical_terms": ["AICTE Pragati Scholarship Scheme for Girl Students", "Pragati technical scholarship for girls"],
        "patterns": [
            # English
            r"\bpragati\b",
            r"\baicte\s+pragati\b",
            # Hindi
            r"प्रगति",
            r"एआईसीटीई\s+प्रगति",
            # Telugu
            r"ప్రగతి",
            r"ఏఐసీటీఈ\s+ప్రగతి",
        ],
    },
    "SCHEME_EDU_003_AICTE_SAKSHAM": {
        "canonical_name": "AICTE Saksham Scholarship Scheme for Specially-Abled Students",
        "canonical_terms": ["AICTE Saksham Scholarship Scheme for Specially-Abled Students", "Saksham scholarship disability"],
        "patterns": [
            # English
            r"\bsaksham\b",
            r"\baicte\s+saksham\b",
            # Hindi
            r"सक्षम",
            r"एआईसीटीई\s+सक्षम",
            # Telugu
            r"సక్షమ్",
            r"సక్షం",
            r"ఏఐసీటీఈ\s+సక్షమ్",
            r"ఏఐసీటీఈ\s+సక్షం",
        ],
    },
    "SCHEME_EDU_004_AICTE_SWANATH": {
        "canonical_name": "AICTE Swanath Scholarship Scheme for Students",
        "canonical_terms": ["AICTE Swanath Scholarship Scheme for Students", "Swanath scholarship for orphan students"],
        "patterns": [
            # English
            r"\bswanath\b",
            r"\baicte\s+swanath\b",
            # Hindi
            r"स्वानाथ",
            r"एआईसीटीई\s+स्वानाथ",
            # Telugu
            r"స్వానాథ్",
            r"ఏఐసీటీఈ\s+స్వానాథ్",
        ],
    },
    "SCHEME_EDU_005_TOP_CLASS_SC": {
        "canonical_name": "Top Class Education Scheme for SC Students",
        "canonical_terms": ["Top Class Education Scheme for SC Students", "Top Class Scholarship for SC Students"],
        "patterns": [
            # English
            r"\btop\s+class\s+sc\b",
            r"\btop\s+class\s+education\s+scheme\b",
            r"\btop\s+class\s+education\b",
            r"\btop\s+class\s+scholarship\b",
            r"\btop\s+class\b",
            r"\bsc\s+top\s+class\b",
            # Hindi
            r"टॉप\s+क्लास\s+एससी",
            r"टॉप\s+क्लास\s+स्कॉलरशिप",
            r"टॉप\s+क्लास\s+छात्रवृत्ति",
            r"अनुसूचित\s+जाति\s+टॉप\s+क्लास",
            # Telugu
            r"టాప్\s+క్లాస్\s+ఎస్సీ",
            r"టాప్\s+క్లాస్\s+స్కాలర్‌షిప్",
            r"టాప్\s+క్లాస్",
        ],
    },
    "SCHEME_AGRI_001_PM_KISAN": {
        "canonical_name": "PM-KISAN Samman Nidhi (Pradhan Mantri Kisan Samman Nidhi)",
        "canonical_terms": ["PM-KISAN Samman Nidhi", "Pradhan Mantri Kisan Samman Nidhi"],
        "patterns": [
            # English
            r"\bpm[-\s]?kisan\b",
            r"\bkisan\s+samman\s+nidhi\b",
            r"\bpm\s+kisan\s+samman\b",
            r"\bkisan\s+samman\b",
            # Hindi
            r"पीएम[-\s]?किसान",
            r"किसान\s+सम्मान\s+निधि",
            r"पीएम\s+किसान\s+सम्मान",
            # Telugu
            r"పీఎం[-\s]?కిసాన్",
            r"కిసాన్\s+సమ్మాన్\s+నిధి",
            r"పీఎం\s+కిసాన్\s+పథకం",
        ],
    },
    "SCHEME_MSME_001_PMEGP": {
        "canonical_name": "Prime Minister's Employment Generation Programme (PMEGP)",
        "canonical_terms": ["Prime Minister's Employment Generation Programme", "PMEGP MSME Subsidy Scheme"],
        "patterns": [
            # English
            r"\bpmegp\b",
            r"\bprime\s+minister(?:'s)?\s+employment\s+generation\b",
            r"\bkvic\s+loan\b",
            r"\bpmegp\s+loan\b",
            r"\bpmegp\s+subsidy\b",
            # Hindi
            r"पीएमईजीपी",
            r"प्रधानमंत्री\s+रोजगार\s+सृजन\s+कार्यक्रम",
            r"पीएम\s+रोजगार\s+सृजन",
            # Telugu
            r"పీఎంఈజీపీ",
            r"ప్రధాన\s+మంత్రి\s+ఉపాధి\s+కల్పన\s+పథకం",
        ],
    },
    "SCHEME_URBAN_001_PM_SVANIDHI": {
        "canonical_name": "PM SVANidhi (Street Vendors AtmaNirbhar Nidhi)",
        "canonical_terms": ["PM SVANidhi", "PM Street Vendor's AtmaNirbhar Nidhi"],
        "patterns": [
            # English
            r"\bpm[-\s]?svanidhi\b",
            r"\bsvanidhi\b",
            r"\bstreet\s+vendor(?:'s)?\s+(?:loan|nidhi|scheme)\b",
            r"\bsvanidhi\s+se\s+samriddhi\b",
            # Hindi
            r"पीएम[-\s]?स्वनिधि",
            r"स्वनिधि\s+(?:योजना|लोन)",
            r"स्ट्रीट\s+वेंडर\s+योजना",
            # Telugu
            r"పీఎం[-\s]?స్వనిధి",
            r"స్వనిధి\s+పథకం",
            r"వీధి\s+వ్యాపారుల\s+రుణం",
        ],
    },
    "SCHEME_LABOUR_001_PM_SYM": {
        "canonical_name": "Pradhan Mantri Shram Yogi Maandhan (PM-SYM)",
        "canonical_terms": ["Pradhan Mantri Shram Yogi Maandhan", "PM-SYM Unorganized Workers Pension Scheme"],
        "patterns": [
            # English
            r"\bpm[-\s]?sym\b",
            r"\bshram\s+yogi\s+maan[-\s]?dhan\b",
            r"\bshram\s+yogi\s+pension\b",
            r"\bpm[-\s]?shram\s+yogi\b",
            # Hindi
            r"पीएम[-\s]?एसवाईएम",
            r"श्रम\s+योगी\s+मान[-\s]?धन",
            r"पीएम\s+श्रम\s+योगी",
            # Telugu
            r"పీఎం[-\s]?ఎస్‌వైఎం",
            r"శ్రమ\s+యోగి\s+మాన్[-\s]?ధన్",
            r"శ్రమ\s+యోగి\s+పెన్షన్",
        ],
    },
    "SCHEME_WOMEN_001_PMUY_2": {
        "canonical_name": "Pradhan Mantri Ujjwala Yojana (PMUY / Ujjwala 2.0)",
        "canonical_terms": ["Pradhan Mantri Ujjwala Yojana", "PMUY Ujjwala 2.0 LPG Connection Scheme"],
        "patterns": [
            # English
            r"\bpmuy\b",
            r"\bujjwala(?:\s+2(?:\.0)?)?\b",
            r"\bpm\s+ujjwala(?:\s+yojana)?\b",
            r"\bpradhan\s+mantri\s+ujjwala\b",
            r"\bfree\s+gas\s+cylinder\s+scheme\b",
            # Hindi
            r"पीएमयूवाई",
            r"उज्ज्वला(?:\s+योजना)?(?:\s+2(?:\.0)?)?",
            r"प्रधानमंत्री\s+उज्ज्वला\s+योजना",
            # Telugu
            r"పీఎంయూవై",
            r"ఉజ్జ్వల(?:\s+పథకం)?(?:\s+2(?:\.0)?)?",
            r"ప్రధాన\s+మంత్రి\s+ఉజ్జ్వల\s+యోజన",
        ],
    },
}


# 2. Unsupported Scheme Entity Recognition Patterns
# Explicitly non-supported Indian schemes to intercept prior to retrieval
UNSUPPORTED_SCHEME_PATTERNS: Dict[str, Dict[str, Any]] = {
    "PM_KMY": {
        "canonical_name": "PM-KMY (Pradhan Mantri Kisan Maan-Dhan Yojana)",
        "patterns": [
            r"\bpm[-\s]?kmy\b",
            r"\bkisan\s+maan[-\s]?dhan\b",
            r"किसान\s+मान[-\s]?धन",
            r"కిసాన్\s+మాన్[\u200c\s-]*ధన్",
        ],
    },
    "PMSBY": {
        "canonical_name": "PMSBY (Pradhan Mantri Suraksha Bima Yojana)",
        "patterns": [
            r"\bpmsby\b",
            r"\bsuraksha\s+bima\b",
            r"सुरक्षा\s+बीमा\s+योजना",
            r"सुरक्षा\s+बीमा",
            r"సురక్ష\s+బీమా\s+యోజన",
        ],
    },
    "PMJJBY": {
        "canonical_name": "PMJJBY (Pradhan Mantri Jeevan Jyoti Bima Yojana)",
        "patterns": [
            r"\bpmjjby\b",
            r"\bjeevan\s+jyoti\s+bima\b",
            r"जीवन\s+ज्योति\s+बीमा",
            r"జీవన్\s+జ్యోతి\s+బీమా",
        ],
    },
    "PMAY": {
        "canonical_name": "PMAY (Pradhan Mantri Awaas Yojana)",
        "patterns": [
            r"\bpmay\b",
            r"\bpmay[-\s]?[gu]\b",
            r"\bawaas\s+yojana\b",
            r"\bawas\s+yojana\b",
            r"\bpucca\s+house\b",
            r"आवास\s+योजना",
            r"ఆవాస్\s+యోజన",
        ],
    },
    "PMJAY": {
        "canonical_name": "PM-JAY / Ayushman Bharat (Pradhan Mantri Jan Arogya Yojana)",
        "patterns": [
            r"\bayushman\s+bharat\b",
            r"\bayushman\s+card\b",
            r"\bpm[-\s]?jay\b",
            r"\bjan\s+arogya\b",
            r"आयुष्मान\s+भारत",
            r"जन\s+आरोग्य",
            r"ఆయుష్మాన్\s+భారత్",
        ],
    },
    "SSY": {
        "canonical_name": "Sukanya Samriddhi Yojana (SSY)",
        "patterns": [
            r"\bsukanya\s+samriddhi\b",
            r"\bssy\s+scheme\b",
            r"\bssy\s+account\b",
            r"सुकन्या\s+समृद्धि",
            r"సుకున్య\s+సమృద్ధి",
        ],
    },
    "ESHRAM": {
        "canonical_name": "e-Shram Yojana",
        "patterns": [
            r"\be[-\s]?shram\b",
            r"\bshramik\s+card\b",
            r"ई[-\s]?श्रम",
            r"శ్రామిక్\s+కార్డు",
        ],
    },
    "APY": {
        "canonical_name": "Atal Pension Yojana (APY)",
        "patterns": [
            r"\batal\s+pension\b",
            r"\bapy\s+scheme\b",
            r"अटल\s+पेंशन",
            r"అటల్\s+పెన్షన్",
        ],
    },
    "MGNREGA": {
        "canonical_name": "MGNREGA (Mahatma Gandhi National Rural Employment Guarantee Scheme)",
        "patterns": [
            r"\bm?gnrega\b",
            r"\bnrega\b",
            r"\brural\s+employment\s+guarantee\b",
            r"\bnational\s+rural\s+employment\b",
            r"\bjob\s+card\b",
            r"मनरेगा",
            r"నరేగా",
        ],
    },
    "MUDRA": {
        "canonical_name": "PM Mudra Yojana",
        "patterns": [
            r"\bmudra\s+(?:loan|yojana|scheme)\b",
            r"मुद्रा\s+(?:लोन|योजना)",
            r"ముద్రా\s+రుణం",
        ],
    },
    "VISHWAKARMA": {
        "canonical_name": "PM Vishwakarma Yojana",
        "patterns": [
            r"\bpm\s+vishwakarma\b",
            r"\bvishwakarma\s+yojana\b",
            r"विश्वकर्मा\s+योजना",
            r"విశ్వకర్మ\s+యోజన",
        ],
    },
    "LADLI_BEHNA": {
        "canonical_name": "Ladli Behna / Majhi Ladki Bahin Yojana",
        "patterns": [
            r"\bladli\s+behna\b",
            r"\bladki\s+bahin\b",
            r"लाडली\s+बहना",
            r"లడ్లీ\s+బహనా",
        ],
    },
}


# 3. Multilingual Domain Terminology & Concept Normalization
# Maps domain categories to multilingual triggers and English canonical expansion concepts
DOMAIN_CONCEPT_PATTERNS: Dict[str, Dict[str, Any]] = {
    "family_income": {
        "canonical_expansion": "family income annual parental income ceiling limit per annum",
        "triggers": [
            # English
            r"\bfamily\s+income\b", r"\bannual\s+income\b", r"\bincome\s+ceiling\b",
            r"\bincome\s+limit\b", r"\bparental\s+income\b", r"\bincome\s+criteria\b",
            # Hindi
            r"पारिवारिक\s+आय", r"वार्षिक\s+आय", r"आय\s+सीमा", r"आमदनी", r"माता-पिता\s+की\s+आय",
            # Telugu
            r"కుటుంబ\s+ఆదాయం", r"వార్షిక\s+ఆదాయం", r"ఆదాయ\s+పరిమితి", r"తల్లిదండ్రుల\s+ఆదాయం",
        ],
    },
    "disability": {
        "canonical_expansion": "specially-abled benchmark disability physical handicap PwD",
        "triggers": [
            # English
            r"\bdisabilit(?:y|ies)\b", r"\bhandicap(?:ped)?\b", r"\bspecially[-\s]abled\b",
            r"\bphysically\s+handicapped\b", r"\bbenchmark\s+disability\b", r"\bpwd\b",
            # Hindi
            r"दिव्यांग(?:ता|जन)?", r"विकलांग(?:ता)?", r"शारीरिक\s+अक्षमता",
            # Telugu
            r"వికలాంగ(?:ుల)?", r"వికలాంగ\s+శాతం", r"దివ్యాంగ", r"అంగవైకల్యం",
        ],
    },
    "educational_qualification": {
        "canonical_expansion": "educational qualification marks percentile class 12 qualifying examination",
        "triggers": [
            # English
            r"\bqualification\b", r"\bpercentile\b", r"\bclass\s+(?:12|xii)\b",
            r"\bintermediate\b", r"\bqualifying\s+exam(?:ination)?\b",
            # Hindi
            r"शैक्षणिक\s+योग्यता", r"12वीं\s+कक्षा", r"इंटरमीडिएट", r"पर्सेंटाइल", r"कटऑफ",
            # Telugu
            r"విద్యార్హత", r"12వ\s+తరగతి", r"ఇంటర్మీడియట్", r"పర్సంటైల్",
        ],
    },
    "diploma_and_degree": {
        "canonical_expansion": "degree diploma technical education engineering regular course",
        "triggers": [
            # English
            r"\bdiploma\b", r"\bdegree\b", r"\bengineering\b", r"\btechnical\s+education\b",
            r"\bpolytechnic\b", r"\blateral\s+entry\b",
            # Hindi
            r"डिप्लोमा", r"डिग्री", r"इंजीनियरिंग", r"तकनीकी\s+शिक्षा", r"पॉलिटेक्निक", r"लेटरल\s+एंट्री",
            # Telugu
            r"డిప్లొమా", r"డిగ్రీ", r"ఇంజనీరింగ్", r"సాంకేతిక\s+విద్య", r"పాలిటెక్నిక్", r"లేటరల్\s+ఎంట్రీ",
        ],
    },
    "scholarship": {
        "canonical_expansion": "scholarship financial assistance grant support",
        "triggers": [
            # English
            r"\bscholarship\b", r"\bfinancial\s+assistance\b", r"\bgrant\b", r"\bfunding\b",
            # Hindi
            r"छात्रवृत्ति", r"स्कॉलरशिप", r"वित्तीय\s+सहायता", r"आर्थिक\s+सहायता",
            # Telugu
            r"స్కాలర్‌షిప్", r"ఉపకార\s+వేతనం", r"ఆర్థిక\s+సహాయం",
        ],
    },
    "required_documents": {
        "canonical_expansion": "required documents valid certificate marksheet UDID card proof",
        "triggers": [
            # English
            r"\brequired\s+documents?\b", r"\bdocuments?\s+to\s+upload\b", r"\bcertificates?\b",
            r"\budid(?:\s+card)?\b", r"\bincome\s+certificate\b", r"\bdisability\s+certificate\b",
            # Hindi
            r"दस्तावेज", r"प्रमाण\s*पत्र", r"आय\s+प्रमाण\s*पत्र", r"दिव्यांगता\s+प्रमाण\s*पत्र", r"यूडीआईडी",
            # Telugu
            r"పత్రాలు", r"డాక్యుమెంట్లు", r"ధృవీకరణ\s+పత్రం", r"ఆదాయ\s+ధృవీకరణ\s+పత్రం",
            r"వికలాంగ\s+ధృవీకరణ\s+పత్రం", r"మార్కుల\s+జాబితా",
        ],
    },
    "application_procedure": {
        "canonical_expansion": "application procedure National Scholarship Portal NSP online application apply",
        "triggers": [
            # English
            r"\bhow\s+to\s+apply\b", r"\bapplication\s+procedure\b", r"\bapplication\s+process\b",
            r"\bapply\s+online\b", r"\bnsp\b", r"\bnational\s+scholarship\s+portal\b",
            # Hindi
            r"आवेदन\s+कैसे\s+करें", r"आवेदन\s+प्रक्रिया", r"ऑनलाइन\s+आवेदन", r"पोर्टल", r"एनएसपी",
            # Telugu
            r"ఎలా\s+దరఖాస్తు\s+చేయాలి", r"దరఖాస్తు\s+విధానం", r"ఆన్‌లైన్\s+దరఖాస్తు", r"పోర్టల్",
        ],
    },
    "renewal": {
        "canonical_expansion": "renewal application subsequent year promotion continuation",
        "triggers": [
            # English
            r"\brenewal\b", r"\brenew\b", r"\bsubsequent\s+year\b", r"\bpromotion\b",
            # Hindi
            r"नवीनीकरण", r"रिन्यू", r"अगले\s+वर्ष",
            # Telugu
            r"పునరుద్ధరణ", r"రెన్యూవల్", r"తదుపరి\s+సంవత్సరం",
        ],
    },
    "girl_students": {
        "canonical_expansion": "girl students female candidates women empowerment",
        "triggers": [
            # English
            r"\bgirl\s+students?\b", r"\bgirls?\b", r"\bfemale\b", r"\bwomen\b",
            # Hindi
            r"छात्रा(?:एं|ओं|ओ)?", r"लड़क(?:ी|ियों|ियाँ|िया)?", r"महिला(?:एं|ओं|ओ)?",
            # Telugu
            r"విద్యార్థిను(?:లు|లకు)?", r"బాలిక(?:లు|లకు)?", r"అమ్మాయి(?:లు|లకు)?", r"మహిళ(?:లు|లకు)?",
        ],
    },
    "orphan_students": {
        "canonical_expansion": "orphan students lost both parents Covid-19 pandemic martyred Armed Forces CAPF",
        "triggers": [
            # English
            r"\borphans?\b", r"\blost\s+(?:both\s+)?parents\b", r"\bcovid(?:-19)?\s+orphan\b",
            r"\bmartyr(?:ed)?\b", r"\barmed\s+forces\b",
            # Hindi
            r"अनाथ", r"माता-पिता\s+(?:की\s+मृत्यु|खो\s+दिए)", r"कोविड\s+अनाथ", r"शहीद",
            # Telugu
            r"అనాథ", r"తల్లిదండ్రులను\s+కోల్పోయిన", r"తల్లిదండ్రులు\s+లేని", r"కోవిడ్\s+అనాథ", r"అమరవీరుల",
        ],
    },
    "institution_and_college": {
        "canonical_expansion": "notified institution college university AICTE approved",
        "triggers": [
            # English
            r"\binstitut(?:ion|e)s?\b", r"\bcolleges?\b", r"\buniversit(?:y|ies)\b",
            r"\bnotified\s+institut(?:ion|e)s?\b", r"\baicte\s+approved\b",
            # Hindi
            r"संस्थान", r"कॉलेज", r"विश्वविद्यालय", r"संस्था", r"मान्यता\s+प्राप्त",
            # Telugu
            r"సంస్థ", r"కళాశాల", r"విశ్వవిద్యాలయం", r"కాలేజీ",
        ],
    },
}


# ---------------------------------------------------------------------------
# Language Detection Helper (Indic Scripts & Romanized Vocabulary)
# ---------------------------------------------------------------------------

ROMAN_TELUGU_WORDS: Set[str] = {
    # Pronouns & possessives
    "naaku", "naku", "meeku", "miku", "nenu", "meeru", "miru", "manaki", "manaku",
    "maaku", "maku", "atanu", "aame", "vaallu", "vallu", "adi", "idi", "evi", "ivi",
    # Question words
    "enti", "emti", "enduku", "evaru", "evvaru", "ela", "eppudu", "ekkada", "ekada",
    "enni", "enta", "entha", "emaina", "emina", "emi", "emem",
    # Verbs & modals
    "kavali", "kaavali", "kavala", "kaavala",
    "cheyali", "cheyyali", "cheyyocha", "cheyocha", "cheppandi", "telusukovali", "teliyadu",
    "telusa", "undi", "unda", "undhi", "undaa", "unnara", "unnav", "unnanu", "unnayi", "untaayi",
    "vastunda", "vasthunda", "vastundi", "vasthundi", "vastundaa", "ravadam", "kattadaniki",
    "chaduvutunna", "chaduvutunnanu", "pettukovacha", "pettukovali", "ivvandi", "teesukovali",
    "avtunda", "avutunda", "avuthunda",
    # Domain & nouns
    "arhatalu", "arhata", "arhathalu", "pathakam", "padhakam", "sahayam", "sahayata",
    "dabbu", "dabbulu", "vidyarthulu", "chadavali", "chaduvu", "panulu",
    # Conversational & markers
    "bagunnara", "bagunnava", "bagundi", "bagundhi", "namaskaram", "dhanyavadalu",
    "sare", "ardhamaindi", "ardham", "avuna", "kadha", "ledu", "ledhu", "ippudu",
    "tarvata", "mari", "inka", "kuda", "kooda", "chala", "gurinchi", "kosam",
}

ROMAN_HINDI_WORDS: Set[str] = {
    # Pronouns & possessives
    "mujhe", "mujhko", "humko", "humein", "hume", "mera", "meri", "mere",
    "aap", "aapko", "aapka", "aapki", "aapke", "tum", "tumhe", "tumko", "tumhara",
    "tumhari", "yeh", "voh", "iska", "iski", "iske", "uska", "uski", "uske",
    # Question words
    "kya", "kyun", "kyon", "kyu", "kaise", "kab", "kaha", "kahan", "kaun", "kitna",
    "kitne", "kitni", "kisko", "kisse",
    # Verbs & modals
    "chahiye", "chaahiye", "kare", "karein", "karna", "karo", "kijie", "kijiye",
    "karenge", "karega", "karegi", "sakenge", "saken",
    "batao", "bataiye", "bataye", "batayein", "boliye", "samajh", "milega", "milegi", "milenge",
    "milta", "milti", "sakta", "sakti", "sakte", "hai", "hain", "tha", "thi",
    "hoga", "hogi", "honge", "hona", "lagta", "lagti",
    # Domain & nouns
    "patrata", "yojana", "chhatravritti", "madad", "paisa", "paise", "rupaya", "rupaye",
    "dastavej", "aavedan", "aawedan", "jankari", "jaankari", "bhare", "bharein", "bharna",
    # Conversational & markers
    "theek", "shukriya", "dhanyavad", "namaste", "pranam", "achha", "accha",
    "bahut", "ab", "phir", "bhi", "aur", "lekin", "nahi", "nahin", "mat", "bare",
    "wale", "wali", "wala", "liye", "honi",
}

ROMAN_TELUGU_PHRASES = re.compile(
    r"\b(?:ela\s+apply\s+cheyali|apply\s+cheyyocha|apply\s+cheyocha|apply\s+cheyali|apply\s+cheyyali|"
    r"nenu\s+apply|naaku\s+kavali|arhatalu\s+enti|scheme\s+gurinchi|cheppandi|dabbu\s+vastunda|"
    r"bagunnara|ela\s+unnaru|meeru\s+evaru|neeku\s+em\s+telusu|pragati\s+scheme\s+arhatalu|"
    r"scholarship\s+vastunda|arhatalu\s+emiti|emaina\s+schemes|schemes\s+unnaya|\w+\s+lo\b)\b",
    re.IGNORECASE,
)

ROMAN_HINDI_PHRASES = re.compile(
    r"\b(?:kaise\s+apply\s+kare|apply\s+kaise\s+kare|kya\s+eligibility|mujhe\s+chahiye|last\s+date\s+kab|"
    r"kitne\s+paise|kaise\s+ho|kya\s+haal|aap\s+kaun|tum\s+kaun|ke\s+bare\s+me|jankari\s+chahiye|"
    r"ke\s+liye|koi\s+scholarship|renewal\s+kaise)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Detects primary language of user query: 'te', 'hi', or 'en'.

    Supports native Telugu script, Devanagari Hindi script, and Romanized
    Telugu / Hindi transliterations using robust lexical and phrase patterns.
    """
    if not text or not isinstance(text, str):
        return "en"

    has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))
    has_telugu = bool(re.search(r"[\u0C00-\u0C7F]", text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))

    if has_devanagari and not has_telugu:
        return "hi"
    if has_telugu and not has_devanagari:
        return "te"
    if has_devanagari and has_telugu:
        deva_count = len(re.findall(r"[\u0900-\u097F]", text))
        telu_count = len(re.findall(r"[\u0C00-\u0C7F]", text))
        return "hi" if deva_count >= telu_count else "te"

    # Pure or mixed Latin text: evaluate Romanized Indic lexical indicators
    if has_latin:
        tokens = set(re.findall(r"[a-zA-Z]+", text.lower()))
        te_score = len(tokens.intersection(ROMAN_TELUGU_WORDS))
        hi_score = len(tokens.intersection(ROMAN_HINDI_WORDS))

        if ROMAN_TELUGU_PHRASES.search(text):
            te_score += 2
        if ROMAN_HINDI_PHRASES.search(text):
            hi_score += 2

        if te_score > 0 and te_score >= hi_score:
            return "te"
        if hi_score > 0 and hi_score > te_score:
            return "hi"

    return "en"


def normalize_language_code(lang: Optional[str]) -> str:
    """Normalizes language code or name to standard short code: 'te', 'hi', or 'en'."""
    if not lang or not isinstance(lang, str):
        return "en"
    l = lang.strip().lower()
    if l in ("te", "mixed-te", "te-in", "telugu") or l.startswith("te") or "telugu" in l or "-te" in l:
        return "te"
    if l in ("hi", "mixed-hi", "hi-in", "hindi") or l.startswith("hi") or "hindi" in l or "-hi" in l:
        return "hi"
    return "en"


def normalize_language_name(lang: Optional[str]) -> str:
    """Normalizes language code or name to standard name: 'telugu', 'hindi', or 'english'."""
    code = normalize_language_code(lang)
    if code == "te":
        return "telugu"
    if code == "hi":
        return "hindi"
    return "english"


# ---------------------------------------------------------------------------
# Abstract Base Provider
# ---------------------------------------------------------------------------

class BaseRewritingProvider(ABC):
    """Abstract interface for query rewriting implementations (Rule-Based or LLM-Based)."""

    @abstractmethod
    def rewrite(self, query: str) -> RewrittenQuery:
        """Rewrites and expands the query while preserving provenance and intent."""
        pass

    @abstractmethod
    def rewrite_with_context(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> RewrittenQuery:
        """Rewrites query resolving multi-turn context, pronouns, and scheme intent."""
        pass


# ---------------------------------------------------------------------------
# Dictionary-Based Rewriter Provider (Deterministic, Zero External API)
# ---------------------------------------------------------------------------

FOLLOWUP_PRONOUN_PATTERNS = [
    # English pronouns and reference phrases
    r"\b(?:it|its|this|that|these|those|the\s+scheme|this\s+scheme|the\s+scholarship|this\s+scholarship)\b",
    # Hindi pronouns and reference phrases
    r"\b(?:इसका|इसकी|इसके|यह|वो|इस\s+योजना|इस\s+छात्रवृत्ति)\b",
    # Telugu pronouns and reference phrases
    r"\b(?:దీని|దీనికి|ఈ\s+పథకం|ఈ\s+స్కాలర్‌షిప్|ఇది)\b",
]

FOLLOWUP_ELLIPTICAL_PATTERNS = [
    r"\b(?:income\s+limit|eligibility|documents|required|deadline|last\s+date|amount|benefits|how\s+to\s+apply|selection\s+criteria|quota|age\s+limit|minimum\s+marks|percentile)\b",
    r"\b(?:दस्तावेज|आय\s+सीमा|योग्यता|पात्रता|अंतिम\s+तिथि|आवेदन\s+कैसे\s+करें|कितनी\s+राशि)\b",
    r"\b(?:పత్రాలు|ఆదాయ\s+పరిమితి|అర్హత|చివరి\s+తేదీ|ఎలా\s+దరఖాస్తు\s+చేయాలి)\b",
]


class DictionaryRewritingProvider(BaseRewritingProvider):
    """Deterministic, rule-based multilingual query rewriter.

    - Performs regex-based scheme entity recognition.
    - Intercepts unsupported schemes before vector retrieval.
    - Resolves multi-turn conversational pronouns and elliptical follow-ups.
    - Normalizes multilingual terminology across key operational domains.
    - Preserves the original query strictly and appends canonical English terms.
    - Never invents eligibility criteria, specific rupee limits, or percentages.
    """

    def __init__(self):
        # Compile supported scheme patterns for case-insensitive matching
        self._scheme_patterns: List[Tuple[str, re.Pattern, str, List[str]]] = []
        for s_id, s_info in SCHEME_ENTITY_PATTERNS.items():
            for pat in s_info["patterns"]:
                self._scheme_patterns.append((
                    s_id,
                    re.compile(pat, re.IGNORECASE),
                    s_info["canonical_name"],
                    s_info["canonical_terms"],
                ))

        # Compile unsupported scheme patterns
        self._unsupported_patterns: List[Tuple[str, re.Pattern, str]] = []
        for s_code, s_info in UNSUPPORTED_SCHEME_PATTERNS.items():
            for pat in s_info["patterns"]:
                self._unsupported_patterns.append((
                    s_code,
                    re.compile(pat, re.IGNORECASE),
                    s_info["canonical_name"],
                ))

        # Compile concept patterns
        self._concept_patterns: List[Tuple[str, re.Pattern, str]] = []
        for cat, info in DOMAIN_CONCEPT_PATTERNS.items():
            for trig in info["triggers"]:
                self._concept_patterns.append((
                    cat,
                    re.compile(trig, re.IGNORECASE),
                    info["canonical_expansion"],
                ))

        # Compile follow-up triggers
        self._followup_pronoun_patterns = [
            re.compile(p, re.IGNORECASE) for p in FOLLOWUP_PRONOUN_PATTERNS
        ]
        self._followup_elliptical_patterns = [
            re.compile(p, re.IGNORECASE) for p in FOLLOWUP_ELLIPTICAL_PATTERNS
        ]

    def detect_unsupported_scheme(self, query: str) -> Optional[Dict[str, str]]:
        """Identifies any explicit unsupported scheme referenced in the query.

        Returns:
            Dict with scheme_code and canonical_name, or None if no unsupported scheme detected.
        """
        for code, pat, canon_name in self._unsupported_patterns:
            if pat.search(query):
                return {"scheme_code": code, "canonical_name": canon_name}
        return None

    def detect_scheme(self, query: str) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Identifies any explicit government scheme referenced in the query.

        Returns:
            Tuple of (scheme_id, canonical_scheme_name, canonical_expansion_terms).
            Returns (None, None, []) if no scheme is recognized.
        """
        for s_id, pat, canon_name, canon_terms in self._scheme_patterns:
            if pat.search(query):
                return s_id, canon_name, canon_terms
        return None, None, []

    def detect_all_schemes(self, query: str) -> List[Tuple[str, str, List[str]]]:
        """Identifies all explicit supported government schemes referenced in the query.

        Returns:
            List of tuples: [(scheme_id, canonical_scheme_name, canonical_expansion_terms), ...]
        """
        found = []
        seen_ids = set()
        for s_id, pat, canon_name, canon_terms in self._scheme_patterns:
            if s_id not in seen_ids and pat.search(query):
                found.append((s_id, canon_name, canon_terms))
                seen_ids.add(s_id)
        return found

    def detect_concepts(self, query: str) -> List[Tuple[str, str]]:
        """Identifies domain concept categories and their canonical English terms."""
        matched: Dict[str, str] = {}
        for cat, pat, canon_exp in self._concept_patterns:
            if cat not in matched and pat.search(query):
                matched[cat] = canon_exp
        return list(matched.items())

    def rewrite_with_context(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> RewrittenQuery:
        """Main contextual rewriting pipeline.

        1. Validates non-empty input.
        2. Detects query language.
        3. Checks for explicitly unsupported scheme requests (e.g., PM-KISAN).
        4. Identifies supported schemes in current query (takes precedence).
        5. If no scheme is present in current query, resolves pronouns/elliptical follow-ups
           from conversation history.
        6. Flags ambiguous follow-ups lacking context.
        7. Enriches query with domain concepts for vector search.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        clean_query = query.strip()
        lang = detect_language(clean_query)

        # 1. Unsupported scheme gate
        unsupported = self.detect_unsupported_scheme(clean_query)
        if unsupported:
            return RewrittenQuery(
                original_query=clean_query,
                rewritten_query=clean_query,
                detected_scheme_id=None,
                detected_language=lang,
                unsupported_scheme=unsupported["canonical_name"],
                is_rewritten=False,
            )

        # 2. Check supported schemes in CURRENT query
        current_schemes = self.detect_all_schemes(clean_query)
        effective_query = clean_query
        scheme_id: Optional[str] = None
        scheme_name: Optional[str] = None
        scheme_terms: List[str] = []
        resolved_from_context = False
        referenced_ids: List[str] = []

        if len(current_schemes) == 1:
            scheme_id, scheme_name, scheme_terms = current_schemes[0]
            referenced_ids = [scheme_id]
        elif len(current_schemes) > 1:
            # Multi-scheme query in current turn
            referenced_ids = [s[0] for s in current_schemes]
            # Leave scheme_id None to search across all schemes
        else:
            # No scheme in current turn: inspect multi-turn context
            is_pronoun_followup = any(p.search(clean_query) for p in self._followup_pronoun_patterns)
            is_elliptical_followup = any(p.search(clean_query) for p in self._followup_elliptical_patterns)

            history_scheme: Optional[Tuple[str, str, List[str]]] = None
            if conversation_history:
                # Bounded to last 10 messages, scanning from newest to oldest
                for msg in reversed(conversation_history[-10:]):
                    content = msg.get("content", "") or msg.get("text", "") or ""
                    if not content or not isinstance(content, str):
                        continue
                    schemes_in_msg = self.detect_all_schemes(content)
                    if schemes_in_msg:
                        history_scheme = schemes_in_msg[0]
                        break

            # Only resolve from history if query is an actual follow-up (pronoun, elliptical, or scheme concept)
            has_scheme_concept = bool(self.detect_concepts(clean_query))
            if history_scheme and (is_pronoun_followup or is_elliptical_followup or has_scheme_concept):
                scheme_id, scheme_name, scheme_terms = history_scheme
                resolved_from_context = True
                referenced_ids = [scheme_id]

                # Reformulate into a standalone retrieval query
                reformulated = clean_query
                if is_pronoun_followup:
                    for p in self._followup_pronoun_patterns:
                        reformulated = p.sub(f"the {scheme_name}", reformulated)
                    reformulated = re.sub(r"\bthe\s+the\b", "the", reformulated, flags=re.IGNORECASE).strip()
                elif is_elliptical_followup:
                    reformulated = f"{clean_query} for {scheme_name}"
                else:
                    reformulated = f"{clean_query} {scheme_name}"

                effective_query = reformulated

            elif is_pronoun_followup:
                # Follow-up pronoun used with no scheme found in prior context
                return RewrittenQuery(
                    original_query=clean_query,
                    rewritten_query=clean_query,
                    detected_scheme_id=None,
                    detected_language=lang,
                    is_ambiguous=True,
                    clarification_message=AMBIGUOUS_FOLLOWUP_MESSAGE,
                    is_rewritten=False,
                )

        # 3. Domain concept detection & enrichment
        concepts = self.detect_concepts(effective_query)
        expanded_tokens: List[str] = []

        if scheme_name:
            expanded_tokens.append(scheme_name)
            for t in scheme_terms:
                if t not in expanded_tokens:
                    expanded_tokens.append(t)

        for _, canon_exp in concepts:
            if canon_exp not in expanded_tokens:
                expanded_tokens.append(canon_exp)

        if expanded_tokens:
            expansion_suffix = " ".join(expanded_tokens)
            rewritten_text = f"{effective_query} {expansion_suffix}".strip()
            is_rewritten = True
        else:
            rewritten_text = effective_query
            is_rewritten = (effective_query != clean_query)

        return RewrittenQuery(
            original_query=clean_query,
            rewritten_query=rewritten_text,
            detected_scheme_id=scheme_id,
            detected_language=lang,
            expanded_terms=expanded_tokens,
            is_rewritten=is_rewritten,
            resolved_from_context=resolved_from_context,
            referenced_scheme_ids=referenced_ids,
        )

    def rewrite(self, query: str) -> RewrittenQuery:
        """Main rewriting pipeline for single-turn queries."""
        return self.rewrite_with_context(query, conversation_history=None)


# ---------------------------------------------------------------------------
# High-Level Modular QueryRewriter Wrapper
# ---------------------------------------------------------------------------

class QueryRewriter:
    """Entrypoint for query rewriting in SahayAI RAG.

    Supports swappable providers (Dictionary-based default; LLM-based future).
    """

    def __init__(self, provider: Optional[BaseRewritingProvider] = None):
        self.provider = provider or DictionaryRewritingProvider()

    def rewrite(self, query: str) -> RewrittenQuery:
        """Enriches user query with cross-lingual canonical policy terminology."""
        return self.provider.rewrite(query)

    def rewrite_with_context(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> RewrittenQuery:
        """Enriches user query resolving multi-turn context and follow-up references."""
        return self.provider.rewrite_with_context(query, conversation_history)

    def detect_scheme_intent(self, query: str) -> Optional[str]:
        """Convenience method to extract canonical scheme_id if present."""
        res = self.rewrite(query)
        return res.detected_scheme_id

    def detect_unsupported_scheme(self, query: str) -> Optional[Dict[str, str]]:
        """Convenience method to check for unsupported schemes."""
        if hasattr(self.provider, "detect_unsupported_scheme"):
            return self.provider.detect_unsupported_scheme(query)
        return None

    def detect_all_schemes(self, query: str) -> List[Tuple[str, str, List[str]]]:
        """Convenience method to extract all supported schemes present in query."""
        if hasattr(self.provider, "detect_all_schemes"):
            return self.provider.detect_all_schemes(query)
        return []

