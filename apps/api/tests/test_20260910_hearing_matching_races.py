"""The same forced transport boundaries run on SQLite and isolated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    ProviderSpendReservation,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseProviderOperation,
    TrackedCaseProviderSnapshot,
    TrackedCaseUpdate,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import poll_tracked_cases, refresh_bookmark
from caseops_api.services.case_tracking_providers import ProviderCaseEvent
from tests.test_20260904_auto_next_hearing_sync import DatedSyncProvider, _enable_tracking
from tests.test_20260910_hearing_matching import snapshot
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_case_tracking import _context_from_bootstrap


def setup_case(client, monkeypatch, *, mode="case_number"):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    # Establish a genuine legacy fixture without setup-created child bookmarks.
    with monkeypatch.context() as fixture_policy:
        fixture_policy.setenv("CASEOPS_CASE_TRACKING_ENABLED", "false")
        get_settings.cache_clear()
        response = client.post(
            "/api/matters/",
            headers=headers,
            json={
                "title": "September 10 matching",
                "matter_code": "MATCH-SEP10",
                "practice_area": "litigation",
                "forum_level": "high_court",
                "status": "active",
                "court_name": "Delhi High Court",
                "client_name": "Example Petitioner",
                "opposing_party": "Example Respondent",
                **(
                    {"filing_number": "321/2026"}
                    if mode == "filing_number"
                    else {"case_number": "WP(C) 9123/2026"}
                ),
            },
        )
        assert response.status_code == 200, response.text
        with get_session_factory()() as session:
            assert session.scalar(select(func.count(TrackedCaseBookmark.id))) == 0
    get_settings.cache_clear()
    _enable_tracking(monkeypatch)
    return boot, headers, response.json()


def exercise_boundary(client, monkeypatch, boundary, change):
    from caseops_api.services import case_tracking

    boot, headers, matter = setup_case(client, monkeypatch)
    claim_time = datetime.now(UTC)
    monkeypatch.setattr(case_tracking, "_now", lambda: claim_time)
    created = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "case_number": "WP(C) 9123/2026",
            "court_name": "Delhi High Court",
            "case_title": "September 10 matching",
            "matter_id": matter["id"],
        },
    )
    assert created.status_code == 201, created.text
    bookmark = created.json()
    context = _context_from_bootstrap(boot)
    entered, release = Event(), Event()
    near = date.today() + timedelta(days=7)
    result = replace(
        snapshot(),
        next_hearing_on=near + timedelta(days=7),
        hearings=[
            ProviderCaseEvent(
                source_record_key="nearest", title="Confirmed hearing", event_date=near
            ),
        ],
    )
    calls = []

    def worker():
        with get_session_factory()() as session:

            class WaitingProvider(DatedSyncProvider):
                def search_cases(self, *, query):
                    assert not session.in_transaction()
                    calls.append(query)
                    entered.set()
                    assert release.wait(15), "Independent writer did not complete during transport"
                    return [self.snapshot]

            provider = WaitingProvider(result)
            if boundary == "scheduled":
                return poll_tracked_cases(session, provider=provider, force=True)
            try:
                return refresh_bookmark(
                    session,
                    context=context,
                    bookmark_id=bookmark["id"],
                    provider=provider,
                    enforce_manual_limit=False,
                )
            except HTTPException as error:
                return error

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        try:
            assert entered.wait(15), "No provider boundary was reached"
            with get_session_factory()() as observer:
                claim = observer.scalar(select(TrackedCaseProviderOperation))
                assert (
                    claim.status == "running" and claim.lease_token and claim.spend_reservation_id
                )
                assert (
                    0
                    < (
                        claim.lease_expires_at.replace(tzinfo=None)
                        - claim.started_at.replace(tzinfo=None)
                    ).total_seconds()
                    <= 180
                )
                hold = observer.get(ProviderSpendReservation, claim.spend_reservation_id)
                assert hold.status == "reserved" and hold.dispatched_at
            if change == "dispose":
                changed = client.patch(
                    f"/api/matters/{matter['id']}/lifecycle/status",
                    headers=headers,
                    json={
                        "to_status": "disposed",
                        "expected_from_status": "active",
                        "expected_updated_at": matter["updated_at"],
                        "reason": "Final disposal during hearing provider wait",
                    },
                )
                assert changed.status_code == 200, changed.text
            elif change in {"case_number", "court_name", "filing_number", "opposing_party"}:
                values = {
                    "case_number": "WP(C) 999/2026",
                    "court_name": "Bombay High Court",
                    "filing_number": "999/2026",
                    "opposing_party": "Changed Respondent",
                }
                changed = client.patch(
                    f"/api/matters/{matter['id']}",
                    headers=headers,
                    json={
                        change: values[change],
                        "expected_updated_at": matter["updated_at"],
                    },
                )
                assert changed.status_code == 200, changed.text
            elif change == "archive":
                changed = client.patch(
                    f"/api/case-tracking/bookmarks/{bookmark['id']}",
                    headers=headers,
                    json={"is_archived": True},
                )
                assert changed.status_code == 200, changed.text
            elif change == "membership":
                with get_session_factory()() as writer:
                    writer.get(CompanyMembership, context.membership.id).is_active = False
                    writer.commit()
            assert not future.done(), "Writer must finish while transport is blocked"
        finally:
            release.set()
        outcome = future.result(timeout=15)
    assert len(calls) == 1 and calls[0].require_complete_results
    with get_session_factory()() as session:
        stored = session.get(Matter, matter["id"])
        operation = session.scalar(select(TrackedCaseProviderOperation))
        hold = session.scalar(select(ProviderSpendReservation))
        assert hold.status == "settled", "A delivered search remains accounted after a denied write"
        if change == "none":
            assert stored.next_hearing_on == near
            assert str(stored.status) == "active" and stored.lifecycle_version == 0
            assert operation.status in {"succeeded", "no_change"}
            assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 1
        else:
            assert stored.next_hearing_on is None
            assert str(stored.status) == ("disposed" if change == "dispose" else "active")
            assert stored.lifecycle_version == (1 if change == "dispose" else 0)
            assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0
            assert session.scalar(select(func.count(TrackedCaseUpdate.id))) == 0
            assert operation.status == "cancelled"
            if boundary == "manual":
                assert isinstance(outcome, HTTPException) and outcome.status_code in {403, 409}
    get_settings.cache_clear()


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "case_number",
        "court_name",
        "filing_number",
        "opposing_party",
        "dispose",
        "archive",
        "membership",
    ],
)
def test_source_identity_and_lifecycle_rechecked_after_transport(
    client, monkeypatch, boundary, change
):
    exercise_boundary(client, monkeypatch, boundary, change)


@pytest.mark.parametrize("ambient", ["true", "false"])
@pytest.mark.parametrize("mode", ["case_number", "filing_number"])
def test_scheduled_legacy_discovery_uses_current_identifiers_and_nearest_date(
    client, monkeypatch, ambient, mode
):
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", ambient)
    get_settings.cache_clear()
    _boot, headers, matter = setup_case(client, monkeypatch, mode=mode)
    nearest = date.today() + timedelta(days=7)
    provider = DatedSyncProvider(
        replace(
            snapshot(),
            next_hearing_on=nearest + timedelta(days=14),
            hearings=[
                ProviderCaseEvent(
                    source_record_key="nearest", title="Confirmed hearing", event_date=nearest
                ),
            ],
        )
    )
    with get_session_factory()() as session:
        poll_tracked_cases(session, provider=provider, force=True)
    read = client.get(f"/api/matters/{matter['id']}", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["next_hearing_on"] == nearest.isoformat()
    assert read.json()["lifecycle_version"] == 0 and read.json()["status"] == "active"
    assert len(provider.search_calls) == 1
    get_settings.cache_clear()


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
@pytest.mark.parametrize("defect", ["missing_court", "malformed_cnr"])
def test_legacy_bookmark_requires_court_and_recovers_from_current_matter(
    client, monkeypatch, boundary, defect
):
    from caseops_api.services import case_tracking

    boot, headers, matter = setup_case(client, monkeypatch)
    created = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "case_number": "WP(C) 9123/2026",
            "court_name": "Delhi High Court",
            "case_title": "Legacy automatic bookmark",
            "matter_id": matter["id"],
        },
    )
    assert created.status_code == 201, created.text
    bookmark = created.json()
    with get_session_factory()() as session:
        stored_matter = session.get(Matter, matter["id"])
        tracking = session.get(TrackedCase, bookmark["tracked_case_id"])
        if defect == "missing_court":
            stored_matter.court_name = None
            tracking.court_name = None
        else:
            stored_matter.cnr_number = "UNKNOWN"
            tracking.cnr_number = "UNKNOWN"
        tracking.metadata_json = {"source": "matter_create_auto_link"}
        session.commit()
    provider = DatedSyncProvider(
        replace(snapshot(), next_hearing_on=date.today() + timedelta(days=7))
    )
    monkeypatch.setattr(case_tracking, "get_case_tracking_provider", lambda: provider)
    before = client.get("/api/case-tracking/bookmarks", headers=headers)
    assert before.status_code == 200, before.text
    old = before.json()["bookmarks"][0]
    assert old["tracked_case"]["manual_refresh_allowed"] is False
    assert "Add the court" in old["tracked_case"]["manual_refresh_disabled_reason"]
    rejected = client.post(
        f"/api/case-tracking/bookmarks/{bookmark['id']}/refresh", headers=headers
    )
    assert rejected.status_code == 409, rejected.text
    with get_session_factory()() as session:
        poll_tracked_cases(session, provider=provider, force=True)
        assert session.scalar(select(func.count(TrackedCaseProviderOperation.id))) == 0
        assert session.scalar(select(func.count(ProviderSpendReservation.id))) == 0
    assert provider.search_calls == [] and provider.bulk_calls == []
    current = client.get(f"/api/matters/{matter['id']}", headers=headers).json()
    corrected = client.patch(
        f"/api/matters/{matter['id']}",
        headers=headers,
        json={
            "court_name": "Delhi High Court",
            "cnr_number": None,
            "expected_updated_at": current["updated_at"],
        },
    )
    assert corrected.status_code == 200, corrected.text
    ready = client.get("/api/case-tracking/bookmarks", headers=headers).json()["bookmarks"][0]
    assert ready["id"] == bookmark["id"] and ready["tracked_case"]["manual_refresh_allowed"] is True
    if boundary == "manual":
        refreshed = client.post(
            f"/api/case-tracking/bookmarks/{bookmark['id']}/refresh", headers=headers
        )
        assert refreshed.status_code == 200, refreshed.text
    else:
        with get_session_factory()() as session:
            poll_tracked_cases(session, provider=provider, force=True)
    persisted = client.get(f"/api/matters/{matter['id']}", headers=headers).json()
    assert persisted["next_hearing_on"] == (date.today() + timedelta(days=7)).isoformat()
    assert persisted["status"] == "active" and persisted["lifecycle_version"] == 0
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(TrackedCaseBookmark.id))) == 1
    assert len(provider.search_calls) == 1
    get_settings.cache_clear()
