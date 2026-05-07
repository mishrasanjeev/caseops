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

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.calendar import (
    CalendarConnectionCallbackResponse,
    CalendarConnectionListResponse,
    CalendarConnectionRecord,
    CalendarConnectionStartResponse,
    CalendarEventKind,
    CalendarEventListResponse,
    CalendarEventSyncResponse,
    CalendarSyncStatusResponse,
)
from caseops_api.services.calendar import (
    aggregate_calendar_events,
    render_events_as_ical,
)
from caseops_api.services.calendar_sync import (
    complete_outlook_connection,
    list_connections,
    revoke_connection,
    start_outlook_connection,
    sync_hearing_to_outlook,
    sync_status,
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
CalendarViewer = Annotated[SessionContext, Depends(require_capability("calendar:view"))]
CalendarSyncer = Annotated[SessionContext, Depends(require_capability("calendar:sync"))]

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
    context: CalendarViewer,
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
    context: CalendarViewer,
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


@router.get(
    "/connections",
    response_model=CalendarConnectionListResponse,
    summary="List the caller's calendar connection state.",
)
async def list_calendar_connections(
    context: CalendarViewer,
    session: DbSession,
) -> CalendarConnectionListResponse:
    return list_connections(session, context=context)


@router.post(
    "/connections/outlook/start",
    response_model=CalendarConnectionStartResponse,
    summary="Start Outlook calendar OAuth without exposing tokens.",
)
async def start_calendar_outlook_connection(
    context: CalendarSyncer,
    session: DbSession,
) -> CalendarConnectionStartResponse:
    return start_outlook_connection(session, context=context)


@router.get(
    "/connections/outlook/callback",
    response_model=CalendarConnectionCallbackResponse,
    summary="Complete Outlook calendar OAuth callback.",
)
async def complete_calendar_outlook_connection(
    context: CalendarSyncer,
    session: DbSession,
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
) -> CalendarConnectionCallbackResponse:
    connection = complete_outlook_connection(
        session,
        context=context,
        code=code,
        state=state,
    )
    return CalendarConnectionCallbackResponse(connected=True, connection=connection)


@router.delete(
    "/connections/{connection_id}",
    response_model=CalendarConnectionRecord,
    summary="Revoke one calendar connection for the caller.",
)
async def revoke_calendar_connection(
    context: CalendarSyncer,
    session: DbSession,
    connection_id: str,
) -> CalendarConnectionRecord:
    return revoke_connection(session, context=context, connection_id=connection_id)


@router.post(
    "/sync/hearings/{hearing_id}",
    response_model=CalendarEventSyncResponse,
    summary="Manually sync one hearing to Outlook.",
)
async def sync_hearing(
    context: CalendarSyncer,
    session: DbSession,
    hearing_id: str,
) -> CalendarEventSyncResponse:
    return sync_hearing_to_outlook(session, context=context, hearing_id=hearing_id)


@router.get(
    "/sync-status",
    response_model=CalendarSyncStatusResponse,
    summary="List manual calendar sync status for the caller.",
)
async def get_calendar_sync_status(
    context: CalendarViewer,
    session: DbSession,
) -> CalendarSyncStatusResponse:
    return sync_status(session, context=context)
