# CaseOps

**The matter-native legal operating system for Indian law firms and corporate legal teams.**

CaseOps unifies matter management, legal research, AI-assisted drafting, hearing preparation,
tracked case refresh, court-order compliance review, date-wise cause-list PDFs, contract
workflows, outside-counsel management, and India-ready matter billing into one
citation-grounded workspace - with tenant isolation, review-first AI assistance, founder-only
production gates, and audit by default. Autonomous scoped-agent execution is readiness-only
until the agent trust plane is activated.

> Founder-stage monorepo. **Pre-alpha.** The backend foundation (matters, documents,
> contracts, billing, authority ingestion) is working and hardened; the AI core is actively
> landing. See [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) for current status and
> priority.

---

## What's in the box

| Surface | Status | Where |
| --- | --- | --- |
| Marketing site (`/`) | Live | `apps/web/app/page.tsx` |
| Sign in and self-service password reset (`/sign-in`, `/account/forgot-password`, `/account/reset-password`) | Live | `apps/web/app/sign-in/`, `apps/web/app/account/forgot-password/`, `apps/web/app/account/reset-password/` |
| App shell + Matter Cockpit (`/app`) | Live | `apps/web/app/app/` |
| API (auth, matters, contracts, documents, billing, authorities, recommendations, drafting, hearing packs, hearing reminders, outside counsel, clients) | Production, security-hardened | `apps/api/` |
| Document worker | Production (Cloud Run Job) | `apps/api/src/caseops_api/workers/` |
| Hearing reminders worker | Production (Cloud Run Job + Scheduler `*/5 * * * *` Asia/Kolkata, SendGrid sender `hearings@caseops.ai`) | `apps/api/src/caseops_api/scripts/send_hearing_reminders.py` |
| GBA Law Office operations pack: Dispose matter status, tracked-only case refresh, review-first compliance extraction, next-hearing provenance, cause-list PDF generation, India-ready matter billing/invoice PDFs | Implemented (2026-06-07) | [`docs/GBA_LAW_OFFICE_USER_GUIDE_2026-06-07.md`](./docs/GBA_LAW_OFFICE_USER_GUIDE_2026-06-07.md), [`docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md`](./docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md), `/guide` |
| Production readiness, Pine Labs UAT evidence, secret-rotation proof, margin/profit gates, MFA login challenge, enterprise readiness scaffolding | Founder-only / disabled until UAT / planned as labelled | `/app/platform-admin/paid-production`, `/api/platform-admin/production-readiness`, `/api/admin/enterprise-readiness` |
| Mobile responsive | Hamburger nav + responsive forms verified on Pixel-5 viewport | Playwright `app-mobile` project |
| PRD | Stable | [`docs/PRD.md`](./docs/PRD.md) |
| Architecture | Stable | [`docs/architecture.md`](./docs/architecture.md) |
| Work plan | Current | [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) |
| Strict bug ledger | Closed (10/10 Properly fixed) | [`docs/STRICT_BUG_TASKLIST_2026-04-22.md`](./docs/STRICT_BUG_TASKLIST_2026-04-22.md) |
| Drafting studio (31 specialised templates including the SC escalation pack — SLP, supreme-court appeal, review, curative, transfer, contempt, interim relief, condonation of delay, exemption, synopsis / list of dates, filing index — plus court-aware PDF + filing bundle + revision diff + bench-aware drafting + filing checklist + mobile + solo mode + governance + live-LLM eval) | Implemented (PG-005, 12 sprints, 2026-05-01; SC pack 2026-05-03) | [`docs/RELEASE_NOTES_2026-05-01.md`](./docs/RELEASE_NOTES_2026-05-01.md) |
| Litigation Strategy & Escalation Planner (matter-level strategy: current posture, primary + alternative routes, forum sequence up to Supreme Court, recommended draft pack with one-click generation, limitation flags, missing facts, risks, authorities, lawyer-review workflow) | Implemented (MOD-LSE, 2026-05-03) | [`docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md`](./docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md) |

---

## User documentation

- Deployed user guide: `/guide` on the web app.
- Detailed GBA Law Office guide: [`docs/GBA_LAW_OFFICE_USER_GUIDE_2026-06-07.md`](./docs/GBA_LAW_OFFICE_USER_GUIDE_2026-06-07.md).
- Source PRD: [`docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md`](./docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md).
- Machine-readable public summaries: `/llms.txt` and `/llms-full.txt`.

---

## Readiness status labels

Public product claims use these labels: `live`, `review-first`, `provider-gated`,
`founder-only`, `disabled until UAT`, or `planned`.

- Pine Labs production payments are `disabled until UAT`; internal evidence, webhook, settlement,
  refund, chargeback, GST/TDS, idempotency, and founder go/no-go scaffolding exists, but live
  payment activation remains blocked.
- Google Workspace, Microsoft 365, inbound email, SMS/WhatsApp, and court-provider automation are
  `provider-gated` where external credentials, admin consent, webhook signing, or legal source
  proof is missing.
- OIDC/SAML SSO, SCIM, private enterprise deployment, and autonomous scoped-agent execution are
  `planned` or readiness-only until UAT, approval, and audit evidence are complete.
- Platform profit, provider cost, secret rotation, and production signoff surfaces are
  `founder-only` and must not be exposed to tenants.

## Documentation changelog - 2026-06-13

- Added founder-only production readiness gates for billing, Pine Labs, provider operations,
  finance/margin, backup/restore, docs, security, and historical connector secret rotation proof.
- Kept Pine Labs live payments disabled while expanding UAT evidence coverage for checkout,
  links, subscriptions, webhooks, settlement, refunds, credit notes, chargebacks, GST/TDS, and
  founder activation decisions.
- Updated billing/profitability readiness: platform-admin reports include revenue, costs, margin,
  credits, add-ons, refunds, chargebacks, settlement exceptions, TDS/GST, and loss-making warnings;
  tenant billing stays cost/profit-blind.
- Hardened MFA/password reset documentation around login challenge, QR provisioning, recovery
  codes, step-up for sensitive actions, and anti-enumeration reset flows.
- Reclassified GBA Law Office, connector readiness, provider operations, public guide, and
  machine-readable docs using `live`, `review-first`, `provider-gated`, `founder-only`,
  `disabled until UAT`, and `planned`.

---

## Monorepo layout

```
caseops/
├── apps/
│   ├── api/            FastAPI backend, Alembic migrations, document worker
│   └── web/            Next.js 16 + React 19 + Tailwind v4 frontend
├── docs/               PRD, architecture, work plan
├── infra/              Cloud Run manifests and deploy helpers
├── tests/              Playwright end-to-end tests
└── docker-compose.yml  Local multi-service dev stack
```

---

## Technology

- **Web** — Next.js 16, React 19, TypeScript 6, Tailwind CSS v4, Radix primitives, TanStack
  Query + Table, React Hook Form + Zod, Sonner toasts, Lucide icons.
- **API** — Python 3.13, FastAPI, Pydantic, SQLAlchemy 2, Alembic, slowapi rate limiter.
- **AI** — `LLMProvider` abstraction with Mock / Anthropic / Google Gemini backends; pluggable
  embeddings provider. Gemini hosted for founder stage; architecture preserves a swap to
  self-hosted Gemma 4 for enterprise tenants that need private inference.
- **Data** — PostgreSQL 17 with `pgvector`, Valkey cache, GCS (or local FS) for documents.
- **Workflow** — custom polling worker today; Temporal is the declared target (work plan §5.1).
- **Payments** — Pine Labs production payments are disabled until UAT and founder go/no-go.
  HMAC webhook verification, idempotency, settlement/refund/dispute evidence, and cross-tenant
  guards are present for readiness and safe testing.
- **Matter billing** - separate from CaseOps SaaS subscription billing; supports firm/client
  billing fields, rates, fixed fees, milestones, GST split fields, TDS adjustments, double
  billing prevention, and server-rendered invoice PDFs.
- **Deployment** — Cloud Run + Cloud SQL + GCS for founder stage; GKE + private networking +
  dedicated inference preserved as the enterprise path.
- **Tests** — pytest (unit + integration), Playwright (marketing + app spine + legacy).

Dependency policy: latest stable production-ready versions only; no betas, no intentional
pins to older majors without a documented blocker. See [`CLAUDE.md`](./CLAUDE.md).

---

## Quickstart

### Prerequisites

- Node.js 22+ and npm 10+
- Python 3.13 and [`uv`](https://github.com/astral-sh/uv)
- Docker (for Postgres 17 + `pgvector` and Valkey)

### 1) Install dependencies

```bash
# JS workspace deps
npm install

# Python deps for the API
cd apps/api && uv sync && cd ../..
```

### 2) Run the stack locally

Option A — full Docker stack (recommended):

```bash
docker compose up --build
```

Starts `web` (port 3000), `api` (port 8000), `worker`, `postgres` (5432), `valkey` (6379).

CaseOps local runtime is Postgres-first. SQLite is only a test fallback and should not be
used for seeded corpora or normal development.

Optional local Temporal dev server for developer runtime checks:

```bash
docker compose -f docker-compose.yml -f docker-compose.temporal.yml up -d temporal
```

This starts a local-only Temporal development server with gRPC on
`localhost:7233` and Temporal Web UI on `http://localhost:8233`. This is not
the operator-owned WTD-5.1c proof and does not mark durable automation ready.
Host-run no-op worker config checks can use:

```bash
CASEOPS_DURABLE_WORKFLOWS_ENABLED=true \
CASEOPS_DURABLE_WORKFLOWS_BACKEND=temporal \
CASEOPS_TEMPORAL_ADDRESS=localhost:7233 \
CASEOPS_TEMPORAL_NAMESPACE=default \
CASEOPS_TEMPORAL_TASK_QUEUE_NOTIFICATIONS=caseops-notification-workflows \
uv --directory apps/api run python -m caseops_api.workers.notification_workflows --check-config --require-available
```

Keep these Temporal proof values out of `apps/api/.env`: the API settings
loader reads that file during `uv --directory apps/api ...` test runs, so
leaving local Temporal values there changes fail-closed test assumptions. Use
inline shell env as above, or keep a gitignored non-auto-loaded snippet such as
`apps/api/.env.temporal.local` and load it explicitly only for this proof
command.

To run the no-op notification workflow worker against the local Temporal dev
server inside Docker:

```bash
docker compose -f docker-compose.yml -f docker-compose.temporal.yml up notification-workflow-worker
```

The local Temporal setup only registers the existing no-op notification runtime
probe. It does not send notifications, schedule reminders, call external
providers, or unblock ADP-20.

Option B — run pieces directly:

```bash
# Terminal 0 — infra only (Postgres + Valkey)
npm run dev:infra

# Terminal 1 — API
npm run dev:api

# Terminal 2 — Web
npm run dev:web

# Terminal 3 — document worker (optional)
cd apps/api && uv run caseops-document-worker
```

### 3) Visit

- Landing page — http://localhost:3000
- Sign in — http://localhost:3000/sign-in
- Forgot password — http://localhost:3000/account/forgot-password
- Workspace (after sign in) — http://localhost:3000/app
- Legacy founder console — http://localhost:3000/legacy
- API docs — http://localhost:8000/docs

---

## Scripts

Run from the repo root.

| Script | What it does |
| --- | --- |
| `npm run dev:infra` | Start local Postgres 17 + pgvector and Valkey via Docker Compose |
| `npm run dev:api` | Start FastAPI with reload |
| `npm run dev:web` | Start the Next.js dev server (Turbopack) |
| `npm run build:web` | Production build of the web app |
| `npm run typecheck:web` | `tsc --noEmit` on the web app |
| `npm run test:api` | pytest suite for the API |
| `npm run lint:api` | ruff lint on the API |
| `npm run test:e2e` | Full legacy Playwright e2e (requires live API + worker + DB) |
| `npm run test:e2e:headed` | Same, in headed mode |
| `npm run test:e2e:marketing` | Marketing suite against a production web build |
| `npm run test:e2e:app` | App shell + matter cockpit suite against a production build |
| `bash scripts/verify-backend.sh [pytest-args]` | **Canonical** backend recipe (bypasses `uv run`'s implicit sync — required on Windows when long-running processes hold a `.venv/Scripts/*.exe` lock). Runs ruff + targeted pytest. |
| `bash scripts/verify-web.sh [--quick] [-g <grep>]` | **Canonical** web recipe — vitest + tsc + (mandatory) `npm run build` + Playwright. The mandatory rebuild prevents stale-bundle false negatives. |

---

## Environment

Create `apps/web/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_APP_URL=http://localhost:3000/app
```

For the API, copy `apps/api/.env.example` and set at minimum `CASEOPS_AUTH_SECRET`,
`CASEOPS_DATABASE_URL`, `CASEOPS_PUBLIC_APP_URL`, Pine Labs credentials (optional), and
LLM provider settings (optional — defaults to the mock provider):

```
CASEOPS_LLM_PROVIDER=mock         # mock | anthropic | gemini
CASEOPS_LLM_MODEL=claude-opus-4-7 # or gemini-2.5-pro, etc.
CASEOPS_LLM_API_KEY=              # required for anthropic / gemini
CASEOPS_MFA_EXISTING_USER_GRACE_DAYS=7
CASEOPS_MFA_STEP_UP_TTL_MINUTES=15
CASEOPS_MFA_MAX_FAILURES_PER_5M=5
CASEOPS_BILLING_COMPANY_GSTIN=09AANCM5923C1ZD
CASEOPS_BILLING_MINIMUM_GROSS_MARGIN_BPS=7000
```

Scheduled tracked-case refresh uses the India window by default:

```bash
CASEOPS_CASE_TRACKING_DAILY_WINDOW_START=16:00
CASEOPS_CASE_TRACKING_DAILY_WINDOW_END=18:00
CASEOPS_CASE_TRACKING_DAILY_TIMEZONE=Asia/Kolkata
```

Production scheduled runs should stay inside the 4 PM-6 PM IST window unless an
operator uses an explicit force/local override. Disabled or misconfigured court
providers must record skipped/blocked state and make no external calls.

> **Security note.** The default `CASEOPS_AUTH_SECRET` is a placeholder and is rejected at
> startup whenever `CASEOPS_ENV` is `staging`, `production`, or `prod`. See
> [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) §2.2.

---

## Testing

- **API unit + integration** — `npm run test:api`. Covers auth, company, matters,
  contracts, documents, authorities, outside counsel, payments, plus the Phase 2 security
  surface (password policy, webhook hardening, rate limiting, session revocation, tenant
  isolation) and Phase 4 AI surface (LLM provider, citations, recommendations).
- **Marketing** — `npm run test:e2e:marketing` runs against a production web build,
  exercises the landing page, SEO surface, OG image, sitemap/robots, and demo-request API.
- **App spine** — `npm run test:e2e:app` runs against a production build + live API;
  covers sign-in, dashboard, matter creation, cockpit tabs, roadmap stubs, sign-out.
- **Mobile responsive** — Playwright `app-mobile` project (`devices['Pixel 5']`,
  393×851, touch) runs `tests/e2e/mobile-responsive.spec.ts` to prove the
  Topbar hamburger + dialog footers + grid stacking on phone viewports.
  `npx playwright test --config playwright.app.config.ts --project app-mobile`.
- **Live integrations** — gated behind `CASEOPS_E2E_ENABLE_LIVE_SOURCES=1` and
  `CASEOPS_E2E_ENABLE_PINE_LABS=1`.

### Bug-fixing protocol

Any bug triage / fix / verification / reopen review on this repo MUST
follow the fail-closed workflow in
[`.claude/skills/bug-fixing/SKILL.md`](./.claude/skills/bug-fixing/SKILL.md):
verdicts are exactly one of `Properly fixed` / `Partially fixed` /
`Not fixed` / `Inconclusive`; mobile bugs need mobile proof; reopened
bugs need fresh end-user verification; schema/enum drift needs the
full adjacent-path audit (backend schema → Zod → TS types → create
form → update form → fixtures). Hooked from `CLAUDE.md` so every
contributor gets it automatically.

### Post-deploy verification

Every Cloud Run deploy must pass the four-step staleness sweep before
being called "deployed" — see
[`memory/feedback_post_deploy_staleness_check.md`](./.claude/projects/C--Users-mishr-caseops/memory/feedback_post_deploy_staleness_check.md):
(1) HEAD vs revision tag, (2) public-domain `/api/health`, (3)
new-shape smoke (a route added in the deploy returns 401, not 404),
(4) image digest cross-check (`gcloud artifacts docker images describe
:$HEAD --format='value(image_summary.digest)'` matches the running
revision's `sha256:...`).

Security, tenant-leakage, agent, and AI-safety tests are tracked in
[`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) §11.

### Frontend component tests

- `npm run test:web` runs Vitest + React Testing Library + jsdom against
  `apps/web`. Fast (single-digit seconds), no browser.
- Covers the forms most visible to users on day one:
  - `QueryErrorState` — retry flow, offline copy, secondary actions.
  - `SignInForm` — zod validation with aria-invalid/aria-describedby
    wiring, forgot-password link preservation, happy-path submit, API error toasts.
  - `ForgotPasswordForm` — anti-enumeration reset request copy,
    validation, resend state, generic API errors, and debug-token hiding.
  - `NewMatterDialog` — validation, trim + uppercase on matter_code,
    submit success.
  - `DataTable` — filter input, Enter/Space keyboard activation on
    clickable rows, labelled pagination buttons.
- `npm run test:watch` for local TDD.

---

## Drafting studio (backend)

The drafting studio turns a matter into a citation-grounded document
through a strict state machine:

```
draft (empty) ──generate──▶ draft (v1)
                               │
                            submit
                               ▼
                           in_review ──request_changes──▶ changes_requested
                               │                                  │
                               │                          regenerate/submit
                               ▼                                  ▼
                           approved ──────────────────────────▶ in_review
                               │
                           finalize
                               ▼
                           finalized (terminal)
```

- **Schema** — `drafts`, `draft_versions`, `draft_reviews`
  (Alembic `20260417_0005`). Each version stores its body and the list
  of citations that survived the verifier; each review row captures
  who moved the draft and when.
- **Approve gate** — `approve` fails closed with 422 when the current
  version has zero verified citations. PRD §17.4: no external-facing
  AI answer without sources.
- **Finalized is terminal** — further generation / submit / approve /
  finalize all return 409 on a finalized draft.
- **Backend** — `services/drafting.py`; routes under
  `/api/matters/{id}/drafts/*`; `MockProvider` emits a deterministic
  draft JSON so CI runs the full pipeline offline.
- **Tests** — `apps/api/tests/test_drafting_studio.py` (7 cases —
  create, generate, full state-machine walk, approve fail-closed
  without citations, approve after regeneration, finalized locks
  transitions, tenant isolation, revision history).

**Frontend (Phase 14b).** `/app/matters/[id]/drafts` lists drafts and a
dialog creates new ones; `/app/matters/[id]/drafts/[draftId]` shows the
current version body, a citations panel with verified-count copy, a
review-history timeline, and a state-aware action bar that only renders
the legal next transitions. A `Download DOCX` button streams a Word
doc directly from `/api/matters/{id}/drafts/{id}/export.docx`. The full
state machine is covered by `tests/e2e/drafting.spec.ts`.

### PG-005 drafting roadmap (12 sprints, closed 2026-05-01)

The drafting studio reached `Implemented` status on 2026-05-01 with all
twelve sprints landed in production. See
[`docs/RELEASE_NOTES_2026-05-01.md`](./docs/RELEASE_NOTES_2026-05-01.md)
for the full release notes.

| Sprint | Surface | Where |
| --- | --- | --- |
| 1 | 4 templates: writ, quashing, written statement, reply / counter-affidavit | `apps/api/src/caseops_api/schemas/drafting_templates.py` |
| 2 | 7 more templates: DV-quashing, S.9 arbitration, caveat, vakalat, amendment of pleadings, compromise, probate (20 templates total) | `apps/api/src/caseops_api/services/drafting_prompts.py` |
| 3 | Court-format-aware PDF export (SC / Delhi HC / Bombay HC + generic profiles) | `apps/api/src/caseops_api/services/court_format_profiles.py` + `services/draft_pdf_export.py` |
| 4 | Filing-grade ZIP bundle (memo + vakalat + index + e-stamp placeholder + exhibits) | `apps/api/src/caseops_api/services/filing_bundle.py` |
| 5 | Court profile expansion: Madras / Calcutta / Karnataka HC + NCLT / NCLAT / DRT (10 profiles) + cause-title formatter | `services/court_format_profiles.py` |
| 6 | Structured draft revision compare (line-level diff hunks + citation deltas) | `services/draft_compare.py` + `<DraftCompareView>` |
| 7 | Bench-aware drafting expanded to 15 of 20 templates | `services/drafting.py` `_BENCH_AWARE_TEMPLATES` |
| 8 | Per-court / per-template pre-filing checklist | `services/filing_checklist.py` + `<FilingChecklistCard>` |
| 9 | DraftingStepper mobile-responsive at 360x800 | `components/drafting/DraftingStepper.tsx` |
| 10 | Solo mode (`?solo=1` flattens stepper into one form) | same |
| 11 | Template governance — admin can hide templates per tenant | `tenant_ai_policies.disabled_template_types_json` (Alembic `20260501_0003`) |
| 12 | Live-LLM drafting quality harness (target 4.8/5) | `caseops_api.scripts.eval_drafting_quality` |

---

## Litigation Strategy and Escalation Planner

The Strategy planner (PRD `docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md`)
turns a matter into a citation-grounded route plan. Distinct from the
four classical recommendation types (`forum`, `authority`, `remedy`,
`next_best_action`) because it produces a *route*, not a list of
options:

- **Current posture** — what stage the matter is at.
- **Recommended route + alternatives** — each citation-anchored.
- **Forum sequence** — escalation ladder up to Supreme Court level
  (SLP / Article 132-134 appeal / review / curative) where legally
  available.
- **Recommended draft pack** — one-click links into the drafting
  flow with the matter pre-filled. SC drafts grey out on lower-court
  matters with a reason.
- **Limitation flags, missing facts, risks, required documents.**

### Hard product rules (non-negotiable)

- Every strategy is `review_required=True` until a partner signs off.
- Refuse / fail-closed on zero verified citations (HTTP 422).
- Output must NOT contain `perfect strategy`, `guaranteed`,
  `will win`, `certain outcome`, `no lawyer needed`, `replace
  advocate`. A structural test (`assert_no_forbidden_phrases`)
  enforces this both as a Pydantic post-processor and as a unit test.
- Missing facts are listed; never invented.
- Authorities, dates, forum names, remedies are never invented.
- Supreme Court routes only where they are legally plausible
  (Articles 132 / 133 / 134 / 136 / 137 / 142 etc.) — gated on the
  matter's `forum_level`.

### Where it lives

- Backend service — `apps/api/src/caseops_api/services/litigation_strategy.py`
- Pydantic schema — `apps/api/src/caseops_api/schemas/litigation_strategy.py`
- Recommendation type — `litigation_strategy` in
  `apps/api/src/caseops_api/services/recommendations.py` (`SUPPORTED_TYPES`)
- Persistence — `recommendations.strategy_payload_json` (Alembic
  `20260503_0001`); same `Recommendation` row carries the strategy
  metadata, audit, and decision flow as the other four recommendation
  types.
- Frontend — `apps/web/app/app/matters/[id]/strategy/page.tsx`
- Capability — `recommendations:generate` (read) and
  `recommendations:decide` (approve / request changes).
- Audit — `recommendation.generated` event with
  `metadata.type='litigation_strategy'`.

### SC + escalation drafting templates (11)

Added alongside the strategy planner so the recommended-drafts panel
has real targets:

| Slug | Forum | Statutory anchor |
| --- | --- | --- |
| `special_leave_petition` | SC | Article 136 |
| `supreme_court_appeal` | SC | Articles 132 / 133 / 134 |
| `review_petition` | SC + HC | Article 137 / Order XLVII Rule 1 CPC |
| `curative_petition` | SC | Rupa Ashok Hurra (2002) 4 SCC 388 |
| `transfer_petition` | SC | Article 139A / s.25 CPC / s.406 BNSS |
| `contempt_petition` | SC + HC | Articles 129 / 215, Contempt of Courts Act 1971 |
| `interim_relief_application` | All | CPC Order XXXIX, Dalpat Kumar three-factor test |
| `condonation_of_delay` | All | s.5 Limitation Act, Mst. Katiji |
| `exemption_application` | SC | SC Rules 2013 Order V / Order XV |
| `synopsis_list_of_dates` | SC | SC Rules 2013 Order V Rule 1(3) |
| `filing_index_checklist` | SC + HC | SC Rules 2013 Order IV |

### Tests

- `apps/api/tests/test_litigation_strategy.py` — 14 tests
- `apps/api/tests/test_sc_strategy_templates.py` — 61 tests
- `apps/api/tests/test_template_recommender.py` — extended
- `apps/web/app/app/matters/[id]/strategy/page.test.tsx` — 7 tests

---

## Upload hardening

Every attachment upload is validated before it touches disk:

1. **Extension whitelist** — `.pdf`, `.docx`, `.doc`, `.txt`, `.png`,
   `.jpg`, `.jpeg`. Anything else rejected with 400.
2. **Declared content-type coherence** — a `.pdf` claiming
   `image/png` is refused (a sloppy client is rarer than a
   malicious one, but both fail here).
3. **Magic-byte check** — the first 16 bytes must match the expected
   signature (`%PDF-` for PDFs, `PK\x03\x04` for DOCX,
   `\x89PNG` for PNGs, `\xd0\xcf\x11\xe0` for legacy `.doc`, etc.).
   A renamed `malware.pdf` that's actually a Windows PE (starts with
   `MZ`) fails here.

Logic in `services/file_security.verify_upload`; cursor resets to 0
on success so the downstream persister reads the full body. Virus
scanning is §9.3 — a future Temporal activity, not shipped today.

---

## Error shape (RFC 7807)

Every non-2xx response is `application/problem+json`:

```json
{
  "type": "verified_citations_required",
  "title": "Unprocessable content",
  "status": 422,
  "detail": "Cannot approve a draft with zero verified citations…",
  "instance": "/api/matters/.../drafts/.../approve"
}
```

`type` is a stable machine-readable slug — the frontend switches on
it to render precise recovery copy. Validation errors keep the raw
pydantic breakdown under `errors`. Unknown errors fall back to
`https://httpstatuses.com/<code>`.

---

## Role and capability gates

FastAPI dependencies in `api/dependencies.py`:

```python
from caseops_api.api.dependencies import require_capability

@router.get("/admin/audit/export", ...)
def export(
    context: Annotated[SessionContext, Depends(require_capability("audit:export"))],
    ...,
):
    ...
```

The server-side `CAPABILITY_ROLES` table mirrors
`apps/web/lib/capabilities.ts` — the TS table gates the UX; the
Python table is the enforcement source of truth.

---

## Court / Bench / Judge registry

`GET /api/courts/` lists the seeded 7 courts (SC + 5 target HCs +
Patna). `GET /api/courts/{id}/judges` lists judges tied to a court.
Matter records carry an optional `court_id` FK alongside the freeform
`court_name`, so old matters keep working and new ones can resolve to
a canonical court without a UI migration.

---

## Ethical walls and matter-level ACL

Matters default to **"every company member sees them"**. Flip
`matters.restricted_access=true` on a sensitive matter and only
memberships listed in `matter_access_grants` open it. Layer on top:
**ethical walls** — rows in `ethical_walls` block a specific
membership regardless of grants, so a conflict-walled associate can't
see a matter even if the partner forgot to revoke their grant.

Rule order (top wins):

1. Company owner → always allowed (can't be locked out of their own firm).
2. Matter's own assignee → always allowed (the responsible lawyer can't be walled from their matter).
3. Ethical wall matches → **denied and audited** (`access_denied`).
4. Matter not restricted → allowed.
5. Explicit grant exists → allowed.
6. Otherwise → denied and audited.

Endpoints for admins / owners:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/matters/{id}/access` | Panel: restricted flag + grants + walls. |
| `POST` | `/api/matters/{id}/access/restricted` | Toggle `{ "restricted": true \| false }`. |
| `POST` | `/api/matters/{id}/access/grants` | `{ membership_id, access_level?, reason? }`. |
| `DELETE` | `/api/matters/{id}/access/grants/{grant_id}` | Revoke a grant. |
| `POST` | `/api/matters/{id}/access/walls` | `{ excluded_membership_id, reason? }`. |
| `DELETE` | `/api/matters/{id}/access/walls/{wall_id}` | Remove a wall. |

Every mutation is audited; every denied access is audited. Tests:
`apps/api/tests/test_ethical_walls.py` (6 cases).

---

## Audit trail

Every tenant-affecting write lands a row in `audit_events` via
`services/audit.record_audit` — append-only by convention, indexed by
`(company_id, created_at)` and `(company_id, action)`. Wired into
matter create, draft state transitions (create / generate / submit /
request-changes / approve / finalize), hearing-pack generate +
review, and hearing outcome capture.

Admins can stream the trail as JSONL:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:8000/api/admin/audit/export?since=2026-04-01" \
     -o audit.jsonl
```

Defaults to the last 30 days. Optional filters: `since=`, `until=`
(ISO-8601), `action=` (e.g. `draft.approve`), `limit=`. Downloads are
themselves audited (`audit.exported` row with row_count in metadata).

Tests: `apps/api/tests/test_audit_events.py` — 5 cases covering
row emission, state-machine linearity, admin-only gate, JSONL
streaming + self-audit, cross-tenant isolation.

---

## Corpus ingestion

Run `caseops-ingest-corpus` to pull Supreme Court and Indian High
Court judgments into the authority corpus. Full CLI usage and the
**model-swap procedure** (swap embedding provider without
re-ingesting text) are in
[`docs/runbooks/corpus-ingest.md`](./docs/runbooks/corpus-ingest.md).

Quick reference:

```bash
# Ingest — streaming from public S3
uv run caseops-ingest-corpus --court sc --years 2020-2024 --from-s3 -v
uv run caseops-ingest-corpus --court hc --years 2020-2024 --from-s3 \
  --hc-courts delhi,bombay,karnataka,madras,telangana -v

# Re-embed — after changing CASEOPS_EMBEDDING_PROVIDER / MODEL
export CASEOPS_EMBEDDING_PROVIDER=voyage
export CASEOPS_EMBEDDING_MODEL=voyage-3-law
uv run caseops-ingest-corpus --reembed -v
```

---

## Hearing prep

CaseOps drafts a citation-grounded **hearing pack** for every scheduled
hearing. Each pack groups matter facts into the PRD §9.6 sections —
chronology, last order, pending compliance, issues, opposition points,
authority cards, and oral points — and is always created as
`review_required` until a partner signs off. A `PATCH` to the hearing
with `status=completed` automatically spawns a follow-up task
(`Post-hearing follow-up — {purpose}`) on the matter's owner.

- Backend: `apps/api/src/caseops_api/services/hearing_packs.py`
- Schema + migration: `alembic/versions/20260417_0004_hearing_packs.py`
- UI: `components/app/HearingPackDialog.tsx`, surfaced on
  `/app/matters/[id]/hearings`
- Tests: `apps/api/tests/test_hearing_packs.py` (6 cases — generation,
  round-trip, review, post-hearing follow-up task, opt-out,
  cross-tenant isolation)

The hearing pack runs through the same `LLMProvider` abstraction as
recommendations. Locally, `CASEOPS_LLM_PROVIDER=mock` (the default)
yields a deterministic pack that exercises all seven item kinds —
enough to test the full UI and route surface offline.

---

## Resilience (loading, empty, error)

Every data surface in the workspace has a defined loading, empty, and
error presentation — no blank frames, no silent failures, no raw
Chromium `ERR_*` pages on a transient API blip. The contract:

- **Loading** — always a branded skeleton or inline spinner, never a
  blank frame. Route-level Suspense falls back to `/app/loading.tsx`.
- **Empty** — `EmptyState` with an icon, a one-line explanation, and
  (when the user has permission) an action that creates the first
  record.
- **Error** — `QueryErrorState` surfaces the API's `detail` message and
  a "Try again" button wired to react-query's `refetch()`. If the error
  is a `NetworkError` (DNS, CORS, or API host unreachable) the copy
  shifts to "Workspace is offline" and an understated amber
  `OfflineBanner` appears at the top of the shell; it auto-hides the
  moment any query succeeds again.
- **404** — `/app/matters/[id]/not-found.tsx` plus an in-layout
  fallback render a branded "Matter not found" with a "Back to matter
  portfolio" out, instead of Next's default 404.
- **Unhandled exceptions** — `/app/error.tsx` catches anything the
  boundary didn't, with a `reset()` action, a back-to-workspace link,
  and a stable digest for support.

The automated gate for this contract lives in
`tests/e2e/query-states.spec.ts` — stubs `/api/matters` to 500 and
`/api/contracts` to 503, asserts the retry surfaces correctly, clicks
"Try again", and asserts the workspace recovers. It also exercises the
404 path. Run with:

```
npm run test:e2e:app
```

---

## Accessibility

CaseOps targets **WCAG 2.1 AA** on the marketing surface, sign-in, and the
authenticated app spine. The house rules:

- Every route has exactly one `<h1>`; heading levels never skip.
- Global `:focus-visible` ring on every interactive element; every
  authenticated and public page carries a skip-link to `#main`.
- Form inputs pair with `<Label htmlFor>`, surface errors via
  `role="alert"` + `aria-describedby`, and set `aria-invalid` on the
  failing field so assistive tech announces the validation state.
- Tables with clickable rows expose `role="button"`, `tabIndex=0`, and
  Enter/Space handlers so they are operable without a mouse.
- Colour tokens are audited against 4.5:1 contrast; text and muted
  surfaces are verified in CI by `@axe-core/playwright`.

The automated gate lives in `tests/e2e/a11y.spec.ts` — zero
`serious`/`critical` axe violations on `/`, `/sign-in`, `/app`,
`/app/matters`, and `/app/contracts`. Run it with:

```
npm run test:e2e:app
```

Findings beyond the automated gate (keyboard-navigation walk-throughs,
screen-reader spot checks) are tracked in
[`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) §3.7.

---

## Legal corpus ingestion (Indian HC + SC)

CaseOps ships a streaming ingester for the two public Indian judgment
buckets. Run it against local data (after `aws s3 cp`), or let the CLI
stream directly from S3 with a workstation-safe disk cap.

Prerequisites:

- Docker Postgres + pgvector up: `docker compose up postgres -d`
- API deps synced: `cd apps/api && uv sync`
- Embeddings backend of choice configured (defaults to a mock provider
  so the pipeline is runnable offline):

```
# Local, free, CPU, ~250 MB model download
cd apps/api && uv sync --extra embeddings
export CASEOPS_EMBEDDING_PROVIDER=fastembed
export CASEOPS_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5

# Or Voyage AI (paid, legal-tuned)
export CASEOPS_EMBEDDING_PROVIDER=voyage
export CASEOPS_EMBEDDING_MODEL=voyage-3-law
export CASEOPS_EMBEDDING_API_KEY=<your-key>

# Or Google Gemini (paired with the Gemini LLM provider)
export CASEOPS_EMBEDDING_PROVIDER=gemini
export CASEOPS_EMBEDDING_MODEL=text-embedding-005
export CASEOPS_EMBEDDING_API_KEY=<your-key>
```

Streaming ingest directly from S3 (no AWS CLI required; boto3 unsigned):

```
# High Court, year 2010, cap 20 PDFs for a trial run
uv run caseops-ingest-corpus --court hc --year 2010 --from-s3 --limit 20

# Supreme Court tarballs, year 1995
uv run caseops-ingest-corpus --court sc --year 1995 --from-s3 --limit 2
```

The streamer downloads a batch (default 25 PDFs), ingests and deletes
each file as it goes, then removes the batch directory. Respects a
soft cap on disk usage (`CASEOPS_CORPUS_INGEST_MAX_WORKDIR_MB`,
default 500 MB).

Ingesting a pre-downloaded directory:

```
# After: aws s3 cp s3://indian-high-court-judgments/data/pdf/year=2010/ ./2010/ ...
uv run caseops-ingest-corpus --court hc --year 2010 --path ./2010 --limit 200
```

Each run deduplicates by a canonical key derived from the filename,
court, year, and file size — rerunning is idempotent.

Quality tiers (what's real, what's honest):

- **Mock embeddings**: pipeline works end-to-end offline. Retrieval still
  benefits from the existing TF-IDF signal, but semantic retrieval is a
  hash approximation. Fine for CI and "does it run?" checks.
- **fastembed (BGE-base)**: first real semantic retrieval. Suitable for
  internal use and demos.
- **Voyage `voyage-3-law` or Gemini `text-embedding-005`**: production-grade
  for a hosted founder-stage deployment.
- **Next quality lifts (not yet shipped):** cross-encoder reranker on the
  top-50, legal-specific fine-tuning, per-jurisdiction filters. Tracked
  in `docs/WORK_TO_BE_DONE.md` §4.2 residuals.

---

## Deployment

Cloud Run assets live in [`infra/cloudrun/`](./infra/cloudrun/). The helper script is
idempotent and deploys API + worker job:

```powershell
.\infra\cloudrun\deploy.ps1 `
  -ProjectId "<gcp-project-id>" `
  -ProjectNumber "<gcp-project-number>" `
  -Region "asia-south1" `
  -CloudSqlInstance "<cloud-sql-instance-name>" `
  -ServiceAccount "<runtime-service-account-email>" `
  -SchedulerServiceAccount "<scheduler-service-account-email>" `
  -ApiImage "<artifact-registry-image-ref>" `
  -DatabaseUrl "<cloud-sql-psycopg-url>" `
  -GcsBucket "<document-bucket-name>" `
  -PublicAppUrl "https://app.caseops.ai"
```

See [`infra/cloudrun/README.md`](./infra/cloudrun/README.md) for the full variable list and
required IAM.

---

## Product principles

CaseOps follows a few non-negotiable rules. Read in full in [`CLAUDE.md`](./CLAUDE.md).

- Matter-native, not chatbot. Every workflow lives on a matter graph.
- Citation-grounded AI. No substantive answer without a source.
- Tenant isolation by default. Ethical walls override broad role access.
- Agent grant, execution, revocation, and audit records exist for readiness; autonomous
  scoped-agent tool execution remains planned until the trust plane is activated.
- Latest stable versions; permissive licenses (MIT, Apache-2.0, BSD, PostgreSQL) only.

---

## Contributing

This is a private repository during founder stage. If you're an invited collaborator, read
[`CLAUDE.md`](./CLAUDE.md) before opening a PR: changes should be surgical, avoid speculative
abstractions, and include verification (tests or concrete checks).

---

## License

© CaseOps. All rights reserved.
