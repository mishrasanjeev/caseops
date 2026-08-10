from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CalendarEventCandidate,
    CalendarEventCandidateStatus,
    Matter,
    MatterHearing,
    MatterHearingStatus,
    MatterNextHearingSource,
)
from caseops_api.schemas.calendar import (
    CalendarProviderEventCandidateCreateRequest,
    CalendarProviderEventCandidateListResponse,
    CalendarProviderEventCandidateRecord,
    CalendarProviderEventCandidateReviewRequest,
    CalendarProviderEventCandidateReviewResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext


def _now() -> datetime:
    return datetime.now(UTC)


def _record(row: CalendarEventCandidate) -> CalendarProviderEventCandidateRecord:
    return CalendarProviderEventCandidateRecord(
        id=row.id,
        company_id=row.company_id,
        provider=row.provider,  # type: ignore[arg-type]
        provider_event_id=row.provider_event_id,
        i_cal_uid=row.i_cal_uid,
        title=row.title,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        location=row.location,
        organizer_display=row.organizer_display,
        provider_status=row.provider_status,
        suggested_matter_id=row.suggested_matter_id,
        linked_matter_id=row.linked_matter_id,
        linked_hearing_id=row.linked_hearing_id,
        confidence=row.confidence,
        status=row.status,  # type: ignore[arg-type]
        conflict_reason=row.conflict_reason,
        provenance=row.provenance_json,
        sync_history=list(row.sync_history_json or []),
        reviewed_by_membership_id=row.reviewed_by_membership_id,
        reviewed_at=row.reviewed_at,
        last_error_redacted=row.last_error_redacted,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _matter_for_candidate(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter:
    if not matter_id:
        raise HTTPException(status_code=400, detail="matter_id is required.")
    matter = session.get(Matter, matter_id)
    if matter is None or matter.company_id != context.company.id:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def _suggest_matter(
    session: Session,
    *,
    context: SessionContext,
    title: str,
) -> Matter | None:
    lowered = title.lower()
    for matter in session.scalars(
        select(Matter).where(
            Matter.company_id == context.company.id,
            visible_matters_filter(context),
        )
    ):
        if matter.matter_code.lower() in lowered:
            return matter
    return None


def create_calendar_event_candidate(
    session: Session,
    *,
    context: SessionContext,
    payload: CalendarProviderEventCandidateCreateRequest,
) -> CalendarProviderEventCandidateRecord:
    existing = session.scalar(
        select(CalendarEventCandidate).where(
            CalendarEventCandidate.company_id == context.company.id,
            CalendarEventCandidate.provider == payload.provider,
            CalendarEventCandidate.provider_event_id == payload.provider_event_id,
        )
    )
    if existing is not None:
        return _record(existing)
    matter = None
    if payload.suggested_matter_id:
        matter = _matter_for_candidate(
            session,
            context=context,
            matter_id=payload.suggested_matter_id,
        )
    if matter is None:
        matter = _suggest_matter(session, context=context, title=payload.title)
    row = CalendarEventCandidate(
        company_id=context.company.id,
        provider=payload.provider,
        provider_event_id=payload.provider_event_id,
        i_cal_uid=payload.i_cal_uid,
        title=payload.title[:500],
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        location=payload.location,
        organizer_display=payload.organizer_display,
        provider_status=payload.provider_status,
        suggested_matter_id=matter.id if matter else None,
        confidence=0.9 if matter else None,
        status=CalendarEventCandidateStatus.NEW,
        provenance_json={
            "provider": payload.provider,
            "provider_event_id": payload.provider_event_id,
            "manual_review_required": True,
        },
        sync_history_json=[
            {"at": _now().isoformat(), "event": "candidate_created"},
        ],
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="calendar.provider_event_candidate.created",
        target_type="calendar_event_candidate",
        target_id=row.id,
        matter_id=matter.id if matter else None,
        metadata={
            "provider": payload.provider,
            "provider_status": payload.provider_status,
            "destructive_writeback": False,
        },
    )
    session.commit()
    return _record(row)


def list_calendar_event_candidates(
    session: Session,
    *,
    context: SessionContext,
    provider: str | None = None,
    matter_id: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> CalendarProviderEventCandidateListResponse:
    filters = [CalendarEventCandidate.company_id == context.company.id]
    if provider:
        filters.append(CalendarEventCandidate.provider == provider)
    if matter_id:
        filters.append(
            (CalendarEventCandidate.linked_matter_id == matter_id)
            | (CalendarEventCandidate.suggested_matter_id == matter_id)
        )
    if status_filter:
        filters.append(CalendarEventCandidate.status == status_filter)
    rows = list(
        session.scalars(
            select(CalendarEventCandidate)
            .where(*filters)
            .order_by(CalendarEventCandidate.updated_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    )
    visible: list[CalendarEventCandidate] = []
    for row in rows:
        target_matter_id = row.linked_matter_id or row.suggested_matter_id
        if target_matter_id is None:
            visible.append(row)
            continue
        matter = session.get(Matter, target_matter_id)
        if matter is None:
            continue
        try:
            assert_access(session, context=context, matter=matter)
        except HTTPException:
            continue
        visible.append(row)
    return CalendarProviderEventCandidateListResponse(
        candidates=[_record(row) for row in visible],
        pending_count=sum(1 for row in visible if row.status == CalendarEventCandidateStatus.NEW),
        conflict_count=sum(
            1 for row in visible if row.status == CalendarEventCandidateStatus.CONFLICT
        ),
    )


def review_calendar_event_candidate(
    session: Session,
    *,
    context: SessionContext,
    candidate_id: str,
    payload: CalendarProviderEventCandidateReviewRequest,
) -> CalendarProviderEventCandidateReviewResponse:
    row = session.scalar(
        select(CalendarEventCandidate).where(
            CalendarEventCandidate.id == candidate_id,
            CalendarEventCandidate.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar candidate not found.")
    if payload.action in {"reject", "ignore"}:
        row.status = (
            CalendarEventCandidateStatus.REJECTED
            if payload.action == "reject"
            else CalendarEventCandidateStatus.IGNORED
        )
        row.reviewed_by_membership_id = context.membership.id
        row.reviewed_at = _now()
        row.sync_history_json = [
            *(row.sync_history_json or []),
            {"at": _now().isoformat(), "event": f"candidate_{payload.action}ed"},
        ]
        session.add(row)
        record_from_context(
            session,
            context,
            action=f"calendar.provider_event_candidate.{payload.action}",
            target_type="calendar_event_candidate",
            target_id=row.id,
            matter_id=row.linked_matter_id or row.suggested_matter_id,
            metadata={"provider": row.provider},
        )
        session.commit()
        return CalendarProviderEventCandidateReviewResponse(candidate=_record(row))
    if payload.action != "accept":
        raise HTTPException(status_code=400, detail="Unsupported calendar candidate action.")
    matter = _matter_for_candidate(
        session,
        context=context,
        matter_id=payload.matter_id or row.linked_matter_id or row.suggested_matter_id,
    )
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="accept a calendar candidate",
    )
    if matter.next_hearing_manual_lock and not payload.force_overwrite_locked:
        row.status = CalendarEventCandidateStatus.CONFLICT
        row.conflict_reason = "manual_locked_next_hearing_requires_explicit_override"
        row.linked_matter_id = matter.id
        row.sync_history_json = [
            *(row.sync_history_json or []),
            {"at": _now().isoformat(), "event": "manual_lock_conflict"},
        ]
        session.add(row)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Matter next hearing is manually locked; explicit override is required.",
        )
    hearing = MatterHearing(
        company_id=matter.company_id,
        matter_id=matter.id,
        hearing_on=row.starts_at.date(),
        forum_name=row.location or matter.court_name or "Provider calendar",
        judge_name=matter.judge_name,
        purpose=row.title[:255],
        status=MatterHearingStatus.SCHEDULED,
    )
    session.add(hearing)
    session.flush()
    matter.next_hearing_on = row.starts_at.date()
    matter.next_hearing_source = MatterNextHearingSource.MANUAL
    matter.next_hearing_source_ref_type = "calendar_event_candidate"
    matter.next_hearing_source_ref_id = row.id
    matter.next_hearing_updated_by_membership_id = context.membership.id
    matter.next_hearing_updated_at = _now()
    if payload.force_overwrite_locked:
        matter.next_hearing_manual_lock = True
    row.status = CalendarEventCandidateStatus.ACCEPTED
    row.linked_matter_id = matter.id
    row.linked_hearing_id = hearing.id
    row.reviewed_by_membership_id = context.membership.id
    row.reviewed_at = _now()
    row.conflict_reason = None
    row.sync_history_json = [
        *(row.sync_history_json or []),
        {
            "at": _now().isoformat(),
            "event": "candidate_accepted",
            "hearing_id": hearing.id,
        },
    ]
    session.add_all([row, matter])
    record_from_context(
        session,
        context,
        action="calendar.provider_event_candidate.accepted",
        target_type="calendar_event_candidate",
        target_id=row.id,
        matter_id=matter.id,
        metadata={
            "provider": row.provider,
            "hearing_id": hearing.id,
            "force_overwrite_locked": payload.force_overwrite_locked,
            "provider_deletion_deleted_caseops_hearing": False,
        },
    )
    session.commit()
    return CalendarProviderEventCandidateReviewResponse(
        candidate=_record(row),
        hearing_id=hearing.id,
    )
