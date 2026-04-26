"""Bench-strategy Phase 2 (MOD-TS-018): L-A / L-B / L-C analysis tables.

Per docs/PRD_BENCH_STRATEGY_2026-04-26.md §4.4.

- judge_decision_index (L-A): one row per (judge, judgment) pair so
  bench-strategy can list "authored / sat on" history per judge in
  O(N) joins instead of recomputing from judges_json each query.
- judge_authority_affinity (L-B): per (judge, cited_authority) pair
  count + last_year + sample_judgment so the bench-strategy panel can
  surface "this bench cites this authority N times".
- judge_statute_focus (L-C): same shape as L-B but for statute sections.

All three are refreshed by a single nightly job (see services/
bench_analysis_layers.py). No Anthropic spend; pure SQL aggregation.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0003"
down_revision = "20260426_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_decision_index",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "judge_id", sa.String(length=36),
            sa.ForeignKey("judges.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "authority_document_id", sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="sat_on"),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("matched_alias", sa.String(length=255), nullable=True),
        sa.Column("match_confidence", sa.String(length=24), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "judge_id", "authority_document_id",
            name="uq_judge_decision_index_unique",
        ),
    )
    op.create_index(
        "ix_judge_decision_index_year",
        "judge_decision_index", ["judge_id", "year"],
    )

    op.create_table(
        "judge_authority_affinity",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "judge_id", sa.String(length=36),
            sa.ForeignKey("judges.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "cited_authority_document_id", sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_year", sa.Integer(), nullable=True),
        sa.Column(
            "sample_judgment_id", sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "refreshed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "judge_id", "cited_authority_document_id",
            name="uq_judge_authority_affinity_unique",
        ),
    )
    op.create_index(
        "ix_judge_authority_affinity_count",
        "judge_authority_affinity", ["judge_id", "citation_count"],
    )

    op.create_table(
        "judge_statute_focus",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "judge_id", sa.String(length=36),
            sa.ForeignKey("judges.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "statute_section_id", sa.String(length=36),
            sa.ForeignKey("statute_sections.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_year", sa.Integer(), nullable=True),
        sa.Column(
            "sample_judgment_id", sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "refreshed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "judge_id", "statute_section_id",
            name="uq_judge_statute_focus_unique",
        ),
    )
    op.create_index(
        "ix_judge_statute_focus_count",
        "judge_statute_focus", ["judge_id", "citation_count"],
    )


def downgrade() -> None:
    op.drop_index("ix_judge_statute_focus_count", table_name="judge_statute_focus")
    op.drop_table("judge_statute_focus")
    op.drop_index("ix_judge_authority_affinity_count", table_name="judge_authority_affinity")
    op.drop_table("judge_authority_affinity")
    op.drop_index("ix_judge_decision_index_year", table_name="judge_decision_index")
    op.drop_table("judge_decision_index")
