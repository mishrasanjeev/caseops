"""Gemini fallback monthly spend cap. DATA-GOVERNANCE-MAP: updated

Revision ID: 20261101_0002
Revises: 20261101_0001
Map: docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml.

Owner decision, 1 November 2026: when OpenAI is out of quota or unavailable,
CaseOps may fall back to gemini-3.8-flash on the managed Google Cloud endpoint,
capped at INR 10,000 (1,000,000 paise) of fresh Gemini spend per IST month.
Two account-level, tenant-independent tables hold that cap: one row per month
(created on first use with zero opening liability) and one content-free
worst-case admission per Gemini transport. No prompt, output, tenant, matter or
user identity is stored. This is separate from the shared AI money guard tables,
which stay off by default.

MIGRATION-LOCK-RISK: acknowledged - two new empty tables and one index on a
newly created empty table; no existing table is touched.
MIGRATION-ROLLBACK: restore-forward - populated spend evidence refuses
downgrade; an application rollback retains this additive financial schema.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261101_0002"
down_revision = "20261101_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_gemini_spend_months",
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("limit_minor", sa.Integer(), nullable=False),
        sa.Column("admitted_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "limit_minor > 0 AND limit_minor <= 1000000",
            name="ck_ai_gemini_spend_limit_owner_ceiling",
        ),
        sa.CheckConstraint(
            "admitted_minor >= 0 AND admitted_minor <= limit_minor",
            name="ck_ai_gemini_spend_within_limit",
        ),
    )
    op.create_table(
        "ai_gemini_spend_admissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "month",
            sa.String(7),
            sa.ForeignKey("ai_gemini_spend_months.month", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("upper_bound_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "upper_bound_minor > 0", name="ck_ai_gemini_spend_admission_positive"
        ),
    )
    op.create_index(
        "ix_ai_gemini_spend_admissions_month", "ai_gemini_spend_admissions", ["month"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    for name, key in (
        ("ai_gemini_spend_admissions", "id"),
        ("ai_gemini_spend_months", "month"),
    ):
        table = sa.table(name, sa.column(key))
        if connection.scalar(sa.select(sa.literal(1)).select_from(table).limit(1)) is not None:
            raise RuntimeError("Refusing to delete retained Gemini spending evidence.")
    op.drop_index(
        "ix_ai_gemini_spend_admissions_month", table_name="ai_gemini_spend_admissions"
    )
    op.drop_table("ai_gemini_spend_admissions")
    op.drop_table("ai_gemini_spend_months")
