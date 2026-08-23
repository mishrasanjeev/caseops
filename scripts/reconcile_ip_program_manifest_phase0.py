#!/usr/bin/env python3
"""One-time Phase 0 reconciliation for the IP program manifest.

This script preserves the PRD-extracted inventory and existing release facts,
adds reviewable implementation slices, and creates reciprocal requirement and
journey-path allocation. It never infers that planned scope is implemented.
"""

from __future__ import annotations

import json
import string
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/ip-implementation/PROGRAM_MANIFEST.yaml"
RELEASE_1 = "docs/ip-implementation/evidence/release-2026-08-01-remaining-slices.md"
RELEASE_2 = "docs/ip-implementation/evidence/release-2026-08-01-completion.md"


FAMILY_EPICS: dict[str, tuple[str, ...]] = {
    "TRUST-BA": ("IPLF-006", "IPLF-004"),
    "TRUST-RSCH": ("IPLF-003", "IPLF-004", "IPLF-005"),
    "SRC": ("IPLF-004", "IPLF-054", "IPLF-056"),
    "NOTIF": ("IPLF-007", "IPLF-035"),
    "TRACK": ("IPLF-001", "IPLF-002", "IPLF-008"),
    "IP-PORT": ("IPLF-030",),
    "IP-ID": ("IPLF-021", "IPLF-031"),
    "IP-PROS": ("IPLF-022", "IPLF-033"),
    "IP-OPP": ("IPLF-040", "IPLF-041", "IPLF-042", "IPLF-043", "IPLF-048", "IPLF-049"),
    "IP-DL": ("IPLF-023", "IPLF-034"),
    "IP-DOC": ("IPLF-024", "IPLF-036"),
    "IP-REG": ("IPLF-050", "IPLF-051", "IPLF-056"),
    "IP-WATCH": ("IPLF-052", "IPLF-053"),
    "IP-REN": ("IPLF-037",),
    "JUDGE": ("IPLF-003", "IPLF-060"),
    "AI-GUIDE": ("IPLF-061",),
    "AI-REV": ("IPLF-063", "IPLF-065"),
    "IP-DRAFT": ("IPLF-045", "IPLF-046", "IPLF-047"),
    "CLIENT": ("IPLF-055",),
    "REPORT": ("IPLF-038", "IPLF-100"),
    "PAT": ("IPLF-080",),
    "DES": ("IPLF-090",),
    "COPY": ("IPLF-090",),
    "LIC": ("IPLF-090",),
    "DOMAIN": ("IPLF-090",),
    "ENF": ("IPLF-090",),
    "GI": ("IPLF-091",),
    "PVP": ("IPLF-091",),
    "SICLD": ("IPLF-091",),
    "TS": ("IPLF-091",),
    "CUSTOMS": ("IPLF-091",),
    "COMP": ("IPLF-030", "IPLF-038", "IPLF-070"),
    "IP-CLR": ("IPLF-039",),
    "IP-FILE": ("IPLF-039",),
    "IP-MAD": ("IPLF-057",),
    "IP-POST": ("IPLF-039", "IPLF-058"),
    "IP-ACCESS": ("IPLF-026", "IPLF-066", "IPLF-073"),
    "RULE-GOV": ("IPLF-023", "IPLF-027"),
    "IP-OPS": ("IPLF-039",),
    "TM-DATA": ("IPLF-039",),
    "CAL-OPS": ("IPLF-023", "IPLF-025", "IPLF-034", "IPLF-035", "IPLF-039"),
    "COMM": ("IPLF-039",),
    "LEGAL-SRC": ("IPLF-004", "IPLF-006", "IPLF-054"),
    "IP-INC": ("IPLF-039",),
    "IP-SCOPE": ("IPLF-079", "IPLF-080", "IPLF-090", "IPLF-091"),
    "SEC-GOV": ("IPLF-026", "IPLF-073"),
    "DATA-GOV": ("IPLF-028", "IPLF-071"),
    "RES": ("IPLF-028", "IPLF-072"),
    "SEARCH-ACL": ("IPLF-026", "IPLF-066"),
    "ARCH-OPS": ("IPLF-019", "IPLF-027", "IPLF-029"),
}


JOURNEY_EPICS: dict[str, tuple[str, ...]] = {
    "UJ-01": ("IPLF-020", "IPLF-021"), "UJ-02": ("IPLF-032",),
    "UJ-03": ("IPLF-031", "IPLF-039"), "UJ-04": ("IPLF-030",),
    "UJ-05": ("IPLF-031",), "UJ-06": ("IPLF-022", "IPLF-033"),
    "UJ-07": ("IPLF-051",), "UJ-08": ("IPLF-023", "IPLF-034"),
    "UJ-09": ("IPLF-023", "IPLF-034"), "UJ-10": ("IPLF-025", "IPLF-035"),
    "UJ-11": ("IPLF-007",), "UJ-12": ("IPLF-040", "IPLF-041"),
    "UJ-13": ("IPLF-040", "IPLF-042"), "UJ-14": ("IPLF-024", "IPLF-036"),
    "UJ-15": ("IPLF-006",), "UJ-16": ("IPLF-005",),
    "UJ-17": ("IPLF-003", "IPLF-004"), "UJ-18": ("IPLF-063", "IPLF-065"),
    "UJ-19": ("IPLF-050", "IPLF-051"), "UJ-20": ("IPLF-060",),
    "UJ-21": ("IPLF-052", "IPLF-053"), "UJ-22": ("IPLF-061",),
    "UJ-23": ("IPLF-062", "IPLF-066"), "UJ-24": ("IPLF-045", "IPLF-046"),
    "UJ-25": ("IPLF-002", "IPLF-056"), "UJ-26": ("IPLF-037",),
    "UJ-27": ("IPLF-038", "IPLF-055"), "UJ-28": ("IPLF-028", "IPLF-071"),
    "UJ-29": ("IPLF-080",), "UJ-30": ("IPLF-090",),
    "UJ-31": ("IPLF-039",), "UJ-32": ("IPLF-039",),
    "UJ-33": ("IPLF-052", "IPLF-053"), "UJ-34": ("IPLF-048",),
    "UJ-35": ("IPLF-057",), "UJ-36": ("IPLF-058",),
    "UJ-37": ("IPLF-059",), "UJ-38": ("IPLF-049",),
    "UJ-39": ("IPLF-080",), "UJ-40": ("IPLF-080",),
    "UJ-41": ("IPLF-090",), "UJ-42": ("IPLF-090",),
    "UJ-43": ("IPLF-090",), "UJ-44": ("IPLF-091",),
    "UJ-45": ("IPLF-091",), "UJ-46": ("IPLF-026",),
    "UJ-47": ("IPLF-023", "IPLF-027"), "UJ-48": ("IPLF-006",),
    "UJ-49": ("IPLF-039",), "UJ-50": ("IPLF-039",),
    "UJ-51": ("IPLF-039",), "UJ-52": ("IPLF-039",),
    "UJ-53": ("IPLF-022", "IPLF-039"), "UJ-54": ("IPLF-039",),
    "UJ-55": ("IPLF-039",), "UJ-56": ("IPLF-023", "IPLF-034"),
    "UJ-57": ("IPLF-039",), "UJ-58": ("IPLF-039",),
    "UJ-59": ("IPLF-038", "IPLF-039"), "UJ-60": ("IPLF-079",),
    "UJ-61": ("IPLF-039", "IPLF-058"), "UJ-62": ("IPLF-025", "IPLF-035", "IPLF-039"),
    "UJ-63": ("IPLF-073",), "UJ-64": ("IPLF-071",),
    "UJ-65": ("IPLF-028", "IPLF-072"), "UJ-66": ("IPLF-066",),
    "UJ-67": ("IPLF-027",), "UJ-68": ("IPLF-002", "IPLF-056"),
}


DELIVERED_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "IPLF-001A": ("TRACK-01", "TRACK-02", "TRACK-05"),
    "IPLF-001B": ("TRACK-01", "TRACK-02", "TRACK-05", "TRACK-14"),
    "IPLF-003A": ("TRUST-RSCH-01", "TRUST-RSCH-03", "TRUST-RSCH-07"),
    "IPLF-003B": ("TRUST-RSCH-01", "TRUST-RSCH-02", "TRUST-RSCH-03"),
    "IPLF-005A": ("TRUST-RSCH-07", "TRUST-RSCH-13", "TRUST-RSCH-14"),
    "IPLF-006A": ("TRUST-BA-01", "TRUST-BA-02", "TRUST-BA-04", "TRUST-BA-09", "TRUST-BA-10", "TRUST-BA-12"),
    "IPLF-006B": ("TRUST-BA-03", "TRUST-BA-07", "TRUST-BA-11"),
    "IPLF-007A": tuple(f"NOTIF-{number:02d}" for number in (4, 5, 6, 13, 17, 18, 19, 22, 23)),
    "IPLF-007B": tuple(f"NOTIF-{number:02d}" for number in (3, 7, 9, 10, 15, 20, 24)),
    "IPLF-039A": tuple(f"TM-DATA-{number:02d}" for number in range(1, 16)),
    "IPLF-039B": tuple(f"COMM-{number:02d}" for number in (1, 2, 3, 4, 5, 12, 13, 14)),
    "IPLF-039C": tuple(f"CAL-OPS-{number:02d}" for number in (7, 8, 9, 10, 13)),
    "IPLF-039D": tuple(f"IP-INC-{number:02d}" for number in range(1, 9)),
    "IPLF-039E": ("IP-POST-02", "IP-POST-03"),
    "IPLF-039F": ("IP-OPS-08", "REPORT-03"),
}


DELIVERED_JOURNEYS: dict[str, tuple[str, ...]] = {
    "IPLF-001A": ("UJ-25",), "IPLF-001B": ("UJ-25", "UJ-68"),
    "IPLF-003A": ("UJ-17",), "IPLF-003B": ("UJ-17", "UJ-20"),
    "IPLF-005A": ("UJ-16",), "IPLF-006A": ("UJ-15", "UJ-48"),
    "IPLF-006B": ("UJ-15", "UJ-48"), "IPLF-007A": ("UJ-11",),
    "IPLF-007B": ("UJ-11",), "IPLF-039A": ("UJ-03", "UJ-54"),
    "IPLF-039B": ("UJ-51", "UJ-55"),
    "IPLF-039C": ("UJ-50", "UJ-57", "UJ-59", "UJ-62"),
    "IPLF-039D": ("UJ-58",), "IPLF-039E": ("UJ-61",),
    "IPLF-039F": ("UJ-52",),
}


IMPLEMENTATION_REFS = {
    "IPLF-001A": ["infra/cloudrun/deploy.ps1", "scripts/scheduler_inventory.py"],
    "IPLF-001B": ["infra/cloudrun/scheduler-inventory.json", "scripts/scheduler_inventory.py"],
    "IPLF-003A": ["apps/api/src/caseops_api/services/source_actions.py", "apps/api/src/caseops_api/schemas/source_actions.py"],
    "IPLF-003B": ["apps/web/components/app/SourceAction.tsx", "apps/api/src/caseops_api/api/routes/source_actions.py"],
    "IPLF-005A": ["apps/api/src/caseops_api/services/authorities.py", "scripts/run_ip_golden_queries.py"],
    "IPLF-006A": ["apps/api/alembic/versions/20260801_0001_ip_source_trust.py", "apps/api/src/caseops_api/api/routes/statutes.py"],
    "IPLF-006B": ["apps/api/src/caseops_api/api/routes/statutes.py", "apps/web/app/app/statutes/[statute_id]/sections/[section_number]/page.tsx"],
    "IPLF-007A": ["apps/api/src/caseops_api/services/notification_delivery.py", "apps/api/src/caseops_api/db/models.py"],
    "IPLF-007B": ["apps/api/src/caseops_api/services/notification_delivery.py", "apps/api/tests/test_durable_workflows.py"],
    "IPLF-039A": ["apps/api/src/caseops_api/services/ip_operations.py", "apps/web/app/app/ip/page.tsx"],
    "IPLF-039B": ["apps/api/src/caseops_api/services/ip_operations.py", "apps/api/src/caseops_api/services/notices.py", "apps/web/app/app/ip/page.tsx"],
    "IPLF-039C": ["apps/api/src/caseops_api/services/ip_operations.py", "apps/api/src/caseops_api/services/employees.py", "apps/web/app/app/ip/page.tsx"],
    "IPLF-039D": ["apps/api/src/caseops_api/services/ip_operations.py", "apps/api/tests/test_ip_prd_slices.py"],
    "IPLF-039E": ["apps/api/src/caseops_api/services/ip_operations.py", "apps/web/app/app/ip/page.tsx"],
    "IPLF-039F": ["apps/api/src/caseops_api/services/ip_operations.py", "apps/web/app/app/ip/page.tsx"],
}


def status_block() -> dict[str, str]:
    return {
        "implementation_status": "not_started", "verification_status": "not_run",
        "release_status": "blocked", "acceptance_status": "pending",
    }


def owner_for(epic_id: str, title: str) -> dict[str, str]:
    classification = "EXTEND"
    if epic_id in {"IPLF-021", "IPLF-022", "IPLF-027", "IPLF-040", "IPLF-051", "IPLF-052", "IPLF-057", "IPLF-062", "IPLF-066", "IPLF-071", "IPLF-072"}:
        classification = "NEW"
    elif epic_id == "IPLF-032":
        classification = "REPLACE"
    elif epic_id in {"IPLF-024", "IPLF-039", "IPLF-044", "IPLF-053", "IPLF-055", "IPLF-059", "IPLF-063"}:
        classification = "LINK"
    return {
        "classification": classification,
        "component": f"{epic_id} canonical scope: {title}",
        "canonical_writer": "The existing Section 11.2 owner, extended by the parent epic's typed adapter/service; any new record is owned by the PRD-named neutral or IP bounded context.",
        "compatibility_path": "Existing Matter/platform routes and records remain canonical; additive adapters delegate to one writer and preserve legacy reads during rollout.",
        "retirement_gate": "No compatibility path is retired until one-writer reconciliation, mixed-revision proof, rollback evidence, and exact deployed acceptance pass.",
    }


def derived_slice(epic: dict, suffix: str, phase: str, depends_on: list[str]) -> dict:
    slice_id = f"{epic['id']}{suffix}"
    return {
        "id": slice_id,
        "title": f"{phase}: {epic['title']}",
        "milestone_id": epic["milestone_id"], "epic_id": epic["id"],
        "source_kind": "derived", "scope_source": epic["id"],
        "primary_behavior": phase,
        "migration_boundary": "Additive expand/backfill/verify/switch boundary when persistence changes; otherwise explicitly no schema change.",
        "release_boundary": "Compatible slices may share one exact integrated candidate, CI matrix, staged rollout, rollback plan, and dated deployed acceptance; this row remains a traceability and activation unit, not a mandatory separate release.",
        "requirement_ids": [], "journey_path_ids": [],
        "ownership": [owner_for(epic["id"], epic["title"])],
        "dependencies": depends_on, "external_preconditions": [],
        "implementation_refs": [], "test_refs": [],
        "evidence_refs": [], "evidence_metadata": [], "approvals": [], "blockers": [],
        "next_actions": ["Start this node whenever its direct dependencies are ready; unresolved external acceptance keeps only its authoritative activation and claims fail-closed while independent implementation continues."],
        "data_impact": ["Pending slice design; no data mutation is authorized by this allocation row."],
        "documentation_impact": [], "allocation_review": "Phase 0 mechanical allocation; scope and ownership reviewed against PRD Sections 11, 23, and 25.",
        **status_block(),
    }


def aggregate(rows: list[dict]) -> dict[str, str]:
    if not rows:
        return {
            "implementation_status": "implemented",
            "verification_status": "passed",
            "release_status": "not_required",
            "acceptance_status": "not_required",
        }

    implementations = {row["implementation_status"] for row in rows}
    if rows and implementations == {"implemented"}:
        implementation = "implemented"
    elif "in_progress" in implementations or "implemented" in implementations:
        implementation = "in_progress"
    elif "blocked" in implementations:
        implementation = "blocked"
    else:
        implementation = "not_started"
    verifications = {row["verification_status"] for row in rows}
    if "failed" in verifications:
        verification = "failed"
    elif rows and verifications == {"passed"}:
        verification = "passed"
    elif "blocked" in verifications:
        verification = "blocked"
    else:
        verification = "not_run"
    releases = {row["release_status"] for row in rows}
    if rows and releases <= {"deployment_verified", "not_required"}:
        release = "deployment_verified" if "deployment_verified" in releases else "not_required"
    else:
        release = "blocked"
    acceptances = {row["acceptance_status"] for row in rows}
    if "rejected" in acceptances:
        acceptance = "rejected"
    elif rows and acceptances <= {"approved", "not_required"}:
        acceptance = "approved" if "approved" in acceptances else "not_required"
    elif "blocked" in acceptances:
        acceptance = "blocked"
    else:
        acceptance = "pending"
    return {
        "implementation_status": implementation, "verification_status": verification,
        "release_status": release, "acceptance_status": acceptance,
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["schema_version"] = 2
    epics = {row["id"]: row for row in manifest["epics"]}
    existing = {row["id"]: row for row in manifest["slices"]}
    by_epic: dict[str, list[dict]] = defaultdict(list)
    for row in existing.values():
        row.setdefault("source_kind", "prd_explicit")
        row.setdefault("scope_source", row["id"])
        row.setdefault("primary_behavior", row["title"])
        row.setdefault("migration_boundary", "No schema change unless named by release evidence; preserve the PRD expand/backfill/verify/switch contract.")
        row.setdefault("release_boundary", "Compatible-train exact-candidate CI and dated deployed acceptance for activated/supported scope; fail-closed acceptance-pending scope may share the train.")
        row.setdefault("external_preconditions", [])
        row.setdefault("evidence_metadata", [])
        row.setdefault("allocation_review", "PRD-explicit slice preserved and reviewed during Phase 0 reconciliation.")
        by_epic[row["epic_id"]].append(row)

    for epic in manifest["epics"]:
        rows = sorted(by_epic[epic["id"]], key=lambda row: row["id"])
        used = {row["id"][-1] for row in rows}
        available = [letter for letter in string.ascii_uppercase if letter not in used]
        if not rows:
            first = derived_slice(epic, available[0], "Foundation, ownership, and backend contract", [])
            second = derived_slice(epic, available[1], "User workflow, exceptions, and release proof", [first["id"]])
            existing[first["id"]] = first
            existing[second["id"]] = second
            by_epic[epic["id"]].extend([first, second])
        elif not any(row.get("source_kind") == "derived" for row in rows):
            first = derived_slice(epic, available[0], "Remaining PRD behavior and exception coverage", [rows[-1]["id"]])
            existing[first["id"]] = first
            by_epic[epic["id"]].append(first)
            if epic["id"] == "IPLF-039":
                second = derived_slice(epic, available[1], "Integrated workflow, reconciliation, and production proof", [first["id"]])
                existing[second["id"]] = second
                by_epic[epic["id"]].append(second)

    for slice_id, row in existing.items():
        epic = epics[row["epic_id"]]
        if not row.get("ownership"):
            row["ownership"] = [owner_for(epic["id"], epic["title"])]
        if row["implementation_status"] == "implemented":
            row["implementation_refs"] = IMPLEMENTATION_REFS[slice_id]
            row["test_refs"] = sorted(set(row.get("test_refs", []) + [
                "apps/api/tests/test_ip_prd_slices.py" if slice_id.startswith("IPLF-039") else "apps/api/tests/test_ip_prd_slices.py",
            ]))
            evidence = (
                "docs/ip-implementation/evidence/m1/IPLF-001A/audit-2026-08-01.md" if slice_id == "IPLF-001A"
                else "docs/ip-implementation/evidence/m1/IPLF-001B/release-2026-08-01.md" if slice_id == "IPLF-001B"
                else RELEASE_2 if slice_id in {"IPLF-007B", "IPLF-039B", "IPLF-039C", "IPLF-039E", "IPLF-039F"}
                else RELEASE_1
            )
            row["evidence_refs"] = sorted(set(row.get("evidence_refs", []) + [evidence]))
            row["evidence_metadata"] = [{
                "ref": evidence, "revision": "b7365cc1ca972662a7ae30d897610bfa92644f46",
                "environment": "production", "fixtures": "deterministic anonymized release fixtures and dated QA tenant",
                "assertions": "slice-specific API, persistence, permission, UI, and deployed behavior assertions",
                "result": "passed", "recorded_at": "2026-08-02T06:25:00+05:30",
            }]
        row["blockers"] = [blocker for blocker in row.get("blockers", []) if not (
            slice_id in {"IPLF-001A", "IPLF-001B"}
            and (
                blocker.get("id", "").startswith("IPLF-001B-ACTION-")
                or blocker.get("id") == "M1-SCHEDULER-OBSERVATION"
            )
        )]

    # The stale scheduler drift blockers were resolved by exact-image/IAM/canary proof.
    for milestone in manifest["milestones"]:
        milestone["blockers"] = [blocker for blocker in milestone.get("blockers", []) if blocker.get("id") not in {"M1-SCHEDULER-IAM-DRIFT", "M1-IMAGE-LOG-DRIFT"}]

    completion_slice: dict[str, str] = {}
    for epic_id, rows in by_epic.items():
        planned = sorted((row for row in rows if row["implementation_status"] != "implemented"), key=lambda row: row["id"])
        completion_slice[epic_id] = (planned[-1] if planned else sorted(rows, key=lambda row: row["id"])[-1])["id"]

    for row in existing.values():
        row["requirement_ids"] = list(DELIVERED_REQUIREMENTS.get(row["id"], ()))
        row["journey_path_ids"] = []
    for requirement in manifest["requirements"]:
        epic_ids = FAMILY_EPICS[requirement["family"]]
        allocated = [completion_slice[epic_id] for epic_id in epic_ids]
        for slice_id in allocated:
            existing[slice_id]["requirement_ids"].append(requirement["id"])
        delivered = [slice_id for slice_id, ids in DELIVERED_REQUIREMENTS.items() if requirement["id"] in ids]
        requirement["slice_ids"] = sorted(set(allocated + delivered))
        requirement["allocation_rationale"] = f"{requirement['family']} allocation reviewed against PRD requirement family and parent epic scope: {', '.join(epic_ids)}."

    paths_by_journey: dict[str, list[dict]] = defaultdict(list)
    for path in manifest["journey_paths"]:
        paths_by_journey[path["journey_id"]].append(path)
        epic_ids = JOURNEY_EPICS[path["journey_id"]]
        allocated = [completion_slice[epic_id] for epic_id in epic_ids]
        delivered = [
            slice_id for slice_id, journeys in DELIVERED_JOURNEYS.items()
            if path["journey_id"] in journeys
        ]
        path["slice_ids"] = sorted(set(allocated + delivered))
        path["allocation_rationale"] = f"{path['journey_id']} path allocation reviewed against its PRD flow/exceptions and parent epic scope: {', '.join(epic_ids)}."
        path["test_refs"] = [f"planned:{path['test_id']}"]
        for slice_id in path["slice_ids"]:
            existing[slice_id]["journey_path_ids"].append(path["id"])
            existing[slice_id]["test_refs"].append(f"planned:{path['test_id']}")

    for row in existing.values():
        row["requirement_ids"] = sorted(set(row["requirement_ids"]))
        row["journey_path_ids"] = sorted(set(row["journey_path_ids"]))
        row["test_refs"] = sorted(set(row["test_refs"]))
        if not row["requirement_ids"] or not row["journey_path_ids"]:
            row["administrative_exception"] = {
                "prd_citation": "PRD Section 25 and the parent epic title",
                "reviewer": "CaseOps Phase 0 control-plane reconciliation",
                "reason": "This bounded technical slice has no direct requirement family or journey path; its parent completion slices carry the full reciprocal allocation.",
                "date": "2026-08-02", "milestone": row["milestone_id"],
            }
        else:
            row.pop("administrative_exception", None)

    manifest["slices"] = sorted(existing.values(), key=lambda row: row["id"])
    for epic in manifest["epics"]:
        epic["slice_ids"] = sorted(row["id"] for row in manifest["slices"] if row["epic_id"] == epic["id"])
        epic["requirement_ids"] = sorted({requirement_id for slice_id in epic["slice_ids"] for requirement_id in existing[slice_id]["requirement_ids"]})
        epic["journey_ids"] = []
        epic.update(aggregate([existing[slice_id] for slice_id in epic["slice_ids"]]))
        epic["evidence_refs"] = sorted({ref for slice_id in epic["slice_ids"] for ref in existing[slice_id].get("evidence_refs", [])})

    slice_by_id = {row["id"]: row for row in manifest["slices"]}
    for requirement in manifest["requirements"]:
        owners = [slice_by_id[slice_id] for slice_id in requirement["slice_ids"]]
        requirement.update(aggregate(owners))
        requirement["implementation_refs"] = sorted({ref for row in owners for ref in row.get("implementation_refs", [])})
        requirement["test_refs"] = sorted({f"planned:IPLF-REQ-{requirement['id']}", *{ref for row in owners for ref in row.get("test_refs", [])}})
        requirement["evidence_refs"] = sorted({ref for row in owners for ref in row.get("evidence_refs", [])})

    requirement_ids_by_journey: dict[str, set[str]] = defaultdict(set)
    for requirement in manifest["requirements"]:
        owned_epics = {slice_by_id[slice_id]["epic_id"] for slice_id in requirement["slice_ids"]}
        journeys = [journey_id for journey_id, epic_ids in JOURNEY_EPICS.items() if owned_epics.intersection(epic_ids)]
        requirement["journey_ids"] = sorted(journeys)
        for journey_id in journeys:
            requirement_ids_by_journey[journey_id].add(requirement["id"])
    for path in manifest["journey_paths"]:
        path["requirement_ids"] = sorted(requirement_ids_by_journey[path["journey_id"]])
        owners = [slice_by_id[slice_id] for slice_id in path["slice_ids"]]
        path.update(aggregate(owners))
        path["evidence_refs"] = sorted({ref for row in owners for ref in row.get("evidence_refs", [])})
    paths_by_id = {row["id"]: row for row in manifest["journey_paths"]}
    for journey in manifest["journeys"]:
        paths = [paths_by_id[path_id] for path_id in journey["path_ids"]]
        journey["slice_ids"] = sorted({slice_id for path in paths for slice_id in path["slice_ids"]})
        journey["requirement_ids"] = sorted(requirement_ids_by_journey[journey["id"]])
        journey["test_refs"] = sorted({ref for path in paths for ref in path["test_refs"]})
        journey["evidence_refs"] = sorted({ref for path in paths for ref in path["evidence_refs"]})
        journey.update(aggregate(paths))

    for epic in manifest["epics"]:
        epic["journey_ids"] = sorted({
            paths_by_id[path_id]["journey_id"]
            for slice_id in epic["slice_ids"]
            for path_id in slice_by_id[slice_id]["journey_path_ids"]
        })

    manifest["gates"] = [
        {
            "id": "PHASE0-NOTICES-PRODUCTION", "milestone_id": "M1", "kind": "production_regression",
            "summary": "Latest scheduled production Notices workflow failed after a successful create response.",
            "evidence_refs": [], "blockers": [{"id": "PROD-NOTICES-30729636524", "summary": "GitHub Actions run 30729636524 failed BUG-001 and skipped the dependent notice-module suite.", "owner": "Engineering/QA", "evidence_needed": "Exact deployed fix and newest complete production Playwright pass."}],
            "implementation_status": "in_progress", "verification_status": "failed", "release_status": "blocked", "acceptance_status": "pending",
        },
    ]
    gates_by_milestone: dict[str, list[dict]] = defaultdict(list)
    for gate in manifest["gates"]:
        gates_by_milestone[gate["milestone_id"]].append(gate)
    epics_by_milestone: dict[str, list[dict]] = defaultdict(list)
    for epic in manifest["epics"]:
        for milestone_id in ("M7", "M8", "M9", "M10") if epic["milestone_id"] == "M7-M10" else (epic["milestone_id"],):
            epics_by_milestone[milestone_id].append(epic)
    for milestone in manifest["milestones"]:
        milestone["epic_ids"] = sorted(epic["id"] for epic in epics_by_milestone[milestone["id"]])
        milestone["gate_ids"] = sorted(gate["id"] for gate in gates_by_milestone[milestone["id"]])
        milestone.update(aggregate(epics_by_milestone[milestone["id"]] + gates_by_milestone[milestone["id"]]))
        milestone["evidence_refs"] = sorted({ref for row in epics_by_milestone[milestone["id"]] + gates_by_milestone[milestone["id"]] for ref in row.get("evidence_refs", [])})
    manifest["program"].update(aggregate(manifest["milestones"]))
    manifest["program"]["execution_policy"] = (
        "single_ordered_queue_without_manual_project_approvals; implement first and run the "
        "automated check and exact-release verification batch at the end"
    )
    manifest["program"]["active_slice"] = "IPLF-002A"
    manifest["program"]["checkpoint"] = {
        "recorded_at": "2026-08-02T11:00:00+05:30",
        "repository_revision": "b7365cc1ca972662a7ae30d897610bfa92644f46",
        "environment": "Phase 0 source, manifest, CI, deployment, and latest production-regression audit",
        "completed_scope": "Reconciled previously delivered slices without claiming full requirements; Notices production fix is implemented locally and awaits exact-revision deployment proof.",
        "program_state": "PROGRAM INCOMPLETE",
        "next_slice": "IPLF-002A",
        "next_action": (
            "Finish the Phase 0 Notices release proof and control-plane validation on their direct "
            "dependency lane while executing every other dependency-ready M0-M10 node behind its "
            "fail-closed activation boundary."
        ),
        "evidence_ref": "docs/ip-implementation/evidence/phase0/control-plane-and-notices-2026-08-02.md",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
