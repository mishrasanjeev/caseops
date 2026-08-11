"""Add bounded-latency trigram indexes for structured authority search.

Revision ID: 20260811_0005
Revises: 20260811_0004
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision = "20260811_0005"
down_revision = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTHORITY_STRUCTURED_SEARCH_TRIGRAM_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_authority_documents_citation_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_authority_documents_citation_trgm ON authority_documents USING gin "
        "((coalesce(case_reference, '') || ' ' || "
        "coalesce(neutral_citation, '')) gin_trgm_ops)",
    ),
    (
        "ix_authority_documents_party_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_authority_documents_party_trgm ON authority_documents USING gin "
        "((coalesce(parties_json, '') || ' ' || coalesce(title, '')) gin_trgm_ops)",
    ),
    (
        "ix_authority_documents_name_prefilter_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_authority_documents_name_prefilter_trgm ON authority_documents USING gin "
        "((coalesce(parties_json, '') || ' ' || coalesce(title, '') || ' ' || "
        "coalesce(bench_name, '')) gin_trgm_ops)",
    ),
    (
        "ix_authority_documents_court_name_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_authority_documents_court_name_trgm ON authority_documents "
        "USING gin (court_name gin_trgm_ops)",
    ),
    (
        "ix_authority_documents_judge_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_authority_documents_judge_trgm ON authority_documents USING gin "
        "((coalesce(bench_name, '') || ' ' || coalesce(judges_json, '')) "
        "gin_trgm_ops)",
    ),
    (
        "ix_authority_documents_act_section_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_authority_documents_act_section_trgm ON authority_documents USING gin "
        "((coalesce(sections_cited_json, '') || ' ' || coalesce(title, '')) "
        "gin_trgm_ops)",
    ),
)

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "AUTHORITY_STRUCTURED_SEARCH_TRIGRAM_INDEXES",
    "upgrade",
    "downgrade",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Avoid blocking corpus ingestion or interactive reads while the indexes
    # are built over the production authority table.
    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for index_name, ddl in AUTHORITY_STRUCTURED_SEARCH_TRIGRAM_INDEXES:
            validity = bind.scalar(
                text(
                    "SELECT i.indisvalid FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relname = :name"
                ),
                {"name": index_name},
            )
            # An interrupted CREATE INDEX CONCURRENTLY leaves an invalid index.
            # IF NOT EXISTS would silently accept it on retry, so remove only
            # that invalid artifact before recreating the index.
            if validity is False:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
            op.execute(ddl)
            created_validity = bind.scalar(
                text(
                    "SELECT i.indisvalid FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relname = :name"
                ),
                {"name": index_name},
            )
            if created_validity is not True:
                raise RuntimeError(f"Authority search index is not valid: {index_name}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    with op.get_context().autocommit_block():
        for index_name, _ in reversed(AUTHORITY_STRUCTURED_SEARCH_TRIGRAM_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
