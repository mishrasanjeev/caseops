#!/usr/bin/env python3
"""Bootstrap, validate, and render the CaseOps IP program control plane.

The canonical manifest is JSON-compatible YAML so this control-plane tool has
no runtime dependency beyond the Python standard library. Generated Markdown
views are projections and must never be edited independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PRD_PATH = REPO_ROOT / "docs" / "PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md"
CONTROL_ROOT = REPO_ROOT / "docs" / "ip-implementation"
MANIFEST_PATH = CONTROL_ROOT / "PROGRAM_MANIFEST.yaml"
GENERATED_ROOT = CONTROL_ROOT / "generated"

EXPECTED_REQUIREMENTS = 436
EXPECTED_FAMILIES = 50
EXPECTED_JOURNEYS = 68

IMPLEMENTATION_STATUSES = {"not_started", "in_progress", "implemented", "blocked"}
VERIFICATION_STATUSES = {"not_run", "failed", "passed", "blocked"}
RELEASE_STATUSES = {
    "not_required",
    "ready_for_review",
    "approved",
    "deployed",
    "deployment_verified",
    "blocked",
}
ACCEPTANCE_STATUSES = {"not_required", "pending", "approved", "rejected", "blocked"}

FORBIDDEN_COMPONENTS = {
    "ip_tasks",
    "ip_hearings",
    "ip_intake_records",
    "ip_conflict_checks",
    "ip_access_grants",
    "ip_portal_grants",
    "ip_notices",
    "ip_import_jobs",
    "ip_payment_records",
    "ip_disbursement_evidence",
    "legal_source_records",
}


class ManifestError(RuntimeError):
    """Raised for one or more structural control-plane failures."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def status_block(*, release_status: str = "blocked") -> dict[str, str]:
    return {
        "implementation_status": "not_started",
        "verification_status": "not_run",
        "release_status": release_status,
        "acceptance_status": "pending",
    }


def parse_requirements(prd: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"^- `([A-Z][A-Z0-9-]+-\d{2})`: (.+)$", re.MULTILINE)
    rows: list[dict[str, Any]] = []
    for requirement_id, text in pattern.findall(prd):
        rows.append(
            {
                "id": requirement_id,
                "family": requirement_id.rsplit("-", 1)[0],
                "text": normalize_space(text),
                "text_sha256": sha256_text(normalize_space(text)),
                "journey_ids": [],
                "implementation_refs": [],
                "test_refs": [],
                "evidence_refs": [],
                "blockers": [],
                **status_block(),
            }
        )
    return rows


def split_exception_block(value: str) -> list[str]:
    value = normalize_space(value)
    if not value:
        return []
    parts = re.split(r";\s+|(?<=[.!?])\s+(?=[A-Z])", value)
    return [part.strip() for part in parts if part.strip()]


def _field(block: str, name: str, next_names: str) -> str:
    match = re.search(
        rf"\*\*{re.escape(name)}:\*\*\s*(.*?)(?=\n\*\*(?:{next_names}):\*\*)",
        block,
        re.DOTALL,
    )
    return normalize_space(match.group(1)) if match else ""


def parse_journeys(prd: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    heading = re.compile(r"^### (UJ-\d{2}): (.+)$", re.MULTILINE)
    matches = list(heading.finditer(prd))
    journeys: list[dict[str, Any]] = []
    paths: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        journey_id = match.group(1)
        title = normalize_space(match.group(2))
        end = matches[index + 1].start() if index + 1 < len(matches) else prd.find("\n## 16.", match.end())
        block = prd[match.end() : end if end >= 0 else len(prd)]
        actor = _field(block, "Actor", "Preconditions")
        preconditions = _field(block, "Preconditions", "Main flow")
        exception_match = re.search(
            r"\*\*Exceptions:\*\*\s*(.*?)(?=\n\*\*Audit/postcondition:\*\*)",
            block,
            re.DOTALL,
        )
        exception_block = normalize_space(exception_match.group(1)) if exception_match else ""
        acceptance_match = re.search(r"\*\*Acceptance:\*\*\s*(.+?)(?=\n\n|\Z)", block, re.DOTALL)
        acceptance = normalize_space(acceptance_match.group(1)) if acceptance_match else ""
        exception_ids: list[str] = []

        normal_id = f"{journey_id}-NORMAL"
        paths.append(
            {
                "id": normal_id,
                "journey_id": journey_id,
                "kind": "normal",
                "source_text": f"Normal path for {journey_id}: {title}",
                "test_id": f"IPLF-{journey_id}-NORMAL",
                "requirement_ids": [],
                "test_refs": [],
                "evidence_refs": [],
                **status_block(),
            }
        )
        for exception_index, exception in enumerate(split_exception_block(exception_block), start=1):
            exception_id = f"{journey_id}-EXC-{exception_index:02d}"
            exception_ids.append(exception_id)
            paths.append(
                {
                    "id": exception_id,
                    "journey_id": journey_id,
                    "kind": "exception",
                    "source_text": exception,
                    "source_sha256": sha256_text(exception),
                    "test_id": f"IPLF-{journey_id}-EXC-{exception_index:02d}",
                    "requirement_ids": [],
                    "test_refs": [],
                    "evidence_refs": [],
                    **status_block(),
                }
            )
        journeys.append(
            {
                "id": journey_id,
                "title": title,
                "actor": actor,
                "preconditions": preconditions,
                "acceptance": acceptance,
                "exception_source_sha256": sha256_text(exception_block),
                "path_ids": [normal_id, *exception_ids],
                "requirement_ids": [],
                "test_refs": [],
                "evidence_refs": [],
                **status_block(),
            }
        )
    return journeys, paths


def parse_backlog(prd: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_milestone: str | None = None
    entries: dict[str, dict[str, Any]] = {}
    for line in prd.splitlines():
        milestone_match = re.match(r"^### (M\d+(?:-M\d+)?) tasks$", line)
        if milestone_match:
            current_milestone = milestone_match.group(1)
            continue
        item = re.match(r"^- `(IPLF-\d{3}[A-Z]?)`: (.+)$", line)
        if item and current_milestone:
            item_id, title = item.groups()
            entries[item_id] = {
                "id": item_id,
                "title": normalize_space(title),
                "milestone_id": current_milestone,
            }

    mandatory = re.search(
        r"### 25\.1 Mandatory first execution order\s+(.*?)(?=\n### 25\.2)",
        prd,
        re.DOTALL,
    )
    if mandatory:
        for item_id, title in re.findall(r"\d+\. `(IPLF-\d{3}[A-Z])`: (.+)", mandatory.group(1)):
            base_id = item_id[:-1]
            base = entries.get(base_id, {})
            entries[item_id] = {
                "id": item_id,
                "title": normalize_space(title),
                "milestone_id": base.get("milestone_id", "M1"),
            }

    epics: list[dict[str, Any]] = []
    slices: list[dict[str, Any]] = []
    for item_id in sorted(entries):
        row = entries[item_id]
        if re.fullmatch(r"IPLF-\d{3}", item_id):
            epics.append(
                {
                    **row,
                    "requirement_ids": [],
                    "journey_ids": [],
                    "slice_ids": [],
                    **status_block(),
                }
            )
        else:
            slices.append(
                {
                    **row,
                    "epic_id": item_id[:-1],
                    "requirement_ids": [],
                    "journey_path_ids": [],
                    "ownership": [],
                    "dependencies": [],
                    "implementation_refs": [],
                    "test_refs": [],
                    "evidence_refs": [],
                    "approvals": [],
                    "blockers": [],
                    "next_actions": [],
                    "data_impact": [],
                    "documentation_impact": [],
                    **status_block(),
                }
            )
    slice_ids_by_epic: dict[str, list[str]] = {}
    for slice_row in slices:
        slice_ids_by_epic.setdefault(slice_row["epic_id"], []).append(slice_row["id"])
    for epic in epics:
        epic["slice_ids"] = slice_ids_by_epic.get(epic["id"], [])
    return epics, slices


def parse_milestones(prd: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"^\| (M\d+): ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", re.MULTILINE)
    for milestone_id, name, target, deliverable, exit_criteria in pattern.findall(prd):
        rows.append(
            {
                "id": milestone_id,
                "name": normalize_space(name),
                "target": normalize_space(target),
                "deliverable": normalize_space(deliverable),
                "exit_criteria": normalize_space(exit_criteria),
                "blockers": [],
                **status_block(),
            }
        )
    return rows


def bootstrap_manifest() -> dict[str, Any]:
    prd = PRD_PATH.read_text(encoding="utf-8")
    requirements = parse_requirements(prd)
    journeys, journey_paths = parse_journeys(prd)
    epics, slices = parse_backlog(prd)
    milestones = parse_milestones(prd)
    return {
        "schema_version": 1,
        "format": "JSON-compatible YAML; PROGRAM_MANIFEST.yaml is canonical",
        "program": {
            "id": "PRD-IPLF-2026-08-01",
            "prd_path": PRD_PATH.relative_to(REPO_ROOT).as_posix(),
            "prd_sha256": sha256_text(prd),
            "baseline": {
                "requirement_count": EXPECTED_REQUIREMENTS,
                "family_count": EXPECTED_FAMILIES,
                "journey_count": EXPECTED_JOURNEYS,
            },
            "implementation_status": "in_progress",
            "verification_status": "failed",
            "release_status": "blocked",
            "acceptance_status": "pending",
            "active_slice": "IPLF-001A",
            "checkpoint": {},
        },
        "milestones": milestones,
        "epics": epics,
        "slices": slices,
        "requirements": requirements,
        "journeys": journeys,
        "journey_paths": journey_paths,
    }


def load_manifest() -> dict[str, Any]:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"Missing canonical manifest: {MANIFEST_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest is not valid JSON-compatible YAML: {exc}") from exc


def compute_verified(row: dict[str, Any]) -> bool:
    release_ok = row.get("release_status") in {"not_required", "deployment_verified"}
    acceptance_ok = row.get("acceptance_status") in {"not_required", "approved"}
    return bool(
        row.get("implementation_status") == "implemented"
        and row.get("verification_status") == "passed"
        and release_ok
        and acceptance_ok
        and not row.get("blockers")
        and row.get("evidence_refs")
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    output.extend("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows)
    return "\n".join(output) + "\n"


def render_views(manifest: dict[str, Any]) -> dict[Path, str]:
    program = manifest["program"]
    requirements = manifest["requirements"]
    journeys = manifest["journeys"]
    paths = manifest["journey_paths"]
    slices = manifest["slices"]
    active = [row for row in slices if row["id"] == program.get("active_slice")]

    summary = (
        "# IP implementation summary\n\n"
        "Generated from `PROGRAM_MANIFEST.yaml`; do not edit directly.\n\n"
        f"- Active slice: `{program.get('active_slice')}`\n"
        f"- Requirements: {len(requirements)} across {len({row['family'] for row in requirements})} families\n"
        f"- Journeys: {len(journeys)} with {len(paths)} atomic normal/exception paths\n"
        f"- Program status: `{program['implementation_status']}` / `{program['verification_status']}` / "
        f"`{program['release_status']}` / `{program['acceptance_status']}`\n"
    )
    requirement_view = "# Requirement traceability\n\nGenerated; do not edit.\n\n" + _table(
        ["Requirement", "Family", "Implementation", "Verification", "Release", "Verified"],
        [
            [row["id"], row["family"], row["implementation_status"], row["verification_status"], row["release_status"], str(compute_verified(row)).lower()]
            for row in requirements
        ],
    )
    journey_view = "# Journey traceability\n\nGenerated; do not edit.\n\n" + _table(
        ["Journey", "Title", "Atomic paths", "Implementation", "Verification", "Verified"],
        [
            [row["id"], row["title"], str(len(row["path_ids"])), row["implementation_status"], row["verification_status"], str(compute_verified(row)).lower()]
            for row in journeys
        ],
    )
    implementation_view = "# Implementation view\n\nGenerated; do not edit.\n\n" + _table(
        ["Slice", "Milestone", "Requirements", "Journey paths", "Implementation", "Verification", "Release", "Acceptance"],
        [
            [row["id"], row["milestone_id"], ", ".join(row["requirement_ids"]), ", ".join(row["journey_path_ids"]), row["implementation_status"], row["verification_status"], row["release_status"], row["acceptance_status"]]
            for row in slices
        ],
    )
    ownership_rows: list[list[str]] = []
    for row in active:
        for owner in row.get("ownership", []):
            ownership_rows.append(
                [row["id"], owner.get("classification", ""), owner.get("component", ""), owner.get("canonical_writer", ""), owner.get("compatibility_path", ""), owner.get("retirement_gate", "")]
            )
    ownership_view = "# Ownership view\n\nGenerated; do not edit.\n\n" + _table(
        ["Slice", "Class", "Component", "Canonical writer", "Compatibility", "Retirement gate"],
        ownership_rows,
    )
    data_view = "# Data view\n\nGenerated; do not edit.\n\n" + _table(
        ["Slice", "Data impact"],
        [[row["id"], "; ".join(row.get("data_impact", [])) or "None declared"] for row in active],
    )
    docs_view = "# Documentation view\n\nGenerated; do not edit.\n\n" + _table(
        ["Slice", "Artifact", "Disposition", "Owner", "Evidence"],
        [
            [row["id"], item.get("artifact", ""), item.get("disposition", ""), item.get("owner", ""), item.get("evidence", "")]
            for row in active
            for item in row.get("documentation_impact", [])
        ],
    )
    release_view = "# Release view\n\nGenerated; do not edit.\n\n" + _table(
        ["Slice", "Release", "Acceptance", "Blockers", "Next actions"],
        [[row["id"], row["release_status"], row["acceptance_status"], "; ".join(item.get("summary", "") for item in row.get("blockers", [])), "; ".join(row.get("next_actions", []))] for row in active],
    )
    return {
        GENERATED_ROOT / "SUMMARY.md": summary,
        GENERATED_ROOT / "REQUIREMENTS.md": requirement_view,
        GENERATED_ROOT / "JOURNEYS.md": journey_view,
        GENERATED_ROOT / "IMPLEMENTATION.md": implementation_view,
        GENERATED_ROOT / "OWNERSHIP.md": ownership_view,
        GENERATED_ROOT / "DATA.md": data_view,
        GENERATED_ROOT / "DOCUMENTATION.md": docs_view,
        GENERATED_ROOT / "RELEASE.md": release_view,
    }


def write_views(manifest: dict[str, Any]) -> None:
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    for path, content in render_views(manifest).items():
        path.write_text(content, encoding="utf-8", newline="\n")


def validate(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    prd = PRD_PATH.read_text(encoding="utf-8")
    parsed_requirements = parse_requirements(prd)
    parsed_journeys, parsed_paths = parse_journeys(prd)
    parsed_epics, parsed_slices = parse_backlog(prd)
    parsed_milestones = parse_milestones(prd)

    requirement_ids = [row.get("id") for row in manifest.get("requirements", [])]
    parsed_requirement_ids = [row["id"] for row in parsed_requirements]
    duplicate_requirements = sorted(key for key, count in Counter(requirement_ids).items() if count > 1)
    if duplicate_requirements:
        errors.append(f"duplicate manifest requirement IDs: {duplicate_requirements}")
    if len(parsed_requirement_ids) != EXPECTED_REQUIREMENTS:
        errors.append(f"PRD requirement count drift: expected {EXPECTED_REQUIREMENTS}, found {len(parsed_requirement_ids)}")
    parsed_families = {row["family"] for row in parsed_requirements}
    if len(parsed_families) != EXPECTED_FAMILIES:
        errors.append(f"PRD family count drift: expected {EXPECTED_FAMILIES}, found {len(parsed_families)}")
    if requirement_ids != parsed_requirement_ids:
        errors.append("manifest requirement IDs/order do not exactly match the PRD")

    journey_ids = [row.get("id") for row in manifest.get("journeys", [])]
    parsed_journey_ids = [row["id"] for row in parsed_journeys]
    if len(parsed_journey_ids) != EXPECTED_JOURNEYS:
        errors.append(f"PRD journey count drift: expected {EXPECTED_JOURNEYS}, found {len(parsed_journey_ids)}")
    if journey_ids != parsed_journey_ids:
        errors.append("manifest journey IDs/order do not exactly match the PRD")

    if [row.get("id") for row in manifest.get("milestones", [])] != [
        row["id"] for row in parsed_milestones
    ]:
        errors.append("manifest milestone IDs/order do not exactly match the PRD")
    if [row.get("id") for row in manifest.get("epics", [])] != [
        row["id"] for row in parsed_epics
    ]:
        errors.append("manifest epic IDs/order do not exactly match the PRD backlog")
    if [row.get("id") for row in manifest.get("slices", [])] != [
        row["id"] for row in parsed_slices
    ]:
        errors.append("manifest slice IDs/order do not exactly match the PRD backlog")

    def comparable_path(row: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        return row.get("id"), row.get("journey_id"), row.get("kind"), row.get("source_text")

    if [comparable_path(row) for row in manifest.get("journey_paths", [])] != [comparable_path(row) for row in parsed_paths]:
        errors.append("manifest atomic normal/exception journey paths do not exactly match the PRD")

    program = manifest.get("program", {})
    if program.get("prd_sha256") != sha256_text(prd):
        errors.append("manifest PRD hash is stale")
    baseline = program.get("baseline", {})
    if baseline != {
        "requirement_count": EXPECTED_REQUIREMENTS,
        "family_count": EXPECTED_FAMILIES,
        "journey_count": EXPECTED_JOURNEYS,
    }:
        errors.append("manifest baseline counts were changed")

    collections = ("milestones", "epics", "slices", "requirements", "journeys", "journey_paths")
    all_rows: list[tuple[str, dict[str, Any]]] = []
    for collection in collections:
        rows = manifest.get(collection, [])
        ids = [row.get("id") for row in rows]
        duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate {collection} IDs: {duplicates}")
        all_rows.extend((collection, row) for row in rows)

    valid_requirements = set(requirement_ids)
    valid_journeys = set(journey_ids)
    valid_paths = {row.get("id") for row in manifest.get("journey_paths", [])}
    valid_epics = {row.get("id") for row in manifest.get("epics", [])}
    valid_slices = {row.get("id") for row in manifest.get("slices", [])}
    for collection, row in all_rows:
        row_id = row.get("id", "<missing>")
        if row.get("implementation_status") not in IMPLEMENTATION_STATUSES:
            errors.append(f"{collection}/{row_id}: invalid implementation_status")
        if row.get("verification_status") not in VERIFICATION_STATUSES:
            errors.append(f"{collection}/{row_id}: invalid verification_status")
        if row.get("release_status") not in RELEASE_STATUSES:
            errors.append(f"{collection}/{row_id}: invalid release_status")
        if row.get("acceptance_status") not in ACCEPTANCE_STATUSES:
            errors.append(f"{collection}/{row_id}: invalid acceptance_status")
        if row.get("implementation_status") == "not_started" and row.get("verification_status") != "not_run":
            errors.append(f"{collection}/{row_id}: not_started rows must have verification not_run")
        if row.get("release_status") == "deployment_verified" and not (
            row.get("implementation_status") == "implemented"
            and row.get("verification_status") == "passed"
        ):
            errors.append(
                f"{collection}/{row_id}: deployment_verified requires implemented and passed"
            )
        if row.get("release_status") == "not_required" or row.get("acceptance_status") == "not_required":
            approval = row.get("not_required_approval") or {}
            required = {"prd_citation", "reviewer", "reason", "date", "milestone"}
            if not required.issubset(approval):
                errors.append(f"{collection}/{row_id}: unapproved not_required status")
        for evidence_ref in row.get("evidence_refs", []):
            evidence_path = REPO_ROOT / evidence_ref
            if not evidence_path.is_file() or evidence_path.stat().st_size < 32:
                errors.append(f"{collection}/{row_id}: broken/empty evidence path {evidence_ref}")

    valid_milestones = {row.get("id") for row in manifest.get("milestones", [])}
    ownership_writers: dict[str, tuple[str, str]] = {}
    for row in manifest.get("slices", []):
        row_id = row["id"]
        if row.get("epic_id") not in valid_epics:
            errors.append(f"slice/{row_id}: unknown epic {row.get('epic_id')}")
        milestone_id = row.get("milestone_id")
        if milestone_id not in valid_milestones and milestone_id != "M7-M10":
            errors.append(f"slice/{row_id}: unknown milestone {milestone_id}")
        unknown_requirements = sorted(set(row.get("requirement_ids", [])) - valid_requirements)
        unknown_paths = sorted(set(row.get("journey_path_ids", [])) - valid_paths)
        if unknown_requirements:
            errors.append(f"slice/{row_id}: unknown requirements {unknown_requirements}")
        if unknown_paths:
            errors.append(f"slice/{row_id}: unknown journey paths {unknown_paths}")
        for owner in row.get("ownership", []):
            component = owner.get("component", "").lower()
            if owner.get("classification") not in {"NEW", "EXTEND", "LINK", "REPLACE"}:
                errors.append(f"slice/{row_id}: invalid ownership classification")
            for required_field in ("component", "canonical_writer", "compatibility_path", "retirement_gate"):
                if not owner.get(required_field):
                    errors.append(f"slice/{row_id}: ownership missing {required_field}")
            if component in FORBIDDEN_COMPONENTS and not owner.get("approved_adr"):
                errors.append(f"slice/{row_id}: forbidden duplicate component {component}")
            writer = owner.get("canonical_writer", "")
            prior = ownership_writers.get(component)
            if component and prior and prior[1] != writer:
                errors.append(
                    f"slice/{row_id}: conflicting canonical writers for {component}: "
                    f"{prior[0]} and {row_id}"
                )
            elif component:
                ownership_writers[component] = (row_id, writer)

    for row in manifest.get("requirements", []):
        unknown = sorted(set(row.get("journey_ids", [])) - valid_journeys)
        if unknown:
            errors.append(f"requirement/{row['id']}: unknown journeys {unknown}")
    for row in manifest.get("journeys", []):
        unknown = sorted(set(row.get("path_ids", [])) - valid_paths)
        if unknown:
            errors.append(f"journey/{row['id']}: unknown paths {unknown}")

    if program.get("active_slice") not in valid_slices:
        errors.append(f"program active_slice is unknown: {program.get('active_slice')}")

    for milestone in manifest.get("milestones", []):
        if compute_verified(milestone):
            incomplete = [
                row["id"]
                for row in manifest.get("slices", [])
                if row.get("milestone_id") == milestone["id"] and not compute_verified(row)
            ]
            if incomplete:
                errors.append(f"milestone/{milestone['id']}: closed with incomplete slices {incomplete}")

    for path, expected in render_views(manifest).items():
        if not path.is_file():
            errors.append(f"missing generated view {path.relative_to(REPO_ROOT)}")
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(f"stale or independently edited generated view {path.relative_to(REPO_ROOT)}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--force", action="store_true")
    subparsers.add_parser("generate")
    subparsers.add_parser("validate")
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        if MANIFEST_PATH.exists() and not args.force:
            raise SystemExit(f"Refusing to overwrite canonical manifest: {MANIFEST_PATH}")
        manifest = bootstrap_manifest()
        CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
        write_views(manifest)
        print(f"bootstrapped {MANIFEST_PATH.relative_to(REPO_ROOT)}")
        return 0

    manifest = load_manifest()
    if args.command == "generate":
        write_views(manifest)
        print(f"generated {len(render_views(manifest))} views")
        return 0

    errors = validate(manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "IP program manifest valid: "
        f"{len(manifest['requirements'])} requirements, "
        f"{len({row['family'] for row in manifest['requirements']})} families, "
        f"{len(manifest['journeys'])} journeys, "
        f"{len(manifest['journey_paths'])} atomic paths"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
