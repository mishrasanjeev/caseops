from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CaseTrackingSupportMatrix,
    Matter,
    MatterNextHearingSuggestion,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseProviderOperation,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import (
    _tracked_case_identity_key,
    _validated_sync_snapshot,
    poll_tracked_cases,
)
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    ProviderBulkRefreshResult,
    ProviderCaseEvent,
    ProviderCaseSnapshot,
    _snapshot_from_payload,
)
from tests.test_auth_company import auth_headers, bootstrap_company


class DatedSyncProvider:
    provider_key = "ecourtsindia"
    transport = object()

    def __init__(self, snapshot: ProviderCaseSnapshot, *, search_results=None) -> None:
        self.snapshot = snapshot
        self.search_results = search_results
        self.bulk_calls: list[list[str]] = []
        self.search_calls: list[CaseSearchQuery] = []

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        return self.snapshot

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        self.search_calls.append(query)
        return list(self.search_results if self.search_results is not None else [self.snapshot])

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        self.bulk_calls.append(list(cnrs))
        return ProviderBulkRefreshResult(snapshots=[self.snapshot])


class FailingDatedSyncProvider(DatedSyncProvider):
    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        self.bulk_calls.append(list(cnrs))
        return ProviderBulkRefreshResult(
            snapshots=[],
            errors={cnr: "Provider temporarily unavailable. [timeout]" for cnr in cnrs},
        )


def _enable_tracking(monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.test")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "test-only")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_AUTO_LINK_LIMIT", "50")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        support = session.scalar(
            select(CaseTrackingSupportMatrix).where(
                CaseTrackingSupportMatrix.provider == "ecourtsindia",
                CaseTrackingSupportMatrix.court == "*",
            )
        )
        if support is None:
            support = CaseTrackingSupportMatrix(
                provider="ecourtsindia",
                court="*",
                bench_jurisdiction="All provider-published courts",
                lookup_method="cnr_or_case_number",
            )
        support.legal_tos_status = "approved"
        support.enabled = True
        support.tenant_visible = True
        session.add(support)
        session.commit()


def _create_older_matter(
    client: TestClient,
    *,
    token: str,
    code: str,
    cnr: str | None = "DLHC010091232026",
    next_hearing_on: date | None = None,
    manual_lock: bool = False,
) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Automatic next hearing {code}",
            "matter_code": code,
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "case_number": "WP(C) 9123/2026",
            "cnr_number": cnr,
            "next_hearing_on": next_hearing_on.isoformat() if next_hearing_on else None,
            "next_hearing_manual_lock": manual_lock,
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _future_snapshot(*, hearing_on: date | None, metadata=None) -> ProviderCaseSnapshot:
    return ProviderCaseSnapshot(
        provider="ecourtsindia",
        cnr_number="DLHC010091232026",
        case_number="WP(C) 9123/2026",
        court_code="DLHC",
        court_name="Delhi High Court",
        case_title="Petitioner v Respondent",
        current_status="Pending",
        next_hearing_on=hearing_on,
        metadata=metadata or {},
    )


def test_older_matter_is_backfilled_synced_and_idempotent_without_reopening(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    previous = datetime.now(UTC).date() + timedelta(days=2)
    matter_id = _create_older_matter(
        client,
        token=token,
        code="AUTO-NHD-OLD-001",
        next_hearing_on=previous,
    )
    _enable_tracking(monkeypatch)
    upcoming = datetime.now(UTC).date() + timedelta(days=14)
    provider = DatedSyncProvider(_future_snapshot(hearing_on=upcoming))

    try:
        with get_session_factory()() as session:
            first = poll_tracked_cases(session, provider=provider, force=True)
            assert len(first) == 1
            assert first[0].checked_count == 1
            assert first[0].metadata["auto_link_backfill"]["linked_count"] == 1
            matter = session.get(Matter, matter_id)
            assert matter is not None
            assert matter.next_hearing_on == upcoming
            assert matter.status == "intake"
            assert matter.is_active is True
            assert matter.lifecycle_version == 0
            assert session.scalar(select(func.count(TrackedCaseBookmark.id))) == 1
            assert session.scalar(select(func.count(MatterNextHearingSuggestion.id))) == 0

            tracked = session.scalar(select(TrackedCase))
            assert tracked is not None
            tracked.next_provider_refresh_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
            second = poll_tracked_cases(session, provider=provider, force=True)
            assert second[0].checked_count == 1
            assert second[0].update_count == 0
            assert session.scalar(select(func.count(TrackedCaseBookmark.id))) == 1
            matter = session.get(Matter, matter_id)
            assert matter is not None
            assert matter.next_hearing_on == upcoming
            assert matter.status == "intake"
            assert matter.lifecycle_version == 0
        assert len(provider.bulk_calls) == 2
    finally:
        get_settings.cache_clear()


def test_automatic_backfill_requires_an_approved_support_scope(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    _create_older_matter(client, token=token, code="AUTO-NHD-SCOPE-001")
    _enable_tracking(monkeypatch)
    provider = DatedSyncProvider(
        _future_snapshot(hearing_on=datetime.now(UTC).date() + timedelta(days=8))
    )

    try:
        with get_session_factory()() as session:
            support = session.scalar(select(CaseTrackingSupportMatrix))
            assert support is not None
            support.legal_tos_status = "pending"
            session.commit()
            runs = poll_tracked_cases(session, provider=provider, force=True)
            assert len(runs) == 1
            assert runs[0].checked_count == 0
            assert runs[0].provider_call_count == 0
            assert runs[0].metadata["auto_link_backfill"]["blocked_count"] == 1
            assert session.scalar(select(func.count(TrackedCase.id))) == 0
            assert session.scalar(select(func.count(TrackedCaseBookmark.id))) == 0
            assert provider.bulk_calls == []
    finally:
        get_settings.cache_clear()


def test_nearest_upcoming_date_wins_and_past_dates_are_never_applied() -> None:
    today = datetime.now(UTC).date()
    tracked = TrackedCase(
        company_id="company",
        provider="ecourtsindia",
        identity_key="cnr:DLHC010091232026",
        cnr_number="DLHC010091232026",
        case_title="Tracked",
    )
    raw = _future_snapshot(hearing_on=today + timedelta(days=20))
    raw = ProviderCaseSnapshot(
        **{
            **raw.__dict__,
            "hearings": [
                ProviderCaseEvent("past", "Past", today - timedelta(days=1)),
                ProviderCaseEvent("near", "Near", today + timedelta(days=5)),
                ProviderCaseEvent("far", "Far", today + timedelta(days=30)),
            ],
        }
    )
    resolved = _validated_sync_snapshot(tracked, [raw])
    assert resolved.next_hearing_on == today + timedelta(days=5)
    assert resolved.metadata["next_hearing_resolution"]["candidate_count"] == 3

    only_past = ProviderCaseSnapshot(
        **{
            **raw.__dict__,
            "next_hearing_on": today - timedelta(days=2),
            "hearings": [ProviderCaseEvent("past", "Past", today - timedelta(days=1))],
        }
    )
    rejected = _validated_sync_snapshot(tracked, [only_past])
    assert rejected.next_hearing_on is None
    assert rejected.metadata["next_hearing_resolution"]["state"] == "unavailable"


@pytest.mark.parametrize(("manual_lock", "expected_cleared"), [(False, True), (True, False)])
def test_confirmed_absence_clears_unlocked_date_but_respects_manual_lock(
    client: TestClient,
    monkeypatch,
    manual_lock: bool,
    expected_cleared: bool,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    existing = datetime.now(UTC).date() + timedelta(days=9)
    matter_id = _create_older_matter(
        client,
        token=token,
        code=f"AUTO-NHD-EMPTY-{'LOCKED' if manual_lock else 'UNLOCKED'}",
        next_hearing_on=existing,
        manual_lock=manual_lock,
    )
    _enable_tracking(monkeypatch)
    provider = DatedSyncProvider(
        _future_snapshot(
            hearing_on=None,
            metadata={"next_hearing_evidence": {"state": "confirmed_absent"}},
        )
    )

    try:
        with get_session_factory()() as session:
            run = poll_tracked_cases(session, provider=provider, force=True)[0]
            assert run.checked_count == 1
            matter = session.get(Matter, matter_id)
            assert matter is not None
            assert (matter.next_hearing_on is None) is expected_cleared
            if not expected_cleared:
                assert matter.next_hearing_on == existing
            assert matter.next_hearing_manual_lock is manual_lock
            assert matter.status == "intake"
            assert session.scalar(select(func.count(MatterNextHearingSuggestion.id))) == 0
    finally:
        get_settings.cache_clear()


def test_provider_failure_retains_last_valid_date_and_lifecycle(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    existing = datetime.now(UTC).date() + timedelta(days=9)
    matter_id = _create_older_matter(
        client,
        token=token,
        code="AUTO-NHD-FAILURE-RETENTION",
        next_hearing_on=existing,
    )
    _enable_tracking(monkeypatch)
    provider = FailingDatedSyncProvider(_future_snapshot(hearing_on=None))

    try:
        with get_session_factory()() as session:
            run = poll_tracked_cases(session, provider=provider, force=True)[0]
            assert run.error_count == 1
            assert run.checked_count == 0
            matter = session.get(Matter, matter_id)
            assert matter is not None
            assert matter.next_hearing_on == existing
            assert matter.status == "intake"
            assert matter.is_active is True
            assert matter.lifecycle_version == 0
            operation = session.scalar(select(TrackedCaseProviderOperation))
            assert operation is not None
            assert operation.response_class == "timeout"
    finally:
        get_settings.cache_clear()


def test_disposed_matter_is_not_backfilled_polled_or_reopened(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_id = _create_older_matter(
        client,
        token=token,
        code="AUTO-NHD-DISPOSED",
        next_hearing_on=datetime.now(UTC).date() + timedelta(days=4),
    )
    read = client.get(f"/api/matters/{matter_id}", headers=auth_headers(token))
    assert read.status_code == 200, read.text
    disposed = client.patch(
        f"/api/matters/{matter_id}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": "disposed",
            "expected_from_status": "intake",
            "expected_updated_at": read.json()["updated_at"],
            "reason": "Court matter finally disposed",
        },
    )
    assert disposed.status_code == 200, disposed.text
    lifecycle_version = disposed.json()["lifecycle_version"]
    _enable_tracking(monkeypatch)
    provider = DatedSyncProvider(
        _future_snapshot(hearing_on=datetime.now(UTC).date() + timedelta(days=10))
    )

    try:
        with get_session_factory()() as session:
            run = poll_tracked_cases(session, provider=provider, force=True)[0]
            assert run.checked_count == 0
            assert provider.bulk_calls == []
            assert session.scalar(select(func.count(TrackedCaseBookmark.id))) == 0
            matter = session.get(Matter, matter_id)
            assert matter is not None
            assert matter.status == "disposed"
            assert matter.is_active is False
            assert matter.lifecycle_version == lifecycle_version
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("snapshots", "response_class"),
    [
        ([], "case_not_found"),
        (
            [
                _future_snapshot(hearing_on=date(2099, 1, 1)),
                _future_snapshot(hearing_on=date(2099, 1, 2)),
            ],
            "ambiguous_match",
        ),
        (
            [
                ProviderCaseSnapshot(
                    provider="ecourtsindia",
                    cnr_number=None,
                    case_number="DIFFERENT/2026",
                    court_code="DLHC",
                    court_name="Delhi High Court",
                    case_title="Different",
                )
            ],
            "match_validation_failed",
        ),
    ],
)
def test_case_number_fallback_requires_exactly_one_verified_match(
    snapshots: list[ProviderCaseSnapshot],
    response_class: str,
) -> None:
    tracked = TrackedCase(
        company_id="company",
        provider="ecourtsindia",
        identity_key="case:WP(C) 9123/2026|court:DLHC",
        case_number="WP(C) 9123/2026",
        court_code="DLHC",
        court_name="Delhi High Court",
        case_title="Tracked",
    )
    with pytest.raises(CaseTrackingProviderError) as raised:
        _validated_sync_snapshot(tracked, snapshots)
    assert raised.value.response_class == response_class


def test_provider_explicit_empty_next_date_is_confirmed_absent() -> None:
    snapshot = _snapshot_from_payload(
        {
            "data": {
                "courtCaseData": {
                    "cnr": "DLHC010091232026",
                    "caseNumber": "WP(C) 9123/2026",
                    "cnrCourtCode": "DLHC",
                    "nextHearingDate": "",
                    "historyOfCaseHearings": [],
                }
            }
        },
        provider="ecourtsindia",
    )
    assert snapshot.next_hearing_on is None
    assert snapshot.metadata["next_hearing_evidence"]["state"] == "confirmed_absent"


def test_non_cnr_identity_uses_court_name_and_never_collapses_distinct_courts() -> None:
    delhi = _tracked_case_identity_key(
        cnr_number=None,
        case_number="CS 10/2026",
        court_code=None,
        court_name="Delhi High Court",
    )
    bombay = _tracked_case_identity_key(
        cnr_number=None,
        case_number="CS 10/2026",
        court_code=None,
        court_name="Bombay High Court",
    )
    assert delhi != bombay
    assert "UNKNOWN" not in delhi


def test_database_allows_only_one_running_refresh_per_tracked_case(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    with get_session_factory()() as session:
        tracked = TrackedCase(
            company_id=company_id,
            provider="ecourtsindia",
            identity_key="cnr:DLHC010099992026",
            cnr_number="DLHC010099992026",
            case_title="Concurrent guard",
        )
        session.add(tracked)
        session.flush()
        session.add(
            TrackedCaseProviderOperation(
                company_id=company_id,
                tracked_case_id=tracked.id,
                provider="ecourtsindia",
                operation_type="manual",
                correlation_id="first-running",
                status="running",
            )
        )
        session.commit()
        session.add(
            TrackedCaseProviderOperation(
                company_id=company_id,
                tracked_case_id=tracked.id,
                provider="ecourtsindia",
                operation_type="scheduled",
                correlation_id="second-running",
                status="running",
            )
        )
        with pytest.raises(Exception, match="uq_tracking_operation_one_running|UNIQUE"):
            session.commit()
