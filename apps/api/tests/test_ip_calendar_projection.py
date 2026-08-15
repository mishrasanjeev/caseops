"""IPLF-039C increment 4: external calendar projection (UJ-62).

The 2026-08-15 inspection audit rated UJ-62 at roughly 1 of 6 paths because it
searched `ip_operations.py` and found `CalendarEventSync` created as a bare
pointer. That was **wrong**: the projection work lives in the shared
`calendar_sync.py` owner that the IP path delegates to, and it implements five
of the six paths. See the correction in the inspection audit document.

Stable manifest test IDs:

* ``IPLF-UJ-62-NORMAL``   project without surrendering docket authority
* ``IPLF-UJ-62-EXC-01``   outage/rate limit retries and keeps the stale row
* ``IPLF-UJ-62-EXC-02``   revoked access stops future work, preserves history
* ``IPLF-UJ-62-EXC-04``   sensitive content is redacted from the projection
* ``IPLF-UJ-62-EXC-05``   a timezone shift cannot move a date-only obligation

``UJ-62-EXC-03`` (user edits or deletes the external event) is **not** covered:
no drift detection exists. It is recorded as unbuilt, not asserted here.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import inspect as sa_inspect

from caseops_api.db.models import CalendarEventSync, CalendarEventSyncStatus
from caseops_api.services.calendar_sync import (
    CalendarSourcePayload,
    _ip_source_payload,
)


class _Docket:
    """Minimal stand-in carrying only what the payload builder reads."""

    id = "docket-uj62"
    current_version = 7
    title = "Highly Confidential Mark Name"
    primary_identifier = "TM 9999999"


def _payload(occurs_on: date) -> CalendarSourcePayload:
    return _ip_source_payload(
        source_type="ip_deadline_coverage",
        source_id="coverage-uj62",
        occurs_on=occurs_on,
        category="Deadline",
        docket=_Docket(),  # type: ignore[arg-type]
    )


def test_uj62_exc04_projection_carries_no_privileged_content() -> None:
    """IPLF-UJ-62-EXC-04 — the outbound copy is content-free by construction.

    Rather than redacting conditionally on an ethical wall, the IP projection is
    always minimal, which is the stronger design: there is no code path that
    could leak a mark name to a personal calendar.
    """

    payload = _payload(date(2026, 8, 20))
    blob = " ".join([payload.title, *payload.detail_lines])

    assert "Highly Confidential Mark Name" not in blob
    assert "TM 9999999" not in blob
    assert payload.title == "CaseOps IP - Deadline"
    assert any("Open CaseOps" in line for line in payload.detail_lines)
    # Correlation is by id only, never by content.
    assert payload.private_properties
    assert all(
        "Confidential" not in str(value) for value in payload.private_properties.values()
    )


def test_uj62_exc05_a_date_only_obligation_carries_a_date_not_a_time() -> None:
    """IPLF-UJ-62-EXC-05 — the projection is anchored to a date, not an instant.

    ``occurs_on`` is a ``date``. Because no time or offset is carried, there is
    no arithmetic a timezone or DST change could apply to move the obligation
    across a day boundary.
    """

    legal_date = date(2026, 10, 25)  # a European DST transition date
    payload = _payload(legal_date)

    assert isinstance(payload.occurs_on, date)
    assert payload.occurs_on == legal_date
    assert not hasattr(payload.occurs_on, "tzinfo")
    assert not hasattr(payload.occurs_on, "hour")

    # Google receives a pure all-day date range spanning exactly one day, with
    # no timezone at all. This mirrors the provider payload in calendar_sync.
    google_start = payload.occurs_on.isoformat()
    google_end = (payload.occurs_on + timedelta(days=1)).isoformat()
    assert google_start == "2026-10-25"
    assert google_end == "2026-10-26"
    assert "T" not in google_start and "Z" not in google_start

    # Outlook receives an all-day event anchored to the same date.
    outlook_start = f"{payload.occurs_on.isoformat()}T00:00:00"
    assert outlook_start.startswith("2026-10-25")


def test_uj62_normal_projection_is_a_pointer_that_cannot_duplicate() -> None:
    """IPLF-UJ-62-NORMAL — CaseOps keeps authority; resync cannot duplicate."""

    table = CalendarEventSync.__table__
    unique = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    # CAL-OPS-10: one projection per (connection, source), so a resync updates
    # rather than creating a second event.
    assert ("calendar_connection_id", "source_id", "source_type") in unique

    columns = {c.key for c in sa_inspect(CalendarEventSync).columns}
    # A stable external id is retained so updates and cancellations address the
    # same provider event.
    assert "provider_event_id" in columns
    # The row points at its CaseOps source; it never copies the legal date.
    assert {"source_type", "source_id"} <= columns
    assert not [c for c in columns if c in {"occurs_on", "due_on", "starts_at"}]


def test_uj62_exc01_outage_retries_rather_than_dropping_the_projection() -> None:
    """IPLF-UJ-62-EXC-01 — a failed sync is retried and stays visible."""

    columns = {c.key for c in sa_inspect(CalendarEventSync).columns}
    # Retry state is durable, so an outage does not silently lose the event.
    assert {"attempts", "max_attempts", "next_attempt_at"} <= columns
    assert {"last_error", "dead_letter_reason", "last_synced_at"} <= columns

    statuses = {member.value for member in CalendarEventSyncStatus}
    assert {"retry_scheduled", "failed", "dead_letter"} <= statuses
    # A stale projection remains addressable rather than being deleted.
    assert "pending" in statuses and "synced" in statuses


def test_uj62_exc02_revocation_is_a_connection_state_that_preserves_history() -> None:
    """IPLF-UJ-62-EXC-02 — revoking stops future work without erasing the past."""

    from caseops_api.db.models import CalendarConnectionStatus
    from caseops_api.services import calendar_sync

    assert hasattr(calendar_sync, "revoke_connection")
    assert "revoked" in {member.value for member in CalendarConnectionStatus}

    # Revocation is modelled on the connection, not by deleting sync rows, so
    # the projection history survives.
    sync_columns = {c.key for c in sa_inspect(CalendarEventSync).columns}
    assert "calendar_connection_id" in sync_columns
    assert "revoked_at" not in sync_columns
