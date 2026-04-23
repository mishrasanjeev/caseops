"""Phase B / J08 / M08 — unified calendar response shape.

The cockpit's ``/app/calendar`` page asks for one merged view of:

- ``MatterHearing`` (next hearing date)
- ``MatterTask`` with a ``due_on``
- ``MatterDeadline`` (drafts, contracts, intake follow-ups all funnel
  here per the docstring on the model)

Returning a flat ``CalendarEventRecord[]`` instead of a per-source
nested response keeps the UI a simple grid render and lets the date
filter / kind filter / search box be pure-client.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CalendarEventKind = Literal["hearing", "task", "deadline"]


class CalendarEventRecord(BaseModel):
    """One row on the calendar — same shape regardless of source."""

    id: str = Field(description="Source row's primary key prefixed by kind.")
    kind: CalendarEventKind
    occurs_on: date = Field(description="ISO yyyy-mm-dd. All events are date-granular.")
    title: str = Field(min_length=1, max_length=400)
    matter_id: str
    matter_title: str
    matter_code: str
    # ``status`` is the source row's status string verbatim (hearing
    # status, task status, deadline status). Useful for grey-ing
    # completed items in the grid without another round-trip.
    status: str | None = None
    # Free-text disambiguation for multiple events on the same matter
    # in the same day. e.g. "Bombay HC, Justice Patel" for a hearing,
    # "High" for a task priority.
    detail: str | None = None


class CalendarEventListResponse(BaseModel):
    range_from: date
    range_to: date
    events: list[CalendarEventRecord]
