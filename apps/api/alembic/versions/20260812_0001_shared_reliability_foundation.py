"""Add neutral idempotency and transactional-outbox foundations.

Revision ID: 20260812_0001
Revises: 20260811_0005
Create Date: 2026-08-12

This is an additive, dark migration.  Downgrading an empty rehearsal database
drops the three new tables.  Once any durable record exists, downgrade fails
closed: application rollback keeps the additive schema and operators roll
forward rather than deleting request or delivery evidence.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260812_0001"
down_revision = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "api_idempotency_records",
    "domain_outbox_events",
    "domain_consumer_effects",
)


def _lock_tables_for_populated_downgrade_check(bind: sa.Connection) -> None:
    """Exclude mixed-revision writers before deciding that evidence is empty."""

    if bind.dialect.name != "postgresql":
        return
    # PostgreSQL ACCESS SHARE (taken by SELECT count(*)) is compatible with
    # INSERT.  Lock every evidence owner in one fixed order first so a writer
    # cannot commit a new durable row between the emptiness check and DROP.
    for table in _TABLES:
        bind.execute(sa.text(f'LOCK TABLE "{table}" IN ACCESS EXCLUSIVE MODE'))


def upgrade() -> None:
    op.create_table(
        "api_idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("actor_scope", sa.String(length=160), nullable=False),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=True),
        sa.Column("actor_company_id", sa.String(length=36), nullable=True),
        sa.Column("http_method", sa.String(length=12), nullable=False),
        sa.Column("operation", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'processing'"),
        ),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column(
            "claim_generation", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("result_type", sa.String(length=80), nullable=True),
        sa.Column("result_id", sa.String(length=160), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "state IN ('processing', 'completed', 'failed')",
            name="ck_api_idempotency_state",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_api_idempotency_request_hash_length",
        ),
        sa.CheckConstraint(
            "claim_generation > 0",
            name="ck_api_idempotency_claim_generation_positive",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_api_idempotency_expiry_after_create",
        ),
        sa.CheckConstraint(
            "(actor_membership_id IS NULL AND actor_company_id IS NULL) OR "
            "(actor_membership_id IS NOT NULL AND actor_company_id = company_id)",
            name="ck_api_idempotency_actor_company",
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND claim_token IS NOT NULL AND "
            "claim_expires_at IS NOT NULL AND finished_at IS NULL) OR "
            "(state IN ('completed', 'failed') AND claim_token IS NULL AND "
            "claim_expires_at IS NULL AND finished_at IS NOT NULL)",
            name="ck_api_idempotency_claim_state",
        ),
        sa.CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name="ck_api_idempotency_response_status",
        ),
        sa.CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL)",
            name="ck_api_idempotency_result_reference",
        ),
        sa.CheckConstraint(
            "state <> 'completed' OR response_status IS NOT NULL",
            name="ck_api_idempotency_completed_response",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "actor_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_api_idempotency_actor_company",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_api_idempotency_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "actor_scope",
            "http_method",
            "operation",
            "idempotency_key",
            name="uq_api_idempotency_scope_key",
        ),
    )
    op.create_index(
        "ix_api_idempotency_scope_lookup",
        "api_idempotency_records",
        ["company_id", "actor_scope", "operation", "idempotency_key"],
    )
    op.create_index(
        "ix_api_idempotency_expiry",
        "api_idempotency_records",
        ["expires_at", "state"],
    )

    op.create_table(
        "domain_outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=160), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_command_id", sa.String(length=160), nullable=True),
        sa.Column("source_event_id", sa.String(length=160), nullable=True),
        sa.Column("producer", sa.String(length=120), nullable=False),
        sa.Column("producer_revision", sa.String(length=64), nullable=True),
        sa.Column("confidentiality", sa.String(length=24), nullable=False),
        sa.Column("correlation_id", sa.String(length=160), nullable=False),
        sa.Column("causation_id", sa.String(length=160), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fence_version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_error_redacted", sa.String(length=500), nullable=True),
        sa.Column("dead_letter_reason", sa.String(length=160), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'retry_scheduled', "
            "'succeeded', 'dead_letter')",
            name="ck_domain_outbox_state",
        ),
        sa.CheckConstraint(
            "confidentiality IN ('internal', 'confidential', 'privileged')",
            name="ck_domain_outbox_confidentiality",
        ),
        sa.CheckConstraint(
            "schema_version > 0", name="ck_domain_outbox_schema_version_positive"
        ),
        sa.CheckConstraint(
            "aggregate_version >= 0",
            name="ck_domain_outbox_aggregate_version_nonnegative",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_domain_outbox_payload_hash_length",
        ),
        sa.CheckConstraint(
            "source_command_id IS NOT NULL OR source_event_id IS NOT NULL",
            name="ck_domain_outbox_source_reference",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_domain_outbox_attempts",
        ),
        sa.CheckConstraint(
            "fence_version >= 0", name="ck_domain_outbox_fence_nonnegative"
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_owner IS NOT NULL AND "
            "lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_owner IS NULL AND "
            "lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_domain_outbox_lease_state",
        ),
        sa.CheckConstraint(
            "state <> 'retry_scheduled' OR next_attempt_at IS NOT NULL",
            name="ck_domain_outbox_retry_time",
        ),
        sa.CheckConstraint(
            "(state = 'succeeded' AND completed_at IS NOT NULL) OR "
            "(state <> 'succeeded' AND completed_at IS NULL)",
            name="ck_domain_outbox_completed_state",
        ),
        sa.CheckConstraint(
            "(state = 'dead_letter' AND dead_lettered_at IS NOT NULL AND "
            "dead_letter_reason IS NOT NULL) OR "
            "(state <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name="ck_domain_outbox_dead_letter_state",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_domain_outbox_id_company"),
        sa.UniqueConstraint(
            "company_id", "event_key", name="uq_domain_outbox_company_event_key"
        ),
    )
    op.create_index(
        "ix_domain_outbox_claim",
        "domain_outbox_events",
        ["state", "next_attempt_at", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_domain_outbox_company_state",
        "domain_outbox_events",
        ["company_id", "state", "created_at"],
    )
    op.create_index(
        "ix_domain_outbox_aggregate",
        "domain_outbox_events",
        ["company_id", "aggregate_type", "aggregate_id", "aggregate_version"],
    )
    op.create_index(
        "ix_domain_outbox_correlation",
        "domain_outbox_events",
        ["company_id", "correlation_id"],
    )

    op.create_table(
        "domain_consumer_effects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("outbox_event_id", sa.String(length=36), nullable=False),
        sa.Column("consumer_name", sa.String(length=120), nullable=False),
        sa.Column("consumer_version", sa.String(length=64), nullable=False),
        sa.Column("effect_key", sa.String(length=200), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'processing'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("outbox_fence_version", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fence_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("result_type", sa.String(length=80), nullable=True),
        sa.Column("result_id", sa.String(length=160), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("last_error_redacted", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('processing', 'completed', 'failed')",
            name="ck_domain_consumer_effect_state",
        ),
        sa.CheckConstraint(
            "attempts > 0", name="ck_domain_consumer_effect_attempts_positive"
        ),
        sa.CheckConstraint(
            "fence_version > 0 AND outbox_fence_version > 0",
            name="ck_domain_consumer_effect_fences_positive",
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_owner IS NOT NULL AND "
            "lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND "
            "completed_at IS NULL AND failed_at IS NULL) OR "
            "(state = 'completed' AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NOT NULL AND "
            "failed_at IS NULL) OR "
            "(state = 'failed' AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NULL AND "
            "failed_at IS NOT NULL)",
            name="ck_domain_consumer_effect_lease_state",
        ),
        sa.CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL)",
            name="ck_domain_consumer_effect_result_reference",
        ),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_domain_consumer_effect_result_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["outbox_event_id", "company_id"],
            ["domain_outbox_events.id", "domain_outbox_events.company_id"],
            name="fk_domain_consumer_effect_outbox_company",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "company_id", name="uq_domain_consumer_effect_id_company"
        ),
        sa.UniqueConstraint(
            "company_id",
            "outbox_event_id",
            "consumer_name",
            name="uq_domain_consumer_effect_event_consumer",
        ),
        sa.UniqueConstraint(
            "company_id",
            "consumer_name",
            "effect_key",
            name="uq_domain_consumer_effect_key",
        ),
    )
    op.create_index(
        "ix_domain_consumer_effect_claim",
        "domain_consumer_effects",
        ["state", "lease_expires_at", "updated_at"],
    )
    op.create_index(
        "ix_domain_consumer_effect_company_consumer",
        "domain_consumer_effects",
        ["company_id", "consumer_name", "state"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    _lock_tables_for_populated_downgrade_check(bind)
    populated = {
        table: int(bind.scalar(sa.text(f"SELECT count(*) FROM {table}")) or 0)
        for table in _TABLES
    }
    populated = {table: count for table, count in populated.items() if count}
    if populated:
        raise RuntimeError(
            "Shared reliability evidence exists; keep the additive schema and "
            f"roll application code forward instead of deleting rows: {populated}"
        )

    op.drop_table("domain_consumer_effects")
    op.drop_table("domain_outbox_events")
    op.drop_table("api_idempotency_records")


__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
)
