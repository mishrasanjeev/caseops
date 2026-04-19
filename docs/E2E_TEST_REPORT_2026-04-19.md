# CaseOps End-to-End Test Report

Date: 2026-04-19
Workspace: `C:\Users\mishr\caseops`
Tester: Codex
Scope: Full local product pass across public web, authenticated app shell, API, unit/integration suites, and route-level UX completeness checks.

## Executive Verdict

The public marketing site is in good shape.

The authenticated product is not end-to-end ready. The dominant blocker is a production-mode auth handoff failure: both `Sign in` and `New workspace` flows stay on `/sign-in` instead of reaching `/app`. That single defect prevents honest browser validation of the core product journeys behind auth.

The backend is materially stronger than the browser UX signal suggests: the API suite is broad and passed cleanly once filesystem sandbox noise was removed. The problem right now is not "nothing works"; it is "the main browser entry path to the product is broken in production-mode E2E."

## Method

I used four layers of evidence:

1. Production build and type safety checks.
2. Web unit/component tests.
3. API integration and feature tests.
4. Playwright browser flows for marketing and authenticated app journeys.

I also inspected the shipped route files and test inventory to separate:

- real, executed browser coverage
- backend-only confidence
- UI surfaces that are still explicitly partial or roadmap-only

## Commands Run

| Command | Result | Notes |
| --- | --- | --- |
| `npm run build:web` | Passed | Initial sandboxed attempt failed because Google Fonts had to be fetched over network. |
| `npm run typecheck:web` | Passed | Route types regenerated cleanly. |
| `npm test` in `apps/web` | Passed | `13 files`, `46 tests` passed. |
| `python -m pytest --basetemp=.pytest-tmp -p no:cacheprovider` in `apps/api` | Passed | `352 passed`, `4 skipped`, `3 warnings`. Required elevated run to avoid Windows temp/sandbox noise. |
| `npm run test:e2e:marketing` | Passed | `8/8` Playwright marketing tests passed. |
| `npm run test:e2e:app` | Failed / timed out | Blocked by auth handoff failure and brittle E2E environment startup. |

## Coverage Status

| Area | Status | Evidence |
| --- | --- | --- |
| Marketing site | Pass | Full Playwright marketing suite passed. |
| SEO / robots / sitemap / OG image | Pass | Covered by `marketing.spec.ts`. |
| Demo request form | Pass | Browser submit path passed. |
| `/legacy` redirects | Pass | Both `/legacy` and `/legacy/*` redirect tests passed. |
| Browser auth entry (`/sign-in`) | Fail | Login and new-workspace handoff never reached `/app`. |
| Authenticated app shell | Blocked | App E2E failures stop before real workflow execution. |
| Matters / documents / drafting / personas / courts / outside counsel / query recovery in browser | Blocked by auth | Specs exist, but failed before entering the app. |
| API feature surface | Pass | Broad backend suite passed end to end. |
| Admin / governance completeness | Partial | Visible roadmap stub still present in shipped UI. |

## Critical Findings

### P0: Authenticated product is unreachable in production-mode browser E2E

Severity: Release blocker

Observed behavior:

- `tests/e2e/app-spine.spec.ts`
- `tests/e2e/a11y.spec.ts` authenticated-shell case
- `tests/e2e/personas.spec.ts`
- `tests/e2e/drafting.spec.ts`
- `tests/e2e/bootstrap-and-upload.spec.ts`
- `tests/e2e/m2-polish.spec.ts` authenticated cases

all stall on the same transition: submit auth form, then wait for `/app`, but the page remains on `/sign-in` until timeout.

Representative failure shape:

- `page.waitForURL("**/app")` or `page.waitForURL(/\/app/)` times out
- final DOM snapshot is still the sign-in page
- this affects both existing-user login and brand-new workspace bootstrap

Impact:

- real browser validation for Matter OS, drafting, documents, query-error recovery, persona-specific onboarding, courts, and polish flows is effectively zero right now
- a user can reach the marketing site, but cannot be proven to enter the actual product

Most likely shared fault domain:

- [apps/web/app/sign-in/SignInForm.tsx](../apps/web/app/sign-in/SignInForm.tsx)
- [apps/web/app/sign-in/NewWorkspaceForm.tsx](../apps/web/app/sign-in/NewWorkspaceForm.tsx)

Both success paths do the same thing:

- parse auth session
- `storeSession(session)`
- `router.replace("/app")` or `router.replace(nextPath)`

This means the defect is likely in one of these shared layers:

- frontend session persistence / hydration
- client-side navigation after auth in production build
- client-side parsing or handling of the auth response

The backend auth endpoints themselves are not the primary suspect because the API suite covering bootstrap and login passed.

### P0: Core browser E2E suite is not stable enough for release gating

Severity: Release blocker

Observed behavior:

- Playwright global setup initially failed because `uv` tried to refresh the local venv while a repo-local `caseops-backfill-corpus-quality.exe` process still held a file lock
- the app suite later timed out after ~30 minutes and left stale Next/Uvicorn/background worker processes behind

Impact:

- CI confidence is overstated if the main app E2E suite is this easy to deadlock or poison with leftover local processes
- release gating cannot rely on this suite until startup, teardown, and temp-dir behavior are deterministic

Evidence points:

- `tests/e2e/global-setup.ts`
- `playwright.app.config.ts`
- lingering repo-local worker processes under `apps/api/.venv/Scripts`

### P1: Production build is not hermetic because it fetches Google Fonts at build time

Severity: High

Observed behavior:

- the first `npm run build:web` attempt failed in restricted mode because Next tried to fetch:
  - `Atkinson Hyperlegible`
  - `JetBrains Mono`
  - `Libre Caslon Text`

Impact:

- build reliability depends on outbound network and Google Fonts availability
- this is fragile for CI, locked-down enterprise environments, and disaster recovery scenarios

Implication:

- the app is not fully self-contained at build time

### P1: Backend quality is much stronger than frontend entry reliability

Severity: High

Observed behavior:

- backend suite passed `352/356` tests with `4 skipped`
- the test inventory covers auth, matters, contracts, outside counsel, drafting, recommendations, ethical walls, teams, audit export, evaluation, court sync, OCR, pagination, webhook security, and tenant isolation

Impact:

- there is meaningful product depth in the backend
- the browser layer is currently the bottleneck preventing that depth from being experienced end to end

This is good news technically, but bad news operationally: the release risk is concentrated in the product entry point and browser integration path.

## Medium-Severity Product / UX Gaps

### P2: Admin surface is explicitly incomplete in shipped UI

Severity: Medium

Observed behavior:

- [apps/web/app/app/admin/page.tsx](../apps/web/app/app/admin/page.tsx) ships a live audit export card
- the same page also renders a `RoadmapStub` for:
  - user directory + ethical walls UI
  - SSO
  - tenant AI policy controls
  - plan entitlements

Impact:

- the route exists, but the overall admin/governance experience is not complete
- enterprise-readiness claims would be overstated if this route is presented as fully shipped

### P2: Sidebar copy implies preview badges that are not actually used

Severity: Medium

Observed behavior:

- [apps/web/components/app/Sidebar.tsx](../apps/web/components/app/Sidebar.tsx) says "Items marked preview are next up on the roadmap."
- none of the current nav items set `placeholder: true`, so no visible preview chips are rendered

Impact:

- this is small, but it is misleading UI copy
- it makes the navigation feel less intentional than it should

## What Passed Cleanly

### Public site

- landing page rendered correctly
- FAQ accordion behavior worked
- `robots.txt` and `sitemap.xml` served correctly
- Open Graph image endpoint returned a PNG
- demo request API validation worked
- landing-page demo form submission worked
- `/legacy` redirects worked

### Web component / route tests

- `46/46` web tests passed
- this includes sign-in/new-workspace form validation behavior, dialog validation, query error states, document page actions, and core reusable UI components

### Backend

- the API suite passed across the core domain areas
- tenant isolation, auth, security, drafting, recommendations, contracts, outside counsel, deadlines, audits, hearings, and evaluations all had passing test coverage

## What I Could Not Honestly Mark as Passed in Browser

Because the auth handoff failed before app entry, I could not honestly certify these browser journeys as working end to end:

- dashboard load after sign-in
- first matter creation from the live app shell
- matter cockpit navigation
- document upload and reindex
- drafting create/generate/review/finalize
- recommendations UX
- outside counsel list/workspace UX
- contracts workspace UX
- courts to court-profile to judge-profile UX
- authenticated accessibility sweep
- persona-specific first-run experience for law firm, GC, and solo
- query-error recovery behavior inside authenticated routes

These are covered indirectly by unit or API tests, but not by a successful browser session in this pass.

## Additional Observations

- The authenticated failure appears in production-style `next start` testing, which is the correct mode to take seriously. This is worse than a dev-only glitch.
- The marketing layer is materially healthier than the app shell.
- The product currently looks much stronger from API test evidence than from browser-entry evidence.
- There is no basis from this pass to call the product fully E2E-ready.

## Release Recommendation

Current recommendation: do not treat the authenticated web app as release-ready.

Required before a credible E2E-ready claim:

1. Fix the shared auth success handoff so both `Sign in` and `New workspace` reliably land on `/app` in production mode.
2. Make the Playwright app suite deterministic on Windows and CI by removing the `uv`/venv lock sensitivity and cleaning server teardown.
3. Re-run the full authenticated Playwright suite and confirm actual post-login workflow coverage passes.
4. Remove or clearly scope partial admin/governance UI if enterprise positioning is being used externally.
5. Make the web build hermetic by self-hosting or vendoring fonts instead of depending on live Google fetches.

## Bottom Line

CaseOps has real product depth and a strong backend test foundation.

But as of this pass, the browser product cannot be signed off as fully working end to end because the production-mode auth entry path is broken, and that defect blocks honest validation of nearly every core in-app feature.
