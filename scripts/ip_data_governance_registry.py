#!/usr/bin/env python3
"""Validate the IPLF-028A dry-run records-governance registry.

The registry intentionally covers only the six new governance tables.  It is
not a declaration that the full platform data map, retention policy, export,
purge, restore, or resilience program has been completed.
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
    / "IPLF_028A_DATA_GOVERNANCE_REGISTRY.yaml"
)
MIGRATION_PATH = (
    REPO_ROOT
    / "apps"
    / "api"
    / "alembic"
    / "versions"
    / "20260813_0001_data_governance_foundation.py"
)
HANDLER_PATH = (
    REPO_ROOT / "apps" / "api" / "src" / "caseops_api" / "services" / "data_governance.py"
)

EXPECTED_COMPONENTS = {
    "data_retention_policies_and_versions": {
        "data_retention_policies",
        "data_retention_versions",
    },
    "legal_holds_and_items": {"legal_holds", "legal_hold_items"},
    "tenant_data_operations_and_items": {
        "tenant_data_operations",
        "tenant_data_operation_items",
    },
}
EXPECTED_TABLES = set().union(*EXPECTED_COMPONENTS.values())


def _runtime_admitted_ids() -> set[str] | None:
    """What the deployed runtime would actually admit, or None if unreadable."""

    api_src = REPO_ROOT / "apps" / "api" / "src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))
    try:
        from caseops_api.governance import generated_data_class_projection as projection
    except Exception:
        return None
    return set(projection.ADMITTED_DATA_CLASSES)


CONFIDENTIALITY_VALUES = {"internal", "confidential", "privileged"}
REGISTRY_STATUS = "repository_schema_implemented_dry_run_only"
RUNTIME_STATUS = "repository_implemented_dry_run_only"
STORAGE_VALUE = "migration_managed_relational_table"
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
    "ownership_component",
    "owner_id",
    "company_scope",
    "company_key",
    "storage",
    "confidentiality",
    "purpose",
    "legal_policy_basis",
    "default_retention",
    "tenant_configurable",
    "disposition_handler",
    "runtime_status",
    "introduced_by",
    "migration_ref",
    "handler_ref",
} | DISPOSITION_FIELDS


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iplf_028_components(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    decision = next(
        (
            row
            for row in ledger.get("epic_decisions", [])
            if row.get("id") == "M2M3-IPLF-028"
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
        errors.append("IPLF-028A data-governance registry schema_version must be 1")
    if registry.get("slice_id") != "IPLF-028A":
        errors.append("data-governance registry must be bounded to IPLF-028A")
    if registry.get("status") != REGISTRY_STATUS:
        errors.append("data-governance registry must state dry-run-only implementation")
    expected_ref = str(LEDGER_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    if registry.get("ownership_ledger_ref") != expected_ref:
        errors.append("data-governance registry must reference the binding ownership ledger")
    if registry.get("ownership_decision_id") != "M2M3-IPLF-028":
        errors.append("data-governance registry must reference the IPLF-028 decision")
    completion_boundary = str(registry.get("completion_boundary", "")).lower()
    for required_term in ("does not claim", "export", "purge", "restore"):
        if required_term not in completion_boundary:
            errors.append(
                "data-governance registry must preserve the explicit incomplete boundary"
            )
            break

    ledger_components = _iplf_028_components(ledger)
    if set(ledger_components) != set(EXPECTED_COMPONENTS):
        errors.append("ownership ledger IPLF-028 components must remain exact")
    for component in EXPECTED_COMPONENTS:
        row = ledger_components.get(component)
        if row is None:
            continue
        if row.get("owner_id") != "platform-shared-foundations":
            errors.append(f"ownership ledger component/{component}: invalid owner")

    known_owner_ids = {
        row.get("id")
        for group in ("new_owners", "existing_owners")
        for row in ledger.get(group, [])
    }
    rows = registry.get("data_classes")
    if not isinstance(rows, list) or not rows:
        errors.append("IPLF-028A data_classes must be non-empty")
        return errors

    table_names = [str(row.get("table_name", "")) for row in rows]
    ids = [str(row.get("id", "")) for row in rows]
    if set(table_names) != EXPECTED_TABLES:
        errors.append(
            "registry table names must exactly match the six IPLF-028A tables: "
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

    migration_ref = str(MIGRATION_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    handler_ref = str(HANDLER_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
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
        component = str(row.get("ownership_component", ""))
        if table_name not in EXPECTED_COMPONENTS.get(component, set()):
            errors.append(
                f"data-class/{data_class_id}: table does not belong to ownership component"
            )
        if row.get("owner_id") != "platform-shared-foundations":
            errors.append(f"data-class/{data_class_id}: must use shared-foundations owner")
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
        if row.get("introduced_by") != "IPLF-028A":
            errors.append(f"data-class/{data_class_id}: introduced_by must be IPLF-028A")
        if row.get("migration_ref") != migration_ref:
            errors.append(f"data-class/{data_class_id}: invalid migration reference")
        if row.get("handler_ref") != handler_ref:
            errors.append(f"data-class/{data_class_id}: invalid handler reference")
        if not isinstance(row.get("tenant_configurable"), bool):
            errors.append(f"data-class/{data_class_id}: tenant_configurable must be boolean")
        for field in DISPOSITION_FIELDS | {
            "purpose",
            "legal_policy_basis",
            "default_retention",
        }:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"data-class/{data_class_id}: {field} must be explicit")

    if not MIGRATION_PATH.is_file() or not HANDLER_PATH.is_file():
        errors.append("data-governance registry implementation references must exist")
        return errors
    migration_source = MIGRATION_PATH.read_text(encoding="utf-8")
    handler_source = HANDLER_PATH.read_text(encoding="utf-8")
    for table_name in EXPECTED_TABLES:
        if f'"{table_name}"' not in migration_source:
            errors.append(f"migration does not create registered table {table_name}")

    # Admission used to be a frozenset literal in the handler, so this checked
    # that each id appeared in that file's SOURCE TEXT. That bond was weak - a
    # commented-out id or an unrelated string would satisfy it - and it broke
    # the moment admission moved to the compiled projection, which is where it
    # belongs. Compare against what the runtime actually admits instead, in both
    # directions: a substring check can only catch a missing id, never an extra
    # one, and an extra admitted class is the more dangerous of the two.
    admitted = _runtime_admitted_ids()
    if admitted is None:
        errors.append(
            "the compiled data-class projection could not be imported, so the "
            "registry cannot be checked against what the runtime admits"
        )
    else:
        for table_name in sorted(EXPECTED_TABLES - admitted):
            errors.append(
                f"dry-run handler does not admit registered data class {table_name}"
            )
        for table_name in sorted(admitted - EXPECTED_TABLES):
            errors.append(
                f"dry-run handler admits {table_name}, which this registry does not "
                "declare"
            )
    for safety_constraint in (
        "ck_tenant_data_operation_dry_run_only",
        "ck_tenant_data_operation_item_never_execute",
        "data_operation_execution_unavailable",
    ):
        source = (
            migration_source
            if safety_constraint.startswith("ck_")
            else handler_source
        )
        if safety_constraint not in source:
            errors.append(f"missing dry-run safety guard {safety_constraint}")
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
    print("IPLF-028A data-governance registry valid: six dry-run-only data classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
