"""LegalWorkspace LW-S9 contract metadata enhancements.

Revision ID: 20260506_0004
Revises: 20260506_0003
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260506_0004"
down_revision = "20260506_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    with op.batch_alter_table("contracts") as batch:
        batch.add_column(sa.Column("contract_type_key", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("contract_type_notes", sa.Text(), nullable=True))

    known_type_updates = {
        "agreement": ("agreement", "general agreement"),
        "nda": ("nda", "non disclosure agreement", "non-disclosure agreement"),
        "addendum": ("addendum",),
        "purchase_order": ("purchase order", "po"),
        "master_services_agreement": (
            "master services agreement",
            "master service agreement",
            "msa",
        ),
        "statement_of_work": ("statement of work", "sow"),
        "lease": ("lease", "lease agreement"),
        "employment": ("employment", "employment agreement"),
        "settlement": ("settlement", "settlement agreement"),
        "amendment": ("amendment",),
    }
    for contract_type_key, labels in known_type_updates.items():
        quoted_labels = ", ".join(f"'{label}'" for label in labels)
        op.execute(
            "UPDATE contracts "
            f"SET contract_type_key = '{contract_type_key}' "
            "WHERE contract_type_key IS NULL "
            f"AND lower(trim(replace(replace(contract_type, '_', ' '), '-', ' '))) "
            f"IN ({quoted_labels})"
        )
    op.execute(
        "UPDATE contracts "
        "SET contract_type_key = 'other', contract_type_notes = contract_type "
        "WHERE contract_type_key IS NULL"
    )

    op.create_table(
        "contract_legal_references",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            sa.String(length=36),
            sa.ForeignKey("contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("act_name", sa.String(length=255), nullable=False),
        sa.Column("section_label", sa.String(length=120), nullable=True),
        sa.Column("clause_label", sa.String(length=120), nullable=True),
        sa.Column(
            "authority_id",
            sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "statute_id",
            sa.String(length=64),
            sa.ForeignKey("statutes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "evidence_attachment_id",
            sa.String(length=36),
            sa.ForeignKey("contract_attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="accepted"),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_contract_legal_references_company_id",
        "contract_legal_references",
        ["company_id"],
    )
    op.create_index(
        "ix_contract_legal_references_contract_id",
        "contract_legal_references",
        ["contract_id"],
    )
    op.create_index(
        "ix_contract_legal_references_authority_id",
        "contract_legal_references",
        ["authority_id"],
    )
    op.create_index(
        "ix_contract_legal_references_statute_id",
        "contract_legal_references",
        ["statute_id"],
    )
    op.create_index(
        "ix_contract_legal_references_evidence_attachment_id",
        "contract_legal_references",
        ["evidence_attachment_id"],
    )
    op.create_index(
        "ix_contract_legal_references_created_by_membership_id",
        "contract_legal_references",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_contract_legal_references_reviewed_by_membership_id",
        "contract_legal_references",
        ["reviewed_by_membership_id"],
    )

    op.create_table(
        "contract_term_suggestions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            sa.String(length=36),
            sa.ForeignKey("contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_attachment_id",
            sa.String(length=36),
            sa.ForeignKey("contract_attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suggested_effective_on", sa.Date(), nullable=True),
        sa.Column("suggested_expires_on", sa.Date(), nullable=True),
        sa.Column("suggested_renewal_on", sa.Date(), nullable=True),
        sa.Column("suggested_duration_months", sa.Integer(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="suggested"),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_contract_term_suggestions_company_id",
        "contract_term_suggestions",
        ["company_id"],
    )
    op.create_index(
        "ix_contract_term_suggestions_contract_id",
        "contract_term_suggestions",
        ["contract_id"],
    )
    op.create_index(
        "ix_contract_term_suggestions_source_attachment_id",
        "contract_term_suggestions",
        ["source_attachment_id"],
    )
    op.create_index(
        "ix_contract_term_suggestions_created_by_membership_id",
        "contract_term_suggestions",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_contract_term_suggestions_reviewed_by_membership_id",
        "contract_term_suggestions",
        ["reviewed_by_membership_id"],
    )

    with op.batch_alter_table("contract_attachments") as batch:
        batch.add_column(sa.Column("attachment_role", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("parent_attachment_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("document_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_contract_attachments_parent_attachment_id",
            "contract_attachments",
            ["parent_attachment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_contract_attachments_parent_attachment_id",
            ["parent_attachment_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("contract_attachments") as batch:
        batch.drop_index("ix_contract_attachments_parent_attachment_id")
        batch.drop_constraint(
            "fk_contract_attachments_parent_attachment_id",
            type_="foreignkey",
        )
        batch.drop_column("notes")
        batch.drop_column("document_date")
        batch.drop_column("parent_attachment_id")
        batch.drop_column("attachment_role")

    op.drop_index(
        "ix_contract_term_suggestions_reviewed_by_membership_id",
        table_name="contract_term_suggestions",
    )
    op.drop_index(
        "ix_contract_term_suggestions_created_by_membership_id",
        table_name="contract_term_suggestions",
    )
    op.drop_index(
        "ix_contract_term_suggestions_source_attachment_id",
        table_name="contract_term_suggestions",
    )
    op.drop_index(
        "ix_contract_term_suggestions_contract_id",
        table_name="contract_term_suggestions",
    )
    op.drop_index(
        "ix_contract_term_suggestions_company_id",
        table_name="contract_term_suggestions",
    )
    op.drop_table("contract_term_suggestions")

    op.drop_index(
        "ix_contract_legal_references_reviewed_by_membership_id",
        table_name="contract_legal_references",
    )
    op.drop_index(
        "ix_contract_legal_references_created_by_membership_id",
        table_name="contract_legal_references",
    )
    op.drop_index(
        "ix_contract_legal_references_evidence_attachment_id",
        table_name="contract_legal_references",
    )
    op.drop_index(
        "ix_contract_legal_references_statute_id",
        table_name="contract_legal_references",
    )
    op.drop_index(
        "ix_contract_legal_references_authority_id",
        table_name="contract_legal_references",
    )
    op.drop_index(
        "ix_contract_legal_references_contract_id",
        table_name="contract_legal_references",
    )
    op.drop_index(
        "ix_contract_legal_references_company_id",
        table_name="contract_legal_references",
    )
    op.drop_table("contract_legal_references")

    with op.batch_alter_table("contracts") as batch:
        batch.drop_column("contract_type_notes")
        batch.drop_column("contract_type_key")
