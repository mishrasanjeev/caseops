"""Expand the canonical record-access owners for IP docket targets.

Revision ID: 20260811_0001
Revises: 20260810_0004

The revision is additive for the previous application. Legacy Matter writers
may continue to provide only their historical target and membership columns
while traffic drains.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0001"
down_revision = "20260810_0004"
branch_labels = None
depends_on = None


def _expand_grants() -> None:
    op.add_column("matter_access_grants", sa.Column("company_id", sa.String(36)))
    op.add_column("matter_access_grants", sa.Column("ip_docket_id", sa.String(36)))
    op.add_column("matter_access_grants", sa.Column("team_id", sa.String(36)))
    op.add_column(
        "matter_access_grants",
        sa.Column("effective_from", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "matter_access_grants",
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "matter_access_grants",
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "matter_access_grants",
        sa.Column("revoked_by_membership_id", sa.String(36)),
    )
    op.add_column(
        "matter_access_grants",
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
    )
    for column_name in (
        "company_id",
        "ip_docket_id",
        "team_id",
        "effective_from",
        "expires_at",
        "revoked_at",
        "revoked_by_membership_id",
    ):
        op.create_index(
            f"ix_matter_access_grants_{column_name}",
            "matter_access_grants",
            [column_name],
        )
    with op.batch_alter_table("matter_access_grants") as batch_op:
        batch_op.alter_column(
            "matter_id", existing_type=sa.String(36), nullable=True
        )
        batch_op.alter_column(
            "membership_id", existing_type=sa.String(36), nullable=True
        )


def _expand_walls() -> None:
    op.add_column("ethical_walls", sa.Column("company_id", sa.String(36)))
    op.add_column("ethical_walls", sa.Column("ip_docket_id", sa.String(36)))
    op.add_column("ethical_walls", sa.Column("excluded_team_id", sa.String(36)))
    op.add_column(
        "ethical_walls",
        sa.Column("effective_from", sa.DateTime(timezone=True)),
    )
    op.add_column("ethical_walls", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("ethical_walls", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.add_column(
        "ethical_walls",
        sa.Column("revoked_by_membership_id", sa.String(36)),
    )
    op.add_column(
        "ethical_walls",
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
    )
    for column_name in (
        "company_id",
        "ip_docket_id",
        "excluded_team_id",
        "effective_from",
        "expires_at",
        "revoked_at",
        "revoked_by_membership_id",
    ):
        op.create_index(
            f"ix_ethical_walls_{column_name}",
            "ethical_walls",
            [column_name],
        )
    with op.batch_alter_table("ethical_walls") as batch_op:
        batch_op.alter_column(
            "matter_id", existing_type=sa.String(36), nullable=True
        )
        batch_op.alter_column(
            "excluded_membership_id",
            existing_type=sa.String(36),
            nullable=True,
        )


def upgrade() -> None:
    _expand_grants()
    _expand_walls()
    op.add_column(
        "matters",
        sa.Column(
            "access_policy_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "ip_docket_records",
        sa.Column(
            "access_policy_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("audit_events", sa.Column("ip_docket_id", sa.String(36)))
    op.create_index(
        "ix_audit_events_ip_docket_id",
        "audit_events",
        ["ip_docket_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_ip_docket_id", table_name="audit_events")
    op.drop_column("audit_events", "ip_docket_id")
    op.drop_column("ip_docket_records", "access_policy_version")
    op.drop_column("matters", "access_policy_version")

    for table_name, team_column in (
        ("ethical_walls", "excluded_team_id"),
        ("matter_access_grants", "team_id"),
    ):
        with op.batch_alter_table(table_name) as batch_op:
            subject_column = (
                "excluded_membership_id"
                if table_name == "ethical_walls"
                else "membership_id"
            )
            batch_op.alter_column(
                subject_column, existing_type=sa.String(36), nullable=False
            )
            batch_op.alter_column(
                "matter_id", existing_type=sa.String(36), nullable=False
            )
        for column_name in (
            "revoked_by_membership_id",
            "revoked_at",
            "expires_at",
            "effective_from",
            team_column,
            "ip_docket_id",
            "company_id",
        ):
            op.drop_index(
                f"ix_{table_name}_{column_name}",
                table_name=table_name,
            )
        for column_name in (
            "record_version",
            "revoked_by_membership_id",
            "revoked_at",
            "expires_at",
            "effective_from",
            team_column,
            "ip_docket_id",
            "company_id",
        ):
            op.drop_column(table_name, column_name)
