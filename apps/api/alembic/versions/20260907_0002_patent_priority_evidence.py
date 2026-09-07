"""Retain patent priority evidence on the canonical IP relationship owner.

Revision ID: 20260907_0002
Revises: 20260907_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged: the existing relationship owner index is
concurrent on PostgreSQL; other indexes belong to a new empty detail table.
MIGRATION-ROLLBACK: restore-forward: refuse removal of retained priority evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260907_0002"
down_revision = "20260907_0001"
branch_labels = None
depends_on = None

TABLE = "ip_patent_priority_details"
OWNER = "ip_relationships"
OWNER_INDEX = "uq_ip_relationship_patent_owner"
OWNER_COLUMNS = ["id", "company_id", "source_docket_id", "target_docket_id"]


def _owner_index(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        op.create_index(OWNER_INDEX, OWNER, OWNER_COLUMNS, unique=True)
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
    with op.get_context().autocommit_block():
        state = bind.execute(state_query, {"name": OWNER_INDEX}).mappings().first()
        if state is not None:
            if not (
                state["indisunique"]
                and state["plain"]
                and state["no_includes"]
                and state["owner"] == OWNER
                and state["method"] == "btree"
                and list(state["columns"]) == OWNER_COLUMNS
            ):
                raise RuntimeError("Existing IP relationship owner index has a conflicting shape.")
            if not state["indisvalid"] or not state["indisready"]:
                bind.execute(sa.text(f"DROP INDEX CONCURRENTLY {OWNER_INDEX}"))
        bind.execute(
            sa.text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {OWNER_INDEX} "
                f"ON {OWNER} ({', '.join(OWNER_COLUMNS)})"
            )
        )
        ready = bind.execute(state_query, {"name": OWNER_INDEX}).mappings().one()
        if not ready["indisvalid"] or not ready["indisready"]:
            raise RuntimeError("IP relationship owner index is not ready.")


def _guards(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(f"""
            CREATE FUNCTION reject_patent_priority_mutation() RETURNS trigger AS $$
            BEGIN
                IF TG_TABLE_NAME = '{TABLE}' THEN
                    RAISE EXCEPTION 'Patent priority evidence is append-only'
                        USING ERRCODE = '23514';
                END IF;
                IF EXISTS (SELECT 1 FROM {TABLE} WHERE relationship_id = OLD.id) THEN
                    RAISE EXCEPTION 'Patent priority evidence is append-only'
                        USING ERRCODE = '23514';
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
                CREATE TRIGGER trg_{table}_patent_priority_append_only
                BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW
                EXECUTE FUNCTION reject_patent_priority_mutation()
            """)
            )
        bind.execute(
            sa.text("""
            CREATE FUNCTION check_patent_priority_owner() RETURNS trigger AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM ip_patent_applications
                    WHERE company_id = NEW.company_id AND docket_id = NEW.source_docket_id)
                OR NOT EXISTS (SELECT 1 FROM ip_patent_applications
                    WHERE company_id = NEW.company_id AND docket_id = NEW.target_docket_id) THEN
                    RAISE EXCEPTION 'Patent priority requires two patent applications'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        bind.execute(
            sa.text(f"""
            CREATE TRIGGER trg_patent_priority_owner
            BEFORE INSERT ON {TABLE} FOR EACH ROW EXECUTE FUNCTION check_patent_priority_owner()
        """)
        )
    elif bind.dialect.name == "sqlite":
        for table in (TABLE, OWNER):
            condition = (
                f"WHEN EXISTS (SELECT 1 FROM {TABLE} WHERE relationship_id = OLD.id)"
                if table == OWNER
                else ""
            )
            for operation in ("UPDATE", "DELETE"):
                bind.execute(
                    sa.text(f"""
                    CREATE TRIGGER trg_{table}_patent_priority_append_only_{operation.lower()}
                    BEFORE {operation} ON {table} {condition}
                    BEGIN SELECT RAISE(ABORT, 'Patent priority evidence is append-only'); END
                """)
                )
        bind.execute(
            sa.text(f"""
            CREATE TRIGGER trg_patent_priority_owner BEFORE INSERT ON {TABLE}
            WHEN NOT EXISTS (SELECT 1 FROM ip_patent_applications
                WHERE company_id = NEW.company_id AND docket_id = NEW.source_docket_id)
            OR NOT EXISTS (SELECT 1 FROM ip_patent_applications
                WHERE company_id = NEW.company_id AND docket_id = NEW.target_docket_id)
            BEGIN SELECT RAISE(ABORT, 'Patent priority requires two patent applications'); END
        """)
        )


def upgrade() -> None:
    bind = op.get_bind()
    _owner_index(bind)
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("relationship_id", sa.String(36), nullable=False),
        sa.Column("source_docket_id", sa.String(36), nullable=False),
        sa.Column("target_docket_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("application_version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False),
        sa.Column("parent_lifecycle_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_priority_id", sa.String(36), nullable=True),
        sa.Column("withdrawn", sa.Boolean(), nullable=False),
        sa.Column("review_flags_json", sa.JSON(), nullable=False),
        sa.Column("source_document_id", sa.String(36), nullable=False),
        sa.Column("source_document_version_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("fact_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["relationship_id", "company_id", "source_docket_id", "target_docket_id"],
            [f"{OWNER}.{column}" for column in OWNER_COLUMNS],
            name="fk_patent_priority_relationship_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_priority_id", "company_id", "source_docket_id"],
            [f"{TABLE}.id", f"{TABLE}.company_id", f"{TABLE}.source_docket_id"],
            name="fk_patent_priority_predecessor_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            name="fk_patent_priority_document_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_patent_priority_actor_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "company_id", "source_docket_id", name="uq_patent_priority_detail_owner"
        ),
        sa.UniqueConstraint("company_id", "sequence", name="uq_patent_priority_sequence"),
        sa.UniqueConstraint(
            "company_id", "supersedes_priority_id", name="uq_patent_priority_successor"
        ),
        sa.CheckConstraint(
            "sequence > 0 AND application_version > 0 AND parent_version > 0 "
            "AND lifecycle_version >= 0 AND parent_lifecycle_version >= 0",
            name="ck_patent_priority_versions",
        ),
        sa.CheckConstraint(
            "supersedes_priority_id IS NULL OR supersedes_priority_id <> id",
            name="ck_patent_priority_predecessor_distinct",
        ),
        sa.CheckConstraint(
            "NOT withdrawn OR supersedes_priority_id IS NOT NULL",
            name="ck_patent_priority_withdrawal_predecessor",
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(fact_sha256) = 64",
            name="ck_patent_priority_hashes",
        ),
    )
    for name, columns in (
        (
            "ix_patent_priorities_company_source_sequence",
            ["company_id", "source_docket_id", "sequence"],
        ),
        (
            "ix_patent_priorities_company_target_sequence",
            ["company_id", "target_docket_id", "sequence"],
        ),
        (
            "ix_patent_priorities_relationship_owner",
            ["relationship_id", "company_id", "source_docket_id", "target_docket_id"],
        ),
        (
            "ix_patent_priorities_predecessor_owner",
            ["supersedes_priority_id", "company_id", "source_docket_id"],
        ),
        (
            "ix_patent_priorities_source_version",
            ["source_document_version_id", "company_id", "source_document_id"],
        ),
        ("ix_patent_priorities_actor_company", ["created_by_membership_id", "company_id"]),
    ):
        op.create_index(name, TABLE, columns)
    _guards(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f"LOCK TABLE {OWNER}, {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first():
        raise RuntimeError(
            "Patent priority evidence exists; restore forward instead of deleting it."
        )
    if bind.dialect.name == "postgresql":
        for table in (TABLE, OWNER):
            bind.execute(
                sa.text(f"DROP TRIGGER trg_{table}_patent_priority_append_only ON {table}")
            )
        bind.execute(sa.text(f"DROP TRIGGER trg_patent_priority_owner ON {TABLE}"))
        bind.execute(sa.text("DROP FUNCTION check_patent_priority_owner()"))
        bind.execute(sa.text("DROP FUNCTION reject_patent_priority_mutation()"))
    elif bind.dialect.name == "sqlite":
        for table in (TABLE, OWNER):
            for operation in ("update", "delete"):
                bind.execute(
                    sa.text(f"DROP TRIGGER trg_{table}_patent_priority_append_only_{operation}")
                )
        bind.execute(sa.text("DROP TRIGGER trg_patent_priority_owner"))
    op.drop_table(TABLE)
    op.drop_index(OWNER_INDEX, table_name=OWNER)
