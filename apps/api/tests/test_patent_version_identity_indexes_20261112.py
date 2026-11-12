"""IPLF-080B/UJ-29, NFT-005/J14-M14: structured version identity migration.

Source authoring is not execution proof. PostgreSQL rehearsals start independently
from template0 and migrate to the exact parent, never clone an application DB.
"""

from __future__ import annotations

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, event, insert, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationCreateRequest,
    PatentApplicationFacts,
    PatentIdentifierFact,
)
from caseops_api.services.ip_patent_application_corrections import correct_patent_application
from caseops_api.services.ip_patent_applications import create_patent_application
from tests.migration_index_catalog import require_index_additions, require_revision, schema_catalog
from tests.test_ip_patent_postgres import _seed, _seed_patent_scale_source
from tests.test_platform_console_migration import fresh_engine, migration_config
from tests.test_postgres_validation import _ip_race_context

PARENT = "20261108_0003"
HEAD = "20261112_0001"
PATH = Path(__file__).resolve().parents[1] / (
    "alembic/versions/20261112_0001_patent_version_identity_indexes.py"
)
SPECS = (
    ("ip_patent_family_versions", "ix_patent_family_versions_identity_key", "family_id"),
    (
        "ip_patent_application_versions", "ix_patent_application_versions_identity_key",
        "application_id",
    ),
)
OWNED = {(table, name) for table, name, _parent in SPECS}
DATA_TABLES = (
    "companies", "company_memberships", "clients", "ip_docket_records", "ip_assets",
    "ip_patent_families", "ip_patent_family_versions", "ip_patent_applications",
    "ip_patent_application_versions", "ip_patent_application_identifiers",
    "ip_patent_application_identities", "ip_documents", "ip_document_versions", "ip_document_links",
)


def _module():
    spec = importlib.util.spec_from_file_location("patent_identity_indexes_20261112", PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def _apply(engine, operation="upgrade"):
    with engine.connect() as connection:
        # Direct invocation owns only this migration, not an Alembic target chain.
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            getattr(_module(), operation)()


def _rows(engine):
    with engine.connect() as connection:
        quote = connection.dialect.identifier_preparer.quote
        if connection.dialect.name == "sqlite":
            return {table: [dict(row) for row in connection.execute(text(
                f"SELECT * FROM {quote(table)} ORDER BY id"
            )).mappings()] for table in DATA_TABLES}
        return {table: connection.scalars(text(
            f"SELECT to_jsonb(r)::text FROM {quote(table)} r ORDER BY id"
        )).all() for table in DATA_TABLES}


def _state(engine, spec):
    with engine.connect() as connection:
        row = _module()._postgres_state(connection, *spec)
        return dict(row) if row is not None else None


def _assert_ready(engine):
    states = [_state(engine, spec) for spec in SPECS]
    assert all(state is not None for state in states)
    assert all(
        all(state[key] for key in ("indisvalid", "indisready", "indislive")) for state in states
    )
    return [state["oid"] for state in states]


def _seed_owned_versions(engine):
    for number in range(2):
        company, actor, family = _seed(engine)
        family = _seed_patent_scale_source(engine, company, actor, family)
        with Session(engine) as session:
            context = _ip_race_context(session, company_id=company, membership_id=actor)
            application = create_patent_application(
                session, context=context, idempotency_key=str(uuid4()),
                payload=PatentApplicationCreateRequest(
                    family_id=family.id, expected_family_version=family.version,
                    expected_family_lifecycle_version=family.lifecycle_version,
                    facts=PatentApplicationFacts(
                        title=f"Migration application {number}", application_kind="complete",
                        jurisdiction="IN", office="IP India", source=family.facts.source,
                        identifiers=(PatentIdentifierFact(
                            identifier_kind="application", raw_value="migration-001",
                            source=family.facts.source,
                        ),),
                    ),
                ),
            )
            correct_patent_application(
                session, context=context, application_id=str(application.id),
                payload=PatentApplicationCorrectionRequest(
                    expected_version=application.version,
                    expected_lifecycle_version=application.lifecycle_version,
                    reason="Preserve populated immutable versions through the migration.",
                    facts=application.facts.model_copy(
                        update={"title": "Corrected migration facts"}
                    ),
                ),
            )
    with engine.connect() as connection:
        for table, _name, _parent in SPECS:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 4
            assert connection.scalar(text(f"SELECT count(DISTINCT company_id) FROM {table}")) == 2


@pytest.mark.parametrize("parent", ["family_id", "application_id"])
@pytest.mark.parametrize("form", ["bare", "column_parentheses", "cast_and_outer_parentheses"])
def test_identity_expression_matcher_accepts_only_reviewed_parentheses(parent, form):
    columns = ("company_id", parent, "version")
    if form == "bare":
        expression = "ARRAY[" + ", ".join(f"{column}::text" for column in columns) + "]"
    elif form == "column_parentheses":
        expression = "ARRAY[" + ", ".join(f"({column})::text" for column in columns) + "]"
    else:
        expression = "(ARRAY[" + ", ".join(f"(({column})::text)" for column in columns) + "])"
    assert _module()._expression_matches(expression, parent)


@pytest.mark.parametrize("expression", [
    "ARRAY[(family_id)::text, (company_id)::text, (version)::text]",
    "ARRAY[(company_id)::text, (application_id)::text, (version)::text]",
    "ARRAY[(company_id)::text, (family_id)::text]",
    "ARRAY[(company_id)::text, (family_id)::text, (version)::text, 'extra']",
    "ARRAY[((company_id || '')::text), (family_id)::text, (version)::text]",
    "ARRAY[(company_id)::text, (family_id)::text, (version + 0)::text]",
    "ARRAY[(company_id)::text, (family_id)::text, (version)::text] COLLATE \"C\"",
    "((ARRAY[(company_id)::text, (family_id)::text, (version)::text]))",
    "ARRAY[((company_id)::text, (family_id)::text, (version)::text]",
    "ARRAY[(company_id)::text), (family_id)::text, (version)::text]",
], ids=["order", "parent", "short", "long", "concat", "arithmetic", "collate",
        "extra_outer", "unclosed", "extra_close"])
def test_identity_expression_matcher_rejects_noncanonical_expressions(expression):
    assert not _module()._expression_matches(expression, "family_id")


def _valid_catalog_state():
    return dict(
        oid=1, relkind="i", owner=SPECS[0][0], owner_schema="public", schema="public",
        method="btree", indisvalid=True, indisready=True, indislive=True,
        indisunique=False, indisprimary=False, indisexclusion=False,
        indnkeyatts=1, indnatts=1, attribute=0, predicate=None,
        opcname="array_ops", opclass_schema="pg_catalog", opcdefault=True,
        array_input=True, matching_method=True, default_collation=True, options=0,
        expression="ARRAY[(company_id)::text, (family_id)::text, (version)::text]",
    )


def _catalog_bind(state):
    return SimpleNamespace(execute=lambda *_a, **_k: SimpleNamespace(
        mappings=lambda: SimpleNamespace(first=lambda: state)
    ))


@pytest.mark.parametrize("change", [
    {"relkind": "r"}, {"owner": "foreign_table"}, {"owner_schema": "foreign_schema"},
    {"method": "hash"}, {"indisunique": True}, {"indisprimary": True},
    {"indisexclusion": True}, {"indnkeyatts": 2}, {"indnatts": 2}, {"attribute": 1},
    {"predicate": "version > 0"}, {"opcname": "foreign_ops"},
    {"opclass_schema": "public"}, {"opcdefault": False}, {"array_input": False},
    {"matching_method": False}, {"default_collation": False}, {"options": 1},
], ids=["relation", "owner", "schema", "method", "unique", "primary", "exclusion",
        "keys", "include", "column", "where", "opclass", "opclass_schema", "default_ops",
        "input_type", "opclass_method", "collation", "sort_options"])
def test_identity_catalog_guard_rejects_conflicting_metadata(change):
    with pytest.raises(RuntimeError, match="conflicting shape"):
        _module()._postgres_state(_catalog_bind(_valid_catalog_state() | change), *SPECS[0])


@pytest.mark.parametrize("flag", ["indisvalid", "indisready", "indislive"])
def test_identity_catalog_guard_admits_same_shape_interrupted_state_for_recovery(flag):
    migration = _module()
    state = _valid_catalog_state() | {flag: False}
    assert migration._postgres_state(_catalog_bind(state), *SPECS[0]) == state
    assert not migration._ready(state)


def test_identity_migration_sqlite_both_directions_are_true_noops():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE retained (id INTEGER PRIMARY KEY, value TEXT)")
            connection.exec_driver_sql("INSERT INTO retained VALUES (1, 'unchanged')")
            for _table, name, _parent in SPECS:
                connection.exec_driver_sql(f"CREATE INDEX {name} ON retained(value)")
        before = schema_catalog(engine)
        for operation in ("upgrade", "upgrade", "downgrade", "downgrade"):
            _apply(engine, operation)
            assert schema_catalog(engine) == before
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM retained").all() == [(1, "unchanged")]
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["upgrade", "downgrade"])
def test_identity_migration_refuses_other_dialects(operation, monkeypatch):
    migration = _module()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: SimpleNamespace(
        dialect=SimpleNamespace(name="mysql")
    )))
    with pytest.raises(RuntimeError, match="Unsupported"):
        getattr(migration, operation)()


@pytest.mark.postgres
def test_identity_indexes_populated_upgrade_reapply_downgrade_reupgrade(
    tmp_path, monkeypatch,
):
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        require_revision(engine, PARENT)
        _seed_owned_versions(engine)
        parent, rows = schema_catalog(engine), _rows(engine)
        statements = []

        def capture(connection, _cursor, statement, _parameters, _context, _many):
            normalized = statement.lstrip()
            if (connection.engine.url.database == engine.url.database
                and normalized.startswith(("CREATE INDEX", "DROP INDEX"))
                and any(name in statement for _table, name in OWNED)):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", capture)
        try:
            command.upgrade(config, HEAD)
            original_oids = _assert_ready(engine)
            head = schema_catalog(engine)
            require_index_additions(parent, head, SPECS)
            require_revision(engine, HEAD)
            assert _rows(engine) == rows
            _apply(engine)
            assert _assert_ready(engine) == original_oids
            assert schema_catalog(engine) == head and _rows(engine) == rows
            for destination in (PARENT, "-1"):
                command.downgrade(config, destination)
                require_revision(engine, PARENT)
                assert schema_catalog(engine) == parent and _rows(engine) == rows
                command.upgrade(config, HEAD)
                _assert_ready(engine)
                require_revision(engine, HEAD)
                assert schema_catalog(engine) == head and _rows(engine) == rows
        finally:
            event.remove(Engine, "before_cursor_execute", capture)
        assert len(statements) == 10
        assert all(
            statement.lstrip().startswith(("CREATE INDEX CONCURRENTLY", "DROP INDEX CONCURRENTLY"))
            for statement in statements
        )


@pytest.mark.parametrize("kind", ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
@pytest.mark.parametrize("destination", ["20261108_0002", "base", "-2"])
def test_identity_chained_restore_forward_refusal_precedes_any_catalog_change(
    kind, destination, tmp_path, monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        _seed_owned_versions(engine)
        rows, catalog = _rows(engine), schema_catalog(engine)
        statements = []

        def capture(connection, _cursor, statement, _parameters, _context, _many):
            if connection.engine.url.database == engine.url.database:
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(RuntimeError) as refused:
                command.downgrade(config, destination)
        finally:
            event.remove(Engine, "before_cursor_execute", capture)
        assert str(refused.value) == (
            "Restore-forward required: removing native attachment provenance could "
            "reenable third-party processing without consent."
        )
        trace = refused.value.__traceback__
        while trace.tb_next is not None:
            trace = trace.tb_next
        assert Path(trace.tb_frame.f_code.co_filename).resolve() == PATH
        assert trace.tb_frame.f_code.co_name == "downgrade"
        assert not any(statement.lstrip().upper().startswith(("CREATE ", "DROP ", "ALTER "))
                       for statement in statements)
        assert _rows(engine) == rows and schema_catalog(engine) == catalog
        require_revision(engine, HEAD)


@pytest.mark.postgres
@pytest.mark.parametrize("operation", ["upgrade", "downgrade"])
@pytest.mark.parametrize("wrong", ["owner", "order", "include", "partial", "descending"])
def test_identity_conflicting_second_name_refuses_before_any_ddl(
    operation, wrong, tmp_path, monkeypatch,
):
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        _seed_owned_versions(engine)
        table, name, parent = SPECS[1]
        if operation == "downgrade":
            command.upgrade(config, HEAD)
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql(f"DROP INDEX CONCURRENTLY {name}")
        expression = f"ARRAY[company_id::text, {parent}::text, version::text]"
        if wrong == "owner":
            table = SPECS[0][0]
            expression = "ARRAY[company_id::text, family_id::text, version::text]"
        elif wrong == "order":
            expression = f"ARRAY[{parent}::text, company_id::text, version::text]"
        suffix = {
            "include": " INCLUDE (company_id)", "partial": " WHERE version > 0"
        }.get(wrong, "")
        ordering = " DESC" if wrong == "descending" else ""
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE INDEX {name} ON {table} (({expression}){ordering}){suffix}"
            )
        catalog, rows = schema_catalog(engine), _rows(engine)
        with engine.connect() as connection:
            original_oid = connection.scalar(text("SELECT to_regclass(:name)::oid"), {"name": name})
        with pytest.raises(RuntimeError, match="conflicting shape"):
            _apply(engine, operation)
        assert schema_catalog(engine) == catalog and _rows(engine) == rows
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass(:name)::oid"), {"name": name}
            ) == original_oid
        require_revision(engine, HEAD if operation == "downgrade" else PARENT)


@pytest.mark.postgres
@pytest.mark.parametrize("spec", SPECS, ids=["family", "application"])
@pytest.mark.parametrize("phase", ["writers", "snapshots"])
def test_identity_cancelled_concurrent_build_recovers_with_retained_versions(
    spec, phase, tmp_path, monkeypatch, record_property,
):
    with fresh_engine("postgres", tmp_path) as engine:
        monkeypatch.setenv("CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS", "5000")
        monkeypatch.setenv("CASEOPS_MIGRATION_DB_STATEMENT_TIMEOUT_MS", "900000")
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        _seed_owned_versions(engine)
        catalog, rows = schema_catalog(engine), _rows(engine)
        table_name, name, _parent = spec
        version_table = Table(table_name, MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            fields = dict(connection.execute(
                select(version_table).order_by(version_table.c.version.desc()).limit(1)
            ).mappings().one())
        fields.update(id=str(uuid4()), version=3, reason="Acknowledged interrupted-index writer.")
        held, observed, acknowledged = [], {}, Event()
        prefix = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "

        def before_build(connection, _cursor, statement, _parameters, _context, _many):
            if connection.engine.url.database != engine.url.database or not statement.startswith(
                prefix
            ) or acknowledged.is_set():
                return
            observed["pid"] = connection.scalar(text("SELECT pg_backend_pid()"))
            observed["sql"] = statement
            for setting in ("lock_timeout", "statement_timeout"):
                observed[setting] = connection.exec_driver_sql("SHOW " + setting).scalar_one()
            blocker = engine.connect().execution_options(isolation_level="REPEATABLE READ")
            held.append(blocker)
            if phase == "writers":
                inserted = blocker.scalar(
                    insert(version_table).values(**fields).returning(version_table.c.id)
                )
                assert inserted == fields["id"]
                observed["acknowledgement"] = "valid immutable version insert returned its id"
            else:
                count = blocker.scalar(select(version_table.c.id).limit(1))
                assert count is not None
                observed["acknowledgement"] = "repeatable-read snapshot returned a version id"
            acknowledged.set()

        expected_phase = {
            "writers": "waiting for writers before build", "snapshots": "waiting for old snapshots"
        }[phase]
        event.listen(Engine, "before_cursor_execute", before_build)
        pool = ThreadPoolExecutor(max_workers=1)
        future = None
        try:
            future = pool.submit(command.upgrade, config, HEAD)
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as monitor:
                deadline, cancelled = time.monotonic() + 30, False
                while time.monotonic() < deadline:
                    if future.done():
                        future.result(timeout=0)
                        pytest.fail("Concurrent build completed without the required observed wait")
                    if acknowledged.is_set():
                        progress = monitor.execute(text(
                            "SELECT p.pid, p.phase, i.indisvalid, i.indisready, i.indislive "
                            "FROM pg_stat_progress_create_index p "
                            "JOIN pg_index i ON i.indexrelid=p.index_relid "
                            "WHERE p.pid=:pid AND p.datname=current_database() "
                            "AND i.indexrelid=to_regclass(:name)"
                        ), {"pid": observed["pid"], "name": name}).mappings().first()
                        if progress is not None and progress["phase"] == expected_phase:
                            assert not progress["indisvalid"] and progress["indislive"]
                            assert progress["indisready"] == (phase == "snapshots")
                            record_property("interrupted_identity_index", dict(progress) | observed)
                            cancelled = monitor.scalar(
                                text("SELECT pg_cancel_backend(:pid)"), {"pid": observed["pid"]}
                            )
                            break
                    time.sleep(0.01)
                assert cancelled, "The acknowledged writer/snapshot build phase was not observed"
                with pytest.raises(DBAPIError) as error:
                    future.result(timeout=10)
                assert error.value.orig.sqlstate == "57014"
        finally:
            try:
                try:
                    for blocker in held:
                        try:
                            blocker.rollback()
                        finally:
                            blocker.close()
                finally:
                    if future is not None and not future.done() and "pid" in observed:
                        with engine.connect().execution_options(
                            isolation_level="AUTOCOMMIT"
                        ) as monitor:
                            monitor.scalar(
                                text("SELECT pg_cancel_backend(:pid)"), {"pid": observed["pid"]}
                            )
            finally:
                try:
                    pool.shutdown(wait=True, cancel_futures=True)
                finally:
                    event.remove(Engine, "before_cursor_execute", before_build)
        assert future.done() and all(blocker.closed for blocker in held)
        record_property("identity_index_worker_joined", True)
        failed = _state(engine, spec)
        assert failed is not None and not failed["indisvalid"] and failed["indislive"]
        assert failed["indisready"] == (phase == "snapshots")
        record_property("failed_identity_index_catalog", failed)
        require_revision(engine, PARENT)
        assert observed["lock_timeout"] == "5s" and observed["statement_timeout"] == "15min"
        assert _rows(engine) == rows
        command.upgrade(config, HEAD)
        _assert_ready(engine)
        assert _state(engine, spec)["oid"] != failed["oid"]
        require_index_additions(catalog, schema_catalog(engine), SPECS)
        require_revision(engine, HEAD)
        assert _rows(engine) == rows
