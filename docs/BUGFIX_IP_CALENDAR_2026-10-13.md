# IP Portfolio and Court Calendar Acceptance

## Scope And Status

Owner supplied two DOCX specifications on October 13. Their original files
remain unchanged in Downloads. This is a new acceptance scope, not evidence
that the earlier PR #533 candidate or production already contains these changes.
Live API and web both report `3dbf364d9834316d181d4a52b2e9b4c7bee431b4`.
No new production deployment or closure is claimed.

Calendar maps to J08/M08/MOD-TS-006, US-022/023/024/025, FT-042/043 and
FT-078..082; role, isolation and query bounds remain SEC-003/004 and NFT-007.
IP maps to existing UJ-02 import, UJ-04 portfolio and UJ-26 renewal journeys,
IPLF-030A/B, IPLF-032A/B, IPLF-037A/B and ARCH-OPS-23. No parallel trademark
model, forum hierarchy, scheduler or lifecycle owner is authorized.

## Requirement Inventory

| ID | Source | Classification | Required acceptance |
| --- | --- | --- | --- |
| IP13-01 | IP sections 2..4 | Valid native Excel date serialization bug; deployed closure pending | Actual upload URL/status/problem/request ID and server cause; accurate transport/auth/parser/system errors |
| IP13-02 | IP section 5 | Enhancement | All 14 supplied headers, safe aliases, ambiguous collision handling, no position mapping |
| IP13-03 | IP section 5.3 | Enhancement | Optional source columns; useful minimum identity; no fabricated applicant/number/classes; unusable row skip |
| IP13-04 | IP sections 6..7 | Enhancement | Extras retained/surfaced, placeholders, multiple classes, optional invalid-date warnings |
| IP13-05 | IP section 8 | Enhancement | Cautious current-workspace/in-file duplicate skips, distinct same-mark applications survive |
| IP13-06 | IP sections 9..11 | Enhancement | Preview does not create dockets; commit revalidates, idempotence and concurrency; history/reload/count reconciliation |
| IP13-07 | IP section 12 | Enhancement | One calendar month, month-end/leap year, due-soon, date-change cancellation and no duplicate alert |
| IP13-08 | IP sections 12..14 | Existing safeguards plus enhancement | Current permissions/lifecycle, no sensitive remarks leak, delivery-channel truth, bounded parser/storage/query work |
| IP13-09 | IP section 13 | Enhancement | Portfolio/import history/renewal visibility, responsive linked-record journey |
| CAL13-01 | Calendar sections 2..4 | Valid display enhancement | Canonical stored SC/HC/DC/other identity, retained bench/region/complex/number only when present |
| CAL13-02 | Calendar section 5 | Valid enhancement | Existing catalog display_order, known time then deterministic ties; unknown fallback; unchanged non-hearing ordering |
| CAL13-03 | Calendar section 6 | Valid bug | Every overflow is keyboard/click interactive, exact-date hidden list/count, all hidden rows once, links and focus return |
| CAL13-04 | Calendar sections 7..10 | Enhancement plus safeguards | Complete identity available, correct time/date/matter, month/week/day, errors, integration and isolation preserved |
| LIFE13-01 | Owner reopening question | Inconclusive historical incident | Persisted Matter identity and lifecycle audit before cause claim; dispose/stale write/import/worker/child/calendar/reopen/reload regressions |

The documents contain requirements and examples, not a reproduced historical
reopening incident or the actual trademark workbook bytes. Do not fabricate
that workbook, a failing request, historical audit or a legal record from the
examples. Deterministic acceptance fixtures must be clearly isolated.

## Root Cause And Accountability

Calendar overflow is a plain div: the current test proves only text presence.
That is insufficient interaction coverage and directly explains why a green
page suite did not catch the dead control. Calendar aggregation also discards
the Matter's catalog identity and hearing time before serialization; styling
alone cannot recover those fields. Existing ordering is title-only within kind.
Use one joined catalog read and its configured order, not another UI hierarchy.

The IP worker's retained baseline now proves a native Excel date storage defect:
`test_native_xlsx_dates_stage_as_json_safe_source_evidence` fails with
`sqlalchemy.exc.StatementError` caused by `TypeError: Object of type datetime
is not JSON serializable`. Its separate HTTP reproduction gets 500 at
`/api/ip/imports/upload`, request ID `ip-native-date-baseline-20261013`.
The source parser must convert native Excel date/time cells to JSON-safe,
lossless source values before staging. Column aliases alone cannot repair it.
These are synthetic, representative workbook bytes, not the missing original
trademark register. Exact-production replay still remains required.

A single authorized production preview reproduces HTTP 500 on exact API/web
`3dbf364d`, request ID `ip-native-date-prod-7a0ae37155884f198720b24eda3006b8`.
It has no `Access-Control-Allow-Origin`, which causes browser fetch to report
a network error instead of exposing the underlying server problem. The probe
uses the committed synthetic native-date workbook (SHA256
`dd3c1cfe03f1518f5293f68798f6bc80d5732926aae0b78aca2e91aadc5e9e1c`),
test-legal only and the no-paid marker. Zero import commits/retries/provider
calls. The importer files have zero diff between serving 3dbf and baseline
51ec. `production-native-date-red-01.json` retains the exact response; this is
RED diagnosis, not production closure of the new source.

Prior shallow closure patterns are concrete: checking a label instead of its
action, a positive example instead of negative/adjacent paths, mocks instead of
real database admission, and branch tests instead of the exact serving build.
This task must preserve failed fixture attempts, reconcile collected inventory,
and retain dated Docker plus production browser evidence per requirement.
An audited explicit reopen is different from silent resurrection. Without a
reported Matter and persisted audit, historical causation remains Inconclusive.

## Evidence So Far

- `import-postgres-bounded-03` is the complete replacement native selection:
  ten cases/30 phases, zero failures/errors/skips, natural exit zero, 231 unchanged
  source pins and confirmed owned container/network removal. It proves actual
  1,000-row HTTP creation through acknowledged 50-row requests, each inside the
  existing 90-second browser deadline, health responsiveness between requests,
  bounded particular materialization/SQL work, context/recovery/identity rules,
  session-owned locks under a one-second idle-transaction limit and both actual
  current-fact reminder deliveries. Total multi-request work took421.36 seconds;
  this is not a claim of instant import or a faster server deadline. Full new-
  candidate Docker/CI/live acceptance still remains. Numeric metrics will be
  retained as JUnit properties in the final full-image gate.
- The complete 1,000-row native replay exposed a real long-import error:
  PostgreSQL terminated the dedicated idle advisory-lock transaction, and the
  470.23-second request failed when that transaction committed. A timeout increase
  is not a fix. Session-owned autocommit locks now have explicit release and
  current-ownership checks. Fifty-row requests return honest staged/202 progress
  and use creator-authorized, versioned continuation after acknowledged success.
  Failed mutations are never automatically retried. The full replacement native
  inventory and later exact-image/live browser gates remain pending.
- `import-postgres-first-01` has seven missing-fixture failures, not seven
  product reproductions. The actual fixture is `isolated_postgres_client`.
  Replacement02 has seven passes and two failures: the lock defect above and a
  cross-tenant fixture that reused the foreign bootstrap cookie. Separate client
  authentication corrects the latter without changing cookie-first auth. Its
  controller also failed to decode cp1252 console bytes after natural pytest
  completion; full raw journal/JUnit/log bytes and cleanup proof remain retained.
- The complete IP/error selection has 70 passes/eight explicit skips among 78
  identities (`ip-cors-complete-01`). The original unexpected500 CORS test has one
  genuine missing-header failure and two passes. Native configured CORS admission
  now applies to the safe unexpected error response as well; untrusted origins,
  route/body contracts and the server exception rethrow remain unchanged.
- The complete frontend source suite passed 1,286 tests before the final batch
  changes. Both final batch/page-control files resolve and execute all 11 cases
  in `import-batches-ui-replacement-02`, with natural exit zero. The earlier zero-
  test failed report remains Incomplete with unknown cause, not accepted coverage.
  An additional source-date dialog description correction awaits final replay.
- Independent source review identified pending acceptance risks: a reviewed
  separate-record decision ignored by the commit duplicate check, workspace
  defaults changing after preview, browser-storage-only interrupted recovery,
  stale identity facts in rescheduled reminders and quadratic same-mark commit
  hydration. These are being reproduced and corrected, not closed by static
  review. Fresh all-unusable jobs must not claim creation; safe all-duplicate
  outcomes remain nonfatal with explicit zero-created/skipped counts as required
  by the owner's document. Native-XLSX browser acceptance now includes a unique
  synthetic mark, actual commit and canonical/portfolio reload, not preview only.
- The current 34-case workflow contract replay after canonical cutoff30e passes
  with 102 phases and natural exit zero (`prod-workflow-cutoff-green-04`). The
  preceding unsupported journal CLI invocation failed before collection and is
  retained as Incomplete, not accepted evidence. The recorder uses its actual
  environment variable. Generated client has a first pass; final server contract
  and full new-source gates still remain.
- User workflow and complete source mapping are documented in
  `docs/ip-implementation/PORTFOLIO_IMPORT_AND_COURT_CALENDAR_USER_GUIDE.md`.
- `calendar-unit-red.json`: original page has two genuine failing assertions,
  missing overflow button and missing canonical court label.
- `calendar-unit-green-01.json`: the full Calendar page unit module passes
  after UI changes; this is local component proof, not deployed closure.
- API initial command used an unsupported journal option and is incomplete.
  `calendar-api-red-02/03` retain invalid fixture admission plus the genuine
  missing-field legacy failure. Corrected fixtures must establish sorting.
- `calendar-api-red-04` retains the missing High Court state fixture defect.
  The corrected `calendar-api-red-05` has two genuine failures: configured
  ordering and missing legacy court metadata. `calendar-api-green-01` passes
  all 13 selected API tests; every selected identity and all phases remain
  retained for reconciliation.
- `calendar-postgres-green-01` passes both selected native PostgreSQL identities,
  all six phases and two JUnit cases with natural exit zero, no skips/failures,
  unchanged source pins and confirmed owned-container/network removal. This
  uses an independently fresh migrated PG17 database, never tenant rows or the
  application DB as a clone template.
- Production read-only business probe on serving `3dbf364d` samples eight recent
  visible test-legal Matters: seven disposed and one active. Seven retained
  transitions are Active -> Disposed; no reopen is found in this sample.
  The sample is bounded and cannot establish the historical incident's cause.
  IDs are hashed and names/reasons/session secrets are not exported.
- Frozen `51ecde9c` full Docker gate is earlier scope and is not new-feature
  acceptance. Source changes here cannot inherit its image or test receipts.
- Independent static review found four acceptance gaps before release: mixed
  local-web/remote-API bootstrap, omitted stored hearing sessions, a Calendar
  response used as its own identity oracle, and an unrequired production
  invocation receipt. The corrections reject mixed targets before requests,
  verify the SHA before authentication/bootstrap, preserve time status/session,
  compare with saved Matter/catalog data, and require the new native receipt.
  Date-number details also expose the first three full identities on touch.
- `calendar-postgres-session-green-02`: all three native identities/nine phases
  pass, natural exit zero, unchanged source pins and owned-resource cleanup.
  Equal exact times, absent exact time and stored Afternoon session are covered.
  `calendar-touch-ui-green-04.json`: both full selected UI/validator files pass
  68 tests, zero skips/failures.
- `calendar-api-session-green-02` retains 47 passes, three expected native
  skips and one new test-selector error: both scheduled and dispatched jobs
  legitimately have evidence steps. The new assertion is scoped to the actual
  dispatch job. `prod-workflow-green-02` replaces all 34 workflow identities,
  with 102 passing phases and natural exit zero. The broader replacement and
  exact new-image browser gates remain outstanding.
- `calendar-api-complete-green-03` is the complete replacement selection:
  51 collected, 48 passed and three PostgreSQL-only skips. All three skipped
  identities have current passing native counterparts above. No missing test
  selection, failed phase or incomplete session is accepted. This remains
  scoped source proof; the new Docker and deployed journeys have not run.

## Do Not Close

PR535 head `7ec007c8` is draft and not deployed. Its complete CI38427578467
finished red: all eight native shards and API coverage shards11/12 failed;
the other eleven API shards and full Web passed. Security38427578388 and
CodeQL38427578420 passed. Browser/staging gates skipped after the failed
prerequisites and are not acceptance. All native shards were independently
inspected/reconciled: 2,912 unique tests, 2,888 passes and24 failed calls,
8,736 phases. Each failed authority fixture stops before its intended race.
Source-bound receipts are indexed in
`ci-7ec007c8-native1-readonly-01/aggregate-saved-receipts/README.md`.

A separately fresh native RED retains the actual preview DTO: both original
authority rows are rejected only for jurisdiction/office
`workspace_context_required`. No original assertion or validator was changed
for diagnosis. Positive fixtures now supply explicit synthetic reviewed context;
a new negative proves missing context still cannot create dockets or events.
The waiter observer now matches session-owned advisory acquisition, real
autocommit/backend PIDs, exact blocker and every original NOWAIT/deadline proof.
The first complete149-case native replay has147 passes/two failures: the
different actor correctly receives creator-only404 at the final obsolete
success expectation. Both failed reports remain retained. The test now requires
that exact denial, same-actor success and owner-only committed rows/dockets/
events; complete replacement is pending, not silently accepted.

`ip-private-authority-current149-native-02` is the complete replacement:
149 identities/447 passing ordered phases, zero skips/failures/errors, exact
collection/JUnit agreement and731 unchanged scoped source pins. The owned
controller and test processes completed naturally and resources were removed.
All earlier failed phases and setup attempts remain retained. This proves the
complete affected module, not the whole amended candidate or live production.

The API11 failure is a separately proven exact-list drift: the second workflow
test omitted `test-legal-write-oct13`. API12's own unchanged HTTP RED independently
confirms its declaration fixture's missing context, not a transferred native
diagnosis. Both complete amended modules pass128 identities/384 phases, no
skips/failures/XML errors, natural exit0. All declaration/nonfabrication and
workflow negative assertions remain, plus unapproved import/source-context
proof. These scoped source receipts are not fresh full CI/Docker or deployment.

Docker r1 stopped before acceptance on a PyPI dependency response-body timeout;
no app or browser outcome is inferred. All owned resources were removed. r2 is
the unchanged frozen7ec replay with a successful web image and slow API dependency
downloads; it cannot certify the later test-amended tree. Preserve both attempts
and complete a new exact-candidate gate after source/fixture reconciliation.

Latest scoped API replay `final-scoped-api-02` completed naturally with 142
collected identities, 128 passes and 14 PostgreSQL-only skips. The skips are
not passes; native counterparts and the complete new-image gate must still
be reconciled. Full Ruff and the production web build pass on the dirty
candidate. Neither establishes deployed acceptance.

Full frontend `full-web-final-02` retained two failures. Controlled observer
delivery reproduces those exact assertions and the corrected two complete
modules pass ten cases without changing UI assertions or deadlines. The
complete `full-web-final-replacement-03` subsequently retained 1,287 passes
and five failures across the same 1,292 identities/201 files. The original
two corrected controls pass. Each new failure was separately inspected:
Specialist intake, Intake and legal-hold tests fail before dependent data is
visible; Billing and foreign-associate tests retain runner stacks near their
original 15-second limit. Their original cache/action chronology is unknown.
Concurrent build/resource effects are not proven. An unchanged standalone
full replacement is required, not a timeout increase or isolated green claim.

The first forced import-claim-loss native attempt, `import-postgres-forced-loss-04`,
failed before collection at the bounded runtime-import preflight. It retains
no passing test evidence. Source pins are unchanged and owned PostgreSQL
resources were removed. A separately fresh replacement remains required.

`import-postgres-forced-loss-05` proves the actual lost-claim HTTP rejection but
fails an invalid test assumption about an already-closed SQLAlchemy wrapper's
`invalidated` property. The corrected `import-postgres-forced-loss-06` passes
its complete native identity/three phases: actual advisory unlock, exact 409
rejection, pool invalidation of the captured driver connection, closed driver
and successful replacement claim. Its source pins agree and owned resources
are removed. No application fence or deadline changed for this test correction.

The complete unchanged frontend `full-web-standalone-replacement-04` retains
1,290 passes and two failures. The Intake initial-list failure repeats; Contract
extraction records a 15-second runner-stack failure with an unknown action
boundary. All other run03 failures pass, but that does not establish resource
causation. A complete two-worker replay retains the same inventory, assertions
and original deadlines; its outcome must be reconciled before release.

CodeQL observer #565's final sentinel passes 86 native cases/258 phases plus
56 pure controls. It never clears another recorder's invalid mark and direct
control-flow interruptions propagate. Original unsafe-restore RED evidence,
all timing envelopes and cleanup remain retained. This is test-observer proof,
not fresh GitHub alert closure or a production GC-causality claim.

No item is Properly fixed until its committed dated Playwright journey passes
on exact local Docker and exact serving API/web revisions. Skips remain
Inconclusive. Hosted green CI, canonical main, guarded deploy, complete release
verification and two clean post-QA private-maintenance runs remain required.
Automated provider traffic remains prohibited; test-legal is the only authorized
production write tenant. GBA remains read-only and external consent/data gaps
stay open. No production lead submission or guessed legal-source content.
