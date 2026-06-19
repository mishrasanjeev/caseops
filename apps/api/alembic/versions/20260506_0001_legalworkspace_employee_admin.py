"""LegalWorkspace LW-S5 employee directory and setup tokens.

Revision ID: 20260506_0001
Revises: 20260505_0004
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260506_0001"
down_revision = "20260505_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "employee_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mobile", sa.String(length=40), nullable=True),
        sa.Column("designation", sa.String(length=160), nullable=True),
        sa.Column("department", sa.String(length=160), nullable=True),
        sa.Column("employee_code", sa.String(length=80), nullable=True),
        sa.Column(
            "manager_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("joined_on", sa.Date(), nullable=True),
        sa.Column(
            "employment_status",
            sa.String(length=24),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_reset_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "force_password_change",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "company_id",
            "membership_id",
            name="uq_employee_profiles_company_membership",
        ),
        sa.UniqueConstraint(
            "company_id",
            "employee_code",
            name="uq_employee_profiles_company_employee_code",
        ),
    )
    op.create_index("ix_employee_profiles_company_id", "employee_profiles", ["company_id"])
    op.create_index(
        "ix_employee_profiles_membership_id",
        "employee_profiles",
        ["membership_id"],
    )
    op.create_index("ix_employee_profiles_department", "employee_profiles", ["department"])
    op.create_index(
        "ix_employee_profiles_manager_membership_id",
        "employee_profiles",
        ["manager_membership_id"],
    )
    op.create_index(
        "ix_employee_profiles_employment_status",
        "employee_profiles",
        ["employment_status"],
    )

    op.create_table(
        "account_setup_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_setup_tokens_company_id", "account_setup_tokens", ["company_id"])
    op.create_index("ix_account_setup_tokens_user_id", "account_setup_tokens", ["user_id"])
    op.create_index(
        "ix_account_setup_tokens_membership_id",
        "account_setup_tokens",
        ["membership_id"],
    )
    op.create_index("ix_account_setup_tokens_purpose", "account_setup_tokens", ["purpose"])
    op.create_index(
        "ix_account_setup_tokens_expires_at",
        "account_setup_tokens",
        ["expires_at"],
    )
    op.create_index("ix_account_setup_tokens_used_at", "account_setup_tokens", ["used_at"])

    bind = op.get_bind()
    memberships = bind.execute(
        sa.text(
            """
            SELECT id, company_id, is_active, created_at
            FROM company_memberships
            """
        )
    ).mappings()
    rows = []
    now = datetime.now(UTC)
    for membership in memberships:
        created_at = membership["created_at"] or now
        rows.append(
            {
                "id": str(uuid4()),
                "company_id": membership["company_id"],
                "membership_id": membership["id"],
                "mobile": None,
                "designation": None,
                "department": None,
                "employee_code": None,
                "manager_membership_id": None,
                "joined_on": None,
                "employment_status": (
                    "active" if bool(membership["is_active"]) else "inactive"
                ),
                "last_login_at": None,
                "setup_sent_at": None,
                "setup_completed_at": created_at,
                "password_reset_sent_at": None,
                "force_password_change": False,
                "created_at": created_at,
                "updated_at": now,
            }
        )
    if rows:
        op.bulk_insert(
            sa.table(
                "employee_profiles",
                sa.column("id", sa.String),
                sa.column("company_id", sa.String),
                sa.column("membership_id", sa.String),
                sa.column("mobile", sa.String),
                sa.column("designation", sa.String),
                sa.column("department", sa.String),
                sa.column("employee_code", sa.String),
                sa.column("manager_membership_id", sa.String),
                sa.column("joined_on", sa.Date),
                sa.column("employment_status", sa.String),
                sa.column("last_login_at", sa.DateTime(timezone=True)),
                sa.column("setup_sent_at", sa.DateTime(timezone=True)),
                sa.column("setup_completed_at", sa.DateTime(timezone=True)),
                sa.column("password_reset_sent_at", sa.DateTime(timezone=True)),
                sa.column("force_password_change", sa.Boolean),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index("ix_account_setup_tokens_used_at", table_name="account_setup_tokens")
    op.drop_index("ix_account_setup_tokens_expires_at", table_name="account_setup_tokens")
    op.drop_index("ix_account_setup_tokens_purpose", table_name="account_setup_tokens")
    op.drop_index("ix_account_setup_tokens_membership_id", table_name="account_setup_tokens")
    op.drop_index("ix_account_setup_tokens_user_id", table_name="account_setup_tokens")
    op.drop_index("ix_account_setup_tokens_company_id", table_name="account_setup_tokens")
    op.drop_table("account_setup_tokens")

    op.drop_index("ix_employee_profiles_employment_status", table_name="employee_profiles")
    op.drop_index("ix_employee_profiles_manager_membership_id", table_name="employee_profiles")
    op.drop_index("ix_employee_profiles_department", table_name="employee_profiles")
    op.drop_index("ix_employee_profiles_membership_id", table_name="employee_profiles")
    op.drop_index("ix_employee_profiles_company_id", table_name="employee_profiles")
    op.drop_table("employee_profiles")
