from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_data_governance_registry.py"
SPEC = importlib.util.spec_from_file_location("ip_data_governance_registry", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_data_governance_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_data_governance_registry)


def _registry() -> dict:
    return copy.deepcopy(
        ip_data_governance_registry._load(ip_data_governance_registry.REGISTRY_PATH)
    )


def test_committed_iplf_028a_registry_matches_shared_ownership_and_guards() -> None:
    assert ip_data_governance_registry.validate(_registry()) == []


def test_registry_rejects_missing_class_alias_owner_and_execute_overclaim() -> None:
    registry = _registry()
    registry["data_classes"][0]["table_name"] = "retention_policies"
    registry["data_classes"][1]["owner_id"] = "ip-legal-state"
    registry["data_classes"][2]["disposition_handler"] = "implemented"
    registry["data_classes"][3]["runtime_status"] = "live"
    registry["data_classes"] = [
        row
        for row in registry["data_classes"]
        if row["id"] != "tenant_data_operation_items"
    ]
    registry["completion_boundary"] = "IPLF-028A completes tenant export and restore."

    errors = ip_data_governance_registry.validate(registry)

    assert any("must exactly match the six IPLF-028A tables" in error for error in errors)
    assert any("must use shared-foundations owner" in error for error in errors)
    assert any("disposition must fail closed" in error for error in errors)
    assert any("runtime status overclaims delivery" in error for error in errors)
    assert any("explicit incomplete boundary" in error for error in errors)


def test_registry_rejects_missing_policy_terms_and_inaccurate_handler_refs() -> None:
    registry = _registry()
    row = registry["data_classes"][0]
    row["default_retention"] = ""
    row["tenant_configurable"] = "yes"
    row["migration_ref"] = "planned:later"
    row["handler_ref"] = "planned:later"

    errors = ip_data_governance_registry.validate(registry)

    assert any("default_retention must be explicit" in error for error in errors)
    assert any("tenant_configurable must be boolean" in error for error in errors)
    assert any("invalid migration reference" in error for error in errors)
    assert any("invalid handler reference" in error for error in errors)
