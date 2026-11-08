"""Record versioned native workspace conduct acceptance.

Revision ID: 20261108_0001
Revises: 20261106_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One empty receipt table references the
existing tenant membership key. No existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL because
the acceptance receipts are retained policy evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261108_0001"
down_revision = "20261106_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "workspace_conduct_acceptances",
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("version", sa.String(10), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "membership_id", "version"),
        sa.ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_workspace_conduct_acceptance_membership",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Workspace conduct acceptance receipts are retained evidence; restore-forward only."
    )
