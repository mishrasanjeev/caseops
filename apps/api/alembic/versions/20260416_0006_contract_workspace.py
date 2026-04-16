"""Add contract workspace tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0006"
down_revision = "20260416_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("linked_matter_id", sa.String(length=36), nullable=True),
        sa.Column("owner_membership_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("contract_code", sa.String(length=80), nullable=False),
        sa.Column("counterparty_name", sa.String(length=255), nullable=True),
        sa.Column("contract_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("jurisdiction", sa.String(length=255), nullable=True),
        sa.Column("effective_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("renewal_on", sa.Date(), nullable=True),
        sa.Column("auto_renewal", sa.Boolean(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("total_value_minor", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_matter_id"], ["matters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["owner_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "contract_code", name="uq_company_contract_code"),
    )
    op.create_index(op.f("ix_contracts_company_id"), "contracts", ["company_id"], unique=False)
    op.create_index(
        op.f("ix_contracts_linked_matter_id"),
        "contracts",
        ["linked_matter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contracts_owner_membership_id"),
        "contracts",
        ["owner_membership_id"],
        unique=False,
    )

    op.create_table(
        "contract_clauses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("clause_type", sa.String(length=120), nullable=False),
        sa.Column("clause_text", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contract_clauses_contract_id"),
        "contract_clauses",
        ["contract_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contract_clauses_created_by_membership_id"),
        "contract_clauses",
        ["created_by_membership_id"],
        unique=False,
    )

    op.create_table(
        "contract_obligations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("owner_membership_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contract_obligations_contract_id"),
        "contract_obligations",
        ["contract_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contract_obligations_owner_membership_id"),
        "contract_obligations",
        ["owner_membership_id"],
        unique=False,
    )

    op.create_table(
        "contract_playbook_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column("clause_type", sa.String(length=120), nullable=False),
        sa.Column("expected_position", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("keyword_pattern", sa.String(length=255), nullable=True),
        sa.Column("fallback_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contract_playbook_rules_contract_id"),
        "contract_playbook_rules",
        ["contract_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contract_playbook_rules_created_by_membership_id"),
        "contract_playbook_rules",
        ["created_by_membership_id"],
        unique=False,
    )

    op.create_table(
        "contract_activity",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contract_activity_contract_id"),
        "contract_activity",
        ["contract_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contract_activity_actor_membership_id"),
        "contract_activity",
        ["actor_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_contract_activity_actor_membership_id"), table_name="contract_activity")
    op.drop_index(op.f("ix_contract_activity_contract_id"), table_name="contract_activity")
    op.drop_table("contract_activity")

    op.drop_index(
        op.f("ix_contract_playbook_rules_created_by_membership_id"),
        table_name="contract_playbook_rules",
    )
    op.drop_index(
        op.f("ix_contract_playbook_rules_contract_id"),
        table_name="contract_playbook_rules",
    )
    op.drop_table("contract_playbook_rules")

    op.drop_index(
        op.f("ix_contract_obligations_owner_membership_id"),
        table_name="contract_obligations",
    )
    op.drop_index(
        op.f("ix_contract_obligations_contract_id"),
        table_name="contract_obligations",
    )
    op.drop_table("contract_obligations")

    op.drop_index(
        op.f("ix_contract_clauses_created_by_membership_id"),
        table_name="contract_clauses",
    )
    op.drop_index(op.f("ix_contract_clauses_contract_id"), table_name="contract_clauses")
    op.drop_table("contract_clauses")

    op.drop_index(op.f("ix_contracts_owner_membership_id"), table_name="contracts")
    op.drop_index(op.f("ix_contracts_linked_matter_id"), table_name="contracts")
    op.drop_index(op.f("ix_contracts_company_id"), table_name="contracts")
    op.drop_table("contracts")
