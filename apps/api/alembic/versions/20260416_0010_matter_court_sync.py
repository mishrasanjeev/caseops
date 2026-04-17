"""add matter court sync tables

Revision ID: 20260416_0010
Revises: 20260416_0009
Create Date: 2026-04-16 20:05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0010"
down_revision = "20260416_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_court_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("triggered_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "imported_cause_list_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "imported_order_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["triggered_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_matter_court_sync_runs_matter_id",
        "matter_court_sync_runs",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_court_sync_runs_triggered_by_membership_id",
        "matter_court_sync_runs",
        ["triggered_by_membership_id"],
        unique=False,
    )

    op.create_table(
        "matter_cause_list_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("sync_run_id", sa.String(length=36), nullable=True),
        sa.Column("listing_date", sa.Date(), nullable=False),
        sa.Column("forum_name", sa.String(length=255), nullable=False),
        sa.Column("bench_name", sa.String(length=255), nullable=True),
        sa.Column("courtroom", sa.String(length=120), nullable=True),
        sa.Column("item_number", sa.String(length=64), nullable=True),
        sa.Column("stage", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sync_run_id"], ["matter_court_sync_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_matter_cause_list_entries_matter_id",
        "matter_cause_list_entries",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_cause_list_entries_sync_run_id",
        "matter_cause_list_entries",
        ["sync_run_id"],
        unique=False,
    )

    op.create_table(
        "matter_court_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("sync_run_id", sa.String(length=36), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("order_text", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sync_run_id"], ["matter_court_sync_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_matter_court_orders_matter_id",
        "matter_court_orders",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_court_orders_sync_run_id",
        "matter_court_orders",
        ["sync_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_matter_court_orders_sync_run_id", table_name="matter_court_orders")
    op.drop_index("ix_matter_court_orders_matter_id", table_name="matter_court_orders")
    op.drop_table("matter_court_orders")

    op.drop_index(
        "ix_matter_cause_list_entries_sync_run_id", table_name="matter_cause_list_entries"
    )
    op.drop_index(
        "ix_matter_cause_list_entries_matter_id", table_name="matter_cause_list_entries"
    )
    op.drop_table("matter_cause_list_entries")

    op.drop_index(
        "ix_matter_court_sync_runs_triggered_by_membership_id",
        table_name="matter_court_sync_runs",
    )
    op.drop_index("ix_matter_court_sync_runs_matter_id", table_name="matter_court_sync_runs")
    op.drop_table("matter_court_sync_runs")
