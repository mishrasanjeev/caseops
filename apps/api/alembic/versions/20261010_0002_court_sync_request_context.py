"""Retain court queue provider isolation across independent execution.

Revision ID: 20261010_0002
Revises: 20261010_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20261010_0002"
down_revision = "20261010_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy jobs have no durable proof of permission to spend.
    op.add_column(
        "matter_court_sync_jobs",
        sa.Column("no_paid_providers", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_matter_court_sync_jobs_queue",
        "matter_court_sync_jobs",
        ["status", "queued_at", "updated_at", "id"],
    )
    op.create_index(
        "ix_matter_court_sync_jobs_recovery",
        "matter_court_sync_jobs",
        ["status", "started_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_matter_court_sync_jobs_recovery", "matter_court_sync_jobs")
    op.drop_index("ix_matter_court_sync_jobs_queue", "matter_court_sync_jobs")
    op.drop_column("matter_court_sync_jobs", "no_paid_providers")
