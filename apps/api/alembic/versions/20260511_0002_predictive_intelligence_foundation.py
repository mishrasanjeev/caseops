"""Predictive intelligence foundation tables.

Revision ID: 20260511_0002
Revises: 20260511_0001
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260511_0002"
down_revision = "20260511_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "predictive_signal_runs",
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
            "actor_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="predictive"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_quality", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("limitation_note", sa.Text(), nullable=True),
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
        "ix_predictive_signal_runs_company_id",
        "predictive_signal_runs",
        ["company_id"],
    )
    op.create_index(
        "ix_predictive_signal_runs_matter_id",
        "predictive_signal_runs",
        ["matter_id"],
    )
    op.create_index(
        "ix_predictive_signal_runs_actor_membership_id",
        "predictive_signal_runs",
        ["actor_membership_id"],
    )

    op.create_table(
        "predictive_signal_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("predictive_signal_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("estimate_label", sa.String(length=120), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_label", sa.String(length=32), nullable=False),
        sa.Column("confidence_band_low", sa.Float(), nullable=True),
        sa.Column("confidence_band_high", sa.Float(), nullable=True),
        sa.Column("limitation_note", sa.Text(), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("missing_data_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_predictive_signal_items_run_id", "predictive_signal_items", ["run_id"])
    op.create_index(
        "ix_predictive_signal_items_company_id",
        "predictive_signal_items",
        ["company_id"],
    )
    op.create_index(
        "ix_predictive_signal_items_matter_id",
        "predictive_signal_items",
        ["matter_id"],
    )
    op.create_index(
        "ix_predictive_signal_items_signal_type",
        "predictive_signal_items",
        ["signal_type"],
    )
    op.create_index(
        "ix_predictive_signal_items_status",
        "predictive_signal_items",
        ["status"],
    )

    op.create_table(
        "predictive_signal_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("predictive_signal_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(length=36),
            sa.ForeignKey("predictive_signal_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("source_date", sa.String(length=32), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_predictive_signal_evidence_run_id",
        "predictive_signal_evidence",
        ["run_id"],
    )
    op.create_index(
        "ix_predictive_signal_evidence_item_id",
        "predictive_signal_evidence",
        ["item_id"],
    )
    op.create_index(
        "ix_predictive_signal_evidence_company_id",
        "predictive_signal_evidence",
        ["company_id"],
    )
    op.create_index(
        "ix_predictive_signal_evidence_matter_id",
        "predictive_signal_evidence",
        ["matter_id"],
    )
    op.create_index(
        "ix_predictive_signal_evidence_source_type",
        "predictive_signal_evidence",
        ["source_type"],
    )
    op.create_index(
        "ix_predictive_signal_evidence_source_id",
        "predictive_signal_evidence",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_predictive_signal_evidence_source_id", "predictive_signal_evidence")
    op.drop_index("ix_predictive_signal_evidence_source_type", "predictive_signal_evidence")
    op.drop_index("ix_predictive_signal_evidence_matter_id", "predictive_signal_evidence")
    op.drop_index("ix_predictive_signal_evidence_company_id", "predictive_signal_evidence")
    op.drop_index("ix_predictive_signal_evidence_item_id", "predictive_signal_evidence")
    op.drop_index("ix_predictive_signal_evidence_run_id", "predictive_signal_evidence")
    op.drop_table("predictive_signal_evidence")

    op.drop_index("ix_predictive_signal_items_status", "predictive_signal_items")
    op.drop_index("ix_predictive_signal_items_signal_type", "predictive_signal_items")
    op.drop_index("ix_predictive_signal_items_matter_id", "predictive_signal_items")
    op.drop_index("ix_predictive_signal_items_company_id", "predictive_signal_items")
    op.drop_index("ix_predictive_signal_items_run_id", "predictive_signal_items")
    op.drop_table("predictive_signal_items")

    op.drop_index("ix_predictive_signal_runs_actor_membership_id", "predictive_signal_runs")
    op.drop_index("ix_predictive_signal_runs_matter_id", "predictive_signal_runs")
    op.drop_index("ix_predictive_signal_runs_company_id", "predictive_signal_runs")
    op.drop_table("predictive_signal_runs")
