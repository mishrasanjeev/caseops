# Local E2E User Guide and QA Automation

Date: 2026-06-30

This guide is the operating contract for local functional QA on a developer or tester workstation. The goal is to make product verification executable, repeatable, and evidence-based instead of relying on manual click-through notes.

## What The Local Suite Proves

The local app E2E suite runs the product as a user sees it:

- API runs from `apps/api` against an isolated SQLite E2E database.
- Web runs from the production Next.js build on `127.0.0.1:3100`.
- Playwright drives Chromium through sign-in, navigation, data creation, uploads, billing, hearings, portals, mobile layouts, and historical bug regressions.
- Test data is created inside each test by API bootstrap or UI flows. The E2E database and `.e2e` runtime folders are reset by the full-suite Playwright global setup or by the focused functional QA runner.

## Workstation Prerequisites

Run from the repository root:

```powershell
npm ci
npm run build:web
npm run test:e2e:app
```

If only the focused functional QA spine is needed:

```powershell
npm run test:e2e:functional-qa
```

`npm run test:e2e:functional-qa` is self-contained: it prepares the local E2E database, builds the web app, starts API and Next on `127.0.0.1`, runs Playwright, and tears both server processes down. The full `test:e2e:app` command uses `playwright.app.config.ts` and expects `npm run build:web` to have been run first.

Do not keep a separate local API on port `8000` or web server on `3100` while running either suite.

## Local Data Lifecycle

The app suite uses:

- Database: `caseops-e2e.db`
- Runtime files: `.e2e/`
- Upload fixtures: `.e2e/uploads/`
- Document storage: `.e2e/documents/`

These are disposable. The suite removes and recreates them at the start of every app E2E run.

The focused runner uses `scripts/run-functional-qa-e2e.mjs`; the full app suite uses `tests/e2e/global-setup.ts`. Both target the same disposable paths.

## Functional User Guide

### 1. Workspace And Sign-In

Users start at `/sign-in`, either joining an existing workspace or creating a new one. Automated coverage checks invalid input, workspace bootstrap, owner sign-in, session persistence, and sign-out redirection.

Primary automated tests:

- `tests/e2e/app-spine.spec.ts`
- `tests/e2e/bootstrap-and-upload.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/m2-polish.spec.ts`

### 2. Home, Today, And Portfolio

The owner lands on `/app`, sees portfolio KPIs, and can move to Today and Portfolio views. Today is a separate operational cockpit for hearings, tasks, drafts, invoices, and deadlines.

Primary automated tests:

- `tests/e2e/app-spine.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/pg-004-today-cockpit-2026-05-01-prod.spec.ts`

### 3. Matter Creation And Case Tracking

Users create matters from `/app/matters`. When case identity is provided, the matter must auto-link to case tracking so court updates are not missed.

Primary automated tests:

- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/hari-2026-06-30-bugs.spec.ts`
- `apps/api/tests/test_case_tracking.py`

### 4. Matter Cockpit

The matter cockpit is the operational center for summary, hearings, documents, billing, communications, drafts, strategy, tasks, timeline, audit, case intelligence, and outside counsel.

Primary automated tests:

- `tests/e2e/app-spine.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/matter-hearings.spec.ts`
- `tests/e2e/bootstrap-and-upload.spec.ts`
- `tests/e2e/billing-payment.spec.ts`
- `tests/e2e/matter-outside-counsel.spec.ts`

### 5. Documents And Matter File QA

Users upload matter documents, see them persist after reload, and can use indexed documents for downstream document intelligence.

Primary automated tests:

- `tests/e2e/bootstrap-and-upload.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/hari-2026-05-11-bugs.spec.ts`
- `tests/e2e/hari-2026-06-08-bugs.spec.ts`

### 6. Hearings, Calendar, Cause List, And Reminders

Users schedule hearings, see them in matter and portfolio contexts, use calendar surfaces, and work with cause-list previews and reminder configuration.

Primary automated tests:

- `tests/e2e/matter-hearings.spec.ts`
- `tests/e2e/hari-ii-bugs.spec.ts`
- `tests/e2e/hari-2026-06-08-bugs.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`

### 7. Research, Statutes, Recommendations, And Drafting

Users run grounded research, browse statutes, draft documents, and view recommendation surfaces with guarded empty states when no source-backed results exist.

Primary automated tests:

- `tests/e2e/research.spec.ts`
- `tests/e2e/drafting.spec.ts`
- `tests/e2e/baad-appeal.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/hari-2026-06-26-bugs.spec.ts`
- `tests/e2e/hari-2026-06-27-bugs.spec.ts`
- `tests/e2e/hari-2026-06-29-bugs.spec.ts`

### 8. Intake, Clients, Contracts, And Outside Counsel

Users triage intake, promote requests to matters, manage clients, work with contracts, and manage outside counsel panels and matter assignments.

Primary automated tests:

- `tests/e2e/intake.spec.ts`
- `tests/e2e/contracts-detail.spec.ts`
- `tests/e2e/matter-outside-counsel.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`

### 9. Billing

Users configure billing, create matter invoices, view usage, and verify provider-gated payment link behavior only when credentials are intentionally configured.

Primary automated tests:

- `tests/e2e/billing-payment.spec.ts`
- `tests/e2e/hari-2026-06-08-bugs.spec.ts`
- `tests/e2e/hari-2026-06-09-bugs.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`

### 10. Admin And Governance

Workspace admins manage employees, roles, teams, notifications, integrations, billing, inbound email, provider operations, and storage governance. Member users must not see admin-only controls.

Primary automated tests:

- `tests/e2e/app-spine.spec.ts`
- `tests/e2e/teams-admin.spec.ts`
- `tests/e2e/functional-qa-regression.spec.ts`
- `tests/e2e/hari-2026-05-09-bugs.spec.ts`
- `tests/e2e/hari-2026-05-11-bugs.spec.ts`

### 11. Portals And External Users

Client and outside-counsel portal access is invite scoped and must land users on their allowed matter surfaces only.

Primary automated tests:

- `tests/e2e/portal-invite-access.spec.ts`
- `tests/e2e/oc-portal.spec.ts`

### 12. Responsive And Accessibility

Mobile-specific tests run in the `app-mobile` Playwright project. Accessibility tests use axe-core for serious and critical violation checks.

Primary automated tests:

- `tests/e2e/mobile-responsive.spec.ts`
- `tests/e2e/a11y.spec.ts`

## Automated QA Test Cases

| ID | Workflow | Automated actions | Expected result | Automation |
| --- | --- | --- | --- | --- |
| FQA-001 | Workspace bootstrap | Create a unique law-firm tenant and owner through the bootstrap API | Tenant, owner, and access token are created without manual seed data | `functional-qa-regression.spec.ts` |
| FQA-002 | Owner sign-in | Enter company slug, owner email, and password on `/sign-in` | User lands on `/app` and sees the authenticated home heading | `functional-qa-regression.spec.ts`, `app-spine.spec.ts` |
| FQA-003 | Matter creation | Create a litigation matter from the Matters UI with code, parties, case number, and CNR | Dialog closes, matter appears in the portfolio, and matter detail routes are reachable | `functional-qa-regression.spec.ts` |
| FQA-004 | Case tracking auto-link | Poll case-tracking bookmarks after matter creation | Bookmark exists with normalized CNR, case number, and Delhi High Court | `functional-qa-regression.spec.ts`, `hari-2026-06-30-bugs.spec.ts` |
| FQA-005 | Primary navigation | Visit home, today, matters, calendar, hearings, cause list, clients, contracts, courts, drafting, drive, intake, mailbox, outside counsel, portfolio, recommendations, research, saved research, statutes, and admin routes | Every page returns HTTP < 400 and renders its expected heading or empty state | `functional-qa-regression.spec.ts` |
| FQA-006 | Admin governance | Visit billing, usage, email templates, employees, inbound email, integrations, matter billing, Microsoft 365, notifications, Outlook, provider operations, roles, and teams | Admin pages render without 5xx responses or missing shell UI | `functional-qa-regression.spec.ts`, `teams-admin.spec.ts` |
| FQA-007 | Platform admin guard | Visit `/app/platform-admin` as a workspace owner | Page renders access denied or a guarded platform-admin state, not a crash | `functional-qa-regression.spec.ts` |
| FQA-008 | Hearing scheduling | Open the matter hearings tab and schedule a future hearing | Dialog submits, closes, and scheduled hearing text appears | `functional-qa-regression.spec.ts`, `matter-hearings.spec.ts` |
| FQA-009 | Document upload | Upload a text fixture to the matter documents tab | Uploaded filename appears on the matter document surface | `functional-qa-regression.spec.ts`, `bootstrap-and-upload.spec.ts` |
| FQA-010 | Matter cockpit surfaces | Visit billing, communications, drafts, knowledge graph, litigation intelligence, outside counsel, predictive intelligence, recommendations, statutes, strategy, tasks, timeline, and audit | Each route renders its expected functional or policy-disabled state | `functional-qa-regression.spec.ts` |
| FQA-011 | Predictive-intelligence policy guard | Visit predictive intelligence in a default local tenant | Page shows source-backed signals when enabled or a controlled disabled-policy state | `functional-qa-regression.spec.ts` |
| FQA-012 | Connector health concurrency | Hit integrations and integrations health concurrently | No 500 responses and no duplicate provider/account health records | `test_connector_automation_readiness.py` |
| FQA-013 | Billing | Open billing and usage surfaces | Billing setup, invoices, usage, and spend pages render | `functional-qa-regression.spec.ts`, `billing-payment.spec.ts` |
| FQA-014 | Intake | Open intake queue and promote intake where applicable | Intake queue renders and promotion regressions remain covered | `functional-qa-regression.spec.ts`, `intake.spec.ts` |
| FQA-015 | Research and saved research | Open research and saved research | Research shell and saved results/empty state render without API crashes | `functional-qa-regression.spec.ts`, `research.spec.ts` |
| FQA-016 | Drafting | Open drafting studio globally and inside a matter | Drafting shell renders and deeper draft flows remain covered by drafting specs | `functional-qa-regression.spec.ts`, `drafting.spec.ts` |
| FQA-017 | Outside counsel | Open workspace and matter outside-counsel surfaces | Counsel pages render and matter counsel assignment regressions stay covered | `functional-qa-regression.spec.ts`, `matter-outside-counsel.spec.ts` |
| FQA-018 | Portals | Exercise client and outside-counsel invite flows | Portal users land only on their scoped matter surfaces | `portal-invite-access.spec.ts`, `oc-portal.spec.ts` |
| FQA-019 | Mobile layout | Run mobile project specs | Mobile navigation, dialogs, and critical forms do not overflow or trap actions | `mobile-responsive.spec.ts` |
| FQA-020 | Accessibility | Run axe-backed app/public checks | No serious or critical accessibility violations on covered pages | `a11y.spec.ts` |

## Functional QA Matrix

| Area | User outcome | Required automated proof |
| --- | --- | --- |
| Sign-in and session | Invalid input rejected; owner signs in; logout clears session | `app-spine.spec.ts`, `functional-qa-regression.spec.ts` |
| Workspace bootstrap | New workspace creates tenant and owner | `bootstrap-and-upload.spec.ts` |
| Matter portfolio | Matter list renders; matter creation works | `app-spine.spec.ts`, `functional-qa-regression.spec.ts` |
| eCourt tracking | New matter with CNR/case number auto-creates tracking bookmark | `hari-2026-06-30-bugs.spec.ts`, `functional-qa-regression.spec.ts` |
| Matter cockpit tabs | Summary, documents, billing, recommendations, audit render | `app-spine.spec.ts`, `functional-qa-regression.spec.ts` |
| Hearings | Hearing can be scheduled and appears in upcoming list | `matter-hearings.spec.ts`, `functional-qa-regression.spec.ts` |
| Documents | Upload persists and surfaces in document list | `bootstrap-and-upload.spec.ts`, `functional-qa-regression.spec.ts` |
| Billing | Invoice UI renders and invoice rows surface | `billing-payment.spec.ts` |
| Intake | Intake request promotes to matter | `intake.spec.ts` |
| Research | Query returns cards or explicit empty state | `research.spec.ts` |
| Drafting | Draft generation/review/finalization flow remains wired | `drafting.spec.ts` |
| Contracts | Contract list and detail tabs render | `contracts-detail.spec.ts` |
| Outside counsel | Workspace and matter counsel surfaces render | `matter-outside-counsel.spec.ts` |
| Admin governance | Roles, teams, employees, integrations, billing, provider ops render | `app-spine.spec.ts`, `teams-admin.spec.ts`, `functional-qa-regression.spec.ts` |
| Integration health race | Concurrent integrations reads do not return 500 or duplicate health records | `test_connector_automation_readiness.py`, `functional-qa-regression.spec.ts` |
| Portal access | Client and OC invite scopes work | `portal-invite-access.spec.ts`, `oc-portal.spec.ts` |
| Mobile | Mobile dialogs/nav do not overflow or trap actions | `mobile-responsive.spec.ts` |
| Accessibility | Key public and authenticated pages have no serious/critical axe findings | `a11y.spec.ts` |

## Release Gate

A functional change should not be called fixed until these pass locally or in CI:

```powershell
npm run build:web
npm run test:e2e:app
```

For high-risk fixes, also run the closest focused tests by filename. Example:

```powershell
apps\api\.venv\Scripts\pytest.exe apps\api\tests\test_connector_automation_readiness.py
npm run test:e2e:functional-qa
npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-30-bugs.spec.ts --project app-chromium
```

## Failure Handling

When a test fails:

1. Open the Playwright trace from `test-results/`.
2. Identify the broken user outcome, not just the selector that failed.
3. Fix the underlying product behavior or test data contract.
4. Add a regression assertion to the closest functional spec.
5. Re-run the focused test and then the app suite.

Selectors may be adjusted only when the user-visible behavior is already correct and the test is stale. A missing page heading, missing empty state, 5xx response, or failed state transition is a product failure until proven otherwise.
