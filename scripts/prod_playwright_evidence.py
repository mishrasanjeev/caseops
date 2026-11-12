"""Retain bounded, privacy-minimized native Playwright release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("test-results/prod-native-evidence")
LIMIT = 64 * 1024 * 1024
SHA = re.compile(r"[a-f0-9]{40}")
INVOCATION = re.compile(r"[a-z][a-z0-9-]{0,63}")
OUTPUT_VARIABLES = (
    "PLAYWRIGHT_JSON_OUTPUT_FILE",
    "PLAYWRIGHT_JSON_OUTPUT_DIR",
    "PLAYWRIGHT_JSON_OUTPUT_NAME",
    "PLAYWRIGHT_JUNIT_OUTPUT_FILE",
    "PLAYWRIGHT_JUNIT_OUTPUT_DIR",
    "PLAYWRIGHT_JUNIT_OUTPUT_NAME",
)
REPORT_FILES = {
    "invocation.json",
    "discovery.json",
    "results.json",
    "results.xml",
    "native-discovery.json",
    "native-results.json",
    "native-results.xml",
    "progress.jsonl",
}
REPORTER = "./scripts/prod_playwright_reporter.cjs"
APP_PROJECT_PARTITIONS = {
    "ci-app-chromium": "app-chromium",
    "ci-app-mobile": "app-mobile",
}
APP_PROJECT_COUNTS = {"app-chromium": 724, "app-mobile": 60}
APP_BASE_PROJECT_COUNTS = {"app-chromium": 719, "app-mobile": 55}
BATCH5_CONTRACT_VERSION = 1
BATCH5_FILES = tuple(
    f"ram-2026-11-11-{name}.spec.ts" for name in ("statutes", "drafting", "contracts", "bugs")
)
BATCH5_PROJECTS = {"batch5-desktop": "batch5-prod-chromium", "batch5-mobile": "batch5-prod-mobile"}
BATCH5_MOVED_CASES = (
    ("ram-2026-11-07-contracts.spec.ts", "AI-CON-01 table-cell tracked changes retain source bytes and survive workspace reload"),
    ("ram-2026-11-07-teams.spec.ts", "AI-TEAM-01 membership and audited lead changes persist after reload"),
)
# Keep the observed774 app and423 production baselines separate from additions.
# Reviewed declarations must match fresh native collection before acceptance.
BATCH5_CASE_COUNTS = {
    "ram-2026-11-11-statutes.spec.ts": (1, 1),
    "ram-2026-11-11-drafting.spec.ts": (1, 1),
    "ram-2026-11-11-contracts.spec.ts": (1, 1),
    "ram-2026-11-11-bugs.spec.ts": (2, 2),
}
BATCH5_PROOF_SCOPES = {
    "ram-2026-11-11-statutes.spec.ts": "workflow-outcome",
    "ram-2026-11-11-contracts.spec.ts": "workflow-outcome",
    "ram-2026-11-11-drafting.spec.ts": "retained-readonly",
    "ram-2026-11-11-bugs.spec.ts": "preview-no-paid-guard",
}
BATCH5_CASE_PROOF_SCOPES = {
    "ram-2026-11-11-bugs.spec.ts": {
        "BUG-003 communications resolved preview and missing-value guard desktop":
        "preview-no-paid-guard",
        "[mobile] BUG-003 communications resolved preview and missing-value guard phone":
        "preview-no-paid-guard",
        ("B5-013/014 assistant factual citation, legal abstention "
         "and research mode navigation desktop"): "assistant-research-no-paid-guard",
        ("[mobile] B5-013/014 assistant factual citation, legal abstention "
         "and research mode navigation phone"): "assistant-research-no-paid-guard",
    },
}
APP_REQUIRED_CASES = (
    ("app-chromium", "control-crawl-contract.spec.ts", (
        "control-crawl-contract.spec.ts",
        "control audit follows fieldset, first-legend and option-group disabled states",
    )),
    ("app-chromium", "watch-acl-query-states.spec.ts", (
        "watch-acl-query-states.spec.ts",
        "Watch removes revoked source evidence from the workspace and report after reload",
    )),
)
# Exact pre-existing capability/provider skips retained from the complete
# source-bound partial run; discovery's empty-result status is never a skip.
APP_EXPECTED_SKIPS = (
    ("app-chromium", "all-modules-regression.spec.ts",
     ("all-modules-regression.spec.ts", "All modules and critical court operations", "e-List search uses the entered case number through the real Docker API",)),
    ("app-chromium", "billing-payment.spec.ts",
     ("billing-payment.spec.ts", "Matter billing — Pine Labs payment link (provider-gated)", "create invoice + payment link, payment link reachable",)),
    ("app-chromium", "case-tracking-summary-2026-09-10.spec.ts",
     ("case-tracking-summary-2026-09-10.spec.ts", "dated async summary: visible fallback, release-image worker, retained source and no-paid fences",)),
    ("app-chromium", "ram-2026-08-24-bugs.spec.ts",
     ("ram-2026-08-24-bugs.spec.ts", "Ram 2026-08-24 local and deployed regressions", "exact deployed API and web identify the release under test",)),
    ("app-chromium", "ram-2026-09-02-bugs.spec.ts",
     ("ram-2026-09-02-bugs.spec.ts", "Ram 2026-09-02 workbook regressions", "exact production release identifies the deployed revision",)),
    ("app-chromium", "ram-2026-09-03-prod.spec.ts",
     ("ram-2026-09-03-prod.spec.ts", "Ram 2026-09-03 Bulk Matter Exact Court mapping", "exact production release identifies the deployed revision",)),
    ("app-chromium", "ram-2026-09-04-bugs.spec.ts",
     ("ram-2026-09-04-bugs.spec.ts", "Ram 2026-09-04 automatic next-hearing sync", "BUG-012 older cnr matter shows its scheduled hearing date without lifecycle mutation",)),
    ("app-chromium", "ram-2026-09-04-bugs.spec.ts",
     ("ram-2026-09-04-bugs.spec.ts", "Ram 2026-09-04 automatic next-hearing sync", "BUG-012 older case-number matter shows its scheduled hearing date without lifecycle mutation",)),
    ("app-chromium", "ram-2026-09-04-bugs.spec.ts",
     ("ram-2026-09-04-bugs.spec.ts", "Ram 2026-09-04 automatic next-hearing sync", "BUG-012 older backfill-bound matter shows its scheduled hearing date without lifecycle mutation",)),
    ("app-chromium", "ram-2026-09-04-bugs.spec.ts",
     ("ram-2026-09-04-bugs.spec.ts", "Ram 2026-09-04 automatic next-hearing sync", "production surface is exact-release ready and regular verification spends zero provider credits",)),
    ("app-chromium", "ram-2026-09-10-hearings.spec.ts",
     ("ram-2026-09-10-hearings.spec.ts", "BUG-014 scheduled CNR, combined registration and filing identities persist the nearest visible hearing",)),
    ("app-chromium", "ram-2026-09-10-hearings.spec.ts",
     ("ram-2026-09-10-hearings.spec.ts", "BUG-014 reported production Matters explain missing court identity without spending",)),
    ("app-chromium", "ram-2026-09-24-prod.spec.ts",
     ("ram-2026-09-24-prod.spec.ts", "QA-owned matter has a canonical hearing and automated eCourts lookup cannot spend",)),
    ("app-chromium", "ram-2026-09-24-prod.spec.ts",
     ("ram-2026-09-24-prod.spec.ts", "reported legacy Matters retain backfilled hearing evidence in their authorized workspace",)),
    ("app-chromium", "ram-2026-09-26-bugs.spec.ts",
     ("ram-2026-09-26-bugs.spec.ts", "Ram 2026-09-26 workbook (IV)", "BUG-032 case tracking recognises a Matter's own eCourts case and opens the existing Matter",)),
    ("app-chromium", "ram-2026-10-08-prod.spec.ts",
     ("ram-2026-10-08-prod.spec.ts", "BUG-003/004: live authorization scopes and rejected callback return to Calendar safely",)),
    ("app-chromium", "ram-2026-10-08-prod.spec.ts",
     ("ram-2026-10-08-prod.spec.ts", "BUG-003: owner-consented Google account remains connected after responsive reloads",)),
    ("app-chromium", "ram-2026-10-31-control-crawl.spec.ts",
     ("ram-2026-10-31-control-crawl.spec.ts", "BUG-015 controls on /app/ip reported docket are usable or explain themselves",)),
    ("app-chromium", "ram-2026-10-31-control-crawl.spec.ts",
     ("ram-2026-10-31-control-crawl.spec.ts", "BUG-015 controls on /app/matters reported Matter billing are usable or explain themselves",)),
    ("app-chromium", "ram-2026-10-31-invoice-pdf.spec.ts",
     ("ram-2026-10-31-invoice-pdf.spec.ts", "BUG-016 [prod-only] the reported invoices INVR-2026-028 and INVR-2026-068 download legible (read-only)",)),
    ("app-mobile", "ram-2026-10-31-invoice-pdf.spec.ts",
     ("ram-2026-10-31-invoice-pdf.spec.ts", "BUG-016 [prod-only] [mobile] the reported invoices download legible at 393px (read-only)",)),
)
TESTER_PARTITIONS = {
    "tester": "tester-prod-chromium",
    "tester-catalog": "tester-prod-chromium",
    "tester-index": "tester-index-prod-chromium",
    "test-legal-write-oct13-a": "test-legal-write-prod-chromium",
    "test-legal-write-oct13-b": "test-legal-write-prod-chromium",
}
# Reviewed exact inventory; any new or removed case requires an explicit update.
TESTER_PARTITION_COUNTS = {
    "tester": 97, "tester-catalog": 18, "tester-index": 6,
    "test-legal-write-oct13-a": 40, "test-legal-write-oct13-b": 11,
}
# These mandatory positive journeys are separate from the reviewed tester union.
BATCH3_MANDATORY_CASES = {
    "batch3-clients-desktop": (
        "batch3-clients-prod-chromium", "ram-2026-10-22-bugs.spec.ts",
        "B3-CLIENT-01/02/03 contact edits preserve retained verified KYC and matter links",
    ),
    "batch3-clients-mobile": (
        "batch3-clients-prod-mobile", "ram-2026-10-22-bugs.spec.ts",
        "[mobile] B3-CLIENT-06 verified-client contact editing persists at 393px",
    ),
    "batch3-drafts-readonly": (
        "batch3-drafts-readonly-prod-chromium", "ram-2026-10-22-drafting.prod.spec.ts",
        "B3-DRAFT-PROD read-only retained finalized and mutable Appeal controls persist after "
        "reload",
    ),
}
# Tester batch 4 (2026-10-31): every production-eligible case per role, exactly.
# The governance roles are required only while the serving release's checked-in
# rule-governance state is enabled; the other roles never select that file.
_B4 = "ram-2026-10-31-{}.spec.ts".format
_B4_ADJ = "ram-2026-11-01-adj-{}.spec.ts".format
_B4_CRAWL = "BUG-015 controls on {} are usable or explain themselves".format
BATCH4_MANDATORY_CASES = {
    "batch4-desktop": ("batch4-prod-chromium", (
        (_B4("calendar-year"), "ENH-017 Year view shows Ram's UI-created hearing and task on "
         "their days in distinct colours and survives reload"),
        *((_B4("control-crawl"), _B4_CRAWL(route)) for route in (
            "/app/ip", "/app/ip Documents tab", "/app/ip/portfolio", "/app/ip/renewals",
            "/app/ip/madrid",
            "/app/ip/recordals", "/app/ip/foreign-associates", "/app/ip/registry",
            "/app/ip/watch", "/app/ip/reports", "/app/ip/client-portal", "/app/ip/patents",
            "/app/ip/specialist", "/app/calendar", "/app/admin/matter-billing",
            "/app/drive", "/app/mailbox", "/app/calendar/conflicts", "/app/admin/notifications",
            "/app/ip reported docket",
            "/app/matters reported Matter billing",
        )),
        (_B4("docket-sweep"), "DOCKET-SWEEP calendar-copy reviews: the daily docket counts "
         "every pending review the server reports, not the first 100"),
        (_B4("fixture-honesty"), "BUG-002 Ram's Documents Classification is provisioned, "
         "never seeded, and previews a classified name"),
        (_B4("foreign-associates"), "BUG-009/010/011/013 Ram walks a new instruction from "
         "every empty picker to a created and retired instruction"),
        (_B4("invoice-pdf"), "BUG-016 draft invoice PDF downloaded from the billing page is "
         "legible, one page and marked DRAFT"),
        (_B4("invoice-pdf"), "BUG-016 [prod-only] the reported invoices INVR-2026-028 and "
         "INVR-2026-068 download legible (read-only)"),
        (_B4("ip-create"), "BUG-001 BUG-002 Ram creates a two-class trademark that opens in "
         "view and records its Nice edition"),
        (_B4("madrid-portal"), "BUG-015 Madrid: Ram records an outbound IR choosing the basic "
         "mark docket through the picker"),
        (_B4("madrid-portal"), "BUG-015 client portal: every offered grant loads its "
         "shareable versions or says why there are none"),
        (_B4("madrid-portal"), "BUG-015 sweep: Madrid, client portal, renewals and reports "
         "ask for no internal record ID"),
        (_B4("matter-links"), "BUG-007 Ram finds a Matter by typing among 60+ Matters, links "
         "it and retires it at 1440x900"),
        (_B4("recordals"), "BUG-008 Ram uploads an instrument from the recordal form and both "
         "parties cite it"),
        (_B4("registry"), "BUG-012 Ram finds a docket beyond the first 50 by its number and "
         "records manual registry evidence through structured fields"),
        (_B4("watch"), "BUG-014 journal capture: 'Class 45' with captured evidence is "
         "recorded, listed and shown on the hit; a bad class token is refused at its field"),
        (_B4_ADJ("pickers"), "B4-ADJ-02 review queues find the Matter by typing and name it, "
         "never by id, at 1440x900"),
    )),
    "batch4-mobile": ("batch4-prod-mobile", (
        (_B4("calendar-year"), "ENH-017 [mobile] Year view opens on screen in one column at "
         "375 px, keeps chips legible, and opens a day"),
        (_B4("docket-sweep"), "[mobile] DOCKET-SWEEP calendar-copy reviews: the count and "
         "list state fit at 393px without horizontal page scroll"),
        (_B4("fixture-honesty"), "BUG-002 [mobile] Classification and its upload gate stay "
         "on screen without horizontal scroll"),
        (_B4("foreign-associates"), "[mobile] BUG-009/010/011/013 Ram walks the new "
         "instruction, records the quote and creates it at 393px"),
        (_B4("invoice-pdf"), "BUG-016 [mobile] draft invoice PDF journey works at 393px "
         "without page overflow"),
        (_B4("invoice-pdf"), "BUG-016 [prod-only] [mobile] the reported invoices download "
         "legible at 393px (read-only)"),
        (_B4("ip-create"), "BUG-001 BUG-002 [mobile] Ram creates a two-class trademark on a "
         "phone without horizontal scroll"),
        (_B4("madrid-portal"), "BUG-015 Madrid [mobile]: intake pickers fit a phone and never "
         "offer a dead choice"),
        (_B4("madrid-portal"), "BUG-015 client portal [mobile]: grant and publish controls "
         "fit a phone"),
        (_B4("matter-links"), "BUG-007 [mobile] Ram finds, links and retires a Matter on a "
         "phone without overflow"),
        (_B4("recordals"), "BUG-008 [mobile] the recordal journey works at Pixel 5 width "
         "without horizontal scroll"),
        (_B4("registry"), "BUG-012 [mobile] the registry journey works at phone width without "
         "horizontal scroll"),
        (_B4("watch"), "[mobile] BUG-014 journal capture works at 393px without horizontal "
         "page scroll"),
        (_B4_ADJ("pickers"), "B4-ADJ-02 [mobile] review queue Matter pickers fit a phone and "
         "name the Matter"),
    )),
    "batch4-governance-desktop": ("batch4-governance-prod-chromium", (
        (_B4("governance-ui"), "BUG-003/004 opposition governed-rule and calendar pickers are "
         "never dead selects"),
        (_B4("governance-ui"), "BUG-005/006 Ram proposes a calendar and sees the honest "
         "pending-approval state"),
    )),
    "batch4-governance-mobile": ("batch4-governance-prod-mobile", (
        (_B4("governance-ui"), "[mobile] BUG-003/004 opposition picker reasons and governance "
         "link fit 393px"),
        (_B4("governance-ui"), "[mobile] BUG-005 governance card controls fit 393px with a "
         "computed source hash"),
    )),
}
GOVERNANCE_STATE = Path("deploy/ip-rule-governance-state.json")
GOVERNANCE_STATE_KEYS = {
    "schema_version", "enabled", "rollout_expires_at", "approved_by", "evidence",
}
TESTER_CATALOG_FILE = "ram-2026-09-05-bugs.spec.ts"
TESTER_PARTITION_CONTRACT = 3
TESTER_CANONICAL_FILES = {"canonical-native-discovery.json", "canonical-discovery.json"}
INDEX_FILES = {
    "ram-2026-10-10-prod.spec.ts": 4,
    "ram-2026-10-12-prod.spec.ts": 2,
}
OCT13_FILES = {
    "ram-2026-10-13-hearings.spec.ts": 2,
    "ram-2026-10-13-ip-portfolio.spec.ts": 4,
    "ram-2026-10-15-ip-controls.spec.ts": 34,
    "ram-2026-10-15-ip-renewal-tracker.spec.ts": 2,
    "ram-2026-10-17-calendar-readiness.spec.ts": 2,
    "ram-2026-10-17-ip-reminders.spec.ts": 4,
    "ram-2026-10-17-ip-tracker.spec.ts": 2,
    "ram-2026-10-22-prod.spec.ts": 1,
}


# Immutable whole-file partitions of the original canonical51 oracle above.
# Their tuple order preserves the two contiguous native discovery blocks.
OCT13_PARTITION_FILES = {
    "test-legal-write-oct13-a": (
        "ram-2026-10-13-hearings.spec.ts",
        "ram-2026-10-13-ip-portfolio.spec.ts",
        "ram-2026-10-15-ip-controls.spec.ts",
    ),
    "test-legal-write-oct13-b": (
        "ram-2026-10-15-ip-renewal-tracker.spec.ts",
        "ram-2026-10-17-calendar-readiness.spec.ts",
        "ram-2026-10-17-ip-reminders.spec.ts",
        "ram-2026-10-17-ip-tracker.spec.ts",
        "ram-2026-10-22-prod.spec.ts",
    ),
}
OCT13_PROJECT = "test-legal-write-prod-chromium"


class EvidenceError(ValueError):
    pass


def _require_current_oct13_namespace(invocation, *, project=None):
    if type(invocation) is not str:
        raise EvidenceError("invalid_release_or_invocation")
    if (
        (invocation.startswith("test-legal-write-oct13") or project == OCT13_PROJECT)
        and invocation not in OCT13_PARTITION_FILES
    ):
        raise EvidenceError("unreviewed_oct13_partition_invocation")


def _app_project_partition(binding):
    invocation = binding["invocation"]
    if invocation not in APP_PROJECT_PARTITIONS:
        return None
    project = APP_PROJECT_PARTITIONS[invocation]
    expected = {
        f"--project={project}", "--config=playwright.app.config.ts",
        "--workers=1", "--retries=0", "--reporter=list",
        f"--output=test-results/{project}",
    }
    if (binding["config"] != "playwright.app.config.ts"
            or binding["project"] != project
            or len(binding["arguments"]) != len(expected)
            or set(binding["arguments"]) != expected):
        raise EvidenceError("app_project_binding_mismatch")
    return invocation


def _app_inventory(canonical):
    rows = canonical["tests"]
    batch5 = [row for row in rows if row["file"] in BATCH5_FILES]
    legacy = [row for row in rows if row["file"] not in BATCH5_FILES]
    if batch5 or BATCH5_CASE_COUNTS:
        _batch5_rows(batch5, {"app-chromium": 0, "app-mobile": 1}, include_moved=False)
    if (Counter(row["project_name"] for row in rows) != APP_PROJECT_COUNTS
            or Counter(row["project_name"] for row in legacy) != APP_BASE_PROJECT_COUNTS
            or len({row["id"] for row in rows}) != sum(APP_PROJECT_COUNTS.values())
            or [row["project_name"] for row in legacy] != [
                project for project, count in APP_BASE_PROJECT_COUNTS.items() for _ in range(count)
            ]
            or len(set(APP_EXPECTED_SKIPS)) != 21
            or not set(APP_EXPECTED_SKIPS).issubset({_app_skip_identity(row) for row in rows})
            or not set(APP_REQUIRED_CASES).issubset({_app_skip_identity(row) for row in rows})
            or any(row["project_id"] != row["project_name"] for row in rows)
            or any(row["retries"] != 0 or row["repeat_each_index"] != 0
                   or row["results"] for row in rows)
            or canonical["configuration"]["workers"] != 1
            or canonical["global_error_count"] != 0
            or canonical["report_status"] != "passed"
            or any(canonical["stats"][key] for key in ("expected", "unexpected", "flaky"))
            or len(canonical["projects"]) != len(APP_PROJECT_COUNTS)
            or {(p["id"], p["name"]) for p in canonical["projects"]}
            != {(project, project) for project in APP_PROJECT_COUNTS}
            or any(p["retries"] != 0 or p["repeatEach"] != 1
                   for p in canonical["projects"])):
        raise EvidenceError("app_canonical_inventory_mismatch")
    return rows


def _batch5_counts():
    if (set(BATCH5_CASE_COUNTS) != set(BATCH5_FILES)
            or any(type(counts) not in (tuple, list) or len(counts) != 2
                   or any(type(count) is not int or count < 0 for count in counts)
                   or counts[0] < 1 for counts in BATCH5_CASE_COUNTS.values())
            or BATCH5_CASE_COUNTS[BATCH5_FILES[0]][1] < 1):
        raise EvidenceError("unreviewed_batch5_case_counts")
    return {**BATCH5_CASE_COUNTS, **{file: (1, 1) for file, _ in BATCH5_MOVED_CASES}}


def _batch5_partition(binding):
    invocation, project = binding["invocation"], binding.get("project")
    if invocation not in BATCH5_PROJECTS:
        if invocation.startswith("batch5") or project in BATCH5_PROJECTS.values():
            raise EvidenceError("unreviewed_batch5_invocation")
        return None
    expected_project = BATCH5_PROJECTS[invocation]
    expected = {
        "--config=playwright.prod-ram.config.ts", f"--project={expected_project}",
        "--workers=1", "--retries=0", "--reporter=list", f"--output=test-results/{invocation}",
    }
    if (binding["config"] != "playwright.prod-ram.config.ts" or project != expected_project
            or len(binding["arguments"]) != len(expected) or set(binding["arguments"]) != expected):
        raise EvidenceError("batch5_role_binding_mismatch")
    _batch5_counts()
    return invocation


def _batch5_rows(rows, projects, *, include_moved=True):
    counts = _batch5_counts()
    if not include_moved:
        counts = {file: pair for file, pair in counts.items() if file in BATCH5_FILES}
    expected = Counter({(file, project): pair[index]
                        for file, pair in counts.items() for project, index in projects.items()
                        if pair[index]})
    if (Counter((row["file"], row["project_name"]) for row in rows) != expected
            or len({row["id"] for row in rows}) != len(rows)
            or any(row["project_id"] != row["project_name"]
                   or ("[mobile]" in row["title_path"][-1]) != (projects[row["project_name"]] == 1)
                   or "[local-only]" in row["title_path"][-1]
                   or row["retries"] != 0 or row["repeat_each_index"] != 0 for row in rows)):
        raise EvidenceError("batch5_case_inventory_mismatch")
    for file, title in BATCH5_MOVED_CASES:
        if file not in counts:
            continue
        expected_titles = {
            project: ("[mobile] " if index else "") + title for project, index in projects.items()
        }
        if any(row["title_path"] != [file, expected_titles[row["project_name"]]]
               for row in rows if row["file"] == file):
            raise EvidenceError("batch5_moved_case_identity_mismatch")
    for file, cases in BATCH5_CASE_PROOF_SCOPES.items():
        expected_cases = Counter(
            (project, (file, title))
            for project, index in projects.items() for title in cases
            if ("[mobile]" in title) == (index == 1)
        )
        actual_cases = Counter(
            (row["project_name"], tuple(row["title_path"]))
            for row in rows if row["file"] == file
        )
        if actual_cases != expected_cases:
            raise EvidenceError("batch5_required_case_identity_mismatch")
    return rows


def _check_batch5_selection(binding, selected, canonical, *, execution=False):
    invocation = _batch5_partition(binding)
    if invocation is None:
        raise EvidenceError("unreviewed_batch5_invocation")
    projects = {project: index for index, project in enumerate(BATCH5_PROJECTS.values())}
    all_rows = [row for row in canonical["tests"] if row["project_name"] in projects]
    _batch5_rows(all_rows, projects)
    expected = [row for row in all_rows if row["project_name"] == BATCH5_PROJECTS[invocation]]
    if (canonical["global_error_count"] or canonical["report_status"] != "passed"
            or any(row["results"] for row in canonical["tests"])
            or selected["projects"] != canonical["projects"]
            or selected["configuration"] != canonical["configuration"]
            or [_tester_case_identity(row) for row in selected["tests"]]
            != [_tester_case_identity(row) for row in expected]):
        raise EvidenceError("batch5_canonical_selection_mismatch")
    if execution:
        if (selected["global_error_count"] or selected["report_status"] != "passed"
                or any(row["status"] != "expected" or len(row["results"]) != 1
                       or row["results"][0]["status"] != "passed"
                       or row["results"][0]["retry"] != 0 for row in selected["tests"])):
            raise EvidenceError("batch5_case_not_passed")
        _batch5_proofs(selected)
    elif selected["global_error_count"] or any(row["results"] for row in selected["tests"]):
        raise EvidenceError("batch5_discovery_executed_tests")


def _batch5_proofs(document):
    scopes = []
    for row in document["tests"]:
        annotations = row["annotations"] + row["results"][0]["annotations"]
        declared = {item.get("description") for item in annotations if item["type"] == "caseops-b5-proof"}
        moved = row["file"] in {file for file, _ in BATCH5_MOVED_CASES}
        cases = BATCH5_CASE_PROOF_SCOPES.get(row["file"])
        if cases is not None:
            if len(row["title_path"]) != 2 or row["title_path"][0] != row["file"]:
                raise EvidenceError("batch5_required_case_identity_mismatch")
            expected = cases.get(row["title_path"][1])
            if expected is None:
                raise EvidenceError("batch5_required_case_identity_mismatch")
        else:
            expected = "legacy-workflow-outcome" if moved else BATCH5_PROOF_SCOPES[row["file"]]
        if (not moved and declared != {expected}) or (moved and declared and declared != {expected}):
            raise EvidenceError("batch5_proof_scope_mismatch")
        scopes.append({"id": row["id"], "file": row["file"], "scope": expected})
    return scopes


def _batch5_source_hashes(root):
    files = ("playwright.app.config.ts", "playwright.prod-ram.config.ts",
             "scripts/prod_playwright_evidence.py", REPORTER,
             *(f"tests/e2e/{file}" for file in (*BATCH5_FILES, *(file for file, _ in BATCH5_MOVED_CASES))))
    if any(not (root / file).is_file() or (root / file).is_symlink() for file in files):
        raise EvidenceError("missing_or_linked_batch5_source")
    return {file: _hash(root / file) for file in files}


def _app_skip_identity(row):
    return row["project_name"], row["file"], tuple(row["title_path"])


def _check_app_selection(binding, selected, canonical, *, execution=False):
    invocation = _app_project_partition(binding)
    if invocation is None:
        raise EvidenceError("unreviewed_app_project_binding")
    project = APP_PROJECT_PARTITIONS[invocation]
    expected = [row for row in _app_inventory(canonical) if row["project_name"] == project]
    if (selected["configuration"] != canonical["configuration"]
            # FullConfig retains every declaration even for --project. Only
            # native test rows are selected; the declaration map stays whole.
            or selected["projects"] != canonical["projects"]
            or [_tester_case_identity(row) for row in selected["tests"]]
            != [_tester_case_identity(row) for row in expected]):
        raise EvidenceError("app_project_selection_mismatch")
    if not execution:
        if (selected["global_error_count"] or selected["report_status"] != "passed"
                or any(row["results"] for row in selected["tests"])
                or any(selected["stats"][key] for key in ("expected", "unexpected", "flaky"))):
            raise EvidenceError("app_project_discovery_executed_tests")
        return
    allowed_skips = {row for row in APP_EXPECTED_SKIPS if row[0] == project}
    actual_skips = set()
    for row in selected["tests"]:
        attempts = row["results"]
        if len(attempts) != 1 or attempts[0]["retry"] != 0:
            raise EvidenceError("app_project_attempt_mismatch")
        actual = attempts[0]["status"]
        if actual == "skipped" and row["status"] == "skipped":
            actual_skips.add(_app_skip_identity(row))
        elif actual != "passed" or row["status"] != "expected":
            raise EvidenceError("app_project_case_not_passed")
    if actual_skips != allowed_skips:
        raise EvidenceError("app_project_skip_inventory_mismatch")


def _tester_partition(binding):
    invocation = binding["invocation"]
    _require_current_oct13_namespace(invocation, project=binding.get("project"))
    if invocation not in TESTER_PARTITIONS:
        return None
    if binding["config"] != "playwright.prod-ram.config.ts":
        raise EvidenceError("tester_partition_config_mismatch")
    if binding["project"] != TESTER_PARTITIONS[invocation]:
        raise EvidenceError("tester_partition_project_mismatch")
    if "--workers=1" not in binding["arguments"] or "--retries=0" not in binding["arguments"]:
        raise EvidenceError("tester_partition_serial_zero_retry_required")
    return invocation


def _tester_inventory(canonical):
    projects = set(TESTER_PARTITIONS.values())
    rows = [row for row in canonical["tests"] if row["project_name"] in projects]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise EvidenceError("empty_or_duplicate_tester_canonical_inventory")
    expected_counts = Counter()
    for invocation, count in TESTER_PARTITION_COUNTS.items():
        expected_counts[TESTER_PARTITIONS[invocation]] += count
    if Counter(row["project_name"] for row in rows) != expected_counts:
        raise EvidenceError("reviewed_tester_partition_counts_mismatch")
    semantic_cases = {
        (row["file"], tuple(row["title_path"]), row["repeat_each_index"])
        for row in rows
    }
    if len(semantic_cases) != len(rows):
        raise EvidenceError("duplicate_tester_semantic_identity")
    for project, expected_files in (
        (TESTER_PARTITIONS["tester-index"], INDEX_FILES), (OCT13_PROJECT, OCT13_FILES)
    ):
        actual = Counter(
            Path(row["file"]).name
            for row in rows
            if row["project_name"] == project
        )
        if actual != Counter(expected_files):
            raise EvidenceError("mandatory_tester_partition_inventory_mismatch")
    core = [row for row in rows if row["project_name"] == TESTER_PARTITIONS["tester"]]
    if not core or any(Path(row["file"]).name in INDEX_FILES | OCT13_FILES for row in core):
        raise EvidenceError("tester_core_partition_overlap")
    if sum(Path(row["file"]).name == TESTER_CATALOG_FILE for row in core) != (
        TESTER_PARTITION_COUNTS["tester-catalog"]
    ):
        raise EvidenceError("mandatory_tester_catalog_inventory_mismatch")
    return rows


def _tester_selected_rows(canonical, invocation):
    rows = [row for row in _tester_inventory(canonical)
            if row["project_name"] == TESTER_PARTITIONS[invocation]]
    if invocation in {"tester", "tester-catalog"}:
        rows = [row for row in rows if (Path(row["file"]).name == TESTER_CATALOG_FILE)
                == (invocation == "tester-catalog")]
    elif invocation in OCT13_PARTITION_FILES:
        rows = [row for row in rows if Path(row["file"]).name in OCT13_PARTITION_FILES[invocation]]
    return rows


def _tester_file_filters(binding):
    invocation = _tester_partition(binding)
    if invocation in OCT13_PARTITION_FILES:
        files = "|".join(re.escape(name) for name in OCT13_PARTITION_FILES[invocation])
        return [rf"(?:^|[/\\])(?:{files})$"]
    if invocation not in {"tester", "tester-catalog"}:
        return []
    catalog = rf"(?:^|[/\\]){re.escape(TESTER_CATALOG_FILE)}$"
    return [catalog if invocation == "tester-catalog" else rf"^(?!.*{catalog}).*$"]


def _check_tester_selection(binding, discovery, canonical):
    invocation = _tester_partition(binding)
    if invocation is None:
        raise EvidenceError("unreviewed_tester_partition_binding")
    expected = [
        _tester_case_identity(row) for row in _tester_selected_rows(canonical, invocation)
    ]
    if [_tester_case_identity(row) for row in discovery["tests"]] != expected:
        raise EvidenceError("tester_partition_selection_mismatch")


def _tester_case_identity(row):
    return (
        row["id"], _identity(row), tuple(row["tags"]),
        row["retries"], row["repeat_each_index"],
    )


def _check_mandatory_cases(batch, project, cases, binding, document, *, execution=False):
    """Require exactly ``cases`` (file, title), each an actual zero-retry pass."""
    if (
        binding["config"] != "playwright.prod-ram.config.ts"
        or binding["project"] != project
        or not {
            "--config=playwright.prod-ram.config.ts", f"--project={project}",
            "--workers=1", "--retries=0",
        }.issubset(binding["arguments"])
        or type(document["configuration"]["workers"]) is not int
        or document["configuration"]["workers"] != 1
    ):
        raise EvidenceError(f"{batch}_role_binding_mismatch")
    rows = document["tests"]
    # Evidence stores titles in their privacy-minimized form (a query string is redacted).
    expected = Counter(
        (_safe(file, {}), (_safe(file, {}), _safe(title, {}))) for file, title in cases
    )
    if len(rows) != len(cases) or Counter(
        (row["file"], tuple(row["title_path"])) for row in rows
    ) != expected or any(
        row["project_id"] != project or row["project_name"] != project
        or type(row["retries"]) is not int or row["retries"] != 0
        or type(row["repeat_each_index"]) is not int or row["repeat_each_index"] != 0
        for row in rows
    ):
        raise EvidenceError(f"mandatory_{batch}_case_inventory_mismatch")
    if any(row["expected_status"] != "passed" for row in rows) or execution and (
        any(
            row["status"] != "expected" or len(row["results"]) != 1
            or row["results"][0]["status"] != "passed"
            or type(row["results"][0]["retry"]) is not int or row["results"][0]["retry"] != 0
            for row in rows
        )
        or document["report_status"] != "passed" or document["global_error_count"] != 0
    ):
        raise EvidenceError(f"mandatory_{batch}_case_not_passed")


def _check_batch3_evidence(binding, document, *, execution=False):
    expected = BATCH3_MANDATORY_CASES.get(binding["invocation"])
    if expected is None:
        return
    project, file, title = expected
    _check_mandatory_cases(
        "batch3", project, ((file, title),), binding, document, execution=execution,
    )


def _check_batch4_evidence(binding, document, *, execution=False):
    expected = BATCH4_MANDATORY_CASES.get(binding["invocation"])
    if expected is None:
        return
    project, cases = expected
    _check_mandatory_cases("batch4", project, cases, binding, document, execution=execution)


def batch4_governance_state(root: Path) -> bool:
    """Return the serving release's checked-in rule-governance switch, strictly."""
    try:
        state = _json(root / GOVERNANCE_STATE)
    except EvidenceError:
        raise EvidenceError("invalid_rule_governance_state") from None
    if (
        not isinstance(state, dict) or set(state) != GOVERNANCE_STATE_KEYS
        or type(state["schema_version"]) is not int or state["schema_version"] != 1
        or type(state["enabled"]) is not bool
    ):
        raise EvidenceError("invalid_rule_governance_state")
    return state["enabled"]


def _check_notes22_evidence(binding, document, *, execution=False):
    _require_current_oct13_namespace(binding["invocation"], project=binding.get("project"))
    if binding["invocation"] != "test-legal-write-oct13-b":
        return
    project = "test-legal-write-prod-chromium"
    file = "ram-2026-10-22-prod.spec.ts"
    title = "NOTES22 newest three of four saved notes persist after reload at 1280px and 393px"
    if (
        binding["config"] != "playwright.prod-ram.config.ts"
        or binding["project"] != project
        or not {"--config=playwright.prod-ram.config.ts", f"--project={project}",
                "--workers=1", "--retries=0"}.issubset(binding["arguments"])
        or type(document["configuration"]["workers"]) is not int
        or document["configuration"]["workers"] != 1
    ):
        raise EvidenceError("notes22_role_binding_mismatch")
    rows = [row for row in document["tests"] if row["file"] == file]
    if len(rows) != 1:
        raise EvidenceError("mandatory_notes22_case_inventory_mismatch")
    row = rows[0]
    if (
        row["project_id"] != project or row["project_name"] != project
        or row["title_path"] != [file, title]
        or type(row["retries"]) is not int or row["retries"] != 0
        or type(row["repeat_each_index"]) is not int or row["repeat_each_index"] != 0
    ):
        raise EvidenceError("mandatory_notes22_case_inventory_mismatch")
    if row["expected_status"] != "passed" or execution and (
        row["status"] != "expected" or len(row["results"]) != 1
        or row["results"][0]["status"] != "passed"
        or type(row["results"][0]["retry"]) is not int or row["results"][0]["retry"] != 0
        or document["report_status"] != "passed" or document["global_error_count"] != 0
    ):
        raise EvidenceError("mandatory_notes22_case_not_passed")


def _json(path: Path):
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise EvidenceError("missing_or_oversized_report")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError):
        raise EvidenceError("invalid_utf8_json") from None


def _write(path: Path, value) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(value, env) -> str:
    result = str(value)
    for key, secret in env.items():
        if (
            re.search(r"PASSWORD|SECRET|TOKEN|API_KEY|COOKIE|AUTH", key, re.I)
            and len(secret) >= 4
        ):
            result = result.replace(secret, "[redacted]")
    # Annotation descriptions are evidence, not a response-body or attachment channel.
    if re.search(
        r"[{}<>]|authorization\s*:|cookie\s*:|\b(?:body|payload)\s*[:=]", result, re.I
    ):
        return "[redacted structured annotation]"
    result = re.sub(r"https?://\S+", "[url-redacted]", result)
    result = re.sub(
        r"\S*\?\S+|\bBearer\s+\S+", "[query-or-token-redacted]", result, flags=re.I
    )
    result = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[email-redacted]", result)
    return result


def _annotations(items, env):
    return [
        {
            "type": _safe(item.get("type", ""), env),
            "description": _safe(item.get("description", ""), env),
        }
        for item in items
    ]


def _inventory(document, env):
    rows = []

    def visit(suite, titles):
        titles = [*titles, suite.get("title", "")]
        for spec in suite.get("specs", []):
            for ordinal, test in enumerate(spec.get("tests", [])):
                rows.append(
                    {
                        "id": f"{spec['id']}:{test['projectId']}:{ordinal}",
                        "native_spec_id": spec["id"],
                        "file": _safe(spec["file"], env),
                        "line": spec["line"],
                        "column": spec.get("column", 0),
                        "tags": spec["tags"],
                        "title_path": [
                            _safe(title, env) for title in [*titles, spec["title"]]
                        ],
                        "project_id": test["projectId"],
                        "project_name": test["projectName"],
                        "expected_status": test.get("expectedStatus"),
                        "status": test.get("status"),
                        "timeout": test["timeout"],
                        "retries": test["retries"],
                        "repeat_each_index": test["repeatEachIndex"],
                        "annotations": _annotations(test.get("annotations", []), env),
                        "results": [
                            {
                                "status": result["status"],
                                "retry": result["retry"],
                                "duration": result.get("duration", 0),
                                "worker_index": result.get("workerIndex"),
                                "parallel_index": result.get("parallelIndex"),
                                "start_time": result.get("startTime"),
                                "error_count": len(result.get("errors", [])),
                                "network_evidence": result.get(
                                    "networkEvidence", {"status": "absent"}
                                ),
                                "annotations": _annotations(
                                    result.get("annotations", []), env
                                ),
                            }
                            for result in test.get("results", [])
                        ],
                    }
                )
        for child in suite.get("suites", []):
            visit(child, titles)

    for suite in document.get("suites", []):
        visit(suite, [])
    ids = [row["id"] for row in rows]
    if not ids or len(set(ids)) != len(ids):
        raise EvidenceError("empty_or_duplicate_inventory")
    return rows


def _native(path, binding, env, phase):
    document = _json(path)
    if (
        document.get("release_sha") != binding["release_sha"]
        or document.get("invocation") != binding["invocation"]
        or document.get("phase") != phase
    ):
        raise EvidenceError("native_invocation_binding_mismatch")
    config = document["config"]
    if Path(config["configFile"]).resolve() != Path(binding["config_path"]).resolve():
        raise EvidenceError("native_config_mismatch")
    root = Path(binding["config_path"]).parent.resolve()
    for directory in [config["rootDir"], *[p["testDir"] for p in config["projects"]]]:
        if not Path(directory).resolve().is_relative_to(root):
            raise EvidenceError("native_test_directory_outside_checkout")
    projects = [
        {
            **{
                key: p[key]
                for key in ("id", "name", "retries", "repeatEach", "timeout")
            },
            "test_directory": Path(p["testDir"]).resolve().relative_to(root).as_posix(),
        }
        for p in config["projects"]
    ]
    options = dict(argument[2:].split("=", 1) for argument in binding["arguments"])
    if (
        type(config["workers"]) is not int
        or config["workers"] <= 0
        or ("workers" in options and config["workers"] != int(options["workers"]))
        or ("retries" in options and options["retries"] != "0")
        or len({(p["id"], p["name"]) for p in projects}) != len(projects)
        or any(
            type(p["retries"]) is not int
            or p["retries"] != 0
            or type(p["repeatEach"]) is not int
            or p["repeatEach"] != 1
            for p in projects
        )
    ):
        raise EvidenceError("native_zero_retry_configuration_mismatch")
    rows = _inventory(document, env)
    for row in rows:
        source = (Path(config["rootDir"]) / row["file"]).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise EvidenceError("native_spec_outside_or_missing_from_checkout")
    requested = binding["project"]
    if requested and requested not in {row["project_name"] for row in rows}:
        raise EvidenceError("native_project_mismatch")
    if any(
        (row["project_id"], row["project_name"])
        not in {(p["id"], p["name"]) for p in projects}
        for row in rows
    ):
        raise EvidenceError("undeclared_native_project")
    for row in rows:
        if (
            type(row["retries"]) is not int
            or row["retries"] != 0
            or type(row["repeat_each_index"]) is not int
            or row["repeat_each_index"] != 0
            or type(row["line"]) is not int
            or row["line"] < 1
            or type(row["column"]) is not int
            or row["column"] < 1
            or not all(isinstance(title, str) for title in row["title_path"])
            or not isinstance(row["tags"], list)
            or not all(isinstance(tag, str) for tag in row["tags"])
        ):
            raise EvidenceError("native_case_metadata_mismatch")
    stats = {
        key: document["stats"][key]
        for key in (
            "startTime",
            "duration",
            "expected",
            "skipped",
            "unexpected",
            "flaky",
        )
    }
    if sum(stats[key] for key in ("expected", "skipped", "unexpected", "flaky")) != len(
        rows
    ):
        raise EvidenceError("native_stats_inventory_mismatch")
    if Counter(row["status"] for row in rows) != Counter(
        {key: stats[key] for key in ("expected", "skipped", "unexpected", "flaky")}
    ):
        raise EvidenceError("native_stats_outcome_mismatch")
    return {
        "binding": binding,
        "projects": projects,
        "configuration": {
            "workers": config["workers"],
            "root_directory": Path(config["rootDir"])
            .resolve()
            .relative_to(root)
            .as_posix(),
        },
        "tests": rows,
        "stats": stats,
        "global_error_count": len(document.get("errors", [])),
        "report_status": document["status"],
    }


def _identity(row):
    return (
        row["native_spec_id"],
        row["project_id"],
        row["project_name"],
        row["file"],
        row["line"],
        row["column"],
        tuple(row["title_path"]),
    )


def _progress(path: Path, binding, result, env, native_errors) -> None:
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise EvidenceError("missing_or_oversized_progress")
    try:
        content = path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in content.splitlines()]
    except (UnicodeError, ValueError):
        raise EvidenceError("invalid_progress_json") from None
    if not content.endswith("\n") or len(rows) < 2:
        raise EvidenceError("incomplete_progress")
    if not all(isinstance(row, dict) for row in rows):
        raise EvidenceError("progress_event_schema_mismatch")
    started, completion = rows[0], rows[-1]
    if (
        set(started) != {"event", "release_sha", "invocation"}
        or started["event"] != "invocation_started"
        or started["release_sha"] != binding["release_sha"]
        or started["invocation"] != binding["invocation"]
        or set(completion) != {"event", "status", "test_count"}
        or completion["event"] != "session_finished"
        or completion["status"] != result["report_status"]
        or type(completion["test_count"]) is not int
        or completion["test_count"] != len(result["tests"])
    ):
        raise EvidenceError("progress_binding_or_completion_mismatch")
    collections = [row for row in rows[1:-1] if row.get("event") == "collection"]
    if len(collections) != 1:
        raise EvidenceError("progress_collection_mismatch")
    collection = collections[0]
    if (
        set(collection) != {"event", "release_sha", "invocation", "suites"}
        or collection["release_sha"] != binding["release_sha"]
        or collection["invocation"] != binding["invocation"]
    ):
        raise EvidenceError("progress_collection_mismatch")
    collected = _inventory(collection, env)

    def identity(row):
        return (_identity(row), row["tags"], row["retries"], row["repeat_each_index"])

    if [identity(row) for row in collected] != [
        identity(row) for row in result["tests"]
    ] or any(row["results"] for row in collected):
        raise EvidenceError("progress_collection_mismatch")
    expected = {row["id"]: row for row in result["tests"]}
    observed = set()
    errors = []
    collection_seen = False
    for packet in rows[1:-1]:
        if packet.get("event") == "collection":
            collection_seen = True
            continue
        if packet.get("event") == "global_error":
            if set(packet) != {"event", "error"}:
                raise EvidenceError("progress_event_schema_mismatch")
            errors.append(packet["error"])
            continue
        if (
            not collection_seen
            or set(packet) != {"event", "suites"}
            or packet["event"] != "test_end"
        ):
            raise EvidenceError("progress_event_schema_mismatch")
        attempts = _inventory(packet, env)
        if len(attempts) != 1:
            raise EvidenceError("progress_attempt_inventory_mismatch")
        row = attempts[0]
        if row["id"] in observed or row != expected.get(row["id"]):
            raise EvidenceError("progress_attempt_mismatch")
        observed.add(row["id"])
    if (
        observed != set(expected)
        or len(errors) != result["global_error_count"]
        or errors != native_errors
    ):
        raise EvidenceError("progress_missing_attempt_or_error")


def _reconcile(discovery, result):
    if (
        discovery["projects"] != result["projects"]
        or discovery["configuration"] != result["configuration"]
        or [
            (r["id"], _identity(r), r["tags"], r["retries"], r["repeat_each_index"])
            for r in discovery["tests"]
        ]
        != [
            (r["id"], _identity(r), r["tags"], r["retries"], r["repeat_each_index"])
            for r in result["tests"]
        ]
    ):
        raise EvidenceError("runtime_inventory_mismatch")
    for row in result["tests"]:
        attempts = row["results"]
        if (
            len(attempts) != 1
            or type(attempts[0]["retry"]) is not int
            or attempts[0]["retry"] != 0
        ):
            raise EvidenceError("native_zero_retry_attempt_mismatch")
        actual = attempts[0]["status"]
        if row["expected_status"] not in {"passed", "failed", "timedOut", "skipped"}:
            raise EvidenceError("native_expected_status_mismatch")
        outcome = (
            "skipped"
            if actual == "skipped"
            else ("expected" if actual == row["expected_status"] else "unexpected")
        )
        if actual != "interrupted" and row["status"] != outcome:
            raise EvidenceError("native_case_outcome_mismatch")


def _junit(raw: Path, output: Path | None, env, result):
    if not raw.is_file() or raw.stat().st_size > LIMIT:
        raise EvidenceError("missing_or_oversized_junit")
    try:
        tree = ET.parse(raw)
    except ET.ParseError:
        raise EvidenceError("invalid_junit") from None
    cases = list(tree.iter("testcase"))
    if len(cases) != len(result["tests"]):
        raise EvidenceError("junit_inventory_mismatch")
    if len(list(tree.iter("skipped"))) != result["stats"]["skipped"]:
        raise EvidenceError("junit_skipped_mismatch")
    if (
        len(list(tree.iter("failure"))) + len(list(tree.iter("error")))
        != result["stats"]["unexpected"]
    ):
        raise EvidenceError("junit_failed_mismatch")
    actual = []
    root = tree.getroot()
    if root.tag != "testsuites" or any(s.tag != "testsuite" for s in root):
        raise EvidenceError("junit_structure_mismatch")
    for suite in root:
        native_cases = suite.findall("testcase")
        if len(native_cases) != 1:
            raise EvidenceError("junit_structure_mismatch")
        case = native_cases[0]
        try:
            titles = json.loads(case.attrib["caseops-title-path"])
            if (
                not isinstance(titles, list)
                or len(titles) < 2
                or not all(isinstance(title, str) for title in titles)
            ):
                raise ValueError
            line, column = int(case.attrib["line"]), int(case.attrib["column"])
            identity = (
                case.attrib["caseops-id"],
                case.attrib["caseops-project-id"],
                case.attrib["caseops-project-name"],
                case.attrib["file"],
                line,
                column,
                tuple(titles),
            )
            outcome = case.attrib["caseops-outcome"]
        except (KeyError, ValueError, TypeError):
            raise EvidenceError("junit_identity_mismatch") from None
        if (
            case.get("line") != str(line)
            or case.get("column") != str(column)
            or case.get("name") != " \u203a ".join(titles[1:])
            or case.get("classname") != titles[0]
            or suite.get("name") != titles[0]
            or suite.get("hostname") != identity[2]
            or suite.get("tests") != "1"
            or suite.get("errors") != "0"
            or suite.get("failures") != str(int(outcome == "unexpected"))
            or suite.get("skipped") != str(int(outcome == "skipped"))
            or len(case.findall("failure")) != int(outcome == "unexpected")
            or len(case.findall("skipped")) != int(outcome == "skipped")
            or case.findall("error")
            or outcome not in {"expected", "skipped", "unexpected", "flaky"}
        ):
            raise EvidenceError("junit_case_outcome_or_display_mismatch")
        actual.append((identity, outcome))
    # Multiplicity is part of the proof: never deduplicate or match joined titles.
    if Counter(actual) != Counter(
        (_identity(row), row["status"]) for row in result["tests"]
    ):
        raise EvidenceError("junit_identity_outcome_mismatch")
    if output is None:
        return
    # Native XML structure/outcomes survive; body/error/output/attachment data do not.
    for element in tree.iter():
        element.attrib = {
            key: value
            if element.tag == "testcase" and key == "caseops-title-path"
            else _safe(value, env)
            for key, value in element.attrib.items()
            if key
            in {
                "name",
                "classname",
                "file",
                "time",
                "tests",
                "failures",
                "errors",
                "skipped",
                "timestamp",
                "type",
                "value",
                "hostname",
                "line",
                "column",
                "caseops-id",
                "caseops-project-id",
                "caseops-project-name",
                "caseops-title-path",
                "caseops-outcome",
            }
            or (element.tag == "skipped" and key == "message")
        }
        if element.tag in {"failure", "error"}:
            element.text = "Native test failure; private detail omitted."
        elif element.tag == "skipped":
            element.text = _safe(element.text or "", env)
        else:
            element.text = None
        element.tail = None
        for child in list(element):
            if child.tag not in {
                "testsuite",
                "testcase",
                "properties",
                "property",
                "skipped",
                "failure",
                "error",
            }:
                element.remove(child)
    with output.open("xb") as stream:
        tree.write(stream, encoding="utf-8", xml_declaration=True)


def _binding(root, invocation, args, env):
    expected = env.get("CASEOPS_EXPECTED_RELEASE_SHA", "")
    if not SHA.fullmatch(expected) or not INVOCATION.fullmatch(invocation):
        raise EvidenceError("invalid_release_or_invocation")
    _require_current_oct13_namespace(invocation)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != expected:
        raise EvidenceError("checkout_sha_mismatch")
    options = {}
    for argument in args:
        if not re.fullmatch(
            r"--(config|project|workers|retries|reporter|output)=[\w./-]+", argument
        ):
            raise EvidenceError("unreviewed_invocation_argument")
        key, value = argument[2:].split("=", 1)
        if key in options:
            raise EvidenceError("duplicate_invocation_option")
        options[key] = value
    if "config" not in options or "output" not in options:
        raise EvidenceError("missing_invocation_option")
    config = root / options["config"]
    if not config.resolve().is_relative_to(root.resolve()) or not config.is_file():
        raise EvidenceError("missing_release_config")
    if options.get("reporter") != "list":
        raise EvidenceError("unreviewed_reporter")
    binding = {
        "release_sha": expected,
        "checkout_sha": head,
        "invocation": invocation,
        "config": options["config"],
        "config_path": str(config.resolve()),
        "config_sha256": _hash(config),
        "project": options.get("project"),
        "arguments": args,
        "capture_version": 2,
    }
    _tester_partition(binding)
    _app_project_partition(binding)
    _batch5_partition(binding)
    return binding


def run(root: Path, invocation: str, args, env=None, launch=subprocess.run) -> int:
    env = dict(os.environ if env is None else env)
    binding = _binding(root, invocation, args, env)
    batch5_sources = _batch5_source_hashes(root) if invocation in BATCH5_PROJECTS else None
    destination = root / EVIDENCE / invocation
    destination.mkdir(parents=True, exist_ok=False)
    # Absolute host paths are checked internally, but never archived.
    public_binding = {
        key: value for key, value in binding.items() if key != "config_path"
    }
    _write(
        destination / "invocation.json",
        {
            "binding": public_binding,
            "source_owned_file_filters": _tester_file_filters(binding),
            "invocation_id": str(uuid4()),
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    marker = {
        "binding": public_binding,
        "phase": "discovery",
        "discovery_exit": None,
        "execution_exit": None,
        "completed": False,
    }
    code = 1
    try:
        cli = root / "node_modules/@playwright/test/cli.js"
        node = shutil.which("node")
        if not node or not cli.is_file() or not (root / REPORTER).is_file():
            raise EvidenceError("missing_release_playwright_cli")
        child_env = {
            key: value for key, value in env.items() if key not in OUTPUT_VARIABLES
        }
        child_env["CASEOPS_PW_EVIDENCE_JSON_FILE"] = str(
            destination / "native-discovery.json"
        )
        child_env["CASEOPS_PW_EVIDENCE_INVOCATION"] = invocation
        child_env["CASEOPS_PW_EVIDENCE_PHASE"] = "discovery"
        discovery_args = [arg for arg in args if not arg.startswith("--reporter=")]
        selected_args = [*discovery_args, *_tester_file_filters(binding)]
        process = launch(
            [
                node,
                str(cli),
                "test",
                *selected_args,
                "--list",
                f"--reporter={REPORTER}",
            ],
            cwd=root,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        marker["discovery_exit"] = process.returncode
        if process.returncode:
            raise EvidenceError("discovery_process_failed")
        discovery = _native(
            destination / "native-discovery.json", binding, env, "discovery"
        )
        if (
            discovery["global_error_count"]
            or any(
                discovery["stats"][key] for key in ("expected", "unexpected", "flaky")
            )
            or any(row["results"] for row in discovery["tests"])
        ):
            raise EvidenceError("discovery_executed_tests")
        discovery["binding"] = public_binding
        _write(destination / "discovery.json", discovery)
        _check_batch3_evidence(binding, discovery)
        _check_batch4_evidence(binding, discovery)
        _check_notes22_evidence(binding, discovery)
        partition = _tester_partition(binding)
        app_partition = _app_project_partition(binding)
        batch5_partition = _batch5_partition(binding)
        if partition is not None or app_partition is not None or batch5_partition is not None:
            canonical_invocation = f"{invocation}-canonical"
            canonical_directory = root / EVIDENCE / canonical_invocation
            canonical_directory.mkdir(parents=True, exist_ok=False)
            canonical_args = [arg for arg in discovery_args if not arg.startswith("--project=")]
            canonical_binding = {
                **binding,
                "invocation": canonical_invocation,
                "project": None,
                "arguments": [arg for arg in args if not arg.startswith("--project=")],
            }
            canonical_env = {
                **child_env,
                "CASEOPS_PW_EVIDENCE_INVOCATION": canonical_invocation,
                "CASEOPS_PW_EVIDENCE_JSON_FILE": str(canonical_directory / "native-discovery.json"),
            }
            process = launch(
                [node, str(cli), "test", *canonical_args, "--list", f"--reporter={REPORTER}"],
                cwd=root,
                env=canonical_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            marker["canonical_discovery_exit"] = process.returncode
            if process.returncode:
                raise EvidenceError("canonical_tester_discovery_failed")
            canonical_path = canonical_directory / "native-discovery.json"
            canonical = _native(canonical_path, canonical_binding, env, "discovery")
            if canonical["global_error_count"] or any(row["results"] for row in canonical["tests"]):
                raise EvidenceError("canonical_tester_discovery_executed_tests")
            canonical["binding"] = {
                key: value for key, value in canonical_binding.items() if key != "config_path"
            }
            if partition is not None:
                _check_tester_selection(binding, discovery, canonical)
            elif batch5_partition is not None:
                _check_batch5_selection(binding, discovery, canonical)
            else:
                _check_app_selection(binding, discovery, canonical)
            with (destination / "canonical-native-discovery.json").open("xb") as stream:
                stream.write(canonical_path.read_bytes())
            _write(destination / "canonical-discovery.json", canonical)
            canonical_path.unlink()
            canonical_directory.rmdir()
        marker["phase"] = "execution"
        child_env["CASEOPS_PW_EVIDENCE_JSON_FILE"] = str(
            destination / "native-results.json"
        )
        child_env["CASEOPS_PW_EVIDENCE_JUNIT_FILE"] = str(
            destination / "native-results.xml"
        )
        child_env["CASEOPS_PW_EVIDENCE_PHASE"] = "execution"
        effective = [
            f"--reporter=list,{REPORTER}" if arg == "--reporter=list" else arg
            for arg in args
        ]
        effective.extend(_tester_file_filters(binding))
        process = launch(
            [node, str(cli), "test", *effective],
            cwd=root,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        marker["execution_exit"] = process.returncode
        result = _native(destination / "native-results.json", binding, env, "execution")
        result["binding"] = public_binding
        _write(destination / "results.json", result)
        _reconcile(discovery, result)
        if app_partition is not None:
            _check_app_selection(binding, result, canonical, execution=True)
        if batch5_partition is not None:
            _check_batch5_selection(binding, result, canonical, execution=True)
        _check_batch3_evidence(binding, result, execution=True)
        _check_batch4_evidence(binding, result, execution=True)
        _check_notes22_evidence(binding, result, execution=True)
        if (
            process.returncode < 0
            or result["report_status"] == "interrupted"
            or any(
                r["status"] == "interrupted"
                for row in result["tests"]
                for r in row["results"]
            )
        ):
            raise EvidenceError("interrupted_execution")
        if any(
            not row["results"]
            or any(
                r["status"]
                not in {
                    "passed",
                    "failed",
                    "timedOut",
                    "skipped",
                }
                for r in row["results"]
            )
            for row in result["tests"]
        ):
            raise EvidenceError("missing_or_invalid_runtime_result")
        _junit(
            destination / "native-results.xml", destination / "results.xml", env, result
        )
        _progress(
            destination / "progress.jsonl",
            binding,
            result,
            env,
            _json(destination / "native-results.json").get("errors", []),
        )
        if _hash(root / binding["config"]) != binding["config_sha256"]:
            raise EvidenceError("config_changed_during_execution")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if head != binding["checkout_sha"]:
            raise EvidenceError("checkout_changed_during_execution")
        if batch5_sources is not None and _batch5_source_hashes(root) != batch5_sources:
            raise EvidenceError("batch5_source_changed_during_execution")
        marker["phase"] = "complete"
        marker["completed"] = True
        code = process.returncode
        if (
            result["report_status"] != "passed"
            or result["global_error_count"]
            or any(row["status"] == "unexpected" for row in result["tests"])
        ):
            code = code or 1
        _write(
            destination / "completion.json",
            {
                **marker,
                "finished_at": datetime.now(UTC).isoformat(),
                "test_count": len(result["tests"]),
                **({"batch5_proof_scopes": _batch5_proofs(result)} if batch5_partition is not None else {}),
                **({"batch5_source_sha256": batch5_sources} if batch5_partition is not None else {}),
                "sha256": {
                    name: _hash(destination / name)
                    for name in sorted(
                        REPORT_FILES | (TESTER_CANONICAL_FILES
                                        if partition is not None or app_partition is not None or batch5_partition is not None
                                        else set())
                    )
                },
            },
        )
    except (
        EvidenceError,
        KeyError,
        TypeError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        marker["incomplete_reason"] = (
            str(error) if isinstance(error, EvidenceError) else type(error).__name__
        )
    finally:
        _write(
            destination / "exit.json",
            {
                **marker,
                "wrapper_exit": code,
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
        print(
            json.dumps(
                {
                    "invocation": invocation,
                    "release_sha": binding["release_sha"],
                    "completed": marker["completed"],
                    "exit": code,
                }
            )
        )
    return code


def _app_native_fields(document):
    """Validate the new App reporter's raw schema before normalization."""
    import math

    def refuse():
        raise EvidenceError("app_raw_native_value_mismatch")

    def fields(value, *, strings="", counts="", signed="", numbers="",
               booleans="", arrays="", objects="", nullable="", required=""):
        groups = {"strings": strings.split(), "counts": counts.split(),
                  "signed": signed.split(), "numbers": numbers.split(),
                  "booleans": booleans.split(), "arrays": arrays.split(),
                  "objects": objects.split(), "nullable": nullable.split()}
        allowed = {key for names in groups.values() for key in names}
        if not isinstance(value, dict) or not set(value) <= allowed:
            raise EvidenceError("app_raw_native_unreviewed_field")
        if not set(required.split()) <= set(value):
            refuse()
        for group, names in groups.items():
            for key in names:
                if key not in value:
                    continue
                item = value[key]
                valid = {
                    "strings": lambda: type(item) is str,
                    "counts": lambda: type(item) is int and 0 <= item <= 9007199254740991,
                    "signed": lambda: type(item) is int and -1 <= item <= 9007199254740991,
                    "numbers": lambda: type(item) in (int, float) and 0 <= item <= 9007199254740991 and math.isfinite(item),
                    "booleans": lambda: type(item) is bool,
                    "arrays": lambda: type(item) is list,
                    "objects": lambda: type(item) is dict,
                    "nullable": lambda: item is None or type(item) is str,
                }[group]()
                if not valid:
                    refuse()

    def timestamp(value):
        if type(value) is not str or not re.fullmatch(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", value):
            refuse()
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            refuse()

    def safe_string(value):
        if type(value) is not str or _safe(value, {}) != value or re.search(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
            refuse()

    def location(value):
        fields(value, strings="file", counts="line column", required="file")
        if (Path(value["file"]).is_absolute() or ".." in Path(value["file"]).parts
                or not re.fullmatch(r"[\w./-]+\.[cm]?[jt]sx?", value["file"])
                or any(value[key] < 1 for key in ("line", "column") if key in value)):
            refuse()

    def annotations(values):
        for value in values:
            fields(value, strings="type description", objects="location", required="type")
            for key in ("type", "description"):
                if key in value:
                    safe_string(value[key])
            if "location" in value:
                location(value["location"])

    def errors(values):
        for value in values:
            fields(value, strings="message", objects="location", required="message")
            if value["message"] != "[redacted native test error; outcome retained]":
                refuse()
            if "location" in value:
                location(value["location"])

    def network(value):
        if type(value) is not dict:
            refuse()
        status = value.get("status")
        if status == "absent":
            fields(value, strings="status", required="status")
            return
        if status == "rejected":
            fields(value, strings="status reason", required="status reason")
            if value["reason"] not in {
                    "type_or_path", "body_bound", "invalid_utf8", "invalid_json", "snapshot_schema",
                    "outcome", "record_schema", "response_schema", "transport_schema", "attachment_inventory"}:
                refuse()
            return
        if status != "retained":
            refuse()
        fields(value, strings="status name contentType", objects="snapshot",
               required="status name contentType snapshot")
        if value["name"] != "sanitized-network-evidence" or value["contentType"] != "application/json":
            refuse()
        snapshot = value["snapshot"]
        fields(snapshot, counts="schemaVersion omitted", booleans="drainTimedOut", arrays="records",
               required="schemaVersion omitted drainTimedOut records")
        if snapshot["schemaVersion"] != 1 or len(snapshot["records"]) > 64:
            refuse()
        routes = {
            "auth/session", "matter/bulk-update", "matter/attachment", "notice/attachment",
            "ip/title-interest", "ip/application", "calendar/events", "ip/renewal-tracker",
            "ip/madrid-list", "ip/madrid-workspace", "ip/foreign-associate-list",
            "ip/foreign-associate-workspace", "ip/recordal-list", "ip/recordal-workspace",
            "ip/portfolio-export-preview", "ip/portfolio-export", "ip/portfolio-export-status",
            "ip/portfolio-export-download", "ip/portfolio-export-retry", "web/sign-in", "web/app-navigation",
        }
        problems = {
            "database_lock_timeout", "database_busy", "database_unavailable", "invalid_token",
            "missing_bearer_token", "rate_limited", "capability_required", "role_required", "step_up_required",
            "mfa_enrollment_required", "validation_error",
        }
        transports = {
            "net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_CLOSED", "net::ERR_CONNECTION_REFUSED",
            "net::ERR_TIMED_OUT", "net::ERR_ABORTED", "net::ERR_FAILED", "net::ERR_INTERNET_DISCONNECTED",
            "net::ERR_NAME_NOT_RESOLVED", "net::ERR_SSL_PROTOCOL_ERROR", "unclassified_transport_failure",
        }
        for row in snapshot["records"]:
            if type(row) is not dict:
                refuse()
            outcome = row.get("outcome")
            if type(outcome) is not str or outcome not in {"response_completed", "transport_failed", "pending_at_test_end",
                               "response_unavailable", "diagnostic_unavailable"}:
                refuse()
            response = outcome == "response_completed"
            fields(row, strings="route method startedAt outcome" + (" failureCode" if outcome == "transport_failed" else ""),
                   nullable="finishedAt" + (" requestId problemType" if response else ""),
                   counts="status" if response else "",
                   required="route method startedAt finishedAt outcome" + (
                       " status requestId problemType" if response else " failureCode" if outcome == "transport_failed" else ""))
            if row["route"] not in routes or row["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                refuse()
            timestamp(row["startedAt"])
            if outcome == "pending_at_test_end":
                if row["finishedAt"] is not None:
                    refuse()
            else:
                timestamp(row["finishedAt"])
            if response:
                if not 100 <= row["status"] <= 599:
                    refuse()
                request_id = row["requestId"]
                if request_id is not None and not re.fullmatch(
                        r"(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})", request_id):
                    refuse()
                if row["problemType"] is not None and row["problemType"] not in problems:
                    refuse()
            elif outcome == "transport_failed" and row["failureCode"] not in transports:
                refuse()

    fields(document, objects="config stats", arrays="suites errors", strings="status release_sha invocation phase",
           required="config stats suites errors status release_sha invocation phase")
    fields(document["stats"], strings="startTime", numbers="duration", counts="expected skipped unexpected flaky",
           required="startTime duration expected skipped unexpected flaky")
    timestamp(document["stats"]["startTime"])
    fields(document["config"], strings="configFile rootDir", counts="workers", arrays="projects",
           required="configFile rootDir workers projects")
    for project in document["config"]["projects"]:
        fields(project, strings="id name testDir", counts="retries repeatEach timeout",
               required="id name testDir retries repeatEach timeout")
    errors(document["errors"])

    def visit(suites):
        for suite in suites:
            fields(suite, strings="title file", arrays="specs suites", required="title")
            safe_string(suite["title"])
            for spec in suite.get("specs", []):
                fields(spec, strings="title id file", counts="line column", booleans="ok", arrays="tags tests",
                       required="title id file line column tags tests")
                safe_string(spec["title"])
                for tag in spec["tags"]:
                    safe_string(tag)
                for test in spec["tests"]:
                    fields(test, counts="timeout retries repeatEachIndex", arrays="annotations results",
                           strings="expectedStatus projectId projectName status",
                           required="timeout retries repeatEachIndex annotations results expectedStatus projectId projectName status")
                    annotations(test["annotations"])
                    for attempt in test["results"]:
                        fields(attempt, signed="workerIndex parallelIndex", counts="retry", numbers="duration",
                               strings="status startTime", arrays="annotations errors", objects="networkEvidence",
                               required="status retry")
                        if "startTime" in attempt:
                            timestamp(attempt["startTime"])
                        annotations(attempt.get("annotations", []))
                        errors(attempt.get("errors", []))
                        if "networkEvidence" in attempt:
                            network(attempt["networkEvidence"])
            visit(suite.get("suites", []))
    visit(document["suites"])


def _validate_app_native(root, directory, binding, discovery, result, canonical):
    """Independently bind raw native channels; a rehashed envelope is not enough."""
    internal = {**binding, "config_path": str((root / binding["config"]).resolve())}
    for name, phase, normalized, selected_binding in (
        ("native-discovery.json", "discovery", discovery, internal),
        ("native-results.json", "execution", result, internal),
        ("canonical-native-discovery.json", "discovery", canonical, {
            **internal, "invocation": f'{binding["invocation"]}-canonical',
            "project": None,
            "arguments": [arg for arg in binding["arguments"]
                          if not arg.startswith("--project=")],
        }),
    ):
        _app_native_fields(_json(directory / name))
        observed = _native(directory / name, selected_binding, {}, phase)
        observed["binding"] = {
            key: value for key, value in selected_binding.items() if key != "config_path"
        }
        if observed != normalized:
            raise EvidenceError("app_raw_native_normalized_mismatch")
    if (_hash(root / binding["config"]) != binding["config_sha256"]
            or result["report_status"] != "passed"
            or result["global_error_count"] or result["stats"]["unexpected"]
            or result["stats"]["flaky"]):
        raise EvidenceError("app_project_source_or_result_mismatch")


def validate(root: Path, required, expected: str) -> None:
    if not SHA.fullmatch(expected) or not required:
        raise EvidenceError("empty_validation_scope")
    for invocation in required:
        if not INVOCATION.fullmatch(invocation):
            raise EvidenceError("invalid_validation_invocation")
        directory = root / EVIDENCE / invocation
        completion = _json(directory / "completion.json")
        exit_marker = _json(directory / "exit.json")
        if not completion["completed"] or not exit_marker["completed"]:
            raise EvidenceError("incomplete_invocation")
        binding = completion["binding"]
        partition = _tester_partition(binding)
        app_partition = _app_project_partition(binding)
        batch5_partition = _batch5_partition(binding)
        report_files = REPORT_FILES | (
            TESTER_CANONICAL_FILES
            if partition is not None or app_partition is not None or batch5_partition is not None else set()
        )
        if (
            binding["release_sha"] != expected
            or binding["checkout_sha"] != expected
            or binding["invocation"] != invocation
            or exit_marker["binding"] != binding
        ):
            raise EvidenceError("completion_release_mismatch")
        if exit_marker["wrapper_exit"] or completion["execution_exit"]:
            raise EvidenceError("failed_invocation")
        if (app_partition is not None or batch5_partition is not None) and (
            completion.get("phase") != "complete"
            or exit_marker.get("phase") != "complete"
            or completion.get("discovery_exit") != 0
            or completion.get("canonical_discovery_exit") != 0
            or exit_marker.get("discovery_exit") != 0
            or exit_marker.get("canonical_discovery_exit") != 0
            or exit_marker.get("execution_exit") != 0
        ):
            raise EvidenceError("app_project_nonterminal_native_exit")
        for name, digest in completion["sha256"].items():
            if name not in report_files:
                raise EvidenceError("unreviewed_evidence_file")
            if _hash(directory / name) != digest:
                raise EvidenceError("evidence_hash_mismatch")
        if set(completion["sha256"]) != report_files:
            raise EvidenceError("missing_required_evidence")
        for name in ("invocation.json", "discovery.json", "results.json"):
            if _json(directory / name)["binding"] != binding:
                raise EvidenceError("evidence_binding_mismatch")
        discovery = _json(directory / "discovery.json")
        result = _json(directory / "results.json")
        if partition is not None or app_partition is not None or batch5_partition is not None:
            canonical = _json(directory / "canonical-discovery.json")
            canonical_binding = canonical["binding"]
            if (
                canonical_binding != {
                    **binding,
                    "invocation": f"{invocation}-canonical",
                    "project": None,
                    "arguments": [
                        arg for arg in binding["arguments"] if not arg.startswith("--project=")
                    ],
                }
                or canonical["global_error_count"]
                or any(row["results"] for row in canonical["tests"])
            ):
                raise EvidenceError("canonical_tester_binding_mismatch")
            if partition is not None:
                _check_tester_selection(binding, discovery, canonical)
            elif batch5_partition is not None:
                _validate_app_native(root, directory, binding, discovery, result, canonical)
                _check_batch5_selection(binding, discovery, canonical)
                _check_batch5_selection(binding, result, canonical, execution=True)
                if completion.get("batch5_source_sha256") != _batch5_source_hashes(root):
                    raise EvidenceError("batch5_source_receipt_mismatch")
                if completion.get("batch5_proof_scopes") != _batch5_proofs(result):
                    raise EvidenceError("batch5_proof_receipt_mismatch")
            else:
                _validate_app_native(root, directory, binding, discovery, result, canonical)
                _check_app_selection(binding, discovery, canonical)
                _check_app_selection(binding, result, canonical, execution=True)
        if (
            completion["test_count"] <= 0
            or len(result["tests"]) != completion["test_count"]
            or [r["id"] for r in discovery["tests"]]
            != [r["id"] for r in result["tests"]]
        ):
            raise EvidenceError("completion_inventory_mismatch")
        _reconcile(discovery, result)
        _check_batch3_evidence(binding, discovery)
        _check_batch3_evidence(binding, result, execution=True)
        _check_batch4_evidence(binding, discovery)
        _check_batch4_evidence(binding, result, execution=True)
        _check_notes22_evidence(binding, discovery)
        _check_notes22_evidence(binding, result, execution=True)
        _junit(directory / "native-results.xml", None, {}, result)
        _junit(directory / "results.xml", None, {}, result)
        _progress(
            directory / "progress.jsonl",
            binding,
            result,
            {},
            _json(directory / "native-results.json").get("errors", []),
        )


def validate_tester_partition_union(root: Path, required, expected: str) -> None:
    if len(required) != len(TESTER_PARTITIONS) or set(required) != set(TESTER_PARTITIONS):
        raise EvidenceError("missing_or_duplicate_tester_partition")
    validate(root, required, expected)
    selected = []
    oct13_selected = []
    canonical_ids = None
    config_hash = None
    for invocation in TESTER_PARTITIONS:
        directory = root / EVIDENCE / invocation
        result = _json(directory / "results.json")
        binding = result["binding"]
        if _tester_partition(binding) != invocation:
            raise EvidenceError("unreviewed_tester_partition_binding")
        digest = binding["config_sha256"]
        if _hash(root / binding["config"]) != digest or (config_hash and config_hash != digest):
            raise EvidenceError("tester_partition_source_mismatch")
        config_hash = digest
        canonical = _tester_inventory(_json(directory / "canonical-discovery.json"))
        identities = [_tester_case_identity(row) for row in canonical]
        if canonical_ids is not None and canonical_ids != identities:
            raise EvidenceError("tester_canonical_inventories_disagree")
        canonical_ids = identities
        if invocation != "tester" and any(
            len(row["results"]) != 1 or row["results"][0]["status"] != "passed"
            or row["results"][0]["retry"] != 0 or row["status"] != "expected"
            for row in result["tests"]
        ):
            raise EvidenceError("mandatory_tester_partition_not_passed")
        selected.extend(_tester_case_identity(row) for row in result["tests"])
        if invocation in OCT13_PARTITION_FILES:
            oct13_selected.extend(_tester_case_identity(row) for row in result["tests"])
    if len(set(selected)) != len(selected) or Counter(selected) != Counter(canonical_ids):
        raise EvidenceError("tester_partition_union_mismatch")
    if oct13_selected != [_tester_case_identity(row) for row in canonical
                           if row["project_name"] == OCT13_PROJECT]:
        raise EvidenceError("oct13_partition_order_or_union_mismatch")


def validate_batch5_release_union(root: Path, required, expected: str):
    roles = [*TESTER_PARTITIONS, *BATCH5_PROJECTS]
    if len(required) != len(roles) or set(required) != set(roles):
        raise EvidenceError("missing_or_duplicate_batch5_release_role")
    validate_tester_partition_union(root, list(TESTER_PARTITIONS), expected)
    validate(root, list(BATCH5_PROJECTS), expected)
    selected = []
    canonical_identity = None
    config_digest = None
    for role in roles:
        directory = root / EVIDENCE / role
        result = _json(directory / "results.json")
        binding = result["binding"]
        digest = binding["config_sha256"]
        if config_digest is not None and digest != config_digest:
            raise EvidenceError("batch5_release_source_mismatch")
        config_digest = digest
        canonical = _json(directory / "canonical-discovery.json")
        retained = _tester_inventory(canonical)
        batch5 = [row for row in canonical["tests"]
                  if row["project_name"] in BATCH5_PROJECTS.values()]
        _batch5_rows(batch5, {project: index for index, project in enumerate(BATCH5_PROJECTS.values())})
        identities = [_tester_case_identity(row) for row in (*retained, *batch5)]
        if canonical_identity is not None and identities != canonical_identity:
            raise EvidenceError("batch5_release_canonical_mismatch")
        canonical_identity = identities
        selected.extend(_tester_case_identity(row) for row in result["tests"])
    if len(selected) != len(set(selected)) or Counter(selected) != Counter(canonical_identity):
        raise EvidenceError("batch5_release_union_mismatch")
    original = sum(TESTER_PARTITION_COUNTS.values()) + 2 * len(BATCH5_MOVED_CASES)
    if original != 176:
        raise EvidenceError("batch5_original_inventory_mismatch")
    return {"tester_release_union": TESTER_PARTITION_CONTRACT, "original_case_count": original,
            "new_batch5_case_count": sum(sum(pair) for pair in BATCH5_CASE_COUNTS.values()),
            "test_count": len(selected), "release_sha": expected}


def validate_app_project_union(root: Path, required, expected: str):
    if (len(required) != len(APP_PROJECT_PARTITIONS)
            or set(required) != set(APP_PROJECT_PARTITIONS)):
        raise EvidenceError("missing_or_duplicate_app_project")
    validate(root, required, expected)
    canonical_identities = None
    config_hash = None
    selected = []
    roles = []
    for invocation, project in APP_PROJECT_PARTITIONS.items():
        directory = root / EVIDENCE / invocation
        result = _json(directory / "results.json")
        binding = result["binding"]
        if _app_project_partition(binding) != invocation:
            raise EvidenceError("unreviewed_app_project_binding")
        digest = binding["config_sha256"]
        if _hash(root / binding["config"]) != digest or (config_hash and config_hash != digest):
            raise EvidenceError("app_project_source_mismatch")
        config_hash = digest
        canonical = _app_inventory(_json(directory / "canonical-discovery.json"))
        identities = [_tester_case_identity(row) for row in canonical]
        if canonical_identities is not None and canonical_identities != identities:
            raise EvidenceError("app_canonical_inventories_disagree")
        canonical_identities = identities
        selected.extend(_tester_case_identity(row) for row in result["tests"])
        roles.append({
            "invocation": invocation, "project": project,
            "test_count": len(result["tests"]),
            "outcomes": dict(Counter(row["status"] for row in result["tests"])),
            "completion_sha256": _hash(directory / "completion.json"),
            "exit_sha256": _hash(directory / "exit.json"),
        })
    if len(set(selected)) != len(selected) or selected != canonical_identities:
        raise EvidenceError("app_project_order_or_union_mismatch")
    identity_bytes = json.dumps(canonical_identities, ensure_ascii=False,
                                separators=(",", ":")).encode("utf-8")
    return {
        "completed": True, "app_project_union": 1,
        "release_sha": expected, "config": "playwright.app.config.ts",
        "config_sha256": config_hash, "test_count": len(selected),
        "canonical_identity_sha256": hashlib.sha256(identity_bytes).hexdigest(),
        "expected_skip_count": len(APP_EXPECTED_SKIPS), "roles": roles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    runner = modes.add_parser("run")
    runner.add_argument("--invocation", required=True)
    runner.add_argument("arguments", nargs=argparse.REMAINDER)
    validator = modes.add_parser("validate")
    validator.add_argument("--required", nargs="+", required=True)
    union = validator.add_mutually_exclusive_group()
    union.add_argument("--tester-partition-union", action="store_true")
    union.add_argument("--app-project-union", action="store_true")
    union.add_argument("--batch5-release-union", action="store_true")
    contract = modes.add_parser("tester-partition-contract")
    contract.add_argument("--required-version", type=int, choices=[TESTER_PARTITION_CONTRACT])
    modes.add_parser("batch4-governance")
    modes.add_parser("batch5-contract")
    options = parser.parse_args()
    try:
        if options.mode == "tester-partition-contract":
            print(json.dumps({"tester_partition_contract": TESTER_PARTITION_CONTRACT,
                              "partitions": TESTER_PARTITION_COUNTS,
                              "catalog_file": TESTER_CATALOG_FILE}))
            return 0
        if options.mode == "batch4-governance":
            print("enabled" if batch4_governance_state(ROOT) else "disabled")
            return 0
        if options.mode == "batch5-contract":
            counts = _batch5_counts()
            _batch5_source_hashes(ROOT)
            print(json.dumps({"batch5_contract": BATCH5_CONTRACT_VERSION, "files": counts,
                              "roles": BATCH5_PROJECTS, "proof_scopes": BATCH5_PROOF_SCOPES,
                              "case_proof_scopes": BATCH5_CASE_PROOF_SCOPES}))
            return 0
        if options.mode == "validate":
            validation = (
                validate_batch5_release_union if options.batch5_release_union else
                validate_app_project_union if options.app_project_union else
                validate_tester_partition_union if options.tester_partition_union else validate
            )
            receipt = validation(
                ROOT,
                options.required,
                os.environ.get("CASEOPS_EXPECTED_RELEASE_SHA", ""),
            )
            if options.app_project_union or options.batch5_release_union:
                print(json.dumps(receipt))
            return 0
        arguments = options.arguments
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        return run(ROOT, options.invocation, arguments)
    except (
        EvidenceError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "completed": False,
                    "reason": str(error)
                    if isinstance(error, EvidenceError)
                    else type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
