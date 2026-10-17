# IP And Calendar Remaining Acceptance

## Scope And Baseline

Owner request: 17 October 2026. Fix the remaining partial and unverified rows
in the two Downloads IP/Calendar summaries, verify local Docker and the exact
production release, and update both workbooks with actual Playwright results.
This extends J08/M08, UJ-02/04/26 and IPLF-023/030/032/037, not a new product.

Canonical main and both production surfaces are
`6af384f81037d6e3a1609f70d54b4525a6772a9b`. Production verification
[38989524122](https://github.com/mishrasanjeev/caseops/actions/runs/38989524122)
completed 396 cases: 378 passed, 18 explicit skips, zero failures or retries.
All 42 dated cases passed. Guarded private maintenance resumed after two clean
post-QA runs. Earlier 29d/599 budget/resume checkpoints remain failed history,
not current deployment blockers. Those results do not accept new source changes.

Fresh workbook imports retain 14 original findings (12 properly fixed, one
partial, one inconclusive), eight Batch2 findings (five properly fixed, three
partial), and 22 acceptance outcomes (17 properly fixed, five partial).
There are ten remaining rows across these three tables, not ten distinct
independent defects. Preserve the original rows, history and evidence.
The initial working count of eleven was an arithmetic overcount, corrected by
the actual worksheet inventory (two plus three plus five); no source row was
removed or omitted.

## Remaining Row Inventory

| Row | Missing Outcome Or Evidence | Classification At Start |
| --- | --- | --- |
| CAL13-04 | External Calendar consent, synchronization and delivery acceptance | Partially fixed; distinguish provider/consent from code defects |
| LIFE13-01 | Identify the reported Matter and persisted historical reopening audit | Inconclusive; no incident identity was supplied |
| B2-BUG-001 | Positive currently eligible approved working-calendar selection | Partially fixed; real source configuration was absent |
| B2-BUG-002 | Positive approved policy-selected rule selection/calculation | Partially fixed; real source configuration was absent |
| B2-ENH-001 | Complete the remaining tracker/reminder/source outcomes below | Partially fixed; aggregate enhancement, not a separate duplicate implementation |
| IP15-002 | Keyboard selection with genuine eligible rule and prerequisite proof | Partially fixed |
| IP15-004 | Date-only/exact hearing time, timezone, source, channel and offset save/reload | Partially fixed |
| IP15-009 | Positive date-source verification without conflating manual/imported facts | Partially fixed; no genuine verified-positive source was established |
| IP15-017 | Actual notification dismissal, then independent next-day recurrence | Partially fixed; read/unread is not dismissal |
| IP15-018 | New filters, saved views, export and complete category continuation parity | Partially fixed |

## Implementation And Verification Order

1. Read the original requirements, current schemas/services/UI and native test
   inventory. Reproduce missing behavior and retain the first failure. Separate
   missing code, missing coverage, absent source data and external consent.
2. Extend the existing tracker and table preferences/export owners, not a
   separate report. Every filter, count, continuation and export must share the
   same current tenant/access/lifecycle and source-date scope. Keep bounded SQL
   work and reject stale or incompatible continuation state.
3. Add genuine retained notification dismissal if absent. Dismiss only the
   recipient's occurrence; keep the delivery receipt, source identity and
   recurring series intact. Distinguish restoration/read status from tomorrow's
   occurrence. Extend the existing hearing/reminder workflow and controls only
   where a concrete missing contract is demonstrated.
4. Audit the positive source/Calendar paths. Never invent an approved legal
   calendar, rule, verified date or OAuth consent to make acceptance green.
   Existing governance, source/version/hash, independent review and current
   policy eligibility remain authoritative. Manual dates stay unverified unless
   a supported canonical source actually establishes otherwise.
5. Add committed dated browser journeys with actual persisted identities at
   desktop and narrow widths. Local deterministic clock/provider fixtures must
   remain loopback-only; do not simulate a future production clock or spend
   provider credits. Inventory the new specs in standard Docker and production
   configurations, including required native receipts.
6. Run focused unit/native PostgreSQL negatives and races, full current local
   Docker acceptance, required build/security/CI gates, merge canonical main,
   guarded exact-main deployment and exact-serving production replay. Retain
   every failed and incomplete attempt. Finish private cadence and worker gates.
7. Publish workbook verdicts from actual case identities and results. A skip,
   unavailable source, pending consent or unknown historical cause cannot be
   relabelled as a pass. Do not replay the consumed test-legal manual-IP grant.

## Required Regression Boundaries

- Tenant/recipient isolation and current docket/Matter access after source or
  lifecycle changes; no silent reopening or child resurrection.
- Retained notification receipt and idempotency after dismissal, independent
  next-day recurrence, same-occurrence replay and preference/quiet-hour rules.
- Exact hearing/reminder date, precision, timezone, source/channel/offset after
  save and reload; date-only must never acquire a fabricated exact time.
- Filter/count/cursor/saved-view/export agreement, complete category paging,
  invalid ranges, stale views, missing dates, closed rows and query-work bounds.
- Manual/imported-unverified provenance and forged/stale verification rejection;
  any genuine positive must retain its actual source and verification boundary.
- Google/Microsoft connection, expired/revoked consent, permission and safe
  recovery contracts without equating deterministic local emulators with live
  external delivery.

## Current Verdict

### Source And Live Configuration Discovery

Owner directed autonomous source discovery. On 17 October, the official
IP India Rules listing supplied a working 97-page Trade Marks Rules 2017 PDF,
retained with SHA-256
`b858aa6874a4373be03b1ee3a7a926f9f7b79dc7a15dbffdc2109cf6c3a33e92`.
Visual review of pages 66-67 includes the renewal chapter and the continuation
of rule 59 before rules 60-61. This is a retained publication, not proof of an
individual registration's current renewal date or completion of independent
rule review. Source:
[official Rules PDF](https://ipindia.gov.in/storage/uploads/docs-operator/f558da2b-ff4f-46bb-9f26-80d7ff16eba9.pdf).

Two official closure notices were also retained and visually read: the
9 April memorandum declaring 14 April 2026 a Central Government holiday
(SHA-256 `1e812ca709730feecafecedc58873e63eab0e18d068550af13729db4fe7e0ff1`),
and the 9 September circular closing Delhi/New Delhi IP offices on
11 September 2026
(`548937d4e81d63578a1ea4d9a99bd99f2abc268e757cc5c52d28d003da346b41`).
They establish those notices, not a complete office/year calendar. Annual
office scope, later amendments, weekends and exceptional working days still
need reconciliation before activation. No production legal record was created
or approved, and no existing reviewer identity was impersonated.
The official six-page DoPT 2026 annual memorandum was subsequently acquired,
hashed and visually reviewed. The full source/provenance distinction is in
[IP Calendar Source Review](IP_CALENDAR_SOURCE_REVIEW_2026-10-17.md).

Initial authenticated production UI inspection displayed Google Calendar
OAuth **not configured** with Connect disabled. That display was not proof of
absent configuration: the subsequent source-bound API readback at
04:38:19 UTC reports tenant-admin Google Workspace configuration present and
Calendar enabled. Ram's own Calendar connection is revoked; another member's
connection count cannot certify his access. Outlook is actually unconfigured.
Neither Google configuration nor a separate Gmail connection establishes
current Calendar consent or successful external delivery.

The repeated readback at exact API/web6af identified 14 `delete_pending` syncs
and one dead-letter sync. The backend admits `delete_pending`, while the web
validator omitted it. Parsing therefore rejected the successful status response
and the page presented that load failure as absent credentials. New contract
and page tests reproduced all five failures (26/31 pass), then the complete
replacement selection passed32/32 after preserving all seven typed states,
adding a retryable readiness error and retaining unknown/loading as unknown.
The intermediate30/31 result remains failed evidence: its older month fixture
omitted the Google provider entry while expecting fabricated missing names.
That fixture now supplies an explicit negative Google configuration, with a
separate unknown-provider-entry regression. No status row, cleanup tombstone,
OAuth grant or provider request was changed to make the UI green.

Adjacent Google/Outlook bulk responses had the same omission, reproduced
separately (40/41 passes), and now share one strict status validator. Exhaustive
typed fixtures bind its cases to generated backend types rather than allowing
arbitrary strings. Google, Outlook and Gmail loading/error handling was also
checked; unavailable reads no longer invent credential or webhook failures or
enable a connection while readiness is unknown. The complete affected web
selection passed96/96 across three files (17 contract, 51 existing schema and
28 Calendar-page cases), with zero skipped cases. These are focused source
results, not completed browser/Docker/production acceptance.

The same readback found exactly one registry link in the authorized tenant's
complete returned link inventory: candidate match status and zero retained
snapshots. The 25-row portfolio sample contains manual/missing date states;
it is not a whole-portfolio absence claim. No genuine reviewed positive
registration-date authority was discovered or created by these reads.

New `ram-2026-10-17-calendar-readiness.spec.ts` defines the corresponding
1280/393 API-to-visible-readiness journey in app/Docker and production selection.
It is candidate-source coverage only until commit, actual Docker and serving replay
complete. No mailbox import, provider sync, revocation or event write was
triggered by the discovery reads.

### Integration Freeze Checkpoint

The candidate implements recipient-owned read/dismiss/restore without cancelling
the renewal series, hearing reminder detail retention, tracker date filters and
scope-bound pagination, and Calendar credential refresh and truthful readiness.
Their dated browser journeys are registered in the standard suite. Four local
Google/Microsoft emulator cases are deliberately absent from production consent
acceptance. Production's reviewed tester partition expands from42 to50 cases;
the independent native and frontend inventory assertions now require that same
seven-file partition. Collection is not execution.

The first full frontend attempt completed1519 tests but failed its inventory
suite's eight-second child collection budget; its four test bodies did not run.
It is not a full pass. That assertion also still named the prior42-case partition.
Selecting only its three reviewed projects, rather than every unrelated project,
preserves the same assertions and budget; the four focused inventory assertions
then passed in1.10 seconds. Complete replacement coverage/build results and all
Docker/hosted/production results remain required, with failed evidence retained.

Review also found that case-folded cursor scope could merge distinct SQL search
queries. A SQLite/PostgreSQL pair reproduced the prior normalization failure and
passed after using the search predicate's canonical lower-casing. This pair is
not a replacement for the previous124-case tracker selection or joined gates.

New work is **NO-GO / Inconclusive** until the relevant amended-source gates
and user-visible outcomes pass. The serving baseline remains separately
certified with its recorded caveats. No new implementation or acceptance is
claimed by this planning checkpoint.

### Review Follow-Up Before Release

PR542 review found a revoked-cleanup token-refresh uncertainty path that could
reuse an old refresh token after an indeterminate provider outcome. It also
found that saved recipient labels depended on a directory cache populated by
another mounted workflow. The latter reproduced in two cold-cache read-only
and failed-read/retry tests; the complete IP page replacement passed57/57 after
enabling the shared read only when saved recipients need resolution. Existing
cached identities still avoid a duplicate request; unknown/inactive assignments
remain retained, and retry performs no hearing or membership mutation.

The refresh regression's first six-case run retained four failures and two
successful cleanup controls. For both providers, three cleanup attempts could
make three token POSTs after an uncertain failure. The correction retains the
encrypted own claim after failed/stale completion and lease expiry; revoked
status remains revoked. A successful rotation still clears its own claim.
Fresh consent, rather than an elapsed lease, owns replacing uncertain tokens.
The replacement complete-module and native checks are distinct required gates.

CodeQL583 identified a potentially uninitialized test fixture recipient ID.
Explicit initialization and a branch assertion preserve the recipient-isolation
test rather than suppressing the diagnostic. A fresh analyzer result is required.

The first full Docker attempt at `a874fb3e` was intentionally interrupted during
image building before PostgreSQL or browser bodies ran. Its log is retained as
incomplete evidence, not a successful gate. The exact two empty run-owned
networks were checked and removed; unrelated containers and volumes were left
untouched. The prior full web result was1523/1523, and the canonical focused
backend completed315 passed/53 explicit PostgreSQL skips across368 identities.
Those are prior-candidate scoped results, not substitutes for the corrected
candidate's fresh complete Docker, hosted, merge and production gates.

CI also exposed an incomplete publication step in this work: the governance
map was rendered, but its generated runtime data-class projection was not,
despite the existing repository instruction requiring both. The resulting
fail-closed CI rejection is retained, not called a Ruff or product failure.
Both artifacts are now regenerated and the complete contract chain is rerun.
The generated change carries only the reviewed map/projection fingerprints;
schema, registered class fields and disposition authority remain unchanged.

The complete hosted API shard9 then found two real Calendar drift regressions
on19a862d4: an invalid encrypted envelope and malformed decrypted JSON escaped
the new preflight before the existing per-connection unreadable boundary. Its
949-case result was809 passed/138 skipped/2 failed, with all2709 phases
reconciled. Focused OAuth/refresh suites had omitted this older drift module;
their green results did not cover this caller. The second Docker attempt was
stopped during native group2: group1's387 identities remain separately retained,
the interrupted group's raw runtime/journal was copied, and only the owned
Compose resources were removed. There was no full Docker pass or deployment.

Expanded local regression also establishes that a rejected refresh must not
abort other connections, and an already errored grant must remain unreadable.
All four cases failed before correction. The corrected drift path records only
an unknown diagnostic after fresh authority checks, never reads with a rejected
or uncertain token, never promotes an errored grant to a positive match, and
does not reactivate the connection. Complete affected-caller inventory and
replacement gates are required before the next Docker freeze.

Readiness has the same adjacent preflight boundary: corrupt credentials must
clear a previous passed result, while a rejected renewal must not mistake its
own committed error state for a concurrent consent change. Three failing
readiness regressions preceded the correction. The helper now carries only its
own non-stale, hashed connection receipt, captured after flush under its existing
locks and exposed only after a successful commit. Current membership, step-up,
probe claim, config and connection checks still decide finalization; a new
consent, revocation or authority change must win. Native forced-interleaving
acceptance is required, not inferred from the receipt's shape.

The old 24-module caller run has an incremental journal but no natural session
completion after the execution context was lost. It is incomplete, not green.
The committed candidate was recovered in a fresh checkout, and uncommitted
corrections were recovered from their exact retained patch records. Earlier
scoped passes remain historical; only fresh current-source gates can authorize
the merge and release. The original new-consent native race also reused an
already consumed OAuth code: that is a fixture failure, not evidence that new
consent was overwritten. Its replacement must prove a genuinely fresh callback
and persisted credential before asserting the race outcome.
