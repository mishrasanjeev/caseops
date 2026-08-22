"""Add the tenant-leading trademark application family index.

Revision ID: 20260822_0001
Revises: 20260821_0005
Create Date: 2026-08-22

The index supports aggregate-first mark-family pagination. It changes no data
and introduces no new record owner or retention surface.

MIGRATION-LOCK-RISK: PostgreSQL builds the index concurrently so normal writes
remain available; other test/development dialects use their ordinary index DDL.
MIGRATION-ROLLBACK: safe; dropping the index changes performance only.
"""

from __future__ import annotations

from alembic import op

revision = "20260822_0001"
down_revision = "20260821_0005"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_tm_applications_company_asset",
                "trademark_applications",
                ["company_id", "asset_id"],
                postgresql_concurrently=True,
            )
    else:
        # MIGRATION-LOCK-RISK: acknowledged: non-PostgreSQL paths are isolated
        # development/test databases and never serve concurrent production writes.
        op.create_index(
            "ix_tm_applications_company_asset",
            "trademark_applications",
            ["company_id", "asset_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                "ix_tm_applications_company_asset",
                table_name="trademark_applications",
                postgresql_concurrently=True,
            )
    else:
        op.drop_index(
            "ix_tm_applications_company_asset",
            table_name="trademark_applications",
        )
