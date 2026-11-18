"""Embedding service supporting multilingual sentence-transformers with query/passage prefixing."""

import hashlib
import math
from typing import List, Optional
import numpy as np

from .config import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
)


class EmbeddingService:
    """Manages dense multilingual text embeddings using SentenceTransformers or mock mode."""

    _shared_model = None

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        use_mock: bool = False,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.use_mock = use_mock
        self.device = device
        self.dimension = EMBEDDING_DIMENSION
        self._model = None

        if not self.use_mock:
            self._load_model()

    def _load_model(self) -> None:
        """Loads SentenceTransformer model lazily or at initialization with singleton reuse and local cache."""
        if EmbeddingService._shared_model is not None:
            self._model = EmbeddingService._shared_model
            return

        try:
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                    local_files_only=True,
                )
            except Exception:
                self._model = SentenceTransformer(self.model_name, device=self.device)

            EmbeddingService._shared_model = self._model
            # Verify dimensionality
            test_emb = self._model.encode(["passage: test"], normalize_embeddings=True)
            self.dimension = int(test_emb.shape[1])
        except Exception as e:
            raise RuntimeError(
                f"Failed to load embedding model '{self.model_name}': {e}"
            ) from e

    def _mock_embedding(self, text: str) -> List[float]:
        """Generates a deterministic, L2-normalized vector for testing without network or GPU."""
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = np.random.RandomState(seed)
        vec = rng.randn(self.dimension).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_passage(self, text: str) -> List[float]:
        """Embeds a single document passage using the passage prefix."""
        if not text or not text.strip():
            raise ValueError("Passage text cannot be empty.")

        formatted_text = f"{PASSAGE_PREFIX}{text.strip()}"

        if self.use_mock:
            return self._mock_embedding(formatted_text)

        emb = self._model.encode(
            [formatted_text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return emb.tolist()

    def embed_passages(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> List[List[float]]:
        """Embeds a list of document passages in batches using the passage prefix."""
        if not texts:
            return []

        formatted_texts = [f"{PASSAGE_PREFIX}{t.strip()}" for t in texts]

        if self.use_mock:
            return [self._mock_embedding(t) for t in formatted_texts]

        embeddings = self._model.encode(
            formatted_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
        )
        return [vec.tolist() for vec in embeddings]

    def embed_query(self, query: str) -> List[float]:
        """Embeds a user query using the query prefix for asymmetric cross-lingual retrieval."""
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        formatted_query = f"{QUERY_PREFIX}{query.strip()}"

        if self.use_mock:
            return self._mock_embedding(formatted_query)

        emb = self._model.encode(
            [formatted_query],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return emb.tolist()
