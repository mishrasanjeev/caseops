"""Generalize drafting targets and preserve immutable generation manifests.

Revision ID: 20260823_0004
Revises: 20260823_0003
Create Date: 2026-08-23

IPLF-045 extends the existing Draft, ModelRun, and
DraftingDataExtractionField owners. Matter drafts are backfilled in place;
new IP drafts point at the canonical docket and optional proceeding. No
parallel drafting or recommendation store is introduced.

MIGRATION-LOCK-RISK: acknowledged: three drafting tables are widened and the
small drafts table is backfilled from matters before target constraints are
enabled. PostgreSQL lock timeout is five seconds.
MIGRATION-ROLLBACK: restore-forward: downgrade refuses while any IP-targeted
draft, model run, or extraction row exists.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260823_0004"
down_revision = "20260823_0003"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def _install_legacy_draft_company_trigger(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION populate_draft_company_from_matter()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.company_id IS NULL AND NEW.matter_id IS NOT NULL THEN
                    SELECT company_id INTO NEW.company_id
                    FROM matters WHERE id = NEW.matter_id;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        """
        CREATE TRIGGER trg_drafts_legacy_company
        BEFORE INSERT OR UPDATE OF matter_id, company_id ON drafts
        FOR EACH ROW EXECUTE FUNCTION populate_draft_company_from_matter()
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    with op.batch_alter_table("ip_proceedings") as batch:
        batch.create_unique_constraint(
            "uq_ip_proceeding_id_company_docket",
            ["id", "company_id", "docket_id"],
        )

    with op.batch_alter_table("drafts") as batch:
        batch.add_column(sa.Column("company_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("ip_docket_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("ip_proceeding_id", sa.String(36), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE drafts SET company_id = ("
            "SELECT matters.company_id FROM matters WHERE matters.id = drafts.matter_id"
            ") WHERE company_id IS NULL"
        )
    )
    missing_company = bind.execute(
        sa.text("SELECT COUNT(*) FROM drafts WHERE company_id IS NULL")
    ).scalar_one()
    if missing_company:
        raise RuntimeError("refusing drafting target switch: orphan Matter drafts exist")
    _install_legacy_draft_company_trigger(bind)
    with op.batch_alter_table("drafts") as batch:
        batch.alter_column("company_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("matter_id", existing_type=sa.String(36), nullable=True)
        batch.create_foreign_key(
            "fk_draft_company",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_draft_matter_company",
            "matters",
            ["matter_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_draft_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_draft_ip_proceeding_target",
            "ip_proceedings",
            ["ip_proceeding_id", "company_id", "ip_docket_id"],
            ["id", "company_id", "docket_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_draft_exactly_one_target",
            "(matter_id IS NOT NULL AND ip_docket_id IS NULL AND "
            "ip_proceeding_id IS NULL) OR "
            "(matter_id IS NULL AND ip_docket_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_draft_ip_proceeding_requires_docket",
            "ip_proceeding_id IS NULL OR ip_docket_id IS NOT NULL",
        )
        batch.create_index("ix_drafts_company_id", ["company_id"])
        batch.create_index("ix_drafts_company_ip_docket", ["company_id", "ip_docket_id"])
        batch.create_index("ix_drafts_ip_proceeding_id", ["ip_proceeding_id"])

    with op.batch_alter_table("model_runs") as batch:
        batch.add_column(sa.Column("ip_docket_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("ip_proceeding_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_model_run_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_model_run_ip_proceeding_target",
            "ip_proceedings",
            ["ip_proceeding_id", "company_id", "ip_docket_id"],
            ["id", "company_id", "docket_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_model_run_single_legal_target",
            "matter_id IS NULL OR ip_docket_id IS NULL",
        )
        batch.create_check_constraint(
            "ck_model_run_ip_proceeding_requires_docket",
            "ip_proceeding_id IS NULL OR ip_docket_id IS NOT NULL",
        )
        batch.create_index("ix_model_runs_ip_docket_id", ["ip_docket_id"])
        batch.create_index("ix_model_runs_ip_proceeding_id", ["ip_proceeding_id"])

    with op.batch_alter_table("drafting_data_extraction_fields") as batch:
        batch.add_column(sa.Column("ip_docket_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_ip_document_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_ip_document_version_id", sa.String(36), nullable=True))
        batch.alter_column("matter_id", existing_type=sa.String(36), nullable=True)
        batch.create_foreign_key(
            "fk_drafting_data_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_drafting_data_ip_document_version_company",
            "ip_document_versions",
            ["source_ip_document_version_id", "company_id", "source_ip_document_id"],
            ["id", "company_id", "document_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_drafting_data_exactly_one_target",
            "(matter_id IS NOT NULL AND ip_docket_id IS NULL) OR "
            "(matter_id IS NULL AND ip_docket_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_drafting_data_single_source",
            "source_attachment_id IS NULL OR source_ip_document_version_id IS NULL",
        )
        batch.create_check_constraint(
            "ck_drafting_data_ip_source_complete",
            "(source_ip_document_version_id IS NULL AND source_ip_document_id IS NULL) OR "
            "(source_ip_document_version_id IS NOT NULL AND source_ip_document_id IS NOT NULL)",
        )
        batch.create_index("ix_drafting_data_company_ip_docket", ["company_id", "ip_docket_id"])
        batch.create_index("ix_drafting_data_source_ip_document_id", ["source_ip_document_id"])
        batch.create_index(
            "ix_drafting_data_source_ip_document_version_id",
            ["source_ip_document_version_id"],
        )

    with op.batch_alter_table("draft_versions") as batch:
        batch.add_column(
            sa.Column(
                "template_manifest_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.add_column(
            sa.Column(
                "context_manifest_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.add_column(
            sa.Column(
                "source_manifest_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    ip_rows = 0
    for table in ("drafts", "model_runs", "drafting_data_extraction_fields"):
        ip_rows += bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE ip_docket_id IS NOT NULL")
        ).scalar_one()
    if ip_rows:
        raise RuntimeError("refusing to downgrade: retained IP drafting records require IPLF-045")

    with op.batch_alter_table("draft_versions") as batch:
        batch.drop_column("source_manifest_json")
        batch.drop_column("context_manifest_json")
        batch.drop_column("template_manifest_json")

    with op.batch_alter_table("drafting_data_extraction_fields") as batch:
        batch.drop_index("ix_drafting_data_source_ip_document_version_id")
        batch.drop_index("ix_drafting_data_source_ip_document_id")
        batch.drop_index("ix_drafting_data_company_ip_docket")
        batch.drop_constraint("ck_drafting_data_ip_source_complete", type_="check")
        batch.drop_constraint("ck_drafting_data_single_source", type_="check")
        batch.drop_constraint("ck_drafting_data_exactly_one_target", type_="check")
        batch.drop_constraint("fk_drafting_data_ip_document_version_company", type_="foreignkey")
        batch.drop_constraint("fk_drafting_data_ip_docket_company", type_="foreignkey")
        batch.alter_column("matter_id", existing_type=sa.String(36), nullable=False)
        batch.drop_column("source_ip_document_version_id")
        batch.drop_column("source_ip_document_id")
        batch.drop_column("ip_docket_id")

    with op.batch_alter_table("model_runs") as batch:
        batch.drop_index("ix_model_runs_ip_proceeding_id")
        batch.drop_index("ix_model_runs_ip_docket_id")
        batch.drop_constraint("ck_model_run_ip_proceeding_requires_docket", type_="check")
        batch.drop_constraint("ck_model_run_single_legal_target", type_="check")
        batch.drop_constraint("fk_model_run_ip_proceeding_target", type_="foreignkey")
        batch.drop_constraint("fk_model_run_ip_docket_company", type_="foreignkey")
        batch.drop_column("ip_proceeding_id")
        batch.drop_column("ip_docket_id")

    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_drafts_legacy_company ON drafts")
        op.execute("DROP FUNCTION IF EXISTS populate_draft_company_from_matter()")
    with op.batch_alter_table("drafts") as batch:
        batch.drop_index("ix_drafts_ip_proceeding_id")
        batch.drop_index("ix_drafts_company_ip_docket")
        batch.drop_index("ix_drafts_company_id")
        batch.drop_constraint("ck_draft_ip_proceeding_requires_docket", type_="check")
        batch.drop_constraint("ck_draft_exactly_one_target", type_="check")
        batch.drop_constraint("fk_draft_ip_proceeding_target", type_="foreignkey")
        batch.drop_constraint("fk_draft_ip_docket_company", type_="foreignkey")
        batch.drop_constraint("fk_draft_matter_company", type_="foreignkey")
        batch.drop_constraint("fk_draft_company", type_="foreignkey")
        batch.alter_column("matter_id", existing_type=sa.String(36), nullable=False)
        batch.drop_column("ip_proceeding_id")
        batch.drop_column("ip_docket_id")
        batch.drop_column("company_id")

    with op.batch_alter_table("ip_proceedings") as batch:
        batch.drop_constraint("uq_ip_proceeding_id_company_docket", type_="unique")
