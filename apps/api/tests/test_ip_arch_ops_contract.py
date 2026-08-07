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
    assert any("initial stable schema version" in error for error in errors)
    assert any("duplicate audit/domain event names" in error for error in errors)
