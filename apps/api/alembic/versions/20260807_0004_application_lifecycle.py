"""Add fail-closed trademark application lifecycle fields.

Revision ID: 20260807_0004
Revises: 20260807_0003
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260807_0004"
down_revision = "20260807_0003"
branch_labels = None
depends_on = None

TERMINAL_PHASES = "'refused', 'abandoned', 'withdrawn', 'closed', 'transferred'"


def upgrade() -> None:
    with op.batch_alter_table("trademark_applications") as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="0")
        )

    op.execute(
        sa.text(
            "UPDATE trademark_applications SET is_active = false "
            f"WHERE filing_phase IN ({TERMINAL_PHASES})"
        )
    )

    with op.batch_alter_table("trademark_applications") as batch_op:
        batch_op.create_check_constraint(
            "ck_tm_application_phase_active_consistent",
            f"(filing_phase IN ({TERMINAL_PHASES}) AND is_active = false) OR "
            f"(filing_phase NOT IN ({TERMINAL_PHASES}) AND is_active = true)",
        )
        batch_op.create_check_constraint(
            "ck_tm_application_lifecycle_version_nonnegative",
            "lifecycle_version >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("trademark_applications") as batch_op:
        batch_op.drop_constraint(
            "ck_tm_application_lifecycle_version_nonnegative", type_="check"
        )
        batch_op.drop_constraint(
            "ck_tm_application_phase_active_consistent", type_="check"
        )
        batch_op.drop_column("lifecycle_version")
        batch_op.drop_column("is_active")
