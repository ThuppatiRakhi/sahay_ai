"""
rag/reranker.py — Lightweight, deterministic reranker for SahayAI RAG.

Adjusts candidate ranking without external LLM calls by leveraging:
1. Scheme affinity (from QueryRewriter intent detection).
2. Chunk format relevance (prioritizing policy/eligibility/FAQ; deprioritizing rosters).
3. Query-chunk domain concept alignment.
4. Preserves raw cosine similarity separately from rerank_score.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RerankedCandidate:
    """Represents a candidate chunk scored and ranked by the reranker."""

    chunk_id: str
    text: str
    similarity_score: float  # Raw cosine similarity from ChromaDB
    rerank_score: float      # Adjusted ranking score
    metadata: Dict[str, Any]
    category: str


# Classification rules for 301 chunks in corpus
def classify_chunk(document_id: str, page_number: int, text: str) -> str:
    """Classifies a chunk into one of 5 mutually exclusive operational categories."""
    if document_id == "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020":
        return "Beneficiary roster"
    if document_id == "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26" and 7 <= page_number <= 41:
        return "Institution list"
    if "FAQS" in document_id or "FAQs" in text or text.strip().startswith("Q.") or "Answer:" in text:
        return "FAQ"
    if any(k in text.lower() for k in [
        "eligibility criteria", "eligibility conditions", "eligibility:", "eligible:",
        "who is eligible", "1.0 objective", "2.0 eligibility", "3.0 number of scholarship"
    ]):
        return "Eligibility"
    return "Policy"


class LightweightReranker:
    """Deterministic, CPU-optimized reranker for government scheme guidelines.

    Scoring formula:
        rerank_score = similarity_score + Δ_scheme + Δ_type + Δ_topic
        clamped to [0.0, 1.0].
    """

    def __init__(
        self,
        scheme_boost: float = 0.05,
        scheme_penalty: float = 0.025,
        roster_penalty: float = 0.15,
        inst_penalty: float = 0.10,
        type_boost: float = 0.025,
        topic_boost: float = 0.025,
        historical_penalty: float = 0.05,
    ):
        self.scheme_boost = scheme_boost
        self.scheme_penalty = scheme_penalty
        self.roster_penalty = roster_penalty
        self.inst_penalty = inst_penalty
        self.type_boost = type_boost
        self.topic_boost = topic_boost
        self.historical_penalty = historical_penalty

    def score_candidate(
        self,
        chunk_id: str,
        text: str,
        metadata: Dict[str, Any],
        similarity_score: float,
        query: str,
        detected_scheme: Optional[str] = None,
    ) -> Tuple[float, str]:
        """Calculates rerank_score and returns (rerank_score, category)."""
        doc_id = str(metadata.get("document_id", ""))
        page_num = int(metadata.get("page_number", 0))
        scheme_id = str(metadata.get("scheme_id", ""))
        cat = classify_chunk(doc_id, page_num, text)

        score = similarity_score
        q_lower = query.lower()
        t_lower = text.lower()

        # 1. Scheme Affinity
        if detected_scheme:
            if scheme_id == detected_scheme:
                score += self.scheme_boost
            else:
                score -= self.scheme_penalty

        # 2. Chunk Format Adjustment
        is_inst_query = any(k in q_lower for k in ["institution", "college", "institutes", "notified", "कॉल", "కళాశాల"])
        is_proc_query = any(k in q_lower for k in [
            "how to apply", "procedure", "document", "upload", "certificate", "portal", "nsp",
            "दस्तावेज", "प्रमाण", "आवेदन", "పత్రాలు", "దరఖాస్తు", "ధృవీకరణ"
        ])

        if cat == "Beneficiary roster":
            score -= self.roster_penalty
        elif cat == "Institution list":
            if is_inst_query:
                score += self.type_boost
            else:
                score -= self.inst_penalty
        elif cat == "FAQ":
            if is_proc_query:
                score += self.type_boost
        elif cat in ["Eligibility", "Policy"]:
            if not is_proc_query and not is_inst_query:
                score += self.type_boost

        # 3. Lexical Topic Alignment
        if ("income" in q_lower or "आय" in q_lower or "ఆదాయం" in q_lower) and "income" in t_lower:
            score += self.topic_boost
        if ("disab" in q_lower or "दिव्यांग" in q_lower or "వికలాంగ" in q_lower or "handicap" in q_lower) and (
            "disab" in t_lower or "handicap" in t_lower or "specially-abled" in t_lower
        ):
            score += self.topic_boost
        if ("orphan" in q_lower or "अनाथ" in q_lower or "అనాథ" in q_lower or "covid" in q_lower) and (
            "orphan" in t_lower or "covid" in t_lower or "death certificate" in t_lower or "died" in t_lower
        ):
            score += self.topic_boost
        if ("girl" in q_lower or "छात्रा" in q_lower or "బాలిక" in q_lower or "women" in q_lower) and (
            "girl" in t_lower or "female" in t_lower or "women" in t_lower
        ):
            score += self.topic_boost

        # 4. Historical Guideline Demotion (Prioritize active revised guidelines over superseded historical versions)
        doc_type = str(metadata.get("document_type", ""))
        is_historical = (
            doc_type == "Historical Guidelines"
            or metadata.get("is_current_guideline") is False
            or doc_id == "DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021"
        )
        if is_historical:
            score -= self.historical_penalty

        reranked = round(max(0.0, min(1.0, score)), 4)
        return reranked, cat

    def rerank(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        detected_scheme: Optional[str] = None,
        top_k: int = 5,
    ) -> List[RerankedCandidate]:
        """Reranks candidate pool and returns top_k candidates ordered by rerank_score."""
        scored_candidates: List[RerankedCandidate] = []

        for cand in candidates:
            c_id = cand["chunk_id"]
            text = cand["text"]
            meta = cand.get("metadata", {})
            sim = float(cand.get("similarity_score", 0.0))

            r_score, cat = self.score_candidate(
                chunk_id=c_id,
                text=text,
                metadata=meta,
                similarity_score=sim,
                query=query,
                detected_scheme=detected_scheme,
            )

            scored_candidates.append(
                RerankedCandidate(
                    chunk_id=c_id,
                    text=text,
                    similarity_score=sim,
                    rerank_score=r_score,
                    metadata=meta,
                    category=cat,
                )
            )

        # Sort descending by rerank_score, tie-break by raw similarity_score
        scored_candidates.sort(
            key=lambda c: (c.rerank_score, c.similarity_score),
            reverse=True,
        )

        return scored_candidates[:top_k]

