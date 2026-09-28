"""Real PostgreSQL proof for bounded IP pleading validation (2026-09-28).

Production's authority corpus exceeds 800K documents, and before the
neutral-citation index every citation recheck scanned all of it. A table large
enough that a sequential scan costs thousands of blocks makes that visible
without timing: the exact captured lookup must use indexes and read a small
bounded number of blocks, with no manual ANALYZE after the bulk load.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.session import get_engine
from tests import test_20260928_pleading_validation_bounded as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres

FILLER_AUTHORITIES = 60_000
LOOKUP_BLOCK_BOUND = 64


def test_pleading_validation_is_one_bounded_statement_set_on_postgres(
    isolated_postgres_client,
):
    journeys.validate_twice(isolated_postgres_client, corpus_rows=400, plan_check=None)


def _seed_production_shaped_corpus() -> int:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO authority_documents
                  (id, source, adapter_name, court_name, forum_level, document_type, title,
                   case_reference, neutral_citation, canonical_key, summary,
                   extracted_char_count, parties_json, bench_name, decision_date,
                   ingested_at, created_at, updated_at)
                SELECT
                  md5('filler' || i)::uuid::text, 'ecourts-hc', 'validation-filler',
                  'Delhi High Court', 'high_court', 'judgment',
                  'Filler party ' || i || ' v State',
                  'CA ' || i || '/2001',
                  CASE WHEN i % 4 = 0 THEN NULL ELSE '2001 FILLER ' || i END,
                  'validation-filler::' || i,
                  repeat(md5(i::text), 20),
                  640,
                  '["Filler party ' || i || '", "State"]',
                  'Bench ' || (i % 40),
                  date '2001-01-01' + (i % 6000),
                  now(), now(), now()
                FROM generate_series(1, :rows) AS i
                """
            ),
            {"rows": FILLER_AUTHORITIES},
        )
        return int(
            connection.scalar(
                text(
                    "SELECT pg_relation_size('authority_documents') "
                    "/ current_setting('block_size')::int"
                )
            )
        )


def test_pleading_citation_lookup_is_index_bounded_at_production_corpus_shape(
    isolated_postgres_client,
):
    table_blocks = _seed_production_shaped_corpus()
    assert table_blocks > 20 * LOOKUP_BLOCK_BOUND

    def lookup_reads_bounded_blocks(engine, statement, parameters) -> None:
        with engine.connect() as connection:
            raw = connection.exec_driver_sql(
                f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}", parameters
            ).scalar()
        plan = (raw if isinstance(raw, list) else json.loads(raw))[0]
        nodes = []

        def walk(node) -> None:
            nodes.append((node["Node Type"], node.get("Relation Name") or node.get("Index Name")))
            for child in node.get("Plans", []):
                walk(child)

        walk(plan["Plan"])
        blocks = plan["Plan"].get("Shared Hit Blocks", 0) + plan["Plan"].get(
            "Shared Read Blocks", 0
        )
        assert ("Seq Scan", "authority_documents") not in nodes, nodes
        assert any(name == "ix_authority_documents_neutral_citation" for _, name in nodes), nodes
        assert blocks <= LOOKUP_BLOCK_BOUND, (blocks, table_blocks, nodes)

    journeys.validate_twice(
        isolated_postgres_client,
        corpus_rows=400,
        plan_check=lookup_reads_bounded_blocks,
    )


def _migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260928_0001_authority_neutral_citation_index.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_citation_index_migration_recovers_an_interrupted_concurrent_build(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _migration()
    name = migration._INDEX_NAME
    schema = f"citation_index_{uuid4().hex}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET search_path TO {schema}, public"))
            connection.execute(
                text(
                    "CREATE TABLE authority_documents "
                    "(id varchar(36), neutral_citation varchar(255))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO authority_documents VALUES "
                    "('a', '2026 DUP 1'), ('b', '2026 DUP 1'), ('c', NULL)"
                )
            )
            # A failed concurrent build leaves a real invalid pg_index row behind.
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX CONCURRENTLY {name} "
                        "ON authority_documents (neutral_citation)"
                    )
                )
            assert connection.scalar(migration._INDEX_HEALTH, {"name": name}) is False
            connection.commit()
            context = MigrationContext.configure(connection)
            with context.begin_transaction(), Operations.context(context):
                migration.upgrade()
                migration.upgrade()
            # autocommit_block restores the level it reads back, READ COMMITTED,
            # so return to AUTOCOMMIT before reads that would otherwise hold locks.
            connection.commit()
            connection.execution_options(isolation_level="AUTOCOMMIT")
            assert connection.scalar(migration._INDEX_HEALTH, {"name": name}) is True
            definition = connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = :schema AND indexname = :name"
                ),
                {"schema": schema, "name": name},
            )
            assert "UNIQUE" not in definition and "(neutral_citation)" in definition
            assert connection.scalar(text("SELECT count(*) FROM authority_documents")) == 3

            # The downgrade removal stays inside the enclosing transaction, so a
            # later refusal in the same downgrade path rolls it back.
            with pg_engine.connect() as transactional:
                transactional.execute(text("SET LOCAL lock_timeout = '10s'"))
                transactional.execute(text(f"SET LOCAL search_path TO {schema}, public"))
                with Operations.context(MigrationContext.configure(transactional)):
                    migration.downgrade()
                assert transactional.scalar(migration._INDEX_HEALTH, {"name": name}) is None
                transactional.rollback()
            assert connection.scalar(migration._INDEX_HEALTH, {"name": name}) is True
        finally:
            connection.rollback()
            connection.execute(text("RESET search_path"))
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            connection.commit()


# Valid indexes that carry the migration's name but cannot serve an exact
# neutral-citation lookup. CREATE INDEX IF NOT EXISTS would keep each of them.
WRONG_SHAPES = {
    "other-column": "CREATE INDEX {name} ON authority_documents (case_reference)",
    "other-table": "CREATE INDEX {name} ON other_citations (neutral_citation)",
    "unique": "CREATE UNIQUE INDEX {name} ON authority_documents (neutral_citation)",
    "expression": "CREATE INDEX {name} ON authority_documents (lower(neutral_citation))",
    "partial": (
        "CREATE INDEX {name} ON authority_documents (neutral_citation) "
        "WHERE neutral_citation IS NOT NULL"
    ),
    "hash": "CREATE INDEX {name} ON authority_documents USING hash (neutral_citation)",
    "operator-class": (
        "CREATE INDEX {name} ON authority_documents (neutral_citation varchar_pattern_ops)"
    ),
    "collation": 'CREATE INDEX {name} ON authority_documents (neutral_citation COLLATE "C")',
    "covering": (
        "CREATE INDEX {name} ON authority_documents (neutral_citation) INCLUDE (case_reference)"
    ),
}


@pytest.mark.parametrize("definition", WRONG_SHAPES.values(), ids=WRONG_SHAPES.keys())
def test_citation_index_migration_refuses_a_same_named_index_of_another_shape(
    pg_engine, definition
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _migration()
    name = migration._INDEX_NAME
    schema = f"citation_shape_{uuid4().hex}"
    index_definition = text(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = :schema AND indexname = :name"
    )
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET search_path TO {schema}, public"))
            connection.execute(
                text(
                    "CREATE TABLE authority_documents (id varchar(36), "
                    "neutral_citation varchar(255), case_reference varchar(255))"
                )
            )
            connection.execute(text("CREATE TABLE other_citations (neutral_citation varchar(255))"))
            connection.execute(
                text(
                    "INSERT INTO authority_documents VALUES "
                    "('a', '2026 ONE 1', 'CA 1/2026'), ('b', '2026 TWO 2', 'CA 2/2026')"
                )
            )
            connection.execute(text(definition.format(name=name)))
            assert connection.scalar(migration._INDEX_HEALTH, {"name": name}) is True
            before = connection.scalar(index_definition, {"schema": schema, "name": name})
            connection.commit()

            context = MigrationContext.configure(connection)
            with pytest.raises(RuntimeError, match="unexpected definition"):
                with context.begin_transaction(), Operations.context(context):
                    migration.upgrade()
            connection.rollback()
            connection.execution_options(isolation_level="AUTOCOMMIT")
            # The foreign index is reported, never dropped or replaced.
            assert connection.scalar(index_definition, {"schema": schema, "name": name}) == before
            assert connection.scalar(migration._INDEX_HEALTH, {"name": name}) is True
        finally:
            connection.rollback()
            connection.execute(text("RESET search_path"))
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            connection.commit()


def _index_inventory(engine) -> list[tuple]:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT p.tablename, p.indexname, p.indexdef, i.indisvalid, i.indisready "
                "FROM pg_indexes p "
                "JOIN pg_namespace n ON n.nspname = p.schemaname "
                "JOIN pg_class c ON c.relname = p.indexname AND c.relnamespace = n.oid "
                "JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE p.schemaname = current_schema() ORDER BY 1, 2"
            )
        ).all()


def test_refused_downgrade_keeps_every_index_including_the_citation_index(
    migration_pg_engine,
):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    engine = migration_pg_engine
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    head = ScriptDirectory.from_config(config).get_current_head()
    company_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, name, slug, company_type, tenant_key, is_active, timezone, created_at) "
                "VALUES (:id, 'Citation index fixture', :slug, 'law_firm', :id, true, "
                "'Asia/Kolkata', now())"
            ),
            {"id": company_id, "slug": f"citation-index-{company_id[:8]}"},
        )
        connection.execute(
            text(
                "INSERT INTO matter_bulk_update_operations "
                "(id, company_id, filename, format, status, total_rows, changed_rows, "
                "invalid_rows, applied_rows, failed_rows, row_results_json, created_at) "
                "VALUES (:id, :company_id, 'retained.xlsx', 'xlsx', 'applied', "
                "1, 1, 0, 1, 0, '[]', now())"
            ),
            {"id": str(uuid4()), "company_id": company_id},
        )
    before = _index_inventory(engine)
    assert ("authority_documents", "ix_authority_documents_neutral_citation") in {
        (row[0], row[1]) for row in before
    }

    for _attempt in range(2):
        # 20260924_0001 refuses while bulk-update history is retained. Every
        # removal above it, including this index, rolls back with the refusal.
        with pytest.raises(RuntimeError, match="retained bulk-update history"):
            command.downgrade(config, "20260920_0001")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
            assert (
                connection.scalar(text("SELECT count(*) FROM matter_bulk_update_operations")) == 1
            )
        assert _index_inventory(engine) == before

    # Without a refusal the same path removes the index, and a second upgrade
    # rebuilds it concurrently to the identical inventory.
    command.downgrade(config, "20260925_0001")
    assert "ix_authority_documents_neutral_citation" not in {
        row[1] for row in _index_inventory(engine)
    }
    command.upgrade(config, "head")
    assert _index_inventory(engine) == before


def test_neutral_citation_index_is_valid_after_head_on_postgres(isolated_postgres_client):
    del isolated_postgres_client
    with get_engine().connect() as connection:
        row = connection.execute(
            text(
                "SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = 'ix_authority_documents_neutral_citation'"
            )
        ).one()
    assert row[0] is True
    assert "(neutral_citation)" in row[1]
    assert "USING btree" in row[1]
