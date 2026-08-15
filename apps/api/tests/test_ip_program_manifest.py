from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_program_manifest.py"
SPEC = importlib.util.spec_from_file_location("ip_program_manifest", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_program_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_program_manifest)


def _manifest() -> dict:
    return copy.deepcopy(ip_program_manifest.load_manifest())


def test_committed_ip_program_manifest_is_structurally_valid() -> None:
    assert ip_program_manifest.validate(_manifest()) == []


def test_validator_rejects_missing_duplicate_requirement_and_exception_rows() -> None:
    manifest = _manifest()
    manifest["requirements"].append(copy.deepcopy(manifest["requirements"][0]))
    manifest["journey_paths"].pop()

    errors = ip_program_manifest.validate(manifest)

    assert any("duplicate manifest requirement IDs" in error for error in errors)
    assert any("atomic normal/exception journey paths" in error for error in errors)


def test_validator_rejects_unapproved_not_required_and_forbidden_owner() -> None:
    manifest = _manifest()
    active = next(row for row in manifest["slices"] if row["id"] == "IPLF-001A")
    active["release_status"] = "not_required"
    active.pop("not_required_approval", None)
    active["ownership"].append(
        {
            "classification": "NEW",
            "component": "ip_tasks",
            "canonical_writer": "services/ip/tasks.py",
        }
    )
    next_slice = next(row for row in manifest["slices"] if row["id"] == "IPLF-001B")
    next_slice["ownership"].append(
        {
            "classification": "EXTEND",
            "component": "Cloud Scheduler and Cloud Run Job deployment control",
            "canonical_writer": "an overlapping second writer",
            "compatibility_path": "none",
            "retirement_gate": "none",
        }
    )

    errors = ip_program_manifest.validate(manifest)

    assert any("unapproved not_required status" in error for error in errors)
    assert any("forbidden duplicate component ip_tasks" in error for error in errors)
    assert any("conflicting canonical writers" in error for error in errors)


def test_validator_rejects_broken_evidence_and_closed_incomplete_milestone() -> None:
    manifest = _manifest()
    active = next(row for row in manifest["slices"] if row["id"] == "IPLF-001A")
    active["evidence_refs"] = ["docs/ip-implementation/evidence/does-not-exist.md"]

    milestone = next(row for row in manifest["milestones"] if row["id"] == "M1")
    milestone.update(
        {
            "implementation_status": "implemented",
            "verification_status": "passed",
            "release_status": "deployment_verified",
            "acceptance_status": "approved",
            "blockers": [],
            "evidence_refs": [
                "docs/ip-implementation/evidence/m1/IPLF-001A/audit-2026-08-01.md"
            ],
        }
    )

    errors = ip_program_manifest.validate(manifest)

    assert any("broken/empty evidence path" in error for error in errors)
    assert any("closed with incomplete slices" in error for error in errors)


def test_validator_rejects_orphan_and_nonreciprocal_coverage() -> None:
    manifest = _manifest()
    requirement = manifest["requirements"][0]
    requirement["slice_ids"] = []
    path = manifest["journey_paths"][0]
    owner = path["slice_ids"][0]
    slice_row = next(row for row in manifest["slices"] if row["id"] == owner)
    slice_row["journey_path_ids"].remove(path["id"])
    path["test_refs"] = []

    errors = ip_program_manifest.validate(manifest)

    assert any("orphan requirement has no slice" in error for error in errors)
    assert any("reverse mapping missing" in error for error in errors)
    assert any("stable test ID is not referenced" in error for error in errors)


def test_validator_rejects_bad_derived_slice_and_empty_unapproved_coverage() -> None:
    manifest = _manifest()
    derived = next(row for row in manifest["slices"] if row["source_kind"] == "derived")
    derived["scope_source"] = "IPLF-999"
    derived["ownership"] = []
    derived["requirement_ids"] = []
    derived["journey_path_ids"] = []
    derived.pop("administrative_exception", None)

    errors = ip_program_manifest.validate(manifest)

    assert any("derived scope_source must equal parent epic" in error for error in errors)
    assert any("missing ownership decision" in error for error in errors)
    assert any(
        "empty coverage lacks approved administrative exception" in error
        for error in errors
    )


def test_validator_rejects_status_drift_stale_blocker_and_completed_active_slice() -> None:
    manifest = _manifest()
    requirement = manifest["requirements"][0]
    requirement["implementation_status"] = "not_started"
    active = next(
        row
        for row in manifest["slices"]
        if row["id"] == manifest["program"]["active_slice"]
    )
    active.update(
        {
            "implementation_status": "implemented",
            "verification_status": "passed",
            "release_status": "deployment_verified",
            "acceptance_status": "approved",
            "implementation_refs": ["scripts/ip_program_manifest.py"],
            "test_refs": ["apps/api/tests/test_ip_program_manifest.py"],
            "evidence_refs": [
                "docs/ip-implementation/evidence/m1/IPLF-001A/audit-2026-08-01.md"
            ],
            "evidence_metadata": [],
            "blockers": [
                {
                    "id": "RESOLVED",
                    "summary": "Resolved by current production evidence.",
                }
            ],
        }
    )

    errors = ip_program_manifest.validate(manifest)

    assert any("must be derived" in error for error in errors)
    assert any("stale resolved blocker" in error for error in errors)
    assert any("lacks evidence_metadata" in error for error in errors)
    assert any("active_slice is already implemented" in error for error in errors)


def test_validator_rejects_missing_epic_decomposition_and_changed_prd_slice() -> None:
    manifest = _manifest()
    explicit = next(row for row in manifest["slices"] if row["source_kind"] == "prd_explicit")
    explicit["title"] = "Changed scope"
    epic = manifest["epics"][0]
    epic["slice_ids"] = []

    errors = ip_program_manifest.validate(manifest)

    assert any("changed PRD-explicit title" in error for error in errors)
    assert any("slice_ids are not reciprocal" in error for error in errors)


def test_validator_rejects_passed_row_citing_unwritten_planned_test() -> None:
    """A `planned:` reference names a test that does not exist yet.

    It is legitimate on an unverified row, but it can never be evidence for a
    passed or deployment-verified claim. Before this rule, 80 rows claimed
    passed/deployment_verified while citing only planned placeholders.
    """

    manifest = _manifest()
    row = next(
        item for item in manifest["slices"] if item["verification_status"] == "passed"
    )
    row["test_refs"] = [*row.get("test_refs", []), "planned:IPLF-UJ-99-NORMAL"]

    errors = ip_program_manifest.validate(manifest)

    assert any(
        "passed/deployment_verified row cites unwritten tests" in error
        for error in errors
    )


def test_validator_allows_planned_test_reference_on_an_unverified_row() -> None:
    """The rule must not punish honest work in progress."""

    manifest = _manifest()
    row = next(
        item
        for item in manifest["slices"]
        if item["verification_status"] == "not_run"
        and item["release_status"] != "deployment_verified"
    )
    row["test_refs"] = [*row.get("test_refs", []), "planned:IPLF-UJ-99-NORMAL"]

    errors = ip_program_manifest.validate(manifest)

    assert not any(
        "cites unwritten tests" in error and row["id"] in error for error in errors
    )
