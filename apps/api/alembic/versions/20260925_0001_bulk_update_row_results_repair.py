"""Repair bulk-update row results added after the original revision was applied.

MIGRATION-LOCK-RISK: acknowledged: adding a column takes a brief table lock.
MIGRATION-ROLLBACK: restore-forward; retained operation history must not be dropped.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260925_0001"
down_revision = "20260924_0001"

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("matter_bulk_update_operations")
    }
    if "row_results_json" not in columns:
        op.add_column(
            "matter_bulk_update_operations",
            sa.Column(
                "row_results_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
        if bind.dialect.name == "postgresql":
            op.alter_column(
                "matter_bulk_update_operations",
                "row_results_json",
                server_default=None,
            )


def downgrade() -> None:
    # The prior revision already declares this column. Keep it in both schema shapes.
    pass
