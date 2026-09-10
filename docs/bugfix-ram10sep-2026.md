# Ram September 10: Reopened Statutes And Hearing Matching

Owner: Codex. Release verdict: **NO-GO**. Both reported workflows remain open.
This record extends the existing catalogue and hearing work, not a second
implementation of either module.

## Source Reconciliation

`CaseOps_Bugs_10Sep2026.xlsx`, sheet `Bug Sheet`, has exactly two populated
issue rows, 2 and 3. SHA-256:
`c2a67eea079182a80c664247525f963327470ff7be5c4f846f3575fe271fd09e`.
Both embedded screenshots were extracted and inspected. The source is unchanged.
Credentials are runtime inputs and are omitted from committed evidence.

| Row | Issue | Assessment | Verdict | Existing ownership |
| --- | --- | --- | --- | --- |
| 2 | BUG-013 | Valid blocked statute-reference workflow, reopening BUG-010/011. The allegation that already-verified records are misclassified is not established by the production sample: BSA lacks verification metadata. | Inconclusive | J05/J07, MOD-TS-017, US-046A-D, FT-S1..S4, IPLF-006 |
| 3 | BUG-014 | Valid missing-date complaint plus an enhancement to the non-CNR identity contract. Differentiate missing court identity, unsupported scope, scheduled tenant exclusion, provider failure and ambiguous matching. | Inconclusive | J08/M08, MOD-TS-006, US-022/023/024/025/057, FT-078-082, NFT-021, SEC-027 |

## Fresh Production Findings

Read-only authenticated Playwright/API inspection on September 10 used the
authoritative no-paid-provider marker. No search, refresh or paid operation was
submitted. Both API and web identify the serving release as
`5145fb3a4b51b26af116220ff10a7389bde6324d` (API revision
`caseops-api-00445-wdz`, web revision `caseops-web-00422-d9r`). The dirty candidate
and previous agent worktrees have not been deployed.

- All 23 statute options were observed after loading. Seventeen have zero
  selectable provisions. Totals are 1,632 verified and 4,336 catalogued sections.
  All nine reported Acts remain disabled in production.
- The sampled BSA parent is `unverified`, with no exact source version, source
  hash or issuing body. Its seven catalogue entries are pending and the verified
  sections response is empty. This is evidence of incomplete deployed source
  data, not permission to relabel those entries verified.
- The four screenshot Matters have persisted null next-hearing dates. Codes
  5977, 5967 and 5927 have case numbers but no CNR, court, catalogue entry,
  state, district, city or filing number. Code 5926 has case number
  `FA/878/2024` and the server-owned `consumer:ncdrc` entry, but no CNR.
  The latter requires its own provider-scope/match diagnosis.
- The retained original import cells were recovered and checked, not inferred
  from the normalized response. Source hash `d26da74d737def7f1911864e32f7a0abdb25eeb8dd553c8dc90a31d2755887ee`
  matches the September 8 completed import. Original Excel rows 490, 480 and
  457 supply `DRT` or `State Commission` with a blank Court and no location.
  Row 456 supplies `National Commission`, resolved to NCDRC. The first three
  do not contain a discarded leaf court that could safely be restored.
- All four are active at lifecycle version zero. The workbook's reopened bug
  status is not evidence of a disposed Matter being automatically resurrected.
  No lifecycle mutation was performed during this inspection.
- The follow-up workspace inspection found no attachments, court orders,
  cause-list entries, notes, hearing records or descriptions on any of the four
  Matters. Each retained activity history contains only Matter creation and
  case-tracking linkage, both on September 8. There is no retained source from
  which to recover the first three missing courts. Exact court/location or CNR
  clarification has been requested while implementation continues. Evidence:
  `matter-source-context-readonly-01.json`; no provider call or mutation.
- The status endpoint exposes configured credentials, not actual scheduled
  eligibility. The previously diagnosed static `test-legal` scheduled paid-call
  exclusion must remain intact. A configured flag cannot establish a successful
  hearing refresh or a funded provider account.
- A separate read-only bookmark inspection at 04:04 UTC found all four already
  auto-linked, with no attempted or successful provider check and no provider
  court code. All four advertise manual refresh as allowed, including the three
  with no CNR or court. Corrected-identity recovery and actionable eligibility
  are therefore required for existing bookmarks, not only new admission.
- The current Cloud Scheduler configuration is enabled at `0 18 * * *` in
  `Asia/Kolkata`, last attempted September 9 at 12:30 UTC. The candidate's
  five-minute continuation window is not deployed. Scheduler dispatch is not
  proof of provider or per-Matter success.

Raw evidence is retained outside git under
`C:/tmp/caseops-sep10-20260910/`. `production-readonly-01.json` captured the
loading option too early. `production-readonly-02.json` captured the complete
statute selector but its subsequent Matter locator timed out because the table
uses an interactive row role. These attempts are retained, not labelled complete
browser acceptance. The corrected read-only `production-readonly-03.json`
completed on September 10 at 03:53 UTC, captured all 23 loaded Act options and
the actual Matter list, and recorded zero paid actions. This reproduces the
production symptoms; it is not post-fix acceptance. API records and the captured
screen establish the observations above; positive fixed-flow acceptance is
still required.

## Implementation And Acceptance Contract

| ID | Required outcome | Negative and adjacent coverage |
| --- | --- | --- |
| RAM10-S1 | Every reported Act with admitted official content is selectable, has positive verified sections, attaches and persists after reload. | Missing metadata, empty text, absent hash/version, invalid source link, historical applicability and genuinely unverified entries stay fail-closed. |
| RAM10-S2 | Reconcile every admitted provision against the exact official source edition and complete inventory. | One positive fixture, seed row counts or Act names cannot certify complete source coverage. Keep retired/quarantined/missing counts distinct. |
| RAM10-H1 | CNR remains the primary exact identity. Without CNR, a canonical court plus exact public registration/filing/case identity is corroborated against every available supplied field. | Conflicting type/year/location/parties fail closed; missing court or party-only evidence cannot be guessed into a match. |
| RAM10-H2 | Scheduled discovery resolves one unique verified candidate and writes the nearest upcoming date into the existing Matter field/list. | Zero, multiple or truncated candidates, unsupported scope, provider errors, past dates and manual locks do not become a guessed date. |
| RAM10-H3 | The reported identities and equivalent fresh local fixtures show the actual date after scheduled execution, reload and at 393/768/1280px. | Assert the specific row value, not just a heading, HTTP 200 or job exit. Separate intentional QA no-paid exclusion from a positive emulator journey. |
| RAM10-H4 | Provider operations release transactions during transport and retain expiring claims, cost accounting and post-I/O access/identity/lifecycle validation. | PostgreSQL manual and scheduled races, worker crash, stale token, revoked access, disposal and identity correction must not publish stale results. |
| RAM10-R1 | Exact candidate source passes local Docker API, PostgreSQL, frontend, dated Playwright, migration and security gates before publication. | Preserve every failed/interrupted attempt and reconcile the complete collected test inventory. Do not reuse old-image evidence. |
| RAM10-R2 | Current canonical main passes CI and deploys exact API/web/job images, release-owned seeds and scheduler configuration. | Rerun dated production Playwright with no-paid isolation. Keep live paid provider verification a separate bounded operational probe. |

## Why The Reports Recurred

1. Source-tree changes and partial content were conflated with deployed,
   complete user workflows. The September 10 production identity confirms the
   expanded catalogue candidate is still absent there.
2. Earlier catalogue acceptance sampled a few positive Acts. That cannot prove
   the reported nine Acts, complete editions, schedules or every consumer.
3. Earlier hearing acceptance observed a column heading and job execution,
   without proving the specific Matter's persisted date and identity inputs.
4. Test-tenant policy, configured credentials, live provider availability and
   scheduled eligibility were not separately visible or separately certified.
5. Interrupted broad gates left no complete result inventory. New pytest runs
   must stream structured setup/call/teardown evidence and a completion event;
   green progress lines cannot substitute for completion.

Do not repair recurrence by weakening verification, allowing paid test calls,
guessing legal identities, retrying uncertain mutations or erasing failed proof.
Permanent safeguards belong in regressions and the release gate, not only here.

## Current Execution

Catalogue, non-CNR hearing matching and async provider-summary integration have
separate owners. Existing IP foundations and patent work is being recovered from
its retained worktrees without overwriting their changes. Shared contracts,
documentation, final integration and deployment remain owned by the main task.
No new issue has been marked fixed, committed, pushed or deployed.

## September 10 Local Checkpoint

- `journal-red-01.xml`: reproduced missing collection evidence under xdist,
  despite successful test calls. `journal-green-01.xml`: all five journal
  regressions pass after retaining the canonical and per-worker inventories.
  Covers serial failures/interruption, duplicate-evidence rejection, parallel
  phase completeness and divergent-worker inventory retention. This repairs
  test evidence, not either product complaint.

- `web-focused-01.xml`: 12 passes, but only three of four intended files were
  selected. The missing billing file makes that inventory incomplete.
- `web-focused-02.xml`: 15 passes, one billing assertion failure. Complete XML
  failure inspection showed the test replaced `/billing/usage`, while the page
  preferred `/billing/reports/spend`. Corrected the fixture endpoint, not the
  expected paise values or the application fallback.
- `web-focused-03.xml`: all 16 tests across the intended four files pass in
  network-disabled Docker, including the unchanged 7-paise hold, 15-paise spend
  and 99,978-paise remaining-budget assertions.
- `web-full-01` stopped before collection because BusyBox requires `sha256sum
  -c`, not GNU `--check`. Retained as a setup failure. The corrected runner
  verified the same frozen source archive before starting tests.
- `web-full-02.xml`: 974 distinct tests in 169 files passed with no failures,
  errors or skips; both application and browser/configuration TypeScript
  checks passed. This complete frontend checkpoint uses `api-full-source-01.tar`
  and predates later agent handoffs. The separate coverage run and current
  integrated browser build remain required.
- The normal browser test configuration now discovers dated Ram hearing and
  statute specs and dated case-tracking summary specs. Previously its dated
  pattern admitted only `-bugs` filenames. The new configuration assertion is
  not a substitute for the actual Playwright collected inventory and journeys.
- `provider-postgres-01.xml`: all 24 provider/backfill PostgreSQL tests pass,
  zero skips/failures/errors, 75.71 seconds, on an independent fresh local
  PostgreSQL container. `provider-postgres-01.jsonl` retains collection and each
  setup/call/teardown result plus successful completion. This includes the
  previously unverified event-loop responsiveness and populated cursor
  downgrade-refusal regressions. Its source is the hash-checked
  `web-source-03.tar`, not later parallel-agent edits.
- Async summary integration passed 196 focused tests, including 61 summary
  and 16 provider PostgreSQL tests, with all 588 phases reconciled. It removes
  model calls from the snapshot transaction and adds a fenced background
  consumer. An integration publication-lock conflict was reproduced and fixed.
  Exact source hashes and failed-attempt reconciliation are retained in
  `C:/tmp/caseops-summary-integration-20260910/HANDOFF.md`. Release-image worker
  and browser consumption remain pending, so this is not user-visible closure.

These are focused checkpoints, not full integrated-source or production
acceptance. Preserve the missing/incomplete September 9 PostgreSQL report and
zero-byte frontend JUnit report as interrupted runs, not passing evidence.

## Integrated Checkpoints After Handoffs

All artifacts below remain under `C:/tmp/caseops-sep10-20260910` unless noted.
Counts overlap; they must not be summed as distinct product coverage.

| Gate | Result | Exact boundary |
| --- | --- | --- |
| `postgres-full-01` | 249 passed; 747 phases; no skipped or failed nodes | All PostgreSQL-marked tests on `api-full-source-01.tar`, before hearing/catalogue/hold integration |
| `web-full-03` | 974 passed in 169 files; coverage retained | Same earlier snapshot; statements 57.2%, lines 60.2%, branches 51.53%, functions 43.28%; existing thresholds unchanged |
| `web-integrated-04` | 1,012 passed; no skips/failures/errors; application and browser type checks passed | Frozen integrated source after the first catalogue/hearing/summary/hold handoffs; statements 57.33%, lines 60.31%, branches 51.67%, functions 43.42%; before hearing v2 follow-up |
| `hearing-integration-01` | 308 passed; 924 phases; no skips/failures | Frozen combined provider, hearing, summary and old-provider/backfill regression inventory, including 24 PostgreSQL hearing nodes |
| `catalogue-integration-01` | Collection failed; zero completed tests | Compiler was incorrectly selected in the API runtime, which intentionally lacks pdfplumber. Full collection failure retained. |
| `catalogue-integration-02` | 102 passed; 306 phases; no skips/failures | Same frozen catalogue source as failed attempt; complete API selection including three PostgreSQL catalogue nodes |
| `catalogue-compiler-01` | 12 passed; 36 phases; full pinned rebuild check passed | Separate `/opt/statute-build` runtime; 4,496 source units: 4,289 verified, 184 retired, 23 quarantined; hash `849a75ed2afc7584b2b1cea80fb34921b7dda32ebadab223ffe6394af3e5be8e` |
| `foundations-integration-01` | 289 passed; 867 phases; no skips/failures | Fresh hold migration, PostgreSQL approval/lifecycle tests, complete governance-map modules and event contracts on the retained frozen source; no access-review campaign or whole-programme closure |
| `native-reranker-01` / `windows-shim-02` | One test passed in each replacement | Earlier full-API source: real cached reranker in network-disabled Docker; Windows-only mocked gcloud CMD test on this Windows workstation. The initial shim command failed before collection because this host does not install xdist. |
| `api-full-01` | Still running at this checkpoint, not green | Two complete event-catalogue failures inspected: summary used unknown owner `case-tracking`; canonical owner is `court-tracking`. Corrected source passed all 33 contract tests; failed broad evidence remains unchanged. |

The 41-file catalogue v3 handoff is integrated, except its stale generated
client was regenerated from the combined API instead of copied. Provider status
fields were preserved. Eight reported Acts now have admitted source units in
this candidate, but Income-tax, Constitution, Motor Vehicles and remaining
schedule/table gaps prevent a catalogue-completion claim. The official
1,098-page Income-tax PDF was acquired through the public publisher's browser
download, hash `ecdd7ea6ef58415848a0bca8f88854c23f52dcb830e9ce7eb42b4520f30db2fc`.
Its encoded text still requires source-specific decoding and complete admission;
acquisition is not verification. Source provenance is in
`income-tax-acquisition-01.json`.

The isolated browser candidate at `docker-candidate-01` contains 2,352
hash-verified source files. `docker-candidate-01-source.json` identifies that
checkpoint; any later fixture correction requires its own provenance and a new
image fingerprint. Docker image/browser acceptance remains outstanding here.

The main integration tree now includes the separately reviewed preservation
workflow: authenticated independent approval, immutable expiring proposals,
bounded register/proposal pages and original-history protection. Migration
`20260909_0003` follows provider revision `20260909_0002`; the governance map
classifies the new table without export or purge admission. Four audit actions
use the existing foundations owner. Fresh integration tests passed 289 nodes,
including the formerly missing-table governance boundary. This
does not close IPLF-028B or any of the 25 remaining IP slices.

The reviewed hearing v2 follow-up preserves older provider and summary fixtures
with disjoint identities and delegates order-download paths to the existing
handler. It parses the provider's `hearingDate` field and adds private-sibling
bookmark isolation plus manual/scheduled PostgreSQL races after scope discovery.
Publication now locks the Matter, then rereads and locks its bookmark before
writing the date. Archives and retargets cannot publish against stale scope.
`hearing-integration-02` is the replacement gate; it is not assumed green from
the earlier 308-test result. Its versioned handoffs and source archive remain
separate from the first browser snapshot.
