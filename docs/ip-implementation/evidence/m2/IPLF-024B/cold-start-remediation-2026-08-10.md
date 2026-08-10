# IPLF-024B evidence-head cold-start remediation — 2026-08-10

## Trigger and diagnosis

The IPLF-024B application release `64f6360b7bd9f4943be56c3d2c28662ce361bf5f`
was already deployment-verified by production workflow `31329680798`. The
later evidence-only main head `aee6d2da94a2f9a38105e98a93529c0ca5bdeba4`
was rebuilt and deployed exactly so documentation was not mistaken for a
released revision. Its push workflow `31345422898` exposed a separate
production regression: the admin integrations page remained at “Loading
integrations...” and the RAM assertion for `connector-health-summary` timed
out.

The failing run completed 58 tests with five conditional skips before that
single failure. Exact-revision Cloud Run request logs showed both
`GET /api/admin/integrations` and `GET /api/admin/integrations/health`
returning HTTP 200 only after about 55 seconds. The page launched four
independent provider reads concurrently. The canonical API configuration has
container concurrency `1`, and burst scale-out made multiple new instances pay
the ClamAV sidecar cold-start cost together.

## Change and independent verification

PR #198 sequenced the four initial provider reads while retaining progressive
rendering: integrations, health, Google Workspace configuration, then Drive
status. A component regression asserts the exact request order. No API,
provider, scheduler, schema, entitlement, or legal-workflow behavior changed.

- PR head: `56a1d0d8330068f05e7f5762799521befe8eb2df`
- CI run: `31346973753`
- Result: all eight API coverage shards, aggregate coverage, API lint,
  PostgreSQL/pgvector, web typecheck/Vitest/build, full Playwright app suite,
  Security, CodeQL, and Codex review passed.
- Merge/main release: `18a199bfb0ef6377f88d7bd401d22b42f68faf91`

## Exact deployment

The canonical `scripts/deploy-prod.sh` pipeline ran from a clean detached
worktree at the exact merge commit.

- Backend image Cloud Build: unique run prefix `427fe57d-d030`
- Web image Cloud Build: unique run prefix `244c219f-189d`
- API digest: `sha256:927f9285d531c7734a0f2a05884cb189aa6a6a200fcf60ea58b75fb2c8f1d0a3`
- Web digest: `sha256:45bd6b2fbce140dc296cf9541ace8166ef2b8a5cb9dc628d0b2414f88f734c80`
- Migration execution: `caseops-migrate-job-m8nrh` — completed
- API revision: `caseops-api-00267-swr` — 100% traffic
- Web revision: `caseops-web-00247-sb7` — 100% traffic
- API health: `{"status":"ok"}`
- Exact public identities: API and web both returned full SHA
  `18a199bfb0ef6377f88d7bd401d22b42f68faf91` with the revisions above.
- Scheduler inventory: all six canonical bindings passed and use the immutable
  API digest; the superseded midnight tracking schedule remains paused.
- ClamAV: sidecar present with immediate two-second startup probing.

## Dated production acceptance

Push workflow `31348569898` first waited for and checked out the exact serving
release. The RAM batch passed 61 tests with three conditional skips in 13.7
minutes, including the integrations surface and the IPLF-024B locked,
fail-closed document journey. The Notice module then passed both cases in 20.6
seconds. Failure media upload was skipped because the workflow was green.

During the exact run, request logs on `caseops-api-00267-swr` showed the
integrations and health reads returning HTTP 200 in approximately 0.16–0.29
seconds. This is supporting operational evidence; the deterministic protection
against a future cold burst is the committed request-order regression.

No real filing, fee, payment, provider mutation, client message, or other legal
effect was created by this remediation or its production verification.
