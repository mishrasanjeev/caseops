"""Complete IP evidence, coverage, rights, and cost control tails.

Revision ID: 20260801_0006
Revises: 20260801_0005
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260801_0006"
down_revision = "20260801_0005"
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
        "ip_evidence_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("evidence_kind", sa.String(40), nullable=False),
        sa.Column("suggested_link_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="needs_review"),
        sa.Column("accepted_effect", sa.String(80), nullable=True),
        sa.Column("duplicate_of_candidate_id", sa.String(36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("reviewed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _company_docket_fk("fk_ip_evidence_candidate_docket_company"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_evidence_candidate_reviewer_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_candidate_id"],
            ["ip_evidence_candidates.id"],
            name="fk_ip_evidence_candidate_duplicate",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "company_id",
            "docket_id",
            "source_type",
            "source_id",
            name="uq_ip_evidence_candidate_source",
        ),
    )
    op.create_index(
        "ix_ip_evidence_candidates_company_status",
        "ip_evidence_candidates",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_ip_evidence_candidates_docket_id",
        "ip_evidence_candidates",
        ["docket_id"],
    )
    op.create_index(
        "ix_ip_evidence_candidates_source_fingerprint",
        "ip_evidence_candidates",
        ["source_fingerprint"],
    )
    op.create_index(
        "ix_ip_evidence_candidates_duplicate_of_candidate_id",
        "ip_evidence_candidates",
        ["duplicate_of_candidate_id"],
    )
    op.create_index(
        "ix_ip_evidence_candidates_reviewed_by_membership_id",
        "ip_evidence_candidates",
        ["reviewed_by_membership_id"],
    )

    with op.batch_alter_table("ip_deadline_coverages") as batch_op:
        batch_op.add_column(
            sa.Column("reassignment_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    op.create_table(
        "ip_related_right_obligations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("title_interest_id", sa.String(36), nullable=True),
        sa.Column("obligation_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("owner_membership_id", sa.String(36), nullable=False),
        sa.Column("matter_deadline_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("completion_evidence_reference", sa.String(500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        _company_docket_fk("fk_ip_related_obligation_docket_company"),
        sa.ForeignKeyConstraint(
            ["title_interest_id"],
            ["ip_title_interests.id"],
            name="fk_ip_related_obligation_title_interest",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_related_obligation_owner_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["matter_deadline_id"],
            ["matter_deadlines.id"],
            name="fk_ip_related_obligation_deadline",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_ip_related_obligations_company_status_due",
        "ip_related_right_obligations",
        ["company_id", "status", "due_on"],
    )
    for column in (
        "docket_id",
        "title_interest_id",
        "due_on",
        "owner_membership_id",
        "matter_deadline_id",
    ):
        op.create_index(
            f"ix_ip_related_right_obligations_{column}",
            "ip_related_right_obligations",
            [column],
        )

    with op.batch_alter_table("ip_cost_items") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reconciliation_status",
                sa.String(24),
                nullable=False,
                server_default="unlinked",
            )
        )
        batch_op.add_column(sa.Column("canonical_amount_minor", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("reconciliation_difference_minor", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("reconciled_by_membership_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_ip_cost_item_reconciler",
            "company_memberships",
            ["reconciled_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_ip_cost_items_reconciled_by_membership_id",
            ["reconciled_by_membership_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("ip_cost_items") as batch_op:
        batch_op.drop_index("ix_ip_cost_items_reconciled_by_membership_id")
        batch_op.drop_constraint("fk_ip_cost_item_reconciler", type_="foreignkey")
        batch_op.drop_column("reconciled_by_membership_id")
        batch_op.drop_column("reconciled_at")
        batch_op.drop_column("reconciliation_difference_minor")
        batch_op.drop_column("canonical_amount_minor")
        batch_op.drop_column("reconciliation_status")

    for column in (
        "matter_deadline_id",
        "owner_membership_id",
        "due_on",
        "title_interest_id",
        "docket_id",
    ):
        op.drop_index(
            f"ix_ip_related_right_obligations_{column}",
            table_name="ip_related_right_obligations",
        )
    op.drop_index(
        "ix_ip_related_obligations_company_status_due",
        table_name="ip_related_right_obligations",
    )
    op.drop_table("ip_related_right_obligations")

    with op.batch_alter_table("ip_deadline_coverages") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("reassignment_version")

    op.drop_index(
        "ix_ip_evidence_candidates_reviewed_by_membership_id",
        table_name="ip_evidence_candidates",
    )
    op.drop_index(
        "ix_ip_evidence_candidates_duplicate_of_candidate_id",
        table_name="ip_evidence_candidates",
    )
    op.drop_index(
        "ix_ip_evidence_candidates_source_fingerprint",
        table_name="ip_evidence_candidates",
    )
    op.drop_index(
        "ix_ip_evidence_candidates_docket_id",
        table_name="ip_evidence_candidates",
    )
    op.drop_index(
        "ix_ip_evidence_candidates_company_status",
        table_name="ip_evidence_candidates",
    )
    op.drop_table("ip_evidence_candidates")
