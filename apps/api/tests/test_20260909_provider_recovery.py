from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingUsageEvent,
    CompanyMembership,
    Matter,
    ProviderSpendReservation,
    TrackedCasePollRun,
    TrackedCaseProviderOperation,
    TrackedCaseProviderSnapshot,
    TrackedCaseUpdate,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.case_tracking import CaseTrackingSearchRequest
from caseops_api.services.case_tracking import (
    download_case_tracking_source,
    poll_tracked_cases,
    refresh_bookmark,
    search_cases,
)
from caseops_api.services.case_tracking_providers import CaseTrackingProviderError
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_case_tracking import FakeCaseTrackingProvider, _context_from_bootstrap


def _setup_tracking_case(client):
    boot = bootstrap_company(client)
    response = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(str(boot["access_token"])),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "court_name": "Delhi High Court",
            "case_title": "Provider recovery boundary",
        },
    )
    assert response.status_code == 201, response.text
    return boot, response.json(), _context_from_bootstrap(boot)


def test_waiting_provider_cannot_starve_the_caseops_event_loop_or_publish_late_results(
    client, monkeypatch,
):
    from caseops_api.services import case_tracking

    boot, bookmark, _context = _setup_tracking_case(client)
    entered, release = Event(), Event()

    class WaitingProvider(FakeCaseTrackingProvider):
        def get_case_by_cnr(self, *, cnr):
            entered.set()
            assert release.wait(10), "CaseOps did not service the independent request"
            raise CaseTrackingProviderError("Deterministic deadline", response_class="timeout")

    monkeypatch.setattr(case_tracking, "get_case_tracking_provider", WaitingProvider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation = pool.submit(
            client.post, f"/api/case-tracking/bookmarks/{bookmark['id']}/refresh",
            headers=auth_headers(str(boot["access_token"])),
        )
        try:
            assert entered.wait(5), "the provider boundary was not reached"
            started = time.monotonic()
            health = pool.submit(client.get, "/api/health").result(timeout=1)
            assert health.status_code == 200 and health.json() == {"status": "ok"}
            assert time.monotonic() - started < 1
            assert not mutation.done(), "health must complete while the provider is still waiting"
        finally:
            release.set()
        result = mutation.result(timeout=5)
        assert result.status_code == 502, result.text
    assert client.get("/api/health").json() == {"status": "ok"}
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(TrackedCaseUpdate.id))) == 0
        assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0
        assert session.scalar(select(TrackedCaseProviderOperation.status)) == "failed"
        hold = session.scalar(select(ProviderSpendReservation))
        assert hold.status == "reserved" and hold.dispatched_at is not None


def test_running_claim_is_durable_and_overlap_makes_no_second_call(client):
    boot, bookmark, context = _setup_tracking_case(client)
    second_provider = FakeCaseTrackingProvider()
    observed = []

    class OverlapProvider(FakeCaseTrackingProvider):
        def get_case_by_cnr(self, *, cnr):
            with get_session_factory()() as second:
                rows = list(
                    second.scalars(
                        select(TrackedCaseProviderOperation).where(
                            TrackedCaseProviderOperation.status == "running"
                        )
                    )
                )
                assert len(rows) == 1
                assert rows[0].lease_token and rows[0].spend_reservation_id
                second.rollback()
                with pytest.raises(HTTPException) as raised:
                    refresh_bookmark(
                        second,
                        context=context,
                        bookmark_id=bookmark["id"],
                        provider=second_provider,
                        enforce_manual_limit=False,
                    )
                assert raised.value.status_code == 409
            observed.append(True)
            return super().get_case_by_cnr(cnr=cnr)

    with get_session_factory()() as session:
        result = refresh_bookmark(
            session,
            context=context,
            bookmark_id=bookmark["id"],
            provider=OverlapProvider(),
            enforce_manual_limit=False,
        )
        assert result.bookmark.id == bookmark["id"]
    assert observed == [True]
    assert second_provider.refresh_calls == []
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(TrackedCaseProviderOperation.id))) == 1
        assert session.scalar(select(func.count(ProviderSpendReservation.id))) == 1


@pytest.mark.parametrize("change", ["membership", "archive"])
def test_scope_revocation_during_transport_keeps_spend_but_no_operational_output(client, change):
    boot, bookmark, context = _setup_tracking_case(client)

    class RevocationProvider(FakeCaseTrackingProvider):
        def get_case_by_cnr(self, *, cnr):
            if change == "membership":
                with get_session_factory()() as second:
                    membership = second.get(CompanyMembership, context.membership.id)
                    membership.is_active = False
                    second.commit()
            else:
                response = client.patch(
                    f"/api/case-tracking/bookmarks/{bookmark['id']}",
                    headers=auth_headers(str(boot["access_token"])),
                    json={"is_archived": True},
                )
                assert response.status_code == 200, response.text
            return super().get_case_by_cnr(cnr=cnr)

    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as raised:
            refresh_bookmark(
                session,
                context=context,
                bookmark_id=bookmark["id"],
                provider=RevocationProvider(),
                enforce_manual_limit=False,
            )
        assert raised.value.status_code == (403 if change == "membership" else 409)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(TrackedCaseUpdate.id))) == 0
        assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0
        assert session.scalar(select(TrackedCaseProviderOperation.status)) == "cancelled"
        assert (
            session.scalar(
                select(func.count(BillingUsageEvent.id)).where(
                    BillingUsageEvent.provider_key == "ecourtsindia"
                )
            )
            == 1
        )
        assert session.scalar(select(ProviderSpendReservation.status)) == "settled"


def test_worker_loss_recovers_automatically_without_erasing_uncertain_budget(client, monkeypatch):
    boot, bookmark, context = _setup_tracking_case(client)

    class LostWorker(FakeCaseTrackingProvider):
        def get_case_by_cnr(self, *, cnr):
            raise SystemExit("deterministic worker loss after durable claim")

    with get_session_factory()() as session:
        with pytest.raises(SystemExit):
            refresh_bookmark(
                session,
                context=context,
                bookmark_id=bookmark["id"],
                provider=LostWorker(),
                enforce_manual_limit=False,
            )
    with get_session_factory()() as session:
        operation = session.scalar(select(TrackedCaseProviderOperation))
        assert operation.status == "running" and operation.lease_token
        operation.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        reservation = session.get(ProviderSpendReservation, operation.spend_reservation_id)
        assert reservation.dispatched_at is not None
        reservation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        held_cost = reservation.amount_minor
        session.commit()
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with get_session_factory()() as session:
            runs = poll_tracked_cases(session, provider=FakeCaseTrackingProvider())
            assert runs[0].checked_count == 1
            assert runs[0].error_count == 0
            assert runs[0].metadata["recovered_attempt_count"] == 1
        response = client.get("/api/billing/usage", headers=auth_headers(str(boot["access_token"])))
        assert response.status_code == 200, response.text
        rows = {row["provider_key"]: row for row in response.json()["by_provider"]}
        assert rows["ecourtsindia"]["reserved_minor"] == held_cost
        assert rows["ecourtsindia"]["spent_minor"] == 165
        assert rows["ecourtsindia"]["remaining_minor"] == 100000 - held_cost - 165
        with get_session_factory()() as session:
            operations = list(
                session.scalars(
                    select(TrackedCaseProviderOperation).order_by(
                        TrackedCaseProviderOperation.created_at
                    )
                )
            )
            assert [row.status for row in operations] == ["failed", "succeeded"]
            assert operations[1].attempts == 2
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
def test_provider_transport_releases_database_transaction(client, monkeypatch, boundary):
    boot = bootstrap_company(client)
    response = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(str(boot["access_token"])),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "court_name": "Delhi High Court",
            "case_title": "Example Petitioner v Example Respondent",
        },
    )
    assert response.status_code == 201, response.text
    context = _context_from_bootstrap(boot)
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()
    observed = []
    try:
        with get_session_factory()() as session:

            class ProbeProvider(FakeCaseTrackingProvider):
                def refresh_cases(self, *, cnrs):
                    observed.append(("bulk", session.in_transaction()))
                    return super().refresh_cases(cnrs=cnrs)

                def get_case_by_cnr(self, *, cnr):
                    observed.append(("cnr", session.in_transaction()))
                    return super().get_case_by_cnr(cnr=cnr)

            provider = ProbeProvider()
            if boundary == "manual":
                result = refresh_bookmark(
                    session,
                    context=context,
                    bookmark_id=response.json()["id"],
                    provider=provider,
                    enforce_manual_limit=False,
                )
                assert result.bookmark.id == response.json()["id"]
            else:
                runs = poll_tracked_cases(session, provider=provider)
                assert len(runs) == 1
                assert runs[0].checked_count == 1
                assert runs[0].error_count == 0
            assert observed
            assert all(not active for _, active in observed), observed
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("revoke", [False, True])
def test_initial_search_releases_transaction_and_reauthorizes_before_result(client, revoke):
    _boot, _bookmark, context = _setup_tracking_case(client)
    with get_session_factory()() as session:

        class SearchProbe(FakeCaseTrackingProvider):
            def search_cases(self, *, query):
                assert not session.in_transaction()
                if revoke:
                    with get_session_factory()() as second:
                        second.get(CompanyMembership, context.membership.id).is_active = False
                        second.commit()
                return super().search_cases(query=query)

        arguments = dict(
            context=context,
            payload=CaseTrackingSearchRequest(case_number="1/2026", court_code="DLHC"),
            provider=SearchProbe(),
        )
        if revoke:
            with pytest.raises(HTTPException) as raised:
                search_cases(session, **arguments)
            assert raised.value.status_code == 403
        else:
            assert len(search_cases(session, **arguments).results) == 1
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(BillingUsageEvent.estimated_cost_minor).where(
                    BillingUsageEvent.provider_key == "ecourtsindia"
                )
            )
            == 60
        )
        assert session.scalar(select(ProviderSpendReservation.status)) == "settled"


@pytest.mark.parametrize("revoke", [False, True])
def test_source_download_releases_transaction_and_rechecks_access(client, monkeypatch, revoke):
    _boot, bookmark, context = _setup_tracking_case(client)
    with get_session_factory()() as session:
        refreshed = refresh_bookmark(
            session,
            context=context,
            bookmark_id=bookmark["id"],
            provider=FakeCaseTrackingProvider(),
            enforce_manual_limit=False,
        )
        update = refreshed.created_updates[0]
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.example")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "fixture")
    get_settings.cache_clear()
    try:
        with get_session_factory()() as session:

            def handler(request):
                assert not session.in_transaction()
                if revoke:
                    with get_session_factory()() as second:
                        second.get(CompanyMembership, context.membership.id).is_active = False
                        second.commit()
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.4\nretained source\n%%EOF",
                )

            arguments = dict(
                context=context,
                bookmark_id=bookmark["id"],
                update_id=update.id,
                transport=httpx.MockTransport(handler),
            )
            if revoke:
                with pytest.raises(HTTPException) as raised:
                    download_case_tracking_source(session, **arguments)
                assert raised.value.status_code == 403
            else:
                assert download_case_tracking_source(session, **arguments).content.startswith(
                    b"%PDF"
                )
        with get_session_factory()() as session:
            assert (
                session.scalar(
                    select(BillingUsageEvent.estimated_cost_minor).where(
                        BillingUsageEvent.usage_type == "case_tracking_source_download"
                    )
                )
                == 375
            )
    finally:
        get_settings.cache_clear()


def test_disposal_during_provider_transport_wins_without_new_children(client):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Concurrent disposal",
            "matter_code": "PROVIDER-DISPOSE",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    matter = response.json()
    created = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "court_name": "Delhi High Court",
            "case_title": "Concurrent disposal",
            "matter_id": matter["id"],
        },
    )
    assert created.status_code == 201, created.text
    context = _context_from_bootstrap(boot)
    with get_session_factory()() as session:

        class DisposalProvider(FakeCaseTrackingProvider):
            def get_case_by_cnr(self, *, cnr):
                assert not session.in_transaction()
                disposed = client.patch(
                    f"/api/matters/{matter['id']}/lifecycle/status",
                    headers=headers,
                    json={
                        "to_status": "disposed",
                        "expected_from_status": "active",
                        "expected_updated_at": matter["updated_at"],
                        "reason": "Final disposal while provider waits",
                    },
                )
                assert disposed.status_code == 200, disposed.text
                return super().get_case_by_cnr(cnr=cnr)

        with pytest.raises(HTTPException) as raised:
            refresh_bookmark(
                session,
                context=context,
                bookmark_id=created.json()["id"],
                provider=DisposalProvider(),
                enforce_manual_limit=False,
            )
        assert raised.value.status_code == 409
    with get_session_factory()() as session:
        stored = session.get(Matter, matter["id"])
        assert str(stored.status) == "disposed" and stored.is_active is False
        assert session.scalar(select(func.count(TrackedCaseUpdate.id))) == 0
        assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0
        assert session.scalar(select(TrackedCaseProviderOperation.status)) == "cancelled"


def test_scheduler_worker_loss_does_not_leave_a_permanently_running_poll(client, monkeypatch):
    _setup_tracking_case(client)
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()

    class LostWorker(FakeCaseTrackingProvider):
        def refresh_cases(self, *, cnrs):
            raise SystemExit("deterministic scheduled worker loss")

    try:
        with get_session_factory()() as session:
            with pytest.raises(SystemExit):
                poll_tracked_cases(session, provider=LostWorker())
        with get_session_factory()() as session:
            old = session.scalar(select(TrackedCasePollRun))
            assert old.status == "running"
            old_id = old.id
            old.started_at = datetime.now(UTC) - timedelta(minutes=4)
            operation = session.scalar(select(TrackedCaseProviderOperation))
            operation.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        with get_session_factory()() as session:
            current = poll_tracked_cases(session, provider=FakeCaseTrackingProvider())[0]
            assert current.checked_count == 1 and current.error_count == 0
            previous = session.get(TrackedCasePollRun, old_id)
            assert previous.status == "interrupted" and previous.completed_at is not None
            assert previous.metadata_json["counters_complete"] is False
            assert previous.metadata_json["operation_recovery"] == "automatic"
            assert (
                session.scalar(
                    select(func.count(TrackedCasePollRun.id)).where(
                        TrackedCasePollRun.status == "running"
                    )
                )
                == 0
            )
    finally:
        get_settings.cache_clear()
