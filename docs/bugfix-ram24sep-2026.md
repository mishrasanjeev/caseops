# Ram Workbook And Bulk-Update Review — 2026-09-24

## Release disposition

**NO-GO for application deployment.** PR #468 now contains the CI-remediation checkpoint `12a9832ef2c3b7fae7c9dc11f69a43ac57c4f751`; canonical `origin/main` was `723debe8f507ed099cee1bf6c5a40ef9753108ca` at the last release check. No merge, application deployment, or exact-release production Playwright run has occurred. The Google Drive API was enabled in the production GCP project as a separate configuration step, without changing Cloud Run service settings. The earlier candidate has meaningful Docker evidence, but eCourts linking/refresh is a separate broad feature and several reported incidents have no persisted record identity with which to reproduce the original failure.

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

The sixth frozen run on fingerprint
`d72870f4fef9090a7593a6f702a734bd022496772b6f5624a6f6695332c3d8a3`
passed as one invocation: 389 PostgreSQL tests; desktop shard 1, 196 passed
with one known skip; desktop shard 2, 191 passed with five known skips; mobile,
four passed. The migration/index checks and release statute reseed passed.
Its source was committed as `d49cbdd3b437bafb1a4bb463a1e6141ba9abdd0f`
and opened in PR #468. The clean-checkout CI then found three additional red
gates: the new ORM table/indexes were missing from the generated data-governance
map, the bulk-update routes/schemas were missing from the generated OpenAPI
client, and a hearing unit test assumed `05 Oct` when the CI locale rendered
`Oct 05`. These are not production validation. The generated contracts are
being regenerated and the locale-dependent assertion corrected; CI must rerun
before any merge or deployment.

## 2026-09-24 CI and provider follow-up

The first PR run remained red. Local remediation regenerated the governance map,
data-class projection and OpenAPI client, corrected the locale-dependent hearing
assertion, and added the migration's governance marker. The migration now refuses
to discard retained bulk-operation history on downgrade. The full static
contract chain found this missing marker before commit; its earlier failure is
retained as a failed gate. Ruff and focused governance tests passed locally;
the full web coverage rerun passed 1,086/1,086 tests with two workers. These
checks do not replace final Docker acceptance or clean-checkout CI.

Provider configuration was audited separately in
`docs/runbooks/provider-setup-2026-09-24.md`. Gmail, Calendar, Pub/Sub and
Secret Manager APIs were already enabled in the production GCP project;
`drive.googleapis.com` was enabled and rechecked on 24 September 2026. No
production Cloud Run connector credentials were changed. Google OAuth consent,
Gmail webhook resources, Microsoft tenant consent and non-Google vendor accounts
remain provider-gated. The sanitized workbook now records these states in a
`Provider Setup` tab without upgrading any bug verdict. No paid provider call
was made.

### BUG-017 persisted production reproduction

A bounded, read-only check using the supplied `test-legal` account and the
no-paid-provider marker against API release `723debe8` found 25 visible matters
with `next_hearing_on >= 2026-01-01`; four had no canonical scheduled
`MatterHearing` in their workspace. Two ordinary active matters are code `5972`
(`3f01ac0c-df3c-40ea-846f-bda253168f8c`, 2026-11-04) and code `5966`
(`2c324e89-9ead-4e16-abd6-4a923733add6`, 2026-09-25); both have
`next_hearing_source=case_tracking`, `next_hearing_manual_lock=false`, and zero
hearings. Their latest history transitions are `Not set -> date` from a
`tracked_case` source, preceded by a manual `date -> Not set` and an earlier
tracked-case restore. This is the precise reported symptom, not a lifecycle
reopen. Two retained `BENCH-PROBE` matters also had stale dates without
hearings and source `unknown`. This is a real stored-data mismatch, not merely
an old UI locator or a projection alert. The audit made no mutation or provider
call. Its exact records must be reconciled after a bounded idempotent backfill,
and the user-visible Matter/Hearings/Calendar/Today/Cause List journey must pass
on the deployed release before BUG-017 can be marked properly fixed.

### Private-projection alert review

The 22 September `active_generation_manifest_mismatch` alert was a real
release-blocking repair-SLO breach: the deferred repair age reached 432 seconds,
above the 300-second limit. It rebuilt at 21:41 UTC and the 21:46 cadence was
clean. Mutation-capable production QA ran from 21:27 to 21:38, overlapping
three maintenance attempts. This supports, but does not prove without persisted
epoch inspection, repeated QA writes fencing safe shadow rebuilds rather than
source corruption. The current schedule confines mutations to exact-release
dispatches. A read-only Cloud Logging audit found zero blocked maintenance
payloads across 394 runs from 23 September 00:01 through 24 September 13:01;
the 13:01 and 13:06 runs each covered six tenants with zero blockers, pending
or failed events, deferred repairs, or rebuilds. No runtime fence/SLO change is
justified by this evidence. A new regression pins the complete scheduled
verification step inventory so future mutation additions require explicit
read-only review. Current clean cadence is old-release evidence only; the final
release still needs its own post-QA rebuild and second clean cadence.

### Combined candidate checkpoint (not deployed)

The checkpoint PR's clean-checkout CI completed green, including all API,
PostgreSQL, web, security, generated-client and Playwright jobs. Subsequent
DOCX, eCourts and bulk-history changes are not covered by that CI result.
On the combined local tree, web typecheck/build passed, the full coverage run
passed 185 files and 1,091 tests, focused API tests passed, and the dated
local DOCX and eCourts browser journeys each passed. The first integrated
DOCX browser attempt failed because a PowerShell patch pipeline corrupted its
binary fixture; the failed result was preserved, the fixture was restored from
the agent's Git blob, its ZIP signature verified, and the unchanged journey
passed. This was a test-asset transfer fault, not authorization to weaken
upload signature checks.

The case-tracking backfill now ignores cancelled rows when deciding whether a
scheduled hearing exists. A provider-free one-shot job pinned to the release
API image is in the deploy script between migration and traffic routing, so
the four persisted test-tenant mismatches are not left for a later paid poll.
The job is bounded and fails if it cannot converge. Full Docker acceptance,
fresh CI, canonical-main merge, deployed-record re-read and production
Playwright remain required before any bug verdict can be upgraded.

### Final link-candidate integration gate

The safe case-link branch was merged into the combined candidate with a
short-lived signed provider selection, server-owned identity and access checks,
idempotent linking, and a user-visible link action. Local combined API checks
passed 97 tests with 10 PostgreSQL-only skips; 17 focused web tests and the
web/E2E typechecks and production web build passed. The first complete Docker
attempt at `49d0e571` ended red before browser shards: 382 PostgreSQL passes
and seven failures. Six came from adapting a case-number-only search fixture
where the PostgreSQL hearing-scope races required a CNR-backed tracked case;
the seventh was a PostgreSQL wrapper still calling the updated helper without
`monkeypatch`. An attempted global CNR change failed all 16 original search
races and was rejected. Separate fixtures now retain both transport boundaries.
The original search races passed 25/25 locally, and the exact PostgreSQL scope
and wrapper selections passed 11/11 on a fresh isolated pgvector database.
These selective replacements do not certify the full release: another complete
Docker inventory, clean-checkout CI, main merge, exact-image deployment and
production Playwright remain required.

The complete replacement Docker run at `6d76c5f9` passed all 389 PostgreSQL
tests and index/seed checks. Desktop shard 1 then found one dated test drift:
`hari-2026-05-30-bugs.spec.ts` opened case tracking with a fictional Matter ID,
yet expected the standalone `Bookmark` action. Matter context now intentionally
requires a verified `Link to Matter` selection. The old standalone search,
bookmark, and update assertion has been restored without fake Matter context;
the separate new link journey retains real Matter-scoped proof. Both dated
journeys passed individually against the local production-style build. An
intermediate Next dev attempt served a stale 404 and left malformed generated
`.next/dev/types`; it was treated as incomplete setup, isolated from source,
and not counted as a product failure. The second full run remains red and did
not reach shard 2/mobile; a complete new candidate run is still required.

The third complete Docker run at `6e152826` passed 389/389 PostgreSQL tests
and desktop shard 1 (198 tests, one expected provider-isolation skip). Desktop
shard 2 found three distinct test-boundary defects. The September 10 legacy
hearing journey tried to create a pre-feature incomplete bookmark through the
current guarded public endpoint, which correctly returned 409. Its fixture now
seeds the pre-feature state only inside isolated E2E Docker, asserts zero prior
bookmarks and tenant scope, and requires the same bookmark ID after ordinary
scheduled recovery. The September 21 DOCX assertion looked for preview text in
the parent DOM after the viewer moved to a sandboxed iframe; it now checks the
actual iframe. The September 24 Matter-link token was signed with the host's
test secret rather than the serving Docker API secret; it now signs inside the
API container without changing server verification. The failed run is retained
under `.tmp/release-20260924-link-third`; it did not reach mobile and is not
release evidence. These fixes and the later bulk-contact/DOCX-index merge need
a fresh complete Docker inventory, clean-checkout CI, canonical-main merge,
exact-image deployment, and production E2E before any verdict is upgraded.

The fourth Docker gate at `a663d36c` completed green: 389/389 PostgreSQL,
both desktop Playwright shards, and mobile. The three previously failing dated
journeys passed. PR #470 was then opened from an identical-tree merge with
current `main`; clean-checkout CodeQL reported a potentially uninitialized
`identity` in standalone case search (and an unnecessary test lambda). The
candidate remains no-go until those annotations are fixed, the changed tree
passes complete Docker acceptance again, and all CI checks are green.
