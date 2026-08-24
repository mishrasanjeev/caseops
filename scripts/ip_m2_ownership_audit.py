#!/usr/bin/env python3
"""Validate and render the M2 one-writer reconciliation audit.

This repository control makes the M2 exit condition reviewable without
pretending that a file reference proves a production run.
It requires every implemented/in-progress M2 slice to retain a canonical-writer
contract, executable repository test references, and an evidence artifact.  A
blocked active slice must name its blocker.  Deployment-verified rows must
retain their dated evidence artifact.  The control neither changes application
state nor authorizes an external operation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "ip-implementation" / "PROGRAM_MANIFEST.yaml"
GENERATED_VIEW_PATH = (
    REPO_ROOT / "docs" / "ip-implementation" / "generated" / "M2_OWNERSHIP_AUDIT.md"
)
MILESTONE_ID = "M2"
ACTIVE_IMPLEMENTATION_STATUSES = {"implemented", "in_progress"}
DEPLOYMENT_VERIFIED_STATUS = "deployment_verified"
REFERENCE_PATH = re.compile(
    r"(?:^|[^A-Za-z0-9_.-])"
    r"((?:apps|docs|infra|scripts|tests|\.github)/"
    r"[A-Za-z0-9_./\-\[\]]+\.(?:md|py|ps1|sh|tsx|ts|yaml|yml|json))"
)
ROOT_REFERENCE_ALLOWLIST = frozenset(
    {
        "playwright.app.config.ts",
        "playwright.config.ts",
        "playwright.ip-a0-prod.config.ts",
    }
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reference_path(reference: object) -> Path | None:
    """Extract a checked-in path from a manifest reference or command string."""

    if not _non_empty(reference):
        return None
    raw_reference = str(reference).strip()
    direct_path = raw_reference.split("::", maxsplit=1)[0]
    if direct_path in ROOT_REFERENCE_ALLOWLIST:
        candidate = REPO_ROOT / direct_path
        if candidate.is_file():
            return candidate
    if direct_path.startswith(("apps/", "docs/", "infra/", "scripts/", "tests/", ".github/")):
        candidate = REPO_ROOT / direct_path
        if candidate.is_file():
            return candidate
    match = REFERENCE_PATH.search(raw_reference)
    if not match:
        return None
    return REPO_ROOT / match.group(1)


def _existing_reference(reference: object) -> bool:
    path = _reference_path(reference)
    return path is not None and path.is_file()


def _display_path(path: Path) -> str:
    """Return a repository-relative path when possible for clear CI errors."""

    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _m2_slices(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    slices = manifest.get("slices", [])
    if not isinstance(slices, list):
        return []
    rows = [
        row
        for row in slices
        if isinstance(row, Mapping) and row.get("milestone_id") == MILESTONE_ID
    ]
    return sorted(rows, key=lambda row: str(row.get("id", "")))


def _ownership_errors(slice_id: str, ownership: object) -> list[str]:
    if not isinstance(ownership, Sequence) or isinstance(ownership, (str, bytes)) or not ownership:
        return [f"{slice_id}: requires at least one canonical-writer ownership record"]
    errors: list[str] = []
    for index, record in enumerate(ownership):
        if not isinstance(record, Mapping):
            errors.append(f"{slice_id}: ownership record {index} must be an object")
            continue
        for field in ("canonical_writer", "compatibility_path", "retirement_gate"):
            if not _non_empty(record.get(field)):
                errors.append(f"{slice_id}: ownership record {index} lacks {field}")
    return errors


def _active_slice_errors(row: Mapping[str, Any]) -> list[str]:
    slice_id = str(row.get("id", "<missing>"))
    errors = _ownership_errors(slice_id, row.get("ownership"))
    implementation_refs = _as_list(row.get("implementation_refs"))
    if not implementation_refs:
        errors.append(f"{slice_id}: active implementation requires implementation_refs")
    elif any(not _existing_reference(reference) for reference in implementation_refs):
        errors.append(f"{slice_id}: implementation_refs must resolve to checked-in files")

    test_refs = _as_list(row.get("test_refs"))
    if not test_refs:
        errors.append(f"{slice_id}: active implementation requires canonical-writer test_refs")
    elif any(
        str(reference).startswith("planned:") or not _existing_reference(reference)
        for reference in test_refs
    ):
        errors.append(
            f"{slice_id}: active implementation must not use planned or missing "
            "canonical-writer test_refs"
        )

    evidence_refs = _as_list(row.get("evidence_refs"))
    if not evidence_refs:
        errors.append(f"{slice_id}: active implementation requires a dated evidence artifact")
    elif any(not _existing_reference(reference) for reference in evidence_refs):
        errors.append(f"{slice_id}: evidence_refs must resolve to checked-in files")

    release_status = row.get("release_status")
    if release_status == "blocked" and not _as_list(row.get("blockers")):
        errors.append(f"{slice_id}: active blocked slice requires an explicit blocker")
    if release_status == DEPLOYMENT_VERIFIED_STATUS and not evidence_refs:
        errors.append(f"{slice_id}: deployment_verified requires a production evidence artifact")
    return errors


def validate(
    manifest: dict[str, Any] | None = None, *, check_generated_view: bool = True
) -> list[str]:
    """Return every M2 audit failure without changing program state."""

    if manifest is None:
        manifest = _load(MANIFEST_PATH)
    errors: list[str] = []
    rows = _m2_slices(manifest)
    if not rows:
        return ["M2 ownership audit requires at least one M2 slice"]
    identifiers = [str(row.get("id", "")) for row in rows]
    if len(set(identifiers)) != len(identifiers):
        errors.append("M2 ownership audit found duplicate slice identifiers")
    for row in rows:
        slice_id = str(row.get("id", "<missing>"))
        if not _non_empty(slice_id):
            errors.append("M2 ownership audit found a slice without an id")
            continue
        status = row.get("implementation_status")
        if status in ACTIVE_IMPLEMENTATION_STATUSES:
            errors.extend(_active_slice_errors(row))
        elif status == "not_started":
            errors.extend(_ownership_errors(slice_id, row.get("ownership")))
            if any(
                _as_list(row.get(field))
                for field in (
                    "implementation_refs",
                    "evidence_refs",
                    "evidence_metadata",
                )
            ):
                errors.append(
                    f"{slice_id}: not_started slice carries implementation or evidence records"
                )
        else:
            errors.append(f"{slice_id}: unknown implementation_status {status!r}")
    if check_generated_view and not errors:
        expected = _render_markdown(manifest)
        if not GENERATED_VIEW_PATH.is_file():
            errors.append(
                f"missing generated M2 ownership audit {_display_path(GENERATED_VIEW_PATH)}"
            )
        elif GENERATED_VIEW_PATH.read_text(encoding="utf-8") != expected:
            errors.append(
                "stale or independently edited generated M2 ownership audit "
                f"{_display_path(GENERATED_VIEW_PATH)}"
            )
    return errors


def _row_state(row: Mapping[str, Any]) -> str:
    implementation_status = str(row.get("implementation_status", ""))
    release_status = str(row.get("release_status", ""))
    if release_status == DEPLOYMENT_VERIFIED_STATUS:
        return "deployment-evidence-recorded"
    if implementation_status in ACTIVE_IMPLEMENTATION_STATUSES:
        if release_status == "blocked":
            return "repository-evidence-recorded-release-blocked"
        return "repository-evidence-recorded"
    return "not-started-or-planned"


def _render_markdown(manifest: Mapping[str, Any]) -> str:
    """Build the checked-in audit projection without mutating the repository."""

    rows = _m2_slices(manifest)
    lines = [
        "# M2 One-Writer Reconciliation Audit",
        "",
        "Generated from `PROGRAM_MANIFEST.yaml`; do not edit this view directly.",
        "",
        "## Boundary",
        "",
        "This is a repository Definition-of-Ready control. It validates required",
        "canonical-writer, test, and evidence references.",
        "run a production operation, or convert a blocked slice into",
        "a released capability.",
        "",
        "## M2 slice inventory",
        "",
        "| Slice | Implementation | Release | Audit state | Tests | Evidence | Blockers |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            (
                "| `{id}` | `{implementation}` | `{release}` | `{state}` | "
                "{tests} | {evidence} | {blockers} |"
            ).format(
                id=row["id"],
                implementation=row["implementation_status"],
                release=row["release_status"],
                state=_row_state(row),
                tests=len(_as_list(row.get("test_refs"))),
                evidence=len(_as_list(row.get("evidence_refs"))),
                blockers=len(_as_list(row.get("blockers"))),
            )
        )
    lines.extend(
        [
            "",
            "## Release interpretation",
            "",
            "`deployment-evidence-recorded` means only that the canonical manifest",
            "contains checked-in evidence for a `deployment_verified` slice. It is not",
            "a substitute for its specified production journey,",
            "or any still-open external gate. `repository-evidence-recorded-release-blocked`",
            "deliberately preserves the active blocker.",
            "",
        ]
    )
    return "\n".join(lines)


def render(manifest: dict[str, Any] | None = None) -> Path:
    """Render the auditable M2 inventory; the program manifest remains canonical."""

    if manifest is None:
        manifest = _load(MANIFEST_PATH)
    errors = validate(manifest, check_generated_view=False)
    if errors:
        raise ValueError("cannot render invalid M2 ownership audit: " + "; ".join(errors))
    GENERATED_VIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_VIEW_PATH.write_text(_render_markdown(manifest), encoding="utf-8")
    return GENERATED_VIEW_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "render"), nargs="?", default="validate")
    args = parser.parse_args(argv)
    if args.command == "render":
        try:
            print(f"rendered {render()}")
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return 0
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"M2 ownership audit valid: {len(_m2_slices(_load(MANIFEST_PATH)))} M2 slices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
