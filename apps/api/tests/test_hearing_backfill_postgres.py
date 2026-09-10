"""Real database acceptance for bounded, resumable hearing admission."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.core.settings import get_settings
from caseops_api.db.models import Matter, TrackedCaseBackfillCursor, TrackedCaseBookmark
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import (
    _system_contexts,
    backfill_existing_matter_case_tracking,
)
from tests import test_20260908_hearing_backfill_starvation as journeys
from tests.test_20260904_auto_next_hearing_sync import _enable_tracking
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("initial_tracking", ["true", "false"])
def test_rejected_batch_and_full_cycle_on_postgres(
    isolated_postgres_client, monkeypatch, initial_tracking
):
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", initial_tracking)
    get_settings.cache_clear()
    journeys.test_blocked_oldest_batch_does_not_starve_supported_later_matter(
        isolated_postgres_client, monkeypatch
    )


def test_failed_admission_keeps_real_postgres_transaction_usable(
    isolated_postgres_client, monkeypatch
):
    journeys.test_failed_backfill_rolls_back_cursor_and_keeps_poll_session_usable(
        isolated_postgres_client, monkeypatch
    )


def test_ten_thousand_row_backfill_bound_on_postgres(isolated_postgres_client, monkeypatch):
    journeys.test_raw_scan_is_bounded_and_advances_even_for_incomplete_rows(
        isolated_postgres_client, monkeypatch, 10000
    )


def test_overlapping_scans_serialize_without_blocking_another_tenant(
    isolated_postgres_client, monkeypatch
):
    client = isolated_postgres_client
    first = bootstrap_company(client)
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Independent Backfill Tenant",
            "company_slug": "independent-backfill",
            "company_type": "law_firm",
            "owner_full_name": "Independent Owner",
            "owner_email": "owner@independent-backfill.example",
            "owner_password": "LocalBackfillOnly123!",
        },
    )
    assert response.status_code == 200, response.text
    second_company = response.json()["company"]["id"]
    first_company = first["company"]["id"]
    _enable_tracking(monkeypatch)
    factory = get_session_factory()
    try:
        with factory() as seed:
            for company_id, count in ((first_company, 51), (second_company, 1)):
                seed.add_all(
                    [
                        Matter(
                            company_id=company_id,
                            title=f"Concurrent admission {index}",
                            matter_code=f"CONCURRENT-{index:03}",
                            practice_area="litigation",
                            forum_level="high_court",
                            status="intake",
                            court_name="Delhi High Court",
                            case_number=f"WP(C) {15000 + index}/2026",
                        )
                        for index in range(count)
                    ]
                )
            seed.commit()
            engine = seed.get_bind()
        application_name = f"backfill-contender-{uuid4().hex[:8]}"

        def context_for(session, company_id):
            return next(row for row in _system_contexts(session) if row.company.id == company_id)

        def concurrent_scan():
            with factory() as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
                result = backfill_existing_matter_case_tracking(
                    session,
                    context=context_for(session, first_company),
                    provider_key="ecourtsindia",
                )
                session.commit()
                return result

        with factory() as winner, ThreadPoolExecutor(max_workers=1) as pool:
            first_result = backfill_existing_matter_case_tracking(
                winner, context=context_for(winner, first_company), provider_key="ecourtsindia"
            )
            assert first_result.linked_count == 50
            contender = pool.submit(concurrent_scan)
            try:
                _wait_for_postgres_lock_wait(engine, application_name=application_name)
                with factory() as independent:
                    independent.execute(text("SET LOCAL lock_timeout = '500ms'"))
                    independent_result = backfill_existing_matter_case_tracking(
                        independent,
                        context=context_for(independent, second_company),
                        provider_key="ecourtsindia",
                    )
                    independent.commit()
                    assert independent_result.linked_count == 1
            finally:
                winner.commit()
            assert contender.result(timeout=10).linked_count == 1
        with factory() as read:
            for company_id, expected in ((first_company, 51), (second_company, 1)):
                assert (
                    read.scalar(
                        select(func.count())
                        .select_from(TrackedCaseBookmark)
                        .where(TrackedCaseBookmark.company_id == company_id)
                    )
                    == expected
                )
                cursor = read.get(TrackedCaseBackfillCursor, (company_id, "ecourtsindia"))
                assert cursor.last_matter_id is None
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("initial_tracking", ["true", "false"])
def test_disposal_after_candidate_discovery_prevents_backfill_child_creation(
    isolated_postgres_client, monkeypatch, initial_tracking
):
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", initial_tracking)
    get_settings.cache_clear()
    client = isolated_postgres_client
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    with journeys.legacy_tracking_creation(monkeypatch):
        created = client.post(
            "/api/matters/",
            headers=headers,
            json={
                "title": "Disposal wins hearing admission",
                "matter_code": "BACKFILL-DISPOSE",
                "practice_area": "litigation",
                "forum_level": "high_court",
                "status": "active",
                "court_name": "Delhi High Court",
                "case_number": "WP(C) 9234/2026",
            },
        )
    assert get_settings().case_tracking_enabled is (initial_tracking == "true")
    assert created.status_code == 200, created.text
    matter = created.json()
    _enable_tracking(monkeypatch)
    factory = get_session_factory()
    with factory() as probe:
        engine = probe.get_bind()
        assert probe.scalar(select(func.count()).select_from(TrackedCaseBookmark)) == 0
    discovered, continue_admission = Event(), Event()

    def pause_parent_lock(connection, cursor, statement, parameters, context, executemany):
        if (
            current_thread().name.startswith("hearing-admission")
            and "FROM matters" in statement
            and "FOR UPDATE" in statement
        ):
            discovered.set()
            assert continue_admission.wait(timeout=10)

    def admit():
        with factory() as session:
            # Retain an old ORM instance to prove the locking read refreshes it.
            stale = session.get(Matter, matter["id"])
            assert stale.status == "active"
            result = backfill_existing_matter_case_tracking(
                session, context=_system_contexts(session)[0], provider_key="ecourtsindia"
            )
            session.commit()
            return result

    event.listen(engine, "before_cursor_execute", pause_parent_lock)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="hearing-admission") as pool:
            future = pool.submit(admit)
            try:
                assert discovered.wait(timeout=10)
                disposed = client.patch(
                    f"/api/matters/{matter['id']}/lifecycle/status",
                    headers=headers,
                    json={
                        "to_status": "disposed",
                        "expected_from_status": "active",
                        "expected_updated_at": matter["updated_at"],
                        "reason": "Disposal during bounded hearing admission.",
                    },
                )
                assert disposed.status_code == 200, disposed.text
            finally:
                continue_admission.set()
            result = future.result(timeout=10)
            assert result.linked_count == 0
            assert result.skipped_count == 1
        with factory() as read:
            final = read.get(Matter, matter["id"])
            assert final.status == "disposed" and not final.is_active
            assert final.lifecycle_version == matter["lifecycle_version"] + 1
            assert read.scalar(select(func.count()).select_from(TrackedCaseBookmark)) == 0
    finally:
        event.remove(engine, "before_cursor_execute", pause_parent_lock)
        get_settings.cache_clear()


def test_backfill_index_migration_recovers_interruption_and_preserves_cursor(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260908_0001_tracking_backfill_cursor.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"backfill_index_{uuid4().hex}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            # Do not let has_table() find a pre-existing public cursor table.
            connection.execute(text(f"SET search_path TO {schema}"))
            connection.execute(text("CREATE TABLE companies (id varchar(36) PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE matters (id varchar(36), company_id varchar(36), "
                    "created_at timestamptz)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE tracked_case_bookmarks (company_id varchar(36), "
                    "matter_id varchar(36), is_archived boolean)"
                )
            )
            connection.execute(text("INSERT INTO companies VALUES ('retained-company')"))
            connection.execute(
                text(
                    "INSERT INTO matters VALUES ('first', 'retained-company', now()), "
                    "('second', 'retained-company', now())"
                )
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX CONCURRENTLY ix_matters_company_created_id "
                        "ON matters (company_id)"
                    )
                )
            connection.commit()
            context = MigrationContext.configure(connection)
            with context.begin_transaction(), Operations.context(context):
                migration.upgrade()
                connection.execute(
                    text(
                        "INSERT INTO tracked_case_backfill_cursors VALUES "
                        "('retained-company', 'ecourtsindia', now(), 'first', now())"
                    )
                )
                migration.upgrade()
            assert (
                connection.scalar(text("SELECT last_matter_id FROM tracked_case_backfill_cursors"))
                == "first"
            )
            assert connection.scalar(text("SELECT count(*) FROM matters")) == 2
            for name, table, _ in migration._INDEXES:
                health = connection.execute(migration._INDEX_HEALTH, {"name": name}).first()
                assert health.ready and health.relname == table

            def schema_shape():
                from sqlalchemy import inspect

                inspector = inspect(connection)
                return {
                    table: {
                        "columns": [
                            (row["name"], str(row["type"]), row["nullable"])
                            for row in inspector.get_columns(table)
                        ],
                        "indexes": inspector.get_indexes(table),
                        "foreign_keys": inspector.get_foreign_keys(table),
                        "checks": inspector.get_check_constraints(table),
                    }
                    for table in inspector.get_table_names()
                }

            before = schema_shape()
            for _ in range(2):
                with pytest.raises(RuntimeError, match="state exists"):
                    with context.begin_transaction(), Operations.context(context):
                        migration.downgrade()
                assert schema_shape() == before
                assert (
                    connection.scalar(
                        text("SELECT last_matter_id FROM tracked_case_backfill_cursors")
                    )
                    == "first"
                )
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
