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
- A proposed schema/governance run selected a nonexistent
  `test_platform_admin_billing.py`; no tests ran and exit 4 is incomplete
  evidence, not green coverage. The replacement verifies actual filenames and
  includes the existing billing and hearing-reminder suites.
- PR #522's fresh head is `66dd8e48b75391f9ac0c8afe08027e8dc5cf0c93`.
  Its focused fresh build/typecheck, 23 public browser tests and 20 adjacent unit
  tests pass. Required GitHub jobs remain queued without assigned runners;
  queued timestamps are not execution proof. No CI bypass is authorized.
- Native CodeQL setup is incomplete: a bounded official bundle transfer
  timed out, and partial downloads plus checksums are preserved. No local SARIF
  or actual-main alert closure is claimed. No suppressions or dismissals were
  introduced. Historical unassigned graph cycles are not silently relabelled
  as removed by the focused assigned-path test.

This checkpoint is not a production GO. The candidate has not completed the
whole fresh Docker/CI inventory or been deployed.

Incremental journals/JUnit are in `.tmp/issues-security-20261009/`. Preserve the
first projection attempt with an unrecognized PostgreSQL environment key and
the adjacent dispatch import-collection error as incomplete evidence. Corrected
baselines must positively run before implementation claims.

## Where Earlier Work Was Insufficient

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
