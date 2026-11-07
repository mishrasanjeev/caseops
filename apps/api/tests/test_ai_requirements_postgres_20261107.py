"""Replay the same audit/access/scale contracts on migrated PostgreSQL."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests import test_ip_watch_report_20261107 as watch
from tests import test_teams as teams

pytestmark = pytest.mark.postgres


def test_retained_watch_report_postgres(
    isolated_postgres_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    watch.test_watch_report_reproduces_disconnected_adapter_and_preserves_review_evidence(
        isolated_postgres_client, monkeypatch,
    )


@pytest.mark.parametrize("source_status", ["available", "unavailable", "stale"])
def test_watch_source_limitations_postgres(
    isolated_postgres_client: TestClient, source_status: str,
) -> None:
    watch.test_watch_report_retains_source_limitations_without_legal_promotion(
        isolated_postgres_client, source_status,
    )


def test_empty_watch_records_postgres(isolated_postgres_client: TestClient) -> None:
    watch.test_watch_report_empty_records_are_distinct_from_unavailable_automated_coverage(
        isolated_postgres_client,
    )


@pytest.mark.parametrize("denial", ["revoke_grant", "add_wall"])
def test_watch_current_access_postgres(
    isolated_postgres_client: TestClient, denial: str,
) -> None:
    watch.test_watch_report_rechecks_source_and_profile_access_without_hidden_counts_or_audit_ids(
        isolated_postgres_client, denial,
    )


def test_terminal_watch_docket_postgres(isolated_postgres_client: TestClient) -> None:
    watch.test_watch_report_excludes_closed_dockets_without_mutating_retained_evidence(
        isolated_postgres_client,
    )


def test_watch_hydration_query_bound_postgres(isolated_postgres_client: TestClient) -> None:
    watch.assert_watch_report_bounds_hydration_and_queries_beyond_row_limit(isolated_postgres_client)


@pytest.mark.parametrize("initial_is_lead", [False, True])
def test_team_lead_audit_postgres(
    isolated_postgres_client: TestClient, initial_is_lead: bool,
) -> None:
    teams.test_team_lead_change_persists_and_audits_once(isolated_postgres_client, initial_is_lead)


@pytest.mark.parametrize(
    ("attempt", "expected_status"),
    [("non_manager", 403), ("foreign_team", 404), ("foreign_member", 400)],
)
def test_team_lead_denials_postgres(
    isolated_postgres_client: TestClient, attempt: str, expected_status: int,
) -> None:
    teams.test_team_lead_change_denials_preserve_membership_and_audit(
        isolated_postgres_client, attempt, expected_status,
    )
