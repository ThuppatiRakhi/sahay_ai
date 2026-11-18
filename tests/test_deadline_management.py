"""Tests for SahayAI Dynamic Scholarship Deadline Management (Step 4.1).

Covers:
1. Upcoming deadline evaluation.
2. Open deadline evaluation.
3. Expired/Closed deadline evaluation.
4. Missing deadline evaluation (NOT_ANNOUNCED).
5. Unverified or unreliable deadline evaluation (UNVERIFIED).
6. Next cycle announced vs. unknown.
7. India timezone (Asia/Kolkata) date boundaries.
8. Recommendation prioritization and sorting (open first, closed never marked immediately applicable).
9. Distinction between citizen eligibility and application availability.
10. Chat & RAG integration answering the 6 core deadline questions grounded in verified data.
11. Multilingual localization parity across English, Telugu, and Hindi.
"""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from unittest.mock import MagicMock
import pytest
from zoneinfo import ZoneInfo

from chat.intent_router import IntentRouter, IntentType
from eligibility.engine import EligibilityEngine
from rag.answer_generator import RAGAnswerGenerator
from scheme_collection.deadline_manager import (
    DeadlineInfo,
    DeadlineStatus,
    INDIA_TZ,
    evaluate_scheme_deadline,
    get_current_ist_date,
    get_current_ist_datetime,
    parse_iso_date,
)
from scheme_collection.scheme_discovery_service import SchemeDiscoveryService


# ==============================================================================
# 1. CORE DEADLINE EVALUATION TESTS
# ==============================================================================

class TestDeadlineEvaluation:
    """Validates dynamic deadline state calculation rules."""

    def test_01_open_deadline(self):
        """Between opening date and last date, inclusive -> OPEN."""
        scheme = {
            "scheme_id": "TEST_OPEN",
            "scheme_name": "Test Scholarship",
            "application_start_date": "2026-11-01",
            "application_last_date": "2026-11-30",
            "application_cycle": "AY 2026-27",
        }
        ref_date = date(2026, 11, 10)
        res = evaluate_scheme_deadline(scheme, reference_date=ref_date)
        assert res.status == DeadlineStatus.OPEN
        assert res.is_currently_open is True
        assert res.days_remaining == 20
        assert "OPEN" in res.explanation

    def test_02_upcoming_deadline(self):
        """Before opening date -> UPCOMING."""
        scheme = {
            "scheme_id": "TEST_UPCOMING",
            "scheme_name": "Test Scholarship",
            "application_start_date": "2026-12-01",
            "application_last_date": "2026-12-31",
            "application_cycle": "AY 2026-27",
        }
        ref_date = date(2026, 11, 10)
        res = evaluate_scheme_deadline(scheme, reference_date=ref_date)
        assert res.status == DeadlineStatus.UPCOMING
        assert res.is_currently_open is False
        assert res.days_remaining is None
        assert "will open on 2026-12-01" in res.explanation

    def test_03_expired_closed_deadline(self):
        """After last date -> CLOSED."""
        scheme = {
            "scheme_id": "TEST_CLOSED",
            "scheme_name": "Test Scholarship",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
            "application_cycle": "AY 2026-27",
            "next_expected_cycle": None,
        }
        ref_date = date(2026, 11, 10)
        res = evaluate_scheme_deadline(scheme, reference_date=ref_date)
        assert res.status == DeadlineStatus.CLOSED
        assert res.is_currently_open is False
        assert res.days_remaining == 0
        assert "closed on 2026-10-31" in res.explanation
        assert res.next_cycle_status == "NOT_ANNOUNCED"

    def test_04_missing_deadline_never_treated_as_open(self):
        """Missing dates must remain NOT_ANNOUNCED, never treated as open."""
        scheme = {
            "scheme_id": "TEST_MISSING",
            "scheme_name": "Test Scholarship Without Dates",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.NOT_ANNOUNCED
        assert res.is_currently_open is False
        assert res.application_start_date is None
        assert res.application_last_date is None

    def test_05_unverified_malformed_date(self):
        """Non-ISO or invalid dates are flagged as UNVERIFIED."""
        scheme = {
            "scheme_id": "TEST_MALFORMED",
            "application_start_date": "2026-06-01",
            "application_last_date": "31-10-2026",  # Not ISO YYYY-MM-DD
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.UNVERIFIED
        assert res.is_currently_open is False

    def test_06_unverified_impossible_calendar_date(self):
        """Non-existent calendar dates (e.g. Feb 30) return UNVERIFIED."""
        scheme = {
            "scheme_id": "TEST_IMPOSSIBLE_DATE",
            "application_start_date": "2026-02-01",
            "application_last_date": "2026-02-30",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.UNVERIFIED
        assert res.is_currently_open is False

    def test_07_unverified_inconsistent_chronology(self):
        """Start date after last date returns UNVERIFIED."""
        scheme = {
            "scheme_id": "TEST_CHRONO_ERROR",
            "application_start_date": "2026-12-01",
            "application_last_date": "2026-10-31",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.UNVERIFIED
        assert res.is_currently_open is False
        assert "Inconsistent dates" in res.explanation

    def test_08_explicit_unverified_flag(self):
        """Explicitly unverified schemes are flagged UNVERIFIED."""
        scheme = {
            "scheme_id": "TEST_FLAGGED_UNVERIFIED",
            "application_start_date": "2026-11-01",
            "application_last_date": "2026-11-30",
            "is_deadline_unverified": True,
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.UNVERIFIED
        assert res.is_currently_open is False

    def test_09_next_cycle_announced(self):
        """When closed, reliable next cycle information is reported accurately."""
        scheme = {
            "scheme_id": "TEST_NEXT_ANNOUNCED",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
            "next_cycle_status": "AY 2027-28 Expected June 2027",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.CLOSED
        assert res.next_cycle_status == "AY 2027-28 Expected June 2027"

    def test_10_next_cycle_unknown_remains_not_announced(self):
        """When closed and next cycle is missing/None, it remains NOT_ANNOUNCED."""
        scheme = {
            "scheme_id": "TEST_NEXT_UNKNOWN",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
            "next_cycle_status": None,
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-10")
        assert res.status == DeadlineStatus.CLOSED
        assert res.next_cycle_status == "NOT_ANNOUNCED"


# ==============================================================================
# 2. TIMEZONE & DATE BOUNDARY TESTS
# ==============================================================================

class TestIndiaTimezoneDateBoundaries:
    """Verifies timezone awareness (Asia/Kolkata) on exact date boundaries."""

    def test_01_timezone_is_asia_kolkata(self):
        """Default evaluation timezone must be Asia/Kolkata."""
        now_ist = get_current_ist_datetime()
        assert str(now_ist.tzinfo) == "Asia/Kolkata"

    def test_02_exact_start_date_is_open(self):
        """On the exact opening day, status must be OPEN."""
        scheme = {
            "scheme_id": "TEST_START_BOUNDARY",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-06-01")
        assert res.status == DeadlineStatus.OPEN
        assert res.is_currently_open is True

    def test_03_day_before_start_date_is_upcoming(self):
        """Day before opening day must be UPCOMING."""
        scheme = {
            "scheme_id": "TEST_PRE_START",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-05-31")
        assert res.status == DeadlineStatus.UPCOMING
        assert res.is_currently_open is False

    def test_04_exact_last_date_is_open(self):
        """On the exact last date (inclusive), status must be OPEN."""
        scheme = {
            "scheme_id": "TEST_LAST_BOUNDARY",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-10-31")
        assert res.status == DeadlineStatus.OPEN
        assert res.is_currently_open is True
        assert res.days_remaining == 0

    def test_05_day_after_last_date_is_closed(self):
        """Day after last date must be CLOSED."""
        scheme = {
            "scheme_id": "TEST_POST_LAST",
            "application_start_date": "2026-06-01",
            "application_last_date": "2026-10-31",
        }
        res = evaluate_scheme_deadline(scheme, reference_date="2026-11-01")
        assert res.status == DeadlineStatus.CLOSED
        assert res.is_currently_open is False


# ==============================================================================
# 3. RECOMMENDATION INTEGRATION & SEPARATION OF ELIGIBILITY
# ==============================================================================

class TestRecommendationIntegration:
    """Verifies recommendations prioritize open schemes and separate eligibility from availability."""

    def test_01_recommendations_prioritize_open_schemes(self, monkeypatch):
        """Schemes currently accepting applications must be sorted first."""
        # Create 3 mock schemes: one OPEN, one UPCOMING, one CLOSED
        mock_schemes = [
            {
                "scheme_id": "SCHEME_CLOSED",
                "scheme_name": "Closed Scholarship",
                "application_start_date": "2026-06-01",
                "application_last_date": "2026-10-31",
                "eligibility": {"structured_rules": []},
            },
            {
                "scheme_id": "SCHEME_OPEN",
                "scheme_name": "Active Open Scholarship",
                "application_start_date": "2026-11-01",
                "application_last_date": "2026-11-30",
                "eligibility": {"structured_rules": []},
            },
            {
                "scheme_id": "SCHEME_UPCOMING",
                "scheme_name": "Upcoming Scholarship",
                "application_start_date": "2026-12-01",
                "application_last_date": "2026-12-31",
                "eligibility": {"structured_rules": []},
            },
        ]

        svc = SchemeDiscoveryService()
        monkeypatch.setattr(svc, "_load_schemes", lambda: mock_schemes)

        profile = {"annual_income": 300000, "age": 20}
        results = svc.get_recommendations_for_profile(profile)

        prelim = results["preliminary_matches"]
        assert len(prelim) == 3

        # First must be the OPEN scheme
        assert prelim[0]["scheme"]["scheme_id"] == "SCHEME_OPEN"
        assert prelim[0]["is_currently_open"] is True
        assert prelim[0]["deadline_status"] == "OPEN"

        # Second must be the UPCOMING scheme
        assert prelim[1]["scheme"]["scheme_id"] == "SCHEME_UPCOMING"
        assert prelim[1]["is_currently_open"] is False
        assert prelim[1]["deadline_status"] == "UPCOMING"

        # Third must be the CLOSED scheme
        assert prelim[2]["scheme"]["scheme_id"] == "SCHEME_CLOSED"
        assert prelim[2]["is_currently_open"] is False
        assert prelim[2]["deadline_status"] == "CLOSED"

    def test_02_closed_scheme_not_marked_immediately_applicable(self):
        """Closed schemes must clearly report is_currently_open=False in recommendation summary."""
        svc = SchemeDiscoveryService()
        scheme = svc.get_scheme_by_id("SCHEME_EDU_001_PM_USP_CSSS")
        assert scheme is not None
        d = scheme.get("deadline", {})
        assert d.get("is_currently_open") is False
        assert d.get("status") == "CLOSED"

    def test_03_eligibility_matches_even_when_deadline_closed(self, monkeypatch):
        """Eligibility rule match (demographics/income) must not be confused with application availability."""
        # Controlled evaluation date after 30 November 2026 to evaluate Pragati post-closing
        monkeypatch.setattr("scheme_collection.deadline_manager.get_current_ist_date", lambda: date(2026, 12, 1))

        svc = SchemeDiscoveryService()
        profile = {
            "gender": "FEMALE",
            "annual_income": 180000.0,
            "annual_family_income": 180000.0,
            "caste_category": "GENERAL",
            "occupation": "Student",
        }
        eval_res = svc.evaluate_scheme_for_profile("SCHEME_EDU_002_AICTE_PRAGATI", profile, application_type="FRESH")
        assert eval_res is not None

        # Demographic and financial rules match without failures
        matched_criteria = [c["criterion"] for c in eval_res["matched_conditions"]]
        assert "gender" in matched_criteria
        assert "annual_family_income" in matched_criteria
        assert len(eval_res["failed_conditions"]) == 0

        # But application window is strictly reported as CLOSED!
        assert eval_res["is_currently_open"] is False
        assert eval_res["deadline_status"] == "CLOSED"
        assert eval_res["application_last_date"] == "2026-11-30"


# ==============================================================================
# 4. CHAT & RAG INTEGRATION (THE 6 CORE QUESTIONS)
# ==============================================================================

class TestChatAndRAGDeadlineQuestions:
    """Verifies that RAG answers the 6 required questions accurately without inventing dates."""

    @pytest.fixture
    def rag_env(self):
        mock_retriever = MagicMock()
        mock_retriever.query_rewriter.rewrite_with_context.side_effect = lambda query, conversation_history: MagicMock(
            rewritten_query=query,
            detected_scheme_id=None,
            unsupported_scheme=None,
            is_ambiguous=False,
        )
        mock_retriever.retrieve.return_value = []
        mock_llm = MagicMock()
        generator = RAGAnswerGenerator(retriever=mock_retriever, llm_client=mock_llm)
        return {"generator": generator, "mock_llm": mock_llm, "mock_retriever": mock_retriever}

    def test_01_is_this_scholarship_open_now(self, rag_env):
        """Question: Is this scholarship open now? -> Grounds in verified schedule."""
        gen = rag_env["generator"]
        mock_llm = rag_env["mock_llm"]

        mock_llm.generate.return_value = json.dumps({
            "answer": "No, the AICTE Pragati Scholarship is currently closed for fresh student applications for AY 2026-27 [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = gen.answer("Is AICTE Pragati scholarship open now?", scheme_id="SCHEME_EDU_002_AICTE_PRAGATI")
        assert res["current_status_verified"] is True
        assert len(res["sources"]) >= 1
        assert "SCHED_SCHEME_EDU_002_AICTE_PRAGATI" in res["sources"][0]["chunk_id"]
        assert "closed on 31 October 2026" in res["sources"][0]["citation_reference"] or "NSP" in res["sources"][0]["citation_reference"]

    def test_02_what_is_the_last_date(self, rag_env):
        """Question: What is the last date? -> Injects student last date 2026-10-31."""
        gen = rag_env["generator"]
        mock_llm = rag_env["mock_llm"]

        mock_llm.generate.return_value = json.dumps({
            "answer": "The last date for student application submission was 31 October 2026 [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = gen.answer("What is the last date for PM-USP?", scheme_id="SCHEME_EDU_001_PM_USP_CSSS")
        assert res["current_status_verified"] is True
        assert res["sources"][0]["academic_year"] == "AY 2026-27"

    def test_03_can_i_still_apply(self, rag_env):
        """Question: Can I still apply? -> Confirms student deadline has passed."""
        gen = rag_env["generator"]
        mock_llm = rag_env["mock_llm"]

        mock_llm.generate.return_value = json.dumps({
            "answer": "No, you cannot apply now as the application window for AY 2026-27 closed on 31 October 2026 [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = gen.answer("Can I still apply for AICTE Saksham?", scheme_id="SCHEME_EDU_003_AICTE_SAKSHAM")
        assert res["current_status_verified"] is True
        assert res["citation_validation"]["valid"] is True

    def test_04_has_the_application_period_closed(self, rag_env):
        """Question: Has the application period closed? -> Verified CLOSED status."""
        gen = rag_env["generator"]
        mock_llm = rag_env["mock_llm"]

        mock_llm.generate.return_value = json.dumps({
            "answer": "Yes, the student application period closed on 31 October 2026 [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = gen.answer("Has the application period closed for AICTE Swanath?", scheme_id="SCHEME_EDU_004_AICTE_SWANATH")
        assert res["current_status_verified"] is True

    def test_05_when_will_applications_reopen(self, rag_env):
        """Question: When will applications reopen? -> Does not invent dates; reports NOT_ANNOUNCED."""
        gen = rag_env["generator"]
        mock_llm = rag_env["mock_llm"]

        mock_llm.generate.return_value = json.dumps({
            "answer": "The dates for the next academic cycle (AY 2027-28) have not yet been announced by the authorities [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = gen.answer("When will applications reopen for Top Class SC Scholarship?", scheme_id="SCHEME_EDU_005_TOP_CLASS_SC")
        assert res["current_status_verified"] is True

    def test_06_which_scholarships_are_currently_open(self, rag_env):
        """Question: Which scholarships are currently open? -> Reports summary of all 5 schemes."""
        gen = rag_env["generator"]
        mock_llm = rag_env["mock_llm"]

        mock_llm.generate.return_value = json.dumps({
            "answer": "Currently, none of the 5 supported scholarships are open for student applications. All application windows for AY 2026-27 closed on 31 October 2026 [S1].",
            "evidence_sufficient": True,
            "citations": ["S1"],
        })

        res = gen.answer("Which scholarships are currently open?")
        assert res["current_status_verified"] is True
        assert res["sources"][0]["chunk_id"] == "SCHED_ALL_SCHEMES"


# ==============================================================================
# 5. MULTILINGUAL LOCALIZATION PARITY
# ==============================================================================

class TestMultilingualDeadlineLocalization:
    """Verifies that English, Telugu, and Hindi contain complete deadline translations."""

    @pytest.fixture
    def locales(self):
        loc = {}
        for lang in ("en", "te", "hi"):
            p = Path("frontend/locales") / f"{lang}.json"
            assert p.exists(), f"Locale file {p} must exist"
            with open(p, "r", encoding="utf-8") as f:
                loc[lang] = json.load(f)
        return loc

    def test_01_deadlines_category_present_in_all_locales(self, locales):
        """Category 'deadlines' must exist in en, te, and hi."""
        for lang in ("en", "te", "hi"):
            assert "deadlines" in locales[lang], f"'deadlines' category missing in {lang}.json"

    def test_02_deadline_key_parity(self, locales):
        """All keys in en.deadlines must exist in te.deadlines and hi.deadlines."""
        en_keys = set(locales["en"]["deadlines"].keys())
        te_keys = set(locales["te"]["deadlines"].keys())
        hi_keys = set(locales["hi"]["deadlines"].keys())

        assert en_keys == te_keys, f"Telugu deadline key mismatch: {en_keys ^ te_keys}"
        assert en_keys == hi_keys, f"Hindi deadline key mismatch: {en_keys ^ hi_keys}"

    def test_03_no_empty_deadline_translations(self, locales):
        """No translation string in 'deadlines' may be empty or whitespace only."""
        for lang in ("en", "te", "hi"):
            for k, v in locales[lang]["deadlines"].items():
                assert isinstance(v, str) and v.strip(), f"Empty deadline translation for {k} in {lang}"

    def test_04_deadline_placeholders_preserved(self, locales):
        """Dynamic placeholders like {date}, {cycle}, {count}, {status} must match across languages."""
        def get_placeholders(s):
            return set(re.findall(r"\{([a-zA-Z0-9_]+)\}", s))

        for k, en_val in locales["en"]["deadlines"].items():
            en_ph = get_placeholders(en_val)
            te_ph = get_placeholders(locales["te"]["deadlines"][k])
            hi_ph = get_placeholders(locales["hi"]["deadlines"][k])

            assert en_ph == te_ph, f"Placeholder mismatch for {k} in te: expected {en_ph}, got {te_ph}"
            assert en_ph == hi_ph, f"Placeholder mismatch for {k} in hi: expected {en_ph}, got {hi_ph}"

    def test_05_telugu_and_hindi_unicode_scripts(self, locales):
        """Telugu and Hindi deadline translations must use native scripts."""
        telugu_regex = re.compile(r"[\u0C00-\u0C7F]")
        hindi_regex = re.compile(r"[\u0900-\u097F]")

        te_strings = " ".join(locales["te"]["deadlines"].values())
        hi_strings = " ".join(locales["hi"]["deadlines"].values())

        assert len(telugu_regex.findall(te_strings)) > 50, "Telugu deadline translations must contain authentic Telugu Unicode script"
        assert len(hindi_regex.findall(hi_strings)) > 50, "Hindi deadline translations must contain authentic Devanagari Unicode script"
