"""OCR text and legal translation versions of matter attachments.

Revision ID: 20261123_0001
Revises: 20261122_0631
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One new empty table with nonunique and
partial-unique indexes on its own columns references existing tenant, matter,
attachment and membership keys. No existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL because the
rows hold reviewed OCR text, translations and their review evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261123_0001"
down_revision = "20261122_0631"
branch_labels = None
depends_on = None

_TABLE = "matter_attachment_renditions"
_ACTIVE_SQL = "status IN ('queued', 'inspecting', 'ocr_processing', 'translation_processing')"


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
            "matter_id",
            sa.String(36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.String(36),
            sa.ForeignKey("matter_attachments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_rendition_id",
            sa.String(36),
            sa.ForeignKey("matter_attachment_renditions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("source_language", sa.String(16), nullable=False),
        sa.Column("target_language", sa.String(16), nullable=True),
        sa.Column("chain_target_language", sa.String(16), nullable=True),
        sa.Column("provider", sa.String(80), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_review", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_json", sa.Text(), nullable=True),
        sa.Column("provider_jobs_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output_storage_key", sa.String(500), nullable=True),
        sa.Column("output_size_bytes", sa.Integer(), nullable=True),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("processing_job_id", sa.String(36), nullable=True),
        sa.Column(
            "requested_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "attachment_id", "kind", "version", name="uq_matter_attachment_rendition_version",
        ),
        sa.UniqueConstraint(
            "output_storage_key", name="uq_matter_attachment_renditions_output_storage_key",
        ),
        sa.CheckConstraint("kind IN ('ocr', 'translation')", name="ck_matter_rendition_kind"),
        sa.CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed', 'needs_correction')",
            name="ck_matter_rendition_review_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_matter_rendition_version"),
        sa.CheckConstraint(
            "kind = 'ocr' OR (source_rendition_id IS NOT NULL AND target_language IS NOT NULL)",
            name="ck_matter_rendition_translation_source",
        ),
    )
    op.create_index(
        "ix_matter_attachment_renditions_company_id", _TABLE, ["company_id"],
    )
    op.create_index(
        "ix_matter_attachment_renditions_matter_id", _TABLE, ["matter_id"],
    )
    op.create_index(
        "ix_matter_attachment_renditions_attachment_id", _TABLE, ["attachment_id"],
    )
    op.create_index(
        "ix_matter_attachment_renditions_source_rendition_id", _TABLE, ["source_rendition_id"],
    )
    op.create_index(
        "ix_matter_attachment_renditions_requested_by_membership_id",
        _TABLE,
        ["requested_by_membership_id"],
    )
    op.create_index(
        "ix_matter_attachment_renditions_reviewed_by_membership_id",
        _TABLE,
        ["reviewed_by_membership_id"],
    )
    op.create_index(
        "uq_matter_attachment_rendition_active",
        _TABLE,
        ["attachment_id", "kind"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_SQL),
        sqlite_where=sa.text(_ACTIVE_SQL),
    )


def downgrade() -> None:
    raise RuntimeError(
        "OCR text, translations and their review evidence are retained; restore-forward only."
    )
