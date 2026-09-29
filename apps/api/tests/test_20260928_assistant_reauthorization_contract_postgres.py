"""Real PostgreSQL proof that saved assistant answers stay locked (2026-09-28).

The SQLite journeys, answer for answer and row state for row state, on
PostgreSQL, where the set-based lock returns its rows in one statement.
"""

from __future__ import annotations

import pytest

from tests import test_20260928_assistant_reauthorization_contract as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_an_access_change_that_keeps_access_locks_both_answers_for_good(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_an_access_change_that_keeps_access_locks_both_answers_for_good(
        isolated_postgres_client, monkeypatch
    )


def test_an_access_loss_and_its_restore_leave_both_answers_locked(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_an_access_loss_and_its_restore_leave_both_answers_locked(
        isolated_postgres_client, monkeypatch
    )


def test_reads_never_write_a_saved_answer_state(isolated_postgres_client, monkeypatch):
    journeys.test_reads_never_write_a_saved_answer_state(isolated_postgres_client, monkeypatch)


def test_a_non_access_event_locks_the_answer_for_good(isolated_postgres_client, monkeypatch):
    journeys.test_a_non_access_event_locks_the_answer_for_good(
        isolated_postgres_client, monkeypatch
    )


def test_an_access_event_locks_a_document_answer_the_index_no_longer_holds(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_an_access_event_locks_a_document_answer_the_index_no_longer_holds(
        isolated_postgres_client, monkeypatch
    )


def test_an_ip_docket_event_locks_its_records_and_linked_documents(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_an_ip_docket_event_locks_its_records_and_linked_documents(
        isolated_postgres_client, monkeypatch
    )


def test_one_event_locks_any_number_of_saved_answers_in_one_statement(
    isolated_postgres_client,
    monkeypatch,
):
    journeys.test_one_event_locks_any_number_of_saved_answers_in_one_statement(
        isolated_postgres_client, monkeypatch
    )
