"""matter_deadlines + tenant_ai_policy

Revision ID: 20260418_0009
Revises: 20260418_0008
Create Date: 2026-04-18 19:00:00

Two unrelated slim tables in one migration to keep the chain tidy.

``matter_deadlines`` (Sprint 13 partial — BG-041):
    Generic deadline entity so hearings, drafts, contracts, intake,
    and post-hearing follow-ups all write to one table. Reduces the
    need to join four tables to answer "what is due this week for
    tenant X".

``tenant_ai_policy`` (Sprint 15 partial — BG-046 schema):
    Per-tenant AI policy. Today this table is READ by the LLM
    provider factory to gate model choice; enforcement of
    token_budget and external_share_requires_approval is tracked
    under the same BG but not shipped in this migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0009"
down_revision = "20260418_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matter_deadlines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Source: which pipeline generated this deadline — hearing,
        # draft-review, intake, contract obligation, tenant-custom.
        sa.Column("source", sa.String(length=32), nullable=False),
        # Free-text kind that the source domain owns, e.g.
        # "reply_due", "compliance_due", "filing_window_close".
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=False, index=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column(
            "assignee_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # Optional back-references — a deadline born from a specific
        # hearing / draft / contract keeps a soft FK so the UI can
        # link users back to the source.
        sa.Column("source_ref_type", sa.String(length=32), nullable=True),
        sa.Column("source_ref_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_matter_deadlines_matter_status_due",
        "matter_deadlines",
        ["matter_id", "status", "due_on"],
    )

    op.create_table(
        "tenant_ai_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Allowed models per purpose. Stored as JSON lists so a tenant
        # can pin drafting to Opus-only while letting metadata
        # extraction fall back to Haiku. Empty list means "no
        # restriction" — the configured per-purpose model wins.
        sa.Column(
            "allowed_models_drafting_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "allowed_models_recommendations_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "allowed_models_hearing_pack_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        # Coarse budgets. `max_tokens_per_session` caps a single call;
        # `monthly_token_budget` is a soft cap the admin can dial.
        sa.Column("max_tokens_per_session", sa.Integer(), nullable=False, server_default="16384"),
        sa.Column("monthly_token_budget", sa.Integer(), nullable=True),
        sa.Column(
            "external_share_requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "training_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_ai_policies")
    op.drop_index(
        "ix_matter_deadlines_matter_status_due", table_name="matter_deadlines"
    )
    op.drop_table("matter_deadlines")
