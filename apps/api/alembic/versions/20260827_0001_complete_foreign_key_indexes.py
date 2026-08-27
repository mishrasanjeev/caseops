"""Complete foreign-key index coverage and add the bounded IP list index.

Revision ID: 20260827_0001
Revises: 20260826_0002

MIGRATION-LOCK-RISK: acknowledged. PostgreSQL indexes are built concurrently,
lock acquisition is capped at five seconds, and each statement has a thirty-
minute ceiling. The migration is restart-safe after an interrupted build.
MIGRATION-ROLLBACK: safe. This revision contains performance indexes only;
downgrade removes deterministic support indexes without changing data.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from caseops_api.db.index_coverage import (
    columns_cover,
    database_foreign_key_gaps,
    foreign_key_index_name,
)

revision = "20260827_0001"
down_revision = "20260826_0002"
branch_labels = None
depends_on = None

HOT_INDEX = "ix_ip_docket_records_company_active_updated"
HOT_INDEX_COLUMNS = ("company_id", "is_active", "updated_at", "id")
IMPLICIT_INDEX_REQUIREMENTS = (
    (
        "ix_calendar_projection_reconciliation_candidates_ip_docket_id",
        "calendar_projection_reconciliation_candidates",
        ("ip_docket_id",),
    ),
    (
        "ix_calendar_projection_reconciliation_candidates_status",
        "calendar_projection_reconciliation_candidates",
        ("status",),
    ),
    ("ix_ip_matter_links_docket_id", "ip_matter_links", ("docket_id",)),
    ("ix_ip_matter_links_matter_id", "ip_matter_links", ("matter_id",)),
    (
        "ix_ip_registry_diffs_resolution_status",
        "ip_registry_diffs",
        ("resolution_status",),
    ),
    (
        "ix_ip_registry_links_freshness_status",
        "ip_registry_links",
        ("freshness_status",),
    ),
    (
        "ix_ip_registry_sync_attempts_status",
        "ip_registry_sync_attempts",
        ("status",),
    ),
    (
        "ix_portal_publications_scheduled_for",
        "portal_publications",
        ("scheduled_for",),
    ),
)


def _quote(connection: sa.Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _postgres_create_indexes(
    connection: sa.Connection, indexes: list[tuple[str, str, tuple[str, ...]]]
) -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("SET lock_timeout = '5s'"))
        op.execute(sa.text("SET statement_timeout = '30min'"))
        for name, table_name, columns in indexes:
            invalid = connection.scalar(
                sa.text(
                    """
                    SELECT NOT i.indisvalid OR NOT i.indisready
                    FROM pg_index AS i
                    JOIN pg_class AS idx ON idx.oid = i.indexrelid
                    JOIN pg_namespace AS ns ON ns.oid = idx.relnamespace
                    WHERE ns.nspname = current_schema() AND idx.relname = :index_name
                    """
                ),
                {"index_name": name},
            )
            if invalid:
                op.execute(
                    sa.text(
                        f"DROP INDEX CONCURRENTLY IF EXISTS {_quote(connection, name)}"
                    )
                )
            quoted_columns = ", ".join(_quote(connection, column) for column in columns)
            op.execute(
                sa.text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_quote(connection, name)} "
                    f"ON {_quote(connection, table_name)} ({quoted_columns})"
                )
            )
        op.execute(sa.text("RESET lock_timeout"))
        op.execute(sa.text("RESET statement_timeout"))


def _candidate_columns(
    inspector: sa.Inspector, table_name: str
) -> list[tuple[str, ...]]:
    candidates = [
        tuple(index.get("column_names") or ())
        for index in inspector.get_indexes(table_name)
        if not (index.get("dialect_options") or {}).get("postgresql_where")
    ]
    primary_key = tuple(
        inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    if primary_key:
        candidates.append(primary_key)
    candidates.extend(
        tuple(unique.get("column_names") or ())
        for unique in inspector.get_unique_constraints(table_name)
    )
    return [candidate for candidate in candidates if candidate]


def _uncovered_implicit_indexes(
    inspector: sa.Inspector,
    planned: list[tuple[str, str, tuple[str, ...]]],
) -> list[tuple[str, str, tuple[str, ...]]]:
    candidates_by_table = {
        table_name: _candidate_columns(inspector, table_name)
        for _, table_name, _ in IMPLICIT_INDEX_REQUIREMENTS
    }
    for _, table_name, columns in planned:
        candidates_by_table.setdefault(table_name, []).append(columns)
    uncovered: list[tuple[str, str, tuple[str, ...]]] = []
    for requirement in IMPLICIT_INDEX_REQUIREMENTS:
        _, table_name, columns = requirement
        candidates = candidates_by_table[table_name]
        if any(columns_cover(candidate, columns) for candidate in candidates):
            continue
        uncovered.append(requirement)
        candidates.append(columns)
    return uncovered


def _remaining_implicit_gaps(
    inspector: sa.Inspector,
) -> list[tuple[str, str, tuple[str, ...]]]:
    return [
        requirement
        for requirement in IMPLICIT_INDEX_REQUIREMENTS
        if not any(
            columns_cover(candidate, requirement[2])
            for candidate in _candidate_columns(inspector, requirement[1])
        )
    ]


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    indexes = [
        (gap.index_name, gap.table_name, gap.columns)
        for gap in database_foreign_key_gaps(inspector)
    ]
    indexes.extend(_uncovered_implicit_indexes(inspector, indexes))
    indexes.append(
        (
            HOT_INDEX,
            "ip_docket_records",
            HOT_INDEX_COLUMNS,
        )
    )
    if connection.dialect.name == "postgresql":
        _postgres_create_indexes(connection, indexes)
    else:
        for name, table_name, columns in indexes:
            op.create_index(name, table_name, list(columns))

    refreshed = sa.inspect(connection)
    remaining = database_foreign_key_gaps(refreshed)
    hot_indexes = {
        index["name"]: tuple(index.get("column_names") or ())
        for index in refreshed.get_indexes("ip_docket_records")
    }
    implicit_gaps = _remaining_implicit_gaps(refreshed)
    if (
        remaining
        or implicit_gaps
        or hot_indexes.get(HOT_INDEX) != HOT_INDEX_COLUMNS
    ):
        raise RuntimeError(
            "Database index migration did not converge to the required coverage."
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    names = {HOT_INDEX, *(name for name, _, _ in IMPLICIT_INDEX_REQUIREMENTS)}
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            columns = tuple(foreign_key.get("constrained_columns") or ())
            if columns:
                names.add(foreign_key_index_name(table_name, columns))
    existing = {
        index["name"]
        for table_name in inspector.get_table_names()
        for index in inspector.get_indexes(table_name)
    }
    removable = sorted(names & existing)
    if connection.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(sa.text("SET lock_timeout = '5s'"))
            for name in removable:
                op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_quote(connection, name)}"))
            op.execute(sa.text("RESET lock_timeout"))
        return
    for name in removable:
        op.drop_index(name)
