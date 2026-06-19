"""SendGrid webhook completion (BUG-038): tenant-scoped email suppression.

Adds the ``email_suppressions`` table populated by SendGrid event
webhooks (bounce / dropped / spam_report / unsubscribe /
group_unsubscribe) and consulted before every outbound matter
email or hearing-reminder send. Auth-flow mailers (account setup,
password reset, portal) intentionally bypass it.

Revision ID: 20260509_0001
Revises: 20260507_0002
Create Date: 2026-05-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260509_0001"
down_revision = "20260507_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "email_suppressions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "recipient_email",
            sa.String(length=320),
            nullable=False,
            index=True,
        ),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("source_message_id", sa.String(length=120), nullable=True),
        sa.Column(
            "last_event_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Inline UniqueConstraint — SQLite does not support ALTER TABLE
        # ADD CONSTRAINT, so declaring it on the create_table call is
        # required for the dev/test SQLite path. Postgres handles
        # either form identically.
        sa.UniqueConstraint(
            "company_id",
            "recipient_email",
            name="uq_email_suppressions_tenant_address",
        ),
    )


def downgrade() -> None:
    op.drop_table("email_suppressions")
