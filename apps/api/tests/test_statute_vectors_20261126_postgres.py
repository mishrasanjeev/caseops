"""PostgreSQL/pgvector proof for the statute vector index (FT-118/FT-119, NFT-026).

Migration 20261126_0101 upgrade and its restore-forward downgrade refusal on
SQLite and PostgreSQL, the pgvector column and HNSW index, and the production
query path (cosine distance through HNSW) with the deterministic offline
embedder. No paid provider is called.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import Statute, StatuteSection, StatuteSectionChunk
from caseops_api.db.session import clear_engine_cache
from caseops_api.services import statute_vectors as vectors
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_ip_document_taxonomy_defaults_migration_20261031 import _alembic_config
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_statute_vectors_20261126 import PARAPHRASE, SECTION_TEXT, ContentWordProvider

PARENT = "20261124_0002"
REVISION = "20261126_0101"
TABLE = "statute_section_chunks"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def fresh_engine(request, tmp_path):
    if request.param == "postgres":
        source = request.getfixturevalue("pg_engine")
        with temporary_http_database(source.url) as engine:
            yield engine
    else:
        engine = create_engine(
            "sqlite+pysqlite:///" + (tmp_path / "statute-vectors.db").as_posix()
        )
        try:
            yield engine
        finally:
            engine.dispose()


def test_migration_adds_only_the_chunk_table_and_refuses_downgrade(
    fresh_engine, monkeypatch
) -> None:
    config = _alembic_config(fresh_engine, monkeypatch)
    postgres = fresh_engine.dialect.name == "postgresql"
    try:
        command.upgrade(config, PARENT)
        assert TABLE not in inspect(fresh_engine).get_table_names()
        command.upgrade(config, REVISION)
        inspector = inspect(fresh_engine)
        columns = {column["name"] for column in inspector.get_columns(TABLE)}
        assert {
            "statute_id", "section_id", "section_number", "section_label", "chunk_index",
            "char_start", "char_end", "content", "source_sha256", "source_version",
            "exact_source_version", "chunker_version", "embedded_text_sha256",
            "embedding_model", "embedding_dimensions", "embedding_json", "embedded_at",
        } <= columns
        assert ("embedding_vector" in columns) is postgres
        assert not {"company_id", "matter_id"} & columns
        indexes = {row["name"] for row in inspector.get_indexes(TABLE)}
        assert {
            "ix_statute_section_chunks_statute_id",
            "ix_statute_section_chunks_embedding_model",
        } <= indexes
        if postgres:
            with fresh_engine.connect() as connection:
                definition = connection.scalar(
                    text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
                    {"name": "ix_statute_section_chunks_embedding_hnsw"},
                )
                vector_type = connection.scalar(
                    text(
                        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                        "WHERE attrelid = CAST(:table AS regclass) AND attname = 'embedding_vector'"
                    ),
                    {"table": TABLE},
                )
            assert "hnsw" in definition and "vector_cosine_ops" in definition
            assert vector_type == "vector(1024)"
        # Restore-forward only: the downgrade refuses before any DDL, so a
        # downgrade through this head never half-changes the schema.
        before = sorted(inspect(fresh_engine).get_table_names())
        with pytest.raises(RuntimeError, match="restore-forward only"):
            command.downgrade(config, PARENT)
        assert sorted(inspect(fresh_engine).get_table_names()) == before
        with fresh_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
    finally:
        clear_engine_cache()


@pytest.mark.postgres
def test_hnsw_path_returns_the_paraphrased_section_and_drops_stale_rows(
    pg_engine, _ensure_migrations  # noqa: F811
) -> None:
    statute_id = f"pg-statute-vectors-{uuid4().hex[:12]}"
    embedder = ContentWordProvider()
    try:
        with Session(pg_engine) as session:
            session.add(Statute(id=statute_id, short_name="PG Act", long_name="PG Revenue Act"))
            session.flush()
            labels = {"Section 4": "Charge of tax", "Section 195": "Other sums",
                      "Section 139": "Return of income"}
            for ordinal, (number, body) in enumerate(SECTION_TEXT.items()):
                session.add(StatuteSection(
                    statute_id=statute_id, section_number=number, section_label=labels[number],
                    section_text=body, section_text_source="official_release_manifest",
                    section_text_fetched_at=datetime.now(UTC),
                    verification_status="verified_official",
                    source_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    source_publisher="India Code", issuing_body="Legislative Department",
                    source_status="official", legal_status="enacted",
                    exact_source_version="pg test edition", source_locator_type="section_deep_link",
                    link_health_status="available", ordinal=ordinal, is_active=True,
                ))
            session.commit()

        with Session(pg_engine) as session:
            summary = vectors.sync_statute_section_chunks(session, embedder=embedder)
        assert summary.errors == 0 and summary.embedded_sections >= 3
        with pg_engine.connect() as connection:
            missing_vectors = connection.scalar(
                text(
                    "SELECT count(*) FROM statute_section_chunks "
                    "WHERE statute_id = :statute AND embedding_vector IS NULL"
                ),
                {"statute": statute_id},
            )
            mismatched = connection.scalar(
                text(
                    "SELECT count(*) FROM statute_section_chunks WHERE statute_id = :statute "
                    "AND embedding_vector <> CAST(embedding_json AS vector)"
                ),
                {"statute": statute_id},
            )
        # The pgvector column holds exactly the vector recorded in embedding_json.
        assert (missing_vectors, mismatched) == (0, 0)

        with Session(pg_engine) as session:
            hits = vectors.search_statute_sections(session, PARAPHRASE, embedder=embedder)
            assert hits[0].statute.id == statute_id
            assert (hits[0].section.section_number, hits[0].match) == ("Section 195", "semantic")
            assert hits[0].similarity >= vectors.min_similarity_for(embedder.model)

        # The production query shape can be served by the HNSW index.
        query_vector = embedder.embed([PARAPHRASE], input_type="query").vectors[0]
        literal = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
        with pg_engine.connect() as connection:
            connection.execute(text("SET enable_seqscan = off"))
            plan = "\n".join(
                row[0]
                for row in connection.execute(
                    text(
                        "EXPLAIN SELECT id, embedding_model, embedding_dimensions, "
                        "1 - (embedding_vector <=> CAST(:query AS vector)) AS similarity "
                        "FROM statute_section_chunks WHERE embedding_vector IS NOT NULL "
                        "ORDER BY embedding_vector <=> CAST(:query AS vector) LIMIT 40"
                    ),
                    {"query": literal},
                )
            )
            connection.rollback()
        assert "ix_statute_section_chunks_embedding_hnsw" in plan, plan

        # A section that loses verification is never returned, even before the
        # index is rebuilt, and the next run removes its chunks.
        with Session(pg_engine) as session:
            section = session.query(StatuteSection).filter_by(
                statute_id=statute_id, section_number="Section 195"
            ).one()
            section.verification_status = "quarantined"
            session.commit()
        with Session(pg_engine) as session:
            hits = vectors.search_statute_sections(session, PARAPHRASE, embedder=embedder)
            assert "Section 195" not in {
                hit.section.section_number for hit in hits if hit.statute.id == statute_id
            }
        with Session(pg_engine) as session:
            vectors.sync_statute_section_chunks(session, embedder=embedder)
        with pg_engine.connect() as connection:
            remaining = connection.scalar(
                text(
                    "SELECT count(*) FROM statute_section_chunks c JOIN statute_sections s "
                    "ON s.id = c.section_id WHERE s.statute_id = :statute "
                    "AND s.section_number = 'Section 195'"
                ),
                {"statute": statute_id},
            )
        assert remaining == 0
    finally:
        with Session(pg_engine) as session:
            session.execute(delete(StatuteSectionChunk).where(
                StatuteSectionChunk.statute_id == statute_id
            ))
            session.execute(delete(StatuteSection).where(StatuteSection.statute_id == statute_id))
            session.execute(delete(Statute).where(Statute.id == statute_id))
            session.commit()
