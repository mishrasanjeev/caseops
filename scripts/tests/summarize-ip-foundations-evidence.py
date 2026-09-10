"""Generate requirement-level handoff from unchanged manifest and retained results."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tarfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".tmp/ip-foundations-evidence"
MANIFEST = ROOT / "docs/ip-implementation/PROGRAM_MANIFEST.yaml"
DESTINATION = (
    ROOT
    / "docs/ip-implementation/evidence/ip-foundations-ops-requirements-2026-09-09.json"
)
SLICES = {
    "IPLF-027B",
    "IPLF-028A",
    "IPLF-028B",
    "IPLF-029A",
    "IPLF-029B",
    "IPLF-039G",
    "IPLF-039H",
    "IPLF-070A",
    "IPLF-070B",
    "IPLF-071A",
    "IPLF-071B",
    "IPLF-072A",
    "IPLF-072B",
    "IPLF-073A",
    "IPLF-073B",
}
ACCEPTED = {"holds-pg-03", "foundations-control-01"}
HOLD_SERVICE = "apps/api/src/caseops_api/services/legal_hold_workflow.py"
HOLD_TEST = "apps/api/tests/test_20260909_legal_hold_workflow.py"
PG_TEST = "apps/api/tests/test_20260909_legal_hold_postgres.py"
DISPOSITION = "apps/api/src/caseops_api/services/data_disposition.py"
OWNED_CODE = [
    "apps/api/alembic/versions/20260909_0003_legal_hold_release_requests.py",
    "apps/api/src/caseops_api/db/models.py",
    "apps/api/src/caseops_api/schemas/legal_holds.py",
    HOLD_SERVICE,
    "apps/api/src/caseops_api/api/routes/data_governance.py",
    "apps/api/src/caseops_api/services/data_governance.py",
    DISPOSITION,
    "apps/api/src/caseops_api/services/capability_catalog.py",
    "apps/api/src/caseops_api/services/capabilities.py",
    "apps/api/src/caseops_api/governance/generated_data_class_projection.py",
    "apps/web/lib/capabilities.ts",
    "apps/web/lib/capabilities.test.ts",
    "apps/web/lib/api/legal-holds.ts",
    "apps/web/lib/api/legal-holds.test.ts",
    "apps/web/lib/api/legal-holds.transport.test.ts",
    "apps/web/app/app/admin/data-governance/holds/page.tsx",
    "apps/web/app/app/admin/data-governance/holds/page.test.tsx",
    "apps/web/app/app/admin/data-governance/page.tsx",
    "apps/web/app/app/admin/page.tsx",
    HOLD_TEST,
    PG_TEST,
    "apps/api/tests/test_20260910_legal_hold_pagination.py",
    "apps/api/tests/test_20260909_legal_hold_migration.py",
    "apps/api/tests/test_datagov05_hold_step_up_and_dual_approval.py",
    "apps/api/tests/test_data_governance_service.py",
    "apps/api/tests/test_datagov04_hold_scope_resolver.py",
    "apps/api/tests/test_datagov17_integrity_scan.py",
    "tests/e2e/iplf-028b-legal-holds-2026-09-09.spec.ts",
    "playwright.ip-foundations.config.ts",
    "scripts/tests/run-ip-foundations-offline.sh",
    "scripts/tests/run-ip-foundations-web.sh",
    "scripts/tests/check-ip-foundations-web.sh",
    "scripts/tests/run-ip-foundations-browser.sh",
    "scripts/tests/Dockerfile.ip-foundations-browser",
    "scripts/tests/summarize-ip-foundations-evidence.py",
    "docs/ip-implementation/evidence/ip-foundations-ops-closure-2026-09-09.md",
    "docs/ip-implementation/evidence/ip-foundations-ops-resume-2026-09-10.md",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def journal(path: Path, accepted: set[str]) -> dict:
    records = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    collected = next(
        (row["nodeids"] for row in records if row["event"] == "collection"), []
    )
    finish = next(
        (row for row in reversed(records) if row["event"] == "session_finished"), None
    )
    reports = [row for row in records if row["event"] == "test_report"]
    inventory = []
    for node in collected:
        phases = {
            row["when"]: row["outcome"] for row in reports if row["nodeid"] == node
        }
        inventory.append({"nodeid": "apps/api/" + node, "phases": phases})
    complete = bool(collected and finish is not None)
    if path.stem in accepted:
        assert complete and finish["exitstatus"] == 0, (
            f"{path.name} has no successful completion"
        )
        assert len(collected) == len(set(collected))
        assert all(
            row["phases"] == {"setup": "passed", "call": "passed", "teardown": "passed"}
            for row in inventory
        ), f"{path.name} has incomplete or non-passing phases"
    return {
        "id": path.stem,
        "sha256": digest(path),
        "complete": complete,
        "exitstatus": finish["exitstatus"] if finish else None,
        "collected": len(collected),
        "call_results": dict(
            Counter(row["outcome"] for row in reports if row["when"] == "call")
        ),
        "failures": [
            row
            for row in records
            if row.get("outcome") == "failed" or row["event"] == "collection_failed"
        ],
        "source_archive": (
            path.with_name(path.stem + "-source.sha256").read_text().strip()
            if path.with_name(path.stem + "-source.sha256").exists()
            else None
        ),
        "tests": inventory,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--backend-run", action="append")
    parser.add_argument("--observed-backend-run", action="append", default=[])
    parser.add_argument("--web-run", default="holds-web-02")
    parser.add_argument("--output-name")
    parser.add_argument("--owned-manifest-name")
    parser.add_argument("--checkout-root", default=str(ROOT))
    parser.add_argument("--baseline-archive", type=Path)
    parser.add_argument("--browser-run")
    args = parser.parse_args()
    accepted = set(args.backend_run or ACCEPTED)
    destination = (
        DESTINATION.with_name("ip-foundations-ops-requirements-final-2026-09-09.json")
        if args.final
        else DESTINATION
    )
    if args.output_name:
        assert Path(args.output_name).name == args.output_name
        destination = DESTINATION.with_name(args.output_name)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in manifest["slices"] if row["id"] in SLICES}
    assert set(rows) == SLICES
    epics = {row["id"]: row for row in manifest["epics"]}
    requirements = {row["id"]: row for row in manifest["requirements"]}
    paths = {row["id"]: row for row in manifest["journey_paths"]}
    runs = [journal(path, accepted) for path in sorted(EVIDENCE.glob("*.jsonl"))]
    assert accepted <= {run["id"] for run in runs}
    observed = set(args.observed_backend_run) | accepted
    assert observed <= {run["id"] for run in runs}
    assert all(run["complete"] for run in runs if run["id"] in observed)
    passed = sorted(
        {
            test["nodeid"]
            for run in runs
            if run["id"] in observed
            for test in run["tests"]
            if test["phases"]
            == {"setup": "passed", "call": "passed", "teardown": "passed"}
        }
    )
    for run in runs:
        for failure in run["failures"]:
            failure["passing_replacement_runs"] = [
                replacement["id"]
                for replacement in runs
                if replacement["id"] in observed
                and replacement["id"] != run["id"]
                and any(
                    node["nodeid"] == "apps/api/" + failure["nodeid"]
                    and node["phases"]
                    == {"setup": "passed", "call": "passed", "teardown": "passed"}
                    for node in replacement["tests"]
                )
            ]

    def matches(refs: list[str]) -> list[str]:
        return [
            node
            for node in passed
            if any(
                node == ref or node.startswith(ref + "::") or node.startswith(ref + "[")
                for ref in refs
            )
        ]

    claims = {
        "DATA-GOV-04": {
            "scope": (
                "Company/data-class preservation commands and current "
                "private-disposition hold fence, with bounded indexed register/proposal pages."
            ),
            "code": [HOLD_SERVICE, DISPOSITION, OWNED_CODE[0]],
            "tests": [
                HOLD_TEST,
                PG_TEST,
                "apps/api/tests/test_20260910_legal_hold_pagination.py",
            ],
            "gap": (
                "Client/record/custodian/date scope, all current/future storage classes "
                "and full integrity propagation remain unimplemented."
            ),
        },
        "DATA-GOV-05": {
            "scope": (
                "Actual owner request and independent owner/admin approval, mandatory "
                "purpose-bound step-up, immutable fresh release evidence, corrected "
                "single-encoded browser commands; no deletion."
            ),
            "code": [HOLD_SERVICE],
            "tests": [HOLD_TEST, PG_TEST],
            "gap": (
                "Tenant-configured preparer/legal/data/executor approval policy, "
                "retention-policy activation and full post-release purge waiting/execution "
                "policy remain unavailable. Technical four-eyes enforcement is not "
                "certification of that policy."
            ),
        },
        "SEC-GOV-01": {
            "scope": (
                "Purpose-bound MFA on preservation commands only; "
                "no other security workflow activated."
            ),
            "code": [HOLD_SERVICE],
            "tests": [HOLD_TEST],
            "gap": (
                "All other named high-risk workflows and complete IPLF-073 acceptance "
                "remain outside this implementation."
            ),
        },
        "SEC-GOV-02": {
            "scope": "Independent current user identities for hold activation/release only.",
            "code": [HOLD_SERVICE],
            "tests": [HOLD_TEST, PG_TEST],
            "gap": (
                "Cross-programme preparer/legal/data/executor policies and "
                "emergency/access-review workflows remain incomplete."
            ),
        },
    }
    inventory = []
    for slice_id, row in sorted(rows.items()):
        epic = epics[row["epic_id"]]
        effective_ids = row["requirement_ids"] or epic["requirement_ids"]
        requirement_rows = []
        for requirement_id in effective_ids:
            requirement = requirements[requirement_id]
            claim = claims.get(requirement_id)
            requirement_rows.append(
                {
                    "id": requirement_id,
                    "source_text": requirement["text"],
                    "source_text_sha256": requirement["text_sha256"],
                    "track_outcome": "partial_shared_control_not_requirement_closure"
                    if claim
                    else "open_no_new_implementation_in_this_track",
                    "implemented_scope": claim["scope"] if claim else None,
                    "owned_implementation_refs": claim["code"] if claim else [],
                    "owned_passing_tests": matches(claim["tests"]) if claim else [],
                    "existing_manifest_tests_executed": matches(
                        requirement.get("test_refs", [])
                    ),
                    "remaining": claim["gap"]
                    if claim
                    else (
                        "Not closed. Existing manifest references are not independently "
                        "certified by this track; full requirement implementation and "
                        "acceptance remain required."
                    ),
                    "manifest_implementation_refs_not_new_work": requirement.get(
                        "implementation_refs", []
                    ),
                }
            )
        journey_ids = row["journey_path_ids"] or sorted(
            path_id
            for path_id, path in paths.items()
            if path["journey_id"] in epic["journey_ids"]
        )
        inventory.append(
            {
                "id": slice_id,
                "title": row["title"],
                "manifest_implementation_status": row["implementation_status"],
                "requirements_source": "slice"
                if row["requirement_ids"]
                else "parent_epic",
                "requirements": requirement_rows,
                "journeys": [
                    {
                        "id": path_id,
                        "source_text": paths[path_id]["source_text"],
                        "track_outcome": "open_not_end_to_end_verified",
                        "existing_manifest_tests_executed": matches(
                            paths[path_id].get("test_refs", [])
                        ),
                    }
                    for path_id in journey_ids
                ],
                "original_blockers": row.get("blockers", []),
            }
        )
    web_path = EVIDENCE / f"{args.web_run}.xml"
    web_cases = ET.parse(web_path).findall(".//testcase")
    assert web_cases and all(
        case.find("failure") is None
        and case.find("error") is None
        and case.find("skipped") is None
        for case in web_cases
    )
    result = {
        "track": "ip-foundations-ops",
        "base_revision": "5145fb3a4b51b26af116220ff10a7389bde6324d",
        "manifest_sha256": digest(MANIFEST),
        "status": "partial_not_release_certified",
        "assigned_slice_count": len(inventory),
        "unique_requirement_count": len(
            {r["id"] for row in inventory for r in row["requirements"]}
        ),
        "assigned_slices": inventory,
        "backend_runs": runs,
        "accepted_backend_runs": sorted(accepted),
        "observed_backend_runs_not_necessarily_green": sorted(observed - accepted),
        "web": {
            "source": web_path.name,
            "sha256": digest(web_path),
            "passed": len(web_cases),
            "tests": [
                {"name": case.get("name"), "classname": case.get("classname")}
                for case in web_cases
            ],
        },
        "browser": {
            "collected": 1,
            "executed": 0,
            "proof": "holds-playwright-collection.txt",
            "gap": (
                "Dated live browser journey and responsive screenshots "
                "are not executed candidate proof."
            ),
        },
        "deployment": "not_run_parent_owned",
    }
    if args.final:
        result["source_files"] = [
            {"path": path, "sha256": digest(ROOT / path)} for path in OWNED_CODE
        ]
        model_source = (
            (ROOT / "apps/api/src/caseops_api/db/models.py").read_bytes().decode()
        )
        model_class = next(
            node
            for node in ast.parse(model_source).body
            if isinstance(node, ast.ClassDef) and node.name == "LegalHoldReleaseRequest"
        )
        model_hunk = "".join(
            model_source.splitlines(keepends=True)[
                model_class.lineno - 1 : model_class.end_lineno
            ]
        )
        result["shared_model_hunk"] = {
            "only_owned_class": model_class.name,
            "start_line": model_class.lineno,
            "end_line": model_class.end_lineno,
            "sha256": hashlib.sha256(model_hunk.encode()).hexdigest(),
            "source": model_hunk,
        }
        result["additional_shared_model_change"] = {
            "class": "LegalHold",
            "add_index": [
                "ix_legal_holds_register_page",
                "company_id",
                "created_at",
                "id",
            ],
        }
        result["integration_warning"] = (
            "Full-file hashes identify the frozen source, not wholesale overwrite authority. "
            "Apply only owned hunks listed in the companion handoff. Regenerate the aggregate "
            "data-class projection and OpenAPI; do not copy shared models or ledgers."
        )
    if args.browser_run:
        browser_path = EVIDENCE / f"{args.browser_run}.json"
        browser_report = json.loads(browser_path.read_text())
        result["browser"] = {
            "source": browser_path.name,
            "sha256": digest(browser_path),
            "stats": browser_report["stats"],
            "errors": browser_report["errors"],
            "suites": browser_report["suites"],
            "gap": "Local synthetic journey only; no integrated or deployed release proof.",
        }
    if args.owned_manifest_name:
        assert (
            args.final
            and Path(args.owned_manifest_name).name == args.owned_manifest_name
        )
        shared = {
            "apps/api/src/caseops_api/db/models.py": "Owned model class and LegalHold index below only.",
            "apps/api/src/caseops_api/api/routes/data_governance.py": (
                "Hold DTO/service imports, LegalHoldOperator and six preservation routes; "
                "preserve diagnostic routes."
            ),
            "apps/api/src/caseops_api/services/data_governance.py": (
                "activate_legal_hold/release_legal_hold delegates; remove obsolete "
                "_as_utc/_require_distinct_approver and unused require_step_up_always import."
            ),
            "apps/api/src/caseops_api/services/data_disposition.py": "Company import and tenant-first lock/reload in _approved_private_operation only.",
            "apps/api/src/caseops_api/services/capability_catalog.py": "legal_holds:manage owner/admin capability only.",
            "apps/api/src/caseops_api/services/capabilities.py": "legal_holds:manage exclusion from custom-role delegation only.",
            "apps/web/lib/capabilities.ts": "legal_holds:manage union/GOVERNANCE entry only.",
            "apps/web/lib/capabilities.test.ts": "Preservation-review role parity and owner-only audit-export regression only.",
            "apps/web/app/app/admin/page.tsx": "legal_holds:manage capability read and matching Legal holds link only.",
            "apps/web/app/app/admin/data-governance/page.tsx": "Legal holds link after PageHeader only.",
            "apps/api/tests/test_data_governance_service.py": "Summary fixture adds scoped rows while draft, then activates; retain assertions.",
            "apps/api/tests/test_datagov04_hold_scope_resolver.py": "Scoped fixtures use draft -> scoped -> active; retain coverage/isolation assertions.",
            "apps/api/tests/test_datagov17_integrity_scan.py": "Fixtures use draft -> scoped -> active -> released; preserve missing-map failure.",
        }
        files = []
        for source in result["source_files"]:
            path = source["path"]
            projection = path.endswith("generated_data_class_projection.py")
            files.append(
                {
                    **source,
                    "bytes": (ROOT / path).stat().st_size,
                    "integration_mode": "regenerate_from_integrated_source"
                    if projection
                    else "merge_owned_hunks"
                    if path in shared
                    else "owned_file",
                    "owned_scope": shared.get(
                        path,
                        "Regenerate, do not copy."
                        if projection
                        else "Entire file from this preservation track.",
                    ),
                }
            )
        owned = {
            "source_root": args.checkout_root,
            "base_revision": result["base_revision"],
            "not_whole_worktree_copy_authority": True,
            "files": files,
            "shared_model_hunk": result["shared_model_hunk"],
            "additional_shared_model_change": result["additional_shared_model_change"],
            "shared_event_catalog_owner": "summary agent; parent integrates",
            "migration_reservation": "20260909_0003; parent linearizes predecessor",
        }
        if args.baseline_archive:
            comparison = {
                "unchanged_unowned_files": 0,
                "changed_unowned_files": [],
                "baseline_sha256": digest(args.baseline_archive),
                "owned_resume_changes": [],
            }
            with tarfile.open(args.baseline_archive) as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    name = member.name.removeprefix("./")
                    if any(
                        part in {"__pycache__", ".ruff_cache", ".pytest_cache"}
                        for part in Path(name).parts
                    ):
                        continue
                    previous = archive.extractfile(member).read()
                    previous_hash = hashlib.sha256(previous).hexdigest()
                    path = ROOT / name
                    current_hash = digest(path) if path.exists() else None
                    if name in OWNED_CODE:
                        if current_hash != previous_hash:
                            comparison["owned_resume_changes"].append(
                                {
                                    "path": name,
                                    "before_sha256": previous_hash,
                                    "after_sha256": current_hash,
                                }
                            )
                        if name == "apps/api/src/caseops_api/db/models.py":

                            def exclude_owned_model_changes(source):
                                source = source.decode().replace("\r\n", "\n")
                                node = next(
                                    node
                                    for node in ast.parse(source).body
                                    if isinstance(node, ast.ClassDef)
                                    and node.name == "LegalHoldReleaseRequest"
                                )
                                lines = source.splitlines(keepends=True)
                                del lines[node.lineno - 1 : node.end_lineno]
                                return "".join(
                                    line
                                    for line in lines
                                    if 'Index("ix_legal_holds_register_page"'
                                    not in line
                                )

                            assert exclude_owned_model_changes(
                                previous
                            ) == exclude_owned_model_changes(path.read_bytes()), (
                                "Unowned model regions changed"
                            )
                            comparison["unowned_model_regions_unchanged"] = True
                    elif current_hash == previous_hash:
                        comparison["unchanged_unowned_files"] += 1
                    else:
                        comparison["changed_unowned_files"].append(name)
            assert not comparison["changed_unowned_files"], comparison[
                "changed_unowned_files"
            ]
            owned["resume_preservation_check"] = comparison
        target = DESTINATION.with_name(args.owned_manifest_name)
        with target.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(owned, indent=2, ensure_ascii=True) + "\n")
    content = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if destination.exists():
        assert destination.read_text() == content, (
            "Never overwrite a different retained evidence report"
        )
    else:
        destination.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "slices": len(inventory),
                "requirements": result["unique_requirement_count"],
                "backend_runs": len(runs),
                "report": str(destination),
            }
        )
    )


if __name__ == "__main__":
    main()
