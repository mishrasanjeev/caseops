"""Add company-scoped IP docket anchors and trademark form versions.

Revision ID: 20260801_0003
Revises: 20260801_0002
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260801_0003"
down_revision = "20260801_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ip_docket_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("matter_id", sa.String(36), nullable=True),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("primary_identifier", sa.String(120), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "archived_by_matter_disposal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ip_docket_matter_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_creator_company",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_docket_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "primary_identifier",
            name="uq_ip_docket_company_identifier",
        ),
    )
    op.create_index("ix_ip_docket_company_status", "ip_docket_records", ["company_id", "status"])
    op.create_index("ix_ip_docket_matter", "ip_docket_records", ["matter_id"])
    op.create_index(
        "ix_ip_docket_records_created_by_membership_id",
        "ip_docket_records",
        ["created_by_membership_id"],
    )

    op.create_table(
        "ip_trademark_particular_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("form_key", sa.String(80), nullable=False),
        sa.Column("form_version", sa.String(40), nullable=False),
        sa.Column("mark_kind", sa.String(40), nullable=False),
        sa.Column("representation_json", sa.JSON(), nullable=False),
        sa.Column("classes_json", sa.JSON(), nullable=False),
        sa.Column("use_priority_json", sa.JSON(), nullable=True),
        sa.Column("parties_json", sa.JSON(), nullable=False),
        sa.Column("agent_json", sa.JSON(), nullable=True),
        sa.Column("filing_manifest_json", sa.JSON(), nullable=False),
        sa.Column("readiness_status", sa.String(24), nullable=False),
        sa.Column("readiness_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_tm_version_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_tm_version_creator_company",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("docket_id", "version", name="uq_ip_tm_docket_version"),
    )
    op.create_index(
        "ix_ip_tm_versions_company_docket",
        "ip_trademark_particular_versions",
        ["company_id", "docket_id"],
    )
    op.create_index(
        "ix_ip_trademark_particular_versions_created_by_membership_id",
        "ip_trademark_particular_versions",
        ["created_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ip_trademark_particular_versions_created_by_membership_id",
        table_name="ip_trademark_particular_versions",
    )
    op.drop_index("ix_ip_tm_versions_company_docket", table_name="ip_trademark_particular_versions")
    op.drop_table("ip_trademark_particular_versions")
    op.drop_index(
        "ix_ip_docket_records_created_by_membership_id",
        table_name="ip_docket_records",
    )
    op.drop_index("ix_ip_docket_matter", table_name="ip_docket_records")
    op.drop_index("ix_ip_docket_company_status", table_name="ip_docket_records")
    op.drop_table("ip_docket_records")
