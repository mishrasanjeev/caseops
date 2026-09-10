# Ram September 08: Statute References And Hearing Sync

Owner: Codex. Release verdict: **NO-GO**. Neither workbook row is closed.
The consolidation worktree is now
`codex-sep08-acceptance-repair-20260908`; the earlier
`codex-catalogue-ip-next-20260908` remains unchanged for its full run.

## Source Reconciliation

Source: `C:/Users/mishr/Downloads/CaseOps_Bugs_08Sep2026.xlsx`.
SHA-256: `f6ae96948d0ab3439b7053df918404fdcb9c71e5d4b15c01955c61e84a61a6ee`.
The sole sheet, `Bug Sheet`, contains two populated issue rows, 2 and 3.
There is no summary-count discrepancy. Credentials are runtime inputs, not
repository fixtures. The original workbook is unchanged.

| Source | Classification and scope | Formal verdict | PRD mapping |
| --- | --- | --- | --- |
| Row 2, BUG-011 | Valid reopened content/completeness defect; same work as BUG-010, not another picker implementation | Partially fixed | J05/J07, MOD-TS-017, US-046A-D, IPLF-006 |
| Row 3, BUG-012 | Valid operational complaint; reported test tenant is deliberately excluded from unattended paid polling. Missing scheduling-policy visibility and inadequate visible-date acceptance are confirmed adjacent defects. Not proof of a broken cron or all matching paths | Inconclusive | J08, M08, MOD-TS-006, US-022/023/024/025/057, FT-078-082 |

## Observed Production Evidence

Read-only collection at `2026-09-08T13:11:27.581Z`, with the explicit
no-paid-provider marker, is retained outside git in
`C:/tmp/caseops-completion-20260908/sep08-production-readonly-01.json`.

- Statute API: 23 Acts; 17 have zero selectable verified provisions.
  The September 08 expanded source candidate is not deployed.
- Scheduler `caseops-case-tracking-poll-1800-ist` is enabled at
  `0 18 * * *`, `Asia/Kolkata`. Its September 08 execution
  `caseops-case-tracking-poll-qm8xx` started at 12:30 UTC and completed at
  12:33:10 UTC. Process success alone does not prove tenant refresh success.
- The execution explicitly carries blocked scheduled slugs
  `caseops-qa;caseops-ip-qa;test-legal`. This is required automated-spend
  isolation, not a provider outage. Normal unmarked human requests remain
  subject to their ordinary readiness and budget gates.
- `test-legal` returns 441 bookmarks, 437 without a provider check and only
  three with a hearing date. The first 100 Matter records contain no CNR and
  only 20 with a court name. This bounded sample is not the entire tenant;
  insufficient identifiers cannot justify guessing a court or hearing date.
- `/api/case-tracking/status` returns configured=true and reason=null, without
  scheduled eligibility. That omission makes readiness look like scheduling.

## Implementation And Acceptance

### Additional Confirmed Backfill Defect

`api-sep08-starvation-red-01.xml` reproduces two consecutive scans of the
same 50 unsupported Matters while the supported 51st Matter remains unlinked.
Every fixture was successfully created through the HTTP API. This is a real
bounded-batch starvation defect, separate from the QA tenant's paid-call policy.

The recovery candidate adds a tenant/provider-owned keyset checkpoint. Every
scanned row consumes the existing batch limit, including unsupported, linked,
terminal and incomplete rows. The checkpoint advances past them and wraps at
the end, so later policy/identifier corrections are reconsidered. This is
technical scan state, never a legal identifier or lifecycle mutation. Parent
locks and fresh bookmark discovery protect admission; failed admission rolls
back its checkpoint as well. Require consecutive-run recovery, full-cycle
reconsideration, isolation, bounded SQL/rows, PostgreSQL concurrency/index
rehearsal and the dated browser journey before closure.

Party-only discovery remains a separate unimplemented matching boundary. Do
not mark a party-name search as identity-verified or populate a hearing without
unique corroborating evidence.

The single 18:00 scheduler dispatch also retains a 50-record provider poll
limit. A successful bounded batch does not establish that an entire larger
tenant was refreshed that evening. Same-window continuation, current-day
eligibility, overlap claims, per-tenant/provider budgets and explicit backlog
visibility must be accepted before making a whole-tenant nightly-completion
claim. This candidate repairs admission fairness; it does not certify that
broader scheduling throughput contract.

1. Keep BUG-011 under the existing complete source inventory. Current candidate:
   15 official documents, 2,941 units, 2,781 verified, 158 retired and two
   quarantined. Eight existing Act editions plus wider supplement/source-pack
   gaps remain. Do not enable unverified options or call this complete.
2. Add server-derived scheduled eligibility and its reason to the existing
   status response. Separate it from live-human availability and the explicit
   request-level no-paid marker. No new provider request or database scan.
3. Display the policy on case tracking without disabling permissible human
   manual refresh. Regress funded tenants, persistent QA tenants, emulator
   tenants, configuration failure and automated requests.
4. Extend the dated Docker Playwright journey with CNR and case-number/court
   matching, actual visible date values in the Matter row, persistence after
   reload, idempotent polling, and unchanged lifecycle. Keep ambiguous, absent,
   past-date, failure, manual-lock and terminal-state backend regressions.
5. Run all modified contracts and complete fresh-image Docker acceptance before
   publication. Require exact-main CI, deployment identity and dated production
   browser proof. Production automation remains zero-paid; it cannot certify
   live paid scheduling merely by returning HTTP 200 or skipping a tenant.

## Reopen Analysis

The adjacent manual-refresh path invalidated only case-tracking queries, leaving
the existing Matter list, workspace, dashboard, portfolio and hearings aggregate
caches valid. Candidate refresh now cancels older Matter reads and invalidates
the canonical Matter query family. A delayed-read test ensures an old response
cannot erase the invalidation. This is a confirmed cache defect, not proof that
the scheduled production poll failed or a terminal Matter reopened.

Verification retained so far:

- Baseline status contract: seven expected failures, each inspected from JUnit.
  Candidate: 75 backend passes and one explicitly Windows-only skip.
- Policy/cache UI: eight passes in offline Docker, plus source/E2E TypeScript
  checks. Frozen baseline frontend: 971 passes across 168 files, no failures.
- Backfill red: one valid reproduced starvation failure. Initial recovery:
  43 passes including adjacent case-tracking checks. Extended 0/50/51/10,000
  row and rollback coverage: six passes in network-disabled Docker.
- PostgreSQL attempt 01: three passes and a fixture-schema failure. Its
  `search_path` exposed a pre-existing public cursor table, not the isolated
  fixture's company parent. Attempt 02: five passes, including concurrency,
  tenant isolation and interrupted-index recovery; the disposal fixture used
  POST instead of the existing PATCH contract. Preserve both failed reports;
  neither is product reproduction or successful disposal-race evidence.
  Attempt 03 passes all six PostgreSQL cases with no skips, including the
  actual disposal race, in `api-sep08-backfill-postgres-03.xml`.
- Strengthened CNR and case-number/court browser journeys: two passes against
  the earlier Docker image `078e637e27e15d960557de7c7541b8370eac32e1`, at all
  three widths. This establishes the existing sync behavior, not new-image or
  production closure. Artifacts: `sep08-hearing-browser-03.xml` and its sibling
  screenshots in `C:/tmp/caseops-completion-20260908/`.
- Retained first browser failure was an incorrect row-role locator. The second
  attempt exposed a test fixture reusing the same case number in one company;
  the company uniqueness rejection was correct. Separate local tenants now
  preserve the same provider identity without weakening product constraints.

The earlier hearing browser assertion checked the column heading, not the
date in the reported Matter row. A valid response and a heading are not user
outcome evidence. The catalogue's earlier narrow source release was never
complete global coverage; broader completion claims would be incorrect.

No supplied row identifies a disposed Matter that automatically reactivated.
Do not conflate a reopened bug ticket with a reopened Matter. Preserve audited
lifecycle rules and require persisted transition evidence before attributing
historical reopening to a worker, import, or UI.

Additional source audit: NDPS extraction reconciled 129 numbered sections and
one Schedule outside the release candidate. Visual inspection found that the
Schedule's four-column, multi-line table requires structure-aware verification;
plain line concatenation is insufficient. The candidate does not admit that
prototype. Motor Vehicles' traffic-sign graphics and existing tabular schedules
need the same semantic-layout audit. The complete catalogue gate remains red.

The first governance regeneration imported the older worktree's editable
package. Repeating with the candidate source explicitly on PYTHONPATH detects
the added table; the corrected inventory contains 317 tables and 5,098 columns.
The current candidate now has its own installed Python environment, with its
resolved module path checked. Never treat the earlier zero-diff generation as
schema evidence.

## Full Verification Follow-Up

The earlier d83b candidate's full offline API run completed 4,267 passes,
194 skips and one failed static selector assertion. Retaining a JUnit argument
made its literal `endswith` assertion stale. The correction parses arguments
and still rejects files, node selections, marker narrowing, `-k`, ignored or
deselected tests and collection-only execution. All 14 focused gate tests pass.
The 194 skips are 192 PostgreSQL tests and the separately verified native-model
and Windows-only deployment checks; they are not included in the pass count.

That image's full PostgreSQL run had 191 passes and one offboarding race timeout.
All five related race cases subsequently passed on both the offline Docker
runner and the Windows runner against its retained database. The affected
deadline-reopen test took 0.55 and 1.10 seconds respectively. Query timings and
the original failed JUnit report are retained. This does not identify the
original timeout's cause or authorize a timeout increase.

The f802 recovery image passes the unchanged 30-second local cold-readiness
budget at 19.3557 seconds. Its real pinned scanner accepts clean content and
rejects EICAR through direct service calls; the outage check raises a service
HTTPException(503), not an actual upload HTTP response. Unrelated HTTP health
remains responsive in 0.3929 seconds. This is not a production
portfolio-latency certificate. Source compiler check reproduces all 2,941
records and bundle hash `71f3bd09ab30a44d97151f60b7271ea7f47ba821a7d0fbcdf1e7500caa6a0639`.

Repeated full migration replay inside every isolated HTTP fixture was an
additional test-time bottleneck. The test-only recovery creates one separate
empty database, migrates it, disables connections to it and clones that exact
schema for each HTTP test. It never clones the shared database or tenant data.
Upgrade/downgrade rehearsals retain their independently fresh migration fixture.
Ten focused PostgreSQL checks pass in 88.46 seconds, including schema, index,
constraint, trigger and alias equality, independent tenant bootstraps, failed
fixture cleanup and all six hearing-backfill cases. The superseded f802 full
run is retained as incomplete, not green. A fresh complete gate using the new
fixture is required; no test selector or deadline has been reduced or relaxed.

The canceled run exposed two buffered failures before the process stopped,
without a final JUnit artifact. Their identities/causes cannot be established
from progress characters and are not classified as fixture or product errors.
Stopping without incremental result retention was a verification mistake.
The replacement runner writes each setup/call/teardown result, full failure
detail and explicit completion event to a fresh JSONL journal. A hard-exit
regression must prove an earlier failure survives without a false completion
record; existing evidence must not be overwritten. The complete set must run
again with those diagnostics, not only the previously passing subset.

Evidence directory: `C:/tmp/caseops-completion-20260908/`. Reports:
`api-next-full-01.xml`, `next-complete-reports-02/postgres.xml`,
`api-postgres-selector-green-01.xml`, `api-offboarding-replay-01.xml`,
`offboarding-host-replay-01.xml`, `recovery-cold-01/result.json`, and
`api-http-template-postgres-01.xml`. Full replacement API/Docker/browser gates
remain pending. Neither workbook row, broader catalogue coverage, any of the
25 unfinished IP slices nor production performance is closed by these checks.

## Configuration-Dependent Fixture Failure

The c079 replacement full run collected all 202 PostgreSQL cases. Its
incremental journal identified two hearing-fixture failures with complete
assertion detail: the starvation journey made 51 searches instead of one,
and the disposal journey already had a bookmark before its race began.
`verify-docker.ps1` enables tracking for browser acceptance; the fixtures
inherited that setting and public Matter creation correctly auto-linked their
records. The original focused runner had tracking disabled. This is not
evidence that the backfill created duplicates or defeated disposal.
The complete result is 200 passed, two failed, zero skipped and zero errors
in 1,101.712 seconds. The earlier offboarding timeout did not recur. All
original failure reports remain retained; a passing replay does not establish
the original timeout's cause.

`api-hearing-fixture-isolation-01.xml` passes both unchanged journeys on
PostgreSQL when the legacy-data setup explicitly disables automatic linking.
The correction scopes that setting only to legacy creation, restores the
previous configuration and asserts zero bookmarks before admission. Both
PostgreSQL journeys now run with enabled and disabled ambient configurations.
Normal enabled auto-linking remains covered by the original September 04
suite; no product switch or provider guard is weakened.
The corrected source passes all 28 selected hearing checks, including eight
PostgreSQL cases, the six bounded-backfill cases and the existing automatic
next-hearing suite, in `api-hearing-setup-green-01.xml` (152.09 seconds).
That targeted run is not a replacement for complete corrected acceptance.

The final selector/journal regression report,
`api-retained-final-01.xml`, passes all 18 checks. The two unclassified
failures from the canceled older run remain unclassified; the new run's
identified failures do not retroactively recover the missing old evidence.

## Provider Transaction Boundary: Open

Two deterministic, network-disabled Docker probes in
`api-hearing-transaction-red-01.xml` reproduced an open application
transaction inside both the manual CNR callback and scheduled bulk/CNR
callbacks. Their public bookmark creation and refresh outcomes succeeded
before the transaction assertion failed. These are valid adjacent product
reproductions, separate from the fixture failures above.

Affected owner: `services/case_tracking.py` (`refresh_bookmark`,
`poll_tracked_cases`, `_new_operation`). Mapping remains J08,
MOD-TS-006, FT-078-082 and the existing provider-concurrency controls.
Do not create a competing provider job owner or fix this by adding a bare
commit. The current running operation has no durable expiry/recovery contract.

Required repair and acceptance:

1. Claim bounded work and reserve budget durably before transport; capture
   immutable source identifiers, actor/tenant identity and a fenced attempt.
2. Release the transaction before bulk, fallback CNR or case-number search.
   Bound total transport time and prevent overlap from purchasing duplicate
   work before a claim exists.
3. On return, reload authorization, active bookmarks, tracked identity,
   authoritative Matter lifecycle and the current claim before persistence.
   A late or superseded writer cannot record current operational output.
4. Recover expired claims after process loss, without losing spend evidence
   or requiring indefinite manual replay. Reconcile uncertain paid outcomes
   conservatively; retries must not evade the account cap.
5. Regress manual and scheduled success, timeout, fallback, concurrent claims,
   crash recovery, revocation and disposal on PostgreSQL. Assert no transaction
   inside each provider callback and unrelated HTTP responsiveness during it.
6. Add exact-image Docker browser acceptance and repeat on production only
   after the full local release gate. Automated tests remain zero-paid.

The provider-boundary repair is not implemented in this candidate. Neither
the new reproduction nor the keyset backfill closes whole-tenant nightly
throughput or party-only identity discovery.

## Completed Docker Acceptance

Frozen candidate fingerprint:
`f0a13e53a55d6c52d9f8530764777e1d9cadc6c3a4560b0635749e0e30f10303`.
This is a pre-commit source fingerprint, not a Git commit. The subsequently
added cold HTTP harness and these evidence updates do not change application
runtime code; they are not retroactively included in that frozen source.

- `recovery-complete-reports-03/postgres.xml`: 204 passed, no failures or
  skips, 1,045.69 seconds. The journal contains an explicit successful finish.
  Schema and index health remained clean after destructive migration rehearsals.
- The exact release seed was restored before the worker and browser restarted:
  23 Acts and 4,766 total seeded rows. Seed-row count is not verified coverage.
- `recovery-complete-browser-03.xml`: 310 passed, zero failures, five skipped,
  1,626.37 seconds. Four skips require production; the fifth requires a Pine
  Labs payment-provider path. Skipped is not verified.
- All three dated hearing journeys passed, including the supported 51st Matter
  after a rejected full page. CNR and case-number paths prove actual visible
  dates, reload, manual refresh and unchanged lifecycle at 393/768/1280px.
- Catalogue selection, attachment, source detail and reload passed at those
  three widths; all 2,941 release-source records were checked. Neither proof
  admits the eight missing editions or wider missing source packs.
- The September 08 scheduled-eligibility surface passed without paid-provider
  traffic or disabling permitted human search. Existing law-firm, import,
  billing, patent-foundation and lifecycle browser journeys remain covered by
  the same broad run. Selected hearing screenshots were visually inspected.

The full API report `api-recovery-full-02.xml` contains 4,276 passes,
200 skips, five failed migrations and five fixture setup errors. Every failed
node was independently inspected: each reports exhausted 1 GiB temporary
storage. The disk-backed, executable-storage replay
`api-recovery-storage-replay-01.xml` passes all ten in 162.38 seconds.
The preflight now refuses insufficient scratch before any test launches;
`storage-preflight-negative-01.json` proves that refusal. No failed report
is overwritten or upgraded to green.

The original 200 skips were 198 PostgreSQL cases, one real native reranker
case and one Windows command-shim case. The latter two now pass explicitly in
`api-native-reranker-03.xml` (offline Docker) and
`api-windows-shim-03.xml` (workstation Windows). PostgreSQL's expanded
204-node run and the 18 final selector/journal plus 28 hearing checks cover
the current additions. `api-evidence-reconciliation-03.json` maps all
4,496 currently collected identities to passing observations, retaining report
hashes. This is composed evidence across snapshots, not a clean single full
current-source run. The two additional provider-transaction probes remain red
and outside that collected inventory. API Ruff and every configured coverage
threshold pass; none of these results is release approval.

## Cold HTTP Proof And Remaining Margin

`recovery-cold-http-01` failed the unchanged 30-second readiness gate.
Its scanner became ready only after roughly 33 seconds. API and scanner state
and logs are retained; neither was OOM-killed. The cause of timing variation
is not established, and no timeout increase is accepted.

`recovery-cold-http-02/result.json` passes real authenticated HTTP clean
upload, byte-identical download, EICAR rejection (400), scanner-outage rejection
(503), no persisted rejected attachment, and successful upload/download after
scanner restart. It used a fresh PostgreSQL database migrated with the same API
image, pinned real ClamAV and an internal network without Internet access.
API identity: `sha256:e3cb3487fe3be42e179c42c542046774b928c6912eedd140ea58c6f5ac060305`.
API limits: two CPU/four GiB. Cold readiness was 29.6629 seconds; post-outage
HTTP health including the Docker launch was 0.9885 seconds (five-second budget).
The checked-in `scripts/verify-api-cold-start.ps1` and
`scripts/cold-upload-http.py` retain this actual HTTP journey. Optional
functional diagnostics after a cold failure preserve the failed result and
nonzero exit code. A narrow passing margin does not erase attempt 01.

The NDPS Schedule prototype now reconciles 162 logical rows from 164 physical
rows, including continuations 110C and 110ZS. Every non-whitespace source-row
character is preserved once. Ruled cells are essential: some serial labels
are bottom-aligned, and transparent text rectangles mislead the default table
detector. `ndps-structured-table-01.json` remains explicitly unadmitted:
publisher-note linkage, complete visual verification, structured API/UI
rendering and admission regressions are still required.

Production is unchanged by this candidate. No commit, push, PR, merge or
deployment has been performed. Formal verdicts remain BUG-011 **Partially
fixed**, BUG-012 **Inconclusive**, release **NO-GO**. All 25 unfinished IP slices,
full catalogue coverage, provider recovery, nightly throughput and the observed
53-second production latency remain open.
