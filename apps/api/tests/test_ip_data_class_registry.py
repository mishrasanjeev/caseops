from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_data_class_registry.py"
SPEC = importlib.util.spec_from_file_location("ip_data_class_registry", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_data_class_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_data_class_registry)


def _registry() -> dict:
    return copy.deepcopy(ip_data_class_registry._load(ip_data_class_registry.REGISTRY_PATH))


def test_committed_iplf_027a_data_class_registry_matches_ownership() -> None:
    assert ip_data_class_registry.validate(_registry()) == []


def test_registry_rejects_alias_missing_workflow_and_duplicate_table() -> None:
    registry = _registry()
    registry["data_classes"][0]["table_name"] = "idempotency_records"
    registry["data_classes"][1]["table_name"] = registry["data_classes"][2][
        "table_name"
    ]
    registry["data_classes"] = [
        row
        for row in registry["data_classes"]
        if row["id"] != "ip_workflow_versions"
    ]

    errors = ip_data_class_registry.validate(registry)

    assert any("must exactly match the five IPLF-027A tables" in error for error in errors)
    assert any("duplicate data-class table names" in error for error in errors)


def test_registry_rejects_owner_scope_handler_and_iplf_028_overclaim() -> None:
    registry = _registry()
    row = registry["data_classes"][0]
    row["owner_id"] = "ip-private-idempotency"
    row["company_scope"] = "optional"
    row["disposition_handler"] = "implemented"
    row["runtime_status"] = "live"
    row["purge_disposition"] = ""
    registry["completion_boundary"] = "IPLF-027A completes data governance."

    errors = ip_data_class_registry.validate(registry)

    assert any("explicit IPLF-028 boundary" in error for error in errors)
    assert any("unknown owner" in error for error in errors)
    assert any("company_id scope must be required" in error for error in errors)
    assert any("disposition must fail closed" in error for error in errors)
    assert any("runtime status overclaims delivery" in error for error in errors)
    assert any("purge_disposition must be explicit" in error for error in errors)
