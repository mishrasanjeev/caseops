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
