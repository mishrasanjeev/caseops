"""PG-004 (2026-05-01) — Per-user `me` endpoints.

Today's only resident: ``GET /api/me/today`` — the daily-cockpit
aggregator that powers the new `/app/today` page. Replaces the
"open the matters list and remember what's hot" workflow with a
prioritised, tenant-scoped, owner-filtered feed.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.today_view import build_today_view

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


class _MatterRefResponse(BaseModel):
    id: str
    title: str
    matter_code: str


class _HearingResponse(BaseModel):
    id: str
    matter: _MatterRefResponse
    hearing_on: date
    forum_name: str
    judge_name: str | None = None
    purpose: str


class _TaskResponse(BaseModel):
    id: str
    matter: _MatterRefResponse
    title: str
    due_on: date | None = None
    status: str
    priority: str
    overdue: bool


class _DraftInReviewResponse(BaseModel):
    id: str
    matter: _MatterRefResponse
    title: str
    draft_type: str
    template_type: str | None = None
    updated_at_iso: str


class _InvoiceResponse(BaseModel):
    id: str
    matter: _MatterRefResponse
    invoice_number: str | None = None
    total_amount_minor: int
    currency: str
    due_on: date
    days_overdue: int
    status: str


class _DeadlineResponse(BaseModel):
    id: str
    matter: _MatterRefResponse
    title: str
    due_on: date
    severity: str
    days_until: int


class TodayViewResponse(BaseModel):
    today: date
    horizon_days: int
    hearings_next_7d: list[_HearingResponse]
    tasks_due_or_overdue: list[_TaskResponse]
    drafts_in_review: list[_DraftInReviewResponse]
    overdue_invoices: list[_InvoiceResponse]
    deadlines_next_7d: list[_DeadlineResponse]


@router.get(
    "/today",
    response_model=TodayViewResponse,
    summary=(
        "Today's prioritised feed for the current user — hearings + "
        "tasks + draft reviews + overdue invoices + deadlines, all "
        "tenant-scoped and matter-access-respecting (PG-004, 2026-05-01)."
    ),
)
async def get_my_today_view(
    context: CurrentContext,
    session: DbSession,
    horizon_days: int = 7,
) -> TodayViewResponse:
    if horizon_days < 1 or horizon_days > 30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="horizon_days must be between 1 and 30.",
        )
    view = build_today_view(
        session, context=context, horizon_days=horizon_days,
    )

    def _matter(ref) -> _MatterRefResponse:
        return _MatterRefResponse(
            id=ref.id, title=ref.title, matter_code=ref.matter_code,
        )

    return TodayViewResponse(
        today=view.today,
        horizon_days=view.horizon_days,
        hearings_next_7d=[
            _HearingResponse(
                id=h.id,
                matter=_matter(h.matter),
                hearing_on=h.hearing_on,
                forum_name=h.forum_name,
                judge_name=h.judge_name,
                purpose=h.purpose,
            )
            for h in view.hearings_next_7d
        ],
        tasks_due_or_overdue=[
            _TaskResponse(
                id=t.id,
                matter=_matter(t.matter),
                title=t.title,
                due_on=t.due_on,
                status=t.status,
                priority=t.priority,
                overdue=t.overdue,
            )
            for t in view.tasks_due_or_overdue
        ],
        drafts_in_review=[
            _DraftInReviewResponse(
                id=d.id,
                matter=_matter(d.matter),
                title=d.title,
                draft_type=d.draft_type,
                template_type=d.template_type,
                updated_at_iso=d.updated_at_iso,
            )
            for d in view.drafts_in_review
        ],
        overdue_invoices=[
            _InvoiceResponse(
                id=i.id,
                matter=_matter(i.matter),
                invoice_number=i.invoice_number,
                total_amount_minor=i.total_amount_minor,
                currency=i.currency,
                due_on=i.due_on,
                days_overdue=i.days_overdue,
                status=i.status,
            )
            for i in view.overdue_invoices
        ],
        deadlines_next_7d=[
            _DeadlineResponse(
                id=d.id,
                matter=_matter(d.matter),
                title=d.title,
                due_on=d.due_on,
                severity=d.severity,
                days_until=d.days_until,
            )
            for d in view.deadlines_next_7d
        ],
    )
