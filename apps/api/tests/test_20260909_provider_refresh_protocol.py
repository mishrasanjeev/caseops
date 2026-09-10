from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingUsageEvent, ProviderSpendReservation, TrackedCase
from caseops_api.db.session import get_session_factory
from caseops_api.services import case_tracking
from caseops_api.services.case_tracking_providers import EcourtsIndiaApiProvider
from tests.test_20260909_provider_recovery import _setup_tracking_case
from tests.test_auth_company import auth_headers
from tests.test_case_tracking import FakeCaseTrackingProvider

CNR = "DLHC010012342026"


def test_queued_refresh_recovers_without_repurchase_or_stale_hearing(client, monkeypatch):
    _boot, bookmark, _context = _setup_tracking_case(client)
    base = datetime.now(UTC)
    phase = "NOT_REQUESTED"
    paths = []
    active_session = None

    def handler(request):
        assert active_session is not None and not active_session.in_transaction()
        paths.append(request.url.path)
        if request.url.path.endswith("/bulk-refresh-status"):
            assert json.loads(request.content) == {"cnrs": [CNR]}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {
                                "cnr": CNR,
                                "status": phase,
                                "requestedAt": base.isoformat(),
                            }
                        ]
                    }
                },
            )
        if request.url.path.endswith("/refresh"):
            assert phase == "NOT_REQUESTED"
            return httpx.Response(202, json={"data": {"cnr": CNR, "status": "QUEUED"}})
        assert phase == "COMPLETED", "A pending scrape must not fetch stale details."
        return httpx.Response(
            200,
            json={
                "data": {
                    "courtCaseData": {
                        "cnr": CNR,
                        "registrationNumber": "1/2026",
                        "courtName": "Delhi High Court",
                        "petitioners": ["Verified petitioner"],
                        "respondents": ["Verified respondent"],
                        "nextHearingDate": (base + timedelta(days=10)).date().isoformat(),
                    }
                }
            },
        )

    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()
    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid", token="fixture", transport=httpx.MockTransport(handler)
    )
    try:
        for offset, expected_spend in ((0, 15), (3, 15), (6, 165)):
            phase = ("NOT_REQUESTED", "PENDING", "COMPLETED")[offset // 3]
            monkeypatch.setattr(
                case_tracking, "_now", lambda offset=offset: base + timedelta(minutes=offset)
            )
            with get_session_factory()() as session:
                active_session = session
                runs = case_tracking.poll_tracked_cases(session, provider=provider)
                assert runs[0].error_count == 0
                assert runs[0].checked_count == (1 if phase == "COMPLETED" else 0)
                assert runs[0].backlog_remaining_count == (0 if phase == "COMPLETED" else 1)
                tracked = session.get(TrackedCase, bookmark["tracked_case"]["id"])
                assert (
                    tracked.last_provider_successful_at is not None
                    if phase == "COMPLETED"
                    else tracked.last_provider_successful_at is None
                )
                assert (
                    session.scalar(
                        select(
                            func.coalesce(func.sum(BillingUsageEvent.estimated_cost_minor), 0)
                        ).where(BillingUsageEvent.provider_key == "ecourtsindia")
                    )
                    == expected_spend
                )
                assert (
                    session.scalar(
                        select(func.count(ProviderSpendReservation.id)).where(
                            ProviderSpendReservation.status == "reserved"
                        )
                    )
                    == 0
                )
        assert sum(path.endswith("/refresh") for path in paths) == 1
        assert sum(path.endswith("/bulk-refresh-status") for path in paths) == 3
        assert sum(path.endswith(CNR) for path in paths) == 1
        with get_session_factory()() as session:
            active_session = session
            last = case_tracking.poll_tracked_cases(session, provider=provider)
            assert last[0].checked_count == 0 and last[0].backlog_remaining_count == 0
        assert len(paths) == 5
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"cnr": "other", "status": "PENDING"}],
        [{"cnr": CNR, "status": "NEW_UNKNOWN"}],
        [{"cnr": CNR, "status": {}}],
        [{"cnr": [], "status": "PENDING"}],
    ],
)
def test_incomplete_or_unknown_status_never_purchases_a_refresh(rows):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": {"results": rows}})

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid", token="fixture", transport=httpx.MockTransport(handler)
    )
    result = provider.refresh_cases(cnrs=[CNR])
    assert result.snapshots == []
    assert "[parse_error]" in result.errors[CNR]
    assert result.confirmed_cost_minor_by_cnr == {CNR: 0}
    assert result.uncertain_charge_cnrs == set()
    assert paths == ["/api/partner/case/bulk-refresh-status"]


def test_bulk_receipt_preserves_accepted_and_invalid_identities():
    cnrs = [CNR, "DLHC010012352026"]
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/bulk-refresh-status"):
            return httpx.Response(
                200,
                json={
                    "data": {"results": [{"cnr": cnr, "status": "NOT_REQUESTED"} for cnr in cnrs]}
                },
            )
        assert request.url.path.endswith("/bulk-refresh")
        return httpx.Response(
            200, json={"data": {"refreshed": [], "queued": [CNR], "invalid": [cnrs[1]]}}
        )

    result = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid", token="fixture", transport=httpx.MockTransport(handler)
    ).refresh_cases(cnrs=cnrs)
    assert result.confirmed_cost_minor_by_cnr == {CNR: 15, cnrs[1]: 0}
    assert result.uncertain_charge_cnrs == set()
    assert "[provider_pending]" in result.errors[CNR]
    assert "[case_not_found]" in result.errors[cnrs[1]]
    assert result.snapshots == [] and len(paths) == 2


def test_nightly_continuation_caps_raw_batch_and_finishes_remaining_case(client, monkeypatch):
    boot, _bookmark, _context = _setup_tracking_case(client)
    for index in range(50):
        created = client.post(
            "/api/case-tracking/bookmarks",
            headers=auth_headers(str(boot["access_token"])),
            json={
                "provider": "ecourtsindia",
                "cnr_number": f"DLHC{90000000 + index:08d}2026",
                "court_name": "Delhi High Court",
                "case_title": f"Nightly continuation {index}",
            },
        )
        assert created.status_code == 201, created.text
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_POLL_LIMIT", "500")
    get_settings.cache_clear()
    provider = FakeCaseTrackingProvider()
    try:
        for checked, backlog in ((50, 1), (1, 0), (0, 0)):
            with get_session_factory()() as session:
                run = case_tracking.poll_tracked_cases(session, provider=provider)[0]
                assert run.checked_count == checked and run.backlog_remaining_count == backlog
                assert run.error_count == 0
        assert [len(batch) for batch in provider.bulk_refresh_calls] == [50, 1]
        assert len(provider.refresh_calls) == len(set(provider.refresh_calls)) == 51
    finally:
        get_settings.cache_clear()
