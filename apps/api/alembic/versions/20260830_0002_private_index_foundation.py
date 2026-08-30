"""Add tenant-private index generations and revocation-safe access manifests.

Revision ID: 20260830_0002
Revises: 20260830_0001

MIGRATION-LOCK-RISK: acknowledged - creates five empty additive tables and
their indexes; no existing tenant, document, assistant, or corpus row is
scanned or rewritten.  Public authority tables are deliberately untouched.
MIGRATION-ROLLBACK: restore-forward after a projection event or saved-output
manifest exists because those rows retain revocation and access evidence.
DATA-GOVERNANCE-MAP: updated for private chunks, ACL scopes, generations,
tombstone events, and content-free saved-output access manifests.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260830_0002"
down_revision = "20260830_0001"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()
    op.create_table(
        "private_index_generations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("generation_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "access_policy_generation", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("tombstone_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expected_projection_count", sa.Integer(), nullable=True),
        sa.Column("verified_projection_count", sa.Integer(), nullable=True),
        sa.Column("verification_sha256", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('building', 'ready', 'active', 'retired', 'failed')",
            name="ck_private_index_generation_state",
        ),
        sa.CheckConstraint(
            "generation_number > 0 AND access_policy_generation > 0 "
            "AND tombstone_generation >= 0",
            name="ck_private_index_generation_versions",
        ),
        sa.CheckConstraint(
            "(state = 'active' AND activated_at IS NOT NULL) OR state <> 'active'",
            name="ck_private_index_generation_active_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "company_id", name="uq_private_index_generation_id_company"
        ),
        sa.UniqueConstraint(
            "company_id",
            "generation_number",
            name="uq_private_index_generation_company_number",
        ),
    )
    op.create_index(
        "ix_private_index_generation_company_state",
        "private_index_generations",
        ["company_id", "state", "generation_number"],
    )
    op.create_index(
        "uq_private_index_generation_one_active",
        "private_index_generations",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "private_index_projections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("generation_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("source_version", sa.String(length=120), nullable=False),
        sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("confidentiality", sa.String(length=24), nullable=False),
        sa.Column("is_privileged", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source_state", sa.String(length=24), nullable=False),
        sa.Column("approval_state", sa.String(length=24), nullable=False),
        sa.Column("access_policy_version", sa.Integer(), nullable=False),
        sa.Column("access_policy_generation", sa.Integer(), nullable=False),
        sa.Column("tombstone_generation", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("embedding_version", sa.String(length=80), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("is_tombstoned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstone_reason", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('client', 'matter', 'matter_document', 'ip_docket', "
            "'ip_document')",
            name="ck_private_projection_source_type",
        ),
        sa.CheckConstraint(
            "chunk_ordinal >= 0", name="ck_private_projection_chunk_ordinal"
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name="ck_private_projection_content_hash"
        ),
        sa.CheckConstraint(
            "confidentiality IN ('internal', 'confidential', 'restricted')",
            name="ck_private_projection_confidentiality",
        ),
        sa.CheckConstraint(
            "source_state IN ('active', 'approved', 'filed', 'indexed', 'quarantined', "
            "'retired', 'deleted')",
            name="ck_private_projection_source_state",
        ),
        sa.CheckConstraint(
            "approval_state IN ('not_required', 'approved', 'rejected', 'withdrawn')",
            name="ck_private_projection_approval_state",
        ),
        sa.CheckConstraint(
            "access_policy_generation > 0 AND tombstone_generation >= 0",
            name="ck_private_projection_generations",
        ),
        sa.CheckConstraint(
            "embedding_dimensions IS NULL OR embedding_dimensions > 0",
            name="ck_private_projection_embedding_dimensions",
        ),
        sa.CheckConstraint(
            "(is_tombstoned = false AND tombstoned_at IS NULL "
            "AND tombstone_reason IS NULL) OR "
            "(is_tombstoned = true AND tombstoned_at IS NOT NULL "
            "AND tombstone_reason IS NOT NULL AND content_text = '' "
            "AND embedding_json IS NULL)",
            name="ck_private_projection_tombstone_shape",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id", "company_id"],
            ["private_index_generations.id", "private_index_generations.company_id"],
            name="fk_private_projection_generation_company",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_private_projection_id_company"),
        sa.UniqueConstraint(
            "generation_id",
            "source_type",
            "source_id",
            "source_version",
            "chunk_ordinal",
            name="uq_private_projection_source_chunk",
        ),
    )
    op.create_index(
        "ix_private_projection_prefilter",
        "private_index_projections",
        ["company_id", "generation_id", "is_tombstoned", "source_type", "source_id"],
    )
    op.create_index(
        "ix_private_projection_generation_policy",
        "private_index_projections",
        ["generation_id", "access_policy_generation", "tombstone_generation"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.execute(
            sa.text(
                "CREATE INDEX ix_private_projection_content_trgm "
                "ON private_index_projections USING gin "
                "(lower(content_text) gin_trgm_ops) WHERE is_tombstoned = false"
            )
        )

    op.create_table(
        "private_index_projection_scopes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("projection_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=24), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("matter_id", sa.String(length=36), nullable=True),
        sa.Column("ip_docket_id", sa.String(length=36), nullable=True),
        sa.Column("access_policy_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(scope_type = 'client' AND client_id = scope_id AND matter_id IS NULL "
            "AND ip_docket_id IS NULL) OR "
            "(scope_type = 'matter' AND matter_id = scope_id AND client_id IS NULL "
            "AND ip_docket_id IS NULL) OR "
            "(scope_type = 'ip_docket' AND ip_docket_id = scope_id AND client_id IS NULL "
            "AND matter_id IS NULL)",
            name="ck_private_projection_scope_typed_target",
        ),
        sa.CheckConstraint(
            "access_policy_version >= 0",
            name="ck_private_projection_scope_policy_version",
        ),
        sa.ForeignKeyConstraint(
            ["projection_id", "company_id"],
            ["private_index_projections.id", "private_index_projections.company_id"],
            name="fk_private_projection_scope_projection_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            name="fk_private_projection_scope_client_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_private_projection_scope_matter_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_private_projection_scope_docket_company",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "projection_id",
            "scope_type",
            "scope_id",
            name="uq_private_projection_scope_target",
        ),
    )
    op.create_index(
        "ix_private_projection_scope_company_target",
        "private_index_projection_scopes",
        ["company_id", "scope_type", "scope_id", "projection_id"],
    )
    op.create_index(
        "ix_fk_private_projection_scope_projection",
        "private_index_projection_scopes",
        ["projection_id", "company_id"],
    )
    op.create_index(
        "ix_fk_private_projection_scope_client",
        "private_index_projection_scopes",
        ["client_id", "company_id"],
    )
    op.create_index(
        "ix_fk_private_projection_scope_matter",
        "private_index_projection_scopes",
        ["matter_id", "company_id"],
    )
    op.create_index(
        "ix_fk_private_projection_scope_docket",
        "private_index_projection_scopes",
        ["ip_docket_id", "company_id"],
    )

    op.create_table(
        "private_projection_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("generation_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=160), nullable=False),
        sa.Column("target_version", sa.String(length=120), nullable=True),
        sa.Column("access_policy_generation", sa.Integer(), nullable=False),
        sa.Column("tombstone_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=False),
        sa.Column("affected_projection_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("affected_saved_output_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('source_changed', 'access_changed', 'revoked', "
            "'tombstoned', 'reindex')",
            name="ck_private_projection_event_type",
        ),
        sa.CheckConstraint(
            "target_type IN ('tenant', 'client', 'matter', 'matter_document', "
            "'ip_docket', 'ip_document')",
            name="ck_private_projection_event_target_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'failed')",
            name="ck_private_projection_event_status",
        ),
        sa.CheckConstraint(
            "access_policy_generation > 0 AND tombstone_generation >= 0",
            name="ck_private_projection_event_generations",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id", "company_id"],
            ["private_index_generations.id", "private_index_generations.company_id"],
            name="fk_private_projection_event_generation_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_private_projection_event_actor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_private_projection_event_idempotency"
        ),
    )
    op.create_index(
        "ix_private_projection_event_company_status",
        "private_projection_events",
        ["company_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_private_projection_event_company_target",
        "private_projection_events",
        ["company_id", "target_type", "target_id", "created_at"],
    )
    op.create_index(
        "ix_fk_private_projection_event_generation",
        "private_projection_events",
        ["generation_id", "company_id"],
    )
    op.create_index(
        "ix_fk_private_projection_event_actor",
        "private_projection_events",
        ["actor_membership_id", "company_id"],
    )

    op.create_table(
        "private_saved_output_access",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("assistant_turn_id", sa.String(length=36), nullable=False),
        sa.Column("generation_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("source_version", sa.String(length=120), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("access_policy_generation", sa.Integer(), nullable=False),
        sa.Column("tombstone_generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("locked_reason", sa.String(length=120), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reauthorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('accessible', 'reauthorization_required', 'locked', 'redacted')",
            name="ck_private_saved_output_access_state",
        ),
        sa.CheckConstraint(
            "access_policy_generation > 0 AND tombstone_generation >= 0",
            name="ck_private_saved_output_generations",
        ),
        sa.CheckConstraint(
            "(state = 'accessible' AND locked_at IS NULL AND locked_reason IS NULL) OR "
            "(state <> 'accessible' AND locked_at IS NOT NULL AND locked_reason IS NOT NULL)",
            name="ck_private_saved_output_lock_shape",
        ),
        sa.ForeignKeyConstraint(
            ["assistant_turn_id", "company_id"],
            ["assistant_turns.id", "assistant_turns.company_id"],
            name="fk_private_saved_output_turn_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id", "company_id"],
            ["private_index_generations.id", "private_index_generations.company_id"],
            name="fk_private_saved_output_generation_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistant_turn_id",
            "source_type",
            "source_id",
            "source_version",
            name="uq_private_saved_output_source_version",
        ),
    )
    op.create_index(
        "ix_private_saved_output_company_turn_state",
        "private_saved_output_access",
        ["company_id", "assistant_turn_id", "state"],
    )
    op.create_index(
        "ix_private_saved_output_company_source",
        "private_saved_output_access",
        ["company_id", "source_type", "source_id", "state"],
    )
    op.create_index(
        "ix_fk_private_saved_output_generation",
        "private_saved_output_access",
        ["generation_id", "company_id"],
    )


def downgrade() -> None:
    _set_postgres_timeouts()
    bind = op.get_bind()
    retained = any(
        bind.scalar(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")) is not None
        for table_name in (
            "private_saved_output_access",
            "private_projection_events",
            "private_index_projections",
        )
    )
    if retained:
        raise RuntimeError(
            "Cannot downgrade while private projection, revocation, or saved-output "
            "evidence exists. Use governed disposition and restore-forward."
        )
    op.drop_table("private_saved_output_access")
    op.drop_table("private_projection_events")
    op.drop_table("private_index_projection_scopes")
    op.drop_table("private_index_projections")
    op.drop_table("private_index_generations")
