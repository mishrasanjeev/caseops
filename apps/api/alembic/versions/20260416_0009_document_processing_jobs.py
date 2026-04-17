"""add document processing jobs

Revision ID: 20260416_0009
Revises: 20260416_0008
Create Date: 2026-04-16 19:10:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0009"
down_revision = "20260416_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_processing_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("attachment_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "processed_char_count",
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
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_processing_jobs_company_id",
        "document_processing_jobs",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_processing_jobs_requested_by_membership_id",
        "document_processing_jobs",
        ["requested_by_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_processing_jobs_target_type",
        "document_processing_jobs",
        ["target_type"],
        unique=False,
    )
    op.create_index(
        "ix_document_processing_jobs_attachment_id",
        "document_processing_jobs",
        ["attachment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_processing_jobs_attachment_id", table_name="document_processing_jobs")
    op.drop_index("ix_document_processing_jobs_target_type", table_name="document_processing_jobs")
    op.drop_index(
        "ix_document_processing_jobs_requested_by_membership_id",
        table_name="document_processing_jobs",
    )
    op.drop_index("ix_document_processing_jobs_company_id", table_name="document_processing_jobs")
    op.drop_table("document_processing_jobs")
