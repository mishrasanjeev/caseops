"""Fence provider attempts and retain uncertain spend after worker loss.

Revision ID: 20260909_0002
Revises: 20260908_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged: nullable expansion; resumable concurrent index.
MIGRATION-ROLLBACK: restore-forward: populated lease or spend-dispatch evidence
refuses downgrade; only the unused expansion can be removed.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260909_0002"
down_revision = "20260908_0001"
branch_labels = None
depends_on = None

_COLUMNS = {
    "tracked_case_provider_operations": {
        "lease_token": sa.String(36),
        "lease_expires_at": sa.DateTime(timezone=True),
        "spend_reservation_id": sa.String(36),
    },
    "provider_spend_reservations": {"dispatched_at": sa.DateTime(timezone=True)},
}
_INDEX = "ix_tracking_operation_recovery"
_TABLE = "tracked_case_provider_operations"
_INDEX_COLUMNS = ["company_id", "status", "lease_expires_at"]


def upgrade() -> None:
    bind = op.get_bind()
    for table, expected in _COLUMNS.items():
        columns = {row["name"]: row for row in sa.inspect(bind).get_columns(table)}
        for name, kind in expected.items():
            existing = columns.get(name)
            if existing is None:
                op.add_column(table, sa.Column(name, kind, nullable=True))
            elif (
                not isinstance(existing["type"], type(kind))
                or not existing["nullable"]
                or (isinstance(kind, sa.String) and existing["type"].length != kind.length)
                or (
                    isinstance(kind, sa.DateTime)
                    and bind.dialect.name == "postgresql"
                    and not existing["type"].timezone
                )
            ):
                raise RuntimeError("Existing provider recovery column has an unexpected shape.")
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            health = bind.execute(
                sa.text(
                    "SELECT t.relname, i.indisvalid AND i.indisready AS ready "
                    "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                    "JOIN pg_class t ON t.oid=i.indrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() AND c.relname=:name"
                ),
                {"name": _INDEX},
            ).first()
            if health is not None and health.relname != _TABLE:
                raise RuntimeError("Provider recovery index belongs to a different table.")
            if health is not None and not health.ready:
                op.execute(sa.text(f"DROP INDEX CONCURRENTLY {_INDEX}"))
            op.execute(
                sa.text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON {_TABLE} "
                    "(company_id, status, lease_expires_at)"
                )
            )
            if (
                bind.execute(
                    sa.text(
                        "SELECT i.indisvalid AND i.indisready FROM pg_index i "
                        "WHERE i.indexrelid=to_regclass(:name)"
                    ),
                    {"name": _INDEX},
                ).scalar_one()
                is not True
            ):
                raise RuntimeError("Provider recovery index did not become ready.")
    elif not any(row["name"] == _INDEX for row in sa.inspect(bind).get_indexes(_TABLE)):
        op.create_index(_INDEX, _TABLE, _INDEX_COLUMNS)
    actual = next(row for row in sa.inspect(bind).get_indexes(_TABLE) if row["name"] == _INDEX)
    if actual["column_names"] != _INDEX_COLUMNS or actual["unique"]:
        raise RuntimeError("Provider recovery index has an unexpected shape.")


def downgrade() -> None:
    bind = op.get_bind()
    for table, columns in _COLUMNS.items():
        predicate = " OR ".join(f"{name} IS NOT NULL" for name in columns)
        if bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE {predicate} LIMIT 1")).first():
            raise RuntimeError("Provider recovery evidence exists; downgrade refused.")
    op.drop_index(_INDEX, table_name=_TABLE)
    for table, columns in reversed(list(_COLUMNS.items())):
        with op.batch_alter_table(table) as batch:
            for name in reversed(columns):
                batch.drop_column(name)
