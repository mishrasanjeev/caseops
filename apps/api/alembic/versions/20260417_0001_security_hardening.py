"""security hardening: webhook idempotency + session validity

Revision ID: 20260417_0001
Revises: 20260416_0015
Create Date: 2026-04-17 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260417_0001"
down_revision = "20260416_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_webhook_events",
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_payment_webhook_events_provider_event_id"),
        "payment_webhook_events",
        ["provider_event_id"],
        unique=False,
    )
    op.create_index(
        "uq_payment_webhook_event_idempotency",
        "payment_webhook_events",
        ["provider", "provider_event_id"],
        unique=True,
    )

    op.add_column(
        "company_memberships",
        sa.Column("sessions_valid_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company_memberships", "sessions_valid_after")
    op.drop_index(
        "uq_payment_webhook_event_idempotency",
        table_name="payment_webhook_events",
    )
    op.drop_index(
        op.f("ix_payment_webhook_events_provider_event_id"),
        table_name="payment_webhook_events",
    )
    op.drop_column("payment_webhook_events", "provider_event_id")
