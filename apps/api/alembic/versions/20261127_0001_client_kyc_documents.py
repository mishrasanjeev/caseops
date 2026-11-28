"""Uploaded KYC documents of a client (BUG-003).

Revision ID: 20261127_0001
Revises: 20261126_0101
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One new empty table; its indexes are built on
its own empty columns and its foreign keys reference existing tenant, client,
membership and portal-user keys. No existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before any DDL because the
rows locate identity documents in the document store and hold the review
evidence of KYC decisions.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0001"
down_revision = "20261126_0101"
branch_labels = None
depends_on = None

_TABLE = "client_kyc_documents"


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
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column(
            "uploaded_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_by_portal_user_id",
            sa.String(36),
            sa.ForeignKey("portal_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("review_decision", sa.String(16), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            ondelete="CASCADE",
            name="fk_client_kyc_documents_client_company",
        ),
        sa.UniqueConstraint("storage_key", name="uq_client_kyc_documents_storage_key"),
        sa.CheckConstraint(
            "document_type IN ('pan', 'aadhaar_masked', 'passport', 'address_proof', 'other')",
            name="ck_client_kyc_documents_type",
        ),
        sa.CheckConstraint(
            "document_type <> 'other' OR label IS NOT NULL",
            name="ck_client_kyc_documents_other_label",
        ),
        sa.CheckConstraint(
            "review_decision IS NULL OR review_decision IN ('approved', 'rejected')",
            name="ck_client_kyc_documents_review_decision",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_client_kyc_documents_size"),
    )
    op.create_index("ix_client_kyc_documents_company_id", _TABLE, ["company_id"])
    op.create_index(
        "ix_client_kyc_documents_client_company", _TABLE, ["client_id", "company_id"],
    )
    op.create_index(
        "ix_client_kyc_documents_uploaded_by_membership_id",
        _TABLE,
        ["uploaded_by_membership_id"],
    )
    op.create_index(
        "ix_client_kyc_documents_uploaded_by_portal_user_id",
        _TABLE,
        ["uploaded_by_portal_user_id"],
    )
    op.create_index(
        "ix_client_kyc_documents_reviewed_by_membership_id",
        _TABLE,
        ["reviewed_by_membership_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Client KYC documents and their review evidence are retained; restore-forward only."
    )
