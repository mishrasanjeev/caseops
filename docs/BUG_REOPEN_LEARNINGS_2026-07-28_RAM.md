# Ram 2026-07-28 Audit: Product Boundary and Deployed Lifecycle Drift

## Scope

Source workbook: `C:\Users\mishr\Downloads\Enhancements_Ram28Jul2026.xlsx`.

The three supplied rows describe Edumatica modules (`Physical Library`,
`Student Due Management`, and `Degree Course / Degree Program`) and an
Edumatica test URL. Those modules and that product are not present in the
CaseOps repository. They are valid-looking Edumatica work items, but they are
not actionable CaseOps bugs or enhancements. No unrelated CaseOps code was
changed to pretend otherwise.

## Brutal reopen audit

The current CaseOps branch already contains the intended lifecycle controls:

- only the dedicated lifecycle endpoint may dispose or reopen a Matter;
- generic Matter PATCH requires an `expected_updated_at` token and rejects
  terminal/inactive rows;
- disposal and reopening update `status`, `is_active`, and
  `lifecycle_version` together;
- reopening lands in `intake`, neutralizes legacy operational children, and
  requires a fresh conflict check before activation;
- the opening gate rejects a check whose lifecycle version is stale or whose
  timestamp predates the latest reopen audit event.

Local evidence passed all of those boundaries. The deployed production replay
on 2026-07-28 did not: after a real production dispose and reopen, the exact
pre-reopen conflict clearance was accepted and the Matter returned to
`active` with HTTP 200 instead of the expected HTTP 409.

That is why cases appeared to reopen again. The prior closure evidence proved
the local candidate, but the deployed surface was not running the same
behavior. A local green test cannot substitute for a deployed-commit proof.
The production build identity was not exposed by `/api/health`, so the exact
deployed commit could not be proven from the surface.

## Evidence

- Local Playwright: `tests/e2e/ram-2026-07-15-bugs.spec.ts`, 3/3 passed.
- Local API: lifecycle stale-clearance and notice filter tests, 2/2 passed.
- Local web: `app/app/notices/page.test.tsx`, 16/16 passed.
- Production Playwright: `tests/e2e/ram-2026-07-15-prod.spec.ts`, first replay
  passed creation defaults and the notice workflow, but the lifecycle test
  failed at the pre-reopen clearance assertion because production returned
  HTTP 200 instead of HTTP 409.
- The first production replay also showed a notice filter empty state. A
  second full replay passed that notice workflow, and a direct authenticated
  production API probe returned the newly-created notice for the combined
  search/status/owner filter. That observation is therefore not promoted to
  a confirmed product bug; it remains an inconclusive flake to monitor.
- The in-app browser connector was unavailable (`No browser is available`).
  Standalone Playwright was used for local and production probes.

## Permanent rules

1. Confirm the workbook's product, URL, and module vocabulary matches the
   repository before changing code. External-product rows are classified as
   out of scope, not shallowly implemented in the wrong product.
2. For lifecycle fixes, the minimum end-user proof is: dispose, reload,
   reject stale metadata writes, hide operational work, reopen to Intake,
   reject pre-reopen conflict clearance, run a fresh check, and only then
   activate.
3. A dated production spec that fails is a finding, not a release sign-off.
   The verdict remains `Inconclusive` until the candidate is deployed and the
   same spec passes against a provable build identity.
4. Production verification must record the account, environment, target
   commit/build identity, exact spec, and any cleanup caveat. `/api/health`
   returning `ok` is availability evidence only, not release identity.
5. Retain the local regression even when production is stale; it protects the
   intended fix from future reopens while deployment drift is repaired.

## CaseOps workbook BUG-001: Judge Aliases navigation

The second 2026-07-28 workbook was a real CaseOps row, unlike the earlier
Edumatica workbook. `BUG-001` was valid: the Judge Aliases API, page, and Admin
landing-page action existed, but the shared `apps/web/components/app/Sidebar.tsx`
navigation registry omitted `/app/admin/judge-aliases`. Because the mobile drawer
renders the same `SidebarBody`, the omission affected both desktop and mobile.

The complete fix added one capability-gated navigation item and a dated
Playwright regression that clicks the link, loads the page, and repeats the
journey at 360px. The local and deployed production specs both passed on
candidate `7495bc6`; the web image was serving 100% traffic as
`caseops-web-00191-vn9` when the production proof passed.

The requested full API/web deployment was correctly stopped by the migration
gate: production's `alembic_version` references `20260723_0001`, but that
revision file is absent from the repository image. The web-only BUG-001 rollout
was safe because it changes no API contract; the API image was not promoted.
This is a release-lineage blocker, not a reason to bypass migrations.

Permanent additions:

- Navigation bugs must start at the real shared registry and cover desktop,
  mobile, capability filtering, destination URL, and rendered destination state.
- Every deployed fix must record the exact image/revision and rerun the same
  dated production Playwright spec; local green is never enough.
- Release automation must fail closed when production's migration head is not
  present in the candidate image. Repair migration lineage before the next API
  rollout; do not stamp over the production revision or skip the migration job.
