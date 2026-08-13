# IPLF-028A production release attempt - 2026-08-13

## Verdict at deployment checkpoint

The bounded IPLF-028A records-governance foundation is merged, deployed, and
independently identified on exact production revision
`2aa839d5391b12479ead576645c89c45ff6de09f`. The release is additive and
unseeded: it introduces six dry-run-only governance tables but performs no
retention decision, legal-hold activation, export, purge, offboarding, restore,
provider operation, object-store operation, or other real-world legal/data act.

This is not M2 data-governance or resilience completion. IPLF-028A remains
`in_progress / not_run / blocked / pending` because the full data map,
authorized retention/hold workflow, data-operation execution boundary, and
database-plus-object resilience rehearsal remain unresolved. `PROGRAM
INCOMPLETE` remains the only accurate program state.

The dated exact-release production Playwright workflow `31674495928` completed
after confirming the exact serving API/web identity. Its RAM/IP batch reported
`65 passed`, `4 failed`, and `3` documented skips; its Notice phase reported
`2 passed`. The four failures are the historical external operator gates: three
recommendation assertions received typed `llm_quota_exhausted` HTTP `503`
responses, and the case-tracking canary received the known provider-health HTTP
`409`. The result is not green and does not satisfy the complete-production
gate. It also does not identify an IPLF-028A schema/data-governance regression.
Exact-main CI `31674495913` subsequently completed successfully. The exact
merged source, deployment identity, and repository CI are therefore verified;
the complete-production gate remains red solely on the documented external
provider conditions above.

## Exact lineage and repository gates

| Control | Exact result |
| --- | --- |
| Pull request | [#217](https://github.com/mishrasanjeev/caseops/pull/217), head `b626d439ef6cd63a53e507439c4a1393e351524c` |
| Canonical main | Merge commit `2aa839d5391b12479ead576645c89c45ff6de09f`; local `main` and `origin/main` resolve to this commit |
| Exact-head CI | `31671172662` passed: eight API coverage shards, aggregate API coverage, PostgreSQL + pgvector, Web typecheck/Vitest/build, and Playwright app suite |
| Exact-head Security / CodeQL / review | `31671172657` / `31671172671` / `31671172666`, all passed |
| Exact-main CI | `31674495913` passed after the merge and exact production deployment |
| Local focused foundation proof | `8 passed` migration/service/registry; `1 passed` FK-index contract; fresh PostgreSQL guard `1 passed, 23 deselected, 1 warning`; program-control suite `53 passed, 1 warning` |

## Exact production deployment and independent verification

| Control | Exact result |
| --- | --- |
| API build | Cloud Build `bfae7e8d-cc10-4d5e-aa48-69005623b297`, tag `2aa839d` |
| API immutable image | `sha256:bd39abed8b81d7cebefc2691761428aa418a278bc29968d3c7b58d1d26ad2daa` |
| Web build | Cloud Build `4b195835-dca2-41f9-a3ee-29f4413587c0`, tag `2aa839d` |
| Web immutable image | `sha256:6ef033cd9c3f7df86929e211e9333053e4dec08ad32b7562ae4ae204f8707c26` |
| Migration | `caseops-migrate-job-kq56w`, `succeededCount=1`, Completed `True` at `2026-08-13T06:48:43.582819Z` |
| API revision | `caseops-api-00286-8x7`, 100% traffic, concurrency `1`, service and revision maximum `20` |
| Web revision | `caseops-web-00264-xpn`, 100% traffic |
| Release identity | `scripts/verify_deployed_release.py --expected-sha 2aa839d5391b12479ead576645c89c45ff6de09f` passed: API and web expose the exact SHA and revisions above |
| Health | `https://api.caseops.ai/api/health` returned `{"status":"ok"}` |
| Scheduler inventory | all six bindings passed state, target, cadence, timezone, invoker identity, IAM, and exact API-digest verification |
| Dark controls | `CASEOPS_AUTO_MIGRATE=false`; `CASEOPS_DOMAIN_OUTBOX_CONSUMERS_ENABLED` and `CASEOPS_IP_WORKFLOW_COMMANDS_ENABLED` absent/default-false |
| Exact-release production workflow | `31674495928` confirmed the serving SHA/revisions, then finished red: RAM/IP `65 passed, 4 failed, 3 skipped`; Notice `2 passed`. The failures are three typed OpenAI quota `503`s and the pre-existing case-tracking provider-health `409`; no green production-suite result is claimed. |

The checked-in `scripts/deploy-prod.sh` ran its ordered build, migration,
scheduler convergence, API, web, staleness, health, and ClamAV sidecar guards
successfully. It verified latest-only traffic and no stale API/web revision
tags.

## Scope preserved after deployment

- All six new tables remain empty unless a future separately approved action
  writes a dry-run evidence record.
- The schema and service prohibit `execution_mode != dry_run` and
  `safe_to_execute=true`; explicit execute attempts return typed
  `data_operation_execution_unavailable` instead of performing I/O.
- There is no IPLF-028A route, worker, scheduler, storage/provider adapter,
  policy seed, export, purge, offboarding, restore, or active legal-hold
  workflow.
- Existing external production failures are not disguised as resolved: the
  configured OpenAI project still needs a quota/credit restoration decision,
  and the case-tracking-provider HTTP 409 health/replay condition needs its
  authorized operator review.

## Required follow-up

1. Preserve workflow `31674495928` as a red complete-suite gate with its three
   provider-quota `503`s and case-tracking-provider `409`; do not reclassify
   those conditions as fixed without an authorized provider operator action and
   a fresh exact-release rerun.
2. Complete the full platform data map and make new SQL/object/index/cache/
   queue/log/export/provider/backup stores fail Definition of Ready without an
   approved registry/disposition update.
3. Obtain named legal/privacy/security/product authorization for retention
   policies, legal-hold lifecycle, step-up/four-eyes, and any user-facing
   data-operation workflow before designing an execution capability.
4. Run the required approved non-live database-plus-object application-cutover
   restore rehearsal and tenant-export dry run. Do not claim RES-13 from this
   empty schema deploy.
