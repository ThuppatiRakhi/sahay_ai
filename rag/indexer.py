"""Indexer script to populate ChromaDB vector store with audited official scheme chunks."""

import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

from .config import (
    DEFAULT_CHUNKS_FILE,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_VECTOR_STORE_DIR,
    EMBEDDING_DIMENSION,
    EXPECTED_SCHEME_CHUNKS,
    TOTAL_EXPECTED_CHUNKS,
)
from .embedding_service import EmbeddingService
from .vector_store import VectorStoreManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_chunks(chunks_path: Path = DEFAULT_CHUNKS_FILE) -> List[Dict[str, Any]]:
    """Loads and validates official preprocessed chunks from JSON file."""
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    if not isinstance(chunks, list):
        raise ValueError(f"Expected list of chunks, got {type(chunks)}")

    logger.info("Loaded %d chunks from %s", len(chunks), chunks_path)
    return chunks


def validate_chunks_integrity(chunks: List[Dict[str, Any]]) -> Dict[str, int]:
    """Validates that loaded chunks conform to the expected distribution and have required fields."""
    if len(chunks) != TOTAL_EXPECTED_CHUNKS:
        raise ValueError(
            f"Chunk count mismatch: expected {TOTAL_EXPECTED_CHUNKS}, got {len(chunks)}"
        )

    chunk_ids = set()
    scheme_counts: Dict[str, int] = {}
    required_keys = [
        "chunk_id",
        "scheme_id",
        "document_id",
        "document_name",
        "page_number",
        "source_url",
        "citation_reference",
        "text",
    ]

    for idx, c in enumerate(chunks):
        c_id = c.get("chunk_id")
        if not c_id:
            raise ValueError(f"Chunk at index {idx} has missing chunk_id.")
        if c_id in chunk_ids:
            raise ValueError(f"Duplicate chunk_id detected: {c_id}")
        chunk_ids.add(c_id)

        for key in required_keys:
            if key not in c:
                raise ValueError(f"Chunk {c_id} is missing required key '{key}'")

        s_id = c["scheme_id"]
        scheme_counts[s_id] = scheme_counts.get(s_id, 0) + 1

    for s_id, expected_count in EXPECTED_SCHEME_CHUNKS.items():
        actual = scheme_counts.get(s_id, 0)
        if actual != expected_count:
            raise ValueError(
                f"Scheme chunk mismatch for {s_id}: expected {expected_count}, got {actual}"
            )

    logger.info("Chunks integrity validated: 301 chunks across 5 schemes match expected counts.")
    return scheme_counts


def index_all_chunks(
    chunks_path: Path = DEFAULT_CHUNKS_FILE,
    persist_dir: Path = DEFAULT_VECTOR_STORE_DIR,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    use_mock: bool = False,
    batch_size: int = 32,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Indexes all 301 audited chunks into the ChromaDB vector database.

    Args:
        chunks_path: Path to batch1_all_rag_chunks.json
        persist_dir: Directory where ChromaDB SQLite and index files are stored.
        model_name: HuggingFace model identifier.
        use_mock: If True, uses deterministic mock embeddings for offline testing.
        batch_size: Number of chunks per embedding and insertion batch.
        overwrite: If True, forces re-embedding and upserting all chunks.

    Returns:
        Summary dictionary with indexing stats and verification status.
    """
    start_time = time.time()
    chunks = load_chunks(chunks_path)
    validate_chunks_integrity(chunks)

    logger.info("Initializing EmbeddingService (model=%s, mock=%s)...", model_name, use_mock)
    embedding_service = EmbeddingService(model_name=model_name, use_mock=use_mock)

    logger.info("Initializing VectorStoreManager (persist_dir=%s)...", persist_dir)
    vector_store = VectorStoreManager(persist_directory=persist_dir)

    initial_count = vector_store.count()
    logger.info("Current vector store chunk count: %d", initial_count)

    logger.info("Indexing chunks into ChromaDB (batch_size=%d)...", batch_size)
    insert_stats = vector_store.insert_chunks(
        chunks=chunks,
        embedding_service=embedding_service,
        batch_size=batch_size,
        overwrite=overwrite,
    )

    final_count = vector_store.count()
    scheme_distribution = vector_store.get_scheme_chunk_counts()
    elapsed = round(time.time() - start_time, 2)

    logger.info(
        "Indexing complete in %.2fs. Inserted: %d, Skipped: %d, Final Total: %d",
        elapsed,
        insert_stats["new_indexed"],
        insert_stats["skipped_existing"],
        final_count,
    )

    summary = {
        "status": "success",
        "chunks_file": str(chunks_path),
        "vector_store_dir": str(persist_dir),
        "embedding_model": model_name,
        "embedding_dimension": embedding_service.dimension,
        "total_expected": TOTAL_EXPECTED_CHUNKS,
        "total_indexed": final_count,
        "new_indexed": insert_stats["new_indexed"],
        "skipped_existing": insert_stats["skipped_existing"],
        "scheme_distribution": scheme_distribution,
        "elapsed_seconds": elapsed,
    }

    return summary


def main():
    """CLI runner for RAG chunk indexer."""
    print("=" * 70)
    print("SahayAI — Official Scheme Chunks Vector Store Indexer")
    print("=" * 70)

    try:
        summary = index_all_chunks()
        print("\nINDEXING SUMMARY:")
        print(f"Status:               {summary['status'].upper()}")
        print(f"Embedding Model:      {summary['embedding_model']}")
        print(f"Embedding Dimension:  {summary['embedding_dimension']}")
        print(f"Total Chunks:         {summary['total_indexed']} / {summary['total_expected']}")
        print(f"New Inserted:         {summary['new_indexed']}")
        print(f"Skipped (Idempotent): {summary['skipped_existing']}")
        print(f"Elapsed Time:         {summary['elapsed_seconds']}s")
        print("\nScheme Distribution:")
        for s_id, count in summary["scheme_distribution"].items():
            expected = EXPECTED_SCHEME_CHUNKS.get(s_id, "?")
            print(f"  - {s_id}: {count} chunks (expected: {expected})")
        print("=" * 70)
        return 0
    except Exception as e:
        logger.error("Indexing failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
