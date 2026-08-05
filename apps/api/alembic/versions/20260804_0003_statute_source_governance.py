"""Add fail-closed statute source governance and immutable review records.

Revision ID: 20260804_0003
Revises: 20260804_0002
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260804_0003"
down_revision = "20260804_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("statutes") as batch:
        batch.add_column(sa.Column("issuing_body", sa.String(160), nullable=True))
        batch.add_column(
            sa.Column(
                "source_category",
                sa.String(32),
                nullable=False,
                server_default="consolidated_statute",
            )
        )
        batch.add_column(
            sa.Column(
                "source_status",
                sa.String(24),
                nullable=False,
                server_default="unverified",
            )
        )
        batch.add_column(
            sa.Column(
                "legal_status", sa.String(24), nullable=False, server_default="enacted"
            )
        )
        batch.add_column(
            sa.Column(
                "verification_status",
                sa.String(24),
                nullable=False,
                server_default="unverified",
            )
        )
        batch.add_column(sa.Column("publication_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("effective_from", sa.Date(), nullable=True))
        batch.add_column(sa.Column("effective_to", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("source_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("exact_source_version", sa.String(160), nullable=True))
        batch.add_column(
            sa.Column(
                "history_status",
                sa.String(32),
                nullable=False,
                server_default="current_text_only",
            )
        )
        batch.add_column(
            sa.Column(
                "source_policy_json", sa.JSON(), nullable=False, server_default="{}"
            )
        )
        batch.create_index(
            "ix_statutes_verification_status", ["verification_status"]
        )

    with op.batch_alter_table("statute_sections") as batch:
        batch.add_column(sa.Column("editorial_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("case_annotations", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ai_explanation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("issuing_body", sa.String(160), nullable=True))
        batch.add_column(
            sa.Column(
                "source_category",
                sa.String(32),
                nullable=False,
                server_default="consolidated_statute",
            )
        )
        batch.add_column(
            sa.Column(
                "source_status",
                sa.String(24),
                nullable=False,
                server_default="unverified",
            )
        )
        batch.add_column(
            sa.Column(
                "legal_status", sa.String(24), nullable=False, server_default="enacted"
            )
        )
        batch.add_column(sa.Column("publication_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("effective_from", sa.Date(), nullable=True))
        batch.add_column(sa.Column("effective_to", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column(
                "amendment_metadata_json", sa.JSON(), nullable=False, server_default="{}"
            )
        )
        batch.add_column(
            sa.Column(
                "history_status",
                sa.String(32),
                nullable=False,
                server_default="current_text_only",
            )
        )
        batch.add_column(sa.Column("exact_source_version", sa.String(160), nullable=True))
        batch.add_column(
            sa.Column(
                "source_locator_type",
                sa.String(32),
                nullable=False,
                server_default="unavailable",
            )
        )
        batch.add_column(
            sa.Column(
                "source_policy_json", sa.JSON(), nullable=False, server_default="{}"
            )
        )
        batch.add_column(
            sa.Column(
                "link_health_status",
                sa.String(24),
                nullable=False,
                server_default="not_checked",
            )
        )
        batch.add_column(
            sa.Column("link_last_checked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("link_last_error", sa.String(240), nullable=True))

    op.create_table(
        "statute_source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "section_id",
            sa.String(36),
            sa.ForeignKey("statute_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposed_source_version", sa.Integer(), nullable=False),
        sa.Column("candidate_text", sa.Text(), nullable=False),
        sa.Column("candidate_sha256", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("source_publisher", sa.String(160), nullable=False),
        sa.Column("issuing_body", sa.String(160), nullable=False),
        sa.Column("source_category", sa.String(32), nullable=False),
        sa.Column("source_status", sa.String(24), nullable=False),
        sa.Column("legal_status", sa.String(24), nullable=False),
        sa.Column("source_locator_type", sa.String(32), nullable=False),
        sa.Column("exact_source_version", sa.String(160), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "amendment_metadata_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("source_policy_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("diff_unified", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column(
            "proposed_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "section_id",
            "proposed_source_version",
            name="uq_statute_source_versions_section_version",
        ),
    )
    op.create_index(
        "ix_statute_source_versions_section_id",
        "statute_source_versions",
        ["section_id"],
    )
    op.create_index(
        "ix_statute_source_versions_proposed_by_membership_id",
        "statute_source_versions",
        ["proposed_by_membership_id"],
    )
    op.create_index(
        "ix_statute_source_versions_reviewed_by_membership_id",
        "statute_source_versions",
        ["reviewed_by_membership_id"],
    )

    op.create_table(
        "statute_source_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "section_id",
            sa.String(36),
            sa.ForeignKey("statute_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("disputed_facts_json", sa.JSON(), nullable=False),
        sa.Column("source_versions_json", sa.JSON(), nullable=False),
        sa.Column("authority_rank_json", sa.JSON(), nullable=False),
        sa.Column("affected_records_json", sa.JSON(), nullable=False),
        sa.Column("impact_scan_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column(
            "decision_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_statute_source_conflicts_section_id",
        "statute_source_conflicts",
        ["section_id"],
    )
    op.create_index(
        "ix_statute_source_conflicts_decision_by_membership_id",
        "statute_source_conflicts",
        ["decision_by_membership_id"],
    )
    op.create_index(
        "ix_statute_source_conflicts_created_by_membership_id",
        "statute_source_conflicts",
        ["created_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_statute_source_conflicts_created_by_membership_id",
        table_name="statute_source_conflicts",
    )
    op.drop_index(
        "ix_statute_source_conflicts_decision_by_membership_id",
        table_name="statute_source_conflicts",
    )
    op.drop_index(
        "ix_statute_source_conflicts_section_id",
        table_name="statute_source_conflicts",
    )
    op.drop_table("statute_source_conflicts")
    op.drop_index(
        "ix_statute_source_versions_reviewed_by_membership_id",
        table_name="statute_source_versions",
    )
    op.drop_index(
        "ix_statute_source_versions_proposed_by_membership_id",
        table_name="statute_source_versions",
    )
    op.drop_index(
        "ix_statute_source_versions_section_id",
        table_name="statute_source_versions",
    )
    op.drop_table("statute_source_versions")

    with op.batch_alter_table("statute_sections") as batch:
        for name in (
            "link_last_error",
            "link_last_checked_at",
            "link_health_status",
            "source_policy_json",
            "source_locator_type",
            "exact_source_version",
            "history_status",
            "amendment_metadata_json",
            "effective_to",
            "effective_from",
            "publication_date",
            "legal_status",
            "source_status",
            "source_category",
            "issuing_body",
            "ai_explanation",
            "case_annotations",
            "editorial_notes",
        ):
            batch.drop_column(name)

    with op.batch_alter_table("statutes") as batch:
        batch.drop_index("ix_statutes_verification_status")
        for name in (
            "source_policy_json",
            "history_status",
            "exact_source_version",
            "source_sha256",
            "source_retrieved_at",
            "effective_to",
            "effective_from",
            "publication_date",
            "verification_status",
            "legal_status",
            "source_status",
            "source_category",
            "issuing_body",
        ):
            batch.drop_column(name)
