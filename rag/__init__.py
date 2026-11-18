"""SahayAI RAG Package for Multilingual Scheme Retrieval.

Provides embedding generation, persistent ChromaDB vector storage,
and cross-lingual semantic search with full citation traceability.
"""

from .config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_TOP_K,
    DEFAULT_VECTOR_STORE_DIR,
    EMBEDDING_DIMENSION,
    OFFICIAL_DISCLAIMER,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    TOTAL_EXPECTED_CHUNKS,
)
from .embedding_service import EmbeddingService
from .vector_store import VectorStoreManager
from .retriever import SchemeRetriever, RetrievalResult
from .query_rewriter import QueryRewriter, RewrittenQuery
from .reranker import LightweightReranker, RerankedCandidate, classify_chunk

__all__ = [
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_TOP_K",
    "DEFAULT_VECTOR_STORE_DIR",
    "EMBEDDING_DIMENSION",
    "OFFICIAL_DISCLAIMER",
    "PASSAGE_PREFIX",
    "QUERY_PREFIX",
    "TOTAL_EXPECTED_CHUNKS",
    "EmbeddingService",
    "VectorStoreManager",
    "SchemeRetriever",
    "RetrievalResult",
    "QueryRewriter",
    "RewrittenQuery",
    "LightweightReranker",
    "RerankedCandidate",
    "classify_chunk",
]

