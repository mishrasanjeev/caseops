"""BUG-045 (Hari 2026-05-11): link evidence to hearing dates.

Adds ``hearing_id`` to ``matter_attachments`` so a lawyer can tag an
uploaded evidence/document with the specific hearing it belongs to,
and filter the documents tab by hearing date.

The column is nullable + ondelete SET NULL so legacy attachments and
attachments whose hearing has been deleted both keep working.

Revision ID: 20260511_0001
Revises: 20260509_0001
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260511_0001"
down_revision = "20260509_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    with op.batch_alter_table("matter_attachments") as batch:
        batch.add_column(sa.Column("hearing_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_matter_attachments_hearing_id",
            "matter_hearings",
            ["hearing_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_matter_attachments_hearing_id",
            ["hearing_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("matter_attachments") as batch:
        batch.drop_index("ix_matter_attachments_hearing_id")
        batch.drop_constraint(
            "fk_matter_attachments_hearing_id",
            type_="foreignkey",
        )
        batch.drop_column("hearing_id")
