from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_arch_ops_contract.py"
SPEC = importlib.util.spec_from_file_location("ip_arch_ops_contract", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_arch_ops_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_arch_ops_contract)


def _contract() -> dict:
    return copy.deepcopy(ip_arch_ops_contract._load(ip_arch_ops_contract.CONTRACT_PATH))


def _catalogue() -> dict:
    return copy.deepcopy(ip_arch_ops_contract._load(ip_arch_ops_contract.CATALOGUE_PATH))


def test_published_contract_covers_every_arch_ops_requirement() -> None:
    assert ip_arch_ops_contract.validate(_contract(), _catalogue()) == []


@pytest.mark.parametrize(
    "requirement_id", [f"ARCH-OPS-{index:02d}" for index in range(1, 27)]
)
def test_each_arch_ops_requirement_has_an_active_control(requirement_id: str) -> None:
    controls = {row["id"]: row for row in _contract()["requirements"]}

    assert controls[requirement_id]["control"]
    assert controls[requirement_id]["enforcement"]
    assert controls[requirement_id]["refs"]


def test_contract_fails_closed_when_a_requirement_or_ref_is_missing() -> None:
    contract = _contract()
    contract["requirements"].pop()
    contract["requirements"][0]["refs"] = ["docs/not-present.md"]

    errors = ip_arch_ops_contract.validate(contract, _catalogue())

    assert any("does not exactly cover" in error for error in errors)
    assert any("missing implementation ref" in error for error in errors)


def test_event_catalogues_require_versioned_complete_distinct_entries() -> None:
    catalogue = _catalogue()
    catalogue["domain_events"][0].pop("retention")
    catalogue["domain_events"][0]["version"] = 2
    catalogue["domain_events"][0]["name"] = catalogue["audit_actions"][0]["name"]

    errors = ip_arch_ops_contract.validate(_contract(), catalogue)

    assert any("missing fields ['retention']" in error for error in errors)
    assert any("versions must be contiguous from 1" in error for error in errors)
    assert any("names cannot cross audit/domain catalogues" in error for error in errors)


def test_event_catalogue_rejects_tenant_alias_unknown_owner_and_scope_drift() -> None:
    catalogue = _catalogue()
    event = catalogue["domain_events"][0]
    event["owner"] = "private-ip-event-bus"
    event["scope"] = "repository"
    event["idempotency_key"] = "tenant_id:missing_field"

    errors = ip_arch_ops_contract.validate(_contract(), catalogue)

    assert any("must use repository-standard company_id" in error for error in errors)
    assert any("unknown owner private-ip-event-bus" in error for error in errors)
    assert any("repository controls cannot be domain events" in error for error in errors)
    assert any("idempotency key components are not required" in error for error in errors)


def test_event_catalogue_allows_contiguous_versions_in_one_collection() -> None:
    catalogue = _catalogue()
    next_version = copy.deepcopy(catalogue["domain_events"][0])
    next_version["version"] = 2
    catalogue["domain_events"].append(next_version)

    assert ip_arch_ops_contract.validate(_contract(), catalogue) == []


def test_event_catalogue_rejects_duplicate_name_version() -> None:
    catalogue = _catalogue()
    catalogue["audit_actions"].append(copy.deepcopy(catalogue["audit_actions"][0]))

    errors = ip_arch_ops_contract.validate(_contract(), catalogue)

    assert any("duplicate event name/version entries" in error for error in errors)
