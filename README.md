# SahayAI 🏛️
### AI-Powered Government Welfare Scheme Discovery & Assistance Platform

## About SahayAI

SahayAI is an AI-powered public welfare assistance platform designed to simplify how citizens discover, understand and access government welfare schemes.

The platform brings together Artificial Intelligence, multilingual conversational assistance, Retrieval-Augmented Generation (RAG), document intelligence, OCR, computer vision and rule-based eligibility assessment to create a unified welfare assistance experience.

Instead of manually searching through multiple government portals and interpreting complex eligibility requirements, citizens can use SahayAI to explore relevant schemes, understand their benefits, process supporting documents and organize application-related information.

The system combines AI-assisted guidance with structured validation mechanisms to improve accessibility, transparency and reliability while incorporating privacy-conscious handling of sensitive citizen information.

## 🎯 Problem Statement

Accessing government welfare schemes can be difficult for many citizens because:

- Scheme information is distributed across multiple government websites and portals.
- Eligibility criteria and application procedures can be difficult to understand.
- Language barriers limit access to important public information.
- Document verification and information extraction can be time-consuming.
- Citizens may struggle to identify schemes relevant to their circumstances.
- Managing supporting documents and application-related information can be confusing.

SahayAI aims to address these challenges through a unified, AI-assisted platform.

## 💡 Project Objectives

1. Simplify government welfare scheme discovery.
2. Provide multilingual AI-assisted guidance.
3. Retrieve relevant scheme information using RAG where implemented.
4. Evaluate structured eligibility requirements using rule-based logic.
5. Automate document information extraction using OCR and document intelligence.
6. Maintain structured citizen profiles and document metadata.
7. Support citizens in organizing scheme application workflows.
8. Incorporate privacy-conscious data handling and verification mechanisms.

## 🌟 Key Features

1. Intelligent Scheme Discovery

Discover and explore government welfare schemes through organized scheme information and structured eligibility requirements.

2. Multilingual AI Assistant

Interact with an AI-powered assistant to understand government schemes, eligibility conditions and application procedures in supported languages.

3. Retrieval-Augmented Generation (RAG)

Use relevant scheme information as retrieval context for AI-generated responses, helping ground answers in available scheme data.

4. Rule-Based Eligibility Assessment

Evaluate citizen profile information against structured scheme eligibility conditions and identify potentially suitable schemes.

5. AI-Powered Document Intelligence

Process supported documents using OCR, image quality assessment and structured field extraction.

6. Citizen Profile Management

Maintain structured citizen information, track confirmation of extracted fields and provide profile data to downstream workflows.

7. Application Assistance Workspace

Organize scheme-related information and supporting documents through a structured application workflow.

8. Chrome Extension

Provide browser-based assistance through the implemented SahayAI extension.

9. Voice AI

Support voice-based interaction through the configured voice functionality.

🏗️ System Architecture

SahayAI follows a modular architecture that connects citizen interaction, AI-assisted scheme discovery, document intelligence, eligibility assessment and application support.

The following flowchart illustrates the high-level relationship between its major components.
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
### Understanding the Architecture

The architecture is organized around a central citizen-facing application that connects multiple specialized modules.

**1. Citizen Interaction Layer**

The user interface acts as the primary interaction point. Citizens can explore schemes, communicate with the AI assistant, manage profile information and access application assistance.

**2. AI Assistant and Knowledge Retrieval Layer**

The AI assistant processes user questions and uses the RAG pipeline, where configured, to retrieve relevant information from the scheme knowledge base before generating responses through an LLM.

**3. Document Intelligence Layer**

The document processing module coordinates image quality assessment, OCR and field extraction. Extracted information can be presented for citizen confirmation before being used in subsequent workflows.

**4. Citizen Profile and Eligibility Layer**

Structured citizen information is maintained through the profile management module. The eligibility engine evaluates available information against scheme-specific rules and produces assessment results.

**5. Scheme Collection and Verification Layer**

Scheme information is collected, validated and separated into raw and verified records. The verification workflow incorporates source checks, operational status validation and human review.

**6. Application Assistance Layer**

The application workspace helps organize scheme-related information and supporting documents. Browser and voice interfaces provide additional interaction capabilities where implemented.

### Core Processing Workflow

1. The citizen accesses the SahayAI platform.
2. The citizen explores government schemes or asks a question through the AI assistant.
3. Relevant scheme information is retrieved from the available knowledge base.
4. Supporting documents can be uploaded and processed using OCR.
5. Extracted information is reviewed and confirmed by the citizen.
6. Citizen profile information is evaluated against structured eligibility conditions.
7. The platform presents relevant information and supports the next steps in the application workflow.

The platform provides AI-assisted information and eligibility guidance. It does not replace official government approval or verification.
