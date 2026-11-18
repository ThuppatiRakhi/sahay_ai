"""
SahayAI Step 3.1: Baseline Benchmark Evaluation Runner
Evaluates CURRENT unmodified RAG retrieval implementation against 21 fixed multilingual queries.
"""

import io
import json
import os
import sys
import time
from pathlib import Path

# Force UTF-8 encoding for Windows stdout/stderr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag.config import (
    DEFAULT_CHUNKS_FILE,
    DEFAULT_VECTOR_STORE_DIR,
    TOTAL_EXPECTED_CHUNKS,
)
from rag.embedding_service import EmbeddingService
from rag.vector_store import VectorStoreManager
from rag.retriever import SchemeRetriever

# 1. Load Chunks and classify data quality
print("Loading all chunks to build classification map...")
with open(DEFAULT_CHUNKS_FILE, "r", encoding="utf-8") as f:
    all_chunks = json.load(f)

chunk_classification = {}
for c in all_chunks:
    cid = c["chunk_id"]
    did = c["document_id"]
    page = c["page_number"]
    text = c["text"]

    if did == "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020":
        cat = "Beneficiary roster"
    elif did == "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26" and 7 <= page <= 41:
        cat = "Institution list"
    elif "FAQS" in did or "FAQs" in c.get("document_name", ""):
        cat = "FAQ"
    elif any(k in text.lower() for k in ["eligibility criteria", "eligibility conditions", "eligibility:", "eligible:", "who is eligible", "1.0 objective", "2.0 eligibility", "3.0 number of scholarship"]):
        cat = "Eligibility"
    else:
        cat = "Policy"

    chunk_classification[cid] = cat

# 2. Fixed Benchmark Dataset: 21 Queries (7 EN, 7 HI, 7 TE)
BENCHMARK_QUERIES = [
    # English Queries
    {
        "query_id": "BENCH_EN_01",
        "question": "What is the minimum disability percentage required for AICTE Saksham scholarship?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01",
        ],
        "category": "Disability criteria",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Saksham guideline chunks mentioning 40% benchmark disability requirement."
    },
    {
        "query_id": "BENCH_EN_02",
        "question": "What is the annual family income ceiling to be eligible for PM-USP CSSS college scholarship?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "relevant_chunk_ids": [
            "DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c01",
            "DOC_EDU_001_CSSS_FAQS_2024_p001_c02",
        ],
        "category": "Family income",
        "is_explicit_scheme": True,
        "expected_behavior": "Return CSSS chunks citing Rs. 4.5 lakh annual parental income ceiling."
    },
    {
        "query_id": "BENCH_EN_03",
        "question": "Who is eligible to apply for AICTE Pragati scholarship for girls?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "relevant_chunk_ids": [
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c02",
            "DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020_p002_c01",
            "DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01",
        ],
        "category": "Eligibility",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Pragati chunks citing max 2 girls per family, technical degree/diploma admission."
    },
    {
        "query_id": "BENCH_EN_04",
        "question": "What documents must be uploaded when applying for AICTE Swanath scholarship?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "relevant_chunk_ids": [
            "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p004_c02",
            "DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021_p003_c01",
            "DOC_EDU_004_SWANATH_FAQS_2022_p002_c02",
        ],
        "category": "Required documents",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Swanath documentation list: death certificate/martyr certificate, income certificate."
    },
    {
        "query_id": "BENCH_EN_05",
        "question": "What financial assistance and allowances are provided under Top Class Education Scheme for SC Students?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC",
        "relevant_chunk_ids": [
            "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01",
            "DOC_EDU_005_TOP_CLASS_SC_FAQS_2022_p001_c02",
        ],
        "category": "Scheme benefits",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Top Class SC provisions: full tuition fee, academic allowance of Rs. 86,000 1st year."
    },
    {
        "query_id": "BENCH_EN_06",
        "question": "I lost both my parents during Covid-19 and got admitted to an engineering college. How do I apply for technical degree scholarship?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "relevant_chunk_ids": [
            "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c01",
            "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p003_c02",
            "DOC_EDU_004_SWANATH_FAQS_2022_p001_c01",
        ],
        "category": "Application procedures",
        "is_explicit_scheme": False,
        "expected_behavior": "Identify Swanath scholarship for Covid orphans and describe online NSP process."
    },
    {
        "query_id": "BENCH_EN_07",
        "question": "Can a student with physical handicap studying diploma engineering get government scholarship support?",
        "language": "English",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c02",
        ],
        "category": "Eligibility",
        "is_explicit_scheme": False,
        "expected_behavior": "Identify Saksham technical scholarship for specially-abled students."
    },

    # Hindi Queries
    {
        "query_id": "BENCH_HI_01",
        "question": "सक्षम छात्रवृत्ति के लिए न्यूनतम दिव्यांगता प्रतिशत क्या होना चाहिए?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01",
        ],
        "category": "Disability criteria",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Saksham chunks establishing minimum 40% benchmark disability requirement."
    },
    {
        "query_id": "BENCH_HI_02",
        "question": "एआईसीटीई प्रगति छात्रवृत्ति के लिए परिवार की वार्षिक आय सीमा कितनी है?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "relevant_chunk_ids": [
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020_p002_c02",
            "DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01",
        ],
        "category": "Family income",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Pragati chunk specifying family income not exceeding Rs. 8 lakh per annum."
    },
    {
        "query_id": "BENCH_HI_03",
        "question": "पीएम-यूएसपी छात्रवृत्ति योजना में कॉलेज के छात्र कैसे पात्र होते हैं?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "relevant_chunk_ids": [
            "DOC_EDU_001_CSSS_GUIDELINES_2024_p001_c01",
            "DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c01",
            "DOC_EDU_001_CSSS_FAQS_2024_p001_c02",
        ],
        "category": "Eligibility",
        "is_explicit_scheme": True,
        "expected_behavior": "Return CSSS eligibility: 80th percentile in Class 12, regular college admission."
    },
    {
        "query_id": "BENCH_HI_04",
        "question": "सक्षम छात्रवृत्ति के लिए कौन सा दिव्यांगता प्रमाण पत्र मान्य है?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p003_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p005_c01",
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p005_c01",
        ],
        "category": "Required documents",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Saksham chunks outlining valid disability certificate from competent authority."
    },
    {
        "query_id": "BENCH_HI_05",
        "question": "अनुसूचित जाति के छात्रों के लिए टॉप क्लास स्कॉलरशिप में कितनी राशि मिलती है?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC",
        "relevant_chunk_ids": [
            "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01",
            "DOC_EDU_005_TOP_CLASS_SC_FAQS_2022_p001_c02",
        ],
        "category": "Scheme benefits",
        "is_explicit_scheme": True,
        "expected_behavior": "Return Top Class SC funding details (tuition fee + academic allowance)."
    },
    {
        "query_id": "BENCH_HI_06",
        "question": "तकनीकी शिक्षा में पढ़ने वाली छात्राओं के लिए सरकारी छात्रवृत्ति कैसे मिलती है?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "relevant_chunk_ids": [
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p003_c02",
            "DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01",
        ],
        "category": "Application procedures",
        "is_explicit_scheme": False,
        "expected_behavior": "Map girl student technical inquiry to Pragati scheme and NSP application steps."
    },
    {
        "query_id": "BENCH_HI_07",
        "question": "अनाथ बच्चों के लिए इंजीनियरिंग कॉलेज की फीस में सहायता वाली योजना कौन सी है?",
        "language": "Hindi",
        "expected_scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "relevant_chunk_ids": [
            "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c01",
            "DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021_p002_c01",
            "DOC_EDU_004_SWANATH_FAQS_2022_p001_c01",
        ],
        "category": "Eligibility",
        "is_explicit_scheme": False,
        "expected_behavior": "Retrieve Swanath scheme orphan provisions of Rs. 50,000/year assistance."
    },

    # Telugu Queries
    {
        "query_id": "BENCH_TE_01",
        "question": "AICTE సక్షమ్ స్కాలర్‌షిప్ పొందడానికి కనీస వికలాంగ శాతం ఎంత ఉండాలి?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01",
        ],
        "category": "Disability criteria",
        "is_explicit_scheme": True,
        "expected_behavior": "Retrieve Saksham guidelines specifying benchmark disability of not less than 40%."
    },
    {
        "query_id": "BENCH_TE_02",
        "question": "స్వానాథ్ స్కాలర్‌షిప్ పథకానికి కుటుంబ వార్షిక ఆదాయ పరిమితి ఎంత?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "relevant_chunk_ids": [
            "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c01",
            "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c02",
            "DOC_EDU_004_SWANATH_FAQS_2022_p001_c01",
        ],
        "category": "Family income",
        "is_explicit_scheme": True,
        "expected_behavior": "Retrieve Swanath chunk citing Rs. 8 lakh per annum income limit."
    },
    {
        "query_id": "BENCH_TE_03",
        "question": "ప్రగతి స్కాలర్‌షిప్ పథకం కింద ఎవరికి దరఖాస్తు చేసుకునే అర్హత ఉంది?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "relevant_chunk_ids": [
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c02",
            "DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01",
        ],
        "category": "Eligibility",
        "is_explicit_scheme": True,
        "expected_behavior": "Retrieve Pragati girl student eligibility criteria in engineering/diploma."
    },
    {
        "query_id": "BENCH_TE_04",
        "question": "పీఎం-యూఎస్‌పీ సెంట్రల్ సెక్టార్ స్కాలర్‌షిప్ కోసం ఏ డాక్యుమెంట్లు సమర్పించాలి?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "relevant_chunk_ids": [
            "DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c02",
            "DOC_EDU_001_CSSS_FAQS_2024_p002_c01",
            "DOC_EDU_001_CSSS_FAQS_2024_p002_c02",
        ],
        "category": "Required documents",
        "is_explicit_scheme": True,
        "expected_behavior": "Retrieve PM-USP CSSS documentation verification criteria."
    },
    {
        "query_id": "BENCH_TE_05",
        "question": "ఏఐసీటీఈ సక్షమ్ స్కాలర్‌షిప్ ద్వారా విద్యార్థులకు ఎంత మొత్తం అందుతుంది?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p003_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c02",
        ],
        "category": "Scheme benefits",
        "is_explicit_scheme": True,
        "expected_behavior": "Retrieve Saksham financial support of Rs. 50,000 per annum."
    },
    {
        "query_id": "BENCH_TE_06",
        "question": "డిగ్రీ లేదా ఇంజనీరింగ్ చదువుతున్న వికలాంగ విద్యార్థులకు ఏ ప్రభుత్వ స్కాలర్‌షిప్ సహాయం ఉంది?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "relevant_chunk_ids": [
            "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01",
            "DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c02",
        ],
        "category": "Eligibility",
        "is_explicit_scheme": False,
        "expected_behavior": "Match disabled student query with Saksham scholarship scheme."
    },
    {
        "query_id": "BENCH_TE_07",
        "question": "టాప్ కాలేజీల్లో సీటు వచ్చిన ఎస్సీ విద్యార్థులకు ఫీజు రీయింబర్స్‌మెంట్ ఎలా లభిస్తుంది?",
        "language": "Telugu",
        "expected_scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC",
        "relevant_chunk_ids": [
            "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p001_c01",
            "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01",
            "DOC_EDU_005_TOP_CLASS_SC_FAQS_2022_p001_c01",
        ],
        "category": "Application procedures",
        "is_explicit_scheme": False,
        "expected_behavior": "Match SC top college query with Top Class SC education funding."
    },
]

# 3. Initialize Existing Retriever
print("Initializing EmbeddingService (intfloat/multilingual-e5-small)...")
embedding_service = EmbeddingService(use_mock=False)
print("Initializing VectorStoreManager...")
vector_store = VectorStoreManager(persist_directory=DEFAULT_VECTOR_STORE_DIR)
retriever = SchemeRetriever(vector_store=vector_store, embedding_service=embedding_service)

print(f"Total vector store chunks: {vector_store.count()}")

# 4. Execute Benchmark Evaluation
results = []
top1_scheme_matches = 0
relevant_hits_at_5 = 0
reciprocal_ranks = []
roster_contaminations = []

by_lang = {"English": {"total": 0, "top1": 0, "hit5": 0, "rr": [], "contam": [], "scores": []},
           "Hindi": {"total": 0, "top1": 0, "hit5": 0, "rr": [], "contam": [], "scores": []},
           "Telugu": {"total": 0, "top1": 0, "hit5": 0, "rr": [], "contam": [], "scores": []}}

print("\nStarting evaluation across 21 queries...")

for idx, item in enumerate(BENCHMARK_QUERIES, start=1):
    qid = item["query_id"]
    qtext = item["question"]
    lang = item["language"]
    expected_scheme = item["expected_scheme_id"]
    relevant_ids = set(item["relevant_chunk_ids"])

    start_t = time.time()
    retrieved = retriever.retrieve(qtext, top_k=5)
    latency = round(time.time() - start_t, 3)

    retrieved_data = []
    top1_match = False
    hit_5 = False
    first_rel_rank = None
    roster_count = 0

    for r_idx, r in enumerate(retrieved, start=1):
        is_rel = r.chunk_id in relevant_ids
        cat = chunk_classification.get(r.chunk_id, "Unknown")
        is_roster_or_list = cat in ["Beneficiary roster", "Institution list"]

        if is_roster_or_list:
            roster_count += 1

        if is_rel and first_rel_rank is None:
            first_rel_rank = r_idx
            hit_5 = True

        if r_idx == 1 and r.scheme_id == expected_scheme:
            top1_match = True

        retrieved_data.append({
            "rank": r_idx,
            "chunk_id": r.chunk_id,
            "scheme_id": r.scheme_id,
            "similarity_score": r.similarity_score,
            "category": cat,
            "is_relevant_policy": is_rel,
            "document_id": r.document_id,
            "page_number": r.page_number,
            "citation_reference": r.citation_reference,
            "text_excerpt": r.text[:220].replace("\n", " ") + ("..." if len(r.text) > 220 else "")
        })

    rr = 1.0 / first_rel_rank if first_rel_rank else 0.0
    reciprocal_ranks.append(rr)
    contam = roster_count / 5.0
    roster_contaminations.append(contam)

    if top1_match:
        top1_scheme_matches += 1
    if hit_5:
        relevant_hits_at_5 += 1

    top1_score = retrieved[0].similarity_score if retrieved else 0.0

    by_lang[lang]["total"] += 1
    if top1_match:
        by_lang[lang]["top1"] += 1
    if hit_5:
        by_lang[lang]["hit5"] += 1
    by_lang[lang]["rr"].append(rr)
    by_lang[lang]["contam"].append(contam)
    by_lang[lang]["scores"].append(top1_score)

    eval_record = {
        "query_id": qid,
        "question": qtext,
        "language": lang,
        "expected_scheme_id": expected_scheme,
        "relevant_chunk_ids": item["relevant_chunk_ids"],
        "category": item["category"],
        "is_explicit_scheme": item["is_explicit_scheme"],
        "expected_behavior": item["expected_behavior"],
        "evaluation": {
            "top1_scheme_match": top1_match,
            "relevant_hit_at_5": hit_5,
            "first_relevant_rank": first_rel_rank,
            "reciprocal_rank": round(rr, 4),
            "roster_contamination_at_5": round(contam, 4),
            "latency_seconds": latency,
            "top1_similarity_score": top1_score,
            "top1_scheme_retrieved": retrieved[0].scheme_id if retrieved else "NONE",
            "top1_chunk_retrieved": retrieved[0].chunk_id if retrieved else "NONE",
        },
        "retrieved_results": retrieved_data
    }
    results.append(eval_record)

    status_icon = "✓" if hit_5 else "✗"
    top1_icon = "✓" if top1_match else "✗"
    print(f"[{idx:02d}/21] {qid} ({lang}): Scheme Top-1={top1_icon} | Rel Hit@5={status_icon} | RR={rr:.2f} | Contam={contam:.1f} | Top1 Score={top1_score:.4f}")

# 5. Compute Aggregate Summary
total_q = len(BENCHMARK_QUERIES)
overall_top1_acc = round(top1_scheme_matches / total_q, 4)
overall_hit5 = round(relevant_hits_at_5 / total_q, 4)
overall_mrr = round(sum(reciprocal_ranks) / total_q, 4)
overall_contam = round(sum(roster_contaminations) / total_q, 4)

summary = {
    "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "embedding_model": "intfloat/multilingual-e5-small",
    "vector_store_chunks_count": vector_store.count(),
    "total_queries_evaluated": total_q,
    "metrics_overall": {
        "top1_scheme_accuracy": overall_top1_acc,
        "relevant_hit_at_5": overall_hit5,
        "mean_reciprocal_rank_mrr": overall_mrr,
        "average_roster_contamination_at_5": overall_contam,
    },
    "metrics_by_language": {},
    "data_quality_chunk_census": {
        "total_chunks": len(all_chunks),
        "classification_counts": {}
    }
}

for cat in ["Policy", "FAQ", "Beneficiary roster", "Institution list", "Eligibility"]:
    count = sum(1 for c in chunk_classification.values() if c == cat)
    summary["data_quality_chunk_census"]["classification_counts"][cat] = {
        "count": count,
        "percentage": round(count / len(all_chunks) * 100, 2)
    }

for lang, data in by_lang.items():
    tot = data["total"]
    summary["metrics_by_language"][lang] = {
        "queries_count": tot,
        "top1_scheme_accuracy": round(data["top1"] / tot, 4),
        "relevant_hit_at_5": round(data["hit5"] / tot, 4),
        "mean_reciprocal_rank_mrr": round(sum(data["rr"]) / tot, 4),
        "average_roster_contamination_at_5": round(sum(data["contam"]) / tot, 4),
        "average_top1_similarity_score": round(sum(data["scores"]) / tot, 4),
    }

final_output = {
    "summary": summary,
    "queries": results
}

# 6. Save JSON Results
out_json_path = PROJECT_ROOT / "reports" / "rag_step3_baseline_results.json"
with open(out_json_path, "w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=2, ensure_ascii=False)

print(f"\nEvaluation complete! Results successfully saved to: {out_json_path}")
print(f"Overall Scheme Top-1 Acc: {overall_top1_acc*100:.1f}%")
print(f"Overall Relevant Hit@5:   {overall_hit5*100:.1f}%")
print(f"Overall MRR:              {overall_mrr:.4f}")
print(f"Overall Roster Contam@5:  {overall_contam*100:.1f}%")

for lang, s in summary["metrics_by_language"].items():
    print(f"  {lang:7s} -> Top1 Acc: {s['top1_scheme_accuracy']*100:.1f}%, Rel Hit@5: {s['relevant_hit_at_5']*100:.1f}%, MRR: {s['mean_reciprocal_rank_mrr']:.4f}, Contam: {s['average_roster_contamination_at_5']*100:.1f}%, AvgScore: {s['average_top1_similarity_score']:.4f}")

