"""Add legal update source records and amendment history.

Revision ID: 20260526_0005
Revises: 20260526_0004
Create Date: 2026-05-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260526_0005"
down_revision = "20260526_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "legal_update_source_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_legal_update_source_runs_source_key"),
        "legal_update_source_runs",
        ["source_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_legal_update_source_runs_status"),
        "legal_update_source_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "legal_update_source_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("source_record_key", sa.String(length=200), nullable=False),
        sa.Column("update_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("source_document_url", sa.String(length=800), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("act_year", sa.Integer(), nullable=True),
        sa.Column("statute_id", sa.String(length=64), nullable=True),
        sa.Column("statute_section_ids_json", sa.JSON(), nullable=True),
        sa.Column("sections_changed_json", sa.JSON(), nullable=True),
        sa.Column("source_category", sa.String(length=80), nullable=True),
        sa.Column("provenance_status", sa.String(length=80), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("summary_status", sa.String(length=24), nullable=False),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["statute_id"], ["statutes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_key",
            "source_record_key",
            name="uq_legal_update_source_records_source_record",
        ),
    )
    for column in (
        "source_key",
        "source_record_key",
        "update_type",
        "normalized_title",
        "published_date",
        "act_year",
        "statute_id",
        "source_category",
        "content_hash",
        "summary_status",
    ):
        op.create_index(
            op.f(f"ix_legal_update_source_records_{column}"),
            "legal_update_source_records",
            [column],
            unique=False,
        )

    op.create_table(
        "statute_change_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("statute_id", sa.String(length=64), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=False),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("sections_changed_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("comparison_json", sa.JSON(), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["legal_update_source_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["statute_id"], ["statutes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "statute_id",
            "source_record_id",
            "change_type",
            name="uq_statute_change_events_source_change",
        ),
    )
    op.create_index(
        op.f("ix_statute_change_events_statute_id"),
        "statute_change_events",
        ["statute_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_statute_change_events_source_record_id"),
        "statute_change_events",
        ["source_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_statute_change_events_change_type"),
        "statute_change_events",
        ["change_type"],
        unique=False,
    )

    with op.batch_alter_table("legal_update_alerts") as batch_op:
        batch_op.add_column(sa.Column("source_record_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("summary_json", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_legal_update_alerts_source_record_id",
            "legal_update_source_records",
            ["source_record_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_legal_update_alerts_source_record_id"),
            ["source_record_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("legal_update_alerts") as batch_op:
        batch_op.drop_index(op.f("ix_legal_update_alerts_source_record_id"))
        batch_op.drop_constraint("fk_legal_update_alerts_source_record_id", type_="foreignkey")
        batch_op.drop_column("summary_json")
        batch_op.drop_column("source_record_id")

    op.drop_index(op.f("ix_statute_change_events_change_type"), table_name="statute_change_events")
    op.drop_index(
        op.f("ix_statute_change_events_source_record_id"),
        table_name="statute_change_events",
    )
    op.drop_index(op.f("ix_statute_change_events_statute_id"), table_name="statute_change_events")
    op.drop_table("statute_change_events")

    for column in (
        "summary_status",
        "content_hash",
        "source_category",
        "statute_id",
        "act_year",
        "published_date",
        "normalized_title",
        "update_type",
        "source_record_key",
        "source_key",
    ):
        op.drop_index(
            op.f(f"ix_legal_update_source_records_{column}"),
            table_name="legal_update_source_records",
        )
    op.drop_table("legal_update_source_records")

    op.drop_index(op.f("ix_legal_update_source_runs_status"), table_name="legal_update_source_runs")
    op.drop_index(
        op.f("ix_legal_update_source_runs_source_key"),
        table_name="legal_update_source_runs",
    )
    op.drop_table("legal_update_source_runs")
