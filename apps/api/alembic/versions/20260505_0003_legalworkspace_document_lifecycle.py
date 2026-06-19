"""LegalWorkspace LW-S3 document lifecycle metadata.

Revision ID: 20260505_0003
Revises: 20260505_0002
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260505_0003"
down_revision = "20260505_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    with op.batch_alter_table("matter_attachments") as batch:
        batch.add_column(sa.Column("document_type", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("lifecycle_stage", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("document_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("sequence_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("linked_court_order_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_matter_attachments_linked_court_order_id",
            "matter_court_orders",
            ["linked_court_order_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_matter_attachments_document_type", ["document_type"])
        batch.create_index("ix_matter_attachments_lifecycle_stage", ["lifecycle_stage"])
        batch.create_index("ix_matter_attachments_document_date", ["document_date"])
        batch.create_index("ix_matter_attachments_sequence_index", ["sequence_index"])
        batch.create_index(
            "ix_matter_attachments_linked_court_order_id",
            ["linked_court_order_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("matter_attachments") as batch:
        batch.drop_index("ix_matter_attachments_linked_court_order_id")
        batch.drop_index("ix_matter_attachments_sequence_index")
        batch.drop_index("ix_matter_attachments_document_date")
        batch.drop_index("ix_matter_attachments_lifecycle_stage")
        batch.drop_index("ix_matter_attachments_document_type")
        batch.drop_constraint(
            "fk_matter_attachments_linked_court_order_id",
            type_="foreignkey",
        )
        batch.drop_column("linked_court_order_id")
        batch.drop_column("sequence_index")
        batch.drop_column("document_date")
        batch.drop_column("lifecycle_stage")
        batch.drop_column("document_type")
