import json
import re
from pathlib import Path
import pypdf

METADATA_PATH = Path("data/official_documents/document_metadata.json")
RAG_CHUNKS_DIR = Path("data/official_documents/rag_chunks")

def clean_text_improved(text: str) -> str:
    """Normalize typography, line breaks, and strip standalone page numbers."""
    if not text:
        return ""

    # Normalize unicode quotes, dashes and bullets
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2013', '-').replace('\u2014', '-')
    text = text.replace('\u2022', '*').replace('\u2026', '...')
    text = text.replace('\u00a0', ' ')

    # Remove control characters except newline and tab
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', ' ', text)

    # Remove standalone page footer/header numbers like 'Page 1 of 8' or 'Page 7 of 7'
    text = re.sub(r'(?im)^\s*page\s+\d+\s+of\s+\d+\s*$', '', text)
    text = re.sub(r'(?im)^\s*page\s+\d+\s*$', '', text)

    # Normalize line breaks and multiple spaces
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def split_into_segments(page_text: str, max_segment_chars: int = 1000) -> list[str]:
    """
    Break page text into logical segments: paragraphs, numbered items, or sentences.
    """
    cleaned = clean_text_improved(page_text)
    if not cleaned or len(cleaned) < 25:
        return []

    paras = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    segments = []

    for para in paras:
        if len(para) <= max_segment_chars:
            segments.append(para)
        else:
            lines = [l.strip() for l in para.split("\n") if l.strip()]
            sub_accum = ""
            for line in lines:
                if len(sub_accum) + len(line) + 1 <= max_segment_chars:
                    sub_accum = (sub_accum + "\n" + line).strip() if sub_accum else line
                else:
                    if sub_accum:
                        segments.append(sub_accum)
                    if len(line) > max_segment_chars:
                        sentences = re.split(r'(?<=[.!?])\s+', line)
                        sent_accum = ""
                        for sent in sentences:
                            if len(sent_accum) + len(sent) + 1 <= max_segment_chars:
                                sent_accum = (sent_accum + " " + sent).strip() if sent_accum else sent
                            else:
                                if sent_accum:
                                    segments.append(sent_accum)
                                sent_accum = sent
                        if sent_accum:
                            sub_accum = sent_accum
                        else:
                            sub_accum = ""
                    else:
                        sub_accum = line
            if sub_accum:
                segments.append(sub_accum)

    return segments

def build_chunks_for_page(
    page_text: str,
    max_chunk_chars: int = 1000,
    min_chunk_chars: int = 250,
    overlap_chars: int = 150
) -> list[str]:
    """
    Assemble segments into cohesive chunks with semantic overlap.
    """
    segments = split_into_segments(page_text, max_segment_chars=max_chunk_chars)
    if not segments:
        return []

    chunks = []
    current_chunk = ""

    for seg in segments:
        if not current_chunk:
            current_chunk = seg
        elif len(current_chunk) + len(seg) + 2 <= max_chunk_chars:
            current_chunk += "\n\n" + seg
        else:
            chunks.append(current_chunk.strip())
            overlap = ""
            if len(current_chunk) > overlap_chars:
                last_part = current_chunk[-overlap_chars:]
                last_space = last_part.find(" ")
                if last_space != -1:
                    overlap = last_part[last_space:].strip()
                else:
                    overlap = last_part.strip()
            else:
                overlap = current_chunk.strip()

            if overlap:
                current_chunk = overlap + "\n\n" + seg
            else:
                current_chunk = seg

    if current_chunk.strip():
        # Merge tiny trailing chunk if previous chunk has headroom
        if chunks and len(current_chunk.strip()) < min_chunk_chars and len(chunks[-1]) + len(current_chunk.strip()) + 2 <= max_chunk_chars + 200:
            chunks[-1] += "\n\n" + current_chunk.strip()
        else:
            chunks.append(current_chunk.strip())

    return chunks

def process_documents_for_rag(
    metadata_path: Path = METADATA_PATH,
    output_dir: Path = RAG_CHUNKS_DIR,
    max_chunk_chars: int = 1000,
    min_chunk_chars: int = 250,
    overlap_chars: int = 150
) -> dict:
    """
    Prepare downloaded official PDFs for the future RAG pipeline.
    Preserves page numbers, scheme IDs, source metadata, authority, and traceable citations.
    """
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata_list = json.load(f)

    all_chunks = []
    summary_stats = {
        "total_documents": len(metadata_list),
        "total_pages": 0,
        "total_chunks": 0,
        "chunks_per_scheme": {},
        "documents_processed": []
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    for doc in metadata_list:
        if not doc.get("opens_correctly"):
            print(f"Skipping {doc['document_id']}: File failed download")
            continue

        file_path = Path(doc["file_path"])
        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue

        scheme_id = doc["scheme_id"]
        scheme_folder = file_path.parent.name
        doc_output_dir = output_dir / scheme_folder
        doc_output_dir.mkdir(parents=True, exist_ok=True)

        reader = pypdf.PdfReader(str(file_path))
        num_pages = len(reader.pages)
        summary_stats["total_pages"] += num_pages

        doc_chunks = []

        for page_idx, page in enumerate(reader.pages):
            page_num = page_idx + 1
            raw_text = page.extract_text() or ""
            chunks = build_chunks_for_page(
                raw_text,
                max_chunk_chars=max_chunk_chars,
                min_chunk_chars=min_chunk_chars,
                overlap_chars=overlap_chars
            )

            for chunk_idx, chunk_text in enumerate(chunks):
                chunk_id = f"{doc['document_id']}_p{page_num:03d}_c{chunk_idx + 1:02d}"
                citation_reference = (
                    f"[{doc['document_name']}, Page {page_num}] "
                    f"({doc['issuing_authority']}, {doc['academic_year']}) "
                    f"Source: {doc['source_url']}"
                )

                authority = doc.get("issuing_authority")

                chunk_record = {
                    "chunk_id": chunk_id,
                    "scheme_id": scheme_id,
                    "document_id": doc["document_id"],
                    "document_name": doc["document_name"],
                    "authority": authority,
                    "issuing_authority": authority,
                    "document_type": doc["document_type"],
                    "academic_year": doc["academic_year"],
                    "publication_date": doc["publication_date"],
                    "page_number": page_num,
                    "chunk_index_in_page": chunk_idx + 1,
                    "source_url": doc["source_url"],
                    "file_path": doc["file_path"],
                    "citation_reference": citation_reference,
                    "language": "en",
                    "char_count": len(chunk_text),
                    "word_count": len(chunk_text.split()),
                    "text": chunk_text
                }
                doc_chunks.append(chunk_record)
                all_chunks.append(chunk_record)

        # Save document-level chunks
        doc_chunks_file = doc_output_dir / f"{doc['document_id']}_chunks.json"
        with open(doc_chunks_file, "w", encoding="utf-8") as f:
            json.dump(doc_chunks, f, indent=2, ensure_ascii=False)

        summary_stats["total_chunks"] += len(doc_chunks)
        summary_stats["chunks_per_scheme"][scheme_id] = (
            summary_stats["chunks_per_scheme"].get(scheme_id, 0) + len(doc_chunks)
        )
        summary_stats["documents_processed"].append({
            "document_id": doc["document_id"],
            "scheme_id": scheme_id,
            "document_name": doc["document_name"],
            "page_count": num_pages,
            "chunk_count": len(doc_chunks),
            "chunks_file": str(doc_chunks_file).replace("\\", "/")
        })

    # Save master index
    index_file = output_dir / "rag_chunks_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(summary_stats, f, indent=2, ensure_ascii=False)

    # Save complete merged batch 1 chunks
    master_chunks_file = output_dir / "batch1_all_rag_chunks.json"
    with open(master_chunks_file, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)

    print("\nRAG Preparation Complete!")
    print(f"Total documents: {summary_stats['total_documents']}")
    print(f"Total pages processed: {summary_stats['total_pages']}")
    print(f"Total chunks created: {summary_stats['total_chunks']}")
    print("Chunks per scheme:", summary_stats["chunks_per_scheme"])
    print(f"Master index saved to: {index_file}")
    print(f"Batch 1 chunks saved to: {master_chunks_file}")

    return summary_stats

if __name__ == '__main__':
    process_documents_for_rag()
