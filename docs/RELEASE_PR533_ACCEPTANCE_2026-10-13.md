# PR 533 Release Acceptance, October 13

## Current Verdict

**NO-GO; not merged or deployed.** This checkpoint covers J09/M07
(US-026..028, FT-034..036), J14/M14, UJ36/UJ61 and QG-SEC-004.
The owner requires green CI, complete exact-candidate workstation Docker
acceptance, canonical-main merge, guarded production deployment and live replay.
Scoped results below do not replace those gates.

## Passive Evidence Capacity Checkpoint

Published `faff06c9` has a RED CI run 38369998534. Its native shard 6 passed
all 362 test calls, but the former-eager court-history negative test failed
teardown because the timing recorder exhausted 512 GC-phase cells. The exact
source-bound native record has 1,062 SELECT samples, `gc_overflow: true`, no SQL
overflow, invalid or unfinished sample, no unpaired GC phase and no leaked
backend/lock. The complete hashed envelope does not waive incomplete timing.
Hosted browser execution was blocked. The full local R8 run remains separate.

Only the test recorder's finite metadata ceiling changes to 4,096 cells; the
callback, production GC policy, locks, deadlines, query budgets and complete
evidence assertion are unchanged. A deterministic 600-phase control fails on
the old buffer. The new default-bound overflow control still fails closed and
retains exactly its bounded count without changing GC callbacks or policy.

The complete affected two-module PostgreSQL replacement has 37 passes and
111 phases, zero skips/failures and exact collection/JUnit agreement. Source
bytes are unchanged during the run, all parent processes are reaped and owned
resources removed. The original large-history fixture records 257 GC events
(514 phase cells), 1,062 SELECTs and complete passive evidence under the new
ceiling. This is local observer proof, not a production GC-causality or latency
claim. Ruff and whitespace checks pass. The first attempted control run skipped
both cases because the PostgreSQL URL was absent; it remains incomplete evidence,
not a RED or a passing reproduction.

Evidence: `ci-faff06c9-reconciliation-01/failed-native6-full-inspection-01` and
`recommendation-authority-read-plan-02/finalizer-gc-capacity-native-red-02` /
`finalizer-gc-capacity-native-green-03`. The old hosted failure and local R8
baseline remain retained. Final amended-tree full CI/Docker, main merge, guarded
deployment and live replay remain mandatory; nothing is merged or deployed.

## Authority Read Correction

The shared indexed-text, embedding-availability and vector-prefilter queries
now use structured SQLAlchemy reads. Fixed indexed constants remain inlined
after compilation; the vector candidate limit remains before document joins,
with unchanged six-decimal vector formatting, filters, ranking and limits.
The production transaction guard and its SQL/function allowlist are unchanged.
Read-error fallbacks may roll back only a proven caller-owned read-only session;
pending/flushed, Core and raw-driver writes remain protected.

The new complete PostgreSQL module passes 42 identities and 126 phases, with
zero failures, skips, duplicate or missing phases. An independently migrated
fresh PG17 database exercises the real CaseOpsSession and HTTP Strategy route,
an uncited rejection and a grounded deterministic success with persisted reload,
empty/vector reads, all nullable filter combinations, nearest-result exclusion,
literal court metacharacters and caller-write preservation after read failures.
Forced generic GIN and forced HNSW plans prove index eligibility, not natural
production plan choice or latency. All providers are deterministic and offline;
no legal-model quality, paid-provider or deployed-fix claim follows.

Evidence is `recommendation-authority-read-plan-02/native-parent-03`: natural
exit zero, unchanged source, every owned container/network removed. The earlier
native-01 loopback setup timeout and native-02 SQL test percent-placeholder
failure remain retained separately. Static independent review has no remaining
findings. The full six-module adjacent-unit replay has 299 passes and 897 phases,
zero skips/failures and unchanged source. Both journals' complete collections
match their JUnit identities, with no missing, duplicate or unknown phase.
Evidence is `recommendation-authority-read-plan-02/full-adjacent-parent-04`.
Amended-tree CI/Docker, canonical merge and live exact-release gates are still
required before release or bug closure.

## PostgreSQL Strategy Checkpoint

Candidate `ba16167de60bfa98502ae4828ca3228ae0bccd97`, tree
`3b2acb25b0be58be09fc0510e6942fabb7c87b01`, has fully reconciled green hosted
CI 38346171604 on merge `891659c0`: 7,603 API passes and 2,858 explained skips,
2,854 native passes, 1,280 log-reported web passes and 533 browser passes with
17 skips. The Linux retention module has 24 passes and one Windows-only skip.
The separate 50-case Windows supplement and its observed-source binding remain
explicit, not fabricated pre-execution fingerprints. Security and CodeQL pass.

Fresh R7 native acceptance completed at `2026-10-13T06:26:16Z`: 2,854 passes,
8,562 phases, no skips/retries/faults and unchanged source. All 4,351 historical
obligations and 84 original failed identities reconcile. The actual new web
image passes 962 material checks. These are separately scoped results.

R7 full Docker acceptance is **NO-GO**. Both desktop artifact-retention
boundaries now succeed, including the actual forward-slash source paths.
However, `ram-2026-09-02-bugs.spec.ts:546` returns two HTTP 500s while generating
`litigation_strategy`. The complete desktop reports contain 532 passes, ten
explicit skips, one failure and three serial-blocked cases; all four mobile
cases remain unexecuted. The first shard has 272 passes/one skip; the second
has 260 passes and 12 producer-reported skips, of which three are blocked by
the serial failure. Do not call those three verified or voluntary exclusions.

The failed request fell outside the retained final API log tail after thousands
of subsequent statute GETs. Fresh isolated diagnostic 04 reproduces the 500
with the unchanged API image, schema, source and equivalent local Matter,
owner policy and Article 14 setup. Observer-only diagnostic 05 reproduces the
same error and captures its origin immediately. No source or guard behavior
changed; both diagnostics cleaned up only their owned resources.

The first unproven read is the exact-name authority lookup: its indexed text
expression contains raw literal columns for empty text and separators. The
second is the raw PostgreSQL embedding-availability SELECT. No pending ORM
insert/update/delete was observed. The exact existing `SET LOCAL
statement_timeout = '60000'` was proven read-only. The transport-boundary guard
correctly refuses to discard unproven caller work, raising its protected
RuntimeError before provider transport. This is a retrieval-construction
compatibility defect, not evidence that the guard should allow arbitrary SQL.

Correct the shared retrieval queries with structured SQLAlchemy expressions.
Keep the production trigram-index expression, generic-plan behavior, bounded
top-chunk HNSW stage before joins, filters, rank, source rules and DML-denial
invariants. Audit populated vector paths as well as the empty probe. Require
real PostgreSQL HTTP/CaseOpsSession regression and the original dated browser
journey, not only SQLite or mocked authority retrieval. Fresh amended-tree
complete gates, canonical merge, guarded deployment and live replay remain.

Current evidence: `ci-ba16167d-reconciliation-01`, `docker-ba16167d-01`,
`docker-ba16167d-native-independent-reconciliation-01`,
`docker-ba16167d-browser-reconciliation-01`,
`recommendation-r7-ba16167d-diagnosis-01` and
`bug004-ba16167d-docker-diagnostic-04`/`05`. Diagnostic setup attempts and
all previous failed/superseded gates remain preserved. There is still no main
merge, cloud backup, production deployment or private scheduler resume.

## Windows Artifact Checkpoint

Candidate `ce19933ded0b25e84e22ab93f1b16f4081c2536a`, tree
`f9b6ceec2d809589ac43ac0970019887da75ec34`, has fresh green hosted CI
38331705227 on actual merge `77a2c664d16d925f4d5a4e683a72c1806b425b05`:
7,598 API passes, 2,857 explained skips, 2,854 native PostgreSQL passes,
1,280 web log-reported passes and 533 browser passes with 17 explained skips.
Security and CodeQL completed on the same tree; current PR open alerts are
zero, without dismissal. Hosted web per-case reports are not uploaded.

Fresh R6 Docker native acceptance completed at `2026-10-13T03:23:05Z`:
2,854 passes, 8,562 phases, zero skips/retries/faults and unchanged source.
All 4,351 historical obligations reconcile; all 84 original failures now pass.
The current Company-first disposal journal proves successful post-provider
Company/Membership/User/Matter locks and zero generated rows, not a timeout-only
rejection. The separate hosted lock-timeout observation remains unattributed;
the fixture's assertions alone do not guarantee timeout-free reacquisition.

Whole R6 Docker acceptance nevertheless failed at `03:48:47Z`. Desktop shard
1 recorded 272 passes and one missing-merchant skip, but its artifact retention
failed before copying. Desktop shard 2 and mobile, 277 cases, did not execute.
The actual report uses `C:/...` paths. Prefixing those as `\\?\C:/...` creates
an invalid Windows native path; .NET's `Attributes=-1` sentinel falsely trips
the reparse bitmask. Exact unchanged-helper replay reproduces this under the
controller's PowerShell 7.6.5. The real retained root is not a reparse point.
Moving only the evidence destination cannot fix this source-path defect.

Normalize native Windows separators before prefixing and reject unavailable
metadata explicitly. Preserve actual junction/ancestor rejection, source and
destination byte/hash checks, atomic manifest publication, original deadlines
and complete collection. Four real-report-format Windows regressions reproduce
the old failure; the complete 50-case Windows retention module passes after
the correction, including long paths and negative controls. These are offline
fake-CLI controls, not another completed browser run or provider acceptance.
The device-prefixed output rejection is Windows-only, with an explicit Linux
skip; normal forward-slash and junction controls still run on both platforms.
The final four-module Windows wrapper/summary run has 127 passes, 381 phases,
all four requested modules collected and zero skips; Ruff and diff checks pass.
An intermediate four-failure run is preserved: two invented extended-path
admission expectations conflicted with the unchanged containment policy, and
two new ancestor fixtures checked the wrong retained directory. The corrected
tests retain the policy and positively check the actual junction target.

Evidence: `ci-ce19933d-reconciliation-01`, `docker-ce19933d-01`,
`docker-ce19933d-native-independent-reconciliation-01`,
`docker-ce19933d-browser-reconciliation-01`, `front-ce19933d-01` and
`retention-forward-slash-20261013-01` under the retained release output root.
The two original contract journeys separately pass on pinned Node 22 at all
nine widths, with actual cropped PNGs. None of these results transfers full
Docker acceptance to the amended tree. Fresh complete gates, canonical merge,
guarded deployment, exact-live replay and clean projection cadence remain
mandatory. No production merge, backup, deployment or scheduler resume occurred.

## Current Browser Finding

The later candidate `6fc6c97fbe9dbf2afd053883afb7088881b75031`
(tree `40c0769eaaf6f31341642008ca1708b2a98bb37e`) remains **NO-GO**.
Its actual hosted merge checkout is
`bac1b3c02c27d94eed66c2c3479ea193e14d3989`, with the same tree.
CI run 38322285885 completed its API, aggregate coverage, PostgreSQL and
web jobs successfully, but complete browser acceptance failed: 550 cases,
532 passed, 17 skipped, one unexpected failure, zero retries/flaky cases
and zero global errors. The skips are not verified positive workflows.

The sole failure is J10/M09/FT-051/052's 393px contract AI source-preservation
journey in `ram-2026-10-12-prod.spec.ts`. Its Playbook tab was visible and
enabled but the Obligations panel heading intercepted its pointer for the
original 15-second action deadline. The actual page snapshot and complete
click error establish a product layout defect, not locator drift or provider
availability. The contract page wraps its eight tabs while inheriting the
shared single-row `h-10` height. Other existing wrapping consumers explicitly
override that height; the shared single-row primitive need not change.

The correction must let the contract tablist contain its wrapped rows and
remain bounded by the available content width. The dated browser journey
now checks every trigger's horizontal/vertical containment, useful width and
real center-point ownership at 320/393px and immediately around the 768px and
1024px breakpoints, as well as 1280px. Its original unforced clicks, four
actions, manual-row retention, response checks and reload assertions remain.
Those stronger browser assertions are not accepted until actually replayed.
The focused page module has five passes, including four unchanged behavior
cases and a retained RED for the new wrapping-class regression. jsdom does
not prove physical geometry. Cropped tablist screenshots are retained only
for loopback fixtures, never for the production record surface.
All failed browser/native evidence remains retained; the clean R4 native
run is still independent of this required frontend correction.

CodeQL run 38322285945 completed all three analyses on that exact merge tree.
Alert 552 is absent from every current SARIF and the current PR open list.
Its PR instance is fixed without dismissal; its last affected commit remains
the earlier merge, while alert-level state/fixed_at are null. Do not invent
an exact new instance commit from those nullable API fields. This proves
scanner absence only, not whole-release or live-provider acceptance.

## Preserved Candidate Evidence

Candidate `dd7c4d5030410c6b0abbc3c941e4022be164f77e` has tree
`7af7505e8662f62fca53be97f2643a1c2cea90a3`. Hosted CI used merge
`5ea5f087b133267ef98afa0c374ce3ff17f3d27c` with the identical tree.

- CI run 38311637729: 10,451 unique API identities, 7,594 passed,
  one failed and 2,856 skipped. The failure is the stale exact upload-path
  expectation in `test_postgres_sharding.py`; combined API coverage and
  hosted Playwright did not execute. All 2,853 native PostgreSQL identities
  passed separately with 8,559 phases and retained native journals.
- Security run 38311637713 passed all eight jobs. CodeQL run 38311637798
  completed its analyses but reported alert 552 (`py/empty-except`) in the
  Gemini raw-response decoder. A successful analysis job is not alert closure.
- Full local Docker run `docker-dd7c4d50-01` naturally ended at
  `2026-10-12T23:09:43.083152+00:00`: 2,853 native identities,
  8,559 phases, 2,852 passed, one failed, zero skipped and zero retries.
  All eight whole-file groups completed and source bytes stayed unchanged.
  The failed call is
  `test_native_recovery_skips_locked_claim_and_respects_batch`.
  Recovery returned one where the test expected zero while its own claim
  was locked. A bounded read-only snapshot from the owned native database
  retained two distinct rows: the earlier job `11bc0b81-8e0a-4f4d-9608-c334a731e1c6`
  was queued with the exact recovery marker at `23:04:45.539196Z`; the job
  created in the failed fixture's time window
  `35255488-e530-46e0-881a-5513e466f998` remained processing.
  Its original SQL journal omitted parameters, so the locked ID is not
  directly recorded there. The source, exact query/update timing and retained
  rows establish an invalid shared-workload zero-count assumption, not a
  demonstrated production SKIP LOCKED defect. The corrected test must use
  the existing independently migrated, connection-disabled-template child
  fixture; production recovery remains global and unchanged.
- The Docker gate correctly stopped before Playwright. Its 550 discovered
  browser identities are an inventory, not executed acceptance. Failure
  diagnostics and pending aggregate products remain preserved; there is no
  successful aggregate completion. Owned Docker resources were cleaned up.
- Candidate secret tree/history scans, all 16 control-plane gates and the
  actual musl web-image 19-package obligation bindings passed. Those results
  apply only to this candidate, not to an amended source tree.

## Prepared Corrections

The exact upload-path regression now includes the native journal directory
and per-shard environment binding without changing shard counts, deadlines,
aggregate failure guards or original artifact paths. Its complete two-module
run has 52 passes and 156 phases.

The Gemini decoder explicitly retains `body = None` on unreadable metadata,
so conservative usage accounting still precedes its typed terminal error.
There is no catch broadening, private logging or suppression. Three native
SDK response-metadata regressions already passed before the clarity edit;
they are not falsely described as behavioral RED. The full four-module
replacement has 365 passes and 1,095 phases. Fresh actual CodeQL is required.

Global recovery zero/count tests now use `isolated_court_audit`, retaining
their original lock, expiry, count and persisted-state assertions. An added
three-tenant regression keeps the oldest claim locked, recovers each of two
unlocked stale claims with `limit=1`, proves no remaining unlocked work,
then recovers the original claim after lock release. Actor/source identity
and the locked claim's state remain preserved; production recovery is unchanged.
The complete three-module PostgreSQL-marked collection has 43 passes,
129 phases and zero skips in `court-recovery-isolation-20261013-02`.
These include native races and fixture/control tests, not 43 independent
overlap races. Its initial run is retained separately: 23 setup failures
were a missing external launcher's basetemp parent (`WinError 3`), not
product reproductions. Both owned resource sets were cleaned up.

Clarification of the preceding observability checkpoint: its 127-case run
contained 103 PostgreSQL-marked cases and 24 pure controls. Within the 103,
65 exercised native audit behavior and 38 were controls. It was not 127
independent PostgreSQL overlaps; canonical native collection remains 2,853.

## Remaining Release Gates

Replay the isolated global recovery correction and the explicit locked plus
unlocked multi-job batch boundary without deleting retained claims, changing
the production recovery scope or weakening assertions.
Then freeze the final source and rerun complete CI, CodeQL and Docker
native/browser acceptance. Reconcile every selected identity and every
setup/call/teardown phase; earlier failed and interrupted runs stay retained.
Merge only the validated tree to current canonical main. Deploy through the
guarded exact-SHA script, including its completed pre-migration backup,
then run exact-live verification and two clean private-projection cadences
before guarded scheduler resume.

Production was last verified on API and web revision `3dbf364d`; this document
does not establish a newer serving revision. No cloud backup, restore, live
provider, legal-model quality or conversion claim follows from these tests.
October paid behavior, automated no-paid fences, Gemini activation consent,
financial-baseline requirements and owner-kept provider gaps remain unchanged.

Evidence is retained under
`outputs/pr-final-release-20261012/`, including
`ci-dd7c4d50-reconciliation-01`, `docker-dd7c4d50-01`,
`docker-dd7c4d50-first07-independent-reconciliation-01`,
`gemini-decoder-intent-20261013-01` and
`finalizer-observability-scope-clarification-01`. The workload snapshot and
original failed phases are in `court-recovery-dd7c4d50-diagnosis-01`;
the corrected full focused proof is in `court-recovery-isolation-20261013-02`.
The later complete failed browser report and exact-tree CodeQL SARIF are in
`ci-6fc6c97f-reconciliation-01`.
