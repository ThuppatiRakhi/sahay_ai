import os
import json
import time
import requests
import io
import pypdf
import urllib3
from pathlib import Path

urllib3.disable_warnings()

BASE_DIR = Path("data/official_documents")
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

DOCUMENTS_TO_COLLECT = [
    # 1. PM-USP CSSS
    {
        "document_id": "DOC_EDU_001_CSSS_GUIDELINES_2024",
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "folder": "PM_USP",
        "filename": "SCHEME_EDU_001_PM_USP_CSSS_Guidelines_2024.pdf",
        "document_name": "Guidelines for the Central Sector Scheme of Scholarship for College and University Students (PM-USP CSSS)",
        "issuing_authority": "Department of Higher Education, Ministry of Education, Government of India",
        "document_type": "Official Guidelines",
        "publication_date": "2024-02-07",
        "academic_year": "AY 2022-23 to AY 2026-27 (15th Finance Commission Cycle)",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/CSSS_GUIDLINES_07022024_updated.pdf",
        "is_current": True,
        "notes": "Latest official guideline revision published on NSP as on 07.02.2024. Contains income limit Rs. 4.5L, stream quota 3:1:3, and revised scholarship rates."
    },
    {
        "document_id": "DOC_EDU_001_CSSS_FAQS_2024",
        "scheme_id": "SCHEME_EDU_001_PM_USP_CSSS",
        "folder": "PM_USP",
        "filename": "SCHEME_EDU_001_PM_USP_CSSS_FAQs_2024.pdf",
        "document_name": "Frequently Asked Questions (FAQs) - PM-USP Central Sector Scheme of Scholarship (CSSS)",
        "issuing_authority": "Department of Higher Education, Ministry of Education, Government of India",
        "document_type": "Official FAQs",
        "publication_date": "2024-02-01",
        "academic_year": "AY 2023-24 / AY 2024-25 / AY 2025-26",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/FAQ_DOHE_CSSS.pdf",
        "is_current": True,
        "notes": "Official 43-question FAQ covering fresh vs renewal, percentile calculations, college change, and Aadhaar seeding."
    },

    # 2. AICTE Pragati
    {
        "document_id": "DOC_EDU_002_PRAGATI_DEGREE_GUIDELINES_2020",
        "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "folder": "PRAGATI",
        "filename": "SCHEME_EDU_002_AICTE_PRAGATI_Degree_Guidelines_2020.pdf",
        "document_name": "Guidelines for AICTE - Pragati Scholarship Scheme for Girl Students (Degree)",
        "issuing_authority": "All India Council for Technical Education (AICTE), Ministry of Education",
        "document_type": "Official Guidelines",
        "publication_date": "2020-07-01",
        "academic_year": "AY 2020-21 onwards (operational through AY 2026-27)",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_G.pdf",
        "is_current": True,
        "notes": "Operational framework for Degree track: 5,000 scholarships, Rs. 50,000/yr, CAP admission mandatory, max 2 girls per family."
    },
    {
        "document_id": "DOC_EDU_002_PRAGATI_DIPLOMA_GUIDELINES_2020",
        "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "folder": "PRAGATI",
        "filename": "SCHEME_EDU_002_AICTE_PRAGATI_Diploma_Guidelines_2020.pdf",
        "document_name": "Guidelines for AICTE - Pragati Scholarship Scheme for Girl Students (Diploma)",
        "issuing_authority": "All India Council for Technical Education (AICTE), Ministry of Education",
        "document_type": "Official Guidelines",
        "publication_date": "2020-07-01",
        "academic_year": "AY 2020-21 onwards (operational through AY 2026-27)",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2011_G.pdf",
        "is_current": True,
        "notes": "Operational framework for Diploma track: 5,000 scholarships, Rs. 50,000/yr, CAP admission mandatory."
    },
    {
        "document_id": "DOC_EDU_002_PRAGATI_FAQS_2020",
        "scheme_id": "SCHEME_EDU_002_AICTE_PRAGATI",
        "folder": "PRAGATI",
        "filename": "SCHEME_EDU_002_AICTE_PRAGATI_FAQs_2020.pdf",
        "document_name": "Frequently Asked Questions (FAQs) - AICTE Pragati Scholarship Scheme",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Official FAQs",
        "publication_date": "2020-08-01",
        "academic_year": "AY 2020-21 onwards",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_F.pdf",
        "is_current": True,
        "notes": "Official AICTE FAQs clarifying two-girl child condition proforma Annexure-III, current financial year income calculation, and reservation norms."
    },

    # 3. AICTE Saksham
    {
        "document_id": "DOC_EDU_003_SAKSHAM_DEGREE_GUIDELINES_2020",
        "scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "folder": "SAKSHAM",
        "filename": "SCHEME_EDU_003_AICTE_SAKSHAM_Degree_Guidelines_2020.pdf",
        "document_name": "Guidelines for AICTE - Saksham Scholarship Scheme for Specially-Abled Students (Degree)",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Official Guidelines",
        "publication_date": "2020-07-01",
        "academic_year": "AY 2020-21 onwards (operational through AY 2026-27)",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2012_G.pdf",
        "is_current": True,
        "notes": "Degree track guidelines: benchmark disability >= 40%, CAP admission, all eligible admitted students covered."
    },
    {
        "document_id": "DOC_EDU_003_SAKSHAM_DIPLOMA_GUIDELINES_2020",
        "scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "folder": "SAKSHAM",
        "filename": "SCHEME_EDU_003_AICTE_SAKSHAM_Diploma_Guidelines_2020.pdf",
        "document_name": "Guidelines for AICTE - Saksham Scholarship Scheme for Specially-Abled Students (Diploma)",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Official Guidelines",
        "publication_date": "2020-07-01",
        "academic_year": "AY 2020-21 onwards",
        "source_url": "https://www.aicte.gov.in/sites/default/files/stdc/Saksham%20Diploma%202020-21.pdf",
        "is_current": True,
        "notes": "Diploma track guidelines for technical diploma students with disability >= 40%."
    },
    {
        "document_id": "DOC_EDU_003_SAKSHAM_FAQS_2020",
        "scheme_id": "SCHEME_EDU_003_AICTE_SAKSHAM",
        "folder": "SAKSHAM",
        "filename": "SCHEME_EDU_003_AICTE_SAKSHAM_FAQs_2020.pdf",
        "document_name": "Frequently Asked Questions (FAQs) - AICTE Saksham Scholarship Scheme",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Official FAQs",
        "publication_date": "2020-08-01",
        "academic_year": "AY 2020-21 onwards",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2012_F.pdf",
        "is_current": True,
        "notes": "Official AICTE Saksham FAQs clarifying medical authority disability certificates, UDID card, and renewal rules."
    },

    # 4. AICTE Swanath
    {
        "document_id": "DOC_EDU_004_SWANATH_REVISED_GUIDELINES_2025",
        "scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "folder": "SWANATH",
        "filename": "SCHEME_EDU_004_AICTE_SWANATH_Revised_Guidelines_2025.pdf",
        "document_name": "AICTE - Swanath Scholarship Scheme for Students (May 2025 Revised Guidelines)",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Official Guidelines (Revised)",
        "publication_date": "2025-05-01",
        "academic_year": "AY 2025-26 and AY 2026-27",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_3038_G.pdf",
        "is_current": True,
        "notes": "Revised guidelines adding Category 4 (critical life-threatening illness / accident disability > 80%) and opening scheme to any year of study."
    },
    {
        "document_id": "DOC_EDU_004_SWANATH_DEGREE_DIPLOMA_GUIDELINES_2021",
        "scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "folder": "SWANATH",
        "filename": "SCHEME_EDU_004_AICTE_SWANATH_Degree_Diploma_Guidelines_2021.pdf",
        "document_name": "Guidelines for AICTE - Swanath Scholarship Scheme for Students (Degree / Diploma - Initial Framework)",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Historical Guidelines",
        "publication_date": "2021-08-01",
        "academic_year": "AY 2021-22 to AY 2024-25",
        "source_url": "https://www.aicte.gov.in/sites/default/files/stdc/AICTE-SWANATH-%20SCHEME-DEGREE-DIPLOMA.pdf",
        "is_current": False,
        "notes": "Historical base framework document defining orphan, COVID-19, and Shaheed categories and original 2,000 slot allocation."
    },
    {
        "document_id": "DOC_EDU_004_SWANATH_FAQS_2022",
        "scheme_id": "SCHEME_EDU_004_AICTE_SWANATH",
        "folder": "SWANATH",
        "filename": "SCHEME_EDU_004_AICTE_SWANATH_FAQs_2022.pdf",
        "document_name": "Frequently Asked Questions (FAQs) - AICTE Swanath Scholarship Scheme",
        "issuing_authority": "All India Council for Technical Education (AICTE)",
        "document_type": "Official FAQs",
        "publication_date": "2022-09-01",
        "academic_year": "AY 2022-23 to AY 2026-27",
        "source_url": "https://www.aicte.gov.in/sites/default/files/stdc/FAQs-Swanath%20Scheme.pdf",
        "is_current": True,
        "notes": "Official AICTE Swanath FAQs covering category certificates, state death registry proofs, and DEFENCE/CAPF proofs."
    },

    # 5. Top Class SC
    {
        "document_id": "DOC_EDU_005_TOP_CLASS_SC_GUIDELINES_2025_26",
        "scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC",
        "folder": "TOP_CLASS_SC",
        "filename": "SCHEME_EDU_005_TOP_CLASS_SC_Guidelines_2025_26.pdf",
        "document_name": "Scheme Guidelines of Top Class Scholarship for SC Students (Applicable from 2025-26)",
        "issuing_authority": "Department of Social Justice and Empowerment, Ministry of Social Justice and Empowerment",
        "document_type": "Official Guidelines",
        "publication_date": "2025-06-01",
        "academic_year": "AY 2025-26 and AY 2026-27",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/Top_Class_Education_Scheme_2018.pdf",
        "is_current": True,
        "notes": "Active guideline on NSP containing 44 pages of updated rules, 60% Class 12 requirement, Rs. 8L income limit, tuition caps, and the complete schedule of empanelled premier institutions."
    },
    {
        "document_id": "DOC_EDU_005_TOP_CLASS_SC_FAQS_2022",
        "scheme_id": "SCHEME_EDU_005_TOP_CLASS_SC",
        "folder": "TOP_CLASS_SC",
        "filename": "SCHEME_EDU_005_TOP_CLASS_SC_FAQs_2022.pdf",
        "document_name": "Frequently Asked Questions (FAQs) - Top Class Education Scheme for SC Students",
        "issuing_authority": "Department of Social Justice and Empowerment, Ministry of Social Justice and Empowerment",
        "document_type": "Official FAQs",
        "publication_date": "2022-06-01",
        "academic_year": "AY 2022-23 to AY 2026-27",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/Top_Class_Education_Scheme_2018_FAQ.pdf",
        "is_current": True,
        "notes": "Official FAQs answering institution selection, fee reimbursement vs allowance disbursement, and 30% girls quota."
    }
]

def download_and_validate():
    metadata_list = []
    
    for item in DOCUMENTS_TO_COLLECT:
        folder_path = BASE_DIR / item["folder"]
        folder_path.mkdir(parents=True, exist_ok=True)
        file_path = folder_path / item["filename"]
        
        print(f"\nProcessing [{item['scheme_id']}] -> {item['filename']}")
        print(f"  Source URL: {item['source_url']}")
        
        download_success = False
        page_count = None
        has_readable_text = False
        requires_ocr = False
        file_size_bytes = 0
        error_msg = None
        
        try:
            r = requests.get(item["source_url"], headers=HEADERS, timeout=30, verify=False)
            if r.status_code == 200 and r.content[:4] == b'%PDF':
                file_size_bytes = len(r.content)
                with open(file_path, "wb") as f:
                    f.write(r.content)
                download_success = True
                print(f"  Downloaded: {file_size_bytes} bytes")
                
                # Validation checks using pypdf
                reader = pypdf.PdfReader(io.BytesIO(r.content))
                page_count = len(reader.pages)
                
                # Check text extractability
                extracted_chars_total = 0
                for p in reader.pages:
                    txt = p.extract_text() or ""
                    extracted_chars_total += len(txt.strip())
                
                avg_chars_per_page = extracted_chars_total / max(1, page_count)
                if avg_chars_per_page > 50:
                    has_readable_text = True
                    requires_ocr = False
                else:
                    has_readable_text = False
                    requires_ocr = True
                    
                print(f"  Pages: {page_count} | Total extracted chars: {extracted_chars_total} | Native text: {has_readable_text} | Requires OCR: {requires_ocr}")
            else:
                error_msg = f"HTTP status {r.status_code}, content header: {r.content[:10]}"
                print(f"  DOWNLOAD FAILED: {error_msg}")
        except Exception as e:
            error_msg = str(e)
            print(f"  DOWNLOAD EXCEPTION: {e}")
            
        doc_record = {
            "document_id": item["document_id"],
            "scheme_id": item["scheme_id"],
            "document_name": item["document_name"],
            "issuing_authority": item["issuing_authority"],
            "document_type": item["document_type"],
            "publication_date": item["publication_date"],
            "academic_year": item["academic_year"],
            "source_url": item["source_url"],
            "download_date": "2026-11-03",
            "file_path": str(file_path).replace("\\", "/"),
            "file_size_bytes": file_size_bytes,
            "page_count": page_count,
            "opens_correctly": download_success,
            "contains_readable_text": has_readable_text,
            "requires_ocr": requires_ocr,
            "source_domain_official": any(dom in item["source_url"] for dom in ["scholarships.gov.in", "aicte.gov.in", "education.gov.in", "socialjustice.gov.in"]),
            "is_current_guideline": item["is_current"],
            "verification_status": "collected_and_validated" if download_success else "download_failed",
            "notes": item["notes"],
            "error": error_msg
        }
        metadata_list.append(doc_record)
        time.sleep(1) # respectful rate limiting
        
    metadata_file = BASE_DIR / "document_metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata_list, f, indent=2, ensure_ascii=False)
        
    print(f"\nAll downloads completed. Metadata saved to {metadata_file}")
    print(f"Total documents processed: {len(metadata_list)}")
    print(f"Successful downloads: {sum(1 for d in metadata_list if d['opens_correctly'])}")

if __name__ == '__main__':
    download_and_validate()
