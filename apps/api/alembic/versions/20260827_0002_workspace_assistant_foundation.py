"""Add the permission-scoped workspace assistant foundation.

Revision ID: 20260827_0002
Revises: 20260827_0001

MIGRATION-LOCK-RISK: acknowledged: the only existing table touched is the one-
row-per-tenant AI policy table; additive columns use constant defaults and
bounded checks. Every flagged index is built on a table created empty in this
same migration before application traffic can use it.
MIGRATION-ROLLBACK: restore-forward: downgrade is allowed only while all
assistant tables are empty because sessions, turns, and citations are audit-
relevant legal work product. Once evidence exists, the migration refuses the
destructive rollback and requires governed export/disposition plus roll-forward.
DATA-GOVERNANCE-MAP: updated for assistant conversations, explicit scope
references, model provenance, retention, and citation records.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260827_0002"
down_revision = "20260827_0001"
branch_labels = None
depends_on = None

ASSISTANT_TABLES = (
    "assistant_citations",
    "assistant_turns",
    "assistant_session_scopes",
    "assistant_sessions",
)


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()
    op.add_column(
        "tenant_ai_policies",
        sa.Column(
            "allowed_models_assistant_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "tenant_ai_policies",
        sa.Column(
            "workspace_assistant_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tenant_ai_policies",
        sa.Column(
            "assistant_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="90",
        ),
    )
    op.add_column(
        "tenant_ai_policies",
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
    )
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.create_check_constraint(
            "ck_tenant_ai_policy_assistant_retention_days",
            "assistant_retention_days >= 1 AND assistant_retention_days <= 3650",
        )
        batch.create_check_constraint(
            "ck_tenant_ai_policy_version_positive",
            "policy_version > 0",
        )

    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_assistant_session_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_assistant_session_version_positive"),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assistant_session_title_nonempty",
        ),
        sa.CheckConstraint(
            "retention_expires_at > created_at",
            name="ck_assistant_session_retention_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_assistant_sessions_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_assistant_session_creator_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_assistant_session_id_company"),
    )
    op.create_index(
        "ix_assistant_sessions_company_status_updated",
        "assistant_sessions",
        ["company_id", "status", "updated_at", "id"],
    )
    op.create_index(
        "ix_assistant_sessions_company_creator_status_updated",
        "assistant_sessions",
        ["company_id", "created_by_membership_id", "status", "updated_at", "id"],
    )
    op.create_index(
        "ix_assistant_sessions_company_creator_updated",
        "assistant_sessions",
        ["company_id", "created_by_membership_id", "updated_at", "id"],
    )
    op.create_index(
        "ix_assistant_sessions_creator_company",
        "assistant_sessions",
        ["created_by_membership_id", "company_id"],
    )
    op.create_index(
        "ix_assistant_sessions_retention_expires_at",
        "assistant_sessions",
        ["retention_expires_at"],
    )

    op.create_table(
        "assistant_session_scopes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("resource_version", sa.String(length=80), nullable=True),
        sa.Column("added_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('tenant', 'client', 'matter', 'ip_docket', 'ip_asset', "
            "'trademark_application', 'ip_proceeding', 'matter_document', 'ip_document')",
            name="ck_assistant_scope_type",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_assistant_scope_ordinal_nonnegative"),
        sa.CheckConstraint(
            "length(trim(scope_id)) > 0",
            name="ck_assistant_scope_id_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "company_id"],
            ["assistant_sessions.id", "assistant_sessions.company_id"],
            name="fk_assistant_scope_session_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_assistant_scope_actor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "scope_type", "scope_id", name="uq_assistant_scope_target"
        ),
        sa.UniqueConstraint("session_id", "ordinal", name="uq_assistant_scope_ordinal"),
    )
    op.create_index(
        "ix_assistant_scopes_company_session",
        "assistant_session_scopes",
        ["company_id", "session_id"],
    )
    op.create_index(
        "ix_assistant_scopes_session_company",
        "assistant_session_scopes",
        ["session_id", "company_id"],
    )
    op.create_index(
        "ix_assistant_scopes_actor_company",
        "assistant_session_scopes",
        ["added_by_membership_id", "company_id"],
    )

    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("retrieval_manifest_json", sa.JSON(), nullable=False),
        sa.Column("permission_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_assistant_turn_sequence_positive"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_assistant_turn_role"),
        sa.CheckConstraint(
            "status IN ('queued', 'completed', 'abstained', 'failed', 'cancelled')",
            name="ck_assistant_turn_status",
        ),
        sa.CheckConstraint(
            "(content_text IS NULL AND content_sha256 IS NULL) OR "
            "(content_text IS NOT NULL AND length(content_sha256) = 64)",
            name="ck_assistant_turn_content_hash",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "company_id"],
            ["assistant_sessions.id", "assistant_sessions.company_id"],
            name="fk_assistant_turn_session_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_assistant_turn_actor_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["model_runs.id"],
            name="fk_assistant_turns_model_run_id_model_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_assistant_turn_id_company"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_assistant_turn_sequence"),
    )
    op.create_index(
        "ix_assistant_turns_company_session",
        "assistant_turns",
        ["company_id", "session_id", "sequence"],
    )
    op.create_index(
        "ix_assistant_turns_session_company",
        "assistant_turns",
        ["session_id", "company_id"],
    )
    op.create_index(
        "ix_assistant_turns_actor_company",
        "assistant_turns",
        ["created_by_membership_id", "company_id"],
    )
    op.create_index(
        "ix_assistant_turns_model_run_id",
        "assistant_turns",
        ["model_run_id"],
    )

    op.create_table(
        "assistant_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("source_version", sa.String(length=80), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_assistant_citation_ordinal_nonnegative"),
        sa.CheckConstraint(
            "length(trim(source_type)) > 0 AND length(trim(source_id)) > 0",
            name="ck_assistant_citation_source_nonempty",
        ),
        sa.CheckConstraint(
            "source_sha256 IS NULL OR length(source_sha256) = 64",
            name="ck_assistant_citation_source_hash",
        ),
        sa.CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)",
            name="ck_assistant_citation_relevance_range",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "company_id"],
            ["assistant_turns.id", "assistant_turns.company_id"],
            name="fk_assistant_citation_turn_company",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", "ordinal", name="uq_assistant_citation_ordinal"),
        sa.UniqueConstraint(
            "turn_id",
            "source_type",
            "source_id",
            "source_version",
            name="uq_assistant_citation_source_version",
        ),
    )
    op.create_index(
        "ix_assistant_citations_company_turn",
        "assistant_citations",
        ["company_id", "turn_id", "ordinal"],
    )
    op.create_index(
        "ix_assistant_citations_turn_company",
        "assistant_citations",
        ["turn_id", "company_id"],
    )


def downgrade() -> None:
    _set_postgres_timeouts()
    connection = op.get_bind()
    for table_name in ASSISTANT_TABLES:
        retained = connection.scalar(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1"))
        if retained is not None:
            raise RuntimeError(
                "Cannot downgrade workspace assistant foundation while retained "
                "assistant evidence exists. Export or purge it through the governed "
                "data-operation workflow first."
            )

    for table_name in ASSISTANT_TABLES:
        op.drop_table(table_name)

    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.drop_constraint(
            "ck_tenant_ai_policy_version_positive",
            type_="check",
        )
        batch.drop_constraint(
            "ck_tenant_ai_policy_assistant_retention_days",
            type_="check",
        )
        batch.drop_column("policy_version")
        batch.drop_column("assistant_retention_days")
        batch.drop_column("workspace_assistant_enabled")
        batch.drop_column("allowed_models_assistant_json")
