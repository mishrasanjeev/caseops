"""Align the database Matter creation default with the product policy.

Revision ID: 20260717_0001
Revises: 20260715_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260717_0001"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode keeps the migration valid for the SQLite migration replay as
    # well as PostgreSQL production. Existing statuses are intentionally left
    # unchanged; this only closes omitted-status creation paths.
    with op.batch_alter_table("matters") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=24),
            existing_nullable=False,
            server_default=sa.text("'active'"),
        )


def downgrade() -> None:
    with op.batch_alter_table("matters") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=24),
            existing_nullable=False,
            server_default=None,
        )
