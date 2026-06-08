"""google drive user connections.

Revision ID: 20260608_0003
Revises: 20260608_0002
Create Date: 2026-06-08 16:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260608_0003"
down_revision = "20260608_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _idx(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_idx(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    op.create_table(
        "user_drive_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
        sa.Column("display_email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("encrypted_token_ref", sa.Text(), nullable=True),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_list_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["company_memberships.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "membership_id",
            "provider",
            name="uq_drive_connections_company_membership_provider",
        ),
    )
    for column in ("company_id", "membership_id", "status"):
        _idx("user_drive_connections", column)


def downgrade() -> None:
    for column in ("company_id", "membership_id", "status"):
        _drop_idx("user_drive_connections", column)
    op.drop_table("user_drive_connections")
