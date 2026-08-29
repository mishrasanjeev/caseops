"""Add the assistant proposed-action preview and confirmation boundary.

Revision ID: 20260829_0001
Revises: 20260828_0002

MIGRATION-LOCK-RISK: none on existing application tables; the migration creates
one empty additive table and its indexes before action execution is enabled.
MIGRATION-ROLLBACK: restore-forward once preview or confirmation evidence exists.
The table is retained legal work-product provenance and cannot be dropped while
populated.
DATA-GOVERNANCE-MAP: updated for assistant action previews, confirmations, and
canonical writer result links.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260829_0001"
down_revision = "20260828_0002"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()
    op.create_table(
        "assistant_action_previews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=24), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("target_version", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("preview_token_sha256", sa.String(length=64), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_type", sa.String(length=32), nullable=True),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("result_href", sa.String(length=2048), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('draft', 'task', 'field_update')",
            name="ck_assistant_action_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'superseded', 'confirmed')",
            name="ck_assistant_action_status",
        ),
        sa.CheckConstraint(
            "session_version > 0 AND policy_version > 0",
            name="ck_assistant_action_versions_positive",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 AND length(preview_token_sha256) = 64",
            name="ck_assistant_action_hashes",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_assistant_action_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "(status = 'confirmed' AND confirmed_at IS NOT NULL AND "
            "result_type IS NOT NULL AND result_id IS NOT NULL AND result_href IS NOT NULL) OR "
            "(status IN ('pending', 'superseded') AND confirmed_at IS NULL AND "
            "result_type IS NULL AND result_id IS NULL AND result_href IS NULL)",
            name="ck_assistant_action_result_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_assistant_action_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "company_id"],
            ["assistant_sessions.id", "assistant_sessions.company_id"],
            name="fk_assistant_action_session_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "company_id"],
            ["assistant_turns.id", "assistant_turns.company_id"],
            name="fk_assistant_action_turn_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_assistant_action_actor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_assistant_action_id_company"),
    )
    op.create_index(
        "ix_assistant_actions_company_actor_status_expiry",
        "assistant_action_previews",
        ["company_id", "created_by_membership_id", "status", "expires_at", "id"],
    )
    op.create_index(
        "ix_assistant_actions_company_session_turn",
        "assistant_action_previews",
        ["company_id", "session_id", "turn_id"],
    )
    op.create_index(
        "ix_assistant_actions_session_company",
        "assistant_action_previews",
        ["session_id", "company_id"],
    )
    op.create_index(
        "ix_assistant_actions_turn_company",
        "assistant_action_previews",
        ["turn_id", "company_id"],
    )
    op.create_index(
        "ix_assistant_actions_turn_proposal",
        "assistant_action_previews",
        ["turn_id", "proposal_id", "created_at"],
    )
    op.create_index(
        "ix_assistant_actions_actor_company",
        "assistant_action_previews",
        ["created_by_membership_id", "company_id"],
    )


def downgrade() -> None:
    _set_postgres_timeouts()
    retained = op.get_bind().scalar(
        sa.text("SELECT 1 FROM assistant_action_previews LIMIT 1")
    )
    if retained is not None:
        raise RuntimeError(
            "Cannot downgrade the assistant action boundary while retained preview or "
            "confirmation evidence exists. Use governed disposition and restore-forward."
        )
    op.drop_table("assistant_action_previews")
