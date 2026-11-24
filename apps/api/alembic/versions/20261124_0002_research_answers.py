"""Source-verified three-part research answers.

Revision ID: 20261124_0002
Revises: 20261124_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One new empty table with nonunique indexes
on its own columns references existing tenant, membership, matter and model-run
keys. No existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL because the
rows hold lawyers' saved research answers and their verified source manifests.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261124_0002"
down_revision = "20261124_0001"
branch_labels = None
depends_on = None

_TABLE = "research_answers"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "context_matter_id",
            sa.String(36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "matter_id",
            sa.String(36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "saved_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("answer_json", sa.Text(), nullable=True),
        sa.Column("source_manifest_json", sa.Text(), nullable=True),
        sa.Column("analysis_version", sa.String(80), nullable=False),
        sa.Column(
            "model_run_id",
            sa.String(36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'answered', 'abstained', 'failed')",
            name="ck_research_answers_status",
        ),
    )
    op.create_index("ix_research_answers_company_id", _TABLE, ["company_id"])
    op.create_index(
        "ix_research_answers_created_by_membership_id", _TABLE, ["created_by_membership_id"]
    )
    op.create_index("ix_research_answers_context_matter_id", _TABLE, ["context_matter_id"])
    op.create_index("ix_research_answers_matter_id", _TABLE, ["matter_id"])
    op.create_index(
        "ix_research_answers_saved_by_membership_id", _TABLE, ["saved_by_membership_id"]
    )
    op.create_index("ix_research_answers_model_run_id", _TABLE, ["model_run_id"])
    op.create_index(
        "ix_research_answers_company_creator",
        _TABLE,
        ["company_id", "created_by_membership_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Saved research answers and their verified sources are retained; restore-forward only."
    )
