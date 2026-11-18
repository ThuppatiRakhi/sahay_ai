"""
Experiment script to test candidate pool sizes (10, 20, 30) and reranking weight profiles
across the 21 fixed multilingual benchmark queries.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag.config import DEFAULT_CHUNKS_FILE, DEFAULT_VECTOR_STORE_DIR
from rag.embedding_service import EmbeddingService
from rag.vector_store import VectorStoreManager
from rag.query_rewriter import QueryRewriter

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

with open("reports/rag_step3_baseline_results.json", "r", encoding="utf-8") as f:
    base_data = json.load(f)

queries = base_data["queries"]

# Embedding & Vector store
embedding_service = EmbeddingService(use_mock=False)
vector_store = VectorStoreManager(persist_directory=DEFAULT_VECTOR_STORE_DIR)
query_rewriter = QueryRewriter()

CONFIGS = {
    "Config_A_Conservative": {
        "scheme_boost": 0.03,
        "scheme_penalty": 0.015,
        "roster_penalty": 0.12,
        "inst_penalty": 0.08,
        "type_boost": 0.02,
        "topic_boost": 0.02,
    },
    "Config_B_Balanced": {
        "scheme_boost": 0.05,
        "scheme_penalty": 0.025,
        "roster_penalty": 0.15,
        "inst_penalty": 0.10,
        "type_boost": 0.025,
        "topic_boost": 0.025,
    },
    "Config_C_Strong": {
        "scheme_boost": 0.07,
        "scheme_penalty": 0.035,
        "roster_penalty": 0.18,
        "inst_penalty": 0.12,
        "type_boost": 0.03,
        "topic_boost": 0.03,
    },
}

POOL_SIZES = [10, 20, 30]

print("=" * 70)
print("RERANKING EXPERIMENTAL GRID SEARCH")
print("=" * 70)

def score_candidate(chunk_dict, sim_score, query_text, detected_scheme, config):
    score = sim_score
    cid = chunk_dict["chunk_id"]
    s_id = chunk_dict["metadata"].get("scheme_id", "")
    text = chunk_dict.get("text", "").lower()
    q_lower = query_text.lower()
    cat = chunk_classification.get(cid, "Policy")

    # 1. Scheme Affinity
    if detected_scheme:
        if s_id == detected_scheme:
            score += config["scheme_boost"]
        else:
            score -= config["scheme_penalty"]

    # 2. Chunk Type & Roster Adjustment
    is_inst_query = any(k in q_lower for k in ["institution", "college", "institutes", "notified"])
    is_proc_query = any(k in q_lower for k in ["how to apply", "procedure", "document", "upload", "certificate", "दस्तावेज", "प्रमाण", "పత్రాలు", "దరఖాస్తు"])

    if cat == "Beneficiary roster":
        score -= config["roster_penalty"]
    elif cat == "Institution list":
        if is_inst_query:
            score += config["type_boost"]
        else:
            score -= config["inst_penalty"]
    elif cat == "FAQ":
        if is_proc_query:
            score += config["type_boost"]
    elif cat in ["Eligibility", "Policy"]:
        if not is_proc_query and not is_inst_query:
            score += config["type_boost"]

    # 3. Topic keywords
    if ("income" in q_lower or "आय" in q_lower or "ఆదాయం" in q_lower) and "income" in text:
        score += config["topic_boost"]
    if ("disab" in q_lower or "दिव्यांग" in q_lower or "వికలాంగ" in q_lower or "handicap" in q_lower) and ("disab" in text or "handicap" in text or "specially-abled" in text):
        score += config["topic_boost"]
    if ("orphan" in q_lower or "अनाथ" in q_lower or "అనాథ" in q_lower or "covid" in q_lower) and ("orphan" in text or "covid" in text or "death certificate" in text or "died" in text):
        score += config["topic_boost"]
    if ("girl" in q_lower or "छात्रा" in q_lower or "బాలిక" in q_lower or "women" in q_lower) and ("girl" in text or "female" in text or "women" in text):
        score += config["topic_boost"]

    return round(max(0.0, min(1.0, score)), 4)

experiment_results = []

for pool_size in POOL_SIZES:
    for cfg_name, cfg in CONFIGS.items():
        top1_matches = 0
        rel_hits_at_5 = 0
        rr_list = []
        contam_list = []
        lang_hits = {"English": 0, "Hindi": 0, "Telugu": 0}
        lang_top1 = {"English": 0, "Hindi": 0, "Telugu": 0}

        for q in queries:
            qid = q["query_id"]
            qtext = q["question"]
            lang = q["language"]
            expected_scheme = q["expected_scheme_id"]
            rel_chunk_ids = set(q["relevant_chunk_ids"])

            # Rewrite query
            rewritten_obj = query_rewriter.rewrite(qtext)
            detected_scheme = rewritten_obj.detected_scheme_id

            # Dense retrieve candidate pool
            query_vec = embedding_service.embed_query(rewritten_obj.rewritten_query)
            query_resp = vector_store.query(query_embedding=query_vec, n_results=pool_size)

            c_ids = query_resp.get("ids", [[]])[0]
            c_docs = query_resp.get("documents", [[]])[0]
            c_metas = query_resp.get("metadatas", [[]])[0]
            c_dists = query_resp.get("distances", [[]])[0]

            candidates = []
            for cid, doc, meta, dist in zip(c_ids, c_docs, c_metas, c_dists):
                sim = round(max(0.0, min(1.0, 1.0 - float(dist))), 4)
                chunk_dict = {"chunk_id": cid, "text": doc, "metadata": meta}
                r_score = score_candidate(chunk_dict, sim, qtext, detected_scheme, cfg)
                candidates.append((r_score, sim, cid, meta.get("scheme_id", "")))

            # Sort by reranked score descending, tie-break by sim
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            top5 = candidates[:5]

            # Eval top 1 scheme
            top1_s = top5[0][3] if top5 else ""
            t1_match = (top1_s == expected_scheme)
            if t1_match:
                top1_matches += 1
                lang_top1[lang] += 1

            # Eval rel hit@5
            hit5 = False
            first_rank = None
            roster_count = 0
            for rk, cand in enumerate(top5, start=1):
                cid = cand[2]
                if cid in rel_chunk_ids and first_rank is None:
                    first_rank = rk
                    hit5 = True
                cat = chunk_classification.get(cid, "Policy")
                if cat in ["Beneficiary roster", "Institution list"]:
                    roster_count += 1

            if hit5:
                rel_hits_at_5 += 1
                lang_hits[lang] += 1

            rr = 1.0 / first_rank if first_rank else 0.0
            rr_list.append(rr)
            contam_list.append(roster_count / 5.0)

        tot = len(queries)
        overall_top1 = top1_matches / tot
        overall_hit5 = rel_hits_at_5 / tot
        overall_mrr = sum(rr_list) / tot
        overall_contam = sum(contam_list) / tot

        res = {
            "pool_size": pool_size,
            "config": cfg_name,
            "overall_top1": round(overall_top1, 4),
            "overall_hit5": round(overall_hit5, 4),
            "overall_mrr": round(overall_mrr, 4),
            "overall_contam": round(overall_contam, 4),
            "en_top1": lang_top1["English"],
            "en_hit5": lang_hits["English"],
            "hi_top1": lang_top1["Hindi"],
            "hi_hit5": lang_hits["Hindi"],
            "te_top1": lang_top1["Telugu"],
            "te_hit5": lang_hits["Telugu"],
        }
        experiment_results.append(res)
        print(f"Pool={pool_size:2d} | {cfg_name:22s} -> Top1={overall_top1*100:5.1f}% | RelHit@5={overall_hit5*100:5.1f}% | MRR={overall_mrr:.4f} | Contam={overall_contam*100:4.1f}% | EN Hit={lang_hits['English']}/7, HI Hit={lang_hits['Hindi']}/7, TE Hit={lang_hits['Telugu']}/7")

# Save experimental summary
with open("reports/reranking_experiments_summary.json", "w", encoding="utf-8") as f:
    json.dump(experiment_results, f, indent=2)
print("Experiment complete. Summary saved.")

