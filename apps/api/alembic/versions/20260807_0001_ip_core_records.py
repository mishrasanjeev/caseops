"""Add canonical IP asset, application, proceeding, and identifier records.

Revision ID: 20260807_0001
Revises: 20260804_0004
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260807_0001"
down_revision = "20260804_0004"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch_op:
        batch_op.create_unique_constraint("uq_clients_id_company", ["id", "company_id"])

    created_at, updated_at = _timestamps()
    op.create_table(
        "ip_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("asset_kind", sa.String(40), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_asset_docket_company",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_asset_id_company"),
        sa.UniqueConstraint("company_id", "docket_id", name="uq_ip_asset_company_docket"),
    )
    op.create_index("ix_ip_assets_docket_id", "ip_assets", ["docket_id"])
    op.create_index("ix_ip_assets_company_kind", "ip_assets", ["company_id", "asset_kind"])

    created_at, updated_at = _timestamps()
    op.create_table(
        "trademark_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("office", sa.String(80), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("filing_phase", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "source_pending_identifier_allocation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_tm_application_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "company_id"],
            ["ip_assets.id", "ip_assets.company_id"],
            name="fk_tm_application_asset_company",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_tm_application_id_company"),
    )
    op.create_index(
        "ix_tm_applications_company_phase",
        "trademark_applications",
        ["company_id", "filing_phase"],
    )
    op.create_index("ix_trademark_applications_docket_id", "trademark_applications", ["docket_id"])
    op.create_index("ix_trademark_applications_asset_id", "trademark_applications", ["asset_id"])

    op.create_table(
        "trademark_application_scopes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("class_number", sa.Integer(), nullable=False),
        sa.Column("specification", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_tm_scope_application_company",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_tm_scope_effective_range",
        ),
        sa.UniqueConstraint(
            "application_id",
            "class_number",
            "effective_from",
            name="uq_tm_scope_application_class_effective",
        ),
    )
    op.create_index(
        "ix_tm_scopes_company_application",
        "trademark_application_scopes",
        ["company_id", "application_id"],
    )

    op.create_table(
        "trademark_representations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("representation_kind", sa.String(40), nullable=False),
        sa.Column("display_text", sa.String(500), nullable=True),
        sa.Column("document_reference", sa.String(500), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_tm_representation_application_company",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("application_id", "version", name="uq_tm_representation_version"),
    )
    op.create_index(
        "ix_tm_representations_company_application",
        "trademark_representations",
        ["company_id", "application_id"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "ip_proceedings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("proceeding_kind", sa.String(40), nullable=False),
        sa.Column("side", sa.String(24), nullable=False),
        sa.Column("office", sa.String(80), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_proceeding_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_proceeding_application_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_proceeding_id_company"),
    )
    op.create_index(
        "ix_ip_proceedings_company_kind", "ip_proceedings", ["company_id", "proceeding_kind"]
    )
    op.create_index("ix_ip_proceedings_docket_id", "ip_proceedings", ["docket_id"])
    op.create_index("ix_ip_proceedings_application_id", "ip_proceedings", ["application_id"])

    op.create_table(
        "ip_identifiers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("proceeding_id", sa.String(36), nullable=True),
        sa.Column("identifier_kind", sa.String(40), nullable=False),
        sa.Column("raw_value", sa.String(160), nullable=False),
        sa.Column("normalized_value", sa.String(160), nullable=False),
        sa.Column("office", sa.String(80), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "reconciliation_status",
            sa.String(32),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column("supersedes_identifier_id", sa.String(36), nullable=True),
        sa.Column("correction_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_identifier_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_identifier_application_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_identifier_proceeding_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_identifier_id"],
            ["ip_identifiers.id"],
            name="fk_ip_identifier_supersedes",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(application_id IS NOT NULL AND proceeding_id IS NULL) OR "
            "(application_id IS NULL AND proceeding_id IS NOT NULL)",
            name="ck_ip_identifier_single_owner",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_identifier_effective_range",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_identifier_id_company"),
    )
    op.create_index(
        "ix_ip_identifiers_company_search",
        "ip_identifiers",
        ["company_id", "identifier_kind", "normalized_value"],
    )
    op.create_index(
        "ix_ip_identifiers_company_docket", "ip_identifiers", ["company_id", "docket_id"]
    )
    op.create_index("ix_ip_identifiers_docket_id", "ip_identifiers", ["docket_id"])
    op.create_index("ix_ip_identifiers_application_id", "ip_identifiers", ["application_id"])
    op.create_index("ix_ip_identifiers_proceeding_id", "ip_identifiers", ["proceeding_id"])
    op.create_index(
        "ix_ip_identifiers_supersedes_identifier_id",
        "ip_identifiers",
        ["supersedes_identifier_id"],
    )

    op.create_table(
        "ip_parties_and_roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("party_name", sa.String(255), nullable=False),
        sa.Column("role_kind", sa.String(40), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_party_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            name="fk_ip_party_client_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_party_effective_range",
        ),
    )
    op.create_index(
        "ix_ip_parties_company_docket", "ip_parties_and_roles", ["company_id", "docket_id"]
    )
    op.create_index("ix_ip_parties_and_roles_docket_id", "ip_parties_and_roles", ["docket_id"])
    op.create_index("ix_ip_parties_and_roles_client_id", "ip_parties_and_roles", ["client_id"])

    op.create_table(
        "ip_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("source_docket_id", sa.String(36), nullable=False),
        sa.Column("target_docket_id", sa.String(36), nullable=False),
        sa.Column("relationship_kind", sa.String(40), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["source_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_relationship_source_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_relationship_target_company",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_docket_id <> target_docket_id",
            name="ck_ip_relationship_distinct_dockets",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_relationship_effective_range",
        ),
        sa.UniqueConstraint(
            "company_id",
            "source_docket_id",
            "target_docket_id",
            "relationship_kind",
            "effective_from",
            name="uq_ip_relationship_effective",
        ),
    )
    op.create_index(
        "ix_ip_relationships_company_source",
        "ip_relationships",
        ["company_id", "source_docket_id"],
    )
    op.create_index(
        "ix_ip_relationships_company_target",
        "ip_relationships",
        ["company_id", "target_docket_id"],
    )
    op.create_index(
        "ix_ip_relationships_source_docket_id", "ip_relationships", ["source_docket_id"]
    )
    op.create_index(
        "ix_ip_relationships_target_docket_id", "ip_relationships", ["target_docket_id"]
    )


def downgrade() -> None:
    op.drop_table("ip_relationships")
    op.drop_table("ip_parties_and_roles")
    op.drop_table("ip_identifiers")
    op.drop_table("ip_proceedings")
    op.drop_table("trademark_representations")
    op.drop_table("trademark_application_scopes")
    op.drop_table("trademark_applications")
    op.drop_table("ip_assets")
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_constraint("uq_clients_id_company", type_="unique")
