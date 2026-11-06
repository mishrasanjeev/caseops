"""B4-ADJ-40: the retained-payload purge and its integrity count read one partial index."""

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import PrivateIndexProjection
from caseops_api.services.private_retrieval_jobs import (
    MAX_RETAINED_PAYLOAD_REPORT,
    _retained_payload_conditions,
    count_retained_private_payload,
    purge_retained_private_payloads,
)
from tests.migration_index_catalog import require_index_additions, require_revision, schema_catalog
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company

PARENT = "20261106_0001"
HEAD = "20261106_0002"
PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261106_0002_private_projection_retained_payload_index.py"
)
TABLE = "private_index_projections"
NAME = "ix_private_projection_retained_payload"
COLUMNS = ["company_id", "is_tombstoned", "generation_id"]
EXPECTED = ((TABLE, NAME, COLUMNS),)
BUILDING = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} %"
STAMP = datetime(2026, 11, 6, 9, 8, 7, tzinfo=UTC)


def module():
    spec = importlib.util.spec_from_file_location("retained_payload_index_20261106", PATH)
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
        assert found["column_names"] == COLUMNS and not found["unique"]
        if engine.dialect.name == "postgresql":
            row = connection.execute(
                text(
                    "SELECT i.indisvalid, i.indisready, pg_get_expr(i.indpred, i.indrelid) "
                    "FROM pg_index i WHERE i.indexrelid = to_regclass(:name)"
                ),
                {"name": NAME},
            ).one()
            assert tuple(row) == (True, True, module().POSTGRES_PREDICATE)
        else:
            assert module()._sqlite_exists(connection)


def seed_generations(engine, *, generations, rows, retained_every, tombstone_every, label_every):
    """One tenant's retained generations after the purge, with a residual backlog.

    Retired rows are blank except every ``retained_every``-th, which still holds
    text, a vector and a label as every pre-fix rebuild left them. Every
    ``tombstone_every``-th row is a tombstone, blank as purged tombstones are,
    except every ``label_every``-th, which still holds its pre-fix label.
    Tombstones accumulate in every retained generation, so they outnumber the
    active generation's live rows, which hold their full payload.
    """
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
                  embedding_json, embedding_dimensions,
                  is_tombstoned, tombstoned_at, tombstone_reason, created_at, updated_at)
                SELECT :prefix || '-' || g || '-' || n, :company, :prefix || '-gen-' || g,
                  'matter_document', 'src-' || n, 'v1', 0,
                  CASE WHEN tomb_label OR live OR backlog THEN 'Matter title ' || n
                    ELSE '' END,
                  CASE WHEN live OR backlog THEN repeat(md5(n::text), 8) ELSE '' END,
                  md5(n::text) || md5(n::text), 'internal', 'active', 'not_required', 1, 1, 0,
                  CASE WHEN live OR backlog THEN '[1.0, 0.0, 0.0]' END,
                  CASE WHEN live OR backlog THEN 3 END,
                  tomb, CASE WHEN tomb THEN CAST(:ts AS timestamptz) END,
                  CASE WHEN tomb THEN 'source_deleted' END, :ts, :ts
                FROM (
                  SELECT g, n, n % :tombstone_every = 0 AS tomb,
                    n % :tombstone_every = 0 AND n % :label_every = 0 AS tomb_label,
                    g = :generations AND n % :tombstone_every <> 0 AS live,
                    g < :generations AND n % :tombstone_every <> 0
                      AND n % :retained_every = 0 AS backlog
                  FROM generate_series(1, :generations) g, generate_series(1, :rows) n
                ) seeded
                """
            ),
            {
                "prefix": company_id[:8],
                "company": company_id,
                "retained_every": retained_every,
                "tombstone_every": tombstone_every,
                "label_every": label_every,
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
        f"CREATE INDEX {NAME} ON {TABLE} (company_id, generation_id) "
        "WHERE content_text <> '' OR embedding_json IS NOT NULL OR label <> ''",
        f"CREATE INDEX {NAME} ON {TABLE} (company_id, is_tombstoned, generation_id) "
        "WHERE content_text <> '' OR embedding_json IS NOT NULL",
        f"CREATE INDEX {NAME} ON {TABLE} (company_id, is_tombstoned, generation_id)",
    ],
    ids=["wrong_columns", "missing_label", "missing_predicate"],
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


def _walk(node):
    yield node
    for child in node.get("Plans", ()):
        yield from _walk(child)


def _exact_retained(engine, company_id):
    """Independent oracle: every row the purge must still blank, uncapped."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                f"SELECT count(*) FROM {TABLE} p WHERE p.company_id = :company "
                "AND (p.content_text <> '' OR p.embedding_json IS NOT NULL OR p.label <> '') "
                "AND (p.is_tombstoned OR p.generation_id IN (SELECT g.id FROM "
                "private_index_generations g WHERE g.company_id = :company "
                "AND g.state IN ('retired', 'failed')))"
            ),
            {"company": company_id},
        ).scalar_one()


def _blocks(plan):
    return plan["Shared Hit Blocks"] + plan["Shared Read Blocks"]


@pytest.mark.postgres
@pytest.mark.parametrize("backlog", ["residual", "full"])
@pytest.mark.parametrize("statistics", ["analyzed", "never_analyzed", "stale_empty"])
@pytest.mark.parametrize("index_built", ["before_seed", "after_seed"])
def test_retained_payload_reads_only_the_partial_index(
    backlog, statistics, index_built, tmp_path, monkeypatch, record_property
):
    """EXPLAINs the scan's and the purge's own statements over retained generations.

    ``full`` is production right after release: every row of every retired
    generation still holds text, a vector and a label, and maintenance is
    paused. ``residual`` is a nearly drained tenant. Production plans these
    right after a rebuild, before autovacuum has analyzed the new rows, so the
    bound must hold without fresh statistics and whether the index predates the
    rows or was built over them. The integrity request polls this count with a
    10 s budget, so it must not grow with the backlog.
    """
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD if index_built == "before_seed" else PARENT)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER TABLE {TABLE} SET (autovacuum_enabled = false)")
            if statistics == "stale_empty":
                connection.exec_driver_sql(f"ANALYZE {TABLE}")
        company_id = seed_generations(
            engine,
            generations=40,
            rows=1500,
            retained_every=1 if backlog == "full" else 499,
            tombstone_every=10,
            label_every=750,
        )
        if index_built == "after_seed":
            command.upgrade(config, HEAD)
        with engine.begin() as connection:
            if statistics == "analyzed":
                connection.exec_driver_sql(f"ANALYZE {TABLE}")
            analyzed = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stats WHERE tablename = :table "
                    "AND attname = 'content_text'"
                ),
                {"table": TABLE},
            ).scalar_one()
        assert analyzed == (1 if statistics == "analyzed" else 0)

        exact = _exact_retained(engine, company_id)
        # 39 retired generations x 1,350 (full) or 3 (residual) non-tombstone
        # rows, plus 2 labelled tombstones of the 150 in each of 40 generations.
        assert exact == 39 * (1350 if backlog == "full" else 3) + 40 * 2

        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if TABLE in statement and "embedding_json IS NOT NULL" in statement:
                statements.append((statement, parameters))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with Session(engine) as session:
                retained = count_retained_private_payload(session, company_id=company_id)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert retained == min(exact, MAX_RETAINED_PAYLOAD_REPORT)
        # The tombstone count alone reaches 80; the retired count reads the rest.
        assert len(statements) == 2

        def explain(statement, parameters):
            with engine.connect() as connection:
                raw = connection.connection.dbapi_connection
                with raw.cursor() as cursor:
                    cursor.execute(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
                    )
                    plan = cursor.fetchone()[0][0]["Plan"]
                raw.rollback()
            return plan

        plans = [explain(*captured) for captured in statements]

        # Negative control: the uncapped count(id) this scan used before the
        # cap. It reads every retained row, so against the full backlog it must
        # exceed the same bound the capped statements stay under.
        with Session(engine) as session:
            dialect = session.get_bind().dialect
            uncapped = [
                str(
                    select(func.count(PrivateIndexProjection.id))
                    .where(condition)
                    .compile(dialect=dialect, compile_kwargs={"literal_binds": True})
                )
                for condition in _retained_payload_conditions(company_id)
            ]
        uncapped_plans = [explain(statement, None) for statement in uncapped]
        record_property(
            "retained_payload_plans",
            {
                "backlog": backlog,
                "statistics": statistics,
                "index_built": index_built,
                "plans": plans,
                "uncapped_negative_control_plans": uncapped_plans,
            },
        )
        for plan in plans:
            nodes = list(_walk(plan))
            projection_indexes = {
                node["Index Name"]
                for node in nodes
                if "Index Name" in node
                and node.get("Relation Name", TABLE) == TABLE
                and not node["Index Name"].startswith("ix_private_index_generation")
                and not node["Index Name"].startswith("private_index_generations")
                and not node["Index Name"].startswith("uq_private_index_generation")
            }
            assert projection_indexes == {NAME}, projection_indexes
            # With fresh statistics the planner may scan the small generations
            # table; the projections table must never be scanned. The block
            # bound below covers both.
            assert not [
                node
                for node in nodes
                if node["Node Type"] == "Seq Scan" and node.get("Relation Name") == TABLE
            ]
            # 40 x 1,500 retained rows and 6,000 tombstones: the prefilter or
            # tombstone index read 2,082 blocks for the residual backlog alone.
            # Capped, each statement reads at most its remaining cap of rows.
            assert _blocks(plan) < 400, plan
        if backlog == "full":
            retired_uncapped = uncapped_plans[1]
            assert _blocks(retired_uncapped) > 2_000, retired_uncapped

        # The purge claims through the same index and drains the whole backlog.
        purge_statements = []

        def capture_purge(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in statement:
                purge_statements.append((statement, parameters))

        purged, calls, drained = 0, 0, False
        event.listen(engine, "before_cursor_execute", capture_purge)
        try:
            while not drained and calls < 3:
                with Session(engine) as session:
                    purge = purge_retained_private_payloads(session, company_id=company_id)
                purged, calls, drained = purged + purge.purged_count, calls + 1, purge.drained
        finally:
            event.remove(engine, "before_cursor_execute", capture_purge)
        # One call blanks at most 50,000 rows; the full backlog needs a second.
        assert (purged, drained, calls) == (exact, True, 2 if exact > 50_000 else 1)
        assert purge_statements
        assert _exact_retained(engine, company_id) == 0
        with Session(engine) as session:
            assert count_retained_private_payload(session, company_id=company_id) == 0
            # The active generation's live rows keep every payload.
            assert (
                session.execute(
                    text(
                        f"SELECT count(*) FROM {TABLE} WHERE generation_id = :gen "
                        "AND NOT is_tombstoned AND content_text <> '' AND label <> '' "
                        "AND embedding_json IS NOT NULL"
                    ),
                    {"gen": f"{company_id[:8]}-gen-40"},
                ).scalar_one()
                == 1500 - 150
            )
        claim = explain(*purge_statements[0])
        claim_nodes = list(_walk(claim))
        assert {
            node["Index Name"]
            for node in claim_nodes
            if node.get("Relation Name") == TABLE and "Index Name" in node
        } <= {NAME}
        assert not [
            node
            for node in claim_nodes
            if node["Node Type"] == "Seq Scan" and node.get("Relation Name") == TABLE
        ]


@pytest.mark.postgres
def test_purge_skips_rows_a_concurrent_writer_holds(tmp_path, monkeypatch):
    """A tenant disposition holding rows never makes the purge wait or deadlock."""
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        company_id = seed_generations(
            engine, generations=3, rows=10, retained_every=2, tombstone_every=100, label_every=100
        )
        with Session(engine) as session:
            total = count_retained_private_payload(session, company_id=company_id)
        assert total == 2 * 5
        held_id = f"{company_id[:8]}-1-2"
        with engine.connect() as holder:
            holder.execute(
                text(f"SELECT id FROM {TABLE} WHERE id = :id FOR UPDATE"), {"id": held_id}
            ).scalar_one()
            with Session(engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                started = time.monotonic()
                purge = purge_retained_private_payloads(session, company_id=company_id)
                elapsed = time.monotonic() - started
            holder.rollback()
        assert elapsed < 2
        assert (purge.purged_count, purge.drained) == (total - 1, False)
        with Session(engine) as session:
            finished = purge_retained_private_payloads(session, company_id=company_id)
        assert (finished.purged_count, finished.drained) == (1, True)


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
        company_id = seed_generations(
            engine, generations=2, rows=6, retained_every=2, tombstone_every=3, label_every=3
        )
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
                # An uncommitted purge-shaped write holds the table while the build starts.
                blocker.execute(
                    text(
                        f"UPDATE {TABLE} SET updated_at = updated_at "
                        "WHERE company_id = :company AND content_text <> ''"
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
