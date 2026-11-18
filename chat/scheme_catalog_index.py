"""Data-driven scheme catalog indexing and typo-tolerant matching for SahayAI.

Dynamically indexes government schemes from the scheme registry (data/schemes/schemes.json)
or an in-memory list, supporting fuzzy matching, typo tolerance, criteria extraction,
and multilingual recognition across English, Hindi, and Telugu.
"""

import difflib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMES_FILE = PROJECT_ROOT / "data" / "schemes" / "schemes.json"
DEFAULT_CENTRAL_SCHEMES_FILE = PROJECT_ROOT / "data" / "schemes" / "central_schemes.json"


class SchemeCatalogIndex:
    """Dynamic catalog index for government schemes supporting typo tolerance and discovery."""

    def __init__(
        self,
        schemes_file: Optional[Path] = None,
        schemes_data: Optional[List[Dict[str, Any]]] = None,
    ):
        self.schemes_file = Path(schemes_file) if schemes_file else DEFAULT_SCHEMES_FILE
        self._schemes: List[Dict[str, Any]] = []
        self._scheme_id_map: Dict[str, Dict[str, Any]] = {}
        # List of (scheme_id, canonical_name, [aliases])
        self._aliases: List[Tuple[str, str, List[str]]] = []
        # Pre-tokenized keywords for fuzzy / typo comparison: list of (scheme_id, canonical_name, keyword)
        self._scheme_keywords: List[Tuple[str, str, str]] = []

        if schemes_data is not None:
            self._index_schemes(schemes_data)
        else:
            self.reload()

    def reload(self, new_data: Optional[List[Dict[str, Any]]] = None) -> None:
        """Reloads and indexes scheme records from files or provided list."""
        if new_data is not None:
            self._index_schemes(new_data)
            return

        combined_schemes: List[Dict[str, Any]] = []
        if self.schemes_file.exists():
            try:
                with open(self.schemes_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        combined_schemes.extend(data)
                    else:
                        logger.error("Invalid schemes file format: expected list")
            except Exception as exc:
                logger.error("Failed to load schemes catalog: %s", exc)

        if DEFAULT_CENTRAL_SCHEMES_FILE.exists():
            try:
                with open(DEFAULT_CENTRAL_SCHEMES_FILE, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    if isinstance(cdata, list):
                        existing_ids = {s.get("scheme_id") for s in combined_schemes}
                        for cs in cdata:
                            if cs.get("scheme_id") not in existing_ids:
                                combined_schemes.append(cs)
            except Exception as exc:
                logger.error("Failed to load central schemes catalog: %s", exc)

        if combined_schemes:
            self._index_schemes(combined_schemes)
        else:
            self._schemes = []

    def _index_schemes(self, schemes: List[Dict[str, Any]]) -> None:
        """Indexes scheme metadata, canonical aliases, and distinctive keywords."""
        self._schemes = schemes
        self._scheme_id_map.clear()
        self._aliases.clear()
        self._scheme_keywords.clear()

        # Stopwords to exclude from fuzzy token matching (including demographic/generic attributes)
        stopwords = {
            "scheme", "scholarship", "schemes", "for", "and", "the", "students", "student",
            "education", "central", "sector", "all", "india", "council", "technical",
            "national", "portal", "government", "ministry", "department", "degree", "diploma",
            "aicte", "girl", "girls", "female", "women", "orphan", "orphans", "disabled",
            "disability", "specially", "abled", "handicap", "divyang", "caste", "scheduled",
            "class", "classes", "merit", "meritorious", "higher", "financial", "assistance",
            "support", "empowerment", "welfare", "college", "university", "fresh", "renewal",
            "online", "first", "second", "lateral", "entry", "approved", "institutions",
            "what", "when", "where", "which", "who", "whom", "how", "can", "could", "would",
            "about", "apply", "eligible", "eligibility", "details", "information",
        }

        # Distinctive multi-word core phrases for each scheme (excluding generic "scholarship"/"scheme")
        self._multiword_phrases: List[Tuple[str, str, str]] = [
            ("SCHEME_EDU_001_PM_USP_CSSS", "PM-USP Central Sector Scholarship Scheme", "central sector"),
            ("SCHEME_EDU_001_PM_USP_CSSS", "PM-USP Central Sector Scholarship Scheme", "pm usp"),
            ("SCHEME_EDU_001_PM_USP_CSSS", "PM-USP Central Sector Scholarship Scheme", "pm-usp csss"),
            ("SCHEME_EDU_005_TOP_CLASS_SC", "Top Class Education Scheme for SC Students", "top class"),
            ("SCHEME_EDU_005_TOP_CLASS_SC", "Top Class Education Scheme for SC Students", "top class sc"),
            ("SCHEME_EDU_005_TOP_CLASS_SC", "Top Class Education Scheme for SC Students", "top class education"),
            ("SCHEME_AGRI_001_PM_KISAN", "PM-KISAN Samman Nidhi", "pm kisan"),
            ("SCHEME_AGRI_001_PM_KISAN", "PM-KISAN Samman Nidhi", "kisan samman"),
            ("SCHEME_MSME_001_PMEGP", "Prime Minister's Employment Generation Programme (PMEGP)", "pmegp"),
            ("SCHEME_MSME_001_PMEGP", "Prime Minister's Employment Generation Programme (PMEGP)", "employment generation"),
            ("SCHEME_URBAN_001_PM_SVANIDHI", "PM SVANidhi", "pm svanidhi"),
            ("SCHEME_URBAN_001_PM_SVANIDHI", "PM SVANidhi", "svanidhi"),
            ("SCHEME_URBAN_001_PM_SVANIDHI", "PM SVANidhi", "street vendor"),
            ("SCHEME_LABOUR_001_PM_SYM", "PM Shram Yogi Maandhan (PM-SYM)", "shram yogi"),
            ("SCHEME_LABOUR_001_PM_SYM", "PM Shram Yogi Maandhan (PM-SYM)", "pm sym"),
            ("SCHEME_WOMEN_001_PMUY_2", "Pradhan Mantri Ujjwala Yojana (PMUY / Ujjwala 2.0)", "pm ujjwala"),
            ("SCHEME_WOMEN_001_PMUY_2", "Pradhan Mantri Ujjwala Yojana (PMUY / Ujjwala 2.0)", "ujjwala yojana"),
            ("SCHEME_WOMEN_001_PMUY_2", "Pradhan Mantri Ujjwala Yojana (PMUY / Ujjwala 2.0)", "ujjwala 2.0"),
        ]

        # Known multilingual and domain aliases per standard scheme IDs
        builtin_aliases = {
            "SCHEME_EDU_001_PM_USP_CSSS": [
                "pm-usp csss", "pm usp", "pmusp", "csss", "central sector scheme",
                "central sector scholarship", "pm uchchatar shiksha protsahan",
                "केंद्रीय क्षेत्र छात्रवृत्ति", "पीएम यूएसपी", "सीएसएसएस",
                "పీఎం యూఎస్‌పీ", "సిఎస్ఎస్ఎస్", "సెంట్రల్ సెక్టార్",
            ],
            "SCHEME_EDU_002_AICTE_PRAGATI": [
                "aicte pragati", "pragati scholarship", "pragati", "pragati scheme",
                "pragati for girls", "girl technical scholarship",
                "एआईसीटीई प्रगति", "प्रगति छात्रवृत्ति", "प्रगति",
                "ఏఐసీటీఈ ప్రగతి", "ప్రగతి స్కాలర్‌షిప్", "ప్రగతి",
            ],
            "SCHEME_EDU_003_AICTE_SAKSHAM": [
                "aicte saksham", "saksham scholarship", "saksham", "saksham scheme",
                "specially-abled scholarship", "disability scholarship aicte",
                "एआईसीटीई सक्षम", "सक्षम छात्रवृत्ति", "सक्षम",
                "ఏఐసీటీఈ సక్షమ్", "ఏఐసీటీఈ సక్షం", "సక్షమ్", "సక్షం",
            ],
            "SCHEME_EDU_004_AICTE_SWANATH": [
                "aicte swanath", "swanath scholarship", "swanath", "swanath scheme",
                "orphan scholarship aicte", "swanath for orphans",
                "एआईसीटीई स्वनाथ", "स्वनाथ छात्रवृत्ति", "स्वनाथ",
                "ఏఐసీటీఈ స్వానాథ్", "స్వానాథ్ స్కాలర్‌షిప్", "స్వానాథ్",
            ],
            "SCHEME_EDU_005_TOP_CLASS_SC": [
                "top class education for sc students", "top class sc", "top class education",
                "top class scholarship", "sc top class",
                "एससी टॉप क्लास", "टॉप क्लास शिक्षा",
                "టాప్ క్లాస్ ఎడ్యుకేషన్", "టాప్ క్లాస్ ఎస్సీ",
            ],
            "SCHEME_AGRI_001_PM_KISAN": [
                "pm kisan", "pm-kisan", "pmkisan", "kisan samman nidhi", "pm kisan samman nidhi",
                "पीएम किसान", "किसान सम्मान निधि", "पीएम-किसान",
                "పీఎం కిసాన్", "పీఎం-కిసాన్", "కిసాన్ సమ్మాన్ నిధి",
            ],
            "SCHEME_MSME_001_PMEGP": [
                "pmegp", "pm employment generation programme", "prime minister employment generation",
                "kvic loan", "pmegp subsidy",
                "पीएमईजीपी", "प्रधानमंत्री रोजगार सृजन कार्यक्रम",
                "పీఎంఈజీపీ", "ప్రధాన మంత్రి ఉపాధి కల్పన పథకం",
            ],
            "SCHEME_URBAN_001_PM_SVANIDHI": [
                "pm svanidhi", "svanidhi", "street vendor loan", "street vendors atmanirbhar nidhi",
                "pm street vendor", "svanidhi se samriddhi",
                "पीएम स्वनिधि", "स्वनिधि योजना", "स्ट्रीट वेंडर योजना",
                "పీఎం స్వనిధి", "స్వనిధి", "వీధి వ్యాపారుల రుణం",
            ],
            "SCHEME_LABOUR_001_PM_SYM": [
                "pm sym", "pm-sym", "pmsym", "shram yogi maandhan", "pradhan mantri shram yogi",
                "unorganized workers pension", "shram yogi pension",
                "पीएम श्रम योगी मानधन", "श्रम योगी मानधन", "पीएम-एसवाईएम",
                "పీఎం శ్రమ యోగి మాన్‌ధన్", "శ్రమ యోగి పెన్షన్", "పీఎం-ఎస్‌వైఎం",
            ],
            "SCHEME_WOMEN_001_PMUY_2": [
                "pmuy", "pmuy 2.0", "pmuy 2", "ujjwala", "ujjwala yojana", "pm ujjwala yojana",
                "free gas cylinder", "lpg connection scheme", "ujjwala 2.0",
                "प्रधानमंत्री उज्ज्वला योजना", "उज्ज्वला योजना", "उज्ज्वला 2.0",
                "ప్రధాన మంత్రి ఉజ్జ్వల యోజన", "ఉజ్జ్వల పథకం", "ఉజ్జ్వల 2.0", "గ్యాస్ కనెక్షన్ పథకం",
            ],
        }

        for s in schemes:
            s_id = s.get("scheme_id")
            if not s_id:
                continue

            self._scheme_id_map[s_id] = s
            s_name = s.get("scheme_name") or s_id
            official_name = s.get("current_official_name") or s_name

            aliases = [s_name.lower(), official_name.lower()]
            if s_id in builtin_aliases:
                aliases.extend([a.lower() for a in builtin_aliases[s_id]])

            # Add distinct multi-word aliases from official name
            short_id_alias = re.sub(r"^scheme_[a-z]+_\d+_", "", s_id.lower()).replace("_", " ")
            aliases.append(short_id_alias)

            self._aliases.append((s_id, s_name, list(set(aliases))))

            # Extract distinctive single keywords for typo/fuzzy matching
            distinctive_tokens: Set[str] = set()
            for text_val in [s_name, official_name]:
                clean_text = re.sub(r"[^\w\s-]", " ", text_val)
                for w in clean_text.split():
                    w_lower = w.lower().strip("-")
                    if len(w_lower) >= 4 and w_lower not in stopwords and not w_lower.isdigit():
                        distinctive_tokens.add(w_lower)

            # Add predefined core keys for highest reliability
            if "PRAGATI" in s_id.upper():
                distinctive_tokens.add("pragati")
            elif "SAKSHAM" in s_id.upper():
                distinctive_tokens.add("saksham")
            elif "SWANATH" in s_id.upper():
                distinctive_tokens.add("swanath")
            elif "CSSS" in s_id.upper():
                distinctive_tokens.add("pmusp")
                distinctive_tokens.add("csss")
            elif "TOP_CLASS" in s_id.upper():
                distinctive_tokens.add("topclass")
            elif "KISAN" in s_id.upper():
                distinctive_tokens.add("pmkisan")
                distinctive_tokens.add("kisan")
            elif "PMEGP" in s_id.upper():
                distinctive_tokens.add("pmegp")
            elif "SVANIDHI" in s_id.upper():
                distinctive_tokens.add("pmsvanidhi")
                distinctive_tokens.add("svanidhi")
            elif "SYM" in s_id.upper():
                distinctive_tokens.add("shramyogi")
                distinctive_tokens.add("pmsym")
            elif "PMUY" in s_id.upper():
                distinctive_tokens.add("ujjwala")
                distinctive_tokens.add("pmuy")

            for token in distinctive_tokens:
                self._scheme_keywords.append((s_id, s_name, token))

    def get_all_schemes(self) -> List[Dict[str, Any]]:
        """Returns all registered schemes in the catalog."""
        return list(self._schemes)

    def get_scheme_by_id(self, scheme_id: str) -> Optional[Dict[str, Any]]:
        """Returns a scheme record by ID."""
        return self._scheme_id_map.get(scheme_id)

    def match_scheme_by_name(self, text: str) -> Optional[Tuple[str, str, float]]:
        """Identifies if a query mentions a registered scheme, with typo tolerance.

        Returns:
            Tuple of (scheme_id, canonical_scheme_name, confidence_score) or None.
        """
        if not text or not text.strip():
            return None

        clean_text = text.lower().strip()

        # 1. Exact or substring alias match (high confidence)
        for s_id, s_name, aliases in self._aliases:
            for alias in aliases:
                # Word-boundary or exact containment for non-trivial aliases
                pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
                if re.search(pattern, clean_text, re.IGNORECASE):
                    return s_id, s_name, 1.0

        # 2. Distinctive multi-word phrase matching with typo tolerance (e.g. "top clas" -> "top class")
        raw_words = [w for w in re.split(r"[\s\-_,.:;!?]+", clean_text) if w]

        best_match: Optional[Tuple[str, str, float]] = None
        highest_score = 0.0

        if len(raw_words) >= 2 and hasattr(self, "_multiword_phrases"):
            for i in range(len(raw_words) - 1):
                # 2-word phrase
                phrase2 = f"{raw_words[i]} {raw_words[i+1]}"
                for s_id, s_name, core_phrase in self._multiword_phrases:
                    if abs(len(phrase2) - len(core_phrase)) <= 3:
                        ratio = difflib.SequenceMatcher(None, phrase2, core_phrase).ratio()
                        if ratio >= 0.85 and ratio > highest_score:
                            highest_score = ratio
                            best_match = (s_id, s_name, ratio)

                # 3-word phrase if available
                if i + 2 < len(raw_words):
                    phrase3 = f"{raw_words[i]} {raw_words[i+1]} {raw_words[i+2]}"
                    for s_id, s_name, core_phrase in self._multiword_phrases:
                        if abs(len(phrase3) - len(core_phrase)) <= 3:
                            ratio = difflib.SequenceMatcher(None, phrase3, core_phrase).ratio()
                            if ratio >= 0.85 and ratio > highest_score:
                                highest_score = ratio
                                best_match = (s_id, s_name, ratio)

        if best_match and highest_score >= 0.85:
            return best_match

        # 3. Single-token fuzzy matching against indexed distinctive scheme keywords
        words = [w.strip() for w in raw_words if len(w) >= 4]

        for word in words:
            # Check against indexed scheme keywords
            for s_id, s_name, keyword in self._scheme_keywords:
                # Direct match
                if word == keyword:
                    return s_id, s_name, 0.98

                # Compute similarity ratio for words of comparable length
                if abs(len(word) - len(keyword)) <= 2:
                    ratio = difflib.SequenceMatcher(None, word, keyword).ratio()
                    # Minimum threshold for typo tolerance (e.g. prgati->pragati=0.91, sakshm->saksham=0.92)
                    if ratio >= 0.82 and ratio > highest_score:
                        highest_score = ratio
                        best_match = (s_id, s_name, ratio)

        if best_match and highest_score >= 0.82:
            return best_match

        return None

    def discover_schemes(self, text: str) -> Tuple[List[str], Dict[str, Any]]:
        """Extracts user attributes and returns matching candidate scheme IDs from the catalog.

        Returns:
            Tuple of (list_of_candidate_scheme_ids, extracted_criteria_dict).
        """
        clean_text = text.lower()
        criteria: Dict[str, Any] = {}
        candidate_ids: List[str] = []

        # 1. Degree / Technical education
        if re.search(r"\b(?:btech|b\.tech|be|b\.e|engineering|diploma|polytechnic|technical)\b", clean_text):
            criteria["education_level"] = "technical_degree"

        # 2. Gender (female / girl student)
        if re.search(r"\b(?:girl|girls|female|women|woman|ammayi|ammayilaki|ladki|ladkiyon|beti|mahila)\b", clean_text):
            criteria["gender"] = "female"

        # 3. Specially-abled / Disability
        if re.search(r"\b(?:disabled|disability|specially-abled|divyang|handicap|pwd|blind|locomotor|hearing)\b", clean_text):
            criteria["disability"] = True

        # 4. Orphan / Vulnerable
        if re.search(r"\b(?:orphan|orphans|parents deceased|father died|mother died|covid orphan|anath)\b", clean_text):
            criteria["orphan"] = True

        # 5. Social Category (SC, ST, OBC, EWS)
        if re.search(r"\b(?:sc|scheduled caste|dalit)\b", clean_text):
            criteria["category"] = "SC"
        elif re.search(r"\b(?:st|scheduled tribe|adivasi)\b", clean_text):
            criteria["category"] = "ST"
        elif re.search(r"\b(?:obc|other backward)\b", clean_text):
            criteria["category"] = "OBC"
        elif re.search(r"\b(?:ews|economically weaker)\b", clean_text):
            criteria["category"] = "EWS"

        # 6. Occupation and Livelihoods (Farmers, Vendors, Unorganized Workers, MSME)
        if re.search(r"\b(?:farmer|farmers|kisan|cultivator|rythu|raitu|kisanon|kheti)\b", clean_text):
            criteria["occupation"] = "farmer"
        elif re.search(r"\b(?:street\s+vendor|vendor|hawker|thela|rehri|vyapari|peddler)\b", clean_text):
            criteria["occupation"] = "vendor"
        elif re.search(r"\b(?:unorganized|shramik|mazdoor|daily\s+wage|laborer|labourer|driver|rickshaw)\b", clean_text):
            criteria["occupation"] = "unorganized"
        elif re.search(r"\b(?:micro\s+enterprise|business\s+loan|startup|msme|self\s+employed|new\s+business|vyapar)\b", clean_text):
            criteria["occupation"] = "entrepreneur"
        elif re.search(r"\b(?:gas\s+cylinder|lpg|cooking\s+gas|chulha|free\s+cylinder)\b", clean_text):
            criteria["welfare_need"] = "lpg"

        # 7. Match extracted criteria against all indexed schemes in catalog
        for scheme in self._schemes:
            s_id = scheme.get("scheme_id", "")
            elig = scheme.get("eligibility", {})
            target_ben = " ".join(scheme.get("target_beneficiaries", [])).lower()
            name_desc = (scheme.get("scheme_name", "") + " " + scheme.get("scheme_description", "")).lower()

            match = False

            # Check Farmer scheme
            if criteria.get("occupation") == "farmer" and ("kisan" in s_id.lower() or "farmer" in target_ben):
                match = True

            # Check Street vendor scheme
            if criteria.get("occupation") == "vendor" and ("svanidhi" in s_id.lower() or "vendor" in target_ben):
                match = True

            # Check Unorganized worker scheme
            if criteria.get("occupation") == "unorganized" and ("sym" in s_id.lower() or "unorganized" in target_ben):
                match = True

            # Check Entrepreneur / PMEGP scheme
            if criteria.get("occupation") == "entrepreneur" and ("pmegp" in s_id.lower() or "employment" in name_desc):
                match = True

            # Check LPG / PMUY scheme
            if (criteria.get("welfare_need") == "lpg" or (criteria.get("gender") == "female" and "gas" in clean_text)) and "pmuy" in s_id.lower():
                match = True

            # Check Girl / Female technical scheme
            if criteria.get("gender") == "female":
                if "girl" in target_ben or elig.get("gender") == "FEMALE" or "pragati" in s_id.lower():
                    match = True

            # Check Specially-abled / Disability scheme
            if criteria.get("disability"):
                if "disab" in target_ben or "specially-abled" in target_ben or "saksham" in s_id.lower() or elig.get("disability_requirement"):
                    match = True

            # Check Orphan scheme
            if criteria.get("orphan"):
                if "orphan" in target_ben or "swanath" in s_id.lower():
                    match = True

            # Check SC Category scheme
            if criteria.get("category") == "SC":
                if "sc" in s_id.lower() or "scheduled caste" in target_ben or "top class" in s_id.lower():
                    match = True

            # Check General technical student if no specific demographic was given
            if criteria.get("education_level") == "technical_degree" and not any([
                criteria.get("gender"), criteria.get("disability"), criteria.get("orphan"), criteria.get("category")
            ]):
                if "aicte" in s_id.lower() or "technical" in name_desc:
                    match = True

            if match and s_id not in candidate_ids:
                candidate_ids.append(s_id)

        # If no specific criteria matched but it's an inquiry about general college scholarships:
        if not candidate_ids and re.search(r"\b(?:college|university|12th|merit|low income|graduation)\b", clean_text):
            for s in self._schemes:
                if "csss" in s.get("scheme_id", "").lower() or "central sector" in s.get("scheme_name", "").lower():
                    candidate_ids.append(s.get("scheme_id"))

        return candidate_ids, criteria
