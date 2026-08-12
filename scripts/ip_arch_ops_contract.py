#!/usr/bin/env python3
"""Validate the published ARCH-OPS controls and IP event catalogues."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
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
    "scope",
    "envelope",
    "emission_status",
    "confidentiality",
    "idempotency_key",
    "consumers",
    "retention",
    "payload_schema",
}
EVENT_COLLECTION_KINDS = {
    "audit_actions": "audit_action",
    "domain_events": "domain_event",
}
IDEMPOTENCY_COMPONENT = re.compile(r"^[a-z][a-z0-9_]*$")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_requirement_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        row["id"]
        for row in manifest.get("requirements", [])
        if row.get("family") == "ARCH-OPS"
    ]


def _validate_catalogue(
    catalogue: dict[str, Any], *, known_owners: set[str | None]
) -> list[str]:
    errors: list[str] = []
    if catalogue.get("schema_version") != 2:
        errors.append("event catalogue schema_version must be 2")
    if not catalogue.get("purpose_boundary"):
        errors.append("event catalogue must distinguish audit and domain-event purposes")
    if "tenant_id" in json.dumps(catalogue, sort_keys=True):
        errors.append("event catalogue must use repository-standard company_id, not tenant_id")

    scopes = set(catalogue.get("scope_values", []))
    emission_statuses = set(catalogue.get("emission_status_values", []))
    envelopes = catalogue.get("envelopes")
    if scopes != {"company", "repository"}:
        errors.append("event catalogue scopes must be exactly company and repository")
    if emission_statuses != {"catalogued_not_emitted", "runtime_emitted"}:
        errors.append("event catalogue emission statuses are incomplete")
    if not isinstance(envelopes, dict) or not envelopes:
        errors.append("event catalogue envelopes must be non-empty")
        envelopes = {}
    for envelope_name, envelope in envelopes.items():
        if not isinstance(envelope, dict):
            errors.append(f"envelope/{envelope_name}: definition must be an object")
            continue
        required = envelope.get("required")
        if envelope.get("scope") not in scopes:
            errors.append(f"envelope/{envelope_name}: invalid scope")
        if envelope.get("kind") not in EVENT_COLLECTION_KINDS.values():
            errors.append(f"envelope/{envelope_name}: invalid kind")
        if not isinstance(required, list) or not required:
            errors.append(f"envelope/{envelope_name}: required fields must be non-empty")

    keys: list[tuple[str, str, int]] = []
    name_collections: dict[str, set[str]] = defaultdict(set)
    versions_by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    for collection, expected_kind in EVENT_COLLECTION_KINDS.items():
        rows = catalogue.get(collection)
        if not isinstance(rows, list) or not rows:
            errors.append(f"event catalogue {collection} must be non-empty")
            continue
        for row in rows:
            name = str(row.get("name", "<missing>"))
            missing = sorted(EVENT_FIELDS - set(row))
            if missing:
                errors.append(f"event/{name}: missing fields {missing}")
            version = row.get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                errors.append(f"event/{name}: version must be a positive integer")
                version = -1
            keys.append((collection, name, version))
            name_collections[name].add(collection)
            versions_by_name[(collection, name)].append(version)
            if row.get("owner") not in known_owners:
                errors.append(f"event/{name}: unknown owner {row.get('owner')}")
            scope = row.get("scope")
            if scope not in scopes:
                errors.append(f"event/{name}: invalid scope")
            if collection == "domain_events" and scope != "company":
                errors.append(f"event/{name}: repository controls cannot be domain events")
            envelope_name = str(row.get("envelope", ""))
            envelope = envelopes.get(envelope_name, {})
            if not envelope:
                errors.append(f"event/{name}: unknown envelope {envelope_name}")
            else:
                if envelope.get("scope") != scope:
                    errors.append(f"event/{name}: envelope scope does not match event scope")
                if envelope.get("kind") != expected_kind:
                    errors.append(f"event/{name}: envelope kind does not match collection")
            emission_status = row.get("emission_status")
            if emission_status not in emission_statuses:
                errors.append(f"event/{name}: invalid emission status")
            if (
                catalogue.get("status")
                == "stable_names_v1_catalogued_no_runtime_emission_claimed"
                and emission_status != "catalogued_not_emitted"
            ):
                errors.append(f"event/{name}: catalogue status cannot claim runtime emission")
            if row.get("confidentiality") not in catalogue.get(
                "confidentiality_values", []
            ):
                errors.append(f"event/{name}: invalid confidentiality")
            if not row.get("idempotency_key") or not row.get("consumers"):
                errors.append(f"event/{name}: idempotency and consumers are required")
            if not row.get("retention"):
                errors.append(f"event/{name}: retention is required")
            payload_schema = row.get("payload_schema")
            if not isinstance(payload_schema, dict):
                errors.append(f"event/{name}: payload_schema must be an object")
                payload_schema = {}
            payload_required = payload_schema.get("required")
            if not isinstance(payload_required, list):
                errors.append(f"event/{name}: payload required fields must be a list")
                payload_required = []
            envelope_required = envelope.get("required", [])
            all_required = set(envelope_required) | set(payload_required)
            if "correlation_id" not in all_required:
                errors.append(f"event/{name}: versioned envelope requires correlation_id")
            scope_identifier = (
                "company_id" if scope == "company" else "repository_revision"
            )
            if scope_identifier not in all_required:
                errors.append(
                    f"event/{name}: {scope} scope requires {scope_identifier}"
                )
            idempotency_components = str(row.get("idempotency_key", "")).split(":")
            invalid_components = [
                component
                for component in idempotency_components
                if not IDEMPOTENCY_COMPONENT.fullmatch(component)
                or component not in all_required
            ]
            if invalid_components:
                errors.append(
                    f"event/{name}: idempotency key components are not required "
                    f"schema fields: {invalid_components}"
                )

    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicate_keys:
        errors.append(f"duplicate event name/version entries: {duplicate_keys}")
    crossed_names = sorted(
        name for name, collections in name_collections.items() if len(collections) > 1
    )
    if crossed_names:
        errors.append(f"names cannot cross audit/domain catalogues: {crossed_names}")
    for (collection, name), versions in versions_by_name.items():
        valid_versions = sorted(version for version in versions if version > 0)
        if valid_versions != list(range(1, max(valid_versions, default=0) + 1)):
            errors.append(
                f"event/{collection}/{name}: versions must be contiguous from 1; "
                f"found {valid_versions}"
            )
    return errors


def validate(
    contract: dict[str, Any] | None = None,
    catalogue: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if contract is None:
        contract = _load(CONTRACT_PATH)
    if catalogue is None:
        catalogue = _load(CATALOGUE_PATH)
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
    errors.extend(_validate_catalogue(catalogue, known_owners=known_owners))
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
