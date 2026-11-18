"""Configuration parameters for SahayAI Multilingual RAG subsystem."""

from pathlib import Path
from dataclasses import dataclass

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_VECTOR_STORE_DIR = DEFAULT_DATA_DIR / "vector_store" / "chroma"
DEFAULT_CHUNKS_FILE = DEFAULT_DATA_DIR / "official_documents" / "rag_chunks" / "batch1_all_rag_chunks.json"
DEFAULT_CHUNKS_INDEX_FILE = DEFAULT_DATA_DIR / "official_documents" / "rag_chunks" / "rag_chunks_index.json"
DEFAULT_METADATA_FILE = DEFAULT_DATA_DIR / "official_documents" / "document_metadata.json"

# Embedding Model Configuration
# intfloat/multilingual-e5-small:
# - Dimension: 384
# - Context length: 512 tokens
# - Languages: 100+ (trained extensively on Indic languages including Hindi and Telugu)
# - Architecture: E5 asymmetric query-passage prefixing
# - Size: ~470 MB (optimized for CPU inference)
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIMENSION = 384
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

# Vector Store Configuration
DEFAULT_COLLECTION_NAME = "sahayai_scheme_guidelines"
DISTANCE_METRIC = "cosine"  # HNSW cosine distance in ChromaDB

# Retrieval Configuration
DEFAULT_TOP_K = 5
MIN_RELEVANCE_SCORE = 0.50

# Policy Disclaimer for RAG outputs
OFFICIAL_DISCLAIMER = (
    "DISCLAIMER: Information retrieved from official government guidelines is provided "
    "for informational and discovery purposes only. Semantic similarity matches do not "
    "constitute official approval, verification, or guarantee of benefit disbursement. "
    "Official eligibility is determined strictly upon application submission and verification "
    "by the competent authority through the designated government portal (e.g., NSP)."
)

# Expected Scheme Distribution for Batch 1 (301 Chunks)
EXPECTED_SCHEME_CHUNKS = {
    "SCHEME_EDU_001_PM_USP_CSSS": 36,
    "SCHEME_EDU_002_AICTE_PRAGATI": 42,
    "SCHEME_EDU_003_AICTE_SAKSHAM": 88,
    "SCHEME_EDU_004_AICTE_SWANATH": 44,
    "SCHEME_EDU_005_TOP_CLASS_SC": 91,
}
TOTAL_EXPECTED_CHUNKS = 301

# Canonical Supported Scheme Catalog for SahayAI (All 10 National Education & Central Welfare Schemes)
SUPPORTED_SCHEMES = {
    # 5 Higher Education & Technical Scholarships
    "SCHEME_EDU_001_PM_USP_CSSS": "PM-USP Central Sector Scholarship Scheme",
    "SCHEME_EDU_002_AICTE_PRAGATI": "AICTE Pragati Scholarship for Girl Students",
    "SCHEME_EDU_003_AICTE_SAKSHAM": "AICTE Saksham Scholarship for Specially-Abled Students",
    "SCHEME_EDU_004_AICTE_SWANATH": "AICTE Swanath Scholarship Scheme",
    "SCHEME_EDU_005_TOP_CLASS_SC": "Top Class Education Scheme for SC Students",
    # 5 Major Central Welfare & Livelihood Schemes
    "SCHEME_AGRI_001_PM_KISAN": "PM-KISAN Samman Nidhi",
    "SCHEME_MSME_001_PMEGP": "Prime Minister's Employment Generation Programme (PMEGP)",
    "SCHEME_URBAN_001_PM_SVANIDHI": "PM SVANidhi (Street Vendors AtmaNirbhar Nidhi)",
    "SCHEME_LABOUR_001_PM_SYM": "Pradhan Mantri Shram Yogi Maandhan (PM-SYM)",
    "SCHEME_WOMEN_001_PMUY_2": "Pradhan Mantri Ujjwala Yojana (PMUY / Ujjwala 2.0)",
}

# Standard Guidance Message for Unsupported Schemes
UNSUPPORTED_SCHEME_MESSAGE = (
    "SahayAI currently specializes in five official national education and scholarship schemes "
    "(PM-USP, AICTE Pragati, AICTE Saksham, AICTE Swanath, Top Class SC) and central welfare schemes "
    "(PM-KISAN, PMEGP, PM SVANidhi, PM-SYM, PMUY 2.0).\n\n"
    "Information about '{scheme_name}' is not currently in our knowledge base. "
    "Please check the respective official ministry portal or visit https://www.myscheme.gov.in."
)

# Standard Clarification Message for Ambiguous Follow-ups
AMBIGUOUS_FOLLOWUP_MESSAGE = (
    "Could you please specify which government scholarship scheme or central welfare scheme you are asking about? "
    "SahayAI provides verified assistance across 10 official central schemes:\n"
    "• Higher Education Scholarships: PM-USP CSSS, AICTE Pragati, AICTE Saksham, AICTE Swanath, Top Class SC\n"
    "• Central Welfare & Livelihoods: PM-KISAN, PMEGP Subsidy, PM SVANidhi, PM-SYM Pension, PM Ujjwala 2.0"
)


