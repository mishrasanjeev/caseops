"""Add provider-gated case tracking tables.

Revision ID: 20260526_0006
Revises: 20260526_0005
Create Date: 2026-05-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260526_0006"
down_revision = "20260526_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "tracked_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("identity_key", sa.String(length=260), nullable=False),
        sa.Column("cnr_number", sa.String(length=32), nullable=True),
        sa.Column("normalized_cnr_number", sa.String(length=32), nullable=True),
        sa.Column("case_number", sa.String(length=120), nullable=True),
        sa.Column("normalized_case_number", sa.String(length=120), nullable=True),
        sa.Column("court_code", sa.String(length=80), nullable=True),
        sa.Column("court_name", sa.String(length=255), nullable=True),
        sa.Column("case_title", sa.String(length=500), nullable=False),
        sa.Column("party_names_json", sa.JSON(), nullable=True),
        sa.Column("current_status", sa.String(length=160), nullable=True),
        sa.Column("current_stage", sa.String(length=160), nullable=True),
        sa.Column("next_hearing_on", sa.Date(), nullable=True),
        sa.Column("last_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("last_provider_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_provider_refresh_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "provider",
            "identity_key",
            name="uq_tracked_cases_provider_identity",
        ),
    )
    for column in (
        "company_id",
        "provider",
        "identity_key",
        "cnr_number",
        "normalized_cnr_number",
        "normalized_case_number",
        "court_code",
        "next_hearing_on",
        "last_provider_checked_at",
    ):
        op.create_index(op.f(f"ix_tracked_cases_{column}"), "tracked_cases", [column])

    op.create_table(
        "tracked_case_bookmarks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("tracked_case_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=True),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("active_scope_key", sa.String(length=80), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("notification_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tracked_case_id"], ["tracked_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "tracked_case_id",
            "created_by_membership_id",
            "active_scope_key",
            name="uq_tracked_case_bookmarks_active_scope",
        ),
    )
    for column in (
        "company_id",
        "tracked_case_id",
        "created_by_membership_id",
        "matter_id",
        "scope_key",
        "active_scope_key",
        "is_archived",
    ):
        op.create_index(
            op.f(f"ix_tracked_case_bookmarks_{column}"),
            "tracked_case_bookmarks",
            [column],
        )

    op.create_table(
        "tracked_case_updates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("tracked_case_id", sa.String(length=36), nullable=False),
        sa.Column("update_type", sa.String(length=40), nullable=False),
        sa.Column("source_record_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("ai_summary_json", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.String(length=800), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("hearing_date", sa.Date(), nullable=True),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("current_hash", sa.String(length=64), nullable=False),
        sa.Column("provider_metadata_json", sa.JSON(), nullable=True),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tracked_case_id"], ["tracked_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tracked_case_id",
            "source_record_key",
            "update_type",
            name="uq_tracked_case_updates_source",
        ),
    )
    for column in (
        "company_id",
        "tracked_case_id",
        "update_type",
        "source_record_key",
        "order_date",
    ):
        op.create_index(
            op.f(f"ix_tracked_case_updates_{column}"),
            "tracked_case_updates",
            [column],
        )

    op.create_table(
        "tracked_case_poll_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_count", sa.Integer(), nullable=False),
        sa.Column("update_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tracked_case_poll_runs_company_id"),
        "tracked_case_poll_runs",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_tracked_case_poll_runs_status"),
        "tracked_case_poll_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tracked_case_poll_runs_status"), table_name="tracked_case_poll_runs")
    op.drop_index(
        op.f("ix_tracked_case_poll_runs_company_id"),
        table_name="tracked_case_poll_runs",
    )
    op.drop_table("tracked_case_poll_runs")

    for column in (
        "order_date",
        "source_record_key",
        "update_type",
        "tracked_case_id",
        "company_id",
    ):
        op.drop_index(
            op.f(f"ix_tracked_case_updates_{column}"),
            table_name="tracked_case_updates",
        )
    op.drop_table("tracked_case_updates")

    for column in (
        "is_archived",
        "active_scope_key",
        "scope_key",
        "matter_id",
        "created_by_membership_id",
        "tracked_case_id",
        "company_id",
    ):
        op.drop_index(
            op.f(f"ix_tracked_case_bookmarks_{column}"),
            table_name="tracked_case_bookmarks",
        )
    op.drop_table("tracked_case_bookmarks")

    for column in (
        "last_provider_checked_at",
        "next_hearing_on",
        "court_code",
        "normalized_case_number",
        "normalized_cnr_number",
        "cnr_number",
        "identity_key",
        "provider",
        "company_id",
    ):
        op.drop_index(op.f(f"ix_tracked_cases_{column}"), table_name="tracked_cases")
    op.drop_table("tracked_cases")
