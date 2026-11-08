"""B4-ADJ-36: the integrity scan's tombstone count reads only tombstoned rows."""

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.services.private_retrieval_jobs import inspect_private_index_integrity
from tests.fixtures_historical_attachments import historical_attachment_sessions
from tests.migration_index_catalog import require_index_additions, require_revision, schema_catalog
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company

PARENT = "20261104_0001"
HEAD = "20261106_0001"
PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261106_0001_private_projection_tombstone_index.py"
)
TABLE = "private_index_projections"
NAME = "ix_private_projection_tombstoned"
EXPECTED = ((TABLE, NAME, ["company_id"]),)
BUILDING = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} %"
STAMP = datetime(2026, 11, 6, 1, 2, 3, tzinfo=UTC)


def module():
    spec = importlib.util.spec_from_file_location("tombstone_index_20261106", PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def apply(engine, operation="upgrade", destination=PARENT):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"destination_rev": destination})
        with context.begin_transaction(), Operations.context(context):
            getattr(module(), operation)()


def shape(engine):
    with engine.connect() as connection:
        found = next(row for row in inspect(connection).get_indexes(TABLE) if row["name"] == NAME)
        assert found["column_names"] == ["company_id"] and not found["unique"]
        if engine.dialect.name == "postgresql":
            row = connection.execute(
                text(
                    "SELECT i.indisvalid, i.indisready, pg_get_expr(i.indpred, i.indrelid) "
                    "FROM pg_index i WHERE i.indexrelid = to_regclass(:name)"
                ),
                {"name": NAME},
            ).one()
            assert tuple(row) == (True, True, "is_tombstoned")
        else:
            assert module()._sqlite_exists(connection)


def seed_generations(engine, *, generations, rows, tombstone_every):
    """Retained generations of one tenant, as production keeps after each rebuild."""
    with Session(engine) as session:
        company_id = _seed_company(session)
        for number in range(1, generations + 1):
            session.execute(
                text(
                    "INSERT INTO private_index_generations (id, company_id, generation_number, "
                    "state, created_at, activated_at, retired_at) VALUES (:id, :company, :n, "
                    ":state, :ts, :active, :retired)"
                ),
                {
                    "id": f"{company_id[:8]}-gen-{number}",
                    "company": company_id,
                    "n": number,
                    "state": "active" if number == generations else "retired",
                    "ts": STAMP,
                    "active": STAMP if number == generations else None,
                    "retired": None if number == generations else STAMP,
                },
            )
        session.execute(
            text(
                """
                INSERT INTO private_index_projections (id, company_id, generation_id,
                  source_type, source_id, source_version, chunk_ordinal, label, content_text,
                  content_sha256, confidentiality, source_state, approval_state,
                  access_policy_version, access_policy_generation, tombstone_generation,
                  is_tombstoned, tombstoned_at, tombstone_reason, created_at, updated_at)
                SELECT :prefix || '-' || g || '-' || n, :company, :prefix || '-gen-' || g,
                  'matter_document', 'src-' || n, 'v1', 0, 'label',
                  CASE WHEN n % :every = 0 THEN '' ELSE repeat(md5(n::text), 8) END,
                  md5(n::text) || md5(n::text), 'internal', 'active', 'not_required', 1, 1, 0,
                  n % :every = 0, CASE WHEN n % :every = 0 THEN CAST(:ts AS timestamptz) END,
                  CASE WHEN n % :every = 0 THEN 'source_deleted' END, :ts, :ts
                FROM generate_series(1, :generations) g, generate_series(1, :rows) n
                """
            ),
            {
                "prefix": company_id[:8],
                "company": company_id,
                "every": tombstone_every,
                "ts": STAMP,
                "generations": generations,
                "rows": rows,
            },
        )
        session.commit()
    return company_id


@pytest.mark.parametrize("kind", KINDS)
def test_index_upgrade_reapply_downgrade_roundtrip(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        parent = schema_catalog(engine)
        command.upgrade(config, HEAD)
        shape(engine)
        head = schema_catalog(engine)
        require_index_additions(parent, head, EXPECTED)
        require_revision(engine, HEAD)
        apply(engine)
        shape(engine)
        assert schema_catalog(engine) == head
        command.downgrade(config, PARENT)
        assert schema_catalog(engine) == parent
        require_revision(engine, PARENT)
        command.upgrade(config, HEAD)
        shape(engine)
        assert schema_catalog(engine) == head


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "wrong",
    [
        f"CREATE INDEX {NAME} ON {TABLE} (generation_id) WHERE is_tombstoned",
        f"CREATE INDEX {NAME} ON {TABLE} (company_id)",
    ],
    ids=["wrong_columns", "missing_predicate"],
)
def test_conflicting_shape_refuses_without_ddl(kind, wrong, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        with engine.begin() as connection:
            connection.exec_driver_sql(wrong)
        catalog = schema_catalog(engine)
        with pytest.raises(RuntimeError, match="conflicting shape"):
            apply(engine)
        assert schema_catalog(engine) == catalog
        require_revision(engine, PARENT)


@pytest.mark.postgres
@pytest.mark.parametrize("statistics", ["analyzed", "never_analyzed", "stale_empty"])
@pytest.mark.parametrize("index_built", ["before_seed", "after_seed"])
def test_integrity_tombstone_count_reads_only_the_partial_index(
    statistics, index_built, tmp_path, monkeypatch, record_property
):
    """Runs the scan's own statement, not a copy of it, against retained generations.

    Production plans this count right after a rebuild, before autovacuum has
    analyzed the new rows, so the bound must hold without fresh statistics and
    whether the index predates the rows or was built over them.
    """
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD if index_built == "before_seed" else PARENT)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER TABLE {TABLE} SET (autovacuum_enabled = false)")
            if statistics == "stale_empty":
                connection.exec_driver_sql(f"ANALYZE {TABLE}")
        company_id = seed_generations(engine, generations=40, rows=1500, tombstone_every=500)
        if index_built == "after_seed":
            command.upgrade(config, HEAD)
        with engine.begin() as connection:
            if statistics == "analyzed":
                connection.exec_driver_sql(f"ANALYZE {TABLE}")
            analyzed = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stats WHERE tablename = :table "
                    "AND attname = 'is_tombstoned'"
                ),
                {"table": TABLE},
            ).scalar_one()
        assert analyzed == (1 if statistics == "analyzed" else 0)

        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            # B4-ADJ-40's retained-payload counts also name these columns; this
            # test owns the unsafe-tombstone count, the one without a label.
            if (
                "is_tombstoned" in statement
                and "content_text !=" in statement
                and "label" not in statement
            ):
                statements.append((statement, parameters))

        # The dated schema predates native attachment provenance. The integrity
        # reader uses the retained attachment identity and hash.
        historical_sessions = historical_attachment_sessions(engine)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with historical_sessions() as session:
                report = inspect_private_index_integrity(session, company_id=company_id)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert report.unsafe_tombstone_count == 0
        assert len(statements) == 1
        statement, parameters = statements[0]

        with engine.connect() as connection:
            raw = connection.connection.dbapi_connection
            with raw.cursor() as cursor:
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)
                plan = cursor.fetchone()[0][0]["Plan"]
        record_property(
            "tombstone_count_plan",
            {"statistics": statistics, "index_built": index_built, "plan": plan},
        )

        def walk(node):
            yield node
            for child in node.get("Plans", ()):
                yield from walk(child)

        nodes = list(walk(plan))
        # With statistics the planner reads the index directly; without them it
        # drives a bitmap heap scan from the same index. Both read only it.
        assert [node["Index Name"] for node in nodes if "Index Name" in node] == [NAME]
        assert {node["Node Type"] for node in nodes} <= {
            "Aggregate",
            "Index Scan",
            "Bitmap Index Scan",
            "Bitmap Heap Scan",
        }
        # 40 generations x 1,500 rows hold 120 tombstones; the prefilter index
        # alone would read every generation's entries for the tenant.
        assert plan["Shared Hit Blocks"] + plan["Shared Read Blocks"] < 200


def _index_row(engine):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT i.indexrelid AS oid, i.indisvalid, i.indisready FROM pg_index i "
                "WHERE i.indexrelid = to_regclass(:name)"
            ),
            {"name": NAME},
        ).first()


def _projection_rows(engine):
    with engine.connect() as connection:
        return connection.execute(
            text(f"SELECT id, md5(CAST(p AS text)) FROM {TABLE} p ORDER BY id")
        ).all()


@pytest.mark.postgres
@pytest.mark.parametrize("phase", ["writers", "snapshots"])
def test_cancelled_concurrent_build_recovers_on_second_upgrade(
    phase, tmp_path, monkeypatch, record_property
):
    """A deploy interrupted mid-build leaves an invalid index; the next upgrade rebuilds it."""
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        company_id = seed_generations(engine, generations=2, rows=6, tombstone_every=3)
        parent = schema_catalog(engine)
        rows = _projection_rows(engine)
        held, observed = [], {}

        def before_build(connection, cursor, statement, parameters, context, executemany):
            if (
                connection.engine.url.database != engine.url.database
                or not statement.startswith(BUILDING[:-1])
                or held
            ):
                return
            for setting in ("lock_timeout", "statement_timeout"):
                observed[setting] = connection.exec_driver_sql("SHOW " + setting).scalar_one()
            blocker = engine.connect().execution_options(isolation_level="REPEATABLE READ")
            held.append(blocker)
            if phase == "writers":
                # An uncommitted tombstoning write holds the table while the build starts.
                blocker.execute(
                    text(
                        f"UPDATE {TABLE} SET updated_at = updated_at "
                        "WHERE company_id = :company AND is_tombstoned"
                    ),
                    {"company": company_id},
                )
            else:
                blocker.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()

        event.listen(Engine, "before_cursor_execute", before_build)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(command.upgrade, config, HEAD)
                try:
                    deadline, cancelled = time.monotonic() + 30, False
                    while time.monotonic() < deadline and not future.done():
                        state = _index_row(engine)
                        if (
                            state is not None
                            and not state.indisvalid
                            and state.indisready == (phase == "snapshots")
                        ):
                            with engine.connect().execution_options(
                                isolation_level="AUTOCOMMIT"
                            ) as monitor:
                                pid = monitor.scalar(
                                    text(
                                        "SELECT pid FROM pg_stat_activity "
                                        "WHERE datname = :database AND state = 'active' "
                                        "AND query LIKE :query AND wait_event_type = 'Lock' "
                                        "AND wait_event = 'virtualxid'"
                                    ),
                                    {"database": engine.url.database, "query": BUILDING},
                                )
                                if pid is not None:
                                    assert monitor.scalar(
                                        text("SELECT pg_cancel_backend(:pid)"), {"pid": pid}
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

        failed = _index_row(engine)
        assert failed is not None and not failed.indisvalid
        assert failed.indisready == (phase == "snapshots")
        require_revision(engine, PARENT)
        assert observed == {"lock_timeout": "5s", "statement_timeout": "15min"}
        assert _projection_rows(engine) == rows

        command.upgrade(config, HEAD)
        shape(engine)
        assert _index_row(engine).oid != failed.oid
        require_index_additions(parent, schema_catalog(engine), EXPECTED)
        require_revision(engine, HEAD)
        assert _projection_rows(engine) == rows
        record_property(
            "native_interruption",
            {"phase": phase, "sqlstate": "57014", "failed_indisready": failed.indisready},
        )
