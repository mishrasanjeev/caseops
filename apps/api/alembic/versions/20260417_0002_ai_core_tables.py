"""AI core: model runs, recommendations, options, decisions

Revision ID: 20260417_0002
Revises: 20260417_0001
Create Date: 2026-04-17 01:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260417_0002"
down_revision = "20260417_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("matter_id", sa.String(length=36), nullable=True),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=True),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_runs_company_id"), "model_runs", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_model_runs_matter_id"), "model_runs", ["matter_id"], unique=False
    )
    op.create_index(
        op.f("ix_model_runs_actor_membership_id"),
        "model_runs",
        ["actor_membership_id"],
        unique=False,
    )
    op.create_index(op.f("ix_model_runs_purpose"), "model_runs", ["purpose"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("primary_option_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("missing_facts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="proposed"),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recommendations_company_id"),
        "recommendations",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendations_matter_id"),
        "recommendations",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendations_type"), "recommendations", ["type"], unique=False
    )

    op.create_table(
        "recommendation_options",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recommendation_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(length=400), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column(
            "supporting_citations_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("risk_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["recommendations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recommendation_options_recommendation_id"),
        "recommendation_options",
        ["recommendation_id"],
        unique=False,
    )

    op.create_table(
        "recommendation_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recommendation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=True),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("selected_option_index", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["recommendations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recommendation_decisions_recommendation_id"),
        "recommendation_decisions",
        ["recommendation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recommendation_decisions_recommendation_id"),
        table_name="recommendation_decisions",
    )
    op.drop_table("recommendation_decisions")
    op.drop_index(
        op.f("ix_recommendation_options_recommendation_id"),
        table_name="recommendation_options",
    )
    op.drop_table("recommendation_options")
    op.drop_index(op.f("ix_recommendations_type"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_matter_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_company_id"), table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index(op.f("ix_model_runs_purpose"), table_name="model_runs")
    op.drop_index(op.f("ix_model_runs_actor_membership_id"), table_name="model_runs")
    op.drop_index(op.f("ix_model_runs_matter_id"), table_name="model_runs")
    op.drop_index(op.f("ix_model_runs_company_id"), table_name="model_runs")
    op.drop_table("model_runs")
