from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import UniqueConstraint

from caseops_api.db import models as db_models
from caseops_api.db.base import Base

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_module(path: Path) -> object:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _migration_fk_index_coverage() -> set[tuple[str, str]]:
    covered: set[tuple[str, str]] = set()
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = _load_module(path)
        for item in getattr(module, "FK_INDEXES", ()):
            assert isinstance(item, tuple) and len(item) == 2, (
                f"{path.name}: FK_INDEXES entries must be (table, column) tuples."
            )
            table, column = item
            assert isinstance(table, str) and isinstance(column, str), (
                f"{path.name}: FK_INDEXES values must be strings."
            )
            covered.add((table, column))
    return covered


def _metadata_leading_indexed_columns() -> set[tuple[str, str]]:
    indexed: set[tuple[str, str]] = set()
    for table in Base.metadata.tables.values():
        for column in table.primary_key.columns:
            indexed.add((table.name, column.name))
        for index in table.indexes:
            columns = [column.name for column in index.columns]
            if columns:
                indexed.add((table.name, columns[0]))
        for constraint in table.constraints:
            if not isinstance(constraint, UniqueConstraint):
                continue
            columns = [column.name for column in constraint.columns]
            if columns:
                indexed.add((table.name, columns[0]))
    return indexed


def _foreign_key_columns() -> set[tuple[str, str]]:
    columns: set[tuple[str, str]] = set()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.foreign_keys:
                columns.add((table.name, column.name))
    return columns


def test_foreign_key_columns_have_leading_index_or_migration_coverage() -> None:
    assert db_models.Matter.__tablename__ in Base.metadata.tables

    missing = (
        _foreign_key_columns()
        - _metadata_leading_indexed_columns()
        - _migration_fk_index_coverage()
    )

    assert not missing, (
        "Foreign-key columns must have a leading metadata index/unique constraint "
        "or be explicitly covered by a migration FK_INDEXES entry. Missing: "
        f"{sorted(missing)}"
    )
