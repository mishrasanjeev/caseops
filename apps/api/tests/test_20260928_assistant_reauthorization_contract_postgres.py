"""Real PostgreSQL proof of the Workspace Assistant reauthorization contract (2026-09-28).

The SQLite journeys, answer for answer and row state for row state, on
PostgreSQL.
"""

from __future__ import annotations

import pytest

from tests import test_20260928_assistant_reauthorization_contract as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_access_change_that_keeps_access_reauthorizes_on_every_read(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_access_change_that_keeps_access_reauthorizes_on_every_read(
        isolated_postgres_client, monkeypatch
    )


def test_access_loss_hides_and_restore_serves_the_document_answer_again(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_access_loss_hides_and_restore_serves_the_document_answer_again(
        isolated_postgres_client, monkeypatch
    )


def test_export_during_an_access_loss_locks_the_answer_for_good(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_export_during_an_access_loss_locks_the_answer_for_good(
        isolated_postgres_client, monkeypatch
    )


def test_a_non_access_event_locks_the_answer_for_good(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_a_non_access_event_locks_the_answer_for_good(
        isolated_postgres_client, monkeypatch
    )
