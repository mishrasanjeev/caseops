"""Record authenticated self account-deletion requests, never execute deletion.

Revision ID: 20261027_0004
Revises: 20261027_0003
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; only a new empty table and its new index are
created. Existing User, company and membership rows are not scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Receipts and their identity/routing evidence
are retained. Downgrade refuses before any DDL, even when the table is empty.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261027_0004"
down_revision = "20261027_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "subject_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "submitted_from_company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_by_membership_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("confirmation_version", sa.String(24), nullable=False),
        sa.Column("submitted_realm", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject_user_id", name="uq_account_deletion_request_subject"),
        sa.ForeignKeyConstraint(
            ["submitted_by_membership_id", "submitted_from_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_account_deletion_request_routing_membership",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("status = 'received'", name="ck_account_deletion_request_received"),
        sa.CheckConstraint(
            "confirmation_version = 'account-deletion-v1'",
            name="ck_account_deletion_request_confirmation",
        ),
        sa.CheckConstraint(
            "submitted_realm IN ('tenant_web', 'native')", name="ck_account_deletion_request_realm"
        ),
    )
    op.create_index(
        "ix_account_deletion_request_routing",
        "account_deletion_requests",
        ["submitted_from_company_id", "submitted_by_membership_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Account deletion-request receipts are retained evidence; restore-forward only."
    )
