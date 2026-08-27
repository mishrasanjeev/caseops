from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import Index, MetaData, UniqueConstraint
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.sql.schema import ForeignKeyConstraint, Table


@dataclass(frozen=True, slots=True)
class ForeignKeyIndexGap:
    table_name: str
    columns: tuple[str, ...]
    constraint_name: str | None

    @property
    def index_name(self) -> str:
        return foreign_key_index_name(self.table_name, self.columns)


def foreign_key_index_name(table_name: str, columns: Sequence[str]) -> str:
    """Return a stable PostgreSQL-safe name for an FK support index."""

    signature = f"{table_name}:{','.join(columns)}"
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:8]  # noqa: S324
    table_part = table_name.lower()[:32]
    column_part = "_".join(columns).lower()[:15]
    return f"ix_fk_{table_part}_{column_part}_{digest}"


def columns_cover(candidate: Sequence[str], required: Sequence[str]) -> bool:
    """Whether an index prefix supports equality joins on every FK column."""

    width = len(required)
    return width > 0 and len(candidate) >= width and set(candidate[:width]) == set(required)


def _table_candidate_columns(table: Table) -> list[tuple[str, ...]]:
    candidates: list[tuple[str, ...]] = []
    primary_key = tuple(column.name for column in table.primary_key.columns)
    if primary_key:
        candidates.append(primary_key)
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            candidates.append(tuple(column.name for column in constraint.columns))
    for index in table.indexes:
        if index.dialect_options["postgresql"].get("where") is not None:
            continue
        names = tuple(getattr(expression, "name", None) for expression in index.expressions)
        if names and all(names):
            candidates.append(names)
    return candidates


def ensure_foreign_key_indexes(metadata: MetaData) -> tuple[str, ...]:
    """Attach support indexes for every metadata FK that lacks full coverage."""

    created: list[str] = []
    for table in sorted(metadata.tables.values(), key=lambda candidate: candidate.name):
        candidates = _table_candidate_columns(table)
        constraints = sorted(
            (
                constraint
                for constraint in table.constraints
                if isinstance(constraint, ForeignKeyConstraint)
            ),
            key=lambda constraint: tuple(column.name for column in constraint.columns),
        )
        for constraint in constraints:
            columns = tuple(column.name for column in constraint.columns)
            if any(columns_cover(candidate, columns) for candidate in candidates):
                continue
            name = foreign_key_index_name(table.name, columns)
            Index(name, *(table.c[column] for column in columns))
            candidates.append(columns)
            created.append(name)
    return tuple(created)


def _database_candidates(inspector: Inspector, table_name: str) -> list[tuple[str, ...]]:
    candidates: list[tuple[str, ...]] = []
    primary_key = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
    if primary_key:
        candidates.append(primary_key)
    for unique in inspector.get_unique_constraints(table_name):
        columns = tuple(unique.get("column_names") or ())
        if columns:
            candidates.append(columns)
    for index in inspector.get_indexes(table_name):
        dialect_options = index.get("dialect_options") or {}
        if dialect_options.get("postgresql_where") is not None:
            continue
        columns = tuple(index.get("column_names") or ())
        if columns and all(columns):
            candidates.append(columns)
    return candidates


def database_foreign_key_gaps(
    inspector: Inspector,
    *,
    table_names: Iterable[str] | None = None,
) -> tuple[ForeignKeyIndexGap, ...]:
    """Inspect a live schema and return every FK without full index coverage."""

    names = sorted(table_names or inspector.get_table_names())
    gaps: list[ForeignKeyIndexGap] = []
    for table_name in names:
        candidates = _database_candidates(inspector, table_name)
        for foreign_key in inspector.get_foreign_keys(table_name):
            columns = tuple(foreign_key.get("constrained_columns") or ())
            if not columns or any(columns_cover(candidate, columns) for candidate in candidates):
                continue
            gaps.append(
                ForeignKeyIndexGap(
                    table_name=table_name,
                    columns=columns,
                    constraint_name=foreign_key.get("name"),
                )
            )
    return tuple(gaps)
