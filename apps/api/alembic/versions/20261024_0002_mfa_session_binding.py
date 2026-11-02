"""Bind new MFA proofs to their authenticated source session for native handoff.

DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: one nullable additive column, no historical-row rewrite.
MIGRATION-ROLLBACK: roll-forward or restore only; native handoff cannot fall back
to historical membership-wide proof after a source-session binding is issued.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261024_0002"
down_revision = "20261024_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_mfa_step_ups", sa.Column("source_token_issued_at", sa.Float(), nullable=True)
    )


def downgrade():
    raise RuntimeError("MFA source-session binding is security evidence; roll-forward or restore.")
