# Ram Workbook And Bulk-Update Review — 2026-09-24

## Release disposition

**NO-GO for production.** This worktree is at `86886a5fc128c2c456a83804095dfa17d9b9960a`; canonical `origin/main` remains `723debe8f507ed099cee1bf6c5a40ef9753108ca`. No merge, push, production mutation, or production Playwright run was performed. The local candidate has meaningful Docker evidence, but eCourts linking/refresh is a separate broad feature and several reported incidents have no persisted record identity with which to reproduce the original failure.

Inputs reviewed: `CaseOps_ai_Bugs(lll).xlsx` (22 populated bug rows, BUG-010 through BUG-031; copied totals are not authoritative) and `CaseOps_Enhancements_Bulk_Update_and_eCourts_Case_Link.docx` (bulk update and eCourts case-link/refresh proposals). A separate sanitized workbook records every row and its current verdict: `C:/Users/mishr/Downloads/CaseOps_Bug_Fix_Summary_2026-09-24.xlsx`. Reporter credentials and workbook secrets are intentionally excluded from this report and all tests/artifacts.

## Findings and verdict discipline

The exact per-row classifications and evidence are in the summary workbook. In short: 19 rows are partially implemented and verified locally but do not have exact-release production proof; BUG-021 and BUG-022 describe the expected fail-closed state when SMS/WhatsApp configuration or webhook prerequisites are absent and are `Not fixed` (no product defect established, no code change appropriate); BUG-031 is `Inconclusive` because its report is truncated; and the two eCourts enhancement items are `Inconclusive` pending full implementation and evidence. No item is marked `Properly fixed`.

BUG-013 is a real document-rendering bug, not merely an enhancement: the current DOCX preview exposes extracted text/tables but does not preserve the original document's visual structure and formatting. It remains `Partially fixed` at best; faithful DOCX rendering is open. The authenticated image preview defect was corrected at the actual transport boundary: browser `<img src>` did not attach the API bearer credential, so the viewer now fetches an authenticated blob, checks decoded image dimensions, and revokes object URLs. Responsive/layout, integration-state, hearing-date, API enum, and bulk-update paths received focused regressions. These local passes do not upgrade items to production-verified.

The proposed bulk workflow is implemented as a guarded mutation plan, not a create/import shortcut: exact template headers, tenant-scoped Matter Code identity, bounded CSV/XLSX, formula rejection, previewed-content and stale-write checks, old/new review, and application through canonical matter update paths. Lifecycle/status fields cannot be changed through this route. Additional DOCX proposal items such as richer per-row result downloads and broader audit/history acceptance remain open; see the row-level workbook.

The eCourts proposal includes exact provider match, safe linkage, candidate disambiguation, scheduled refresh, canonical `MatterHearing` materialization, synchronization across hearing surfaces, deduplication, stale-data preservation, and outcome history. Those requirements are not satisfied by a generic clickable link or a green local hearing list. No external URL is guessed and no paid provider was called.

## “Cases reopening” investigation

The supplied issue list does not include a Matter ID, persisted status/lifecycle version before and after, or lifecycle audit events. Therefore it cannot establish accidental reopening. A next-hearing update (`Not set` to a date) is not a lifecycle transition. Neither is a private-projection maintenance alert: it concerns derived private output availability, not the authoritative Matter lifecycle. The correct investigation is to compare the exact Matter's persisted lifecycle state/version and ordered audit events, then correlate actor, route, request, and transaction outcome. Do not change lifecycle guards or infer resurrection from dashboard counts or hearing history. The regression contract remains: dedicated version-checked lifecycle endpoint only; generic PATCH/import/worker/child updates cannot reactivate terminal rows; dispose, stale-write rejection, explicit audited reopen, no child resurrection, and final state after reload.

## Root-cause review and permanent learning

The recurring shallow-fix pattern was treating a visible symptom as the defect, substituting a nearby surface for the specified user journey, and treating local/unit success as release evidence. This pass corrected the scope before closure: it separated bugs from expected missing-configuration states and feature requests, rejected workbook summary totals in favor of populated rows, corrected BUG-013's classification, and did not infer case resurrection without persisted lifecycle evidence. It also retained strict no-paid-provider isolation and excluded the supplied secrets from artifacts.

One concrete integration miss surfaced during Docker acceptance: adding the bulk-operation ORM model changed the data-class schema fingerprint. The first PostgreSQL run had 11 failures because the generated projection was stale. The permanent fix was to regenerate and validate the projection and rerun the legal-hold/PostgreSQL coverage, not to relax the intentional fail-closed guard. The rerun passed 388 PostgreSQL tests with zero failures. This failure and the other durable rules are recorded append-only in `AGENTS.md`.

## Verification evidence

- Targeted API suite: 81 passed, 33 warnings.
- Frontend focused suite: 61 passed across four files.
- Web typecheck and Ruff checks passed.
- Docker PostgreSQL acceptance: 388 passed, 0 failed on the updated candidate. The first failed report (377 passed, 11 failed due to stale generated projection) was preserved rather than overwritten.
- Focused Docker Playwright: `tests/e2e/ram-2026-09-21-bugfixes.spec.ts`, 2 passed. The candidate exercised bulk template/download/preview/apply/history, authenticated image decode, DOCX extracted content, and hearing surfaces. This was a local Docker run, not production.
- The full `verify-docker.ps1` invocation did not finish green in one run: its initial browser attempt failed, after which the underlying image authentication and test setup defects were corrected and the focused Docker E2E passed separately. Do not describe this as one clean full-harness pass.
- Production exact-SHA Playwright: not run. Production deploy: not performed. Paid-provider calls: none.

## Remaining acceptance gates

1. Complete DOCX fidelity/viewer behavior and assert the actual rendered structure.
2. Obtain exact safe incident identities and persisted evidence for Sync, hearing propagation, and integration-state reports; do not spend provider credits to manufacture evidence.
3. Implement and test the full eCourts matching/linking/scheduled-refresh contract, including `MatterHearing` and all listed surfaces, deduplication, stale-value behavior, and recovery history.
4. Complete bulk result/error report and durable history/audit acceptance against the documented contract.
5. Run the exact local Docker release gate as one green invocation, reconcile collected test inventory, merge/push the validated tree to canonical `main`, deploy that exact commit, prove API/web release identity, and run committed production Playwright journeys before any item is called properly fixed.

## 2026-09-24 release review follow-up

An independent release review found four bulk-update integrity risks before
promotion: inaccessible Matter codes exposed IDs and versions in preview;
changing a catalog court silently cleared derived lineage outside the reviewed
diff; an out-of-team owner could pass preview but fail apply; and a denial audit
could commit earlier rows in an apply batch. A wide XLSX also could induce
unbounded parsing work. The candidate now conceals inaccessible codes, previews
canonical court lineage, validates team roles before approval, rolls back the
whole batch on apply-time conflicts while recording the denial separately, and
bounds XLSX columns and iterations. New regressions cover these paths on the
local test database, including an additional PostgreSQL transaction case in
the Docker gate. The initial full Docker attempt was intentionally interrupted
after these findings; its partial journal is retained under
`.tmp/release-20260924-full-docker-2/` and is not release evidence.

The next frozen Docker run completed all 389 PostgreSQL tests, including the
new bulk rollback race, but desktop Playwright shard 1 failed 1 of 196 cases:
the 768px OTHER-IP-090-091 test reached its tenth independent domain before
its 120-second budget expired. The 393px and 1280px variants passed. This is
retained as a failed, incomplete release gate under
`.tmp/release-20260924-final-acceptance/` and `test-results/`.
The ten-domain browser loop is now partitioned into three named groups per
width without reducing source, lifecycle, screenshot, or responsive assertions.
The full Docker gate must be rerun on that new source fingerprint; the prior
PostgreSQL pass is not a complete replacement acceptance.

The replacement run at fingerprint `22f4034cbe56771f1a9f90077511972cdc1b8bedcf7101442e450cd292b6a416`
passed all 389 PostgreSQL tests and desktop shard 1, including all nine
partitioned OTHER-IP cases. Desktop shard 2 had one dated test-drift failure:
`ram-2026-09-20-bugs.spec.ts` expected overdue and missing-date follow-up
queues while an exact hearing-date filter was active. The actual six matching
hearings were present, and the focused page test already specifies that the
follow-up queues are hidden under the filter. The dated browser test now
asserts the six filtered records, clears the filter, and then asserts both
queues and the court handoff. Mobile and certification were not reached in
that red run; the complete gate must be rerun on the changed fingerprint.

The next full run again passed 389 PostgreSQL tests but desktop shard 1 had
one intermittent local transport failure: a patent-party GET returned
`ECONNRESET` after a committed mutation. The API remained healthy and never
received the failed GET; the loopback proxy logged no upstream error. The
proxy had advertised reusable downstream connections while closing idle
sockets after five seconds. It now strips the upstream hop-by-hop keep-alive
header, advertises `Connection: close` downstream, and closes only after the
complete body while retaining bounded upstream pooling. Seven proxy tests
pass, including complete mutation response and fresh downstream socket proof.
This run is red and incomplete; shard 2/mobile did not execute.

The fourth full Docker run (`.tmp/release-20260924-fourth-acceptance/`,
fingerprint `23de94527ec8`) passed all 389 PostgreSQL tests and desktop shard
1. Desktop shard 2 had one browser locator failure after clearing the exact
hearing-date filter: both the follow-up region and the main hearing bucket
correctly displayed `Past listing date (1)`, making the page-wide locator
ambiguous. The exact-date results and hidden follow-up assertions passed.
The dated test now scopes post-clear assertions to the named follow-up region.
This fourth run remains red; mobile was not reached and the complete frozen
gate must run again.

The fifth frozen run (`.tmp/release-20260924-fifth-acceptance/`, fingerprint
`acecd5cee9013d11ed1f15abd8f199f51ba7c0322cdd5c11f384b2b0141a3289`)
completed PostgreSQL with 388 passes and one failure in the new bulk
post-preview access-race regression. Its test hook changed access during the
canonical dry-run preview inside a rolled-back savepoint, so the apply request
correctly rejected a stale preview token before the first batch write. The
hook now flips only after the first non-nested apply update and explicitly
asserts that this phase was reached. No browser project ran in this red gate;
the full frozen inventory must be rerun.
