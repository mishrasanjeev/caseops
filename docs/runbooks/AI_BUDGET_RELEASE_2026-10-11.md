# AI Budget Candidate Evidence

## Release Verdict

### R8 Infrastructure Failure

Exact `3ca46ae5` Docker R8 finished exit 1 at 16:28:41 UTC before native or
browser execution. Images built, migration and index-health probes passed.
The new native gate rejected the caller's noncanonical Compose image handle:
the caller inspected the full image metadata but retained the short handle
instead of its canonical `Id`. This introduced acceptance-wrapper defect is
not a product reproduction. Bounded pre-cleanup logs/state and the full console
are retained in `docker-r8`; all seven owned containers and both networks and
volumes were subsequently absent. No provider call or production mutation.

The replacement caller retains the exact inspected canonical ID and rejects
missing, ambiguous, malformed, wrong-release and failed inspections. Actual
caller AST controls reproduced eight failures on the old script; all ten
controls now pass on pwsh and Windows PowerShell. A failed intermediate
Windows ambiguous-array control is retained; it caught the PowerShell 5.1
JSON-array wrapping distinction. Read-only real Compose/inspection replay with
the retained API/web images reproduced bare 64-hex IDs without the `sha256:`
prefix, proved canonical output from the corrected caller, and removed both
owned network-disabled inert containers without ever starting them. That is
caller proof, not native or browser acceptance. Focused Windows replacement:
28 tests / 84 passing phases, full ordered collection and JUnit agreement,
zero skips/failures. The first reconciliation helper incorrectly split `::`
inside parameter IDs; its mismatch is retained and corrected, not relabelled
as a test failure. Complete amended Docker/CI remains required;
R7's original five browser failures remain Inconclusive pending full replay.

### 15:38 UTC Exact-Candidate Checkpoint

Production API/web still serve `3dbf364d9834316d181d4a52b2e9b4c7bee431b4`.
PR #533 is draft/unmerged at `bf2fc616`; no provider activation or primary
promotion occurred. Current hosted CI is green, including independently
reconciled native/API/browser artifacts. The hosted browser used GitHub's
`d9db2df5` PR merge, whose tree exactly matches bf2; that is not literal
candidate or production identity.

Exact-bf2 Docker R7 failed, controller exit 1 at 15:12 UTC. Native gate:
2,301 passes / 6,903 passing phases, matching complete collection/JUnit and
completion. Desktop browser union: 507 identities, 490 passes, five failures,
12 skips (including three serial dependency skips), no flaky cases. Four
mobile identities and final post-browser health were not reached. Original
reports, all five failed traces and the incremental native journal are retained
under `outputs/ai-budget-release-recovery-20261011` in the original checkout.
The independent `docker-r7-sidecar-20261011T1530Z-87d7b2f4/README.md` reconciles
all desktop identities and failure boundaries; failed evidence is not replaced.

Both poll subprocesses lost their native error/signal; selection and Drive
report explicit subprocess timeouts; public-demo replay reports a socket reset
without an HTTP response. Their failure-time internal phases and common root
cause remain **Inconclusive**. Later read-only diagnostics found native-test
tenant contamination in the browser database, a cold selection process near
its 30-second limit, and a seven-case idle Drive replay passing in 29.19 seconds.
Those observations do not close any failed browser journey.

Replacement work on `codex/release-browser-recovery-20261011` isolates native
PostgreSQL into an independently migrated database, retains bounded failure
logs and subprocess receipts, runs the selection fixture through the validated
host runtime against read-only Docker PostgreSQL, runs Drive isolation inside
the acceptance API image, and explicitly closes completed loopback web
connections. Original deadlines, provider fences and workflow assertions stay
unchanged. The latest focused run passes 19 receipt/database/header-policy
controls, with matching JSON/XML identities and no retries or skips; the
actual web header and all affected journeys still require acceptance.
Standard discovery includes all 20 added regressions: 531 identities,
527 desktop and four mobile, with every original identity retained. The
Windows wrapper regressions pass 26 API tests / 78 phases, including 37
behavioral cases on each of PowerShell and pwsh. Linux CI and real-image
integration still require the amended gate. This infrastructure
repair does not bound the production poller's global tenant scan or prove the
cause of the original socket reset. Complete amended Docker/CI, canonical main,
guarded exact-SHA deployment and live replay still precede certification.

Focused amendment receipts: `browser-amendment-reconciliation-r3.json` and
`native-isolation-local-r1/payload/api-reconciliation.json` under the retained
original-checkout recovery output directory. The two failed intermediate
wrapper controls remain retained beside their passing replacement; neither
they nor the passing controls replace R7's five failed product journeys.

The selected Gemini fallback remains disabled pending the global processing
and retention review. It is neither a legal-quality certification nor a free
route after the shared November INR 10,000 allowance is exhausted.

**NO-GO pending complete release gates.** This is not a production deployment
receipt, provider activation or legal-quality certification. Canonical source
base: `dfda0eb3ee3d109f86092962a08d125878b24932`. Candidate branch:
`codex/ai-budget-release-20261011`.

The owner superseded the earlier INR 5,000/pause instruction: October continues
unchanged, and the new shared AI allowance is INR 10,000 per month. The candidate
defaults to enabled from November 2026. No production provider, secret, balance
or October pause was changed during local implementation.

## Completed Local Evidence

### Selected Fallback Amendment

The latest owner instruction selects exactly `gemini-3.5-flash-lite` as fallback.
It is not promoted to primary: no like-for-like legal benchmark establishes an
advantage over Luna, and official standard token rates are higher. October's
primary stays unchanged. Recommendations-only opt-in routing and managed native
structured output are being added; live global processing/retention review,
API/IAM/ADC, paid-path evidence and the November billing baseline remain open.
No automated paid call is permitted and budget exhaustion cannot trigger a
provider switch. Upstream quota/credit exhaustion also remains fail-closed.

Native adapter receipts are retained in `gemini-adapter-*` beside the recovery
outputs. Initial RED has 100 call failures/14 controls; usage RED has 27 call
failures/146 controls. The agent's frozen six-file GREEN has 269 passed calls,
807 phases, no skips and completion exit 0, including 173 native adapter cases.
An expanded eight-file run remains failed (355 passed/12 failed). Every failure
was read independently: six contents-only byte expectations and six raw-cause
expectations predate complete request reservation and exception sanitization.
The replacement keeps liability, actual SDK attempt and transaction assertions;
it must rerun both complete historical files, not only the passing adapter file.

Routing RED r1 reproduced four intended HTTP failures with 12 passing controls.
Exploratory GREEN r1 passed 52 but was not the frozen combined candidate. R2
retains 19 passed/6 failed calls: four dynamic client fixtures reset the configured
provider, and two role fixtures incorrectly treated Member as non-generating.
These are harness errors, not six product reproductions. Activation now follows
client bootstrap and Viewer supplies the genuine denied-capability case. R3
completed all four requested recommendation files: 71 passed, 213 phases,
71 JUnit identities, no skips/failures and exit 0; its four PostgreSQL cases
were explicitly deselected and still require the native gate. It also proves
policy revocation during fallback, no third call after malformed/unsafe output,
retained rejected-model evidence and current actor/access rejection. The larger
frozen combined run and full amended Docker/CI/live gates remain required.

Combined frozen offline replacement completed all **18 requested files**, with
591 collected/passed calls, 1,773 successful setup/call/teardown phases, 591
JUnit identities, no skips/failures/errors, no unknown/missing phase identities
and caller/session exits 0 in `fallback-combined-frozen-r1`. It includes every
native adapter and both complete previously failing historical files (61 + 37
cases), recommendation journeys, event-loop responsiveness, money admission,
embedding, classification, compliance and contract denial controls. All eight
PostgreSQL-selected cases were explicitly excluded by `-m 'not postgres'`; this
is not complete native Docker or production acceptance. Whole API source/test
Ruff, governance registry/map, change-relative governance, migration preflight
and diff checks pass. No paid transport or runtime activation occurred.

Docker R3 on `5a66c0910c0d0c6243b18ceb2446a1f23c843fcf` was intentionally
interrupted to implement this new scope. The retained native journal has 2,266
collected identities, 169 passed calls, 508 phase reports, zero failed reports
and **no session completion event**. It is incomplete, not a replacement for
failed R2. The exact owned pytest process tree was stopped and reaped; only its
label-verified Docker project/volumes/networks were removed. Results remain at
`outputs/ai-budget-release-recovery-20261011/docker-r3` in the original checkout.
The amended tree requires a new full acceptance run and fresh CI.

The separate exact-image `5a66c091` public-content run completed 26 tests with
zero skipped/flaky/unexpected results. Its inventory, native JSON and inspected
desktop/mobile screenshots are retained in `docker-public-content-r1` beside
R3. This is public-content proof for that candidate only, not fallback, whole
application or production acceptance.

- Python 3.13.14, repository locked API dependencies; incompatible OneDrive
  hardlink installation was retained and replaced by a successful copy-mode sync.
- Node 22.14.0 fresh production build passed. Earlier Node 24 type checking was
  static evidence only and was not substituted for the pinned build.
- Four selected web unit files: 13 passed, including the new page's eight
  content/metadata/nonce contracts and historical resource/ownership/discovery.
- Complete public-content inventory: 26 passed, zero skipped or flaky. All 23
  historical identities remain, plus three article identities. Metadata,
  canonical/sitemap, link fragments, noindex, desktop/mobile accessibility,
  layout, article source caveats and absence of model names were exercised.
- A second unchanged public run retained JSON results and desktop/mobile source
  caveat screenshots, both visually inspected. No demo leads were submitted.
- Backend initial gates retained 289/289 passes each in separate r1/r2 journals.
  Expanded r3 gate: **339 collected, 339 passed, zero missing call results**, with
  setup/call/teardown and `session_finished: exitstatus 0` retained.
- Final r4 gate: **343 collected and passed**, no skipped or missing results,
  including the caller-held SQLite writer mutex and three actionable HTTP-copy
  controls. Whole API source/test Ruff and `git diff --check` passed.
- Five new money test files contributed 205 cases in r4: budget primitive 47,
  dispatch/process/migration 13, LLM boundary 61, native LLM SDK transport 37,
  embedding boundary 47. The expanded gate contained eight historical
  adapter/settings files, 138 cases. Earlier r3 had 204 new/135 historical;
  those smaller inventories are retained, not substituted for r4.
- PostgreSQL money-lock controls prove both directed lock orders using separate
  backend PIDs and owned UUID schemas; teardown proved those schemas absent.
- Native SDK controls use pinned OpenAI 2.32.0, google-genai 1.73.1 and HTTPX
  0.28.1 with verified inert MockTransport bindings. These are offline request,
  retry, structured-schema and pre-transport accounting tests, not paid legal
  quality samples. No billable provider was invoked.
- A fresh owned PostgreSQL 17 container upgraded to `20261011_0001`; empty
  downgrade to `20260928_0001` removed both financial tables, then upgrade restored
  them. The initializer admitted an explicitly fictitious local policy once and
  replayed without change. Populated downgrade correctly refused, retaining head,
  both tables and the exact opening/admitted amounts. No production policy was
  initialized, and these fixture amounts are not account billing evidence.
- Governance map/runtime projection generation and validation passed. Migration
  graph has one head. Change-relative validation remains required after commit.

Local retained artifacts are in this worktree's `.tmp/ai-money-native-20261011-r1`,
`r2`, `r3`, `.tmp/ai-money-web-20261011-r2` and
`.tmp/ai-money-migration-20261011`. Earlier incomplete/misspelled lint selection
was retained and corrected; it was never full-coverage evidence.

## Adjacent Denial Amendment

Independent review of the first candidate found that the shared SDK denial
could still be treated as an ordinary failed document by operational callers.
The amendment stops metadata/backfill/statute batches, retains denied ingest
inputs, preserves accepted predictive classifications, cools down summaries
without exhausting transport attempts and distinguishes compliance's deferred
AI phase from its completed deterministic work. Provider I/O in the amended
corpus paths owns no source transaction, and publication rechecks frozen source
identity. Remote retained staging is bounded to one owned slot per temp root.

Retained red evidence includes 13 failures/eight controls for metadata and
structured backfill; 21 failures/three controls for corpus money stops and
transaction ownership; five additional title/source/timestamp failures; two
repeated remote-staging failures; and two original summary financial-denial
failures. Early collection/fixture defects are explicitly NOT RUN, not product
reproductions. Initial amended summary runs still failed before the complete
55-case replacement passed; the failed receipts remain available.

Agent-scoped replacement evidence: corpus 157 passes/471 phases, summary
55 passes/165 phases and classification/statute 38 passes/114 phases, zero skips.
These do not certify the combined tree. Parent r5 selected 27 exact files and
collected 714 identities, including PostgreSQL: **708 passed, six explicit
Windows title-extraction skips, zero failures/errors**, pytest completion exit 0,
714 JUnit identities and 2,136 setup/call/teardown reports. Independent native
reconciliation proves the exact requested file inventory, each permitted skipped
phase, no duplicate/missing result and unchanged API source hashes. Both owned
runner/pytest PIDs are absent. The outer console tee failed after pytest completion
with a Windows UnicodeEncodeError (caller exit 1); its failed receipt is retained,
not relabeled clean wrapper acceptance. Six skipped identities still require
positive Linux replay; the canonical amended planner selects their module in
coverage shard 7/13. Evidence: `.tmp/ai-money-native-20261011-r5/results.jsonl`,
`results.xml` and `independent-reconciliation.json`. The compliance red control reproduced one
missing deferred-phase annotation while the ordinary failure control passed;
its first replacement exposed a test assertion treating serialized audit JSON
as a dictionary. That test defect was corrected without changing the API.

CodeQL's side-effect-in-assert finding and mixed implicit return were corrected
in source. Alerts 541/542 (Alembic reflective metadata) and 543 (ORM registration)
were individually dismissed as false positives; 546 is an isolated test-worker
failure receipt, individually classified as used in tests. No scanning rule or
security boundary was relaxed. Fresh amended analysis is still required.

The terminated ingest VM was not resumed. Its legacy sweep wrapper tolerates
nonzero stage exits, and dormant pre-guard images cannot be certified as guarded
executors. Upgrade and prove the authoritative database/adapters before any
resumption; do not infer a global account cap from the API alone.

## Remaining Gates

### Recovery Checkpoint

PR #533 remains draft and unmerged at `665f2b19b1caaf2fdae508cb0e3e9d620d5bfa27`.
Independent GitHub readback confirms its CI `38117093547`, Security
`38117093542`, CodeQL `38117093566` and PR review `38117093539` completed
successfully. These hosted results do not supersede a failed local gate.
API and web readback still serve `3dbf364d9834316d181d4a52b2e9b4c7bee431b4`,
revisions `caseops-api-00488-5sd` / `caseops-web-00465-sk6`.

The prior session recorded a complete second Docker PostgreSQL run on `665f2b19`:
2,262 collected, 2,261 passed, one failed, zero skipped, 6,786 phase results and
2,262 JUnit identities, session exit 1. The failing identity was
`test_compliance_participant_fence_20261010_postgres.py::test_real_downstream_compliance_completes_in_both_lock_orders[text-mutation-manual_sync]`,
with PostgreSQL 55P03 waiting for the Company row. Browser/reseed phases were
not reached. The isolated project was reported removed after completion.

On recovery the old checkout, uncommitted court-write amendment, final temporary
reports and helper container are absent. Their historical counts are retained
here as the prior session's recorded failure, not independently re-read raw
artifacts or current acceptance. Committed work was recovered from the same
branch into `ai-budget-release-recovery-20261011`. Reconstruct and rerun the
regression and full gates; do not upgrade a claim using inaccessible evidence.
The original lock timeout remains **Inconclusive**, not an established deadlock
or proof of CPU starvation. See [court-write investigation](MATTER_COURT_WRITE_BOUNDS_2026-10-11.md).

One original native SQL journal was independently recovered from retained pytest
storage. Its SHA-256 is
`1cc97fb78c03919fa17c08bf318acaa712d4e4d28f69a21c9b81963463ab61be`;
both original and copied bytes agree. It positively retains the 55P03,
directed Company-row wait and clean contender cleanup, not full-suite counts.
Recovered path: `.tmp/recovered-docker-r2/failed-compliance-manual-sync-native-sql.jsonl`.
Fresh unchanged-source original/counterpart replay completed **2/2**, six phases,
two JUnit identities, no skip/failure, caller and pytest exit 0 in
`.tmp/recovery-original-lock-r1`. It does not explain the prior timeout or replace
complete Docker acceptance.

Recovery review found an additional corpus finalization boundary: denied PDFs
were retained by local ingestion but deleted by the remote driver's `finally`
when run reload/commit raised before a summary returned. Eight actual-ingest
controls (HC/SC, reload/commit failure, denial at first/second call) reproduced
the loss with eight call failures, eight successful setups/teardowns and exit 1
in `.tmp/corpus-finalization-recovery-red-r1`. The narrow staging-state fix
passed all three complete affected files: **154 collected/calls passed, 462
successful phases, 154 JUnit identities, zero skips/failures and both exits 0**
in `.tmp/corpus-finalization-recovery-green-r1`. Pending bytes, accepted rows,
bounded provider attempts and blocked restaging are asserted. This is scoped
local proof, not combined Docker or production certification.

Court recovery harness attempts remain preserved: r1 collected zero (malformed
JUnit argument), r2 skipped all four (incorrect database environment variable),
and r3 reproduced update hydration but two siblings stopped on invented ORM
field assertions. These are not three successful bug reproductions. Corrected
fixtures must finish actual write and downstream outcomes before work-bound RED.

Corrected court r4 reproduced all three intended hydration failures after real
outcome and access/lifecycle controls. The narrow writer opt-out then passed
**68/68** across all three complete PostgreSQL files, 204 successful phases,
68 JUnit identities, no skips/failures and both exits 0 in
`.tmp/court-write-recovery-green-r1`. Locked getter work is two queries with no
unrelated historical ORM materialization at 1/501 retained histories; default
read hydration and all actual outputs remain. These scoped controls do not
supersede the earlier full Docker failure or establish its original cause.

Contract review found a shared helper treating financial denial as a transient
provider error, retrying it and returning 422 with minute-retry advice. The
narrow correction catches the typed denial on both call boundaries without
changing caller transaction ownership. Corrected scoped RED r3 has **53
collected, 24 intended call failures, 29 controls passed**, successful setup/
teardown, no skips and both exits 1. GREEN r4 has **53/53 passed, 159 successful
phases, 53 JUnit identities, no skips/failures, both exits 0**, with unchanged
source hashes and exactly both requested files. Paths:
`.tmp/contract-denial-recovery-r3red-narrow` / `r4green-narrow`.
All four actual HTTP workflows preserve accepted rows; helper tests preserve
uncommitted updates/inserts/deletes and reject cross-tenant access before calls.
Earlier r1/r2 receipts for an exploratory transaction-release opt-in are
superseded, not final acceptance. That opt-in was removed: safe transaction
release needs separate post-provider source/access revalidation and race proof.
The pre-existing contract transaction-ownership gap remains open.

Fresh recovery raw receipts have also been copied outside the temporary checkout
to `C:/Users/mishr/OneDrive/Documents/CaseOps/outputs/ai-budget-release-recovery-20261011`.
This checkpoint preserves failures as well as replacement runs. New combined
Docker evidence must be retained there too; scoped passes are not its substitute.

The first Docker run at `ab07681ecbd27f9ce110f73ec664ec9c5fe74a5d` was
intentionally interrupted after independent review found missing corpus-driver
money-denial halt handling. Its journal retains 2,237 collected identities and
27 completed calls, no completion event: **incomplete, not acceptance**.
The owned Python child was confirmed absent, and only its exact Compose project
`caseops-acceptance-ab07681ecbd2-a27280ba9b78` was removed, including the
acceptance emulator, both networks and owned volumes. Replacement evidence is
required for the amended commit. The full web unit suite independently passed
1,242 tests across 198 files. Hosted CodeQL, security and web checks passed on
the earlier candidate, but are not closure evidence for the amendment.

1. Pass change-relative governance and migration contracts after commit.
2. Run committed clean-image Docker acceptance: full PostgreSQL inventory,
   migration rehearsals, release catalogue reseeding and complete browser phases.
   Earlier broader release failures remain open until full replacement evidence.
3. Require green CI/security on this PR, merge canonical main and verify the
   exact validated release tree. Do not merge an unrelated draft with open gates.
4. Guarded canonical deployment only; exact API/web/job identity, live replay,
   QA certification and quiescent private-projection cadences remain required.
5. Reconcile the November opening liability and pinned all-in pricing before paid
   admission. Use one authoritative database for every executor. Conservative
   admissions are not external invoices or protection against calls outside
   CaseOps. Missing monthly reconciliation fails closed, not zero-funded.
6. Gemini managed access/privacy/region, native strict contract parity and retained
   legal benchmark remain open. No full migration or automatic fallback is live.
   A paid fallback cannot exceed the aggregate INR 10,000 allowance.

## Fallback Review And CI Checkpoint

`67fab368` is not release-certified. CI run `38128905001` failed its PostgreSQL
aggregate. Shards 1, 3 and 4 are labelled failed; shard 2 is labelled cancelled,
but its uploaded native journal also completed with one call failure and exit 1.
All four failures have been read individually: the isolated HTTP client's
authoritative no-paid marker correctly disables availability fallback, whereas
the new fake-provider tests expected a human route. This is a diagnosed harness
defect, not permission to remove the marker or weaken production isolation.

Local RED retains four collected failures, successful setup/teardown and exit 1
in `fallback-postgres-red-r1`. The corrected human-route emulation replaces only
the routing marker dependency after deterministic transports are installed. Its
unmodified marked-request sibling proves zero paid construction or reservation.
Scoped PostgreSQL GREEN r1 retains five collected/passed cases, 15 phases,
matching JUnit identities and both exits 0. Neither closes a full release gate.

Independent review also reproduced two product defects: stale authority
body/version/access accepted across fallback, and managed authentication allowed
past the shared deadline. Authority RED retains eight collected calls: seven
failures, one existing post-transport chunk-change control and exit 1. One
primary chunk-change case rejected persistence only after incurring fallback;
the other failures could return saved output. Body/excerpt byte and immutable
version checks now fence admission and persistence with bounded current scalar
reads. The deadline correction is implemented; full combined amended proof is
still required. Its frozen native/adjacent 337-case receipt covers credential
discovery/refresh, constructor, serialization, admission, dispatch and return
with public SDK/auth APIs and deterministic offline transports.

The initial authority baseline now must match retrieval-time metadata and
excerpt hashes, not a subsequently relabelled edition. Coherence RED retains
three intended failures; GREEN r2 has six passing SQLite/PostgreSQL cases.
Boundary r1 has 20 passing cases for byte caps, unmodified public DTO, deleted/
replaced chunks and final persistence locks (60 phases, no skips, completion
exit 0). Metadata RED r1 separately retains four call failures (title, summary,
citation and source reference), all returning stale success before correction.
Source locking rejects concurrent version/chunk writes and parent-FK insertion
until final commit, not during transport. Work bounds are six sources, 4,096
child rows, two scalar reads, 8 MiB per body and 64 KiB per chunk. PostgreSQL
uses its core SHA-256 functions, not an uninstalled extension. No public DTO or
migration change is introduced by this amendment.

The frozen replacement `fallback-combined-final-r1` passed **762/762 cases in
all 24 selected files**, including every one of **39 PostgreSQL cases** (35
fallback HTTP/locking, two money races and two compliance boundaries). It has
2,286 passing setup/call/teardown phases, 762 matching JUnit identities, no
skips/failures/errors, no unknown or missing identities, exact canonical ordered
collection and both exits 0. All Python source/test hashes agree before/after.
The 92-case route file, 173-case native adapter and 21-case deadline file are
actually discovered/run. Receipt: the durable recovery directory's
`fallback-combined-final-r1/{reconciliation,postgres-reconciliation}.json`.
This is affected/adjacent proof, not the complete PostgreSQL/Docker inventory,
hosted amended CI or exact-production acceptance. Full replacement gates remain
required, and no live model-quality or managed activation is implied.

R4 was intentionally stopped and its exact parent/pytest processes reaped to
allow these amendments. Its unchanged raw journal has 2,270 collected identities,
80 completed calls and 241 phase records, **no completion event**. The passing
26-case public-content replay on its exact `67fab368` API/web image is separate:
both release identities matched before/after and responsive screenshots were
inspected, but the full application PostgreSQL/Playwright gate did not complete.
No production mutation or provider activation occurred. Retain every failed and
interrupted receipt under the durable recovery directory; replace them with a
fresh frozen-candidate gate, not a selective rerun presented as full acceptance.

## Native CI Capacity Checkpoint

CI run `38133373299` on `9667ad02` completed cancelled, not green. Native
PostgreSQL shard 1 reached the existing 12-minute job budget after 571 of its
576 calls passed. Its 1,713 emitted phases passed, but it has no completion
event or JUnit. Shards 2, 3 and 4 each completed all 575 selected calls and
1,725 phases, with exit 0 and matching JUnit. Their canonical 2,301-node
inventories agree; the selected union contains every node exactly once. The
aggregate correctly failed. Retained evidence is
`ci-9667ad02-native-reconciliation.json` and the four individual artifact
directories. A partial timeout is incomplete, not a successful pytest gate
or a demonstrated product failure.

All 13 API coverage shards, combined API coverage, web, Ruff, security and
CodeQL passed. The dependent hosted browser gate skipped; that is not browser
acceptance. Native shard 2's 11m50s job also had insufficient growth headroom.
The capacity amendment uses eight native shards and at most four simultaneous
native runners, without raising the 12-minute timeout, reducing the inventory
or relaxing aggregate reconciliation. Regression coverage must execute the
actual workflow launcher configuration and prove complete non-overlapping
selection, count agreement and the unchanged timeout/concurrency contract.
The capacity amendment still needs its own current hosted acceptance.

Its local intended RED has 28 collected cases: 27 passing calls and one
capacity-contract failure, successful setup/teardown and exit 1. Frozen
bounded GREEN has all 28 shard cases plus the separately collected amended
deployment contract, 87 passing phases, matching JUnit and both exits 0.
Source hashes agree. The complete Windows adjacent attempt remains incomplete
and failing: 201 hardening cases, 183 passing calls, four inspected failures,
one POSIX-only skip and 13 unfinished. Each failure reports the external
offline shell allowlist's omitted `seq`; the 900-second bound ended without
completion/JUnit. This is not clean full coverage. Preserve it and require
fresh complete hosted coverage of the current files, including POSIX controls.
Receipt: `ci-shard-capacity-r1/bounded-final-receipt.json`. No production
deploy behavior, provider fence or unrelated assertion was weakened.

Clean-image Docker R5 remains running at frozen `9667ad02` with no test filter.
This capacity amendment is being prepared in a separate checkout; it does not
alter or retroactively certify that gate. The amended release still requires
current Docker, green hosted CI, canonical merge, guarded deployment and exact
serving browser acceptance. Production provider configuration is unchanged.

## User Documents

- [Recommendations user guide](../AI_RECOMMENDATIONS_USER_GUIDE.md)
- [Shared spending reconciliation](ai-spending-reconciliation.md)
- [Gemini assessment and official sources](../AI_PROVIDER_BUDGET_GEMINI_ASSESSMENT_2026-10-11.md)
- Public article candidate: `/resources/source-grounded-legal-recommendations`.
  It contains no model name and makes no guarantee of legal accuracy or outcomes.
