"""Add structured recommendation analysis.

Revision ID: 20260526_0004
Revises: 20260526_0003
Create Date: 2026-05-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260526_0004"
down_revision = "20260526_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("analysis_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "analysis_json")
