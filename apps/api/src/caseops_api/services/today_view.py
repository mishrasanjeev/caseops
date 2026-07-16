"""PG-004 (2026-05-01) — Today cockpit aggregator.

Pulls everything a fee-earner needs to see when they open the app
in the morning into a single tenant-scoped, matter-access-respecting
payload. Replaces the old "open the matters list and remember what's
hot" workflow with a per-user prioritised feed.

Returns five streams keyed by urgency:

1. ``hearings_next_7d`` — `MatterHearing` rows with `hearing_on`
   between today and today + horizon_days, status SCHEDULED.
2. ``tasks_due_or_overdue`` — `MatterTask` rows with `due_on` ≤ today
   + horizon_days, status NOT in (completed, cancelled). Owner-scoped: returns
   tasks owned by the current user OR unassigned.
3. ``drafts_in_review`` — `Draft` rows with status IN_REVIEW across
   the tenant. Reviewer queue.
4. ``overdue_invoices`` — `MatterInvoice` rows with `due_on` < today
   AND status in (issued, partially_paid). The collections worry list.
5. ``deadlines_next_7d`` — `MatterDeadline` rows with `due_on` ≤
   today + horizon_days. Hard statutory dates separate from tasks.

All five share a common `MatterRef` (id + title + matter_code) so the
frontend can deeplink to the matter cockpit.

Isolation is enforced on every join by BOTH:
  1. tenant     — `Matter.company_id == context.company.id`
  2. matter-ACL — `visible_matters_filter(session, context=context)`,
     the same predicate `list_matters` uses, so restricted /
     team-scoped / ethical-walled matters the caller is not entitled
     to never surface in the Today feed or in next-action.
The function never reads a row outside the caller's tenant, and never
a matter the caller could not also see in the matters list.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Draft,
    DraftStatus,
    InvoiceStatus,
    Matter,
    MatterDeadline,
    MatterHearing,
    MatterHearingStatus,
    MatterInvoice,
    MatterTask,
    MatterTaskStatus,
)
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.session_context import SessionContext


@dataclass(frozen=True)
class MatterRef:
    id: str
    title: str
    matter_code: str


@dataclass(frozen=True)
class TodayHearing:
    id: str
    matter: MatterRef
    hearing_on: date
    forum_name: str
    judge_name: str | None
    purpose: str


@dataclass(frozen=True)
class TodayTask:
    id: str
    matter: MatterRef
    title: str
    due_on: date | None
    status: str
    priority: str
    overdue: bool


@dataclass(frozen=True)
class TodayDraftInReview:
    id: str
    matter: MatterRef
    title: str
    draft_type: str
    template_type: str | None
    updated_at_iso: str


@dataclass(frozen=True)
class TodayInvoice:
    id: str
    matter: MatterRef
    invoice_number: str | None
    total_amount_minor: int
    currency: str
    due_on: date
    days_overdue: int
    status: str


@dataclass(frozen=True)
class TodayDeadline:
    id: str
    matter: MatterRef
    title: str
    due_on: date
    severity: str
    days_until: int


# Per-stream row cap for GET /api/me/today. The Today feed is a
# triage glance, not a list view — a single user is never meant to
# action hundreds of items from one morning screen. Capping keeps the
# payload bounded; the matters / hearings / calendar list views remain
# the unbounded source of truth. next-action does NOT use this cap (it
# passes limit=None) so its single-most-urgent pick is never skewed by
# truncation. No prior local constant existed for this.
MAX_PER_STREAM = 100

_STREAM_KEYS: tuple[str, ...] = (
    "hearings_next_7d",
    "tasks_due_or_overdue",
    "drafts_in_review",
    "overdue_invoices",
    "deadlines_next_7d",
)


@dataclass(frozen=True)
class TodayView:
    today: date
    horizon_days: int
    hearings_next_7d: list[TodayHearing]
    tasks_due_or_overdue: list[TodayTask]
    drafts_in_review: list[TodayDraftInReview]
    overdue_invoices: list[TodayInvoice]
    deadlines_next_7d: list[TodayDeadline]
    # Additive bounding metadata (response-shape extension, not a
    # breaking change — the five arrays above are unchanged). Keyed by
    # the stream names in _STREAM_KEYS.
    #   stream_limits    — the per-stream cap that was applied
    #   stream_counts    — number of rows RETURNED (== len(array) ≤ cap;
    #                       intentionally not an unbounded total, which
    #                       would cost an extra COUNT per stream)
    #   stream_truncated — True iff more rows existed beyond the cap
    stream_limits: dict[str, int]
    stream_counts: dict[str, int]
    stream_truncated: dict[str, bool]


# ---------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------


def build_today_view(
    session: Session,
    *,
    context: SessionContext,
    horizon_days: int = 7,
    today: date | None = None,
) -> TodayView:
    """Aggregate the per-user Today feed. ``today`` is injectable for
    deterministic tests; defaults to ``date.today()``."""
    today = today or date.today()
    horizon_end = today + timedelta(days=max(0, horizon_days))
    # Read the module constant at call time so tests can monkeypatch it.
    cap = MAX_PER_STREAM
    # Over-fetch one row past the cap: if we get cap+1 back, the stream
    # is truncated. Cheaper than a separate COUNT(*) per stream.
    probe = cap + 1

    raw = {
        "hearings_next_7d": _hearings(
            session, context, today, horizon_end, limit=probe,
        ),
        "tasks_due_or_overdue": _tasks(
            session, context, today, horizon_end, limit=probe,
        ),
        "drafts_in_review": _drafts_in_review(session, context, limit=probe),
        "overdue_invoices": _overdue_invoices(
            session, context, today, limit=probe,
        ),
        "deadlines_next_7d": _deadlines(
            session, context, today, horizon_end, limit=probe,
        ),
    }

    bounded: dict[str, list] = {}
    stream_truncated: dict[str, bool] = {}
    stream_counts: dict[str, int] = {}
    stream_limits: dict[str, int] = {}
    for key in _STREAM_KEYS:
        rows = raw[key]
        truncated = len(rows) > cap
        kept = rows[:cap]
        bounded[key] = kept
        stream_truncated[key] = truncated
        stream_counts[key] = len(kept)
        stream_limits[key] = cap

    return TodayView(
        today=today,
        horizon_days=horizon_days,
        hearings_next_7d=bounded["hearings_next_7d"],
        tasks_due_or_overdue=bounded["tasks_due_or_overdue"],
        drafts_in_review=bounded["drafts_in_review"],
        overdue_invoices=bounded["overdue_invoices"],
        deadlines_next_7d=bounded["deadlines_next_7d"],
        stream_limits=stream_limits,
        stream_counts=stream_counts,
        stream_truncated=stream_truncated,
    )


# ---------------------------------------------------------------
# Per-stream queries. Each enforces BOTH:
#   1. tenant isolation  — Matter.company_id == context.company.id
#   2. matter-access ACL — visible_matters_filter(...) so restricted
#      / team-scoped / ethical-walled matters the caller is not
#      entitled to never surface in the Today feed or next-action.
# This is the SAME predicate list_matters uses, so the Today cockpit
# can never show a matter the matters list would hide.
# ---------------------------------------------------------------


def _matter_ref(matter: Matter) -> MatterRef:
    return MatterRef(id=matter.id, title=matter.title, matter_code=matter.matter_code)


def _hearings(
    session: Session,
    context: SessionContext,
    today: date,
    horizon_end: date,
    *,
    limit: int | None = None,
) -> list[TodayHearing]:
    stmt = (
        select(MatterHearing, Matter)
        .join(Matter, Matter.id == MatterHearing.matter_id)
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            MatterHearing.status == MatterHearingStatus.SCHEDULED,
            MatterHearing.hearing_on >= today,
            MatterHearing.hearing_on <= horizon_end,
        )
        .order_by(MatterHearing.hearing_on.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    return [
        TodayHearing(
            id=h.id,
            matter=_matter_ref(m),
            hearing_on=h.hearing_on,
            forum_name=h.forum_name,
            judge_name=h.judge_name,
            purpose=h.purpose,
        )
        for h, m in rows
    ]


def _tasks(
    session: Session,
    context: SessionContext,
    today: date,
    horizon_end: date,
    *,
    limit: int | None = None,
) -> list[TodayTask]:
    membership_id = context.membership.id
    stmt = (
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
            or_(
                # Owner-scoped: tasks I own OR unassigned tasks
                # (so a fresh tenant doesn't show 0 tasks).
                MatterTask.owner_membership_id == membership_id,
                MatterTask.owner_membership_id.is_(None),
            ),
            or_(
                MatterTask.due_on.is_(None),
                MatterTask.due_on <= horizon_end,
            ),
        )
        .order_by(
            # Priority sort: overdue first, then due-soon, then no-date.
            MatterTask.due_on.is_(None).asc(),
            MatterTask.due_on.asc(),
            MatterTask.created_at.asc(),
        )
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    return [
        TodayTask(
            id=t.id,
            matter=_matter_ref(m),
            title=t.title,
            due_on=t.due_on,
            status=t.status,
            priority=t.priority,
            overdue=bool(t.due_on and t.due_on < today),
        )
        for t, m in rows
    ]


def _drafts_in_review(
    session: Session,
    context: SessionContext,
    *,
    limit: int | None = None,
) -> list[TodayDraftInReview]:
    stmt = (
        select(Draft, Matter)
        .join(Matter, Matter.id == Draft.matter_id)
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            Draft.status == DraftStatus.IN_REVIEW,
        )
        .order_by(Draft.updated_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    return [
        TodayDraftInReview(
            id=d.id,
            matter=_matter_ref(m),
            title=d.title,
            draft_type=str(d.draft_type),
            template_type=d.template_type,
            updated_at_iso=d.updated_at.isoformat() if d.updated_at else "",
        )
        for d, m in rows
    ]


def _overdue_invoices(
    session: Session,
    context: SessionContext,
    today: date,
    *,
    limit: int | None = None,
) -> list[TodayInvoice]:
    stmt = (
        select(MatterInvoice, Matter)
        .join(Matter, Matter.id == MatterInvoice.matter_id)
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            MatterInvoice.due_on.is_not(None),
            MatterInvoice.due_on < today,
            MatterInvoice.status.in_(
                (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID),
            ),
        )
        .order_by(MatterInvoice.due_on.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    return [
        TodayInvoice(
            id=inv.id,
            matter=_matter_ref(m),
            invoice_number=inv.invoice_number,
            total_amount_minor=int(inv.total_amount_minor or 0),
            currency=inv.currency,
            due_on=inv.due_on,
            days_overdue=(today - inv.due_on).days,
            status=inv.status,
        )
        for inv, m in rows
        if inv.due_on  # narrow `due_on` null check for the type-checker
    ]


def _deadlines(
    session: Session,
    context: SessionContext,
    today: date,
    horizon_end: date,
    *,
    limit: int | None = None,
) -> list[TodayDeadline]:
    stmt = (
        select(MatterDeadline, Matter)
        .join(Matter, Matter.id == MatterDeadline.matter_id)
        .where(
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.notin_(("closed", "disposed")),
            visible_matters_filter(session, context=context),
            MatterDeadline.status.notin_(("done", "cancelled")),
            MatterDeadline.due_on >= today - timedelta(days=14),
            MatterDeadline.due_on <= horizon_end,
        )
        .order_by(MatterDeadline.due_on.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    out: list[TodayDeadline] = []
    for d, m in rows:
        days_until = (d.due_on - today).days
        # Severity is on the model in some schemas; tolerate absence.
        severity = getattr(d, "severity", None) or "normal"
        out.append(
            TodayDeadline(
                id=d.id,
                matter=_matter_ref(m),
                title=getattr(d, "title", "") or "",
                due_on=d.due_on,
                severity=str(severity),
                days_until=days_until,
            )
        )
    return out


# ---------------------------------------------------------------
# Per-matter "Next action" — single highest-priority item for the
# matter cockpit.
# ---------------------------------------------------------------


@dataclass(frozen=True)
class NextAction:
    """Highest-priority item demanding attention on a specific matter.

    Returned by `/api/matters/{matter_id}/next-action`. Lets the
    matter cockpit show "the one thing the user should do next" on
    this matter without making the user piece it together from five
    sections.
    """

    kind: str  # "hearing" | "task" | "draft" | "invoice" | "deadline"
    label: str  # human-readable title
    detail: str  # secondary line (date / status / amount)
    severity: str  # "urgent" | "soon" | "normal"
    href: str  # deeplink the cockpit card uses
    due_on_iso: str | None = None


# Severity ordering. Lower number = higher priority.
_SEVERITY_RANK = {"urgent": 0, "soon": 1, "normal": 2}


def build_matter_next_action(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    today: date | None = None,
) -> NextAction | None:
    """Pick the single most urgent item on a matter.

    Priority order (within the same severity bucket, earliest date
    wins):
    1. Overdue task / overdue invoice / overdue deadline → URGENT.
    2. Hearing today / hearing tomorrow / draft in review → SOON.
    3. Anything in the next 7 days → NORMAL.

    Returns None if nothing demands attention on this matter.
    """
    today = today or date.today()
    horizon_end = today + timedelta(days=7)

    # Reuse the per-stream queries by reading just one matter's slice.
    # Each helper applies visible_matters_filter, so a matter the
    # caller is not entitled to (restricted / team-scoped / walled)
    # yields zero candidates here and next-action returns None — the
    # same isolation the Today feed gets. (Per-matter SQL scoping to
    # avoid the whole-tenant scan is a separate perf change, P1-3.)
    hearings = [
        h for h in _hearings(
            session, context, today, horizon_end,
        ) if h.matter.id == matter_id
    ]
    tasks = [
        t for t in _tasks(
            session, context, today, horizon_end,
        ) if t.matter.id == matter_id
    ]
    drafts = [
        d for d in _drafts_in_review(
            session, context,
        ) if d.matter.id == matter_id
    ]
    invoices = [
        i for i in _overdue_invoices(
            session, context, today,
        ) if i.matter.id == matter_id
    ]
    deadlines = [
        d for d in _deadlines(
            session, context, today, horizon_end,
        ) if d.matter.id == matter_id
    ]

    candidates: list[NextAction] = []

    for inv in invoices:
        candidates.append(
            NextAction(
                kind="invoice",
                label=f"Overdue invoice {inv.invoice_number or ''}",
                detail=(
                    f"{inv.days_overdue}d overdue · "
                    f"{inv.currency} {inv.total_amount_minor / 100:,.0f}"
                ),
                severity="urgent",
                href=f"/app/matters/{matter_id}/billing",
                due_on_iso=inv.due_on.isoformat(),
            )
        )

    for t in tasks:
        if t.overdue:
            candidates.append(
                NextAction(
                    kind="task",
                    label=t.title,
                    detail=f"Task overdue · due {t.due_on.isoformat() if t.due_on else 'unset'}",
                    severity="urgent",
                    href=f"/app/matters/{matter_id}",
                    due_on_iso=t.due_on.isoformat() if t.due_on else None,
                )
            )

    for d in deadlines:
        if d.days_until <= 0:
            severity = "urgent"
            detail = f"Deadline {'today' if d.days_until == 0 else f'{abs(d.days_until)}d overdue'}"
        elif d.days_until <= 2:
            severity = "soon"
            detail = f"Deadline in {d.days_until}d"
        else:
            severity = "normal"
            detail = f"Deadline in {d.days_until}d"
        candidates.append(
            NextAction(
                kind="deadline",
                label=d.title,
                detail=detail,
                severity=severity,
                href=f"/app/matters/{matter_id}",
                due_on_iso=d.due_on.isoformat(),
            )
        )

    for h in hearings:
        days_until = (h.hearing_on - today).days
        if days_until <= 1:
            severity = "soon"
        else:
            severity = "normal"
        candidates.append(
            NextAction(
                kind="hearing",
                label=f"Hearing — {h.purpose}",
                detail=f"{h.forum_name} · {h.hearing_on.isoformat()} (in {days_until}d)",
                severity=severity,
                href=f"/app/matters/{matter_id}/hearings",
                due_on_iso=h.hearing_on.isoformat(),
            )
        )

    for t in tasks:
        if not t.overdue and t.due_on is not None:
            days_until = (t.due_on - today).days
            severity = "soon" if days_until <= 1 else "normal"
            candidates.append(
                NextAction(
                    kind="task",
                    label=t.title,
                    detail=f"Task due in {days_until}d",
                    severity=severity,
                    href=f"/app/matters/{matter_id}",
                    due_on_iso=t.due_on.isoformat(),
                )
            )

    for d in drafts:
        candidates.append(
            NextAction(
                kind="draft",
                label=f"{d.title} — pending review",
                detail=f"{d.template_type or d.draft_type} · waiting for partner sign-off",
                severity="soon",
                href=f"/app/matters/{matter_id}/drafts/{d.id}",
                due_on_iso=None,
            )
        )

    if not candidates:
        return None

    # Sort: severity first (urgent < soon < normal), then earliest date,
    # then by kind preference (invoice > task > deadline > hearing > draft).
    kind_rank = {
        "invoice": 0, "task": 1, "deadline": 2, "hearing": 3, "draft": 4,
    }
    candidates.sort(key=lambda c: (
        _SEVERITY_RANK.get(c.severity, 9),
        c.due_on_iso or "9999-99-99",
        kind_rank.get(c.kind, 9),
    ))
    return candidates[0]


__all__ = [
    "MatterRef",
    "NextAction",
    "TodayDeadline",
    "TodayDraftInReview",
    "TodayHearing",
    "TodayInvoice",
    "TodayTask",
    "TodayView",
    "build_matter_next_action",
    "build_today_view",
]
