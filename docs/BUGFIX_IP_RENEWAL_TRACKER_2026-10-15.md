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

During this batch, the first new column test also checked before loaded rows
were guaranteed. That failure cannot independently diagnose the product. The
corrected test waits for the actual loaded header; the earlier reports remain
retained rather than being relabelled as a clean product reproduction.

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
