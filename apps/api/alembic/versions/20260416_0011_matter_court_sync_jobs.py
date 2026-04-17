"""add matter court sync jobs

Revision ID: 20260416_0011
Revises: 20260416_0010
Create Date: 2026-04-16 22:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0011"
down_revision = "20260416_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_court_sync_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("sync_run_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("adapter_name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "imported_cause_list_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "imported_order_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["matter_court_sync_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_matter_court_sync_jobs_company_id",
        "matter_court_sync_jobs",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_court_sync_jobs_matter_id",
        "matter_court_sync_jobs",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_court_sync_jobs_requested_by_membership_id",
        "matter_court_sync_jobs",
        ["requested_by_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_court_sync_jobs_sync_run_id",
        "matter_court_sync_jobs",
        ["sync_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_court_sync_jobs_sync_run_id",
        table_name="matter_court_sync_jobs",
    )
    op.drop_index(
        "ix_matter_court_sync_jobs_requested_by_membership_id",
        table_name="matter_court_sync_jobs",
    )
    op.drop_index(
        "ix_matter_court_sync_jobs_matter_id",
        table_name="matter_court_sync_jobs",
    )
    op.drop_index(
        "ix_matter_court_sync_jobs_company_id",
        table_name="matter_court_sync_jobs",
    )
    op.drop_table("matter_court_sync_jobs")
