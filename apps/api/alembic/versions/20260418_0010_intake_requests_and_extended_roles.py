"""matter_intake_requests + widen membership roles

Revision ID: 20260418_0010
Revises: 20260418_0009
Create Date: 2026-04-18 22:30:00

Sprint 8b BG-025 + BG-026. One migration covers both:

- ``matter_intake_requests`` — GC intake queue. Business unit files a
  request (title, category, priority, requester + description); legal
  team triages, assigns, and either promotes to a Matter (via
  ``linked_matter_id``) or rejects.
- ``membership_roles`` widening — the existing role column is already
  a ``varchar(16)`` on PostgreSQL, so adding "partner" / "paralegal"
  / "viewer" to the enum is a no-op at the storage layer. We do not
  add a CHECK constraint because the application enforces the
  MembershipRole enum on every mutating path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0010"
down_revision = "20260418_0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matter_intake_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_to_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="new"),
        sa.Column("requester_name", sa.String(length=255), nullable=False),
        sa.Column("requester_email", sa.String(length=320), nullable=True),
        sa.Column("business_unit", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("desired_by", sa.Date(), nullable=True),
        sa.Column("triage_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_matter_intake_requests_company_id",
        "matter_intake_requests",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_intake_requests_status",
        "matter_intake_requests",
        ["status"],
    )
    op.create_index(
        "ix_matter_intake_requests_submitted_by",
        "matter_intake_requests",
        ["submitted_by_membership_id"],
    )
    op.create_index(
        "ix_matter_intake_requests_assigned_to",
        "matter_intake_requests",
        ["assigned_to_membership_id"],
    )
    op.create_index(
        "ix_matter_intake_requests_linked_matter",
        "matter_intake_requests",
        ["linked_matter_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_intake_requests_linked_matter", table_name="matter_intake_requests"
    )
    op.drop_index(
        "ix_matter_intake_requests_assigned_to", table_name="matter_intake_requests"
    )
    op.drop_index(
        "ix_matter_intake_requests_submitted_by", table_name="matter_intake_requests"
    )
    op.drop_index("ix_matter_intake_requests_status", table_name="matter_intake_requests")
    op.drop_index("ix_matter_intake_requests_company_id", table_name="matter_intake_requests")
    op.drop_table("matter_intake_requests")
