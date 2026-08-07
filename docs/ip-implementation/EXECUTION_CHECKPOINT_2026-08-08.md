# IP Law Firm PRD execution checkpoint — 8 August 2026

## Executive status

The repository-controlled program is actively progressing and remains
`PROGRAM INCOMPLETE`. Slices through IPLF-022A are implemented, independently
verified, merged to canonical `main`, deployed as exact immutable revisions,
and accepted by the dated production browser workflow. IPLF-022B is fully
implemented and freshly verified on the accepted IPLF-022A base; its
independent PR, production migration/deployment, and exact-revision production
acceptance are the next release gates.

No seven-consecutive-day natural-scheduler observation is used as a release
blocker. Deterministic scheduler configuration, identity, immutable image,
cadence, timezone, invocation, and bounded canary evidence are used for
release decisions. Natural executions remain operational evidence. The
authority-metadata job's $40.07 rolling spend stop against its $40.00 cap is
preserved as a correct policy stop; the cap was not weakened or bypassed.

Genuine human legal acceptance, provider permissions, pilot approval, real
filings, fees, deadline decisions, and external communications remain genuine
gates. Automation does not fabricate them.

## IPLF-022A production closure

IPLF-022A delivered the append-only docket-event foundation and fail-closed
docket lifecycle service. Terminal transitions, Matter disposal, lifecycle
versions, audit events, and operational-child neutralization are atomic under
the parent lock. Generic metadata changes, imports, background workers, and
child updates cannot reactivate terminal rows. Controlled reopen preserves
history and does not resurrect children.

The production Notice workflow exposed and closed three sequential upload
latency boundaries:

1. Immediate GCS re-download before ClamAV acceptance was removed by scanning
   the exact temporary bytes before any durable local/GCS persistence.
2. The document worker stopped flushing and locking a new parent attachment
   across the external embedding call.
3. The worker stopped holding the parent Matter lifecycle lock across that
   provider call. It now rechecks and locks the Matter under `no_autoflush`
   immediately before the first child/vector persistence, so concurrent
   disposal still rolls the provider result back fail-closed.

The final repair passed PR `#185` as candidate
`d99da43b89010ea5f40b7c4ff7dc27b32d577b55` and merged to canonical `main`
as `01361f499fdad42bc95884fadcdbfff7e9cafc0a`.

| Release evidence | Exact result |
| --- | --- |
| CI | `31267547501`, all eight API shards, aggregate coverage, PostgreSQL/pgvector, web, and Playwright passed |
| Security | `31267547499`, passed |
| CodeQL | `31267547507`, Actions/Python/JavaScript-TypeScript passed |
| API build | `c54ca0ab-7f92-4ada-8682-d5a0cf358c53` |
| Web build | `7c103f78-5db9-40b7-addf-0b9ce0dc2f4e` |
| API digest | `sha256:7438133f141cb59085f63c9a0d0544fd711c25a76f16030bcc74eaf168185dde` |
| Web digest | `sha256:c16d8051f7959c4906c5d40731e316ab6babcc6d68e7a1d29cf7c241e42d5b0a` |
| Migration | `caseops-migrate-job-wwl4b`, successful |
| API/Web revisions | `caseops-api-00254-pq4` / `caseops-web-00234-dwd`, 100% traffic |
| Production acceptance | `31268892105`, RAM and Notice suites passed in 25m23s |

The accepted Notice uploads returned HTTP 200 in 0.417412085 seconds
(received), 0.755888145 seconds (reply), and 0.336074321 seconds (sent). All
six scheduled jobs matched the exact API digest and checked-in configuration;
health, release identity, and the required ClamAV sidecar probe passed.

## IPLF-022B implementation checkpoint

IPLF-022B is restacked on the accepted main as feature commit
`f82ff8ea4ffa8cd2a9ebf7ff88e3d52e223c6e66`. It adds the capability-gated
prosecution and lifecycle user workflows, additive application lifecycle
migration `20260807_0004`, preview-before-commit event and lifecycle APIs,
optimistic concurrency, registry candidate/reconciliation treatment,
backdated-event recalculation markers, evidence checklists, downstream-impact
acknowledgement, successor validation, controlled restoration/reopen, and
mobile-safe web actions.

Fresh restacked verification passed:

- 27 API/migration prosecution, lifecycle, record, workspace, and readiness
  tests;
- 46 migration-order, foreign-key-index, manifest, ownership, and
  architecture/operations tests;
- full API Ruff and all four repository control-plane validators;
- 7 IP-page Vitest tests, TypeScript, and a 65-route Next.js production build;
  and
- 2 dated Playwright scenarios, including every grouped action rendered
  within a 360-pixel viewport and the full linked Matter evidence/coverage/
  obligation/cost/reconciliation/lifecycle workflow.

IPLF-022B remains `ready_for_review`, not `deployment_verified`, until its
exact candidate passes independent CI/Security/CodeQL, merges to `main`, runs
the production migration, deploys exact API/web artifacts, reconciles the six
schedulers, passes HTTPS identity verification, and completes the dated
production workflow.

## Remaining program boundary

The next unimplemented slice is IPLF-023A. Later M2/M3 slices, including the
reciprocal IPLF-033B ownership for the remaining trademark-specific
IP-PROS-01..12 and UJ-06/UJ-53 depth, are not represented as complete. The
canonical manifest and generated views remain the source of truth for all 436
requirements, 50 families, 68 journeys, and 317 atomic paths.

Detailed per-slice evidence remains under `docs/ip-implementation/evidence/`;
this checkpoint is a consolidated operational handoff, not a substitute for
those exact test, deployment, rollback, and acceptance records.
