"""drafting studio schema

Revision ID: 20260417_0005
Revises: 20260417_0004
Create Date: 2026-04-17 09:00:00

Adds the drafting studio tables: drafts, draft_versions, draft_reviews.

A Draft is the long-lived document the firm is working on for a matter.
DraftVersion is a snapshot — each LLM generation or human edit lands a
new row so the state machine can always roll back. DraftReview captures
the submit / request-changes / approve / finalize actions as an audit
trail tied to a specific version.

Citations are stored as a JSON array on the version (not a separate
table) so retrieval is one query; every approve transition re-verifies
them against the authority corpus.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260417_0005"
down_revision = "20260417_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("draft_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_drafts_matter_status", "drafts", ["matter_id", "status"])
    op.create_index("ix_drafts_updated_at", "drafts", ["updated_at"])

    op.create_table(
        "draft_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "draft_id",
            sa.String(length=36),
            sa.ForeignKey("drafts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "generated_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "model_run_id",
            sa.String(length=36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verified_citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("draft_id", "revision", name="uq_draft_versions_revision"),
    )
    op.create_index(
        "ix_draft_versions_draft_rev", "draft_versions", ["draft_id", "revision"],
    )

    op.create_table(
        "draft_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "draft_id",
            sa.String(length=36),
            sa.ForeignKey("drafts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "version_id",
            sa.String(length=36),
            sa.ForeignKey("draft_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_draft_reviews_draft_created", "draft_reviews", ["draft_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_draft_reviews_draft_created", table_name="draft_reviews")
    op.drop_table("draft_reviews")
    op.drop_index("ix_draft_versions_draft_rev", table_name="draft_versions")
    op.drop_table("draft_versions")
    op.drop_index("ix_drafts_updated_at", table_name="drafts")
    op.drop_index("ix_drafts_matter_status", table_name="drafts")
    op.drop_table("drafts")
