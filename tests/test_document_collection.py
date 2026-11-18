import json
from pathlib import Path
import pytest
import pypdf

DOCS_DIR = Path("data/official_documents")
METADATA_PATH = DOCS_DIR / "document_metadata.json"
CHUNKS_INDEX_PATH = DOCS_DIR / "rag_chunks" / "rag_chunks_index.json"
BATCH1_CHUNKS_PATH = DOCS_DIR / "rag_chunks" / "batch1_all_rag_chunks.json"

EXPECTED_SCHEME_IDS = [
    "SCHEME_EDU_001_PM_USP_CSSS",
    "SCHEME_EDU_002_AICTE_PRAGATI",
    "SCHEME_EDU_003_AICTE_SAKSHAM",
    "SCHEME_EDU_004_AICTE_SWANATH",
    "SCHEME_EDU_005_TOP_CLASS_SC"
]

EXPECTED_FOLDERS = [
    "PM_USP",
    "PRAGATI",
    "SAKSHAM",
    "SWANATH",
    "TOP_CLASS_SC"
]

def test_document_folders_exist():
    assert DOCS_DIR.exists(), "Official documents directory does not exist"
    for folder in EXPECTED_FOLDERS:
        folder_path = DOCS_DIR / folder
        assert folder_path.exists() and folder_path.is_dir(), f"Folder {folder} is missing"

def test_metadata_file_validity():
    assert METADATA_PATH.exists(), "document_metadata.json does not exist"
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    assert isinstance(metadata, list)
    assert len(metadata) >= 5, "Metadata should contain records for all Batch 1 schemes"

def test_all_expected_schemes_covered_in_metadata():
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    covered_schemes = {doc["scheme_id"] for doc in metadata}
    for expected_id in EXPECTED_SCHEME_IDS:
        assert expected_id in covered_schemes, f"Scheme {expected_id} is missing in document metadata"

def test_metadata_fields_and_file_existence():
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    required_fields = [
        "document_id", "scheme_id", "document_name", "issuing_authority",
        "document_type", "publication_date", "academic_year", "source_url",
        "download_date", "file_path", "verification_status", "page_count"
    ]

    for doc in metadata:
        for rf in required_fields:
            assert rf in doc, f"Field {rf} missing in document {doc.get('document_id')}"
        assert doc["page_count"] is not None and doc["page_count"] > 0
        assert doc["opens_correctly"] is True, f"Document {doc['document_id']} failed to open"
        assert doc["contains_readable_text"] is True, f"Document {doc['document_id']} does not contain readable text"

        file_path = Path(doc["file_path"])
        assert file_path.exists(), f"Physical file missing for {doc['file_path']}"
        assert file_path.stat().st_size > 1000, f"File {doc['file_path']} is suspiciously small"

def test_downloaded_pdfs_open_with_pypdf():
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    for doc in metadata:
        file_path = Path(doc["file_path"])
        reader = pypdf.PdfReader(str(file_path))
        assert len(reader.pages) == doc["page_count"]
        first_page_text = reader.pages[0].extract_text()
        assert first_page_text is not None and len(first_page_text.strip()) > 0

def test_rag_chunks_structure_and_traceability():
    assert CHUNKS_INDEX_PATH.exists(), "RAG chunks index missing"
    assert BATCH1_CHUNKS_PATH.exists(), "Batch 1 chunks master file missing"

    with open(BATCH1_CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    assert len(chunks) > 0, "No RAG chunks created"

    required_chunk_fields = [
        "chunk_id", "scheme_id", "document_id", "document_name",
        "authority", "issuing_authority", "document_type", "academic_year", "publication_date",
        "page_number", "chunk_index_in_page", "source_url", "file_path",
        "citation_reference", "language", "char_count", "word_count", "text"
    ]

    seen_chunk_ids = set()
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    doc_map = {d["document_id"]: d for d in metadata}

    for chunk in chunks:
        for cf in required_chunk_fields:
            assert cf in chunk, f"Chunk {chunk.get('chunk_id')} missing {cf}"

        # Uniqueness
        assert chunk["chunk_id"] not in seen_chunk_ids, f"Duplicate chunk_id: {chunk['chunk_id']}"
        seen_chunk_ids.add(chunk["chunk_id"])

        # Page validation & bounds
        assert chunk["page_number"] >= 1
        dmeta = doc_map[chunk["document_id"]]
        assert chunk["page_number"] <= dmeta["page_count"]

        # Size and text sanity
        text = chunk["text"]
        assert len(text.strip()) >= 100, f"Chunk {chunk['chunk_id']} is too short ({len(text)} chars)"
        assert len(text) <= 1250, f"Chunk {chunk['chunk_id']} exceeds max bound ({len(text)} chars)"
        assert "\ufffd" not in text, f"Chunk {chunk['chunk_id']} contains replacement char"
        assert chunk["char_count"] == len(text)
        assert chunk["word_count"] == len(text.split())

        # Source URL and citations
        assert chunk["source_url"].startswith("http")
        assert f"Page {chunk['page_number']}" in chunk["citation_reference"]
        assert chunk["authority"] == chunk["issuing_authority"]
        assert chunk["language"] == "en"

def test_rag_chunks_distribution_and_index_match():
    with open(CHUNKS_INDEX_PATH, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    with open(BATCH1_CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    assert index_data["total_chunks"] == len(chunks)
    assert index_data["total_documents"] == 13
    assert index_data["total_pages"] == 126

    for sid in EXPECTED_SCHEME_IDS:
        count_in_index = index_data["chunks_per_scheme"].get(sid, 0)
        count_in_chunks = sum(1 for c in chunks if c["scheme_id"] == sid)
        assert count_in_index == count_in_chunks
        assert count_in_chunks > 0

def test_schemes_json_and_verified_schemes_intact():
    schemes_file = Path("data/schemes/schemes.json")
    verified_file = Path("data/schemes/verified_schemes.json")

    assert schemes_file.exists()
    assert verified_file.exists()

    with open(schemes_file, "r", encoding="utf-8") as f:
        schemes = json.load(f)
    assert len(schemes) == 5
    for s in schemes:
        assert s["verification_status"] == "pending_review"
        assert s["is_verified"] is False

    with open(verified_file, "r", encoding="utf-8") as f:
        verified = json.load(f)
    assert verified == []
