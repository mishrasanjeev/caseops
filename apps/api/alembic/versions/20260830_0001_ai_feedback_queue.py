"""Add the tenant-scoped AI and Product Guide feedback queue.

Revision ID: 20260830_0001
Revises: 20260829_0001

MIGRATION-LOCK-RISK: acknowledged - creates one empty additive table and
indexes before the feedback UI is enabled; no existing table is scanned.
MIGRATION-ROLLBACK: restore-forward after feedback is accepted because these
diagnostic records retain review and audit provenance.
DATA-GOVERNANCE-MAP: updated for minimal feedback, reviewer notes, and
canonical target references; prompts, answers, citations, and sources are not copied.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260830_0001"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()
    op.create_table(
        "ai_feedback_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("submitted_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("submission_key", sa.String(length=80), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=160), nullable=False),
        sa.Column("parent_target_id", sa.String(length=160), nullable=True),
        sa.Column("target_version", sa.String(length=128), nullable=True),
        sa.Column("target_href", sa.String(length=2048), nullable=True),
        sa.Column("feedback_type", sa.String(length=16), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "surface IN ('product_guide', 'workspace_assistant')",
            name="ck_ai_feedback_surface",
        ),
        sa.CheckConstraint(
            "target_type IN ('product_guide_command', 'product_guide_section', "
            "'product_guide_permission', 'product_guide_no_match', 'assistant_turn')",
            name="ck_ai_feedback_target_type",
        ),
        sa.CheckConstraint(
            "feedback_type IN ('rating', 'report')",
            name="ck_ai_feedback_type",
        ),
        sa.CheckConstraint(
            "rating IS NULL OR rating IN ('helpful', 'not_helpful')",
            name="ck_ai_feedback_rating",
        ),
        sa.CheckConstraint(
            "category IS NULL OR category IN ('answer_quality', 'wrong_navigation', "
            "'missing_permission_explanation', 'unsafe_citation', 'outdated_guidance', "
            "'missing_guidance', 'other')",
            name="ck_ai_feedback_category",
        ),
        sa.CheckConstraint("priority IN ('normal', 'high')", name="ck_ai_feedback_priority"),
        sa.CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'dismissed')",
            name="ck_ai_feedback_status",
        ),
        sa.CheckConstraint(
            "(feedback_type = 'rating' AND rating IS NOT NULL AND category IS NULL) OR "
            "(feedback_type = 'report' AND rating IS NULL AND category IS NOT NULL)",
            name="ck_ai_feedback_payload_shape",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND reviewed_by_membership_id IS NULL AND reviewed_at IS NULL) OR "
            "(status IN ('in_review', 'resolved', 'dismissed') AND "
            "reviewed_by_membership_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_ai_feedback_review_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_ai_feedback_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ai_feedback_submitter_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ai_feedback_reviewer_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_ai_feedback_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "submitted_by_membership_id",
            "submission_key",
            name="uq_ai_feedback_submitter_submission_key",
        ),
    )
    op.create_index(
        "ix_ai_feedback_company_status_created",
        "ai_feedback_items",
        ["company_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_ai_feedback_company_surface_created",
        "ai_feedback_items",
        ["company_id", "surface", "created_at", "id"],
    )
    op.create_index(
        "ix_ai_feedback_company_category_status",
        "ai_feedback_items",
        ["company_id", "category", "status", "created_at"],
    )
    op.create_index(
        "ix_ai_feedback_submitter_company",
        "ai_feedback_items",
        ["submitted_by_membership_id", "company_id"],
    )
    op.create_index(
        "ix_ai_feedback_reviewer_company",
        "ai_feedback_items",
        ["reviewed_by_membership_id", "company_id"],
    )


def downgrade() -> None:
    _set_postgres_timeouts()
    retained = op.get_bind().scalar(sa.text("SELECT 1 FROM ai_feedback_items LIMIT 1"))
    if retained is not None:
        raise RuntimeError(
            "Cannot downgrade while retained AI feedback evidence exists. "
            "Use governed disposition and restore-forward."
        )
    op.drop_table("ai_feedback_items")
