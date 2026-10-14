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

## October 14 Acceptance Review Follow-Up

Exact d2e447e4 hosted native receipts reconcile 2,913 passing identities and
8,739 passing phases with zero failures, errors or skips. All 149 authority
admission cases pass. Hosted Web, Security and CodeQL pass; full browser CI
and local Docker are still incomplete. Production remains 3dbf364d on both
surfaces. These outcomes do not certify the subsequent browser-test amendments.

A separate review found genuine acceptance omissions, not reproduced product
defects: week/day clicks had no content assertions; small imports never reached
continuation or storage-loss recovery; the corrected renewal date was cleared
before its visible Portfolio reload; and month-only dialog instructions were
unqualified. The original review is retained in
`release-guide-browser-review-01/README.md`, including its partial matrix.

The dated journeys now assert persisted day/week hearing identities and timing,
all fourteen source mappings and original cell values, invalid-date warnings,
the visible corrected date before withdrawal, and a 101-row history recovery.
The latter retains one acknowledged 50-row server result, clears session storage,
then proves creator-owned resume202/resume200, exact progress, unchanged original
IDs, all 101 persisted canonical records and responsive visible reload. It does
not retry a failed mutation, mock an API response or make a paid provider call.
The guide qualifies date-number and overflow dialogs as month-view controls.

These changes remain pending execution on a new frozen candidate and the exact
production release. Test source, static review and type checking are not browser
acceptance. Native reminder dispatch and month-end arithmetic retain their own
evidence; a visible queued alert is not a delivered external notification.

## Code-Scanning Gate Correction

On ed856074, CodeQL's three analysis jobs passed, but the exact PR535 merge ref
still had open findings567 (an exported metadata constant) and568/569 (the new
Ops/Renewals cycle). No zero-findings or release claim is made from job success.
The adjacent notification-delivery/source-predicate back edge is also included
in the audit. Codex review's successful workflow skipped its actual review and
transcript steps after its key guard; this is not a completed automated review.

The source correction makes the import parser's existing exports explicit,
extracts the unchanged docket/actor guards into a neutral access module, and
extracts unchanged read-only source/provenance checks into a neutral source
module. Source-date correction stays with canonical docket version writes;
renewals and delivery no longer import each other's workflow owner. Existing
guard aliases remain available to all current callers. Query predicates,
capabilities, lock order, error details, source-date history and stale-intent
cancellation are not relaxed. New AST/dependency and export controls accompany
the existing PostgreSQL and browser workflows.

This integration correction is not release-certified yet. It requires
complete source-bound scoped replacements, fresh full CI/Docker, actual empty
candidate alert inventory, canonical main and the guarded/live release gates.
Earlier frozen acceptance attempts remain incomplete or failed; no old result
certifies this later service-boundary change.

## Hosted Browser Reconciliation

CI38450575816 on immutable ed856074 completed with 556 app cases: 534 passed,
two failed and20 skipped. All identities, zero-retry attempts, both JUnit files,
native receipts, complete individual errors and skip reasons are reconciled in
`ci-ed856074-browser-readonly-01/HANDOFF.md`. Both Calendar widths pass on that
CI checkout only. The IP desktop test fails before date-correction acceptance;
its three later serial cases do not execute and remain unverified.

The historical IPLF-030B journey expects an obsolete unresolved-duplicate
default and old commit copy. Its corrected journey positively proves default
Skip, explicit linking to the seeded docket, the distinct created docket,
1-created/1-linked counts and retained reload. The new IP journey queried one
exact application number but expected both same-mark rows; it now searches the
shared mark and asserts each exact application number and its saved docket href.
Neither finding justifies changing duplicate policy or identifier search.
The original failed assertions and full source-bound CI receipts remain intact.

Current seven-module source replacement completes109 cases:98 passed,11 explicit
native-environment skips,316 ordered phases, exact JUnit and all seven files,
nine unchanged source pins and natural exit0. This includes IP imports, current
source reminders, renewals and locked capability/coverage controls, not native
or deployed acceptance. New dependency controls retained the transitive Portal
and then Communications/document-processing back edges as RED until their
actual shared boundaries are corrected. No DAG assertion is relaxed.

## Shared Boundary Replacement Status

The directed Ops/Renewals/Delivery controls now pass after moving the exact
SendGrid sender to a neutral transport leaf. Communications retains its existing
alias; all fifteen existing sender mocks across six files additionally patch
the new delivery binding. The original sender AST, payload, timeout20, claim,
admission and ambiguous-acceptance behavior remain unchanged. The complete
101-case sender/caller replacement passes303 phases; its three DAG controls
pass separately. Evidence: sendgrid-transport-boundary-20261014-01/README.md.
These are local, deterministic checks, not paid delivery or native acceptance.

Portal and notification availability now share read-only current-source policy;
the original DTO enrichment and access audit remain with Portal. Twenty-eight
complete DTO/JSON parity vectors pass using fake sessions, not persisted native
rows. Fresh original HTTP journeys must also run through the isolated migrated
PostgreSQL fixture, alongside complete authority149 and notification races.
The new native adapter delegates sixteen cases to the unchanged original HTTP
assertions and real clock/monkeypatch fixtures. It asserts PostgreSQL and the
no-paid marker, without overriding the application or shared fixture policy.
Its source and Ruff checks do not constitute native execution evidence.
Earlier partial runs and all three dependency RED cohorts remain preserved.

The user cannot identify the allegedly reopened Matter. LIFE13-01 therefore
remains Inconclusive; neither an eight-record read nor a passing synthetic
dispose/reopen regression establishes its historical cause. No lifecycle fence
has been weakened. Fresh live fingerprints on October14 still serve3dbf364d on
both API and web. PR535 has not been merged or deployed.

## Native Replacement And Export Declaration

On47265b8d the complete eighteen-module local replacement reconciles369
identities:315 passes,54 explicit native-environment skips and1053 ordered
phases, zero failures and unchanged745 source pins. Its complete native
selection separately reconciles221 passes/663 phases with zero skips, errors,
failures or phase faults, all149 authority identities and all16 original HTTP
adapters. Source pins, JUnit, natural exit0 and owned resource cleanup agree.
Evidence: final-service-complete-20261014-01/reconciliation.json and
ip-portal-source-native-20261014-01/reconciliation-20261013T211723Z-2c87091b/receipt.json.
These are scoped local/native evidence, not full Docker or production closure.

Latest exact-ref CodeQL analysis1946885214 on merge db921fab has one finding570:
the retained public compatibility import is not declared as an export. Original
567/568/569 have fixed instances on the PR ref, with no dismissal. The new
declaration lists all twelve canonical renewal workflow functions and that
unchanged predicate. A regression requires one literal unique13-name inventory,
every callable and exact compatibility identity. No star-import consumer was
found. No function body, API schema, lock or policy changes for this declaration.
The [official query](https://github.com/github/codeql/blob/main/python/ql/src/Imports/UnusedImport.ql)
recognizes explicitly declared exports; no synthetic use or rule suppression
is introduced. Fresh actual analysis, full current-head CI/Docker and live
verification remain required. Production still serves3dbf364d.

The complete amended dependency/export/sender modules pass115 identities and
345 ordered phases with no skips or failures, exact JUnit, unchanged730 source
pins and natural exit0. Evidence: export570-service-complete-20261014-01/
reconciliation.json. This proves the new declaration and retained callable/DAG
contracts locally, not actual hosted alert closure or whole-release acceptance.

## Governance Change-Gate Omission

Exact ec035cf4 hosted CI38470077953 failed API job115547412945 before Ruff:
the canonical-base data-governance change gate rejected the new SendGrid
transport without a map update. Standalone map validation passed, but projection,
guide, migration and later validation commands were not reached. The complete
job log and exact merge/tree binding are retained in ci-ec035cf4-reconciliation-01/
failures/GOVERNANCE.md. This is not a Ruff diagnostic or a native race failure.

I missed the complete local control-plane command inventory before freezing
this candidate. Running focused lint/tests did not catch the missing governed
owner declaration. That omission cost another acceptance attempt and must not
be hidden by the preceding passing native scope or empty CodeQL inventory.
The original ec Docker run is superseded/incomplete; its completed first native
shard and partial second shard remain separate evidence, not a release pass.

The existing connector-and-payment-provider-held-records class now references
the unchanged sender and both caller owners. The latest note states its exact
wire data and unchanged upstream safeguards, with no new class, retention,
policy approval, external request or activation. Both generated views are
regenerated; runtime changes are only the reviewed-map fingerprint/projection
identity, not admitted classes, schema, handlers or policy. A regression proves
the truthful reference and continued change-gate refusal without map review.
Complete current CI contract commands, fresh source-bound tests, CI/Docker,
canonical merge, guarded deployment and exact live acceptance still remain.

## Positive Workspace Fixture Omission

Current c28 CI38479605818 completed with a failing browser job115589365035.
Its complete556-case receipt reports535 passes, one failure and20 skips.
The sole failed October13 IP1280 journey reaches the linked docket URL, but
line357 cannot find its heading: the retained page shows workspace setup with
missing_entitlement and workspace_configuration_missing. The local helper
bootstrapped a fresh tenant without the non-billable IP entitlement and manual
workspace configuration/enablement used by the existing IPLF030B fixture.
The product's setup gate is working; imported docket reads are not proof of
that distinct work area's readiness. This is a fixture failure, not proof that
the persisted docket is missing or that a lifecycle/access gate needs weakening.

I omitted those positive preconditions and used serial grouping for four
independent cases. Three following October13 IP cases consequently did not
execute; the later correction, mobile and acknowledged-history recovery
assertions remain unverified. Two October13 Calendar cases passed. Complete
native/API and scanning receipts do not erase this browser failure. Original
receipts, all20 skip annotations and the full error context are preserved in
ci-c28f584c-reconciliation-01/derived/browser. No production closure is claimed.

The replacement must establish only a fresh loopback tenant's non-billable
manual workspace, assert actual readiness before navigation, leave production
entitlements/configuration untouched, and execute all four independent IP
cases with one worker and no retries. Preserve every original import, saved
identity, source correction and recovery assertion. Full amended local Docker,
hosted CI, canonical merge and exact-release live replay still remain required.

## Renewal Correction Transport Defect

The amended fixture's complete four-case browser diagnostic now executes every
case. Both acknowledged-history recovery cases pass. Both source-import cases
reach the actual linked docket, then fail at source-date correction with422:
the API receives a JSON string instead of the required request object. Full
results and both complete errors remain in ip13-fixture-setup-recovery-c28f584c-01/
browser-four-02. The preceding outside-config global-setup resolution failure
is preserved separately as incomplete collection, not a product reproduction.

The new endpoint wrapper calls JSON.stringify before apiRequest serializes it
again. The shared client is correct. This same mistake was already documented
for BUG017 in addMatterStatuteReference; I reintroduced it in a new wrapper and
the mocked page handler did not inspect the real wire body. The earlier fixture
failure and serial cascade concealed the later defective workflow. Neither
better error copy nor a positive preview/commit could close that acceptance.

The correction passes the raw object through the unchanged client. A six-case
fetch-boundary regression initially has two genuine failures for date change
and null clearing, plus four passed rejection/no-retry controls. Original RED
JSON and JUnit remain at renewal-transport-red-01. It preserves exact version,
reason, JSON content type, cookie credentials and CSRF. Full adjacent-caller
audit, replacement transport/browser tests, fresh final Docker/CI and exact
production replay still remain required; no deployed fix is claimed.

The complete replacement transport/client/endpoints/import-page/fixture selection
passes38 cases across all five intended modules, zero failures/skips, natural
exit0. Proof: renewal-transport-complete-green-01 JSON/JUnit. This is scoped
local transport/UI evidence, not the required fresh browser or release gate.

A separate marked, read-only production readiness check at00:15:41Z confirms
test-legal on serving3dbf has a configured, enabled manual workspace with no
automations or configuration blockers, but lacks the IP entitlement. This is
different from the fresh local fixture's missing configuration. No subscription,
plan or production configuration was changed. Owner authorization for a
non-billable QA entitlement is pending; exact live acceptance cannot pretend
that this existing tenant is ready. Original source hashes and historical
reopening causation remain unchanged and Inconclusive respectively.

The fresh replacement browser-four-03 independently executes all four intended
IP cases: four passes, zero skips/failures/retries, exact collected/phase/JSON/
JUnit identities and2867 unchanged source pins across build and execution.
Both1280 and393 paths complete linked-record opening, correction/clear/reload
and acknowledged-history recovery. Owned processes are reaped and prior runtime
restored. This is dirty-source CI reproduction, not final Docker or live proof.

The adjacent TypeScript AST audit resolves679 client-bound calls in20 files,
including357 explicit bodies. It detects the known defect on immutable c28 and
zero additional offenders on corrected source. Opaque helper returns and
arbitrary interprocedural flows remain outside the proven scope; no formal
whole-program guarantee is claimed. Proof: api-request-preencoding-readonly-01.
The unchanged client's literal-string contract is also regression-tested so
caller mistakes cannot be hidden by guessing that string input is encoded JSON.

## Approved QA Entitlement And Current Release Checkpoint

On October14 the owner explicitly authorized non-billable manual IP for the
existing test-legal tenant only. This supersedes the pending-authorization
checkpoint above, not its read-only evidence. No production grant has executed.
The current subscription endpoint cannot set an IP-only override; upgrading
the whole plan or widening the normal QA bootstrap would exceed the scope.

The scoped one-shot operator uses the existing subscription and audit owners,
exact company/subscription identity, an inspected before-fingerprint and one
retained operation UUID. It changes the IP override and normal update timestamp
atomically with the receipt, preserving billing, other override keys, provider
flags, workspace configuration and GBA. A consumed operation must not regrant
after revocation. No new provider transmission, account, subscription, paid plan
or automated grant policy is authorized. Procedure:
`docs/runbooks/test-legal-manual-ip-qa-grant.md`.

The corrected f745a17d candidate has39 passed cases across the five complete
transport/client/endpoints/import-page/fixture modules. Its fresh real-browser
replay has four passes at1280 and393, without skips or mutation retries. All19
current API prerequisite commands pass on clean f745, with source and canonical
base unchanged. This is scoped proof only: the new operator and joined release
still require fresh final-source gates. Earlier c28 browser failure and its
interrupted Docker gate remain failed and incomplete respectively. PR535 has
not been merged or deployed; production remains3dbf364d at this checkpoint.

The final operator selection has39 SQLite passes/117 phases and29 PostgreSQL
passes/87 phases, with no failures/skips, exact ordered JUnit agreement, stable
source pins and owned-resource cleanup. Independent review caught an inspection
cleanup bug before production use: returning a pooled connection before clearing
query_only could poison another checkout, and always clearing to OFF could widen
a connection whose original state was ON. The corrected routine owns the exact
connection, restores its prior state on success/failure, and invalidates it when
cleanup fails. Native tests use the canonical independently migrated template;
an initial host-connection setup failure remains incomplete, not a product RED.
Proof: qa-manual-ip-operator-20261014-01/README.md.

Deployment-control review also found pre-production contract mistakes concealed
by handcrafted cloud fixtures: execution annotations belong at top-level v1
metadata, structured stdout is stored as jsonPayload, log visibility is delayed,
and protobuf Struct renders integer-valued JSON numbers as floats. Actual SDK/
protobuf contracts now drive the controls; observation can poll only an empty
log result within a deadline and never repeat the grant. The original failing
regressions remain in red-03/red-04/red-07. A complete amended helper selection
passes92 cases/276 phases; its final text-versus-structured numeric restriction
still requires the complete replacement proof before the joined release gate.

Production CLI inspection at02:00:34Z is read-only, source-pinned and reaped.
It establishes the service's complete before-fingerprint for the exact existing
test-legal subscription; it is not a grant or release acceptance. The approved
one-time request is prepared outside the release checkout and will be rechecked
under the grant's locks. Production still serves3dbf364d; no deployed closure is
claimed. The unidentified Matter incident remains Inconclusive.

The complete helper replacement now passes94 cases/282 phases, Ruff and Bash,
with unchanged owned source pins and natural/reaped exit0. Only structured
jsonPayload accepts protobuf's logical integer1.0; text JSON requires integer1
for both grant and inspection. Both new text-rejection RED cases are preserved
alongside the earlier92-case scope. Proof: qa-manual-ip-release-helper-20261014-01/
final-09/README.md. No cloud execution or production grant is inferred. The
joined candidate still needs full fresh gates and exact live acceptance.

## Source-Renewal Delivery Acceptance Follow-Up

IP13-07 (UJ-02/04/26, IPLF-037) had browser proof of queued/corrected/cleared
dates, not an actual delivered source-renewal alert. The dated portfolio journey
now makes a unique current source version due soon, identifies its exact single
in-app intent, requires one delivered attempt and visible delivered status after
reload, and opens that exact receipt in the admin surface at both widths. It
then clears the source date while retaining the original delivered history and
immutable import rows. Production only observes the ordinary scheduler; it does
not trigger a global worker or an external delivery. Loopback fixtures invoke
the actual delivery owner for only their own exact in-app intent and verify its
recipient/source receipt with zero external calls.

This is new acceptance coverage, not a claim of deployment or completed live
delivery. The replacement full-source release gates and live replay remain
required. Native current-facts tests retain the stronger body, lifecycle and
access assertions; admin receipt visibility alone does not prove those facts.
