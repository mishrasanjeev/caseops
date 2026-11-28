"""Firm branding and verification tokens for billing PDFs (ENH-001).

Revision ID: 20261127_0002
Revises: 20261127_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Two new empty tables; their indexes are
built on their own empty columns and their foreign keys reference existing
company, matter and membership keys. No existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before any DDL: the
verification table is the only record behind QR codes printed on PDFs already
sent to clients, so dropping it would turn genuine documents into failed
verifications. To stop branding, clear the settings rows; to stop verification,
revoke the rows.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0002"
down_revision = "20261127_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "company_document_brandings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signatory_name", sa.String(160), nullable=True),
        sa.Column("signatory_designation", sa.String(160), nullable=True),
        sa.Column(
            "watermark_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("watermark_text", sa.String(60), nullable=True),
        sa.Column("logo_storage_key", sa.String(500), nullable=True),
        sa.Column("logo_sha256", sa.String(64), nullable=True),
        sa.Column("logo_width", sa.Integer(), nullable=True),
        sa.Column("logo_height", sa.Integer(), nullable=True),
        sa.Column("signature_storage_key", sa.String(500), nullable=True),
        sa.Column("signature_sha256", sa.String(64), nullable=True),
        sa.Column("signature_width", sa.Integer(), nullable=True),
        sa.Column("signature_height", sa.Integer(), nullable=True),
        sa.Column(
            "updated_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", name="uq_company_document_branding_company"),
    )
    op.create_index(
        "ix_company_document_brandings_company_id",
        "company_document_brandings",
        ["company_id"],
    )
    op.create_index(
        "ix_company_document_brandings_updated_by_membership_id",
        "company_document_brandings",
        ["updated_by_membership_id"],
    )
    op.create_table(
        "billing_document_verifications",
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
            nullable=True,
        ),
        sa.Column("document_kind", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("document_number", sa.String(80), nullable=False),
        sa.Column("document_issued_on", sa.Date(), nullable=False),
        sa.Column("issuer_name", sa.String(255), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status_at_generation", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.Column(
            "generated_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(255), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_billing_document_verification_token"),
    )
    op.create_index(
        "ix_billing_document_verifications_company_id",
        "billing_document_verifications",
        ["company_id"],
    )
    op.create_index(
        "ix_billing_document_verifications_matter_id",
        "billing_document_verifications",
        ["matter_id"],
    )
    op.create_index(
        "ix_billing_document_verifications_generated_by_membership_id",
        "billing_document_verifications",
        ["generated_by_membership_id"],
    )
    op.create_index(
        "ix_billing_document_verifications_source",
        "billing_document_verifications",
        ["company_id", "source_type", "source_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Billing document verification records back printed QR codes; restore-forward only."
    )
