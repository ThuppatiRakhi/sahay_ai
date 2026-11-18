"""ChromaDB vector store manager with persistent storage, deduplication, and metadata filtering."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import chromadb
from chromadb.config import Settings

from .config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_VECTOR_STORE_DIR,
    DISTANCE_METRIC,
)
from .embedding_service import EmbeddingService


class VectorStoreManager:
    """Manages persistent vector index, chunk insertion with deduplication, and filtered queries."""

    def __init__(
        self,
        persist_directory: Path = DEFAULT_VECTOR_STORE_DIR,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name

        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(anonymized_telemetry=False, is_persistent=True),
        )
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """Initializes or retrieves the collection configured with cosine distance."""
        return self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": DISTANCE_METRIC},
        )

    def count(self) -> int:
        """Returns the number of indexed chunks in the collection."""
        return self.collection.count()

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single chunk by chunk_id."""
        result = self.collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas"],
        )
        if result and result["ids"]:
            return {
                "chunk_id": result["ids"][0],
                "text": result["documents"][0] if result.get("documents") else "",
                "metadata": result["metadatas"][0] if result.get("metadatas") else {},
            }
        return None

    def get_scheme_chunk_counts(self) -> Dict[str, int]:
        """Returns the distribution of chunks indexed per scheme_id."""
        total = self.count()
        if total == 0:
            return {}

        results = self.collection.get(
            include=["metadatas"],
            limit=total,
        )
        counts: Dict[str, int] = {}
        for meta in results.get("metadatas", []):
            scheme_id = meta.get("scheme_id", "UNKNOWN")
            counts[scheme_id] = counts.get(scheme_id, 0) + 1
        return counts

    def insert_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embedding_service: EmbeddingService,
        batch_size: int = 32,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Inserts chunks into ChromaDB with embeddings, preventing duplicate insertion.
        
        Args:
            chunks: List of chunk dictionaries.
            embedding_service: EmbeddingService instance to compute dense vectors.
            batch_size: Batch size for embedding and insertion.
            overwrite: If False, chunks already present are skipped to avoid redundant work.
            
        Returns:
            Dictionary with statistics: total_submitted, new_indexed, skipped_existing, total_in_collection.
        """
        if not chunks:
            return {
                "total_submitted": 0,
                "new_indexed": 0,
                "skipped_existing": 0,
                "total_in_collection": self.count(),
            }

        # Check existing chunk IDs to ensure idempotency and prevent duplicate work
        existing_ids = set()
        if not overwrite and self.count() > 0:
            all_records = self.collection.get(include=[])
            existing_ids = set(all_records.get("ids", []))

        chunks_to_index = []
        skipped_count = 0

        for chunk in chunks:
            c_id = chunk["chunk_id"]
            if not overwrite and c_id in existing_ids:
                skipped_count += 1
            else:
                chunks_to_index.append(chunk)

        if not chunks_to_index:
            return {
                "total_submitted": len(chunks),
                "new_indexed": 0,
                "skipped_existing": skipped_count,
                "total_in_collection": self.count(),
            }

        # Batch embed and upsert
        new_indexed_count = 0
        for i in range(0, len(chunks_to_index), batch_size):
            batch = chunks_to_index[i : i + batch_size]
            batch_ids = [c["chunk_id"] for c in batch]
            batch_texts = [c["text"] for c in batch]

            # Generate embeddings
            embeddings = embedding_service.embed_passages(batch_texts)

            # Build metadata dict with scalar types supported by Chroma
            batch_metadatas = []
            for c in batch:
                meta = {
                    "scheme_id": str(c.get("scheme_id", "")),
                    "document_id": str(c.get("document_id", "")),
                    "document_name": str(c.get("document_name", "")),
                    "authority": str(c.get("authority", c.get("issuing_authority", ""))),
                    "document_type": str(c.get("document_type", "")),
                    "academic_year": str(c.get("academic_year", "")),
                    "publication_date": str(c.get("publication_date", "")),
                    "page_number": int(c.get("page_number", 0)),
                    "chunk_index_in_page": int(c.get("chunk_index_in_page", 0)),
                    "source_url": str(c.get("source_url", "")),
                    "citation_reference": str(c.get("citation_reference", "")),
                    "language": str(c.get("language", "en")),
                    "char_count": int(c.get("char_count", len(c.get("text", "")))),
                    "word_count": int(c.get("word_count", len(c.get("text", "").split()))),
                }
                batch_metadatas.append(meta)

            self.collection.upsert(
                ids=batch_ids,
                documents=batch_texts,
                embeddings=embeddings,
                metadatas=batch_metadatas,
            )
            new_indexed_count += len(batch)

        return {
            "total_submitted": len(chunks),
            "new_indexed": new_indexed_count,
            "skipped_existing": skipped_count,
            "total_in_collection": self.count(),
        }

    def query(
        self,
        query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Queries the vector index by dense vector with optional metadata filtering."""
        query_kwargs: Dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_kwargs["where"] = where

        return self.collection.query(**query_kwargs)

    def reset(self) -> None:
        """Deletes all chunks and recreates the collection."""
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
        self.collection = self._get_or_create_collection()
