"""Real source-writer composition controls; DB execution separately authorized."""

from contextlib import ExitStack
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql

from caseops_api.db.models import MembershipRole
from caseops_api.db.session import _proven_read_statement
from caseops_api.db.task_queue_page_models import (
    MatterTaskQueueDirty,
    MatterTaskQueueGroup,
    MatterTaskQueuePage,
)
from caseops_api.db.task_queue_page_schema_v1 import (
    backfill,
    install,
    postgres_statements,
    sqlite_statements,
)
from caseops_api.services import matter_work_queue as queue
from caseops_api.services.task_queue_pages import statement
from tests.sql_observation import is_read_only_select


@pytest.fixture
def raw_source():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        # The trigger's complete source input shape, including nullable retained
        # tenant scope. Deliberately no ORM event can maintain this fixture.
        connection.exec_driver_sql("""CREATE TABLE matter_tasks (
         id TEXT PRIMARY KEY,company_id TEXT,matter_id TEXT,owner_membership_id TEXT,
         title TEXT NOT NULL,status TEXT NOT NULL,priority TEXT NOT NULL,due_on DATE,
         created_at TIMESTAMP NOT NULL,updated_at TIMESTAMP NOT NULL,ip_docket_id TEXT,
         cancelled_by_matter_disposal BOOLEAN NOT NULL DEFAULT false,neutralized_at TIMESTAMP,
         neutralized_by_ip_lifecycle_event_id TEXT,neutralized_by_ip_lifecycle_version INTEGER)""")
        MatterTaskQueueGroup.__table__.create(connection)
        MatterTaskQueuePage.__table__.create(connection)
        MatterTaskQueueDirty.__table__.create(connection)
        install(connection)
    try:
        yield engine
    finally:
        engine.dispose()


def put(connection, identity, **updates):
    row = dict(
        id=identity,
        company_id="company",
        matter_id="matter",
        owner_membership_id=None,
        title="Retained 😀 task",
        status="todo",
        priority="medium",
        due_on="2028-02-29",
        created_at="2026-10-27 01:02:03.123456",
        updated_at="2026-10-27 01:02:03.654321",
    )
    row.update(updates)
    connection.exec_driver_sql(
        f"INSERT INTO matter_tasks ({','.join(row)}) VALUES ({','.join(':' + k for k in row)})", row
    )


def source_rows(connection):
    return connection.exec_driver_sql("SELECT * FROM matter_tasks ORDER BY id").all()


def unpack(connection):
    result = []
    groups = {
        r["id"]: r for r in connection.execute(select(MatterTaskQueueGroup.__table__)).mappings()
    }
    for page in connection.execute(select(MatterTaskQueuePage.__table__)).mappings():
        group = groups[page["group_id"]]
        for slot in range(page["entry_count"]):
            result.append(
                dict(
                    company_id=group["company_id"],
                    matter_id=group["matter_id"],
                    owner=None if group["owner_is_null"] else group["owner_key"],
                    **{
                        k: page[f"s{slot}_{k}"]
                        for k in (
                            "id",
                            "title",
                            "status",
                            "priority",
                            "due_on",
                            "created_at",
                            "updated_at",
                        )
                    },
                )
            )
    return sorted(result, key=lambda r: r["id"])


def test_all_three_raw_writer_bridges_and_deferred_pg_collection_have_closed_input_scope():
    postgres = [sql.replace("public.", "") for sql in postgres_statements()]
    for operation in ("insert", "update", "delete"):
        trigger = next(
            x for x in postgres if x.startswith(f"CREATE TRIGGER trg_task_queue_{operation} ")
        )
        assert "FOR EACH STATEMENT" in trigger and "REFERENCING" in trigger
        body = next(x for x in postgres if f"FUNCTION caseops_task_queue_{operation}()" in x)
        assert "INSERT INTO matter_task_queue_dirty" in body
        assert "pg_advisory" not in body and "FOR UPDATE" not in body
    finalize = next(x for x in postgres if "FUNCTION caseops_finalize_task_queue()" in x)
    assert finalize.count('ORDER BY company_id COLLATE "C"') == 1
    assert "SELECT DISTINCT hashtext" in finalize and "ORDER BY lock_key" in finalize
    assert finalize.index("pg_advisory_xact_lock(1145393713, 0)") < finalize.index(
        "ORDER BY lock_key"
    )
    assert "LANGUAGE plpgsql VOLATILE" in finalize
    assert "DEFERRABLE INITIALLY DEFERRED" in "\n".join(postgres)
    assert len(sqlite_statements()) == 3
    assert all("LEFT(" not in sql.upper() and "SUBSTR(" not in sql.upper() for sql in postgres)


@pytest.mark.parametrize("ownership", ["mine", "team", "unassigned"])
def test_actual_typed_packed_query_has_no_task_from_and_policy_before_group_bounds(ownership):
    context = SimpleNamespace(
        company=SimpleNamespace(id="company"),
        membership=SimpleNamespace(id="member", role=MembershipRole.MEMBER),
        user=SimpleNamespace(id="user"),
    )
    query = statement(
        None,
        context=context,
        ownership=ownership,
        dates="dated",
        lower=date(2028, 2, 1),
        upper=date(2028, 3, 1),
        anchor={
            "id": "old-task",
            "due_on": date(2028, 2, 2),
            "created_at": datetime(2026, 10, 27, tzinfo=UTC),
        },
    )
    assert is_read_only_select(query)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "FROM matter_tasks" not in sql and "JOIN matter_tasks" not in sql
    assert "MATERIALIZED" in sql and "LATERAL" in sql and "VALUES (" in sql
    assert "statement_timestamp()" in sql
    assert "OFFSET" not in sql and "jsonb_array_elements" not in sql
    assert query._limit_clause.value == 26 and len(query._order_by_clauses) == 4
    wrapped = statement(
        None,
        context=context,
        ownership=ownership,
        dates="dated",
        lower=date(2028, 2, 1),
        upper=date(2028, 3, 1),
        anchor={
            "id": "old-task",
            "due_on": date(2028, 2, 2),
            "created_at": datetime(2026, 10, 27, tzinfo=UTC),
        },
        outer_bound=False,
    )
    assert wrapped._limit_clause is None and not wrapped._order_by_clauses
    compiled = str(
        wrapped.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert is_read_only_select(wrapped)
    assert "FROM matter_tasks" not in compiled and "JOIN matter_tasks" not in compiled
    assert "LIMIT 2" in compiled and "LIMIT 26" in compiled
    assert "MATERIALIZED" in compiled and "LATERAL" in compiled
    with pytest.raises(ValueError, match="global page bound must be explicit"):
        statement(None, context=context, ownership=ownership, dates="all", outer_bound=None)


def test_model_derived_tables_introduce_no_parent_foreign_key_row_locks():
    for model in (MatterTaskQueueGroup, MatterTaskQueuePage, MatterTaskQueueDirty):
        assert list(model.__table__.foreign_keys) == []
    assert len(MatterTaskQueuePage.__table__.columns) == 186


def test_raw_insert_dense_pages_exact_unicode_and_nullable_legacy_rows(raw_source):
    with raw_source.begin() as connection:
        for n in range(26):
            put(connection, f"task-{n:02}", title="😀" * 1024 if n == 0 else "Kept sibling")
        put(connection, "legacy-null-company", company_id=None)
        rows = unpack(connection)
        assert len(rows) == 26 and rows[0]["title"] == "😀" * 1024
        pages = list(connection.execute(select(MatterTaskQueuePage.entry_count)).scalars())
        assert sorted(pages) == [1, 25]
        assert len(source_rows(connection)) == 27


def test_raw_owner_date_status_cancel_and_reparent_updates_refresh_both_scopes(raw_source):
    with raw_source.begin() as connection:
        put(connection, "changed")
        for updates, expected in [
            ("owner_membership_id='peer',due_on=NULL", {"owner": "peer", "due_on": None}),
            (
                "company_id='other',matter_id='second'",
                {"company_id": "other", "matter_id": "second"},
            ),
        ]:
            connection.exec_driver_sql(f"UPDATE matter_tasks SET {updates} WHERE id='changed'")
            row = unpack(connection)
            assert len(row) == 1 and all(row[0][k] == v for k, v in expected.items())
            assert len(connection.execute(select(MatterTaskQueueGroup.id)).all()) == 1
        connection.exec_driver_sql("UPDATE matter_tasks SET status='completed' WHERE id='changed'")
        assert unpack(connection) == []
        connection.exec_driver_sql("UPDATE matter_tasks SET status='todo' WHERE id='changed'")
        assert len(unpack(connection)) == 1
        connection.exec_driver_sql(
            "UPDATE matter_tasks SET cancelled_by_matter_disposal=true WHERE id='changed'"
        )
        assert unpack(connection) == []
        assert source_rows(connection)[0].status == "todo"


def test_rollback_of_source_and_derived_changes_is_atomic_and_delete_does_not_resurrect(raw_source):
    with raw_source.begin() as connection:
        put(connection, "retained")
    with raw_source.connect() as connection:
        before = source_rows(connection)
        connection.rollback()
        transaction = connection.begin()
        connection.exec_driver_sql("DELETE FROM matter_tasks WHERE id='retained'")
        assert unpack(connection) == []
        transaction.rollback()
        assert source_rows(connection) == before
        assert [r["id"] for r in unpack(connection)] == ["retained"]
        connection.rollback()
        with connection.begin():
            connection.exec_driver_sql("DELETE FROM matter_tasks WHERE id='retained'")
        assert unpack(connection) == []


def test_backfill_never_updates_source_and_retains_complete_earlier_rows(raw_source):
    with raw_source.begin() as connection:
        put(connection, "retained", due_on=None)
        before = source_rows(connection)
        connection.exec_driver_sql("DELETE FROM matter_task_queue_pages")
        connection.exec_driver_sql("DELETE FROM matter_task_queue_groups")
        # A source UPDATE, including id=id, would fail this real trigger.
        connection.exec_driver_sql(
            "CREATE TRIGGER forbid_source_backfill_update BEFORE UPDATE ON matter_tasks "
            "BEGIN SELECT RAISE(ABORT, 'source update forbidden'); END"
        )
        backfill(connection)
        assert source_rows(connection) == before
        assert [row["id"] for row in unpack(connection)] == ["retained"]


def test_retained_statement_chooses_own_write_source_at_execution_without_construction_io():
    context = SimpleNamespace(
        company=SimpleNamespace(id="company"),
        membership=SimpleNamespace(id="member", role=MembershipRole.MEMBER),
        user=SimpleNamespace(id="user"),
    )
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    query = queue.work_queue_statement(
        session, context=context, ownership="unassigned", dates="all"
    )
    assert is_read_only_select(query)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "UNION ALL" in sql
    # Strict function allowlist compatibility is separate from structural SELECT.
    assert _proven_read_statement(query)
    assert sql.count("txid_current_if_assigned()") == 2
    from sqlalchemy.sql.selectable import CompoundSelect

    assert isinstance(query, CompoundSelect)
    assert "queue_own_write_page" in sql
    assert "queue_committed_page" not in sql and "queue_current_transaction_page" not in sql
    assert sql.count("queue_authorized_actor AS MATERIALIZED") == 1
    assert "ORDER BY due_on ASC NULLS LAST, created_at ASC, id ASC" in sql
    team_query = queue.work_queue_statement(session, context=context, ownership="team", dates="all")
    team_sql = str(
        team_query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert is_read_only_select(team_query) and _proven_read_statement(team_query)
    # Actor fact, ONE active-owner-team set, and complete eligible groups.
    # Both transaction branches refer to the same statement-local facts.
    assert team_sql.count("AS MATERIALIZED") == 3
    assert [column.name for column in query.selected_columns] == [
        "id",
        "title",
        "status",
        "priority",
        "due_on",
        "created_at",
        "updated_at",
        "owner_membership_id",
        "matter_id",
        "matter_title",
        "matter_code",
        "matter_status",
        "is_active",
        "lifecycle_version",
    ]


def test_plan_observer_charges_all_work_and_refuses_missing_counts():
    from copy import deepcopy

    from tests.test_matter_work_queue_20261027_postgres import _all_relation_work

    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 26,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "CTE Scan",
                        "Actual Rows": 2,
                        "Actual Loops": 3,
                        "Rows Removed by Filter": 4,
                        "Plans": [
                            {
                                "Node Type": "Bitmap Index Scan",
                                "Actual Rows": 1,
                                "Actual Loops": 2,
                                "Rows Removed by Index Recheck": 5,
                            }
                        ],
                    },
                ],
            }
        }
    ]
    assert _all_relation_work(plan) == 26 + (2 + 4) * 3 + (1 + 5) * 2
    for field, value in [
        ("Actual Rows", None),
        ("Actual Loops", -1),
        ("Rows Removed by Filter", float("nan")),
    ]:
        changed = deepcopy(plan)
        if value is None:
            changed[0]["Plan"].pop(field)
        else:
            changed[0]["Plan"][field] = value
        with pytest.raises((KeyError, AssertionError)):
            _all_relation_work(changed)


def migration_module():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1] / "alembic/versions/"
        "20261027_0006_matter_task_queue_pages.py"
    )
    spec = importlib.util.spec_from_file_location("closed_task_queue_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_helper_has_exact_lf_pin_and_no_import_side_effects():
    import hashlib
    from pathlib import Path

    from caseops_api.db.base import Base

    migration = migration_module()
    listeners = len(Base.metadata.dispatch.after_create)
    schema = migration._load_schema_v1()
    assert len(Base.metadata.dispatch.after_create) == listeners
    source = migration._schema_path().read_bytes()
    assert b"\r" not in source
    assert hashlib.sha256(source).hexdigest() == migration.SCHEMA_HELPER_SHA256
    assert schema["SLOTS"] == 25
    revokes = [sql for sql in schema["postgres_statements"]() if sql.startswith("REVOKE ")]
    assert len(revokes) == 6 and len(set(revokes)) == 6
    assert all(sql.endswith(" FROM PUBLIC") for sql in revokes)
    attributes = Path(__file__).resolve().parents[3] / ".gitattributes"
    assert (
        "apps/api/src/caseops_api/db/task_queue_page_schema_v1.py text eol=lf"
        in attributes.read_text().splitlines()
    )


def test_corrupt_helper_refuses_before_database_binding_and_closes_actual_descriptor(
    tmp_path, monkeypatch
):
    import os
    from types import SimpleNamespace

    migration = migration_module()
    source = migration._schema_path().read_bytes()
    path = tmp_path / "closed.py"
    path.write_bytes(source + b"\nPRIVATE_INVALID_SOURCE_NOT_FOR_ERROR_MESSAGES\n")
    monkeypatch.setattr(migration, "_schema_path", lambda: path)
    fds, bindings = [], []

    def opened(*args):
        fd = os.open(*args)
        fds.append(fd)
        return fd

    io = SimpleNamespace(
        open=opened,
        read=os.read,
        fstat=os.fstat,
        close=os.close,
        O_RDONLY=os.O_RDONLY,
        O_NOFOLLOW=getattr(os, "O_NOFOLLOW", 0),
        O_NONBLOCK=getattr(os, "O_NONBLOCK", 0),
        name=os.name,
    )
    monkeypatch.setattr(migration, "os", io)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bindings.append(True))
    with pytest.raises(RuntimeError, match="^TASK_QUEUE_SCHEMA_DEPENDENCY_INVALID$"):
        migration.upgrade()
    assert not bindings and len(fds) == 1
    with pytest.raises(OSError):
        os.fstat(fds[0])


def test_helper_growth_after_fstat_is_bounded_and_descriptor_closes(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    migration = migration_module()
    path = tmp_path / "closed.py"
    path.write_bytes(migration._schema_path().read_bytes())
    monkeypatch.setattr(migration, "_schema_path", lambda: path)
    fds, counts = [], []

    def opened(*args):
        fd = os.open(*args)
        fds.append(fd)
        return fd

    def read(fd, count):
        if not counts:
            with path.open("ab") as appended:
                appended.write(b"x" * 200000)
        value = os.read(fd, count)
        counts.append(len(value))
        return value

    io = SimpleNamespace(open=opened, read=read, fstat=os.fstat, close=os.close)
    with pytest.raises(RuntimeError, match="^TASK_QUEUE_SCHEMA_DEPENDENCY_INVALID$"):
        migration._load_schema_v1(io)
    assert sum(counts) == 131073
    with pytest.raises(OSError):
        os.fstat(fds[0])


def test_windows_named_device_portability_does_not_relax_descriptor_identity(tmp_path, monkeypatch):
    import os
    import stat
    from types import SimpleNamespace

    migration = migration_module()
    named = dict(
        st_dev=0,
        st_ino=1,
        st_size=2,
        st_mtime_ns=3,
        st_ctime_ns=4,
        st_mode=stat.S_IFREG | 0o444,
        st_uid=0,
        st_gid=0,
        st_nlink=1,
    )
    opened = {**named, "st_dev": 99}
    assert migration._same_named_descriptor(
        SimpleNamespace(**named), SimpleNamespace(**opened), windows=True
    )
    assert not migration._same_named_descriptor(SimpleNamespace(**named), SimpleNamespace(**opened))
    assert not migration._same_named_descriptor(
        SimpleNamespace(**named), SimpleNamespace(**{**opened, "st_ino": 9}), windows=True
    )
    path = tmp_path / "closed.py"
    path.write_bytes(migration._schema_path().read_bytes())
    monkeypatch.setattr(migration, "_schema_path", lambda: path)
    fds, stats = [], []

    def opened_fd(*args):
        fd = os.open(*args)
        fds.append(fd)
        return fd

    def changed_fd_device(fd):
        real = os.fstat(fd)
        values = {key: getattr(real, key) for key in migration._SCHEMA_METADATA}
        values["st_dev"] = 99 + len(stats)
        stats.append(values)
        return SimpleNamespace(**values)

    io = SimpleNamespace(
        open=opened_fd,
        read=os.read,
        fstat=changed_fd_device,
        close=os.close,
        O_RDONLY=os.O_RDONLY,
        name="nt",
    )
    monkeypatch.setattr(migration, "os", io)  # Module-local double, not os.name/pathlib mutation.
    with pytest.raises(RuntimeError, match="^TASK_QUEUE_SCHEMA_DEPENDENCY_INVALID$"):
        migration._load_schema_v1()
    with pytest.raises(OSError):
        os.fstat(fds[0])


def test_frozen_ddl_modulo_reaches_psycopg_without_parameter_adaptation():
    """Real SQLAlchemy dispatch + installed psycopg conversion, without PG I/O."""
    from psycopg import ProgrammingError
    from psycopg._queries import PostgresQuery
    from psycopg.adapt import Transformer
    from sqlalchemy import event

    engine = create_engine("sqlite://")
    accepted = []
    parameterized = []

    def original_parameter_dispatch(cursor, sql, parameters, context):
        parameterized.append(sql)
        # SQLAlchemy's original default dispatch sends an empty tuple. The
        # installed PG adapter mistakes the actual SQL modulo for a placeholder.
        converted = PostgresQuery(Transformer())
        converted.convert(sql, parameters)
        return True

    def literal_dispatch(cursor, sql, context):
        assert context.no_parameters is True
        converted = PostgresQuery(Transformer())
        converted.convert(sql, None)
        assert converted.query == sql.encode("utf-8")
        accepted.append(sql)
        return True  # No DDL executes on the offline SQLite transport.

    event.listen(engine.dialect, "do_execute", original_parameter_dispatch)
    event.listen(engine.dialect, "do_execute_no_params", literal_dispatch)
    statements = postgres_statements()
    assert "ordinal % 25" in statements[0]
    try:
        with engine.connect() as connection:
            with pytest.raises(ProgrammingError, match="incomplete placeholder"):
                connection.exec_driver_sql(statements[0])
            adapter = SimpleNamespace(
                dialect=SimpleNamespace(name="postgresql"),
                exec_driver_sql=connection.exec_driver_sql,
            )
            install(adapter)
        assert parameterized == statements[:1]
        assert accepted == statements
    finally:
        engine.dispose()


@pytest.fixture
def database_journal(tmp_path, monkeypatch):
    import os

    from tests import fixtures_postgres_client as fixtures

    target = tmp_path / "database-ownership.jsonl"
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    monkeypatch.setenv("CASEOPS_TEST_DATABASE_OWNERSHIP_JOURNAL", str(target))
    monkeypatch.setenv(
        "CASEOPS_TEST_DATABASE_OWNERSHIP_RUN_ID", "3492ed1a-64b0-4a98-994b-28e4a7f81da4"
    )
    connection = SimpleNamespace(
        connection=SimpleNamespace(
            driver_connection=SimpleNamespace(info=SimpleNamespace(backend_pid=12345))
        )
    )
    return fixtures, target, connection


def journal_rows(path):
    import json

    return [json.loads(line) for line in path.read_text().splitlines()]


def fake_database_admin(fixtures, target, connection, monkeypatch, *, unknown_create=False):
    from contextlib import contextmanager

    effects = []

    def execute(sql):
        rows = journal_rows(target)
        if sql.startswith("CREATE DATABASE "):
            assert [row["event"] for row in rows] == ["create_intent"]
            effects.append("create_dispatched")
            if unknown_create:
                raise OSError("synthetic lost create acknowledgement")
        elif sql.startswith("DROP DATABASE "):
            effects.append("drop_ack")
        else:
            raise AssertionError("Unexpected database command")

    connection.exec_driver_sql = execute

    @contextmanager
    def connect():
        yield connection

    admin = SimpleNamespace(
        connect=connect,
        dialect=postgresql.dialect(),
        dispose=lambda: effects.append("admin_disposed"),
    )
    probe = SimpleNamespace(url=None, dispose=lambda: effects.append("probe_disposed"))

    def factory(url, **kwargs):
        if kwargs.get("isolation_level") == "AUTOCOMMIT":
            return admin
        probe.url = url
        return probe

    monkeypatch.setattr(fixtures, "create_engine", factory)
    return effects, probe


def test_canonical_database_journal_records_intent_then_real_ack_before_yield(
    database_journal, monkeypatch
):
    import hashlib
    import os
    from pathlib import Path

    from sqlalchemy.engine import make_url

    fixtures, target, connection = database_journal
    effects, probe = fake_database_admin(fixtures, target, connection, monkeypatch)
    source = make_url("postgresql+psycopg://journal-fixture@localhost/caseops")
    with fixtures.temporary_http_database(source) as engine:
        assert engine is probe
        rows = journal_rows(target)
        assert [row["event"] for row in rows] == ["create_intent", "create_ack"]
        assert all(row["pid"] == os.getpid() and row["backendPid"] == 12345 for row in rows)
        assert all(row["databaseName"] == engine.url.database for row in rows)
        assert all(row["sourceDatabase"] == "caseops" for row in rows)
        expected = hashlib.sha256(Path(fixtures.__file__).read_bytes()).hexdigest()
        assert all(row["fixtureSourceSha256"] == expected for row in rows)
        assert rows[0]["canonicalCreateSqlSha256"] == rows[1]["canonicalCreateSqlSha256"]
        assert (
            "journal-fixture" not in target.read_text() and "postgresql" not in target.read_text()
        )
    assert effects == ["create_dispatched", "probe_disposed", "drop_ack", "admin_disposed"]


def test_database_journal_disabled_preserves_original_zero_journal_io(monkeypatch):
    from tests import fixtures_postgres_client as fixtures

    monkeypatch.delenv("CASEOPS_TEST_DATABASE_OWNERSHIP_JOURNAL", raising=False)
    monkeypatch.setattr(fixtures, "os", SimpleNamespace(environ={}))
    fixtures._database_ownership_journal("invalid", None, None, None, None)


@pytest.mark.parametrize("invalid", ["hardlink", "oversize"])
def test_database_journal_invalid_file_refuses_before_create(
    database_journal, monkeypatch, invalid
):
    import os

    from sqlalchemy.engine import make_url

    fixtures, target, connection = database_journal
    if invalid == "hardlink":
        os.link(target, target.with_suffix(".link"))
    else:
        target.write_bytes(b"x" * (1024**2))
    effects, _ = fake_database_admin(fixtures, target, connection, monkeypatch)
    with ExitStack() as entered:
        with pytest.raises(RuntimeError, match="^POSTGRES_DATABASE_OWNERSHIP_JOURNAL_INVALID$"):
            entered.enter_context(
                fixtures.temporary_http_database(make_url("postgresql+psycopg://localhost/caseops"))
            )
    assert effects == ["admin_disposed"]


def test_database_journal_ack_write_failure_keeps_normal_owned_cleanup(
    database_journal, monkeypatch
):
    from sqlalchemy.engine import make_url

    fixtures, target, connection = database_journal
    effects, _ = fake_database_admin(fixtures, target, connection, monkeypatch)
    original = fixtures._database_ownership_journal

    def fail_ack(event, *args):
        if event == "create_ack":
            raise RuntimeError("POSTGRES_DATABASE_OWNERSHIP_JOURNAL_INVALID")
        original(event, *args)

    monkeypatch.setattr(fixtures, "_database_ownership_journal", fail_ack)
    with ExitStack() as entered:
        with pytest.raises(RuntimeError, match="^POSTGRES_DATABASE_OWNERSHIP_JOURNAL_INVALID$"):
            entered.enter_context(
                fixtures.temporary_http_database(make_url("postgresql+psycopg://localhost/caseops"))
            )
    assert [row["event"] for row in journal_rows(target)] == ["create_intent"]
    assert effects == ["create_dispatched", "drop_ack", "admin_disposed"]


def test_database_journal_lost_create_ack_retains_intent_without_retry(
    database_journal, monkeypatch
):
    from sqlalchemy.engine import make_url

    fixtures, target, connection = database_journal
    effects, _ = fake_database_admin(fixtures, target, connection, monkeypatch, unknown_create=True)
    with ExitStack() as entered:
        with pytest.raises(OSError, match="^synthetic lost create acknowledgement$"):
            entered.enter_context(
                fixtures.temporary_http_database(make_url("postgresql+psycopg://localhost/caseops"))
            )
    assert [row["event"] for row in journal_rows(target)] == ["create_intent"]
    assert effects == ["create_dispatched", "admin_disposed"]


@pytest.mark.parametrize("write_kind", ["short", "zero", "parent_swap"])
def test_database_journal_complete_writes_final_namespace_and_fd_closure(
    database_journal, monkeypatch, write_kind
):
    import os

    fixtures, target, connection = database_journal
    real = fixtures.os
    opened = []
    writes = []

    def open_fd(*args):
        fd = real.open(*args)
        opened.append(fd)
        return fd

    def write_fd(fd, data):
        if write_kind == "zero":
            writes.append(0)
            return 0
        n = real.write(fd, data[:7] if write_kind == "short" else data)
        writes.append(n)
        if write_kind == "parent_swap" and len(writes) == 1:
            parent = target.parent
            moved = parent.with_name(parent.name + "-retained")
            parent.rename(moved)
            parent.symlink_to(moved, target_is_directory=True)
        return n

    attributes = [
        "environ",
        "name",
        "getpid",
        "fstat",
        "read",
        "close",
        "fsync",
        "O_RDONLY",
        "O_WRONLY",
        "O_APPEND",
    ]
    proxy = SimpleNamespace(**{name: getattr(real, name) for name in attributes})
    for name in ["getuid", "O_NOFOLLOW", "O_NONBLOCK"]:
        if hasattr(real, name):
            setattr(proxy, name, getattr(real, name))
    proxy.open, proxy.write = open_fd, write_fd
    monkeypatch.setattr(fixtures, "os", proxy)
    args = (
        "create_intent",
        "caseops_http_template_" + "1" * 32,
        "caseops",
        "CREATE DATABASE fixture",
        connection,
    )
    if write_kind == "short":
        fixtures._database_ownership_journal(*args)
        assert len(writes) > 1 and len(journal_rows(target)) == 1
    else:
        with pytest.raises(RuntimeError, match="^POSTGRES_DATABASE_OWNERSHIP_JOURNAL_INVALID$"):
            fixtures._database_ownership_journal(*args)
    assert len(opened) == 2
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
