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

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Matter,
    MatterDeadline,
    MatterHearing,
    MatterTask,
)
from caseops_api.schemas.calendar import (
    CalendarEventKind,
    CalendarEventRecord,
)
from caseops_api.services.identity import SessionContext


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
    company_id = context.company.id
    events: list[CalendarEventRecord] = []

    if "hearing" in selected_kinds:
        events.extend(_collect_hearings(session, company_id, range_from, range_to))
    if "task" in selected_kinds:
        events.extend(_collect_tasks(session, company_id, range_from, range_to))
    if "deadline" in selected_kinds:
        events.extend(_collect_deadlines(session, company_id, range_from, range_to))

    # Stable sort: date first, then kind to keep multiple events on
    # the same day grouped predictably (hearings render above tasks
    # render above deadlines — gives the lawyer a glanceable order).
    _kind_order = {"hearing": 0, "task": 1, "deadline": 2}
    events.sort(key=lambda e: (e.occurs_on, _kind_order.get(e.kind, 99), e.title))
    return events


def _collect_hearings(
    session: Session,
    company_id: str,
    range_from: date,
    range_to: date,
) -> list[CalendarEventRecord]:
    rows = session.execute(
        select(MatterHearing, Matter)
        .join(Matter, Matter.id == MatterHearing.matter_id)
        .where(
            Matter.company_id == company_id,
            MatterHearing.hearing_on >= range_from,
            MatterHearing.hearing_on <= range_to,
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
    company_id: str,
    range_from: date,
    range_to: date,
) -> list[CalendarEventRecord]:
    rows = session.execute(
        select(MatterTask, Matter)
        .join(Matter, Matter.id == MatterTask.matter_id)
        .where(
            Matter.company_id == company_id,
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
    company_id: str,
    range_from: date,
    range_to: date,
) -> list[CalendarEventRecord]:
    rows = session.execute(
        select(MatterDeadline, Matter)
        .join(Matter, Matter.id == MatterDeadline.matter_id)
        .where(
            Matter.company_id == company_id,
            MatterDeadline.due_on >= range_from,
            MatterDeadline.due_on <= range_to,
        )
    ).all()
    out: list[CalendarEventRecord] = []
    for deadline, matter in rows:
        # Deadlines carry source + kind metadata that's useful in the
        # detail line ("draft · filing", "contract · renewal").
        detail_parts = [p for p in (deadline.source, deadline.kind) if p]
        out.append(
            CalendarEventRecord(
                id=f"deadline:{deadline.id}",
                kind="deadline",
                occurs_on=deadline.due_on,
                title=deadline.title[:400],
                matter_id=matter.id,
                matter_title=matter.title,
                matter_code=matter.matter_code,
                status=deadline.status,
                detail=" · ".join(detail_parts) or None,
            )
        )
    return out


__all__ = ["aggregate_calendar_events"]
