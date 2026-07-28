"""Add an optional court or forum number to matters.

Revision ID: 20260723_0001
Revises: 20260717_0002
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260723_0001"
down_revision = "20260717_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("matters") as batch_op:
        batch_op.add_column(sa.Column("court_forum_number", sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("matters") as batch_op:
        batch_op.drop_column("court_forum_number")
