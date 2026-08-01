"""Add IP notice, deadline, incident, title, and cost links.

Revision ID: 20260801_0004
Revises: 20260801_0003
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260801_0004"
down_revision = "20260801_0003"
branch_labels = None
depends_on = None


def _company_docket_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["docket_id", "company_id"],
        ["ip_docket_records.id", "ip_docket_records.company_id"],
        name=name,
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "company_notice_ip_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("notice_id", sa.String(36), nullable=False),
        sa.Column("link_kind", sa.String(40), nullable=False),
        sa.Column("accepted_effect", sa.String(80), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _company_docket_fk("fk_notice_ip_link_docket_company"),
        sa.ForeignKeyConstraint(
            ["notice_id", "company_id"],
            ["company_notices.id", "company_notices.company_id"],
            name="fk_notice_ip_link_notice_company",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("notice_id", "docket_id", name="uq_notice_ip_link"),
    )
    op.create_index("ix_notice_ip_links_company", "company_notice_ip_links", ["company_id"])
    op.create_index(
        "ix_company_notice_ip_links_docket_id", "company_notice_ip_links", ["docket_id"]
    )

    op.create_table(
        "ip_deadline_coverages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("matter_deadline_id", sa.String(36), nullable=False),
        sa.Column("responsible_membership_id", sa.String(36), nullable=False),
        sa.Column("backup_membership_id", sa.String(36), nullable=True),
        sa.Column("coverage_status", sa.String(24), nullable=False, server_default="accepted"),
        sa.Column(
            "calendar_projection_status", sa.String(24), nullable=False, server_default="pending"
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _company_docket_fk("fk_ip_deadline_coverage_docket_company"),
        sa.ForeignKeyConstraint(
            ["matter_deadline_id"],
            ["matter_deadlines.id"],
            name="fk_ip_deadline_coverage_deadline",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("docket_id", "matter_deadline_id", name="uq_ip_deadline_coverage"),
    )
    op.create_index("ix_ip_deadline_coverage_company", "ip_deadline_coverages", ["company_id"])
    op.create_index(
        "ix_ip_deadline_coverages_matter_deadline_id",
        "ip_deadline_coverages",
        ["matter_deadline_id"],
    )

    op.create_table(
        "ip_deadline_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("matter_deadline_id", sa.String(36), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("containment", sa.Text(), nullable=True),
        sa.Column("correction_deadline_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("corrective_action", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_membership_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _company_docket_fk("fk_ip_deadline_incident_docket_company"),
        sa.ForeignKeyConstraint(
            ["matter_deadline_id"], ["matter_deadlines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["correction_deadline_id"], ["matter_deadlines.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_ip_deadline_incidents_company_status", "ip_deadline_incidents", ["company_id", "status"]
    )
    op.create_index(
        "ix_ip_deadline_incidents_docket_id", "ip_deadline_incidents", ["docket_id"]
    )
    op.create_index(
        "ix_ip_deadline_incidents_matter_deadline_id",
        "ip_deadline_incidents",
        ["matter_deadline_id"],
    )
    op.create_index(
        "ix_ip_deadline_incidents_correction_deadline_id",
        "ip_deadline_incidents",
        ["correction_deadline_id"],
    )

    op.create_table(
        "ip_title_interests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("interest_type", sa.String(32), nullable=False),
        sa.Column("party_name", sa.String(255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("related_docket_id", sa.String(36), nullable=True),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("recordal_status", sa.String(32), nullable=False, server_default="not_required"),
        sa.Column("conflict_flags_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _company_docket_fk("fk_ip_title_interest_docket_company"),
    )
    op.create_index(
        "ix_ip_title_interests_company_docket", "ip_title_interests", ["company_id", "docket_id"]
    )
    op.create_index("ix_ip_title_interests_docket_id", "ip_title_interests", ["docket_id"])

    op.create_table(
        "ip_cost_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("matter_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("billing_link_type", sa.String(40), nullable=True),
        sa.Column("billing_link_id", sa.String(64), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _company_docket_fk("fk_ip_cost_item_docket_company"),
        sa.ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ip_cost_item_matter_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_ip_cost_item_amount_nonnegative"),
        sa.CheckConstraint("length(currency) = 3", name="ck_ip_cost_item_currency"),
    )
    op.create_index("ix_ip_cost_items_company_docket", "ip_cost_items", ["company_id", "docket_id"])
    op.create_index("ix_ip_cost_items_docket_id", "ip_cost_items", ["docket_id"])
    op.create_index("ix_ip_cost_items_matter_id", "ip_cost_items", ["matter_id"])


def downgrade() -> None:
    op.drop_index("ix_ip_cost_items_matter_id", table_name="ip_cost_items")
    op.drop_index("ix_ip_cost_items_docket_id", table_name="ip_cost_items")
    op.drop_index("ix_ip_cost_items_company_docket", table_name="ip_cost_items")
    op.drop_table("ip_cost_items")
    op.drop_index("ix_ip_title_interests_docket_id", table_name="ip_title_interests")
    op.drop_index("ix_ip_title_interests_company_docket", table_name="ip_title_interests")
    op.drop_table("ip_title_interests")
    op.drop_index(
        "ix_ip_deadline_incidents_correction_deadline_id",
        table_name="ip_deadline_incidents",
    )
    op.drop_index(
        "ix_ip_deadline_incidents_matter_deadline_id",
        table_name="ip_deadline_incidents",
    )
    op.drop_index("ix_ip_deadline_incidents_docket_id", table_name="ip_deadline_incidents")
    op.drop_index("ix_ip_deadline_incidents_company_status", table_name="ip_deadline_incidents")
    op.drop_table("ip_deadline_incidents")
    op.drop_index(
        "ix_ip_deadline_coverages_matter_deadline_id",
        table_name="ip_deadline_coverages",
    )
    op.drop_index("ix_ip_deadline_coverage_company", table_name="ip_deadline_coverages")
    op.drop_table("ip_deadline_coverages")
    op.drop_index("ix_company_notice_ip_links_docket_id", table_name="company_notice_ip_links")
    op.drop_index("ix_notice_ip_links_company", table_name="company_notice_ip_links")
    op.drop_table("company_notice_ip_links")
