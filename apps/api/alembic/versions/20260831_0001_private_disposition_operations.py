"""Add private-worker retry state and disposition checkpoint evidence.

Revision ID: 20260831_0001
Revises: 20260830_0002

MIGRATION-LOCK-RISK: acknowledged - adds three nullable/defaulted columns,
bounded due/maintenance indexes and one state-leading generation-maintenance
index, then creates one empty checkpoint table. PostgreSQL uses metadata-only
additive columns; SQLite test upgrades may rebuild the private event table to
add equivalent checks.
MIGRATION-ROLLBACK: restore-forward after a retry attempt or disposition
checkpoint exists because those rows are security and provider-delay evidence.
DATA-GOVERNANCE-MAP: updated for content-minimized disposition checkpoints and
private projection retry metadata.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260831_0001"
down_revision = "20260830_0002"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()
    op.create_index(
        "ix_private_index_generation_maintenance",
        "private_index_generations",
        ["state", "company_id"],
    )
    with op.batch_alter_table("private_projection_events", recreate="auto") as batch:
        batch.add_column(
            sa.Column(
                "attempt_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_private_projection_event_attempt_count",
            "attempt_count >= 0",
        )
        batch.create_check_constraint(
            "ck_private_projection_event_applied_shape",
            "(status = 'applied' AND applied_at IS NOT NULL "
            "AND next_attempt_at IS NULL) OR status <> 'applied'",
        )
        batch.create_check_constraint(
            "ck_private_projection_event_failed_shape",
            "(status = 'failed' AND error_code IS NOT NULL "
            "AND next_attempt_at IS NULL) OR status <> 'failed'",
        )
        batch.create_unique_constraint(
            "uq_private_projection_event_id_company",
            ["id", "company_id"],
        )
    op.create_index(
        "ix_private_projection_event_due",
        "private_projection_events",
        ["company_id", "status", "next_attempt_at", "created_at", "id"],
    )
    op.create_index(
        "ix_private_projection_event_maintenance",
        "private_projection_events",
        ["status", "company_id"],
    )

    op.create_table(
        "tenant_data_disposition_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("subsystem", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_reference_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("outcome_type", sa.String(length=40), nullable=True),
        sa.Column("provider_name", sa.String(length=80), nullable=True),
        sa.Column("provider_receipt_ref", sa.String(length=255), nullable=True),
        sa.Column("exception_code", sa.String(length=120), nullable=True),
        sa.Column("expected_resolution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("private_event_id", sa.String(length=36), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'exception', 'failed')",
            name="ck_data_disposition_checkpoint_status",
        ),
        sa.CheckConstraint(
            "outcome_type IS NULL OR outcome_type IN ('receipt', 'deletion_delay_exception')",
            name="ck_data_disposition_checkpoint_outcome_type",
        ),
        sa.CheckConstraint(
            "length(target_reference_hash) = 64",
            name="ck_data_disposition_checkpoint_target_hash",
        ),
        sa.CheckConstraint(
            "evidence_sha256 IS NULL OR length(evidence_sha256) = 64",
            name="ck_data_disposition_checkpoint_evidence_hash",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_data_disposition_checkpoint_attempt_count",
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'exception') OR ("
            "private_event_id IS NOT NULL AND attempt_count > 0 "
            "AND evidence_json IS NOT NULL)",
            name="ck_data_disposition_checkpoint_terminal_evidence",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND outcome_type = 'receipt' "
            "AND provider_receipt_ref IS NOT NULL AND evidence_sha256 IS NOT NULL "
            "AND completed_at IS NOT NULL AND exception_code IS NULL) "
            "OR status <> 'completed'",
            name="ck_data_disposition_checkpoint_completed_shape",
        ),
        sa.CheckConstraint(
            "(status = 'exception' AND outcome_type = 'deletion_delay_exception' "
            "AND exception_code IS NOT NULL AND evidence_sha256 IS NOT NULL "
            "AND completed_at IS NOT NULL AND provider_receipt_ref IS NULL "
            "AND provider_name IS NOT NULL) "
            "OR status <> 'exception'",
            name="ck_data_disposition_checkpoint_exception_shape",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "company_id"],
            ["tenant_data_operations.id", "tenant_data_operations.company_id"],
            name="fk_data_disposition_checkpoint_operation_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["private_event_id", "company_id"],
            ["private_projection_events.id", "private_projection_events.company_id"],
            name="fk_data_disposition_checkpoint_private_event_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "subsystem",
            "target_type",
            "target_reference_hash",
            name="uq_data_disposition_checkpoint_target",
        ),
    )
    op.create_index(
        "ix_data_disposition_checkpoint_company_status",
        "tenant_data_disposition_checkpoints",
        ["company_id", "status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_data_disposition_checkpoint_operation",
        "tenant_data_disposition_checkpoints",
        ["operation_id", "company_id", "subsystem"],
    )
    op.create_index(
        "ix_fk_data_disposition_checkpoint_private_event",
        "tenant_data_disposition_checkpoints",
        ["private_event_id", "company_id"],
    )


def downgrade() -> None:
    _set_postgres_timeouts()
    checkpoint_count = int(
        op.get_bind().scalar(sa.text("SELECT count(*) FROM tenant_data_disposition_checkpoints"))
        or 0
    )
    retry_evidence_count = int(
        op.get_bind().scalar(
            sa.text(
                "SELECT count(*) FROM private_projection_events "
                "WHERE attempt_count > 0 OR last_attempt_at IS NOT NULL "
                "OR next_attempt_at IS NOT NULL"
            )
        )
        or 0
    )
    if checkpoint_count or retry_evidence_count:
        raise RuntimeError(
            "Refusing to discard private retry or disposition evidence; restore-forward."
        )

    op.drop_index(
        "ix_fk_data_disposition_checkpoint_private_event",
        table_name="tenant_data_disposition_checkpoints",
    )
    op.drop_index(
        "ix_data_disposition_checkpoint_operation",
        table_name="tenant_data_disposition_checkpoints",
    )
    op.drop_index(
        "ix_data_disposition_checkpoint_company_status",
        table_name="tenant_data_disposition_checkpoints",
    )
    op.drop_table("tenant_data_disposition_checkpoints")

    op.drop_index(
        "ix_private_projection_event_maintenance",
        table_name="private_projection_events",
    )
    op.drop_index("ix_private_projection_event_due", table_name="private_projection_events")
    with op.batch_alter_table("private_projection_events", recreate="auto") as batch:
        batch.drop_constraint("uq_private_projection_event_id_company", type_="unique")
        batch.drop_constraint("ck_private_projection_event_failed_shape", type_="check")
        batch.drop_constraint("ck_private_projection_event_applied_shape", type_="check")
        batch.drop_constraint("ck_private_projection_event_attempt_count", type_="check")
        batch.drop_column("next_attempt_at")
        batch.drop_column("last_attempt_at")
        batch.drop_column("attempt_count")
    op.drop_index(
        "ix_private_index_generation_maintenance",
        table_name="private_index_generations",
    )
