"""Join retained mobile and audit-provenance migration histories.

Revision ID: 20261101_0001
Revises: 20261028_0002, 20261029_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. This revision performs no DDL or data I/O;
Alembic applies both existing branches normally before recording their join.
MIGRATION-ROLLBACK: restore-forward. The historical branch guards remain
unchanged; this join does not authorize removal of their retained records.
"""

revision = "20261101_0001"
down_revision = ("20261028_0002", "20261029_0002")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError(
        "Mobile/audit migration merge is restore-forward; restore the reviewed backup."
    )
