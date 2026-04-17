# CaseOps

**The matter-native legal operating system for Indian law firms and corporate legal teams.**

CaseOps unifies matter management, legal research, AI-assisted drafting, hearing preparation,
contract workflows, outside-counsel management, and billing into one citation-grounded
workspace — with tenant isolation, scoped agent grants, and audit by default.

> Founder-stage monorepo. **Pre-alpha.** The backend foundation (matters, documents,
> contracts, billing, authority ingestion) is working and hardened; the AI core is actively
> landing. See [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) for current status and
> priority.

---

## What's in the box

| Surface | Status | Where |
| --- | --- | --- |
| Marketing site (`/`) | Live | `apps/web/app/page.tsx` |
| Sign in (`/sign-in`) | Live | `apps/web/app/sign-in/` |
| App shell + Matter Cockpit (`/app`) | Live | `apps/web/app/app/` |
| Legacy founder console (`/legacy`) | Preserved during rebuild | `apps/web/app/legacy/` |
| API (auth, matters, contracts, documents, billing, authorities, recommendations) | Founder-stage, security-hardened | `apps/api/` |
| Document worker | Founder-stage | `apps/api/src/caseops_api/workers/` |
| PRD | Stable | [`docs/PRD.md`](./docs/PRD.md) |
| Architecture | Stable | [`docs/architecture.md`](./docs/architecture.md) |
| Work plan | Current | [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) |

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
- **Payments** — Pine Labs integration with HMAC webhook verification, idempotency, and
  cross-tenant guards.
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
```

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
- **Legacy e2e** — `npm run test:e2e` drives the founder-mode console end-to-end.
- **Live integrations** — gated behind `CASEOPS_E2E_ENABLE_LIVE_SOURCES=1` and
  `CASEOPS_E2E_ENABLE_PINE_LABS=1`.

Security, tenant-leakage, agent, and AI-safety tests are tracked in
[`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) §11.

### Frontend component tests

- `npm run test:web` runs Vitest + React Testing Library + jsdom against
  `apps/web`. Fast (single-digit seconds), no browser.
- Covers the forms most visible to users on day one:
  - `QueryErrorState` — retry flow, offline copy, secondary actions.
  - `SignInForm` — zod validation with aria-invalid/aria-describedby
    wiring, happy-path submit, API error toasts.
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

**Still shipping in Phase 14b** (next session):
`/app/matters/[id]/drafts` editor with version diff and reviewer
approve/reject, DOCX export via `python-docx`, PDF export via
`weasyprint`, and template selection.

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
- Agents run with scoped grants, expiry, budgets, revocation, and audit.
- Latest stable versions; permissive licenses (MIT, Apache-2.0, BSD, PostgreSQL) only.

---

## Contributing

This is a private repository during founder stage. If you're an invited collaborator, read
[`CLAUDE.md`](./CLAUDE.md) before opening a PR: changes should be surgical, avoid speculative
abstractions, and include verification (tests or concrete checks).

---

## License

© CaseOps. All rights reserved.
