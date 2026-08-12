#!/usr/bin/env python3
"""Validate the bounded IPLF-027A data-class implementation registry.

This is deliberately not the IPLF-028 runtime data map. It keeps the five
IPLF-027A migration-managed tables aligned with the ownership ledger while
requiring every data operation to remain explicitly fail-closed until IPLF-028
provides the approved retention/hold/export/purge/restore handlers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "ip-implementation" / "OWNERSHIP_LEDGER.yaml"
REGISTRY_PATH = (
    REPO_ROOT
    / "docs"
    / "ip-implementation"
    / "IPLF_027A_DATA_CLASS_REGISTRY.yaml"
)

EXPECTED_TABLES = {
    "api_idempotency_records",
    "domain_consumer_effects",
    "domain_outbox_events",
    "ip_workflow_definitions",
    "ip_workflow_versions",
}
CONFIDENTIALITY_VALUES = {"internal", "confidential", "privileged"}
REGISTRY_STATUS = "repository_schema_implemented_runtime_unreleased"
STORAGE_VALUE = "migration_managed_relational_table"
RUNTIME_STATUS = "repository_implemented_runtime_unreleased"
DISPOSITION_FIELDS = {
    "retention_disposition",
    "legal_hold_disposition",
    "export_disposition",
    "purge_disposition",
    "restore_disposition",
    "projection_disposition",
}
REQUIRED_DATA_CLASS_FIELDS = {
    "id",
    "table_name",
    "owner_id",
    "company_scope",
    "company_key",
    "storage",
    "confidentiality",
    "disposition_handler",
    "runtime_status",
    "introduced_by",
} | DISPOSITION_FIELDS


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iplf_027_tables(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    decision = next(
        (
            row
            for row in ledger.get("epic_decisions", [])
            if row.get("id") == "M2M3-IPLF-027"
        ),
        None,
    )
    if decision is None:
        return {}
    return {
        str(row.get("name")): row
        for row in decision.get("components", [])
        if row.get("kind") == "table"
    }


def validate(registry: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    if registry is None:
        registry = _load(REGISTRY_PATH)
    ledger = _load(LEDGER_PATH)

    if registry.get("schema_version") != 1:
        errors.append("IPLF-027A data-class registry schema_version must be 1")
    if registry.get("slice_id") != "IPLF-027A":
        errors.append("data-class registry must be bounded to IPLF-027A")
    if registry.get("status") != REGISTRY_STATUS:
        errors.append(
            "data-class registry must state repository implementation with runtime unreleased"
        )
    expected_ref = str(LEDGER_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    if registry.get("ownership_ledger_ref") != expected_ref:
        errors.append("data-class registry must reference the binding ownership ledger")
    if registry.get("ownership_decision_id") != "M2M3-IPLF-027":
        errors.append("data-class registry must reference the IPLF-027 decision")
    completion_boundary = str(registry.get("completion_boundary", ""))
    if "IPLF-028" not in completion_boundary or "does not claim" not in completion_boundary:
        errors.append("data-class registry must preserve the explicit IPLF-028 boundary")

    ledger_tables = _iplf_027_tables(ledger)
    if set(ledger_tables) != EXPECTED_TABLES:
        errors.append(
            "ownership ledger IPLF-027 tables must exactly match the five admitted "
            f"data classes: {sorted(EXPECTED_TABLES)}"
        )

    known_owner_ids = {
        row.get("id")
        for group in ("new_owners", "existing_owners")
        for row in ledger.get(group, [])
    }
    rows = registry.get("data_classes")
    if not isinstance(rows, list) or not rows:
        errors.append("IPLF-027A data_classes must be non-empty")
        return errors

    table_names = [str(row.get("table_name", "")) for row in rows]
    ids = [str(row.get("id", "")) for row in rows]
    if set(table_names) != EXPECTED_TABLES:
        errors.append(
            "registry table names must exactly match the five IPLF-027A tables: "
            f"{sorted(EXPECTED_TABLES)}"
        )
    duplicate_tables = sorted(
        name for name, count in Counter(table_names).items() if count > 1
    )
    duplicate_ids = sorted(name for name, count in Counter(ids).items() if count > 1)
    if duplicate_tables:
        errors.append(f"duplicate data-class table names: {duplicate_tables}")
    if duplicate_ids:
        errors.append(f"duplicate data-class IDs: {duplicate_ids}")

    for row in rows:
        data_class_id = str(row.get("id", "<missing>"))
        table_name = str(row.get("table_name", "<missing>"))
        missing = sorted(REQUIRED_DATA_CLASS_FIELDS - set(row))
        if missing:
            errors.append(f"data-class/{data_class_id}: missing fields {missing}")
        if data_class_id != table_name:
            errors.append(f"data-class/{data_class_id}: ID must equal exact table name")
        if row.get("owner_id") not in known_owner_ids:
            errors.append(f"data-class/{data_class_id}: unknown owner")
        ledger_row = ledger_tables.get(table_name)
        if ledger_row and row.get("owner_id") != ledger_row.get("owner_id"):
            errors.append(f"data-class/{data_class_id}: owner differs from ledger")
        if row.get("company_scope") != "required" or row.get("company_key") != "company_id":
            errors.append(f"data-class/{data_class_id}: company_id scope must be required")
        if row.get("storage") != STORAGE_VALUE:
            errors.append(
                f"data-class/{data_class_id}: storage must be migration-managed relational"
            )
        if row.get("confidentiality") not in CONFIDENTIALITY_VALUES:
            errors.append(f"data-class/{data_class_id}: invalid confidentiality")
        if row.get("disposition_handler") != "unimplemented_fail_closed":
            errors.append(f"data-class/{data_class_id}: disposition must fail closed")
        if row.get("runtime_status") != RUNTIME_STATUS:
            errors.append(f"data-class/{data_class_id}: runtime status overclaims delivery")
        if row.get("introduced_by") != "IPLF-027A":
            errors.append(f"data-class/{data_class_id}: introduced_by must be IPLF-027A")
        for field in DISPOSITION_FIELDS:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"data-class/{data_class_id}: {field} must be explicit")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate",), nargs="?", default="validate")
    parser.parse_args(argv)
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "IPLF-027A data-class registry valid: five company-scoped "
        "migration-managed classes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
