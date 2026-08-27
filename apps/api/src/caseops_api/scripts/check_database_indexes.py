from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

from caseops_api.db.base import Base
from caseops_api.db.index_coverage import columns_cover, database_foreign_key_gaps
from caseops_api.db.session import get_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeclaredIndex:
    columns: tuple[str, ...] | None
    requires_exact_name: bool


def _alembic_config_path() -> Path:
    configured = os.getenv("CASEOPS_ALEMBIC_CONFIG")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path.cwd() / "alembic.ini")
    candidates.extend(parent / "alembic.ini" for parent in Path(__file__).resolve().parents)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("could not locate alembic.ini for schema-head verification")


def _required_schema_revision() -> str:
    config_path = _alembic_config_path()
    config = Config(str(config_path))
    script_location = config.get_main_option("script_location")
    if not script_location:
        raise RuntimeError("alembic.ini does not declare script_location")
    script_path = Path(script_location)
    if not script_path.is_absolute():
        config.set_main_option(
            "script_location", str((config_path.parent / script_path).resolve())
        )
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one Alembic head, found {sorted(heads)}")
    return heads[0]


def _declared_index_columns(index: sa.Index) -> tuple[str, ...] | None:
    names = [getattr(expression, "name", None) for expression in index.expressions]
    return tuple(str(name) for name in names) if all(names) else None


def _declared_indexes() -> dict[str, dict[str, DeclaredIndex]]:
    return {
        table.name: {
            index.name: DeclaredIndex(
                columns=_declared_index_columns(index),
                requires_exact_name=not index._column_flag,  # noqa: SLF001
            )
            for index in table.indexes
            if index.name and not index.name.startswith("ix_fk_")
        }
        for table in Base.metadata.tables.values()
    }


def _invalid_postgres_indexes(connection: Connection) -> list[dict[str, Any]]:
    if connection.dialect.name != "postgresql":
        return []
    rows = connection.execute(
        sa.text(
            """
            SELECT ns.nspname AS schema_name, tbl.relname AS table_name,
                   idx.relname AS index_name, i.indisvalid, i.indisready
            FROM pg_index AS i
            JOIN pg_class AS idx ON idx.oid = i.indexrelid
            JOIN pg_class AS tbl ON tbl.oid = i.indrelid
            JOIN pg_namespace AS ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = current_schema()
              AND (NOT i.indisvalid OR NOT i.indisready)
            ORDER BY tbl.relname, idx.relname
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def _sequential_scan_warnings(connection: Connection) -> list[dict[str, Any]]:
    if connection.dialect.name != "postgresql":
        return []
    rows = connection.execute(
        sa.text(
            """
            SELECT relname AS table_name, n_live_tup, n_dead_tup,
                   seq_scan, seq_tup_read, idx_scan
            FROM pg_stat_user_tables
            WHERE seq_scan >= 1000 AND seq_tup_read >= 1000000
            ORDER BY seq_tup_read DESC
            LIMIT 25
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def build_index_health_report(connection: Connection) -> dict[str, Any]:
    required_schema_revision = _required_schema_revision()
    inspector = sa.inspect(connection)
    table_names = set(inspector.get_table_names())
    gaps = database_foreign_key_gaps(inspector, table_names=table_names)
    missing_declared: list[dict[str, str]] = []
    mismatched_declared: list[dict[str, Any]] = []
    for table_name, expected_indexes in sorted(_declared_indexes().items()):
        if table_name not in table_names:
            continue
        actual_indexes = {
            index["name"]: tuple(index.get("column_names") or ())
            for index in inspector.get_indexes(table_name)
        }
        actual_columns = tuple(actual_indexes.values())
        for index_name, declared in sorted(expected_indexes.items()):
            if not declared.requires_exact_name and declared.columns is not None:
                if any(
                    columns_cover(candidate, declared.columns)
                    for candidate in actual_columns
                ):
                    continue
                missing_declared.append({"table_name": table_name, "index_name": index_name})
                continue
            if index_name not in actual_indexes:
                missing_declared.append({"table_name": table_name, "index_name": index_name})
            elif (
                declared.columns is not None
                and actual_indexes[index_name] != declared.columns
            ):
                mismatched_declared.append(
                    {
                        "table_name": table_name,
                        "index_name": index_name,
                        "expected_columns": list(declared.columns),
                        "actual_columns": list(actual_indexes[index_name]),
                    }
                )
    versions = []
    if "alembic_version" in table_names:
        versions = list(connection.scalars(sa.text("SELECT version_num FROM alembic_version")))
    invalid = _invalid_postgres_indexes(connection)
    failures = {
        "foreign_key_gaps": [
            {
                "table_name": gap.table_name,
                "columns": list(gap.columns),
                "constraint_name": gap.constraint_name,
                "required_index_name": gap.index_name,
            }
            for gap in gaps
        ],
        "missing_declared_indexes": missing_declared,
        "mismatched_declared_indexes": mismatched_declared,
        "invalid_indexes": invalid,
        "schema_revision_mismatch": (
            [] if versions == [required_schema_revision] else versions
        ),
    }
    return {
        "status": "ok" if not any(failures.values()) else "failed",
        "required_schema_revision": required_schema_revision,
        "schema_revisions": versions,
        **failures,
        "sequential_scan_warnings": _sequential_scan_warnings(connection),
    }


def main() -> int:
    try:
        engine = get_engine()
        if engine.dialect.name != "postgresql":
            raise RuntimeError("database index health requires PostgreSQL")
        with engine.connect() as connection, connection.begin():
            connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
            report = build_index_health_report(connection)
    except Exception as exc:
        report = {"status": "failed", "error": str(exc)}
    print("CASEOPS_DB_INDEX_HEALTH " + json.dumps(report, sort_keys=True, default=str))
    if report["status"] != "ok":
        logger.error("Database index health failed: %s", report)
        return 2
    logger.info("Database index health passed with complete schema coverage.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
