"""Public Trade Marks Journal source store and tenant-scoped feed state.

Revision ID: 20261122_0001
Revises: 20261121_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Five new, empty tables and their indexes are
created. Existing tables are referenced by foreign keys only; no existing row
is scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL because the
public source lineage and the tenant comparison receipts are retained evidence
that journal-watch hits point to.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261122_0001"
down_revision = "20261121_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "ip_public_journal_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("listing_sha256", sa.String(64), nullable=True),
        sa.Column("issues_listed", sa.Integer(), nullable=False),
        sa.Column("documents_discovered", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'refused')",
            name="ck_ip_public_journal_check_status",
        ),
    )
    op.create_index(
        "ix_ip_public_journal_checks_source_checked",
        "ip_public_journal_checks",
        ["source_key", "checked_at"],
    )
    op.create_table(
        "ip_public_journal_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("journal_number", sa.String(40), nullable=False),
        sa.Column("journal_date", sa.Date(), nullable=False),
        sa.Column("available_on", sa.Date(), nullable=True),
        sa.Column("file_name", sa.String(400), nullable=False),
        sa.Column("source_url", sa.String(800), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_key", "journal_number", "file_name", name="uq_ip_public_journal_document_file"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'parsed', 'needs_review', 'failed')",
            name="ck_ip_public_journal_document_status",
        ),
    )
    op.create_index(
        "ix_ip_public_journal_documents_status_date",
        "ip_public_journal_documents",
        ["status", "journal_date"],
    )
    op.create_table(
        "ip_public_journal_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("entry_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("review_reason", sa.String(200), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("journal_page", sa.String(20), nullable=True),
        sa.Column("application_number", sa.String(40), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("mark_text", sa.String(500), nullable=True),
        sa.Column("proprietor_name", sa.String(500), nullable=True),
        sa.Column("class_numbers_json", sa.JSON(), nullable=False),
        sa.Column("goods_services_json", sa.JSON(), nullable=False),
        sa.Column("registry_office", sa.String(80), nullable=True),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["ip_public_journal_documents.id"],
            name="fk_ip_public_journal_entry_document",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("document_id", "entry_index", name="uq_ip_public_journal_entry_index"),
        sa.CheckConstraint(
            "status IN ('parsed', 'needs_review')",
            name="ck_ip_public_journal_entry_status",
        ),
        sa.CheckConstraint(
            "status <> 'parsed' OR application_number IS NOT NULL",
            name="ck_ip_public_journal_entry_parsed_application",
        ),
    )
    op.create_table(
        "ip_journal_feed_settings",
        sa.Column("company_id", sa.String(36), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("run_as_membership_id", sa.String(36), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_ip_journal_feed_setting_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_as_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_feed_setting_run_as",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_feed_setting_updated_by",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_ip_journal_feed_settings_run_as",
        "ip_journal_feed_settings",
        ["run_as_membership_id", "company_id"],
    )
    op.create_index(
        "ix_ip_journal_feed_settings_updated_by",
        "ip_journal_feed_settings",
        ["updated_by_membership_id", "company_id"],
    )
    op.create_table(
        "ip_journal_feed_tenant_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("run_as_membership_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("entries_compared", sa.Integer(), nullable=False),
        sa.Column("matched_entries", sa.Integer(), nullable=False),
        sa.Column("publications_created", sa.Integer(), nullable=False),
        sa.Column("hits_created", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_ip_journal_feed_tenant_run_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["ip_public_journal_documents.id"],
            name="fk_ip_journal_feed_tenant_run_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_as_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_feed_tenant_run_actor",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "document_id", name="uq_ip_journal_feed_tenant_run"),
        sa.CheckConstraint(
            "status IN ('completed', 'no_active_profiles', 'feature_unavailable', "
            "'actor_unavailable', 'incident_kill_switch', 'match_limit_exceeded', 'failed')",
            name="ck_ip_journal_feed_tenant_run_status",
        ),
    )
    op.create_index(
        "ix_ip_journal_feed_tenant_runs_document",
        "ip_journal_feed_tenant_runs",
        ["document_id"],
    )
    op.create_index(
        "ix_ip_journal_feed_tenant_runs_actor",
        "ip_journal_feed_tenant_runs",
        ["run_as_membership_id", "company_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Public journal lineage and tenant feed receipts are retained evidence; "
        "restore-forward only."
    )
