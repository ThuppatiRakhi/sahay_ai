# SahayAI — Step 3.3: Lightweight Reranking and Scheme-Aware Retrieval

**Date:** November 7, 2026  
**Status:** Implemented, benchmark reproduced, all 153 tests passing  
**Corpus:** 301 chunks across 5 scholarship schemes  
**Embedding Model:** `intfloat/multilingual-e5-small` (CPU)  
**Vector Store:** ChromaDB (`data/vector_store/chroma/`)

---

## 1. Pre-Implementation Verification and Diagnostic Findings

Before implementing reranking, verification checks were conducted on the codebase and benchmark data.

### 1.1 Telugu Non-Policy List Contamination Audit

The Step 3.2 benchmark showed a discrepancy in its contamination reporting.

- Query `BENCH_TE_06` retrieved an institution-directory chunk from `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26`.
- This chunk belongs to the institution directory rather than the main scholarship policy.
- The Step 3.2 benchmark output recorded contamination for this query.
- Institution directories and beneficiary rosters are different categories and should not automatically be treated as equivalent.

The reranker therefore applies different penalties to beneficiary rosters and institution lists.

### 1.2 English Query Retrieval Regression Analysis

In Step 3.2, query rewriting improved Hindi and Telugu retrieval but did not improve every English query.

Examples:

1. **`BENCH_EN_02` — CSSS family income**
   - Query: "What is the maximum family income limit for Central Sector Scheme of Scholarship?"
   - Step 3.2 ranked a different scheme first.
   - Step 3.3 detected the CSSS scheme intent and used scheme affinity scoring to improve the ranking.
   - Step 3.3 achieved a relevant evidence hit.

2. **`BENCH_EN_04` — Swanath required documents**
   - Query: "Which documents must be uploaded for AICTE Swanath Scholarship Scheme?"
   - Similar document-related wording in another scheme's FAQ affected dense retrieval.
   - Step 3.3 used scheme affinity to improve Swanath retrieval.
   - A relevant chunk appeared at rank 5.

3. **`BENCH_EN_07` — Disability scholarship support**
   - Query: "Can a student with disability pursuing diploma engineering get scholarship support?"
   - This is a generic query without an explicit scheme name.
   - Step 3.3 did not retrieve the expected scheme as the top result.
   - This remains an unresolved retrieval failure.

### 1.3 Ground-Truth Label Consistency

The benchmark uses fixed query labels:

- `expected_scheme_id`
- `relevant_chunk_ids`

The Step 3.1, Step 3.2 and Step 3.3 comparisons use the same 21 benchmark queries and their expected labels.

No benchmark label changes are intended as part of reranking.

### 1.4 Independent Retrieval Paths

The retriever supports separate controls for:

- Query rewriting.
- Reranking.

The benchmark can therefore evaluate rewriting and reranking independently.

When reranking is disabled, retrieval uses the original similarity ordering. When enabled, the candidate pool is adjusted using the lightweight reranking score.

---

## 2. Lightweight Reranker Architecture

Implemented in:

- `rag/reranker.py`
- `rag/retriever.py`

### 2.1 Chunk Categorization

The reranker classifies corpus chunks into five operational categories:

1. **Beneficiary roster:** Past awardee or selected-student lists, including the Saksham Diploma list.
2. **Institution list:** Institution-directory chunks from the Top Class Education scheme documents.
3. **FAQ:** Frequently asked questions and answers.
4. **Eligibility:** Chunks containing explicit eligibility criteria.
5. **Policy:** General administrative guidelines and operational conditions.

These categories are used for ranking adjustments. They do not establish whether a scheme is currently active or whether a particular applicant is eligible.

### 2.2 Scoring Formula

For each candidate chunk \(c\), the reranker calculates:

\[
s_{\text{rerank}} =
\operatorname{clamp}
\left(
s_{\text{sim}} +
\Delta_{\text{scheme}} +
\Delta_{\text{type}} +
\Delta_{\text{topic}},
0.0, 1.0
\right)
\]

Where:

- \(s_{\text{sim}}\): Original cosine similarity.
- \(\Delta_{\text{scheme}}\): Scheme affinity adjustment.
- \(\Delta_{\text{type}}\): Chunk category adjustment.
- \(\Delta_{\text{topic}}\): Topic alignment adjustment.

### 2.3 Scoring Parameters

**Scheme affinity**

- Matching detected scheme: `+0.05`
- Different scheme: `-0.025`
- No unambiguous scheme detected: `0.0`

**Chunk category adjustment**

- Beneficiary roster: `-0.15`
- Institution list: `-0.10` for non-institution queries
- Institution list: `+0.025` for institution-related queries
- FAQ: `+0.025` for procedural or document-related queries
- Policy or eligibility: `+0.025` for relevant eligibility or policy queries

**Topic alignment**

- Matching domain concepts: `+0.025`

Examples of topic concepts include:

- Income.
- Disability.
- Orphan status.
- Girl students.

### 2.4 Strict Separation of Scores

The retriever maintains two distinct scores:

- `similarity_score`: Original cosine similarity from the embedding model.
- `rerank_score`: Adjusted score used to order the candidate pool.

The reranking score is an internal ranking signal. It is **not** an eligibility confidence score, probability of approval, or factual confidence score.

### 2.5 Candidate Pool

The reproduced Step 3.3 production benchmark uses:

- Candidate pool size: `30`
- Final retrieved results: `5`
- Query rewriting: Enabled
- Reranking: Enabled
- Automatic scheme filtering: Disabled

The candidate-pool size of 30 is the current tested configuration, not a proven global optimum.

---

## 3. Candidate Pool Sizing Experiments

Candidate pool sizes of 10, 20 and 30 were explored using:

`reports/experiment_reranking.py`

The experiment script contains a separate scoring implementation from the production reranker in `rag/reranker.py`.

Consequently, its grid-search results should be treated as exploratory rather than as independently validated production results.

The production benchmark was reproduced using `candidate_pool_size=30`.

Further controlled comparisons are required before concluding that 30 is the optimal candidate-pool size.

**Current production benchmark configuration:** Candidate pool size = 30.

---

## 4. Benchmark Evaluation Results

Evaluation was performed against 21 fixed multilingual queries:

- 7 English queries.
- 7 Hindi queries.
- 7 Telugu queries.

### 4.1 Overall Progression Across RAG Steps

| Metric | Step 3.1 Baseline | Step 3.2 Query Rewriting | Step 3.3 Rewriting + Reranking |
|:---|:---:|:---:|:---:|
| Scheme Top-1 Accuracy | 42.9% (9/21) | 71.4% (15/21) | **85.7% (18/21)** |
| Relevant Hit@5 | 33.3% (7/21) | 52.4% (11/21) | **66.7% (14/21)** |
| Mean Reciprocal Rank (MRR) | 0.1778 | 0.3373 | **0.4635** |
| Non-Policy List Contamination@5 | 4.8% | 0.9% | **1.9%** |

**Interpretation:**

- Scheme Top-1 measures whether the first retrieved result belongs to the expected scheme.
- Relevant Hit@5 measures whether at least one expected relevant chunk appears among the first five results.
- MRR measures the ranking position of the first relevant result.
- Non-Policy List Contamination@5 measures the share of retrieved positions occupied by beneficiary-roster or institution-list chunks.

The contamination metric includes both beneficiary rosters and institution lists. It must not be interpreted as beneficiary-roster contamination alone.

### 4.2 Detailed Breakdown by Language

| Language | Metric | Step 3.1 Baseline | Step 3.2 Rewriting | Step 3.3 Rewriting + Reranking |
|:---|:---|:---:|:---:|:---:|
| English | Scheme Top-1 | 71.4% | 57.1% | **85.7%** |
| English | Relevant Hit@5 | 42.9% | 42.9% | **85.7%** |
| English | MRR | 0.3571 | 0.3333 | **0.5333** |
| Hindi | Scheme Top-1 | 28.6% | 85.7% | **85.7%** |
| Hindi | Relevant Hit@5 | 28.6% | 71.4% | **71.4%** |
| Hindi | MRR | 0.1190 | 0.4643 | **0.5000** |
| Telugu | Scheme Top-1 | 28.6% | 71.4% | **85.7%** |
| Telugu | Relevant Hit@5 | 28.6% | 42.9% | **42.9%** |
| Telugu | MRR | 0.0571 | 0.2143 | **0.3571** |

### 4.3 Key Observations

1. **Overall improvement:** Step 3.3 achieved 85.7% Scheme Top-1, 66.7% Relevant Hit@5 and an MRR of 0.4635.

2. **English retrieval improved:** Scheme Top-1 increased from 57.1% in Step 3.2 to 85.7% in Step 3.3.

3. **Hindi retrieval remains relatively strong:** Relevant Hit@5 reached 71.4%.

4. **Telugu evidence retrieval remains a weakness:** Relevant Hit@5 is only 42.9%, even though Scheme Top-1 reached 85.7%. Correctly identifying a scheme does not guarantee retrieval of supporting evidence.

5. **Residual list contamination remains:** Step 3.3 reports 1.9% non-policy list contamination. The affected queries identified in the benchmark output are `BENCH_HI_05` and `BENCH_TE_07`. Their retrieved chunks should be inspected before deciding whether they represent genuinely irrelevant results.

### 4.4 Benchmark Limitations

- The benchmark contains only 21 queries.
- Seven queries per language are insufficient to establish generalized multilingual retrieval performance.
- Scheme Top-1 is not a measure of factual answer accuracy.
- Relevant Hit@5 and MRR depend on the manually assigned ground-truth chunk IDs.
- The reranker uses heuristic scoring adjustments and requires broader evaluation.
- The current results do not prove that generated answers are factually correct or fully supported by citations.
- Current benchmark performance should not be represented as production-grade retrieval quality.

---

## 5. Citation Traceability and Metadata Preservation

Each `RetrievalResult` is expected to preserve source provenance.

The relevant metadata fields include:

- `chunk_id`: Unique identifier for the retrieved chunk.
- `scheme_id`: Canonical scheme identifier.
- `document_id`: Source document identifier.
- `document_name`: Official document title.
- `authority`: Issuing ministry or statutory body.
- `page_number`: Source PDF page number.
- `source_url`: Source document URL.
- `citation_reference`: Structured citation reference.
- `similarity_score`: Original cosine similarity.
- `rerank_score`: Adjusted ranking score.
- `disclaimer`: Applicable disclaimer statement.

Preserving citation metadata is necessary for traceability, but metadata alone does not prove that a retrieved passage supports a generated answer.

The answer-generation stage must validate the relationship between the answer and its supporting chunks.

---

## 6. Test Suite Status

The test suite was expanded during RAG development.

Latest reproduced test result:

```text
153 passed, 1 warning in 17.12s
```

The warning originates from ChromaDB's telemetry dependency using the deprecated `asyncio.iscoroutinefunction` function.

It is a dependency deprecation warning, not a test failure.

### 6.1 Test Result

- Total tests: 153
- Passed: 153
- Failed: 0
- Warnings: 1

### 6.2 Test Coverage Areas

The test suite includes tests for:

- Document collection.
- Field extraction.
- Image quality.
- OCR.
- User profile.
- Query rewriting.
- RAG retrieval.
- Scheme handling.

All 153 tests passed in the latest reported test run.

---

## 7. Conclusion and Next Development Stage

Step 3.3 introduces lightweight reranking on top of multilingual query rewriting and vector retrieval.

The reproduced benchmark shows improvement over the original baseline:

- Scheme Top-1: 42.9% to 85.7%.
- Relevant Hit@5: 33.3% to 66.7%.
- MRR: 0.1778 to 0.4635.

These results demonstrate progress on the current fixed benchmark, but they do not establish production readiness.

### Next Stage: RAG Answer Generation

The next development stage should implement:

1. Answer generation using retrieved official document chunks.
2. Source citations with document titles and page references.
3. Evidence-grounded responses that do not invent eligibility conditions or scholarship amounts.
4. An insufficient-evidence fallback when retrieved chunks do not support an answer.
5. Clear distinction between official policy information and general explanations.
6. Multilingual response generation for English, Hindi and Telugu.
7. Tests verifying that answers are supported by their cited evidence.

**Core design principle:** The LLM may explain retrieved policy evidence, but it must not invent scheme rules or independently decide a citizen's eligibility. Eligibility decisions should remain in the deterministic eligibility engine.