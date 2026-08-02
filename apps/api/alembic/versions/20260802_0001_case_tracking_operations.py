"""Add durable case-tracking operations, snapshots, and freshness state.

Revision ID: 20260802_0001
Revises: 20260801_0006
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260802_0001"
down_revision = "20260801_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracked_cases", sa.Column("last_provider_attempted_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "tracked_cases", sa.Column("last_provider_successful_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "tracked_cases", sa.Column("next_provider_refresh_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "tracked_cases",
        sa.Column(
            "provider_freshness_status",
            sa.String(24),
            nullable=False,
            server_default="never_succeeded",
        ),
    )
    op.add_column("tracked_cases", sa.Column("last_response_class", sa.String(32)))
    op.add_column("tracked_cases", sa.Column("last_operation_id", sa.String(36)))
    op.add_column("tracked_cases", sa.Column("quarantined_at", sa.DateTime(timezone=True)))
    op.add_column("tracked_cases", sa.Column("quarantine_reason_redacted", sa.Text()))
    for column in (
        "last_provider_attempted_at",
        "last_provider_successful_at",
        "next_provider_refresh_at",
        "provider_freshness_status",
        "last_operation_id",
    ):
        op.create_index(f"ix_tracked_cases_{column}", "tracked_cases", [column])

    op.create_table(
        "tracked_case_provider_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("tracked_case_id", sa.String(36), nullable=False),
        sa.Column("poll_run_id", sa.String(36)),
        sa.Column("requested_by_membership_id", sa.String(36)),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("operation_type", sa.String(24), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("response_class", sa.String(32)),
        sa.Column("error_redacted", sa.Text()),
        sa.Column("cost_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("quarantined_at", sa.DateTime(timezone=True)),
        sa.Column("quarantine_reason_redacted", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracked_case_id"], ["tracked_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["poll_run_id"], ["tracked_case_poll_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "company_id", "correlation_id", name="uq_tracking_operation_correlation"
        ),
    )
    for column in (
        "company_id",
        "tracked_case_id",
        "poll_run_id",
        "requested_by_membership_id",
        "provider",
        "operation_type",
        "correlation_id",
        "status",
        "response_class",
    ):
        op.create_index(
            f"ix_tracked_case_provider_operations_{column}",
            "tracked_case_provider_operations",
            [column],
        )

    op.create_table(
        "tracked_case_provider_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("tracked_case_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("diff_json", sa.JSON()),
        sa.Column("source_url", sa.String(800)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracked_case_id"], ["tracked_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["tracked_case_provider_operations.id"], ondelete="CASCADE"
        ),
    )
    for column in ("company_id", "tracked_case_id", "operation_id", "raw_hash", "normalized_hash"):
        op.create_index(
            f"ix_tracked_case_provider_snapshots_{column}",
            "tracked_case_provider_snapshots",
            [column],
        )


def downgrade() -> None:
    op.drop_table("tracked_case_provider_snapshots")
    op.drop_table("tracked_case_provider_operations")
    for column in (
        "last_provider_attempted_at",
        "last_provider_successful_at",
        "next_provider_refresh_at",
        "provider_freshness_status",
        "last_operation_id",
    ):
        op.drop_index(f"ix_tracked_cases_{column}", table_name="tracked_cases")
    for column in (
        "quarantine_reason_redacted",
        "quarantined_at",
        "last_operation_id",
        "last_response_class",
        "provider_freshness_status",
        "next_provider_refresh_at",
        "last_provider_successful_at",
        "last_provider_attempted_at",
    ):
        op.drop_column("tracked_cases", column)
