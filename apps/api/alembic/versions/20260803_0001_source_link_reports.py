"""Add tenant source-link defect and health-check requests.

Revision ID: 20260803_0001
Revises: 20260802_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260803_0001"
down_revision = "20260802_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_link_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("reported_by_membership_id", sa.String(36), nullable=True),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False),
        sa.Column("origin_surface", sa.String(64), nullable=False),
        sa.Column("issue_type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("source_reference_sha256", sa.String(64), nullable=True),
        sa.Column("destination_class", sa.String(40), nullable=False),
        sa.Column("source_state", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "target_type in ('authority_document', 'statute_section', 'judge_appointment')",
            name="ck_source_link_reports_target_type",
        ),
        sa.CheckConstraint(
            "issue_type in ('broken', 'wrong_document', 'access_denied', 'stale', 'other')",
            name="ck_source_link_reports_issue_type",
        ),
        sa.CheckConstraint(
            "status in ('queued', 'investigating', 'resolved', 'dismissed')",
            name="ck_source_link_reports_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reported_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_source_link_reports_company_id",
        "source_link_reports",
        ["company_id"],
    )
    op.create_index(
        "ix_source_link_reports_reported_by_membership_id",
        "source_link_reports",
        ["reported_by_membership_id"],
    )
    op.create_index(
        "ix_source_link_reports_issue_type",
        "source_link_reports",
        ["issue_type"],
    )
    op.create_index(
        "ix_source_link_reports_status",
        "source_link_reports",
        ["status"],
    )
    op.create_index(
        "ix_source_link_reports_target_created",
        "source_link_reports",
        ["target_type", "target_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_link_reports_target_created", table_name="source_link_reports")
    op.drop_index("ix_source_link_reports_status", table_name="source_link_reports")
    op.drop_index("ix_source_link_reports_issue_type", table_name="source_link_reports")
    op.drop_index(
        "ix_source_link_reports_reported_by_membership_id",
        table_name="source_link_reports",
    )
    op.drop_index("ix_source_link_reports_company_id", table_name="source_link_reports")
    op.drop_table("source_link_reports")
