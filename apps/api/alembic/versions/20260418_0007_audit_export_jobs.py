"""audit export jobs

Revision ID: 20260418_0007
Revises: 20260418_0006
Create Date: 2026-04-18 16:00:00

Adds a job-queue surface for long-running audit exports (§10.4). The
sync ``/api/admin/audit/export`` endpoint continues to stream for
small tenants; the async variant writes one row here per request, a
worker runs the export, uploads the artifact to storage, and marks
the job complete. The client polls ``GET /api/admin/audit/export/jobs/{id}``
and downloads once ``status == 'completed'``.

This table is also the slot where a Temporal / Cloud Tasks trigger
will later attach — keeping the job state in Postgres means the
worker choice (FastAPI BackgroundTasks today, Cloud Tasks + Cloud Run
Jobs or Temporal tomorrow) is a runtime config, not a schema change.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0007"
down_revision = "20260418_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_export_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "requested_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="jsonl"),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_filter", sa.String(length=120), nullable=True),
        sa.Column("row_limit", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_audit_export_jobs_company_status",
        "audit_export_jobs",
        ["company_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_export_jobs_company_status", table_name="audit_export_jobs"
    )
    op.drop_table("audit_export_jobs")
