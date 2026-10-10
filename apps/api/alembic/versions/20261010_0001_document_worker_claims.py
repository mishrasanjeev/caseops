"""Bound document queue scans and retain automated-provider isolation.

DATA-GOVERNANCE-MAP: updated
Revision ID: 20261010_0001
Revises: 20260928_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20261010_0001"
down_revision = "20260928_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An old receipt cannot prove whether its lost request context allowed spend.
    op.add_column("document_processing_jobs", sa.Column(
        "no_paid_providers", sa.Boolean(), nullable=False, server_default=sa.true(),
    ))
    op.create_index("ix_document_processing_jobs_queue", "document_processing_jobs",
                    ["status", "queued_at", "id"])
    op.create_index("ix_document_processing_jobs_recovery", "document_processing_jobs",
                    ["status", "started_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_document_processing_jobs_recovery", "document_processing_jobs")
    op.drop_index("ix_document_processing_jobs_queue", "document_processing_jobs")
    op.drop_column("document_processing_jobs", "no_paid_providers")
