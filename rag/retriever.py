"""Multilingual semantic retriever for government scheme guidelines with citation traceability."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from .config import DEFAULT_TOP_K, OFFICIAL_DISCLAIMER, SUPPORTED_SCHEMES
from .embedding_service import EmbeddingService
from .vector_store import VectorStoreManager
from .query_rewriter import QueryRewriter, RewrittenQuery
from .reranker import LightweightReranker, RerankedCandidate


@dataclass
class RetrievalResult:
    """Represents a verified guideline excerpt retrieved by semantic similarity."""

    chunk_id: str
    text: str
    similarity_score: float
    scheme_id: str
    document_id: str
    document_name: str
    authority: str
    page_number: int
    source_url: str
    citation_reference: str
    academic_year: str
    disclaimer: str = OFFICIAL_DISCLAIMER
    rerank_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts result to dictionary."""
        return asdict(self)


class SchemeRetriever:
    """Executes semantic search across official scheme guidelines with metadata filtering."""

    def __init__(
        self,
        vector_store: VectorStoreManager,
        embedding_service: EmbeddingService,
        query_rewriter: Optional[QueryRewriter] = None,
        reranker: Optional[LightweightReranker] = None,
    ):
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.reranker = reranker or LightweightReranker()

    def retrieve(
        self,
        query: str,
        scheme_id: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        score_threshold: Optional[float] = None,
        enable_query_rewriting: bool = True,
        auto_scheme_filter: bool = False,
        enable_reranking: bool = True,
        candidate_pool_size: int = 30,
    ) -> List[RetrievalResult]:
        """Performs cross-lingual semantic retrieval for a user query.

        Args:
            query: User search query in English, Hindi, Telugu, or other Indic languages.
            scheme_id: Optional scheme filter to restrict retrieval to a single scheme.
            top_k: Maximum number of relevant chunks to return.
            score_threshold: Minimum cosine similarity score threshold (0.0 to 1.0).
            enable_query_rewriting: Whether to normalize and enrich query using QueryRewriter.
            auto_scheme_filter: If True and scheme_id is not provided, automatically applies
                                metadata filter when a scheme is unambiguously detected.
            enable_reranking: Whether to apply lightweight query-dependent reranking.
            candidate_pool_size: Size of candidate pool retrieved from vector store prior to reranking.

        Returns:
            List of RetrievalResult objects ordered by relevance.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        clean_query = query.strip()
        effective_query = clean_query
        effective_scheme_id = scheme_id
        rewritten_obj: Optional[RewrittenQuery] = None

        # Multilingual query rewriting and intent recognition
        if enable_query_rewriting and self.query_rewriter:
            rewritten_obj = self.query_rewriter.rewrite(clean_query)
            effective_query = rewritten_obj.rewritten_query

            # Unsupported scheme gate or ambiguous query: abort immediately without querying vector DB
            if rewritten_obj.unsupported_scheme or rewritten_obj.is_ambiguous:
                return []

            # Auto-filter scheme if explicitly enabled and detected
            if not effective_scheme_id and auto_scheme_filter and rewritten_obj.detected_scheme_id:
                effective_scheme_id = rewritten_obj.detected_scheme_id

        # Embed query using asymmetric prefix protocol (EmbeddingService adds 'query: ')
        query_vec = self.embedding_service.embed_query(effective_query)

        # Construct metadata filter if requested
        where_filter = None
        if effective_scheme_id:
            where_filter = {"scheme_id": effective_scheme_id}

        results: List[RetrievalResult] = []

        if enable_reranking and self.reranker:
            # Retrieve candidate pool from vector store
            fetch_count = max(top_k, candidate_pool_size)
            query_response = self.vector_store.query(
                query_embedding=query_vec,
                n_results=fetch_count,
                where=where_filter,
            )

            ids_list = query_response.get("ids", [[]])[0]
            docs_list = query_response.get("documents", [[]])[0]
            metas_list = query_response.get("metadatas", [[]])[0]
            dists_list = query_response.get("distances", [[]])[0]

            candidates: List[Dict[str, Any]] = []
            for chunk_id, doc_text, meta, distance in zip(
                ids_list, docs_list, metas_list, dists_list
            ):
                cand_scheme_id = meta.get("scheme_id")
                # Safeguard: only chunks belonging to supported schemes
                if cand_scheme_id not in SUPPORTED_SCHEMES:
                    continue

                similarity = round(max(0.0, min(1.0, 1.0 - float(distance))), 4)
                if score_threshold is not None and similarity < score_threshold:
                    continue
                candidates.append({
                    "chunk_id": chunk_id,
                    "text": doc_text,
                    "similarity_score": similarity,
                    "metadata": meta,
                })

            detected_scheme = rewritten_obj.detected_scheme_id if (enable_query_rewriting and rewritten_obj) else None
            reranked_candidates = self.reranker.rerank(
                candidates=candidates,
                query=effective_query,
                detected_scheme=detected_scheme,
                top_k=top_k,
            )

            for cand in reranked_candidates:
                meta = cand.metadata
                result = RetrievalResult(
                    chunk_id=cand.chunk_id,
                    text=cand.text,
                    similarity_score=cand.similarity_score,
                    scheme_id=str(meta.get("scheme_id", "")),
                    document_id=str(meta.get("document_id", "")),
                    document_name=str(meta.get("document_name", "")),
                    authority=str(meta.get("authority", "")),
                    page_number=int(meta.get("page_number", 0)),
                    source_url=str(meta.get("source_url", "")),
                    citation_reference=str(meta.get("citation_reference", "")),
                    academic_year=str(meta.get("academic_year", "")),
                    disclaimer=OFFICIAL_DISCLAIMER,
                    rerank_score=cand.rerank_score,
                )
                results.append(result)

        else:
            # Query vector store directly without reranking
            query_response = self.vector_store.query(
                query_embedding=query_vec,
                n_results=top_k,
                where=where_filter,
            )

            ids_list = query_response.get("ids", [[]])[0]
            docs_list = query_response.get("documents", [[]])[0]
            metas_list = query_response.get("metadatas", [[]])[0]
            dists_list = query_response.get("distances", [[]])[0]

            for chunk_id, doc_text, meta, distance in zip(
                ids_list, docs_list, metas_list, dists_list
            ):
                cand_scheme_id = meta.get("scheme_id")
                if cand_scheme_id not in SUPPORTED_SCHEMES:
                    continue

                similarity = round(max(0.0, min(1.0, 1.0 - float(distance))), 4)

                if score_threshold is not None and similarity < score_threshold:
                    continue

                result = RetrievalResult(
                    chunk_id=chunk_id,
                    text=doc_text,
                    similarity_score=similarity,
                    scheme_id=str(meta.get("scheme_id", "")),
                    document_id=str(meta.get("document_id", "")),
                    document_name=str(meta.get("document_name", "")),
                    authority=str(meta.get("authority", "")),
                    page_number=int(meta.get("page_number", 0)),
                    source_url=str(meta.get("source_url", "")),
                    citation_reference=str(meta.get("citation_reference", "")),
                    academic_year=str(meta.get("academic_year", "")),
                    disclaimer=OFFICIAL_DISCLAIMER,
                    rerank_score=None,
                )
                results.append(result)

        return results

    def format_results_summary(self, results: List[RetrievalResult]) -> str:
        """Formats retrieval results into a structured human-readable text."""
        if not results:
            return "No matching official guideline excerpts found."

        lines = [f"Retrieved {len(results)} relevant official guideline excerpts:\n"]
        for idx, res in enumerate(results, start=1):
            excerpt = res.text.replace("\n", " ").strip()
            if len(excerpt) > 280:
                excerpt = excerpt[:277] + "..."

            score_line = f"[{idx}] Similarity Score: {res.similarity_score:.4f}"
            if res.rerank_score is not None:
                score_line += f" | Rerank Score: {res.rerank_score:.4f}"
            lines.append(score_line)
            lines.append(f"     Scheme: {res.scheme_id}")
            lines.append(f"     Document: {res.document_name} (Page {res.page_number})")
            lines.append(f"     Issuing Authority: {res.authority}")
            lines.append(f"     Source URL: {res.source_url}")
            lines.append(f"     Excerpt: \"{excerpt}\"")
            lines.append(f"     Citation: {res.citation_reference}\n")

        lines.append(OFFICIAL_DISCLAIMER)
        return "\n".join(lines)
