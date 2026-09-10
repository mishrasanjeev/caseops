"""PostgreSQL acceptance for durable provider claims and resumable expansion."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests import test_20260909_provider_recovery as journeys
from tests import test_20260909_provider_refresh_protocol as protocol
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_overlapping_provider_attempt_is_durably_fenced(isolated_postgres_client):
    journeys.test_running_claim_is_durable_and_overlap_makes_no_second_call(
        isolated_postgres_client
    )


@pytest.mark.parametrize("change", ["membership", "archive"])
def test_revoked_scope_cannot_publish_provider_result(isolated_postgres_client, change):
    journeys.test_scope_revocation_during_transport_keeps_spend_but_no_operational_output(
        isolated_postgres_client, change
    )


def test_lost_worker_recovers_without_freeing_unknown_spend(isolated_postgres_client, monkeypatch):
    journeys.test_worker_loss_recovers_automatically_without_erasing_uncertain_budget(
        isolated_postgres_client, monkeypatch
    )


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
def test_transport_does_not_hold_postgres_transaction(
    isolated_postgres_client, monkeypatch, boundary
):
    journeys.test_provider_transport_releases_database_transaction(
        isolated_postgres_client, monkeypatch, boundary
    )


def test_async_scrape_status_recovers_without_duplicate_purchase(
    isolated_postgres_client, monkeypatch
):
    protocol.test_queued_refresh_recovers_without_repurchase_or_stale_hearing(
        isolated_postgres_client, monkeypatch
    )


def test_concurrent_disposal_wins_without_operational_output(isolated_postgres_client):
    journeys.test_disposal_during_provider_transport_wins_without_new_children(
        isolated_postgres_client
    )


def test_caseops_remains_responsive_during_provider_wait(isolated_postgres_client, monkeypatch):
    journeys.test_waiting_provider_cannot_starve_the_caseops_event_loop_or_publish_late_results(
        isolated_postgres_client, monkeypatch,
    )


@pytest.mark.parametrize("revoke", [False, True])
def test_initial_search_releases_database_and_reauthorizes(isolated_postgres_client, revoke):
    journeys.test_initial_search_releases_transaction_and_reauthorizes_before_result(
        isolated_postgres_client, revoke
    )


@pytest.mark.parametrize("revoke", [False, True])
def test_source_download_rechecks_current_access(isolated_postgres_client, monkeypatch, revoke):
    journeys.test_source_download_releases_transaction_and_rechecks_access(
        isolated_postgres_client, monkeypatch, revoke
    )


def test_fifty_one_cases_continue_without_repeat_provider_work(
    isolated_postgres_client, monkeypatch
):
    protocol.test_nightly_continuation_caps_raw_batch_and_finishes_remaining_case(
        isolated_postgres_client, monkeypatch
    )


def test_orphan_poll_run_records_interruption_and_recovers(isolated_postgres_client, monkeypatch):
    journeys.test_scheduler_worker_loss_does_not_leave_a_permanently_running_poll(
        isolated_postgres_client, monkeypatch
    )


def test_expansion_recovers_invalid_index_and_preserves_evidence_on_two_refusals(pg_engine):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260909_0002_provider_attempt_leases.py"
    )
    spec = importlib.util.spec_from_file_location("provider_lease_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    schema = f"provider_recovery_{uuid4().hex}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET search_path TO {schema}"))
            connection.execute(
                text(
                    "CREATE TABLE tracked_case_provider_operations (id varchar(36), "
                    "company_id varchar(36), status varchar(24), lease_token varchar(36), "
                    "lease_expires_at timestamptz, spend_reservation_id varchar(36))"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE provider_spend_reservations "
                    "(id varchar(36), dispatched_at timestamptz)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO tracked_case_provider_operations VALUES "
                    "('retained', 'company', 'running', 'lease', now(), 'hold'), "
                    "('sibling', 'company', 'running', NULL, NULL, NULL)"
                )
            )
            connection.execute(
                text("INSERT INTO provider_spend_reservations VALUES ('hold', now())")
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX CONCURRENTLY {module._INDEX} "
                        "ON tracked_case_provider_operations (company_id)"
                    )
                )
            connection.commit()
            context = MigrationContext.configure(connection)
            with context.begin_transaction(), Operations.context(context):
                module.upgrade()
                module.upgrade()
            actual = next(
                row
                for row in inspect(connection).get_indexes(module._TABLE)
                if row["name"] == module._INDEX
            )
            assert actual["column_names"] == module._INDEX_COLUMNS and not actual["unique"]
            assert (
                connection.scalar(
                    text(
                        "SELECT indisvalid AND indisready FROM pg_index "
                        "WHERE indexrelid=to_regclass(:name)"
                    ),
                    {"name": module._INDEX},
                )
                is True
            )

            def shape():
                return {
                    table: (
                        [
                            (row["name"], str(row["type"]), row["nullable"])
                            for row in inspect(connection).get_columns(table)
                        ],
                        inspect(connection).get_indexes(table),
                    )
                    for table in module._COLUMNS
                }

            before = shape()
            for _ in range(2):
                with pytest.raises(RuntimeError, match="evidence exists"):
                    with context.begin_transaction(), Operations.context(context):
                        module.downgrade()
                assert shape() == before
                assert (
                    connection.scalar(
                        text(
                            "SELECT lease_token FROM tracked_case_provider_operations "
                            "WHERE id='retained'"
                        )
                    )
                    == "lease"
                )
                assert (
                    connection.scalar(
                        text(
                            "SELECT dispatched_at IS NOT NULL FROM provider_spend_reservations "
                            "WHERE id='hold'"
                        )
                    )
                    is True
                )
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
