#!/usr/bin/env python3
"""Validate the binding IP ownership ledger and forbidden-duplicate guard.

The ledger is JSON-compatible YAML so this check has no dependency outside the
Python standard library.  It deliberately validates both planned M2/M3 work and
the repository tree: a proposal cannot reserve a second writer, and a later
commit cannot quietly add one under a slightly different file or table name.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PRD_PATH = REPO_ROOT / "docs" / "PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md"
MANIFEST_PATH = REPO_ROOT / "docs" / "ip-implementation" / "PROGRAM_MANIFEST.yaml"
LEDGER_PATH = REPO_ROOT / "docs" / "ip-implementation" / "OWNERSHIP_LEDGER.yaml"

CLASSIFICATIONS = {"NEW", "EXTEND", "LINK", "REPLACE"}
COMPONENT_KINDS = {"table", "service", "route", "page", "job", "contract"}
MILESTONES = {"M2", "M3"}
LEDGER_STATUS = "engineering_control_published_machine_enforced"
IPLF_027_COMPONENTS_BY_KIND = {
    "table": {
        "api_idempotency_records",
        "domain_consumer_effects",
        "domain_outbox_events",
        "ip_workflow_definitions",
        "ip_workflow_versions",
    },
    "service": {
        "ip-workflow-version-service",
        "shared-api-idempotency-service",
        "shared-outbox-consumer-service",
        "shared-transactional-outbox-service",
    },
    "contract": {
        "durable-workflow-adapter",
        "ip-lifecycle-workflow-version-adapter",
    },
}

# Exact names are checked after identifier normalization.  Patterns cover the
# common "same subsystem, new spelling" variants for services/pages/jobs.
FORBIDDEN_IDENTIFIERS = {
    "ip_access_grants",
    "ip_conflict_checks",
    "ip_court_master",
    "ip_drafting_engine",
    "ip_disbursement_evidence",
    "ip_document_processor",
    "ip_hearings",
    "ip_import_jobs",
    "ip_intake_records",
    "ip_malware_scan_jobs",
    "ip_notices",
    "ip_ocr_jobs",
    "ip_payment_records",
    "ip_portal_grants",
    "ip_recommendation_engine",
    "ip_tasks",
    "legal_source_records",
}
FORBIDDEN_PATTERNS = {
    "ip_notification_control_plane": re.compile(
        r"\bip_(?:notification|reminder)_(?:delivery|dispatcher|intent|queue|schedule|worker)s?\b"
    ),
    "ip_provider_control_plane": re.compile(
        r"\bip_provider_(?:operations|readiness|support|cost|replay|dead_letter)s?\b"
    ),
    "ip_report_control_plane": re.compile(
        r"\bip_(?:report|export)_(?:engine|job|artifact|scheduler|storage|delivery)s?\b"
    ),
    "ip_connector_control_plane": re.compile(
        r"\bip_(?:email|oauth|calendar|drive)_connectors?\b"
    ),
}
SCAN_ROOTS = (
    REPO_ROOT / "apps" / "api" / "src" / "caseops_api",
    REPO_ROOT / "apps" / "api" / "alembic" / "versions",
    REPO_ROOT / "apps" / "web" / "app",
    REPO_ROOT / "infra" / "cloudrun",
)
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".json", ".yaml", ".yml", ".ps1", ".sh"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normal_identifier(value: str) -> str:
    value = value.replace("-", "_").replace("/", "_").replace("\\", "_")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value).lower()
    return re.sub(r"_+", "_", value).strip("_")


def _section_11_2_capabilities(prd: str) -> list[str]:
    start = prd.index("### 11.2 Existing CaseOps owners to extend")
    end = prd.index("### 11.3 New shared platform records", start)
    rows: list[str] = []
    for line in prd[start:end].splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        columns = [column.strip() for column in line.strip("|").split("|")]
        if columns[0] == "Capability":
            continue
        rows.append(columns[0])
    return rows


def _m2_m3_epics(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (row["id"], row["milestone_id"])
        for row in manifest.get("epics", [])
        if row.get("milestone_id") in MILESTONES
    ]


def _scan_forbidden_components() -> list[str]:
    errors: list[str] = []
    for root in SCAN_ROOTS:
        if not root.is_dir():
            errors.append(f"ownership scan root is missing: {root.relative_to(REPO_ROOT)}")
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            errors.extend(_forbidden_text_errors(path.relative_to(REPO_ROOT), text))
    return errors


def _forbidden_text_errors(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    haystacks = {_normal_identifier(path.stem), text.lower(), _normal_identifier(text)}
    for forbidden in FORBIDDEN_IDENTIFIERS:
        if any(re.search(rf"\b{re.escape(forbidden)}\b", value) for value in haystacks):
            errors.append(f"forbidden duplicate identifier {forbidden} in {path}")
    for label, pattern in FORBIDDEN_PATTERNS.items():
        if any(pattern.search(value) for value in haystacks):
            errors.append(f"forbidden duplicate pattern {label} in {path}")
    return errors


def validate(
    ledger: dict[str, Any] | None = None, *, scan_repository: bool = True
) -> list[str]:
    errors: list[str] = []
    if ledger is None:
        ledger = _load_json(LEDGER_PATH)
    manifest = _load_json(MANIFEST_PATH)
    prd = PRD_PATH.read_text(encoding="utf-8")

    if ledger.get("schema_version") != 1:
        errors.append("ownership ledger schema_version must be 1")
    if ledger.get("status") != LEDGER_STATUS:
        errors.append(f"ownership ledger status must be {LEDGER_STATUS}")
    if ledger.get("prd_path") != str(PRD_PATH.relative_to(REPO_ROOT)).replace("\\", "/"):
        errors.append("ownership ledger prd_path does not identify the binding PRD")

    expected_capabilities = _section_11_2_capabilities(prd)
    owners = ledger.get("existing_owners", [])
    capabilities = [row.get("capability") for row in owners]
    if capabilities != expected_capabilities:
        errors.append("ownership ledger capabilities/order do not exactly match PRD Section 11.2")
    owner_ids = [row.get("id") for row in owners]
    duplicate_owner_ids = sorted(key for key, count in Counter(owner_ids).items() if count > 1)
    if duplicate_owner_ids:
        errors.append(f"duplicate ownership ledger owner IDs: {duplicate_owner_ids}")

    required_owner_fields = {
        "id",
        "capability",
        "classification",
        "canonical_writer",
        "code_refs",
        "compatibility_path",
        "reconciliation",
        "retirement_gate",
        "earliest_milestone",
        "forbidden_components",
    }
    for owner in owners:
        owner_id = owner.get("id", "<missing>")
        missing = sorted(required_owner_fields - set(owner))
        if missing:
            errors.append(f"owner/{owner_id}: missing fields {missing}")
        if owner.get("classification") not in CLASSIFICATIONS:
            errors.append(f"owner/{owner_id}: invalid classification")
        for ref in owner.get("code_refs", []):
            path = REPO_ROOT / ref
            if not path.exists():
                errors.append(f"owner/{owner_id}: missing repository owner ref {ref}")
        for name in owner.get("forbidden_components", []):
            if _normal_identifier(name) not in FORBIDDEN_IDENTIFIERS and not any(
                pattern.search(_normal_identifier(name)) for pattern in FORBIDDEN_PATTERNS.values()
            ):
                errors.append(f"owner/{owner_id}: unguarded forbidden component {name}")

    decisions = ledger.get("epic_decisions", [])
    actual_epics = [(row.get("epic_id"), row.get("milestone")) for row in decisions]
    expected_epics = _m2_m3_epics(manifest)
    if actual_epics != expected_epics:
        errors.append("ownership ledger epic decisions/order do not exactly cover every M2/M3 epic")
    decision_ids = {row.get("id") for row in decisions}
    if len(decision_ids) != len(decisions):
        errors.append("ownership ledger epic decision IDs are not unique")

    known_owner_ids = set(owner_ids) | {
        row.get("id") for row in ledger.get("new_owners", [])
    }
    component_names: list[str] = []
    required_component_fields = {
        "kind",
        "name",
        "classification",
        "owner_id",
        "canonical_writer",
        "state_boundary",
        "implementation_phase",
    }
    for decision in decisions:
        decision_id = decision.get("id", "<missing>")
        if not decision.get("components"):
            errors.append(
                f"decision/{decision_id}: "
                "has no table/service/route/page/job/contract decision"
            )
        for component in decision.get("components", []):
            missing = sorted(required_component_fields - set(component))
            name = str(component.get("name", ""))
            component_names.append(name)
            if missing:
                errors.append(f"decision/{decision_id}/{name}: missing fields {missing}")
            if component.get("kind") not in COMPONENT_KINDS:
                errors.append(f"decision/{decision_id}/{name}: invalid component kind")
            if component.get("classification") not in CLASSIFICATIONS:
                errors.append(f"decision/{decision_id}/{name}: invalid classification")
            if component.get("owner_id") not in known_owner_ids:
                errors.append(f"decision/{decision_id}/{name}: unknown canonical owner")
            normalized = _normal_identifier(name)
            if normalized in FORBIDDEN_IDENTIFIERS or any(
                pattern.search(normalized) for pattern in FORBIDDEN_PATTERNS.values()
            ):
                errors.append(f"decision/{decision_id}/{name}: proposes a forbidden duplicate")
            if component.get("classification") == "REPLACE":
                adr_ref = component.get("adr_ref")
                if not adr_ref or not (REPO_ROOT / adr_ref).is_file():
                    errors.append(f"decision/{decision_id}/{name}: REPLACE lacks a committed ADR")

    duplicate_components = sorted(
        key for key, count in Counter(component_names).items() if count > 1
    )
    if duplicate_components:
        errors.append(f"duplicate proposed component ownership: {duplicate_components}")

    iplf_027 = next(
        (row for row in decisions if row.get("epic_id") == "IPLF-027"),
        None,
    )
    if iplf_027 is None:
        errors.append("ownership ledger is missing the IPLF-027 shared-foundation decision")
    else:
        components = iplf_027.get("components", [])
        for kind, expected_names in IPLF_027_COMPONENTS_BY_KIND.items():
            actual_names = {
                str(row.get("name", ""))
                for row in components
                if row.get("kind") == kind
            }
            if actual_names != expected_names:
                errors.append(
                    f"IPLF-027 {kind} components must exactly match "
                    f"{sorted(expected_names)}; found {sorted(actual_names)}"
                )

    for ref in ledger.get("adr_refs", []):
        if not (REPO_ROOT / ref).is_file():
            errors.append(f"ownership ledger ADR is missing: {ref}")

    if scan_repository:
        errors.extend(_scan_forbidden_components())
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
    print("IP ownership ledger valid: Section 11.2 owners and all M2/M3 proposals are unique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
