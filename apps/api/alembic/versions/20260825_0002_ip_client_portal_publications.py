"""Generalize portal grants and add approved IP client publications.

Revision ID: 20260825_0002
Revises: 20260825_0001
Create Date: 2026-08-25

IPLF-055 extends the existing portal identity/grant and client-instruction
owners. It adds neutral immutable report artifacts and publication links; it
does not create a second client portal, notification queue, document store, or
IP instruction ledger.

MIGRATION-LOCK-RISK: acknowledged: one bounded grant backfill, one bounded
instruction backfill, additive tables/indexes, and batch constraint changes;
PostgreSQL lock timeout is five seconds.
MIGRATION-ROLLBACK: restore-forward after any IP grant, publication, or portal-
submitted instruction exists. Empty pre-activation schemas may downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260825_0002"
down_revision = "20260825_0001"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def _set_lock_timeout() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))


def upgrade() -> None:
    _set_lock_timeout()

    with op.batch_alter_table("portal_users") as batch:
        batch.create_unique_constraint("uq_portal_user_id_company", ["id", "company_id"])

    with op.batch_alter_table("matter_portal_grants") as batch:
        batch.add_column(sa.Column("company_id", sa.String(length=36)))
        batch.add_column(sa.Column("ip_docket_record_id", sa.String(length=36)))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("granted_by_label_snapshot", sa.String(length=255)))
        batch.add_column(sa.Column("revoked_by_membership_id", sa.String(length=36)))
        batch.add_column(sa.Column("revoked_by_label_snapshot", sa.String(length=255)))
        batch.add_column(sa.Column("revoked_reason", sa.Text()))
        batch.add_column(sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))

    op.execute(
        sa.text(
            "UPDATE matter_portal_grants "
            "SET company_id = ("
            "SELECT portal_users.company_id FROM portal_users "
            "WHERE portal_users.id = matter_portal_grants.portal_user_id), "
            "granted_by_label_snapshot = 'membership:' || granted_by_membership_id"
        )
    )

    with op.batch_alter_table("matter_portal_grants") as batch:
        batch.alter_column("company_id", existing_type=sa.String(length=36), nullable=False)
        batch.alter_column(
            "granted_by_label_snapshot",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch.alter_column("matter_id", existing_type=sa.String(length=36), nullable=True)
        batch.drop_constraint("uq_matter_portal_grant_user_matter", type_="unique")
        batch.create_unique_constraint("uq_portal_grant_id_company", ["id", "company_id"])
        batch.create_foreign_key(
            "fk_portal_grant_user_company",
            "portal_users",
            ["portal_user_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_portal_grant_matter_company",
            "matters",
            ["matter_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_portal_grant_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_record_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_portal_grant_revoker",
            "company_memberships",
            ["revoked_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_portal_grant_exactly_one_target",
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_record_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
        batch.create_check_constraint("ck_portal_grant_row_version_positive", "row_version > 0")
        batch.create_check_constraint(
            "ck_portal_grant_expiry_after_grant",
            "expires_at IS NULL OR expires_at > granted_at",
        )
        batch.create_check_constraint(
            "ck_portal_grant_revocation_evidence",
            "revoked_at IS NULL OR ip_docket_record_id IS NULL OR "
            "(revoked_by_label_snapshot IS NOT NULL AND revoked_reason IS NOT NULL)",
        )
        batch.create_index("ix_matter_portal_grants_company_id", ["company_id"])
        batch.create_index("ix_matter_portal_grants_ip_docket_record_id", ["ip_docket_record_id"])
        batch.create_index("ix_matter_portal_grants_expires_at", ["expires_at"])
        batch.create_index(
            "ix_matter_portal_grants_revoked_by_membership_id",
            ["revoked_by_membership_id"],
        )

    op.create_index(
        "uq_portal_grant_user_matter_active",
        "matter_portal_grants",
        ["portal_user_id", "matter_id"],
        unique=True,
        postgresql_where=sa.text("matter_id IS NOT NULL AND revoked_at IS NULL"),
        sqlite_where=sa.text("matter_id IS NOT NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "uq_portal_grant_user_ip_active",
        "matter_portal_grants",
        ["portal_user_id", "ip_docket_record_id"],
        unique=True,
        postgresql_where=sa.text("ip_docket_record_id IS NOT NULL AND revoked_at IS NULL"),
        sqlite_where=sa.text("ip_docket_record_id IS NOT NULL AND revoked_at IS NULL"),
    )

    op.create_table(
        "report_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("report_kind", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column(
            "audience",
            sa.String(length=32),
            nullable=False,
            server_default="client_portal",
        ),
        sa.Column("confidentiality", sa.String(length=32), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("freshness_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("rows_json", sa.JSON(), nullable=False),
        sa.Column("exclusions_json", sa.JSON(), nullable=False),
        sa.Column("source_versions_json", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by_membership_id", sa.String(length=36)),
        sa.Column("generated_by_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("approved_by_membership_id", sa.String(length=36)),
        sa.Column("approved_by_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["generated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_report_artifact_generator_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_report_artifact_approver_company",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_report_artifact_id_company"),
        sa.UniqueConstraint(
            "company_id", "snapshot_sha256", name="uq_report_artifact_company_snapshot"
        ),
        sa.CheckConstraint("length(snapshot_sha256) = 64", name="ck_report_artifact_sha256"),
        sa.CheckConstraint("row_count >= 0", name="ck_report_artifact_row_count"),
        sa.CheckConstraint(
            "audience = 'client_portal'", name="ck_report_artifact_client_portal_audience"
        ),
    )
    op.create_index("ix_report_artifacts_company_id", "report_artifacts", ["company_id"])
    op.create_index("ix_report_artifacts_report_kind", "report_artifacts", ["report_kind"])
    op.create_index("ix_report_artifacts_snapshot_sha256", "report_artifacts", ["snapshot_sha256"])

    op.create_table(
        "portal_publications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("portal_user_id", sa.String(length=36), nullable=False),
        sa.Column("report_artifact_id", sa.String(length=36)),
        sa.Column("document_version_id", sa.String(length=36)),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_intent_id", sa.String(length=36)),
        sa.Column("approved_by_membership_id", sa.String(length=36)),
        sa.Column("approved_by_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_membership_id", sa.String(length=36)),
        sa.Column("revoked_by_label_snapshot", sa.String(length=255)),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["portal_user_id", "company_id"],
            ["portal_users.id", "portal_users.company_id"],
            name="fk_portal_publication_user_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_artifact_id", "company_id"],
            ["report_artifacts.id", "report_artifacts.company_id"],
            name="fk_portal_publication_report_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "company_id"],
            ["ip_document_versions.id", "ip_document_versions.company_id"],
            name="fk_portal_publication_document_version_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_intent_id"],
            ["notification_delivery_intents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_portal_publication_approver_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_portal_publication_id_company"),
        sa.CheckConstraint(
            "(CASE WHEN report_artifact_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN document_version_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_portal_publication_exactly_one_content",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'published', 'revoked')",
            name="ck_portal_publication_status",
        ),
        sa.CheckConstraint(
            "status <> 'scheduled' OR scheduled_for IS NOT NULL",
            name="ck_portal_publication_schedule_required",
        ),
        sa.CheckConstraint(
            "status <> 'revoked' OR "
            "(revoked_at IS NOT NULL AND revoked_by_label_snapshot IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_portal_publication_revocation_evidence",
        ),
    )
    op.create_index("ix_portal_publications_company_id", "portal_publications", ["company_id"])
    op.create_index(
        "ix_portal_publications_portal_user_id",
        "portal_publications",
        ["portal_user_id"],
    )
    op.create_index(
        "ix_portal_publications_delivery_intent_id",
        "portal_publications",
        ["delivery_intent_id"],
    )
    op.create_index(
        "ix_portal_publications_report_artifact_id",
        "portal_publications",
        ["report_artifact_id"],
    )
    op.create_index(
        "ix_portal_publications_document_version_id",
        "portal_publications",
        ["document_version_id"],
    )
    op.create_index(
        "ix_portal_publications_revoked_by_membership_id",
        "portal_publications",
        ["revoked_by_membership_id"],
    )
    op.create_index(
        "ix_portal_publications_user_status",
        "portal_publications",
        ["portal_user_id", "status", "scheduled_for"],
    )

    op.create_table(
        "portal_publication_targets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("publication_id", sa.String(length=36), nullable=False),
        sa.Column("portal_grant_id", sa.String(length=36), nullable=False),
        sa.Column("ip_docket_record_id", sa.String(length=36), nullable=False),
        sa.Column("docket_version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False),
        sa.Column("access_policy_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["publication_id", "company_id"],
            ["portal_publications.id", "portal_publications.company_id"],
            name="fk_portal_publication_target_publication_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["portal_grant_id", "company_id"],
            ["matter_portal_grants.id", "matter_portal_grants.company_id"],
            name="fk_portal_publication_target_grant_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ip_docket_record_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_portal_publication_target_docket_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "publication_id",
            "ip_docket_record_id",
            name="uq_portal_publication_target_docket",
        ),
        sa.CheckConstraint("docket_version > 0", name="ck_portal_publication_docket_version"),
        sa.CheckConstraint(
            "lifecycle_version >= 0", name="ck_portal_publication_lifecycle_version"
        ),
        sa.CheckConstraint(
            "access_policy_version >= 0",
            name="ck_portal_publication_access_policy_version",
        ),
    )
    op.create_index(
        "ix_portal_publication_targets_company_id",
        "portal_publication_targets",
        ["company_id"],
    )
    op.create_index(
        "ix_portal_publication_targets_publication_id",
        "portal_publication_targets",
        ["publication_id"],
    )
    op.create_index(
        "ix_portal_publication_targets_portal_grant_id",
        "portal_publication_targets",
        ["portal_grant_id"],
    )
    op.create_index(
        "ix_portal_publication_targets_ip_docket_record_id",
        "portal_publication_targets",
        ["ip_docket_record_id"],
    )

    with op.batch_alter_table("ip_client_instructions") as batch:
        batch.add_column(sa.Column("instruction_thread_key", sa.String(length=120)))
        batch.add_column(
            sa.Column(
                "instruction_kind",
                sa.String(length=32),
                nullable=False,
                server_default="renewal",
            )
        )
        batch.add_column(sa.Column("source_portal_user_id", sa.String(length=36)))
        batch.add_column(sa.Column("source_portal_grant_id", sa.String(length=36)))
        batch.add_column(sa.Column("portal_publication_id", sa.String(length=36)))
        batch.add_column(sa.Column("creator_label_snapshot", sa.String(length=255)))

    op.execute(
        sa.text(
            "UPDATE ip_client_instructions SET "
            "instruction_thread_key = 'renewal:' || renewal_term_id, "
            "creator_label_snapshot = 'membership:' || created_by_membership_id"
        )
    )

    with op.batch_alter_table("ip_client_instructions") as batch:
        batch.alter_column(
            "instruction_thread_key", existing_type=sa.String(length=120), nullable=False
        )
        batch.alter_column(
            "creator_label_snapshot", existing_type=sa.String(length=255), nullable=False
        )
        batch.alter_column("renewal_term_id", existing_type=sa.String(length=36), nullable=True)
        batch.alter_column(
            "created_by_membership_id", existing_type=sa.String(length=36), nullable=True
        )
        batch.drop_constraint("uq_ip_client_instruction_term_version", type_="unique")
        batch.create_unique_constraint(
            "uq_ip_client_instruction_thread_version",
            ["company_id", "instruction_thread_key", "instruction_version"],
        )
        batch.drop_constraint("ck_ip_client_instruction_decision", type_="check")
        batch.create_check_constraint(
            "ck_ip_client_instruction_decision",
            "decision IN ('renew', 'do_not_renew', 'proceed', 'do_not_proceed', "
            "'defer', 'clarification_required')",
        )
        batch.create_check_constraint(
            "ck_ip_client_instruction_kind",
            "instruction_kind IN ('renewal', 'proceeding', 'filing', 'watch', 'general')",
        )
        batch.create_check_constraint(
            "ck_ip_client_instruction_portal_source_complete",
            "(source_portal_user_id IS NULL AND source_portal_grant_id IS NULL "
            "AND portal_publication_id IS NULL) OR "
            "(source_portal_user_id IS NOT NULL AND source_portal_grant_id IS NOT NULL "
            "AND portal_publication_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_ip_client_instruction_creator_required",
            "created_by_membership_id IS NOT NULL OR source_portal_user_id IS NOT NULL",
        )
        batch.create_foreign_key(
            "fk_ip_client_instruction_portal_user_company",
            "portal_users",
            ["source_portal_user_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ip_client_instruction_portal_grant_company",
            "matter_portal_grants",
            ["source_portal_grant_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ip_client_instruction_publication_company",
            "portal_publications",
            ["portal_publication_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_ip_client_instructions_source_portal_user_id",
            ["source_portal_user_id"],
        )
        batch.create_index(
            "ix_ip_client_instructions_source_portal_grant_id",
            ["source_portal_grant_id"],
        )
        batch.create_index(
            "ix_ip_client_instructions_portal_publication_id",
            ["portal_publication_id"],
        )
        batch.create_index(
            "ix_ip_client_instructions_renewal_term_id",
            ["renewal_term_id"],
        )


def downgrade() -> None:
    _set_lock_timeout()
    bind = op.get_bind()
    activated = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM matter_portal_grants "
            " WHERE ip_docket_record_id IS NOT NULL) + "
            "(SELECT count(*) FROM portal_publications) + "
            "(SELECT count(*) FROM ip_client_instructions "
            " WHERE source_portal_user_id IS NOT NULL OR renewal_term_id IS NULL)"
        )
    ).scalar_one()
    if int(activated or 0) > 0:
        raise RuntimeError(
            "IP portal data exists; restore-forward instead of downgrading 20260825_0002."
        )

    with op.batch_alter_table("ip_client_instructions") as batch:
        batch.drop_index("ix_ip_client_instructions_renewal_term_id")
        batch.drop_index("ix_ip_client_instructions_portal_publication_id")
        batch.drop_index("ix_ip_client_instructions_source_portal_grant_id")
        batch.drop_index("ix_ip_client_instructions_source_portal_user_id")
        batch.drop_constraint("fk_ip_client_instruction_publication_company", type_="foreignkey")
        batch.drop_constraint("fk_ip_client_instruction_portal_grant_company", type_="foreignkey")
        batch.drop_constraint("fk_ip_client_instruction_portal_user_company", type_="foreignkey")
        batch.drop_constraint("ck_ip_client_instruction_creator_required", type_="check")
        batch.drop_constraint("ck_ip_client_instruction_portal_source_complete", type_="check")
        batch.drop_constraint("ck_ip_client_instruction_kind", type_="check")
        batch.drop_constraint("ck_ip_client_instruction_decision", type_="check")
        batch.create_check_constraint(
            "ck_ip_client_instruction_decision",
            "decision IN ('renew', 'do_not_renew', 'defer', 'clarification_required')",
        )
        batch.drop_constraint("uq_ip_client_instruction_thread_version", type_="unique")
        batch.create_unique_constraint(
            "uq_ip_client_instruction_term_version",
            ["renewal_term_id", "instruction_version"],
        )
        batch.alter_column(
            "created_by_membership_id", existing_type=sa.String(length=36), nullable=False
        )
        batch.alter_column("renewal_term_id", existing_type=sa.String(length=36), nullable=False)
        batch.drop_column("creator_label_snapshot")
        batch.drop_column("portal_publication_id")
        batch.drop_column("source_portal_grant_id")
        batch.drop_column("source_portal_user_id")
        batch.drop_column("instruction_kind")
        batch.drop_column("instruction_thread_key")

    op.drop_table("portal_publication_targets")
    op.drop_table("portal_publications")
    op.drop_table("report_artifacts")

    op.drop_index("uq_portal_grant_user_ip_active", table_name="matter_portal_grants")
    op.drop_index("uq_portal_grant_user_matter_active", table_name="matter_portal_grants")
    with op.batch_alter_table("matter_portal_grants") as batch:
        batch.drop_index("ix_matter_portal_grants_revoked_by_membership_id")
        batch.drop_index("ix_matter_portal_grants_expires_at")
        batch.drop_index("ix_matter_portal_grants_ip_docket_record_id")
        batch.drop_index("ix_matter_portal_grants_company_id")
        batch.drop_constraint("ck_portal_grant_revocation_evidence", type_="check")
        batch.drop_constraint("ck_portal_grant_expiry_after_grant", type_="check")
        batch.drop_constraint("ck_portal_grant_row_version_positive", type_="check")
        batch.drop_constraint("ck_portal_grant_exactly_one_target", type_="check")
        batch.drop_constraint("fk_portal_grant_revoker", type_="foreignkey")
        batch.drop_constraint("fk_portal_grant_ip_docket_company", type_="foreignkey")
        batch.drop_constraint("fk_portal_grant_matter_company", type_="foreignkey")
        batch.drop_constraint("fk_portal_grant_user_company", type_="foreignkey")
        batch.drop_constraint("uq_portal_grant_id_company", type_="unique")
        batch.create_unique_constraint(
            "uq_matter_portal_grant_user_matter", ["portal_user_id", "matter_id"]
        )
        batch.alter_column("matter_id", existing_type=sa.String(length=36), nullable=False)
        batch.drop_column("row_version")
        batch.drop_column("revoked_reason")
        batch.drop_column("revoked_by_label_snapshot")
        batch.drop_column("revoked_by_membership_id")
        batch.drop_column("granted_by_label_snapshot")
        batch.drop_column("expires_at")
        batch.drop_column("ip_docket_record_id")
        batch.drop_column("company_id")

    with op.batch_alter_table("portal_users") as batch:
        batch.drop_constraint("uq_portal_user_id_company", type_="unique")
