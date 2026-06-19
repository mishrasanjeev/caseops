from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    EmailCalendarCandidate,
    EmailCalendarCandidateStatus,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
)
from caseops_api.schemas.calendar import (
    EmailInvitationCandidateExtractRequest,
    EmailInvitationCandidateExtractResponse,
    EmailInvitationCandidateListResponse,
    EmailInvitationCandidateRecord,
    EmailInvitationCandidateReviewRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.session_context import SessionContext

_MAX_PREVIEW_CHARS = 280
_MAX_SCAN_ROWS = 500
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_INDIA_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")
_TEXT_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"\b(?:at|from|time\s*:?)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r"\b(?:venue|location|place)\s*[:\-]\s*([^.;\n\r]{2,160})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Extraction:
    title: str
    start_at: datetime
    end_at: datetime | None
    location: str | None
    preview: str | None
    confidence_band: str
    normalized_key: str


def list_email_invitation_candidates(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> EmailInvitationCandidateListResponse:
    rows = _candidate_rows(
        session,
        context=context,
        matter_id=matter_id,
        status_filter=status_filter,
        limit=limit,
    )
    records = [_candidate_record(candidate, matter) for candidate, matter in rows]
    return EmailInvitationCandidateListResponse(
        candidates=records,
        pending_count=sum(1 for item in records if item.status == "needs_review"),
        duplicate_count=sum(
            1 for item in records if item.status == "duplicate_skipped"
        ),
    )


def extract_email_invitation_candidates(
    session: Session,
    *,
    context: SessionContext,
    payload: EmailInvitationCandidateExtractRequest,
) -> EmailInvitationCandidateExtractResponse:
    matter = _load_matter(session, context=context, matter_id=payload.matter_id)
    communications = _candidate_communications(
        session,
        context=context,
        matter_id=matter.id if matter is not None else None,
        limit=payload.limit,
    )
    examined = 0
    created = 0
    duplicates = 0
    candidates: list[tuple[EmailCalendarCandidate, Matter]] = []
    matters_by_id: dict[str, Matter] = {}

    for row, row_matter in communications:
        examined += 1
        matters_by_id[row_matter.id] = row_matter
        extraction = _extract_from_communication(row)
        if extraction is None:
            continue
        candidate, was_created = _upsert_candidate(
            session,
            context=context,
            communication=row,
            matter=row_matter,
            extraction=extraction,
        )
        if was_created:
            created += 1
        if candidate.status == EmailCalendarCandidateStatus.DUPLICATE_SKIPPED:
            duplicates += 1
        candidates.append((candidate, row_matter))

    record_from_context(
        session,
        context,
        action="calendar.email_candidate.extracted",
        target_type="email_calendar_candidate",
        matter_id=matter.id if matter is not None else None,
        metadata={
            "examined_count": examined,
            "created_count": created,
            "duplicate_count": duplicates,
            "field_keys": [
                "title",
                "start_at",
                "end_at",
                "location",
                "source_preview",
            ],
            "source": "imported_email_metadata",
            "deterministic": True,
        },
    )
    session.commit()
    return EmailInvitationCandidateExtractResponse(
        examined_count=examined,
        created_count=created,
        duplicate_count=duplicates,
        candidates=[
            _candidate_record(candidate, matters_by_id[candidate.matter_id])
            for candidate, _ in candidates
        ],
    )


def review_email_invitation_candidate(
    session: Session,
    *,
    context: SessionContext,
    candidate_id: str,
    payload: EmailInvitationCandidateReviewRequest,
) -> EmailInvitationCandidateRecord:
    candidate, matter = _load_candidate_with_matter(
        session,
        context=context,
        candidate_id=candidate_id,
    )
    now = datetime.now(UTC)
    if payload.action == "reject":
        if candidate.status == EmailCalendarCandidateStatus.APPROVED_CREATED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approved calendar candidates cannot be rejected.",
            )
        candidate.status = EmailCalendarCandidateStatus.REJECTED
        candidate.reviewed_by_membership_id = context.membership.id
        candidate.reviewed_at = now
        record_from_context(
            session,
            context,
            action="calendar.email_candidate.rejected",
            target_type="email_calendar_candidate",
            target_id=candidate.id,
            matter_id=matter.id,
            metadata=_candidate_audit_metadata(candidate, action="reject"),
        )
        session.commit()
        session.refresh(candidate)
        return _candidate_record(candidate, matter)

    if candidate.status == EmailCalendarCandidateStatus.DUPLICATE_SKIPPED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate email invitation candidates require no event creation.",
        )
    if candidate.created_deadline_id:
        candidate.status = EmailCalendarCandidateStatus.APPROVED_CREATED
        candidate.reviewed_by_membership_id = context.membership.id
        candidate.reviewed_at = candidate.reviewed_at or now
        session.commit()
        session.refresh(candidate)
        return _candidate_record(candidate, matter)

    deadline = MatterDeadline(
        matter_id=matter.id,
        source="email_invitation",
        kind="calendar_event_candidate",
        title=candidate.detected_title[:255],
        notes="Created from a reviewed imported-email calendar candidate.",
        due_on=candidate.detected_start_at.date(),
        status=MatterDeadlineStatus.OPEN,
        source_ref_type="communication",
        source_ref_id=candidate.communication_id,
        created_by_membership_id=context.membership.id,
    )
    session.add(deadline)
    session.flush()
    candidate.status = EmailCalendarCandidateStatus.APPROVED_CREATED
    candidate.created_deadline_id = deadline.id
    candidate.reviewed_by_membership_id = context.membership.id
    candidate.reviewed_at = now
    record_from_context(
        session,
        context,
        action="calendar.email_candidate.approved",
        target_type="email_calendar_candidate",
        target_id=candidate.id,
        matter_id=matter.id,
        metadata={
            **_candidate_audit_metadata(candidate, action="approve"),
            "created_event_type": "matter_deadline",
            "created_event_id_hash": _hash_value(deadline.id),
        },
    )
    session.commit()
    session.refresh(candidate)
    return _candidate_record(candidate, matter)


def _candidate_rows(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
    status_filter: str | None,
    limit: int,
) -> list[tuple[EmailCalendarCandidate, Matter]]:
    stmt = (
        select(EmailCalendarCandidate, Matter)
        .join(Matter, Matter.id == EmailCalendarCandidate.matter_id)
        .where(
            EmailCalendarCandidate.company_id == context.company.id,
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )
        .order_by(
            EmailCalendarCandidate.detected_start_at.asc(),
            EmailCalendarCandidate.created_at.asc(),
        )
        .limit(max(1, min(limit, 100)))
    )
    if matter_id:
        matter = _load_matter(session, context=context, matter_id=matter_id)
        stmt = stmt.where(EmailCalendarCandidate.matter_id == matter.id)
    if status_filter:
        stmt = stmt.where(EmailCalendarCandidate.status == status_filter)
    return list(session.execute(stmt).all())


def _candidate_communications(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
    limit: int,
) -> list[tuple[Communication, Matter]]:
    stmt = (
        select(Communication, Matter)
        .join(Matter, Matter.id == Communication.matter_id)
        .where(
            Communication.company_id == context.company.id,
            Communication.matter_id.is_not(None),
            Communication.channel == CommunicationChannel.EMAIL.value,
            Communication.direction == CommunicationDirection.INBOUND.value,
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )
        .order_by(Communication.occurred_at.desc(), Communication.created_at.desc())
        .limit(max(1, min(limit, _MAX_SCAN_ROWS)))
    )
    if matter_id:
        stmt = stmt.where(Matter.id == matter_id)
    rows = list(session.execute(stmt).all())
    return [
        (communication, matter)
        for communication, matter in rows
        if _is_imported_email(communication)
    ]


def _load_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter | None:
    if matter_id is None:
        return None
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _load_candidate_with_matter(
    session: Session,
    *,
    context: SessionContext,
    candidate_id: str,
) -> tuple[EmailCalendarCandidate, Matter]:
    row = session.execute(
        select(EmailCalendarCandidate, Matter)
        .join(Matter, Matter.id == EmailCalendarCandidate.matter_id)
        .where(
            EmailCalendarCandidate.id == candidate_id,
            EmailCalendarCandidate.company_id == context.company.id,
            Matter.company_id == context.company.id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email invitation calendar candidate not found.",
        )
    candidate, matter = row
    assert_access(session, context=context, matter=matter)
    return candidate, matter


def _upsert_candidate(
    session: Session,
    *,
    context: SessionContext,
    communication: Communication,
    matter: Matter,
    extraction: _Extraction,
) -> tuple[EmailCalendarCandidate, bool]:
    existing = session.scalar(
        select(EmailCalendarCandidate).where(
            EmailCalendarCandidate.company_id == context.company.id,
            EmailCalendarCandidate.matter_id == matter.id,
            EmailCalendarCandidate.communication_id == communication.id,
            EmailCalendarCandidate.normalized_key == extraction.normalized_key,
        )
    )
    if existing is not None:
        return existing, False

    duplicate = session.scalar(
        select(EmailCalendarCandidate)
        .where(
            EmailCalendarCandidate.company_id == context.company.id,
            EmailCalendarCandidate.matter_id == matter.id,
            EmailCalendarCandidate.normalized_key == extraction.normalized_key,
            EmailCalendarCandidate.status.in_(
                [
                    EmailCalendarCandidateStatus.NEEDS_REVIEW.value,
                    EmailCalendarCandidateStatus.APPROVED_CREATED.value,
                ]
            ),
        )
        .order_by(EmailCalendarCandidate.created_at.asc())
        .limit(1)
    )
    status_value = (
        EmailCalendarCandidateStatus.DUPLICATE_SKIPPED
        if duplicate is not None
        else EmailCalendarCandidateStatus.NEEDS_REVIEW
    )
    candidate = EmailCalendarCandidate(
        company_id=context.company.id,
        matter_id=matter.id,
        communication_id=communication.id,
        thread_key=_communication_thread_key(communication),
        normalized_key=extraction.normalized_key,
        detected_title=extraction.title,
        detected_start_at=extraction.start_at,
        detected_end_at=extraction.end_at,
        detected_location=extraction.location,
        source_preview=extraction.preview,
        confidence_band=extraction.confidence_band,
        status=status_value,
        duplicate_of_candidate_id=duplicate.id if duplicate is not None else None,
        created_by_membership_id=context.membership.id,
    )
    session.add(candidate)
    session.flush()
    return candidate, True


def _extract_from_communication(row: Communication) -> _Extraction | None:
    text = _source_text(row)
    if not text:
        return None
    date_match = _find_date(text)
    if date_match is None:
        return None
    matched_date, match_end = date_match
    time_match = _find_time(text[match_end : match_end + 80])
    hour = time_match[0] if time_match else 0
    minute = time_match[1] if time_match else 0
    start_at = datetime(
        matched_date.year,
        matched_date.month,
        matched_date.day,
        hour,
        minute,
        tzinfo=UTC,
    )
    end_at = start_at + timedelta(hours=1) if time_match else None
    location = _compact_optional(_find_location(text), max_chars=255)
    title = _candidate_title(row)
    preview = _compact_optional(text, max_chars=_MAX_PREVIEW_CHARS)
    confidence = _confidence_band(has_time=time_match is not None, has_location=bool(location))
    normalized_key = _normalized_key(
        title=title,
        start_at=start_at,
        location=location,
    )
    return _Extraction(
        title=title,
        start_at=start_at,
        end_at=end_at,
        location=location,
        preview=preview,
        confidence_band=confidence,
        normalized_key=normalized_key,
    )


def _find_date(text: str) -> tuple[datetime, int] | None:
    matches: list[tuple[int, datetime, int]] = []
    for match in _ISO_DATE_RE.finditer(text):
        try:
            value = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=UTC,
            )
        except ValueError:
            continue
        matches.append((match.start(), value, match.end()))
    for match in _INDIA_DATE_RE.finditer(text):
        try:
            value = datetime(
                int(match.group(3)),
                int(match.group(2)),
                int(match.group(1)),
                tzinfo=UTC,
            )
        except ValueError:
            continue
        matches.append((match.start(), value, match.end()))
    for match in _TEXT_DATE_RE.finditer(text):
        month = _MONTHS.get(match.group(2).casefold())
        if month is None:
            continue
        try:
            value = datetime(
                int(match.group(3)),
                month,
                int(match.group(1)),
                tzinfo=UTC,
            )
        except ValueError:
            continue
        matches.append((match.start(), value, match.end()))
    if not matches:
        return None
    _, value, end = sorted(matches, key=lambda row: row[0])[0]
    return value, end


def _find_time(text: str) -> tuple[int, int] | None:
    match = _TIME_RE.search(text)
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    marker = (match.group(3) or "").casefold()
    if hour > 23 or minute > 59:
        return None
    if marker == "pm" and hour < 12:
        hour += 12
    if marker == "am" and hour == 12:
        hour = 0
    return hour, minute


def _find_location(text: str) -> str | None:
    match = _LOCATION_RE.search(text)
    return match.group(1) if match else None


def _source_text(row: Communication) -> str:
    parts = [row.subject or "", row.body or ""]
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    # Only existing bounded metadata is considered; never dereference body or
    # attachment storage records.
    for key in ("invite_preview", "body_preview", "event_preview"):
        value = metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(part for part in parts if part)


def _candidate_title(row: Communication) -> str:
    raw = _compact_optional(row.subject, max_chars=255) or "Email invitation"
    cleaned = re.sub(
        r"^\s*(re|fw|fwd)\s*:\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*(calendar\s+invite|invitation|meeting)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return (cleaned or "Email invitation")[:255]


def _communication_thread_key(row: Communication) -> str | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    for key in (
        "provider_thread_id",
        "thread_id",
        "conversation_id",
        "provider_conversation_id",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            provider = str(metadata.get("provider") or "email").strip() or "email"
            return f"{provider}:{value.strip()}"[:180]
    return row.external_message_id[:180] if row.external_message_id else None


def _is_imported_email(row: Communication) -> bool:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return (
        metadata.get("source") == "manual_inbound_email_import"
        or metadata.get("source") == "gmail_provider_import"
        or metadata.get("automation_mode") == "manual_only"
        or metadata.get("automation_mode") == "provider_review_first"
    )


def _confidence_band(*, has_time: bool, has_location: bool) -> str:
    if has_time and has_location:
        return "high"
    if has_time or has_location:
        return "medium"
    return "low"


def _normalized_key(
    *,
    title: str,
    start_at: datetime,
    location: str | None,
) -> str:
    raw = "|".join(
        [
            _normalise_for_key(title),
            start_at.isoformat(),
            _normalise_for_key(location or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise_for_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _compact_optional(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    compacted = re.sub(r"\s+", " ", value).strip()
    if not compacted:
        return None
    return compacted[:max_chars]


def _candidate_record(
    candidate: EmailCalendarCandidate,
    matter: Matter,
) -> EmailInvitationCandidateRecord:
    return EmailInvitationCandidateRecord(
        id=candidate.id,
        company_id=candidate.company_id,
        matter_id=candidate.matter_id,
        matter_title=matter.title,
        matter_code=matter.matter_code,
        communication_id=candidate.communication_id,
        thread_key=candidate.thread_key,
        status=str(candidate.status),
        detected_title=candidate.detected_title,
        detected_start_at=candidate.detected_start_at,
        detected_end_at=candidate.detected_end_at,
        detected_location=candidate.detected_location,
        source_preview=candidate.source_preview,
        confidence_band=candidate.confidence_band,
        duplicate_of_candidate_id=candidate.duplicate_of_candidate_id,
        created_deadline_id=candidate.created_deadline_id,
        reviewed_by_membership_id=candidate.reviewed_by_membership_id,
        reviewed_at=candidate.reviewed_at,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _candidate_audit_metadata(
    candidate: EmailCalendarCandidate,
    *,
    action: str,
) -> dict[str, object]:
    return {
        "action": action,
        "candidate_id_hash": _hash_value(candidate.id),
        "matter_id_hash": _hash_value(candidate.matter_id),
        "communication_id_hash": _hash_value(candidate.communication_id),
        "normalized_key_hash": _hash_value(candidate.normalized_key),
        "status": str(candidate.status),
        "has_location": bool(candidate.detected_location),
        "has_end_at": bool(candidate.detected_end_at),
        "has_source_preview": bool(candidate.source_preview),
        "source_preview_length": len(candidate.source_preview or ""),
        "field_keys": ["title", "start_at", "end_at", "location"],
    }


def _hash_value(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
