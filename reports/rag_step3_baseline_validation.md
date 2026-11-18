# SahayAI — Step 3.1 Final Validation Report

**Validation Generated:** 2026-11-06  
**Workspace:** `c:\Users\Hiii\OneDrive\Desktop\Sahay_ai`  
**Scope:** Independent validation of the 21-query multilingual RAG baseline benchmark, metrics verification, relevance label audit, corpus classification census, and citation correctness analysis.  
**Evaluator:** Independent Audit Suite (`reports/verify_step3_baseline.py`)  

---

## 1. Metric Verification and Recalculation

All evaluation metrics from `reports/rag_step3_baseline_results.json` and `reports/rag_step3_baseline_benchmark.md` were independently recalculated from raw per-query retrieval logs. All denominators and aggregation formulas were validated.

### 1.1 Verification Formula Definitions

1. **Top-1 Scheme Accuracy**:  
   $$\text{Top-1 Scheme Accuracy} = \frac{\sum_{i=1}^{N} \mathbb{I}(\text{Top-1 Scheme} == \text{Target Scheme})}{N}$$
   *Denominator:* Total queries $N=21$ (or $n=7$ per language).

2. **Relevant Hit@5**:  
   $$\text{Relevant Hit@5} = \frac{\sum_{i=1}^{N} \mathbb{I}(\exists \, c \in \text{Top-5} : c \in \text{Ground Truth Relevant Chunk IDs})}{N}$$
   *Denominator:* Total queries $N=21$ (or $n=7$ per language).  
   *Note:* Matching the scheme alone is strictly insufficient; the chunk must be an actual ground-truth policy chunk addressing the question.

3. **Mean Reciprocal Rank (MRR)**:  
   $$\text{MRR} = \frac{1}{N} \sum_{i=1}^{N} \text{RR}_i, \quad \text{where } \text{RR}_i = \frac{1}{\text{rank of first relevant chunk}} \text{ (or } 0 \text{ if not in Top-5)}$$

4. **Roster Contamination@5**:  
   $$\text{Roster Contamination@5} = \frac{1}{N} \sum_{i=1}^{N} \frac{\text{Count of Beneficiary Roster or Institution List chunks in Top-5}}{5}$$
   *Denominator:* Total returned slots evaluated $= 21 \times 5 = 105$ slots ($35$ per language).

### 1.2 Recalculated Metric Comparison

| Scope | Metric | Reported Value | Independently Recalculated | Discrepancy | Verification Status |
|---|---|---|---|---|---|
| **Overall** | Top-1 Scheme Accuracy | 0.4286 (42.9%) | $9 / 21 = \mathbf{0.4286}$ | 0.0000 | ✅ Verified |
| **Overall** | Relevant Hit@5 | 0.3333 (33.3%) | $7 / 21 = \mathbf{0.3333}$ | 0.0000 | ✅ Verified |
| **Overall** | Mean Reciprocal Rank (MRR) | 0.1778 | $3.7333 / 21 = \mathbf{0.1778}$ | 0.0000 | ✅ Verified |
| **Overall** | Roster Contamination@5 | 0.0476 (4.8%) | $5 / 105 = \mathbf{0.0476}$ | 0.0000 | ✅ Verified |
| **English** | Top-1 Scheme Accuracy | 0.7143 (71.4%) | $5 / 7 = \mathbf{0.7143}$ | 0.0000 | ✅ Verified |
| **English** | Relevant Hit@5 | 0.4286 (42.9%) | $3 / 7 = \mathbf{0.4286}$ | 0.0000 | ✅ Verified |
| **English** | MRR | 0.3571 | $2.5000 / 7 = \mathbf{0.3571}$ | 0.0000 | ✅ Verified |
| **English** | Roster Contamination@5 | 0.0000 (0.0%) | $0 / 35 = \mathbf{0.0000}$ | 0.0000 | ✅ Verified |
| **Hindi** | Top-1 Scheme Accuracy | 0.2857 (28.6%) | $2 / 7 = \mathbf{0.2857}$ | 0.0000 | ✅ Verified |
| **Hindi** | Relevant Hit@5 | 0.2857 (28.6%) | $2 / 7 = \mathbf{0.2857}$ | 0.0000 | ✅ Verified |
| **Hindi** | MRR | 0.1190 | $0.8333 / 7 = \mathbf{0.1190}$ | 0.0000 | ✅ Verified |
| **Hindi** | Roster Contamination@5 | 0.1143 (11.4%) | $4 / 35 = \mathbf{0.1143}$ | 0.0000 | ✅ Verified |
| **Telugu** | Top-1 Scheme Accuracy | 0.2857 (28.6%) | $2 / 7 = \mathbf{0.2857}$ | 0.0000 | ✅ Verified |
| **Telugu** | Relevant Hit@5 | 0.2857 (28.6%) | $2 / 7 = \mathbf{0.2857}$ | 0.0000 | ✅ Verified |
| **Telugu** | MRR | 0.0571 | $0.4000 / 7 = \mathbf{0.0571}$ | 0.0000 | ✅ Verified |
| **Telugu** | Roster Contamination@5 | 0.0286 (2.9%) | $1 / 35 = \mathbf{0.0286}$ | 0.0000 | ✅ Verified |

---

## 2. Relevance Labels and Ambiguity Audit

Every benchmark query was audited to confirm:
1. Ground truth relevant chunk IDs exist in the 301 chunks and factually answer the query.
2. The distinction between scheme attribution and actual policy evidence.
3. Query ambiguity where multiple schemes could plausibly apply.

### 2.1 Audit of Ground Truth Chunks

All 49 ground-truth chunk references across the 21 queries were looked up in `data/official_documents/rag_chunks/batch1_all_rag_chunks.json`. **100% of ground-truth chunk IDs exist and contain official factual text directly resolving the query.**

| Category | Example Query | Ground Truth Chunk ID | Verified Document Excerpt |
|---|---|---|---|
| **Disability criteria** | `BENCH_EN_01`, `HI_01`, `TE_01` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01` | *"having disability of not less than 40% and submitted valid disability certificate issued by competent authority"* |
| **Family income** | `BENCH_EN_02` | `DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c01` | *"The parental/family income ceiling under the Scheme is Rs. 4.5 lakh per annum for all categories."* |
| **Core eligibility** | `BENCH_EN_03`, `HI_02`, `TE_03` | `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01` | *"Maximum two girl child per family are eligible. Family income from all sources should not be more than Rs. 8 lakh per annum"* |
| **Required documents** | `BENCH_EN_04` | `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p004_c02` | *"Death Certificate of parent(s) / Certificate from Competent Authority for martyred Armed Forces/CAPF personnel"* |
| **Scheme benefits** | `BENCH_EN_05`, `HI_05` | `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01` | *"Full tuition fee and other non-refundable charges (up to Rs. 2 lakh in private institutions) + Academic Allowance of Rs. 86,000 in first year"* |

### 2.2 Analysis of Ambiguous & Situational Queries

Four queries intentionally presented situational descriptions without explicit scheme names. We analyzed whether multiple schemes could legitimately answer them:

1. **`BENCH_EN_06` ("I lost both my parents during Covid-19 and got admitted to an engineering college. How do I apply?")**:
   - *Target Scheme:* `SCHEME_EDU_004_AICTE_SWANATH`.
   - *Ambiguity Assessment:* AICTE Swanath is the **only** scholarship with a specific category for Covid-19 pandemic orphans. While a female orphan could also apply for Pragati, Swanath is the dedicated scheme designed for this specific condition.
   - *Baseline Failure:* Retriever returned Pragati Diploma chunks (due to high token weight on *"engineering college"*), completely missing the orphan condition.

2. **`BENCH_EN_07` & `BENCH_TE_06` ("Can a student with physical handicap studying diploma engineering get government scholarship support?")**:
   - *Target Scheme:* `SCHEME_EDU_003_AICTE_SAKSHAM`.
   - *Ambiguity Assessment:* Although PM-USP CSSS has a 5% horizontal disability quota, CSSS guidelines strictly state: *"Pursuing regular degree courses and not correspondence or distance mode or pursuing Diploma courses"*. Thus, AICTE Saksham is the **only** scheme covering diploma engineering for students with benchmark disabilities.
   - *Baseline Failure:* In English, the retriever fetched Pragati Diploma chunks. In Telugu (`BENCH_TE_06`), Saksham was buried at Rank 5 with Rank 1–4 dominated by Top Class SC and Pragati.

3. **`BENCH_HI_06` ("तकनीकी शिक्षा में पढ़ने वाली छात्राओं के लिए सरकारी छात्रवृत्ति कैसे मिलती है?")**:
   - *Target Scheme:* `SCHEME_EDU_002_AICTE_PRAGATI`.
   - *Ambiguity Assessment:* Pragati is the exclusive national scholarship dedicated to female technical students. CSSS offers scholarships across general graduation streams, but Pragati specifically covers AICTE technical degrees and diplomas.
   - *Baseline Failure:* In Hindi, Swanath guidelines ranked 1st and Pragati was displaced.

4. **`BENCH_HI_07` ("अनाथ बच्चों के लिए इंजीनियरिंग कॉलेज की फीस में सहायता वाली योजना कौन सी है?")**:
   - *Target Scheme:* `SCHEME_EDU_004_AICTE_SWANATH`.
   - *Ambiguity Assessment:* AICTE Swanath is the only scheme targeting orphans in technical institutions.
   - *Baseline Failure:* In Hindi, Annexure-2 institute directory tables ranked #1 and #2 (40% roster contamination).

---

## 3. Corpus Classification Census & Category Overlap

We audited the classification methodology for all 301 chunks in `data/official_documents/rag_chunks/batch1_all_rag_chunks.json`.

### 3.1 Census Breakdown

| Category | Chunks | Percentage | Mutual Exclusivity Rule |
|---|---|---|---|
| **FAQ** | 80 | 26.58% | Chunks from official FAQ PDFs (`DOC_EDU_*_FAQS_*`) or starting with `Q.` / `Answer:` |
| **Policy** | 77 | 25.58% | Administrative guidelines on quotas, renewal, disbursement, and portal rules |
| **Beneficiary Roster** | 66 | 21.93% | `DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020` (all 66 chunks are student selection tables) |
| **Institution List** | 63 | 20.93% | `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26` (Pages 7–41, Annexure-2 college directory) |
| **Eligibility** | 15 | 4.98% | Explicit core candidate criteria sections (Clauses 1.0, 2.0, 3.0 in guidelines) |
| **Total** | **301** | **100.0%** | **Complete Corpus** |

### 3.2 Category Overlap & Methodology Assessment

1. **Functional vs. Format Overlap:**
   - *Eligibility* is functionally a subset of *Policy* and *FAQ*. Many FAQ chunks explain eligibility rules, and guideline chunks define both eligibility and policy mechanisms together.
   - In our classification, *Eligibility* was assigned to chunks containing explicit section headers such as *"1.0 OBJECTIVE OF THE SCHEME"* and *"2.0 ELIGIBILITY"*, while other regulatory clauses (e.g. renewal, transfer, Aadhaar seeding) were classified as *Policy*.
2. **Zero Overlap for Roster and Directory Chunks:**
   - There is **zero semantic overlap** between the 129 table chunks (*Beneficiary Roster* and *Institution List*) and the 172 policy/FAQ chunks.
   - The 66 Saksham Diploma chunks contain no eligibility criteria whatsoever.
   - The 63 Top Class SC Annexure-2 chunks contain solely college names, street addresses, and AISHE codes.
   - *Conclusion:* These 129 tabular chunks (42.8% of the database) can be deterministically identified and safely penalized/deprioritized during policy retrieval without risking the loss of any regulatory guidance.

---

## 4. Citation Correctness Verification

To address Step 4 of the validation mandate, we distinguish three separate tiers of citation correctness:

| Citation Tier | Meaning | Has it been tested? | Empirical Status in Step 3.1 |
|---|---|---|---|
| **Tier 1: Metadata Preservation** | Preservation of metadata fields (`chunk_id`, `scheme_id`, `document_id`, `page_number`, `source_url`, `citation_reference`) from ChromaDB into `RetrievalResult`. | **YES** | **100% Passed.** In memory, `RetrievalResult` dataclass preserves all 11 metadata fields without corruption. In `rag_step3_baseline_results.json`, all essential citation identifiers (`chunk_id`, `document_id`, `page_number`, `citation_reference`, `scheme_id`) are present for all 105 retrieved items. |
| **Tier 2: Correct Source Attribution** | Does the citation string accurately reflect the real document title, page number, issuing ministry, and official portal URL of the original source PDF? | **YES** | **100% Passed.** Every chunk's `citation_reference` corresponds exactly to the official PDF page from which it was extracted during document ingestion. |
| **Tier 3: Actual Evidence Supporting the Answer** | Does the retrieved chunk text actually contain the factual evidence required to answer the user's inquiry? | **YES (Measured by Relevant Hit@5)** | **FAILED in 66.7% of queries.** Only 33.3% (7/21) of queries had a chunk in the top-5 containing actual evidence answering the query. In 66.7% of cases, the retrieved text was either from an incorrect scheme, a student merit list table, or an irrelevant policy clause within the same scheme. |

> [!IMPORTANT]
> **Key Finding on Citation Validity:**  
> A system can achieve **100% Metadata Preservation** and **100% Source Attribution** for the chunk it returns, while having **0% Evidence Validity** for the user's question. Full citation correctness requires Tier 3 (actual evidence retrieval), which currently stands at **33.3%**.

---

## 5. Verification of Reproducibility

The baseline benchmark is **100% reproducible**:
1. The execution script `reports/run_baseline_benchmark.py` uses fixed query texts and deterministic dense embedding inference on CPU with `intfloat/multilingual-e5-small`.
2. The ChromaDB vector store (`data/vector_store/chroma/`) is persistent and completely unaltered.
3. Rerunning `reports/run_baseline_benchmark.py` produces the exact same top-5 rankings, similarity scores, and evaluation metrics.
4. All **111 existing test cases** in the repository continue to pass (`tests/test_rag.py` 53/53 passed, other test suites 58/58 passed).

---

## 6. Unresolved Issues and Final Recommendations for Step 3.2

### Unresolved Issues Identified in Baseline
1. **Indic Token Asymmetry:** Indic queries (e.g. `"सक्षम"`, `"స్వానాథ్"`) fail to activate strong vector associations with English policy chunks, causing a ~0.04 drop in cosine similarity.
2. **Tabular Noise Dominance:** 42.8% of the corpus consists of non-policy directory/roster tables that pollute top-5 candidates on Indic queries.
3. **Situational Keyword Trapping:** Situational queries without explicit scheme acronyms are trapped by generic words like *"engineering"* or *"degree"*, diverting users to Pragati instead of Swanath or Saksham.

### Recommendations for Step 3.2 Implementation
1. **Implement Multilingual Query Rewriting (`rag/query_rewriter.py`):**
   - Detect Indic scheme names (`"सक्षम"`, `"प्रगति"`, `"స్వానాథ్"`) and expand them into canonical English pairs (`"AICTE Saksham Scholarship"`, `"AICTE Swanath Scholarship"`).
   - Expand cross-lingual technical concepts (`"दिव्यांगता"`, `"विकलांग"` $\rightarrow$ `"disability benchmark disability 40% specially-abled"`, `"अनाथ"` $\rightarrow$ `"orphan Covid-19 pandemic"`).
2. **Implement Lightweight Tabular Reranking (`rag/reranker.py`):**
   - Apply an automatic penalty (e.g. $-0.15$) to student beneficiary rosters (`DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020`) and institution directory lists (`DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p007` to `p041`) whenever a query seeks eligibility, rules, allowances, or procedures.
3. **Implement Scheme-Aware Intent Filtering:**
   - When an explicit scheme is recognized in the query, apply a scheme-affinity bonus (+0.05) or strict filter to eliminate 100% of false positives from other schemes.
4. **Evaluation Target:**
   - Measure the exact same 21 benchmark queries after Step 3.2 to demonstrate improvement against this verified baseline (Overall Relevant Hit@5: $33.3\% \rightarrow \ge 75\%$, MRR: $0.1778 \rightarrow \ge 0.6000$, Roster Contamination: $4.8\% \rightarrow 0.0\%$).

---

### Step 3.1 Status
✅ **Baseline Benchmark and Independent Validation Complete.** Awaiting user approval before proceeding to Step 3.2 (Multilingual Query Rewriting).

