# SahayAI 🏛️

**SahayAI** is an AI-powered public welfare assistance platform designed to help citizens identify, verify eligibility for, and access government welfare schemes. By combining computer vision, OCR document intelligence, and a citizen profile management layer, SahayAI streamlines welfare discovery and document verification while strictly safeguarding citizen privacy.

---

## 📁 Repository Structure

```text
SahayAI/
│
├── data/
│   ├── schemes/
│   │   ├── schemes.json
│   │   └── verified_schemes.json
│   │
│   └── sample_documents/
│       ├── .gitkeep
│       ├── sample_synthetic_aadhaar.png
│       ├── sample_synthetic_pan.png
│       └── sample_synthetic_income_cert.pdf
│
├── scheme_collection/
│   ├── __init__.py
│   ├── collect_schemes.py
│   ├── scheme_validator.py
│   └── verify_schemes.py
│
├── document_ai/
│   ├── __init__.py
│   ├── document_processor.py
│   ├── extract_fields.py
│   ├── image_quality.py
│   └── ocr.py
│
├── profile/
│   ├── __init__.py
│   ├── database.py
│   └── profile_manager.py
│
├── shared_contracts/
│   ├── __init__.py
│   └── schemas.json
│
├── tests/
│   ├── __init__.py
│   ├── test_field_extraction.py
│   ├── test_image_quality.py
│   ├── test_ocr.py
│   ├── test_profile.py
│   └── test_schemes.py
│
├── requirements.txt
├── README.md
├── .env.example
└── .gitignore
```

---

## 🧩 Corrected Module Architectures & Responsibilities

### 1. `document_ai/`
- **`ocr.py` (`OCREngine`)**:
  - **Tesseract OCR (Windows & Linux)**: Searches standard installation paths (`C:\Program Files\Tesseract-OCR\tesseract.exe`, system `PATH`, and `TESSERACT_CMD`).
  - **RapidOCR (ONNX)**: Built-in local ONNX engine running directly without requiring external binaries.
  - **Scanned PDF Pipeline**: When a PDF has no embedded digital text, `pypdfium2` automatically renders pages to high-resolution bitmaps and processes them through the active OCR engine.
  - **Digital PDF Extraction**: Native digital text extraction via `pypdf`.
  - **Backend Status Verification**: `get_backend_status()` inspects actual engine readiness before reporting status.
- **`image_quality.py` (`ImageQualityAssessor`)**:
  - Uses OpenCV and Pillow to evaluate blur (Laplacian variance), mean brightness, specular flash glare (>= 252 luminance), and minimum resolution.
  - Safely intercepts corrupt or unreadable files (`UnidentifiedImageError`, decoding failures) and returns structured rejection recommendations without crashing.
- **`extract_fields.py` (`DocumentFieldExtractor` & `PIIVault`)**:
  - **Default PII Masking**: Aadhaar numbers (`XXXX-XXXX-1234`) and PAN identifiers (`XXXXX1234X`) are masked by default across all values, display fields, and evidence snippets.
  - **Authorized Encryption**: `PIIVault` provides authenticated symmetric encryption (Fernet / AES-128-CBC with HMAC-SHA256) when full identifiers are explicitly authorized.
  - **Multi-Format Extraction**: Recognizes ISO (`YYYY-MM-DD`), slash (`DD/MM/YYYY`), dot (`DD.MM.YYYY`), dash (`DD-MM-YYYY`), and currency denominations (including Lakh/Lakhs).
  - **Heuristic Confidence**: All confidence metrics are explicitly labeled as `heuristic_confidence`.
  - **User Confirmation Queue**: Automatically surfaces missing or uncertain fields in `needs_user_confirmation`.
- **`document_processor.py` (`DocumentProcessor`)**:
  - Coordinates quality gating, OCR execution, and field extraction with resilient error containment.

### 2. `profile/`
- **`database.py` (`Database`)**:
  - SQLite database layer with enforced `PRAGMA foreign_keys = ON;` on every connection.
  - `document_metadata` maintains `FOREIGN KEY (profile_id) REFERENCES profiles(profile_id) ON DELETE CASCADE`.
- **`profile_manager.py` (`ProfileManager`)**:
  - Full CRUD operations on citizen profiles.
  - Citizen confirmation tracking (`confirm_profile`).
  - **PII Storage Sanitization**: Automatically redacts unmasked sensitive identifiers in `save_document_metadata` to prevent plaintext PII storage in SQLite.
  - Cascade deletion: Deleting a profile automatically purges all linked document records.
  - Clean export (`get_profile_for_recommendation`) for external eligibility engines.

### 3. `scheme_collection/`
- **`verify_schemes.py` (`SchemeVerifier`)**:
  - **5-Stage Verification Architecture**:
    - **Stage A (Structural Validation)**: Required fields, eligibility constraints (`min_age <= max_age`), benefits, and documents.
    - **Stage B (Source Authenticity)**: Verifies that publishing authority is a recognized government ministry/department under trusted domains.
    - **Stage C (Operational Status)**: Validates that the scheme is `ACTIVE` (rejects `DISCONTINUED`, `INACTIVE`, or unconfirmed schemes).
    - **Stage D (Application URL)**: Validates reachability and redirect chains with the explicit caveat that HTTP 200 alone does **not** prove authenticity.
    - **Stage E (Human Review)**: Mandatory human reviewer sign-off (`reviewer_id`, `decision="APPROVED"`, `review_notes`) required before marking `is_verified = True`.
- **`collect_schemes.py` (`SchemeCollector`)**:
  - Generic and source-specific ingestion interfaces (`LocalFileSchemeSource`, `OfficialAPISchemeSource`).
  - Strict compliance with portal rate limits (HTTP 429) and access restrictions (HTTP 401/403) without attempting bypasses.
  - Zero hallucination / fabrication of missing scheme attributes.
  - Raw unverified records in `data/schemes/schemes.json` remain strictly isolated from `data/schemes/verified_schemes.json`.

---

## 🔒 Privacy & Security Protections

1. **Zero Plaintext PII in Logs**: Logs use `mask_sensitive_patterns` (`XXXX-XXXX-7777` and `XXXXX1234X`).
2. **Default Masking in Extraction**: `fields["aadhaar_number"]["value"]` contains masked display format by default.
3. **Encrypted Storage**: Authorized storage of raw identifiers requires explicit encryption through `PIIVault`.
4. **SQLite Sanitization**: Unmasked identifiers passed to `save_document_metadata` are sanitized before writing to disk.
5. **Foreign Key Integrity**: Deleting a profile automatically cascades to delete all linked document records.

---

## 🛠️ Tesseract OCR Setup on Windows

SahayAI natively supports both **RapidOCR (ONNX)** (ready out of the box) and **Tesseract OCR**.

### Installing Tesseract on Windows:
1. **Via Winget**:
   ```powershell
   winget install UB-Mannheim.TesseractOCR
   ```
2. **Manual Installer**:
   - Download the official Windows 64-bit installer from the UB-Mannheim repository:
     [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
   - Install to the default directory: `C:\Program Files\Tesseract-OCR\tesseract.exe`
3. **Environment Configuration**:
   - If installed in a custom directory, set `TESSERACT_CMD` in `.env`:
     ```env
     TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
     ```
   - SahayAI automatically detects Tesseract at `C:\Program Files\Tesseract-OCR\tesseract.exe`, `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`, `%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe`, and in system `PATH`.

---

## 🚀 Running the Project & Tests

### 1. Activate Virtual Environment
```powershell
.\venv\Scripts\Activate.ps1
```

### 2. Run Test Suite
```powershell
pytest -v
```
All 40 unit and integration tests will execute across all modules.
