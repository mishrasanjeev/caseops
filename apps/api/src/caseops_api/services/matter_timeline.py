"""Sprint Q8 — matter timeline builder.

A matter's timeline is the chronological merge of three event sources:

- ``MatterHearing`` — past + future listings, with status + outcome note.
- ``MatterDeadline`` — generic deadlines (hearings, drafts, contracts,
  follow-ups) all written to one table.
- ``MatterCourtOrder`` — court-synced orders.

The timeline powers three surfaces:

1. The ``timeline`` section of ``MatterExecutiveSummary`` (Q5).
2. The body of the exported summary PDF / DOCX (Q7).
3. A future "Events" tile on the matter cockpit.

This module owns the merge + ordering only. No LLM work, no side
effects — a pure function over session + matter_id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Matter,
    MatterCourtOrder,
    MatterDeadline,
    MatterHearing,
)
from caseops_api.services.identity import SessionContext

TimelineEventKind = Literal["hearing", "deadline", "court_order"]


@dataclass(frozen=True)
class TimelineEvent:
    """One chronologically-placed event on a matter's timeline.

    ``event_date`` is the date we use for sorting. For hearings it is
    the listing date; for deadlines the due date; for court orders the
    order date. ``title`` + ``summary`` are presentation-ready strings.
    """

    event_date: date
    kind: TimelineEventKind
    title: str
    summary: str
    status: str | None = None
    source_ref_id: str | None = None
    extra: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class MatterTimeline:
    matter_id: str
    generated_at: datetime
    events: list[TimelineEvent]


def build_matter_timeline(
    *, session: Session, matter: Matter,
) -> MatterTimeline:
    """Pure builder. Callers supply the Matter so tenancy is already
    enforced at the edge."""

    events: list[TimelineEvent] = []
    events.extend(_events_from_hearings(session=session, matter_id=matter.id))
    events.extend(_events_from_deadlines(session=session, matter_id=matter.id))
    events.extend(_events_from_court_orders(session=session, matter_id=matter.id))

    # Stable sort by (date, kind). Kind tie-break keeps hearings above
    # deadlines above court orders on the same date — the order
    # lawyers expect when they scan a day in the cockpit.
    kind_rank: dict[TimelineEventKind, int] = {
        "hearing": 0,
        "court_order": 1,
        "deadline": 2,
    }
    events.sort(key=lambda e: (e.event_date, kind_rank[e.kind], e.title))
    return MatterTimeline(
        matter_id=matter.id,
        generated_at=datetime.now(),
        events=events,
    )


def build_matter_timeline_by_id(
    *, session: Session, context: SessionContext, matter_id: str,
) -> MatterTimeline:
    """Tenancy-safe entry point for the route layer."""
    matter = session.scalar(
        select(Matter)
        .where(Matter.id == matter_id)
        .where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )
    return build_matter_timeline(session=session, matter=matter)


def _events_from_hearings(
    *, session: Session, matter_id: str,
) -> list[TimelineEvent]:
    rows = list(
        session.scalars(
            select(MatterHearing).where(MatterHearing.matter_id == matter_id)
        )
    )
    out: list[TimelineEvent] = []
    for row in rows:
        pieces = [row.forum_name]
        if row.judge_name:
            pieces.append(f"before {row.judge_name}")
        summary = ". ".join(pieces)
        if row.outcome_note:
            summary = f"{summary} — {row.outcome_note}"
        out.append(TimelineEvent(
            event_date=row.hearing_on,
            kind="hearing",
            title=row.purpose or "Hearing",
            summary=summary,
            status=row.status,
            source_ref_id=row.id,
        ))
    return out


def _events_from_deadlines(
    *, session: Session, matter_id: str,
) -> list[TimelineEvent]:
    rows = list(
        session.scalars(
            select(MatterDeadline).where(MatterDeadline.matter_id == matter_id)
        )
    )
    out: list[TimelineEvent] = []
    for row in rows:
        summary = row.notes or f"{row.kind} deadline"
        out.append(TimelineEvent(
            event_date=row.due_on,
            kind="deadline",
            title=row.title,
            summary=summary,
            status=row.status,
            source_ref_id=row.id,
            extra={"kind": row.kind, "source": row.source},
        ))
    return out


def _events_from_court_orders(
    *, session: Session, matter_id: str,
) -> list[TimelineEvent]:
    rows = list(
        session.scalars(
            select(MatterCourtOrder).where(MatterCourtOrder.matter_id == matter_id)
        )
    )
    out: list[TimelineEvent] = []
    for row in rows:
        out.append(TimelineEvent(
            event_date=row.order_date,
            kind="court_order",
            title=row.title,
            summary=row.summary,
            status=None,
            source_ref_id=row.id,
            extra={"source": row.source},
        ))
    return out


__all__ = [
    "MatterTimeline",
    "TimelineEvent",
    "TimelineEventKind",
    "build_matter_timeline",
    "build_matter_timeline_by_id",
]
