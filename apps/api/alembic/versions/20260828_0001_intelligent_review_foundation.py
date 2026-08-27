"""Add target-aware intelligent review and Draft handoff fields.

Revision ID: 20260828_0001
Revises: 20260827_0002

MIGRATION-LOCK-RISK: acknowledged. All new payload columns are nullable; the
two non-null state columns use constant defaults. Existing recommendations are
backfilled as not_applicable before constraints are added. Composite target
constraints validate only bounded recommendation/report/draft rows. Production
deployment runs this migration before routing the new application revision.
MIGRATION-ROLLBACK: restore-forward once intelligent-review rows or linked
Drafts exist. Downgrade refuses to discard frozen legal work product.
DATA-GOVERNANCE-MAP: updated for target, source, prompt/model, selection,
finalization, and approved Draft-version lineage.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260828_0001"
down_revision = "20260827_0002"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()

    with op.batch_alter_table("authority_research_reports") as batch:
        batch.create_unique_constraint(
            "uq_authority_research_reports_id_company",
            ["id", "company_id"],
        )

    with op.batch_alter_table("recommendations") as batch:
        batch.alter_column(
            "matter_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch.add_column(sa.Column("ip_docket_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("ip_proceeding_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("source_research_report_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "review_state",
                sa.String(length=24),
                nullable=False,
                server_default="not_applicable",
            )
        )
        batch.add_column(
            sa.Column(
                "review_progress",
                sa.Integer(),
                nullable=False,
                server_default="100",
            )
        )
        batch.add_column(sa.Column("review_error_code", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("review_payload_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("review_context_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_manifest_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("review_selection_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("review_template_version", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("prompt_policy_version", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("output_hash", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("finalized_by_membership_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.create_unique_constraint(
            "uq_recommendations_id_company",
            ["id", "company_id"],
        )
        batch.create_foreign_key(
            "fk_recommendation_matter_company",
            "matters",
            ["matter_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_recommendation_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_recommendation_ip_proceeding_target",
            "ip_proceedings",
            ["ip_proceeding_id", "company_id", "ip_docket_id"],
            ["id", "company_id", "docket_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_recommendation_research_report_company",
            "authority_research_reports",
            ["source_research_report_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_recommendation_finalizer_company",
            "company_memberships",
            ["finalized_by_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_recommendation_exactly_one_target",
            "(matter_id IS NOT NULL AND ip_docket_id IS NULL AND "
            "ip_proceeding_id IS NULL) OR "
            "(matter_id IS NULL AND ip_docket_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_recommendation_ip_proceeding_requires_docket",
            "ip_proceeding_id IS NULL OR ip_docket_id IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_recommendation_review_source",
            "(type = 'intelligent_review' AND source_research_report_id IS NOT NULL) OR "
            "(type <> 'intelligent_review' AND source_research_report_id IS NULL)",
        )
        batch.create_check_constraint(
            "ck_recommendation_review_state",
            "review_state IN ('not_applicable', 'queued', 'running', 'ready', "
            "'abstained', 'failed', 'finalized', 'published')",
        )
        batch.create_check_constraint(
            "ck_recommendation_review_progress",
            "review_progress >= 0 AND review_progress <= 100",
        )

    op.create_index(
        "ix_fk_recommendations_matter_id_compa_edcf1c7f",
        "recommendations",
        ["matter_id", "company_id"],
    )
    op.create_index(
        "ix_fk_recommendations_ip_proceeding_i_0c288976",
        "recommendations",
        ["ip_proceeding_id", "company_id", "ip_docket_id"],
    )
    op.create_index(
        "ix_fk_recommendations_source_research_ae8b70ed",
        "recommendations",
        ["source_research_report_id", "company_id"],
    )
    op.create_index(
        "ix_fk_recommendations_finalized_by_me_a0403a0f",
        "recommendations",
        ["finalized_by_membership_id", "company_id"],
    )
    op.create_index(
        "ix_recommendations_company_review_state_created",
        "recommendations",
        ["company_id", "review_state", "created_at"],
    )
    op.create_index(
        "ix_recommendations_company_ip_docket_created",
        "recommendations",
        ["company_id", "ip_docket_id", "created_at"],
    )

    with op.batch_alter_table("drafts") as batch:
        batch.add_column(sa.Column("source_recommendation_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_draft_source_recommendation_company",
            "recommendations",
            ["source_recommendation_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_draft_source_recommendation",
            ["source_recommendation_id"],
        )
    op.create_index(
        "ix_fk_drafts_source_recommen_7a6e2990",
        "drafts",
        ["source_recommendation_id", "company_id"],
    )


def downgrade() -> None:
    _set_postgres_timeouts()
    bind = op.get_bind()
    review_count = bind.execute(
        sa.text("SELECT count(*) FROM recommendations WHERE type = 'intelligent_review'")
    ).scalar_one()
    linked_draft_count = bind.execute(
        sa.text("SELECT count(*) FROM drafts WHERE source_recommendation_id IS NOT NULL")
    ).scalar_one()
    if review_count or linked_draft_count:
        raise RuntimeError(
            "Refusing destructive downgrade: intelligent-review work product exists; "
            "use governed export/disposition and restore-forward."
        )

    op.drop_index("ix_fk_drafts_source_recommen_7a6e2990", table_name="drafts")
    with op.batch_alter_table("drafts") as batch:
        batch.drop_constraint("uq_draft_source_recommendation", type_="unique")
        batch.drop_constraint("fk_draft_source_recommendation_company", type_="foreignkey")
        batch.drop_column("source_recommendation_id")

    for index_name in (
        "ix_recommendations_company_ip_docket_created",
        "ix_recommendations_company_review_state_created",
        "ix_fk_recommendations_finalized_by_me_a0403a0f",
        "ix_fk_recommendations_source_research_ae8b70ed",
        "ix_fk_recommendations_ip_proceeding_i_0c288976",
        "ix_fk_recommendations_matter_id_compa_edcf1c7f",
    ):
        op.drop_index(index_name, table_name="recommendations")

    with op.batch_alter_table("recommendations") as batch:
        batch.drop_constraint("ck_recommendation_review_progress", type_="check")
        batch.drop_constraint("ck_recommendation_review_state", type_="check")
        batch.drop_constraint("ck_recommendation_review_source", type_="check")
        batch.drop_constraint("ck_recommendation_ip_proceeding_requires_docket", type_="check")
        batch.drop_constraint("ck_recommendation_exactly_one_target", type_="check")
        batch.drop_constraint("fk_recommendation_finalizer_company", type_="foreignkey")
        batch.drop_constraint("fk_recommendation_research_report_company", type_="foreignkey")
        batch.drop_constraint("fk_recommendation_ip_proceeding_target", type_="foreignkey")
        batch.drop_constraint("fk_recommendation_ip_docket_company", type_="foreignkey")
        batch.drop_constraint("fk_recommendation_matter_company", type_="foreignkey")
        batch.drop_constraint("uq_recommendations_id_company", type_="unique")
        for column_name in (
            "updated_at",
            "finalized_at",
            "finalized_by_membership_id",
            "output_hash",
            "prompt_policy_version",
            "review_template_version",
            "review_selection_json",
            "source_manifest_json",
            "review_context_json",
            "review_payload_json",
            "review_error_code",
            "review_progress",
            "review_state",
            "source_research_report_id",
            "ip_proceeding_id",
            "ip_docket_id",
        ):
            batch.drop_column(column_name)
        batch.alter_column(
            "matter_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )

    with op.batch_alter_table("authority_research_reports") as batch:
        batch.drop_constraint(
            "uq_authority_research_reports_id_company",
            type_="unique",
        )
