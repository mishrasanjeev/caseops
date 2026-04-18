"""unified audit_events table (§5.4)

Revision ID: 20260418_0001
Revises: 20260417_0005
Create Date: 2026-04-18 06:00:00

Adds `audit_events`, the system-wide append-only audit trail. Every
tenant-affecting write goes through `services/audit.record_audit()` and
lands one row here. Existing scattered audit surfaces
(MatterActivity, ContractActivity, MatterInvoicePaymentAttempt) stay
for feature-specific UX; this table is the enterprise / compliance
layer that backs `/api/admin/audit/export`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0001"
down_revision = "20260417_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # actor_type discriminates human vs service vs agent. Kept as a
        # plain string so future actor shapes (external webhooks, etc.)
        # don't need a migration.
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column(
            "actor_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action", sa.String(length=80), nullable=False, index=True),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=True, index=True),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Most common query: give me this tenant's events in a time window.
    op.create_index(
        "ix_audit_events_company_created",
        "audit_events",
        ["company_id", "created_at"],
    )
    # Filter by action within a tenant (export UI + admin investigations).
    op.create_index(
        "ix_audit_events_company_action",
        "audit_events",
        ["company_id", "action"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_company_action", table_name="audit_events")
    op.drop_index("ix_audit_events_company_created", table_name="audit_events")
    op.drop_table("audit_events")
