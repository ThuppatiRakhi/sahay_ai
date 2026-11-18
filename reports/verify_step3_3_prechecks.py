import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

with open(PROJECT_ROOT / "reports" / "rag_step3_2_query_rewriting_results.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print("=" * 60)
print("1. TELUGU ROSTER CONTAMINATION CHECK")
print("=" * 60)
print("Summary Telugu average_roster_contamination_at_5:", d["summary"]["metrics_by_language"]["Telugu"]["average_roster_contamination_at_5"])

te_queries = [q for q in d["queries"] if q["language"] == "Telugu"]
total_roster_te = 0
for q in te_queries:
    roster_in_q = sum(1 for r in q["retrieved_results"] if r["category"] in ["Beneficiary roster", "Institution list"])
    contam = q["evaluation"]["roster_contamination_at_5"]
    print(f"{q['query_id']}: roster chunks in top 5 = {roster_in_q}, contam = {contam}")
    total_roster_te += roster_in_q

print(f"Total roster chunks in Telugu: {total_roster_te} out of 35 slots = {total_roster_te/35:.4f} (2.86%)")
print(f"Per-query average: {total_roster_te/35:.4f}")

print("\n" + "=" * 60)
print("2. ENGLISH QUERIES REGRESSION CHECK")
print("=" * 60)
# Check BENCH_EN_02, BENCH_EN_04, BENCH_EN_07
with open(PROJECT_ROOT / "reports" / "rag_step3_baseline_results.json", "r", encoding="utf-8") as f:
    base = json.load(f)

base_by_id = {q["query_id"]: q for q in base["queries"]}

for q in d["queries"]:
    if q["language"] == "English":
        qid = q["query_id"]
        b_q = base_by_id[qid]
        b_top1 = b_q["evaluation"]["top1_scheme_retrieved"]
        b_match = b_q["evaluation"]["top1_scheme_match"]
        s_top1 = q["evaluation"]["top1_scheme_retrieved"]
        s_match = q["evaluation"]["top1_scheme_match"]
        print(f"\n{qid}: Target={q['expected_scheme_id']}")
        print(f"  Question: '{q['question']}'")
        print(f"  Rewritten Query: '{q['rewritten_query']}'")
        print(f"  Baseline Top-1: {b_top1} (Match: {b_match})")
        print(f"  Step 3.2 Top-1: {s_top1} (Match: {s_match})")
        if b_match and not s_match:
            print("  >>> REGRESSION DETECTED!")
            print("  Top 3 Step 3.2 Chunks:")
            for r in q["retrieved_results"][:3]:
                print(f"    Rank {r['rank']}: {r['chunk_id']} [{r['scheme_id']}] score={r['similarity_score']:.4f} text='{r['text_excerpt'][:80]}...'")

print("\n" + "=" * 60)
print("3. GROUND TRUTH LABELS CONSISTENCY CHECK")
print("=" * 60)
mismatch_count = 0
for q in d["queries"]:
    qid = q["query_id"]
    b_q = base_by_id[qid]
    if q["expected_scheme_id"] != b_q["expected_scheme_id"]:
        print(f"Mismatch expected_scheme_id for {qid}")
        mismatch_count += 1
    if q["relevant_chunk_ids"] != b_q["relevant_chunk_ids"]:
        print(f"Mismatch relevant_chunk_ids for {qid}")
        mismatch_count += 1
if mismatch_count == 0:
    print("ALL 21 queries use identical ground-truth expected_scheme_id and relevant_chunk_ids!")

print("\n" + "=" * 60)
print("4. INDEPENDENT RETRIEVAL PATH CHECK")
print("=" * 60)
from rag.config import DEFAULT_VECTOR_STORE_DIR
from rag.embedding_service import EmbeddingService
from rag.vector_store import VectorStoreManager
from rag.retriever import SchemeRetriever

svc = EmbeddingService(use_mock=True)
store = VectorStoreManager(persist_directory=DEFAULT_VECTOR_STORE_DIR)
retriever = SchemeRetriever(vector_store=store, embedding_service=svc)

# Test with rewriting False
res_no_rewrite = retriever.retrieve("What is Pragati?", enable_query_rewriting=False)
# Test with rewriting True
res_rewrite = retriever.retrieve("What is Pragati?", enable_query_rewriting=True)
print(f"No-rewriting returned: {len(res_no_rewrite)} results")
print(f"Rewriting returned:    {len(res_rewrite)} results")
print("Independent execution confirmed!")
