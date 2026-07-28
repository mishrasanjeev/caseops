# CaseOps Full E2E Test Report

Date: 2026-07-09 IST
Production build tested: `1aef504`

## Executive Summary

Production `main` is deployed and serving `100%` traffic on both Cloud Run services:

- API: `caseops-api-00196-jvp`, image `caseops-api:1aef504`
- Web: `caseops-web-00175-p4x`, image `caseops-web:1aef504`

Result: functional, regression, accessibility, mobile, dependency, secret-scan, and production smoke/Notice checks passed. One production regression suite probe initially returned a transient `503`; the same test passed on rerun. One hardcoded historical QA stress matter is not visible to the provided `legal` tenant, so I ran an equivalent visible-tenant stress probe, which passed with status `200` in `30.3s`.

## Coverage Inventory

Functional areas covered:

- Public marketing, segment pages, guide, SEO, robots, sitemap, OG image, demo request.
- Authentication, bootstrap/new workspace, sign-in, sign-out, expired session redirect, password setup/reset states.
- App shell, top-level navigation, role-gated admin visibility.
- Dashboard, Today cockpit, portfolio, mobile navigation.
- Matters list, create/edit, status changes, matter code validation, conflict checks, activation gate.
- Matter cockpit tabs: overview, documents, hearings, drafts, billing, audit, communications, timeline, tasks, recommendations, statutes, knowledge graph, litigation intelligence, predictive intelligence, outside counsel, notices.
- Notice module: received notices, sent notices, metadata, file upload, reply upload, reply status, child documents, filters, production upload.
- Drafting studio, template grid, draft lifecycle, appeal strength, bench context, filing bundle, PDF/DOCX export guards.
- Research, saved research, contextual/keyword search, garbled OCR suppression, citation grounding.
- Recommendations, authority recommendation generation, conflict-check recommendation flows, HNSW/stress endpoint behavior.
- Courts, judges, cause lists, court orders, case tracking, statutes and statute references.
- Clients, intake queue, contracts, outside counsel portal, portal invite/access, client portal.
- Calendar/hearings, Outlook/Google fallback states, reminders, .ics/mobile calendar behavior.
- Matter billing, invoices, payment-link gating, receipts, admin billing, platform billing readiness.
- Admin: teams, employees, roles, email templates, inbound email, integrations, Microsoft 365, provider operations, judge aliases, notifications, matter billing.
- Platform admin: provider events, integrations, paid production, costs, profit.
- Nonfunctional: production build, route generation, mobile 360px layout, axe serious/critical accessibility checks, API response time stress probe.
- Security: CSRF, cookie auth, bearer fallback, tenant isolation, role guards, rate limiting, webhook signatures, SendGrid webhook fail-closed behavior, file/CSV hardening, virus scan behavior, password policy, session revocation, ethical walls, AI/storage quota controls, dependency audit, secret scan, production headers.

## Local Automated Results

| Area | Result |
|---|---:|
| API lint (`ruff`) | Passed |
| Backend pytest collection | `1,993` tests collected |
| Backend pytest sharded execution | `1,965 passed`, `28 skipped`, `0 failed` |
| Web Vitest | `469 passed`, `109 files passed` |
| Web typecheck | Passed |
| Web production build | Passed, `62` static pages generated |
| Local Playwright app suite | `110 passed`, `1 skipped`, `1 initial SEO env failure` |
| Local failed SEO rerun after production-site-env rebuild | Passed |

Note: The monolithic backend pytest run exceeded the 20-minute timeout. I split the same collected suite by module; every collected file completed successfully in shards.

Local Playwright note: the initial local marketing failure was a build-environment issue, not a page flow failure. The prebuilt `.next` metadata used local `.env.local` canonical URL. Rebuilding with `NEXT_PUBLIC_SITE_URL=https://caseops.ai` and `NEXT_PUBLIC_APP_URL=https://caseops.ai/app` made the failed assertion pass.

## Production E2E Results

| Suite | Result |
|---|---:|
| Production smoke (`playwright.smoke.config.ts`) | `10 passed` |
| Production Notice module (`playwright.notice-prod.config.ts`) | `2 passed` |
| Broader production regression (`playwright.prod-ram.config.ts`) | `39 passed`, `4 skipped`, `2 initial failures` |
| Rerun: citation-grounding 422 rate probe | Passed |
| Equivalent visible-tenant HNSW/recommendations stress probe | Passed: `200` in `30,312ms` |

Production Notice details:

- Created a production test matter.
- Uploaded received notice attachment.
- Added metadata: type, department, subject, authority, internal SPOC, dates, mode, source, amount, summary, response plan.
- Uploaded reply document.
- Verified reply status changed to `Reply Sent`.
- Uploaded sent notice attachment.
- Verified sent notice metadata and counsel.
- Filtered received notices by query and reply status.

Production smoke details:

- Disposable tenant bootstrap and sign-in.
- Calendar tabs and `.ics` link.
- Clients list.
- Saved research.
- Admin email templates.
- CSRF cookie/header round trip.
- Dashboard mobile layout.
- Portal sign-in and no-token verify page.
- Authenticated and public mobile + axe accessibility sweeps.

## Security Results

| Check | Result |
|---|---:|
| `npm audit --audit-level=high` | `0 vulnerabilities` |
| `pip-audit` against API venv | No known vulnerabilities found |
| `gitleaks detect --config .gitleaks.toml --no-git --redact` | No leaks found |
| Focused backend security tests | `100 passed` |
| Additional governance/security tests | `61 passed` |
| Production web headers | HSTS, CSP, frame deny, nosniff, referrer policy, permissions policy present |
| Production API health | `GET /api/health` returned `200 {"status":"ok"}` |

Secret-scan note: `gitleaks` skipped `apps/api/.pytest_cache` due local permission denial; committed source and working tree scan completed with no leaks found.

## Nonfunctional Results

- Production Cloud Run web/API revisions are ready and serving `100%` traffic.
- Web production build completed successfully.
- Local and production mobile sweeps covered 360px/Pixel 5 shapes.
- Axe accessibility checks found zero serious/critical blockers in the exercised public/authenticated surfaces.
- Production recommendations stress probe returned `200` in `30.3s`, under the `<110s` HNSW/prefilter threshold.
- Production smoke completed in `37.3s`; production Notice completed in `10.1s`.

## Observations

1. The initial production citation-grounding probe returned `503` once, then passed on rerun. This should be treated as transient production/provider reliability noise, but it is worth tracking if it recurs.
2. The historical stress-matter production spec hardcodes matter `31f0577f-ea2e-4033-b16b-d04e16b13729`, which is not visible in the provided `legal` tenant and returned `404`. I validated the same endpoint behavior with a newly created rich matter in the visible tenant; it passed.
3. Local Playwright on this Windows shell sometimes leaves its web-server lifecycle hanging until the outer timeout even after tests finish. No leftover API/web process remained after checks.
4. `HEAD /api/health` returns `405`; `GET /api/health` is the supported health method and returns `200`.

## Final Verdict

The deployed `main` build passed the available full functional, nonfunctional, security, local regression, production smoke, and production Notice verification coverage. No open product-blocking failure remains from this run.
