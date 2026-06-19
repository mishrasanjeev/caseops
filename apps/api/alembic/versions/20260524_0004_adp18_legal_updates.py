"""ADP-18 law amendment and regulatory update monitor.

Revision ID: 20260524_0004
Revises: 20260524_0003
Create Date: 2026-05-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260524_0004"
down_revision = "20260524_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "legal_update_watchlists",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("practice_area", sa.String(length=120), nullable=True),
        sa.Column(
            "statute_id",
            sa.String(length=64),
            sa.ForeignKey("statutes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("jurisdiction", sa.String(length=120), nullable=True),
        sa.Column("statute_terms_json", sa.JSON(), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=True),
        sa.Column("source_category", sa.String(length=80), nullable=True),
        sa.Column("update_types_json", sa.JSON(), nullable=True),
        sa.Column("since_date", sa.Date(), nullable=True),
        sa.Column("until_date", sa.Date(), nullable=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contract_id",
            sa.String(length=36),
            sa.ForeignKey("contracts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_legal_update_watchlists_company_id",
        "legal_update_watchlists",
        ["company_id"],
    )
    op.create_index(
        "ix_legal_update_watchlists_created_by_membership_id",
        "legal_update_watchlists",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_legal_update_watchlists_statute_id",
        "legal_update_watchlists",
        ["statute_id"],
    )
    op.create_index(
        "ix_legal_update_watchlists_source_key",
        "legal_update_watchlists",
        ["source_key"],
    )
    op.create_index(
        "ix_legal_update_watchlists_source_category",
        "legal_update_watchlists",
        ["source_category"],
    )
    op.create_index(
        "ix_legal_update_watchlists_matter_id",
        "legal_update_watchlists",
        ["matter_id"],
    )
    op.create_index(
        "ix_legal_update_watchlists_contract_id",
        "legal_update_watchlists",
        ["contract_id"],
    )
    op.create_index(
        "ix_legal_update_watchlists_is_archived",
        "legal_update_watchlists",
        ["is_archived"],
    )

    op.create_table(
        "legal_update_alerts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "watchlist_id",
            sa.String(length=36),
            sa.ForeignKey("legal_update_watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_record_key", sa.String(length=160), nullable=False),
        sa.Column("update_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "statute_id",
            sa.String(length=64),
            sa.ForeignKey("statutes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "statute_section_id",
            sa.String(length=36),
            sa.ForeignKey("statute_sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "authority_document_id",
            sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contract_id",
            sa.String(length=36),
            sa.ForeignKey("contracts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("statute_name", sa.String(length=255), nullable=True),
        sa.Column("section_number", sa.String(length=64), nullable=True),
        sa.Column("jurisdiction", sa.String(length=120), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("source_category", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("provenance_status", sa.String(length=80), nullable=False),
        sa.Column("relevance_explanation", sa.String(length=500), nullable=False),
        sa.Column("snippet", sa.String(length=280), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "watchlist_id",
            "source_record_key",
            name="uq_legal_update_watchlist_source_record",
        ),
    )
    op.create_index(
        "ix_legal_update_alerts_company_id",
        "legal_update_alerts",
        ["company_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_watchlist_id",
        "legal_update_alerts",
        ["watchlist_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_update_type",
        "legal_update_alerts",
        ["update_type"],
    )
    op.create_index(
        "ix_legal_update_alerts_statute_id",
        "legal_update_alerts",
        ["statute_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_statute_section_id",
        "legal_update_alerts",
        ["statute_section_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_authority_document_id",
        "legal_update_alerts",
        ["authority_document_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_matter_id",
        "legal_update_alerts",
        ["matter_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_contract_id",
        "legal_update_alerts",
        ["contract_id"],
    )
    op.create_index(
        "ix_legal_update_alerts_source_key",
        "legal_update_alerts",
        ["source_key"],
    )
    op.create_index(
        "ix_legal_update_alerts_source_category",
        "legal_update_alerts",
        ["source_category"],
    )
    op.create_index(
        "ix_legal_update_alerts_is_read",
        "legal_update_alerts",
        ["is_read"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_update_alerts_is_read", table_name="legal_update_alerts")
    op.drop_index(
        "ix_legal_update_alerts_source_category",
        table_name="legal_update_alerts",
    )
    op.drop_index("ix_legal_update_alerts_source_key", table_name="legal_update_alerts")
    op.drop_index("ix_legal_update_alerts_contract_id", table_name="legal_update_alerts")
    op.drop_index("ix_legal_update_alerts_matter_id", table_name="legal_update_alerts")
    op.drop_index(
        "ix_legal_update_alerts_authority_document_id",
        table_name="legal_update_alerts",
    )
    op.drop_index(
        "ix_legal_update_alerts_statute_section_id",
        table_name="legal_update_alerts",
    )
    op.drop_index("ix_legal_update_alerts_statute_id", table_name="legal_update_alerts")
    op.drop_index("ix_legal_update_alerts_update_type", table_name="legal_update_alerts")
    op.drop_index("ix_legal_update_alerts_watchlist_id", table_name="legal_update_alerts")
    op.drop_index("ix_legal_update_alerts_company_id", table_name="legal_update_alerts")
    op.drop_table("legal_update_alerts")

    op.drop_index(
        "ix_legal_update_watchlists_is_archived",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_contract_id",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_matter_id",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_source_category",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_source_key",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_statute_id",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_created_by_membership_id",
        table_name="legal_update_watchlists",
    )
    op.drop_index(
        "ix_legal_update_watchlists_company_id",
        table_name="legal_update_watchlists",
    )
    op.drop_table("legal_update_watchlists")
