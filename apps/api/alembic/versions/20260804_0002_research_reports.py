"""Add immutable tenant research report snapshots.

Revision ID: 20260804_0002
Revises: 20260804_0001

This additive revision follows the IPLF-004B source-reporting migration so the
release graph remains linear.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260804_0002"
down_revision = "20260804_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authority_research_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("query", sa.String(600), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("criteria_json", sa.JSON(), nullable=False),
        sa.Column("result_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("analysis_version", sa.String(80), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_authority_research_reports_company_created",
        "authority_research_reports",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_authority_research_reports_company_id",
        "authority_research_reports",
        ["company_id"],
    )
    op.create_index(
        "ix_authority_research_reports_created_by_membership_id",
        "authority_research_reports",
        ["created_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_research_reports_created_by_membership_id",
        table_name="authority_research_reports",
    )
    op.drop_index(
        "ix_authority_research_reports_company_id",
        table_name="authority_research_reports",
    )
    op.drop_index(
        "ix_authority_research_reports_company_created",
        table_name="authority_research_reports",
    )
    op.drop_table("authority_research_reports")
