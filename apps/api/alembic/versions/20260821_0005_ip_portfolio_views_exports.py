"""Add personal IP portfolio views and audited export jobs.

Revision ID: 20260821_0005
Revises: 20260821_0004
Create Date: 2026-08-21

Both tables begin empty and introduce no backfill or existing-row lock. The
revision follows the independently owned IPLF-039F cost migration after that
lane landed as ``20260821_0004``.

MIGRATION-LOCK-RISK: none beyond catalog locks for two new empty tables.
MIGRATION-ROLLBACK: safe while the feature is not serving; exported artifacts
must be removed through the storage retention path before a production drop.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260821_0005"
down_revision = "20260821_0004"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    with op.batch_alter_table("ip_import_rows") as batch:
        batch.add_column(
            sa.Column(
                "duplicate_candidates_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(sa.Column("reconciliation_decision", sa.String(length=24)))
        batch.add_column(sa.Column("reconciled_target_docket_id", sa.String(length=36)))
        batch.create_foreign_key(
            "fk_ip_import_row_reconciled_docket_company",
            "ip_docket_records",
            ["reconciled_target_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_ip_import_row_reconciliation_decision",
            "reconciliation_decision IS NULL OR reconciliation_decision IN "
            "('create_separate', 'link_existing', 'skip')",
        )

    op.create_table(
        "ip_portfolio_saved_views",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="personal"),
        sa.Column("team_id", sa.String(length=36)),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("columns_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_portfolio_view_membership_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id", "company_id"],
            ["teams.id", "teams.company_id"],
            name="fk_ip_portfolio_view_team_company",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_portfolio_view_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "membership_id",
            "name",
            name="uq_ip_portfolio_view_member_name",
        ),
        sa.CheckConstraint(
            "(scope = 'personal' AND team_id IS NULL) OR "
            "(scope = 'team' AND team_id IS NOT NULL)",
            name="ck_ip_portfolio_view_scope_owner",
        ),
    )
    op.create_index(
        "ix_ip_portfolio_views_company_member",
        "ip_portfolio_saved_views",
        ["company_id", "membership_id"],
    )

    op.create_table(
        "ip_portfolio_export_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("format", sa.String(length=12), nullable=False, server_default="csv"),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("columns_json", sa.JSON(), nullable=False),
        sa.Column("row_limit", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("storage_key", sa.String(length=1024)),
        sa.Column("row_count", sa.Integer()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_portfolio_export_requester_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_portfolio_export_id_company"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ip_portfolio_export_status",
        ),
        sa.CheckConstraint("format IN ('csv')", name="ck_ip_portfolio_export_format"),
        sa.CheckConstraint(
            "row_limit > 0 AND row_limit <= 50000",
            name="ck_ip_portfolio_export_row_limit",
        ),
    )
    op.create_index(
        "ix_ip_portfolio_exports_company_requester_created",
        "ip_portfolio_export_jobs",
        ["company_id", "requested_by_membership_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ip_portfolio_exports_company_requester_created",
        table_name="ip_portfolio_export_jobs",
    )
    op.drop_table("ip_portfolio_export_jobs")
    op.drop_index(
        "ix_ip_portfolio_views_company_member",
        table_name="ip_portfolio_saved_views",
    )
    op.drop_table("ip_portfolio_saved_views")
    with op.batch_alter_table("ip_import_rows") as batch:
        batch.drop_constraint(
            "fk_ip_import_row_reconciled_docket_company",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "ck_ip_import_row_reconciliation_decision",
            type_="check",
        )
        batch.drop_column("reconciled_target_docket_id")
        batch.drop_column("reconciliation_decision")
        batch.drop_column("duplicate_candidates_json")
