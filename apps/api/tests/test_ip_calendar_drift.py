"""IPLF-039C increment 11 — external calendar drift (UJ-62-EXC-03).

The projection is a copy; CaseOps holds the obligation. Nothing detected that
copy being edited or deleted in the provider, so a lawyer's calendar could
quietly disagree with the date they are accountable for. This is the last
functional gap on the slice.

The design decision worth stating: an unreadable provider records ``unknown``,
never ``matches``. Reporting a match for something that was never read is the
same falsehood as counting unknown work as no work (UJ-50-EXC-03).

Stable manifest test IDs:

* ``IPLF-UJ-62-EXC-03``       a moved or deleted event is detected
* ``IPLF-UJ-62-EXC-03-A``     an unreadable provider is unknown, not matching
* ``IPLF-UJ-62-EXC-03-B``     re-projecting clears the finding
* ``IPLF-UJ-62-EXC-03-C``     a finding names no record the caller cannot open
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import calendar_sync
from caseops_api.services.calendar_sync import (
    CalendarProviderError,
    check_ip_calendar_projection_drift,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars

DUE = date.today() + timedelta(days=30)


class _Reader:
    """A provider stand-in that only answers the read used for drift."""

    configured = True

    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[str] = []

    def fetch_event(self, *, token_payload: dict, provider_event_id: str):
        self.calls.append(provider_event_id)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Unreadable:
    """A provider that exists but cannot be read back."""

    configured = True

    def fetch_event(self, *, token_payload: dict, provider_event_id: str):
        raise CalendarProviderError("Google Calendar read failed.")


class _NoReadCapability:
    """An older provider with no read capability at all."""

    configured = True


def _seed(client: TestClient, *, restricted: bool = False):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    membership_id = str(bootstrap["membership"]["id"])
    matter = _mk_matter(client, token, "IP-DRIFT-62")

    docket = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "DRIFTMARK",
            "matter_id": matter["id"],
            "restricted": restricted,
            "particulars": _particulars("DRIFTMARK"),
        },
    )
    assert docket.status_code == 201, docket.text
    docket_id = docket.json()["id"]

    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Renewal",
            "due_on": str(DUE),
            "assignee_membership_id": membership_id,
        },
    )
    assert deadline.status_code == 200, deadline.text
    deadline_id = deadline.json()["id"]

    # Link the deadline to the docket, then project it, directly: creating a
    # live provider connection is not what this test is about.
    factory = get_session_factory()
    with factory() as session:
        from caseops_api.db.models import MatterDeadline

        row = session.get(MatterDeadline, deadline_id)
        assert row is not None
        # A deadline targets a Matter or an IP docket, never both
        # (ck_matter_deadline_exactly_one_target), so retarget it.
        row.matter_id = None
        row.ip_docket_id = docket_id
        company_id = row.company_id

        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider="google_calendar",
            status=CalendarConnectionStatus.CONNECTED,
            encrypted_token_ref=calendar_sync._encrypt_token_payload(
                {"access_token": "drift-token"}
            ),
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection.id,
            source_type="matter_deadline",
            source_id=deadline_id,
            provider_event_id="provider-event-1",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        session.add(sync)
        session.commit()
        sync_id, connection_id = sync.id, connection.id

    return {
        "headers": headers,
        "membership_id": membership_id,
        "docket_id": docket_id,
        "deadline_id": deadline_id,
        "sync_id": sync_id,
        "connection_id": connection_id,
        "context_ids": (company_id, membership_id),
    }


def _run(context_ids) -> list:
    from caseops_api.db.models import Company, CompanyMembership

    company_id, membership_id = context_ids
    factory = get_session_factory()
    with factory() as session:
        membership = session.get(CompanyMembership, membership_id)
        company = session.get(Company, company_id)
        assert membership is not None and company is not None
        context = SessionContext(company=company, user=membership.user, membership=membership)
        return check_ip_calendar_projection_drift(session, context=context)


def _drift_status(sync_id: str) -> tuple[str, str | None]:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(CalendarEventSync, sync_id)
        assert row is not None
        return row.drift_status, row.drift_detail


@pytest.fixture(autouse=True)
def _reset_provider():
    yield
    calendar_sync.set_google_calendar_provider_for_tests(None)


def test_uj62_exc03_a_moved_event_is_detected(client: TestClient) -> None:
    """IPLF-UJ-62-EXC-03 — the copy no longer sits on the obligation date."""

    seeded = _seed(client)
    moved_to = (DUE + timedelta(days=3)).isoformat()
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": moved_to, "cancelled": False})
    )

    findings = _run(seeded["context_ids"])

    assert len(findings) == 1
    assert findings[0].drift_status == "moved"
    assert findings[0].ip_docket_id == seeded["docket_id"]
    status, detail = _drift_status(seeded["sync_id"])
    assert status == "moved"
    # Content-free: it says the copy moved, not to when. The authoritative date
    # lives in CaseOps, and a drift note is not the place to restate it.
    assert detail is not None
    assert moved_to not in detail
    assert "DRIFTMARK" not in detail


def test_uj62_exc03_a_deleted_event_is_detected(client: TestClient) -> None:
    """A deleted copy leaves the deadline invisible on the calendar."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_Reader(None))

    findings = _run(seeded["context_ids"])

    assert [f.drift_status for f in findings] == ["missing"]
    assert _drift_status(seeded["sync_id"])[0] == "missing"


def test_uj62_exc03_a_cancelled_event_counts_as_missing(client: TestClient) -> None:
    """Providers cancel rather than delete; the effect on the lawyer is the same."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": DUE.isoformat(), "cancelled": True})
    )

    findings = _run(seeded["context_ids"])

    assert [f.drift_status for f in findings] == ["missing"]


def test_uj62_exc03_an_untouched_event_matches(client: TestClient) -> None:
    """The check must not manufacture drift where there is none."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": DUE.isoformat(), "cancelled": False})
    )

    findings = _run(seeded["context_ids"])

    assert findings == []
    assert _drift_status(seeded["sync_id"])[0] == "matches"


def test_uj62_exc03a_an_unreadable_provider_is_unknown_not_matching(
    client: TestClient,
) -> None:
    """IPLF-UJ-62-EXC-03-A — unverified is not verified.

    This is the same rule as UJ-50-EXC-03's null-rather-than-zero: a projection
    that could not be read must not be recorded as correct.
    """

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_Unreadable())

    findings = _run(seeded["context_ids"])

    assert [f.drift_status for f in findings] == ["unknown"]
    assert _drift_status(seeded["sync_id"])[0] == "unknown"


def test_uj62_exc03a_a_provider_without_a_read_capability_is_unknown(
    client: TestClient,
) -> None:
    """A provider that cannot read back fails closed rather than silently passing."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_NoReadCapability())

    findings = _run(seeded["context_ids"])

    assert [f.drift_status for f in findings] == ["unknown"]


def test_uj62_exc03a_an_undated_event_is_unknown(client: TestClient) -> None:
    """A copy with no readable date cannot be confirmed to match."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": None, "cancelled": False})
    )

    findings = _run(seeded["context_ids"])

    assert [f.drift_status for f in findings] == ["unknown"]


def test_uj62_exc03b_reprojecting_clears_a_finding(client: TestClient) -> None:
    """IPLF-UJ-62-EXC-03-B — the repair loop closes, without a re-check lying.

    Re-projecting repairs the copy, so a recorded drift becomes stale. It is
    cleared to `unchecked` rather than to `matches`: the new copy has not been
    read back yet, and only a check may claim a match.
    """

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_Reader(None))
    assert _run(seeded["context_ids"])
    assert _drift_status(seeded["sync_id"])[0] == "missing"

    factory = get_session_factory()
    with factory() as session:
        row = session.get(CalendarEventSync, seeded["sync_id"])
        assert row is not None
        # Simulate the success path's reset, which is what a re-projection does.
        row.drift_status = "unchecked"
        row.drift_checked_at = None
        row.drift_detail = None
        session.commit()

    assert _drift_status(seeded["sync_id"]) == ("unchecked", None)

    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": DUE.isoformat(), "cancelled": False})
    )
    assert _run(seeded["context_ids"]) == []
    assert _drift_status(seeded["sync_id"])[0] == "matches"


def test_uj62_exc03b_a_successful_resync_resets_drift_in_the_source() -> None:
    """The reset above is the product's behaviour, not only the test's.

    Asserted against the source so the two cannot drift apart: the success path
    clears the recorded drift rather than leaving a stale finding attached to a
    freshly projected event.
    """

    import inspect

    source = inspect.getsource(calendar_sync._sync_source_to_provider)
    assert 'sync.drift_status = "unchecked"' in source
    assert "sync.drift_checked_at = None" in source


def test_uj62_exc03c_a_finding_names_no_record_the_caller_cannot_open(
    client: TestClient,
) -> None:
    """IPLF-UJ-62-EXC-03-C — a drift check is not a way to enumerate records.

    The row is still checked and recorded, because the drift is real and the
    owner needs it; it is simply not reported to a caller who cannot open the
    record it names.
    """

    from caseops_api.db.models import Company, CompanyMembership
    from tests.test_ip_deadline_workflow import _member

    seeded = _seed(client, restricted=True)
    calendar_sync.set_google_calendar_provider_for_tests(_Reader(None))

    outsider_id, _token = _member(
        client,
        # The owner token is needed to create the member.
        str(seeded["headers"]["Authorization"]).removeprefix("Bearer "),
        name="Drift Outsider",
        email="drift-outsider@asterlegal.in",
    )

    company_id, _owner_id = seeded["context_ids"]
    factory = get_session_factory()
    with factory() as session:
        membership = session.get(CompanyMembership, outsider_id)
        company = session.get(Company, company_id)
        assert membership is not None and company is not None
        outsider_context = SessionContext(
            company=company, user=membership.user, membership=membership
        )
        findings = check_ip_calendar_projection_drift(session, context=outsider_context)

    assert findings == []
    # Nothing was written for a record this caller cannot open, and crucially
    # one such row did not abort the whole check.
    assert _drift_status(seeded["sync_id"])[0] == "unchecked"

    # The owner's own run does record it: the drift is real and they need it.
    assert [f.drift_status for f in _run(seeded["context_ids"])] == ["missing"]
    assert _drift_status(seeded["sync_id"])[0] == "missing"


def test_uj62_exc03_the_drift_check_route_reports_findings(client: TestClient) -> None:
    """The endpoint itself, not only the service behind it.

    Added after the route-coverage gate caught that every drift assertion here
    called the service directly, so the route's capability gate and its
    serialisation were unproven.
    """

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_Reader(None))

    response = client.post(
        "/api/ip/calendar-projections/drift-check", headers=seeded["headers"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checked_at"]
    assert [row["drift_status"] for row in body["findings"]] == ["missing"]
    finding = body["findings"][0]
    assert finding["sync_id"] == seeded["sync_id"]
    assert finding["ip_docket_id"] == seeded["docket_id"]
    # The response names identifiers, never the record title.
    assert "DRIFTMARK" not in response.text

    # A second check with the copy restored reports clean through the same route.
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": DUE.isoformat(), "cancelled": False})
    )
    clean = client.post("/api/ip/calendar-projections/drift-check", headers=seeded["headers"])
    assert clean.status_code == 200, clean.text
    assert clean.json()["findings"] == []
