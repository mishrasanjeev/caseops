# CaseOps

CaseOps is a matter-native legal operating system for Indian law firms and corporate legal teams. This repository starts with the founder-stage monorepo skeleton aligned with the product PRD and the middle-path GCP architecture.

## Monorepo Layout

- `apps/web`: Next.js web application
- `apps/api`: FastAPI backend
- `docs`: PRD and implementation docs
- `infra`: infrastructure artifacts and deployment assets

## Technology Baseline

- `npm` workspaces for JavaScript and TypeScript packages
- `uv` for Python environment and dependency management
- `Docker` from day one for local consistency
- `Cloud Run + Cloud SQL + GCS` as the founder-to-first-customer deployment target
- `Temporal + Grantex` reserved as first-class architectural components even if not fully wired in the initial skeleton

## Quick Start

### Web

```powershell
cd apps/web
npm install
npm run dev
```

### API

```powershell
cd apps/api
uv sync
uv run uvicorn caseops_api.main:app --reload --app-dir src
```

### Local Docker Compose

```powershell
docker compose up --build
```

## Current Status

This initial scaffold includes:

- monorepo root configuration
- a FastAPI service with health and metadata endpoints
- a Next.js application shell
- local Dockerfiles and a compose file
- architecture documentation aligned with the PRD

## Guiding Documents

- [PRD](./docs/PRD.md)
- [Architecture](./docs/architecture.md)
- [Coding Guidelines](./CLAUDE.md)
