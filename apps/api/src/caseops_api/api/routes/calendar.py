"""Phase B / J08 / M08 — unified calendar route.

GET /api/calendar/events — aggregates hearings, tasks, and deadlines
for the caller's company in one call, returning a date-sorted list
the cockpit calendar grid renders directly.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.calendar import (
    CalendarEventKind,
    CalendarEventListResponse,
)
from caseops_api.services.calendar import aggregate_calendar_events
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]

# Largest range the API will serve in one call. The cockpit only ever
# fetches a single month at a time, so 92 days is generous for a
# possible "next 3 months" view without ever pulling thousands of
# rows in a single response.
_MAX_RANGE_DAYS = 92


@router.get(
    "/events",
    response_model=CalendarEventListResponse,
    summary="Aggregate hearings, tasks, and deadlines into one calendar feed.",
)
async def list_calendar_events(
    context: CurrentContext,
    session: DbSession,
    range_from: Annotated[
        date,
        Query(
            alias="from",
            description="Inclusive start date (yyyy-mm-dd).",
        ),
    ],
    range_to: Annotated[
        date,
        Query(
            alias="to",
            description="Inclusive end date (yyyy-mm-dd).",
        ),
    ],
    kinds: Annotated[
        list[CalendarEventKind] | None,
        Query(
            description=(
                "Filter to a subset of event kinds. Default returns all "
                "three (hearing, task, deadline)."
            ),
        ),
    ] = None,
) -> CalendarEventListResponse:
    if range_from > range_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`from` must be on or before `to`.",
        )
    if (range_to - range_from) > timedelta(days=_MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Calendar range is capped at {_MAX_RANGE_DAYS} days. "
                "Request a narrower window."
            ),
        )
    events = aggregate_calendar_events(
        session,
        context=context,
        range_from=range_from,
        range_to=range_to,
        kinds=kinds,
    )
    return CalendarEventListResponse(
        range_from=range_from,
        range_to=range_to,
        events=events,
    )
