"""LegalWorkspace LW-S7 custom role templates.

Revision ID: 20260506_0003
Revises: 20260506_0002
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260506_0003"
down_revision = "20260506_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "custom_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_role", sa.String(length=20), nullable=True),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "slug", name="uq_custom_roles_company_slug"),
    )
    op.create_index("ix_custom_roles_company_id", "custom_roles", ["company_id"])
    op.create_index(
        "ix_custom_roles_created_by_membership_id",
        "custom_roles",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_custom_roles_updated_by_membership_id",
        "custom_roles",
        ["updated_by_membership_id"],
    )

    with op.batch_alter_table("company_memberships") as batch:
        batch.add_column(sa.Column("custom_role_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_company_memberships_custom_role_id_custom_roles",
            "custom_roles",
            ["custom_role_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_company_memberships_custom_role_id",
            ["custom_role_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("company_memberships") as batch:
        batch.drop_index("ix_company_memberships_custom_role_id")
        batch.drop_constraint(
            "fk_company_memberships_custom_role_id_custom_roles",
            type_="foreignkey",
        )
        batch.drop_column("custom_role_id")

    op.drop_index(
        "ix_custom_roles_updated_by_membership_id",
        table_name="custom_roles",
    )
    op.drop_index(
        "ix_custom_roles_created_by_membership_id",
        table_name="custom_roles",
    )
    op.drop_index("ix_custom_roles_company_id", table_name="custom_roles")
    op.drop_table("custom_roles")
