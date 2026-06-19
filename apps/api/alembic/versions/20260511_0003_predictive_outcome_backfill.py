"""Predictive outcome classification and aggregate snapshots.

Revision ID: 20260511_0003
Revises: 20260511_0002
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260511_0003"
down_revision = "20260511_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "predictive_outcome_classifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("classification_label", sa.String(length=80), nullable=False),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("court_name", sa.String(length=255), nullable=True),
        sa.Column("forum_level", sa.String(length=40), nullable=True),
        sa.Column("judge_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("matter_type", sa.String(length=120), nullable=True),
        sa.Column("party_side", sa.String(length=32), nullable=True),
        sa.Column("decision_year", sa.Integer(), nullable=True),
        sa.Column("rationale_snippet", sa.Text(), nullable=True),
        sa.Column("method", sa.String(length=40), nullable=False, server_default="deterministic"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="classified"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "model_run_id",
            sa.String(length=36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "source_type",
            "source_id",
            "classification_label",
            "signal_type",
            name="uq_predictive_outcome_classification_source_label_signal",
        ),
    )
    for column in (
        "source_type",
        "source_id",
        "source_hash",
        "company_id",
        "matter_id",
        "classification_label",
        "signal_type",
        "court_name",
        "forum_level",
        "matter_type",
        "party_side",
        "decision_year",
        "status",
        "model_run_id",
    ):
        op.create_index(
            f"ix_predictive_outcome_classifications_{column}",
            "predictive_outcome_classifications",
            [column],
        )

    op.create_table(
        "predictive_outcome_aggregate_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_key", sa.String(length=700), nullable=False),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("court_name", sa.String(length=255), nullable=True),
        sa.Column("forum_level", sa.String(length=40), nullable=True),
        sa.Column("judge_id", sa.String(length=36), nullable=True),
        sa.Column("matter_type", sa.String(length=120), nullable=True),
        sa.Column("party_side", sa.String(length=32), nullable=True),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neutral_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consistency", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "confidence_label",
            sa.String(length=32),
            nullable=False,
            server_default="insufficient",
        ),
        sa.Column("confidence_band_low", sa.Float(), nullable=True),
        sa.Column("confidence_band_high", sa.Float(), nullable=True),
        sa.Column("evidence_source_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("feature_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="insufficient_evidence",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "scope_key",
            name="uq_predictive_outcome_aggregate_scope_key",
        ),
    )
    for column in (
        "scope_type",
        "scope_key",
        "company_id",
        "matter_id",
        "court_name",
        "forum_level",
        "judge_id",
        "matter_type",
        "party_side",
        "year_start",
        "year_end",
        "signal_type",
        "status",
    ):
        op.create_index(
            f"ix_predictive_outcome_aggregate_snapshots_{column}",
            "predictive_outcome_aggregate_snapshots",
            [column],
        )


def downgrade() -> None:
    for column in (
        "status",
        "signal_type",
        "year_end",
        "year_start",
        "party_side",
        "matter_type",
        "judge_id",
        "forum_level",
        "court_name",
        "matter_id",
        "company_id",
        "scope_key",
        "scope_type",
    ):
        op.drop_index(
            f"ix_predictive_outcome_aggregate_snapshots_{column}",
            table_name="predictive_outcome_aggregate_snapshots",
        )
    op.drop_table("predictive_outcome_aggregate_snapshots")

    for column in (
        "model_run_id",
        "status",
        "decision_year",
        "party_side",
        "matter_type",
        "forum_level",
        "court_name",
        "signal_type",
        "classification_label",
        "matter_id",
        "company_id",
        "source_hash",
        "source_id",
        "source_type",
    ):
        op.drop_index(
            f"ix_predictive_outcome_classifications_{column}",
            table_name="predictive_outcome_classifications",
        )
    op.drop_table("predictive_outcome_classifications")
