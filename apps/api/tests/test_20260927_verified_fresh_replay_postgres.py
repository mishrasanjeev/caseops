"""Real PostgreSQL proof for the verification-fixture refresh and fresh-evidence replay.

The daily cap is only a cap if concurrent scheduler executions cannot both buy
the lookup. On PostgreSQL the claim serializes on advisory transaction locks and
commits before transport; SQLite serializes writers and cannot prove that. The
SQLite journeys are replayed here on the production engine as well.
"""

import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import pytest

from caseops_api.db.session import get_session_factory
from caseops_api.services import case_tracking
from tests import test_20260927_verified_fresh_replay as journeys
from tests.test_auth_company import bootstrap_company
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_concurrent_scheduled_executions_buy_one_lookup_without_holding_a_transaction(
    isolated_postgres_client, monkeypatch
):
    journeys._enable(monkeypatch)
    company_id = str(bootstrap_company(isolated_postgres_client)["company"]["id"])
    journeys.Clock(monkeypatch, journeys.REFRESHED_AT)
    sessions: dict[int, object] = {}
    start = threading.Barrier(2)
    entered, release = threading.Event(), threading.Event()
    calls = []

    class BlockingProvider(journeys.FixtureProvider):
        def search_cases(self, *, query):
            calls.append(query)
            session = sessions[threading.get_ident()]
            assert not session.in_transaction(), "the provider was called inside a transaction"
            entered.set()
            assert release.wait(60), "the test never released provider transport"
            return [journeys.bug032_snapshot()]

    provider = BlockingProvider()

    def scheduled_execution():
        with get_session_factory()() as session:
            sessions[threading.get_ident()] = session
            start.wait(timeout=30)
            return case_tracking.poll_tracked_cases(
                session,
                provider=provider,
                enforce_window=True,
                now=journeys.REFRESHED_AT,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(scheduled_execution) for _ in range(2)]
        try:
            assert entered.wait(60), "neither execution reached provider transport"
            # The execution that lost the claim completes while the winner is
            # still inside transport: no lock or transaction spans the call.
            done, pending = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            assert (len(done), len(pending)) == (1, 1)
        finally:
            release.set()
        results = [future.result(timeout=120) for future in futures]

    outcomes = sorted(
        str(outcome["outcome"])
        for runs in results
        for outcome in journeys._fixture_outcomes(runs, company_id)
    )
    assert outcomes == ["concurrent_refresh", "refreshed"]
    assert len(calls) == 1
    [operation] = journeys._fixture_operations(company_id)
    assert (operation.status, operation.response_class) == ("succeeded", "success")


def test_scheduled_refresh_stores_one_daily_lookup_as_evidence_only(
    isolated_postgres_client, monkeypatch
):
    journeys.test_scheduled_refresh_stores_one_daily_lookup_as_evidence_only(
        isolated_postgres_client, monkeypatch
    )


def test_replay_answers_the_reported_search_from_fresh_evidence_like_a_live_lookup(
    isolated_postgres_client, monkeypatch
):
    journeys.test_replay_answers_the_reported_search_from_fresh_evidence_like_a_live_lookup(
        isolated_postgres_client, monkeypatch
    )


def test_replay_never_serves_evidence_older_than_24_hours(isolated_postgres_client, monkeypatch):
    journeys.test_replay_never_serves_evidence_older_than_24_hours(
        isolated_postgres_client, monkeypatch
    )


def test_a_later_provider_answer_supersedes_but_an_outage_does_not(
    isolated_postgres_client, monkeypatch
):
    journeys.test_a_later_provider_answer_supersedes_but_an_outage_does_not(
        isolated_postgres_client, monkeypatch
    )


@pytest.mark.parametrize("tamper", ["body", "hash", "cnr"])
def test_tampered_evidence_is_never_replayed(isolated_postgres_client, monkeypatch, tamper):
    journeys.test_tampered_evidence_is_never_replayed(isolated_postgres_client, monkeypatch, tamper)


def test_replay_is_confined_to_registered_fixtures_in_their_own_workspace(
    isolated_postgres_client, monkeypatch
):
    journeys.test_replay_is_confined_to_registered_fixtures_in_their_own_workspace(
        isolated_postgres_client, monkeypatch
    )


def test_lease_recovery_fails_a_lost_attempt_without_touching_the_tracked_case(
    isolated_postgres_client, monkeypatch
):
    journeys.test_lease_recovery_fails_a_lost_attempt_without_touching_the_tracked_case(
        isolated_postgres_client, monkeypatch
    )


def test_an_exhausted_budget_refuses_the_lookup_before_any_claim(
    isolated_postgres_client, monkeypatch
):
    journeys.test_an_exhausted_budget_refuses_the_lookup_before_any_claim(
        isolated_postgres_client, monkeypatch
    )


def test_a_matter_link_to_the_fixture_case_is_reused_and_left_unchanged(
    isolated_postgres_client, monkeypatch
):
    journeys.test_a_matter_link_to_the_fixture_case_is_reused_and_left_unchanged(
        isolated_postgres_client, monkeypatch
    )
