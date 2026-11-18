"""
Script to independently verify all calculations, relevance labels,
corpus classification, and citation correctness for Step 3.1.
"""

import json
from pathlib import Path
from collections import Counter

# 1. Load results JSON
results_path = Path("c:/Users/Hiii/OneDrive/Desktop/Sahay_ai/reports/rag_step3_baseline_results.json")
with open(results_path, "r", encoding="utf-8") as f:
    data = json.load(f)

summary = data["summary"]
queries = data["queries"]

print("=" * 70)
print("SECTION 1: INDEPENDENT METRICS RECALCULATION")
print("=" * 70)

total_q = len(queries)
top1_scheme_count = 0
rel_hit5_count = 0
rr_sum = 0.0
contam_sum = 0.0

lang_stats = {}

for q in queries:
    lang = q["language"]
    if lang not in lang_stats:
        lang_stats[lang] = {"count": 0, "top1": 0, "hit5": 0, "rr_sum": 0.0, "contam_sum": 0.0}

    ev = q["evaluation"]
    top1_match = ev["top1_scheme_match"]
    hit5 = ev["relevant_hit_at_5"]
    rr = ev["reciprocal_rank"]
    contam = ev["roster_contamination_at_5"]

    # Also independently verify from retrieved_results
    retrieved = q["retrieved_results"]
    expected_scheme = q["expected_scheme_id"]
    rel_chunk_ids = set(q["relevant_chunk_ids"])

    # Independent check of top1_match
    indep_top1_match = (retrieved[0]["scheme_id"] == expected_scheme) if retrieved else False
    assert indep_top1_match == top1_match, f"Mismatch in top1_match for {q['query_id']}"

    # Independent check of hit5 and first_relevant_rank
    indep_hit5 = False
    indep_first_rank = None
    indep_roster_count = 0
    for r_idx, r in enumerate(retrieved, start=1):
        if r["chunk_id"] in rel_chunk_ids and indep_first_rank is None:
            indep_first_rank = r_idx
            indep_hit5 = True
        if r["category"] in ["Beneficiary roster", "Institution list"]:
            indep_roster_count += 1

    assert indep_hit5 == hit5, f"Mismatch in hit5 for {q['query_id']}: ev says {hit5}, indep says {indep_hit5}"
    indep_rr = 1.0 / indep_first_rank if indep_first_rank else 0.0
    assert abs(indep_rr - rr) < 1e-4, f"Mismatch in RR for {q['query_id']}"
    indep_contam = indep_roster_count / 5.0
    assert abs(indep_contam - contam) < 1e-4, f"Mismatch in contam for {q['query_id']}"

    if top1_match:
        top1_scheme_count += 1
        lang_stats[lang]["top1"] += 1
    if hit5:
        rel_hit5_count += 1
        lang_stats[lang]["hit5"] += 1
    rr_sum += rr
    contam_sum += contam
    lang_stats[lang]["count"] += 1
    lang_stats[lang]["rr_sum"] += rr
    lang_stats[lang]["contam_sum"] += contam

print(f"Total queries: {total_q}")
print(f"Overall Top-1 Scheme Accuracy: {top1_scheme_count} / {total_q} = {top1_scheme_count/total_q:.4f} (Reported: {summary['metrics_overall']['top1_scheme_accuracy']})")
print(f"Overall Relevant Hit@5:         {rel_hit5_count} / {total_q} = {rel_hit5_count/total_q:.4f} (Reported: {summary['metrics_overall']['relevant_hit_at_5']})")
print(f"Overall MRR:                    {rr_sum/total_q:.4f} (Reported: {summary['metrics_overall']['mean_reciprocal_rank_mrr']})")
print(f"Overall Roster Contamination@5: {contam_sum/total_q:.4f} (Reported: {summary['metrics_overall']['average_roster_contamination_at_5']})")

print("\nBy Language:")
for lang, s in lang_stats.items():
    c = s["count"]
    rep = summary["metrics_by_language"][lang]
    print(f"  {lang:7s} (n={c}):")
    print(f"    Top1 Scheme Acc: {s['top1']}/{c} = {s['top1']/c:.4f} (Reported: {rep['top1_scheme_accuracy']})")
    print(f"    Relevant Hit@5:  {s['hit5']}/{c} = {s['hit5']/c:.4f} (Reported: {rep['relevant_hit_at_5']})")
    print(f"    MRR:             {s['rr_sum']/c:.4f} (Reported: {rep['mean_reciprocal_rank_mrr']})")
    print(f"    Roster Contam:   {s['contam_sum']/c:.4f} (Reported: {rep['average_roster_contamination_at_5']})")

print("\n" + "=" * 70)
print("SECTION 2: RELEVANCE LABELS & AMBIGUITY AUDIT")
print("=" * 70)

with open("c:/Users/Hiii/OneDrive/Desktop/Sahay_ai/data/official_documents/rag_chunks/batch1_all_rag_chunks.json", "r", encoding="utf-8") as f:
    chunks_raw = json.load(f)

chunks_by_id = {c["chunk_id"]: c for c in chunks_raw}

for q in queries:
    qid = q["query_id"]
    qtext = q["question"]
    lang = q["language"]
    cat = q["category"]
    rel_ids = q["relevant_chunk_ids"]
    is_explicit = q["is_explicit_scheme"]
    top1_retrieved = q["retrieved_results"][0]

    print(f"\n[{qid}] ({lang}) {cat} | Explicit: {is_explicit}")
    print(f"  Q: \"{qtext}\"")
    print(f"  Expected Scheme: {q['expected_scheme_id']}")
    print(f"  Ground Truth Relevant Chunk IDs: {rel_ids}")
    for cid in rel_ids:
        chunk_obj = chunks_by_id.get(cid)
        if chunk_obj:
            snippet = chunk_obj["text"][:120].replace("\n", " ")
            print(f"    ✓ {cid} (p.{chunk_obj['page_number']}) -> \"{snippet}...\"")
        else:
            print(f"    ✗ ERROR: Chunk ID {cid} not found in 301 chunks!")

    print(f"  Top-1 Retrieved: {top1_retrieved['chunk_id']} (score: {top1_retrieved['similarity_score']}) [{top1_retrieved['scheme_id']}]")
    print(f"    Category: {top1_retrieved['category']} | Is Relevant Policy: {top1_retrieved['is_relevant_policy']}")
    print(f"    Snippet: \"{top1_retrieved['text_excerpt'][:120]}...\"")

print("\n" + "=" * 70)
print("SECTION 3: CORPUS CLASSIFICATION OVERLAP AUDIT")
print("=" * 70)

cat_counts = Counter()
doc_breakdown = {}

for c in chunks_raw:
    cid = c["chunk_id"]
    did = c["document_id"]
    page = c["page_number"]
    text = c["text"]

    is_roster = (did == "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020")
    is_inst_list = (did == "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26" and 7 <= page <= 41)
    is_faq = ("FAQS" in did or "FAQs" in c.get("document_name", "") or text.strip().startswith("Q.") or "Answer:" in text)
    is_elig = any(k in text.lower() for k in ["eligibility criteria", "eligibility conditions", "eligibility:", "eligible:", "who is eligible", "1.0 objective", "2.0 eligibility", "3.0 number of scholarship"])

    if is_roster:
        assigned = "Beneficiary roster"
    elif is_inst_list:
        assigned = "Institution list"
    elif is_faq:
        assigned = "FAQ"
    elif is_elig:
        assigned = "Eligibility"
    else:
        assigned = "Policy"

    cat_counts[assigned] += 1
    doc_breakdown.setdefault(did, Counter())[assigned] += 1

print(f"Total chunks verified: {len(chunks_raw)}")
for cat, cnt in cat_counts.most_common():
    print(f"  {cat:20s}: {cnt:3d} ({cnt/len(chunks_raw)*100:5.2f}%)")

print("\n" + "=" * 70)
print("SECTION 4: CITATION FIELD INTEGRITY AUDIT")
print("=" * 70)

missing_fields_count = 0
for q in queries:
    for r in q["retrieved_results"]:
        for fld in ["chunk_id", "scheme_id", "document_id", "document_name", "page_number", "citation_reference"]:
            if not r.get(fld):
                missing_fields_count += 1
                print(f"Missing {fld} in retrieved result {r.get('chunk_id')}")

print("\n" + "=" * 70)
print("SECTION 5: DETAILED QUERY-BY-QUERY GROUND TRUTH & RETRIEVAL AUDIT")
print("=" * 70)

for q in queries:
    qid = q["query_id"]
    lang = q["language"]
    cat = q["category"]
    rel_ids = set(q["relevant_chunk_ids"])
    retrieved = q["retrieved_results"]
    found_ranks = [(r["rank"], r["chunk_id"], r["scheme_id"], r["similarity_score"]) for r in retrieved if r["chunk_id"] in rel_ids]
    top1 = retrieved[0]
    print(f"{qid} ({lang:7s} | {cat:22s}): Target={q['expected_scheme_id']}")
    print(f"  Ground Truth Chunks: {list(rel_ids)}")
    print(f"  Top-1 Retrieved:     {top1['chunk_id']} [{top1['scheme_id']}] score={top1['similarity_score']:.4f}")
    if found_ranks:
        print(f"  ✓ Relevant Hit in Top 5: Ranks {[f[0] for f in found_ranks]}")
        for fr in found_ranks:
            print(f"    Rank {fr[0]}: {fr[1]} [{fr[2]}] score={fr[3]:.4f}")
    else:
        print(f"  ✗ NO Relevant Hit in Top 5 (First relevant rank: None, RR: 0.0)")
        # Show top 3 chunks retrieved to understand why it failed
        for r in retrieved[:3]:
            print(f"    Rank {r['rank']}: {r['chunk_id']} [{r['scheme_id']}] ({r['category']}) score={r['similarity_score']:.4f}")
            print(f"      Text: \"{r['text_excerpt'][:100]}...\"")

