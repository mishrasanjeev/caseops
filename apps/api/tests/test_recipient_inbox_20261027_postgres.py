"""Repeat populated inbox HTTP/authority/cursor contracts on isolated PostgreSQL."""

import pytest

from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_recipient_inbox_20261027 import (
    ambiguous_fence,
    chronology,
    close_reopen,
    cursor_contract,
    denied_changes,
    empty_page,
    exact_primary_link_refusal,
    exact_source_candidate_refusal,
    generation_and_corruption,
    malformed_status,
    other_recipients,
    plan_bound,
    postcommit_denial,
    read_only_recipient,
    roundtrip,
    source_bounds,
)

forbid_unadmitted_network = _forbid_unadmitted_network
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("kind", ["matter", "ip_docket"])
def test_populated_owned_roundtrip_postgres(isolated_postgres_client, monkeypatch, kind):
    roundtrip(isolated_postgres_client, monkeypatch, kind)


@pytest.mark.parametrize(
    "kind,change",
    [
        ("matter", "wall"),
        ("matter", "team"),
        ("matter", "disposed"),
        ("matter", "membership"),
        ("ip_docket", "restricted"),
        ("ip_docket", "capability"),
        ("ip_docket", "membership"),
    ],
)
def test_current_authority_postgres(isolated_postgres_client, monkeypatch, kind, change):
    denied_changes(isolated_postgres_client, monkeypatch, kind, change)


def test_other_recipient_and_tenant_postgres(isolated_postgres_client, monkeypatch):
    other_recipients(isolated_postgres_client, monkeypatch)


def test_chronology_and_exact_ties_postgres(isolated_postgres_client, monkeypatch):
    chronology(isolated_postgres_client, monkeypatch)


def test_empty_candidate_continuation_postgres(isolated_postgres_client, monkeypatch):
    empty_page(isolated_postgres_client, monkeypatch)


def test_second_link_after_advisory_before_fence_postgres(isolated_postgres_client, monkeypatch):
    ambiguous_fence(isolated_postgres_client, monkeypatch)


def test_status_errors_and_private_response_headers_postgres(isolated_postgres_client, monkeypatch):
    malformed_status(isolated_postgres_client, monkeypatch)


def test_cursor_scope_and_expiry_postgres(isolated_postgres_client):
    cursor_contract(isolated_postgres_client)


@pytest.mark.parametrize(
    "change", ["new_generation", "not_delivered", "wrong_schedule", "malformed_source"]
)
def test_current_source_and_schedule_postgres(isolated_postgres_client, monkeypatch, change):
    generation_and_corruption(isolated_postgres_client, monkeypatch, change)


def test_receipt_action_without_matter_write_postgres(isolated_postgres_client, monkeypatch):
    read_only_recipient(isolated_postgres_client, monkeypatch)


def test_parent_close_and_reopen_postgres(isolated_postgres_client, monkeypatch):
    close_reopen(isolated_postgres_client, monkeypatch)


def test_response_failure_after_actual_commit_postgres(isolated_postgres_client, monkeypatch):
    postcommit_denial(isolated_postgres_client, monkeypatch)


def test_complete_statement_observation_postgres(isolated_postgres_client, monkeypatch, tmp_path):
    source_bounds(isolated_postgres_client, monkeypatch, output=tmp_path)


@pytest.mark.parametrize("index_timing", ["before_seed", "after_seed"])
@pytest.mark.parametrize("adverse", [False, True])
def test_exact_default_adverse_plans_and_index_timing_postgres(
    isolated_postgres_client,
    monkeypatch,
    tmp_path,
    index_timing,
    adverse,
):
    plan_bound(
        isolated_postgres_client,
        monkeypatch,
        index_timing=index_timing,
        adverse=adverse,
        output=tmp_path,
    )


@pytest.mark.parametrize("kind", ["owned", "foreign"])
def test_exact_pk_candidate_hint_keeps_current_source_authority_postgres(
    isolated_postgres_client,
    monkeypatch,
    kind,
):
    exact_source_candidate_refusal(isolated_postgres_client, monkeypatch, kind)


def test_exact_primary_bridge_does_not_borrow_sibling_candidate_postgres(
    isolated_postgres_client,
    monkeypatch,
):
    exact_primary_link_refusal(isolated_postgres_client, monkeypatch)
