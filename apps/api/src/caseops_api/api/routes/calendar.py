"""Phase B / J08 / M08 — unified calendar route.

GET /api/calendar/events — aggregates hearings, tasks, and deadlines
for the caller's company in one call, returning a date-sorted list
the cockpit calendar grid renders directly.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.calendar import (
    CalendarEventKind,
    CalendarEventListResponse,
)
from caseops_api.services.calendar import (
    aggregate_calendar_events,
    render_events_as_ical,
)
from caseops_api.services.identity import SessionContext


class ICalendarResponse(Response):
    """RFC 5545 iCalendar response. P0-003 (2026-04-24): the prior
    implementation used ``response_class=PlainTextResponse`` which
    forced FastAPI to declare ``text/plain`` in OpenAPI even though
    the runtime response set ``text/calendar`` on the wire.
    Subclassing ``Response`` with the correct ``media_type`` keeps
    OpenAPI and the wire header in sync, which test_openapi_quality
    asserts."""

    media_type = "text/calendar; charset=utf-8"


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


@router.get(
    "/events.ics",
    response_class=ICalendarResponse,
    summary="Download / subscribe to the calendar as iCalendar (FT-043).",
)
async def list_calendar_events_ical(
    context: CurrentContext,
    session: DbSession,
    range_from: Annotated[date, Query(alias="from")],
    range_to: Annotated[date, Query(alias="to")],
    kinds: Annotated[list[CalendarEventKind] | None, Query()] = None,
) -> ICalendarResponse:
    """Return the same event feed as :func:`list_calendar_events` but
    wire-formatted as RFC 5545 vCalendar. Google Calendar / Outlook
    / Apple Calendar all accept this as a subscribable URL so users
    see their CaseOps events alongside their personal calendar.
    """
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
    body = render_events_as_ical(
        events, calendar_name=f"CaseOps — {context.company.name}",
    )
    return ICalendarResponse(
        content=body,
        headers={
            # Content-Disposition so a browser "download" button
            # yields a nicely-named .ics file, while subscribe-by-
            # URL clients just read the body and ignore the header.
            "Content-Disposition": 'inline; filename="caseops-calendar.ics"',
        },
    )
