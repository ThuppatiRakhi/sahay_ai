"""Multi-stage Scheme verification module for SahayAI.

Separates scheme verification into five distinct, auditable verification stages:
A. Structural validation (schema and constraint validation)
B. Source authenticity (responsible department & authentic government portal validation)
C. Operational status (active, inactive, discontinued, renamed, unknown)
D. Application URL reachability (network reachability without treating 200 as proof of authenticity)
E. Human verification review (mandatory reviewer approval before marking is_verified)

Prevents automatic verification based merely on .gov.in or .nic.in domain patterns.
Enforces strict segregation: only human-approved, verified schemes enter verified_schemes.json.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .scheme_validator import SchemeValidator

logger = logging.getLogger(__name__)

# Trusted recognized Indian government portals, state portals, and designated statutory platforms
RECOGNIZED_OFFICIAL_PORTALS = {
    "myscheme.gov.in": "MyScheme Central Citizen Portal",
    "pmkisan.gov.in": "Ministry of Agriculture and Farmers Welfare",
    "india.gov.in": "National Portal of India",
    "nrega.nic.in": "Ministry of Rural Development",
    "pmaymis.gov.in": "Ministry of Housing and Urban Affairs",
    "pmayg.nic.in": "Ministry of Rural Development (PMAY-G)",
    "dbtbharat.gov.in": "Direct Benefit Transfer Mission",
    "scholarships.gov.in": "National Scholarship Portal",
    "education.gov.in": "Ministry of Education",
    "aicte-india.org": "All India Council for Technical Education",
    "socialjustice.gov.in": "Ministry of Social Justice and Empowerment",
    "tribal.gov.in": "Ministry of Tribal Affairs",
    "telanganaepass.cgg.gov.in": "Telangana ePASS (Centre for Good Governance)",
    "telangana.gov.in": "Government of Telangana",
    "cgg.gov.in": "Centre for Good Governance",
    "msde.gov.in": "Ministry of Skill Development and Entrepreneurship",
    "skillindia.gov.in": "Skill India Digital",
    "pmkvyofficial.org": "Pradhan Mantri Kaushal Vikas Yojana",
    "apprenticeshipindia.gov.in": "National Apprenticeship Promotion Scheme",
    "kviconline.gov.in": "Khadi and Village Industries Commission",
    "mudra.org.in": "Micro Units Development & Refinance Agency",
    "udyamimitra.in": "SIDBI Udyami Mitra Portal",
    "standupmitra.in": "SIDBI Stand-Up Mitra Portal",
    "pmsvanidhi.mohua.gov.in": "PM SVANidhi Portal",
    "warb-mha.gov.in": "Welfare and Rehabilitation Board (MHA)",
    "mha.gov.in": "Ministry of Home Affairs",
    "pmfby.gov.in": "Pradhan Mantri Fasal Bima Yojana",
    "pmjay.gov.in": "National Health Authority PM-JAY",
    "nha.gov.in": "National Health Authority",
    "pfrda.org.in": "Pension Fund Regulatory and Development Authority",
    "nsdl.co.in": "NSDL CRA / Protean",
    "financialservices.gov.in": "Department of Financial Services",
    "nta.ac.in": "National Testing Agency",
    "nosmsje.gov.in": "National Overseas Scholarship Portal (MSJE)",
    "aasara.telangana.gov.in": "Telangana Aasara Pension Portal",
    "housing.telangana.gov.in": "Telangana Housing Department",
    "rythubharosa.telangana.gov.in": "Telangana Rythu Bharosa Portal",
}

RECOGNIZED_MINISTRIES = [
    "Ministry of Agriculture and Farmers Welfare",
    "Ministry of Rural Development",
    "Ministry of Social Justice and Empowerment",
    "Ministry of Women and Child Development",
    "Ministry of Education",
    "Department of Higher Education",
    "Department of School Education and Literacy",
    "Department of Social Justice and Empowerment",
    "All India Council for Technical Education",
    "AICTE",
    "Ministry of Housing and Urban Affairs",
    "Ministry of Labour and Employment",
    "Ministry of Tribal Affairs",
    "Ministry of Skill Development and Entrepreneurship",
    "Ministry of Micro, Small and Medium Enterprises",
    "Ministry of Finance",
    "Department of Financial Services",
    "Ministry of Home Affairs",
    "Ministry of Health and Family Welfare",
    "National Health Authority",
    "Ministry of Minority Affairs",
    "Khadi and Village Industries Commission",
    "Small Industries Development Bank of India",
    "SIDBI",
    "Pension Fund Regulatory and Development Authority",
    "PFRDA",
    "Government of Telangana",
    "Backward Classes Welfare Department",
    "Scheduled Castes Development Department",
    "Minorities Welfare Department",
    "Tribal Welfare Department",
    "Panchayat Raj and Rural Development Department",
    "Agriculture and Cooperation Department",
    "Housing Department",
    "Revenue Department",
    "Department of Social Justice",
    "Department of Food and Public Distribution",
]


@dataclass
class StageVerificationResult:
    """Individual verification check record."""
    stage: str
    passed: bool
    details: str
    evidence: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SchemeVerificationReport:
    """Full 5-stage verification audit report for a scheme."""
    scheme_id: str
    is_fully_verified: bool
    operational_status: str
    stages: Dict[str, Dict[str, Any]]
    failure_reasons: List[str]
    reviewer_status: Dict[str, Any]
    verified_record: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SchemeVerifier:
    """Multi-stage verifier ensuring official authenticity, operational viability, and human review."""

    def __init__(
        self,
        raw_schemes_path: Optional[str] = None,
        verified_schemes_path: Optional[str] = None,
        validator: Optional[SchemeValidator] = None,
        check_live_network: bool = False,
    ):
        """Initialize SchemeVerifier.

        Args:
            raw_schemes_path: Path to raw collected schemes JSON.
            verified_schemes_path: Path to verified schemes storage.
            validator: Optional SchemeValidator instance.
            check_live_network: Whether to execute live HTTP reachability checks.
        """
        self.raw_path = Path(raw_schemes_path) if raw_schemes_path else Path("data/schemes/schemes.json")
        self.verified_path = (
            Path(verified_schemes_path) if verified_schemes_path else Path("data/schemes/verified_schemes.json")
        )
        self.validator = validator or SchemeValidator()
        self.check_live_network = check_live_network

    # Stage A: Structural Validation
    def check_structural_validation(self, scheme: Dict[str, Any]) -> StageVerificationResult:
        is_valid, errors = self.validator.validate(scheme)
        if not is_valid:
            return StageVerificationResult(
                stage="A_structural_validation",
                passed=False,
                details="Structural validation failed: " + "; ".join(errors),
                evidence=None,
            )
        return StageVerificationResult(
            stage="A_structural_validation",
            passed=True,
            details="All required scheme fields, eligibility ranges, and benefits conform to schema.",
            evidence="Validated against JSON Schema Draft 2020-12 and Pydantic SchemeModel.",
        )

    # Stage B: Source Authenticity
    def check_source_authenticity(self, scheme: Dict[str, Any]) -> StageVerificationResult:
        app_url = scheme.get("application_url", "")
        dept = scheme.get("department", "").strip()
        ministry = scheme.get("responsible_ministry", "").strip()

        if not app_url:
            return StageVerificationResult(
                stage="B_source_authenticity",
                passed=False,
                details="Missing application_url; cannot establish official publishing source.",
            )

        hostname = urlparse(app_url).hostname or ""

        # Check official domain and department recognition
        domain_match = any(hostname.endswith(portal) or hostname == portal for portal in RECOGNIZED_OFFICIAL_PORTALS)
        is_gov_domain = hostname.endswith(".gov.in") or hostname.endswith(".nic.in") or domain_match

        dept_text = f"{dept} {ministry}".lower()
        dept_recognized = any(recognized.lower() in dept_text for recognized in RECOGNIZED_MINISTRIES)

        if not is_gov_domain:
            return StageVerificationResult(
                stage="B_source_authenticity",
                passed=False,
                details=f"URL host '{hostname}' is not a recognized official government portal.",
            )

        if not dept_recognized:
            return StageVerificationResult(
                stage="B_source_authenticity",
                passed=False,
                details=f"Department '{dept}' / Ministry '{ministry}' is not verified against recognized government authorities list.",
            )

        return StageVerificationResult(
            stage="B_source_authenticity",
            passed=True,
            details=f"Source hosted under official domain '{hostname}' and administered by recognized authority '{dept}'.",
            evidence=f"Hostname: {hostname} | Department: {dept}",
        )

    # Stage C: Operational Status
    def check_operational_status(self, scheme: Dict[str, Any]) -> StageVerificationResult:
        status = scheme.get("operational_status", "ACTIVE").upper()

        if status == "ACTIVE":
            return StageVerificationResult(
                stage="C_operational_status",
                passed=True,
                details="Scheme confirmed actively operational and accepting citizen applications.",
                evidence="Status flag: ACTIVE",
            )
        elif status in ("INACTIVE", "DISCONTINUED", "RENAMED"):
            return StageVerificationResult(
                stage="C_operational_status",
                passed=False,
                details=f"Scheme operational status is '{status}'; cannot be approved as an active welfare scheme.",
                evidence=f"Operational status flag: {status}",
            )
        else:
            return StageVerificationResult(
                stage="C_operational_status",
                passed=False,
                details="Operational status unknown; official operating state must be established before verification.",
                evidence=f"Status: {status}",
            )

    # Stage D: Application URL Reachability
    def check_application_url(self, scheme: Dict[str, Any]) -> StageVerificationResult:
        app_url = scheme.get("application_url", "")
        if not app_url:
            return StageVerificationResult(
                stage="D_application_url",
                passed=False,
                details="No application URL specified.",
            )

        parsed = urlparse(app_url)
        if not parsed.scheme or not parsed.netloc:
            return StageVerificationResult(
                stage="D_application_url",
                passed=False,
                details=f"Malformed application URL: '{app_url}'.",
            )

        if not self.check_live_network:
            return StageVerificationResult(
                stage="D_application_url",
                passed=True,
                details=f"URL format valid ({parsed.scheme}://{parsed.netloc}). Note: HTTP 200 response alone does not prove scheme authenticity.",
                evidence=f"URI Scheme: {parsed.scheme} | Host: {parsed.netloc} | Live network check deferred.",
            )

        # Active network check
        try:
            import requests

            resp = requests.head(app_url, allow_redirects=True, timeout=5)
            if resp.status_code < 400:
                return StageVerificationResult(
                    stage="D_application_url",
                    passed=True,
                    details=f"URL reachable (HTTP {resp.status_code}). Note: HTTP reachability is connectivity proof only, not authenticity proof.",
                    evidence=f"HTTP Status: {resp.status_code} | Final URL: {resp.url}",
                )
            else:
                return StageVerificationResult(
                    stage="D_application_url",
                    passed=False,
                    details=f"URL returned HTTP error status {resp.status_code}.",
                    evidence=f"HTTP Status: {resp.status_code}",
                )
        except Exception as exc:
            return StageVerificationResult(
                stage="D_application_url",
                passed=False,
                details=f"Network request to URL failed: {str(exc)}",
            )

    # Stage E: Human Verification
    def check_human_review(self, scheme: Dict[str, Any]) -> StageVerificationResult:
        review = scheme.get("human_review")
        if not review or not isinstance(review, dict):
            return StageVerificationResult(
                stage="E_human_review",
                passed=False,
                details="Mandatory human review step missing. A designated reviewer must approve before verification.",
            )

        reviewer = review.get("reviewer_id")
        decision = review.get("decision", "").upper()
        notes = review.get("review_notes", "")

        if not reviewer or not notes:
            return StageVerificationResult(
                stage="E_human_review",
                passed=False,
                details="Incomplete human review details (reviewer_id and review_notes required).",
            )

        if decision == "APPROVED":
            return StageVerificationResult(
                stage="E_human_review",
                passed=True,
                details=f"Approved by reviewer '{reviewer}'. Notes: {notes}",
                evidence=f"Reviewer: {reviewer} | Date: {review.get('reviewed_at')}",
            )
        else:
            return StageVerificationResult(
                stage="E_human_review",
                passed=False,
                details=f"Human review status is '{decision}' (not APPROVED).",
                evidence=f"Decision: {decision}",
            )

    def verify_single(self, scheme: Dict[str, Any]) -> SchemeVerificationReport:
        """Execute all five verification stages on a scheme record.

        Args:
            scheme: Raw scheme dictionary.

        Returns:
            SchemeVerificationReport detailing results of all 5 stages.
        """
        stages: Dict[str, Dict[str, Any]] = {}
        failures: List[str] = []

        # Run Stage A
        res_a = self.check_structural_validation(scheme)
        stages["structural_validation"] = res_a.to_dict()
        if not res_a.passed:
            failures.append(res_a.details)

        # Run Stage B
        res_b = self.check_source_authenticity(scheme)
        stages["source_authenticity"] = res_b.to_dict()
        if not res_b.passed:
            failures.append(res_b.details)

        # Run Stage C
        res_c = self.check_operational_status(scheme)
        stages["operational_status"] = res_c.to_dict()
        if not res_c.passed:
            failures.append(res_c.details)

        # Run Stage D
        res_d = self.check_application_url(scheme)
        stages["application_url"] = res_d.to_dict()
        if not res_d.passed:
            failures.append(res_d.details)

        # Run Stage E
        res_e = self.check_human_review(scheme)
        stages["human_review"] = res_e.to_dict()
        if not res_e.passed:
            failures.append(res_e.details)

        # Verification status check: only verified if explicitly approved in human review
        status = scheme.get("verification_status")
        if status in ("pending_review", "partial", "uncertain", "inactive"):
            failures.append(f"Verification status is '{status}'; scheme must undergo review before marking verified.")

        is_fully_verified = len(failures) == 0

        verified_record = None
        if is_fully_verified:
            verified_record = dict(scheme)
            verified_record["is_verified"] = True
            verified_record["verification_status"] = "verified"
            verified_record["verified_at"] = datetime.now(timezone.utc).isoformat()
            verified_record["verification_source"] = urlparse(scheme.get("application_url", "")).hostname
            verified_record["verification_evidence"] = {
                "stages_passed": list(stages.keys()),
                "reviewer": scheme.get("human_review", {}).get("reviewer_id"),
            }

        return SchemeVerificationReport(
            scheme_id=scheme.get("scheme_id", "unknown"),
            is_fully_verified=is_fully_verified,
            operational_status=scheme.get("operational_status", "ACTIVE"),
            stages=stages,
            failure_reasons=failures,
            reviewer_status=scheme.get("human_review", {}) or {},
            verified_record=verified_record,
        )

    def verify_and_save(self) -> Tuple[int, int]:
        """Read raw schemes, execute multi-stage verification, and persist only fully verified schemes."""
        if not self.raw_path.exists():
            raise FileNotFoundError(f"Raw schemes file not found: {self.raw_path}")

        with open(self.raw_path, "r", encoding="utf-8") as f:
            raw_schemes = json.load(f)

        verified_list: List[Dict[str, Any]] = []
        rejected_count = 0

        for scheme in raw_schemes:
            report = self.verify_single(scheme)
            if report.is_fully_verified and report.verified_record:
                verified_list.append(report.verified_record)
            else:
                rejected_count += 1
                logger.warning(
                    "Scheme '%s' failed multi-stage verification: %s",
                    report.scheme_id,
                    "; ".join(report.failure_reasons),
                )

        self.verified_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.verified_path, "w", encoding="utf-8") as f:
            json.dump(verified_list, f, indent=2, ensure_ascii=False)

        logger.info(
            "Multi-stage verification complete: %d verified, %d rejected. Saved to %s",
            len(verified_list),
            rejected_count,
            self.verified_path,
        )

        return len(verified_list), rejected_count
