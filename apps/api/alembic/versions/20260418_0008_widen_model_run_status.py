"""widen model_runs.status to varchar(64)

Revision ID: 20260418_0008
Revises: 20260418_0007
Create Date: 2026-04-18 18:00:00

The old ``VARCHAR(24)`` ceiling overflowed when Pass 1 added the
``rejected_no_verified_citations`` label (30 chars). SQLite tests
accept it silently; Postgres raises ``StringDataRightTruncation``.
Widening to 64 gives plenty of headroom for future descriptive
statuses without recurring schema churn.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0008"
down_revision = "20260418_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("model_runs") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.String(length=24),
            type_=sa.String(length=64),
            existing_nullable=False,
            existing_server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("model_runs") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.String(length=64),
            type_=sa.String(length=24),
            existing_nullable=False,
        )
