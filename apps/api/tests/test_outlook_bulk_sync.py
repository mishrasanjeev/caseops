"""BUG-039 (Hari 2026-05-09) — bounded manual bulk Outlook sync.

Companion to the per-hearing sync covered by
``test_legalworkspace_calendar_sync.py``. Tests live in a dedicated
file so the PR diff is small and the test set stays runnable on its
own. Reuses the same StubOutlookProvider + helpers — keeps fixture
drift impossible.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import CalendarEventSync
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_sync import set_outlook_provider_for_tests
from tests.test_auth_company import bootstrap_company
from tests.test_legalworkspace_calendar_sync import (
    StubOutlookProvider,
    _auth,
    _bootstrap_company,
    _connect_outlook,
    _create_matter,
    _schedule_hearing,
)


# Range that always covers the hearing scheduled by `_schedule_hearing`
# (today + 7 days) without exceeding the bounded-sync 92-day guard.
def _bounded_range() -> dict[str, str]:
    today = date.today()
    return {
        "from": (today - timedelta(days=1)).isoformat(),
        "to": (today + timedelta(days=30)).isoformat(),
    }


def test_outlook_bulk_sync_creates_then_updates_idempotently(
    client: TestClient,
) -> None:
    """First call creates one CalendarEventSync row; second call over the
    same range updates it. ``created`` then ``updated`` accumulate as
    expected; total rows in the DB stay at 1."""
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_outlook(client, token, provider)
        matter = _create_matter(client, token, "BUG-039-BULK")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        first = client.post(
            "/api/calendar/sync/outlook",
            headers=_auth(token),
            json={**_bounded_range()},
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["examined"] == 1
        assert body["created"] == 1
        assert body["updated"] == 0
        assert body["failed"] == 0
        assert body["skipped"] == 0
        assert body["durable_automation"] == "blocked_pending_temporal"
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["source_type"] == "matter_hearing"
        assert item["source_id"] == hearing["id"]
        assert item["sync_status"] == "synced"
        assert item["matter_id"] == matter["id"]
        assert item["provider_event_id"] == "remote-event-1"
        assert item["last_error"] is None

        second = client.post(
            "/api/calendar/sync/outlook",
            headers=_auth(token),
            json={**_bounded_range()},
        )
        assert second.status_code == 200, second.text
        body2 = second.json()
        assert body2["examined"] == 1
        assert body2["created"] == 0
        assert body2["updated"] == 1
        assert body2["items"][0]["sync_status"] == "synced"

        factory = get_session_factory()
        with factory() as session:
            rows = list(session.scalars(select(CalendarEventSync)))
            assert len(rows) == 1
    finally:
        set_outlook_provider_for_tests(None)


def test_outlook_bulk_sync_returns_409_when_no_outlook_connection(
    client: TestClient,
) -> None:
    """Without a connected Outlook account the endpoint must surface
    409 with an actionable message rather than silently exit zero."""
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    response = client.post(
        "/api/calendar/sync/outlook",
        headers=_auth(token),
        json={**_bounded_range()},
    )
    assert response.status_code == 409, response.text


def test_outlook_bulk_sync_rejects_overlong_range(client: TestClient) -> None:
    """Mirror the GET /events range guard — bulk sync MUST stay
    bounded. >92 days returns 400 with an actionable detail."""
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_outlook(client, token, provider)
        response = client.post(
            "/api/calendar/sync/outlook",
            headers=_auth(token),
            json={"from": "2020-01-01", "to": "2025-01-01"},
        )
        assert response.status_code == 400, response.text
        assert "92 days" in response.json()["detail"]
    finally:
        set_outlook_provider_for_tests(None)


def test_outlook_bulk_sync_skips_unsupported_source_types(
    client: TestClient,
) -> None:
    """source_types that aren't ``matter_hearing`` are accepted but
    surfaced as ``skipped`` items with a clear ``skip_reason``. We do
    NOT silently claim 'sync all' when only hearings are wired."""
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_outlook(client, token, provider)
        matter = _create_matter(client, token, "BUG-039-SKIP")
        hearing = _schedule_hearing(client, token, str(matter["id"]))
        response = client.post(
            "/api/calendar/sync/outlook",
            headers=_auth(token),
            json={
                **_bounded_range(),
                "source_types": [
                    "matter_hearing",
                    "matter_task",
                    "matter_deadline",
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["examined"] == 1
        assert body["created"] == 1
        assert body["skipped"] == 2

        skipped = [
            item for item in body["items"] if item["sync_status"] == "skipped"
        ]
        assert {item["source_type"] for item in skipped} == {
            "matter_task",
            "matter_deadline",
        }
        assert all(
            item["skip_reason"] == "source_type_unsupported"
            for item in skipped
        )

        synced = [
            item for item in body["items"] if item["sync_status"] == "synced"
        ]
        assert len(synced) == 1
        assert synced[0]["source_id"] == hearing["id"]
    finally:
        set_outlook_provider_for_tests(None)


def test_outlook_bulk_sync_respects_matter_id_filter_and_tenant_scope(
    client: TestClient,
) -> None:
    """``matter_id`` narrows the loop — hearings on other matters in the
    same tenant are not synced. A different tenant's hearings are
    entirely invisible (visible_matters_filter prevents leakage)."""
    provider = StubOutlookProvider()
    try:
        boot_a = _bootstrap_company(
            client, slug="bug-039-a", email="owner-a@bug-039.example"
        )
        token_a = str(boot_a["access_token"])
        _connect_outlook(client, token_a, provider)
        matter_a1 = _create_matter(client, token_a, "BUG-039-A1")
        matter_a2 = _create_matter(client, token_a, "BUG-039-A2")
        hearing_a1 = _schedule_hearing(client, token_a, str(matter_a1["id"]))
        _schedule_hearing(client, token_a, str(matter_a2["id"]))

        boot_b = _bootstrap_company(
            client, slug="bug-039-b", email="owner-b@bug-039.example"
        )
        token_b = str(boot_b["access_token"])
        _connect_outlook(client, token_b, provider)
        matter_b1 = _create_matter(client, token_b, "BUG-039-B1")
        _schedule_hearing(client, token_b, str(matter_b1["id"]))

        # Tenant A bulk-syncs ONLY matter A1. Must hit 1 hearing,
        # never the A2 hearing or any B hearing.
        response = client.post(
            "/api/calendar/sync/outlook",
            headers=_auth(token_a),
            json={
                **_bounded_range(),
                "matter_id": str(matter_a1["id"]),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["examined"] == 1
        assert body["created"] == 1
        assert body["items"][0]["source_id"] == hearing_a1["id"]
    finally:
        set_outlook_provider_for_tests(None)


def test_outlook_bulk_sync_per_hearing_failure_records_failed_status(
    client: TestClient,
) -> None:
    """A provider failure on one hearing is recorded as ``failed`` on
    that item; the batch summary reflects the failure and persists
    ``last_error`` on the CalendarEventSync row. The single-hearing
    API contract stays unchanged."""
    provider = StubOutlookProvider(fail=True)
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_outlook(client, token, provider)
        matter = _create_matter(client, token, "BUG-039-FAIL")
        _schedule_hearing(client, token, str(matter["id"]))
        response = client.post(
            "/api/calendar/sync/outlook",
            headers=_auth(token),
            json={**_bounded_range()},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["examined"] == 1
        assert body["created"] == 0
        assert body["updated"] == 0
        assert body["failed"] == 1
        item = body["items"][0]
        assert item["sync_status"] == "failed"
        assert item["last_error"] is not None

        factory = get_session_factory()
        with factory() as session:
            rows = list(session.scalars(select(CalendarEventSync)))
            assert len(rows) == 1
            assert rows[0].sync_status == "failed"
            assert rows[0].last_error
    finally:
        set_outlook_provider_for_tests(None)
