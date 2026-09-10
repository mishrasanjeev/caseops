"""Keep bounded hearing backfills progressing past rejected rows.

Revision ID: 20260908_0001
Revises: 20260907_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged: new operational table; existing-table
indexes are concurrent on PostgreSQL and resumable after interrupted builds.
MIGRATION-ROLLBACK: restore-forward: populated cursor state refuses downgrade;
only an empty, never-used expansion can be removed. Poll/audit records are retained.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260908_0001"
down_revision = "20260907_0002"
branch_labels = None
depends_on = None

_TABLE = "tracked_case_backfill_cursors"
_INDEXES = (
    ("ix_matters_company_created_id", "matters", ["company_id", "created_at", "id"]),
    (
        "ix_tracking_bookmarks_company_matter_active",
        "tracked_case_bookmarks",
        ["company_id", "matter_id", "is_archived"],
    ),
)
_INDEX_HEALTH = sa.text(
    "SELECT t.relname, i.indisvalid AND i.indisready AS ready "
    "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_class t ON t.oid = i.indrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relname = :name"
)


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column(
                "company_id",
                sa.String(36),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("provider", sa.String(40), primary_key=True),
            sa.Column("last_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_matter_id", sa.String(36), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "(last_created_at IS NULL) = (last_matter_id IS NULL)",
                name="ck_tracking_backfill_cursor_pair",
            ),
        )
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    expected = {
        "company_id": (sa.String, 36, False),
        "provider": (sa.String, 40, False),
        "last_created_at": (sa.DateTime, None, True),
        "last_matter_id": (sa.String, 36, True),
        "updated_at": (sa.DateTime, None, False),
    }
    if set(columns) != set(expected) or any(
        not isinstance(columns[name]["type"], kind)
        or (length is not None and columns[name]["type"].length != length)
        or columns[name]["nullable"] != nullable
        for name, (kind, length, nullable) in expected.items()
    ):
        raise RuntimeError("Existing hearing backfill cursor has an unexpected shape.")
    if inspector.get_pk_constraint(_TABLE)["constrained_columns"] != ["company_id", "provider"]:
        raise RuntimeError("Existing hearing backfill cursor has an unexpected identity.")
    foreign_keys = inspector.get_foreign_keys(_TABLE)
    if len(foreign_keys) != 1 or not any(
        key["constrained_columns"] == ["company_id"]
        and key["referred_table"] == "companies"
        and key["referred_columns"] == ["id"]
        and key["options"].get("ondelete") == "CASCADE"
        for key in foreign_keys
    ):
        raise RuntimeError("Existing hearing backfill cursor has an unexpected tenant boundary.")
    checks = inspector.get_check_constraints(_TABLE)
    expected_check = "last_created_at is null = last_matter_id is null"
    if (
        len(checks) != 1
        or " ".join(checks[0]["sqltext"].replace("(", " ").replace(")", " ").lower().split())
        != expected_check
    ):
        raise RuntimeError(
            "Existing hearing backfill cursor has an unexpected position constraint."
        )
    if bind.dialect.name == "postgresql":
        if any(not columns[name]["type"].timezone for name in ("last_created_at", "updated_at")):
            raise RuntimeError("Existing hearing backfill cursor timestamps must retain timezone.")
        with op.get_context().autocommit_block():
            for name, table, index_columns in _INDEXES:
                health = bind.execute(_INDEX_HEALTH, {"name": name}).first()
                if health is not None and health.relname != table:
                    raise RuntimeError("Backfill index name belongs to an unexpected table.")
                if health is not None and not health.ready:
                    op.execute(sa.text(f"DROP INDEX CONCURRENTLY {name}"))
                op.execute(
                    sa.text(
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                        f"ON {table} ({', '.join(index_columns)})"
                    )
                )
                health = bind.execute(_INDEX_HEALTH, {"name": name}).first()
                if health is None or not health.ready:
                    raise RuntimeError("Hearing backfill index is not ready.")
                actual = next(
                    row for row in sa.inspect(bind).get_indexes(table) if row["name"] == name
                )
                if actual["column_names"] != index_columns or actual["unique"]:
                    raise RuntimeError("Hearing backfill index has an unexpected shape.")
    else:
        for name, table, index_columns in _INDEXES:
            actual = next(
                (row for row in sa.inspect(bind).get_indexes(table) if row["name"] == name), None
            )
            if actual is None:
                op.create_index(name, table, index_columns)
            elif actual["column_names"] != index_columns or actual["unique"]:
                raise RuntimeError("Hearing backfill index has an unexpected shape.")


def downgrade() -> None:
    if op.get_bind().execute(sa.text(f"SELECT 1 FROM {_TABLE} LIMIT 1")).first() is not None:
        raise RuntimeError("Hearing backfill state exists; restore or roll forward.")
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_table(_TABLE)
