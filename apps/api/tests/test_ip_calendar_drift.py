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

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingSubscription,
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProjectionReconciliationCandidate,
    CalendarProvider,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import calendar_sync
from caseops_api.services.calendar_sync import (
    CalendarProviderError,
    CalendarProviderPreconditionError,
    GoogleCalendarProvider,
    MicrosoftGraphOutlookProvider,
    check_ip_calendar_projection_drift,
)
from caseops_api.services.ip_capability_catalog import ip_workspace_readiness
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


class _StaleReviewedWriter(_Reader):
    """Provider stand-in that refuses a write against a later event version."""

    def __init__(self, result: object) -> None:
        super().__init__(result)
        self.expected_revisions: list[str | None] = []

    def upsert_calendar_item(
        self,
        *,
        token_payload: dict,
        item: object,
        existing_provider_event_id: str | None,
        expected_provider_revision: str | None = None,
    ) -> str:
        del token_payload, item, existing_provider_event_id
        self.expected_revisions.append(expected_provider_revision)
        raise CalendarProviderPreconditionError(
            "Provider event changed after reconciliation review."
        )


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


def _candidates(sync_id: str) -> list[CalendarProjectionReconciliationCandidate]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(CalendarProjectionReconciliationCandidate)
                .where(CalendarProjectionReconciliationCandidate.calendar_event_sync_id == sync_id)
                .order_by(CalendarProjectionReconciliationCandidate.created_at)
            ).all()
        )


def _manual_docketing_reason(context_ids: tuple[str, str]) -> str:
    from caseops_api.db.models import Company, CompanyMembership

    company_id, membership_id = context_ids
    factory = get_session_factory()
    with factory() as session:
        membership = session.get(CompanyMembership, membership_id)
        company = session.get(Company, company_id)
        assert membership is not None and company is not None
        context = SessionContext(company=company, user=membership.user, membership=membership)
        return next(
            item.reason
            for item in ip_workspace_readiness(
                session,
                context=context,
                settings=get_settings(),
            )
            if item.feature_id == "manual_docketing"
        )


def _set_ip_workspace_entitlement(company_id: str, *, enabled: bool) -> None:
    factory = get_session_factory()
    with factory() as session:
        subscription = session.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.company_id == company_id)
            .order_by(BillingSubscription.created_at.desc())
        )
        if subscription is None:
            subscription = BillingSubscription(
                company_id=company_id,
                status="manual_active",
                segment="law_firm",
                source="calendar-drift-fixture",
                externally_billable=False,
                entitlement_overrides_json={"ip_workspace": enabled},
            )
            session.add(subscription)
        else:
            overrides = dict(subscription.entitlement_overrides_json or {})
            overrides["ip_workspace"] = enabled
            subscription.entitlement_overrides_json = overrides
        session.commit()


def _set_workspace_rollout(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    expires_at: str,
) -> None:
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ROLLOUT_EXPIRES_AT", expires_at)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_provider():
    get_settings.cache_clear()
    yield
    calendar_sync.set_google_calendar_provider_for_tests(None)
    calendar_sync.set_outlook_provider_for_tests(None)
    get_settings.cache_clear()


def test_graph_fetch_event_uses_projection_timezone_and_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real Graph adapter must not turn midnight IST into the prior UTC date."""

    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "id": "graph-event/one",
                "isAllDay": True,
                "isCancelled": False,
                "changeKey": "graph-revision-7",
                "lastModifiedDateTime": "2026-08-20T05:00:00Z",
                "start": {
                    "dateTime": "2026-08-20T00:00:00.0000000",
                    "timeZone": "India Standard Time",
                },
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    event = MicrosoftGraphOutlookProvider().fetch_event(
        token_payload={"access_token": "graph-token"},
        provider_event_id="graph-event/one",
    )

    assert event == {
        "id": "graph-event/one",
        "start_date": "2026-08-20",
        "cancelled": False,
        "provider_revision": "graph-revision-7",
        "provider_updated_at": "2026-08-20T05:00:00Z",
    }
    assert str(captured["url"]).endswith("/graph-event%2Fone")
    assert captured["params"] == {
        "$select": "id,isAllDay,isCancelled,start,changeKey,lastModifiedDateTime"
    }
    assert captured["timeout"] == 15
    assert captured["headers"] == {
        "Authorization": "Bearer graph-token",
        "Prefer": 'outlook.timezone="India Standard Time"',
    }


@pytest.mark.parametrize(
    ("start", "expected_date"),
    [
        ({"date": "2026-08-20"}, "2026-08-20"),
        ({"dateTime": "2026-08-22T09:30:00+05:30"}, "2026-08-22"),
    ],
)
def test_google_fetch_event_parses_documented_start_shapes(
    monkeypatch: pytest.MonkeyPatch,
    start: dict[str, str],
    expected_date: str,
) -> None:
    """The real Google adapter accepts all-day and timed Event resources."""

    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "id": "google-event/one",
                "status": "confirmed",
                "start": start,
                "etag": '"google-revision-9"',
                "updated": "2026-08-20T05:05:00Z",
                "sequence": 3,
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    event = GoogleCalendarProvider().fetch_event(
        token_payload={"access_token": "google-token"},
        provider_event_id="google-event/one",
    )

    assert event == {
        "id": "google-event/one",
        "start_date": expected_date,
        "cancelled": False,
        "provider_revision": '"google-revision-9"',
        "provider_precondition_revision": '"google-revision-9"',
        "provider_updated_at": "2026-08-20T05:05:00Z",
        "provider_sequence": 3,
    }
    assert str(captured["url"]).endswith("/google-event%2Fone")
    assert captured["headers"] == {"Authorization": "Bearer google-token"}
    assert captured["timeout"] == 15


def test_google_reviewed_repair_uses_provider_version_precondition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_patch(url: str, **kwargs: object) -> httpx.Response:
        captured.update({"url": url, **kwargs})
        return httpx.Response(200, request=httpx.Request("PATCH", url), json={})

    monkeypatch.setattr(httpx, "patch", fake_patch)
    GoogleCalendarProvider().upsert_calendar_item(
        token_payload={"access_token": "provider-token"},
        item=SimpleNamespace(
            title="Renewal",
            occurs_on=DUE,
            detail_lines=("CaseOps projection",),
            category="IP",
            private_properties={},
        ),
        existing_provider_event_id="provider-event-1",
        expected_provider_revision='"google-version-11"',
    )

    headers = captured["headers"]
    payload = captured["json"]
    assert isinstance(headers, dict)
    assert isinstance(payload, dict)
    assert headers.get("If-Match") == '"google-version-11"'
    assert "changeKey" not in payload


def test_graph_reviewed_repair_fails_closed_without_a_documented_precondition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_patch(url: str, **kwargs: object) -> httpx.Response:
        del url, kwargs
        nonlocal called
        called = True
        raise AssertionError("Graph PATCH must not be attempted")

    monkeypatch.setattr(httpx, "patch", fake_patch)
    with pytest.raises(CalendarProviderPreconditionError):
        MicrosoftGraphOutlookProvider().upsert_calendar_item(
            token_payload={"access_token": "provider-token"},
            item=SimpleNamespace(
                title="Renewal",
                occurs_on=DUE,
                detail_lines=("CaseOps projection",),
                category="IP",
                private_properties={},
            ),
            existing_provider_event_id="provider-event-1",
            expected_provider_revision="graph-version-11",
        )
    assert called is False


def test_google_reviewed_repair_refuses_a_stale_provider_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_patch(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(412, request=httpx.Request("PATCH", url))

    monkeypatch.setattr(httpx, "patch", fake_patch)
    with pytest.raises(CalendarProviderPreconditionError):
        GoogleCalendarProvider().upsert_calendar_item(
            token_payload={"access_token": "provider-token"},
            item=SimpleNamespace(
                title="Renewal",
                occurs_on=DUE,
                detail_lines=("CaseOps projection",),
                category="IP",
                private_properties={},
            ),
            existing_provider_event_id="provider-event-1",
            expected_provider_revision='"reviewed-version"',
        )


@pytest.mark.parametrize(
    "provider",
    [MicrosoftGraphOutlookProvider(), GoogleCalendarProvider()],
    ids=["graph", "google"],
)
def test_fetch_event_404_returns_missing(
    monkeypatch: pytest.MonkeyPatch,
    provider: MicrosoftGraphOutlookProvider | GoogleCalendarProvider,
) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    assert (
        provider.fetch_event(
            token_payload={"access_token": "provider-token"},
            provider_event_id="missing-event",
        )
        is None
    )


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (MicrosoftGraphOutlookProvider(), "Microsoft Graph calendar read failed."),
        (GoogleCalendarProvider(), "Google Calendar read failed."),
    ],
    ids=["graph", "google"],
)
def test_fetch_event_http_error_is_safely_wrapped(
    monkeypatch: pytest.MonkeyPatch,
    provider: MicrosoftGraphOutlookProvider | GoogleCalendarProvider,
    message: str,
) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(429, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(CalendarProviderError, match=message):
        provider.fetch_event(
            token_payload={"access_token": "provider-token"},
            provider_event_id="rate-limited-event",
        )


def test_drift_reader_passes_tenant_context_to_provider_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant-admin OAuth configuration must not fall back to process env."""

    session_marker = object()
    context_marker = object()
    provider = _Reader(
        {"id": "provider-event-1", "start_date": "2026-08-20", "cancelled": False}
    )

    def fake_provider_for(
        provider_name: CalendarProvider,
        session: object | None = None,
        *,
        context: object | None = None,
    ) -> _Reader:
        assert provider_name == CalendarProvider.GOOGLE_CALENDAR
        assert session is session_marker
        assert context is context_marker
        return provider

    monkeypatch.setattr(calendar_sync, "_provider_for", fake_provider_for)
    connection = SimpleNamespace(
        status=CalendarConnectionStatus.CONNECTED,
        provider=CalendarProvider.GOOGLE_CALENDAR,
        encrypted_token_ref=calendar_sync._encrypt_token_payload(
            {"access_token": "tenant-token"}
        ),
    )

    reader = calendar_sync._drift_provider_reader(
        session_marker,  # type: ignore[arg-type]
        context=context_marker,  # type: ignore[arg-type]
        connection=connection,  # type: ignore[arg-type]
    )

    assert reader is not None
    assert reader("provider-event-1") == {
        "id": "provider-event-1",
        "start_date": "2026-08-20",
        "cancelled": False,
    }


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


@pytest.mark.parametrize(
    "damaged_token_kind",
    ["invalid_envelope", "malformed_json"],
)
def test_uj62_exc03a_a_damaged_token_does_not_abort_other_connections(
    client: TestClient,
    damaged_token_kind: str,
) -> None:
    """One unreadable credential is unknown; later connections are still checked."""

    seeded = _seed(client)
    factory = get_session_factory()
    with factory() as session:
        damaged_connection = session.get(
            UserCalendarConnection, seeded["connection_id"]
        )
        assert damaged_connection is not None
        if damaged_token_kind == "invalid_envelope":
            damaged_connection.encrypted_token_ref = "not-a-fernet-token"
        else:
            malformed = calendar_sync._fernet().encrypt(b"{not-json")
            damaged_connection.encrypted_token_ref = (
                "fernet:" + malformed.decode("ascii")
            )

        healthy_connection = UserCalendarConnection(
            company_id=seeded["context_ids"][0],
            membership_id=seeded["membership_id"],
            provider=CalendarProvider.OUTLOOK,
            status=CalendarConnectionStatus.CONNECTED,
            encrypted_token_ref=calendar_sync._encrypt_token_payload(
                {"access_token": "healthy-token"}
            ),
        )
        session.add(healthy_connection)
        session.flush()
        healthy_sync = CalendarEventSync(
            company_id=seeded["context_ids"][0],
            calendar_connection_id=healthy_connection.id,
            source_type="matter_deadline",
            source_id=seeded["deadline_id"],
            provider_event_id="provider-event-healthy",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        session.add(healthy_sync)
        session.commit()
        healthy_sync_id = healthy_sync.id

    reader = _Reader(
        {
            "id": "provider-event-healthy",
            "start_date": DUE.isoformat(),
            "cancelled": False,
        }
    )
    calendar_sync.set_google_calendar_provider_for_tests(reader)
    calendar_sync.set_outlook_provider_for_tests(reader)

    findings = _run(seeded["context_ids"])

    assert [(item.sync_id, item.drift_status) for item in findings] == [
        (seeded["sync_id"], "unknown")
    ]
    assert _drift_status(seeded["sync_id"])[0] == "unknown"
    assert _drift_status(healthy_sync_id)[0] == "matches"
    assert reader.calls == ["provider-event-healthy"]


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


def test_uj62_exc03_persists_an_immutable_content_minimised_candidate(
    client: TestClient,
) -> None:
    """A provider-side move is reviewable without copying provider content.

    The same observed state must deduplicate to its original evidence record;
    a later observation produces a new candidate and supersedes, rather than
    edits, the earlier snapshot.
    """

    seeded = _seed(client)
    first_observed_date = (DUE + timedelta(days=1)).isoformat()
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader(
            {
                "id": "provider-event-1",
                "start_date": first_observed_date,
                "cancelled": False,
                "provider_revision": "revision-1",
                "provider_updated_at": "2026-08-20T05:00:00Z",
                "provider_sequence": 1,
                "title": "must not persist",
            }
        )
    )

    first_findings = _run(seeded["context_ids"])
    assert len(first_findings) == 1
    first_id = first_findings[0].reconciliation_candidate_id
    assert first_id
    first = _candidates(seeded["sync_id"])
    assert len(first) == 1
    assert first[0].id == first_id
    assert first[0].status == "pending"
    assert first[0].drift_status == "moved"
    assert first[0].expected_snapshot_json == {
        "schema_version": 1,
        "provider_event_id": "provider-event-1",
        "projection_synced_at": None,
        "source_type": "matter_deadline",
        "source_id": seeded["deadline_id"],
        "occurs_on": DUE.isoformat(),
    }
    assert first[0].observed_snapshot_json == {
        "schema_version": 1,
        "readable": True,
        "event_present": True,
        "cancelled": False,
        "start_date": first_observed_date,
        "provider_revision": "revision-1",
        "provider_updated_at": "2026-08-20T05:00:00Z",
        "provider_sequence": 1,
    }
    assert len(first[0].snapshot_sha256) == 64
    assert "title" not in first[0].observed_snapshot_json
    assert "body" not in first[0].observed_snapshot_json
    assert "attendees" not in first[0].observed_snapshot_json

    same_findings = _run(seeded["context_ids"])
    assert [item.reconciliation_candidate_id for item in same_findings] == [first_id]
    assert len(_candidates(seeded["sync_id"])) == 1

    second_observed_date = (DUE + timedelta(days=2)).isoformat()
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader({"id": "provider-event-1", "start_date": second_observed_date, "cancelled": False})
    )
    second_findings = _run(seeded["context_ids"])
    assert len(second_findings) == 1
    assert second_findings[0].reconciliation_candidate_id != first_id
    candidates = _candidates(seeded["sync_id"])
    assert [row.status for row in candidates] == ["superseded", "pending"]
    assert candidates[0].observed_snapshot_json["start_date"] == first_observed_date
    assert candidates[1].observed_snapshot_json["start_date"] == second_observed_date


def test_uj62_exc03_candidate_decisions_are_authorized_and_never_import_a_provider_date(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept preserves CaseOps; reject queues an exact known-ID reprojection."""

    seeded = _seed(client)
    moved_date = (DUE + timedelta(days=1)).isoformat()
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader(
            {
                "id": "provider-event-1",
                "start_date": moved_date,
                "cancelled": False,
                "provider_revision": '"revision-accepted"',
            }
        )
    )
    first = _run(seeded["context_ids"])[0]
    assert first.reconciliation_candidate_id

    listed = client.get(
        "/api/ip/calendar-projections/reconciliation-candidates",
        headers=seeded["headers"],
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()["candidates"]
    assert [row["id"] for row in body] == [first.reconciliation_candidate_id]
    assert body[0]["observed_snapshot"]["start_date"] == moved_date

    purposes: list[str] = []

    def allow_step_up(*_args, **kwargs) -> None:
        purposes.append(str(kwargs["purpose"]))

    monkeypatch.setattr(calendar_sync, "require_recent_step_up", allow_step_up)
    stale = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{first.reconciliation_candidate_id}/decision",
        headers=seeded["headers"],
        json={
            "action": "accept",
            "evidence_reference": "matter-note:stale-calendar-review",
            "expected_snapshot_sha256": "0" * 64,
        },
    )
    assert stale.status_code == 409, stale.text
    assert _candidates(seeded["sync_id"])[0].status == "pending"
    accepted = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{first.reconciliation_candidate_id}/decision",
        headers=seeded["headers"],
        json={
            "action": "accept",
            "evidence_reference": "matter-note:calendar-drift-reviewed",
            "expected_snapshot_sha256": body[0]["snapshot_sha256"],
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert purposes == [
        "calendar_projection_reconciliation",
        "calendar_projection_reconciliation",
    ]
    factory = get_session_factory()
    with factory() as session:
        sync = session.get(CalendarEventSync, seeded["sync_id"])
        assert sync is not None
        assert sync.sync_status == CalendarEventSyncStatus.SYNCED
    # An accepted observation stays visible in history but is not re-opened or
    # re-audited on each scan while the exact external state remains unchanged.
    assert _run(seeded["context_ids"]) == []
    assert _candidates(seeded["sync_id"])[0].status == "accepted"

    changed_date = (DUE + timedelta(days=2)).isoformat()
    calendar_sync.set_google_calendar_provider_for_tests(
        _Reader(
            {
                "id": "provider-event-1",
                "start_date": changed_date,
                "cancelled": False,
                "provider_revision": '"revision-restored"',
                "provider_precondition_revision": '"revision-restored"',
            }
        )
    )
    second = _run(seeded["context_ids"])[0]
    assert second.reconciliation_candidate_id
    pending = _candidates(seeded["sync_id"])[-1]
    # A rejection is a request to issue a provider PATCH.  It must not queue
    # latent remote work while the credential has been disconnected.
    with factory() as session:
        connection = session.get(UserCalendarConnection, seeded["connection_id"])
        assert connection is not None
        connection.status = CalendarConnectionStatus.ERROR
        session.commit()
    unavailable = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{second.reconciliation_candidate_id}/decision",
        headers=seeded["headers"],
        json={
            "action": "reject",
            "evidence_reference": "matter-note:connection-unavailable",
            "expected_snapshot_sha256": pending.snapshot_sha256,
        },
    )
    assert unavailable.status_code == 409, unavailable.text
    with factory() as session:
        connection = session.get(UserCalendarConnection, seeded["connection_id"])
        sync = session.get(CalendarEventSync, seeded["sync_id"])
        assert connection is not None and sync is not None
        assert connection.status == CalendarConnectionStatus.ERROR
        assert sync.sync_status == CalendarEventSyncStatus.SYNCED
        connection.status = CalendarConnectionStatus.CONNECTED
        session.commit()
    rejected = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{second.reconciliation_candidate_id}/decision",
        headers=seeded["headers"],
        json={
            "action": "reject",
            "evidence_reference": "matter-note:restore-authoritative-projection",
            "expected_snapshot_sha256": pending.snapshot_sha256,
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    with factory() as session:
        sync = session.get(CalendarEventSync, seeded["sync_id"])
        assert sync is not None
        assert sync.sync_status == CalendarEventSyncStatus.PENDING
        assert sync.provider_event_id == "provider-event-1"
        assert sync.source_id == seeded["deadline_id"]
        assert sync.reconciliation_candidate_id == second.reconciliation_candidate_id
        assert sync.reconciliation_snapshot_sha256 == pending.snapshot_sha256
        assert sync.reconciliation_provider_revision == '"revision-restored"'

        # A successful worker repair advances the projection generation. If
        # the same external edit then recurs, the old rejected snapshot must
        # not suppress a new actionable candidate.
        sync.sync_status = CalendarEventSyncStatus.SYNCED
        sync.last_synced_at = datetime.now(UTC)
        sync.drift_status = "unchecked"
        sync.drift_checked_at = None
        sync.drift_detail = None
        sync.reconciliation_candidate_id = None
        sync.reconciliation_snapshot_sha256 = None
        sync.reconciliation_provider_revision = None
        session.commit()
    repeated = _run(seeded["context_ids"])[0]
    assert repeated.reconciliation_candidate_id
    assert repeated.reconciliation_candidate_id != second.reconciliation_candidate_id


def test_uj62_exc03_unknown_snapshot_cannot_queue_an_external_rewrite(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unverified provider state is not evidence that a PATCH is required."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_Unreadable())
    finding = _run(seeded["context_ids"])[0]
    assert finding.drift_status == "unknown"
    candidate = _candidates(seeded["sync_id"])[0]
    monkeypatch.setattr(calendar_sync, "require_recent_step_up", lambda *_a, **_kw: None)

    rejected = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{candidate.id}/decision",
        headers=seeded["headers"],
        json={
            "action": "reject",
            "evidence_reference": "matter-note:provider-unreadable",
            "expected_snapshot_sha256": candidate.snapshot_sha256,
        },
    )
    assert rejected.status_code == 409, rejected.text
    with get_session_factory()() as session:
        sync = session.get(CalendarEventSync, seeded["sync_id"])
        assert sync is not None
        assert sync.sync_status == CalendarEventSyncStatus.SYNCED


def test_uj62_exc03_missing_snapshot_cannot_queue_an_external_rewrite(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ID is not safe evidence for an automatic create or overwrite."""

    seeded = _seed(client)
    calendar_sync.set_google_calendar_provider_for_tests(_Reader(None))
    finding = _run(seeded["context_ids"])[0]
    assert finding.drift_status == "missing"
    candidate = _candidates(seeded["sync_id"])[0]
    monkeypatch.setattr(calendar_sync, "require_recent_step_up", lambda *_a, **_kw: None)

    rejected = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{candidate.id}/decision",
        headers=seeded["headers"],
        json={
            "action": "reject",
            "evidence_reference": "matter-note:provider-event-missing",
            "expected_snapshot_sha256": candidate.snapshot_sha256,
        },
    )
    assert rejected.status_code == 409, rejected.text
    with get_session_factory()() as session:
        sync = session.get(CalendarEventSync, seeded["sync_id"])
        assert sync is not None
        assert sync.sync_status == CalendarEventSyncStatus.SYNCED


def test_uj62_exc03_stale_review_never_overwrites_a_later_provider_edit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed(client)
    moved_date = (DUE + timedelta(days=1)).isoformat()
    provider = _StaleReviewedWriter(
        {
            "id": "provider-event-1",
            "start_date": moved_date,
            "cancelled": False,
            "provider_revision": '"reviewed-version"',
            "provider_precondition_revision": '"reviewed-version"',
        }
    )
    calendar_sync.set_google_calendar_provider_for_tests(provider)
    finding = _run(seeded["context_ids"])[0]
    candidate = _candidates(seeded["sync_id"])[0]
    monkeypatch.setattr(calendar_sync, "require_recent_step_up", lambda *_a, **_kw: None)
    decision = client.post(
        f"/api/ip/calendar-projections/reconciliation-candidates/{finding.reconciliation_candidate_id}/decision",
        headers=seeded["headers"],
        json={
            "action": "reject",
            "evidence_reference": "matter-note:guarded-provider-restore",
            "expected_snapshot_sha256": candidate.snapshot_sha256,
        },
    )
    assert decision.status_code == 200, decision.text

    from caseops_api.db.models import Company, CompanyMembership

    company_id, membership_id = seeded["context_ids"]
    with get_session_factory()() as session:
        company = session.get(Company, company_id)
        membership = session.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        response = calendar_sync._sync_source_to_provider(
            session,
            context=SessionContext(
                company=company,
                membership=membership,
                user=membership.user,
            ),
            source_type="matter_deadline",
            source_id=seeded["deadline_id"],
            calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
        )

    assert provider.expected_revisions == ['"reviewed-version"']
    assert response.sync.sync_status == CalendarEventSyncStatus.SYNCED
    with get_session_factory()() as session:
        sync = session.get(CalendarEventSync, seeded["sync_id"])
        assert sync is not None
        assert sync.sync_status == CalendarEventSyncStatus.SYNCED
        assert sync.provider_event_id == "provider-event-1"
        assert sync.drift_status == "unknown"
        assert sync.reconciliation_candidate_id is None
        assert sync.reconciliation_snapshot_sha256 is None
        assert sync.reconciliation_provider_revision is None


def test_uj62_exc03_candidate_listing_does_not_disclose_restricted_docket_evidence(
    client: TestClient,
) -> None:
    """A candidate is no alternate route into a restricted docket's calendar."""

    from caseops_api.db.models import Company, CompanyMembership
    from caseops_api.services.calendar_sync import (
        list_ip_calendar_projection_reconciliation_candidates,
    )
    from tests.test_ip_deadline_workflow import _member

    seeded = _seed(client, restricted=True)
    calendar_sync.set_google_calendar_provider_for_tests(_Reader(None))
    assert _run(seeded["context_ids"])[0].reconciliation_candidate_id

    outsider_id, _token = _member(
        client,
        str(seeded["headers"]["Authorization"]).removeprefix("Bearer "),
        name="Candidate outsider",
        email="candidate-outsider@asterlegal.in",
    )
    factory = get_session_factory()
    with factory() as session:
        company = session.get(Company, seeded["context_ids"][0])
        outsider = session.get(CompanyMembership, outsider_id)
        assert company is not None and outsider is not None
        outsider_context = SessionContext(
            company=company,
            membership=outsider,
            user=outsider.user,
        )
        assert (
            list_ip_calendar_projection_reconciliation_candidates(
                session,
                context=outsider_context,
                include_resolved=True,
            )
            == []
        )


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


@pytest.mark.parametrize(
    ("enabled", "expires_at", "grant_entitlement", "expected_reason"),
    [
        (False, "2099-01-01T00:00:00Z", True, "rollout_disabled"),
        (True, "2099-01-01T00:00:00Z", False, "missing_entitlement"),
        (True, "2020-01-01T00:00:00Z", True, "rollout_expired"),
    ],
    ids=["disabled", "unentitled", "expired"],
)
def test_drift_route_fails_closed_before_provider_access(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    expires_at: str,
    grant_entitlement: bool,
    expected_reason: str,
) -> None:
    seeded = _seed(client)
    _set_ip_workspace_entitlement(
        seeded["context_ids"][0],
        enabled=grant_entitlement,
    )
    _set_workspace_rollout(
        monkeypatch,
        enabled=enabled,
        expires_at=expires_at,
    )
    reader = _Reader(
        {"id": "provider-event-1", "start_date": DUE.isoformat(), "cancelled": False}
    )
    calendar_sync.set_google_calendar_provider_for_tests(reader)
    assert _manual_docketing_reason(seeded["context_ids"]) == expected_reason

    response = client.post(
        "/api/ip/calendar-projections/drift-check", headers=seeded["headers"]
    )

    assert response.status_code == 503, response.text
    # The global 5xx handler intentionally masks internal readiness details.
    assert response.json()["detail"] == "Service unavailable"
    assert reader.calls == []
    assert _drift_status(seeded["sync_id"]) == ("unchecked", None)


def test_uj62_exc03_the_drift_check_route_reports_findings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint itself, not only the service behind it.

    Added after the route-coverage gate caught that every drift assertion here
    called the service directly, so the route's capability gate and its
    serialisation were unproven.
    """

    seeded = _seed(client)
    _set_ip_workspace_entitlement(seeded["context_ids"][0], enabled=True)
    _set_workspace_rollout(
        monkeypatch,
        enabled=True,
        expires_at="2099-01-01T00:00:00Z",
    )
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


@pytest.mark.parametrize("winner", ["source", "connection", "actor"])
def test_drift_provider_read_discards_stale_authority_without_open_transaction(
    client: TestClient,
    winner: str,
) -> None:
    from caseops_api.db.models import (
        Company,
        CompanyMembership,
        MatterDeadline,
        MembershipRole,
    )

    seeded = _seed(client)
    company_id, membership_id = seeded["context_ids"]
    worker_sessions: list = []

    class AuthorityChangingReader(_Reader):
        def fetch_event(self, *, token_payload: dict, provider_event_id: str):
            assert worker_sessions
            # The read claim is durable and every row lock is released before
            # the external provider callback begins.
            assert worker_sessions[0].in_transaction() is False
            with get_session_factory()() as concurrent:
                if winner == "source":
                    source = concurrent.get(MatterDeadline, seeded["deadline_id"])
                    assert source is not None
                    source.due_on = source.due_on + timedelta(days=1)
                elif winner == "connection":
                    connection = concurrent.get(
                        UserCalendarConnection,
                        seeded["connection_id"],
                    )
                    assert connection is not None
                    connection.status = CalendarConnectionStatus.REVOKED
                    connection.encrypted_token_ref = None
                else:
                    membership = concurrent.get(CompanyMembership, membership_id)
                    assert membership is not None
                    membership.role = MembershipRole.VIEWER
                concurrent.commit()
            return super().fetch_event(
                token_payload=token_payload,
                provider_event_id=provider_event_id,
            )

    reader = AuthorityChangingReader(
        {
            "id": "provider-event-1",
            "start_date": DUE.isoformat(),
            "cancelled": False,
        }
    )
    calendar_sync.set_google_calendar_provider_for_tests(reader)
    try:
        with get_session_factory()() as worker:
            worker_sessions.append(worker)
            company = worker.get(Company, company_id)
            membership = worker.get(CompanyMembership, membership_id)
            assert company is not None and membership is not None
            context = SessionContext(
                company=company,
                membership=membership,
                user=membership.user,
            )
            assert check_ip_calendar_projection_drift(worker, context=context) == []
        assert reader.calls == ["provider-event-1"]
        assert _drift_status(seeded["sync_id"]) == ("unchecked", None)
    finally:
        calendar_sync.set_google_calendar_provider_for_tests(None)
