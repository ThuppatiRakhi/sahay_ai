"""
tests/test_rag.py — SahayAI RAG Pipeline Test Suite

Tests cover:
  - Embedding service (mock + real model)
  - Vector store (persistence, deduplication, filtering)
  - Retriever (English, Hindi, Telugu cross-lingual queries)
  - Indexer integrity (chunk loading and validation)
  - Citation traceability
"""

import json
import math
import tempfile
import os
from pathlib import Path

import pytest

from rag.config import (
    EMBEDDING_DIMENSION,
    EXPECTED_SCHEME_CHUNKS,
    OFFICIAL_DISCLAIMER,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    TOTAL_EXPECTED_CHUNKS,
    DEFAULT_CHUNKS_FILE,
)
from rag.embedding_service import EmbeddingService
from rag.vector_store import VectorStoreManager
from rag.retriever import SchemeRetriever, RetrievalResult
from rag.reranker import LightweightReranker, RerankedCandidate, classify_chunk
from rag.indexer import load_chunks, validate_chunks_integrity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mock_embedding_service():
    """EmbeddingService in mock mode — no model download required."""
    return EmbeddingService(use_mock=True)


@pytest.fixture(scope="module")
def chunks():
    """Load all 301 chunks from the official batch1 file."""
    return load_chunks(DEFAULT_CHUNKS_FILE)


@pytest.fixture(scope="module")
def fresh_vector_store(tmp_path_factory):
    """Provides a fresh, isolated temp-directory vector store populated with mock embeddings."""
    tmp_dir = tmp_path_factory.mktemp("chroma_test")
    svc = EmbeddingService(use_mock=True)
    store = VectorStoreManager(persist_directory=tmp_dir, collection_name="test_collection")
    return store, svc, tmp_dir


@pytest.fixture(scope="module")
def populated_store_and_retriever(tmp_path_factory, chunks):
    """
    Builds a temporary vector store with all 301 chunks (mock embeddings)
    and a SchemeRetriever wired to it. Used for retrieval tests.
    """
    tmp_dir = tmp_path_factory.mktemp("chroma_retrieval")
    svc = EmbeddingService(use_mock=True)
    store = VectorStoreManager(persist_directory=tmp_dir, collection_name="retrieval_test")
    store.insert_chunks(chunks, svc, batch_size=64)
    retriever = SchemeRetriever(vector_store=store, embedding_service=svc)
    return store, svc, retriever


# ---------------------------------------------------------------------------
# Section 1: Embedding Service Tests
# ---------------------------------------------------------------------------

class TestEmbeddingService:
    """Tests for EmbeddingService — dimensionality, normalization, and prefixing."""

    def test_mock_mode_initialized(self, mock_embedding_service):
        assert mock_embedding_service.use_mock is True

    def test_embed_passage_returns_correct_dimension(self, mock_embedding_service):
        vec = mock_embedding_service.embed_passage("This is an English government scheme passage.")
        assert isinstance(vec, list)
        assert len(vec) == EMBEDDING_DIMENSION, (
            f"Expected dimension {EMBEDDING_DIMENSION}, got {len(vec)}"
        )

    def test_embed_query_returns_correct_dimension(self, mock_embedding_service):
        vec = mock_embedding_service.embed_query("What is the income limit?")
        assert len(vec) == EMBEDDING_DIMENSION

    def test_embed_passage_normalized(self, mock_embedding_service):
        """Mock embeddings must be L2-normalized (unit norm) to work correctly with cosine similarity."""
        vec = mock_embedding_service.embed_passage("Test passage for normalization check.")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-5, f"Expected unit-norm vector, got norm={norm}"

    def test_embed_query_normalized(self, mock_embedding_service):
        vec = mock_embedding_service.embed_query("Test query normalization.")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-5

    def test_embed_passages_batch_returns_correct_count(self, mock_embedding_service):
        texts = ["Passage one.", "Passage two.", "Passage three."]
        vecs = mock_embedding_service.embed_passages(texts)
        assert len(vecs) == 3
        for vec in vecs:
            assert len(vec) == EMBEDDING_DIMENSION

    def test_passage_and_query_produce_different_embeddings(self, mock_embedding_service):
        """The E5 asymmetric protocol requires different prefixes for passages and queries."""
        text = "income limit for aicte pragati scholarship"
        passage_vec = mock_embedding_service.embed_passage(text)
        query_vec = mock_embedding_service.embed_query(text)
        # Different prefix → different hash → different mock embedding
        assert passage_vec != query_vec

    def test_empty_passage_raises(self, mock_embedding_service):
        with pytest.raises(ValueError):
            mock_embedding_service.embed_passage("")

    def test_empty_query_raises(self, mock_embedding_service):
        with pytest.raises(ValueError):
            mock_embedding_service.embed_query("   ")

    def test_deterministic_mock_embedding(self, mock_embedding_service):
        """Same input should always produce the same mock embedding."""
        v1 = mock_embedding_service.embed_passage("government scholarship")
        v2 = mock_embedding_service.embed_passage("government scholarship")
        assert v1 == v2

    def test_different_texts_produce_different_embeddings(self, mock_embedding_service):
        v1 = mock_embedding_service.embed_passage("income ceiling scholarship")
        v2 = mock_embedding_service.embed_passage("disability percentage requirement")
        assert v1 != v2


# ---------------------------------------------------------------------------
# Section 2: Chunk Loading and Indexer Integrity Tests
# ---------------------------------------------------------------------------

class TestChunkLoading:
    """Tests for chunk loading and schema validation."""

    def test_total_chunk_count(self, chunks):
        assert len(chunks) == TOTAL_EXPECTED_CHUNKS, (
            f"Expected {TOTAL_EXPECTED_CHUNKS} chunks, got {len(chunks)}"
        )

    def test_scheme_distribution(self, chunks):
        from collections import Counter
        distribution = Counter(c["scheme_id"] for c in chunks)
        for scheme_id, expected_count in EXPECTED_SCHEME_CHUNKS.items():
            actual = distribution.get(scheme_id, 0)
            assert actual == expected_count, (
                f"Scheme {scheme_id}: expected {expected_count} chunks, got {actual}"
            )

    def test_all_chunks_have_required_fields(self, chunks):
        required = [
            "chunk_id", "scheme_id", "document_id", "document_name",
            "authority", "page_number", "source_url", "citation_reference", "text",
        ]
        for c in chunks:
            for field in required:
                assert field in c, f"Chunk {c.get('chunk_id', 'UNKNOWN')} missing '{field}'"

    def test_no_duplicate_chunk_ids(self, chunks):
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk_ids detected in chunk file."

    def test_no_empty_text(self, chunks):
        empty = [c["chunk_id"] for c in chunks if not c.get("text", "").strip()]
        assert empty == [], f"Chunks with empty text: {empty}"

    def test_minimum_chunk_length(self, chunks):
        """Every chunk should have meaningful content — at least 50 characters."""
        short = [c["chunk_id"] for c in chunks if len(c.get("text", "")) < 50]
        assert short == [], f"Chunks too short: {short}"

    def test_all_chunks_have_source_urls(self, chunks):
        missing = [c["chunk_id"] for c in chunks if not c.get("source_url", "").startswith("http")]
        assert missing == [], f"Chunks with invalid/missing source_url: {missing}"

    def test_all_chunks_have_citation_references(self, chunks):
        missing = [c["chunk_id"] for c in chunks if not c.get("citation_reference", "").strip()]
        assert missing == [], f"Chunks missing citation_reference: {missing}"

    def test_validate_chunks_integrity_passes(self, chunks):
        """validate_chunks_integrity should not raise for valid chunk set."""
        result = validate_chunks_integrity(chunks)
        assert isinstance(result, dict)
        assert len(result) == 5

    def test_all_chunks_english_language(self, chunks):
        non_english = [c["chunk_id"] for c in chunks if c.get("language", "en") != "en"]
        assert non_english == [], f"Unexpected non-English chunks: {non_english}"


# ---------------------------------------------------------------------------
# Section 3: Vector Store Tests
# ---------------------------------------------------------------------------

class TestVectorStore:
    """Tests for VectorStoreManager — persistence, deduplication, and filtering."""

    def test_initial_count_zero(self, fresh_vector_store):
        store, svc, _ = fresh_vector_store
        assert store.count() == 0

    def test_insert_small_batch(self, fresh_vector_store, chunks):
        store, svc, _ = fresh_vector_store
        # Only insert first 10 for lightweight unit testing
        result = store.insert_chunks(chunks[:10], svc, batch_size=5)
        assert result["new_indexed"] == 10
        assert result["skipped_existing"] == 0
        assert store.count() == 10

    def test_idempotent_second_insert(self, fresh_vector_store, chunks):
        """Reinserting the same 10 chunks should produce 0 new insertions."""
        store, svc, _ = fresh_vector_store
        # Same 10 chunks already inserted above
        result = store.insert_chunks(chunks[:10], svc, batch_size=5)
        assert result["new_indexed"] == 0
        assert result["skipped_existing"] == 10
        assert store.count() == 10

    def test_get_chunk_by_id(self, fresh_vector_store, chunks):
        store, svc, _ = fresh_vector_store
        first_chunk = chunks[0]
        chunk_id = first_chunk["chunk_id"]
        retrieved = store.get_chunk(chunk_id)
        assert retrieved is not None
        assert retrieved["chunk_id"] == chunk_id
        assert retrieved["text"] == first_chunk["text"]

    def test_get_nonexistent_chunk_returns_none(self, fresh_vector_store):
        store, svc, _ = fresh_vector_store
        result = store.get_chunk("NONEXISTENT_CHUNK_ID_DOES_NOT_EXIST")
        assert result is None

    def test_scheme_chunk_counts_correctness(self, fresh_vector_store, chunks):
        """Check scheme_id distribution after inserting 10 chunks."""
        store, svc, _ = fresh_vector_store
        distribution = store.get_scheme_chunk_counts()
        # All 10 first chunks belong to SCHEME_EDU_001_PM_USP_CSSS
        assert "SCHEME_EDU_001_PM_USP_CSSS" in distribution
        assert distribution["SCHEME_EDU_001_PM_USP_CSSS"] == 10


# ---------------------------------------------------------------------------
# Section 4: Populated Store — Full 301 Chunks (Mock Embeddings)
# ---------------------------------------------------------------------------

class TestPopulatedVectorStore:
    """Tests on the fully populated store (301 mock-embedded chunks)."""

    def test_total_indexed_count(self, populated_store_and_retriever):
        store, _, _ = populated_store_and_retriever
        assert store.count() == TOTAL_EXPECTED_CHUNKS

    def test_scheme_distribution_all_five_schemes(self, populated_store_and_retriever):
        store, _, _ = populated_store_and_retriever
        distribution = store.get_scheme_chunk_counts()
        assert len(distribution) == 5
        for scheme_id, expected in EXPECTED_SCHEME_CHUNKS.items():
            assert distribution.get(scheme_id, 0) == expected, (
                f"Scheme {scheme_id}: expected {expected}, got {distribution.get(scheme_id, 0)}"
            )

    def test_filtered_query_by_scheme_id(self, populated_store_and_retriever):
        store, svc, _ = populated_store_and_retriever
        query_vec = svc.embed_query("scholarship eligibility criteria")
        result = store.query(
            query_embedding=query_vec,
            n_results=5,
            where={"scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI"},
        )
        returned_ids = result.get("ids", [[]])[0]
        returned_metas = result.get("metadatas", [[]])[0]
        assert len(returned_ids) > 0
        for meta in returned_metas:
            assert meta["scheme_id"] == "SCHEME_EDU_002_AICTE_PRAGATI", (
                f"Unexpected scheme_id in filtered result: {meta['scheme_id']}"
            )

    def test_metadata_fields_present_in_results(self, populated_store_and_retriever):
        store, svc, _ = populated_store_and_retriever
        query_vec = svc.embed_query("disability percentage")
        result = store.query(query_embedding=query_vec, n_results=1)
        meta = result["metadatas"][0][0]
        required_meta_keys = [
            "scheme_id", "document_id", "document_name", "authority",
            "page_number", "source_url", "citation_reference", "academic_year",
        ]
        for key in required_meta_keys:
            assert key in meta, f"Missing metadata key '{key}' in query result"


# ---------------------------------------------------------------------------
# Section 5: Retriever Tests
# ---------------------------------------------------------------------------

class TestSchemeRetriever:
    """Tests for SchemeRetriever — structured output, citation preservation, filtering."""

    def test_retrieve_returns_list(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("What is the income eligibility for AICTE Pragati scholarship?")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_retrieve_top_k(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("scholarship for girl students in engineering", top_k=3)
        assert len(results) <= 3

    def test_retrieval_result_has_all_fields(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("minimum disability percentage requirement", top_k=1)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, RetrievalResult)
        assert r.chunk_id
        assert r.text
        assert r.scheme_id
        assert r.document_id
        assert r.document_name
        assert r.authority
        assert isinstance(r.page_number, int)
        assert r.source_url.startswith("http")
        assert r.citation_reference

    def test_similarity_score_in_range(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("government scholarship for college students", top_k=5)
        for r in results:
            assert 0.0 <= r.similarity_score <= 1.0, (
                f"Similarity score {r.similarity_score} out of range [0,1]"
            )

    def test_disclaimer_always_present(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("Top Class SC scholarship institutions list")
        for r in results:
            assert OFFICIAL_DISCLAIMER in r.disclaimer

    def test_scheme_filter_restricts_results(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve(
            "scholarship amount per year",
            scheme_id="SCHEME_EDU_004_AICTE_SWANATH",
            top_k=5,
        )
        for r in results:
            assert r.scheme_id == "SCHEME_EDU_004_AICTE_SWANATH", (
                f"Filter leaked: got scheme_id={r.scheme_id}"
            )

    def test_retrieve_empty_query_raises(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        with pytest.raises(ValueError):
            retriever.retrieve("")

    def test_citation_reference_non_empty(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("document guidelines scholarship", top_k=5)
        for r in results:
            assert r.citation_reference.strip(), f"Empty citation_reference for chunk {r.chunk_id}"

    def test_format_results_summary_non_empty(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("eligibility income limit scheme")
        summary = retriever.format_results_summary(results)
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert OFFICIAL_DISCLAIMER in summary

    def test_format_empty_results_summary(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        summary = retriever.format_results_summary([])
        assert "No matching" in summary

    def test_result_to_dict(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("AICTE scholarship application", top_k=1)
        d = results[0].to_dict()
        assert isinstance(d, dict)
        assert "chunk_id" in d
        assert "text" in d
        assert "similarity_score" in d
        assert "citation_reference" in d
        assert "disclaimer" in d


# ---------------------------------------------------------------------------
# Section 6: Cross-lingual Semantic Retrieval Tests (Mock Mode)
# ---------------------------------------------------------------------------

class TestCrossLingualRetrieval:
    """
    Cross-lingual query tests using MOCK embeddings.
    
    NOTE: Mock embeddings are deterministic pseudo-random vectors that do NOT carry
    semantic meaning. These tests verify the ARCHITECTURAL correctness of the retrieval
    pipeline (query → embed → search → results with citations) rather than semantic relevance.
    Real semantic relevance tests are conducted separately in the RAG integration report
    using the intfloat/multilingual-e5-small model (see reports/rag_embedding_vector_search.md).
    """

    def test_english_query_pipeline_completes(self, populated_store_and_retriever):
        """English query must traverse the full pipeline and return structured results."""
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve(
            "What is the family income ceiling for AICTE Pragati scholarship?",
            top_k=5,
        )
        assert len(results) > 0
        for r in results:
            assert r.chunk_id
            assert r.source_url

    def test_hindi_query_pipeline_completes(self, populated_store_and_retriever):
        """Hindi query must complete the full pipeline without errors."""
        _, _, retriever = populated_store_and_retriever
        # "What is the minimum disability percentage for Saksham scholarship?"
        results = retriever.retrieve(
            "सक्षम छात्रवृत्ति के लिए न्यूनतम दिव्यांगता प्रतिशत क्या है?",
            top_k=5,
        )
        assert isinstance(results, list)
        assert len(results) > 0

    def test_telugu_query_pipeline_completes(self, populated_store_and_retriever):
        """Telugu query must complete the full pipeline without errors."""
        _, _, retriever = populated_store_and_retriever
        # "Who is eligible for the Swanath scholarship?"
        results = retriever.retrieve(
            "స్వానాథ్ స్కాలర్‌షిప్ ఎవరికి వర్తిస్తుంది?",
            top_k=5,
        )
        assert isinstance(results, list)
        assert len(results) > 0

    def test_all_queries_return_citation_traceable_results(self, populated_store_and_retriever):
        """Every result from every language must be citation-traceable."""
        _, _, retriever = populated_store_and_retriever
        queries = [
            "income ceiling scholarship 2024",
            "शैक्षणिक छात्रवृत्ति आवेदन",
            "విద్యా స్కాలర్‌షిప్ పాత్రత",
        ]
        for q in queries:
            results = retriever.retrieve(q, top_k=3)
            for r in results:
                assert r.citation_reference.strip(), f"Empty citation for query: {q}"
                assert r.source_url.startswith("http"), f"Invalid source_url for query: {q}"
                assert r.page_number >= 1, f"Invalid page_number for query: {q}"

    def test_scheme_filtering_works_with_hindi_query(self, populated_store_and_retriever):
        """Scheme filtering must work regardless of query language."""
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve(
            "शीर्ष श्रेणी एससी छात्रवृत्ति",
            scheme_id="SCHEME_EDU_005_TOP_CLASS_SC",
            top_k=5,
        )
        for r in results:
            assert r.scheme_id == "SCHEME_EDU_005_TOP_CLASS_SC"


# ---------------------------------------------------------------------------
# Section 7: Scheme Record Integrity Tests (non-RAG)
# ---------------------------------------------------------------------------

class TestSchemeRecordIntegrity:
    """Ensures scheme records remain untouched and in pending_review state throughout RAG step."""

    def test_schemes_json_exists(self):
        schemes_path = Path("data/schemes/schemes.json")
        assert schemes_path.exists()

    def test_all_schemes_pending_review(self):
        schemes_path = Path("data/schemes/schemes.json")
        with open(schemes_path, encoding="utf-8") as f:
            schemes = json.load(f)
        for s in schemes:
            assert s.get("verification_status") == "pending_review", (
                f"Scheme {s.get('scheme_id')} has unexpected status: {s.get('verification_status')}"
            )

    def test_no_scheme_is_verified(self):
        schemes_path = Path("data/schemes/schemes.json")
        with open(schemes_path, encoding="utf-8") as f:
            schemes = json.load(f)
        for s in schemes:
            assert s.get("is_verified") is False, (
                f"Scheme {s.get('scheme_id')} is unexpectedly marked as verified."
            )

    def test_verified_schemes_json_remains_empty(self):
        verified_path = Path("data/schemes/verified_schemes.json")
        with open(verified_path, encoding="utf-8") as f:
            verified = json.load(f)
        assert verified == [], (
            f"verified_schemes.json must remain empty; found {len(verified)} record(s)."
        )

    def test_five_schemes_present(self):
        schemes_path = Path("data/schemes/schemes.json")
        with open(schemes_path, encoding="utf-8") as f:
            schemes = json.load(f)
        assert len(schemes) == 5

    def test_expected_scheme_ids_present(self):
        schemes_path = Path("data/schemes/schemes.json")
        with open(schemes_path, encoding="utf-8") as f:
            schemes = json.load(f)
        ids = {s["scheme_id"] for s in schemes}
        expected_ids = set(EXPECTED_SCHEME_CHUNKS.keys())
        assert ids == expected_ids


# ---------------------------------------------------------------------------
# Section 8: Lightweight Reranker and Scheme-Aware Retrieval Tests
# ---------------------------------------------------------------------------

class TestLightweightReranker:
    """Unit tests for LightweightReranker logic, categorization, and scoring."""

    def test_chunk_classification(self):
        # Beneficiary roster
        assert classify_chunk("DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020", 3, "Table of students") == "Beneficiary roster"
        # Institution list
        assert classify_chunk("DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26", 12, "IIT Delhi, New Delhi") == "Institution list"
        # FAQ
        assert classify_chunk("DOC_EDU_001_PM_USP_CSSS_FAQS_2024", 2, "Q. What is the income ceiling?") == "FAQ"
        assert classify_chunk("DOC_EDU_002_PRAGATI_GUIDELINES_2020", 5, "Answer: The candidate must...") == "FAQ"
        # Eligibility
        assert classify_chunk("DOC_EDU_002_PRAGATI_GUIDELINES_2020", 1, "2.0 ELIGIBILITY CRITERIA for scholarship") == "Eligibility"
        # Policy
        assert classify_chunk("DOC_EDU_004_SWANATH_GUIDELINES_2020", 1, "General guidelines and terms") == "Policy"

    def test_reranker_initialization_defaults(self):
        reranker = LightweightReranker()
        assert reranker.scheme_boost == 0.05
        assert reranker.scheme_penalty == 0.025
        assert reranker.roster_penalty == 0.15
        assert reranker.inst_penalty == 0.10
        assert reranker.type_boost == 0.025
        assert reranker.topic_boost == 0.025

    def test_scheme_affinity_boost_and_penalty(self):
        reranker = LightweightReranker()
        meta_match = {"scheme_id": "SCHEME_EDU_003_SAKSHAM", "document_id": "DOC_003", "page_number": 1}
        meta_other = {"scheme_id": "SCHEME_EDU_002_PRAGATI", "document_id": "DOC_002", "page_number": 1}

        # Matched scheme gets boost (+0.05 + type_boost 0.025 = +0.075)
        score_match, _ = reranker.score_candidate(
            chunk_id="c1",
            text="Standard policy text",
            metadata=meta_match,
            similarity_score=0.80,
            query="Saksham scholarship",
            detected_scheme="SCHEME_EDU_003_SAKSHAM",
        )
        # Other scheme gets penalty (-0.025 + type_boost 0.025 = 0.00)
        score_other, _ = reranker.score_candidate(
            chunk_id="c2",
            text="Standard policy text",
            metadata=meta_other,
            similarity_score=0.80,
            query="Saksham scholarship",
            detected_scheme="SCHEME_EDU_003_SAKSHAM",
        )
        assert score_match > score_other
        assert round(score_match - score_other, 4) == 0.075

    def test_roster_penalty_deprioritizes_rosters(self):
        reranker = LightweightReranker()
        meta_roster = {
            "scheme_id": "SCHEME_EDU_003_SAKSHAM",
            "document_id": "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020",
            "page_number": 3,
        }
        meta_policy = {
            "scheme_id": "SCHEME_EDU_003_SAKSHAM",
            "document_id": "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020",
            "page_number": 1,
        }

        score_roster, cat_roster = reranker.score_candidate(
            chunk_id="c_roster",
            text="S.No Name College State",
            metadata=meta_roster,
            similarity_score=0.85,
            query="Saksham eligibility criteria",
            detected_scheme="SCHEME_EDU_003_SAKSHAM",
        )
        score_policy, cat_policy = reranker.score_candidate(
            chunk_id="c_policy",
            text="Eligibility criteria for disabled students",
            metadata=meta_policy,
            similarity_score=0.85,
            query="Saksham eligibility criteria",
            detected_scheme="SCHEME_EDU_003_SAKSHAM",
        )

        assert cat_roster == "Beneficiary roster"
        assert score_roster < score_policy
        # Roster has -0.15 penalty, policy has +0.025 boost -> diff = 0.175 (plus topic boost if triggered)
        assert score_policy - score_roster >= 0.15

    def test_topic_alignment_boost(self):
        reranker = LightweightReranker()
        meta = {"scheme_id": "SCHEME_EDU_001_PM_USP_CSSS", "document_id": "DOC_001", "page_number": 1}

        # Query and text share "income" topic
        score_topic, _ = reranker.score_candidate(
            chunk_id="c_income",
            text="The parental annual income must not exceed 4.5 lakh.",
            metadata=meta,
            similarity_score=0.80,
            query="What is the family income limit?",
        )
        score_no_topic, _ = reranker.score_candidate(
            chunk_id="c_other",
            text="The student must obtain at least 80th percentile.",
            metadata=meta,
            similarity_score=0.80,
            query="What is the family income limit?",
        )
        assert score_topic > score_no_topic
        assert round(score_topic - score_no_topic, 4) == 0.025

    def test_score_clamping(self):
        reranker = LightweightReranker(roster_penalty=0.90)
        meta = {
            "scheme_id": "SCHEME_EDU_003_SAKSHAM",
            "document_id": "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020",
            "page_number": 2,
        }
        score, _ = reranker.score_candidate(
            chunk_id="c_low",
            text="low score chunk",
            metadata=meta,
            similarity_score=0.10,
            query="random query",
            detected_scheme="OTHER_SCHEME",
        )
        assert score >= 0.0

    def test_rerank_orders_candidates(self):
        reranker = LightweightReranker()
        candidates = [
            {
                "chunk_id": "roster_1",
                "text": "Beneficiary roster table",
                "similarity_score": 0.90,
                "metadata": {"scheme_id": "SCHEME_EDU_003_SAKSHAM", "document_id": "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020", "page_number": 2},
            },
            {
                "chunk_id": "policy_1",
                "text": "Eligibility: 40% disability and income limit Rs 8 lakh per annum",
                "similarity_score": 0.86,
                "metadata": {"scheme_id": "SCHEME_EDU_003_SAKSHAM", "document_id": "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020", "page_number": 1},
            },
        ]
        reranked = reranker.rerank(
            candidates=candidates,
            query="AICTE Saksham disability eligibility",
            detected_scheme="SCHEME_EDU_003_SAKSHAM",
            top_k=2,
        )
        assert len(reranked) == 2
        # Policy chunk must be promoted to rank 1 over roster chunk despite lower initial similarity
        assert reranked[0].chunk_id == "policy_1"
        assert reranked[1].chunk_id == "roster_1"
        # Raw similarity score is preserved intact
        assert reranked[0].similarity_score == 0.86
        assert reranked[1].similarity_score == 0.90
        # Rerank score is distinct from similarity score
        assert reranked[0].rerank_score != reranked[0].similarity_score


class TestRetrieverWithReranker:
    """Integration tests for SchemeRetriever with LightweightReranker enabled/disabled."""

    def test_retriever_defaults_have_reranker(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        assert hasattr(retriever, "reranker")
        assert isinstance(retriever.reranker, LightweightReranker)

    def test_retrieve_with_reranking_enabled(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve(
            query="AICTE Pragati eligibility for girl students",
            top_k=5,
            enable_reranking=True,
            candidate_pool_size=30,
        )
        assert len(results) > 0
        for r in results:
            assert r.rerank_score is not None
            assert isinstance(r.rerank_score, float)
            assert 0.0 <= r.rerank_score <= 1.0
            assert isinstance(r.similarity_score, float)
            assert 0.0 <= r.similarity_score <= 1.0

    def test_retrieve_with_reranking_disabled(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve(
            query="AICTE Pragati eligibility for girl students",
            top_k=5,
            enable_reranking=False,
        )
        assert len(results) > 0
        for r in results:
            assert r.rerank_score is None
            assert isinstance(r.similarity_score, float)

    def test_pool_size_parameter(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        res_pool_10 = retriever.retrieve("scholarship", top_k=3, candidate_pool_size=10, enable_reranking=True)
        res_pool_30 = retriever.retrieve("scholarship", top_k=3, candidate_pool_size=30, enable_reranking=True)
        assert len(res_pool_10) == 3
        assert len(res_pool_30) == 3

    def test_format_results_summary_includes_rerank_score(self, populated_store_and_retriever):
        _, _, retriever = populated_store_and_retriever
        results = retriever.retrieve("Saksham eligibility", top_k=1, enable_reranking=True)
        summary = retriever.format_results_summary(results)
        assert "Rerank Score:" in summary
        assert "Similarity Score:" in summary
