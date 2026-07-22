"""Build the Ram 2026-07-22 CaseOps bug-fix evidence workbook.

The source workbook contains tester credentials.  This generated artifact
records which tenant/account was exercised, but deliberately never stores a
password.  Run-time evidence must be updated below before the workbook is
regenerated for delivery.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


DEFAULT_OUTPUT = Path(r"C:\tmp\CaseOps_BugFix_Summary_Ram22Jul2026.xlsx")
SOURCE_WORKBOOK = Path(r"C:\Users\mishr\Downloads\CaseOps_Bugs_Ram22Jul2026.xlsx")

NAVY = "17324D"
TEAL = "087E8B"
PALE_TEAL = "DDF4F2"
PALE_BLUE = "EAF1F8"
PALE_AMBER = "FFF2CC"
PALE_GREEN = "E2F0D9"
PALE_RED = "FCE8E6"
WHITE = "FFFFFF"
INK = "1F2937"
MUTED = "52606D"
LINE = "C9D4DF"

THIN = Side(style="thin", color=LINE)
CELL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


def _title(ws, title: str, subtitle: str, last_column: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    ws["A1"] = title
    ws["A1"].font = Font(size=18, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
    ws["A2"] = subtitle
    ws["A2"].font = Font(size=10, italic=True, color=MUTED)
    ws["A2"].alignment = WRAP
    ws.row_dimensions[2].height = 30


def _header_row(ws, row: int, columns: int) -> None:
    for cell in ws[row][:columns]:
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.font = Font(bold=True, color=WHITE)
        cell.alignment = WRAP
        cell.border = CELL_BORDER
    ws.row_dimensions[row].height = 30


def _table(ws, name: str, start_row: int, end_row: int, end_column: int) -> None:
    ref = f"A{start_row}:{get_column_letter(end_column)}{end_row}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)


def _finish_sheet(ws, *, widths: list[int], landscape: bool = True) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = WRAP
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = ws.dimensions
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.oddFooter.center.text = "CaseOps | Ram 22 Jul 2026 | Confidential QA evidence"
    ws.oddFooter.right.text = "Page &P of &N"


def build_executive_summary(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Executive Summary"
    _title(
        ws,
        "CaseOps — Ram 22 July 2026 issue assessment and fix summary",
        "Formal verdicts follow the strict rule: no ‘Properly fixed’ claim before the candidate commit is deployed and the production Playwright regression passes.",
        2,
    )

    metadata = [
        ("Source workbook", str(SOURCE_WORKBOOK)),
        ("Assessment date", "2026-07-22"),
        ("Candidate baseline", "33bf177b45eeb556ea5a02a82f2d8644cd7e5c25"),
        ("Reported issues", "=COUNTA('Issue Assessment'!A5:A1000)"),
        ("Valid product-policy enhancements", '=COUNTIF(\'Issue Assessment\'!F5:F1000,"Valid enhancement")'),
        ("Valid regressions", '=COUNTIF(\'Issue Assessment\'!F5:F1000,"Valid regression")'),
        ("Formal verdict", "Inconclusive — local candidate verified; production returned the prior mandatory-gate 409 because this candidate is not deployed"),
        ("Tester identity", "legal / hari.gupta@gmail.com (password supplied at runtime; not stored)"),
    ]
    ws.append([])
    for label, value in metadata:
        ws.append([label, value])
        ws.cell(ws.max_row, 1).font = Font(bold=True, color=NAVY)
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=PALE_BLUE)
        ws.cell(ws.max_row, 1).border = CELL_BORDER
        ws.cell(ws.max_row, 2).border = CELL_BORDER
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 115

    start = ws.max_row + 2
    ws.cell(start, 1, "Decision")
    ws.cell(start, 2, "Evidence-backed conclusion")
    _header_row(ws, start, 2)
    decisions = [
        (
            "Classification",
            "BUG-001 is a valid product-policy enhancement, not a regression against the pre-22-Jul contract. The July 15 acceptance explicitly made direct creation Active by default while retaining the Intake/On Hold → Active conflict gate.",
        ),
        (
            "Why it appeared to reopen",
            "The earlier acceptance boundary covered creation, not every route into Active. The old split policy was duplicated in service logic, a gate evaluator, UI recovery copy, lifecycle/reopen tests, PRD/current guidance, and production regressions. Those tests protected the old requirement, so they could not detect the new policy expectation.",
        ),
        (
            "Depth of correction",
            "The candidate removes the server gate and dead evaluator, removes UI blocking guidance, keeps conflict review usable as an advisory workflow, preserves terminal lifecycle/CAS/tenant protections, updates the authoritative contract, and adds a state × conflict-result regression matrix.",
        ),
        (
            "What remains",
            "Deploy this exact candidate and run tests/e2e/ram-2026-07-22-prod.spec.ts with the tester credential. Until that succeeds, the formal verdict remains Inconclusive rather than Fixed.",
        ),
    ]
    for decision in decisions:
        ws.append(decision)
    _table(ws, "ExecutiveDecisions", start, ws.max_row, 2)
    for row in range(start + 1, ws.max_row + 1):
        ws.row_dimensions[row].height = 64
    ws.freeze_panes = "A4"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.oddFooter.center.text = "CaseOps | Ram 22 Jul 2026 | Confidential QA evidence"


def build_issue_assessment(wb: Workbook) -> None:
    ws = wb.create_sheet("Issue Assessment")
    _title(
        ws,
        "Issue assessment",
        "One source row was present. Classification separates whether the report is valid from whether it is a defect under the prior documented contract.",
        14,
    )
    headers = [
        "Issue ID",
        "Severity",
        "Reported Type",
        "Module",
        "Reported Status",
        "Evaluated Classification",
        "Validity",
        "Pre-change Verdict",
        "Requested Acceptance",
        "Root Cause",
        "Implemented Correction",
        "Adjacent Paths Audited",
        "Formal Post-work Verdict",
        "Closure Blocker",
    ]
    ws.append([])
    ws.append(headers)
    _header_row(ws, 4, len(headers))
    ws.append(
        [
            "BUG-001",
            "Medium",
            "Functional Bug",
            "Matter Management / Matter Status Update",
            "Open",
            "Valid enhancement",
            "Valid request; policy change",
            "Not fixed against the new 22-Jul acceptance",
            "Intake or On Hold may move to Active regardless of whether the latest conflict review is missing, pending, conflicted, cleared, waived, stale after reopen, or scoped to an older party name. Conflict review remains available and auditable.",
            "Previous July 15 work intentionally changed only direct creation. Existing-matter promotion retained a documented server gate and matching UI/tests/copy. The test suite therefore enforced a split contract instead of one cross-product invariant.",
            "Removed the activation gate/evaluator and gate-only UI. Retained advisory scans/resolution, tenant scoping, lifecycle provenance, row locking, optimistic concurrency, terminal-state protection, controlled reopen, and operational-child neutralisation.",
            "Direct create; Intake→Active; On Hold→Active; missing/pending/conflicted/cleared/waived/stale conflict results; changed opposing party; post-reopen activation; import-created Intake; cross-tenant review access; generic disposed writes; controlled reopen; UI edit/reload; public/current product copy.",
            "Inconclusive",
            "Candidate not deployed. Production Playwright must pass against the deployed candidate commit before ‘Properly fixed’ is permitted.",
        ]
    )
    _table(ws, "IssueAssessment", 4, 5, len(headers))
    ws.row_dimensions[5].height = 240
    _finish_sheet(
        ws,
        widths=[12, 11, 18, 30, 16, 22, 23, 28, 52, 58, 58, 70, 22, 55],
    )


def build_policy_matrix(wb: Workbook) -> None:
    ws = wb.create_sheet("Policy Matrix")
    _title(
        ws,
        "Permanent status and conflict-review contract",
        "This is the regression matrix—not a list of examples. Every row is an invariant that future changes must preserve unless the PRD is explicitly versioned again.",
        7,
    )
    headers = [
        "Entry Path",
        "Starting Status",
        "Conflict Review State",
        "Requested Operation",
        "Expected Result",
        "Safeguard That Remains",
        "Regression Coverage",
    ]
    ws.append([])
    ws.append(headers)
    _header_row(ws, 4, len(headers))
    rows = [
        ("Create", "n/a", "None", "Create directly as Active", "Allowed", "Create validation, tenant scope, audit", "Backend + July 15/22 E2E"),
        ("Edit", "Intake", "None", "PATCH status to Active", "Allowed", "CAS token and status consistency", "Backend + local July 22 E2E passed; production E2E committed, pending deploy"),
        ("Edit", "Intake", "Pending", "PATCH status to Active", "Allowed", "Review remains visible/auditable", "Backend matrix"),
        ("Edit", "Intake", "Conflicted", "PATCH status to Active", "Allowed", "Resolution capability still enforced", "Backend matrix"),
        ("Edit", "Intake", "Cleared / waived", "PATCH status to Active", "Allowed", "Review history preserved", "Backend matrix"),
        ("Edit", "On Hold", "None / any result", "PATCH status to Active", "Allowed", "CAS token and status consistency", "Backend + local July 22 E2E passed; production case committed, not run after earlier 409"),
        ("Edit", "Intake", "Old party scope", "Change party and activate", "Allowed", "Old review remains historical", "Backend matrix"),
        ("Import", "Intake", "None", "PATCH imported matter to Active", "Allowed", "Import validation and tenant scope", "Backend regression"),
        ("Controlled reopen", "Disposed → Intake", "Pre-disposal result", "Activate without a new review", "Allowed", "Lifecycle version marks old review historical", "Backend lifecycle + local July 22 E2E passed; production case committed, not run after earlier 409"),
        ("Generic edit", "Disposed", "Any", "PATCH status or operational fields", "Blocked", "Dedicated lifecycle endpoint, capability, reason", "Existing terminal lifecycle suite"),
        ("Conflict review", "Any operational status", "Any", "Run / list / resolve", "Allowed by capability", "Tenant isolation and audit", "Conflict-check API + UI regressions"),
        ("Cross tenant", "Any", "Another tenant's review", "Read / resolve", "404 / blocked", "Tenant isolation", "Backend regression"),
    ]
    for row in rows:
        ws.append(row)
    _table(ws, "PermanentPolicyMatrix", 4, ws.max_row, len(headers))
    for row in range(5, ws.max_row + 1):
        ws.row_dimensions[row].height = 48
    _finish_sheet(ws, widths=[24, 22, 26, 35, 22, 43, 38])


def build_verification_evidence(wb: Workbook) -> None:
    ws = wb.create_sheet("Verification Evidence")
    _title(
        ws,
        "Verification evidence",
        "A failed or blocked run remains visible. Local evidence cannot substitute for deployment proof, and unrelated setup failures are not counted as pass/fail evidence for BUG-001.",
        8,
    )
    headers = [
        "Layer",
        "Environment",
        "Command / Spec",
        "Acceptance Covered",
        "Result",
        "Evidence",
        "Counts / Timing",
        "Verdict Impact",
    ]
    ws.append([])
    ws.append(headers)
    _header_row(ws, 4, len(headers))
    rows = [
        (
            "Policy regression anchor",
            "Local API",
            "scripts/verify-backend.ps1 tests/test_conflict_checks.py -k test_intake_to_active_does_not_require_conflict_check",
            "Confirms current Intake→Active transition is nonblocking",
            "PASS",
            "The renamed regression returned HTTP 200, persisted Active, and emitted no conflict-gate denial audit.",
            "Included in the 59-test backend run",
            "Supports local candidate verification",
        ),
        (
            "Production baseline",
            "Production / Chromium",
            "ram-2026-07-15-prod.spec.ts --grep BUG-002|lifecycle",
            "Tester authentication and legacy lifecycle path",
            "BLOCKED (unrelated setup)",
            "Explicit tester sign-in succeeded, then the older test stopped because the production forum-state catalog remained empty. It never reached the lifecycle assertion and is not used as BUG-001 evidence.",
            "1 failed before target; 1 skipped",
            "No closure credit",
        ),
        (
            "Backend regression",
            "Local API",
            "scripts/verify-backend.ps1 tests/test_conflict_checks.py tests/test_matter_lifecycle.py tests/test_intake.py tests/test_matter_imports.py",
            "Optional-review state matrix; reopen history; import/intake path; retained safeguards",
            "PASS",
            "Canonical verifier passed Ruff across src/tests and every test in the four affected backend files.",
            "59 passed in 170.67s",
            "Local backend evidence complete",
        ),
        (
            "Frontend regression",
            "Local jsdom",
            "Focused Vitest; npm --prefix apps/web run typecheck; production Next.js build",
            "Status save without gate hint/error; conflict card distinguishes current from historical review",
            "PASS",
            "Three focused test files passed 19 tests, TypeScript passed, and the 64-route production build completed.",
            "19 tests; 3 files; typecheck + build pass",
            "Local frontend evidence complete",
        ),
        (
            "E2E harness reproducibility",
            "Fresh local checkout",
            "tests/e2e/global-setup.ts + scripts/verify-web.{ps1,sh}",
            "Fresh no-install-project venv import; build-time API origin/CSP consistency",
            "PASS after repair",
            "First runs exposed missing src-layout PYTHONPATH and a Next.js bundle baked with localhost while CSP allowed 127.0.0.1. The harness now sets both deterministically; no accidental editable install or stale bundle is required.",
            "Two setup defects reproduced and repaired",
            "Prevents false browser verdicts",
        ),
        (
            "Local browser E2E",
            "Fresh local tenant / Chromium",
            "tests/e2e/ram-2026-07-22-bugs.spec.ts",
            "Exact local identity; Intake/no-check; controlled dispose/reopen; historical clearance; final Active persistence",
            "PASS",
            "The shared legal/tester-email identity passed both July 22 cases: no-check Intake activation in 1.3s and cleared review → Active → Dispose → Reopen to Intake → Historical (stale) clearance → Active/read-back/reload in 2.1s. Combined July 15 + July 22 local execution passed 5/5. Password was runtime-only.",
            "5/5 combined in 20.5s; July 22: 2/2 (1.3s, 2.1s)",
            "Local candidate verified",
        ),
        (
            "Production browser E2E",
            "Production / Chromium",
            "tests/e2e/ram-2026-07-22-prod.spec.ts",
            "Committed Intake/no-check and controlled-reopen tester workflows with terminal cleanup",
            "FAIL — prior deployed policy reproduced",
            "The extended spec authenticated and created a unique Intake matter. Its first activation returned HTTP 409 with the legacy Clear/Waived requirement; the second serial controlled-reopen case did not run. afterAll emitted no cleanup failure. Re-run the same committed spec after deployment.",
            "1 failed at expected 200/actual 409; second serial case did not run",
            "Formal verdict remains Inconclusive",
        ),
    ]
    for row in rows:
        ws.append(row)
    _table(ws, "VerificationEvidence", 4, ws.max_row, len(headers))
    ws.conditional_formatting.add(
        f"E5:E{ws.max_row}",
        FormulaRule(formula=["ISNUMBER(SEARCH(\"PASS\",E5))"], fill=PatternFill("solid", fgColor=PALE_GREEN)),
    )
    ws.conditional_formatting.add(
        f"E5:E{ws.max_row}",
        FormulaRule(formula=["OR(ISNUMBER(SEARCH(\"FAIL\",E5)),ISNUMBER(SEARCH(\"BLOCK\",E5)))"], fill=PatternFill("solid", fgColor=PALE_RED)),
    )
    for row in range(5, ws.max_row + 1):
        ws.row_dimensions[row].height = 72
    _finish_sheet(ws, widths=[24, 24, 65, 50, 31, 68, 24, 34])


def build_permanent_learnings(wb: Workbook) -> None:
    ws = wb.create_sheet("Permanent Learnings")
    _title(
        ws,
        "Brutal recurrence analysis and permanent rules",
        "These rules are mirrored in the repository bug-fixing skill and July 22 learning record so they survive beyond this workbook.",
        5,
    )
    headers = ["ID", "Where We Went Wrong", "Why Prior Checks Missed It", "Permanent Rule", "Regression Lock"]
    ws.append([])
    ws.append(headers)
    _header_row(ws, 4, len(headers))
    rows = [
        (
            "L1",
            "We treated direct Active creation and promotion of an existing Intake/On Hold matter as separate policies.",
            "July 15 acceptance and tests explicitly preserved the second gate, so the suite went green while users still encountered a mandatory check on another path into the same state.",
            "Define one invariant per business outcome and enumerate every entry path before implementation.",
            "Creation + Intake + On Hold + reopen + import rows in Policy Matrix.",
        ),
        (
            "L2",
            "The same policy was copied into backend decisions, UI error recognition, help text, marketing, PRD, and tests.",
            "A shallow service-only or copy-only patch would leave contradictory behavior and future developers would restore the gate from another ‘source of truth.’",
            "When policy changes, grep and update enforcement, recovery UI, copy, tests, PRD, task ledgers, and permanent skills in the same change.",
            "Repository-wide stale-policy scan must be clean except explicitly superseded history.",
        ),
        (
            "L3",
            "Regression tests encoded an implementation rule (‘latest check must be clear/waived’) instead of the user outcome (‘status may become Active’).",
            "Those tests actively prevented the requested behavior and made the obsolete rule look safe.",
            "Test externally observable outcomes with a state × review-result matrix; do not preserve obsolete internal decision objects.",
            "Missing, pending, conflicted, cleared, waived, stale, and changed-party cases all allow activation.",
        ),
        (
            "L4",
            "Reopen semantics conflated historical validity with operational permission.",
            "It is correct that a pre-disposal conflict result belongs to an older lifecycle, but incorrect under the new policy to make that provenance fact an activation blocker.",
            "Keep old results historical after reopen; never turn advisory provenance into an implicit gate.",
            "Reopen increments lifecycle version, preserves history, and permits immediate Intake→Active.",
        ),
        (
            "L5",
            "Prior closeout records drifted: one learning document held production evidence while authoritative task ledgers still said pending.",
            "Contradictory verdict sources make reopened reports hard to classify and encourage rework against stale assumptions.",
            "One formal verdict per issue; reconcile every authoritative ledger during closeout and retain explicit supersession notes for history.",
            "July 15 records annotated as superseded; July 22 remains Inconclusive pending deployment.",
        ),
        (
            "L6",
            "We could have mistaken a friendlier 409 message or a review CTA for a fix.",
            "The user would still be unable to save Active, so the reported outcome would remain broken.",
            "A workflow bug is fixed only when the user completes the intended action on the deployed surface.",
            "Playwright asserts HTTP 2xx, dialog closes, reload persists Active, and cleanup completes.",
        ),
    ]
    for row in rows:
        ws.append(row)
    _table(ws, "PermanentLearnings", 4, ws.max_row, len(headers))
    for row in range(5, ws.max_row + 1):
        ws.row_dimensions[row].height = 100
    _finish_sheet(ws, widths=[8, 58, 62, 62, 50])


def build(output: Path) -> None:
    wb = Workbook()
    build_executive_summary(wb)
    build_issue_assessment(wb)
    build_policy_matrix(wb)
    build_verification_evidence(wb)
    build_permanent_learnings(wb)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)

    # Read-back verification catches broken table ranges, invalid formulas, or
    # an accidentally truncated artifact before delivery.
    check = load_workbook(output, data_only=False, read_only=False)
    expected = [
        "Executive Summary",
        "Issue Assessment",
        "Policy Matrix",
        "Verification Evidence",
        "Permanent Learnings",
    ]
    if check.sheetnames != expected:
        raise RuntimeError(f"Unexpected sheet topology: {check.sheetnames!r}")
    if check["Issue Assessment"]["A5"].value != "BUG-001":
        raise RuntimeError("BUG-001 assessment row is missing")
    if check["Executive Summary"]["B10"].value is None:
        raise RuntimeError("Formal verdict is missing")
    check.close()
    print(f"wrote and verified {output}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    build(target)
