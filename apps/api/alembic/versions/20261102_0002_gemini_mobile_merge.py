"""Join main's Gemini fallback spend cap with the retained mobile/audit join.

main added 20261101_0002 (Gemini fallback spend cap) on top of 20261101_0001
while this branch joined 20261101_0001 with the mobile/audit chain as
20261102_0001. This no-op revision joins those two heads.

Revision ID: 20261102_0002
Revises: 20261102_0001, 20261101_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. This revision performs no DDL or data I/O;
Alembic applies both existing branches normally before recording their join.
MIGRATION-ROLLBACK: restore-forward. The joined branches keep their own
guards; this join does not authorize removal of their retained records.
"""

revision = "20261102_0002"
down_revision = ("20261102_0001", "20261101_0002")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError(
        "Gemini/mobile migration merge is restore-forward; restore the reviewed backup."
    )
