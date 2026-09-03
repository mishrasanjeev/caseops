"""Add configured aliases to the shared forum catalog.

Revision ID: 20260903_0001
Revises: 20260901_0001

DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260903_0001"
down_revision = "20260901_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REPORTED_DWARKA_ALIAS = "Dwarka_SWCF"
_DWARKA_ENTRY_ID = "consumer:dcdrc:delhi:dwarka"


def upgrade() -> None:
    with op.batch_alter_table("forum_catalog_entries") as batch:
        batch.add_column(
            sa.Column(
                "aliases_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    table = sa.table(
        "forum_catalog_entries",
        sa.column("id", sa.String()),
        sa.column("aliases_json", sa.JSON()),
    )
    op.get_bind().execute(
        table.update()
        .where(table.c.id == _DWARKA_ENTRY_ID)
        .values(aliases_json=[_REPORTED_DWARKA_ALIAS])
    )


def downgrade() -> None:
    with op.batch_alter_table("forum_catalog_entries") as batch:
        batch.drop_column("aliases_json")
