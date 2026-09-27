"""Automated verification replays fresh stored provider evidence, never stale results.

Automated production runs may not spend provider credits, so the BUG-032 dated
journey could only assert the no-paid rejection: no provider result or matcher
decision existed in production, and the fix had to be confirmed by hand. The
owner chose (2026-09-27) a server-owned verification fixture that the 18:00 IST
scheduled job refreshes at most once a day, and replay of that stored lookup to
automated requests that opt in, provided it is fresh.

These regressions pin both halves:

- the refresh runs only in the window-enforcing scheduled job, makes the exact
  provider request a live CNR search makes, at most once per fixture per
  Asia/Kolkata day (failures included), reserves budget and durably claims the
  work before transport with no transaction open, stores integrity-hashed
  evidence without publishing anything to the tracked case, and is never
  retried by lease recovery;
- replay answers only requests carrying both the automation marker and the
  opt-in, only for the registry fixture in its own tenant and only for a CNR
  lookup, only from evidence retrieved at most 24 hours earlier that no later
  provider answer superseded and whose hashes verify, and through the same
  presentation code as a live lookup. Everything else fails closed with a typed
  reason and never calls the provider.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_HEADER,
    NO_PAID_PROVIDERS_VALUE,
    PROVIDER_REPLAY_HEADER,
    PROVIDER_REPLAY_VALUE,
    provider_replay_requested,
    reset_automated_test_request,
    reset_provider_replay_request,
    set_automated_test_request,
    set_provider_replay_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingUsageEvent,
    CompanyProviderSpendPolicy,
    ProviderSpendReservation,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseProviderOperation,
    TrackedCaseProviderSnapshot,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import case_tracking, case_tracking_verification
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    ProviderBulkRefreshResult,
    ProviderCaseEvent,
    ProviderCaseSnapshot,
)
from caseops_api.services.case_tracking_verification import (
    PROVIDER_VERIFICATION_FIXTURES,
    ProviderVerificationFixture,
    snapshot_from_evidence,
)
from caseops_api.services.hearing_matching import HearingIdentity, reliable_identity
from caseops_api.services.paid_provider_safety import paid_provider_test_tenant_reason
from caseops_api.services.provider_operations import _case_tracking_record
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_case_tracking import (
    ExplodingLiveCaseTrackingProvider,
    FakeCaseTrackingProvider,
    _context_from_bootstrap,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_CNR = "DLHC010317282019"
TENANT = "aster-legal"
# 18:15 Asia/Kolkata, inside the 18:00-20:00 scheduled refresh window.
REFRESHED_AT = datetime(2026, 9, 28, 12, 45, tzinfo=UTC)
DAY = timedelta(days=1)
FIXTURE = ProviderVerificationFixture(
    key="test-bug-032", company_slug=TENANT, provider="ecourtsindia", cnr=FIXTURE_CNR
)
REPLAY_HEADERS = {
    NO_PAID_PROVIDERS_HEADER: NO_PAID_PROVIDERS_VALUE,
    PROVIDER_REPLAY_HEADER: PROVIDER_REPLAY_VALUE,
}


def bug032_snapshot(cnr: str = FIXTURE_CNR) -> ProviderCaseSnapshot:
    """The provider's wording differs from the Matter's; the CNR decides."""

    return ProviderCaseSnapshot(
        provider="ecourtsindia",
        cnr_number=cnr,
        case_number="6209/2019",
        court_code="DLHC01",
        court_name="DLHC",
        case_title="Satish Kumar Mehani v Punjab National Bank & ORS.",
        party_names=["Satish Kumar Mehani", "Punjab National Bank & ORS."],
        current_status="Pending",
        current_stage="AFTER NOTICE MISC. MATTERS",
        next_hearing_on=date(2026, 12, 1),
        orders=[
            ProviderCaseEvent(
                source_record_key="order:2026-09-01",
                title="Order dated 01 Sep 2026",
                event_date=date(2026, 9, 1),
                source_url="https://webapi.ecourtsindia.com/api/partner/case/order-1.pdf",
                text="Directions issued. " * 400,
                metadata={"page_count": 2},
            )
        ],
        hearings=[
            ProviderCaseEvent(
                source_record_key="hearing:2026-12-01",
                title="Listed for hearing",
                event_date=date(2026, 12, 1),
            )
        ],
        source_url="https://webapi.ecourtsindia.com/case/DLHC010317282019",
        metadata={"provider_case_id": "fixture-1"},
        matching_identity=HearingIdentity(
            cnr=cnr,
            case_number="W.P.(C) 6209/2019",
            case_type="W.P.(C)",
            court_code="DLHC01",
            court_name="High Court of Delhi",
            parties=("Satish Kumar Mehani", "Punjab National Bank & ORS."),
            advocates=("R. Counsel",),
        ),
    )


class FixtureProvider(FakeCaseTrackingProvider):
    """A free provider for the scheduled refresh; it must be called outside a transaction."""

    def __init__(self, results=None, *, error: BaseException | None = None) -> None:
        super().__init__()
        self.results = [bug032_snapshot()] if results is None else results
        self.error = error
        self.sessions: list = []
        self.during_call = None

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        self.search_calls.append(query)
        for session in self.sessions:
            assert not session.in_transaction(), "the provider was called inside a transaction"
        if self.during_call is not None:
            self.during_call()
        if self.error is not None:
            raise self.error
        return list(self.results)

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        raise AssertionError("the fixture refresh makes exactly the live CNR search request")

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        raise AssertionError("the fixture refresh never uses bulk refresh")


class LiveEquivalentProvider(FakeCaseTrackingProvider):
    """What a live CNR search returns, reachable only by an allowed (human) request."""

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        self.search_calls.append(query)
        return [bug032_snapshot()]


class Clock:
    def __init__(self, monkeypatch, at: datetime) -> None:
        self.at = at
        monkeypatch.setattr(case_tracking, "_now", lambda: self.at)


def _enable(monkeypatch, fixtures=(FIXTURE,)) -> None:
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://webapi.ecourtsindia.com")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "must-not-be-used")
    get_settings.cache_clear()
    monkeypatch.setattr(
        case_tracking_verification, "PROVIDER_VERIFICATION_FIXTURES", tuple(fixtures)
    )
    # Every HTTP search in this module reaches a live-shaped adapter that fails
    # the test if a provider request is attempted.
    monkeypatch.setattr(
        case_tracking, "get_case_tracking_provider", ExplodingLiveCaseTrackingProvider
    )


def _scheduled_poll(provider, *, at: datetime, clock: Clock, force: bool = False):
    clock.at = at
    with get_session_factory()() as session:
        if isinstance(provider, FixtureProvider):
            provider.sessions = [session]
        return case_tracking.poll_tracked_cases(
            session, provider=provider, enforce_window=not force, force=force, now=at
        )


def _fixture_outcomes(runs, company_id: str) -> list[dict[str, object]]:
    run = next(run for run in runs if run.company_id == company_id)
    return list(run.metadata.get("verification_fixture_refresh") or [])


def _fixture_operations(company_id: str) -> list[TrackedCaseProviderOperation]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(TrackedCaseProviderOperation)
                .where(
                    TrackedCaseProviderOperation.company_id == company_id,
                    TrackedCaseProviderOperation.operation_type == "verification_fixture",
                )
                .order_by(TrackedCaseProviderOperation.started_at)
            )
        )


def _search(client: TestClient, token: str, payload: dict, headers: dict | None = None):
    return client.post(
        "/api/case-tracking/search",
        headers={**auth_headers(token), **(headers or {})},
        json=payload,
    )


def _create_bug032_matter(client: TestClient, token: str, code: str = "BUG-032") -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "SATISH KUMAR MEHANI VS PUNJAB NATIONAL BANK",
            "matter_code": code,
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Satish Kumar Mehani",
            "opposing_party": "Punjab National Bank",
            "case_number": "W.P.(C) 6209/2019",
            "cnr_number": FIXTURE_CNR,
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _audit(company_id: str, action: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id, AuditEvent.action == action)
                .order_by(AuditEvent.created_at)
            )
        )


def _store_evidence(monkeypatch, *, at: datetime = REFRESHED_AT, results=None) -> Clock:
    clock = Clock(monkeypatch, at)
    provider = FixtureProvider(results)
    runs = _scheduled_poll(provider, at=at, clock=clock)
    assert len(provider.search_calls) == 1, runs
    return clock


# --- The registry and its deployment contract ------------------------------------


def test_production_registry_holds_only_the_reported_case_in_a_blocked_qa_workspace():
    assert PROVIDER_VERIFICATION_FIXTURES == (
        ProviderVerificationFixture(
            key="ram-20260926-bug-032",
            company_slug="caseops-qa",
            provider="ecourtsindia",
            cnr="DLHC010317282019",
        ),
    )
    inventory = json.loads(
        (REPO_ROOT / "infra" / "cloudrun" / "scheduler-inventory.json").read_text("utf-8")
    )
    poll_job = next(
        job for job in inventory["jobs"] if job.get("run_job_name") == "caseops-case-tracking-poll"
    )
    blocked = set(
        poll_job["bootstrap"]["environment"]["CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS"].split(
            ";"
        )
    )
    deploy = (REPO_ROOT / "scripts" / "deploy-prod.sh").read_text("utf-8")
    deployed = re.search(r'^PAID_PROVIDER_BLOCKED_COMPANY_SLUGS="([^"]+)"', deploy, re.M)
    assert deployed is not None
    keys = [fixture.key for fixture in PROVIDER_VERIFICATION_FIXTURES]
    assert len(keys) == len(set(keys))
    for fixture in PROVIDER_VERIFICATION_FIXTURES:
        assert reliable_identity(HearingIdentity(cnr=fixture.cnr))
        # Ordinary scheduled polling never spends in the fixture's workspace;
        # the capped fixture refresh is the only unattended paid call there.
        assert fixture.company_slug in blocked
        assert fixture.company_slug in deployed.group(1).split(";")
        workspace = SimpleNamespace(company=SimpleNamespace(slug=fixture.company_slug))
        assert paid_provider_test_tenant_reason(workspace) is not None  # type: ignore[arg-type]


def test_replay_needs_the_automation_marker_as_well_as_the_opt_in():
    for marker, opt_in, expected in (
        (NO_PAID_PROVIDERS_VALUE, PROVIDER_REPLAY_VALUE, True),
        (None, PROVIDER_REPLAY_VALUE, False),
        (NO_PAID_PROVIDERS_VALUE, None, False),
        (NO_PAID_PROVIDERS_VALUE, "fresh", False),
    ):
        marker_token = set_automated_test_request(marker)
        replay_token = set_provider_replay_request(opt_in)
        try:
            assert provider_replay_requested() is expected
        finally:
            reset_provider_replay_request(replay_token)
            reset_automated_test_request(marker_token)


def test_stored_evidence_rebuilds_the_snapshot_the_live_lookup_produced():
    live = bug032_snapshot()
    stored = case_tracking._snapshot_payload(live)
    replayed = snapshot_from_evidence(json.loads(json.dumps(stored)))

    assert case_tracking._search_record(replayed) == case_tracking._search_record(live)
    assert case_tracking._snapshot_matching_identity(
        replayed
    ) == case_tracking._snapshot_matching_identity(live)
    assert replayed.matching_identity == live.matching_identity
    assert replayed.next_hearing_on == live.next_hearing_on
    assert [event.source_record_key for event in replayed.orders] == ["order:2026-09-01"]
    # The stored text is a bounded preview, and the rebuilt event says so.
    assert len(replayed.orders[0].text or "") == 4000
    assert replayed.orders[0].text_truncated is True
    assert replayed.hearings[0].text_truncated is False


# --- The scheduled refresh ---------------------------------------------------------


def test_scheduled_refresh_stores_one_daily_lookup_as_evidence_only(
    client: TestClient, monkeypatch
):
    _enable(monkeypatch)
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    clock = Clock(monkeypatch, REFRESHED_AT)
    provider = FixtureProvider()

    runs = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock)

    assert provider.search_calls == [CaseSearchQuery(cnr_number=FIXTURE_CNR)]
    [outcome] = _fixture_outcomes(runs, company_id)
    assert outcome["outcome"] == "refreshed" and outcome["response_class"] == "success"
    [operation] = _fixture_operations(company_id)
    assert (operation.status, operation.response_class) == ("succeeded", "success")
    assert (operation.attempts, operation.max_attempts, operation.next_attempt_at) == (1, 1, None)
    assert operation.requested_by_membership_id is None
    assert operation.metadata_json["spend_outcome"] == "confirmed_estimate"
    with get_session_factory()() as session:
        tracked = session.get(TrackedCase, operation.tracked_case_id)
        assert tracked.identity_key == f"cnr:{FIXTURE_CNR}"
        assert tracked.metadata_json == {"verification_fixture": "test-bug-032"}
        # Evidence only: nothing is published to the tracked case.
        assert tracked.current_status is None and tracked.next_hearing_on is None
        assert tracked.last_provider_successful_at is None
        assert tracked.last_operation_id is None
        assert tracked.provider_freshness_status == "never_succeeded"
        assert (
            session.scalar(
                select(func.count(TrackedCaseBookmark.id)).where(
                    TrackedCaseBookmark.tracked_case_id == tracked.id
                )
            )
            == 0
        )
        snapshot = session.scalar(
            select(TrackedCaseProviderSnapshot).where(
                TrackedCaseProviderSnapshot.operation_id == operation.id
            )
        )
        assert snapshot is not None and case_tracking._snapshot_hashes_verified(snapshot)
        usage = session.scalars(
            select(BillingUsageEvent).where(BillingUsageEvent.company_id == company_id)
        ).all()
        assert [(item.usage_type, item.estimated_cost_minor) for item in usage] == [
            ("case_tracking_verification_fixture", operation.cost_minor)
        ]
        assert operation.cost_minor >= 150
        assert (
            session.scalar(
                select(func.count(ProviderSpendReservation.id)).where(
                    ProviderSpendReservation.company_id == company_id,
                    ProviderSpendReservation.status == "reserved",
                )
            )
            == 0
        )
    [audit] = _audit(company_id, "case_tracking.verification_fixture_refresh")
    assert audit.actor_type == "system" and audit.target_id == operation.id

    # Every later execution of the same Asia/Kolkata day is refused before transport.
    for minutes in (5, 70, 104):
        again = _scheduled_poll(provider, at=REFRESHED_AT + timedelta(minutes=minutes), clock=clock)
        assert _fixture_outcomes(again, company_id) == [
            {"fixture_key": "test-bug-032", "outcome": "daily_cap_reached", "calls_today": 1}
        ]
    assert len(provider.search_calls) == 1

    # The next day's window buys exactly one more lookup.
    _scheduled_poll(provider, at=REFRESHED_AT + DAY, clock=clock)
    _scheduled_poll(provider, at=REFRESHED_AT + DAY + timedelta(minutes=5), clock=clock)
    assert len(provider.search_calls) == 2
    assert len(_fixture_operations(company_id)) == 2


def test_only_the_window_enforcing_scheduled_run_refreshes_a_fixture(
    client: TestClient, monkeypatch
):
    _enable(monkeypatch)
    company_id = str(bootstrap_company(client)["company"]["id"])
    clock = Clock(monkeypatch, REFRESHED_AT)
    provider = FixtureProvider()

    # 09:00 IST: the enforcing job records blocked runs and stops early.
    outside = _scheduled_poll(provider, at=datetime(2026, 9, 28, 3, 30, tzinfo=UTC), clock=clock)
    assert outside[0].status == "blocked"
    # Break-glass (--force) and unwindowed local runs never buy the lookup.
    forced = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock, force=True)
    assert _fixture_outcomes(forced, company_id) == [
        {"fixture_key": "test-bug-032", "outcome": "outside_scheduled_window"}
    ]
    with get_session_factory()() as session:
        unwindowed = case_tracking.poll_tracked_cases(session, provider=provider)
    assert _fixture_outcomes(unwindowed, company_id) == [
        {"fixture_key": "test-bug-032", "outcome": "outside_scheduled_window"}
    ]
    assert provider.search_calls == [] and _fixture_operations(company_id) == []


@pytest.mark.parametrize(
    ("error", "response_class", "spend_outcome"),
    [
        (
            CaseTrackingProviderError("deadline", response_class="timeout"),
            "timeout",
            "pending_confirmation",
        ),
        (
            CaseTrackingProviderError(
                "not found", response_class="case_not_found", http_status_code=404
            ),
            "case_not_found",
            "not_charged",
        ),
    ],
)
def test_a_failed_lookup_uses_the_day_and_is_never_retried(
    client: TestClient, monkeypatch, error, response_class, spend_outcome
):
    _enable(monkeypatch)
    company_id = str(bootstrap_company(client)["company"]["id"])
    clock = Clock(monkeypatch, REFRESHED_AT)
    provider = FixtureProvider(error=error)

    runs = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock)
    retry = _scheduled_poll(provider, at=REFRESHED_AT + timedelta(minutes=5), clock=clock)

    assert _fixture_outcomes(runs, company_id)[0]["outcome"] == "failed"
    assert _fixture_outcomes(retry, company_id)[0]["outcome"] == "daily_cap_reached"
    assert len(provider.search_calls) == 1
    [operation] = _fixture_operations(company_id)
    assert (operation.status, operation.response_class) == ("failed", response_class)
    assert operation.metadata_json["spend_outcome"] == spend_outcome
    assert _case_tracking_record_for(operation).retryable is False
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count(BillingUsageEvent.id)).where(
                    BillingUsageEvent.company_id == company_id
                )
            )
            == 0
        )


def _case_tracking_record_for(operation: TrackedCaseProviderOperation):
    with get_session_factory()() as session:
        row = session.get(TrackedCaseProviderOperation, operation.id)
        assert row is not None
        return _case_tracking_record(row)


@pytest.mark.parametrize(
    ("results", "response_class"),
    [
        ([], "case_not_found"),
        ([bug032_snapshot(cnr="DLHC010000012019")], "parse_error"),
        ([bug032_snapshot(), bug032_snapshot()], "parse_error"),
    ],
)
def test_an_answer_that_is_not_exactly_the_fixture_is_billed_but_never_stored(
    client: TestClient, monkeypatch, results, response_class
):
    _enable(monkeypatch)
    company_id = str(bootstrap_company(client)["company"]["id"])
    clock = Clock(monkeypatch, REFRESHED_AT)

    runs = _scheduled_poll(FixtureProvider(results), at=REFRESHED_AT, clock=clock)

    assert _fixture_outcomes(runs, company_id)[0]["response_class"] == response_class
    [operation] = _fixture_operations(company_id)
    assert operation.status == "failed"
    assert operation.metadata_json["spend_outcome"] == "confirmed_estimate"
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0


def test_request_and_process_boundaries_still_refuse_the_fixture_refresh(
    client: TestClient, monkeypatch
):
    _enable(monkeypatch)
    company_id = str(bootstrap_company(client)["company"]["id"])
    clock = Clock(monkeypatch, REFRESHED_AT)
    provider = ExplodingLiveCaseTrackingProvider()

    # A live-shaped adapter inside a pytest process is never reached.
    runs = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock)
    assert _fixture_outcomes(runs, company_id) == [
        {"fixture_key": "test-bug-032", "outcome": "blocked", "reason": "automated_test_process"}
    ]
    # Nor under an automated no-paid request, which is checked first.
    marker = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        marked = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock)
    finally:
        reset_automated_test_request(marker)
    assert _fixture_outcomes(marked, company_id)[0]["reason"] == "automated_test_request"
    assert _fixture_operations(company_id) == []


def test_an_exhausted_budget_refuses_the_lookup_before_any_claim(client: TestClient, monkeypatch):
    _enable(monkeypatch)
    company_id = str(bootstrap_company(client)["company"]["id"])
    with get_session_factory()() as session:
        session.add(
            CompanyProviderSpendPolicy(
                company_id=company_id,
                provider_key="ecourtsindia",
                monthly_limit_minor=100,
                currency="INR",
                policy_source="test_exhausted_budget",
            )
        )
        session.commit()
    clock = Clock(monkeypatch, REFRESHED_AT)
    provider = FixtureProvider()

    runs = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock)

    assert _fixture_outcomes(runs, company_id) == [
        {"fixture_key": "test-bug-032", "outcome": "blocked", "reason": "provider_budget_exhausted"}
    ]
    assert provider.search_calls == [] and _fixture_operations(company_id) == []
    with get_session_factory()() as session:
        # The whole claim rolled back, including a newly created tracked case.
        assert session.scalar(select(func.count(TrackedCase.id))) == 0


def test_lease_recovery_fails_a_lost_attempt_without_touching_the_tracked_case(
    client: TestClient, monkeypatch
):
    _enable(monkeypatch)
    company_id = str(bootstrap_company(client)["company"]["id"])
    clock = Clock(monkeypatch, REFRESHED_AT)
    provider = FixtureProvider()

    def worker_lost_its_lease() -> None:
        clock.at = REFRESHED_AT + timedelta(minutes=4)
        with get_session_factory()() as recovery:
            assert (
                case_tracking._recover_expired_provider_attempts(recovery, company_id=company_id)
                == 1
            )
            recovery.commit()

    provider.during_call = worker_lost_its_lease
    runs = _scheduled_poll(provider, at=REFRESHED_AT, clock=clock)

    assert _fixture_outcomes(runs, company_id)[0]["outcome"] == "lease_lost"
    [operation] = _fixture_operations(company_id)
    assert (operation.status, operation.response_class) == ("failed", "timeout")
    assert operation.metadata_json["lease_expired"] is True
    assert operation.next_attempt_at is None
    assert operation.error_redacted == (
        "Provider worker lease expired; the verification lookup is not retried today."
    )
    assert _case_tracking_record_for(operation).retryable is False
    with get_session_factory()() as session:
        tracked = session.get(TrackedCase, operation.tracked_case_id)
        assert tracked.last_response_class is None and tracked.last_error is None
        assert tracked.next_provider_refresh_at is None
        assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0
    later = _scheduled_poll(provider, at=REFRESHED_AT + timedelta(minutes=10), clock=clock)
    assert _fixture_outcomes(later, company_id)[0]["outcome"] == "daily_cap_reached"
    assert len(provider.search_calls) == 1


def test_a_matter_link_to_the_fixture_case_is_reused_and_left_unchanged(
    client: TestClient, monkeypatch
):
    _enable(monkeypatch)
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    matter_id = _create_bug032_matter(client, str(boot["access_token"]))
    with get_session_factory()() as session:
        bookmark = session.scalar(
            select(TrackedCaseBookmark).where(TrackedCaseBookmark.matter_id == matter_id)
        )
        assert bookmark is not None
        before = session.get(TrackedCase, bookmark.tracked_case_id)
        frozen = {
            column.key: getattr(before, column.key)
            for column in TrackedCase.__table__.columns
            if column.key != "updated_at"
        }
    Clock(monkeypatch, REFRESHED_AT)
    provider = FixtureProvider()

    with get_session_factory()() as session:
        provider.sessions = [session]
        outcomes = case_tracking._refresh_verification_fixtures(
            session,
            context=_context_from_bootstrap(boot),
            active_provider=provider,
            scheduled_window_open=True,
        )

    assert outcomes[0]["outcome"] == "refreshed"
    [operation] = _fixture_operations(company_id)
    with get_session_factory()() as session:
        after = session.get(TrackedCase, operation.tracked_case_id)
        assert after.id == frozen["id"]
        assert {key: getattr(after, key) for key in frozen} == frozen


# --- Replay --------------------------------------------------------------------------


def test_replay_answers_the_reported_search_from_fresh_evidence_like_a_live_lookup(
    client: TestClient, monkeypatch
):
    _enable(monkeypatch)
    boot = bootstrap_company(client)
    token, company_id = str(boot["access_token"]), str(boot["company"]["id"])
    clock = _store_evidence(monkeypatch)
    matter_id = _create_bug032_matter(client, token)
    clock.at = REFRESHED_AT + timedelta(hours=2)
    in_matter = {
        # Exactly what the Case Tracking page sends inside the Matter scope.
        "matter_id": matter_id,
        "query": FIXTURE_CNR,
        "cnr_number": FIXTURE_CNR,
        "case_number": "W.P.(C) 6209/2019",
        "court_code": None,
    }

    replayed = _search(client, token, in_matter, REPLAY_HEADERS)
    replayed_global = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)

    assert replayed.status_code == 200, replayed.text
    assert replayed_global.status_code == 200, replayed_global.text
    [result] = replayed.json()["results"]
    assert result["cnr_number"] == FIXTURE_CNR
    assert result["case_title"] == "Satish Kumar Mehani v Punjab National Bank & ORS."
    assert result["next_hearing_on"] == "2026-12-01"
    # BUG-032: the Matter's own case is recognised, never "Does not match".
    assert result["link_token"] or result["linked_to_matter"]
    [existing] = replayed_global.json()["results"][0]["existing_matters"]
    assert existing["matter_id"] == matter_id
    [operation] = _fixture_operations(company_id)
    with get_session_factory()() as session:
        stored = session.scalar(
            select(TrackedCaseProviderSnapshot).where(
                TrackedCaseProviderSnapshot.operation_id == operation.id
            )
        )
        raw_hash = stored.raw_hash
    assert replayed.json()["replay"] == {
        "status": "served",
        "fixture_key": "test-bug-032",
        "provider_call_performed": False,
        "evidence_captured_at": REFRESHED_AT.isoformat().replace("+00:00", "Z"),
        "evidence_age_seconds": 7200,
        "max_age_seconds": 86400,
        "snapshot_sha256": raw_hash,
    }
    audits = [
        json.loads(event.metadata_json or "{}")
        for event in _audit(company_id, "case_tracking.search_replay")
    ]
    assert sorted(item["matter_scoped"] for item in audits) == [False, True]
    assert {item["provider_call_performed"] for item in audits} == {False}
    assert {item["evidence_operation_id"] for item in audits} == {operation.id}
    with get_session_factory()() as session:
        # Replay spends nothing: the only usage is the scheduled fixture lookup.
        assert session.scalars(
            select(BillingUsageEvent.usage_type).where(BillingUsageEvent.company_id == company_id)
        ).all() == ["case_tracking_verification_fixture"]

    # A person's live search of the same case presents exactly the same result.
    monkeypatch.setattr(case_tracking, "get_case_tracking_provider", LiveEquivalentProvider)
    live = _search(client, token, in_matter)
    live_global = _search(client, token, {"cnr_number": FIXTURE_CNR})
    assert live.status_code == 200 and live_global.status_code == 200, live.text
    assert live.json()["replay"] is None

    def comparable(body: dict) -> list[dict]:
        return [{**item, "link_token": bool(item["link_token"])} for item in body["results"]]

    assert comparable(replayed.json()) == comparable(live.json())
    assert comparable(replayed_global.json()) == comparable(live_global.json())


def test_replay_never_serves_evidence_older_than_24_hours(client: TestClient, monkeypatch):
    _enable(monkeypatch)
    token = str(bootstrap_company(client)["access_token"])
    clock = _store_evidence(monkeypatch)

    clock.at = REFRESHED_AT + DAY
    boundary = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)
    clock.at = REFRESHED_AT + DAY + timedelta(seconds=1)
    stale = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)
    clock.at = REFRESHED_AT - timedelta(seconds=1)
    future = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)

    assert boundary.status_code == 200, boundary.text
    assert boundary.json()["replay"]["evidence_age_seconds"] == 86400
    for response, age in ((stale, 86401), (future, 0)):
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["code"] == "paid_provider_blocked_for_test"
        assert body["reason"] == "automated_test_request"
        assert "no external request was made" in body["detail"]
        assert body["replay"]["status"] == "stale"
        assert body["replay"]["evidence_age_seconds"] == age
        assert "results" not in body


def test_a_later_provider_answer_supersedes_but_an_outage_does_not(client: TestClient, monkeypatch):
    _enable(monkeypatch)
    boot = bootstrap_company(client)
    token, company_id = str(boot["access_token"]), str(boot["company"]["id"])
    clock = _store_evidence(monkeypatch)
    next_day = REFRESHED_AT + DAY - timedelta(minutes=10)  # 18:05 IST, 23h50m later

    outage = FixtureProvider(error=CaseTrackingProviderError("slow", response_class="timeout"))
    _scheduled_poll(outage, at=next_day, clock=clock)
    clock.at = next_day + timedelta(minutes=5)
    after_outage = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)
    assert after_outage.status_code == 200, after_outage.text
    assert after_outage.json()["replay"]["evidence_age_seconds"] == 86100

    # The same situation, but the provider now says the case does not exist.
    with get_session_factory()() as session:
        latest = session.scalars(
            select(TrackedCaseProviderOperation)
            .where(TrackedCaseProviderOperation.company_id == company_id)
            .order_by(TrackedCaseProviderOperation.started_at.desc())
        ).first()
        latest.response_class = "case_not_found"
        session.commit()
    superseded = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)
    assert superseded.status_code == 409, superseded.text
    assert superseded.json()["replay"] == {
        "status": "superseded",
        "fixture_key": "test-bug-032",
        "max_age_seconds": 86400,
        "latest_response_class": "case_not_found",
    }


@pytest.mark.parametrize("tamper", ["body", "hash", "cnr"])
def test_tampered_evidence_is_never_replayed(client: TestClient, monkeypatch, tamper):
    _enable(monkeypatch)
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    clock = _store_evidence(monkeypatch)
    with get_session_factory()() as session:
        stored = session.scalar(select(TrackedCaseProviderSnapshot))
        raw = dict(stored.raw_json)
        if tamper == "body":
            raw["next_hearing_on"] = "2026-10-01"
        elif tamper == "hash":
            stored.raw_hash = "0" * 64
        else:
            raw["cnr_number"] = "DLHC010000012019"
        stored.raw_json = raw
        if tamper == "cnr":
            # Rehashed consistently, yet not the fixture's case.
            stored.raw_hash = case_tracking._hash_value(raw)
        session.commit()
    clock.at = REFRESHED_AT + timedelta(hours=1)

    response = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)

    assert response.status_code == 409, response.text
    assert response.json()["replay"]["status"] == "integrity_failed"


def test_replay_is_confined_to_registered_fixtures_in_their_own_workspace(
    client: TestClient, monkeypatch
):
    other = ProviderVerificationFixture(
        key="test-other", company_slug="second-legal", provider="ecourtsindia", cnr=FIXTURE_CNR
    )
    _enable(monkeypatch, fixtures=(FIXTURE, other))
    token = str(bootstrap_company(client)["access_token"])
    clock = _store_evidence(monkeypatch)
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Legal LLP",
            "company_slug": "second-legal",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondlegal.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert second.status_code == 200, second.text
    second_token = str(second.json()["access_token"])
    clock.at = REFRESHED_AT + timedelta(hours=1)

    cases = [
        # Another workspace never sees this workspace's evidence.
        (second_token, {"cnr_number": FIXTURE_CNR}, "missing"),
        (token, {"cnr_number": "DLHC010000012019"}, "not_a_verification_fixture"),
        (token, {"query": FIXTURE_CNR}, "unsupported_query"),
        (
            token,
            {"case_number": "W.P.(C) 6209/2019", "court_name": "Delhi High Court"},
            "unsupported_query",
        ),
    ]
    for caller, payload, expected in cases:
        response = _search(client, caller, payload, REPLAY_HEADERS)
        assert response.status_code == 409, response.text
        assert response.json()["replay"]["status"] == expected, payload


def test_requests_without_both_headers_keep_the_ordinary_paid_gate(client: TestClient, monkeypatch):
    _enable(monkeypatch)
    token = str(bootstrap_company(client)["access_token"])
    clock = _store_evidence(monkeypatch)
    clock.at = REFRESHED_AT + timedelta(hours=1)

    marker_only = _search(
        client,
        token,
        {"cnr_number": FIXTURE_CNR},
        {NO_PAID_PROVIDERS_HEADER: NO_PAID_PROVIDERS_VALUE},
    )
    opt_in_only = _search(
        client,
        token,
        {"cnr_number": FIXTURE_CNR},
        {PROVIDER_REPLAY_HEADER: PROVIDER_REPLAY_VALUE},
    )

    assert marker_only.status_code == 409, marker_only.text
    assert marker_only.json()["reason"] == "automated_test_request"
    # A person's request is never answered from stored evidence; here the
    # live-shaped adapter is refused only because this is a test process.
    assert opt_in_only.status_code == 409, opt_in_only.text
    assert opt_in_only.json()["reason"] == "automated_test_process"
    assert "replay" not in marker_only.json() and "replay" not in opt_in_only.json()


def test_a_free_provider_is_called_normally_even_when_replay_is_requested(
    client: TestClient, monkeypatch
):
    """The Docker emulator is not a paid host: replay only replaces a refused call."""

    _enable(monkeypatch)
    token = str(bootstrap_company(client)["access_token"])
    provider = LiveEquivalentProvider()
    monkeypatch.setattr(case_tracking, "get_case_tracking_provider", lambda: provider)

    response = _search(client, token, {"cnr_number": FIXTURE_CNR}, REPLAY_HEADERS)

    assert response.status_code == 200, response.text
    assert response.json()["replay"] is None
    assert provider.search_calls == [
        CaseSearchQuery(cnr_number=FIXTURE_CNR, query=None, case_number=None)
    ]
