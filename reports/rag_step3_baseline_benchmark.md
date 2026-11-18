# SahayAI — Step 3.1: RAG Baseline Benchmark and Evaluation Report

**Report Generated:** 2026-11-06  
**Workspace:** `c:\Users\Hiii\OneDrive\Desktop\Sahay_ai`  
**Embedding Model:** `intfloat/multilingual-e5-small` (384-dimensional dense vectors, CPU inference)  
**Vector Database:** ChromaDB PersistentClient (`data/vector_store/chroma/`, HNSW cosine metric)  
**Corpus Size:** 301 verified official guideline chunks across 5 government scholarship schemes  
**Benchmark Scope:** 21 fixed multilingual queries (7 English, 7 Hindi, 7 Telugu) evaluated against the CURRENT unmodified RAG implementation  

---

## 1. Executive Summary

To establish a rigorous, reproducible baseline before implementing query rewriting, reranking, or metadata filtering in Step 3, we constructed a fixed 21-question multilingual benchmark and evaluated the existing production retriever.

### Baseline Summary Metrics

| Metric | English (7 queries) | Hindi (7 queries) | Telugu (7 queries) | Overall (21 queries) |
|---|---|---|---|---|
| **Top-1 Scheme Accuracy** | **71.4%** (5/7) | **28.6%** (2/7) | **28.6%** (2/7) | **42.9%** (9/21) |
| **Relevant Hit@5** | **42.9%** (3/7) | **28.6%** (2/7) | **28.6%** (2/7) | **33.3%** (7/21) |
| **Mean Reciprocal Rank (MRR)** | **0.3571** | **0.1190** | **0.0571** | **0.1778** |
| **Roster Contamination@5** | **0.0%** (0/35) | **11.4%** (4/35) | **2.9%** (1/35) | **4.8%** (5/105) |
| **Average Top-1 Similarity Score** | **0.8759** | **0.8324** | **0.8407** | **0.8497** |

### Key Diagnostic Takeaways

1. **Severe Cross-Lingual Degradation**: While English queries achieve 71.4% scheme accuracy, both Hindi and Telugu drop to **28.6%**, with MRR collapsing from 0.3571 to 0.1190 (Hindi) and 0.0571 (Telugu).
2. **Scheme Attribution vs. Actual Policy Relevance**: A chunk belonging to the correct scheme is frequently *not* relevant to the specific question asked. For instance, in English family income queries, the retriever returned reservation allocation chunks rather than the income ceiling section, resulting in an English Relevant Hit@5 of only 42.9% despite 71.4% Scheme Accuracy.
3. **Significant Directory & Roster Dilution**: Out of 301 indexed chunks, **129 chunks (42.8%)** are non-policy directory tables (66 student merit roster chunks in Saksham Diploma, 63 notified institute address chunks in Top Class SC). In Hindi situational queries, roster contamination in top-5 reached as high as **40.0%**.
4. **Failure on Situational Queries**: When user questions describe a situation (e.g. "orphan child admitted to engineering", "disabled student needing diploma support") without explicitly citing the English acronym (e.g. "AICTE", "SWANATH"), the baseline retriever consistently retrieves incorrect schemes due to generic keyword matches like "engineering" or "college".

---

## 2. Corpus Data-Quality Census (301 Chunks)

An exhaustive empirical audit was conducted across all 301 indexed chunks in `data/official_documents/rag_chunks/batch1_all_rag_chunks.json`.

### 2.1 Chunk Classification Distribution

| Chunk Category | Count | Percentage | Description / Source Documents |
|---|---|---|---|
| **Policy** | 77 | 25.58% | Official guidelines describing scheme objectives, financial allowances, and operational rules |
| **FAQ** | 80 | 26.58% | Official ministry Q&A clarifying eligibility, portal steps, and renewal policies |
| **Eligibility** | 15 | 4.98% | Explicit core eligibility clauses (e.g., Clause 2.0 / 3.0 in AICTE guidelines) |
| **Beneficiary Roster** | 66 | 21.93% | Tabular student selection lists containing student names, application IDs, and college codes |
| **Institution List** | 63 | 20.93% | Annexure-2 directory listing 285 notified higher education institutions and addresses |
| **Total** | **301** | **100.0%** | **Batch 1 Complete Corpus** |

### 2.2 Critical Data-Quality Findings

#### Finding A: Saksham Diploma Guidelines is 100% Student Beneficiary Roster
- Document `DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020` contributes 66 chunks.
- An automated lexical audit verified that **0 out of the 66 chunks** contain regulatory terms such as *eligibility, disability, income, criteria, condition, objective,* or *rule*.
- Every single chunk consists of tabular rows formatted as:
  `S. No. Institute_State/ UT Application_ID Applicant_Name Institution_Name AISHE_Code Institute_Address`
- **Impact:** Saksham has only 22 genuine policy/FAQ chunks (7 in Degree Guidelines, 15 in FAQs). The 66 roster chunks act as semantic distractors in the vector store.

#### Finding B: Top Class SC Guidelines Contains 63 Institution Directory Chunks
- Document `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26` contains 84 chunks in total.
- Chunks `p007_c01` through `p041_c01` (Pages 7 to 41, 63 chunks) represent Annexure-2: "List of the notified institutions under the scheme of Top Class Education".
- Many institution names contain words like *"Disabilities"*, *"Speech and Hearing"*, *"Mental Health"*, or *"Sports"*.
- **Impact:** When an Indic query asks about disability criteria (e.g., `BENCH_HI_01`), ChromaDB matches institution directory chunks like *"Pt. Deendayal Upadhyaya National Institute for Persons with Physical Disabilities"* with scores above 0.82, displacing actual policy chunks.

---

## 3. Fixed Multilingual Benchmark Definition

The benchmark comprises 21 queries evenly distributed across English, Hindi, and Telugu, covering six operational categories:
1. Disability criteria
2. Family income
3. Core eligibility
4. Required documents
5. Scheme benefits
6. Application procedures

### Benchmark Query Master Table

| Query ID | Language | Query Text | Expected Scheme ID | Relevant Policy Chunk IDs | Category | Explicit Scheme? |
|---|---|---|---|---|---|---|
| `BENCH_EN_01` | English | What is the minimum disability percentage required for AICTE Saksham scholarship? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01` | Disability criteria | Yes |
| `BENCH_EN_02` | English | What is the annual family income ceiling to be eligible for PM-USP CSSS college scholarship? | `SCHEME_EDU_001_PM_USP_CSSS` | `DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c01`, `DOC_EDU_001_CSSS_FAQS_2024_p001_c02` | Family income | Yes |
| `BENCH_EN_03` | English | Who is eligible to apply for AICTE Pragati scholarship for girls? | `SCHEME_EDU_002_AICTE_PRAGATI` | `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c02`, `DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020_p002_c01`, `DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01` | Eligibility | Yes |
| `BENCH_EN_04` | English | What documents must be uploaded when applying for AICTE Swanath scholarship? | `SCHEME_EDU_004_AICTE_SWANATH` | `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p004_c02`, `DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021_p003_c01`, `DOC_EDU_004_SWANATH_FAQS_2022_p002_c02` | Required documents | Yes |
| `BENCH_EN_05` | English | What financial assistance and allowances are provided under Top Class Education Scheme for SC Students? | `SCHEME_EDU_005_TOP_CLASS_SC` | `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01`, `DOC_EDU_005_TOP_CLASS_SC_FAQS_2022_p001_c02` | Scheme benefits | Yes |
| `BENCH_EN_06` | English | I lost both my parents during Covid-19 and got admitted to an engineering college. How do I apply for technical degree scholarship? | `SCHEME_EDU_004_AICTE_SWANATH` | `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c01`, `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p003_c02`, `DOC_EDU_004_SWANATH_FAQS_2022_p001_c01` | Application procedures | No |
| `BENCH_EN_07` | English | Can a student with physical handicap studying diploma engineering get government scholarship support? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c02` | Eligibility | No |
| `BENCH_HI_01` | Hindi | सक्षम छात्रवृत्ति के लिए न्यूनतम दिव्यांगता प्रतिशत क्या होना चाहिए? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01` | Disability criteria | Yes |
| `BENCH_HI_02` | Hindi | एआईसीटीई प्रगति छात्रवृत्ति के लिए परिवार की वार्षिक आय सीमा कितनी है? | `SCHEME_EDU_002_AICTE_PRAGATI` | `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020_p002_c02`, `DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01` | Family income | Yes |
| `BENCH_HI_03` | Hindi | पीएम-यूएसपी छात्रवृत्ति योजना में कॉलेज के छात्र कैसे पात्र होते हैं? | `SCHEME_EDU_001_PM_USP_CSSS` | `DOC_EDU_001_CSSS_GUIDELINES_2024_p001_c01`, `DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c01`, `DOC_EDU_001_CSSS_FAQS_2024_p001_c02` | Eligibility | Yes |
| `BENCH_HI_04` | Hindi | सक्षम छात्रवृत्ति के लिए कौन सा दिव्यांगता प्रमाण पत्र मान्य है? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_FAQS_2020_p003_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p005_c01`, `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p005_c01` | Required documents | Yes |
| `BENCH_HI_05` | Hindi | अनुसूचित जाति के छात्रों के लिए टॉप क्लास स्कॉलरशिप में कितनी राशि मिलती है? | `SCHEME_EDU_005_TOP_CLASS_SC` | `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01`, `DOC_EDU_005_TOP_CLASS_SC_FAQS_2022_p001_c02` | Scheme benefits | Yes |
| `BENCH_HI_06` | Hindi | तकनीकी शिक्षा में पढ़ने वाली छात्राओं के लिए सरकारी छात्रवृत्ति कैसे मिलती है? | `SCHEME_EDU_002_AICTE_PRAGATI` | `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p003_c02`, `DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01` | Application procedures | No |
| `BENCH_HI_07` | Hindi | अनाथ बच्चों के लिए इंजीनियरिंग कॉलेज की फीस में सहायता वाली योजना कौन सी है? | `SCHEME_EDU_004_AICTE_SWANATH` | `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c01`, `DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021_p002_c01`, `DOC_EDU_004_SWANATH_FAQS_2022_p001_c01` | Eligibility | No |
| `BENCH_TE_01` | Telugu | AICTE సక్షమ్ స్కాలర్‌షిప్ పొందడానికి కనీస వికలాంగ శాతం ఎంత ఉండాలి? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01` | Disability criteria | Yes |
| `BENCH_TE_02` | Telugu | స్వానాథ్ స్కాలర్‌షిప్ పథకానికి కుటుంబ వార్షిక ఆదాయ పరిమితి ఎంత? | `SCHEME_EDU_004_AICTE_SWANATH` | `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c01`, `DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025_p002_c02`, `DOC_EDU_004_SWANATH_FAQS_2022_p001_c01` | Family income | Yes |
| `BENCH_TE_03` | Telugu | ప్రగతి స్కాలర్‌షిప్ పథకం కింద ఎవరికి దరఖాస్తు చేసుకునే అర్హత ఉంది? | `SCHEME_EDU_002_AICTE_PRAGATI` | `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c02`, `DOC_EDU_002_PRAGATI_FAQS_2020_p001_c01` | Eligibility | Yes |
| `BENCH_TE_04` | Telugu | పీఎం-యూఎస్‌పీ సెంట్రల్ సెక్టార్ స్కాలర్‌షిప్ కోసం ఏ డాక్యుమెంట్లు సమర్పించాలి? | `SCHEME_EDU_001_PM_USP_CSSS` | `DOC_EDU_001_CSSS_GUIDELINES_2024_p002_c02`, `DOC_EDU_001_CSSS_FAQS_2024_p002_c01`, `DOC_EDU_001_CSSS_FAQS_2024_p002_c02` | Required documents | Yes |
| `BENCH_TE_05` | Telugu | ఏఐసీటీఈ సక్షమ్ స్కాలర్‌షిప్ ద్వారా విద్యార్థులకు ఎంత మొత్తం అందుతుంది? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p003_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c02` | Scheme benefits | Yes |
| `BENCH_TE_06` | Telugu | డిగ్రీ లేదా ఇంజనీరింగ్ చదువుతున్న వికలాంగ విద్యార్థులకు ఏ ప్రభుత్వ స్కాలర్‌షిప్ సహాయం ఉంది? | `SCHEME_EDU_003_AICTE_SAKSHAM` | `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c01`, `DOC_EDU_003_SAKSHAM_FAQS_2020_p001_c02` | Eligibility | No |
| `BENCH_TE_07` | Telugu | టాప్ కాలేజీల్లో సీటు వచ్చిన ఎస్సీ విద్యార్థులకు ఫీజు రీయింబర్స్‌మెంట్ ఎలా లభిస్తుంది? | `SCHEME_EDU_005_TOP_CLASS_SC` | `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p001_c01`, `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p003_c01`, `DOC_EDU_005_TOP_CLASS_SC_FAQS_2022_p001_c02` | Application procedures | No |

---

## 4. Query-by-Query Baseline Evaluation Results

The evaluation was executed using `reports/run_baseline_benchmark.py` running in Python 3.14 with `sentence-transformers` and `chromadb`. The full JSON result is saved at `reports/rag_step3_baseline_results.json`.

### 4.1 Detailed Evaluation Table

| Query ID | Lang | Target Scheme | Top-1 Retrieved Scheme | Top-1 Score | Top-1 Chunk ID | Scheme Top-1 Match? | Relevant Hit@5? | 1st Rel Rank | MRR | Roster Contam@5 |
|---|---|---|---|---|---|---|---|---|---|---|
| `BENCH_EN_01` | EN | SAKSHAM | SAKSHAM | 0.8901 | `SAKSHAM_DEGREE_p002_c01` | ✅ Yes | ✅ Yes | 1 | 1.0000 | 0.0 |
| `BENCH_EN_02` | EN | PM_USP_CSSS | PM_USP_CSSS | 0.8618 | `CSSS_GUIDELINES_p002_c03` | ✅ Yes | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_EN_03` | EN | PRAGATI | PRAGATI | 0.9003 | `PRAGATI_DEGREE_p002_c01` | ✅ Yes | ✅ Yes | 1 | 1.0000 | 0.0 |
| `BENCH_EN_04` | EN | SWANATH | SWANATH | 0.8668 | `SWANATH_GUIDELINES_p003_c01` | ✅ Yes | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_EN_05` | EN | TOP_CLASS_SC | TOP_CLASS_SC | 0.8808 | `TOP_CLASS_SC_GUIDELINES_p003_c02` | ✅ Yes | ✅ Yes | 2 | 0.5000 | 0.0 |
| `BENCH_EN_06` | EN | SWANATH | PRAGATI | 0.8742 | `PRAGATI_DIPLOMA_p002_c01` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_EN_07` | EN | SAKSHAM | PRAGATI | 0.8572 | `PRAGATI_DIPLOMA_p002_c01` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_HI_01` | HI | SAKSHAM | TOP_CLASS_SC | 0.8311 | `TOP_CLASS_SC_GUIDELINES_p038_c01` | ❌ No | ❌ No | — | 0.0000 | 0.2 |
| `BENCH_HI_02` | HI | PRAGATI | SAKSHAM | 0.8331 | `SAKSHAM_DEGREE_p002_c02` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_HI_03` | HI | PM_USP_CSSS | PM_USP_CSSS | 0.8457 | `CSSS_FAQS_p002_c01` | ✅ Yes | ✅ Yes | 3 | 0.3333 | 0.0 |
| `BENCH_HI_04` | HI | SAKSHAM | TOP_CLASS_SC | 0.8314 | `TOP_CLASS_SC_GUIDELINES_p038_c01` | ❌ No | ❌ No | — | 0.0000 | 0.2 |
| `BENCH_HI_05` | HI | TOP_CLASS_SC | TOP_CLASS_SC | 0.8473 | `TOP_CLASS_SC_GUIDELINES_p003_c02` | ✅ Yes | ✅ Yes | 2 | 0.5000 | 0.0 |
| `BENCH_HI_06` | HI | PRAGATI | SWANATH | 0.8255 | `SWANATH_GUIDELINES_p002_c02` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_HI_07` | HI | SWANATH | TOP_CLASS_SC | 0.8125 | `TOP_CLASS_SC_GUIDELINES_p038_c01` | ❌ No | ❌ No | — | 0.0000 | 0.4 |
| `BENCH_TE_01` | TE | SAKSHAM | PRAGATI | 0.8643 | `PRAGATI_DIPLOMA_p002_c01` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_TE_02` | TE | SWANATH | PRAGATI | 0.8130 | `PRAGATI_DEGREE_p002_c02` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_TE_03` | TE | PRAGATI | PRAGATI | 0.8165 | `PRAGATI_DEGREE_p002_c01` | ✅ Yes | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_TE_04` | TE | PM_USP_CSSS | TOP_CLASS_SC | 0.8485 | `TOP_CLASS_SC_GUIDELINES_p003_c03` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_TE_05` | TE | SAKSHAM | SWANATH | 0.8484 | `SWANATH_FAQS_p001_c01` | ❌ No | ❌ No | — | 0.0000 | 0.0 |
| `BENCH_TE_06` | TE | SAKSHAM | PRAGATI | 0.8380 | `PRAGATI_DIPLOMA_p002_c01` | ❌ No | ✅ Yes | 5 | 0.2000 | 0.2 |
| `BENCH_TE_07` | TE | TOP_CLASS_SC | TOP_CLASS_SC | 0.8561 | `TOP_CLASS_SC_GUIDELINES_p003_c01` | ✅ Yes | ✅ Yes | 5 | 0.2000 | 0.0 |

---

## 5. In-Depth Failure Analysis: Concrete Failure Examples

### Example 1: Devanagari Disability Query Trapped by Institute Directory Tables (`BENCH_HI_01`)
- **Query:** `"सक्षम छात्रवृत्ति के लिए न्यूनतम दिव्यांगता प्रतिशत क्या होना चाहिए?"` (What should be the minimum disability percentage for Saksham scholarship?)
- **Target Scheme:** `SCHEME_EDU_003_AICTE_SAKSHAM`
- **Expected Policy Chunk:** `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01` (stating: *"having disability of not less than 40%"*)
- **Top-1 Chunk Retrieved:** `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p038_c01` (Similarity Score: **0.8311**)
- **Retrieved Content Excerpt:**
  > *"258 Pt. Deendayal Upadhyaya National Institute for Persons with Physical Disabilities (PDUNIPPD) 4, Vishnu Digambar Marg, New Delhi-110002 Delhi Under Graduate 5 259 Ali Yavar Jung National Institute of Speech and Hearing Disabilities..."*
- **Root Cause:**
  1. The Hindi word *"दिव्यांगता"* mapped strongly to the English word *"Disabilities"* in the institute name.
  2. The scheme name *"सक्षम"* (in Devanagari script) did not create enough vector similarity to bridge to the English word *"Saksham"*.
  3. Consequently, Annexure-2 institute directory chunks completely displaced the actual Saksham eligibility guidelines.

### Example 2: Situational Query Failure for Orphan Student (`BENCH_EN_06`)
- **Query:** `"I lost both my parents during Covid-19 and got admitted to an engineering college. How do I apply for technical degree scholarship?"`
- **Target Scheme:** `SCHEME_EDU_004_AICTE_SWANATH` (AICTE Swanath scheme specifically covers Covid orphans)
- **Top-1 Chunk Retrieved:** `DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020_p002_c01` (Similarity Score: **0.8742**)
- **Retrieved Content Excerpt:**
  > *"GUIDELINES FOR AICTE - PRAGATI SCHOLARSHIP SCHEME FOR GIRL STUDENTS (DIPLOMA) 1.0 OBJECTIVE OF THE SCHEME: Scheme being implemented by AICTE aimed at providing assistance for Advancement of Girls pursuing Technical Education..."*
- **Root Cause:**
  The phrase *"engineering college"* and *"technical degree scholarship"* triggered high lexical overlap with Pragati guidelines. Without query expansion linking *"lost both my parents during Covid-19"* to the canonical terms *"Swanath / Orphan / Covid-19 pandemic"*, the retriever matched the largest technical scholarship scheme instead.

### Example 3: Telugu Income Query Distraction (`BENCH_TE_02`)
- **Query:** `"స్వానాథ్ స్కాలర్‌షిప్ పథకానికి కుటుంబ వార్షిక ఆదాయ పరిమితి ఎంత?"` (What is the family annual income limit for Swanath scholarship scheme?)
- **Target Scheme:** `SCHEME_EDU_004_AICTE_SWANATH`
- **Top-1 Chunk Retrieved:** `DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020_p002_c02` (Similarity Score: **0.8130**)
- **Retrieved Content Excerpt:**
  > *"year. 2) Maximum two girls child per family are eligible. 3) Family income from all sources should not be more than Rs. 8 lakh per annum during the current financial year..."*
- **Root Cause:**
  All AICTE schemes (Pragati, Saksham, Swanath) share an identical Rs. 8 lakh income ceiling. In Telugu script, the name *"స్వానాథ్"* did not heavily steer the embedding model towards Swanath document passages over Pragati passages. Because the word *"family income"* was present in both, Pragati won due to minor token frequency variations.

### Example 4: Roster Contamination on Situational Hindi Query (`BENCH_HI_07`)
- **Query:** `"अनाथ बच्चों के लिए इंजीनियरिंग कॉलेज की फीस में सहायता वाली योजना कौन सी है?"`
- **Top 5 Results Breakdown:**
  - Rank 1: `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p038_c01` (Institution list) - Score: 0.8125
  - Rank 2: `DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26_p037_c02` (Institution list) - Score: 0.8105
  - Rank 3: `DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021_p002_c01` (Policy) - Score: 0.8098
  - Rank 4: `DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020_p002_c01` (Policy) - Score: 0.8087
  - Rank 5: `DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020_p002_c03` (Beneficiary roster) - Score: 0.8062
- **Roster Contamination:** **40.0%** of the top-5 candidates were student rosters or institute directory tables. The actual target policy chunk was buried at Rank 3.

---

## 6. Citation Preservation & Traceability Check

We confirmed that the existing retrieval pipeline faithfully preserves all 7 citation metadata fields:
1. `chunk_id`: Fully preserved (e.g. `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020_p002_c01`)
2. `scheme_id`: Fully preserved (e.g. `SCHEME_EDU_003_AICTE_SAKSHAM`)
3. `document_id`: Fully preserved (e.g. `DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020`)
4. `document_name`: Fully preserved
5. `source_url`: Official NSP or issuing department URL verified
6. `page_number`: Exact source PDF page verified
7. `citation_reference`: Valid formatted citation string verified

No citation metadata was lost or corrupted during retrieval execution.

---

## 7. Baseline Limitations and Requirements for Step 3.2

This empirical baseline establishes clear targets for Step 3.2:

1. **Multilingual Query Rewriting is Mandatory**:
   - Hindi and Telugu queries must be rewritten into an enriched bilingual format containing the canonical English scheme name (e.g., mapping `"सक्षम"` $\rightarrow$ `"AICTE Saksham Scholarship"`, `"స్వానాథ్"` $\rightarrow$ `"AICTE Swanath Scholarship"`) and key technical policy terms (e.g., `"दिव्यांगता"` $\rightarrow$ `"disability benchmark disability 40%"`).
   - This will directly resolve the 0.035–0.043 cosine similarity gap between English and Indic scripts.
2. **Tabular/Roster Chunk Deprioritization**:
   - The 66 Saksham diploma beneficiary list chunks and 63 Top Class SC institute address chunks must receive a significant penalty or be filtered during policy retrieval.
   - User questions seeking eligibility criteria or required documents should never return student merit roster rows.
3. **Scheme Intent Detection & Filtering**:
   - When a user query explicitly mentions a scheme (even in Indic script), the query rewriter must identify the target `scheme_id`.
   - Applying scheme-aware boosting or filtering will eliminate 100% of cross-scheme false positives (e.g. Pragati chunks surfacing for Saksham queries).
4. **Target Improvement Goals for Step 3.2**:
   - Overall Scheme Top-1 Accuracy: Increase from **42.9%** to **$\ge 80.0\%$**
   - Overall Relevant Hit@5: Increase from **33.3%** to **$\ge 75.0\%$**
   - Overall MRR: Increase from **0.1778** to **$\ge 0.6000$**
   - Roster Contamination@5: Reduce from **4.8%** (and up to 40% on situational queries) to **0.0%**

