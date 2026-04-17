# CaseOps — Work To Be Done

**Author:** Engineering review
**Date:** 2026-04-16
**Scope:** Gap analysis between `docs/PRD.md` v1.0.0 and the current codebase (`main` branch, commits through `ee894c0`).
**Status:** For founder review and sprint planning.
**Instructions for readers:** Every item below traces to either (a) a specific PRD section, (b) a concrete file:line reference in the repo, or (c) a security/correctness bug that blocks production. Do not expand scope beyond these.

---

## 0. How to read this document

### Severity levels

- **P0 — Blocking.** Cannot ship to any external user. Either a security bug, a legally-sensitive data risk, or a core PRD promise that is absent (drafting, recommendations, agents).
- **P1 — Launch-gating.** Required before first paying customer or enterprise pilot.
- **P2 — Hardening.** Required before enterprise / multi-tenant SaaS scale, but not for founder-stage pilot.
- **P3 — Phase 3+.** Post-GA polish.

### Work-item format

Every work item uses:

- **Traces to:** PRD section and/or concrete file:line
- **Problem:** what is wrong today
- **Done when:** acceptance criteria

---

## 1. Executive summary

The backend has a respectable Phase-0/early-Phase-1 foundation: matter workspace, documents, contracts, billing with Pine Labs, and authority ingestion are real. Multi-tenant scoping is consistently threaded through services via `SessionContext`. 14 Alembic migrations are clean.

However, three very large gaps exist between the PRD and the product:

1. **The frontend is a prototype, not a product.** The entire web app is one 5,965-line `apps/web/app/page.tsx` with anchor-link navigation, 26+ `useState` hooks, no component decomposition, and an information architecture that covers 6 of the PRD's 10 top-level sections. The user has explicitly said the UX is unacceptable.
2. **The PRD's AI promise is unbuilt.** There is no LLM integration anywhere in the codebase, no Drafting Studio, no Recommendation Engine, no Grantex agent identity, no Temporal, and no proper RAG (pgvector is installed but unused; "semantic" search is a hardcoded synonym map).
3. **Several security and governance primitives are missing.** System-wide audit trail, token revocation on suspend, webhook idempotency, MFA, rate limiting, password policy, and a cross-tenant check on the payment webhook path.

This document enumerates the work needed to close these gaps, in priority order, with acceptance criteria per item.

---

## 2. P0 — Security and correctness fixes

> **Status (Phase 2, 2026-04-17):** §2.1, §2.2, §2.3, §2.4, §2.5, §2.6, §2.7, §2.8 all **landed**.
> 35 new security tests (101 total API tests green). Alembic migration `20260417_0001`
> adds `payment_webhook_events.provider_event_id` (unique per provider) and
> `company_memberships.sessions_valid_after`. `slowapi` wired for auth rate limiting.

### 2.1 Pine Labs webhook accepts unsigned requests when secret is empty — **DONE**

- **Traces to:** `apps/api/src/caseops_api/services/pine_labs.py:85-92`
- **Problem:** `verify_pine_labs_signature` returned `True` when `pine_labs_webhook_secret` was unset.
- **Landed:** `verify_pine_labs_signature` now raises `WebhookSecretNotConfigured`; the handler maps that to `503`. Tampered signatures still return `401`.
- **Tests:** `tests/test_webhook_security.py::test_webhook_without_configured_secret_returns_503`, `::test_webhook_with_tampered_signature_returns_401`.

### 2.2 JWT signing key ships with a hardcoded default — **DONE**

- **Traces to:** `apps/api/src/caseops_api/core/settings.py:22`
- **Landed:** `Settings` validator rejects the placeholder secret whenever `CASEOPS_ENV` is `staging`/`production`/`prod`. `local` still accepts it for dev. `.env.example` annotated.
- **Tests:** `tests/test_security_settings.py` (5 cases).
- **Open:** Cloud Run manifest update to reference Secret Manager — covered under §8.5.

### 2.3 Suspended users keep working tokens until expiry — **DONE**

- **Traces to:** `apps/api/src/caseops_api/services/identity.py:159-166`; `apps/api/src/caseops_api/api/dependencies.py`
- **Landed:** Added `company_memberships.sessions_valid_after` (nullable timestamptz). JWTs now carry `iat`; `get_session_context` rejects tokens whose `iat` predates the cutoff. Membership suspension bumps the cutoff to now. Existing `is_active` check continues to block suspended memberships immediately.
- **Tests:** `tests/test_session_revocation.py` (4 cases including a real pre-cutoff token being rejected).
- **Deferred:** refresh-token rotation and explicit logout endpoint remain for the auth-service workstream.

### 2.4 Payment webhook has no cross-tenant assertion — **DONE**

- **Traces to:** `apps/api/src/caseops_api/services/payments.py:322-401`
- **Landed:** Handler loads the invoice with its matter + company and asserts `attempt.merchant_order_id` begins with `{company.slug}-`. Mismatch → `409 Conflict`, webhook event recorded with `processing_status="cross_tenant_rejected"`, invoice state unchanged.
- **Tests:** `tests/test_webhook_security.py::test_webhook_rejects_cross_tenant_attempt` (also asserts the invoice status did not advance).

### 2.5 Payment webhook has no idempotency key — **DONE**

- **Traces to:** `apps/api/src/caseops_api/services/payments.py:322-401`; `apps/api/src/caseops_api/db/models.py` (PaymentWebhookEvent)
- **Landed:** Added `payment_webhook_events.provider_event_id` (nullable, indexed) and a unique index on `(provider, provider_event_id)`. Handler extracts event id from payload (`event_id` / `webhook_event_id` / `id` / `notification_id` / `reference_id`) and returns `200 already_processed=true` on duplicates without re-applying state. `PaymentWebhookAckResponse.already_processed` added.
- **Tests:** `tests/test_webhook_security.py::test_webhook_is_idempotent_on_repeat_event_id`.

### 2.6 No rate limiting on auth endpoints — **DONE**

- **Traces to:** `apps/api/src/caseops_api/api/routes/auth.py`, `.../bootstrap.py`
- **Landed:** `slowapi` added; per-IP limiter on `/api/auth/login` (default 20/min) and `/api/bootstrap/company` (default 10/hour). Limits are settings-driven (`CASEOPS_AUTH_RATE_LIMIT_LOGIN_PER_MINUTE`, `..._BOOTSTRAP_PER_HOUR`, `..._ENABLED`). Exceeding returns `429`.
- **Tests:** `tests/test_rate_limiting.py` (2 cases). Default conftest disables the limiter to keep the broader suite stable; the rate-limit tests opt in.

### 2.7 No password policy — **DONE**

- **Traces to:** `apps/api/src/caseops_api/services/identity.py` (registration path)
- **Landed:** New `core/password_policy.py` enforces min 12, max 128, upper/lower/digit/symbol, no whitespace. Applied on `register_company_owner` and `create_company_user`. Weak passwords return `400` with a specific message.
- **Tests:** `tests/test_password_policy.py` (11 cases covering policy unit rules + API routes).

### 2.8 Provider payload is persisted raw — **DONE**

- **Traces to:** `apps/api/src/caseops_api/services/payments.py:186` writes `provider_payload_json` directly.
- **Landed:** `redact_provider_payload` in `services/pine_labs.py` replaces known-sensitive fields (`card_*`, `cvv*`, `vpa`, `customer_email`, `customer_phone`, `pan`, `aadhaar`, `otp`) with `[redacted]` at any nesting depth before storage on both `MatterInvoicePaymentAttempt.provider_payload_json` and `PaymentWebhookEvent.payload_json`.
- **Tests:** `tests/test_webhook_security.py::test_webhook_redacts_sensitive_fields_before_persistence` asserts sensitive values never land in either table.

---

## 3. P0 — Frontend rebuild

> **Status (Phase 3, 2026-04-17):** §3.1–3.4 **landed**. Legacy single-page console moved to
> `/legacy`; new app shell, Matter Cockpit with 5 tabs (Overview, Documents, Hearings,
> Billing, Audit), sign-in page with zod + RHF, TanStack Query data layer, and DataTable
> primitive. Roadmap stubs for Hearings, Research, Drafting, Recommendations, Contracts,
> Outside Counsel, Portfolio, Admin. 3 new Playwright specs, 10/10 e2e green, 101/101 pytest
> green. §3.5 (portfolio-wide DataTable reuse) started; §3.6 (role-aware UI), §3.7 (a11y
> baseline), §3.8 (error states), §3.9 (component tests) deferred.

The user has rejected the original UI. A targeted rebuild is mandatory. This is the largest single workstream.

### 3.1 Replace the monolithic `page.tsx` — **DONE**

- **Traces to:** (pre-rebuild) `apps/web/app/page.tsx` (5,965 lines)
- **Landed:** legacy UI preserved at `/legacy` (kept so founder-mode flows like bootstrap still work). New App Router tree under `/app`: dashboard, `/app/matters`, `/app/matters/[id]` with nested `documents/`, `hearings/`, `billing/`, `audit/`. Stubs for `/app/hearings`, `research`, `drafting`, `recommendations`, `contracts`, `outside-counsel`, `portfolio`, `admin`. No single component exceeds 300 lines. Public `/sign-in` page with RHF + zod.
- **Remaining from the original "Done when" list:**
  - Next.js App Router used for real routing. Route tree at minimum:
    - `/` (home dashboard, persona-aware: law-firm / GC / solo, per PRD §8.3)
    - `/matters` and `/matters/[id]` (Matter Cockpit spine)
    - `/matters/[id]/documents`, `/matters/[id]/hearings`, `/matters/[id]/drafts`, `/matters/[id]/recommendations`, `/matters/[id]/billing`, `/matters/[id]/audit`
    - `/hearings` (portfolio-level)
    - `/research`
    - `/drafting`
    - `/recommendations`
    - `/contracts` and `/contracts/[id]`
    - `/outside-counsel` and `/outside-counsel/[id]`
    - `/portfolio`
    - `/admin` and its sub-routes (users, SSO, AI policy, audit export, billing)
  - `page.tsx` reduced to a persona-selecting home; all other surface lives under dedicated route modules.
  - No component in the tree exceeds 300 lines.

### 3.2 Adopt a component library and design system — **DONE**

- **Landed:** Tailwind v4 `@theme` tokens (color, font, radius, shadow), Radix primitives (Dialog, Dropdown, Tabs, Avatar, Label, Select, Slot, Tooltip), `@tanstack/react-query` + `@tanstack/react-table`, `react-hook-form` + `zod` + `@hookform/resolvers`, `sonner` toasts, `lucide-react` icons, `class-variance-authority` + `tailwind-merge`. All at latest stable. Shadcn-style `components/ui/` primitives (Card, Input, Label, Textarea, Select, Tabs, Dialog, DropdownMenu, Avatar, Skeleton, EmptyState, StatusBadge, PageHeader, DataTable).
- **Deferred:** `@testing-library/react` + Playwright component tests — §3.9.

### 3.3 State and data layer — **DONE**

- **Landed:** `lib/api/client.ts` typed `apiRequest` with auth header injection + RFC-like error normalization. `lib/api/schemas.ts` zod schemas for `AuthSession`, `AuthContext`, `Matter`, `MattersList`. `lib/api/endpoints.ts` typed `signIn`, `fetchAuthContext`, `listMatters`, `fetchMatter`, `fetchMatterWorkspace`, `createMatter`. `lib/session.ts` with localStorage + event-bus and `lib/use-session.ts` hook (single source). `AppProviders` mounts `QueryClient` with sane defaults. No duplicate fetchers; TanStack Query cache keys: `["matters", "list"]`, `["matters", id, "workspace"]`.

### 3.4 Matter Cockpit (primary spine) — **DONE (v1)**

- **Landed:** `/app/matters/[id]/layout.tsx` fetches `/api/matters/{id}/workspace` once; nested routes for Overview, Documents, Hearings, Billing, Audit all read the same cache. Header shows parties, status, practice area, court, next hearing, matter code. Overview: summary, latest court order, open tasks, upcoming hearings, recent activity, recent notes. Audit tab renders the full activity timeline. Hearings tab renders cause-list imports, orders, and scheduled hearings. Billing tab computes totals (billed, collected, balance, billable minutes) and lists invoices + recent time entries. Empty states on every tab; all driven by real API data. Renders correctly for matters with zero data and for loaded matters.
- **Deferred:** Drafts, Research, Recommendations tabs — blocked on their respective backends (§4.3, §4.2, §4.4).

### 3.5 Tables everywhere that today are timeline-cards

- **Traces to:** `apps/web/app/page.tsx:4761-4934` (counsel), `3478+` (billing), `3780+` (matters); PRD §10 "dense, professional workflows"
- **Problem:** Lists are static vertical cards. No sort, filter, column config, row selection, bulk actions, pagination.
- **Done when:**
  - `DataTable` component (TanStack Table) reused across Matters, Invoices, Contracts, Outside Counsel, Recommendations, Hearings, Authorities.
  - Server-side pagination and filtering on all list endpoints (see §6 for API work).

### 3.6 Role-aware UI

- **Traces to:** `apps/web/app/page.tsx:1033-1037` (single role check)
- **Problem:** Partner, associate, paralegal see identical forms.
- **Done when:**
  - Role-capability map (Owner / Admin / Partner / Senior / Junior / Paralegal / GC / Ops / Auditor / Billing / OutsideCounselViewer) drives navigation and action visibility.
  - Admin routes hidden for non-admins server-side (not just UI-hidden).

### 3.7 Accessibility baseline

- **Traces to:** `apps/web/app/globals.css` (no `:focus-visible`), no ARIA labels, no `<h1>`; PRD §19.7 Accessibility
- **Done when:**
  - Keyboard navigation works across all primary flows (create matter, upload doc, draft, approve invoice).
  - All form inputs have associated labels and error announcements.
  - Heading hierarchy is correct on every route.
  - Axe CI check passes with zero critical violations on the spine routes.

### 3.8 Error, empty, and loading states

- **Traces to:** `apps/web/app/page.tsx:1226-1247` (errors swallowed silently)
- **Done when:**
  - Every query has defined loading, empty, and error presentation. Errors surface recovery actions.

### 3.9 Frontend tests

- **Done when:**
  - Component tests for critical forms (matter intake, contract upload, invoice approval, user invite).
  - Playwright spec per persona home (law firm, GC, solo) replaces the single giant `auth-admin.spec.ts`.

---

## 4. P0 — AI core (LLM, drafting, recommendations)

Without this, the PRD's central promise does not exist.

### 4.1 LLM integration

- **Traces to:** `apps/api/pyproject.toml` (no SDK); PRD §12.1, §3.5
- **Problem:** No Anthropic/OpenAI/vLLM SDK. All "generation" is deterministic string assembly in `services/briefing.py`, `services/matter_review.py`, `services/contract_review.py`.
- **Done when:**
  - `services/llm.py` abstracts a single provider interface (`generate`, `rerank`, `embed`) with provider pluggability.
  - Default provider wired to Anthropic (per PRD model portfolio, or substitute per founder decision); enterprise routing flag points to self-hosted endpoint.
  - Token usage and latency captured per call and written to `ModelRun` (see §7.3).
  - Prompt templates version-controlled in `apps/api/src/caseops_api/prompts/`.

### 4.2 Proper RAG

- **Traces to:** `docker-compose.yml:56` (pgvector installed but unused); `services/retrieval.py:53-289` (TF-IDF + hardcoded synonyms)
- **Problem:** No embeddings, no ANN index.
- **Done when:**
  - `authority_document_chunk` and `matter_attachment_chunk` gain an `embedding` vector column and HNSW/IVFFLAT index.
  - Embedding generation is a worker job with backfill support.
  - `services/retrieval.py` combines hybrid lexical + vector scoring; tenant/matter scoping enforced in SQL (not in application code only).
  - Per-tenant namespacing decision recorded: authority corpus shared vs. tenant-private (PRD §13.2).

### 4.3 Drafting Studio

- **Traces to:** PRD §9.5, §10.3; no draft tables today
- **Problem:** Core PRD feature absent.
- **Done when:**
  - Schema: `Draft`, `DraftVersion`, `DraftReview` tables with cascading and audit fields.
  - API: `/matters/{id}/drafts` CRUD; submit-for-review, request-changes, approve, finalize state machine.
  - Service: `services/drafting.py` assembles prompt from matter context + retrieved authorities + selected template; invokes LLM; returns draft with inline citation anchors.
  - Export: DOCX and PDF export (use `python-docx` and `weasyprint` or similar).
  - Frontend: `/matters/[id]/drafts` editor with version diff, reviewer approve/reject.
  - Safety: every draft carries a `draft` status until explicit approval (PRD §9.5 acceptance criterion).

### 4.4 Recommendation engine

- **Traces to:** PRD §9.7, §11, §23.1; no recommendation tables today
- **Problem:** Headline differentiator absent.
- **Done when:**
  - Schema: `Recommendation`, `RecommendationOption`, `RecommendationDecision` tables. Fields match PRD §23.1 schema: `type`, `title`, `options[]`, `primary_recommendation`, `rationale`, `citations[]`, `assumptions[]`, `missing_facts[]`, `confidence`, `next_action`, `review_required`.
  - Types supported in v1: forum, remedy, authority, next-best action, outside counsel. Settlement/escalation deferred.
  - Pipeline: rules → retrieval → ranker → explanation, per PRD §11.3.
  - User accept/reject/edit captured as `RecommendationDecision`; stored for HITL training (§7.3).
  - Guardrail: no recommendation without at least one supporting authority; `review_required=True` on any client-facing final recommendation.

### 4.5 Hearing preparation — full workflow

- **Traces to:** `services/briefing.py` (today: read-only summary); PRD §9.6, §10.4
- **Problem:** Generates text blocks; does not generate a hearing pack.
- **Done when:**
  - Schema: `HearingPack`, `HearingPackItem` (chronology item, last-order summary, pending-compliance item, issue, opposition point, authority card, oral point).
  - Auto-generation on `MatterHearing` creation or within N days of `next_hearing_on`.
  - Post-hearing: outcome capture → auto-creates follow-up tasks and proposes next-hearing date.

### 4.6 Citation verification and refusal logic

- **Traces to:** PRD §11.5, §17.4
- **Done when:**
  - Before any LLM output is returned, cited authorities are verified to exist and to contain the cited proposition (string match or second-pass verifier model).
  - Low-evidence or contradictory-evidence prompts return an explicit uncertainty response, not a confident answer.
  - Test suite covers hallucination, low-context refusal, and contradictory authority surfacing (PRD §19.6.1–19.6.3).

---

## 5. P1 — Workflow & agent infrastructure

### 5.1 Temporal for durable workflows

- **Traces to:** PRD §3.4, §14.4; `apps/api/src/caseops_api/workers/document_processor.py`
- **Problem:** Custom DB-polling worker; stale-job recovery is manual; no replay.
- **Done when:**
  - Temporal deployed (docker-compose entry + Cloud Run/GKE manifest path).
  - Workflows ported: `DocumentIngestionWorkflow`, `CourtSyncWorkflow`, `DraftingWorkflow`, `HearingPackWorkflow`, `RecommendationWorkflow`.
  - Each workflow has explicit retry policy, timeouts, and a versioning strategy.
  - Old custom-polling worker retired.

### 5.2 Grantex (or equivalent) agent identity

- **Traces to:** PRD §3.4, §13.5, §23.2; no agent tables today
- **Problem:** Cannot safely run autonomous agents.
- **Done when:**
  - Schema: `AgentGrant`, `AgentExecution`, `AgentToolCall` tables with scopes, expiry, budget, revocation timestamp.
  - Every agent-initiated DB write passes through a scope check; denied attempts logged.
  - PRD-listed scopes modeled: `matter.read`, `document.read`, `draft.write`, `recommendation.generate`, `external.share`, `email.send`.
  - Approval gates: actions requiring human approval block until a `HumanApproval` record is created.
  - Tests cover unauthorized tool call, forged grant, expired grant, budget overrun, revoked grant.

### 5.3 Notification service

- **Traces to:** PRD §9.10 fee-collection, PRD §9.2 invitations; today `payments.py` generates a link but never emails it
- **Done when:**
  - `services/notifications.py` with transactional email backend (SendGrid/SES).
  - Templates: user invite, password reset, invoice issued, invoice reminder, payment receipt, upcoming hearing reminder, approval request.
  - Delivery is a Temporal activity with retry.
  - Per-tenant sender domain config and DKIM/SPF documented.

### 5.4 Unified audit service

- **Traces to:** PRD §15.4, §17.2; today audit is scattered across `MatterActivity`, `ContractActivity`, `MatterInvoicePaymentAttempt`
- **Problem:** No system-wide trail. Company profile edits, user suspensions, authority ingests, admin policy changes are not audited.
- **Done when:**
  - `AuditEvent` table with: `actor_type` (human|agent|system), `actor_id`, `tenant_id`, `matter_id?`, `action`, `target_type`, `target_id`, `result`, `metadata`, `approval_chain?`, `timestamp`.
  - Write-once constraint (no UPDATE/DELETE from application code; optional append-only enforced via DB role).
  - Every write path in `services/` emits an audit event via a shared helper.
  - `/admin/audit/export` endpoint returns tenant-scoped audit data (JSONL, time-bounded).

### 5.5 Token revocation + session management

- **Traces to:** §2.3 above
- **Done when:** refresh-token rotation with short-lived access tokens; `revoked_tokens` table or `sessions_valid_after` on membership; logout endpoint revokes refresh token.

### 5.6 Ethical walls and matter-level ACL

- **Traces to:** PRD §13.4; today only `assignee_membership_id` exists
- **Done when:**
  - Schema: `MatterAccessGrant` (matter_id, principal_type user|team, principal_id, access_level) and `EthicalWall` (matter_id, excluded_principal_type, excluded_principal_id, reason).
  - All matter queries filter by explicit access grants, not just company_id.
  - Tests: user with broad role denied on walled matter; ethical-wall violation logged and blocked.

### 5.7 Teams

- **Traces to:** PRD §4, §13.4, §15.1
- **Done when:** `Team`, `TeamMembership` tables; team-scoped matter access; UI to manage teams.

---

## 6. P1 — API hygiene

### 6.1 Pagination on every list endpoint

- **Traces to:** All of `apps/api/src/caseops_api/api/routes/*.py`
- **Problem:** `list_matters`, `list_contracts`, `list_authorities`, etc., return whole tables. A 1,000-matter firm will hit both DB and UI hard.
- **Done when:**
  - Keyset or cursor pagination added to all list endpoints, with a consistent `limit`/`cursor` contract.
  - Default limit 50, max 200. Documented in OpenAPI.

### 6.2 Role-based dependency decorators

- **Traces to:** `apps/api/src/caseops_api/api/dependencies.py`; manual role checks in `services/identity.py:209,230,293`
- **Problem:** Every route author must remember to check role. Some forget (review needed).
- **Done when:**
  - `require_role(...)` and `require_capability(...)` FastAPI dependencies exist and are used across all mutating routes.
  - Lint rule or test sweep verifies no mutating endpoint lacks a role guard.

### 6.3 Input validation at boundaries

- **Traces to:** route files; Pydantic handles most, but free-text fields are unbounded
- **Done when:**
  - Max lengths on all string fields.
  - File-upload MIME whitelist and magic-byte verification (not just extension).
  - Sanitizer on any field rendered back to HTML on the frontend.

### 6.4 Structured error responses

- **Done when:** All errors return RFC 7807 problem-details shape (`type`, `title`, `status`, `detail`, `instance`). Frontend renders machine-readable `type` for actionable UX.

### 6.5 OpenAPI quality

- **Done when:** Every endpoint has a description, response examples, and machine-readable error codes. A typed TS client is generated from it (or hand-kept in lockstep).

---

## 7. P1 — Data model additions

Beyond what §4 and §5 add.

### 7.1 First-class Court, Bench, Judge

- **Traces to:** PRD §10.6, §15.1; today `judge_name`, `court_name` are strings on `Matter`, `MatterCauseListEntry`, `MatterCourtOrder`
- **Done when:**
  - `Court`, `Bench`, `Judge` master tables.
  - Migration upgrades existing string references to FK where resolvable; unresolved strings kept in a side column for manual matching.
  - Judge profile aggregation endpoint (authored orders, citation trends) — no favorability scoring (PRD §10.6 guardrail).

### 7.2 Task, Deadline, Obligation

- **Traces to:** PRD §10.1, §9.6 post-hearing tasks, §10.7 contract obligations (exists only for contracts)
- **Done when:**
  - Generic `Task` with `assignee`, `due_on`, `status`, `source` (hearing, draft review, intake, contract obligation).
  - Deadline reminders wired to notification service.

### 7.3 Model runs and evaluation

- **Traces to:** PRD §12.7, §17.4
- **Done when:**
  - `ModelRun` records every LLM call (prompt hash, model id, tokens, cost, latency, tenant, matter).
  - `EvaluationRun` records benchmark runs (citation accuracy, hallucination rate, extraction accuracy).
  - Admin UI can gate a new model version behind a passing evaluation.

### 7.4 Statute, Section, Issue, Relief

- **Traces to:** PRD §15.1
- **Done when:** master tables exist; matter-to-issue and matter-to-relief linkage tables exist; research engine can filter by statute/section.

### 7.5 Consistency sweep

- **Done when:**
  - All tables use `DateTime(timezone=True)` consistently; `Date` is reserved only for legally meaningful dates (decision_date, next_hearing_on).
  - Every mutable entity has `created_at` and `updated_at`.
  - Soft-delete policy decided: either all-hard (documented) or `deleted_at` columns on `Matter`, `Contract`, `Document`.

---

## 8. P1 — Observability and operations

### 8.1 OpenTelemetry

- **Traces to:** PRD §14.4, §18.2; `pyproject.toml` has no OTEL packages
- **Done when:**
  - `opentelemetry-instrumentation-fastapi`, `...-sqlalchemy`, `...-httpx`, `...-logging` added.
  - Traces exported to OTLP collector; spans include `tenant_id`, `matter_id` (when in scope), `user_id`, `model_id`, `tool_name`.
  - Dashboards track PRD §18.2 signals: API latency, queue depth, failed workflows, retrieval latency, model latency, token cost, document parse failures, auth failures, grant issuance.

### 8.2 Structured logging with tenant context

- **Done when:**
  - JSON logs with `tenant_id`, `request_id`, `user_id`, `matter_id` on every log line during request scope.
  - PII redaction middleware on outbound logs (emails, payment payloads).

### 8.3 Backups and restore

- **Traces to:** PRD §18.3
- **Done when:**
  - Daily Cloud SQL automated backups; monthly restore drill documented.
  - GCS versioning enabled on document buckets; lifecycle policy for soft-deleted objects.
  - Tenant-scoped export job produces a signed archive; tested end-to-end.

### 8.4 CI/CD

- **Traces to:** `infra/` has Cloud Run manifests, no GitHub Actions today
- **Done when:**
  - GitHub Actions pipeline: lint (ruff, eslint, tsc), test (pytest, playwright), build images, push to Artifact Registry, deploy to staging Cloud Run.
  - Required status checks on PRs; `main` protected.
  - Alembic migration check fails PR if `revision` is missing or out-of-order.

### 8.5 Secret management

- **Done when:**
  - Cloud Run manifest references Secret Manager for `auth_secret`, `pine_labs_*`, LLM keys.
  - Rotation runbook in `docs/runbooks/secret-rotation.md` (to be authored when §11.3 is done).
  - Local `.env.example` lists every CASEOPS_ env var (sync with `settings.py`).

---

## 9. P1 — Document intelligence depth

### 9.1 Broader parsers

- **Traces to:** PRD §14.4 lists Docling, Apache Tika, Tesseract, PaddleOCR; today only `pdfminer.six`, `pypdfium2`, Tesseract
- **Problem:** DOCX contracts, scanned mixed-layout PDFs, emails are parsed poorly or not at all.
- **Done when:**
  - Docling added for rich PDF/DOCX structural parsing.
  - Tika fallback for legacy formats.
  - PaddleOCR option enabled for scanned Indian-language pages.
  - `DocumentProcessingJob` records which parser was used.

### 9.2 Structural extraction

- **Done when:**
  - Legal document structural extractors (party detection, date normalization, clause segmentation) replace regex-based chunking.
  - Contract clause extraction uses LLM with structured output (JSON schema), not current heuristics (`services/contract_review.py`).

### 9.3 Virus scanning

- **Traces to:** PRD §17.2
- **Done when:** ClamAV or vendor scanning step in the ingestion workflow; infected uploads quarantined and audited.

---

## 10. P2 — Admin & governance console

### 10.1 Company / tenant management

- **Traces to:** PRD §9.1, §10.9
- **Done when:** Admin UI covers: company profile, branding, timezone, plan & billing, data region, retention, deletion/export workflows.

### 10.2 SSO

- **Traces to:** PRD §13.3
- **Done when:** OIDC and SAML with per-tenant provider config; JIT user provisioning via IdP claims; scope-to-role mapping.

### 10.3 AI policy controls

- **Traces to:** PRD §17.4
- **Done when:**
  - Tenant policy table for: allowed models, allowed providers, max tokens per session, external-share approval requirement, training-data opt-in.
  - Enforcement middleware refuses calls that violate tenant policy.
  - Prompt and tool-call audit is queryable by admins.

### 10.4 Audit export

- **Traces to:** §5.4, PRD §17.3
- **Done when:** Admins can export JSONL/CSV of `AuditEvent` filtered by time window; download is itself audited.

### 10.5 Plan entitlements

- **Done when:** Entitlement enforcement (seat limits, matter limits, feature flags) driven by plan record.

---

## 11. P2 — Testing coverage

### 11.1 Tenant-leakage tests — **INITIAL COVERAGE LANDED**

- **Traces to:** PRD §19.3
- **Landed:** `tests/test_tenant_isolation.py` — 8 tests: two companies bootstrapped side-by-side; cross-tenant access to matter list / matter-by-id / matter mutation / contract list / contract read / company profile / user directory / user suspension / invoice payment-link is denied. All pass (403/404).
- **Still to do:** extend to documents (GCS object access, signed URLs), search-result filtering, audit-log scope, vector embeddings when those land, and agent grants (blocked on §5.2).

### 11.2 Authorization matrix tests

- **Done when:** Parametrized tests over (role, endpoint, expected status). Sweeps horizontal/vertical escalation and suspended-user scenarios.

### 11.3 Agent/Grantex tests

- **Traces to:** PRD §19.4
- **Done when:** All scenarios from PRD §19.4 covered (issue, expiry, revocation, out-of-scope, unauthorized tool, approval block, audit record, budget enforcement).

### 11.4 AI safety tests

- **Traces to:** PRD §19.6
- **Done when:** Citation accuracy benchmark, hallucination under low context, refusal on weak evidence, prompt-injection resistance, data-exfiltration red-team tests are automated and run in CI.

### 11.5 Payment tests

- **Done when:** Webhook signature bypass, replay, cross-tenant, idempotency, refund/dispute state, and missing-secret cases all asserted.

### 11.6 E2E coverage

- **Traces to:** `tests/e2e/`
- **Done when:** Each PRD UAT scenario (§19.8) has a Playwright spec that exercises it end-to-end (law firm journey, GC journey, solo journey).

### 11.7 Accessibility

- **Done when:** `@axe-core/playwright` run on every route; zero critical violations on spine routes.

---

## 12. P2 — Court integrations and data sources

### 12.1 Jurisdiction coverage per PRD §3.7

- **Done when:** Integration adapters exist for:
  - Delhi / NCR (District + High Court), Maharashtra, Karnataka, Telangana
  - Supreme Court of India
- Tamil Nadu, Gujarat feature-flagged.
- Each adapter has health state and per-tenant credentials (PRD §16.3).

### 12.2 Connector health UI

- **Done when:** `/admin/integrations` shows per-connector status, last successful sync, failure reason.

### 12.3 Email and calendar

- **Done when:** At least one email ingest (for intake) and one calendar sync (for hearing dates) are live.

---

## 13. P3 — Enterprise / post-launch

These are explicitly deferred by PRD §20.5.

- Private / self-hosted inference stack (enterprise inference offering).
- Advanced SSO (cross-domain trust, SCIM provisioning).
- Dedicated tenant adapters and private VPC deployment.
- vLLM / llama.cpp local-inference path.
- OpenSearch if Postgres hybrid search saturates.
- Broader secondary jurisdiction rollout (Tamil Nadu, Gujarat) to full parity.

---

## 14. PRD § coverage matrix

| PRD § | Area | Today | Target |
| --- | --- | --- | --- |
| §8 IA, §8.2 Workspaces | 10 top-level sections | 6 sections as anchors | §3.1 routing, §3.4 cockpit |
| §9.1 Onboarding wizard | — | Basic bootstrap only | §10.1 admin console |
| §9.4 Research | Lexical + synonym map | Hybrid vector + lexical | §4.2 |
| §9.5 Drafting | — | Not built | §4.3 |
| §9.6 Hearing prep | Read-only brief | Full hearing pack + post-hearing | §4.5 |
| §9.7 Recommendations | — | Not built | §4.4 |
| §9.8 Contract review | Heuristic clause detection | LLM structured extraction | §9.2 |
| §9.10 Billing | Invoices + Pine Labs | Reminders, collections, aging, profitability | §5.3 notifications; §10.1 admin |
| §10.6 Judge/Court intel | Strings only | Master tables + profile | §7.1 |
| §11 Recommendation engine | — | Full pipeline | §4.4 |
| §12 Model strategy | No LLM | Providers + RAG + LoRA path | §4.1, §4.2, §7.3 |
| §13.3 MFA, SSO | Local password | MFA + OIDC/SAML | §2.7, §10.2 |
| §13.4 Ethical walls | — | Matter ACL + walls | §5.6 |
| §13.5 Grantex | — | Agent identity + scopes | §5.2 |
| §14.4 Docling/Tika | Missing | Added | §9.1 |
| §14.4 OpenTelemetry | Missing | Added | §8.1 |
| §15.1 Entities | ~60% | Remaining entities | §7 |
| §15.4 Audit | Scattered | Unified AuditEvent | §5.4 |
| §17.4 AI governance | — | Tenant policy + prompt audit | §10.3 |
| §18.3 Backup/restore | Implicit | Documented + drilled | §8.3 |
| §19.3 Tenant leakage tests | Absent | Present | §11.1 |
| §19.4 Grantex tests | Absent | Present | §11.3 |
| §19.6 AI safety tests | Absent | Present | §11.4 |

---

## 15. Suggested sequencing

The items above do not need to ship together. A plausible order, given founder-stage constraints:

**Sprint A (2 weeks) — security hardening only.** §2.1 through §2.8. Do not touch features. Ship a patch release.

**Sprint B–C (4 weeks) — frontend spine.** §3.1, §3.2, §3.3, §3.4 (Matter Cockpit), §3.5 DataTable. Retire the 5,965-line `page.tsx`.

**Sprint D–E (4 weeks) — AI core v1.** §4.1 LLM, §4.2 RAG, §4.4 Recommendation (forum + authority types only), §4.6 citation verification. Unblock the PRD's headline promise.

**Sprint F (2 weeks) — drafting v1.** §4.3 basic draft generation + version history + DOCX export.

**Sprint G–H (4 weeks) — governance and agents.** §5.2 Grantex (or equivalent), §5.4 AuditEvent, §5.6 ethical walls, §10.3 AI policy. Pre-requisite for any enterprise pilot.

**Sprint I (2 weeks) — observability.** §8.1 OTEL, §8.2 logging, §8.4 CI/CD.

**Sprint J onward — Temporal, SSO, Admin console, broader court integrations, full test matrix.**

Re-order as founder priorities dictate. The critical insight is that **Sprint A is a prerequisite for any external traffic** and **Sprint B-E are prerequisites for a believable product demo**.

---

## 16. Explicit non-goals for now

These items are PRD-scoped but should not be started yet:

- Foundation model training (PRD §12.2 explicitly excludes).
- Autonomous filing in court (PRD §6.3 non-goal).
- Judge favorability scoring (PRD §6.3, §10.6 non-goal).
- Solo self-serve tier launch (PRD §22.2 open question).
- On-prem air-gapped deployment (PRD §20.5, not before enterprise).

---

## 17. Open questions for founder

Items whose resolution changes the plan:

1. **Authority corpus model.** Shared global corpus (current default, simpler) or per-tenant namespaces (PRD §13.2 implies). Decision affects §4.2 schema.
2. **LLM provider.** Anthropic hosted, OpenAI hosted, or self-hosted open model (Gemma / gpt-oss-20b per PRD §3.5). Decision affects §4.1 and §10.3.
3. **SSO priority.** Is OIDC+SAML required for first paying customer, or deferrable?
4. **Commercial packaging.** Per-seat / per-matter / hybrid (PRD §22.2 open). Affects §10.5 entitlements.
5. **Grantex deployment.** Is there an existing Grantex service, or do we build a minimal internal equivalent?
6. **Drafting exports.** DOCX-only for v1, or PDF-parity from day one?

---

## 18. Definition of "done" for this document

This work plan is complete when, for every P0 and P1 item, either:

- a PR has landed that satisfies the "Done when" criteria, and
- the item is crossed out with the commit SHA, or
- the founder has explicitly deferred it and this doc is updated to reflect the new priority.
