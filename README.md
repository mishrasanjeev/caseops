# CaseOps

**The matter-native legal operating system for Indian law firms and corporate legal teams.**

CaseOps unifies matter management, legal research, AI-assisted drafting, hearing preparation,
contract workflows, outside-counsel management, and billing into one citation-grounded
workspace â€” with tenant isolation, scoped agent grants, and audit by default.

> This repository is the founder-stage monorepo. It is **pre-alpha**: the backend foundation
> (matters, documents, contracts, billing, authority ingestion) works; the AI core (drafting,
> recommendations, agents) and a proper frontend are in active rebuild. See
> [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) for the current plan.

---

## What's in the box

| Surface | Status | Where |
| --- | --- | --- |
| Marketing site | Live (Phase 1) | `apps/web/app/page.tsx` |
| App shell + Matter Cockpit | Live (Phase 3) | `apps/web/app/app/` |
| Sign in | Live | `apps/web/app/sign-in/` |
| Legacy workspace | Preserved at `/legacy` until rebuild completes | `apps/web/app/legacy/` |
| API (auth, matters, contracts, documents, billing, authorities) | Founder-stage, hardened in Phase 2 | `apps/api/` |
| Document worker | Founder-stage | `apps/api/src/caseops_api/workers/` |
| PRD | Stable | [`docs/PRD.md`](./docs/PRD.md) |
| Architecture | Stable | [`docs/architecture.md`](./docs/architecture.md) |
| Work plan | Current | [`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) |

---

## Monorepo layout

```
caseops/
â”œâ”€â”€ apps/
â”‚   â”œâ”€â”€ api/            FastAPI backend, Alembic migrations, document worker
â”‚   â””â”€â”€ web/            Next.js 16 + React 19 + Tailwind v4 frontend
â”œâ”€â”€ docs/               PRD, architecture, work plan
â”œâ”€â”€ infra/              Cloud Run manifests and deploy helpers
â”œâ”€â”€ tests/              Playwright end-to-end tests
â””â”€â”€ docker-compose.yml  Local multi-service dev stack
```

---

## Technology

- **Web** â€” Next.js 16, React 19, TypeScript 6, Tailwind CSS v4, `lucide-react`
- **API** â€” Python 3.13, FastAPI, Pydantic, SQLAlchemy 2, Alembic
- **Data** â€” PostgreSQL 17 with `pgvector`, Valkey cache, GCS (or local FS) for documents
- **Worker** â€” custom polling worker (to be replaced with Temporal â€” see work plan Â§5.1)
- **Payments** â€” Pine Labs integration (HMAC webhook verification)
- **Deployment** â€” Cloud Run + Cloud SQL + GCS for founder stage; GKE path preserved
- **Tests** â€” pytest (unit), Playwright (e2e)

Dependency policy: latest stable production-ready versions only; no betas, no intentional pins
to older majors without a documented blocker. See [`CLAUDE.md`](./CLAUDE.md).

---

## Quickstart

### Prerequisites

- Node.js 22+ and npm 10+
- Python 3.13 and [`uv`](https://github.com/astral-sh/uv)
- Docker (for Postgres + Valkey locally) or a live Postgres 17 + `pgvector`

### 1) Install dependencies

```bash
# JS workspace deps
npm install

# Python deps for the API
cd apps/api && uv sync && cd ../..
```

### 2) Run the stack locally

Option A â€” full Docker stack (recommended):

```bash
docker compose up --build
```

Starts `web` (port 3000), `api` (port 8000), `worker`, `postgres` (5432), `valkey` (6379).

CaseOps local runtime is Postgres-first. SQLite is only a legacy/test fallback and should not be used for local seeded corpora or normal app development.

Option B â€” run pieces directly:

```bash
# Terminal 0 - infra only
npm run dev:infra

# Terminal 1 - API
npm run dev:api

# Terminal 2 â€” Web
npm run dev:web

# Terminal 3 â€” worker (optional, for document OCR/indexing)
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
| `npm run dev:web` | Start the Next.js dev server (Turbopack) |
| `npm run dev:api` | Start FastAPI with reload |
| `npm run build:web` | Production build of the web app |
| `npm run typecheck:web` | `tsc --noEmit` on the web app |
| `npm run test:api` | pytest suite for the API |
| `npm run lint:api` | ruff lint on the API |
| `npm run test:e2e` | Legacy Playwright e2e (requires live API + worker + DB) |
| `npm run test:e2e:headed` | Same, in headed mode |
| `npm run test:e2e:marketing` | Marketing suite against a production web build |
| `npm run test:e2e:app` | App shell + matter cockpit suite against a production build |

---

## Environment

Create `apps/web/.env.local` from the example:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_APP_URL=http://localhost:3000/app
```

For the API, copy `apps/api/.env.example` and set at minimum `CASEOPS_AUTH_SECRET`,
`CASEOPS_DATABASE_URL`, `CASEOPS_PUBLIC_APP_URL`, and (optional) Pine Labs credentials.

> **Security note.** The default `CASEOPS_AUTH_SECRET` shipped in settings is a placeholder.
> Never deploy without setting your own. See `docs/WORK_TO_BE_DONE.md` Â§2.2.

---

## Testing

- **API unit tests** â€” `npm run test:api`. Covers auth, company, matters, contracts, documents,
  authorities, outside counsel.
- **End-to-end** â€” `npm run test:e2e` starts real API + Web + worker and drives the browser
  through founder-mode flows.
- **Live integrations** â€” gated behind `CASEOPS_E2E_ENABLE_LIVE_SOURCES=1` and
  `CASEOPS_E2E_ENABLE_PINE_LABS=1`.

Security, tenant-leakage, agent, and AI-safety tests are tracked in
[`docs/WORK_TO_BE_DONE.md`](./docs/WORK_TO_BE_DONE.md) Â§11.

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

CaseOps is built on a few non-negotiable rules. Read in full in [`CLAUDE.md`](./CLAUDE.md).

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

Â© CaseOps. All rights reserved.
