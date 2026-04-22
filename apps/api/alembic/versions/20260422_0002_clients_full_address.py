"""Strict Ledger #4 (BUG-022) — extend clients with street address columns.

Hari's bug report said the client profile must show "address" but the
original schema only had city/state/country, so a typed door-no /
street was silently discarded. Add address_line_1, address_line_2,
postal_code (all nullable) so the create/edit forms can persist the
full mailing address and the detail page renders a complete profile.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260422_0002"
down_revision = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(
            sa.Column("address_line_1", sa.String(length=255), nullable=True),
        )
        batch.add_column(
            sa.Column("address_line_2", sa.String(length=255), nullable=True),
        )
        batch.add_column(
            sa.Column("postal_code", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("postal_code")
        batch.drop_column("address_line_2")
        batch.drop_column("address_line_1")
