"""IPLF-030B/UJ-04: independent provenance-index migration rehearsals."""

from __future__ import annotations

import importlib.util
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent
from caseops_api.db.session import clear_engine_cache
from caseops_api.scripts.check_database_indexes import _declared_index_columns
from tests.test_queue_isolation_migration_recovery_20261010 import _index_state, _owners

API = Path(__file__).resolve().parents[1]
REVISION = "20261028_0001"
PREVIOUS = "20261026_0001"
NAME = "ix_audit_events_source_provenance"
TABLE = "audit_events"
COLUMNS = ["company_id", "action", "target_type", "target_id", "ip_docket_id"]
MIGRATION = API / "alembic/versions/20261028_0001_audit_provenance_identity_index.py"
DIALECTS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


def _config():
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "alembic"))
    return config


def _module():
    spec = importlib.util.spec_from_file_location("audit_provenance_migration", MIGRATION)
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
    """Migrate a new database from template0, never clone application rows."""
    kind = getattr(request, "param", "postgres")
    admin_engine, name = None, None
    if kind == "postgres":
        admin_engine = request.getfixturevalue("pg_engine")
        name = "audit_provenance_index_" + uuid4().hex
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(sa.text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
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
            assert name is not None and re.fullmatch(r"audit_provenance_index_[0-9a-f]{32}", name)
            assert name != admin_engine.url.database
            with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
                admin.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                assert not admin.scalar(
                    sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                )
            record_property("independent_postgres_database_removed", True)
        else:
            record_property("sqlite_file_retained_as_test_artifact", True)
        record_property("independent_connections_closed", True)


def _insert(connection, company):
    identity = str(uuid4())
    connection.execute(
        sa.text(
            f"INSERT INTO {TABLE} (id, company_id, actor_type, action, target_type, "
            "target_id, ip_docket_id, result, created_at) VALUES "
            "(:id, :company, 'system', 'migration.provenance.fixture', 'migration_fixture', "
            ":target, NULL, 'success', CURRENT_TIMESTAMP)"
        ),
        {"id": identity, "company": company, "target": str(uuid4())},
    )
    return identity


def _append(engine, company):
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
        return _insert(connection, company)


def _snapshot(engine):
    with engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT * FROM {TABLE} ORDER BY id")).all()


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
            connection.execute(
                sa.text("SELECT sql FROM main.sqlite_master WHERE name = :name"), {"name": NAME}
            ).one()
        )


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_parent_roundtrip_and_restart_preserve_append_only_audit(database, record_property):
    engine, config = database, _config()
    command.upgrade(config, PREVIOUS)
    company = _owners(engine)[0]
    ids = [_append(engine, company) for _ in range(3)]
    before = _snapshot(engine)
    command.upgrade(config, REVISION)
    shape = _shape(engine)
    _apply(engine)
    command.upgrade(config, REVISION)
    assert _shape(engine) == shape and _snapshot(engine) == before
    command.downgrade(config, PREVIOUS)
    assert NAME not in {row["name"] for row in sa.inspect(engine).get_indexes(TABLE)}
    assert _version(engine) == PREVIOUS and _snapshot(engine) == before
    _apply(engine, "downgrade")
    command.upgrade(config, REVISION)
    _shape(engine)
    assert _version(engine) == REVISION and _snapshot(engine) == before
    record_property("audit_rows_preserved", sorted(ids))


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_fresh_upgrade_has_exact_nonpartial_model_parity(database):
    engine = database
    command.upgrade(_config(), REVISION)
    _shape(engine)
    declared = next(index for index in AuditEvent.__table__.indexes if index.name == NAME)
    assert _declared_index_columns(declared) == tuple(COLUMNS)
    actual = next(row for row in sa.inspect(engine).get_indexes(TABLE) if row["name"] == NAME)
    assert actual["column_names"] == COLUMNS and not actual["unique"]
    assert _version(engine) == REVISION


@pytest.mark.parametrize("database", ["sqlite"], indirect=True)
@pytest.mark.parametrize("destination", ["20261019_0001", "base", None])
def test_sqlite_wide_or_unknown_downgrade_refuses_before_drop(database, destination):
    engine = database
    command.upgrade(_config(), REVISION)
    _append(engine, _owners(engine)[0])
    before, shape = _snapshot(engine), _shape(engine)
    with pytest.raises(RuntimeError, match="exact immediate parent"):
        if destination is None:
            _apply(engine, "downgrade", destination=None)
        else:
            command.downgrade(_config(), destination)
    assert _shape(engine) == shape and _snapshot(engine) == before
    assert _version(engine) == REVISION


def _minimal(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {TABLE} (id varchar(36) PRIMARY KEY, company_id varchar(36) NOT NULL, "
            "action varchar(80) NOT NULL, target_type varchar(80) NOT NULL, "
            "target_id varchar(120), ip_docket_id varchar(36))"
        )
        connection.exec_driver_sql(
            f"INSERT INTO {TABLE} (id, company_id, action, target_type, target_id) "
            "VALUES ('retained', 'company', 'fixture', 'fixture', 'source')"
        )


def _conflict(engine, conflict):
    columns = ", ".join(COLUMNS)
    prefix, suffix, method, table = "", "", "", TABLE
    with engine.begin() as connection:
        if conflict == "object":
            connection.exec_driver_sql(f"CREATE TABLE {NAME} (id integer)")
            return
        if conflict == "columns":
            columns = "company_id, action"
        elif conflict == "reversed":
            columns = ", ".join(reversed(COLUMNS))
        elif conflict == "predicate":
            suffix = " WHERE ip_docket_id IS NOT NULL"
        elif conflict == "include":
            suffix = " INCLUDE (id)"
        elif conflict == "order":
            columns = "company_id DESC, " + ", ".join(COLUMNS[1:])
        elif conflict == "expression":
            columns = "lower(company_id), " + ", ".join(COLUMNS[1:])
        elif conflict == "opclass":
            columns = "company_id varchar_pattern_ops, " + ", ".join(COLUMNS[1:])
        elif conflict == "collation":
            collation = "POSIX" if engine.dialect.name == "postgresql" else "NOCASE"
            columns = f'company_id COLLATE "{collation}", ' + ", ".join(COLUMNS[1:])
        elif conflict == "unique":
            prefix = "UNIQUE "
        elif conflict == "method":
            method, columns = " USING hash", "company_id"
        elif conflict == "owner":
            table = "other_audit_events"
            connection.exec_driver_sql(
                f"CREATE TABLE {table} (company_id varchar(36), action varchar(80), "
                "target_type varchar(80), target_id varchar(120), ip_docket_id varchar(36))"
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
                    "SELECT c.oid, c.relkind, pg_get_indexdef(i.indexrelid), i.indisvalid, i.indisready "
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


def _assert_conflict(engine, conflict):
    _minimal(engine)
    _conflict(engine, conflict)
    before, shape = _snapshot(engine), _object_state(engine)
    for operation in ("upgrade", "downgrade"):
        with pytest.raises(RuntimeError, match="conflicting shape"):
            _apply(engine, operation)
        assert _object_state(engine) == shape and _snapshot(engine) == before


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


@pytest.mark.postgres
@pytest.mark.parametrize("phase", ["writers", "snapshots"])
def test_cancelled_concurrent_build_recovers_without_audit_loss(database, phase, record_property):
    engine, config = database, _config()
    command.upgrade(config, PREVIOUS)
    company = _owners(engine)[0]
    ids = [_append(engine, company) for _ in range(2)]
    original = {row.id: tuple(row) for row in _snapshot(engine)}
    assert set(original) == set(ids)
    held, observed, admitted = [], {}, {}

    def before_build(connection, cursor, statement, parameters, context, executemany):
        if (
            connection.engine.url.database != engine.url.database
            or not statement.startswith(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} ")
            or held
        ):
            return
        assert connection.connection.driver_connection.autocommit is True
        for setting in ("lock_timeout", "statement_timeout"):
            observed[setting] = connection.exec_driver_sql("SHOW " + setting).scalar_one()
        blocker = engine.connect().execution_options(isolation_level="REPEATABLE READ")
        held.append(blocker)
        if phase == "writers":
            # Retain an uncommitted append, never UPDATE an immutable audit row.
            _insert(blocker, company)
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
                                observed["concurrent_audit"] = _append(engine, company)
                                admitted.update(
                                    {
                                        row.id: tuple(row)
                                        for row in _snapshot(engine)
                                        if row.id == observed["concurrent_audit"]
                                    }
                                )
                                assert set(admitted) == {observed["concurrent_audit"]}
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
    before = _snapshot(engine)
    assert {row.id for row in before} == set(ids) | set(admitted)
    assert {row.id: tuple(row) for row in before if row.id in original} == original
    assert {row.id: tuple(row) for row in before if row.id in admitted} == admitted
    command.upgrade(config, REVISION)
    healthy = _shape(engine)
    assert healthy[0] != failed.oid and _snapshot(engine) == before
    _apply(engine)
    assert _shape(engine) == healthy and _snapshot(engine) == before
    record_property(
        "native_interruption",
        {
            "phase": phase,
            "sqlstate": "57014",
            "invalid_state": tuple(failed),
            "budgets": observed,
            "exact_audit_ids": sorted(row.id for row in before),
        },
    )


@pytest.mark.postgres
def test_ordinary_drop_lock_timeout_preserves_index_head_and_audit(database, record_property):
    engine, config = database, _config()
    command.upgrade(config, REVISION)
    _append(engine, _owners(engine)[0])
    before, shape = _snapshot(engine), _shape(engine)
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
    assert _snapshot(engine) == before
    command.downgrade(config, PREVIOUS)
    assert _version(engine) == PREVIOUS and _snapshot(engine) == before
    record_property("drop_lock_timeout", {"sqlstate": "55P03", "elapsed_seconds": elapsed})
