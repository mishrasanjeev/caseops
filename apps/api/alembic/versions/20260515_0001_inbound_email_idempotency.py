"""Inbound email communication idempotency.

Revision ID: 20260515_0001
Revises: 20260513_0001
Create Date: 2026-05-15
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "20260515_0001"
down_revision = "20260513_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("communications") as batch_op:
        batch_op.create_unique_constraint(
            "uq_communications_message_scope",
            ["company_id", "matter_id", "external_message_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("communications") as batch_op:
        batch_op.drop_constraint(
            "uq_communications_message_scope",
            type_="unique",
        )
