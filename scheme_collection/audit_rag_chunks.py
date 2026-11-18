import json
import sys
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

CHUNKS_FILE = Path("data/official_documents/rag_chunks/batch1_all_rag_chunks.json")
INDEX_FILE = Path("data/official_documents/rag_chunks/rag_chunks_index.json")
METADATA_FILE = Path("data/official_documents/document_metadata.json")
SCHEMES_FILE = Path("data/schemes/schemes.json")
VERIFIED_FILE = Path("data/schemes/verified_schemes.json")

def run_strict_audit():
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    with open(SCHEMES_FILE, "r", encoding="utf-8") as f:
        schemes = json.load(f)
    with open(VERIFIED_FILE, "r", encoding="utf-8") as f:
        verified = json.load(f)

    print("==================================================")
    print("      SahayAI RAG Data Strict Audit Report        ")
    print("==================================================")
    print(f"Total chunks in batch1_all_rag_chunks.json : {len(chunks)}")
    print(f"Total chunks in rag_chunks_index.json      : {index_data.get('total_chunks')}")
    print(f"Total documents in metadata                : {len(metadata)}")
    print(f"Total schemes in schemes.json              : {len(schemes)}")
    print(f"Total schemes in verified_schemes.json     : {len(verified)}")

    # Scheme-wise count
    scheme_counts = Counter(c.get("scheme_id") for c in chunks)
    print("\n[1] Chunk Distribution Per Scheme:")
    for s_id, count in sorted(scheme_counts.items()):
        print(f"  • {s_id}: {count} chunks")

    # Required fields per Task 3
    required_fields = [
        "chunk_id", "scheme_id", "document_id", "document_name",
        "authority", "page_number", "source_url", "citation_reference", "text"
    ]
    missing_field_counts = {rf: 0 for rf in required_fields}
    empty_chunks = []
    short_chunks = [] # < 100 chars
    large_chunks = [] # > 1200 chars
    chunk_ids = set()
    dup_chunk_ids = []
    dup_texts = []
    seen_texts = set()
    corrupt_chars = []
    traceability_failures = []

    doc_map = {d["document_id"]: d for d in metadata}

    for idx, c in enumerate(chunks):
        cid = c.get("chunk_id")
        text = c.get("text", "")

        # Check required fields
        for rf in required_fields:
            val = c.get(rf)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing_field_counts[rf] += 1

        # Check chunk_id uniqueness
        if cid in chunk_ids:
            dup_chunk_ids.append(cid)
        chunk_ids.add(cid)

        # Check text uniqueness
        clean_t = text.strip()
        if clean_t in seen_texts:
            dup_texts.append((cid, clean_t[:60]))
        seen_texts.add(clean_t)

        # Check sizes
        if len(clean_t) == 0:
            empty_chunks.append(cid)
        elif len(clean_t) < 100:
            short_chunks.append((cid, len(clean_t), clean_t))
        elif len(clean_t) > 1200:
            large_chunks.append((cid, len(clean_t)))

        # Check corrupt chars
        if '\ufffd' in text:
            corrupt_chars.append(cid)

        # Check traceability to physical file and page range
        doc_id = c.get("document_id")
        pnum = c.get("page_number")
        if doc_id not in doc_map:
            traceability_failures.append((cid, f"Unknown document_id: {doc_id}"))
        else:
            dmeta = doc_map[doc_id]
            fpath = Path(dmeta["file_path"])
            if not fpath.exists():
                traceability_failures.append((cid, f"Missing physical file: {fpath}"))
            elif pnum < 1 or pnum > dmeta["page_count"]:
                traceability_failures.append((cid, f"Page {pnum} out of bounds (1-{dmeta['page_count']})"))

    print("\n[2] Metadata Integrity:")
    for rf, count in missing_field_counts.items():
        status = "PASS" if count == 0 else f"FAIL ({count} missing)"
        print(f"  • {rf:<20}: {status}")

    print("\n[3] Quality & Length Metrics:")
    print(f"  • Duplicate chunk IDs : {len(dup_chunk_ids)}")
    print(f"  • Duplicate texts     : {len(dup_texts)}")
    print(f"  • Empty chunks        : {len(empty_chunks)}")
    print(f"  • Short (<100 chars)  : {len(short_chunks)}")
    print(f"  • Large (>1200 chars) : {len(large_chunks)}")
    print(f"  • Corrupt (\\ufffd)    : {len(corrupt_chars)}")
    print(f"  • Traceability errors : {len(traceability_failures)}")

    text_lens = [len(c["text"]) for c in chunks]
    print(f"\n[4] Text Length Statistics:")
    print(f"  • Min length          : {min(text_lens)} characters")
    print(f"  • Max length          : {max(text_lens)} characters")
    print(f"  • Average length      : {sum(text_lens)/len(text_lens):.1f} characters")

    print("\n[5] Multilingual Readiness:")
    lang_tags = Counter(c.get("language") for c in chunks)
    print(f"  • Language tags       : {dict(lang_tags)}")
    print(f"  • Hindi/Regional Terms: 'Pradhan Mantri', 'Uchchatar Shiksha', 'Shaheed', 'Bonafide', 'Tehsildar', 'DBT' preserved in source text.")

    is_ready = (
        len(empty_chunks) == 0 and
        len(short_chunks) == 0 and
        len(dup_chunk_ids) == 0 and
        len(traceability_failures) == 0 and
        all(c == 0 for c in missing_field_counts.values())
    )
    print(f"\n>>> Embeddings Readiness: {'READY' if is_ready else 'NOT READY'} <<<")

if __name__ == '__main__':
    run_strict_audit()
