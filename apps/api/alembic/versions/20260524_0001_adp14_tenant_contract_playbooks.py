"""ADP-14 tenant-managed contract playbooks + rules.

Revision ID: 20260524_0001
Revises: 20260523_0001
Create Date: 2026-05-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260524_0001"
down_revision = "20260523_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_contract_playbooks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contract_type_key", sa.String(length=80), nullable=True),
        sa.Column("jurisdiction", sa.String(length=120), nullable=True),
        sa.Column("party_perspective", sa.String(length=20), nullable=True),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "company_id",
            "name",
            name="uq_tenant_contract_playbook_company_name",
        ),
    )
    op.create_index(
        "ix_tenant_contract_playbooks_company_id",
        "tenant_contract_playbooks",
        ["company_id"],
    )

    op.create_table(
        "tenant_contract_playbook_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "playbook_id",
            sa.String(length=36),
            sa.ForeignKey("tenant_contract_playbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column("clause_type", sa.String(length=120), nullable=False),
        sa.Column("expected_position", sa.Text(), nullable=False),
        sa.Column("fallback_text", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("keyword_pattern", sa.String(length=255), nullable=True),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    )
    op.create_index(
        "ix_tenant_contract_playbook_rules_playbook_id",
        "tenant_contract_playbook_rules",
        ["playbook_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_contract_playbook_rules_playbook_id",
        table_name="tenant_contract_playbook_rules",
    )
    op.drop_table("tenant_contract_playbook_rules")
    op.drop_index(
        "ix_tenant_contract_playbooks_company_id",
        table_name="tenant_contract_playbooks",
    )
    op.drop_table("tenant_contract_playbooks")
