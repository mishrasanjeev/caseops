"""Add trigram indexes for conflict-check party scans.

Revision ID: 20260708_0001
Revises: 20260706_0001
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "20260708_0001"
down_revision = "20260706_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFLICT_TRIGRAM_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_clients_name_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_clients_name_trgm "
        "ON clients USING gin (lower(name) gin_trgm_ops)",
    ),
    (
        "ix_matters_client_name_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_matters_client_name_trgm "
        "ON matters USING gin (lower(client_name) gin_trgm_ops) "
        "WHERE client_name IS NOT NULL",
    ),
    (
        "ix_matters_opposing_party_trgm",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_matters_opposing_party_trgm "
        "ON matters USING gin (lower(opposing_party) gin_trgm_ops) "
        "WHERE opposing_party IS NOT NULL",
    ),
)

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "CONFLICT_TRIGRAM_INDEXES",
    "upgrade",
    "downgrade",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for _, ddl in CONFLICT_TRIGRAM_INDEXES:
            op.execute(ddl)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    with op.get_context().autocommit_block():
        for index_name, _ in reversed(CONFLICT_TRIGRAM_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
