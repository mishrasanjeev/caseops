"""Add tenant-safe IP document taxonomy, versions, and typed links.

Revision ID: 20260809_0001
Revises: 20260807_0005
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260809_0001"
down_revision = "20260807_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ip_document_taxonomy_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_seeded", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_doc_taxonomy_updater_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_doc_taxonomy_id_company"),
        sa.UniqueConstraint("company_id", "key", name="uq_ip_doc_taxonomy_company_key"),
        sa.CheckConstraint("version > 0", name="ck_ip_doc_taxonomy_version_positive"),
    )
    op.create_index(
        "ix_ip_document_taxonomy_entries_company_id",
        "ip_document_taxonomy_entries",
        ["company_id"],
    )
    op.create_index(
        "ix_ip_document_taxonomy_entries_updated_by_membership_id",
        "ip_document_taxonomy_entries",
        ["updated_by_membership_id"],
    )

    op.create_table(
        "ip_document_taxonomy_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("taxonomy_entry_id", sa.String(36), nullable=False),
        sa.Column("alias", sa.String(160), nullable=False),
        sa.Column("normalized_alias", sa.String(160), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["taxonomy_entry_id", "company_id"],
            ["ip_document_taxonomy_entries.id", "ip_document_taxonomy_entries.company_id"],
            name="fk_ip_doc_taxonomy_alias_entry_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_doc_taxonomy_alias_creator_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "company_id", "normalized_alias", name="uq_ip_doc_taxonomy_alias_company"
        ),
    )
    for column in ("company_id", "taxonomy_entry_id", "created_by_membership_id"):
        op.create_index(
            f"ix_ip_document_taxonomy_aliases_{column}",
            "ip_document_taxonomy_aliases",
            [column],
        )

    op.create_table(
        "ip_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("taxonomy_entry_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("confidentiality", sa.String(24), nullable=False),
        sa.Column("is_privileged", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["taxonomy_entry_id", "company_id"],
            ["ip_document_taxonomy_entries.id", "ip_document_taxonomy_entries.company_id"],
            name="fk_ip_document_taxonomy_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_creator_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_document_id_company"),
        sa.CheckConstraint("current_version > 0", name="ck_ip_document_current_version_positive"),
        sa.CheckConstraint(
            "confidentiality IN ('internal', 'confidential', 'restricted')",
            name="ck_ip_document_confidentiality",
        ),
    )
    for column in ("company_id", "taxonomy_entry_id", "created_by_membership_id"):
        op.create_index(f"ix_ip_documents_{column}", "ip_documents", [column])

    op.create_table(
        "ip_document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(24), nullable=False),
        sa.Column("extracted_char_count", sa.Integer(), nullable=False),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocr_quality_score", sa.Float(), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("uploaded_by_membership_id", sa.String(36), nullable=False),
        sa.Column("locked_by_membership_id", sa.String(36), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "company_id"],
            ["ip_documents.id", "ip_documents.company_id"],
            name="fk_ip_document_version_document_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_version_uploader_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["locked_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_version_locker_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_document_version_id_company"),
        sa.UniqueConstraint(
            "id",
            "company_id",
            "document_id",
            name="uq_ip_document_version_id_company_document",
        ),
        sa.UniqueConstraint("document_id", "version", name="uq_ip_document_version_number"),
        sa.UniqueConstraint("storage_key", name="uq_ip_document_version_storage_key"),
        sa.CheckConstraint("version > 0", name="ck_ip_document_version_positive"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_ip_document_version_size_nonnegative"),
        sa.CheckConstraint(
            "length(sha256_hex) = 64", name="ck_ip_document_version_sha256_length"
        ),
        sa.CheckConstraint(
            "extracted_char_count >= 0",
            name="ck_ip_document_version_extracted_chars_nonnegative",
        ),
        sa.CheckConstraint(
            "ocr_quality_score IS NULL OR "
            "(ocr_quality_score >= 0 AND ocr_quality_score <= 1)",
            name="ck_ip_document_version_ocr_quality_range",
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'review', 'approved', 'filed', 'served', 'accepted', "
            "'rejected', 'superseded')",
            name="ck_ip_document_version_state",
        ),
        sa.CheckConstraint(
            "(state IN ('approved', 'filed') AND locked_at IS NOT NULL "
            "AND locked_by_membership_id IS NOT NULL) OR "
            "(state NOT IN ('approved', 'filed'))",
            name="ck_ip_document_version_approval_lock",
        ),
    )
    for column in (
        "company_id",
        "document_id",
        "sha256_hex",
        "uploaded_by_membership_id",
        "locked_by_membership_id",
    ):
        op.create_index(f"ix_ip_document_versions_{column}", "ip_document_versions", [column])

    op.create_table(
        "ip_document_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=True),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=True),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("proceeding_id", sa.String(36), nullable=True),
        sa.Column("event_id", sa.String(36), nullable=True),
        sa.Column("deadline_id", sa.String(36), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "company_id"],
            ["ip_documents.id", "ip_documents.company_id"],
            name="fk_ip_document_link_document_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            name="fk_ip_document_link_version_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_document_link_docket_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_document_link_application_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_document_link_proceeding_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_document_link_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_document_link_deadline_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_link_creator_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "document_id", "target_type", "target_id", name="uq_ip_document_link_target"
        ),
        sa.CheckConstraint(
            "(CASE WHEN docket_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN application_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN proceeding_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN event_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN deadline_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_ip_document_link_exactly_one_target",
        ),
        sa.CheckConstraint(
            "CASE target_type "
            "WHEN 'docket' THEN CASE WHEN docket_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'application' THEN CASE WHEN application_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'proceeding' THEN CASE WHEN proceeding_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'event' THEN CASE WHEN event_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'deadline' THEN CASE WHEN deadline_id = target_id THEN 1 ELSE 0 END "
            "ELSE 0 END = 1",
            name="ck_ip_document_link_target_consistent",
        ),
    )
    for column in (
        "company_id",
        "document_id",
        "version_id",
        "docket_id",
        "application_id",
        "proceeding_id",
        "event_id",
        "deadline_id",
        "created_by_membership_id",
    ):
        op.create_index(f"ix_ip_document_links_{column}", "ip_document_links", [column])


def downgrade() -> None:
    op.drop_table("ip_document_links")
    op.drop_table("ip_document_versions")
    op.drop_table("ip_documents")
    op.drop_table("ip_document_taxonomy_aliases")
    op.drop_table("ip_document_taxonomy_entries")
