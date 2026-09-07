"""Extend canonical IP parties with immutable, sourced patent facts.

Revision ID: 20260907_0001
Revises: 20260906_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged: build the existing-party owner index
concurrently on PostgreSQL; remaining DDL targets a new empty detail table.
MIGRATION-ROLLBACK: restore-forward: never remove retained patent party evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260907_0001"
down_revision = "20260906_0002"
branch_labels = None
depends_on = None

TABLE = "ip_patent_party_details"
OWNER = "ip_parties_and_roles"
OWNER_INDEX = "uq_ip_party_owner"


def _owner_index(bind: sa.Connection) -> None:
    columns = ["id", "company_id", "docket_id"]
    if bind.dialect.name != "postgresql":
        op.create_index(OWNER_INDEX, OWNER, columns, unique=True)
        return
    state_query = sa.text("""
        SELECT i.indisvalid, i.indisready, i.indisunique,
               i.indpred IS NULL AND i.indexprs IS NULL AS plain,
               i.indnkeyatts = i.indnatts AS no_includes,
               t.relname AS owner, am.amname AS method,
               ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum, pos)
                     JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                     ORDER BY k.pos) AS columns
        FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_am am ON am.oid = c.relam
        WHERE n.nspname = current_schema() AND c.relname = :name
    """)
    # An interrupted concurrent index can survive without the Alembic revision.
    with op.get_context().autocommit_block():
        state = bind.execute(state_query, {"name": OWNER_INDEX}).mappings().first()
        if state is not None:
            if not (
                state["indisunique"]
                and state["plain"]
                and state["no_includes"]
                and state["owner"] == OWNER
                and state["method"] == "btree"
                and list(state["columns"]) == columns
            ):
                raise RuntimeError("Existing IP party owner index has a conflicting shape.")
            if not state["indisvalid"] or not state["indisready"]:
                bind.execute(sa.text(f"DROP INDEX CONCURRENTLY {OWNER_INDEX}"))
        bind.execute(
            sa.text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {OWNER_INDEX} "
                f"ON {OWNER} (id, company_id, docket_id)"
            )
        )
        ready = bind.execute(state_query, {"name": OWNER_INDEX}).mappings().one()
        if not ready["indisvalid"] or not ready["indisready"]:
            raise RuntimeError("IP party owner index is not ready.")


def _guards(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(f"""
            CREATE FUNCTION reject_patent_party_evidence_mutation() RETURNS trigger AS $$
            BEGIN
                IF TG_TABLE_NAME = '{TABLE}' THEN
                    RAISE EXCEPTION 'Patent party evidence is append-only' USING ERRCODE = '23514';
                END IF;
                IF EXISTS (SELECT 1 FROM {TABLE} WHERE id = OLD.id) THEN
                    RAISE EXCEPTION 'Patent party evidence is append-only' USING ERRCODE = '23514';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        for table in (TABLE, OWNER):
            bind.execute(
                sa.text(f"""
                CREATE TRIGGER trg_{table}_patent_append_only
                BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW
                EXECUTE FUNCTION reject_patent_party_evidence_mutation()
            """)
            )
    elif bind.dialect.name == "sqlite":
        for table in (TABLE, OWNER):
            condition = (
                f"WHEN EXISTS (SELECT 1 FROM {TABLE} WHERE id = OLD.id)" if table == OWNER else ""
            )
            for operation in ("UPDATE", "DELETE"):
                bind.execute(
                    sa.text(f"""
                    CREATE TRIGGER trg_{table}_patent_append_only_{operation.lower()}
                    BEFORE {operation} ON {table} {condition}
                    BEGIN SELECT RAISE(ABORT, 'Patent party evidence is append-only'); END
                """)
                )


def upgrade() -> None:
    bind = op.get_bind()
    _owner_index(bind)
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("anchor_version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_party_id", sa.String(36), nullable=True),
        sa.Column("address_json", sa.JSON(), nullable=False),
        sa.Column("source_document_id", sa.String(36), nullable=False),
        sa.Column("source_document_version_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("fact_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.ForeignKeyConstraint(
            ["id", "company_id", "docket_id"],
            [f"{OWNER}.id", f"{OWNER}.company_id", f"{OWNER}.docket_id"],
            name="fk_patent_party_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_party_id", "company_id", "docket_id"],
            [f"{TABLE}.id", f"{TABLE}.company_id", f"{TABLE}.docket_id"],
            name="fk_patent_party_predecessor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            name="fk_patent_party_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_patent_party_actor",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", "docket_id", name="uq_patent_party_detail_owner"),
        sa.UniqueConstraint("company_id", "docket_id", "sequence", name="uq_patent_party_sequence"),
        sa.UniqueConstraint("company_id", "supersedes_party_id", name="uq_patent_party_successor"),
        sa.CheckConstraint(
            "sequence > 0 AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_party_versions",
        ),
        sa.CheckConstraint(
            "supersedes_party_id IS NULL OR supersedes_party_id <> id",
            name="ck_patent_party_no_self",
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(fact_sha256) = 64", name="ck_patent_party_hashes"
        ),
    )
    for name, columns in (
        ("ix_patent_party_predecessor", ["company_id", "supersedes_party_id", "docket_id"]),
        (
            "ix_patent_party_source",
            ["company_id", "source_document_version_id", "source_document_id"],
        ),
        ("ix_patent_party_actor", ["company_id", "created_by_membership_id"]),
        ("ix_patent_party_fact", ["company_id", "docket_id", "fact_sha256"]),
    ):
        op.create_index(name, TABLE, columns)
    _guards(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f"LOCK TABLE {OWNER}, {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first():
        raise RuntimeError("Patent party evidence exists; restore forward instead of deleting it.")
    if bind.dialect.name == "postgresql":
        for table in (TABLE, OWNER):
            bind.execute(sa.text(f"DROP TRIGGER trg_{table}_patent_append_only ON {table}"))
        bind.execute(sa.text("DROP FUNCTION reject_patent_party_evidence_mutation()"))
    elif bind.dialect.name == "sqlite":
        for table in (TABLE, OWNER):
            for operation in ("update", "delete"):
                bind.execute(sa.text(f"DROP TRIGGER trg_{table}_patent_append_only_{operation}"))
    op.drop_table(TABLE)
    op.drop_index(OWNER_INDEX, table_name=OWNER)
