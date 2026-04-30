"""matter_conflict_checks — pre-engagement conflict-of-interest gate (PG-001).

Single table per `MatterConflictCheck` model. Stores opposing/related party
names, candidate matches found during the scan (clients, matters, contacts
overlap), and partner resolution (cleared / conflicted / waived).

Revision ID: 20260430_0001
Revises: 20260427_0001
Create Date: 2026-04-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260430_0001"
down_revision = "20260427_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matter_conflict_checks",
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
            "ran_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("opposing_party_name", sa.String(length=255), nullable=False),
        sa.Column(
            "related_party_names_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "candidates_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_matter_conflict_checks_company_id",
        "matter_conflict_checks",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_conflict_checks_matter_id",
        "matter_conflict_checks",
        ["matter_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_conflict_checks_matter_id",
        table_name="matter_conflict_checks",
    )
    op.drop_index(
        "ix_matter_conflict_checks_company_id",
        table_name="matter_conflict_checks",
    )
    op.drop_table("matter_conflict_checks")
