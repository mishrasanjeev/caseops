"""Persist source renewal cadence and canonical-intent occurrence evidence.

DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged - new empty tables and one additive JSON column.
MIGRATION-ROLLBACK: restore-forward - retained occurrences/policy refuse downgrade.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261015_0001"
down_revision = "20261011_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ip_workspace_configurations",
        sa.Column("renewal_reminder_policy_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "ip_portfolio_renewal_series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("recipient_membership_id", sa.String(36), nullable=False),
        sa.Column("timezone", sa.String(64)),
        sa.Column("cadence_days", sa.Integer()),
        sa.Column("delivery_time", sa.String(5)),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("last_delivery_key", sa.String(64)),
        sa.Column("policy_error", sa.String(80)),
        sa.Column("reconcile_after", sa.DateTime(timezone=True)),
        sa.Column("next_reminder_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancellation_reason", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "docket_id", name="uq_ip_renewal_series_docket"),
        sa.UniqueConstraint("id", "company_id", "docket_id", name="uq_ip_renewal_series_scope"),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "source_version"],
            [
                "ip_trademark_particular_versions.docket_id",
                "ip_trademark_particular_versions.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "generation > 0 AND (cadence_days IS NULL OR cadence_days BETWEEN 1 AND 31) "
            "AND ((policy_error IS NULL AND timezone IS NOT NULL AND cadence_days IS NOT NULL "
            "AND delivery_time IS NOT NULL) OR (policy_error IS NOT NULL "
            "AND next_reminder_at IS NULL AND reconcile_after IS NOT NULL))",
            name="ck_ip_renewal_series_policy",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "last_delivery_key"],
            [
                "notification_delivery_intents.company_id",
                "notification_delivery_intents.idempotency_key",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_ip_renewal_series_retry",
        "ip_portfolio_renewal_series",
        ["reconcile_after", "company_id", "id"],
    )
    op.create_index(
        "ix_ip_renewal_series_due",
        "ip_portfolio_renewal_series",
        ["next_reminder_at", "company_id", "id"],
    )
    op.create_table(
        "ip_portfolio_renewal_occurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("series_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("recipient_membership_id", sa.String(36), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("local_on", sa.Date(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_key", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("series_id", "generation", "local_on", name="uq_ip_renewal_occurrence"),
        sa.ForeignKeyConstraint(
            ["series_id", "company_id", "docket_id"],
            [
                "ip_portfolio_renewal_series.id",
                "ip_portfolio_renewal_series.company_id",
                "ip_portfolio_renewal_series.docket_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "source_version"],
            [
                "ip_trademark_particular_versions.docket_id",
                "ip_trademark_particular_versions.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "delivery_key"],
            [
                "notification_delivery_intents.company_id",
                "notification_delivery_intents.idempotency_key",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("generation > 0", name="ck_ip_renewal_occurrence_generation"),
    )
    op.create_index(
        "ix_ip_renewal_occurrence_history",
        "ip_portfolio_renewal_occurrences",
        ["company_id", "docket_id", "local_on"],
    )
    op.create_index(
        "ix_ip_renewal_occurrence_delivery",
        "ip_portfolio_renewal_occurrences",
        ["company_id", "delivery_key"],
    )

    op.create_index(
        "ix_ip_renewal_occurrence_current",
        "ip_portfolio_renewal_occurrences",
        ["company_id", "docket_id", "source_version", "generation", "local_on", "created_at", "id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for name in ("ip_portfolio_renewal_occurrences", "ip_portfolio_renewal_series"):
        if connection.scalar(sa.text(f"SELECT 1 FROM {name} LIMIT 1")) is not None:
            raise RuntimeError(
                "Restore-forward required: retained portfolio renewal evidence exists."
            )
    configured = connection.scalar(
        sa.text(
            "SELECT 1 FROM ip_workspace_configurations "
            "WHERE CAST(renewal_reminder_policy_json AS TEXT) NOT IN ('{}', 'null') LIMIT 1"
        )
    )
    if configured is not None:
        raise RuntimeError("Restore-forward required: configured renewal reminder policy exists.")
    op.drop_table("ip_portfolio_renewal_occurrences")
    op.drop_table("ip_portfolio_renewal_series")
    op.drop_column("ip_workspace_configurations", "renewal_reminder_policy_json")
