"""
SahayAI Step 3.2 & Step 3.3: Benchmark Evaluation Runner
Evaluates RAG retrieval with QueryRewriter and LightweightReranker across the fixed 21 benchmark queries.
Compares directly against Step 3.1 baseline metrics using identical ground truth labels.
"""

import argparse
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

from rag.config import DEFAULT_CHUNKS_FILE, DEFAULT_VECTOR_STORE_DIR
from rag.embedding_service import EmbeddingService
from rag.vector_store import VectorStoreManager
from rag.retriever import SchemeRetriever
from rag.query_rewriter import QueryRewriter
from rag.reranker import LightweightReranker

parser = argparse.ArgumentParser(description="Run SahayAI Step 3 Benchmark Evaluation")
parser.add_argument("--step", choices=["3.2", "3.3"], default="3.3", help="Evaluation step (3.2 or 3.3)")
parser.add_argument("--pool-size", type=int, default=30, help="Candidate pool size for reranker")
parser.add_argument("--no-rerank", action="store_true", help="Disable reranker (pure dense search)")
parser.add_argument("--no-rewrite", action="store_true", help="Disable query rewriter")
args = parser.parse_args()

enable_reranking = (args.step == "3.3") and not args.no_rerank
enable_rewriting = not args.no_rewrite
step_id = "3.3_lightweight_reranking" if enable_reranking else "3.2_query_rewriting"
out_filename = "rag_step3_3_reranking_results.json" if enable_reranking else "rag_step3_2_query_rewriting_results.json"

# 1. Load baseline queries and classifications from Step 3.1
baseline_results_path = PROJECT_ROOT / "reports" / "rag_step3_baseline_results.json"
with open(baseline_results_path, "r", encoding="utf-8") as f:
    baseline_data = json.load(f)

benchmark_queries = baseline_data["queries"]
baseline_summary = baseline_data["summary"]

# Load Step 3.2 data for delta comparisons if running Step 3.3
step3_2_summary = None
step3_2_path = PROJECT_ROOT / "reports" / "rag_step3_2_query_rewriting_results.json"
if step3_2_path.exists():
    with open(step3_2_path, "r", encoding="utf-8") as f:
        step3_2_summary = json.load(f).get("summary")

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

# 2. Initialize Retriever with QueryRewriter and LightweightReranker
print(f"Initializing SahayAI Benchmark Runner [{step_id}]...")
print("EmbeddingService: intfloat/multilingual-e5-small (CPU)")
embedding_service = EmbeddingService(use_mock=False)
vector_store = VectorStoreManager(persist_directory=DEFAULT_VECTOR_STORE_DIR)
query_rewriter = QueryRewriter()
reranker = LightweightReranker()

retriever = SchemeRetriever(
    vector_store=vector_store,
    embedding_service=embedding_service,
    query_rewriter=query_rewriter,
    reranker=reranker,
)

print(f"Total vector store chunks: {vector_store.count()}")
print(f"Reranking enabled: {enable_reranking} (candidate_pool_size={args.pool_size})")
print(f"Rewriting enabled: {enable_rewriting}")
print("Starting Evaluation across 21 fixed benchmark queries...\n")

results = []
top1_scheme_matches = 0
relevant_hits_at_5 = 0
reciprocal_ranks = []
roster_contaminations = []

by_lang = {
    "English": {"total": 0, "top1": 0, "hit5": 0, "rr": [], "contam": [], "scores": []},
    "Hindi": {"total": 0, "top1": 0, "hit5": 0, "rr": [], "contam": [], "scores": []},
    "Telugu": {"total": 0, "top1": 0, "hit5": 0, "rr": [], "contam": [], "scores": []},
}

for idx, item in enumerate(benchmark_queries, start=1):
    qid = item["query_id"]
    qtext = item["question"]
    lang = item["language"]
    expected_scheme = item["expected_scheme_id"]
    relevant_ids = set(item["relevant_chunk_ids"])

    start_t = time.time()
    retrieved = retriever.retrieve(
        query=qtext,
        top_k=5,
        enable_query_rewriting=enable_rewriting,
        auto_scheme_filter=False,
        enable_reranking=enable_reranking,
        candidate_pool_size=args.pool_size,
    )
    latency = round(time.time() - start_t, 3)

    rewritten_obj = query_rewriter.rewrite(qtext) if enable_rewriting else None

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
            "rerank_score": r.rerank_score,
            "category": cat,
            "is_relevant_policy": is_rel,
            "document_id": r.document_id,
            "document_name": r.document_name,
            "authority": r.authority,
            "source_url": r.source_url,
            "page_number": r.page_number,
            "citation_reference": r.citation_reference,
            "text_excerpt": r.text[:220].replace("\n", " ") + ("..." if len(r.text) > 220 else ""),
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
    top1_r_score = retrieved[0].rerank_score if retrieved else None

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
        "rewritten_query": rewritten_obj.rewritten_query if rewritten_obj else qtext,
        "detected_scheme_id": rewritten_obj.detected_scheme_id if rewritten_obj else None,
        "expanded_terms": rewritten_obj.expanded_terms if rewritten_obj else [],
        "expected_scheme_id": expected_scheme,
        "relevant_chunk_ids": item["relevant_chunk_ids"],
        "category": item["category"],
        "is_explicit_scheme": item["is_explicit_scheme"],
        "evaluation": {
            "top1_scheme_match": top1_match,
            "relevant_hit_at_5": hit_5,
            "first_relevant_rank": first_rel_rank,
            "reciprocal_rank": round(rr, 4),
            "roster_contamination_at_5": round(contam, 4),
            "latency_seconds": latency,
            "top1_similarity_score": top1_score,
            "top1_rerank_score": top1_r_score,
            "top1_scheme_retrieved": retrieved[0].scheme_id if retrieved else "NONE",
            "top1_chunk_retrieved": retrieved[0].chunk_id if retrieved else "NONE",
        },
        "retrieved_results": retrieved_data,
    }
    results.append(eval_record)

    hit_icon = "✓" if hit_5 else "✗"
    top1_icon = "✓" if top1_match else "✗"
    score_display = f"Top1 Sim={top1_score:.4f}"
    if top1_r_score is not None:
        score_display += f" | Rerank={top1_r_score:.4f}"
    print(f"[{idx:02d}/21] {qid} ({lang}): Scheme Top1={top1_icon} | Rel Hit@5={hit_icon} | RR={rr:.2f} | Contam={contam:.1f} | {score_display}")

# 3. Compute Aggregates
total_q = len(benchmark_queries)
overall_top1_acc = round(top1_scheme_matches / total_q, 4)
overall_hit5 = round(relevant_hits_at_5 / total_q, 4)
overall_mrr = round(sum(reciprocal_ranks) / total_q, 4)
overall_contam = round(sum(roster_contaminations) / total_q, 4)

summary = {
    "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "step": step_id,
    "embedding_model": "intfloat/multilingual-e5-small",
    "reranker_config": {
        "enabled": enable_reranking,
        "candidate_pool_size": args.pool_size if enable_reranking else None,
        "scoring_formula": "rerank_score = similarity_score + Δ_scheme + Δ_type + Δ_topic",
        "parameters": {
            "scheme_boost": reranker.scheme_boost,
            "scheme_penalty": reranker.scheme_penalty,
            "roster_penalty": reranker.roster_penalty,
            "inst_penalty": reranker.inst_penalty,
            "type_boost": reranker.type_boost,
            "topic_boost": reranker.topic_boost,
        } if enable_reranking else None,
    },
    "vector_store_chunks_count": vector_store.count(),
    "total_queries_evaluated": total_q,
    "metrics_overall": {
        "top1_scheme_accuracy": overall_top1_acc,
        "relevant_hit_at_5": overall_hit5,
        "mean_reciprocal_rank_mrr": overall_mrr,
        "average_roster_contamination_at_5": overall_contam,
    },
    "metrics_by_language": {},
    "baseline_comparison": {
        "baseline_overall": baseline_summary["metrics_overall"],
        "delta_vs_baseline": {
            "top1_scheme_accuracy": round(overall_top1_acc - baseline_summary["metrics_overall"]["top1_scheme_accuracy"], 4),
            "relevant_hit_at_5": round(overall_hit5 - baseline_summary["metrics_overall"]["relevant_hit_at_5"], 4),
            "mean_reciprocal_rank_mrr": round(overall_mrr - baseline_summary["metrics_overall"]["mean_reciprocal_rank_mrr"], 4),
            "average_roster_contamination_at_5": round(overall_contam - baseline_summary["metrics_overall"]["average_roster_contamination_at_5"], 4),
        }
    }
}

if step3_2_summary:
    summary["step3_2_comparison"] = {
        "step3_2_overall": step3_2_summary["metrics_overall"],
        "delta_vs_step3_2": {
            "top1_scheme_accuracy": round(overall_top1_acc - step3_2_summary["metrics_overall"]["top1_scheme_accuracy"], 4),
            "relevant_hit_at_5": round(overall_hit5 - step3_2_summary["metrics_overall"]["relevant_hit_at_5"], 4),
            "mean_reciprocal_rank_mrr": round(overall_mrr - step3_2_summary["metrics_overall"]["mean_reciprocal_rank_mrr"], 4),
            "average_roster_contamination_at_5": round(overall_contam - step3_2_summary["metrics_overall"]["average_roster_contamination_at_5"], 4),
        }
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
        "delta_vs_baseline": {
            "top1_scheme_accuracy": round((data["top1"] / tot) - baseline_summary["metrics_by_language"][lang]["top1_scheme_accuracy"], 4),
            "relevant_hit_at_5": round((data["hit5"] / tot) - baseline_summary["metrics_by_language"][lang]["relevant_hit_at_5"], 4),
            "mean_reciprocal_rank_mrr": round((sum(data["rr"]) / tot) - baseline_summary["metrics_by_language"][lang]["mean_reciprocal_rank_mrr"], 4),
        }
    }

final_output = {
    "summary": summary,
    "queries": results,
}

out_json_path = PROJECT_ROOT / "reports" / out_filename
with open(out_json_path, "w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=2, ensure_ascii=False)

print(f"\nBenchmark complete! Results saved to: {out_json_path}")
print(f"Overall Scheme Top-1: {overall_top1_acc*100:.1f}% (Baseline: {baseline_summary['metrics_overall']['top1_scheme_accuracy']*100:.1f}%) [Δ: {(overall_top1_acc - baseline_summary['metrics_overall']['top1_scheme_accuracy'])*100:+.1f}%]")
print(f"Overall Rel Hit@5:   {overall_hit5*100:.1f}% (Baseline: {baseline_summary['metrics_overall']['relevant_hit_at_5']*100:.1f}%) [Δ: {(overall_hit5 - baseline_summary['metrics_overall']['relevant_hit_at_5'])*100:+.1f}%]")
print(f"Overall MRR:         {overall_mrr:.4f} (Baseline: {baseline_summary['metrics_overall']['mean_reciprocal_rank_mrr']:.4f}) [Δ: {overall_mrr - baseline_summary['metrics_overall']['mean_reciprocal_rank_mrr']:+.4f}]")
print(f"Overall Contam@5:    {overall_contam*100:.1f}% (Baseline: {baseline_summary['metrics_overall']['average_roster_contamination_at_5']*100:.1f}%) [Δ: {(overall_contam - baseline_summary['metrics_overall']['average_roster_contamination_at_5'])*100:+.1f}%]")

for lang, s in summary["metrics_by_language"].items():
    b_lang = baseline_summary["metrics_by_language"][lang]
    print(f"  {lang:7s} -> Top1: {s['top1_scheme_accuracy']*100:.1f}% (Δ: {(s['top1_scheme_accuracy'] - b_lang['top1_scheme_accuracy'])*100:+.1f}%), Rel Hit@5: {s['relevant_hit_at_5']*100:.1f}% (Δ: {(s['relevant_hit_at_5'] - b_lang['relevant_hit_at_5'])*100:+.1f}%), MRR: {s['mean_reciprocal_rank_mrr']:.4f} (Δ: {s['mean_reciprocal_rank_mrr'] - b_lang['mean_reciprocal_rank_mrr']:+.4f})")


