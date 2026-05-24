"""ADP-19 email invitation calendar candidates.

Revision ID: 20260524_0005
Revises: 20260524_0004
Create Date: 2026-05-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260524_0005"
down_revision = "20260524_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_calendar_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "communication_id",
            sa.String(length=36),
            sa.ForeignKey("communications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_key", sa.String(length=180), nullable=True),
        sa.Column("normalized_key", sa.String(length=96), nullable=False),
        sa.Column("detected_title", sa.String(length=255), nullable=False),
        sa.Column("detected_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_location", sa.String(length=255), nullable=True),
        sa.Column("source_preview", sa.String(length=280), nullable=True),
        sa.Column("confidence_band", sa.String(length=24), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="needs_review",
        ),
        sa.Column(
            "duplicate_of_candidate_id",
            sa.String(length=36),
            sa.ForeignKey("email_calendar_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_deadline_id",
            sa.String(length=36),
            sa.ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "company_id",
            "matter_id",
            "communication_id",
            "normalized_key",
            name="uq_email_calendar_candidate_source_key",
        ),
    )
    op.create_index(
        "ix_email_calendar_candidates_company_id",
        "email_calendar_candidates",
        ["company_id"],
    )
    op.create_index(
        "ix_email_calendar_candidates_matter_id",
        "email_calendar_candidates",
        ["matter_id"],
    )
    op.create_index(
        "ix_email_calendar_candidates_communication_id",
        "email_calendar_candidates",
        ["communication_id"],
    )
    op.create_index(
        "ix_email_calendar_candidates_detected_start_at",
        "email_calendar_candidates",
        ["detected_start_at"],
    )
    op.create_index(
        "ix_email_calendar_candidates_status",
        "email_calendar_candidates",
        ["status"],
    )
    op.create_index(
        "ix_email_calendar_candidates_created_deadline_id",
        "email_calendar_candidates",
        ["created_deadline_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_calendar_candidates_created_deadline_id",
        table_name="email_calendar_candidates",
    )
    op.drop_index(
        "ix_email_calendar_candidates_status",
        table_name="email_calendar_candidates",
    )
    op.drop_index(
        "ix_email_calendar_candidates_detected_start_at",
        table_name="email_calendar_candidates",
    )
    op.drop_index(
        "ix_email_calendar_candidates_communication_id",
        table_name="email_calendar_candidates",
    )
    op.drop_index(
        "ix_email_calendar_candidates_matter_id",
        table_name="email_calendar_candidates",
    )
    op.drop_index(
        "ix_email_calendar_candidates_company_id",
        table_name="email_calendar_candidates",
    )
    op.drop_table("email_calendar_candidates")
