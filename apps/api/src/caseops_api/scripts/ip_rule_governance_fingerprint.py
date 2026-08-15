"""Read-only, deterministic A0 fingerprint for IP rule-governance state.

The command intentionally emits hashes and aggregate timestamps only.  It
never emits row content, and every query runs in one database-enforced,
read-only snapshot transaction.  The result can therefore be retained as
release evidence without copying tenant or legal-source data into logs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

from sqlalchemy import DateTime, Select, or_, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.schema import Table

from caseops_api.db.models import AuditEvent, CompanyIpRulePolicy, IpRuleSet, IpRuleVersion
from caseops_api.db.session import get_engine

SCHEMA_VERSION = 1
STREAM_BATCH_SIZE = 500
STATEMENT_TIMEOUT_MS = 60_000
MAX_BASELINE_BYTES = 1_000_000
AUDIT_ACTION_PREFIX = "ip.rule_version."
AUDIT_TARGET_TYPES = ("company_ip_rule_policy", "ip_rule_set", "ip_rule_version")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")

_AUDIT_FILTER = {
    "action_prefix": AUDIT_ACTION_PREFIX,
    "match": "action_prefix_or_target_type",
    "target_types": list(AUDIT_TARGET_TYPES),
}


def _canonicalize(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats cannot be fingerprinted canonically.")
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        resolved = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return resolved.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    raise TypeError(f"Unsupported fingerprint value type: {type(value).__name__}")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _database_context(connection: Connection) -> dict[str, object]:
    if connection.dialect.name == "postgresql":
        database_schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    else:
        database_schema = "main"
    if not isinstance(database_schema, str) or not database_schema:
        raise RuntimeError("The active database schema could not be identified.")

    alembic_heads = list(
        connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).scalars()
    )
    if not alembic_heads or not all(isinstance(head, str) and head for head in alembic_heads):
        raise RuntimeError("The database has no valid Alembic head context.")
    return {
        "alembic_heads": alembic_heads,
        "database_schema": database_schema,
        "dialect": connection.dialect.name,
    }


def _dataset_fingerprint(
    connection: Connection,
    *,
    name: str,
    table: Table,
    statement: Select[Any],
    filter_description: Mapping[str, object] | None = None,
) -> dict[str, object]:
    columns = list(table.columns)
    timestamp_columns = [column.name for column in columns if isinstance(column.type, DateTime)]
    primary_key_columns = list(table.primary_key.columns)
    if not primary_key_columns:
        raise RuntimeError(f"Fingerprint dataset {name} has no stable primary key.")

    digest = sha256()
    digest.update(
        _canonical_json_bytes(
            {
                "columns": [column.name for column in columns],
                "dataset": name,
                "filter": dict(filter_description or {}),
                "schema_version": SCHEMA_VERSION,
            }
        )
    )
    digest.update(b"\n")
    maxima: dict[str, str | None] = {column_name: None for column_name in timestamp_columns}
    count = 0

    result = connection.execution_options(
        stream_results=True,
        max_row_buffer=STREAM_BATCH_SIZE,
    ).execute(statement.order_by(*primary_key_columns))
    try:
        for row in result.mappings().yield_per(STREAM_BATCH_SIZE):
            canonical_row = [_canonicalize(row[column.name]) for column in columns]
            digest.update(_canonical_json_bytes(canonical_row))
            digest.update(b"\n")
            count += 1
            for column_name in timestamp_columns:
                value = row[column_name]
                if value is None:
                    continue
                canonical_timestamp = _canonicalize(value)
                if not isinstance(canonical_timestamp, str):
                    raise TypeError(f"Timestamp column {column_name} did not serialize as text.")
                previous = maxima[column_name]
                if previous is None or canonical_timestamp > previous:
                    maxima[column_name] = canonical_timestamp
    finally:
        result.close()

    populated_maxima = [value for value in maxima.values() if value is not None]
    return {
        "content_sha256": digest.hexdigest(),
        "count": count,
        "max_timestamp": max(populated_maxima, default=None),
        "max_timestamps": maxima,
    }


def _collect_snapshot(connection: Connection) -> dict[str, object]:
    database_context = _database_context(connection)
    audit_table = AuditEvent.__table__
    datasets = {
        "ip_rule_sets": _dataset_fingerprint(
            connection,
            name="ip_rule_sets",
            table=IpRuleSet.__table__,
            statement=select(IpRuleSet.__table__),
        ),
        "ip_rule_versions": _dataset_fingerprint(
            connection,
            name="ip_rule_versions",
            table=IpRuleVersion.__table__,
            statement=select(IpRuleVersion.__table__),
        ),
        "company_ip_rule_policies": _dataset_fingerprint(
            connection,
            name="company_ip_rule_policies",
            table=CompanyIpRulePolicy.__table__,
            statement=select(CompanyIpRulePolicy.__table__),
        ),
        "audit_events_ip_rule_governance": _dataset_fingerprint(
            connection,
            name="audit_events_ip_rule_governance",
            table=audit_table,
            statement=select(audit_table).where(
                or_(
                    audit_table.c.action.startswith(AUDIT_ACTION_PREFIX, autoescape=True),
                    audit_table.c.target_type.in_(AUDIT_TARGET_TYPES),
                )
            ),
            filter_description=_AUDIT_FILTER,
        ),
    }
    body: dict[str, object] = {
        "database_context": database_context,
        "datasets": datasets,
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "audit_filter": _AUDIT_FILTER,
            "datasets": list(datasets),
            "read_control": {
                "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
                "stream_batch_size": STREAM_BATCH_SIZE,
            },
        },
    }
    captured_at = _canonicalize(_now_utc())
    if not isinstance(captured_at, str):
        raise TypeError("Capture timestamp did not serialize as text.")
    return {
        **body,
        "captured_at": captured_at,
        "overall_sha256": sha256(_canonical_json_bytes(body)).hexdigest(),
    }


def fingerprint_database(engine: Engine) -> dict[str, object]:
    """Fingerprint one consistent snapshot without permitting database writes."""

    dialect = engine.dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError(f"Unsupported fingerprint database dialect: {dialect}")

    with engine.connect() as connection:
        if dialect == "postgresql":
            transaction = connection.begin()
            try:
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                connection.exec_driver_sql(
                    f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"
                )
                read_only = connection.exec_driver_sql(
                    "SELECT current_setting('transaction_read_only')"
                ).scalar_one()
                if read_only != "on":
                    raise RuntimeError("PostgreSQL did not enter a read-only transaction.")
                isolation = connection.exec_driver_sql(
                    "SELECT current_setting('transaction_isolation')"
                ).scalar_one()
                if isolation != "repeatable read":
                    raise RuntimeError("PostgreSQL did not enter repeatable-read isolation.")
                timeout = connection.exec_driver_sql(
                    "SELECT current_setting('statement_timeout')"
                ).scalar_one()
                if timeout not in {"1min", "60s", "60000ms"}:
                    raise RuntimeError("PostgreSQL did not apply the bounded statement timeout.")
                return _collect_snapshot(connection)
            finally:
                transaction.rollback()

        # SQLite's query_only pragma makes an accidental DML statement fail at
        # the database boundary.  It is connection-scoped, so restore it before
        # returning the pooled connection; neither pragma commits a transaction.
        connection.exec_driver_sql("PRAGMA query_only = ON")
        try:
            if connection.exec_driver_sql("PRAGMA query_only").scalar_one() != 1:
                raise RuntimeError("SQLite did not enter query-only mode.")
            return _collect_snapshot(connection)
        finally:
            connection.rollback()
            connection.exec_driver_sql("PRAGMA query_only = OFF")
            connection.rollback()


def _load_baseline(path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_BASELINE_BYTES:
        raise ValueError("Fingerprint baseline exceeds the size limit.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Fingerprint baseline must be a JSON object.")
    return value


def compare_fingerprints(
    expected: Mapping[str, object], current: Mapping[str, object]
) -> list[str]:
    """Return only safe dataset identifiers whose canonical evidence differs."""

    mismatches: list[str] = []
    expected_datasets = expected.get("datasets")
    current_datasets = current.get("datasets")
    if not isinstance(expected_datasets, Mapping) or not isinstance(current_datasets, Mapping):
        return ["snapshot"]
    for name in sorted(set(expected_datasets) | set(current_datasets)):
        if expected_datasets.get(name) != current_datasets.get(name):
            mismatches.append(str(name))
    if (
        expected.get("schema_version") != current.get("schema_version")
        or expected.get("database_context") != current.get("database_context")
        or expected.get("scope") != current.get("scope")
        or expected.get("overall_sha256") != current.get("overall_sha256")
    ) and not mismatches:
        mismatches.append("snapshot")
    return mismatches


def _write_json(stream: TextIO, value: Mapping[str, object]) -> None:
    stream.write(_canonical_json_bytes(value).decode("utf-8"))
    stream.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit a read-only fingerprint of IP rule-governance database state."
    )
    comparison = parser.add_mutually_exclusive_group()
    comparison.add_argument(
        "--compare",
        type=Path,
        metavar="BASELINE_JSON",
        help="exit 3 unless the current canonical snapshot equals this baseline",
    )
    comparison.add_argument(
        "--expect-sha256",
        metavar="SHA256",
        help="exit 3 unless the current overall SHA-256 equals this value",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    expected_sha = args.expect_sha256.lower() if args.expect_sha256 else None
    if expected_sha is not None and SHA256_PATTERN.fullmatch(expected_sha) is None:
        _write_json(sys.stderr, {"error": "invalid_expected_sha256"})
        return 2

    engine: Engine | None = None
    try:
        baseline = _load_baseline(args.compare) if args.compare else None
        engine = get_engine()
        current = fingerprint_database(engine)
    except Exception as exc:
        _write_json(
            sys.stderr,
            {"error": "fingerprint_failed", "type": type(exc).__name__},
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    _write_json(sys.stdout, current)
    mismatches = compare_fingerprints(baseline, current) if baseline is not None else []
    if expected_sha is not None and current["overall_sha256"] != expected_sha:
        mismatches = ["overall_sha256"]
    if mismatches:
        _write_json(
            sys.stderr,
            {
                "actual_overall_sha256": current["overall_sha256"],
                "error": "fingerprint_mismatch",
                "mismatched_datasets": mismatches,
            },
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
