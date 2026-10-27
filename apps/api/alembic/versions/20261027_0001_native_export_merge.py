"""Join retained native-auth and portfolio-worker migration histories.

Revision ID: 20261027_0001
Revises: 20261024_0002, 20261026_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. This revision performs no DDL or data I/O;
Alembic applies each existing branch normally before recording their join.
MIGRATION-ROLLBACK: restore-forward. Both historical branch guards remain
unchanged; this merge does not authorize deletion of their retained history.
"""

revision = "20261027_0001"
down_revision = ("20261024_0002", "20261026_0001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
