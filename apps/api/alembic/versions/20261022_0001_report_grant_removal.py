"""Retain report-grant removal independently of shared User identity.

Revision ID: 20261022_0001
Revises: 20261021_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; one nullable column under canonical lock and
statement budgets, without scanning or rewriting existing grants or identities.
MIGRATION-ROLLBACK: roll-forward or restore only; removal and audit evidence
must not be discarded by a downgrade, including on nontransactional SQLite DDL.
"""
import sqlalchemy as sa

from alembic import op

revision = "20261022_0001"
down_revision = "20261021_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "platform_report_admins", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    raise RuntimeError("Report-grant removal is retained access history; roll-forward or restore.")
