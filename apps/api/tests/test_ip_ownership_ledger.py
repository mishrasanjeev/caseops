from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_ownership_ledger.py"
SPEC = importlib.util.spec_from_file_location("ip_ownership_ledger", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_ownership_ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_ownership_ledger)


def _ledger() -> dict:
    return copy.deepcopy(ip_ownership_ledger._load_json(ip_ownership_ledger.LEDGER_PATH))


def test_committed_ip_ownership_ledger_and_repository_have_one_writer() -> None:
    assert ip_ownership_ledger.validate(_ledger()) == []


def test_validator_requires_exact_section_11_2_and_m2_m3_coverage() -> None:
    ledger = _ledger()
    ledger["existing_owners"][0]["capability"] = "Convenient second task owner"
    ledger["epic_decisions"].pop()

    errors = ip_ownership_ledger.validate(ledger, scan_repository=False)

    assert any("do not exactly match PRD Section 11.2" in error for error in errors)
    assert any("do not exactly cover every M2/M3 epic" in error for error in errors)


def test_validator_rejects_forbidden_proposal_and_replace_without_adr() -> None:
    ledger = _ledger()
    proposal = ledger["epic_decisions"][0]["components"][0]
    proposal.update(
        {
            "kind": "table",
            "name": "ip_tasks",
            "classification": "REPLACE",
            "owner_id": "shared-tasks",
        }
    )
    proposal.pop("adr_ref", None)

    errors = ip_ownership_ledger.validate(ledger, scan_repository=False)

    assert any("proposes a forbidden duplicate" in error for error in errors)
    assert any("REPLACE lacks a committed ADR" in error for error in errors)


def test_forbidden_source_scan_catches_exact_and_disguised_control_planes() -> None:
    errors = ip_ownership_ledger._forbidden_text_errors(
        Path("apps/api/src/caseops_api/services/ip_tasks.py"),
        "class IpProviderOperations: pass\n",
    )

    assert any("forbidden duplicate identifier ip_tasks" in error for error in errors)
    assert any("forbidden duplicate pattern ip_provider_control_plane" in error for error in errors)


def test_iplf_027_admits_only_exact_shared_and_workflow_foundation_names() -> None:
    ledger = _ledger()
    decision = next(
        row for row in ledger["epic_decisions"] if row["epic_id"] == "IPLF-027"
    )

    names_by_kind = {
        kind: {row["name"] for row in decision["components"] if row["kind"] == kind}
        for kind in ip_ownership_ledger.IPLF_027_COMPONENTS_BY_KIND
    }

    assert names_by_kind == ip_ownership_ledger.IPLF_027_COMPONENTS_BY_KIND


def test_iplf_027_rejects_idempotency_alias_and_missing_workflow_table() -> None:
    ledger = _ledger()
    decision = next(
        row for row in ledger["epic_decisions"] if row["epic_id"] == "IPLF-027"
    )
    idempotency = next(
        row
        for row in decision["components"]
        if row["name"] == "api_idempotency_records"
    )
    idempotency["name"] = "idempotency_records"
    decision["components"] = [
        row
        for row in decision["components"]
        if row["name"] != "ip_workflow_versions"
    ]

    errors = ip_ownership_ledger.validate(ledger, scan_repository=False)

    assert any("IPLF-027 table components must exactly match" in error for error in errors)
