"""Backfill tenant correlation for legacy shared-work rows.

Revision ID: 20260810_0002
Revises: 20260810_0001
"""

from __future__ import annotations

from alembic import op

revision = "20260810_0002"
down_revision = "20260810_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("matter_tasks", "matter_hearings", "matter_deadlines"):
        op.execute(
            f"""
            UPDATE {table_name} AS work
               SET company_id = matters.company_id
              FROM matters
             WHERE work.matter_id = matters.id
               AND work.company_id IS NULL
            """
        )


def downgrade() -> None:
    # Backfilled tenant keys are correct derived facts.  Clearing them would
    # make a rollback less safe and is unnecessary for the additive revision.
    pass
