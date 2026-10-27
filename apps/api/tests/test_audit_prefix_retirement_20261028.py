"""IPLF-030B/UJ-04: guarded prefix retirement and fresh migration recovery.

Wrong-shape cases are native catalogue-guard units on independent minimal
schemas, not full-history migration acceptance. The other twenty cases rehearse
fresh complete migration history, ownership, interruption and rollback.
"""

from __future__ import annotations

import importlib.util
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.db.models import AuditEvent
from tests import test_audit_provenance_identity_index_20261028 as parent
from tests.test_audit_provenance_identity_index_20261028 import (
    DIALECTS,
    _append,
    _config,
    _insert,
    _owners,
    _snapshot,
    _version,
)
from tests.test_queue_isolation_migration_recovery_20261010 import _index_state

database = parent.database

API = Path(__file__).resolve().parents[1]
MIGRATION = API / "alembic/versions/20261028_0002_retire_audit_company_action_prefix.py"
REVISION = "20261028_0002"
PARENT = "20261028_0001"
ANCESTOR = "20261026_0001"
TABLE = "audit_events"
LEGACY = "ix_audit_events_company_action"
FULL = "ix_audit_events_source_provenance"
PREFIX = ["company_id", "action"]
COLUMNS = [*PREFIX, "target_type", "target_id", "ip_docket_id"]
PG_CONFLICTS = [
    "columns", "reversed", "predicate", "include", "order", "expression",
    "opclass", "collation", "unique", "method", "owner", "object",
]
SQLITE_CONFLICTS = [
    "columns", "reversed", "predicate", "order", "expression", "collation",
    "unique", "owner", "object",
]


def _module():
    spec = importlib.util.spec_from_file_location("audit_prefix_retirement", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(engine, operation="upgrade", *, destination=PARENT):
    with engine.connect() as connection:
        opts = {} if destination is None else {"destination_rev": destination}
        context = MigrationContext.configure(connection, opts=opts)
        with context.begin_transaction(), Operations.context(context):
            getattr(_module(), operation)()


def _state(engine, name):
    columns = COLUMNS if name == FULL else PREFIX
    with engine.connect() as connection:
        module = _module()
        if engine.dialect.name == "postgresql":
            return module._postgres_state(connection, name, columns)
        return module._sqlite_exists(connection, name, columns)


def _healthy(engine, name):
    state = _state(engine, name)
    assert state
    if engine.dialect.name == "postgresql":
        assert state["indisvalid"] and state["indisready"] and state["indislive"]


def _catalog(engine):
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            return connection.execute(sa.text(
                "SELECT c.relname, c.oid, pg_get_indexdef(c.oid), "
                "i.indisvalid, i.indisready, i.indislive "
                "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                "JOIN pg_class t ON t.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = current_schema() AND t.relname = :table "
                "ORDER BY c.relname"
            ), {"table": TABLE}).all()
        return connection.execute(sa.text(
            "SELECT name, sql FROM main.sqlite_master "
            "WHERE type = 'index' AND tbl_name = :table ORDER BY name"
        ), {"table": TABLE}).all()


def _others(engine):
    return [tuple(row) for row in _catalog(engine) if row[0] not in {LEGACY, FULL}]


def _object(engine, name):
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            return connection.execute(sa.text(
                "SELECT c.oid, c.relkind, pg_get_indexdef(i.indexrelid), "
                "i.indisvalid, i.indisready, i.indislive "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE n.nspname = current_schema() AND c.relname = :name"
            ), {"name": name}).one_or_none()
        return connection.execute(sa.text(
            "SELECT type, tbl_name, sql FROM main.sqlite_master WHERE name = :name"
        ), {"name": name}).one_or_none()


def _seed_shared(engine):
    company, _actor, matter = _owners(engine)
    foreign, _foreign_actor, foreign_matter = _owners(engine)
    start = datetime(2026, 10, 28, 12, tzinfo=UTC)
    duplicate_target = str(uuid4())
    data = []
    for tenant, parent_matter, action, offset, target in (
        (company, matter, "migration.provenance.fixture", 0, duplicate_target),
        (company, matter, "migration.provenance.fixture", 1, duplicate_target),
        (company, matter, "migration.provenance.fixture", 1, duplicate_target),
        (company, matter, "migration.provenance.fixture", 2, duplicate_target),
        (company, matter, "migration.other.fixture", 1, str(uuid4())),
        (foreign, foreign_matter, "migration.provenance.fixture", 1, duplicate_target),
    ):
        data.append({
            "id": str(uuid4()), "company_id": tenant, "matter_id": parent_matter,
            "actor_type": "system", "action": action, "target_type": "migration_fixture",
            "target_id": target, "result": "success", "metadata_json": '{"fixture":true}',
            "created_at": start + timedelta(minutes=offset),
        })
    with engine.begin() as connection:
        connection.execute(AuditEvent.__table__.insert(), data)
    return company, foreign, start, data


def _shared_reads(engine, company, foreign, start):
    table = AuditEvent.__table__
    filters = (table.c.company_id == company,
               table.c.action == "migration.provenance.fixture",
               table.c.created_at >= start + timedelta(minutes=1),
               table.c.created_at <= start + timedelta(minutes=2))
    statement = sa.select(table.c.id, table.c.target_id, table.c.created_at).where(*filters)
    with engine.connect() as connection:
        rows = connection.execute(statement.order_by(table.c.created_at, table.c.id)).all()
        page = connection.execute(statement.order_by(
            table.c.created_at, table.c.id).offset(1).limit(2)).all()
        count = connection.scalar(sa.select(sa.func.count()).select_from(table).where(*filters))
        other = connection.execute(sa.select(table.c.id).where(
            table.c.company_id == foreign,
            table.c.action == "migration.provenance.fixture",
        ).order_by(table.c.id)).all()
    assert count == len(rows) == 3 and page == rows[1:3] and len(other) == 1
    assert rows[0].target_id == rows[1].target_id == rows[2].target_id
    assert not ({row.id for row in rows} & {row.id for row in other})
    return rows, page, count, other


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_fresh_upgrade_retires_only_the_legacy_prefix(database):
    engine, config = database, _config()
    command.upgrade(config, REVISION)
    _healthy(engine, FULL)
    assert not _state(engine, LEGACY) and _version(engine) == REVISION
    assert {row[0] for row in _catalog(engine)} >= {
        "ix_audit_events_company_created", "ix_audit_events_company_id",
        "ix_audit_events_action", "ix_audit_events_target_id", FULL,
    }
    assert LEGACY not in {index.name for index in AuditEvent.__table__.indexes}


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_parent_replay_restore_preserve_rows_and_shared_readers(database, record_property):
    engine, config = database, _config()
    command.upgrade(config, PARENT)
    _healthy(engine, FULL)
    _healthy(engine, LEGACY)
    company, foreign, start, data = _seed_shared(engine)
    before, others = _snapshot(engine), _others(engine)
    full = _object(engine, FULL)
    reads = _shared_reads(engine, company, foreign, start)
    command.upgrade(config, REVISION)
    _apply(engine)
    command.upgrade(config, REVISION)
    assert not _state(engine, LEGACY) and _object(engine, FULL) == full
    assert _others(engine) == others and _snapshot(engine) == before
    assert _shared_reads(engine, company, foreign, start) == reads
    command.downgrade(config, PARENT)
    _healthy(engine, LEGACY)
    assert _object(engine, FULL) == full and _version(engine) == PARENT
    assert _snapshot(engine) == before and _others(engine) == others
    assert _shared_reads(engine, company, foreign, start) == reads
    _apply(engine, "downgrade")
    command.upgrade(config, REVISION)
    assert not _state(engine, LEGACY) and _object(engine, FULL) == full
    assert _snapshot(engine) == before and _shared_reads(engine, company, foreign, start) == reads
    record_property("retained_exact_audit_ids", sorted(row["id"] for row in data))


def _wrong_shape(engine, name, conflict, monkeypatch):
    # Guard units need real catalogue objects, not another full migration replay.
    parent._minimal(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE INDEX {FULL} ON {TABLE} ({', '.join(COLUMNS)})"
        )
        connection.exec_driver_sql(
            f"CREATE INDEX {LEGACY} ON {TABLE} ({', '.join(PREFIX)})"
        )
        connection.exec_driver_sql(f'DROP INDEX "{name}"')
    if name == LEGACY and conflict == "columns":
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE INDEX {LEGACY} ON {TABLE} (company_id)")
    else:
        # Reuse the existing actual-SQL adversaries, not duplicated schema fixtures.
        with monkeypatch.context() as patch:
            patch.setattr(parent, "NAME", name)
            patch.setattr(parent, "COLUMNS", COLUMNS if name == FULL else PREFIX)
            parent._conflict(engine, conflict)
    before, catalog = _snapshot(engine), _catalog(engine)
    objects = (_object(engine, FULL), _object(engine, LEGACY))
    for operation in ("upgrade", "downgrade"):
        with pytest.raises(RuntimeError, match="conflicting shape"):
            _apply(engine, operation)
        assert _snapshot(engine) == before and _catalog(engine) == catalog
        assert (_object(engine, FULL), _object(engine, LEGACY)) == objects
        assert not sa.inspect(engine).has_table("alembic_version")


@pytest.mark.postgres
@pytest.mark.parametrize("name", [LEGACY, FULL])
@pytest.mark.parametrize("conflict", PG_CONFLICTS)
def test_postgres_wrong_shape_is_never_retired_or_rewritten(database, name, conflict, monkeypatch):
    _wrong_shape(database, name, conflict, monkeypatch)


@pytest.mark.parametrize("database", ["sqlite"], indirect=True)
@pytest.mark.parametrize("name", [LEGACY, FULL])
@pytest.mark.parametrize("conflict", SQLITE_CONFLICTS)
def test_sqlite_wrong_shape_is_never_retired_or_rewritten(database, name, conflict, monkeypatch):
    _wrong_shape(database, name, conflict, monkeypatch)


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_missing_full_leaves_legacy_untouched_for_both_operations(database):
    engine = database
    command.upgrade(_config(), PARENT)
    _append(engine, _owners(engine)[0])
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {FULL}")
    before, legacy = _snapshot(engine), _object(engine, LEGACY)
    for operation in ("upgrade", "downgrade"):
        with pytest.raises(RuntimeError, match="missing or unready"):
            _apply(engine, operation)
        assert _object(engine, LEGACY) == legacy and _snapshot(engine) == before
        assert _version(engine) == PARENT


@pytest.mark.parametrize("database", DIALECTS, indirect=True)
def test_absent_legacy_is_idempotent_only_behind_a_healthy_full(database):
    engine = database
    command.upgrade(_config(), PARENT)
    _append(engine, _owners(engine)[0])
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {LEGACY}")
    before, full = _snapshot(engine), _object(engine, FULL)
    _apply(engine)
    _apply(engine)
    assert _object(engine, FULL) == full and _snapshot(engine) == before
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {FULL}")
    with pytest.raises(RuntimeError, match="missing or unready"):
        _apply(engine)
    assert not _state(engine, LEGACY) and _snapshot(engine) == before


@pytest.mark.parametrize("database", ["sqlite"], indirect=True)
@pytest.mark.parametrize("destination", [ANCESTOR, "base", None])
def test_sqlite_nonparent_downgrade_refuses_before_any_ddl(database, destination):
    engine, config = database, _config()
    command.upgrade(config, REVISION)
    _append(engine, _owners(engine)[0])
    before, catalog = _snapshot(engine), _catalog(engine)
    with pytest.raises(RuntimeError, match="exact immediate parent"):
        if destination is None:
            _apply(engine, "downgrade", destination=None)
        else:
            command.downgrade(config, destination)
    assert _catalog(engine) == catalog and _snapshot(engine) == before
    assert _version(engine) == REVISION


@pytest.mark.postgres
def test_full_in_a_different_schema_cannot_authorize_retirement(database):
    engine = database
    command.upgrade(_config(), PARENT)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA foreign_catalog")
        connection.exec_driver_sql(f"DROP INDEX {FULL}")
        connection.exec_driver_sql(f"CREATE TABLE foreign_catalog.{TABLE} (LIKE {TABLE})")
        connection.exec_driver_sql(
            f"CREATE INDEX {FULL} ON foreign_catalog.{TABLE} ({', '.join(COLUMNS)})"
        )
    legacy, before = _object(engine, LEGACY), _snapshot(engine)
    with pytest.raises(RuntimeError, match="missing or unready"):
        _apply(engine)
    assert _object(engine, LEGACY) == legacy and _snapshot(engine) == before


@pytest.mark.postgres
def test_foreign_schema_legacy_is_not_an_owned_drop_target(database):
    engine = database
    command.upgrade(_config(), PARENT)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {LEGACY}")
        connection.exec_driver_sql("CREATE SCHEMA foreign_catalog")
        connection.exec_driver_sql(f"CREATE TABLE foreign_catalog.{TABLE} (LIKE {TABLE})")
        connection.exec_driver_sql(
            f"CREATE INDEX {LEGACY} ON foreign_catalog.{TABLE} ({', '.join(PREFIX)})"
        )
    with engine.connect() as connection:
        oid = connection.scalar(sa.text(f"SELECT 'foreign_catalog.{LEGACY}'::regclass::oid"))
    _apply(engine)
    with engine.connect() as connection:
        assert connection.scalar(sa.text(
            f"SELECT 'foreign_catalog.{LEGACY}'::regclass::oid"
        )) == oid
    _healthy(engine, FULL)


def _cancel_upgrade(engine, revision, name, phase, company, record_property):
    """Observe/cancel real native DDL in this fresh DB, retaining ordinary appends."""
    held, observed = [], {}
    create = name == FULL

    def target(connection, statement):
        return (connection.engine.url.database == engine.url.database
                and statement.startswith("CREATE INDEX CONCURRENTLY" if create
                                         else "DROP INDEX CONCURRENTLY")
                and re.search(rf"\b{re.escape(name)}\b", statement))

    def hold(connection, cursor, statement, parameters, context, executemany):
        if not target(connection, statement) or held:
            return
        assert connection.connection.driver_connection.autocommit is True
        for setting in ("lock_timeout", "statement_timeout"):
            observed[setting] = connection.exec_driver_sql("SHOW " + setting).scalar_one()
        blocker = engine.connect().execution_options(isolation_level="REPEATABLE READ")
        held.append(blocker)
        if phase == "writers":
            _insert(blocker, company)
        else:
            blocker.execute(sa.text(f"SELECT * FROM {TABLE}")).all()

    event.listen(Engine, "before_cursor_execute", hold)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(command.upgrade, _config(), revision)
            try:
                deadline, cancelled = time.monotonic() + 30, False
                while time.monotonic() < deadline and not future.done():
                    state = _index_state(engine, name)
                    wanted = (state is not None and not state.indisvalid
                              and (not create or state.indisready == (phase == "snapshots")))
                    if wanted:
                        with engine.connect().execution_options(
                            isolation_level="AUTOCOMMIT"
                        ) as monitor:
                            pid = monitor.scalar(sa.text(
                                "SELECT pid FROM pg_stat_activity WHERE datname = :database "
                                "AND state = 'active' AND query LIKE :query "
                                "AND wait_event_type = 'Lock'"
                            ), {"database": engine.url.database,
                                "query": ("CREATE INDEX CONCURRENTLY" if create else
                                          "DROP INDEX CONCURRENTLY") + f"%{name}%"})
                            if pid is not None:
                                started = time.monotonic()
                                observed["concurrent_audit"] = _append(engine, company)
                                observed["append_seconds"] = time.monotonic() - started
                                assert observed["append_seconds"] < 2
                                assert monitor.scalar(
                                    sa.text("SELECT pg_cancel_backend(:pid)"), {"pid": pid}
                                )
                                cancelled = True
                                break
                    time.sleep(0.02)
                assert cancelled, "Real owned concurrent-DDL wait was not observed"
                with pytest.raises(DBAPIError) as error:
                    future.result(timeout=10)
                assert error.value.orig.sqlstate == "57014"
            finally:
                for blocker in held:
                    blocker.rollback()
                    blocker.close()
                held.clear()
    finally:
        event.remove(Engine, "before_cursor_execute", hold)
    assert observed["lock_timeout"] == "5s" and observed["statement_timeout"] == "15min"
    record_property("native_cancel_and_writer", observed)
    return observed


@pytest.mark.postgres
@pytest.mark.parametrize("phase", ["writers", "snapshots"])
def test_real_unready_full_leaves_legacy_untouched_until_parent_repairs(
    database, phase, record_property,
):
    engine, config = database, _config()
    command.upgrade(config, ANCESTOR)
    company = _owners(engine)[0]
    _append(engine, company)
    legacy = _object(engine, LEGACY)
    _cancel_upgrade(engine, PARENT, FULL, phase, company, record_property)
    failed = _index_state(engine, FULL)
    assert failed is not None and not failed.indisvalid
    assert failed.indisready == (phase == "snapshots") and _version(engine) == ANCESTOR
    before = _snapshot(engine)
    for operation in ("upgrade", "downgrade"):
        with pytest.raises(RuntimeError, match="missing or unready"):
            _apply(engine, operation)
        assert _object(engine, LEGACY) == legacy and _snapshot(engine) == before
    command.upgrade(config, PARENT)
    _healthy(engine, FULL)
    command.upgrade(config, REVISION)
    assert not _state(engine, LEGACY) and _snapshot(engine) == before


@pytest.mark.postgres
@pytest.mark.parametrize("phase", ["before", "after"])
def test_drop_dispatch_interruption_resumes_without_parent_rewrite(database, phase):
    engine, config = database, _config()
    command.upgrade(config, PARENT)
    _append(engine, _owners(engine)[0])
    before, full, legacy = _snapshot(engine), _object(engine, FULL), _object(engine, LEGACY)

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if (connection.engine.url.database == engine.url.database
                and statement.startswith("DROP INDEX CONCURRENTLY") and LEGACY in statement):
            assert connection.connection.driver_connection.autocommit is True
            raise RuntimeError("staged-interruption-" + phase)

    hook = "before_cursor_execute" if phase == "before" else "after_cursor_execute"
    event.listen(Engine, hook, interrupt)
    try:
        with pytest.raises(RuntimeError, match="staged-interruption-" + phase):
            command.upgrade(config, REVISION)
    finally:
        event.remove(Engine, hook, interrupt)
    assert _version(engine) == PARENT and _object(engine, FULL) == full
    assert _snapshot(engine) == before
    assert _object(engine, LEGACY) == (legacy if phase == "before" else None)
    command.upgrade(config, REVISION)
    _apply(engine)
    assert not _state(engine, LEGACY) and _object(engine, FULL) == full
    assert _snapshot(engine) == before and _version(engine) == REVISION


@pytest.mark.postgres
def test_real_cancelled_drop_allows_append_and_resumes(database, record_property):
    engine, config = database, _config()
    command.upgrade(config, PARENT)
    company = _owners(engine)[0]
    _append(engine, company)
    original, full = {row.id: tuple(row) for row in _snapshot(engine)}, _object(engine, FULL)
    observed = _cancel_upgrade(engine, REVISION, LEGACY, "snapshots", company, record_property)
    failed = _index_state(engine, LEGACY)
    assert failed is not None and not failed.indisvalid and _version(engine) == PARENT
    before = _snapshot(engine)
    assert {row.id for row in before} == set(original) | {observed["concurrent_audit"]}
    assert {row.id: tuple(row) for row in before if row.id in original} == original
    with pytest.raises(RuntimeError, match="Restored legacy audit prefix is unready"):
        _apply(engine, "downgrade")
    assert _snapshot(engine) == before and _object(engine, FULL) == full
    command.upgrade(config, REVISION)
    _apply(engine)
    assert not _state(engine, LEGACY) and _object(engine, FULL) == full
    assert _snapshot(engine) == before and _version(engine) == REVISION


@pytest.mark.postgres
@pytest.mark.parametrize("blocked_phase", ["restore", "parent_drop"])
def test_restore_and_parent_drop_share_one_rollback_boundary(
    database, blocked_phase, record_property,
):
    engine, config = database, _config()
    command.upgrade(config, REVISION)
    company = _owners(engine)[0]
    _append(engine, company)
    before, full, others = _snapshot(engine), _object(engine, FULL), _others(engine)
    budgets, ddl = {}, []

    def observe(connection, cursor, statement, parameters, context, executemany):
        if (connection.engine.url.database == engine.url.database
                and (statement.startswith("CREATE INDEX") or statement.startswith("DROP INDEX"))
                and (LEGACY in statement or FULL in statement)):
            assert connection.connection.driver_connection.autocommit is False
            assert "CONCURRENTLY" not in statement
            ddl.append(statement)
            for setting in ("lock_timeout", "statement_timeout"):
                budgets[setting] = connection.exec_driver_sql("SHOW " + setting).scalar_one()

    destination = PARENT if blocked_phase == "restore" else ANCESTOR
    event.listen(Engine, "before_cursor_execute", observe)
    try:
        with engine.connect() as blocker:
            if blocked_phase == "restore":
                _insert(blocker, company)
            else:
                blocker.execute(sa.text(f"SELECT * FROM {TABLE} LIMIT 1")).all()
            started = time.monotonic()
            with pytest.raises(DBAPIError) as error:
                command.downgrade(config, destination)
            elapsed = time.monotonic() - started
            assert error.value.orig.sqlstate == "55P03" and elapsed < 10
            assert blocker.scalar(sa.text("SELECT 1")) == 1
            blocker.rollback()
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert budgets == {"lock_timeout": "5s", "statement_timeout": "15min"}
    assert ddl and LEGACY in ddl[0]
    if blocked_phase == "parent_drop":
        assert FULL in ddl[-1]
    assert _version(engine) == REVISION and _object(engine, FULL) == full
    assert not _state(engine, LEGACY) and _snapshot(engine) == before and _others(engine) == others
    command.downgrade(config, destination)
    _healthy(engine, LEGACY)
    if destination == PARENT:
        assert _object(engine, FULL) == full
    else:
        assert not _state(engine, FULL)
    assert _version(engine) == destination and _snapshot(engine) == before
    record_property("transactional_restore_timeout", {
        "phase": blocked_phase, "sqlstate": "55P03", "elapsed_seconds": elapsed,
        "budgets": budgets, "ddl": ddl,
    })
