"""Widen notification event types for source-qualified workflow names.

Revision ID: 20260826_0001
Revises: 20260825_0006

MIGRATION-LOCK-RISK: acknowledged: widening VARCHAR(40) to VARCHAR(80) is a
metadata-only PostgreSQL operation, protected by a five-second lock timeout.
MIGRATION-ROLLBACK: restore-forward after an event name longer than 40
characters exists; downgrade refuses to narrow until every owner is compatible.
DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260826_0001"
down_revision = "20260825_0006"
branch_labels = None
depends_on = None

_TABLES = (
    "notification_rules",
    "in_app_notifications",
    "notification_delivery_intents",
    "notification_delivery_events",
)


def _set_lock_timeout() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def _resize(length: int, existing_length: int) -> None:
    for table_name in _TABLES:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.alter_column(
                    "event_type",
                    existing_type=sa.String(existing_length),
                    type_=sa.String(length),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                table_name,
                "event_type",
                existing_type=sa.String(existing_length),
                type_=sa.String(length),
                existing_nullable=False,
            )


def upgrade() -> None:
    _set_lock_timeout()
    _resize(80, 40)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _set_lock_timeout()
        for table_name in _TABLES:
            too_long = bind.execute(
                sa.text(
                    f"SELECT 1 FROM {table_name} "
                    "WHERE length(event_type) > 40 LIMIT 1"
                )
            ).first()
            if too_long is not None:
                raise RuntimeError(
                    f"restore-forward required: {table_name}.event_type contains "
                    "a value longer than 40 characters"
                )
    _resize(40, 80)
