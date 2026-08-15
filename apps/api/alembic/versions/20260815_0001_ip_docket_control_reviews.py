"""IPLF-039C rebuild: signed-off daily docket control reviews.

Additive and unseeded. Gives the existing control report a durable review
record so CAL-OPS-09's "produce and sign off" can hold, and so an incomplete or
export-failed report can be refused rather than silently accepted.

Revision ID: 20260815_0001
Revises: 20260814_0002

DATA-GOVERNANCE-MAP: updated
``ip_docket_control_reviews`` is registered as
``tenant_restricted_legal_content``. The stored filters, freshness block and
mandatory exception list reference IP records by identifier and describe the
state of a firm's docket on a given day, so the review is disclosive of
workload even though it stores no record titles. It is tenant-scoped through
``company_id`` under the fail-closed ``registry_fail_closed`` handler; a signed
review is immutable evidence and has no approved runtime deletion path. The
canonical snapshot retains the query/schema versions, timezone, hidden-count
policy, included accessible record IDs/hashes, report output and exceptions;
``manifest_sha256`` binds those bytes so later docket changes cannot rewrite
what was signed. Signer and creator references are company-matched at the
database boundary while their existing attribution-loss behavior is retained.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0001"
down_revision = "20260814_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    op.create_table(
        "ip_docket_control_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("freshness_json", sa.JSON(), nullable=False),
        sa.Column(
            "completeness_status", sa.String(length=16), nullable=False, server_default="complete"
        ),
        sa.Column("incompleteness_reasons_json", sa.JSON(), nullable=False),
        sa.Column("mandatory_exception_ids_json", sa.JSON(), nullable=False),
        sa.Column("query_version", sa.String(length=64), nullable=False),
        sa.Column(
            "snapshot_schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("report_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "export_status", sa.String(length=16), nullable=False, server_default="not_requested"
        ),
        sa.Column("export_error_redacted", sa.String(length=500), nullable=True),
        sa.Column("signed_off_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("signer_label_snapshot", sa.String(length=255), nullable=True),
        sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["signed_off_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["signed_off_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_review_signer_company",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_review_creator_company",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "completeness_status IN ('complete', 'incomplete')",
            name="ck_ip_control_review_completeness",
        ),
        sa.CheckConstraint(
            "export_status IN ('not_requested', 'generated', 'failed')",
            name="ck_ip_control_review_export_status",
        ),
        # A signed-off review must be complete and must not carry a failed
        # export: the database refuses the state the service also refuses.
        sa.CheckConstraint(
            "signed_off_at IS NULL OR "
            "(completeness_status = 'complete' AND export_status <> 'failed')",
            name="ck_ip_control_review_signoff_requires_clean",
        ),
        sa.CheckConstraint(
            "signed_off_at IS NULL OR signed_off_by_membership_id IS NOT NULL",
            name="ck_ip_control_review_signoff_has_signer",
        ),
    )
    op.create_index(
        "ix_ip_docket_control_reviews_company_id", "ip_docket_control_reviews", ["company_id"]
    )
    op.create_index(
        "ix_ip_docket_control_reviews_signed_off_by_membership_id",
        "ip_docket_control_reviews",
        ["signed_off_by_membership_id"],
    )
    op.create_index(
        "ix_ip_docket_control_reviews_created_by_membership_id",
        "ip_docket_control_reviews",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_ip_docket_control_reviews_company_generated",
        "ip_docket_control_reviews",
        ["company_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ip_docket_control_reviews_company_generated", table_name="ip_docket_control_reviews"
    )
    op.drop_index(
        "ix_ip_docket_control_reviews_created_by_membership_id",
        table_name="ip_docket_control_reviews",
    )
    op.drop_index(
        "ix_ip_docket_control_reviews_signed_off_by_membership_id",
        table_name="ip_docket_control_reviews",
    )
    op.drop_index(
        "ix_ip_docket_control_reviews_company_id", table_name="ip_docket_control_reviews"
    )
    op.drop_table("ip_docket_control_reviews")
