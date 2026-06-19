"""Matter timeline builder.

LW-S2 keeps the timeline as a composed read model over existing source
tables. The service owns ordering and normalization only; persistence
stays on hearings, court orders, attachments, deadlines, tasks, and
activity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterCourtOrder,
    MatterDeadline,
    MatterHearing,
    MatterProceedingReviewStatus,
    MatterProceedingSignal,
    MatterProceedingSignalType,
    MatterTask,
)
from caseops_api.schemas.matters import (
    MatterTimelineItemRecord,
    MatterTimelineLinkRecord,
    MatterTimelineResponse,
)
from caseops_api.services.matter_access import assert_access
from caseops_api.services.session_context import SessionContext

TimelineEventKind = Literal[
    "hearing",
    "court_order",
    "document",
    "deadline",
    "task",
    "activity",
]
TimelineSort = Literal["asc", "desc"]

TIMELINE_MAX_PAGE_SIZE = 500
TIMELINE_MAX_SOURCE_EVENTS = 500
ALL_TIMELINE_TYPES: set[str] = {
    "hearing",
    "court_order",
    "document",
    "deadline",
    "task",
    "activity",
}


@dataclass(frozen=True)
class TimelineEvent:
    """One normalized event on a matter's legal timeline."""

    event_date: date
    kind: TimelineEventKind
    title: str
    summary: str
    status: str | None = None
    source_ref_id: str | None = None
    source_type: str | None = None
    event_time: datetime | None = None
    badges: list[str] = field(default_factory=list)
    order_kind: str | None = None
    is_interim_order: bool = False
    stay_status: str | None = None
    stay_effective_until: date | None = None
    linked_attachment_id: str | None = None
    extra: dict[str, str | bool | int | None] = field(default_factory=dict)


@dataclass(frozen=True)
class MatterTimeline:
    matter_id: str
    generated_at: datetime
    events: list[TimelineEvent]
    sort: TimelineSort = "asc"


def parse_timeline_types(types: str | None) -> set[TimelineEventKind] | None:
    if not types:
        return None
    parsed = {item.strip() for item in types.split(",") if item.strip()}
    invalid = parsed - ALL_TIMELINE_TYPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported timeline type(s): {', '.join(sorted(invalid))}.",
        )
    return parsed or None  # type: ignore[return-value]


def _page_size(limit: int) -> int:
    return min(max(limit, 1), TIMELINE_MAX_PAGE_SIZE)


def _clamp_source_limit(source_limit: int | None) -> int:
    if source_limit is None:
        return TIMELINE_MAX_SOURCE_EVENTS
    return min(max(source_limit, 1), TIMELINE_MAX_SOURCE_EVENTS)


def _start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=UTC)


def timeline_response(
    timeline: MatterTimeline,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> MatterTimelineResponse:
    page_size = _page_size(limit)
    offset = _decode_offset_cursor(cursor)
    page = timeline.events[offset : offset + page_size]
    next_cursor = (
        str(offset + page_size)
        if offset + page_size < len(timeline.events)
        else None
    )
    return MatterTimelineResponse(
        matter_id=timeline.matter_id,
        sort=timeline.sort,
        items=[_event_to_record(timeline.matter_id, event) for event in page],
        next_cursor=next_cursor,
        generated_at=timeline.generated_at,
    )


def timeline_source_limit(*, limit: int = 100, cursor: str | None = None) -> int:
    page_size = _page_size(limit)
    offset = _decode_offset_cursor(cursor)
    return min(max(offset + page_size, page_size), TIMELINE_MAX_SOURCE_EVENTS)


def build_matter_timeline(
    *,
    session: Session,
    matter: Matter,
    sort: TimelineSort = "asc",
    from_date: date | None = None,
    to_date: date | None = None,
    event_types: set[TimelineEventKind] | None = None,
    include_activity: bool = False,
    source_limit: int | None = TIMELINE_MAX_SOURCE_EVENTS,
) -> MatterTimeline:
    """Pure builder. Callers supply the Matter after tenancy/access
    enforcement."""

    active_types = set(event_types) if event_types is not None else ALL_TIMELINE_TYPES
    per_source_limit = _clamp_source_limit(source_limit)
    events: list[TimelineEvent] = []
    if "hearing" in active_types:
        events.extend(
            _events_from_hearings(
                session=session,
                matter_id=matter.id,
                sort=sort,
                from_date=from_date,
                to_date=to_date,
                source_limit=per_source_limit,
            )
        )
    if "court_order" in active_types:
        events.extend(
            _events_from_court_orders(
                session=session,
                matter_id=matter.id,
                sort=sort,
                from_date=from_date,
                to_date=to_date,
                source_limit=per_source_limit,
            )
        )
    if "document" in active_types:
        events.extend(
            _events_from_attachments(
                session=session,
                matter_id=matter.id,
                sort=sort,
                from_date=from_date,
                to_date=to_date,
                source_limit=per_source_limit,
            )
        )
    if "deadline" in active_types:
        events.extend(
            _events_from_deadlines(
                session=session,
                matter_id=matter.id,
                sort=sort,
                from_date=from_date,
                to_date=to_date,
                source_limit=per_source_limit,
            )
        )
    if "task" in active_types:
        events.extend(
            _events_from_tasks(
                session=session,
                matter_id=matter.id,
                sort=sort,
                from_date=from_date,
                to_date=to_date,
                source_limit=per_source_limit,
            )
        )
    if include_activity and "activity" in active_types:
        events.extend(
            _events_from_activity(
                session=session,
                matter_id=matter.id,
                sort=sort,
                from_date=from_date,
                to_date=to_date,
                source_limit=per_source_limit,
            )
        )

    if from_date is not None:
        events = [event for event in events if event.event_date >= from_date]
    if to_date is not None:
        events = [event for event in events if event.event_date <= to_date]

    kind_rank: dict[TimelineEventKind, int] = {
        "hearing": 0,
        "court_order": 1,
        "document": 2,
        "deadline": 3,
        "task": 4,
        "activity": 5,
    }
    events.sort(
        key=lambda e: (
            kind_rank[e.kind],
            e.event_time or datetime.combine(e.event_date, time.min, tzinfo=UTC),
            e.title.lower(),
            e.source_type or e.kind,
            e.source_ref_id or "",
        )
    )
    events.sort(key=lambda e: e.event_date, reverse=sort == "desc")
    return MatterTimeline(
        matter_id=matter.id,
        generated_at=datetime.now(UTC),
        events=events,
        sort=sort,
    )


def build_matter_timeline_by_id(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    sort: TimelineSort = "asc",
    from_date: date | None = None,
    to_date: date | None = None,
    event_types: set[TimelineEventKind] | None = None,
    source_limit: int | None = TIMELINE_MAX_SOURCE_EVENTS,
) -> MatterTimeline:
    """Tenant- and matter-access-safe entry point for routes."""
    matter = session.scalar(
        select(Matter)
        .where(Matter.id == matter_id)
        .where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return build_matter_timeline(
        session=session,
        matter=matter,
        sort=sort,
        from_date=from_date,
        to_date=to_date,
        event_types=event_types,
        include_activity=True,
        source_limit=source_limit,
    )


def _events_from_hearings(
    *,
    session: Session,
    matter_id: str,
    sort: TimelineSort,
    from_date: date | None,
    to_date: date | None,
    source_limit: int,
) -> list[TimelineEvent]:
    stmt = select(MatterHearing).where(MatterHearing.matter_id == matter_id)
    if from_date is not None:
        stmt = stmt.where(MatterHearing.hearing_on >= from_date)
    if to_date is not None:
        stmt = stmt.where(MatterHearing.hearing_on <= to_date)
    date_order = (
        MatterHearing.hearing_on.desc()
        if sort == "desc"
        else MatterHearing.hearing_on.asc()
    )
    stmt = stmt.order_by(
        date_order,
        MatterHearing.purpose.asc(),
        MatterHearing.id.asc(),
    ).limit(source_limit)
    rows = list(
        session.scalars(stmt)
    )
    out: list[TimelineEvent] = []
    today = date.today()
    for row in rows:
        pieces = [row.forum_name]
        if row.judge_name:
            pieces.append(f"before {row.judge_name}")
        summary = ". ".join(pieces)
        if row.outcome_note:
            summary = f"{summary} - {row.outcome_note}"
        badges = []
        if row.status == "completed":
            badges.append("completed")
        elif row.hearing_on >= today:
            badges.append("upcoming")
        else:
            badges.append("past")
        out.append(
            TimelineEvent(
                event_date=row.hearing_on,
                kind="hearing",
                title=row.purpose or "Hearing",
                summary=summary,
                status=row.status,
                source_ref_id=row.id,
                source_type="matter_hearing",
                badges=badges,
                extra={
                    "forum": row.forum_name,
                    "judge_name": row.judge_name,
                },
            )
        )
    return out


def _events_from_court_orders(
    *,
    session: Session,
    matter_id: str,
    sort: TimelineSort,
    from_date: date | None,
    to_date: date | None,
    source_limit: int,
) -> list[TimelineEvent]:
    stmt = select(MatterCourtOrder).where(MatterCourtOrder.matter_id == matter_id)
    if from_date is not None:
        stmt = stmt.where(MatterCourtOrder.order_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(MatterCourtOrder.order_date <= to_date)
    date_order = (
        MatterCourtOrder.order_date.desc()
        if sort == "desc"
        else MatterCourtOrder.order_date.asc()
    )
    stmt = stmt.order_by(
        date_order,
        MatterCourtOrder.synced_at.asc(),
        MatterCourtOrder.title.asc(),
        MatterCourtOrder.id.asc(),
    ).limit(source_limit)
    rows = list(
        session.scalars(stmt)
    )
    signals_by_order: dict[str, list[MatterProceedingSignal]] = {}
    order_ids = [row.id for row in rows]
    if order_ids:
        for signal in session.scalars(
            select(MatterProceedingSignal)
            .where(MatterProceedingSignal.court_order_id.in_(order_ids))
            .order_by(MatterProceedingSignal.created_at.asc())
        ):
            signals_by_order.setdefault(signal.court_order_id, []).append(signal)
    out: list[TimelineEvent] = []
    for row in rows:
        order_kind = row.order_kind or "daily_order"
        stay_status = row.stay_status or "none"
        is_interim = bool(row.is_interim_order) or order_kind == "interim_order"
        badges: list[str] = []
        if is_interim:
            badges.append("interim")
        if stay_status != "none":
            badges.append(f"stay:{stay_status}")
        proceeding_signals = signals_by_order.get(row.id, [])
        pending_count = sum(
            1
            for signal in proceeding_signals
            if signal.due_on is not None
            and signal.review_status
            in {
                MatterProceedingReviewStatus.REVIEW_REQUIRED,
                MatterProceedingReviewStatus.AUTO_PROMOTED,
            }
        )
        next_hearing_on = next(
            (
                signal.hearing_on
                for signal in proceeding_signals
                if signal.signal_type == MatterProceedingSignalType.NEXT_HEARING
                and signal.hearing_on is not None
            ),
            None,
        )
        if pending_count:
            badges.append(f"compliance:{pending_count}")
        if next_hearing_on is not None:
            badges.append("next hearing")
        judge_names = row.judge_names_json if isinstance(row.judge_names_json, list) else []
        out.append(
            TimelineEvent(
                event_date=row.order_date,
                kind="court_order",
                title=row.title,
                summary=row.summary,
                status=stay_status if stay_status != "none" else None,
                source_ref_id=row.id,
                source_type="matter_court_order",
                badges=badges,
                order_kind=order_kind,
                is_interim_order=is_interim,
                stay_status=stay_status,
                stay_effective_until=row.stay_effective_until,
                linked_attachment_id=row.order_attachment_id,
                event_time=row.synced_at,
                extra={
                    "source": row.source,
                    "bench_name": row.bench_name,
                    "judge_names": ", ".join(str(name) for name in judge_names) or None,
                    "proceeding_signal_count": len(proceeding_signals),
                    "pending_compliance_count": pending_count,
                    "next_hearing_on": next_hearing_on.isoformat()
                    if next_hearing_on
                    else None,
                },
            )
        )
    return out


def _events_from_attachments(
    *,
    session: Session,
    matter_id: str,
    sort: TimelineSort,
    from_date: date | None,
    to_date: date | None,
    source_limit: int,
) -> list[TimelineEvent]:
    stmt = select(MatterAttachment).where(MatterAttachment.matter_id == matter_id)
    if from_date is not None:
        stmt = stmt.where(MatterAttachment.created_at >= _start_of_day(from_date))
    if to_date is not None:
        stmt = stmt.where(MatterAttachment.created_at <= _end_of_day(to_date))
    date_order = (
        MatterAttachment.created_at.desc()
        if sort == "desc"
        else MatterAttachment.created_at.asc()
    )
    stmt = stmt.order_by(
        date_order,
        MatterAttachment.original_filename.asc(),
        MatterAttachment.id.asc(),
    ).limit(source_limit)
    rows = list(
        session.scalars(stmt)
    )
    out: list[TimelineEvent] = []
    for row in rows:
        summary = row.content_type or "Matter document"
        lifecycle_stage = row.lifecycle_stage or "unclassified"
        out.append(
            TimelineEvent(
                event_date=row.created_at.date(),
                event_time=row.created_at,
                kind="document",
                title=row.original_filename,
                summary=summary,
                status=row.processing_status,
                source_ref_id=row.id,
                source_type="matter_attachment",
                badges=[row.processing_status, lifecycle_stage],
                linked_attachment_id=row.id,
                extra={
                    "content_type": row.content_type,
                    "size_bytes": row.size_bytes,
                    "document_type": row.document_type,
                    "lifecycle_stage": row.lifecycle_stage,
                    "document_date": row.document_date.isoformat()
                    if row.document_date
                    else None,
                    "sequence_index": row.sequence_index,
                    "linked_court_order_id": row.linked_court_order_id,
                },
            )
        )
    return out


def _events_from_deadlines(
    *,
    session: Session,
    matter_id: str,
    sort: TimelineSort,
    from_date: date | None,
    to_date: date | None,
    source_limit: int,
) -> list[TimelineEvent]:
    stmt = select(MatterDeadline).where(MatterDeadline.matter_id == matter_id)
    if from_date is not None:
        stmt = stmt.where(MatterDeadline.due_on >= from_date)
    if to_date is not None:
        stmt = stmt.where(MatterDeadline.due_on <= to_date)
    date_order = (
        MatterDeadline.due_on.desc()
        if sort == "desc"
        else MatterDeadline.due_on.asc()
    )
    stmt = stmt.order_by(
        date_order,
        MatterDeadline.title.asc(),
        MatterDeadline.id.asc(),
    ).limit(source_limit)
    rows = list(
        session.scalars(stmt)
    )
    out: list[TimelineEvent] = []
    for row in rows:
        summary = row.notes or f"{row.kind} deadline"
        out.append(
            TimelineEvent(
                event_date=row.due_on,
                kind="deadline",
                title=row.title,
                summary=summary,
                status=row.status,
                source_ref_id=row.id,
                source_type="matter_deadline",
                badges=[row.status],
                extra={"kind": row.kind, "source": row.source},
            )
        )
    return out


def _events_from_tasks(
    *,
    session: Session,
    matter_id: str,
    sort: TimelineSort,
    from_date: date | None,
    to_date: date | None,
    source_limit: int,
) -> list[TimelineEvent]:
    task_event_date = func.coalesce(MatterTask.due_on, func.date(MatterTask.created_at))
    stmt = select(MatterTask).where(MatterTask.matter_id == matter_id)
    if from_date is not None:
        stmt = stmt.where(
            or_(
                MatterTask.due_on >= from_date,
                and_(
                    MatterTask.due_on.is_(None),
                    MatterTask.created_at >= _start_of_day(from_date),
                ),
            )
        )
    if to_date is not None:
        stmt = stmt.where(
            or_(
                MatterTask.due_on <= to_date,
                and_(
                    MatterTask.due_on.is_(None),
                    MatterTask.created_at <= _end_of_day(to_date),
                ),
            )
        )
    date_order = task_event_date.desc() if sort == "desc" else task_event_date.asc()
    stmt = stmt.order_by(
        date_order,
        MatterTask.created_at.asc(),
        MatterTask.title.asc(),
        MatterTask.id.asc(),
    ).limit(source_limit)
    rows = list(
        session.scalars(stmt)
    )
    out: list[TimelineEvent] = []
    for row in rows:
        event_date = row.due_on or row.created_at.date()
        out.append(
            TimelineEvent(
                event_date=event_date,
                event_time=row.created_at,
                kind="task",
                title=row.title,
                summary=row.description or f"{row.priority} priority task",
                status=row.status,
                source_ref_id=row.id,
                source_type="matter_task",
                badges=[row.status, row.priority],
                extra={
                    "priority": row.priority,
                    "has_due_date": row.due_on is not None,
                },
            )
        )
    return out


def _events_from_activity(
    *,
    session: Session,
    matter_id: str,
    sort: TimelineSort,
    from_date: date | None,
    to_date: date | None,
    source_limit: int,
) -> list[TimelineEvent]:
    stmt = select(MatterActivity).where(MatterActivity.matter_id == matter_id)
    if from_date is not None:
        stmt = stmt.where(MatterActivity.created_at >= _start_of_day(from_date))
    if to_date is not None:
        stmt = stmt.where(MatterActivity.created_at <= _end_of_day(to_date))
    date_order = (
        MatterActivity.created_at.desc()
        if sort == "desc"
        else MatterActivity.created_at.asc()
    )
    stmt = stmt.order_by(
        date_order,
        MatterActivity.title.asc(),
        MatterActivity.id.asc(),
    ).limit(source_limit)
    rows = list(
        session.scalars(stmt)
    )
    out: list[TimelineEvent] = []
    for row in rows:
        out.append(
            TimelineEvent(
                event_date=row.created_at.date(),
                event_time=row.created_at,
                kind="activity",
                title=row.title,
                summary=row.detail or row.event_type,
                status=row.event_type,
                source_ref_id=row.id,
                source_type="matter_activity",
                badges=[row.event_type],
                extra={
                    "event_type": row.event_type,
                    "actor_membership_id": row.actor_membership_id,
                },
            )
        )
    return out


def _decode_offset_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timeline cursor.",
        ) from exc
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timeline cursor.",
        )
    return offset


def _event_to_record(matter_id: str, event: TimelineEvent) -> MatterTimelineItemRecord:
    document_href = (
        f"/app/matters/{matter_id}/documents/{event.linked_attachment_id}/view"
        if event.linked_attachment_id
        else None
    )
    source_id = event.source_ref_id
    return MatterTimelineItemRecord(
        id=f"{event.kind}:{source_id or event.event_date.isoformat()}",
        event_type=event.kind,
        event_date=event.event_date,
        event_time=event.event_time,
        title=event.title,
        status=event.status,
        summary=event.summary,
        source_type=event.source_type or event.kind,
        source_id=source_id,
        badges=event.badges,
        links=MatterTimelineLinkRecord(
            matter=f"/app/matters/{matter_id}",
            document=document_href,
        ),
        order_kind=event.order_kind,
        is_interim_order=event.is_interim_order,
        stay_status=event.stay_status,
        stay_effective_until=event.stay_effective_until,
        linked_attachment_id=event.linked_attachment_id,
        metadata=event.extra,
    )


__all__ = [
    "ALL_TIMELINE_TYPES",
    "MatterTimeline",
    "TimelineEvent",
    "TimelineEventKind",
    "build_matter_timeline",
    "build_matter_timeline_by_id",
    "parse_timeline_types",
    "timeline_response",
    "timeline_source_limit",
]
