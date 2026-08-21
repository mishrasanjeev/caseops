"""Add the tenant-leading trademark application family index.

Revision ID: 20260822_0001
Revises: 20260821_0005
Create Date: 2026-08-22

The index supports aggregate-first mark-family pagination. It changes no data
and introduces no new record owner or retention surface.

MIGRATION-LOCK-RISK: a normal catalog/index-build lock is required on
``trademark_applications``. Production rollout should use the standard brief
write-maintenance window and inspect table/index size first.
MIGRATION-ROLLBACK: safe; dropping the index changes performance only.
"""

from __future__ import annotations

from alembic import op

revision = "20260822_0001"
down_revision = "20260821_0005"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: no change; index duplicates tenant/asset lookup keys only.


def upgrade() -> None:
    op.create_index(
        "ix_tm_applications_company_asset",
        "trademark_applications",
        ["company_id", "asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tm_applications_company_asset",
        table_name="trademark_applications",
    )
