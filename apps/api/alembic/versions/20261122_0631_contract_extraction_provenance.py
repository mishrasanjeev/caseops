"""Preserve provenance for AI-generated contract clauses and obligations.

Revision ID: 20261122_0631
Revises: 20261112_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Two constant-default boolean columns
need brief table locks without a PostgreSQL table rewrite. Lock and
statement timeouts bound the migration. Historical free text is untouched.
MIGRATION-ROLLBACK: restore-forward. Losing provenance would make retained
rows indistinguishable from manually authored records.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261122_0631"
down_revision = "20261112_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    for table in ("contract_clauses", "contract_obligations"):
        op.add_column(
            table,
            sa.Column("extracted_by_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    raise RuntimeError(
        "Contract extraction provenance is restore-forward. Restore the reviewed backup."
    )
