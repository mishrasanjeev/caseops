"""ADP-01 firm storage governance quota.

Revision ID: 20260522_0001
Revises: 20260515_0001
Create Date: 2026-05-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260522_0001"
down_revision = "20260515_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("storage_quota_bytes")
