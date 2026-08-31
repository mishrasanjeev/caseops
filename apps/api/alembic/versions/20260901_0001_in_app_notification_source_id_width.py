"""Widen in-app notification source identities to match delivery intents.

Revision ID: 20260901_0001
Revises: 20260831_0002

Notification delivery intents already admit 120-character source identities.
The in-app delivery projection copied those values into a VARCHAR(36) column,
causing deterministic reminder jobs to fail after locking their Matter rows.

MIGRATION-LOCK-RISK: acknowledged: widening VARCHAR(36) to VARCHAR(120) is a
metadata-only PostgreSQL operation, protected by a five-second lock timeout.
MIGRATION-ROLLBACK: restore-forward after a source identity longer than 36
characters exists; downgrade refuses to truncate persisted notification data.
DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260901_0001"
down_revision = "20260831_0002"
branch_labels = None
depends_on = None

TABLE_NAME = "in_app_notifications"
OLD_LENGTH = 36
NEW_LENGTH = 120


def _set_lock_timeout() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def _resize(*, length: int, existing_length: int) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.alter_column(
                "source_id",
                existing_type=sa.String(existing_length),
                type_=sa.String(length),
                existing_nullable=False,
            )
        return
    op.alter_column(
        TABLE_NAME,
        "source_id",
        existing_type=sa.String(existing_length),
        type_=sa.String(length),
        existing_nullable=False,
    )


def upgrade() -> None:
    _set_lock_timeout()
    _resize(length=NEW_LENGTH, existing_length=OLD_LENGTH)


def downgrade() -> None:
    _set_lock_timeout()
    bind = op.get_bind()
    too_long = bind.execute(
        sa.text(f"SELECT 1 FROM {TABLE_NAME} WHERE length(source_id) > {OLD_LENGTH} LIMIT 1")
    ).first()
    if too_long is not None:
        raise RuntimeError(
            "restore-forward required: in_app_notifications.source_id contains "
            "a value longer than 36 characters"
        )
    _resize(length=OLD_LENGTH, existing_length=NEW_LENGTH)
