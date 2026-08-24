"""Extend authority sources with licensed-provider lineage and review state.

Revision ID: 20260825_0001
Revises: 20260824_0003
Create Date: 2026-08-25

IPLF-054 extends the canonical authority document and immutable research-report
owners. It does not create a parallel legal-source corpus.

MIGRATION-LOCK-RISK: acknowledged: additive nullable columns, two constant
defaults, and bounded index creation; PostgreSQL lock timeout is five seconds.
MIGRATION-ROLLBACK: restore-forward: an empty pre-activation schema may be
downgraded, but after licensed source data or report lineage exists the
downgrade refuses and operators must restore-forward.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260825_0001"
down_revision = "20260824_0003"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    with op.batch_alter_table("authority_research_reports") as batch:
        batch.add_column(sa.Column("invalidated_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("invalidation_reason", sa.Text()))
        batch.create_index(
            "ix_authority_research_reports_invalidated_at", ["invalidated_at"]
        )

    with op.batch_alter_table("authority_documents") as batch:
        batch.add_column(sa.Column("provider_document_id", sa.String(length=120)))
        batch.add_column(sa.Column("publisher_name", sa.String(length=255)))
        batch.add_column(sa.Column("jurisdiction", sa.String(length=120)))
        batch.add_column(sa.Column("issuing_body", sa.String(length=255)))
        batch.add_column(sa.Column("source_category", sa.String(length=80)))
        batch.add_column(sa.Column("authority_status", sa.String(length=80)))
        batch.add_column(sa.Column("binding_status", sa.String(length=80)))
        batch.add_column(sa.Column("canonical_url", sa.String(length=500)))
        batch.add_column(sa.Column("content_hash", sa.String(length=64)))
        batch.add_column(sa.Column("source_version", sa.String(length=120)))
        batch.add_column(sa.Column("retrieved_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column(
                "source_access_state",
                sa.String(length=40),
                nullable=False,
                server_default="available",
            )
        )
        batch.add_column(sa.Column("attribution_json", sa.JSON()))
        batch.add_column(sa.Column("license_policy_version", sa.String(length=80)))
        batch.add_column(sa.Column("source_metadata_json", sa.JSON()))
        batch.add_column(
            sa.Column(
                "legal_review_status",
                sa.String(length=32),
                nullable=False,
                server_default="unreviewed",
            )
        )
        batch.add_column(
            sa.Column(
                "first_reviewed_by_membership_id",
                sa.String(length=36),
            )
        )
        batch.add_column(sa.Column("first_reviewed_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column(
                "second_reviewed_by_membership_id",
                sa.String(length=36),
            )
        )
        batch.add_column(sa.Column("second_reviewed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("legal_review_note", sa.Text()))
        batch.create_index(
            "ix_authority_documents_provider_document_id", ["provider_document_id"]
        )
        batch.create_index("ix_authority_documents_jurisdiction", ["jurisdiction"])
        batch.create_index("ix_authority_documents_source_category", ["source_category"])
        batch.create_index("ix_authority_documents_content_hash", ["content_hash"])
        batch.create_index(
            "ix_authority_documents_legal_review_status", ["legal_review_status"]
        )
        batch.create_index(
            "ix_authority_documents_first_reviewed_by_membership_id",
            ["first_reviewed_by_membership_id"],
        )
        batch.create_index(
            "ix_authority_documents_second_reviewed_by_membership_id",
            ["second_reviewed_by_membership_id"],
        )
        batch.create_foreign_key(
            "fk_authority_documents_first_legal_reviewer",
            "company_memberships",
            ["first_reviewed_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_authority_documents_second_legal_reviewer",
            "company_memberships",
            ["second_reviewed_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "authority_research_report_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "report_id",
            sa.String(length=36),
            sa.ForeignKey("authority_research_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "authority_document_id",
            sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("source_version", sa.String(length=120)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "report_id",
            "authority_document_id",
            name="uq_authority_research_report_source",
        ),
    )
    op.create_index(
        "ix_authority_research_report_sources_report_id",
        "authority_research_report_sources",
        ["report_id"],
    )
    op.create_index(
        "ix_authority_research_report_sources_document",
        "authority_research_report_sources",
        ["authority_document_id", "content_hash"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    licensed_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM authority_documents "
            "WHERE source = 'indian_kanoon_licensed'"
        )
    ).scalar_one()
    lineage_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM authority_research_report_sources")
    ).scalar_one()
    if licensed_count or lineage_count:
        raise RuntimeError(
            "Refusing IPLF-054 downgrade after licensed authority lineage exists."
        )

    op.drop_index(
        "ix_authority_research_report_sources_document",
        table_name="authority_research_report_sources",
    )
    op.drop_index(
        "ix_authority_research_report_sources_report_id",
        table_name="authority_research_report_sources",
    )
    op.drop_table("authority_research_report_sources")

    with op.batch_alter_table("authority_documents") as batch:
        batch.drop_constraint(
            "fk_authority_documents_second_legal_reviewer", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_authority_documents_first_legal_reviewer", type_="foreignkey"
        )
        batch.drop_index("ix_authority_documents_second_reviewed_by_membership_id")
        batch.drop_index("ix_authority_documents_first_reviewed_by_membership_id")
        batch.drop_index("ix_authority_documents_legal_review_status")
        batch.drop_index("ix_authority_documents_content_hash")
        batch.drop_index("ix_authority_documents_source_category")
        batch.drop_index("ix_authority_documents_jurisdiction")
        batch.drop_index("ix_authority_documents_provider_document_id")
        for column in (
            "legal_review_note",
            "second_reviewed_at",
            "second_reviewed_by_membership_id",
            "first_reviewed_at",
            "first_reviewed_by_membership_id",
            "legal_review_status",
            "source_metadata_json",
            "license_policy_version",
            "attribution_json",
            "source_access_state",
            "retrieved_at",
            "source_version",
            "content_hash",
            "canonical_url",
            "binding_status",
            "authority_status",
            "source_category",
            "issuing_body",
            "jurisdiction",
            "publisher_name",
            "provider_document_id",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("authority_research_reports") as batch:
        batch.drop_index("ix_authority_research_reports_invalidated_at")
        batch.drop_column("invalidation_reason")
        batch.drop_column("invalidated_at")
