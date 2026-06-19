"""provider cost profiles and margin simulations.

Revision ID: 20260608_0001
Revises: 20260606_0001
Create Date: 2026-06-08 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260608_0001"
down_revision = "20260606_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def _create_index(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_index(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    op.create_table(
        "provider_cost_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("unit_amount_minor", sa.Integer(), nullable=True),
        sa.Column("unit_amount_bps", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "unit_amount_minor IS NOT NULL OR unit_amount_bps IS NOT NULL",
            name="ck_provider_cost_profiles_amount_present",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_platform_admin_id"],
            ["platform_admin_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "category",
        "provider",
        "currency",
        "effective_from",
        "status",
        "created_by_platform_admin_id",
    ):
        _create_index("provider_cost_profiles", column)
    op.create_index(
        "ix_provider_cost_profiles_lookup",
        "provider_cost_profiles",
        ["category", "provider", "currency", "effective_from"],
    )

    op.create_table(
        "billing_margin_simulations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scenario_name", sa.String(length=160), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("run_by_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_by_platform_admin_id"],
            ["platform_admin_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("currency", "run_by_platform_admin_id", "created_at"):
        _create_index("billing_margin_simulations", column)


def downgrade() -> None:
    for column in ("currency", "run_by_platform_admin_id", "created_at"):
        _drop_index("billing_margin_simulations", column)
    op.drop_table("billing_margin_simulations")

    op.drop_index("ix_provider_cost_profiles_lookup", table_name="provider_cost_profiles")
    for column in reversed(
        (
            "category",
            "provider",
            "currency",
            "effective_from",
            "status",
            "created_by_platform_admin_id",
        )
    ):
        _drop_index("provider_cost_profiles", column)
    op.drop_table("provider_cost_profiles")
