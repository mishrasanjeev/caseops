# IP Controls And Renewal Tracker

## Scope And Current Verdict

The October 15 inputs are `CaseOps_Bugs (2).xlsx` (seven populated issue rows)
and `CaseOps_IP_Portfolio_Renewal_Deadline_Tracker_Specification.docx`.
The existing owners are J08/M08 for working-calendar surfaces and UJ-02/04/26,
IPLF-023/030/032/037 for IP deadline governance, portfolio, import and renewal.
This extends those workflows, not a separate IP product or deadline engine.

Release verdict: **NO-GO** until the new implementation has complete Docker,
CI/security, canonical-main deployment and exact-serving Playwright evidence.
Every new report is **Inconclusive** during reproduction and implementation.
The previously accepted source candidate ecb49cd2 is separate baseline evidence,
not proof that this new specification is implemented or deployed.

## Source Findings

- The seven bug rows cover working-calendar and rule selectors plus responsive
  layout in deadline, hearing, proposal and opposition forms. A blank selector
  does not establish missing legal data, permission failure or a broken popup.
  Inspect its actual response, options and policy before changing admission.
- The portfolio's column allowlist and defaults omit Application Date and
  Renewal Due Date. Renewal is currently embedded in the Deadlines cell.
- `schedule_imported_renewal_reminder` queues one start-date in-app intent.
  `synchronize_imported_renewal_reminder` suppresses a new intent after delivery
  for the same date. This does not implement daily recurring occurrences.
- The existing `portfolio-renewal-date` correction is imported-source-only and
  updates only renewal date. It is not an independent application-date editor
  for every current manual or imported trademark record.
- The specification's 31 March 2028 example is internally inconsistent.
  Its normative last-valid-day calendar rule yields **29 February 2028**.
  Use 28 February for 2027, not 2028. Do not silently implement the typo.
- Adjacent selector audit: `deadline_workspace` returns active rules for
  governance review even when company policy has not selected them. Proposal
  admission correctly rejects those rules. The new additive server-owned
  `eligible_rule_version_ids` applies that exact current policy without hiding
  governance history or issuing an extra query per rule. A complete ten-case
  local deadline-workflow module passes, including policy removal and retained
  active history; native PostgreSQL and live picker proof remain pending.
- A read-only production check on 15 October 2026 at 15:43 UTC pinned both
  API and web to `0c82fbb008b524cd8ad75df0a445edaeabc1199d`. The authorized
  test-legal workspace already allowed manual IP, but returned zero working
  calendars and zero rule versions. The loaded native selectors also contained
  zero options and Calculate was disabled. This establishes a missing source
  prerequisite and poor empty-state guidance, not a proven broken popup. The
  original screenshot's docket is unidentified; the check used a representative
  authorized docket, made no business writes and did not activate legal rules.

## Acceptance Inventory

| ID | Required User Outcome | Required Proof |
| --- | --- | --- |
| IP15-001 | Calendar selector distinguishes loading, load failure and no eligible active calendars. | Component negative states and exact browser options. |
| IP15-002 | Rule selector shows only eligible active versions with prerequisites explained. | Component policy negatives and keyboard browser selection. |
| IP15-003 | Deadline inputs and Calculate action remain readable without bypassing prerequisites. | Available-container widths and disabled-policy browser proof. |
| IP15-004 | Hearing/reminder fields remain usable and retain time/timezone values. | Save, reload and narrow-width browser journey. |
| IP15-005 | Calendar and tested-rule proposal forms reflow independently. | Container-bound field/button geometry at breakpoint boundaries. |
| IP15-006 | Opposition form and stage prerequisites remain legible and enforced. | Geometry and missing-prerequisite rejection. |
| IP15-007 | Application Date and Renewal Due Date are default visible columns and selectable columns. | Portfolio component and browser reload. |
| IP15-008 | Either nullable date can be edited independently without changing unrelated facts. | Versioned API, stale/terminal rejection and browser persisted read-back. |
| IP15-009 | Dates retain truthful Missing, Manual, Imported-unverified or verified provenance. | Server-source predicates and visible source labels. |
| IP15-010 | One-calendar-month start clamps correctly across leap years and year boundaries. | Deterministic exact date/time tests. |
| IP15-011 | Persistent reminders recur daily by default through the due date inclusive. | Worker clock-controlled next-day and due-day tests. |
| IP15-012 | Cadence and local delivery time are configurable in the existing workspace policy. | Validated policy, timezone and DST tests. |
| IP15-013 | Same occurrence cannot be delivered twice, including concurrent workers. | Database uniqueness, PostgreSQL race and replay. |
| IP15-014 | Import/edit/downtime catch-up creates one current occurrence, not missed-day bursts. | Deterministic multi-day recovery and idempotent backfill. |
| IP15-015 | Date change/removal replaces or cancels pending work atomically. | Immutable history, current-source delivery fence and race. |
| IP15-016 | Closed, renewed, cancelled or unauthorized records receive no new reminders. | Docket/Matter lifecycle, revoked access and cross-tenant negatives. |
| IP15-017 | Notification dismissal does not suppress tomorrow's reminder. | Two distinct daily occurrences after dismissal/delivery. |
| IP15-018 | Tracker categories and counts reflect the currently authorized database scope. | Pagination/filter/saved-view/export parity and query bounds. |
| IP15-019 | A queued intent is not displayed as confirmed delivery. | Attempt/delivered/error timestamps and truthful UI states. |
| IP15-020 | Failed delivery is visible and safely retryable without duplicate occurrence. | Delivery failure/recovery under the canonical notification worker. |
| IP15-021 | Existing optional-column, native-date and duplicate-import contracts stay valid. | Complete current import regressions and dated browser journeys. |
| IP15-022 | Existing records and original imported/custom values remain intact. | Migration/backfill idempotence, original-row preservation and reload. |

Responsive acceptance includes 393, 768, 1024, 1280 and 1536 pixel viewports
and actual space left after navigation and nested panels. Check minimum usable
control widths, sibling overlap and visible actions, not page overflow alone.
Desktop-only or DOM-presence checks do not close the layout reports.

## Permanent Learnings

The concrete weaknesses in the earlier implementation and verification were:

1. Retaining an imported date did not make it visible or independently editable
   in the portfolio. Read/write DTOs, columns, exports and the actual editor
   must be treated as one user contract.
2. Proving one queued or delivered start-date alert did not prove recurrence.
   The old test did not advance to a second eligible date or prove same-day
   deduplication under two workers.
3. Viewport breakpoints and `min-w-0` alone did not prove usable form fields
   inside the narrower IP detail panel. Actual widths, clipping, actions and
   saved values need browser assertions.
4. An active rule was offered as if it were calculation-eligible even when
   company policy had not selected it. The backend correctly refused it;
   the UI still invited a failing action.
5. A green candidate or a deployed image was not production certification.
   Prior unstarted/failed live journeys stay open until a complete exact-serving
   replacement passes. New reports are not covered by old report names.
6. The existing configuration HTTP helper rebuilt hidden policy from defaults.
   Adding reminder cadence to that form exposed the risk of dropping other
   asset types, jurisdictions, channels, calendar policy or provider settings.
   A new real-transport regression first failed with one failure and sixteen
   passes, then all seventeen passed after preserving the supplied current
   configuration. Async form hydration and complete browser acceptance remain
   part of the final gate, not covered by that transport test alone.
7. The new cadence controls were initially added to a setup-only screen.
   Source review showed that enabled workspaces could not reach them. The
   active workspace now has a capability-gated configuration entry, with ready
   and denied-role component regressions. The dated browser journey also saves
   and reloads local policy, then re-enables the manual workspace normally.
   Production acceptance observes existing configuration without rewriting it.
8. Carrying a checked prior-consent checkbox into a policy save could refresh
   the recorded provider acceptance actor and time. A separate transport
   regression first failed on that exact Boolean. The helper now retains
   existing unchanged consent and sends new acceptance only explicitly for a
   configured provider. Native persistence and full browser proof are still
   required; these are candidate findings, not historical production diagnoses.
9. Protecting only the new manual-date object left the older imported snapshot
   mutable through generic version updates. A genuine imported-record HTTP
   regression returned 200 after an unauthorized snapshot date change. The
   shared writer now preserves both reserved objects on omission and rejects
   explicit alteration or rebinding. Complete adjacent-module acceptance is
   23 passes on SQLite and 23 on PostgreSQL. Older fixture helpers now use
   canonical reasoned corrections and retain intermediate immutable versions,
   actors, audits and cancelled intents. Their complete two-module replay is
   39 PostgreSQL passes and 35 SQLite passes with four explicit PG-only skips.
   Whole Docker acceptance remains required. An import-row identity is not
   proof of values.
10. The first provenance fixture inventory missed a direct generic writer and
    a recipient's shared-helper assumptions. Complete CI exposed eight failed
    identities across six shards, including three fresh-head index checks.
    The source protection was correct; fixtures now use the canonical writer,
    actual versions and same-day receipt rules. The complete consumer audit
    includes the native adapter, not just imports of one helper.
11. A quiet-hours patch that works tomorrow morning can still block the next
    evening because today's earlier receipt exists. Queue and delivery checks
    now use the same effective local delivery date. Three consecutive overnight
    cycles and removal of quiet hours prove both recurrence and no duplicate
    receipt-day delivery, with all source/access/lifecycle bounds intact.
12. The models automatically attached six foreign-key support indexes that the
    new migration omitted. Metadata-created databases hid that difference.
    The migration now creates all six and independently fresh migrated schema
    health must pass. Its retained-evidence downgrade check also now excludes
    writers before reading under a bounded lock timeout; a real PostgreSQL race
    first proved the old code could erase a concurrently committed policy.
13. Moving six production cases to a new serialized partition did not move
    their step-local credentials. The actual resolved index step now receives
    the existing QA tenant bindings and has names-only fail-fast checks. The
    original missing-key regression failed before correction; all 14 new
    contract/guard cases and their three complete modules passed afterward.
14. The six added migration indexes changed governance fingerprints even though
    model metadata already contained those indexes. The assumption that no
    regeneration was needed was wrong. Canonical generation and rendering now
    precede all 12 actual CI preflight commands; all 12 passed locally.
15. The 101-row browser test started a ten-second final-visibility assertion
    while its first 50-row UI continuation was still outstanding. Restricted
    exact-serving diagnostics reproduced this twice; initial batches took
    16.39 and 25.56 seconds, below the unchanged 90-second request budget.
    The test now waits for both genuine acknowledgements and validates their
    status, source identity, version and row progress before the same visible
    completion assertion. Its 180-second total budget and ten-second visibility
    budget are unchanged, with no transport retry. The server's SQL timing is
    not established by that test failure; the unrelated health read remained
    responsive after abandonment. New local and exact-release browser proof
    is still required for the amended journey.

## Verification Checkpoint

The expanded backend inventory is 219 identities across 15 complete modules:
219 PostgreSQL passes / 657 ordered phases, and 147 SQLite passes with 72
explicit PostgreSQL-only exclusions. Both collected the same inventory.
The workflow/evidence/scheduler regression inventory is 270 passes / 810
ordered phases across three complete modules, with no skips. The earlier
failed and incomplete runs remain retained. These are scoped source checks,
not new whole-Docker or production acceptance.

The separate baseline b4bee6f8 is deployed but its exact-release production
run 38777040009 is NO-GO: 360 identities, 334 passes, 18 explicit skips and
eight failures. Both court Calendar and source-renewal portfolio journeys
passed at desktop/mobile widths. A separate unchanged six-case index replay
with the required QA environment then passed on b4bee, confirming the wiring
defect; it does not rewrite the failed workflow as green. The two 101-row
failures have separate exact-serving timing evidence as described above.
Their original ledgers retain 100 committed rows, one valid pending row,
zero failed rows and source values. The original jobs were not blindly resumed.
The new seven browser cases, the amended acknowledgement journey,
fresh whole Docker, green CI and a corrected exact-release replay remain
required before the new scope is marked fixed.

The `2cd44384` Docker admission failed before any browser case started: the
acknowledgement unit imported a helper absent from the web builder's explicit
dependency closure. The local Next build did not prove container packaging.
The unchanged closure inventory regression also reproduced both missing-input
failures. Admit only that helper in Docker and Cloud Build, copy it only into
the builder, and include it in the dirty-context guard. Negative regressions
must reject an omitted copy, either omitted allowlist entry and a dirty uploaded
helper. Retain this failed admission and rerun the fresh image and browser gates.

The first complete nine-case Docker diagnostic on `0ea00b90` passed both
101-row recovery widths but failed all seven new cases. All five controls
snapshots retained the correct disabled combobox and empty option; an exact
label locator missed it. The shared Field also rendered invalid nested labels.
The new unit assertion reproduced five nested labels before the markup fix.
Use one wrapping label with a styled span, target the actual named combobox,
and require exactly one visible control before an empty-inventory comparison.
Both tracker snapshots retained the intended row, but its `has` locator
incorrectly repeated the ancestor region inside each row. Correct that relative
locator in both the dated and missing-date states. These are not evidence of
lost source dates or missing controls. Preserve every option, policy, date,
geometry, reload and persistence assertion; the complete browser replay remains
required before closure.

The next diagnostic on `93caf94e` passed both tracker widths and both batch
widths. All five controls widths reached independent calendar activation and
received HTTP 403. One unchanged local 393px replay retained the exact problem:
`https://caseops.ai/errors/csrf`, `Missing CSRF token.` This was a cookie-only
test reviewer context without its required CSRF header, not a capability denial.
The fixture now creates a separate same-actor Bearer context, verifies the
current company/member/admin and activation capability, and disposes both
contexts on their respective failure paths. Both activation responses must
contain the requested identity and active status. No production CSRF, role,
entitlement, independent-review or legal-source guard changed.

The reviewer-fixture behavioral regression retained 3 passes and 28 failures
before the fix, then 47 passes across the complete new and shared fixture
modules. The unchanged authentication-cookie module also passed all 19 cases,
including rejection of missing and mismatched CSRF tokens. Independent review
found no actionable issue in the fixture correction.

Code scanning separately reported four quality notes, not new security-severity
findings: import-cycle alerts 579/580 and repeated-import alerts 581/582. Moving
the legacy imported-date adapter into the date-writer module removes the back
edge without changing its executable logic, public route, DTO, source gates,
locks or audit behavior. Dependency regressions cover lazy back edges, route
binding and both fresh import orders. Removing the two redundant local `json`
imports retains the existing module import. Fresh GitHub scanning must confirm
closure; source changes alone do not close the alerts.

The joined source checkpoint has 219 PostgreSQL passes with 657 ordered passing
phases across the complete 15-module native inventory. A separate SQLite and
dependency scope has 185 passes and 27 explicit PostgreSQL skips across 212
identities; it is not the same inventory as the native run. Its whole-tree pin
recorded the concurrent frontend fixture edit, so it is only scoped backend
proof, not a whole-source freeze claim. The fresh full web run has 1,443 passes
across 208 files, both type checks, coverage floors, a fresh build and discovery
of all seven new browser cases. Discovery is not browser execution. Whole
Docker, fresh CI and code scanning, canonical merge, guarded deployment and
exact-serving browser acceptance remain required. Production is still the
separate `b4bee6f8` baseline with failed certification, not this joined source.

The `a5d68f5b` nine-case Docker diagnostic then passed both tracker widths,
both batch widths and the 1280px controls journey. Four other controls widths
failed at the post-reload `response.json()` call with Chromium's
`Network.getResponseBody: No resource with given identifier found`. The exact
HTTP-status guard had passed. The upstream project's
[navigation/body-lifetime report](https://github.com/microsoft/playwright/issues/41512)
documents this protocol-resource boundary. These failures are retained; they
are not successful browser acceptance or evidence that the saved date was lost.

The correction removes both navigation-crossing GET response handles. After
each required reload, a mandatory same-owner authenticated API read retains all
existing identity, active-option and persisted-deadline checks. Native options
and the actual reloaded deadline/date must still be visible. The candidate card
must also appear before the second reload; it comes from the canonical workspace
query, not optimistic mutation state. POST acknowledgements, no-paid markers
and all budgets remain unchanged. This proves API/UI agreement, not the body of
the browser's particular GET. There is no catch-and-retry or fallback request.
All 47 fixture unit cases and the E2E type check pass after this test-only edit;
fresh complete browser and release acceptance remain pending.

During this batch, the first new column test also checked before loaded rows
were guaranteed. That failure cannot independently diagnose the product. The
corrected test waits for the actual loaded header; the earlier reports remain
retained rather than being relabelled as a clean product reproduction.

### October 16 Selected-Value Readability Correction

The `83e2bb01` isolated Docker diagnostic passed all nine selected cases, but
complete Linux CI38807524492 did not: 564 browser identities contained 542
passes, 17 explicit skips and five controls failures. All five reported the
colleague selector; the 1280/1536px cases also reported the calendar selector.
The old geometry helper retained only concatenated option text, not the failing
numeric predicate. Its green Windows result was not cross-platform readability
proof. These CI failures remain retained rather than dismissed or retried away.

An isolated matching Playwright1.60/Chromium148 headless-shell probe produced
220 measurements: all 90 long-selection failures were scroll-overflow checks,
while short selections and all box/containment predicates passed. A prior
Chromium153 probe returned equal scroll/client widths despite visibly clipped
long text. Both were fixed-HTML diagnostics, not actual app or release
acceptance. Additional remote-browser app probes stopped in transport/runtime
observer setup before the original app body and remain inconclusive. They
created no app fixture or successful product proof.

The resulting correction gives PersonPicker a visible, wrapping current
identity description. Rule and calendar options reuse their complete typed
caption in the existing visible detail, including distinguishing source facts.
Descriptions bind the actual selected source ID; changing or clearing a value
must not leave stale evidence. Existing membership, eligibility, approval and
keyboard behavior remain unchanged. There is no CSS overflow-hiding repair.

The browser guard retains useful-width, viewport, form and page bounds. A
native scroll-overflow result is acceptable only when a unique linked detail
has the same current source ID and complete caption, is visible in normal
flow, remains unclipped within its owning layout and overlaps no control.
Known source-backed choices require this detail even on browsers that report
no native overflow. Numeric diagnostics omit private option labels and values.
Eighteen pure-DOM guard regressions cover the valid presentation and missing,
stale, wrong, hidden, transparent, clipped, ellipsized or absolutely positioned
details, ancestor clipping, escaped owning-layout bounds, narrow/out-of-bounds
controls, empty choices and non-select overflow. The ancestor-clipping negative
first failed against the new guard (16 passes, one failure), then passed after
the visibility check included the clipping ancestors. That failure is retained.
The full controls journeys cover 393px and below/at/above 640, 768, 1024, 1280
and 1536px, with long rule/calendar fixtures and selection/clear checks.

The obsolete `83e2bb01` whole Docker run was intentionally interrupted after
its complete 3,036-test PostgreSQL gate passed with 9,108 ordered phases and no
skips/retries. Completed desktop shard1 has 281 passes and two explicit skips;
the remaining browser run is incomplete and Review did not run. Its retained
partial inventory is not final release acceptance. All owned processes,
containers, networks and volumes were removed before source editing. The
corrected candidate still requires fresh complete Docker, CI, canonical-main
merge, guarded deployment, exact-serving replay and private-cadence evidence.

Independent joined review also caught a release-consumer mismatch before
freezing: the expanded controls file defines 34 cases (16 widths and 18 guard
contracts), while the evidence producer still expected five. The exact dated
partition is now 42 cases: two hearings, four portfolio, 34 controls and two
tracker journeys. The reviewed 115/6/42 partition and per-file count fences stay
strict. Backend consumer regressions reject missing or substituted files, and
a standard web regression runs the real production configuration's collection,
not app execution, and checks its exact identities and disjoint file inventory.
This is collection proof, not successful execution of those 42 journeys.

The subsequent `7357b9bb` full web run passed all 1,451 tests in 209 files,
both type checks and a fresh build. Its early Docker preview was still NO-GO:
38 cases completed with 22 passes, 16 failures and no skips or retries. The
393/639px cases reached a later caption-fact check that reused the calendar's
original draft status after successful activation. The current active caption
and approved-workspace checks were correct; this expectation now uses the
activation response's current status. Fact diagnostics name the field without
printing its private value. A negative inside the existing guard rejects the
stale draft expectation and accepts the activated state.

The other fourteen widths failed earlier, at the reloaded hearing's reschedule
date input: its `sm:w-auto` produced a 149px box against the useful-width
contract. This is a separate adjacent layout gap, not another activation
failure. Date/time action controls use stable responsive widths capped by the
actual available container instead. Each controls journey now changes the
hearing date through its real action, checks the PATCH acknowledgement and
visible result, then requires a reload and same-owner API proof that the new
date retained exact time, timezone and purpose. The 34/42 reviewed case counts
are unchanged. All sixteen old preview failures remain retained; the full
Docker gate and Review did not start on that failed candidate. This product
layout amendment requires fresh full web, CI, Docker and production evidence.

The empty production selectors also demonstrate why testing only synthetic
positive options was insufficient. Reconcile the real eligible API identities
with the loaded native options. Test honest empty, loading and failed requests
separately, then exercise independent review and selection using isolated local
legal-rule fixtures. Do not publish invented production rules to turn a missing
configuration into a misleading success.

The earlier one-month alert implementation matched a single date but did not
prove a recurring series. Future recurrence acceptance must advance the clock,
prove distinct consecutive occurrences, replay the same occurrence and inspect
real persisted delivery content. A queued or delivered label alone is not proof.

Nested forms must respond to their own available width. Viewport breakpoints
alone can produce unusable fields inside a narrow detail pane even when the
whole browser is wide. Assert actual control geometry and action visibility.

No reported Matter identity was available for the historical reopening claim.
Its cause remains **Inconclusive**. Preserve dedicated lifecycle transitions,
stale-write rejection, terminal children and audit evidence; do not invent an
automatic reopening cause or weaken the existing protections.

## Release And Configuration Boundaries

- All automated acceptance sends `X-CaseOps-Automated-Test: no-paid-providers`.
  Local Docker uses deterministic provider emulators. No paid external probes.
- In-app reminders must work independently of Outlook or Google consent.
  This change does not authorize external delivery or invent legal deadlines.
- Manual IP is already enabled for test-legal by the consumed one-time operation.
  Do not grant again, alter GBA, change paid plans or broaden provider policy.
- Preserve old failed/incomplete evidence. Do not describe skipped checks as
  passes or transfer the baseline candidate's green results to new source.
- Update the separate Downloads summary and the prior IP/Calendar summary with
  exact implementation, test and serving-release truth before closure.
