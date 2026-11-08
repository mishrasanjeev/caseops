"""Retain private workspace conduct reports and intake routing.

Revision ID: 20261108_0002
Revises: 20261108_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Only a new, empty report table and its
indexes are created. No existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL because
reports are retained conduct evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261108_0002"
down_revision = "20261108_0001"
branch_labels = None
depends_on = None

TABLE = "workspace_conduct_reports"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("reporter_membership_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("target_kind", sa.String(8), nullable=False),
        sa.Column("target_membership_id", sa.String(36), nullable=True),
        sa.Column("source_kind", sa.String(8), nullable=False),
        sa.Column("source_matter_id", sa.String(36), nullable=False),
        sa.Column("source_item_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("routing", sa.String(9), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "reporter_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_workspace_conduct_reporter",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "target_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_workspace_conduct_report_target",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "company_id", "reporter_membership_id", "operation_id",
            name="uq_workspace_conduct_report_operation",
        ),
        sa.CheckConstraint(
            "(target_kind IN ('note', 'file') AND target_kind = source_kind) OR "
            "(target_kind = 'user' AND target_membership_id IS NOT NULL "
            "AND source_kind IN ('note', 'file'))",
            name="ck_workspace_conduct_report_target",
        ),
        sa.CheckConstraint(
            "routing IN ('workspace', 'publisher')",
            name="ck_workspace_conduct_report_routing",
        ),
        sa.CheckConstraint(
            "reason IN ('harassment_threats', 'exploitation', 'impersonation', "
            "'unlawful_content', 'spam_malware_fraud', 'unauthorized_disclosure', 'other')",
            name="ck_workspace_conduct_report_reason",
        ),
    )
    op.create_index(
        "ix_workspace_conduct_report_target", TABLE, ["company_id", "target_membership_id"],
    )
    op.create_index(
        "ix_workspace_conduct_report_workspace", TABLE,
        ["company_id", "routing", "received_at", "id"],
    )
    op.create_index(
        "ix_workspace_conduct_report_publisher", TABLE, ["routing", "received_at", "id"],
    )


def downgrade() -> None:
    raise RuntimeError("Workspace conduct reports are retained evidence; restore-forward only.")
