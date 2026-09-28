"""Index authority neutral citations used by exact citation lookups.

Draft citation verification, pleading validation, hearing packs and appeal
strength match citations with ``id``, ``case_reference`` and
``neutral_citation`` equality. ``neutral_citation`` had no equality index, so
the OR of those three predicates read the whole authority corpus (>800K
documents) on every IP pleading validate request: about 4.6 seconds in
production.

DATA-GOVERNANCE-MAP: updated

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
# Literal DDL keeps the index name visible to the governance migration-index
# inventory in scripts/ip_data_governance_map.py.
_INDEX_DDL = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_authority_documents_neutral_citation "
    "ON authority_documents (neutral_citation)"
)
_SQLITE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_authority_documents_neutral_citation "
    "ON authority_documents (neutral_citation)"
)
_INDEX_HEALTH = text(
    "SELECT i.indisvalid FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relname = :name"
)
# IF NOT EXISTS keeps any index of this name. Accept only the exact shape this
# migration builds: a plain, non-unique B-tree on the column, with its default
# operator class and collation.
_INDEX_SHAPE = text(
    "SELECT t.relname, am.amname, i.indisunique, i.indnatts, "
    "i.indexprs IS NULL AND i.indpred IS NULL, a.attname, "
    "opc.opcdefault, i.indcollation[0] = a.attcollation "
    "FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_class t ON t.oid = i.indrelid "
    "JOIN pg_am am ON am.oid = c.relam "
    "JOIN pg_opclass opc ON opc.oid = i.indclass[0] "
    "LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0] "
    "WHERE n.nspname = current_schema() AND c.relname = :name"
)
_EXPECTED_SHAPE = (
    "authority_documents", "btree", False, 1, True, "neutral_citation", True, True,
)

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
)


def _require_expected_shape(bind) -> None:
    row = bind.execute(_INDEX_SHAPE, {"name": _INDEX_NAME}).one_or_none()
    shape = tuple(row) if row is not None else None
    if shape != _EXPECTED_SHAPE:
        raise RuntimeError(
            f"{_INDEX_NAME} has an unexpected definition {shape}; "
            f"expected {_EXPECTED_SHAPE}. Inspect it before upgrading: this "
            "migration does not drop an index it did not build."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite is the test engine only; keep its plans on the same index.
        op.execute(_SQLITE_INDEX_DDL)
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
        # IF NOT EXISTS keeps a same-named index of any shape.
        _require_expected_shape(bind)


def downgrade() -> None:
    # Keep this removal in Alembic's transaction. A later restore-forward
    # refusal must roll it back together with the rest of the downgrade path.
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
