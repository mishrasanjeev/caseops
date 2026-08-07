# IPLF-020B production verification closure — 2026-08-07

## Verdict

`PROGRAM INCOMPLETE`. IPLF-020B's repository implementation, independent CI,
migration-aware deployments, immutable-image convergence, and intended dark
production behavior are proven. The slice is not yet marked
`deployment_verified` because the complete dated production workflow must be
green on one exact serving commit. No failed run is waived.

This record also documents a production-suite regression in the pre-existing
IPLF-007C notification surface discovered by the second IPLF-020B verification
run. The regression is being corrected at its real UI cache owner before the
full workflow is rerun. It is not treated as an IP entitlement or rollout
reason, and no production control is enabled to make a test pass.

## First exact release and stale IP assertion

PR #172 passed CI, Security, CodeQL, PostgreSQL, OpenAPI, web build, and the
application Playwright suite. It merged as
`76e8a54b423787ee2bced724b29dc6d35102a7e2` and deployed with:

- migration execution `caseops-migrate-job-zxntg`: success;
- API `caseops-api-00243-xvj` at 100% traffic, digest
  `sha256:744709fe1bbda3c6394ad81de7f16758e64689df54090d850f3599db4e67a20a`;
- web `caseops-web-00223-cv4` at 100% traffic, digest
  `sha256:d6ffa4ca0b011fb5135da59f79de344fcd88c1f7ca909ac390952b13c618651f`;
- exact public identity, scheduler inventory, health, and ClamAV: passed.

Production workflow `31143525027` failed after 55 RAM tests passed because the
August 1 specification still expected an enabled trademark docket. Production
was intentionally dark: the QA tenant had no `ip_workspace` entitlement and
the server rollout flag was disabled. The test was corrected to assert the
actual fail-closed contract: readiness succeeds, `workspace_available=false`,
disabled reasons are visible at 360 pixels, creation/docket surfaces are
absent, and the browser never requests `/api/ip/dockets`.

## Corrected IP proof, exact deployment, and second workflow

The correction was committed as
`927b00d4c9e21ca4e2967a04b52ac6dd115666e3`, reviewed in PR #173, and passed:

- all eight API coverage shards and the combined per-area coverage gate;
- API Ruff, PostgreSQL/pgvector, OpenAPI clean generation, web typecheck,
  Vitest/coverage/build, and the application Playwright suite;
- CodeQL for actions, Python, and JavaScript/TypeScript;
- secret, dependency, license, and Cloud Run secret-reference checks.

PR #173 merged as canonical `main`
`6d7a4fcc43096ba1a23e0902bb7e2801b556a51e`. Local `main` and `origin/main`
were fast-forwarded to the same SHA. The canonical deploy completed:

- migration execution `caseops-migrate-job-hh7rk`: success;
- API `caseops-api-00244-7l2` at 100% traffic, immutable API digest
  `sha256:ea5cc6908884d72f073831cff659998314f6022ee2cb3546f6ed9ed54ab39bd3`;
- web `caseops-web-00224-7z2` at 100% traffic, build digest
  `sha256:5e20884d158100d83feffee346b379d1b67604ab4e1692fd4f90a2f113de60e7`;
- all six recurring jobs converged to the immutable API digest;
- public API/web identity returned the full expected SHA;
- health and ClamAV sidecar checks passed.

Production workflow `31146475554` checked out the exact serving SHA. The
corrected IPLF-020B desktop/360-pixel test passed in 8.7 seconds. The RAM batch
finished with 56 passed, four expected skips, and one failure; the Notice suite
correctly did not run after the RAM failure.

## Notification regression diagnosis

The failure was
`ram-2026-08-05-prod.spec.ts` IPLF-007C safe in-app notification acceptance.
The POST returned HTTP 200 with a durable `delivered` intent and zero external
provider calls. A direct authenticated admin GET returned that exact intent and
the delivered metric. Only the already-open React view failed to render its row
within ten seconds.

The uploaded Playwright accessibility snapshot proved that the page retained
its pre-click 50-row cache while the QA tenant contained more than 1,800 intent
records created by serial production checks. The mutation showed its success
toast before the asynchronous invalidation/refetch completed. Under an initial
list/refetch race, invalidation alone did not guarantee that the committed row
became user-visible. Persistence, tenancy, authorization, and API ordering were
not the failing owners.

## Corrective implementation and local proof

Commit `e47c9137eca87d8ea206451b5f42880c39425a07` updates every active
`["admin", "notifications"]` query cache with the committed response before
requesting authoritative reconciliation. It deduplicates by intent ID and
updates the displayed delivered metric exactly once. The server refetch remains
the final authority; the cache update only closes the confirmed-response UI
gap.

The regression test intentionally leaves the authoritative refetch unresolved.
It proves that the exact committed row and delivered count still become visible
from the POST response, which reproduces the production timing boundary without
adding sleeps or weakening the production assertion.

Local verification:

```text
npm --prefix apps/web test -- --run app/app/admin/notifications/page.test.tsx
1 file passed; 4 tests passed

npm --prefix apps/web run typecheck
passed; Next route types generated and TypeScript emitted no errors

git diff --check
passed
```

## Remaining release gate

The notification correction must pass independent CI, merge to canonical
`main`, deploy through `scripts/deploy-prod.sh` as one exact new SHA, converge
all recurring jobs to that image, pass public identity verification, and pass
both the complete RAM and Notice production suites. Only then may IPLF-020B be
recorded as `deployment_verified` and the serial IPLF-021A release begin.

This evidence does not claim M0 human approval, lawyer approval of legal
fixtures, provider approval, enabled IP production operations, complete UJ-01,
M2 completion, or overall program completion.
