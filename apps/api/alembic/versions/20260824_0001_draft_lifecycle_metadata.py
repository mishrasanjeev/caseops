"""Add structured metadata to append-only draft review events.

Revision ID: 20260824_0001
Revises: 20260823_0004
Create Date: 2026-08-24

IPLF-046 keeps filing, rejection, correction, and service history on the
canonical DraftReview event stream. Existing rows receive an empty metadata
object and are otherwise unchanged.

MIGRATION-LOCK-RISK: acknowledged: one nullable-free text column is added to
the small draft_reviews table with a constant default. PostgreSQL lock timeout
is five seconds.
MIGRATION-ROLLBACK: metadata is additive; downgrade drops only the new column.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260824_0001"
down_revision = "20260823_0004"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    with op.batch_alter_table("draft_reviews") as batch:
        batch.add_column(
            sa.Column(
                "metadata_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("draft_reviews") as batch:
        batch.drop_column("metadata_json")
