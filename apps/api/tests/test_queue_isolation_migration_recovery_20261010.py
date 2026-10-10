"""UJ-67: restartable queue expansion without discarding provider policy."""

from __future__ import annotations

import ast
import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership

API = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Queue:
    table: str
    migration: str
    previous: str
    filename: str

    def index(self, kind):
        return f"ix_{self.table}_{kind}"


QUEUES = (
    Queue(
        "document_processing_jobs",
        "20261010_0001",
        "20260928_0001",
        "20261010_0001_document_worker_claims.py",
    ),
    Queue(
        "matter_court_sync_jobs",
        "20261010_0002",
        "20261010_0001",
        "20261010_0002_court_sync_request_context.py",
    ),
)


def _module(queue):
    spec = importlib.util.spec_from_file_location(
        "queue_migration_" + queue.migration,
        API / "alembic" / "versions" / queue.filename,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(engine, queue, operation="upgrade"):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            getattr(_module(queue), operation)()


def _config():
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "alembic"))
    return config


@pytest.fixture
def independent_database(pg_engine, monkeypatch, record_property):
    name = "queue_recovery_" + uuid4().hex
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = sa.create_engine(pg_engine.url.set(database=name))
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    record_property("independent_database", name)
    try:
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            assert not admin.scalar(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
        record_property("independent_database_dropped", True)


def _minimal_table(engine, queue, marker_ddl=None):
    columns = (
        "id varchar(36) PRIMARY KEY, status varchar(24) NOT NULL, "
        "queued_at timestamp with time zone, updated_at timestamp with time zone, "
        "started_at timestamp with time zone"
    )
    with engine.begin() as connection:
        connection.execute(sa.text(f"CREATE TABLE {queue.table} ({columns})"))
        if marker_ddl:
            connection.execute(
                sa.text(f"ALTER TABLE {queue.table} ADD COLUMN no_paid_providers {marker_ddl}")
            )


@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
def test_static_concurrent_indexes_and_executable_restore_forward_refusal(queue):
    source = (API / "alembic" / "versions" / queue.filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "DATA-GOVERNANCE-MAP: updated" in source
    creates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_index"
    ]
    assert creates
    assert all(
        any(
            keyword.arg == "postgresql_concurrently"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in call.keywords
        )
        for call in creates
    )
    downgrade = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    assert len(downgrade.body) == 1 and isinstance(downgrade.body[0], ast.Raise)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith("drop_")
        for node in ast.walk(downgrade)
    )


@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
def test_sqlite_restart_preserves_true_false_and_refuses_downgrade(tmp_path, queue):
    engine = sa.create_engine("sqlite+pysqlite:///" + (tmp_path / "queue.db").as_posix())
    try:
        _minimal_table(engine, queue)
        with engine.begin() as connection:
            connection.execute(
                sa.text(f"INSERT INTO {queue.table} (id, status) VALUES ('old', 'queued')")
            )
        _apply(engine, queue)
        with engine.begin() as connection:
            assert (
                bool(
                    connection.scalar(
                        sa.text(f"SELECT no_paid_providers FROM {queue.table} WHERE id = 'old'")
                    )
                )
                is True
            )
            connection.execute(
                sa.text(
                    f"INSERT INTO {queue.table} (id, status, no_paid_providers) "
                    "VALUES ('human', 'queued', false)"
                )
            )
        _apply(engine, queue)
        with engine.connect() as connection:
            before = connection.execute(sa.text(f"SELECT * FROM {queue.table} ORDER BY id")).all()
        with pytest.raises(RuntimeError, match="restore-forward"):
            _apply(engine, queue, "downgrade")
        with engine.connect() as connection:
            assert (
                connection.execute(sa.text(f"SELECT * FROM {queue.table} ORDER BY id")).all()
                == before
            )
            assert {row["name"] for row in sa.inspect(connection).get_indexes(queue.table)} == {
                queue.index("queue"),
                queue.index("recovery"),
            }
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
@pytest.mark.parametrize(
    "shape",
    [
        "integer NOT NULL DEFAULT 1",
        "boolean DEFAULT true",
        "boolean NOT NULL DEFAULT false",
        "boolean NOT NULL",
    ],
)
def test_existing_column_conflicts_are_rejected_without_data_rewrite(
    independent_database, queue, shape
):
    engine = independent_database
    _minimal_table(engine, queue, shape)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                f"INSERT INTO {queue.table} (id, status, no_paid_providers) "
                "VALUES ('retained', 'queued', :value)"
            ),
            {"value": 1 if shape.startswith("integer") else False},
        )
    with engine.connect() as connection:
        before = connection.execute(sa.text(f"SELECT * FROM {queue.table}")).all()
        column = sa.inspect(connection).get_columns(queue.table)[-1]
        column_shape = (str(column["type"]), column["nullable"], column["default"])
    with pytest.raises(RuntimeError, match="no-paid marker has a conflicting shape"):
        _apply(engine, queue)
    with engine.connect() as connection:
        assert connection.execute(sa.text(f"SELECT * FROM {queue.table}")).all() == before
        column = sa.inspect(connection).get_columns(queue.table)[-1]
        assert (str(column["type"]), column["nullable"], column["default"]) == column_shape
        assert sa.inspect(connection).get_indexes(queue.table) == []


@pytest.mark.postgres
@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
@pytest.mark.parametrize("conflict", ["columns", "predicate", "include", "order", "owner"])
def test_conflicting_index_is_never_dropped(independent_database, queue, conflict):
    engine = independent_database
    _minimal_table(engine, queue, "boolean NOT NULL DEFAULT true")
    table = queue.table
    column_sql = (
        "status, queued_at, " + ("updated_at, " if table.startswith("matter_") else "") + "id"
    )
    tail = ""
    with engine.begin() as connection:
        if conflict == "columns":
            column_sql = "id"
        elif conflict == "predicate":
            tail = " WHERE status = 'queued'"
        elif conflict == "include":
            tail = " INCLUDE (started_at)"
        elif conflict == "order":
            column_sql = column_sql.replace("status", "status DESC")
        elif conflict == "owner":
            connection.execute(sa.text(f"CREATE TABLE other_queue (LIKE {table})"))
            table = "other_queue"
        connection.execute(
            sa.text(f"CREATE INDEX {queue.index('queue')} ON {table} ({column_sql}){tail}")
        )
        before = connection.execute(
            sa.text(
                "SELECT c.oid, pg_get_indexdef(c.oid), i.indisvalid, i.indisready "
                "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid WHERE c.relname = :name"
            ),
            {"name": queue.index("queue")},
        ).one()
    with pytest.raises(RuntimeError, match="queue index has a conflicting shape"):
        _apply(engine, queue)
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.text(
                    "SELECT c.oid, pg_get_indexdef(c.oid), i.indisvalid, i.indisready "
                    "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE c.relname = :name"
                ),
                {"name": queue.index("queue")},
            ).one()
            == before
        )


def _insert_receipt(engine, queue, owner, *, status="queued", marker=None):
    job_id = str(uuid4())
    company, actor, matter = owner
    columns = "id, company_id, status, queued_at, updated_at"
    values = ":id, :company, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
    parameters = {
        "id": job_id,
        "company": company,
        "status": status,
        "actor": actor,
        "matter": matter,
        "attachment": str(uuid4()),
    }
    if queue.table == "document_processing_jobs":
        columns += ", target_type, attachment_id, action, attempt_count, processed_char_count"
        values += ", 'matter_attachment', :attachment, 'initial_index', 0, 0"
    else:
        columns += (
            ", matter_id, requested_by_membership_id, source, source_reference, "
            "imported_cause_list_count, imported_order_count"
        )
        values += ", :matter, :actor, 'local-emulator', 'retained-source', 0, 0"
    if marker is not None:
        columns += ", no_paid_providers"
        values += ", :marker"
        parameters["marker"] = marker
    with engine.begin() as connection:
        connection.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
        connection.execute(
            sa.text(f"INSERT INTO {queue.table} ({columns}) VALUES ({values})"), parameters
        )
    return job_id


def _owners(engine):
    with Session(engine) as session:
        company = _seed_company(session)
        actor = _seed_membership(session, company)
        matter = _seed_matter(session, company)
        session.commit()
    return company, actor, matter


def _snapshot(engine, queue):
    with engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT * FROM {queue.table} ORDER BY id")).all()


def _index_state(engine, name):
    with engine.connect() as connection:
        return connection.execute(
            sa.text(
                "SELECT c.oid, i.indisvalid, i.indisready, pg_get_indexdef(c.oid) "
                "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = :name"
            ),
            {"name": name},
        ).one_or_none()


@pytest.mark.postgres
@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
@pytest.mark.parametrize("kind,phase", [("queue", "writers"), ("recovery", "snapshots")])
def test_real_cancelled_build_restarts_preserving_all_receipts(
    independent_database, queue, kind, phase, record_property
):
    engine = independent_database
    config = _config()
    command.upgrade(config, queue.previous)
    owner = _owners(engine)
    legacy = [
        _insert_receipt(engine, queue, owner, status=status) for status in ("queued", "processing")
    ]
    assert "no_paid_providers" not in {
        column["name"] for column in sa.inspect(engine).get_columns(queue.table)
    }
    held = []
    observed = {}
    name = queue.index(kind)

    def hold_before_build(connection, cursor, statement, parameters, context, executemany):
        if (
            connection.engine.url.database != engine.url.database
            or not statement.startswith(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ")
            or held
        ):
            return
        assert connection.connection.driver_connection.autocommit is True
        observed["lock_timeout"] = connection.exec_driver_sql("SHOW lock_timeout").scalar_one()
        observed["statement_timeout"] = connection.exec_driver_sql(
            "SHOW statement_timeout"
        ).scalar_one()
        observed["human"] = _insert_receipt(engine, queue, owner, marker=False)
        observed["marked"] = _insert_receipt(engine, queue, owner, marker=True)
        blocker = engine.connect().execution_options(isolation_level="REPEATABLE READ")
        held.append(blocker)
        if phase == "writers":
            blocker.execute(
                sa.text(f"UPDATE {queue.table} SET status = status WHERE id = :id"),
                {"id": legacy[0]},
            )
        else:
            blocker.execute(sa.text(f"SELECT * FROM {queue.table}")).all()

    event.listen(Engine, "before_cursor_execute", hold_before_build)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(command.upgrade, config, queue.migration)
            try:
                deadline = time.monotonic() + 30
                cancelled = False
                while time.monotonic() < deadline and not future.done():
                    state = _index_state(engine, name)
                    if (
                        state is not None
                        and state.indisvalid is False
                        and state.indisready == (phase == "snapshots")
                    ):
                        with engine.connect().execution_options(
                            isolation_level="AUTOCOMMIT"
                        ) as monitor:
                            pid = monitor.scalar(
                                sa.text(
                                    "SELECT pid FROM pg_stat_activity "
                                    "WHERE datname = :database AND state = 'active' "
                                    "AND query LIKE :query AND wait_event_type = 'Lock' "
                                    "AND wait_event = 'virtualxid'"
                                ),
                                {
                                    "database": engine.url.database,
                                    "query": f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} %",
                                },
                            )
                            if pid is not None:
                                # Read/write must still succeed during the actual index wait.
                                observed["concurrent_writer"] = _insert_receipt(
                                    engine,
                                    queue,
                                    owner,
                                    marker=True,
                                )
                                result = monitor.scalar(
                                    sa.text("SELECT pg_cancel_backend(:pid)"),
                                    {"pid": pid},
                                )
                                assert result is True
                                cancelled = True
                                break
                    time.sleep(0.02)
                assert cancelled, "No genuine concurrent-build wait/cancellation was observed"
                with pytest.raises(DBAPIError) as error:
                    future.result(timeout=10)
                assert error.value.orig.sqlstate == "57014"
            finally:
                # Failed assertions must not leave the executor waiting on its blocker.
                for blocker in held:
                    blocker.rollback()
                    blocker.close()
                held.clear()
    finally:
        event.remove(Engine, "before_cursor_execute", hold_before_build)
    failed = _index_state(engine, name)
    assert failed is not None and failed.indisvalid is False
    assert failed.indisready == (phase == "snapshots")
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == queue.previous
        )
        markers = dict(
            connection.execute(sa.text(f"SELECT id, no_paid_providers FROM {queue.table}")).all()
        )
    assert all(markers[job_id] is True for job_id in legacy)
    assert markers[observed["human"]] is False and markers[observed["marked"]] is True
    before = _snapshot(engine, queue)
    assert observed["lock_timeout"] == "5s"
    assert observed["statement_timeout"] == "15min"
    assert markers[observed["concurrent_writer"]] is True
    command.upgrade(config, queue.migration)
    assert _snapshot(engine, queue) == before
    healthy = [_index_state(engine, queue.index(kind)) for kind in ("queue", "recovery")]
    assert all(row is not None and row.indisvalid and row.indisready for row in healthy)
    assert _index_state(engine, name).oid != failed.oid
    command.upgrade(config, queue.migration)
    assert healthy == [_index_state(engine, queue.index(kind)) for kind in ("queue", "recovery")]
    assert _snapshot(engine, queue) == before
    record_property(
        "native_interruption",
        {
            "index": name,
            "phase": phase,
            "sqlstate": "57014",
            "invalid_state": tuple(failed),
            "budgets": observed,
        },
    )


@pytest.mark.postgres
@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
def test_actual_downgrade_refuses_before_any_receipt_or_index_loss(independent_database, queue):
    engine = independent_database
    config = _config()
    command.upgrade(config, queue.previous)
    owner = _owners(engine)
    _insert_receipt(engine, queue, owner)
    command.upgrade(config, queue.migration)
    _insert_receipt(engine, queue, owner, marker=False)
    before = _snapshot(engine, queue)
    indexes = [_index_state(engine, queue.index(kind)) for kind in ("queue", "recovery")]
    with pytest.raises(RuntimeError, match="restore-forward"):
        command.downgrade(config, queue.previous)
    assert _snapshot(engine, queue) == before
    assert indexes == [_index_state(engine, queue.index(kind)) for kind in ("queue", "recovery")]
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == queue.migration
        )


@pytest.mark.postgres
def test_full_head_refusal_rolls_back_earlier_guard_ddl(independent_database):
    engine = independent_database
    config = _config()
    command.upgrade(config, "20260928_0001")
    owner = _owners(engine)
    for queue in QUEUES:
        _insert_receipt(engine, queue, owner)
    command.upgrade(config, "head")
    for queue in QUEUES:
        _insert_receipt(engine, queue, owner, marker=False)
    receipts = [_snapshot(engine, queue) for queue in QUEUES]
    catalog_sql = sa.text(
        "SELECT t.tgname, pg_get_triggerdef(t.oid), p.proname, pg_get_functiondef(p.oid) "
        "FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
        "WHERE t.tgrelid = 'document_processing_jobs'::regclass AND NOT t.tgisinternal "
        "ORDER BY t.tgname"
    )
    with engine.connect() as connection:
        head = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
        catalog = connection.execute(catalog_sql).all()
        assert len(catalog) == 2
    with pytest.raises(RuntimeError, match="restore-forward"):
        command.downgrade(config, "20260928_0001")
    assert [_snapshot(engine, queue) for queue in QUEUES] == receipts
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == head
        assert connection.execute(catalog_sql).all() == catalog
    command.upgrade(config, "head")
    assert [_snapshot(engine, queue) for queue in QUEUES] == receipts


@pytest.mark.postgres
@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.migration)
def test_old_read_transaction_bounds_column_ddl_without_partial_expansion(
    independent_database, queue, monkeypatch, record_property
):
    engine = independent_database
    config = _config()
    command.upgrade(config, queue.previous)
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS", "1000")
    get_settings.cache_clear()
    with engine.connect() as reader:
        reader.execute(sa.text(f"SELECT * FROM {queue.table} LIMIT 1"))
        started = time.monotonic()
        with pytest.raises(DBAPIError) as error:
            command.upgrade(config, queue.migration)
        elapsed = time.monotonic() - started
        assert error.value.orig.sqlstate == "55P03"
        assert elapsed < 5
        assert reader.scalar(sa.text("SELECT 1")) == 1
        reader.rollback()
    assert "no_paid_providers" not in {
        column["name"] for column in sa.inspect(engine).get_columns(queue.table)
    }
    assert _index_state(engine, queue.index("queue")) is None
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == queue.previous
        )
    command.upgrade(config, queue.migration)
    record_property("old_read_ddl_refusal", {"sqlstate": "55P03", "elapsed_seconds": elapsed})
