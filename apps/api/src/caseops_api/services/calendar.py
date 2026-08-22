"""Phase B / J08 / M08 — unified calendar event aggregator.

One read across hearings, tasks, and the generic deadlines table to
produce a single typed list the UI can grid-render. Tenant-scoped on
every join via ``Matter.company_id``; a leaked event between
companies is the worst possible outcome here, so the join is the
first thing every query enforces.

Why a service rather than three route handlers:

- The UI's calendar page makes ONE network request, not three. That
  keeps the latency budget tight (~50 ms total across DB joins) and
  removes any client-side merge logic that could drop or double-count
  rows.
- A future ical export (FT-043 in slice 2) reuses the same service
  function — keeps the export deterministic vs. whatever the UI
  happened to render at the time.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDeadline,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
    MatterHearingStatus,
    MatterTask,
    MatterTaskStatus,
)
from caseops_api.schemas.calendar import (
    CalendarEventKind,
    CalendarEventRecord,
)
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.session_context import SessionContext


def aggregate_calendar_events(
    session: Session,
    *,
    context: SessionContext,
    range_from: date,
    range_to: date,
    kinds: Iterable[CalendarEventKind] | None = None,
) -> list[CalendarEventRecord]:
    """Merge hearings + tasks + deadlines for the caller's company
    into a single date-sorted list.

    The range is inclusive on both ends — ``range_from <= due_on <=
    range_to`` — to match the natural "show me Monday through Friday"
    user intent.
    """
    if range_from > range_to:
        return []
    selected_kinds = set(kinds) if kinds else {"hearing", "task", "deadline"}
    events: list[CalendarEventRecord] = []

    if "hearing" in selected_kinds:
        events.extend(_collect_hearings(session, context, range_from, range_to))
    if "task" in selected_kinds:
        events.extend(_collect_tasks(session, context, range_from, range_to))
    if "deadline" in selected_kinds:
        events.extend(_collect_deadlines(session, context, range_from, range_to))

    # Stable sort: date first, then kind to keep multiple events on
    # the same day grouped predictably (hearings render above tasks
    # render above deadlines — gives the lawyer a glanceable order).
    _kind_order = {"hearing": 0, "task": 1, "deadline": 2}
    events.sort(key=lambda e: (e.occurs_on, _kind_order.get(e.kind, 99), e.title))
    return events


def _collect_hearings(
    session: Session,
    context: SessionContext,
    range_from: date,
    range_to: date,
) -> list[CalendarEventRecord]:
    rows = session.execute(
        select(MatterHearing, Matter)
        .join(Matter, Matter.id == MatterHearing.matter_id)
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            MatterHearing.hearing_on >= range_from,
            MatterHearing.hearing_on <= range_to,
            MatterHearing.status.in_(
                (MatterHearingStatus.SCHEDULED, MatterHearingStatus.ADJOURNED)
            ),
        )
    ).all()
    out: list[CalendarEventRecord] = []
    for hearing, matter in rows:
        # The hearing display title is the purpose if set, else "Hearing"
        # — keeps the calendar grid readable at small sizes.
        display_title = (hearing.purpose or "Hearing").strip() or "Hearing"
        # detail = forum + judge so the lawyer can scan without opening.
        detail_parts = [hearing.forum_name]
        if hearing.judge_name:
            detail_parts.append(hearing.judge_name)
        out.append(
            CalendarEventRecord(
                id=f"hearing:{hearing.id}",
                kind="hearing",
                display_type="hearing",
                occurs_on=hearing.hearing_on,
                title=display_title[:400],
                matter_id=matter.id,
                matter_title=matter.title,
                matter_code=matter.matter_code,
                status=hearing.status,
                detail=" · ".join(p for p in detail_parts if p) or None,
            )
        )
    return out


def _collect_tasks(
    session: Session,
    context: SessionContext,
    range_from: date,
    range_to: date,
) -> list[CalendarEventRecord]:
    rows = session.execute(
        select(MatterTask, Matter)
        .join(Matter, Matter.id == MatterTask.matter_id)
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            MatterTask.status.notin_(
                (MatterTaskStatus.COMPLETED, MatterTaskStatus.CANCELLED)
            ),
            MatterTask.due_on.is_not(None),
            MatterTask.due_on >= range_from,
            MatterTask.due_on <= range_to,
        )
    ).all()
    out: list[CalendarEventRecord] = []
    for task, matter in rows:
        assert task.due_on is not None  # narrowed by the WHERE clause
        out.append(
            CalendarEventRecord(
                id=f"task:{task.id}",
                kind="task",
                display_type="task_date",
                occurs_on=task.due_on,
                title=task.title[:400],
                matter_id=matter.id,
                matter_title=matter.title,
                matter_code=matter.matter_code,
                status=task.status,
                detail=task.priority or None,
            )
        )
    return out


def _collect_deadlines(
    session: Session,
    context: SessionContext,
    range_from: date,
    range_to: date,
) -> list[CalendarEventRecord]:
    rows = session.execute(
        select(MatterDeadline, Matter, IpDeadline.docket_id)
        .join(Matter, Matter.id == MatterDeadline.matter_id)
        .outerjoin(
            IpDeadline,
            and_(
                IpDeadline.id == MatterDeadline.source_ref_id,
                IpDeadline.company_id == MatterDeadline.company_id,
                MatterDeadline.source_ref_type.in_(
                    ("ip_deadline", "ip_deadline_internal_target")
                ),
            ),
        )
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            MatterDeadline.status.notin_(
                (MatterDeadlineStatus.DONE, MatterDeadlineStatus.CANCELLED)
            ),
            MatterDeadline.due_on >= range_from,
            MatterDeadline.due_on <= range_to,
        )
    ).all()
    out: list[CalendarEventRecord] = []
    for deadline, matter, ip_docket_id in rows:
        # Deadlines carry source + kind metadata that's useful in the
        # detail line ("draft · filing", "contract · renewal").
        detail_parts = [p for p in (deadline.source, deadline.kind) if p]
        out.append(
            CalendarEventRecord(
                id=f"deadline:{deadline.id}",
                kind="deadline",
                display_type=_deadline_display_type(deadline.kind),
                occurs_on=deadline.due_on,
                title=deadline.title[:400],
                matter_id=matter.id,
                matter_title=matter.title,
                matter_code=matter.matter_code,
                status=deadline.status,
                ip_docket_id=ip_docket_id,
                detail=" · ".join(detail_parts) or None,
            )
        )
    return out


def _deadline_display_type(kind: str) -> str:
    """Map legacy deadline kinds to stable user-facing calendar semantics."""

    normalized = kind.strip().lower()
    if normalized == "internal_target":
        return "internal_target"
    if normalized in {"renewal", "renewal_due"}:
        return "renewal"
    if normalized in {"client_instruction", "client_instruction_date"}:
        return "client_instruction"
    if normalized == "reminder":
        return "reminder"
    if normalized in {
        "legal_deadline",
        "filing",
        "filing_deadline",
        "filing_due",
        "reply_due",
    }:
        return "filing_deadline"
    return "deadline"


def render_events_as_ical(
    events: list[CalendarEventRecord],
    *,
    calendar_name: str = "CaseOps",
) -> str:
    """Serialise ``CalendarEventRecord`` rows as an RFC 5545 VCALENDAR
    stream for authenticated browser download/import.

    All events are date-granular — VALUE=DATE with DTSTART and
    DTEND on consecutive days. RFC 5545 line folding at 75 octets is
    omitted because every major consumer (Google, Outlook, Apple)
    tolerates the longer lines and our summaries are <200 chars
    anyway.

    No external dependency — the vcal grammar is simple enough that
    a 40-line hand-roll is clearer than pulling in a new package
    (and keeps the Anthropic-friendly dep footprint tight).
    """
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CaseOps//Calendar//EN",
        f"X-WR-CALNAME:{_ical_escape(calendar_name)}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        start = event.occurs_on.strftime("%Y%m%d")
        # Non-floating all-day event — DTEND is the day after DTSTART
        # per iCal convention so the slot fills a single calendar cell.
        from datetime import timedelta as _td

        end = (event.occurs_on + _td(days=1)).strftime("%Y%m%d")
        description_parts = [
            f"Matter: {event.matter_code} · {event.matter_title}",
        ]
        if event.detail:
            description_parts.append(event.detail)
        if event.status:
            description_parts.append(f"Status: {event.status}")
        description = "\\n".join(_ical_escape(p) for p in description_parts)
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event.id}@caseops.ai",
            f"SUMMARY:{_ical_escape(f'[{event.kind.upper()}] {event.title}')}",
            f"DTSTART;VALUE=DATE:{start}",
            f"DTEND;VALUE=DATE:{end}",
            f"DESCRIPTION:{description}",
            f"CATEGORIES:{event.kind.upper()}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    # RFC 5545 requires CRLF line breaks.
    return "\r\n".join(lines) + "\r\n"


def _ical_escape(text: str) -> str:
    """Escape the four characters RFC 5545 mandates inside a TEXT
    property value: backslash, comma, semicolon, newline."""
    return (
        text.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


__all__ = ["aggregate_calendar_events", "render_events_as_ical"]
