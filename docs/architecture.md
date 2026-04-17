# CaseOps Architecture

## Purpose

This document turns the PRD into the first implementation architecture for `caseops.ai`. It is optimized for:

- founder-stage execution
- enterprise-shaped evolution
- strict multi-tenancy
- legal AI safety and auditability
- permissive-license technology choices

## Architecture Principles

1. `Matter-native`: every workflow anchors to a matter, contract, investigation, or legal request.
2. `Tenant-isolated`: every persistent object is tenant-aware from day one.
3. `Enterprise-shaped`: start lightweight on GCP but preserve clean upgrade paths.
4. `AI as a controlled subsystem`: models generate and explain, but workflows and permissions stay deterministic.
5. `Durable-by-design`: long-running work belongs in workflow orchestration, not request handlers.

## Founder-Stage Deployment Shape

### Initial Platform

- `Cloud Run` for stateless web and API services, plus document-worker jobs
- `Cloud SQL for PostgreSQL` as the primary system of record
- `GCS` for document storage, exports, and backups
- `Secret Manager` for runtime secrets
- hosted inference for shared SaaS mode
- packaged private inference as an enterprise deployment option

### Why this shape

- keeps the cost profile lean before the first customer
- still supports autoscaling for stateless workloads
- avoids a Kubernetes operations tax too early
- preserves a clean migration path to `GKE`

## Monorepo Shape

```text
caseops/
  apps/
    api/
    web/
  docs/
  infra/
```

## Application Services

### Web App

- `Next.js`
- primary UI for law firms and GCs
- server-rendered and client-enhanced dashboards
- email/password auth first
- SSO-ready boundaries from the beginning

### API App

- `FastAPI`
- canonical backend for domain APIs
- settings-driven configuration
- future home for auth, tenancy, matters, billing, contracts, hearings, and recommendation endpoints

### Future Dedicated Services

These are intentionally lightweight at the moment, but the architecture expects them:

- workflow service using `Temporal`
- agent trust integration through `Grantex`
- document worker service for OCR, parsing, and reindex jobs
- search and retrieval service
- recommendation service
- billing and payment webhook service

### Current Worker Shape

- attachment uploads enqueue `document_processing_jobs`
- a dedicated worker can drain queued jobs independently of API traffic
- stale jobs can be recovered and requeued
- scheduled maintenance can enqueue retries for `needs_ocr` or `failed` files and reindex older indexed files
- this maps cleanly to `Cloud Run jobs`, a worker service on `Cloud Run`, or later `Temporal` activities

## AI Architecture

### Serving Strategy

- shared SaaS: hosted inference first
- enterprise: `CaseOps-managed private inference stack`
- model routing kept behind internal provider interfaces

### Model Roles

- `Gemma 4 31B IT`: multimodal reasoning and premium synthesis
- `gpt-oss-20b`: economical general reasoning and tool-friendly workflows
- `Gemma 4 E4B` or similar: lightweight local or constrained deployments
- smaller task models: extraction, reranking, and classification

### Training Strategy

- keep law in retrieval, not in static model memory
- fine-tune for workflow behavior, format, and style only
- use HITL edits and approved outputs to improve quality over time
- train separate task models for extraction and recommendation ranking

## Data Plane

### Primary Stores

- `PostgreSQL + pgvector`: transactional domain data and early vector storage
- `GCS`: documents and generated artifacts
- `Valkey`: cache and ephemeral coordination

### Document Storage Strategy

- founder mode uses the `local` storage backend with a shared Docker volume between API and worker containers
- cloud mode uses the `gcs` storage backend
- attachment records keep a backend-neutral `storage_key`
- runtime consumers resolve that key either directly from local disk or through a cached `GCS` materialization path under `/tmp`
- this keeps download, OCR, review, and retrieval code stable across environments

### Later Additions

- `OpenSearch` when corpus size and retrieval requirements justify dedicated search infrastructure
- dedicated analytics and event pipelines when product telemetry expands

## Security Model

### Human Identity

- email/password first
- SSO-ready design for future OIDC/SAML integration
- role-based access controls by tenant

### Agent Identity

- `Grantex` governs agent identity, scoped grants, revocation, budgets, and audit

### Tenant Isolation

- tenant-aware schema from day one
- future row-level security and stronger policy enforcement
- no cross-tenant training by default

## Local Development

### Docker Compose

The initial compose stack exists for local use:

- web
- api
- worker
- postgres with `pgvector`
- valkey

This keeps the local topology close enough to the cloud architecture without introducing full infrastructure complexity.

## Cloud Worker Shape

- `infra/cloudrun/api-service.yaml` deploys the HTTP API on `Cloud Run`
- `infra/cloudrun/document-worker-job.yaml` deploys the document processor as a `Cloud Run Job`
- the worker job runs `caseops-document-worker --once`
- `Cloud Scheduler` can invoke that job on a short cadence so queued OCR and reindex work drains without needing a permanently running non-HTTP service
- both API and worker use the same API image and the same `GCS` document backend

## Next Build Priorities

1. add authentication and tenant bootstrap flows
2. add database migrations and first domain tables
3. add matter and company management endpoints
4. integrate Pine Labs fee collection workflows
5. introduce Temporal and Grantex into the running skeleton
