"""Independent migration rehearsals for the tenant/source receipt index."""

from __future__ import annotations

import importlib.util
import json
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import DocumentProcessingJob
from caseops_api.db.session import clear_engine_cache
from caseops_api.scripts.check_database_indexes import (
    _declared_index_columns,
    build_index_health_report,
)
from tests.test_queue_isolation_migration_recovery_20261010 import (
    QUEUES,
    _index_state,
    _owners,
    _snapshot,
)

API = Path(__file__).resolve().parents[1]
REVISION = "20261019_0001"
PREVIOUS = "20261015_0001"
NAME = "ix_document_processing_jobs_company_target"
TABLE = "document_processing_jobs"
COLUMNS = ["company_id", "target_type"]
MIGRATION = API / "alembic/versions/20261019_0001_document_processing_company_target_index.py"
DIALECTS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


def _config():
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "alembic"))
    return config


def _module():
    spec = importlib.util.spec_from_file_location("document_company_index_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(engine, operation="upgrade", *, destination=PREVIOUS):
    with engine.connect() as connection:
        opts = {} if destination is None else {"destination_rev": destination}
        context = MigrationContext.configure(connection, opts=opts)
        with context.begin_transaction(), Operations.context(context):
            getattr(_module(), operation)()


@pytest.fixture
def database(request, tmp_path, monkeypatch, record_property):
    """Each rehearsal creates a fresh database, never a migrated tenant clone."""
    kind = getattr(request, "param", "postgres")
    admin_engine = None
    name = None
    if kind == "postgres":
        admin_engine = request.getfixturevalue("pg_engine")
        name = "document_index_" + uuid4().hex
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(sa.text(f'CREATE DATABASE "{name}"'))
        engine = sa.create_engine(admin_engine.url.set(database=name))
        record_property("independent_database", name)
    else:
        assert kind == "sqlite"
        engine = sa.create_engine("sqlite+pysqlite:///" + (tmp_path / "fresh.db").as_posix())
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("CASEOPS_ALEMBIC_CONFIG", str(API / "alembic.ini"))
    get_settings.cache_clear()
    clear_engine_cache()
    try:
        yield engine
    finally:
        clear_engine_cache()
        engine.dispose()
        get_settings.cache_clear()
        if admin_engine is not None:
            assert name is not None
            with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
                admin.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                assert not admin.scalar(
                    sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                )
            record_property("independent_postgres_database_removed", True)
        else:
            record_property("sqlite_file_retained_as_test_artifact", True)
        record_property("independent_connections_closed", True)


def _receipt(engine, company, marker=None):
    job_id = str(uuid4())
    columns = (
        "id, company_id, target_type, attachment_id, action, status, attempt_count, "
        "processed_char_count, queued_at, updated_at"
    )
    values = (
        ":id, :company, 'matter_attachment', :attachment, 'initial_index', 'queued', "
        "0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
    )
    parameters = {"id": job_id, "company": company, "attachment": str(uuid4())}
    if marker is not None:
        columns += ", no_paid_providers"
        values += ", :marker"
        parameters["marker"] = marker
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
        connection.execute(
            sa.text(f"INSERT INTO {TABLE} ({columns}) VALUES ({values})"), parameters
        )
    return job_id


def _version(engine):
    with engine.connect() as connection:
        return connection.scalar(sa.text("SELECT version_num FROM alembic_version"))


def _shape(engine):
    module = _module()
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            state = module._postgres_state(connection)
            assert state is not None and state["indisvalid"] and state["indisready"]
            return tuple(_index_state(engine, NAME))
        assert module._sqlite_exists(connection)
        return tuple(
            connection.exec_driver_sql(
                "SELECT sql FROM main.sqlite_master WHERE name = '" + NAME + "'"
            ).one()
        )


def _receipt_snapshot(engine):
    return _snapshot(engine, QUEUES[0])


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_parent_roundtrip_and_restart_preserve_populated_receipts(database, record_property):
    engine = database
    config = _config()
    command.upgrade(config, PREVIOUS)
    company = _owners(engine)[0]
    ids = [_receipt(engine, company, marker) for marker in (None, False, True)]
    before = _receipt_snapshot(engine)
    with engine.connect() as connection:
        assert dict(
            connection.execute(sa.text(f"SELECT id, no_paid_providers FROM {TABLE}")).all()
        ) == dict(zip(ids, (True, False, True), strict=True))
    command.upgrade(config, REVISION)
    original = _shape(engine)
    _apply(engine)
    command.upgrade(config, REVISION)
    assert _shape(engine) == original
    assert _receipt_snapshot(engine) == before
    command.downgrade(config, PREVIOUS)
    assert NAME not in {row["name"] for row in sa.inspect(engine).get_indexes(TABLE)}
    assert _version(engine) == PREVIOUS and _receipt_snapshot(engine) == before
    _apply(engine, "downgrade")
    command.upgrade(config, REVISION)
    _shape(engine)
    assert _version(engine) == REVISION and _receipt_snapshot(engine) == before
    record_property("roundtrip", {"markers": [True, False, True], "rows_unchanged": True})


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_fresh_current_head_has_complete_model_and_schema_health(
    database, tmp_path, record_property
):
    engine = database
    config = _config()
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1
    command.upgrade(config, "head")
    with engine.connect() as connection:
        report = build_index_health_report(connection)
    path = tmp_path / "current-head-index-health.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    record_property("current_head_index_health", report)
    record_property("current_head_index_health_artifact", str(path))
    assert report["status"] == "ok", report
    assert report["schema_revisions"] == heads == [report["required_schema_revision"]]
    declared = next(
        index for index in DocumentProcessingJob.__table__.indexes if index.name == NAME
    )
    assert _declared_index_columns(declared) == tuple(COLUMNS)
    assert (
        next(row for row in sa.inspect(engine).get_indexes(TABLE) if row["name"] == NAME)[
            "column_names"
        ]
        == COLUMNS
    )
    _shape(engine)


@pytest.mark.parametrize("database", ["sqlite"], indirect=True)
@pytest.mark.parametrize("destination", ["20261011_0001", "base", None])
def test_sqlite_wide_or_unknown_downgrade_refuses_before_drop(database, destination):
    engine = database
    config = _config()
    command.upgrade(config, REVISION)
    company = _owners(engine)[0]
    for marker in (False, True):
        _receipt(engine, company, marker)
    before, shape = _receipt_snapshot(engine), _shape(engine)
    with pytest.raises(RuntimeError, match="exact immediate parent"):
        if destination is None:
            _apply(engine, "downgrade", destination=None)
        else:
            command.downgrade(config, destination)
    assert _shape(engine) == shape
    assert _version(engine) == REVISION and _receipt_snapshot(engine) == before


def _minimal(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {TABLE} (id varchar(36) PRIMARY KEY, company_id varchar(36) NOT NULL, "
            "target_type varchar(40) NOT NULL, error_text text, "
            "no_paid_providers boolean NOT NULL DEFAULT true)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO {TABLE} (id, company_id, target_type, no_paid_providers) "
            "VALUES ('retained', 'company', 'matter_attachment', false)"
        )


def _conflict(engine, conflict):
    columns = "company_id, target_type"
    prefix, suffix, method, table = "", "", "", TABLE
    with engine.begin() as connection:
        if conflict == "object":
            connection.exec_driver_sql(f"CREATE TABLE {NAME} (id integer)")
            return
        if conflict == "columns":
            columns = "company_id"
        elif conflict == "reversed":
            columns = "target_type, company_id"
        elif conflict == "predicate":
            suffix = " WHERE no_paid_providers"
        elif conflict == "include":
            suffix = " INCLUDE (error_text)"
        elif conflict == "order":
            columns = "company_id DESC, target_type"
        elif conflict == "expression":
            columns = "lower(company_id), target_type"
        elif conflict == "opclass":
            columns = "company_id varchar_pattern_ops, target_type"
        elif conflict == "collation":
            collation = "POSIX" if engine.dialect.name == "postgresql" else "NOCASE"
            columns = f'company_id COLLATE "{collation}", target_type'
        elif conflict == "unique":
            prefix = "UNIQUE "
        elif conflict == "method":
            method, columns = " USING hash", "company_id"
        elif conflict == "owner":
            table = "other_jobs"
            connection.exec_driver_sql(
                f"CREATE TABLE {table} (company_id varchar(36), target_type varchar(40))"
            )
        else:
            raise AssertionError(conflict)
        connection.exec_driver_sql(
            f"CREATE {prefix}INDEX {NAME} ON {table}{method} ({columns}){suffix}"
        )


def _object_state(engine):
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            return connection.execute(
                sa.text(
                    "SELECT c.oid, c.relkind, pg_get_indexdef(i.indexrelid), "
                    "i.indisvalid, i.indisready "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE n.nspname = current_schema() AND c.relname = :name"
                ),
                {"name": NAME},
            ).one()
        return connection.execute(
            sa.text("SELECT type, tbl_name, sql FROM main.sqlite_master WHERE name = :name"),
            {"name": NAME},
        ).one()


@pytest.mark.postgres
@pytest.mark.parametrize(
    "conflict",
    [
        "columns",
        "reversed",
        "predicate",
        "include",
        "order",
        "expression",
        "opclass",
        "collation",
        "unique",
        "method",
        "owner",
        "object",
    ],
)
def test_postgres_conflicting_shape_never_drops_or_rewrites(database, conflict):
    _assert_conflict(database, conflict)


@pytest.mark.parametrize("database", ["sqlite"], indirect=True)
@pytest.mark.parametrize(
    "conflict",
    [
        "columns",
        "reversed",
        "predicate",
        "order",
        "expression",
        "collation",
        "unique",
        "owner",
        "object",
    ],
)
def test_sqlite_conflicting_shape_never_drops_or_rewrites(database, conflict):
    _assert_conflict(database, conflict)


def _assert_conflict(engine, conflict):
    _minimal(engine)
    _conflict(engine, conflict)
    before, shape = _receipt_snapshot(engine), _object_state(engine)
    for operation in ("upgrade", "downgrade"):
        with pytest.raises(RuntimeError, match="conflicting shape"):
            _apply(engine, operation)
        assert _object_state(engine) == shape
        assert _receipt_snapshot(engine) == before


@pytest.mark.postgres
@pytest.mark.parametrize("phase", ["writers", "snapshots"])
def test_cancelled_concurrent_build_recovers_without_receipt_loss(database, phase, record_property):
    engine, config = database, _config()
    command.upgrade(config, PREVIOUS)
    company = _owners(engine)[0]
    ids = [_receipt(engine, company, marker) for marker in (False, True)]
    original = {row.id: tuple(row) for row in _receipt_snapshot(engine)}
    assert set(original) == set(ids)
    admitted = {}
    held, observed = [], {}

    def before_build(connection, cursor, statement, parameters, context, executemany):
        if (
            connection.engine.url.database != engine.url.database
            or not statement.startswith(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} ")
            or held
        ):
            return
        assert connection.connection.driver_connection.autocommit is True
        observed["lock_timeout"] = connection.exec_driver_sql("SHOW lock_timeout").scalar_one()
        observed["statement_timeout"] = connection.exec_driver_sql(
            "SHOW statement_timeout"
        ).scalar_one()
        blocker = engine.connect().execution_options(isolation_level="REPEATABLE READ")
        held.append(blocker)
        if phase == "writers":
            # Timestamp bookkeeping retains the real writer wait without forging
            # the separately guarded execution protocol's status transition.
            blocker.execute(
                sa.text(f"UPDATE {TABLE} SET updated_at = updated_at WHERE id = :id"),
                {"id": ids[0]},
            )
        else:
            blocker.execute(sa.text(f"SELECT * FROM {TABLE}")).all()

    event.listen(Engine, "before_cursor_execute", before_build)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(command.upgrade, config, REVISION)
            try:
                deadline, cancelled = time.monotonic() + 30, False
                while time.monotonic() < deadline and not future.done():
                    state = _index_state(engine, NAME)
                    if (
                        state is not None
                        and not state.indisvalid
                        and state.indisready == (phase == "snapshots")
                    ):
                        with engine.connect().execution_options(
                            isolation_level="AUTOCOMMIT"
                        ) as monitor:
                            pid = monitor.scalar(
                                sa.text(
                                    "SELECT pid FROM pg_stat_activity WHERE datname = :database "
                                    "AND state = 'active' AND query LIKE :query "
                                    "AND wait_event_type = 'Lock' AND wait_event = 'virtualxid'"
                                ),
                                {
                                    "database": engine.url.database,
                                    "query": f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} %",
                                },
                            )
                            if pid is not None:
                                observed["concurrent_receipt"] = _receipt(engine, company, True)
                                admitted.update(
                                    {
                                        row.id: tuple(row)
                                        for row in _receipt_snapshot(engine)
                                        if row.id == observed["concurrent_receipt"]
                                    }
                                )
                                assert set(admitted) == {observed["concurrent_receipt"]}
                                assert monitor.scalar(
                                    sa.text("SELECT pg_cancel_backend(:pid)"), {"pid": pid}
                                )
                                cancelled = True
                                break
                    time.sleep(0.02)
                assert cancelled, "The real concurrent-build wait was not observed"
                with pytest.raises(DBAPIError) as error:
                    future.result(timeout=10)
                assert error.value.orig.sqlstate == "57014"
            finally:
                for blocker in held:
                    blocker.rollback()
                    blocker.close()
                held.clear()
    finally:
        event.remove(Engine, "before_cursor_execute", before_build)
    failed = _index_state(engine, NAME)
    assert failed is not None and not failed.indisvalid
    assert failed.indisready == (phase == "snapshots") and _version(engine) == PREVIOUS
    assert observed["lock_timeout"] == "5s" and observed["statement_timeout"] == "15min"
    before = _receipt_snapshot(engine)
    assert {row.id for row in before} == set(ids) | set(admitted)
    assert {row.id: tuple(row) for row in before if row.id in original} == original
    assert {row.id: tuple(row) for row in before if row.id in admitted} == admitted
    assert {row.id: row.no_paid_providers for row in before} == {
        ids[0]: False,
        ids[1]: True,
        observed["concurrent_receipt"]: True,
    }
    command.upgrade(config, REVISION)
    healthy = _shape(engine)
    assert healthy[0] != failed.oid
    assert _receipt_snapshot(engine) == before
    _apply(engine)
    assert _shape(engine) == healthy and _receipt_snapshot(engine) == before
    record_property(
        "native_interruption",
        {
            "phase": phase,
            "sqlstate": "57014",
            "invalid_state": tuple(failed),
            "budgets": observed,
            "original_rows_unchanged_after_first_attempt": True,
            "exact_receipt_ids": sorted(row.id for row in before),
        },
    )


@pytest.mark.postgres
def test_ordinary_drop_rolls_back_with_later_historical_refusal(database, record_property):
    engine, config = database, _config()
    command.upgrade(config, REVISION)
    company = _owners(engine)[0]
    for marker in (False, True):
        _receipt(engine, company, marker)
    before, shape = _receipt_snapshot(engine), _shape(engine)
    observed = []
    catalog_sql = sa.text(
        "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), pg_get_functiondef(t.tgfoid) "
        "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE c.relnamespace = 'public'::regnamespace AND NOT t.tgisinternal "
        "AND c.relname IN ('document_processing_jobs', 'matter_compliance_extraction_runs') "
        "ORDER BY c.relname, t.tgname"
    )
    with engine.connect() as connection:
        catalog = connection.execute(catalog_sql).all()

    def after_drop(connection, cursor, statement, parameters, context, executemany):
        if (
            connection.engine.url.database != engine.url.database
            or not statement.strip().startswith("DROP INDEX ")
            or NAME not in statement
        ):
            return
        assert "CONCURRENTLY" not in statement
        assert connection.connection.driver_connection.autocommit is False
        assert connection.scalar(sa.text("SELECT to_regclass(:name)"), {"name": NAME}) is None
        observed.append(
            {
                "statement": statement,
                "autocommit": False,
                "backend_pid": connection.scalar(sa.text("SELECT pg_backend_pid()")),
                "transaction": connection.scalar(sa.text("SELECT txid_current()")),
            }
        )

    event.listen(Engine, "after_cursor_execute", after_drop)
    config.cmd_opts = Namespace(x=["compliance_tail_fresh_downgrade=true"])
    try:
        with pytest.raises(RuntimeError, match="restore-forward"):
            command.downgrade(config, "20260928_0001")
    finally:
        event.remove(Engine, "after_cursor_execute", after_drop)
    assert len(observed) == 1, "The actual transactional DROP must precede the older refusal"
    assert _version(engine) == REVISION
    assert _shape(engine) == shape and _receipt_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.execute(catalog_sql).all() == catalog
        health = build_index_health_report(connection)
    assert health["status"] == "ok", health
    assert health["schema_revisions"] == [REVISION]
    record_property("current_head_health_after_refusal_rollback", health)
    record_property("transactional_drop_rollback", observed)


@pytest.mark.postgres
def test_ordinary_drop_lock_timeout_rolls_back_index_head_and_receipts(database, record_property):
    engine, config = database, _config()
    command.upgrade(config, REVISION)
    company = _owners(engine)[0]
    for marker in (False, True):
        _receipt(engine, company, marker)
    before, shape = _receipt_snapshot(engine), _shape(engine)
    with engine.connect() as reader:
        reader.execute(sa.text(f"SELECT * FROM {TABLE} LIMIT 1")).all()
        started = time.monotonic()
        with pytest.raises(DBAPIError) as error:
            command.downgrade(config, PREVIOUS)
        elapsed = time.monotonic() - started
        assert error.value.orig.sqlstate == "55P03" and elapsed < 10
        assert reader.scalar(sa.text("SELECT 1")) == 1
        reader.rollback()
    assert _shape(engine) == shape and _version(engine) == REVISION
    assert _receipt_snapshot(engine) == before
    command.downgrade(config, PREVIOUS)
    assert _version(engine) == PREVIOUS and _receipt_snapshot(engine) == before
    record_property("drop_lock_timeout", {"sqlstate": "55P03", "elapsed_seconds": elapsed})
