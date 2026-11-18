"""Intelligent Intent Understanding and Routing Subsystem for SahayAI.

Provides multi-stage intent classification, typo tolerance, multilingual semantic
routing, and context-aware follow-up resolution BEFORE document retrieval.
Distinguishes between general conversation, scheme inquiries, and ambiguous messages
without hardcoding fixed phrases or treating unknown phrases as scheme queries.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from rag.answer_generator import sanitize_input
from rag.query_rewriter import (
    QueryRewriter,
    detect_language,
    normalize_language_code,
    normalize_language_name,
)
from .scheme_catalog_index import SchemeCatalogIndex

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Categorical intent types supported by SahayAI."""
    GENERAL_CONVERSATION = "general_conversation"
    SCHEME_INQUIRY = "scheme_inquiry"
    AMBIGUOUS = "ambiguous"


@dataclass
class IntentResult:
    """Structured decision output from the Intent Routing layer."""
    intent: IntentType
    confidence: float
    detected_scheme_id: Optional[str] = None
    detected_scheme_name: Optional[str] = None
    unsupported_scheme: Optional[str] = None
    detected_language: str = "en"
    is_followup: bool = False
    is_discovery: bool = False
    candidate_scheme_ids: List[str] = field(default_factory=list)
    extracted_criteria: Dict[str, Any] = field(default_factory=dict)
    clarification_prompt: Optional[str] = None


# Core regex patterns for deterministic safeguards

GREETING_PATTERN = re.compile(
    r"^(?:hi+|hello+|heyy*|hel+o+|hlo|hellow|good\s+(?:morning|afternoon|evening|day|night)|"
    r"gud\s+(?:mrng|mng|aftn|eve)|namaste+|namaskar(?:am)?|pranam|ram\s+ram|vanakkam|"
    r"kya\s+haal\s+hai|ela\s+unnaru|bagunnara|bagunnava|kem\s+cho|adaab|"
    r"नमस्ते|नमस्कार|प्रणाम|నమస్కారం|నమస్తే)[\s!.,?]*$",
    re.IGNORECASE,
)

GREETING_PREFIX_PATTERN = re.compile(
    r"^(?:hi+|hello+|heyy*|hel+o+|namaste+|namaskar(?:am)?|good\s+(?:morning|afternoon|evening))\b",
    re.IGNORECASE,
)

GRATITUDE_PATTERN = re.compile(
    r"^(?:thanks?(?:\s+(?:a\s+lot|you|very\s+much|so\s+much))?|thx|ty|dhanyavad(?:alu)?|"
    r"shukriya|(?:okay|ok)?\s*(?:got\s+it)?|okay|ok|understood|cool|great|nice|perfect|"
    r"theek\s+hai|sare|ardhamaindi|धन्यवाद|शुक्रिया|ధన్యవాదాలు)[\s!.,?]*$",
    re.IGNORECASE,
)

SMALL_TALK_PATTERN = re.compile(
    r"\b(?:who\s+(?:are\s+you|made\s+you|created\s+you)|what\s+is\s+your\s+name|"
    r"what\s+can\s+you\s+do|how\s+are\s+you|how\s+do\s+you\s+work|tell\s+me\s+a\s+joke|"
    r"are\s+you\s+(?:an?\s+)?(?:ai|human|robot|bot)|what\s+is\s+sahayai|"
    r"kaise\s+ho|kya\s+kar\s+rahe\s+ho|tum\s+kaun\s+ho|aap\s+kaun\s+hain|"
    r"ela\s+unnav|meeru\s+evaru|neeku\s+em\s+telusu)\b",
    re.IGNORECASE,
)

GENERAL_KNOWLEDGE_CONCEPTS = re.compile(
    r"\b(?:recursion|photosynthesis|binary\s+search|quicksort|merge\s+sort|algorithm|"
    r"python|java|c\+\+|javascript|function|loop|pointer|array|data\s+structure|"
    r"object\s+oriented|class|inheritance|polymorphism|compiler|operating\s+system|"
    r"newton|einstein|gravity|speed\s+of\s+light|dna|rna|cell|mitochondria|"
    r"capital\s+of|who\s+was|who\s+is\s+(?!eligible|entitled)|prime\s+minister\s+of|president\s+of|"
    r"apj\s+abdul\s+kalam|mahatma\s+gandhi|bhagat\s+singh|how\s+many\s+continents|"
    r"why\s+is\s+the\s+sky\s+blue|solar\s+system|planet|galaxy|math|calculate|geometry|"
    r"solve|reverse\s+a\s+string|bubble\s+sort|fibonacci|factorial)\b",
    re.IGNORECASE,
)

SCHEME_DISCOVERY_MARKERS = re.compile(
    r"\b(?:scholarship|scolarship|scholarships|scolarships|scheme|schemes|"
    r"financial\s+support|financial\s+assistance|financial\s+help|financial\s+aid|"
    r"help\s+(?:available\s+)?for|help\s+to|support\s+for|benefits?\s+for|"
    r"(?:orphan|orphans|divyang|specially-abled)\s+students?|"
    r"stipend|fellowship|grant|grants|tuition\s+fee|college\s+fees|fee\s+reimbursement|"
    r"subsidy|welfare\s+scheme|government\s+scheme|sarkari\s+scheme|sarkari\s+sahayata|"
    r"chhatravritti|yojana|pathakam|sahayam|upakara\s+vetanam|"
    r"nsp\s+portal|national\s+scholarship\s+portal|scholarship\s+portal|"
    r"paise\s+milenge|fee\s+ke\s+liye|dabbu\s+vastunda|fees\s+kattadaniki|"
    r"scholarship\s+vastunda|scheme\s+emaina\s+unda)\b|"
    r"[\u0900-\u097F]*?(?:छात्रवृत्ति|योजना|आर्थिक\s+सहायता|वजीफा|स्कॉलरशिप)[\u0900-\u097F]*?|"
    r"[\u0C00-\u0C7F]*?(?:స్కాలర్‌షిప్|పథకం|సహాయం|ఉపకార\s+వేతనం)[\u0C00-\u0C7F]*?",
    re.IGNORECASE,
)

FOLLOWUP_SCHEME_PRONOUNS = re.compile(
    r"\b(?:it|its|this|that|these|those|the\s+scheme|this\s+scheme|the\s+scholarship|this\s+scholarship)\b|"
    r"\b(?:इसका|इसकी|इसके|यह|वो|इस\s+योजना|इस\s+छात्रवृत्ति)\b|"
    r"\b(?:దీని|దీనికి|ఈ\s+పథకం|ఈ\s+స్కాలర్‌షిప్|ఇది)\b",
    re.IGNORECASE,
)

FOLLOWUP_SCHEME_ASPECTS = re.compile(
    r"\b(?:documents?|eligibility|eligible|deadline|deadlines|last\s+date|closing\s+date|end\s+date|"
    r"start\s+date|opening\s+date|open\s+now|currently\s+open|still\s+open|is\s+it\s+open|are\s+they\s+open|"
    r"can\s+i\s+(?:still\s+)?apply|can\s+we\s+apply|can\s+students\s+apply|"
    r"has\s+(?:the\s+)?(?:application\s+)?(?:period\s+|window\s+)?closed|is\s+it\s+closed|"
    r"when\s+will\s+(?:applications\s+)?reopen|when\s+will\s+it\s+open|reopen|reopening|next\s+cycle|"
    r"how\s+to\s+apply|application\s+process|selection\s+criteria|portal\s+link|"
    r"income\s+limit|family\s+income|annual\s+income|income\s+ceiling|"
    r"amount|scholarship\s+amount|how\s+much|benefits|stipend\s+rate|"
    r"age\s+limit|minimum\s+marks|percentage|cutoff|percentile|"
    r"can\s+boys\s+apply|can\s+girls\s+apply|who\s+can\s+apply|"
    r"renewal|how\s+to\s+renew|subsequent\s+years|duration)\b|"
    r"\b(?:दस्तावेज|आय\s+सीमा|पात्रता|योग्यता|अंतिम\s+तिथि|आवेदन\s+कैसे\s+करें|कितनी\s+राशि|खुला\s+है|खुली\s+है|बंद\s+हो\s+गया|कब\s+खुलेगा|दोबारा\s+कब|अगला\s+चक्र)\b|"
    r"\b(?:పత్రాలు|ఆదాయ\s+పరిమితి|అర్హత|చివరి\s+తేదీ|ఎలా\s+దరఖాస్తు\s+చేయాలి|ఓపెన్\s+అయిందా|ముగిసిందా|గడువు|మళ్లీ\s+ఎప్పుడు|తదుపరి\s+సైకిల్)\b",
    re.IGNORECASE,
)

AMBIGUOUS_VAGUE_PATTERNS = re.compile(
    r"^(?:details|tell\s+me\s+more|more\s+info|help\s+me|proceed|what\s+next|status|"
    r"information\s+please|tell\s+me|continue|start|check|verify|yes|no|ok\s+and)[\s!.,?]*$",
    re.IGNORECASE,
)

EXPLICIT_TELUGU_SWITCH = re.compile(
    r"\b(?:in\s+telugu|to\s+telugu|telugu\s+lo|telugulo|telugu\s+cheppandi|telugu\s+me)\b",
    re.IGNORECASE,
)

EXPLICIT_HINDI_SWITCH = re.compile(
    r"\b(?:in\s+hindi|to\s+hindi|hindi\s+me|hindime|hindi\s+batao|hindi\s+lo)\b",
    re.IGNORECASE,
)

EXPLICIT_ENGLISH_SWITCH = re.compile(
    r"\b(?:in\s+english|to\s+english|english\s+lo|english\s+me|english\s+please)\b",
    re.IGNORECASE,
)

NEUTRAL_FOLLOWUP_PATTERN = re.compile(
    r"^(?:details|tell\s+me\s+more|more\s+info|help\s+me|proceed|what\s+next|status|"
    r"information\s+please|tell\s+me|continue|start|check|verify|yes|no|ok|okay|"
    r"documents|eligibility|income|benefits|deadline|last\s+date|amount)[\s!.,?]*$",
    re.IGNORECASE,
)


class IntentRouter:
    """Modular and robust intent classification and routing engine for SahayAI."""

    def __init__(
        self,
        catalog_index: Optional[SchemeCatalogIndex] = None,
        query_rewriter: Optional[QueryRewriter] = None,
    ):
        self.catalog_index = catalog_index or SchemeCatalogIndex()
        self.rewriter = query_rewriter or QueryRewriter()

    def determine_turn_language(
        self,
        query: str,
        preferred_language: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Determines the appropriate response language for the current turn.

        Precedence:
        1. Explicit switch commands in query (e.g., 'in telugu', 'in hindi', 'in english').
        2. Detected message language (native Telugu / Devanagari script, or Romanized Indic vocabulary).
        3. Continuity with prior turns for neutral/short follow-ups.
        4. Explicit preferred_language when set to an Indic language (e.g., voice assistant).
        5. Default to 'en'.
        """
        clean = query.strip() if query else ""

        # 1. Explicit language switch in current message
        if EXPLICIT_TELUGU_SWITCH.search(clean):
            return "te"
        if EXPLICIT_HINDI_SWITCH.search(clean):
            return "hi"
        if EXPLICIT_ENGLISH_SWITCH.search(clean):
            return "en"

        # 2. Native script in current query (Devanagari or Telugu characters)
        has_telugu_script = bool(re.search(r"[\u0C00-\u0C7F]", clean))
        has_deva_script = bool(re.search(r"[\u0900-\u097F]", clean))
        if has_telugu_script and not has_deva_script:
            return "te"
        if has_deva_script and not has_telugu_script:
            return "hi"

        # 3. Explicit user selection of Indic language (e.g. from Voice Assistant language dropdown)
        if preferred_language:
            norm_pref = normalize_language_code(preferred_language)
            if norm_pref in ("te", "hi"):
                return norm_pref

        # 4. Romanized Indic vocabulary detection (Tenglish / Hinglish in Latin script)
        msg_lang = detect_language(clean)
        if msg_lang in ("te", "mixed-te"):
            return "te"
        if msg_lang in ("hi", "mixed-hi"):
            return "hi"

        # 5. Contextual continuity for neutral or short follow-ups
        words = clean.split()
        is_neutral = bool(NEUTRAL_FOLLOWUP_PATTERN.match(clean)) or len(words) <= 2
        if is_neutral and conversation_history:
            for prev in reversed(conversation_history):
                content = prev.get("content", "") or prev.get("text", "") or ""
                if not content or not isinstance(content, str):
                    continue
                prev_lang = detect_language(content)
                norm_prev = normalize_language_code(prev_lang)
                if norm_prev in ("te", "hi"):
                    return norm_prev
                if prev.get("language") in ("te", "hi"):
                    return prev["language"]
                break

        return "en"

    def route(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        preferred_language: Optional[str] = None,
    ) -> IntentResult:
        """Classifies citizen message intent into GENERAL_CONVERSATION, SCHEME_INQUIRY, or AMBIGUOUS.

        Evaluates input using deterministic safeguards, data-driven scheme recognition,
        typo-tolerant matching, and multi-turn context resolution.

        Args:
            query: Citizen input text.
            conversation_history: Optional prior messages in chronological order.
            preferred_language: Optional user-selected target language preference (e.g. 'te-IN', 'hi-IN').

        Returns:
            IntentResult with structured intent and routing metadata.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        clean_query = sanitize_input(query)

        # Context-aware and message-grounded language determination
        detected_lang = self.determine_turn_language(
            query=clean_query,
            preferred_language=preferred_language,
            conversation_history=conversation_history,
        )

        # -------------------------------------------------------------------
        # Step 1: Explicit Unsupported Scheme Interception
        # -------------------------------------------------------------------
        unsupported = self.rewriter.detect_unsupported_scheme(clean_query)
        if unsupported:
            return IntentResult(
                intent=IntentType.SCHEME_INQUIRY,
                confidence=1.0,
                unsupported_scheme=unsupported["canonical_name"],
                detected_language=detected_lang,
            )

        # -------------------------------------------------------------------
        # Step 2: Data-Driven Scheme Catalog Matching with Typo-Tolerance
        # -------------------------------------------------------------------
        scheme_match = self.catalog_index.match_scheme_by_name(clean_query)
        if scheme_match:
            s_id, s_name, score = scheme_match
            return IntentResult(
                intent=IntentType.SCHEME_INQUIRY,
                confidence=score,
                detected_scheme_id=s_id,
                detected_scheme_name=s_name,
                detected_language=detected_lang,
            )

        # -------------------------------------------------------------------
        # Step 3: General Conversation Fast-Paths (No Scheme Overtones)
        # -------------------------------------------------------------------
        is_greeting = bool(GREETING_PATTERN.match(clean_query))
        is_gratitude = bool(GRATITUDE_PATTERN.match(clean_query))
        is_small_talk = bool(SMALL_TALK_PATTERN.search(clean_query))
        is_gk_academic = bool(GENERAL_KNOWLEDGE_CONCEPTS.search(clean_query))

        has_scheme_marker = bool(SCHEME_DISCOVERY_MARKERS.search(clean_query))

        # Pure greeting or gratitude or small talk (without any scheme reference)
        if (is_greeting or is_gratitude or is_small_talk) and not has_scheme_marker:
            return IntentResult(
                intent=IntentType.GENERAL_CONVERSATION,
                confidence=0.98,
                detected_language=detected_lang,
            )

        # Education, Programming, or General Knowledge question without scheme intent
        if is_gk_academic and not has_scheme_marker:
            return IntentResult(
                intent=IntentType.GENERAL_CONVERSATION,
                confidence=0.95,
                detected_language=detected_lang,
            )

        # -------------------------------------------------------------------
        # Step 4: Scheme Inquiry & Scholarship Discovery Semantic Detection
        # -------------------------------------------------------------------
        if has_scheme_marker:
            candidate_ids, criteria = self.catalog_index.discover_schemes(clean_query)
            return IntentResult(
                intent=IntentType.SCHEME_INQUIRY,
                confidence=0.92,
                is_discovery=True,
                candidate_scheme_ids=candidate_ids,
                extracted_criteria=criteria,
                detected_language=detected_lang,
            )

        # -------------------------------------------------------------------
        # Step 5: Multi-Turn Conversation Context Resolution
        # -------------------------------------------------------------------
        if conversation_history:
            prev_scheme: Optional[Tuple[str, str]] = None
            last_was_general = False

            # Scan recent turns from newest to oldest
            for msg in reversed(conversation_history[-6:]):
                content = msg.get("content", "") or msg.get("text", "") or ""
                if not content or not isinstance(content, str):
                    continue

                # Check if previous message mentioned or was about a scheme
                hist_match = self.catalog_index.match_scheme_by_name(content)
                if hist_match:
                    prev_scheme = (hist_match[0], hist_match[1])
                    break

                # Check if previous message was general conversation
                if GENERAL_KNOWLEDGE_CONCEPTS.search(content) or SMALL_TALK_PATTERN.search(content):
                    last_was_general = True
                    break

            # If previous context was about a scheme:
            if prev_scheme:
                s_id, s_name = prev_scheme
                is_pronoun = bool(FOLLOWUP_SCHEME_PRONOUNS.search(clean_query))
                is_aspect = bool(FOLLOWUP_SCHEME_ASPECTS.search(clean_query))

                # If current turn is a clear follow-up about that scheme
                if is_pronoun or is_aspect:
                    return IntentResult(
                        intent=IntentType.SCHEME_INQUIRY,
                        confidence=0.90,
                        detected_scheme_id=s_id,
                        detected_scheme_name=s_name,
                        is_followup=True,
                        detected_language=detected_lang,
                    )
                # But if current turn is a greeting, small talk, or general question,
                # do NOT force the old scheme context!
                if is_greeting or is_gratitude or is_small_talk or is_gk_academic:
                    return IntentResult(
                        intent=IntentType.GENERAL_CONVERSATION,
                        confidence=0.95,
                        detected_language=detected_lang,
                    )

            # If previous context was general conversation and current query is a follow-up
            if last_was_general and not has_scheme_marker:
                # e.g., "can you give an example in python?", "why is that?", "explain more"
                if len(clean_query.split()) >= 2:
                    return IntentResult(
                        intent=IntentType.GENERAL_CONVERSATION,
                        confidence=0.88,
                        is_followup=True,
                        detected_language=detected_lang,
                    )

        # -------------------------------------------------------------------
        # Step 6: Ambiguous Query Interception
        # -------------------------------------------------------------------
        # Short, vague messages without context or gibberish
        if AMBIGUOUS_VAGUE_PATTERNS.match(clean_query) or (len(clean_query) < 12 and len(clean_query.split()) == 1 and not is_greeting and not is_gratitude):
            return IntentResult(
                intent=IntentType.AMBIGUOUS,
                confidence=0.5,
                clarification_prompt=None,  # Handled by ConversationalHandler
                detected_language=detected_lang,
            )

        # -------------------------------------------------------------------
        # Step 7: Safe Default (Never treat every unknown phrase as scheme query)
        # -------------------------------------------------------------------
        # If no scheme indicator was found, route to general conversation!
        return IntentResult(
            intent=IntentType.GENERAL_CONVERSATION,
            confidence=0.75,
            detected_language=detected_lang,
        )
