"""Persist the requester's no-paid marker on queued AI work.

Revision ID: 20261126_0201
Revises: 20261124_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL: removing
the marker would let an independent worker spend on automated-test requests.

Research answers and intelligent reviews now run in an independent Cloud Run
job, outside the request whose header carried the no-paid marker. Each queued
row records that marker so the worker can restore it before any embedding or
model call. Both columns are added with a constant default, which PostgreSQL
stores in the catalog without rewriting or scanning existing rows.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261126_0201"
down_revision = "20261124_0002"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("research_answers", "no_paid_providers"),
    ("recommendations", "review_no_paid_providers"),
)


def _add_marker(bind, table: str, column: str) -> None:
    existing = next(
        (row for row in sa.inspect(bind).get_columns(table) if row["name"] == column),
        None,
    )
    if existing is None:
        op.add_column(
            table,
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        return
    # A restarted upgrade keeps an identical column; anything else is drift.
    if not (
        isinstance(existing["type"], sa.Boolean)
        and not existing["nullable"]
        and str(existing["default"]).strip().lower()
        == ("false" if bind.dialect.name == "postgresql" else "0")
        and not existing.get("computed")
    ):
        raise RuntimeError(f"Existing {table}.{column} has a conflicting shape.")


def upgrade() -> None:
    bind = op.get_bind()
    for table, column in _COLUMNS:
        _add_marker(bind, table, column)


def downgrade() -> None:
    raise RuntimeError(
        "Queued AI work keeps its no-paid provider marker; restore-forward only."
    )
