# SahayAI — Step 2.1: RAG Retrieval Quality Validation Report

**Report generated:** 2026-11-05  
**Workspace:** `c:\Users\Hiii\OneDrive\Desktop\Sahay_ai`  
**Model:** `intfloat/multilingual-e5-small` (384-dim, CPU)  
**Vector store:** ChromaDB PersistentClient (301 chunks, HNSW cosine)  
**Tests passed:** 53/53 (mock mode) + 111 total project tests

---

## 1. Executive Summary

This report validates the retrieval quality of SahayAI's multilingual RAG pipeline across English, Hindi, and Telugu queries, with a focused diagnosis of the **Hindi Saksham retrieval problem** identified during Step 2.

### Key Findings

| Area | Status | Summary |
|---|---|---|
| English retrieval | ✅ **Strong** | 4–5 Saksham chunks in top-5 for all queries; scores 0.85–0.93 |
| Hindi retrieval | ⚠️ **Partial** | 0–4 Saksham chunks in top-5 depending on query; scores 0.80–0.86 |
| Telugu retrieval | ⚠️ **Partial** | 1–2 Saksham chunks in top-5; scores 0.81–0.86 |
| Citation correctness | ✅ **Complete** | All 7 citation fields verified across all 3 languages |
| Profile import compat. | ✅ **Working** | stdlib shadowing workaround functional (cProfile, torch, profile) |
| Retrieval pipeline | ✅ **Correct** | Architecture, filtering, score conversion all correct |

**Root cause of Hindi Saksham partial retrieval: Cross-lingual embedding distance compression**, not a code defect. See §3.

---

## 2. English Retrieval Results

English queries consistently retrieve the correct Saksham chunks with high similarity and correct scheme attribution.

### 2.1 Detailed Results

| Query ID | Query | Saksham in Top-5 | Top-1 Score | Top-1 Scheme | Top-1 Chunk |
|---|---|---|---|---|---|
| EN_01 | "What is the minimum disability percentage for AICTE Saksham scholarship?" | **4/5** | 0.8858 | ✅ SAKSHAM | `SAKSHAM_DEGREE_GUIDELINES_p002_c01` |
| EN_02 | "What is the annual family income limit for Saksham scholarship?" | **4/5** | 0.8683 | ✅ SAKSHAM | `SAKSHAM_FAQS_p005_c01` |
| EN_03 | "Is admission through centralized admission process required for AICTE Saksham?" | **4/5** | 0.8768 | ✅ SAKSHAM | `SAKSHAM_FAQS_p002_c04` |
| EN_04 | "What disability certificate documents are required for Saksham scholarship?" | **5/5** | 0.8560 | ✅ SAKSHAM | `SAKSHAM_DEGREE_GUIDELINES_p002_c01` |
| EN_05 | "AICTE Pragati scholarship eligibility criteria for girl students" | 0/5 | 0.9302 | ✅ PRAGATI | `PRAGATI_DEGREE_GUIDELINES_p002_c01` |
| EN_06 | "AICTE Swanath scholarship for orphan students eligibility" | 0/5 | 0.9042 | ✅ SWANATH | `SWANATH_DEGREE_DIPLOMA_GUIDELINES_p002_c01` |
| EN_07 | "Top Class SC scholarship eligible institutions list" | 0/5 | 0.8896 | ✅ TOP_CLASS_SC | `TOP_CLASS_SC_GUIDELINES_p001_c01` |

**Assessment:** English retrieval is **strong and accurate**. EN_01 through EN_04 correctly return Saksham chunks as top results. EN_05 through EN_07 correctly return their respective target schemes. The E5 model's English-to-English retrieval quality is high.

### 2.2 Top-1 Retrieved Content Samples

**EN_01 (Disability percentage):**
> "GUIDELINES FOR AICTE - SAKSHAM SCHOLARSHIP SCHEME FOR SPECIALLY-ABLED STUDENT (DEGREE) 1.0 OBJECTIVE OF THE SCHEME: Saksham is a MHRD Scheme being implemented by AICTE aimed at providing encouragemen..."  
> *Source: Saksham Degree Guidelines 2020, Page 2*

**EN_02 (Income limit):**
> "torejectionofapplication. (Please don't forget to strike off whichever is not applicable. Failure may lead to the reject..."  
> *Source: Saksham FAQs 2020, Page 5*

**EN_03 (Centralized admission):**
> "same. Students are also advised to request their Institute to verify and forward the application within the time period..."  
> *Source: Saksham FAQs 2020, Page 2*

---

## 3. Hindi Retrieval Results — Saksham Diagnosis

### 3.1 Query-by-Query Results

| Query ID | Hindi Query | Intent | Saksham in Top-5 | Top-1 Score | Top-1 Scheme |
|---|---|---|---|---|---|
| HI_01 | "AICTE सक्षम छात्रवृत्ति के लिए पात्रता शर्तें क्या हैं?" | Eligibility conditions | **2/5** | 0.8637 | ❌ PRAGATI |
| HI_02 | "सक्षम छात्रवृत्ति के लिए न्यूनतम दिव्यांगता प्रतिशत क्या है?" | Disability percentage | **0/5** | 0.8218 | ❌ PM_USP_CSSS |
| HI_03 | "सक्षम छात्रवृत्ति के लिए पारिवारिक आय सीमा कितनी है?" | Family income limit | **1/5** | 0.8274 | ❌ PRAGATI |
| HI_04 | "केंद्रीकृत प्रवेश प्रक्रिया के माध्यम से प्रवेश" | Centralized admission | **4/5** | 0.8233 | ✅ SAKSHAM |
| HI_05 | "दिव्यांगता प्रमाणपत्र सक्षम छात्रवृत्ति आवेदन के लिए आवश्यक है" | Disability certificate | **0/5** | 0.8398 | ❌ TOP_CLASS_SC |
| HI_06 | "विकलांग छात्रों के लिए AICTE छात्रवृत्ति" | AICTE scholarship for disabled | **2/5** | 0.8578 | ✅ SAKSHAM |
| HI_07 | "40 प्रतिशत दिव्यांगता सक्षम" | 40% disability Saksham | **0/5** | 0.8276 | ❌ TOP_CLASS_SC |

### 3.2 Root Cause Analysis

> [!IMPORTANT]
> **The Hindi retrieval weakness is caused by cross-lingual embedding distance compression — NOT a code defect.**

The diagnosis reveals five contributing factors, ordered by impact:

#### Factor 1: Cross-lingual distance compression (PRIMARY)

The `multilingual-e5-small` model maps Hindi queries and English passages into a shared 384-dim space. Cross-lingual pairs inherently have **lower cosine similarity** than same-language pairs:

| Comparison Pair | English Query Score | Hindi Query Score | Score Gap |
|---|---|---|---|
| CMP_01: Disability percentage | 0.8901 | 0.8492 | **−0.041** |
| CMP_02: Family income limit | 0.8703 | 0.8267 | **−0.044** |
| CMP_03: Centralized admission | 0.8465 | 0.8240 | **−0.023** |
| CMP_04: Disability certificate | 0.9032 | 0.8647 | **−0.039** |
| CMP_05: Eligibility overview | 0.8778 | 0.8702 | **−0.008** |

The English top-1 similarity consistently exceeds 0.85, while Hindi queries compress to 0.82–0.86. This compression narrows the distance margin between relevant Saksham chunks and irrelevant chunks from other AICTE schemes, causing scheme cross-contamination in results.

#### Factor 2: Semantic overlap between AICTE schemes

All five schemes share similar vocabulary about eligibility, income limits, and scholarship application processes. The AICTE schemes (Pragati, Saksham, Swanath) in particular share nearly identical eligibility structures:

- Income requirements → shared across Pragati (₹8 lakh), Saksham (₹8 lakh), Swanath (₹8 lakh)
- Application process → all use NSP portal
- General conditions → similar rejection criteria, admission processes

When Hindi query embeddings have compressed similarity margins, the model cannot reliably distinguish Saksham from Pragati/Swanath/CSSS.

#### Factor 3: Transliteration anchor absent

The term "Saksham" appears in English in the indexed chunks but the Hindi query uses "सक्षम" (the Devanagari form). The E5 model handles cross-script mapping, but "AICTE" appearing in Latin script in both queries (HI_01, HI_06) produces better retrieval (2/5 Saksham) than pure Hindi queries without "AICTE" (HI_02, HI_07 → 0/5 Saksham). This suggests the model anchors on shared Latin-script tokens.

#### Factor 4: Chunk content density

Of the 88 Saksham chunks, content analysis shows:
- Only **3 chunks** contain the word "disability"
- Only **7 chunks** contain income-related terms
- **41 chunks** match "CAP" — but most are student name lists from the Diploma beneficiary roster, not policy text
- **12 chunks** contain "certificate"

The Saksham Diploma Guidelines document contributes ~60 chunks that are primarily **beneficiary name lists** (student rosters), not eligibility guidelines. These tabular chunks are semantically uninformative and dilute retrieval quality.

#### Factor 5: Query specificity vs. chunk granularity

Highly specific Hindi queries about "40% disability" (HI_07) fail because the indexed Saksham chunks describe the requirement using different phrasing ("specially-abled", "benchmark disability") rather than explicit percentages. The cross-lingual gap further reduces the model's ability to bridge these vocabulary differences.

### 3.3 Diagnosis Conclusion

| Potential Cause | Verdict |
|---|---|
| ❌ Embedding quality defect | No — model works correctly for English; Hindi scores are within expected cross-lingual range |
| ⚠️ Query wording | Contributing — queries with "AICTE" (Latin) anchor work better |
| ⚠️ Missing information in chunks | Contributing — only 3 of 88 Saksham chunks contain "disability" |
| ⚠️ Retrieval ranking | Contributing — distance compression causes cross-scheme contamination |
| ❌ Metadata filtering | No — `scheme_id` filtering works correctly when applied |

**The retrieval pipeline is architecturally correct.** Hindi retrieval quality will improve in Step 3 when LLM integration adds:
1. **Query rewriting** — expanding Hindi queries to include English scheme names
2. **Re-ranking** — LLM-based re-ranking of retrieved candidates
3. **Scheme-aware filtering** — applying `scheme_id` filter when context makes the target scheme clear

---

## 4. Telugu Retrieval Results

| Query ID | Telugu Query | Intent | Top-1 Score | Top-1 Scheme |
|---|---|---|---|---|
| TE_01 | "AICTE సక్షమ్ స్కాలర్‌షిప్ అర్హత నిబంధనలు" | Saksham eligibility | 0.8577 | ✅ SAKSHAM |
| TE_02 | "వికలాంగ శాతం స్కాలర్‌షిప్ పాత్రత" | Disability percentage | 0.8192 | ❌ PM_USP_CSSS |
| TE_03 | "AICTE స్వానాథ్ స్కాలర్‌షిప్ ఎవరికి వర్తిస్తుంది" | Swanath eligibility | 0.8653 | ✅ SWANATH |

**Assessment:** Telugu retrieval follows the same pattern as Hindi — queries containing the Latin-script "AICTE" anchor retrieve the correct scheme (TE_01, TE_03), while pure Telugu queries about specific conditions (TE_02) drift to other schemes. The cross-lingual compression effect is comparable to Hindi.

---

## 5. English vs Hindi Comparison (Task 2)

### 5.1 Side-by-Side Saksham Retrieval

| Topic | English: Saksham in Top-5 | Hindi: Saksham in Top-5 | English Top-1 | Hindi Top-1 | Gap |
|---|---|---|---|---|---|
| Disability percentage | **4/5** | **2/5** | 0.8901 | 0.8492 | −0.041 |
| Family income limit | **4/5** | **0/5** | 0.8703 | 0.8267 | −0.044 |
| Centralized admission | **4/5** | **0/5** | 0.8465 | 0.8240 | −0.023 |
| Disability certificate | **5/5** | **2/5** | 0.9032 | 0.8647 | −0.039 |
| Eligibility overview | **3/5** | **2/5** | 0.8778 | 0.8702 | −0.008 |

### 5.2 Observations

1. **Consistent score drop**: Hindi queries produce 0.008–0.044 lower similarity scores than equivalent English queries.
2. **Worst case: CMP_02 (income limit)**: Hindi query returns **0 Saksham chunks** in top-5, compared to **4/5** for English. The income-related vocabulary in Hindi ("पारिवारिक आय सीमा") maps poorly to the English chunks that use "family income from all sources should not be more than Rs. 8 lakh".
3. **Best case: CMP_05 (eligibility overview)**: The smallest gap (−0.008), because the Hindi query contains "AICTE" in Latin script, providing a strong cross-script anchor.
4. **Similarity scores are NOT eligibility confidence.** A score of 0.87 means "the query and passage are semantically similar" — it does not indicate 87% probability of eligibility.

---

## 6. Citation Correctness Verification (Task 3)

### 6.1 Fields Verified

Every retrieved result was checked for the presence and validity of these 7 citation fields:

| Field | Validation Rule | Status |
|---|---|---|
| `chunk_id` | Non-empty string | ✅ All passed |
| `scheme_id` | Non-empty string matching `SCHEME_EDU_*` | ✅ All passed |
| `document_id` | Non-empty string matching `DOC_EDU_*` | ✅ All passed |
| `document_name` | Non-empty descriptive string | ✅ All passed |
| `source_url` | Starts with `http` | ✅ All passed |
| `page_number` | Integer ≥ 1 | ✅ All passed |
| `citation_reference` | Non-empty formatted citation string | ✅ All passed |

### 6.2 Citation Verification by Language

| Language | Query | Results Checked | All Fields Valid |
|---|---|---|---|
| English | "AICTE Saksham scholarship eligibility..." | 3 | ✅ |
| Hindi | "AICTE सक्षम छात्रवृत्ति पात्रता" | 3 | ✅ |
| Telugu | "సక్షమ్ స్కాలర్‌షిప్ అర్హత" | 3 | ✅ |

### 6.3 Sample Citation Output

```
[Guidelines for AICTE - Saksham Scholarship Scheme for Specially-Abled Students (Degree), Page 2]
(All India Council for Technical Education (AICTE), AY 2020-21 onwards (operational through AY 2026-27))
Source: https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2012_G.pdf
```

**Assessment:** Citation traceability is **fully intact** across all three languages. Every retrieved chunk preserves the complete provenance chain from original PDF to chunk, including the exact page number, document name, issuing authority, academic year, and source URL.

---

## 7. Profile Import Compatibility (Task 4)

### 7.1 Test Results

| Test | Result | Details |
|---|---|---|
| `import cProfile` | ✅ OK | `cProfile.Profile` functional; ran enable/disable cycle |
| `import profile` (stdlib) | ✅ OK | Resolves to `profile/__init__.py` with fallback shim |
| `profile.run` available | ✅ Yes | Forwarded from stdlib via `__getattr__` |
| `profile.runctx` available | ✅ Yes | Forwarded from stdlib via `__getattr__` |
| `profile.Profile` available | ✅ Yes | Forwarded from stdlib via `__getattr__` |
| `from profile import Database` | ✅ OK | SahayAI-specific import works |
| `from profile import ProfileManager` | ✅ OK | SahayAI-specific import works |
| `import torch` | ✅ OK | PyTorch 2.15.0+cpu loads without conflict |
| Recursive import check | ✅ OK | No recursive import detected |

### 7.2 How the Workaround Works

The `profile/__init__.py` module uses a two-part strategy:

1. **Eager binding**: At import time, it searches `sys.path` (excluding `.` and `""`) for the real stdlib `profile.py`, loads it, and binds `run`, `runctx`, and `Profile` as module-level attributes.
2. **Lazy fallback**: `__getattr__` intercepts any other attribute access and delegates to the loaded stdlib module.

This means:
- `import profile; profile.run(...)` → calls stdlib `profile.run` ✅
- `from profile import Database` → imports SahayAI's `Database` class ✅
- `import cProfile` → loads stdlib `cProfile` directly (no shadowing) ✅
- `import torch` → torch's internal use of `cProfile` works correctly ✅

### 7.3 Known Limitation

`sys.modules["profile"]` resolves to the **project package**, not the stdlib module. This means `sys.modules["profile"].__file__` points to `profile/__init__.py`, not the stdlib `profile.py`. This is cosmetically inaccurate but functionally correct, because the `__getattr__` delegation ensures all stdlib `profile` operations work.

> [!NOTE]
> The `profile` package naming is a known design trade-off. Renaming is deferred to a future step as specified in the task requirements.

---

## 8. Saksham Chunk Content Analysis

### 8.1 Keyword Distribution in 88 Saksham Chunks

| Keyword Category | Chunks with Hits | Examples |
|---|---|---|
| Disability terms | **3** of 88 | "disability", "disabled", "benchmark disability" |
| Income terms | **7** of 88 | "income", "8 lakh", "family income" |
| CAP/admission terms | **41** of 88 | "CAP" — but mostly in student name lists |
| Certificate terms | **12** of 88 | "certificate", "UDID", "disability certificate" |

### 8.2 Chunk Quality Issue

Of the 88 Saksham chunks:
- **~60 chunks** are from the Diploma Guidelines document, which is primarily a **beneficiary student roster** (tabular data with student names, application IDs, institution names, and addresses)
- **~28 chunks** are from the Degree Guidelines and FAQs, which contain the actual **policy text** about eligibility, disability requirements, income limits, and application procedures

The student roster chunks are semantically uninformative for retrieval. They match "Saksham" via `scheme_id` metadata but do not contain eligibility information. This explains why:
- HI_04 ("centralized admission process") returns **4/5 Saksham** — it matches the tabular roster chunks
- HI_02 ("disability percentage") returns **0/5 Saksham** — the specific disability information exists in only 3 policy chunks buried among 85 non-relevant Saksham chunks

---

## 9. Problems Found

| # | Problem | Severity | Correction |
|---|---|---|---|
| 1 | Hindi queries without Latin-script anchors ("AICTE") return 0 Saksham chunks | ⚠️ Medium | No code change — expected cross-lingual behavior; will be addressed by LLM query rewriting in Step 3 |
| 2 | ~60 of 88 Saksham chunks are student roster tables, not policy text | ⚠️ Medium | No change made — chunk preprocessing is from Step 1; can be filtered in future re-chunking |
| 3 | Only 3 Saksham chunks contain "disability" keyword | ℹ️ Low | Correct representation of source documents; not a preprocessing error |
| 4 | Cross-lingual score compression (0.02–0.044 gap) | ℹ️ Expected | Inherent to `multilingual-e5-small` model; larger models reduce gap |

**No corrections were made.** All identified issues are behavioral characteristics of the embedding model and chunk content, not code defects. The retrieval pipeline implementation is correct.

---

## 10. Test Results

### 10.1 RAG Test Suite (53 tests)

```
tests/test_rag.py — 53 passed, 0 failed, 0 errors
```

| Test Section | Tests | Status |
|---|---|---|
| EmbeddingService | 10 | ✅ All passed |
| Chunk Loading & Integrity | 9 | ✅ All passed |
| Vector Store | 6 | ✅ All passed |
| Populated Vector Store | 4 | ✅ All passed |
| SchemeRetriever | 11 | ✅ All passed |
| Cross-Lingual Retrieval | 5 | ✅ All passed |
| Scheme Record Integrity | 8 | ✅ All passed |

### 10.2 Full Project Test Suite (111 tests)

```
All 111 tests passed across test_rag.py, test_schemes.py, test_profile.py, 
test_document_collection.py, test_field_extraction.py, test_image_quality.py, test_ocr.py
```

---

## 11. Final Recommendation

### The RAG retrieval pipeline is architecturally sound and ready for Step 3 (LLM integration).

The partial Hindi retrieval for Saksham is a **known characteristic of cross-lingual dense retrieval** with `multilingual-e5-small`, not a defect. The following mitigations should be implemented in Step 3:

| Mitigation | Implementation Step | Expected Impact |
|---|---|---|
| **Query expansion/rewriting** | Step 3 (LLM) | LLM rewrites Hindi query to include English scheme name → +2–3 Saksham chunks in top-5 |
| **LLM re-ranking** | Step 3 (LLM) | Re-rank top-10 results using LLM semantic understanding → correct top-5 |
| **Scheme-aware filtering** | Step 3 (LLM) | When user mentions a specific scheme, apply `scheme_id` filter → 5/5 correct scheme |
| **Hybrid retrieval** | Future | Add BM25 keyword search alongside dense retrieval → catch exact term matches |

> [!TIP]
> The existing `scheme_id` metadata filter already works perfectly for Hindi queries when the target scheme is known. For example, filtering HI_02 by `scheme_id="SCHEME_EDU_003_AICTE_SAKSHAM"` would return 5/5 Saksham chunks. The LLM can extract scheme intent from conversational context and apply this filter automatically.

### Do Not:
- ❌ Do not rebuild the RAG system
- ❌ Do not modify scheme verification status
- ❌ Do not claim Hindi retrieval is successful for all query types (it is partial)
- ❌ Do not implement LLM integration in this step

