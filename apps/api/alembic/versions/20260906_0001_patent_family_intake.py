"""Add restricted patent-family facts without changing trademark records.

Revision ID: 20260906_0001
Revises: 20260905_0003
DATA-GOVERNANCE-MAP: updated
"""

# MIGRATION-LOCK-RISK: acknowledged: indexes cover only tables created empty in
# this transaction; no populated shared table is scanned or indexed here.
# MIGRATION-ROLLBACK: restore-forward: downgrade locks the family tables and
# refuses retained disclosure evidence; table removal is limited to empty data.

import sqlalchemy as sa

from alembic import op

revision = "20260906_0001"
down_revision = "20260905_0003"
branch_labels = None
depends_on = None


def _create_version_immutability(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text("""
            CREATE FUNCTION reject_patent_family_version_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Patent disclosure versions are append-only'
                    USING ERRCODE = '23514';
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        bind.execute(
            sa.text("""
            CREATE TRIGGER trg_patent_family_versions_append_only
            BEFORE UPDATE OR DELETE ON ip_patent_family_versions
            FOR EACH ROW EXECUTE FUNCTION reject_patent_family_version_mutation()
        """)
        )
    elif bind.dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            bind.execute(
                sa.text(f"""
                CREATE TRIGGER trg_patent_family_versions_append_only_{operation.lower()}
                BEFORE {operation} ON ip_patent_family_versions
                BEGIN
                    SELECT RAISE(ABORT, 'Patent disclosure versions are append-only');
                END
            """)
            )


def upgrade() -> None:
    op.create_table(
        "ip_patent_families",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_patent_family_docket_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "company_id"],
            ["ip_assets.id", "ip_assets.company_id"],
            name="fk_patent_family_asset_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            name="fk_patent_family_client_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_patent_family_id_company"),
        sa.UniqueConstraint("company_id", "docket_id", name="uq_patent_family_company_docket"),
        sa.UniqueConstraint("company_id", "asset_id", name="uq_patent_family_company_asset"),
    )
    op.create_index(
        "ix_patent_families_company_client",
        "ip_patent_families",
        ["company_id", "client_id", "id"],
    )
    op.create_index(
        "ix_patent_families_company_cursor",
        "ip_patent_families",
        ["company_id", "id"],
    )
    op.create_table(
        "ip_patent_family_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("disclosure_date", sa.Date(), nullable=False),
        sa.Column("disclosure_narrative", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.String(36), nullable=True),
        sa.Column("source_document_version_id", sa.String(36), nullable=True),
        sa.Column("source_registry_snapshot_id", sa.String(36), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("source_normalized_sha256", sa.String(64), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_id", "company_id"],
            ["ip_patent_families.id", "ip_patent_families.company_id"],
            name="fk_patent_family_version_family_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            name="fk_patent_family_version_client_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_patent_family_version_actor_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            name="fk_patent_family_version_document_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_registry_snapshot_id", "company_id"],
            ["ip_registry_snapshots.id", "ip_registry_snapshots.company_id"],
            name="fk_patent_family_version_registry_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_patent_family_version_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "family_id",
            "version",
            name="uq_patent_family_version_number",
        ),
        sa.CheckConstraint("version > 0", name="ck_patent_family_version_positive"),
        sa.CheckConstraint(
            "(source_document_version_id IS NULL AND source_document_id IS NULL "
            "AND source_registry_snapshot_id IS NULL "
            "AND source_sha256 IS NULL AND source_normalized_sha256 IS NULL) OR "
            "(source_document_version_id IS NOT NULL AND source_document_id IS NOT NULL "
            "AND source_registry_snapshot_id IS NULL "
            "AND source_sha256 IS NOT NULL AND length(source_sha256) = 64 "
            "AND source_normalized_sha256 IS NULL) OR "
            "(source_document_version_id IS NULL AND source_document_id IS NULL "
            "AND source_registry_snapshot_id IS NOT NULL "
            "AND source_sha256 IS NOT NULL AND source_normalized_sha256 IS NOT NULL "
            "AND length(source_sha256) = 64 AND length(source_normalized_sha256) = 64)",
            name="ck_patent_family_version_source_pin",
        ),
    )
    op.create_index(
        "ix_patent_family_versions_company_created",
        "ip_patent_family_versions",
        ["company_id", "created_at", "id"],
    )
    for suffix, column in (
        ("client", "client_id"),
        ("actor", "created_by_membership_id"),
        ("document", "source_document_version_id"),
        ("registry", "source_registry_snapshot_id"),
    ):
        op.create_index(
            f"ix_patent_family_versions_company_{suffix}",
            "ip_patent_family_versions",
            ["company_id", column, *(["source_document_id"] if suffix == "document" else [])],
        )
    _create_version_immutability(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE ip_patent_families, ip_patent_family_versions IN ACCESS EXCLUSIVE MODE"
            )
        )
    if bind.execute(sa.text("SELECT 1 FROM ip_patent_families LIMIT 1")).first():
        raise RuntimeError(
            "Patent disclosure evidence exists; restore forward instead of deleting it."
        )
    op.drop_table("ip_patent_family_versions")
    op.drop_table("ip_patent_families")
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP FUNCTION reject_patent_family_version_mutation()"))
