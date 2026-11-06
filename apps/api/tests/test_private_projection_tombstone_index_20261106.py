"""B4-ADJ-36: the integrity scan's tombstone count reads only tombstoned rows."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.services.private_retrieval_jobs import inspect_private_index_integrity
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
def test_integrity_tombstone_count_reads_only_the_partial_index(tmp_path, monkeypatch):
    """Runs the scan's own statement, not a copy of it, against retained generations."""
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, "head")
        company_id = seed_generations(engine, generations=40, rows=1500, tombstone_every=500)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ANALYZE {TABLE}")

        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if "is_tombstoned" in statement and "content_text !=" in statement:
                statements.append((statement, parameters))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with Session(engine) as session:
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

        def walk(node):
            yield node
            for child in node.get("Plans", ()):
                yield from walk(child)

        scans = [node for node in walk(plan) if "Index Name" in node or "Relation Name" in node]
        assert [node.get("Index Name") for node in scans] == [NAME]
        # 40 generations x 1,500 rows hold 120 tombstones; the prefilter index
        # alone would read every generation's entries for the tenant.
        assert plan["Shared Hit Blocks"] + plan["Shared Read Blocks"] < 200
