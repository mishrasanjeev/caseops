"""Validate the aggregate-only IPLF-027B A0 fingerprint evidence contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

DATASET_TIMESTAMPS = {
    "audit_events_ip_rule_governance": {"created_at"},
    "company_ip_rule_policies": {"created_at", "updated_at"},
    "ip_rule_sets": {"created_at"},
    "ip_rule_versions": {
        "activated_at",
        "created_at",
        "disabled_at",
        "fixtures_passed_at",
    },
}
SCOPE_DATASETS = [
    "ip_rule_sets",
    "ip_rule_versions",
    "company_ip_rule_policies",
    "audit_events_ip_rule_governance",
]
AUDIT_TARGET_TYPES = ["company_ip_rule_policy", "ip_rule_set", "ip_rule_version"]
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def validate_snapshot(value: object, *, require_postgresql: bool) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["root"]
    if set(value) != {
        "captured_at",
        "database_context",
        "datasets",
        "overall_sha256",
        "schema_version",
        "scope",
    }:
        errors.append("top_level_keys")
    if value.get("schema_version") != 1:
        errors.append("schema_version")
    captured_at = value.get("captured_at")
    if not isinstance(captured_at, str) or TIMESTAMP_PATTERN.fullmatch(captured_at) is None:
        errors.append("captured_at")

    context = value.get("database_context")
    if not isinstance(context, dict):
        errors.append("database_context")
    else:
        dialect = context.get("dialect")
        if require_postgresql and dialect != "postgresql":
            errors.append("database_dialect")
        elif dialect not in {"postgresql", "sqlite"}:
            errors.append("database_dialect")
        schema = context.get("database_schema")
        if not isinstance(schema, str) or not schema:
            errors.append("database_schema")
        heads = context.get("alembic_heads")
        if (
            not isinstance(heads, list)
            or not heads
            or heads != sorted(heads)
            or not all(isinstance(head, str) and head for head in heads)
        ):
            errors.append("alembic_heads")

    scope = value.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope")
    else:
        if scope.get("datasets") != SCOPE_DATASETS:
            errors.append("scope_datasets")
        if scope.get("audit_filter") != {
            "action_prefix": "ip.rule_version.",
            "match": "action_prefix_or_target_type",
            "target_types": AUDIT_TARGET_TYPES,
        }:
            errors.append("audit_filter")
        if scope.get("read_control") != {
            "statement_timeout_ms": 60_000,
            "stream_batch_size": 500,
        }:
            errors.append("read_control")

    datasets = value.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != set(SCOPE_DATASETS):
        errors.append("datasets")
    else:
        for name, timestamp_columns in DATASET_TIMESTAMPS.items():
            dataset = datasets.get(name)
            if not isinstance(dataset, dict) or set(dataset) != {
                "content_sha256",
                "count",
                "max_timestamp",
                "max_timestamps",
            }:
                errors.append(f"{name}.shape")
                continue
            if SHA256_PATTERN.fullmatch(str(dataset.get("content_sha256", ""))) is None:
                errors.append(f"{name}.content_sha256")
            count = dataset.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                errors.append(f"{name}.count")
            maxima = dataset.get("max_timestamps")
            if not isinstance(maxima, dict) or set(maxima) != timestamp_columns:
                errors.append(f"{name}.max_timestamps")
                continue
            for timestamp in maxima.values():
                if timestamp is not None and (
                    not isinstance(timestamp, str) or TIMESTAMP_PATTERN.fullmatch(timestamp) is None
                ):
                    errors.append(f"{name}.timestamp")
            populated = [timestamp for timestamp in maxima.values() if timestamp is not None]
            if dataset.get("max_timestamp") != max(populated, default=None):
                errors.append(f"{name}.max_timestamp")

    digest = value.get("overall_sha256")
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        errors.append("overall_sha256")
    else:
        stable_body: dict[str, Any] = {
            key: item for key, item in value.items() if key not in {"captured_at", "overall_sha256"}
        }
        if sha256(_canonical_bytes(stable_body)).hexdigest() != digest:
            errors.append("overall_sha256_content")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--require-postgresql", action="store_true")
    parser.add_argument("--print-sha", action="store_true")
    args = parser.parse_args()
    try:
        value = json.loads(args.snapshot.read_text(encoding="utf-8"))
        errors = validate_snapshot(value, require_postgresql=args.require_postgresql)
    except Exception as exc:
        print(f"ERROR: invalid fingerprint snapshot: {type(exc).__name__}", file=sys.stderr)
        return 1
    if errors:
        print("ERROR: invalid fingerprint snapshot: " + ",".join(errors), file=sys.stderr)
        return 1
    if args.print_sha:
        assert isinstance(value, dict)
        print(value["overall_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
