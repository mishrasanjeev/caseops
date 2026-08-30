"""Add append-only trademark filing transaction evidence.

Revision ID: 20260830_0003
Revises: 20260830_0002

MIGRATION-LOCK-RISK: acknowledged - creates one empty additive table, its
indexes, and append-only triggers; no existing application is scanned or
rewritten.
MIGRATION-ROLLBACK: restore-forward after any filing transaction exists because
the rows are retained legal transaction and acknowledgement evidence.
DATA-GOVERNANCE-MAP: updated for filing transaction evidence and actor lineage.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260830_0003"
down_revision = "20260830_0002"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def _create_append_only_guard() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION prevent_ip_filing_transaction_mutation()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'IP filing transactions are append-only';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_filing_transactions_append_only
                BEFORE UPDATE OR DELETE ON ip_filing_transactions
                FOR EACH ROW EXECUTE FUNCTION prevent_ip_filing_transaction_mutation()
                """
            )
        )
        return
    if bind.dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER trg_ip_filing_transactions_append_only_{operation.lower()}
                    BEFORE {operation} ON ip_filing_transactions
                    BEGIN
                        SELECT RAISE(ABORT, 'IP filing transactions are append-only');
                    END
                    """
                )
            )


def _drop_append_only_guard() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_ip_filing_transactions_append_only "
                "ON ip_filing_transactions"
            )
        )
        op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_ip_filing_transaction_mutation()"))
    elif bind.dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ip_filing_transactions_append_only_update"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ip_filing_transactions_append_only_delete"))


def upgrade() -> None:
    _set_postgres_timeouts()
    op.create_table(
        "ip_filing_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_kind", sa.String(length=40), nullable=False),
        sa.Column("attempt_key", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("related_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("filing_event_id", sa.String(length=36), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_confirmation", sa.String(length=500), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("recorded_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "transaction_kind IN ('submitted', 'fee_paid', "
            "'acknowledgement_received', 'defect_recorded', 'rejected', "
            "'resubmitted', 'accepted')",
            name="ck_ip_filing_transaction_kind",
        ),
        sa.CheckConstraint(
            "(transaction_kind = 'submitted' AND related_transaction_id IS NULL) OR "
            "(transaction_kind = 'fee_paid') OR "
            "(transaction_kind NOT IN ('submitted', 'fee_paid') "
            "AND related_transaction_id IS NOT NULL)",
            name="ck_ip_filing_transaction_related_shape",
        ),
        sa.CheckConstraint(
            "(transaction_kind = 'accepted' AND filing_event_id IS NOT NULL "
            "AND authorized_confirmation IS NOT NULL) OR "
            "(transaction_kind <> 'accepted' AND filing_event_id IS NULL "
            "AND authorized_confirmation IS NULL)",
            name="ck_ip_filing_transaction_acceptance_shape",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_ip_filing_transaction_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_filing_transaction_docket_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_filing_transaction_application_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_transaction_id", "company_id"],
            ["ip_filing_transactions.id", "ip_filing_transactions.company_id"],
            name="fk_ip_filing_transaction_related_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["filing_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_filing_transaction_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_filing_transaction_recorder_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_filing_transaction_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "application_id",
            "idempotency_key",
            name="uq_ip_filing_transaction_idempotency",
        ),
    )
    op.create_index(
        "ix_ip_filing_transactions_company_application",
        "ip_filing_transactions",
        ["company_id", "application_id", "occurred_at"],
    )
    op.create_index(
        "ix_ip_filing_transactions_attempt",
        "ip_filing_transactions",
        ["company_id", "application_id", "attempt_key", "occurred_at"],
    )
    op.create_index(
        "uq_ip_filing_transaction_one_acceptance",
        "ip_filing_transactions",
        ["company_id", "application_id"],
        unique=True,
        postgresql_where=sa.text("transaction_kind = 'accepted'"),
        sqlite_where=sa.text("transaction_kind = 'accepted'"),
    )
    op.create_index(
        "uq_ip_filing_transaction_attempt_submission",
        "ip_filing_transactions",
        ["company_id", "application_id", "attempt_key"],
        unique=True,
        postgresql_where=sa.text("transaction_kind IN ('submitted', 'resubmitted')"),
        sqlite_where=sa.text("transaction_kind IN ('submitted', 'resubmitted')"),
    )
    _create_append_only_guard()


def downgrade() -> None:
    _set_postgres_timeouts()
    retained = (
        op.get_bind().execute(sa.text("SELECT count(*) FROM ip_filing_transactions")).scalar_one()
    )
    if retained:
        raise RuntimeError("refusing to downgrade: retained IP filing transaction evidence exists")
    _drop_append_only_guard()
    op.drop_index(
        "uq_ip_filing_transaction_attempt_submission",
        table_name="ip_filing_transactions",
    )
    op.drop_index(
        "uq_ip_filing_transaction_one_acceptance",
        table_name="ip_filing_transactions",
    )
    op.drop_index(
        "ix_ip_filing_transactions_attempt",
        table_name="ip_filing_transactions",
    )
    op.drop_index(
        "ix_ip_filing_transactions_company_application",
        table_name="ip_filing_transactions",
    )
    op.drop_table("ip_filing_transactions")
