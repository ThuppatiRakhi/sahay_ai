"""
tests/test_query_rewriter.py — Unit tests for multilingual query rewriting subsystem.

Tests cover:
- English scheme name recognition
- Hindi scheme name recognition
- Telugu scheme name recognition
- Mixed-language queries
- Queries without scheme names
- Income-related terminology expansion
- Disability-related terminology expansion
- Original query preservation
- Negative constraint: No invented eligibility conditions or numbers
- Unknown scheme names handling
- EmbeddingService prefix compatibility (no double-prefixing)
"""

import pytest
from rag.query_rewriter import QueryRewriter, RewrittenQuery, DictionaryRewritingProvider
from rag.embedding_service import EmbeddingService


@pytest.fixture
def rewriter():
    return QueryRewriter()


# ---------------------------------------------------------------------------
# Section 1: Scheme Entity Recognition Tests
# ---------------------------------------------------------------------------

class TestSchemeEntityRecognition:
    """Verifies that English, Hindi, and Telugu scheme names map to canonical IDs."""

    @pytest.mark.parametrize(
        "query, expected_scheme_id",
        [
            # English scheme names
            ("What are the guidelines for AICTE Pragati scholarship?", "SCHEME_EDU_002_AICTE_PRAGATI"),
            ("Who can apply for AICTE Saksham scholarship?", "SCHEME_EDU_003_AICTE_SAKSHAM"),
            ("Eligibility for AICTE Swanath scheme", "SCHEME_EDU_004_AICTE_SWANATH"),
            ("How to apply for PM-USP CSSS college scholarship?", "SCHEME_EDU_001_PM_USP_CSSS"),
            ("Top Class Education Scheme for SC Students benefits", "SCHEME_EDU_005_TOP_CLASS_SC"),

            # Hindi scheme names
            ("सक्षम छात्रवृत्ति के लिए पात्रता क्या है?", "SCHEME_EDU_003_AICTE_SAKSHAM"),
            ("एआईसीटीई प्रगति छात्रवृत्ति में कितनी राशि मिलती है?", "SCHEME_EDU_002_AICTE_PRAGATI"),
            ("स्वानाथ छात्रवृत्ति के लिए कौन पात्र है?", "SCHEME_EDU_004_AICTE_SWANATH"),
            ("पीएम-यूएसपी छात्रवृत्ति योजना के नियम", "SCHEME_EDU_001_PM_USP_CSSS"),
            ("टॉप क्लास एससी छात्रवृत्ति आवेदन", "SCHEME_EDU_005_TOP_CLASS_SC"),

            # Telugu scheme names
            ("AICTE సక్షమ్ స్కాలర్‌షిప్ అర్హతలు ఏమిటి?", "SCHEME_EDU_003_AICTE_SAKSHAM"),
            ("ప్రగతి స్కాలర్‌షిప్ పథకం ఎవరికి వర్తిస్తుంది?", "SCHEME_EDU_002_AICTE_PRAGATI"),
            ("స్వానాథ్ స్కాలర్‌షిప్ కోసం ఎలా దరఖాస్తు చేయాలి?", "SCHEME_EDU_004_AICTE_SWANATH"),
            ("పీఎం-యూఎస్‌పీ సెంట్రల్ సెక్టార్ స్కాలర్‌షిప్ వివరాలు", "SCHEME_EDU_001_PM_USP_CSSS"),
            ("టాప్ క్లాస్ ఎస్సీ స్కాలర్‌షిప్ మొత్తం ఎంత?", "SCHEME_EDU_005_TOP_CLASS_SC"),

            # Mixed-language queries
            ("AICTE सक्षम scholarship eligibility", "SCHEME_EDU_003_AICTE_SAKSHAM"),
            ("AICTE ప్రగతి scholarship for girls", "SCHEME_EDU_002_AICTE_PRAGATI"),
            ("AICTE స్వానాథ్ scheme guidelines", "SCHEME_EDU_004_AICTE_SWANATH"),
        ],
    )
    def test_scheme_entity_recognition(self, rewriter, query, expected_scheme_id):
        result = rewriter.rewrite(query)
        assert result.detected_scheme_id == expected_scheme_id
        assert expected_scheme_id in rewriter.detect_scheme_intent(query)

    def test_unknown_scheme_name_returns_none(self, rewriter):
        """Unknown or unindexed schemes must not be forced to an ID."""
        queries = [
            "What is the eligibility for National Means cum Merit Scholarship?",
            "How to apply for Post Matric Scholarship for OBC?",
            "राज्य सरकार की मेधावी छात्र योजना",
            "ఆంధ్రప్రదేశ్ విద్యా దీవెన పథకం",
        ]
        for q in queries:
            result = rewriter.rewrite(q)
            assert result.detected_scheme_id is None

    def test_queries_without_scheme_names(self, rewriter):
        """Situational queries without explicit schemes must return detected_scheme_id=None."""
        situational_queries = [
            "Scholarships available for girl students in engineering",
            "Financial aid for students with benchmark disabilities",
            "अनाथ बच्चों के लिए कॉलेज की फीस में सहायता",
            "వికలాంగ విద్యార్థులకు ఏ ప్రభుత్వ స్కాలర్‌షిప్ సహాయం ఉంది?",
        ]
        for q in situational_queries:
            result = rewriter.rewrite(q)
            assert result.detected_scheme_id is None


# ---------------------------------------------------------------------------
# Section 2: Multilingual Terminology Normalization Tests
# ---------------------------------------------------------------------------

class TestTerminologyNormalization:
    """Verifies that cross-lingual technical concepts trigger canonical expansions."""

    def test_income_related_terminology(self, rewriter):
        # English
        res_en = rewriter.rewrite("What is the family income limit for scholarship?")
        assert "family income" in res_en.rewritten_query.lower()
        assert "parental income" in res_en.rewritten_query.lower()

        # Hindi
        res_hi = rewriter.rewrite("छात्रवृत्ति के लिए वार्षिक पारिवारिक आय सीमा कितनी है?")
        assert "family income" in res_hi.rewritten_query.lower()
        assert "ceiling limit" in res_hi.rewritten_query.lower()

        # Telugu
        res_te = rewriter.rewrite("కుటుంబ వార్షిక ఆదాయ పరిమితి ఎంత?")
        assert "family income" in res_te.rewritten_query.lower()
        assert "annual" in res_te.rewritten_query.lower()

    def test_disability_related_terminology(self, rewriter):
        # English
        res_en = rewriter.rewrite("Requirements for students with physical handicap")
        assert "specially-abled" in res_en.rewritten_query.lower()
        assert "benchmark disability" in res_en.rewritten_query.lower()

        # Hindi
        res_hi = rewriter.rewrite("दिव्यांग छात्रों के लिए न्यूनतम दिव्यांगता प्रतिशत")
        assert "specially-abled" in res_hi.rewritten_query.lower()
        assert "disability" in res_hi.rewritten_query.lower()

        # Telugu
        res_te = rewriter.rewrite("వికలాంగ విద్యార్థులకు నిబంధనలు")
        assert "disability" in res_te.rewritten_query.lower()

    def test_girl_students_terminology(self, rewriter):
        res_hi = rewriter.rewrite("तकनीकी शिक्षा में पढ़ने वाली छात्राओं के लिए सहायता")
        assert "girl students" in res_hi.rewritten_query.lower()

        res_te = rewriter.rewrite("ఇంజనీరింగ్ చదివే బాలికలకు స్కాలర్‌షిప్")
        assert "girl students" in res_te.rewritten_query.lower()

    def test_orphan_students_terminology(self, rewriter):
        res_en = rewriter.rewrite("Scholarships for students who lost both parents in covid")
        assert "orphan students" in res_en.rewritten_query.lower()
        assert "covid-19" in res_en.rewritten_query.lower()

        res_hi = rewriter.rewrite("अनाथ बच्चों के लिए इंजीनियरिंग फीस सहायता")
        assert "orphan students" in res_hi.rewritten_query.lower()

    def test_documents_terminology(self, rewriter):
        res_hi = rewriter.rewrite("आवेदन के लिए कौन सा प्रमाण पत्र आवश्यक है?")
        assert "required documents" in res_hi.rewritten_query.lower()
        assert "certificate" in res_hi.rewritten_query.lower()


# ---------------------------------------------------------------------------
# Section 3: Original Query Preservation and Non-Invention Tests
# ---------------------------------------------------------------------------

class TestPreservationAndSafety:
    """Verifies that original queries are strictly preserved and no policy rules are invented."""

    def test_original_query_preserved_exactly(self, rewriter):
        test_queries = [
            "What is the family income limit?",
            "सक्षम छात्रवृत्ति के लिए आवश्यक दस्तावेज",
            "ప్రగతి స్కాలర్‌షిప్ ఎలా దరఖాస్తు చేయాలి?",
        ]
        for q in test_queries:
            result = rewriter.rewrite(q)
            assert result.original_query == q
            assert result.rewritten_query.startswith(q)

    def test_no_invented_eligibility_conditions_or_numbers(self, rewriter):
        """The rewriter must NOT inject specific rupee limits (e.g. 8 lakh, 4.5 lakh) or percentages (e.g. 40%)."""
        neutral_queries = [
            "What is the family income ceiling for CSSS?",
            "सक्षम छात्रवृत्ति के लिए आय सीमा कितनी है?",
            "స్వానాథ్ పథకానికి ఆదాయ పరిమితి ఎంత?",
            "What is the disability percentage for Saksham?",
            "दिव्यांगता प्रतिशत कितना होना चाहिए?",
        ]
        for q in neutral_queries:
            result = rewriter.rewrite(q)
            # Ensure specific factual numbers were not fabricated/injected by the rewriter
            assert "8 lakh" not in result.rewritten_query.lower()
            assert "4.5 lakh" not in result.rewritten_query.lower()
            assert "8,00,000" not in result.rewritten_query
            assert "40%" not in result.rewritten_query
            assert "40 percent" not in result.rewritten_query.lower()

    def test_empty_query_raises_value_error(self, rewriter):
        with pytest.raises(ValueError):
            rewriter.rewrite("")
        with pytest.raises(ValueError):
            rewriter.rewrite("   ")


# ---------------------------------------------------------------------------
# Section 4: E5 Embedding Compatibility Tests
# ---------------------------------------------------------------------------

class TestEmbeddingCompatibility:
    """Verifies that rewritten queries do not have 'query: ' prefix so that EmbeddingService does not double-prefix."""

    def test_no_double_prefixing(self, rewriter):
        queries = [
            "What is the Pragati income limit?",
            "सक्षम छात्रवृत्ति पात्रता",
            "స్వానాథ్ దరఖాస్తు విధానం",
        ]
        for q in queries:
            result = rewriter.rewrite(q)
            # Must NOT begin with 'query: '
            assert not result.rewritten_query.startswith("query: ")
            assert not result.rewritten_query.startswith("passage: ")

    def test_compatibility_with_mock_embedding_service(self, rewriter):
        """Rewritten query should smoothly pass through EmbeddingService without error."""
        svc = EmbeddingService(use_mock=True)
        res = rewriter.rewrite("सक्षम छात्रवृत्ति के लिए आय सीमा")
        vec = svc.embed_query(res.rewritten_query)
        assert isinstance(vec, list)
        assert len(vec) == 384

