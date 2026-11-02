"""Join retained mobile and audit-provenance migration histories.

main's 20261101_0001 (IP document retirement) already used this join's
original id, so the never-released join takes 20261102_0001 and joins main's
head with the retained mobile/audit chain.

Revision ID: 20261102_0001
Revises: 20261101_0001, 20261029_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. This revision performs no DDL or data I/O;
Alembic applies both existing branches normally before recording their join.
MIGRATION-ROLLBACK: restore-forward. The historical branch guards remain
unchanged; this join does not authorize removal of their retained records.
"""

revision = "20261102_0001"
down_revision = ("20261101_0001", "20261029_0002")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError(
        "Mobile/audit migration merge is restore-forward; restore the reviewed backup."
    )
