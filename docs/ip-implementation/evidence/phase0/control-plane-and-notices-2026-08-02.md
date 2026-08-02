# IP program Phase 0 trust-repair and Notices regression record

**Evidence date:** 2 August 2026 (Asia/Kolkata)

**Repository:** CaseOps

**Branch:** `codex/ip-program-phase0-trust-repair-20260802`

**Starting revision:** `b7365cc1ca972662a7ae30d897610bfa92644f46`

**Directive:** `docs/CODEX_CLI_PROMPT_COMPLETE_REMAINING_IP_PRD_2026-08-02.md`

**Scope:** Phase 0.1 through Phase 0.4 only: current truth, the red production Notices regression, canonical manifest repair, and reconciliation of already delivered IP slices.

## Result and completion boundary

Phase 0 repository work is implemented locally and its focused verification is green. The production regression gate remains open until this exact change is committed, passes exact-commit CI/Security/CodeQL, is deployed, and the newest complete production Playwright workflow passes against the serving revision. This record will be amended with those immutable identifiers after release.

The full M0-M10 PRD is **not complete**. The manifest intentionally computes `in_progress / failed / blocked / pending` at this pre-release checkpoint. It does not convert deployment into legal, provider, pilot, security, data-governance, or human acceptance.

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

The active/next slice is now `IPLF-002A`, the dependency-ready M1 integration-health/freshness foundation, after Phase 0 release proof. The program remains blocked by the red production regression gate until this fix is deployed and retested, and by the explicit M0 human program-lock gate.

## Reconciled delivered scope

The following existing slices retain implementation claims only for behavior supported by code, tests, and dated release evidence:

- `IPLF-001A/B`: scheduler/IAM drift audit, immutable inventory, reconciliation, and bounded verification;
- `IPLF-003A/B`: shared typed source-state/open contract and rendered source actions;
- `IPLF-005A`: typed research outcomes, privacy-preserving observations, and golden-query runner;
- `IPLF-006A/B`: fail-closed statute quarantine, provenance, and curator command;
- `IPLF-007A/B`: durable notification intent lineage, provider evidence, suppression fallback, one dispatcher, and rollback flag;
- `IPLF-039A-F`: trademark particulars/readiness, review-gated evidence intake over canonical notice/communication owners, coverage reassignment, deadline incidents, effective-dated title/obligations, and Matter-billing reconciliation.

Requirement and path rows remain partial when those slices cover only fields or exceptions inside a broader PRD requirement. Human acceptance remains pending.

## Focused verification completed before commit

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

The full repository, browser, exact-commit CI, production deployment, and newest production Playwright results belong below and must be completed before Phase 0 exits.

## Release evidence to append

The following fields are intentionally pending and release blocking:

- release commit on `main` and `origin/main`;
- exact CI, Security, and CodeQL run IDs for that commit;
- exact API/web image digests and Cloud Run revisions for that commit;
- migration execution and serving schema-head reconciliation;
- post-deploy scheduler/job convergence against the new API digest;
- newest complete production Playwright run, including BUG-001, the notice-module suite, IP evidence-intake regression, desktop, and 360px visible actions;
- confirmation that local `main` and `origin/main` both resolve to the released commit.

## External and later-program boundary

Codex cannot self-approve the M0 program lock, legal rules/forms/deadlines, provider terms/credentials, pilot migration/UAT, retention/purge policy, security/records acceptance, or M8-M10 child PRDs. Those rows remain explicit gates. The correct eventual statement, if all repository-controlled work finishes before those approvals, is:

`PROGRAM INCOMPLETE - REPOSITORY WORK COMPLETE, EXTERNAL ACCEPTANCE PENDING`

At this checkpoint even that narrower statement is premature: substantial M0-M10 repository implementation remains represented by the derived `not_started` slices.
