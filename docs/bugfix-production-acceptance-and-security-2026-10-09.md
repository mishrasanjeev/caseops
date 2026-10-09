# Production Acceptance And Security Follow-Up - 2026-10-09

## Release Truth

PRs #525/#526 are merged and serving as
`b1d3fb23a73bf16ee2000ddc230d422085ba45e4`, tree
`cdad83f947f3365985fc51169f57e1504d81da6a`. API revision
`caseops-api-00487-m58` and web revision `caseops-web-00464-qzf` received
100% latest-only traffic after the guarded release completed at 09:06 UTC.
Older ledger not-deployed statements remain historical, not current truth.

Deployment is not certification. Exact-release production verification
`37909107955` failed: 299 required identities, 276 passed, five failed and
18 skipped. The optional cost file added one pass. Complete failed native
reports are sealed under
`.tmp/release-followup-20261009/prod-b1-37909107955-full-failed-proof-r1/`,
SHA-256 `c8a8ca50a63d3a6a81147928eb3cf4a9781e75ef3bf4a0ad1e3771f713000dac`.
Private-projection cadence remains paused pending full replacement acceptance
and two later clean quiescent maintenance executions.

## Open Inventory

The authoritative initial GitHub inventory contains four issues, two PRs and
28 code-scanning findings. A green CodeQL job does not establish zero alerts;
reconcile actual main alert states after fresh analysis. No dismissals are used.

| Item | Scope | Current Verdict |
| --- | --- | --- |
| #527 | Five exact-b1 production failures below | Not fixed in production |
| #521 / PR #522 | Discoverable sign-in noindex; conflicting draft | Not deployed; Google exclusion separately unverified |
| #513 | Durable public demo admission before success | Candidate scoped gates pass; combined release pending; sender/retention remain default-off |
| #515 | Truthful persona, pilot and CTA claims | Candidate scoped gates pass; exact-serving replay pending |
| PR #520 | Navigation-safe Gmail/Drive persisted-status assertions | Green required checks; merged 14:27 UTC as `5c322339e87d32cf6cfa3a121c36831ca837f3df`; current live replay pending |
| Alerts 519-524 | Six high storage `py/path-injection` findings | Candidate 334-test gate passes; fresh CodeQL and release pending |
| Alerts 423,493-495,499-500,506-512,515,525-528 | Eighteen `py/cyclic-import` findings | Assigned reverse paths removed; integrated 29-test graph gate passes; fresh CodeQL pending |
| Alerts 492,516-518 | Lambda and implicit-list-concatenation findings | Candidate reviewed; fresh CodeQL pending |

## Failed Journeys And Evidence Limits

| Journey | Exact Failure | Attribution |
| --- | --- | --- |
| IPLF-058B UJ36/UJ61 recordal | Title-interest admission returns database-lock 503 | Exact holder unproved |
| Ram 2026-09-21 BUG-006/ENH-007 | Bulk update returns database-lock 503 | Exact holder unproved |
| Ram 2026-09-21 next hearing | Sign-in returns database-lock 503 | Auth/provenance conflict reproduced locally; live replay required |
| Ram 2026-09-24 BUG-013 | Sign-in never reaches app within 180 seconds | DOCX assertions never ran; not a DOCX reproduction |
| Notice-module production | Notice file upload returns database-busy 503 | Snapshot proves failure; full trace unavailable |

Do not infer one root from sibling failures. Read-only production sampling
observed historical Membership/User FK key-share holders and Company waiters,
but not their complete holder request/instance chains. Six empty-result SELECT
plans do not establish populated event/save work. The workflow already uses
`max-parallel: 1`; queued job timestamps do not prove concurrent mutation.
No timeout, SLO, malware, quota, lifecycle or access fence is relaxed.

## Reproductions And Candidate Repairs

PRD: authentication US-001; document J03/J04/M02/M03/US-007/008/036/051;
lock-sensitive IP/Matter M08/M13/M14/UJ36/UJ61; public acquisition
J19/M21/US-063/FT-094/096/NFT-023/SEC-031.

- Twelve auth handlers ran synchronous SQL/password/MFA services on the event
  loop. The baseline fails twelve dispatch checks and a real socket test:
  blocked login also blocks unrelated `/api/build`. Worker dispatch preserves
  all 13 auth OpenAPI paths, SHA-256
  `0fb9dbcf72e89ba2a6c5b0e44a2bf33c126882b5954542e4dfe4bbff1bafd62e`.
  Initial complete three-file replacement: 24 passed with all phases and
  completion. The complete adjacent auth/security/notice replacement then
  passed 94 tests across seven files, with 282 phases and native completion.
- Real PostgreSQL historical `FOR KEY SHARE` on Membership or User blocks
  auth's `FOR UPDATE` until SQLSTATE 55P03. Both baseline compatibility cases
  fail; both deactivation-serialization baselines pass. Use the existing
  helper's `no_key_update=True` mode for session minting only, retaining current
  identity exclusion and cutoff tests. Provenance is not live authorization.
  The later five-file PostgreSQL replacement passed 46 tests and all 138
  phases, including both lock orders, deactivation and existing cutoff races.
- A populated 10,001-chunk event hydrates all retained text/embeddings and
  updates ORM instances under the tenant fence. The failed wide-read baseline
  is retained. A set-based replacement returns only source identities,
  preserving targeting, count, identity-map synchronization, manifest
  invalidation, permanent saved-output closure and shadow fencing. Initial
  complete two-file replacement: ten passed, including the populated case,
  isolation and replay. A separate complete foundation/saved-output gate
  passed 16 tests and 48 phases. This is not complete attribution of the live
  failures; the real document-finalizer overlap remains a required boundary.

## Combined Candidate Checkpoint

- Dependency/caller replacement enumerated all 438 identities in 17 files.
  Each of four xdist workers agreed with the complete ordered collection.
  The corrected gate passed 437 with one POSIX-only mount-policy skip on
  Windows, with 1,313 retained phases and completion. Linux coverage of that
  skip remains required. The preceding two Alembic failures used the default
  database address instead of the owned isolated PostgreSQL URL; their full
  failures remain in `cycles/focused-integrated-r4/`. The replacement sets both
  `CASEOPS_TEST_POSTGRES_URL` and `CASEOPS_DATABASE_URL` to the owned sidecar.
- Storage acceptance passed 334 identities across nine complete files and
  1,002 phases. It rejects portable-key traversal and symlink/junction/hard-link
  redirection under a service-owned root, and retains storage-adapter/caller
  contracts. It does not assert protection against an OS actor that can mutate
  service-owned directories between checks and I/O.
- Public acquisition scoped acceptance reports 106 backend, 25 web-unit and
  62 browser passes. All 23 new browser identities are selected by the standard
  suite. Public production replay must select only the 14 non-mutating checks;
  lead admission and retry tests are loopback-only. No synthetic production
  leads are permitted. Sender purpose/SMTP wiring and retention-policy approval
  remain open and default-off. XFF spoof resistance is unproved.
- The canonical OpenAPI generator replaces the partial client edit with all
  124 generated additions. Web typecheck passes. Governance map, rendered view
  and runtime data-class projection are regenerated and validate; the dirty
  source gate inspected 69 changed/untracked paths, including 22 governed source
  files, without errors. Repeat the committed diff gate before release.
- The nine-file replacement schema/governance/demo/billing/reminder inventory
  passes 141 tests and 423 reconciled phases. The POSIX mount-policy case that
  skipped on Windows separately passes on Linux with networking disabled,
  read-only source and three retained phases. That focused supplement does not
  certify the whole current Linux suite.
- Independent review found a pre-existing cached-pending event replay that
  overwrote a committed applied count and timestamp. The adjacent-path audit
  then positively reproduced cached building state preserving a newer ready
  shadow's verification manifest. Both authoritative locked reads now use
  `populate_existing=True`; all Company/generation locks and epoch/SLO fences
  remain unchanged. Failed seven-probe review and one-case shadow baseline are
  retained. The standard, portable five-file replacement passes 57 tests and
  171 phases, including scoped removal, permanent saved-child closure, replay,
  readiness invalidation and stale-writer rejection.
- Integration caught incomplete protected lead readback: the existing client
  parser discarded the new fields and the admin table did not expose the new
  attribution/notification state. The completed four-file follow-up passes
  34 web units and 63 scoped browser cases, including all 24 SEO identities.
  A real founder login sees the new request and its honest pending notification
  state after reload at 360/1280 widths; an ordinary tenant receives 403.
  Legacy metadata remains optional. Sender and retention remain default-off.
- The actual Matter/IP document-finalizer overlap replacement passes nine
  tests and 27 phases against the latest event and shadow refresh guards.
  Four real login HTTP bodies complete with 200 before finalizer release;
  reverse auth ordering, revocation/cutoff, disposal winners, permanent output
  locking, other-tenant controls and completed-job replay also pass. Every
  captured backend lock is absent at cleanup. The preserved strong-auth
  baseline positively fails with HTTP 503/55P03 and a directed blocker graph.
  This proves local susceptibility, not attribution of every production
  failure or Cloud Run CPU/billing causality. Contract finalization has no
  matching private event and is not claimed covered by this inventory.
- Four dated failed-journey specs now collect bounded, sanitized browser-only
  network evidence on failure: route category, timestamps, HTTP status,
  validated request ID and allowlisted error type. No request bodies, raw URLs,
  credentials, document bytes, HAR, screenshots or video are added. Page events
  do not cover APIRequestContext calls. Three sanitizer units and root E2E
  typecheck pass; the first fresh browser run passes all 21 selected public and
  diagnostic identities. The subsequent five-second diagnostic drain bound
  still requires the frozen replacement browser/Docker gate.
- A proposed schema/governance run selected a nonexistent
  `test_platform_admin_billing.py`; no tests ran and exit 4 is incomplete
  evidence, not green coverage. The replacement verifies actual filenames and
  includes the existing billing and hearing-reminder suites.
- PR #522's fresh head is `66dd8e48b75391f9ac0c8afe08027e8dc5cf0c93`.
  Its focused fresh build/typecheck, 23 public browser tests and 20 adjacent unit
  tests pass. By 15:10 UTC, web, security, CodeQL, review, the first ten API
  shards and all four PostgreSQL shards pass; remaining API shards and the
  PostgreSQL aggregate are still queued. Queued timestamps are not execution
  proof. No CI bypass is authorized.
- Native CodeQL setup is incomplete: a bounded official bundle transfer
  timed out, and partial downloads plus checksums are preserved. No local SARIF
  or actual-main alert closure is claimed. No suppressions or dismissals were
  introduced. Historical unassigned graph cycles are not silently relabelled
  as removed by the focused assigned-path test.
  A second bounded official-asset attempt stopped at 4,436,992 of 567,240,125
  bytes after 120 seconds; observed throughput projected more than four hours.
  Its manifest and both earlier partial downloads remain retained. Hosted
  exact-candidate/main analysis and actual alert reconciliation remain required.
- Scheduled production run `37932036960` succeeded only for read-only statute
  verification. Its mutating production matrix was skipped, so it does not
  replace the failed complete dispatch `37909107955` or permit cadence resume.

This checkpoint is not a production GO. The candidate has not completed the
whole fresh Docker/CI inventory or been deployed.

The first complete Docker attempt on `a369f791` fails during web image build:
the new colocated diagnostic unit imports a helper absent from the narrow
builder context (TS2307). No PostgreSQL or browser execution is claimed for
that run. Both root upload/context allowlists now admit only the pure sanitizer
helper, copied into the builder alone; no browser fixture, credential or test
directory is copied to the runtime. A two-case build-context regression and a
fresh complete Docker replacement are required. The failed log remains in
`.tmp/issues-security-20261009/docker-a369f791-r1.log`.

The replacement `d50b9231` image build, schema/index health and 512 MiB job
check pass, but its complete PostgreSQL run is deliberately interrupted to
repair a newly confirmed CI cancellation boundary. Retained partial phase
results lack completion and are incomplete evidence. The owned process tree
and Compose project are cleaned up; a fresh final-head full run is required.

Superseded CI run `37944906741` retains queued `always()` API/PostgreSQL
aggregates after all its prerequisite jobs are cancelled. Current `d50b9231`
CI is pending in that same PR concurrency group. A normal cancel at 15:17 UTC
does not finish the stale run; the documented force-cancel endpoint at 15:27
completes it and the current run moves from pending to queued. Both aggregate
job conditions now include `!cancelled()` without altering prerequisite
failure checks, coverage thresholds, evidence reconciliation or E2E needs.
Two exact-manifest regressions positively fail before that change. Hosted
current-head execution is still required; this does not establish an account-
wide runner outage or explain PR #522's independent queued jobs.

The final cancellation/context/profile selection passes eight tests with 24
phases and completion. Cleanup's default profile omission left the explicitly
started owned provider emulator attached to both owned networks; enabling the
acceptance profile removes it and the networks. Reset/final cleanup now include
that profile, with no global prune or unrelated resource removal.

The strengthened positive invalidation case now includes 10,001 projections
and 10,000 saved-output rows spanning active/retired history. All are invalidated
with bounded SQL, no retained private-byte hydration, exact counts and replay;
already locked history and unrelated controls stay unchanged. The final four-
file critical PostgreSQL gate passes 24 tests and 72 reconciled phases. Its
whole propagation-through-commit duration is 0.718 seconds under the unchanged
five-second budget, recorded in compatible JUnit suite properties. The initial
0.698-second pass and its testcase-property compatibility warning are retained;
the final suite-level property report removes that recording defect without
suppressing warnings or weakening the performance assertion.

Pre-browser integration audit finds the new server-side admission proxy missing
its internal Docker API origin. The frozen `43836619` web container has only
the browser's loopback URL; a guarded local-only valid request positively
returns 503, and no production lead or provider call is made. Its running
1992-case PostgreSQL inventory is interrupted rather than misclassified as
complete; partial journals and the safe 503 baseline remain retained. Owned
profile-aware cleanup removes every container, volume and network.

Compose now gives the web server `http://api:8000` separately from the browser
origin. The proxy preserves only the recognized no-paid marker, not auth,
cookies or referrers. A source-manifest contract and native proxy unit cover
this boundary. The API runtime is unchanged; all release acceptance must still
run fresh on the final combined commit. Earlier same-host browser success
missed the separate Docker network namespace and was insufficient setup proof.

The complete current five-file web selection passes 38 units, and the selected
pipeline/context/profile/origin contracts pass nine tests and 27 phases. E2E
typecheck passes. Acceptance now checks the server-to-server health and exact
release identity from inside the web container before expensive PostgreSQL
work, with a five-second deadline and no unsafe external fallback. The final
Docker browser gate must still prove durable admission/readback over this
actual internal network, not only mocked proxy transport.

Incremental journals/JUnit are in `.tmp/issues-security-20261009/`. Preserve the
first projection attempt with an unrecognized PostgreSQL environment key and
the adjacent dispatch import-collection error as incomplete evidence. Corrected
baselines must positively run before implementation claims.

## Where Earlier Work Was Insufficient

### Fresh Hosted Security And CI Findings

Hosted candidate `97c11aee` Python analysis `1924545564` completes successfully
but reports five new `py/unused-import` findings (#529-533). The original 28
assigned findings are absent from this PR analysis, not yet closed on main.
Public document-policy compatibility exports need an explicit public contract;
unused private access helpers belong in their leaf policy module. Preserve
real callers and import-order tests rather than suppressing the query.

Security run `37955418566` fails on two reviewed non-secret test lookalikes:
a traversal-path fixture in historical `c0f9775f` and a local-only HTTP signing
placeholder in `21bf8411`. Current attack patterns retain their negative
coverage with a neutral filename; each local fixture now generates its signing
key. Only those exact historical commit/file/rule/line fingerprints are added
to the existing false-positive ledger. No rule, test-directory or CodeQL
exclusion is added. A matched-version native history replay and positive new-
credential canary remain required before secret-scan closure.

The complete storage/finalizer replacement passes 230 tests and 690 reconciled
phases with native completion. Docker `97c11aee` proves image identity, schema,
index health and the in-web internal API-origin preflight, but its 1,992-case
PostgreSQL gate is interrupted for the newly discovered repairs. Its journal
has no completion event and is incomplete; all owned profile-aware resources
are removed. A complete fresh final-head Docker replacement is still required.

CI `37955418568` API shard 4 retains one failed historical assertion expecting
aggregate `always()` instead of the repaired `always() && !cancelled()`.
This is contract propagation missed by the narrower new cancellation tests,
not a reason to undo the repair or waive the failed shard. Reconcile the whole
shard, preserve artifact-upload `always()` and prerequisite failure guards,
then replay the complete old contract file and deployment-hardening inventory.
The complete hosted failed shard contains 573 tests in 49 files and exactly
one failure; all identities and phases reconcile. The three-file replacement
contains the whole historical shard-plan file, all deployment hardening and
production-workflow contracts: 227 collected, 226 passed and one Windows
POSIX-only skip, with 680 phases and native completion. The unchanged POSIX
case has the earlier network-disabled Linux supplement.

The import repair keeps all 17 public document-workflow functions explicitly
exported and removes three private facade imports. The two new regressions
positively fail before repair; all 31 boundary tests then pass with 93 phases.
The actual PostgreSQL successor/subject caller passes unchanged assertions.
Runtime function ASTs and the complete original policy test remain unchanged.
Full API Ruff passes. Fresh hosted analysis is still required.

Matched native Gitleaks `v8.24.3`, image digest
`e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055`,
reproduces exactly the two hosted fingerprints. Replacement history and both
current fixture files have zero findings. A separate offline Git repository
introduces a fake credential at the same file/rule/line in a new commit and
positively fails with one finding. Default rules and all 28 ordered attack
shapes remain intact; no shared Git history is rewritten. Native reports and
hashed manifest are in `gitleaks-independent-97c11aee-r3/` under the evidence
root. These are candidate-local scan proofs, not final-head hosted CI.

Current-head hosted CI, all-language scans and live acceptance remain NO-GO.

- Smoke, local and CI success sounded like full product acceptance while the
  exact-serving gate remained failed. Deployment and certification must differ.
- Actor-order races omitted sign-in versus historical FK provenance. Identity
  serialization used a lock stronger than necessary for immutable identifiers.
- In-process HTTP success did not prove real instance responsiveness during
  synchronous work in async handlers. Exercise two actual socket requests.
- Empty-result plans and small fixtures missed populated invalidation work.
  Lifecycle commands must not hydrate retained private bytes under a lock.
- Green scan execution did not mean the security findings were resolved.
- Google consent, provider readiness and Google-reported indexing outcomes are
  independent boundaries. Do not weaken tests or manufacture acceptance.

## Required Closure

Review agent changes and complete inventories, retain every phase and each
xdist worker collection, run fresh complete Docker/PostgreSQL/Playwright and
required CI, merge validated PRs to canonical main, then use only the guarded
exact-SHA release workflow. Replay every formerly failed complete journey plus
the full production inventory. Require two clean post-QA maintenance executions
before guarded cadence resume, and fresh main CodeQL alert reconciliation.

Keep #521 open until Google positively reports noindex exclusion. Calendar
BUG-003/004 remain Inconclusive until authorized Google consent and positive
persisted connection/reload proof. Previously user-approved provider and GBA
identity gaps remain open. Tests retain the no-paid-provider marker, use local
emulators and never submit synthetic production demo leads.
