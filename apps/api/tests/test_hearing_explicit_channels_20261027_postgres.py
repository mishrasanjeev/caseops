"""Same populated HTTP/queue/claim boundary on isolated PostgreSQL databases."""

from __future__ import annotations

import pytest

from tests.test_hearing_explicit_channels_20261027 import (
    empty_http_roundtrip,
    enqueue_fence,
    legacy_positive,
    missing_source,
    parent_fence,
    retained_queue,
    terminal_and_claim,
    timeout_then_optout,
)
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)

forbid_unadmitted_network = _forbid_unadmitted_network
pytestmark = pytest.mark.postgres


def test_empty_http_plan_reschedule_postgres(isolated_postgres_client, monkeypatch):
    empty_http_roundtrip(isolated_postgres_client, monkeypatch)


@pytest.mark.parametrize("policy", [None, {}])
def test_legacy_actual_offline_wire_postgres(isolated_postgres_client, monkeypatch, policy):
    legacy_positive(isolated_postgres_client, monkeypatch, policy)


@pytest.mark.parametrize(
    "channel,status", [("email", "queued"), ("email", "retry_scheduled"), ("in_app", "queued")]
)
def test_retained_channels_no_reactivation_postgres(
    isolated_postgres_client, monkeypatch, channel, status
):
    retained_queue(isolated_postgres_client, monkeypatch, channel, status)


@pytest.mark.parametrize("state", ["sent", "delivered", "live", "expired"])
def test_terminal_uncertain_state_postgres(isolated_postgres_client, monkeypatch, state):
    terminal_and_claim(isolated_postgres_client, monkeypatch, state)


def test_timeout_then_optout_no_fallback_postgres(isolated_postgres_client, monkeypatch):
    timeout_then_optout(isolated_postgres_client, monkeypatch)


@pytest.mark.parametrize(
    "provider_ready,channels", [(True, []), (False, []), (True, ["email"]), (False, ["email"])]
)
def test_primary_and_companion_fence_postgres(
    isolated_postgres_client, monkeypatch, provider_ready, channels
):
    enqueue_fence(
        isolated_postgres_client, monkeypatch, provider_ready=provider_ready, channels=channels
    )


def test_current_policy_after_parent_fence_postgres(isolated_postgres_client, monkeypatch):
    parent_fence(isolated_postgres_client, monkeypatch)


def test_missing_source_no_legacy_fallback_postgres(isolated_postgres_client, monkeypatch):
    missing_source(isolated_postgres_client, monkeypatch)
