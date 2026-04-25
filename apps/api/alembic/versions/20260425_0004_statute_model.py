"""Statute + Bare Acts Model — Slice S1 (MOD-TS-017).

Per docs/PRD_STATUTE_MODEL_2026-04-25.md §3. Adds 4 tables:

- statutes: master act roster (BNSS, BNS, BSA, CrPC, IPC,
  Constitution, NI Act).
- statute_sections: one row per Section / Article / Order-Rule under
  each Act. section_text is nullable so the seed can ship section
  numbers + labels first; bare text fetched lazily.
- matter_statute_references: Matter → StatuteSection link with
  relevance label.
- authority_statute_references: AuthorityDocument → StatuteSection
  link populated by Slice S3's resolver.

Schema decisions worth flagging:
- statutes.id is a string (e.g. 'bnss-2023') not uuid for human-
  readable URL paths and seed idempotence.
- statute_sections uses a UUID id but (statute_id, section_number)
  is unique so the resolver can look up by natural key.
- matter_statute_references.relevance is a free text string (not
  enum) so we can add 'opposing', 'context', etc. without a
  migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0004"
down_revision = "20260425_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statutes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("short_name", sa.String(length=64), nullable=False),
        sa.Column("long_name", sa.String(length=255), nullable=False),
        sa.Column("enacted_year", sa.Integer(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=64), nullable=False, server_default="india"),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_statutes_short_name", "statutes", ["short_name"])

    op.create_table(
        "statute_sections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "statute_id", sa.String(length=64),
            sa.ForeignKey("statutes.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("section_number", sa.String(length=64), nullable=False),
        sa.Column("section_label", sa.String(length=500), nullable=True),
        sa.Column("section_text", sa.Text(), nullable=True),
        sa.Column("section_url", sa.String(length=500), nullable=True),
        sa.Column(
            "parent_section_id", sa.String(length=36),
            sa.ForeignKey("statute_sections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "statute_id", "section_number",
            name="uq_statute_sections_unique",
        ),
    )
    op.create_index(
        "ix_statute_sections_lookup",
        "statute_sections",
        ["statute_id", "ordinal"],
    )

    op.create_table(
        "matter_statute_references",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id", sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "section_id", sa.String(length=36),
            sa.ForeignKey("statute_sections.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column(
            "relevance", sa.String(length=32), nullable=False,
            server_default="cited",
        ),
        sa.Column(
            "added_by_membership_id", sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "matter_id", "section_id", "relevance",
            name="uq_matter_statute_references_unique",
        ),
    )

    op.create_table(
        "authority_statute_references",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "authority_id", sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "section_id", sa.String(length=36),
            sa.ForeignKey("statute_sections.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column(
            "occurrence_count", sa.Integer(), nullable=False, server_default="1",
        ),
        sa.Column(
            "source", sa.String(length=64), nullable=False,
            server_default="layer2_extract",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "authority_id", "section_id",
            name="uq_authority_statute_references_unique",
        ),
    )


def downgrade() -> None:
    op.drop_table("authority_statute_references")
    op.drop_table("matter_statute_references")
    op.drop_index("ix_statute_sections_lookup", table_name="statute_sections")
    op.drop_table("statute_sections")
    op.drop_index("ix_statutes_short_name", table_name="statutes")
    op.drop_table("statutes")
