"""Index authority neutral citations used by exact citation lookups.

Draft citation verification, pleading validation, hearing packs and appeal
strength match citations with ``id``, ``case_reference`` and
``neutral_citation`` equality. ``neutral_citation`` had no equality index, so
the OR of those three predicates read the whole authority corpus (>800K
documents) on every IP pleading validate request: about 4.6 seconds in
production.

Revision ID: 20260928_0001
Revises: 20260925_0001
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision = "20260928_0001"
down_revision = "20260925_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_authority_documents_neutral_citation"
_INDEX_DDL = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    f"{_INDEX_NAME} ON authority_documents (neutral_citation)"
)
_INDEX_HEALTH = text(
    "SELECT i.indisvalid FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relname = :name"
)

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite is the test engine only; keep its plans on the same index.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} ON authority_documents (neutral_citation)"
        )
        return

    # Ingestion writes this table continuously, so build without blocking
    # writers. An interrupted concurrent build leaves an invalid index behind;
    # remove only that artifact before retrying.
    with op.get_context().autocommit_block():
        validity = bind.scalar(_INDEX_HEALTH, {"name": _INDEX_NAME})
        if validity is False:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
        op.execute(_INDEX_DDL)
        if bind.scalar(_INDEX_HEALTH, {"name": _INDEX_NAME}) is not True:
            raise RuntimeError(f"Authority citation index is not valid: {_INDEX_NAME}")


def downgrade() -> None:
    # Keep this removal in Alembic's transaction. A later restore-forward
    # refusal must roll it back together with the rest of the downgrade path.
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
