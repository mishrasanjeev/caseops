"""Shared account AI money admission. DATA-GOVERNANCE-MAP: updated

MIGRATION-LOCK-RISK: acknowledged - the index is on a newly created empty table.
MIGRATION-ROLLBACK: restore-forward - populated evidence refuses downgrade;
production application rollback retains this additive financial schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20261011_0001"
down_revision = "20260928_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_spend_months",
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("limit_minor", sa.Integer(), nullable=False),
        sa.Column("opening_spend_minor", sa.Integer(), nullable=False),
        sa.Column("admitted_minor", sa.Integer(), nullable=False),
        sa.Column("inr_per_usd_all_in", sa.Numeric(12, 6), nullable=False),
        sa.Column("pricing_json", sa.JSON(), nullable=False),
        sa.Column("opening_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "limit_minor > 0 AND limit_minor <= 1000000", name="ck_ai_spend_limit_owner_ceiling"
        ),
        sa.CheckConstraint(
            "opening_spend_minor >= 0 AND admitted_minor >= opening_spend_minor",
            name="ck_ai_spend_nonnegative",
        ),
        sa.CheckConstraint("inr_per_usd_all_in > 0", name="ck_ai_spend_fx_positive"),
    )
    op.create_table(
        "ai_provider_spend_admissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "month",
            sa.String(7),
            sa.ForeignKey("ai_provider_spend_months.month", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("upper_bound_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("upper_bound_minor > 0", name="ck_ai_spend_admission_positive"),
    )
    op.create_index(
        "ix_ai_provider_spend_admissions_month", "ai_provider_spend_admissions", ["month"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    for name in ("ai_provider_spend_admissions", "ai_provider_spend_months"):
        table = sa.table(name, sa.column("id" if name.endswith("admissions") else "month"))
        if connection.scalar(sa.select(sa.literal(1)).select_from(table).limit(1)) is not None:
            raise RuntimeError("Refusing to delete retained AI spending evidence during downgrade.")
    op.drop_index(
        "ix_ai_provider_spend_admissions_month", table_name="ai_provider_spend_admissions"
    )
    op.drop_table("ai_provider_spend_admissions")
    op.drop_table("ai_provider_spend_months")
