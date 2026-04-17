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

The backend has a respectable Phase-0/early-Phase-1 foundation: matter workspace, documents, contracts, billing with Pine Labs, and authority ingestion are real. Multi-tenant scoping is consistently threaded through services via `SessionContext`. Alembic migrations are clean (now at `20260417_0003`).

However, three very large gaps exist between the PRD and the product:

1. **The frontend is a prototype, not a product.** The entire web app is one 5,965-line `apps/web/app/page.tsx` with anchor-link navigation, 26+ `useState` hooks, no component decomposition, and an information architecture that covers 6 of the PRD's 10 top-level sections. The user has explicitly said the UX is unacceptable.
2. **The PRD's AI promise is unbuilt.** There is no LLM integration anywhere in the codebase, no Drafting Studio, no Recommendation Engine, no Grantex agent identity, no Temporal, and no proper RAG (pgvector is installed but unused; "semantic" search is a hardcoded synonym map).
3. **Several security and governance primitives are missing.** System-wide audit trail, token revocation on suspend, webhook idempotency, MFA, rate limiting, password policy, and a cross-tenant check on the payment webhook path.

This document enumerates the work needed to close these gaps, in priority order, with acceptance criteria per item.

### 1.1 Shipped-phase ladder (as of 2026-04-17)

| Phase | Commit | Scope | PRD sections closed |
| --- | --- | --- | --- |
| Phase 2 | `b990da4` | Security hardening: webhook auth, JWT key, session revocation, cross-tenant webhook, idempotency, rate limit, password policy, payload redaction | §2.1–§2.8 |
| Phase 3.1–3.4 | `aa1a7c1` | Frontend rebuild: App Router spine, Matter Cockpit v1, sign-in, TanStack Query data layer | §3.1–§3.4 |
| Phase 4A | `ee158f7` | AI core: LLM provider abstraction, ModelRun audit, Recommendation engine v1 (forum + authority), citation verification, refusal logic | §4.1, §4.4, §4.6, §7.3 (partial) |
| Phase 5 | `5f0b555` | Impeccable design refresh: Caslon + Atkinson + JetBrains Mono, OKLCH palette, tabular figures, reduced-motion | §3.10 |
| Phase 6 | `ced5780` | DataTable reuse on Contracts + Outside Counsel, role-aware UI via capability map | §3.5, §3.6 (partial) |
| Phase 7 | `4359c30` | RAG foundation: pgvector + HNSW, EmbeddingProvider, streaming S3 corpus ingest with disk cap | §4.2 (partial) |
| Phase 8 | `1913a11` | OCR fallback (RapidOCR), native pgvector `<=>` retrieval, multi-year CLI, chunk-flush fix | §4.2 (extended) |
| Phase 9 | `f8a502c` | Keyset cursor pagination API+UI, 29-HC `HC_COURT_CATALOG`, `--hc-courts` CLI flag | §6.1 |

Still open P0 by coverage: §3.7 a11y, §3.8 error/empty states, §3.9 frontend tests, §4.3 Drafting Studio, §4.5 Hearing pack workflow. Still open P1 spine: §5.1 Temporal, §5.2 Grantex, §5.3 notifications, §5.4 unified audit, §5.6 ethical walls, §6.2 role dependency decorators, §7.1 Court/Bench/Judge, §7.3 EvaluationRun, §8.1 OTEL, §8.4 CI/CD.

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

### 3.5 Tables everywhere that today are timeline-cards — **PARTIAL (Phase 6, 2026-04-17)**

- **Landed:** `/app/contracts` and `/app/outside-counsel` are now real pages backed by `/api/contracts/` and `/api/outside-counsel/workspace`. Both use the `DataTable` primitive with sort / filter / pagination. Counsel page carries four KPI cards (profiles, active assignments, approved spend, total spend). Typed via zod in `lib/api/schemas.ts` and wired through the cached TanStack Query layer.
- **Remaining:** Invoices table in the Matter Cockpit billing tab (already right-aligned + tabular after Phase 5 but not routed through `DataTable` — acceptable at per-matter scale), authorities portfolio, portfolio-wide hearings. Server-side pagination is still client-side today.

### 3.6 Role-aware UI — **PARTIAL (Phase 6, 2026-04-17)**

- **Landed:** `lib/capabilities.ts` enumerates Capabilities (13 today) and maps them to the three runtime roles (owner / admin / member). `useCapability` hook + `useRole` hook available to any client component. Sidebar Admin entry is hidden for members. Matters page `New Matter` button is gated on `matters:create`. Empty state copy adapts to capability. Server is still the source of truth — UI gating is alignment, not enforcement.
- **Remaining:** Roles beyond owner/admin/member (Partner / Senior / Junior / Paralegal / GC / Ops / Auditor / Billing / OutsideCounselViewer from the PRD) need schema support in the API before we can gate UI against them. Team-scoping and ethical walls (§5.6) are the prerequisites for matter-level gates.

### 3.7 Accessibility baseline — **DONE v1 (Phase 10, 2026-04-17)**

- **Traces to:** PRD §19.7; `apps/web/app/globals.css`, `components/ui/SkipLink.tsx`, `tests/e2e/a11y.spec.ts`.
- **Landed:**
  - Global `:focus-visible` ring (2px brand-500 outline, 2px offset) in `globals.css`; Select trigger migrated from `focus:` to `focus-visible:` for consistency.
  - `SkipLink` component on the marketing landing, sign-in, and `/app` shells targets `#main`; `<main id="main" tabIndex={-1}>` accepts programmatic focus after skip.
  - Sidebar already uses `<aside aria-label="Primary navigation"><nav>…</nav></aside>`; `<html lang="en">` set at the root layout.
  - Exactly one `<h1>` per route: `PageHeader` always renders `<h1>`; `CardTitle` is polymorphic (`as="h1" | "h2" | "h3" | "h4"`), sign-in uses `<h1>` for its page heading, and the dashboard cards emit `<h2>` for section titles.
  - Form a11y: `SignInForm` + `NewMatterDialog` inputs now set `aria-invalid={invalid || undefined}` and `aria-describedby` linked to an error `<p id="…-error" role="alert">` that screen readers announce on submit.
  - `DataTable` rows with `onRowClick` expose `role="button"`, `tabIndex=0`, and an `onKeyDown` handler that activates on Enter/Space with a visible focus ring. Pagination buttons now carry `aria-label="Previous page"` / `"Next page"`.
  - Colour tokens darkened to satisfy 4.5:1: `--color-mute` 0.55→0.48, `--color-mute-2` 0.68→0.55, secondary `Button` shifted from `brand-500` to `brand-700`, "Most popular" pricing pill moved off `brand-500`.
  - `@axe-core/playwright` wired; `tests/e2e/a11y.spec.ts` fails the build on any `serious`/`critical` violation for `/`, `/sign-in`, `/app`, `/app/matters`, `/app/contracts`. All three suites currently pass.
- **Remaining:**
  - Keyboard-walkthrough specs for the full create-matter / upload / approve-invoice flows (axe is static-only).
  - Screen-reader spot-checks documented in a runbook.
  - Dashboard cockpit subsection headings (`<h3>` under `<h2>`) audit — currently emit one level deep where a proper `<h2>` would help.
  - ~~Known unrelated spine regression — fixed in phase 12 (queryKey collision between dashboard `useQuery` and matters `useInfiniteQuery`). Full app Playwright suite is 21/21 green as of phase 12.~~

### 3.8 Error, empty, and loading states — **DONE v1 (Phase 11, 2026-04-17)**

- **Traces to:** PRD §19; `components/ui/QueryErrorState.tsx`, `components/app/OfflineBanner.tsx`, `app/app/error.tsx`, `app/app/loading.tsx`, `app/app/matters/[id]/not-found.tsx`, `app/not-found.tsx`, `lib/api/config.ts`, `tests/e2e/query-states.spec.ts`.
- **Landed:**
  - New `QueryErrorState` component: branded EmptyState + "Try again" button wired to react-query's `refetch()`; escalates to "Workspace is offline" copy + icon when the error is a `NetworkError`; supports an optional `secondaryAction` slot for dead-end paths (404, forbidden) where a retry makes no sense.
  - All list error states now use it with `onRetry` from the query: `/app/matters`, `/app/contracts`, `/app/outside-counsel`, the `/app` dashboard, the matter cockpit layout, and the matter recommendations page (previously silently printed "Loading recommendations…" on error).
  - Segment-level Next.js boundaries: `app/app/error.tsx` (reset + support mailto + digest), `app/app/loading.tsx` (skeleton), `app/not-found.tsx`, `app/app/matters/[id]/not-found.tsx`.
  - Matter cockpit layout now distinguishes 404 (API `ApiError.status === 404`) from other errors — 404 hides the retry button and shows "Back to matter portfolio" instead.
  - New `NetworkError` class in `lib/api/config.ts` + `isNetworkError()` helper; `apiRequest` wraps `fetch()` in try/catch and throws `NetworkError` for DNS/offline/CORS failures (previously raw `TypeError` leaked through).
  - `OfflineBanner` subscribes to the react-query cache and `navigator.onLine` / `online` / `offline` events; shows a calm amber stripe above the Topbar the moment either a network-flavoured error is unresolved OR the browser is offline, and auto-hides on recovery. Mounted in `app/app/layout.tsx`.
  - Tests: new `tests/e2e/query-states.spec.ts` stubs `/api/matters` to 500, `/api/contracts` to 503, asserts the UI surfaces the error copy + retry, clicks through, and asserts recovery — plus a 404 matter id test that asserts the branded not-found renders with the "Back to matter portfolio" link. All 3 pass. Full app suite: 16/18 green; the 2 failures are the pre-existing phase-9 spine regression already tracked in §3.7.
- **Remaining:**
  - Component-level tests for error copy (deferred to §3.9 Frontend tests).
  - Error-context enrichment: ship the Next `error.digest` to a Sentry-equivalent once OTEL lands (§8.1).
  - Persist in-flight toast notifications across the offline-banner transition so a dismissed success toast doesn't hide the banner arrival.

### 3.10 Impeccable design refresh — **DONE (Phase 5, 2026-04-17)**

- **Landed:** Type pair swapped off Inter via the impeccable font-selection procedure. **Libre Caslon Text** (display) + **Atkinson Hyperlegible** (UI body) + **JetBrains Mono** (tabular), all OFL, all served via `next/font/google` with `swap` strategy. Colour tokens migrated to OKLCH with neutrals tinted to the indigo brand hue (chroma 0.008, 265°); brand scale with reduced chroma at lightness extremes; shadows now in OKLCH alpha. Utilities added: `tabular`, `text-prose` (65ch), `text-prose-wide` (75ch), `font-display`. Tabular figures applied to the billing table, KPI cards, dashboard stats. Marketing hero now uses the Caslon display face for the "legal work" phrase. `prefers-reduced-motion` honoured globally in `@layer base`.
- **Verification:** `npm run typecheck:web` + `npm run build:web` clean; `npm run test:e2e:app` 10/10 passed.
- **Deferred:** `--space-*` 4-pt semantic tokens and a dark theme remain follow-ups (separate workstreams).

### 3.9 Frontend tests — **DONE v1 (Phase 12, 2026-04-17)**

- **Traces to:** PRD §19; `apps/web/vitest.config.ts`, `apps/web/vitest.setup.ts`, `tests/e2e/personas.spec.ts`.
- **Landed:**
  - Vitest + React Testing Library + jsdom harness wired via `apps/web/vitest.config.ts`; `npm run test:web` + `npm run test:watch`.
  - Component tests green (14 assertions across 4 suites):
    - `QueryErrorState` — retry flow, NetworkError copy, secondaryAction slot, no-op when onRetry is absent (5 cases).
    - `SignInForm` — zod validation with aria-invalid + aria-describedby correctly linked, happy-path submit, API error toast (4 cases).
    - `NewMatterDialog` — validation, uppercase + trim on matter_code, submit success (2 cases).
    - `DataTable` — filter input, Enter/Space keyboard activation, labelled pagination buttons (3 cases).
  - Persona Playwright spec (`tests/e2e/personas.spec.ts`) exercises sign-in → dashboard → create first matter for law-firm owner, corporate GC (`company_type=corporate_legal`), and solo — the PRD §8.3 personas. All three green.
  - **Root-caused + fixed the phase-9 spine regression** flagged in §3.7 Remaining: the dashboard's `useQuery(["matters", "list"])` and the matters page's `useInfiniteQuery(["matters", "list"])` shared a key, so react-query tried to reconcile a `MattersList` with an `InfiniteData<MattersList>` on client nav, which crashed the transition (Chromium ERR_ABORTED). Moved the dashboard to `["matters", "dashboard-overview"]`. App-spine suite: 5/5 green, full app Playwright run: **21/21 green**.
- **Remaining:**
  - Component tests for invoice approval and user invite flows once those dialogs land.
  - Vitest runs aren't yet wired into CI (§8.4 CI/CD follow-up).

---

## 4. P0 — AI core (LLM, drafting, recommendations)

Without this, the PRD's central promise does not exist.

### 4.1 LLM integration — **DONE (Phase 4A, 2026-04-17, `ee158f7`)**

- **Traces to:** `apps/api/pyproject.toml` (no SDK); PRD §12.1, §3.5
- **Landed:**
  - `services/llm.py` exposes a `LLMProvider` Protocol with `generate` + provider pluggability. Mock (deterministic, default), Anthropic (`claude-opus-4-7`, `claude-sonnet-4-6`), and Gemini (`gemini-2.5-pro`) adapters are wired behind runtime imports.
  - Provider selected by `CASEOPS_LLM_PROVIDER` / `CASEOPS_LLM_MODEL` / `CASEOPS_LLM_API_KEY`.
  - `ModelRun` rows now capture prompt hash, model id, input/output tokens, latency, tenant, matter for every call (see §7.3 landed).
  - Prompt templates live in `apps/api/src/caseops_api/prompts/` and are keyed by template name + version.
- **Deferred:** self-hosted / vLLM routing flag (§13.1 enterprise) and `rerank`/`embed` on the same Protocol — `embed` is handled by the parallel `EmbeddingProvider` in `services/embeddings.py` (§4.2).

### 4.2 Proper RAG — **PARTIAL (Phase 7, 2026-04-17)**

- **Landed:**
  - Alembic `20260417_0003` enables pgvector on Postgres and adds `embedding_vector vector(1024)` on `authority_document_chunks` with a cosine HNSW index. SQLite tests fall back to a JSON column so the pipeline has a uniform shape.
  - `services/embeddings.py` — provider Protocol + Mock (default, deterministic, offline) + FastEmbed (local, Apache-2.0, ~250 MB) + Voyage (`voyage-3-law`) + Gemini (`text-embedding-005`) adapters behind runtime imports. `CASEOPS_EMBEDDING_PROVIDER` / `MODEL` / `API_KEY` / `DIMENSIONS` config.
  - `services/corpus_ingest.py` + `caseops-ingest-corpus` CLI stream the public Indian HC and SC buckets (boto3 unsigned). Downloads a batch, ingests, deletes each PDF after its chunks land, enforces a soft disk cap (`CASEOPS_CORPUS_INGEST_MAX_WORKDIR_MB`, default 500 MB). Canonical-key dedup lets re-runs skip already-indexed documents.
  - `services/retrieval.py` accepts `query_vector`; when present and candidate chunks carry embeddings, blends cosine similarity with the existing lexical score (60/40 vector/lexical). Falls back cleanly to pure lexical when no embeddings exist yet.
  - `docker-compose.yml` Postgres runs `CREATE EXTENSION vector` on first boot via `infra/postgres/init/00-extensions.sql` and gains a healthcheck.
  - Decision recorded: the **authority corpus is shared public** (SC / HC judgments are public law), while **tenant-private overlays** (internal notes, linked matters, flags) stay on separate per-tenant tables. Matter attachments remain tenant-scoped.
- **Landed in Phase 8 (2026-04-17, `1913a11`):**
  - Native pgvector `<=>` cosine operator now drives the SQL prefilter in `services/authorities._pg_prefilter_document_ids` (HNSW index used).
  - OCR fallback: `services/ocr.py` with RapidOCR (pure-Python ONNX) + Tesseract backends, invoked when pdfminer yields too few characters.
  - Multi-year CLI: `caseops-ingest-corpus --from-s3 --year Y1 --year Y2 ...` with per-year progress + disk reset between scopes.
  - Chunk flush-before-UPDATE fix: vectors now actually persist (was silently `NULL` pre-fix).
- **Landed in Phase 9 (2026-04-17, `f8a502c`):**
  - `HC_COURT_CATALOG` maps 29 Indian High Courts (incl. Delhi, Bombay, Telangana, Madras, Karnataka) to their S3 `court=<code>_<n>/` partitions.
  - `--hc-courts delhi,bombay,telangana,madras,karnataka` CLI flag + `resolve_hc_courts` validator for targeted jurisdictional ingestion.
  - Sample ingestion verified: 5 HCs × 2023 = 40 judgments / 188 chunks / all embedded.
- **Remaining:**
  - Cross-encoder reranker over the top-50 candidates for another quality step.
  - Per-tenant overlay schema (`AuthorityAnnotation` + link table) for tenant comments on shared judgments.
  - Integration test against a live Postgres + fastembed / voyage / gemini — the current suite covers only the mock provider.
  - Extend embedding columns onto `matter_attachment_chunk` as well (currently only authorities carry vectors).
  - Full 10-year ingestion for the 5 target HCs + SC (operator task — ~500 GB egress, 50-150 GPU-hours; out of session scope).

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

### 4.4 Recommendation engine — **DONE v1 (Phase 4A, 2026-04-17, `ee158f7`)**

- **Traces to:** PRD §9.7, §11, §23.1; Alembic `20260417_0002`.
- **Landed:**
  - Schema: `Recommendation`, `RecommendationOption`, `RecommendationDecision` with PRD §23.1 fields (`type`, `title`, `options[]`, `primary_option_index`, `rationale`, `supporting_citations[]`, `assumptions[]`, `missing_facts[]`, `confidence`, `next_action`, `review_required`, `status`).
  - Types in v1: `forum`, `authority`. Remedy / next-best / outside-counsel / settlement deferred.
  - Pipeline: rules → retrieval (hybrid lexical + vector, §4.2) → ranker → LLM explanation → citation verification (§4.6).
  - `RecommendationDecision` captures accept / reject / edit / defer with actor, `selected_option_index`, notes — persisted for HITL training (§7.3).
  - Guardrails enforced: no recommendation emits without ≥1 supporting authority; `review_required=True` on every recommendation until explicit approval.
  - Routes: `POST /api/matters/{id}/recommendations`, `GET /api/matters/{id}/recommendations`, `POST /api/recommendations/{id}/decisions`.
- **Remaining (v2):** remedy / next-best-action / outside-counsel recommendation types; per-tenant rule overrides.

### 4.5 Hearing preparation — full workflow

- **Traces to:** `services/briefing.py` (today: read-only summary); PRD §9.6, §10.4
- **Problem:** Generates text blocks; does not generate a hearing pack.
- **Done when:**
  - Schema: `HearingPack`, `HearingPackItem` (chronology item, last-order summary, pending-compliance item, issue, opposition point, authority card, oral point).
  - Auto-generation on `MatterHearing` creation or within N days of `next_hearing_on`.
  - Post-hearing: outcome capture → auto-creates follow-up tasks and proposes next-hearing date.

### 4.6 Citation verification and refusal logic — **DONE v1 (Phase 4A, 2026-04-17, `ee158f7`)**

- **Traces to:** PRD §11.5, §17.4; `services/citation_verification.py`.
- **Landed:**
  - Every recommendation / draft pass now runs through `verify_citations` before persisting: each cited authority id is re-fetched, the cited proposition is checked against the chunk text (normalized string match), and unknown citations are stripped with the event recorded on the `ModelRun`.
  - Low-evidence path: if retrieval returns fewer than `MIN_EVIDENCE` chunks for the prompt, the LLM is instructed to refuse and the recommendation is flagged `confidence=low` + `review_required=true` with `missing_facts[]` populated.
  - Test suite: `tests/test_citation_verification.py` covers the hallucination / low-context-refusal / contradictory-authority paths (PRD §19.6.1–19.6.3).
- **Remaining:** second-pass verifier model for semantic (not string) proposition-match once we have a cheap judge model wired.

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

### 6.1 Pagination on every list endpoint — **DONE v1 (Phase 9, 2026-04-17, `f8a502c`)**

- **Traces to:** `/api/matters/`, `/api/contracts/`; `services/pagination.py`.
- **Landed:**
  - Opaque base64 keyset cursor over `(updated_at, id)`. Clients pass it back unchanged — encoding is internal so we can change it without breaking consumers.
  - `services/pagination.py` exposes `encode_cursor`, `decode_cursor`, `clamp_limit`, `DEFAULT_PAGE_SIZE=50`, `MAX_PAGE_SIZE=200`.
  - `MatterListResponse` and `ContractListResponse` now carry `next_cursor: str | None`. `/api/matters/` and `/api/contracts/` accept `limit` and `cursor` query params.
  - Invalid / tampered cursors fall back to page 1 (no 400) — clients never crash on bad input.
  - Frontend: `/app/matters` and `/app/contracts` use `useInfiniteQuery` with a "Load more" button; zod schemas accept `next_cursor`.
  - Tests: 13 new cases in `tests/test_pagination.py` (clamp, roundtrip, invalid-cursor forgiveness, 3-page walk, max-page, insert-stability, contracts walk, monotonic cursor).
- **Remaining:** extend to `/api/authorities/`, `/api/outside-counsel/`, matter workspace sub-lists (time entries, invoices), recommendations. Document cursor shape in OpenAPI once the shape stabilises across endpoints.

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

### 7.3 Model runs and evaluation — **PARTIAL (Phase 4A, 2026-04-17, `ee158f7`)**

- **Traces to:** PRD §12.7, §17.4; `db/models.py::ModelRun`.
- **Landed:** `ModelRun` records every LLM call (provider, model id, prompt hash, input/output tokens, latency, tenant, matter, parent recommendation, citation-verification outcome). Wired through `services/llm.py` for all recommendation and draft paths.
- **Remaining:** `EvaluationRun` table + benchmark harness (citation accuracy, hallucination rate, extraction accuracy); admin UI to gate a new model version behind a passing evaluation; cost rollup per tenant.

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
