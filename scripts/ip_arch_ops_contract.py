#!/usr/bin/env python3
"""Validate the published ARCH-OPS controls and IP event catalogues."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "ip-implementation" / "PROGRAM_MANIFEST.yaml"
LEDGER_PATH = REPO_ROOT / "docs" / "ip-implementation" / "OWNERSHIP_LEDGER.yaml"
CONTRACT_PATH = REPO_ROOT / "docs" / "ip-implementation" / "ARCH_OPS_CONTRACT.yaml"
CATALOGUE_PATH = REPO_ROOT / "docs" / "ip-implementation" / "IP_EVENT_CATALOG.yaml"

GOVERNANCE_OWNERS = {
    "api-contract",
    "api-data",
    "architecture",
    "audit-domain-events",
    "capability-catalogue",
    "program-control",
    "release-engineering",
}
EVENT_FIELDS = {
    "name",
    "version",
    "owner",
    "confidentiality",
    "idempotency_key",
    "consumers",
    "retention",
    "payload_schema",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_requirement_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        row["id"]
        for row in manifest.get("requirements", [])
        if row.get("family") == "ARCH-OPS"
    ]


def _validate_catalogue(catalogue: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalogue.get("schema_version") != 1:
        errors.append("event catalogue schema_version must be 1")
    if not catalogue.get("purpose_boundary"):
        errors.append("event catalogue must distinguish audit and domain-event purposes")

    names: list[str] = []
    for collection in ("audit_actions", "domain_events"):
        rows = catalogue.get(collection)
        if not isinstance(rows, list) or not rows:
            errors.append(f"event catalogue {collection} must be non-empty")
            continue
        for row in rows:
            name = str(row.get("name", "<missing>"))
            names.append(name)
            missing = sorted(EVENT_FIELDS - set(row))
            if missing:
                errors.append(f"event/{name}: missing fields {missing}")
            if row.get("version") != 1:
                errors.append(f"event/{name}: initial stable schema version must be 1")
            if row.get("confidentiality") not in catalogue.get(
                "confidentiality_values", []
            ):
                errors.append(f"event/{name}: invalid confidentiality")
            if not row.get("idempotency_key") or not row.get("consumers"):
                errors.append(f"event/{name}: idempotency and consumers are required")
            if not row.get("retention"):
                errors.append(f"event/{name}: retention is required")
            required = row.get("payload_schema", {}).get("required")
            if not isinstance(required, list) or "correlation_id" not in required:
                errors.append(
                    f"event/{name}: versioned payload requires correlation_id"
                )

    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate audit/domain event names: {duplicates}")
    return errors


def validate(
    contract: dict[str, Any] | None = None,
    catalogue: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    contract = contract or _load(CONTRACT_PATH)
    catalogue = catalogue or _load(CATALOGUE_PATH)
    manifest = _load(MANIFEST_PATH)
    ledger = _load(LEDGER_PATH)

    if contract.get("schema_version") != 1:
        errors.append("ARCH-OPS contract schema_version must be 1")
    expected_ids = _expected_requirement_ids(manifest)
    actual_ids = [row.get("id") for row in contract.get("requirements", [])]
    if actual_ids != expected_ids:
        errors.append("ARCH-OPS contract does not exactly cover PRD ARCH-OPS-01..26")

    known_owners = GOVERNANCE_OWNERS | {
        row.get("id")
        for group in ("new_owners", "existing_owners")
        for row in ledger.get(group, [])
    }
    controls: list[str] = []
    for row in contract.get("requirements", []):
        requirement_id = row.get("id", "<missing>")
        control = row.get("control")
        controls.append(control)
        if row.get("owner") not in known_owners:
            errors.append(f"{requirement_id}: unknown control owner")
        if not control or not row.get("enforcement"):
            errors.append(f"{requirement_id}: control and enforcement are required")
        refs = row.get("refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{requirement_id}: at least one implementation ref is required")
            continue
        for ref in refs:
            if not (REPO_ROOT / ref).is_file():
                errors.append(f"{requirement_id}: missing implementation ref {ref}")

    duplicate_controls = sorted(
        control for control, count in Counter(controls).items() if count > 1
    )
    if duplicate_controls:
        errors.append(f"ARCH-OPS control identifiers are not unique: {duplicate_controls}")

    for name, ref in contract.get("shared_refs", {}).items():
        if not (REPO_ROOT / ref).is_file():
            errors.append(f"shared ref {name} is missing: {ref}")
    errors.extend(_validate_catalogue(catalogue))
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
    print("ARCH-OPS contract valid: 26 controls and versioned event catalogues published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
