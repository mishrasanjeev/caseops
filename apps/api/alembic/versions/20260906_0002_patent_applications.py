"""Add independent, source-pinned patent applications and immutable identifiers.

Revision ID: 20260906_0002
Revises: 20260906_0001
DATA-GOVERNANCE-MAP: updated
"""

# MIGRATION-LOCK-RISK: acknowledged: all indexes belong to the four application
# tables created empty in this transaction, not populated shared owner tables.
# MIGRATION-ROLLBACK: restore-forward: downgrade locks and checks all four tables
# before any drop, refusing every retained application or identifier row.

import sqlalchemy as sa

from alembic import op

revision = "20260906_0002"
down_revision = "20260906_0001"
branch_labels = None
depends_on = None

TABLES = (
    "ip_patent_applications",
    "ip_patent_application_versions",
    "ip_patent_application_identifiers",
    "ip_patent_application_identities",
)
IMMUTABLE_TABLES = TABLES[1:3]


def _source_columns() -> list[sa.Column]:
    return [
        sa.Column("source_document_id", sa.String(36), nullable=False),
        sa.Column("source_document_version_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
    ]


def _source_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["source_document_version_id", "company_id", "source_document_id"],
        [
            "ip_document_versions.id",
            "ip_document_versions.company_id",
            "ip_document_versions.document_id",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def _version_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["application_version_id", "company_id", "application_id"],
        [
            "ip_patent_application_versions.id",
            "ip_patent_application_versions.company_id",
            "ip_patent_application_versions.application_id",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def _immutability(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text("""
            CREATE FUNCTION reject_patent_application_evidence_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Patent application evidence is append-only'
                    USING ERRCODE = '23514';
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        for table in IMMUTABLE_TABLES:
            bind.execute(
                sa.text(f"""
                CREATE TRIGGER trg_{table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_patent_application_evidence_mutation()
            """)
            )
    elif bind.dialect.name == "sqlite":
        for table in IMMUTABLE_TABLES:
            for operation in ("UPDATE", "DELETE"):
                bind.execute(
                    sa.text(f"""
                    CREATE TRIGGER trg_{table}_append_only_{operation.lower()}
                    BEFORE {operation} ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, 'Patent application evidence is append-only');
                    END
                """)
                )


def upgrade() -> None:
    op.create_table(
        TABLES[0],
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("prosecution_phase", sa.String(32), nullable=False, server_default="disclosure"),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_patent_application_docket_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "company_id"],
            ["ip_assets.id", "ip_assets.company_id"],
            name="fk_patent_application_asset_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "company_id"],
            ["ip_patent_families.id", "ip_patent_families.company_id"],
            name="fk_patent_application_family_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_patent_application_id_company"),
        sa.UniqueConstraint("company_id", "docket_id", name="uq_patent_application_docket"),
        sa.UniqueConstraint("company_id", "asset_id", name="uq_patent_application_asset"),
    )
    op.create_index(
        "ix_patent_applications_company_family", TABLES[0], ["company_id", "family_id", "id"]
    )
    op.create_index("ix_patent_applications_company_cursor", TABLES[0], ["company_id", "id"])
    op.create_table(
        TABLES[1],
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("application_kind", sa.String(32), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("office", sa.String(80), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("source_pending_identifier_allocation", sa.Boolean(), nullable=False),
        *_source_columns(),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["ip_patent_applications.id", "ip_patent_applications.company_id"],
            name="fk_patent_app_version_application",
            ondelete="RESTRICT",
        ),
        _source_fk("fk_patent_app_version_source"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_patent_app_version_actor",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_patent_app_version_id_company"),
        sa.UniqueConstraint(
            "id", "company_id", "application_id", name="uq_patent_app_version_owner"
        ),
        sa.UniqueConstraint(
            "company_id", "application_id", "version", name="uq_patent_app_version_number"
        ),
        sa.CheckConstraint("version > 0", name="ck_patent_app_version_positive"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_patent_app_version_hash"),
        sa.CheckConstraint(
            "publication_date IS NULL OR filing_date IS NULL OR publication_date >= filing_date",
            name="ck_patent_app_version_dates",
        ),
    )
    op.create_index(
        "ix_patent_app_versions_source",
        TABLES[1],
        ["company_id", "source_document_version_id", "source_document_id"],
    )
    op.create_index(
        "ix_patent_app_versions_actor", TABLES[1], ["company_id", "created_by_membership_id"]
    )
    op.create_table(
        TABLES[2],
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("application_version_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("identifier_kind", sa.String(20), nullable=False),
        sa.Column("raw_value", sa.String(120), nullable=False),
        *_source_columns(),
        _version_fk("fk_patent_app_identifier_version"),
        _source_fk("fk_patent_app_identifier_source"),
        sa.UniqueConstraint("id", "company_id", name="uq_patent_app_identifier_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "application_version_id",
            "ordinal",
            name="uq_patent_app_identifier_ordinal",
        ),
        sa.CheckConstraint(
            "ordinal >= 0 AND ordinal < 20", name="ck_patent_app_identifier_ordinal"
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_patent_app_identifier_hash"),
    )
    op.create_index(
        "ix_patent_app_identifiers_version_owner",
        TABLES[2],
        ["company_id", "application_version_id", "application_id"],
    )
    op.create_index(
        "ix_patent_app_identifiers_source",
        TABLES[2],
        ["company_id", "source_document_version_id", "source_document_id"],
    )
    op.create_table(
        TABLES[3],
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("application_version_id", sa.String(36), nullable=False),
        sa.Column("identity_sha256", sa.String(64), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("office_key", sa.String(320), nullable=False),
        sa.Column("identifier_kind", sa.String(20), nullable=False),
        sa.Column("value_key", sa.String(480), nullable=False),
        _version_fk("fk_patent_app_identity_version"),
        sa.UniqueConstraint("company_id", "identity_sha256", name="uq_patent_app_identity_scope"),
        sa.CheckConstraint("length(identity_sha256) = 64", name="ck_patent_app_identity_hash"),
    )
    op.create_index(
        "ix_patent_app_identities_application", TABLES[3], ["company_id", "application_id"]
    )
    op.create_index(
        "ix_patent_app_identities_lookup", TABLES[3], ["company_id", "value_key", "application_id"]
    )
    op.create_index(
        "ix_patent_app_identities_version_owner",
        TABLES[3],
        ["company_id", "application_version_id", "application_id"],
    )
    _immutability(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f"LOCK TABLE {', '.join(TABLES)} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Patent application evidence exists; restore forward instead of deleting it."
            )
    for table in reversed(TABLES):
        op.drop_table(table)
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP FUNCTION reject_patent_application_evidence_mutation()"))
