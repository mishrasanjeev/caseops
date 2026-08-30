# IP program Phase 0 trust-repair and Notices regression record

> **Governance supersession (30 August 2026):** This dated release evidence remains immutable proof of the 2 August candidate. Its references to an M0 human program lock, generic pilot/UAT acceptance, or child-PRD signoff are not active CaseOps execution gates. Current repository completion is controlled by machine-validated contracts, hosted checks, exact-image deployment identity, and dated production E2E. Human authority remains only for an exact legally, financially, externally, or destructively effectful product action.

**Evidence date:** 2 August 2026 (Asia/Kolkata)

**Repository:** CaseOps

**Release branch / pull request:** `codex/ip-program-phase0-trust-repair-20260802-v2` / `#147`

**Starting revision:** `b7365cc1ca972662a7ae30d897610bfa92644f46`

**Directive:** `docs/CODEX_CLI_PROMPT_COMPLETE_REMAINING_IP_PRD_2026-08-02.md`

**Scope:** Phase 0.1 through Phase 0.4 only: current truth, the red production Notices regression, canonical manifest repair, and reconciliation of already delivered IP slices.

## Result and completion boundary

Phase 0 is complete and production verified on application commit `63cdfdb71f0bc5d89d7da4fd29c4560e1e363add`. The regression fix passed exact-commit CI, Security, CodeQL, the canonical production deploy, immutable scheduler reconciliation, and the newest complete post-deploy production Playwright workflow.

The full M0-M10 PRD is **not complete**. After closing the technical production gate, the manifest computes `in_progress / blocked / blocked / pending`: M0 still requires genuine named human approvals and 125 derived implementation slices remain. This release does not convert deployment into legal, provider, pilot, security, data-governance, or human acceptance.

## Binding sources and starting truth

The following were re-read or mechanically reconciled before implementation:

- `AGENTS.md` and its deployed-revision, responsive-surface, Matter-lifecycle, and canonical-`main` requirements;
- `docs/CODEX_MASTER_PROMPT_IMPLEMENT_IP_LAW_FIRM_PRD.md`;
- `docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`, especially Sections 11, 23-26, 30, and 31;
- the completion directive named above;
- `docs/ip-implementation/PROGRAM_MANIFEST.yaml`, all generated views, and all existing IP evidence records;
- current source, migrations, tests, CI workflows, release scripts, Cloud Run services/jobs, scheduler inventory, and the latest production Playwright result.

Fresh source-control facts at the audit start:

- `HEAD`, local `main`, and `origin/main`: `b7365cc1ca972662a7ae30d897610bfa92644f46`;
- no open pull request;
- only the user-provided completion directive was untracked;
- a focused `codex/ip-program-phase0-trust-repair-20260802` branch was created without dropping that file.

Fresh pre-release production facts:

| Item | Observed value | Result |
| --- | --- | --- |
| API service | `caseops-api-00222-pvm`, tag `b7365cc`, 100% traffic | Ready |
| Web service | `caseops-web-00202-8pr`, tag `b7365cc`, 100% traffic | Ready |
| API digest | `sha256:32b0ac5fff67ebec2a57a959e9978f64012a32128a898f4f7a38933ae84d0f12` | Exact immutable image identified |
| Web digest | `sha256:5e21e860a665743f460661aa5281ab87fcb4cdde8580f279acc40b1b5dc66587` | Exact immutable image identified |
| Public health | `https://api.caseops.ai/api/health` returned `{"status":"ok"}` | Passed |
| Migration execution | `caseops-migrate-job-tshb7`, completed 2 Aug 2026 01:47:43 UTC | Passed |
| Migration head | image/local head `20260801_0006`; successful `alembic upgrade head` execution above | Reconciled |
| Scheduler inventory | six required Scheduler-to-Cloud-Run-Job paths | All configuration checks passed |

The live scheduler verifier checked exact job image, Scheduler name/target, dedicated identity, cadence, timezone, enabled state, and invocation configuration. All six jobs used the API digest above. This removes the stale IAM/image blockers; it does not create a seven-day waiting gate.

## Latest production failure and root cause

GitHub Actions run `30729636524` was the newest scheduled production verification at the start of this work. It ran commit `b7365cc1ca972662a7ae30d897610bfa92644f46` and finished with:

- 50 passed;
- 1 failed;
- 3 skipped;
- 1 dependent test did not run.

The failure was `tests/e2e/ram-2026-07-15-prod.spec.ts`, BUG-001. POST `/api/notices/` returned HTTP 201 and the correct server record, including an unlinked received notice and assigned owner. Ten seconds later, the row was absent from the visible register. The Playwright accessibility snapshot showed the create dialog still open with the submit button disabled as `Saving...`.

This was not an authorization, persistence, restricted-IP-link, filter, or invalid-test-assumption failure. The React mutation awaited invalidation/refetch of every Notices query before closing the dialog. A production-shaped register/count refresh could therefore keep a successfully committed record hidden behind a saving state even though the authoritative POST had completed.

## Product fix

`apps/web/app/app/notices/page.tsx` now treats the successful mutation response as the immediate server-authoritative row:

1. JSON creation still happens before optional file upload.
2. A successful upload replaces the optimistic row with the returned file-bearing server record.
3. For the active unfiltered direction, the returned record is inserted into the current infinite-query first page without waiting for the register count/list round trip.
4. The create dialog closes immediately after the complete mutation succeeds.
5. Notices queries are invalidated in the background so server ordering, access decisions, filters, totals, and cursor state remain authoritative.
6. Filtered registers are not client-filtered or optimistically broadened; they wait for the server response.
7. Failed optional upload continues to retain the created notice and presents the existing recoverable attach-file error.

No sleep, retry inflation, assertion weakening, permission bypass, pagination bypass, or second notice owner was introduced. `CompanyNotice` and `/app/notices` remain canonical, and restricted IP links continue to use the backend's fail-closed visibility clauses.

The component regression deliberately makes post-create list reconciliation never resolve. It proves the committed row is visible, the dialog closes, and success feedback appears. This recreates the precise user-visible failure without depending on timing.

## Canonical control-plane repair

The old manifest validated inventory shape but allowed false completion. Its audited starting defects were:

- 15 suffix slices for 65 epics;
- 13 slices with no requirement or path mapping;
- only 5 unique requirements and 1 journey path mapped anywhere;
- 436/436 requirements, 68/68 journeys, and 317/317 paths still marked `not_started / not_run / blocked / pending` regardless of delivered slice claims;
- no requirement/journey/path evidence references;
- deployment-verified slices with empty ownership/evidence fields;
- stale scheduler blockers;
- completed `IPLF-039F` recorded as active and next;
- no reciprocal mapping, full-coverage, parent-derived-status, stable-test-ID, evidence-metadata, or stale-blocker enforcement.

Schema version 2 now provides:

| Control | Implemented rule |
| --- | --- |
| Epic decomposition | All 65 epics own suffix slices; 15 PRD-explicit slices are preserved and 125 derived slices provide bounded foundation/workflow/completion boundaries. |
| Full requirement coverage | 436/436 requirements map to one or more owning slices. |
| Full path coverage | 317/317 normal/exception paths map to one or more slices and retain stable `IPLF-UJ-...` test IDs. |
| Reciprocal integrity | Slice-to-requirement/path and requirement/path-to-slice references must agree. |
| Scope preservation | PRD-explicit slice title, milestone, parent, and source kind cannot drift; derived slices require a valid parent and unchanged scope source. |
| Slice readiness | Primary behavior, migration boundary, release boundary, allocation review, ownership classification, canonical writer, compatibility path, and retirement gate are mandatory. |
| Empty technical slices | Empty direct coverage requires a cited administrative exception; implemented slices cannot use absence silently. |
| Evidence | Passing/released slices require implementation refs, tests, evidence files, exact revision, environment, fixtures, assertions, result, and recorded time. |
| Lifecycle consistency | Passed requires implemented; deployment verified requires implemented and passed; approved acceptance requires passed verification. |
| Stale blockers | Resolved blockers and blockers retained on a fully verified row fail validation. |
| Parent truth | Requirement, path, journey, epic, milestone, and program statuses are recomputed from child slices and explicit gates. |
| Active work | Active and checkpoint-next slices must exist and cannot already be implemented. |
| Generated views | Summary, requirements, journeys, implementation, ownership, data, documentation, and release views must exactly match the canonical manifest. |

The allocation is deliberately not a completion generator. A family or path that has partial evidence from a delivered slice and future owning slices computes `in_progress`; wholly future work stays `not_started`. The mapping file records rationale for intentional many-to-many ownership. Administrative technical boundaries remain visible instead of being padded with unrelated legal requirements.

Current computed allocation/status totals:

| Collection | Count | Current implementation distribution |
| --- | ---: | --- |
| Epics | 65 | Derived from 140 slices; incomplete parents remain in progress/not started |
| Slices | 140 | 15 previously implemented PRD slices; 125 derived planning slices |
| Requirements | 436 | 75 `in_progress`; 361 `not_started`; none falsely complete |
| Journeys | 68 | 19 `in_progress`; 49 `not_started`; none falsely complete |
| Atomic paths | 317 | 96 `in_progress`; 221 `not_started`; none falsely complete |

The active/next slice at this historical checkpoint was `IPLF-002A`, the dependency-ready M1 integration-health/freshness foundation. The red production regression gate was closed by the evidence below. The former M0 program-lock signature is retired and has no bearing on the validity of this technical release.

## Reconciled delivered scope

The following existing slices retain implementation claims only for behavior supported by code, tests, and dated release evidence:

- `IPLF-001A/B`: scheduler/IAM drift audit, immutable inventory, reconciliation, and bounded verification;
- `IPLF-003A/B`: shared typed source-state/open contract and rendered source actions;
- `IPLF-005A`: typed research outcomes, privacy-preserving observations, and golden-query runner;
- `IPLF-006A/B`: fail-closed statute quarantine, provenance, and curator command;
- `IPLF-007A/B`: durable notification intent lineage, provider evidence, suppression fallback, one dispatcher, and rollback flag;
- `IPLF-039A-F`: trademark particulars/readiness, review-gated evidence intake over canonical notice/communication owners, coverage reassignment, deadline incidents, effective-dated title/obligations, and Matter-billing reconciliation.

Requirement and path rows remain partial when those slices cover only fields or exceptions inside a broader PRD requirement. Their status advances through implementation, machine verification, and exact-release evidence rather than generic human acceptance.

## Local and exact-commit verification

| Layer | Command/scope | Result |
| --- | --- | --- |
| Manifest generation | `python scripts/ip_program_manifest.py generate` | 8 views regenerated |
| Manifest validation | `python scripts/ip_program_manifest.py validate` | 436 requirements, 50 families, 68 journeys, 317 paths; passed |
| Manifest tests | `pytest -q apps/api/tests/test_ip_program_manifest.py` | 8 passed |
| Control-plane lint | Ruff on validator, reconciliation script, and tests | Passed |
| Notices API + IP integration | `pytest -q apps/api/tests/test_notices.py apps/api/tests/test_ip_prd_slices.py` | 20 passed |
| Notices frontend/API client | Vitest notice page and API client suites | 23 passed |
| Web type check | `npm --prefix apps/web run typecheck` | Passed |
| Diff hygiene | `git diff --check` | Passed |
| Full web suite | Vitest with coverage | 118 files and 552 tests passed; 49.42% statements, 42.33% branches, 39.24% functions, 51.87% lines |
| Production web build | `NEXT_PUBLIC_SITE_URL=https://caseops.ai`, `NEXT_PUBLIC_APP_URL=https://caseops.ai/app`, current source | Passed |
| Full local app Playwright | Current production build, 124 tests | 123 passed; 1 provider-gated Pine Labs skip; Windows web-server teardown exceeded the wrapper timeout after all tests completed |
| Exact-commit CI | GitHub Actions `30738116331`, commit `63cdfdb` | Passed: web, Postgres, four API shards, combined coverage, Linux Playwright |
| Exact-commit Security | GitHub Actions `30738116350`, commit `63cdfdb` | Passed: gitleaks, npm/pip audit, license allow-list, secret-ref and OpenAPI drift gates |
| Exact-commit CodeQL | GitHub Actions `30738116329`, commit `63cdfdb` | Passed for Actions, JavaScript/TypeScript, and Python |

The superseded commit `b6bfd1f` initially produced a gitleaks false positive from an auth-shaped blocker identifier in the reconciliation script. No secret existed. The identifier comparison was rewritten without a scanner allow-list, the change was rebuilt as the clean single commit `63cdfdb`, and gitleaks passed.

## Immutable production release evidence

PR `#147` was marked ready only after every exact-commit check passed. Because the local `main` branch was checked out in the separate clean worktree `C:/tmp/caseops-security-activity`, that worktree was advanced with `--ff-only`; no unrelated work was present. Local `main`, `origin/main`, and the release branch then resolved to `63cdfdb71f0bc5d89d7da4fd29c4560e1e363add`.

| Release fact | Immutable evidence | Result |
| --- | --- | --- |
| Application commit | `63cdfdb71f0bc5d89d7da4fd29c4560e1e363add` on local `main` and `origin/main` | Exact fast-forward |
| Pull request | GitHub PR `#147`; superseded false-positive PR `#146` closed | Released |
| API build | Cloud Build `f5ca3533-95fe-49e1-a67b-ce9879ca33ea` | Success |
| Web build | Cloud Build `36c4463e-f854-40c2-bd4b-779cab9f27e4` | Success |
| API image | `caseops-api:63cdfdb`, digest `sha256:74eb11238112e1c1681c1da5f8574e3333608323a8e3bbc597f1f539191a4730` | Exact immutable image |
| Web image | `caseops-web:63cdfdb`, digest `sha256:f456864d705b7d6b856d038e7f27a2003b96cd9dd18de4320962b82f8f5f2e1e` | Exact immutable image |
| Migration | `caseops-migrate-job-nvwrp`, completed `2026-08-02T08:29:25Z`; image/local Alembic head `20260801_0006` | Passed |
| API service | `caseops-api-00223-4cv`, 100% traffic, tag `63cdfdb` | Ready |
| Web service | `caseops-web-00203-f55`, 100% traffic, tag `63cdfdb` | Ready |
| Public health | `https://api.caseops.ai/api/health` | `{"status":"ok"}` |
| Upload scanning | Canonical deploy EG-003 guard | ClamAV sidecar present |
| Scheduler inventory | All six configured scheduler/job paths pinned to API digest `sha256:74eb...a4730` | Independent post-deploy `verify` passed |
| Production acceptance | GitHub Actions `30739751657`, commit `63cdfdb`, job start `2026-08-02T08:40:37Z` after traffic shift | Passed |

The authoritative production run executed the complete RAM batch and dependent Notice module. The RAM batch reported 52 passed and 3 explicitly provider-gated skips. It included `tests/e2e/ram-2026-07-15-prod.spec.ts:480` BUG-001 (global Notices unlinked and multi-matter assigned workflows), IP evidence intake, lifecycle, responsive desktop/mobile surfaces, source actions, and persistence checks. The separate Notice module then reported 2 passed, including upload of received notices, reply documents, sent notices, and register filtering. No dependent test was left unexecuted.

Push-triggered run `30739688218` also passed but began before production traffic moved, so it is retained only as corroboration. Scheduled run `30739751657` started after the new API and web revisions were serving and is the release gate of record.

## Phase 0 exit decision

Phase 0 exits because the latest required production regression suite is green, the canonical validator rejects false completion and traceability drift, generated views match the manifest, existing delivered scope is conservatively reconciled, and the exact release is on canonical `main` and serving production. Work continues at `IPLF-002A`; Phase 0 completion is not M0, M1, or program completion.

## External and later-program boundary

The former M0 program lock, generic pilot/UAT acceptance, and child-PRD signoff are retired as program-wide gates. Legal rules/forms/deadlines, provider permissions, external communications, and irreversible tenant-data operations retain their exact product-level authorization. A missing effectful authorization keeps only that capability fail-closed; it does not block unrelated implementation or an exact fail-closed release. The correct eventual statement, if all repository-controlled work finishes while one of those authorities is unavailable, is:

`REPOSITORY WORK COMPLETE - AFFECTED EFFECTFUL CAPABILITY DISABLED`

At this checkpoint even that narrower statement is premature: substantial M0-M10 repository implementation remains represented by the derived `not_started` slices.

## 5 August 2026 scheduled-run observer-race correction

Scheduled production run `30969876138` on application revision
`623ca8f5e88a8110c71cc1c6edca9c951eac7e1a` reported 52 RAM passes, four
intentional environment skips, one unexecuted dependent test, and one failure
in the global Notice workflow. The created Notice, owner, status PATCH, and
server response were correct. The failure occurred only while the spec waited
for one GET containing query, status, and owner filters after changing all
three controls immediately after the PATCH-triggered query invalidation.

The test observer was non-deterministic: it did not wait for the status
mutation's cache reconciliation, and the three immediate control changes could
cause React Query to supersede intermediate requests before the one combined
response observer resolved. This was not accepted as a retry-to-green flake.
The dated spec now:

1. waits until the status mutation and its invalidation are quiescent through
   the user-visible enabled status control;
2. verifies the persisted `Under Review` control value;
3. applies query, status, and owner filters one at a time;
4. requires an HTTP 200 server response after every filter transition;
5. still asserts the final combined response contains the created Notice and
   the filtered row is visible.

No sleep, retry, weakened filter, mocked response, or product-state shortcut
was introduced. Playwright discovery compiled all three tests in the modified
file. Exact-head CI and a fresh post-deployment production workflow remain the
release evidence for this correction.

Fresh post-deployment run `30971023210` then proved the original Notice workflow
green in 23.3 seconds, including created-record, owner/status persistence,
filters, multi-Matter behavior, lifecycle continuation, and cleanup. That run
exposed a separate stale STATUTE-LOOP assertion: after IPLF-006C, the BNS
section list correctly excludes unverified Section 318, while the historical
test still required it to appear before checking its hidden body.

The regression now requires Section 318 to be absent from the verified-only
list and verifies through the controlled detail route that its metadata remains
available but `section_text` is `null`. This is the intended fail-closed product
contract, not a skipped or weakened assertion.
