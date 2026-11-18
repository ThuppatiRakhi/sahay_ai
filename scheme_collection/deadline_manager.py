"""Dynamic Scholarship Deadline Management System for SahayAI.

Provides:
- Timezone-aware (Asia/Kolkata) deadline evaluation.
- Distinct states: UPCOMING, OPEN, CLOSED, NOT_ANNOUNCED, UNVERIFIED.
- Strict separation between citizen eligibility and application availability.
- Multi-cycle and next-cycle tracking without date fabrication.
- Verified evidence excerpts for RAG and Chat grounding.
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

INDIA_TZ = ZoneInfo("Asia/Kolkata")
ISO_DATE_REGEX = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class DeadlineStatus(str, Enum):
    """Lifecycle statuses for scholarship and scheme application deadlines."""
    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    NOT_ANNOUNCED = "NOT_ANNOUNCED"
    UNVERIFIED = "UNVERIFIED"
    YEAR_ROUND = "YEAR_ROUND"
    QUOTA_DEPENDENT = "QUOTA_DEPENDENT"
    NEEDS_LIVE_VERIFICATION = "NEEDS_LIVE_VERIFICATION"


@dataclass
class DeadlineInfo:
    """Standardized representation of a scholarship's application window."""
    scheme_id: str
    status: DeadlineStatus
    is_currently_open: bool
    application_start_date: Optional[str] = None
    application_last_date: Optional[str] = None
    application_cycle: Optional[str] = None
    deadline_source: Optional[str] = None
    deadline_verified_at: Optional[str] = None
    next_cycle_status: Optional[str] = "NOT_ANNOUNCED"
    days_remaining: Optional[int] = None
    student_submission_deadline: Optional[str] = None
    institute_verification_deadline: Optional[str] = None
    nodal_verification_deadline: Optional[str] = None
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


def get_current_ist_datetime() -> datetime:
    """Return the current datetime in the Asia/Kolkata timezone."""
    return datetime.now(INDIA_TZ)


def get_current_ist_date() -> date:
    """Return the current calendar date in the Asia/Kolkata timezone."""
    return get_current_ist_datetime().date()


def parse_iso_date(date_val: Union[str, date, datetime]) -> Optional[date]:
    """Safely parse a date or date-string into a date object."""
    if date_val is None:
        return None
    if isinstance(date_val, datetime):
        return date_val.astimezone(INDIA_TZ).date() if date_val.tzinfo else date_val.date()
    if isinstance(date_val, date):
        return date_val

    clean_str = str(date_val).strip()
    if not clean_str or clean_str.upper() in ("NONE", "NULL", "UNKNOWN", "NOT_ANNOUNCED"):
        return None

    if not ISO_DATE_REGEX.match(clean_str):
        return None

    try:
        return datetime.strptime(clean_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def evaluate_scheme_deadline(
    scheme: Dict[str, Any],
    reference_date: Optional[Union[date, datetime, str]] = None,
) -> DeadlineInfo:
    """Deterministically evaluates dynamic deadline status for a scholarship scheme.

    Rules:
    - Timezone: Asia/Kolkata.
    - Before opening date: UPCOMING.
    - Between opening date and last date, inclusive: OPEN.
    - After last date: CLOSED.
    - Missing opening and closing dates: NOT_ANNOUNCED.
    - Missing deadline is NEVER treated as open.
    - Invalid, conflicting, or unverified dates: UNVERIFIED.
    - Next cycle only shown when supported by reliable information.

    Args:
        scheme: Scheme dictionary from registry.
        reference_date: Optional evaluation date override (useful for testing date boundaries).

    Returns:
        DeadlineInfo dataclass with complete availability metadata.
    """
    scheme_id = scheme.get("scheme_id") or "UNKNOWN_SCHEME"

    # 1. Resolve current evaluation date in Asia/Kolkata
    if reference_date is None:
        eval_date = get_current_ist_date()
    elif isinstance(reference_date, str):
        parsed_ref = parse_iso_date(reference_date)
        eval_date = parsed_ref if parsed_ref else get_current_ist_date()
    elif isinstance(reference_date, datetime):
        eval_date = reference_date.astimezone(INDIA_TZ).date() if reference_date.tzinfo else reference_date.date()
    else:
        eval_date = reference_date

    # 2. Extract deadline attributes from scheme record
    raw_start = scheme.get("application_start_date")
    raw_last = (
        scheme.get("application_last_date")
        or scheme.get("application_deadline")
        or scheme.get("last_application_deadline")
        or scheme.get("student_submission_deadline")
    )
    cycle = scheme.get("application_cycle") or scheme.get("current_application_cycle")
    source = scheme.get("deadline_source") or scheme.get("application_status_evidence") or scheme.get("source_portal")
    verified_at = scheme.get("deadline_verified_at") or scheme.get("application_status_last_checked")
    raw_next_cycle = scheme.get("next_cycle_status") or scheme.get("next_expected_cycle")

    student_deadline = scheme.get("student_submission_deadline") or raw_last
    inst_deadline = scheme.get("institute_verification_deadline")
    nodal_deadline = scheme.get("nodal_verification_deadline")

    # 3. Explicit UNVERIFIED checks
    if (
        scheme.get("deadline_status") == "UNVERIFIED"
        or scheme.get("is_deadline_unverified") is True
        or scheme.get("verification_status") == "unverified"
        or scheme.get("deadline_unreliable") is True
    ):
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.UNVERIFIED,
            is_currently_open=False,
            application_start_date=raw_start if isinstance(raw_start, str) else None,
            application_last_date=raw_last if isinstance(raw_last, str) else None,
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="UNVERIFIED",
            days_remaining=None,
            explanation="Application deadline information is unverified or marked unreliable.",
        )

    # 4. Check for distinct non-calendar availability statuses
    app_avail = (scheme.get("application_availability_status") or scheme.get("application_status") or "").upper()
    if app_avail == "YEAR_ROUND":
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.YEAR_ROUND,
            is_currently_open=True,
            application_start_date=raw_start if isinstance(raw_start, str) else None,
            application_last_date=raw_last if isinstance(raw_last, str) else None,
            application_cycle=cycle or "Year-Round",
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="CONTINUOUS",
            days_remaining=None,
            explanation="Applications are accepted year-round subject to scheme operational guidelines.",
        )

    if app_avail == "QUOTA_DEPENDENT":
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.QUOTA_DEPENDENT,
            is_currently_open=False,
            application_start_date=raw_start if isinstance(raw_start, str) else None,
            application_last_date=raw_last if isinstance(raw_last, str) else None,
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="QUOTA_DEPENDENT",
            days_remaining=None,
            explanation="Application availability depends on local agency and distributor quotas.",
        )

    if app_avail == "NEEDS_LIVE_VERIFICATION":
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.NEEDS_LIVE_VERIFICATION,
            is_currently_open=False,
            application_start_date=raw_start if isinstance(raw_start, str) else None,
            application_last_date=raw_last if isinstance(raw_last, str) else None,
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="NEEDS_LIVE_VERIFICATION",
            days_remaining=None,
            explanation="Portal is accessible, but live application intake requires real-time portal/state verification.",
        )

    # 5. Check for missing dates
    if (raw_start is None or str(raw_start).strip() == "") and (raw_last is None or str(raw_last).strip() == ""):
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.NOT_ANNOUNCED,
            is_currently_open=False,
            application_start_date=None,
            application_last_date=None,
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="NOT_ANNOUNCED",
            days_remaining=None,
            explanation="No application window dates have been announced by the authorities for this scheme.",
        )

    # 5. Parse and validate date formats
    start_date = parse_iso_date(raw_start) if raw_start else None
    last_date = parse_iso_date(raw_last) if raw_last else None

    # If raw dates were provided but failed to parse into valid ISO dates -> UNVERIFIED
    if raw_last is not None and str(raw_last).strip() and last_date is None:
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.UNVERIFIED,
            is_currently_open=False,
            application_start_date=str(raw_start) if raw_start else None,
            application_last_date=str(raw_last),
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="UNVERIFIED",
            days_remaining=None,
            explanation=f"Application last date '{raw_last}' is malformed or not in valid YYYY-MM-DD ISO format.",
        )

    if raw_start is not None and str(raw_start).strip() and start_date is None:
        return DeadlineInfo(
            scheme_id=scheme_id,
            status=DeadlineStatus.UNVERIFIED,
            is_currently_open=False,
            application_start_date=str(raw_start),
            application_last_date=str(raw_last) if raw_last else None,
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status="UNVERIFIED",
            days_remaining=None,
            explanation=f"Application start date '{raw_start}' is malformed or not in valid YYYY-MM-DD ISO format.",
        )

    # If both dates are provided, ensure chronological consistency
    if start_date is not None and last_date is not None:
        if start_date > last_date:
            return DeadlineInfo(
                scheme_id=scheme_id,
                status=DeadlineStatus.UNVERIFIED,
                is_currently_open=False,
                application_start_date=start_date.isoformat(),
                application_last_date=last_date.isoformat(),
                application_cycle=cycle,
                deadline_source=source,
                deadline_verified_at=verified_at,
                next_cycle_status="UNVERIFIED",
                days_remaining=None,
                explanation=f"Inconsistent dates: start date ({start_date}) is after last date ({last_date}).",
            )

    # If only start_date is provided and no last_date
    if last_date is None and start_date is not None:
        if eval_date < start_date:
            status = DeadlineStatus.UPCOMING
            is_open = False
            days_rem = None
            explanation = f"Applications will open on {start_date.isoformat()} for cycle {cycle or 'upcoming'}."
        else:
            # Start date passed, but closing date is unannounced
            status = DeadlineStatus.NOT_ANNOUNCED
            is_open = False
            days_rem = None
            explanation = f"Applications started on {start_date.isoformat()}, but closing deadline has not been announced."

        return DeadlineInfo(
            scheme_id=scheme_id,
            status=status,
            is_currently_open=is_open,
            application_start_date=start_date.isoformat(),
            application_last_date=None,
            application_cycle=cycle,
            deadline_source=source,
            deadline_verified_at=verified_at,
            next_cycle_status=raw_next_cycle or "NOT_ANNOUNCED",
            days_remaining=days_rem,
            explanation=explanation,
        )

    # 6. Evaluate against reference date
    assert last_date is not None

    clean_start_str = start_date.isoformat() if start_date else None
    clean_last_str = last_date.isoformat()

    # Next cycle resolution
    if raw_next_cycle and str(raw_next_cycle).strip() and str(raw_next_cycle).strip().upper() not in ("NONE", "NULL", "NOT_ANNOUNCED"):
        next_cycle_status = str(raw_next_cycle).strip()
    else:
        next_cycle_status = "NOT_ANNOUNCED"

    if start_date is not None and eval_date < start_date:
        # Before opening date -> UPCOMING
        status = DeadlineStatus.UPCOMING
        is_open = False
        days_rem = None
        explanation = f"Applications will open on {clean_start_str} for cycle {cycle or 'upcoming'}."
    elif eval_date <= last_date:
        # Between opening date (or start) and last date, inclusive -> OPEN
        status = DeadlineStatus.OPEN
        is_open = True
        days_rem = (last_date - eval_date).days
        explanation = f"Applications are currently OPEN until {clean_last_str} for cycle {cycle or 'current'} ({days_rem} days remaining)."
    else:
        # After last date -> CLOSED
        status = DeadlineStatus.CLOSED
        is_open = False
        days_rem = 0
        explanation = f"Application period for cycle {cycle or 'current'} closed on {clean_last_str}."

    return DeadlineInfo(
        scheme_id=scheme_id,
        status=status,
        is_currently_open=is_open,
        application_start_date=clean_start_str,
        application_last_date=clean_last_str,
        application_cycle=cycle,
        deadline_source=source,
        deadline_verified_at=verified_at,
        next_cycle_status=next_cycle_status,
        days_remaining=days_rem,
        student_submission_deadline=str(student_deadline) if student_deadline else clean_last_str,
        institute_verification_deadline=str(inst_deadline) if inst_deadline else None,
        nodal_verification_deadline=str(nodal_deadline) if nodal_deadline else None,
        explanation=explanation,
    )


def build_all_schemes_deadline_status(
    schemes: List[Dict[str, Any]],
    reference_date: Optional[Union[date, datetime, str]] = None,
) -> Dict[str, DeadlineInfo]:
    """Map each scheme_id in the collection to its calculated DeadlineInfo."""
    status_map: Dict[str, DeadlineInfo] = {}
    for scheme in schemes:
        s_id = scheme.get("scheme_id")
        if s_id:
            status_map[s_id] = evaluate_scheme_deadline(scheme, reference_date=reference_date)
    return status_map


def get_open_schemes(
    schemes: List[Dict[str, Any]],
    reference_date: Optional[Union[date, datetime, str]] = None,
) -> List[Dict[str, Any]]:
    """Filter schemes that are currently OPEN for application submission."""
    open_schemes = []
    for s in schemes:
        d_info = evaluate_scheme_deadline(s, reference_date=reference_date)
        if d_info.is_currently_open:
            s_copy = dict(s)
            s_copy["deadline"] = d_info.to_dict()
            open_schemes.append(s_copy)
    return open_schemes


def generate_deadline_context_for_rag(
    scheme: Dict[str, Any],
    reference_date: Optional[Union[date, datetime, str]] = None,
) -> str:
    """Generate verified, factual schedule text excerpt for inclusion in RAG evidence context."""
    d_info = evaluate_scheme_deadline(scheme, reference_date=reference_date)
    s_name = scheme.get("scheme_name") or scheme.get("scheme_id")
    cycle = d_info.application_cycle or "Current Academic Year"

    lines = [
        f"Official Verified Application & Deadline Schedule for {s_name} ({cycle}):",
        f"- Application Status: {d_info.status.value}",
        f"- Currently Accepting Applications: {'YES' if d_info.is_currently_open else 'NO'}",
    ]
    if d_info.application_start_date:
        lines.append(f"- Application Opening Date: {d_info.application_start_date}")
    if d_info.application_last_date:
        lines.append(f"- Student Application Closing Date / Last Date: {d_info.application_last_date}")
    if d_info.status == DeadlineStatus.CLOSED:
        lines.append(f"- Reason for Closure: Student application window closed on {d_info.application_last_date}.")
    elif d_info.status == DeadlineStatus.OPEN and d_info.days_remaining is not None:
        lines.append(f"- Days Remaining to Apply: {d_info.days_remaining} day(s)")
    if d_info.institute_verification_deadline:
        lines.append(f"- Institute Verification Deadline: {d_info.institute_verification_deadline}")
    if d_info.nodal_verification_deadline:
        lines.append(f"- Nodal Officer / SNO Verification Deadline: {d_info.nodal_verification_deadline}")
    if d_info.next_cycle_status:
        lines.append(f"- Next Application Cycle Status: {d_info.next_cycle_status}")
    if d_info.deadline_source:
        lines.append(f"- Authority Source: {d_info.deadline_source}")
    if d_info.deadline_verified_at:
        lines.append(f"- Verified As Of Date: {d_info.deadline_verified_at}")

    return "\n".join(lines)

