"""Independent fresh-database upgrade/downgrade, never a tenant DB clone."""

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.scripts.check_database_indexes import build_index_health_report
from tests.fixtures_postgres_client import temporary_http_database

TABLES = {"ip_portfolio_renewal_series", "ip_portfolio_renewal_occurrences"}
PREVIOUS = "20261011_0001"
HEAD = "20261015_0001"


@contextmanager
def _fresh_engine(kind, tmp_path):
    if kind == "postgres":
        source = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
        with temporary_http_database(source) as engine:
            yield engine
    else:
        engine = create_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'renewal-migration.db').as_posix()}"
        )
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.mark.parametrize("kind", ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def test_fresh_upgrade_preserves_catalog_and_empty_downgrade(kind, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    with _fresh_engine(kind, tmp_path) as engine:
        url = engine.url.render_as_string(hide_password=False)
        monkeypatch.setenv("CASEOPS_ENV", "local")
        monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
        get_settings.cache_clear()
        clear_engine_cache()
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, PREVIOUS)
        before_tables = set(inspect(engine).get_table_names())
        assert TABLES.isdisjoint(before_tables)
        with engine.connect() as connection:
            before_aliases = connection.execute(
                text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
            ).all()
        assert before_aliases
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables | TABLES
        assert "renewal_reminder_policy_json" in {
            row["name"] for row in schema.get_columns("ip_workspace_configurations")
        }
        assert ("series_id", "generation", "local_on") in {
            tuple(row["column_names"])
            for row in schema.get_unique_constraints("ip_portfolio_renewal_occurrences")
        }
        assert {
            tuple(row["constrained_columns"])
            for row in schema.get_foreign_keys("ip_portfolio_renewal_occurrences")
        } >= {
            ("series_id", "company_id", "docket_id"),
            ("recipient_membership_id", "company_id"),
            ("docket_id", "source_version"),
            ("company_id", "delivery_key"),
        }
        assert ("next_reminder_at", "company_id", "id") in {
            tuple(row["column_names"]) for row in schema.get_indexes("ip_portfolio_renewal_series")
        }
        assert ("reconcile_after", "company_id", "id") in {
            tuple(row["column_names"]) for row in schema.get_indexes("ip_portfolio_renewal_series")
        }
        assert ("company_id", "last_delivery_key") in {
            tuple(row["constrained_columns"])
            for row in schema.get_foreign_keys("ip_portfolio_renewal_series")
        }
        assert (
            "company_id",
            "docket_id",
            "source_version",
            "generation",
            "local_on",
            "created_at",
            "id",
        ) in {
            tuple(row["column_names"])
            for row in schema.get_indexes("ip_portfolio_renewal_occurrences")
        }
        with engine.connect() as connection:
            health = build_index_health_report(connection)
            if os.environ.get("CASEOPS_TEST_RESULT_JOURNAL"):
                target = (
                    Path(os.environ["CASEOPS_TEST_RESULT_JOURNAL"]).parent
                    / f"index-health-{kind}.json"
                )
                target.write_text(json.dumps(health, indent=2), encoding="utf-8")
            assert health["status"] == "ok", health
            assert (
                connection.execute(
                    text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
                ).all()
                == before_aliases
            )
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        command.downgrade(config, PREVIOUS)
        assert set(inspect(engine).get_table_names()) == before_tables
        command.upgrade(config, HEAD)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


@pytest.mark.parametrize("policy_only", [False, True])
def test_populated_evidence_or_policy_refuses_destructive_downgrade(
    client, monkeypatch, policy_only
):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import select

    from caseops_api.db.models import IpWorkspaceConfiguration
    from caseops_api.db.session import get_engine, get_session_factory
    from tests.test_ip_portfolio_spec_20261013 import _actor
    from tests.test_ip_renewal_tracker_20261015 import _imported

    actor = _actor(client) if policy_only else _imported(client, monkeypatch)[0]
    if policy_only:
        with get_session_factory()() as session:
            config = session.scalar(
                select(IpWorkspaceConfiguration).where(
                    IpWorkspaceConfiguration.company_id == actor["company"]["id"]
                )
            )
            config.renewal_reminder_policy_json = {"cadence_days": 2}
            session.commit()
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261015_0001_portfolio_renewal_occurrences.py"
    )
    spec = importlib.util.spec_from_file_location("renewal_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = get_engine()
    before = set(inspect(engine).get_table_names())
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match="Restore-forward required"):
            migration.downgrade()
    assert set(inspect(engine).get_table_names()) == before


@pytest.mark.postgres
@pytest.mark.parametrize("writer_kind", ["policy", "series", "occurrence"])
def test_downgrade_refuses_policy_writer_committed_while_waiting_for_ddl(
    isolated_postgres_client, writer_kind
):
    import importlib.util
    import json
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, datetime
    from threading import Event
    from time import monotonic
    from uuid import uuid4

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from caseops_api.db.models import IpPortfolioRenewalOccurrence, IpPortfolioRenewalSeries
    from caseops_api.db.session import get_engine
    from tests.test_ip_039a_filing_particulars import _particulars
    from tests.test_ip_portfolio_spec_20261013 import _actor

    actor = _actor(isolated_postgres_client)
    docket = isolated_postgres_client.post(
        "/api/ip/dockets",
        headers=actor["headers"],
        json={
            "title": "First concurrent renewal evidence",
            "restricted": False,
            "particulars": _particulars("Concurrent migration source"),
        },
    )
    assert docket.status_code == 201, docket.text
    docket_id = docket.json()["id"]
    engine = get_engine()
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261015_0001_portfolio_renewal_occurrences.py"
    )
    spec = importlib.util.spec_from_file_location("renewal_downgrade_race", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    started = Event()
    state = {"writer_kind": writer_kind}
    series_id = str(uuid4())

    def downgrade():
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10000ms'")
            state["migration_pid"] = connection.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()

    with engine.connect() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = writer.begin()
        writer_pid = writer.scalar(text("SELECT pg_backend_pid()"))
        if writer_kind == "policy":
            writer.execute(
                text(
                    "UPDATE ip_workspace_configurations SET renewal_reminder_policy_json = :policy "
                    "WHERE company_id = :company"
                ),
                {"policy": json.dumps({"cadence_days": 2}), "company": actor["company"]["id"]},
            )
        else:
            values = dict(
                company_id=actor["company"]["id"],
                docket_id=docket_id,
                source_version=1,
                generation=1,
                due_on=date(2028, 3, 31),
                recipient_membership_id=actor["membership"]["id"],
            )
            writer.execute(
                IpPortfolioRenewalSeries.__table__.insert().values(
                    id=series_id,
                    start_on=date(2028, 2, 29),
                    timezone="Asia/Kolkata",
                    cadence_days=1,
                    delivery_time="09:00",
                    policy_version=1,
                    **values,
                )
            )
            if writer_kind == "occurrence":
                writer.execute(
                    IpPortfolioRenewalOccurrence.__table__.insert().values(
                        series_id=series_id,
                        local_on=date(2028, 3, 1),
                        scheduled_for=datetime(2028, 3, 1),
                        **values,
                    )
                )
        future = pool.submit(downgrade)
        try:
            assert started.wait(5)
            deadline = monotonic() + 5
            blocked = None
            with engine.connect() as observer:
                while monotonic() < deadline:
                    observer.rollback()
                    blocked = (
                        observer.execute(
                            text(
                                "SELECT query, wait_event_type, pg_blocking_pids(pid) AS blockers "
                                "FROM pg_stat_activity WHERE pid = :pid"
                            ),
                            {"pid": state["migration_pid"]},
                        )
                        .mappings()
                        .one()
                    )
                    if writer_pid in blocked["blockers"]:
                        break
                    assert not future.done(), "Downgrade did not wait for the actual writer."
                    Event().wait(0.02)
            assert blocked["wait_event_type"] == "Lock" and writer_pid in blocked["blockers"]
            state["blocked_query"] = dict(blocked)
            transaction.commit()
            state["writer_commit_returned"] = True
            error = None
            try:
                future.result(timeout=10)
            except RuntimeError as caught:
                error = caught
        finally:
            if transaction.is_active:
                transaction.rollback()
    tables = set(inspect(engine).get_table_names())
    columns = {row["name"] for row in inspect(engine).get_columns("ip_workspace_configurations")}
    state.update(
        tables_retained=TABLES <= tables,
        policy_column_retained="renewal_reminder_policy_json" in columns,
        migration_error=str(error) if error else None,
    )
    if os.environ.get("CASEOPS_TEST_RESULT_JOURNAL"):
        target = (
            Path(os.environ["CASEOPS_TEST_RESULT_JOURNAL"]).parent
            / f"downgrade-committed-{writer_kind}-race.json"
        )
        target.write_text(json.dumps(state, indent=2), encoding="utf-8")
    assert error is not None and "Restore-forward required" in str(error), state
    assert state["tables_retained"] and state["policy_column_retained"]
    assert state["blocked_query"]["query"].startswith("LOCK TABLE "), state
    with engine.connect() as connection:
        if writer_kind == "policy":
            assert connection.scalar(
                text(
                    "SELECT renewal_reminder_policy_json FROM ip_workspace_configurations "
                    "WHERE company_id = :company"
                ),
                {"company": actor["company"]["id"]},
            ) == {"cadence_days": 2}
        else:
            assert (
                connection.scalar(
                    text("SELECT id FROM ip_portfolio_renewal_series WHERE id = :id"),
                    {"id": series_id},
                )
                == series_id
            )
            assert connection.scalar(
                text("SELECT count(*) FROM ip_portfolio_renewal_occurrences WHERE series_id = :id"),
                {"id": series_id},
            ) == int(writer_kind == "occurrence")


@pytest.mark.postgres
@pytest.mark.parametrize("caller_timeout", [0, 250])
def test_downgrade_writer_exclusion_is_bounded_and_preserves_stricter_timeout(
    isolated_postgres_client, caller_timeout
):
    import importlib.util
    from time import monotonic

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import OperationalError

    from caseops_api.db.session import get_engine
    from tests.test_ip_portfolio_spec_20261013 import _actor

    actor = _actor(isolated_postgres_client)
    engine = get_engine()
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261015_0001_portfolio_renewal_occurrences.py"
    )
    spec = importlib.util.spec_from_file_location("renewal_bounded_downgrade", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as writer:
        writer.execute(
            text(
                "UPDATE ip_workspace_configurations SET renewal_reminder_policy_json = :policy "
                "WHERE company_id = :company"
            ),
            {"policy": '{"cadence_days": 2}', "company": actor["company"]["id"]},
        )
        started = monotonic()
        with pytest.raises(OperationalError) as caught, engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL lock_timeout = '{caller_timeout}ms'")
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
        elapsed = monotonic() - started
        assert caught.value.orig.sqlstate == "55P03"
        budget = (caller_timeout or 5000) / 1000
        assert budget * 0.8 <= elapsed < budget + 2
    assert TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT renewal_reminder_policy_json FROM ip_workspace_configurations "
                "WHERE company_id = :company"
            ),
            {"company": actor["company"]["id"]},
        ) == {"cadence_days": 2}


@pytest.mark.postgres
def test_empty_downgrade_excludes_policy_writer_after_final_preflight(isolated_postgres_client):
    import importlib.util
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    from caseops_api.db.session import get_engine
    from tests.test_ip_portfolio_spec_20261013 import _actor

    actor = _actor(isolated_postgres_client)
    engine = get_engine()
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261015_0001_portfolio_renewal_occurrences.py"
    )
    spec = importlib.util.spec_from_file_location("renewal_post_preflight", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    checked, release = Event(), Event()
    statements = []

    def pause_after_preflight(_connection, _cursor, statement, _parameters, _context, _many):
        if not current_thread().name.startswith("renewal-empty-downgrade"):
            return
        statements.append(statement)
        if statement.startswith("SELECT 1 FROM ip_workspace_configurations "):
            checked.set()
            assert release.wait(5), "Writer probe did not release the empty downgrade."

    def downgrade():
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration.downgrade()

    event.listen(engine, "after_cursor_execute", pause_after_preflight)
    try:
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="renewal-empty-downgrade"
        ) as pool:
            future = pool.submit(downgrade)
            try:
                assert checked.wait(5)
                with pytest.raises(OperationalError) as caught, engine.begin() as writer:
                    writer.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
                    writer.execute(
                        text(
                            "UPDATE ip_workspace_configurations "
                            "SET renewal_reminder_policy_json = :policy "
                            "WHERE company_id = :company"
                        ),
                        {"policy": '{"cadence_days": 2}', "company": actor["company"]["id"]},
                    )
                assert caught.value.orig.sqlstate == "55P03"
            finally:
                release.set()
            future.result(timeout=5)
    finally:
        event.remove(engine, "after_cursor_execute", pause_after_preflight)
    if os.environ.get("CASEOPS_TEST_RESULT_JOURNAL"):
        target = (
            Path(os.environ["CASEOPS_TEST_RESULT_JOURNAL"]).parent / "downgrade-post-preflight.json"
        )
        target.write_text(
            json.dumps({"statements": statements, "writer_sqlstate": caught.value.orig.sqlstate}),
            encoding="utf-8",
        )
    lock_at = next(i for i, sql in enumerate(statements) if sql.startswith("LOCK TABLE "))
    assert all(i > lock_at for i, sql in enumerate(statements) if sql.startswith("SELECT 1 "))
    assert TABLES.isdisjoint(inspect(engine).get_table_names())
