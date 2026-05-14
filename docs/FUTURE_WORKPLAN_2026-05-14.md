# CaseOps Future Workplan — Consolidated Gap & Deferred-Feature Ledger

**Generated:** 2026-05-14
**Revised:** 2026-05-14 (rebaselined against `main` per Codex review 2026-05-14 — see `docs/CODEX_REVIEW_FUTURE_WORKPLAN_2026-05-14.md`; judge-favorability stance preserved — see top hard-rails line)
**Branch baseline:** `main` (HEAD `58116d286c7fe2067fd881d104df25c96b78565a`)
**Sources consulted:**
- `docs/PRD_CLAUDE_CODE_2026-04-23.md` (canonical execution PRD)
- `docs/PRD.md` (original Apr-15 PRD)
- `docs/PRD_LITIGATION_INTELLIGENCE_EXPANSION_2026-05-11.md` (present on `main`)
- `docs/PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05.md`
- `docs/PRD_MATTER_FILE_QA_2026-05-13.md` (present on `main`)
- `docs/PRD_BENCH_MAPPING_2026-04-25.md`
- `docs/PRD_BENCH_STRATEGY_2026-04-26.md`
- `docs/PRD_STATUTE_MODEL_2026-04-25.md`
- `docs/PRD_CAUSE_LIST_SCRAPER_2026-04-25.md`
- `docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md`
- `docs/WORK_TO_BE_DONE.md`
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
- `docs/STRICT_PRODUCT_GAPS_2026-04-30.md`
- `docs/STRICT_BUG_TASKLIST_2026-04-22.md`
- `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`
- `docs/PRODUCT_GAP_ANALYSIS_2026-05-01.md`
- `docs/STRATEGY_PLANNER_FOLLOWUPS_2026-05-03.md`
- `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md`
- `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
- Live repo scan: `apps/api/src/caseops_api/{api/routes,services}/`, `apps/web/app/app/`, `apps/api/alembic/versions/`

**Scope:** Every PRD item, expansion feature, hardening task, or feature-gap that is **NOT** currently Properly Implemented + Verified as of HEAD on `main` (`58116d2`).

> **Rebaseline note (2026-05-14):** This document was rebaselined against `main` HEAD `58116d2` per Codex review `docs/CODEX_REVIEW_FUTURE_WORKPLAN_2026-05-14.md`. Status, priority, evidence paths, and acceptance criteria were corrected for items where the prior corpus-branch baseline diverged from production reality on `main`. Litigation Intelligence (LI-S1..S8) and Matter File Q&A V1 service/schema/migration/test files exist on `main` and remain closed; see Appendix B. Total gap count: 130. P0 count: 21.

## How to read this document

- **Status codes:** `Missing` | `Partial` | `Stale-doc` | `Deferred-by-design`
- **Priority:** P0 (blocks GA / litigation-wedge readiness) · P1 (post-GA must) · P2 (nice-to-have) · P3 (research / strategic bet)
- Each item lists PRD ref, current repo evidence (path or `none`), and an acceptance check.
- Stable IDs `G-001…G-NNN` are unique across the whole document.
- Where another strict ledger already owns an item (`EG-*`, `WTD-*`, `PG-*`, `AQ-*`, `MFQ-*`, `LI-*`, `BS-*`, `BAAD-*`, `MOD-TS-*`), the legacy ID is preserved in parentheses for traceability.
- **Hard rails preserved:** Judge favorability and predictive outcome surfaces are **in-scope and active** — they bias toward the user's position on their matter (per user stance 2026-05-14, codifying `feedback_user_bias_in_recommendations.md`). All such surfaces must remain citation-grounded, sample-size gated, tenant-policy controlled, audited via `ModelRun` + `AuditEvent`, and degrade gracefully when evidence is weak. No fabricated statistics. Production embedding = Voyage `voyage-4-large`. Production Layer-2 = `gpt-5-mini`. Corpus quality target = **4.8/5**.

---

## 1. Foundation gaps (multi-tenant, security, infra, hotspots)

### G-001 Backend & web hotspot decomposition (EG-008)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** STRICT_ENTERPRISE_GAP_TASKLIST §Structural Code Risks
- **Current evidence (re-measured on `main`):** `apps/api/src/caseops_api/db/models.py` (6643 lines), `services/matters.py` (2687), `api/routes/matters.py` (2760), `services/court_sync_sources.py` (1276), `apps/web/lib/api/endpoints.ts` (4156)
- **Acceptance:** Each oversized hotspot split into ≤500-line modules with narrow responsibilities; manual API client retired route-by-route; CI line-count check fails when any of the five files exceed agreed thresholds (`models.py ≤ 2000`, `services/matters.py ≤ 1000`, `routes/matters.py ≤ 1000`, `endpoints.ts` removed in favour of generated client).

### G-002 Exception-handling discipline (EG-009)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** STRICT_ENTERPRISE_GAP_TASKLIST §EG-009
- **Current evidence:** `services/drafting_preview.py:97-118`, `services/contracts.py:835-868`, `services/matters.py:1309-1339`
- **Acceptance:** No bare/broad `except` swallowing critical-path errors; user-visible detail is actionable without leaking internals; raw exception logged at WARN/ERROR.

### G-003 Temporal durable workflow engine (WTD-5.1)
- **Status:** Missing · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE §15 (Claude Code Execution Contract requires Temporal as the durable orchestration path); LegalWorkspace §15.3 Temporal Requirement
- **Current evidence:** none — reminders, court sync, ingestion, escalations run on ad-hoc polling/Cloud Run Jobs
- **Acceptance:** Critical workflows (hearing reminders, court sync, AutoMail send, ingestion sweeps, escalation planner re-runs) migrated to Temporal with idempotent activities + signal-based pause/resume + dead-letter handling. Verification: `scripts/verify-backend.ps1 apps/api/tests/test_temporal_workflows.py` green and `Grep "BackgroundTasks" apps/api/src/caseops_api/api/routes` returns no critical-path workflow start (calendar / notifications / ingestion / drafting / escalation).

### G-004 Grantex agent-identity / scoped-grant / budget plane (WTD-5.2)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE §Core Principles (Grantex = trust plane)
- **Current evidence:** none
- **Acceptance:** Agent actions carry scoped delegation token, per-tenant budget cap, revocation hook, and per-action audit.

### G-005 Durable notification service (WTD-5.3)
- **Status:** Missing · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE J08; LegalWorkspace §15
- **Current evidence:** `services/hearing_reminders.py`, `notification_rules.py` (partial; in-app + SendGrid one-shot)
- **Acceptance:** Multi-channel (in-app + email + SMS) delivery queue with retry / DLQ / status webhook → audit; deliverability dashboard surfaces queued / sent / failed. Verification: `apps/api/tests/test_notifications_durable_delivery.py` covering retry, DLQ, webhook status, and audit-emission paths green; Playwright spec asserts admin dashboard renders queued/sent/failed counts.

### G-006 OIDC + SAML SSO (WTD-10.2, PG-009)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE J14, US-041, NFT-016, SEC-020
- **Current evidence:** none — only password auth + magic-link portal exist (`apps/web/app/app/admin/page.tsx:478` roadmap text)
- **Priority rationale:** Enterprise/J14 hardening — does not block the J05-J09 litigation wedge. Demoted from P0 per Codex Check C 2026-05-14.
- **Acceptance:** SAML + OIDC IdP integration with JIT provisioning + role mapping + domain capture + session/IP controls. Verification: OIDC + SAML fixture tests under `apps/api/tests/test_sso_*.py` green, Playwright spec asserts admin IdP mapping flow, plus a negative test for domain mismatch.

### G-007 SCIM provisioning + MFA enforcement (PG-009)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §P0
- **Current evidence:** none
- **Priority rationale:** J14 enterprise-hardening — same reasoning as G-006. Demoted from P0 per Codex Check C 2026-05-14.
- **Acceptance:** SCIM 2.0 endpoints for user/group sync; MFA policy enforced server-side per tenant; bypassable only by emergency-recovery admin. Verification: SCIM create/update/deactivate conformance tests, MFA-enforcement unit tests, and an audit assertion on emergency-admin bypass.

### G-008 Plan entitlements + usage metering (WTD-10.5, PG-010)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE §16 ("Enterprise completion"), J14
- **Current evidence:** none — marketing pricing exists but no `Plan` / `PlanEntitlement` model
- **Priority rationale:** Commercial launch control — does not block J05-J09 litigation output. Demoted from P0 per Codex Check C 2026-05-14.
- **Acceptance:** `Plan` + `PlanEntitlement` tables gate feature flags, seat limits, AI quotas, overage billing; admin UI shows current usage vs entitlement. Verification: route/page tests proving seat-limit, feature-flag, AI-quota, and overage behaviour; SQL assertion on `PlanEntitlement` constraints.

### G-009 Tenant management console (WTD-10.1)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE §16 enterprise completion
- **Current evidence:** none — only per-tenant admin pages
- **Acceptance:** Super-admin console for company create/suspend, plan assignment, AI-policy override, audit export across tenants.

### G-010 AI policy controls — broader (WTD-10.3)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE SEC-013; LI-S7 controlled-predictive contract
- **Current evidence:** `services/tenant_ai_policy.py:9-11`, `services/llm.py:636-663`, `TenantAIPolicy.predictive_bench_strategy_enabled` (PG-107 only)
- **Acceptance:** Per-purpose model allow-list, retention controls, provider routing toggle, cost cap per workspace, full admin UI.

### G-011 Cross-region backup export + per-tenant export + cutover drill (WTD-8.3 sub-items)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE NFT-010
- **Current evidence:** `docs/RESTORE_DRILL_2026-04-24.md` (same-region restore proven; cross-region + per-tenant export + Cloud Run cutover pending)
- **Acceptance:** Quarterly cross-region restore drill; tenant data-export pipeline (DPDP / right-to-portability); documented Cloud Run cutover to restored DB.

### G-012 Full CI/CD with branch protection + staged deploy (WTD-8.4)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE §16
- **Current evidence:** `scripts/deploy-prod.sh` canonical path; no staging environment / canary
- **Acceptance:** Branch-protected main, staging→prod promotion gate, automated canary % traffic split, automated rollback.

### G-013 Secret-management completion + provider key rotation (WTD-8.5)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** SEC-017
- **Current evidence:** `infra/cloudrun/api-service.yaml:14-66`; Pine Labs UAT key not rotated with provider
- **Acceptance:** All sensitive env via Secret Manager (done) + 90-day cadence enforced + provider-side rotation (Pine Labs, SendGrid, Anthropic) automated.

### G-014 Air-gapped / no-egress deployment package (PRD §J15, US-045)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_CLAUDE_CODE J15, US-045, NFT-017, SEC-022
- **Current evidence:** LLM + embedding abstractions exist; no offline packaging
- **Acceptance:** Single-tenant on-prem image bundle; `CASEOPS_OFFLINE_MODE=true` blocks every external host; documented runbook.

### G-015 DPDP / SOC 2 trust pack + retention / legal-hold UI (PG-207)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-207
- **Current evidence:** none
- **Acceptance:** Public trust center page; per-tenant retention policy + legal-hold + support-access admin controls; DPA template.

### G-016 Browser session — HttpOnly enterprise hardening sweep
- **Status:** Partial · **Priority:** P2
- **PRD ref:** SEC-001 (EG-001 main path closed)
- **Current evidence:** `apps/web/lib/session.ts:35-37` (closed); residual cookies for `caseops_csrf` JS-readable by design
- **Acceptance:** Enterprise tenants able to disable any client-storage caching of identity; full localStorage audit.

### G-017 Migration-order test + per-tenant DB-validation breadth (AQ-005 follow-on)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** STRICT_ENTERPRISE_GAP_TASKLIST AQ-005
- **Current evidence:** `tests/test_postgres_validation.py` (6 PG-only cases on a `pgvector/pgvector:pg17` CI service)
- **Acceptance:** All DB-sensitive tests run under Postgres-in-CI (not only the validation file); ON DELETE / JSONB / unique-constraint coverage expanded matrix-wide.

---

## 2. Core matter-cockpit gaps

### G-018 Matter Tasks tab + Deadlines tab (WTD-7.2 remaining)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE Module §M08; J03; US-022
- **Current evidence:** `MatterTask` + `MatterDeadline` models + `services/calendar_service.py` exist; no cockpit sub-tab
- **Acceptance:** `/app/matters/[id]/tasks` + `/app/matters/[id]/deadlines` render the existing feed with create/assign/complete; admin task templates per practice area. Verification: sibling `page.test.tsx` for both routes plus backend create/assign/complete tests in `apps/api/tests/test_matter_tasks_deadlines.py` and a negative matter-access test (forbidden user cannot read sibling matter's tasks).

### G-019 Matter Command Center "Next action" card (PG-004 follow-on)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE J03 ("clear next state"); PRODUCT_GAP_ANALYSIS §P0 "Daily command center"
- **Current evidence:** `services/today_view.py` + `/app/today` shipped; matter-cockpit derived next-action card NOT shipped; sidebar default route not swapped to `/app/today`
- **Acceptance:** Cockpit overview surfaces matter-scoped "Next action" derived from the today_view feed; sidebar default flips to `/app/today` for users with active matters. Verification: backend test asserts the next-action payload is derived from `today_view.compute_feed(...)`; Playwright spec confirms sidebar default route only changes for accounts with ≥1 active matter and remains on `/app` otherwise.

### G-020 Generic matter Notes + Activity timeline UX surfacing (J03)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE J03 (notes, tasks, hearings, invoices, attachments)
- **Current evidence:** `services/matter_timeline.py` exists; activity surfacing scattered
- **Acceptance:** Unified activity timeline on cockpit overview with filter by event type and tenant audit lineage.

### G-021 Matter health score + intervention logic
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §Matter Management Required improvements
- **Current evidence:** none
- **Acceptance:** Stale-activity + overdue-task + spend-variance + missing-document signals roll up to per-matter score with "needs attention" intervention chip.

### G-022 Conflict-check intake gate + related-party graph + waiver workflow (PG-001 v2)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-001
- **Current evidence:** v1 shipped (`MatterConflictCheck`, `services/conflict_checks.py`, migration `20260430_0001`, `ConflictCheckCard`); intake gate + witnesses/opposing-counsel/vendors + bulk-waiver/partner-approval pending
- **Acceptance:** Matter status promotion `intake → active` blocked unless conflict is `cleared` or `partner-waived`; contact table covers witnesses, opposing counsel, vendors; waiver requires partner approval email. Verification: state-machine test in `apps/api/tests/test_conflict_intake_gate.py` asserts the transition is rejected (HTTP 409) when conflict is `open` and accepted only on `cleared`/`waived`; audit + email assertions on the waiver path.

### G-023 Engagement letter + fee-arrangement workflow (PG-002)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-002
- **Current evidence:** none — no `MatterEngagement` / `fee_arrangement` model
- **Priority rationale:** Commercial/intake gate — does not block research, drafting, hearing prep, or bench-strategy J05-J09 surfaces. Demoted from P0 per Codex Check C 2026-05-14.
- **Acceptance:** Engagement-letter template by practice area + fee basis (hourly/fixed/contingent/retainer/capped/milestone); intake step + e-sign + signed PDF stored in attachments; matter open blocked until signed or waived. Verification: model migration committed; e-sign adapter contract test asserts callback writes attachment row; matter-open test asserts blocked state when engagement is `unsigned`; waiver path emits an audit row.

### G-024 Trust / retainer / advance ledger (PG-003)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-003
- **Current evidence:** none — `MatterInvoice` exists but no advance/trust schema
- **Acceptance:** `MatterTrustLedger` (deposit/withdrawal/transfer + balance) + matter Billing Trust card + admin Trust report + Bar Council compliance copy.

### G-025 Matter templates by practice area (PG-103)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-103
- **Current evidence:** none
- **Acceptance:** `MatterTemplate` (practice_area + default_tasks + default_documents + default_filing_checklist) usable from intake.

### G-026 Document request lists + secure collection (PG-104)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-104
- **Current evidence:** Client portal exists; no per-matter `DocumentRequest`
- **Acceptance:** `DocumentRequest` + portal "Documents requested from you" + auto-attach to request item.

### G-027 Claim amount + plaintiff/defendant + matter tags (LegalWorkspace §10-§14)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05 §10 (Claim amount), §11 (Document type), §14 (Matter tags); migration `20260505_0001_legalworkspace_matter_tags_claims.py` exists
- **Current evidence:** Migration shipped; `Matter` still uses `client_name`/`opposing_party`; tag UX/search depth needs verification at the cockpit
- **Acceptance:** Plaintiff/defendant distinct fields + claim amount + claim currency + tenant-scoped matter tags with autocomplete + tag-based portfolio filter.

### G-028 Forum hierarchy catalog + matter forum (LegalWorkspace §13)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05 §13 + migration `20260505_0004_legalworkspace_forum_catalog.py`
- **Current evidence:** Migration shipped; UX coverage needs surfacing in intake + cockpit
- **Acceptance:** Forum catalog (SC, HC, district, tribunal, arbitration) wired through intake + matter cockpit + research filters.

### G-029 Order timeline / interim-order / stay tracker (LegalWorkspace §15 + migration `20260505_0002_legalworkspace_order_timeline.py`)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05 §15
- **Current evidence:** Migration shipped; cockpit UI for stay/interim tracking pending
- **Acceptance:** Matter cockpit Orders tab with interim/stay flags, source PDF link, deadline propagation back into MatterDeadline.

### G-030 Document lifecycle stage + sequence index (LegalWorkspace §11 + migration `20260505_0003`)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05 §11
- **Current evidence:** Migration shipped; lifecycle taxonomy/UX needs documents-tab surface
- **Acceptance:** Documents tab shows lifecycle stage (pleading / order / annexure / etc.) + sequence index + filterable by type.

---

## 3. Authority corpus & retrieval gaps

### G-031 Proper RAG completion (WTD-4.2)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE §12 Data Source rules; LI-S4 source policy
- **Current evidence:** `apps/api/src/caseops_api/db/models.py:3106` and `:3182` define authority documents/chunks; `apps/api/src/caseops_api/scripts/eval_hnsw_recall.py:552` evaluates recall; 4.8/5 corpus-quality target NOT uniformly met across target buckets.
- **Acceptance:** Per-bucket recall@10 ≥ 95% + 4.8/5 readiness rating on the EN-only SC + HC + tribunal slices; reranker on by default. Verification: committed `caseops-eval-hnsw-recall` output (under `docs/eval_artifacts/`) per bucket reporting `rating: X.Y/5 (recall@10=…, MRR=…, rank=…)`, all ≥ 4.8/5.

### G-032 Research treatment / good-law signal (PG-006)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §PG-006; PRD_CLAUDE_CODE J05
- **Current evidence:** `apps/api/src/caseops_api/services/authority_treatments.py` describes Phase 1B treatment aggregation + the adverse-treatment validator wired into drafting; `apps/web/app/app/research/page.tsx:540-547` renders the good-law `TreatmentBadge` with severity tone and count. Remaining: full classifier coverage, "must verify before filing" gate UX, and corpus backfill.
- **Acceptance:** Treatment classification (followed / distinguished / overruled / doubted / considered / reversed / dissented) with confidence + evidence quote; "must verify before filing" gate on adverse treatment; backfill on corpus. Verification: backend treatment-classifier unit tests against ≥ 20 labelled fixtures, research-page badge render test, and drafting adverse-treatment cannot-file test.

### G-033 Citation graph depth + good-law badges in research/drafting (PG-101 follow-on)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §Research module
- **Current evidence:** `AuthorityCitation` + `citation_extraction.py` populate the graph; `apps/web/app/app/research/page.tsx:540-547` renders treatment badges. Remaining: cited-by / followed / overruled counts on the result card and citation-graph drill-down.
- **Acceptance:** Per-authority "cited by N · followed M · overruled K" badge; citation graph drill-down; research panel shows authority confidence (court + recency). Verification: API test for `GET /api/authorities/{id}/treatments` returns counts per category; web test asserts badge + drill-down render with the returned counts.

### G-034 Tribunal corpus ingestion (LI-S4 follow-on for NCLT/NCLAT/DRT/DRAT/ITAT/NGT/CAT/NCDRC)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE §12.1; LI PRD §3.8; PRD §M05
- **Current evidence:** `services/authority_sources.py` registers tribunal entries as "planned/blocked"; no live corpus
- **Acceptance:** One pilot tribunal family ingested under registered source + 4.8/5 quality gate + research filter exposes forum-level=tribunal.

### G-035 District / session court corpus (LI-S4 follow-on)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** LI PRD §3.6; PRD_CLAUDE_CODE §12.1
- **Current evidence:** `forum_level=lower_court` exists; Central Delhi District public-posture adapter only; eCourts blocked (captcha)
- **Acceptance:** One verified-source pilot district ingested with full lineage + research filter exposes state + district.

### G-036 Statute model depth — amendments, effective dates, state amendments, repeals (PG-205, WTD-7.4 follow-on)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_STATUTE_MODEL_2026-04-25 §2 (v2 scope); PRD_CLAUDE_CODE M04
- **Current evidence:** Core schema + 7 central acts + 91 sections via `20260425_0004`; long-tail enrichment + amendment history + cross-act mapping (CrPC↔BNSS) + state acts missing
- **Acceptance:** Amendment history table + effective_from/to per section + state amendments + CrPC↔BNSS mapping + bare-text enrichment for long-tail sections.

### G-037 Statute bare-text enrichment for long-tail sections
- **Status:** Partial · **Priority:** P2
- **PRD ref:** WTD-7.4 (out-of-V1)
- **Current evidence:** 91 sections seeded with source URL; bare text exists for the seven anchor acts only
- **Acceptance:** Section-level bare text available for every section that drafting prompts may quote; verbatim-quote integrity test in CI.

### G-038 Persistent `language` column on `AuthorityDocument` (PG-110 follow-on)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PG-110 §Open follow-ons (2026-05-01)
- **Current evidence:** PG-110 v1 uses post-retrieval ASCII filter (over-fetch cost)
- **Acceptance:** SQL `WHERE language='en'` replaces over-fetch; Layer-2 re-extract cleans citation-only titles into proper case names.

### G-039 Coverage confidence UI in research / drafting / recommendations (PG-108)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PG-108
- **Current evidence:** none
- **Acceptance:** `coverage_for_query(matter, query)` returns courts-in-scope + year-range + doc-count + freshness; UI badge per result card; "limited corpus" warning when below threshold.

### G-040 Source coverage matrix + freshness SLA (PRODUCT_GAP §P0 "Corpus moat not proven")
- **Status:** Missing · **Priority:** P0
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §P0
- **Current evidence:** none — no public coverage manifest
- **Acceptance:** Published doc-count by jurisdiction × court × document type × update frequency × source license + freshness SLA. Verification: generated JSON+CSV coverage manifest emitted to `docs/coverage/source_matrix.{json,csv}` with required fields (jurisdiction, court, doc_type, freshness_days, license, source_url); CI check fails if any required field is missing or freshness exceeds SLA.

### G-041 Licensed commentary integration (US-013, M04)
- **Status:** Missing · **Priority:** P3
- **PRD ref:** PRD_CLAUDE_CODE §12.1; US-013
- **Current evidence:** none; SCC / Manupatra deferred per cost discipline
- **Acceptance:** Licensed-source adapter pattern + SEC-024 license tracking + retrieval pathway honors per-tenant license entitlement.

### G-042 Indian Kanoon / SCC Online / Manupatra licensing (PG-006 corpus)
- **Status:** Deferred-by-design · **Priority:** P3
- **PRD ref:** LI PRD §5.1; PG-006
- **Current evidence:** none; not default sources
- **Acceptance:** License + terms agreement signed; SEC-024 tracker entry; adapter implementation.

### G-043 Mixed matter-file + public-authority retrieval with separate citations (MFQ residual caveat)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_MATTER_FILE_QA_2026-05-13 §7.2 (planned), §21
- **Current evidence:** MFQ-S1-S5 uses uploaded chunks only
- **Acceptance:** Matter File Q&A response renders separately-tagged "uploaded sources" + "public authority sources" without cross-contamination.

---

## 4. Bench / judge intelligence gaps

### G-044 Bench-strategy V1 — Phases 1-5 (BS-FT-*, MOD-TS-018)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_BENCH_STRATEGY_2026-04-26; user stance 2026-05-14 (PRD-gate lifted, codifying `feedback_user_bias_in_recommendations.md`); supersedes `project_bench_strategy_prd_gated.md`
- **Current evidence:** Backend governance from PG-107 v1/v2 shipped (`TenantAIPolicy.predictive_bench_strategy_enabled`, ModelRun + AuditEvent on every render); HC sitting-judges + bench resolver + bench-specific authority substrate live; frontend consumer surfaces (cockpit, drafting prompt, authority rerank, recommendations) do not yet consume the favorability signal
- **Acceptance:** Surface produces a per-bench, per-position recommendation that satisfies all six favorability guardrails: (1) citation-grounded — cites source authority IDs; (2) sample-size band visible — "n=N, recall@10=…"; (3) per-tenant `TenantAIPolicy.predictive_bench_strategy_enabled` toggle honored; (4) `ModelRun` + `AuditEvent` emitted on every render (success and failure); (5) degrades to "insufficient bench history" when evidence is weak; (6) structural no-fabrication test asserts the rendered output references only source IDs returned by the retriever. HC sitting-judges backfill complete for top-N HCs; Layer-3 extraction within $10/court/day ceiling; drafting "missed citations" hint live. Verification: one backend test (`apps/api/tests/test_bench_strategy_guardrails.py`) and one Playwright spec proving all six guardrails on render.

### G-045 Bench-strategy V2 — NJDG pendency + cross-tenant trend + per-bench inter-judge dynamics
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_BENCH_STRATEGY_2026-04-26 §5 "Out of V1"; user stance 2026-05-14 (un-deferred)
- **Current evidence:** none
- **Acceptance:** NJDG pendency ingest + cross-tenant aggregate respects tenant policy + DPDP; per-judge tendency analysis available in research view; per-bench inter-judge dynamics surfaced satisfying all six favorability guardrails: (1) citation-grounded with source IDs; (2) sample-size band visible ("n=N, recall@10=…"); (3) per-tenant `TenantAIPolicy.predictive_*_enabled` toggle honored; (4) `ModelRun` + `AuditEvent` emitted on every render; (5) graceful "insufficient evidence" degrade path; (6) structural no-fabrication test. Verification: the same six-guardrail test set (backend + Playwright) green before V2 trend / inter-judge analytics ship.

### G-046 Cause-list scraper per court (PRD_CAUSE_LIST_SCRAPER_2026-04-25) [PRD-GATED]
- **Status:** Deferred-by-design · **Priority:** P1 (post-gate)
- **PRD ref:** PRD_CAUSE_LIST_SCRAPER_2026-04-25 §What this PRD must define
- **Current evidence:** Downstream pipeline ready (`MatterCauseListEntry` + `bench_resolver.py` + `BenchSpecificAuthority`); recon probe showed 4/8 HC scrapers viable, others 403/captcha/SPA
- **Acceptance:** PRD body filled in (source preference, frequency, auth, rate limits, failure UX, coverage order, cost ceiling, dedupe, audit); first N courts shipped.

### G-047 Manual cause-list paste-in workflow
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_CAUSE_LIST_SCRAPER_2026-04-25 §What's NOT in scope
- **Current evidence:** none
- **Acceptance:** Separate PRD + paste-in form on matter cockpit; `source='manual'` lineage.

### G-048 Arbitrator registry + arbitration intelligence (US-016, M05)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_CLAUDE_CODE §12.1, US-016
- **Current evidence:** none (DIAC / MCIA / ICA registries not modeled)
- **Acceptance:** Arbitrator profile schema + search + arbitration matter workflow + Section 9 / Section 34 / Section 11 templates already exist.

### G-049 Judge career-history backfill for non-Delhi HCs (Slice A follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** PRD_BENCH_MAPPING_2026-04-25 §6
- **Current evidence:** SC backfill (35 rows) + Delhi HC (32 rows) live; other HCs deferred
- **Acceptance:** Remaining HCs backfilled as their sitting-judges scraper lands.

### G-050 Tolerant judge alias matcher — broader coverage (MOD-TS-001-E follow-on)
- **Status:** Partial · **Priority:** P3
- **PRD ref:** PRD_BENCH_MAPPING_2026-04-25 Slice D
- **Current evidence:** 269 aliases for 63 judges (Delhi/SC); other HCs pending sitting-judges backfill
- **Acceptance:** Aliases ≥ 4/judge for all HC sitting judges; resolver self-test ≥ 95% recall on bench-name corpus.

### G-128 Authority rerank consumes judge-favorability signal
- **Status:** Partial · **Priority:** P0
- **PRD ref:** `feedback_user_bias_in_recommendations.md` + LI-S7; user stance 2026-05-14
- **Current evidence:** `apps/api/src/caseops_api/services/recommendations.py:169-205` defines `_rerank_by_outcome_bias` which reorders results by `outcome_label` per practice-area mapping, applied at `:252`. It is a practice-area outcome bias, not yet the full bench-specific rerank consuming the indexed-bench-history signal with policy + audit completeness.
- **Acceptance:** When the matter has a hearing assigned to a bench, the authority rerank boosts judgments authored by that bench OR cited approvingly by that bench. All six favorability guardrails enforced: (1) citation-grounded (cites source IDs that drive the boost); (2) sample-size band visible on the rerank explanation; (3) per-tenant `TenantAIPolicy.predictive_*_enabled` toggle honored — falls back to general relevance when off; (4) `ModelRun` + `AuditEvent` emitted on every rerank invocation; (5) degrades to "insufficient bench history" fallback when sample size is below threshold; (6) structural no-fabrication test asserts the rerank does not synthesise any bench statistic beyond what the retriever returned. Verification: rerank test with indexed bench history, insufficient-history fallback test, policy-off fallback test, `ModelRun` row assertion, `AuditEvent` assertion, and no-fabricated-stats structural test.

---

## 5. Drafting & document-generation gaps

### G-051 Drafting quality 4.8/5 (PRODUCT_GAP §P0 "Drafting quality contradiction")
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE FT-029, FT-031, §15 4.8/5 gate; PRODUCT_GAP_ANALYSIS_2026-05-01
- **Current evidence:** `caseops_api.scripts.eval_drafting_quality` shipped; `docs/eval_artifacts/drafting_quality.json` showed `0.0/5` against `4.8/5` target on 2026-05-01
- **Acceptance:** Drafting eval ≥ 4.8/5 on all 20 templates with ≥ 8 representative scenarios per template; regression snapshot per template; failing eval blocks release. Verification: `caseops-eval-drafting` command emits per-template artifact under `docs/eval_artifacts/drafting/<template>.json`; CI release-verify job fails when any template scores below 4.8/5.

### G-052 Senior-lawyer review / signoff workflow (PRODUCT_GAP §P0 "Review workflow not lawyer-grade")
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE FT-028 (request_changes), FT-030 (finalize)
- **Current evidence:** Draft request-changes + finalize states exist; reviewer assignment + issue threads + redline history + privilege labels missing
- **Acceptance:** Reviewer assignment + threaded comments + redline history + privilege/work-product labels + signoff + filing-bundle audit row. Verification: backend tests for review-thread, redline diff, and signoff state machine in `apps/api/tests/test_drafting_review_workflow.py`; Playwright spec asserts reviewer assignment UX and the filing-bundle audit row appears post-signoff.

### G-053 Notice factory + batch notice generation depth (FT-033)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE US-020, FT-033, J07
- **Current evidence:** Per-template prompts shipped; isolated per-recipient orchestration + bulk export not surfaced
- **Acceptance:** Batch notice run page; per-recipient data isolation test; bulk DOCX/PDF/ZIP export.

### G-054 Template library governance — version history + audit + tenant-uploaded templates (Sprint 11 follow-on)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE US-019
- **Current evidence:** `tenant_ai_policies.disabled_template_types_json` (Sprint 11, migration `20260501_0003`); no tenant-uploaded template path
- **Acceptance:** Tenant-uploaded template store + version history + audit + golden fixture per tenant template.

### G-055 Citation insertion + pinpoint reference + treatment check inside drafting (PRODUCT_GAP §Drafting)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PRD_CLAUDE_CODE FT-029
- **Current evidence:** Citation verifier blocks zero-citation drafts; pinpoint refs + treatment warnings not present
- **Acceptance:** Drafting inserts citations with pinpoint para/page + adverse-treatment warning + cannot-draft-safely state when authorities are missing. Verification: fixtures under `apps/api/tests/fixtures/drafting/citation_pinpoint/` cover pinpoint-paragraph extraction, adverse-treatment surfaced, and no-authority refusal; drafting service tests assert the cannot-file state is returned (not a silent best-effort draft).

### G-056 Bench-aware drafting prompt — all 15 templates production-quality (Sprint 7 follow-on)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** BAAD-001
- **Current evidence:** Code wires 15 of 20 templates to bench context; production quality verified for appeal_memorandum only (commit `4a2191d`)
- **Acceptance:** Per-template golden + drafting eval ≥ 4.8/5 + structural no-favorability test green on all 15.

### G-057 Court-format coverage beyond 10 profiles (Sprint 5 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** PRD_CLAUDE_CODE FT-031, J07
- **Current evidence:** 10 profiles (SC + 6 HC + NCLT/NCLAT/DRT + generic); remaining 19 HCs use generic fallback
- **Acceptance:** Court-format profile + cause-title rule for every HC that the corpus covers; tribunal-family expansion.

### G-058 Drafting mobile + solo mode parity (Sprint 9-10 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** NFT-013
- **Current evidence:** DraftingStepper 360px responsive + `?solo=1` flatten shipped; broader UX polish + offline drafting absent
- **Acceptance:** Drafting passes axe + 360px sweep + solo mode covers all 20 templates.

### G-059 DocX redline / track-changes export for negotiation (PG-008 sub-scope)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PG-008 CLM lifecycle scope
- **Current evidence:** none
- **Acceptance:** Track-changes DOCX export between two draft versions + reviewer comments.

### G-129 Drafting prompt injects bench-favorability context
- **Status:** Partial · **Priority:** P0
- **PRD ref:** BAAD + LI-S7 + user stance 2026-05-14
- **Current evidence:** Bench-aware appeal drafting v1 shipped (BAAD-001, commit `4a2191d`); `apps/api/tests/test_drafting_bench_aware.py:82-117` proves the predictive addendum fires for every bench-aware template and does not fire for non-bench templates. Remaining: per-template golden + drafting-eval pass at 4.8/5 across the full template set.
- **Acceptance:** Every drafting template consumes a bench-favorability brief when the matter has a hearing on an indexed bench, satisfying all six favorability guardrails: (1) citation-grounded with indexed-decision IDs; (2) sample-size band visible; (3) per-tenant policy gated; (4) `ModelRun` + `AuditEvent` on each render; (5) degrades to "insufficient bench history" when evidence is weak; (6) structural no-fabrication test green. Verification: golden under `apps/api/tests/fixtures/drafting/bench_aware/<template>.json` per template; Playwright drafting-render spec asserts the addendum appears for bench-aware templates and is absent for non-bench templates; drafting eval ≥ 4.8/5 per template.

---

## 6. Hearing prep & mock-hearing gaps

### G-060 Hearing pack auto-trigger + authority matching + DOCX/PDF export (WTD-4.5)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE FT-039, US-025, WTD-4.5
- **Current evidence:** `services/hearing_packs.py` exists; scheduled auto-trigger absent; DOCX/PDF export partial
- **Acceptance:** Hearing-pack auto-trigger N days before listing + authority match using bench-strategy context + exportable DOCX/PDF.

### G-061 Mock-hearing simulator V2 — LLM-graded feedback (LI-S3 follow-on)
- **Status:** Deferred-by-design · **Priority:** P2
- **PRD ref:** LI PRD §LI-S3 (V1 deterministic only)
- **Current evidence:** `apps/api/src/caseops_api/services/mock_hearing.py`, schemas, migration `20260511_0006_mock_hearing_simulator.py`, and UI present on `main`; deterministic V1 only — LLM-graded rubric not active.
- **Acceptance:** Optional LLM feedback persists `ModelRun`; deterministic fallback kept; structural no-emotion/no-biometric test still green. Verification: `apps/api/tests/test_mock_hearing.py` extended with an LLM-path test plus a structural assertion that the response never contains emotion/biometric vocabulary.

### G-062 Voice / audio mock hearing simulator (LI-S3 §Out of scope)
- **Status:** Deferred-by-design · **Priority:** P3
- **PRD ref:** LI PRD §3.2 (Voice and stress simulation deferred)
- **Current evidence:** none
- **Acceptance:** Privacy + consent + retention + provider policy approved BEFORE any voice code.

### G-063 Affidavit-intelligence LLM path (LI-S2 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** LI PRD §LI-S2
- **Current evidence:** `apps/api/src/caseops_api/services/affidavit_intelligence.py`, schema, and migration `20260511_0005_affidavit_intelligence.py` present on `main`; V1 deterministic over raw chunks active — LLM path documented but inactive.
- **Acceptance:** Optional LLM path with source anchors + JSON schema + `ModelRun`; turn-on test asserts no probability/emotional copy. Verification: extend `apps/api/tests/test_affidavit_intelligence.py` with an LLM-path golden + a structural negative-vocabulary assertion.

### G-064 Proceeding-sheet automatic monitoring across verified adapters (LI-S1 follow-on)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** LI PRD §LI-S1
- **Current evidence:** Deterministic extraction from `MatterCourtOrder.order_text` + task/deadline creation + audit; broad daily monitoring deferred
- **Acceptance:** Source-verified court adapters poll proceeding sheets daily; review queue routes high-confidence directions into tasks; external notification gated by human review.

### G-065 Court / hearing day dashboard (PRODUCT_GAP §Court And Hearing Operations)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §4
- **Current evidence:** Per-matter hearings page exists; no cause-list + courtroom + stage + counsel + notes + last-order + next-ask consolidated day view
- **Acceptance:** `/app/hearings/today` cause-list view; client-update generator after each hearing.

### G-066 Mobile hearing-day mode (PG-105)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** PG-105
- **Current evidence:** Mobile responsive layouts; no `/app/m/hearings` PWA install path or offline cache
- **Acceptance:** Phone-first hearings page with offline 24h cache + one-tap status + voice-memo upload.

### G-067 Order-extraction → deadline recalculation loop (PRODUCT_GAP §4)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** LI PRD §LI-S1
- **Current evidence:** `MatterProceedingSignal` extracts directions but recalculation of dependent deadlines on order arrival is not automatic
- **Acceptance:** New order auto-recalculates existing `MatterDeadline` rows + triggers reminder reschedule.

---

## 7. Predictive & analytics intelligence gaps

### G-068 LI-S7D+ predictive surfaces beyond v1 (calibrated model + broader coverage + rollout hardening)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** LI PRD §LI-S7D+; user stance 2026-05-14 (promoted from P1)
- **Current evidence:** `apps/api/src/caseops_api/services/predictive_intelligence.py` + schema + migration `20260511_0002_predictive_intelligence_foundation.py` present on `main` (LI-S7A/B/C data contract + classification + UI); calibration, broader sources, rollout hardening pending. PG-107 bench predictive code at `apps/api/src/caseops_api/services/bench_strategy_context.py:375-392` complements this surface.
- **Acceptance:** Calibrated outcome model with Brier / calibration score covering outcome prediction, motion grant rate, appeal success likelihood, and settlement likelihood — each surface satisfying all six favorability guardrails: (1) citation-grounded (cites underlying authority IDs); (2) sample-size band visible ("n=N, recall@10=…"); (3) per-tenant `TenantAIPolicy.predictive_*_enabled` toggle honored; (4) `ModelRun` + `AuditEvent` emitted on every render; (5) degrades to "insufficient evidence" when sample size is below the per-surface threshold; (6) structural no-fabrication test asserts every numeric claim maps to a source row. Broader source-family coverage + staged per-tenant rollout. Verification: calibration artifact under `docs/eval_artifacts/predictive/` with Brier and reliability curves below threshold; backend tests in `apps/api/tests/test_predictive_intelligence.py` cover the six guardrails per surface.

### G-069 LI-S6 accept / reject / edit review mutations
- **Status:** Deferred-by-design · **Priority:** P2
- **PRD ref:** LI PRD §LI-S6 acceptance
- **Current evidence:** Read-only review page + audit
- **Acceptance:** Reviewer mutation endpoints + per-item disposition audit + signal degradation when rejected.

### G-070 Legal knowledge graph materialization (LI-S6 deferred, US-LI-009)
- **Status:** Deferred-by-design · **Priority:** P2
- **PRD ref:** LI PRD §3.9, US-LI-009
- **Current evidence:** Citation graph + judge appointments + statutes exist as substrate; no graph API/UI
- **Acceptance:** `legal_graph_nodes` + `legal_graph_edges` materialized nightly + `/api/legal-graph` + UI explorer.

### G-071 Per-tenant AI spend dashboard + retrieval quality dashboard (PG-206)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PG-206
- **Current evidence:** `ModelRun` + `VoyageUsage` ledgers exist; no operator dashboard surface
- **Acceptance:** Admin `/app/admin/ai-spend` shows per-tenant per-purpose token + dollar burn + caps + alerts.

### G-072 Sources-used / sources-ignored panel on drafts + hearing-packs (PG-109 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** PG-109
- **Current evidence:** Recommendation source panel shipped (migration `20260501_0002`); draft + hearing-pack panels missing
- **Acceptance:** Same "sources considered / cited" panel on draft detail + hearing-pack detail.

### G-073 Per-workflow LLM evaluation harness + goldens (PG-110, WTD-11.4)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** PG-110; PRD_CLAUDE_CODE §15
- **Current evidence:** `services/evaluation.py` skeleton + `caseops-eval-citations` + `caseops-eval-workflows`; no automated goldens per workflow
- **Acceptance:** Golden datasets for bail, anticipatory bail, quashing, Section 34, commercial suit, writ, cheque bounce; CI gate on each. Verification: each golden lives under `apps/api/tests/fixtures/workflows/<workflow>.json`; CI job fails when any workflow's threshold (citation-coverage, hallucination-rate, refusal-on-no-authority) regresses.

### G-074 AI safety benchmark automation (WTD-11.4)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** SEC-014 (prompt-injection + data-exfiltration benchmark)
- **Current evidence:** Single-test prompt-injection cases present; no scheduled benchmark
- **Acceptance:** Nightly suite covering prompt-injection + data-exfiltration + refusal + jailbreak on research + drafting + recommendations + matter-file-qa.

### G-075 Litigation Strategy & Escalation Planner — V2 multi-tenant cross-matter comparison
- **Status:** Deferred-by-design · **Priority:** P3
- **PRD ref:** PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03 §7 (Out of scope v1)
- **Current evidence:** v1 service `litigation_strategy.py` shipped; cross-matter retrieval boundary unbuilt
- **Acceptance:** Separate PRD + cross-matter retrieval policy + tenant opt-in.

### G-076 Litigation Strategy — cost / quantum modeling
- **Status:** Deferred-by-design · **Priority:** P3
- **PRD ref:** PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03 §7
- **Current evidence:** none
- **Acceptance:** Separate PRD.

### G-130 Per-matter outcome forecast (cited)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRD_LI_EXPANSION §LI-S7D; user stance 2026-05-14
- **Current evidence:** none
- **Acceptance:** Matter cockpit shows a forecast band (e.g. "Bail likely granted, n=312 comparable matters before this bench, recall@10=0.91") with drill-down to cited decisions; all six favorability guardrails enforced: (1) citation-grounded — drill-down lists every authority ID driving the band; (2) sample-size band visible; (3) tenant-policy gated via `TenantAIPolicy.predictive_*_enabled`; (4) `ModelRun` + `AuditEvent` on each render; (5) degrades to "insufficient comparable history" when below the per-position sample-size threshold; (6) structural no-fabrication test green. Verification: forecast API test in `apps/api/tests/test_matter_outcome_forecast.py`, Playwright cockpit spec asserts the band + drill-down + degrade path, SQL assertion on `AuditEvent` rows per render, synthetic no-fabrication fixture.

---

## 8. Litigation strategy / escalation planner gaps

### G-077 Strategy-planner HTTPS→HTTP redirect on trailing-slash (STRATEGY_PLANNER_FOLLOWUPS §1)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** STRATEGY_PLANNER_FOLLOWUPS_2026-05-03 §1
- **Current evidence:** FastAPI `redirect_slashes=True` builds Location header from request scheme; behind Cloud Run TLS terminator the redirect drops to HTTP
- **Acceptance:** `ProxyHeadersMiddleware` wired in `main.py` so scheme reflects `X-Forwarded-Proto`; redirect probe returns HTTPS.

### G-078 Strategy-planner full UAT smoke after PR-8 fixes
- **Status:** Partial · **Priority:** P2
- **PRD ref:** STRATEGY_PLANNER_FOLLOWUPS_2026-05-03 §2-3 (both closed by PR #8)
- **Current evidence:** Code-side closes shipped + regression tests; real-data prod probe across forum_sequence + recommended_drafts on a sparse-retrieval matter still on followup list
- **Acceptance:** End-to-end prod probe ≥ 1 matter where strategy returns non-empty `recommended_drafts` + cited authorities.

---

## 9. Matter file Q&A gaps (MFQ residual)

### G-079 MFQ export to matter brief + richer hearing-prep artifact
- **Status:** Partial · **Priority:** P2
- **PRD ref:** PRD_MATTER_FILE_QA_2026-05-13 §7.2 (planned), §21
- **Current evidence:** `apps/api/src/caseops_api/services/matter_file_qa.py` + schema + migration `20260513_0001_matter_file_qa_history.py` present on `main`; idempotent export-to-matter-note shipped — export-to-brief / hearing-pack endpoint absent.
- **Acceptance:** `POST /api/ai/matters/{id}/file-qa/{entry_id}/export-to-brief` writes a structured brief section with bounded sources. Verification: backend test asserts idempotency (re-POST same entry returns same brief-section row) and source-boundary (only matter-uploaded chunks cited).

### G-080 MFQ multi-document comparison mode
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_MATTER_FILE_QA_2026-05-13 §7.2
- **Current evidence:** Single-question retrieval over all matter chunks only
- **Acceptance:** Diff mode: "compare allegations in FIR vs charge-sheet" returns paired source snippets.

### G-081 MFQ document-viewer-scoped Q&A
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_MATTER_FILE_QA_2026-05-13 §7.2
- **Current evidence:** Documents-page section only
- **Acceptance:** Q&A panel inside `/app/matters/[id]/documents/[attachment_id]/view`.

### G-082 MFQ conversation memory across questions
- **Status:** Missing · **Priority:** P3
- **PRD ref:** PRD_MATTER_FILE_QA_2026-05-13 §7.2
- **Current evidence:** One-shot Q&A; no session memory
- **Acceptance:** Optional chained-question mode with bounded context window.

### G-083 MFQ voice/audio input
- **Status:** Deferred-by-design · **Priority:** P3
- **PRD ref:** PRD_MATTER_FILE_QA_2026-05-13 §7.2
- **Current evidence:** none
- **Acceptance:** Requires voice privacy policy first.

---

## 10. Workspace / collaboration / approvals / contracts gaps

### G-084 Universal command palette / global search (PG-101)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PG-101; PRODUCT_GAP §16 UX
- **Current evidence:** `/app/research` only; no cross-resource palette
- **Priority rationale:** Improves operator speed; does not block any single J05-J09 litigation journey end-to-end. Demoted from P0 per Codex Check C 2026-05-14.
- **Acceptance:** `Cmd+K` searches matters / clients / drafts / hearings / authorities / contacts ranked + tenant + matter-access scoped. Verification: Playwright spec asserts the palette hides resources outside the user's tenant and outside their matter-access set (negative cases for both).

### G-085 Review queue inbox — drafts + recs + KYC + invoices + contracts (PG-102)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PG-102
- **Current evidence:** Each module has its own review path
- **Acceptance:** `ReviewItem` polymorphic table + `/app/review` aggregator + partner dashboard.

### G-086 Communications inbound capture + threading (PG-106)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PG-106; PRD_CLAUDE_CODE J12
- **Current evidence:** `services/communications.py` reads existing rows; no inbound forwarder
- **Acceptance:** Inbound forwarder `matter+<id>@caseops.ai` creates MatterCommunication; threaded UI; read receipts.

### G-087 Microsoft 365 + Google Workspace email/calendar integration (PRODUCT_GAP §12 Communications)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §12; WTD-12.3
- **Current evidence:** none — no OAuth integration code
- **Acceptance:** OAuth-based Microsoft + Google email/calendar adapters + matter-based email filing.

### G-088 AutoMail depth (M11)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE FT-047, FT-048, US-036
- **Current evidence:** Template-driven outbound shipped; delivery webhook + comm status flow partial
- **Acceptance:** Per-template outbound + tracked delivery status + per-recipient bounce/retry.

### G-089 CLM lifecycle — request → approval → e-sign → obligations (PG-008)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PG-008; PRD_CLAUDE_CODE J10
- **Current evidence:** `apps/api/src/caseops_api/db/models.py:2595`, `:2723`, and `:2974` already model contracts, obligations, and attachments; `services/contract_intelligence.py` extracts metadata. ContractRequest / ContractApproval / ESignature lifecycle objects pending.
- **Priority rationale:** Core LegalWorkspace/GC feature; not the litigation-wedge P0 path. Demoted from P0 per Codex Check C 2026-05-14.
- **Acceptance:** Intake → approval matrix → e-sign integration → obligation calendar → renewal alerts. Verification: Playwright path `request → approval → e-sign → obligation → renewal-alert` green; backend audit assertions on each transition.

### G-090 Contract type + legal classification + ancillary docs (LegalWorkspace §18)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05 §18; migration `20260506_0004_legalworkspace_contract_metadata.py`
- **Current evidence:** Migration shipped; UX coverage + ancillary categorization (amendment / annexure / approval / PO) needs verification
- **Acceptance:** Controlled-type contract create form + ancillary attachment role + clause/section index in contract repo search.

### G-091 GC spend depth — rate cards + budgets + billing guidelines + scorecards (PG-007)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PG-007; PRD_CLAUDE_CODE US-038, US-039, J13
- **Current evidence:** `apps/api/src/caseops_api/api/routes/outside_counsel.py` exposes portfolio analytics (`/workspace`) and spend recording (`/spend-records`); `services/outside_counsel.py` covers profile + assignment. Full `RateCard` / `MatterBudget` / `BillingGuideline` / `OutsideCounselScorecard` depth remains.
- **Priority rationale:** Core GC feature; not the litigation-wedge P0 path. Demoted from P0 per Codex Check C 2026-05-14 (also corrected from Missing → Partial).
- **Acceptance:** Full spend stack + executive dashboard (spend by firm / matter / practice + budget variance + aging). Verification: backend tests for rate-card application, budget variance, billing-guideline enforcement, scorecard computation, executive-dashboard endpoint with tenant-isolation negative test.

### G-092 Outside-counsel cross-counsel visibility toggle UX (Phase C-3 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** FT-074
- **Current evidence:** Migration `oc_cross_visibility_enabled` shipped (AQ-005 verified PG insertion); UI toggle visibility pending
- **Acceptance:** Admin per-grant toggle + audit.

### G-093 Employee admin + bulk import + custom roles (LegalWorkspace §19-§20)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05 §19-§20; migrations `20260506_0001-0003`
- **Current evidence:** Migrations + service files shipped (`employee_imports.py`, `employees.py`, `custom_roles.py`); UX surfacing in admin needs verification
- **Acceptance:** Admin employee directory + CSV bulk-import wizard + custom-role builder + permission simulator.

### G-094 SSO role-mapping + permission templates UI (LegalWorkspace §19)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** SEC-020; G-006 (SSO blocker)
- **Current evidence:** none
- **Acceptance:** After G-006 ships, admin maps SSO group → custom role.

### G-095 Legal translator module (MOD-TS-003, M17)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_CLAUDE_CODE J16, US-048, US-049, FT-067, FT-068; MOD-TS-003
- **Current evidence:** none — no translation UI / glossary store
- **Acceptance:** Side-by-side English ↔ Hindi + regional pairs; legal glossary preserved; export.

### G-096 Support / help module (MOD-TS-011, M14)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRD_CLAUDE_CODE J14, US-043, FT-063; MOD-TS-011
- **Current evidence:** none — no in-app help / feedback / ticketing
- **Acceptance:** Help center + feedback form + ticket creation.

### G-097 Empty-state copy hygiene sweep (PG-204)
- **Status:** Partial · **Priority:** P3
- **PRD ref:** PG-204
- **Current evidence:** Founder/prototype language remains on a few pages
- **Acceptance:** Audit-pass across all `apps/web/app/app/**` empty states.

---

## 11. Frontend UX, responsive, accessibility gaps

### G-098 Page-level sibling tests for residual uncovered pages (AQ-003)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** AQ-003
- **Current evidence (re-measured on `main`):** 44 authed app pages; 9 missing sibling `page.test.tsx` files per `apps/web/app/__page-coverage-matrix.test.ts:26-68` allow-list (down from 30 baseline).
- **Acceptance:** Sibling page test for every authed `/app/**` route; marketing pages have SEO + CTA + mobile + keyboard automation. Verification: `ALLOWED_UNTESTED` set in `apps/web/app/__page-coverage-matrix.test.ts` is empty for authed routes; matrix test green.

### G-099 Mobile (360px) responsive sweep across all forms / dialogs / cockpit tabs
- **Status:** Partial · **Priority:** P1
- **PRD ref:** NFT-013; user memory feedback_brutal_bug_fixing_2026_04_24.md
- **Current evidence:** `tests/e2e/mobile-responsive.spec.ts` covers 3 cases; full cockpit + drafting + contracts + portal not asserted
- **Acceptance:** 360×800 scrollWidth assertion on every authed page + form-submit probe.

### G-100 Route-wide accessibility automation (WTD-11.7)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** NFT-014
- **Current evidence:** Axe sweeps cover smoke surfaces only
- **Acceptance:** axe on every authed page + keyboard navigation test + focus order test.

### G-101 Impeccable design audit pass on cockpit + drafting + research + recommendations
- **Status:** Partial · **Priority:** P2
- **PRD ref:** CLAUDE.md Frontend rules + `.impeccable.md`
- **Current evidence:** Per-feature impeccable craft done; system-wide audit pending
- **Acceptance:** Audit-skill report + critical findings closed; OKLCH-only palette + Bloomberg-Terminal density verified.

### G-102 Universal saved-views + keyboard shortcuts (PRODUCT_GAP §16)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRODUCT_GAP_ANALYSIS_2026-05-01 §16
- **Current evidence:** none
- **Acceptance:** Saved-view per list page + power-user shortcuts documented.

### G-103 Persona-specific dashboards (PRODUCT_GAP §17 Reporting)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PRODUCT_GAP §17
- **Current evidence:** `/app/today` only
- **Acceptance:** Partner dashboard (utilization + revenue + matter risk) + GC dashboard (spend + cycle time + vendor scorecard) + solo dashboard (cash + hearings).

---

## 12. Testing, QA, and verification gaps

### G-104 Backend full coverage threshold ratchet (AQ-001 sub-item)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** AQ-001
- **Current evidence:** 81% full-suite line; ratchet not enforced (per-area gates cover 9 files); 779 passed local / 11 skipped / 1643s Windows
- **Acceptance:** CI fails on regression of total backend coverage (line + branch) OR per-area gate expanded to full surface.

### G-105 API route operation-level coverage matrix (AQ-004 / P1-002)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** AQ-004
- **Current evidence:** Route matrix exists; 16 `ALLOWED_UNTESTED` baseline waivers remain
- **Acceptance:** Each route × {happy / negative / auth / authz / tenant / audit / rate-limit} category covered; waivers burned down.

### G-106 PRD-complete E2E coverage (WTD-11.6)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** WTD-11.6
- **Current evidence:** 66 Playwright tests across 19 spec files; full PRD journey set not exhausted
- **Acceptance:** Every J0X / FT-* mapped to one Playwright spec + each spec wired into default CI testMatch.

### G-107 Authorization matrix tests (WTD-11.2)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** SEC-003, SEC-004
- **Current evidence:** `apps/api/src/caseops_api/api/dependencies.py:259-278` enforces capabilities; `apps/api/tests/test_role_guards.py:140` sweeps mutating routes. Exhaustive role × resource × action coverage is not complete (corrected from Missing → Partial per Codex Check A 2026-05-14).
- **Acceptance:** Per-capability matrix test against every protected route; cross-tenant 404 enforced. Verification: generated route × role × capability matrix artifact under `docs/audit/route_role_matrix.json`; cross-tenant 404 negative test for every protected route in the matrix; CI fails when a new route lands without a matrix row.

### G-108 Payment verification depth (WTD-11.5)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRD_CLAUDE_CODE J11
- **Current evidence:** `tests/e2e/billing-payment.spec.ts:39-46` (provider-gated skip); no UAT proof
- **Acceptance:** `CASEOPS_RELEASE_MODE=true` job in release CI exercises Pine Labs UAT; webhook signature + idempotency proven.

### G-109 Browser-diversity Playwright matrix (AQ-006 sub-item)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** AQ-006
- **Current evidence:** Single browser; release matrix not configured
- **Acceptance:** Chrome + Firefox + WebKit + mobile-WebKit matrix on every E2E spec.

### G-110 Garbled-snippet detector regression suite (BUG-026 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** docs/BUG_VERIFY_HARI_RAM_2026-04-28.md
- **Current evidence:** Detector exists; ≥ 10 real-data failure samples not in regression
- **Acceptance:** Regression-test detector against ≥ 10 REAL failure samples; replace synthetic-only checks.

### G-111 Manual-tester replacement standard (AQ-* aggregate)
- **Status:** Partial (NO-GO per audit) · **Priority:** P0
- **PRD ref:** AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25 verdict
- **Current evidence:** AQ-001 / 003 / 004 / 006 partial
- **Acceptance:** All AQ items `Implemented`; CI demonstrably catches ≥ 95% of regression escapes for 30 days running. Verification: define the regression-escape denominator as bugs filed with `regression` label against the 30-day production window; CI artifact `docs/audit/regression_escape_30d.json` updated weekly; release sign-off fails when the rolling 30-day catch rate drops below 95%.

### G-112 Web v8 coverage threshold ratchet (AQ-002 follow-on)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** AQ-002 (closed) — ratchet remains operational concern
- **Current evidence:** Thresholds `lines:31 / statements:30 / branches:22 / functions:25` (rounded down from baseline)
- **Acceptance:** Quarterly ratchet upward; no down-ratchet to silence flakes.

---

## 13. Operational / observability / cost gaps

### G-113 Model-evaluation admin gate + cost rollup (WTD-7.3)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** WTD-7.3
- **Current evidence:** `services/evaluation.py:12-137` + `EvaluationRun` model
- **Acceptance:** Admin `/app/admin/eval` shows last run + threshold + block-release toggle; per-purpose cost rollup.

### G-114 Connector health UI + blocked-reason reporting (WTD-12.2)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** NFT-LI-005
- **Current evidence:** none
- **Acceptance:** Admin connector dashboard shows last success / last failure / parser version / blocked reason per adapter.

### G-115 Broader court adapters + per-tenant connector credentials (WTD-12.1)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** WTD-12.1
- **Current evidence:** SC + 6 HC official adapters; broader district / tribunal blocked
- **Acceptance:** Per-tenant credential vault (Bar Council ID + password) + connector for each verified adapter.

### G-116 Inbound email ingest into MatterCommunication (WTD-12.3b)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** WTD-12.3b (split from WTD-12.3 on 2026-05-14; calendar-sync half is closed per WTD-12.3a — see Appendix B)
- **Current evidence:** No `services/email_ingest*`, `services/inbound_email*`, or `routes/inbound*` on `main` (HEAD `58116d2`); existing `services/email_templates.py` + `services/email_suppression.py` are outbound-only and do not satisfy this gap. Calendar sync side is Implemented (`services/calendar_sync.py`, `api/routes/calendar.py`, three test files) and tracked as closed under WTD-12.3a.
- **Acceptance:** Inbound IMAP, Microsoft Graph, and Gmail API receivers write into `MatterCommunication` with (a) matter-threading rule (subject + In-Reply-To + participant) covered by `apps/api/tests/test_email_ingest.py` (to be added), (b) idempotent dedupe by Message-ID, (c) `AuditEvent` on every ingest, (d) per-tenant credential vault + revocation, (e) attachment passthrough to `MatterDocument` with the same ClamAV gate as upload path, (f) tenant-isolation test proving cross-tenant Message-ID collisions cannot leak.

### G-117 Tenant AI-spend daily cap + alert + auto-throttle (PG-206 sub-item)
- **Status:** Partial · **Priority:** P0
- **PRD ref:** user memory feedback_corpus_spend_audit
- **Current evidence:** ModelRun + VoyageUsage ledgers; daily cap `$100` for metadata_extract; auto-throttle missing
- **Acceptance:** Per-tenant per-purpose cap enforced server-side; threshold alert; auto-throttle on breach. Verification: backend test asserts cap enforcement at the per-tenant × per-purpose key (e.g. `metadata_extract`), alert emission via the notification channel, and a hard-block / auto-throttle negative test that proves further calls are rejected once the cap is breached.

### G-118 Post-deploy staleness sweep automation
- **Status:** Partial · **Priority:** P2
- **PRD ref:** user memory feedback_post_deploy_staleness_check
- **Current evidence:** Manual `scripts/verify-release.{sh,ps1}` + 4-step manual sweep
- **Acceptance:** Post-deploy hook runs HEAD vs revision tag + public-domain health + new-shape smoke + web BUILD_ID over the wire; pass before "deployed" message.

### G-119 Ingest-VM watchdog soak + alert escalation
- **Status:** Partial · **Priority:** P2
- **PRD ref:** docs/INGEST_WATCHDOG_SOAK_2026-05-04.md + user memory feedback_ingestor_vm_hourly_watchdog
- **Current evidence:** Cloud Scheduler → Cloud Run Job watchdog `caseops-ingest-watchdog-15m` shipped
- **Acceptance:** Soak ≥ 14d; alert routes to operator email if 3 successive watchdog runs report stalled progress.

### G-120 Observability — per-tenant retrieval quality dashboard (NFT-018)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** NFT-018
- **Current evidence:** `caseops-eval-hnsw-recall` writes evaluation_runs / evaluation_cases; admin dashboard pending
- **Acceptance:** Admin dashboard renders recall@10 / MRR / rank trends per court bucket with stop-the-line alert on bucket-over-bucket drop.

### G-121 OpenAPI client drift gate (DRIFT-004 / WTD-6.5)
- **Status:** Partial · **Priority:** P2
- **PRD ref:** WTD-6.5
- **Current evidence (re-measured on `main`):** `apps/web/lib/api/openapi-types.ts` generated; manual `apps/web/lib/api/endpoints.ts` (4156 LOC) still hand-maintained; CI drift check exists at `.github/workflows/security.yml:140-150`.
- **Acceptance:** Endpoint shape derived from generated types; CI fails on manual drift. Verification: `endpoints.ts` removed in favour of a generated client (or shrunk to ≤ 200 LOC of bespoke wrappers); drift CI job stays green; type-check against `openapi-types.ts` covers every wrapper.

---

## 14. Onboarding / migration / business gaps

### G-122 Bulk migration importers (PG-203)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PG-203; PRODUCT_GAP §18 Onboarding
- **Current evidence:** Employee CSV importer shipped (LegalWorkspace §20); matter/client/contact CSV missing
- **Acceptance:** CSV importer for matters + clients + contacts + tasks + invoices + contracts + one practice-management adapter; duplicate detection.

### G-123 Court fee + limitation + stamp + filing deadline calculators (PG-111)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** PG-111
- **Current evidence:** none
- **Acceptance:** Calculator service per state/court covering court fees + stamp duty + limitation + filing deadlines; widget in cockpit + drafting prep.

### G-124 Billing depth — WIP / aging / realization / GST / TDS (PG-112)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PG-112
- **Current evidence:** `MatterInvoice` + `MatterTimeEntry`; no aging/realization/WIP reports; no GST/TDS
- **Acceptance:** Aging report (0-30/30-60/60-90/90+) + realization rate + WIP dashboard + GST (CGST/SGST/IGST) + TDS + Tally/Zoho export.

### G-125 Analytics dashboards — matter aging + hearing load + utilization (PG-202)
- **Status:** Missing · **Priority:** P2
- **PRD ref:** PG-202
- **Current evidence:** none (depends on G-124)
- **Acceptance:** Persona dashboards + scheduled reports + drill-down.

### G-126 Pricing / packaging surfaces in-product (PG-201 / WTD-10.5)
- **Status:** Missing · **Priority:** P1
- **PRD ref:** Cross-ref G-008
- **Current evidence:** Marketing pricing exists; in-product plan badge / upgrade CTA missing
- **Acceptance:** Per-user plan + entitlement badges + upgrade flow.

### G-127 GC legal-front-door + intake/triage/SLA (PRODUCT_GAP §8)
- **Status:** Partial · **Priority:** P1
- **PRD ref:** PRODUCT_GAP §8 GC
- **Current evidence:** `apps/api/src/caseops_api/api/routes/intake.py:44-104` exposes list / create / triage / promote endpoints; `apps/web/app/app/intake/page.tsx` renders the intake UI (corrected from Missing → Partial per Codex Check A 2026-05-14). SLA + capacity dashboard + stakeholder portal status remain missing.
- **Acceptance:** Business-user legal-request portal + auto-triage + SLA + capacity dashboard + stakeholder status. Verification: backend tests assert SLA timer enforcement and capacity dashboard endpoint returns per-attorney load; Playwright spec for stakeholder portal status visibility.

---

## 15. Explicitly Deferred-by-design (out of immediate scope but planned)

> Items previously deferred under the neutrality stance (PRD §10.6) have been promoted to active workplan as of 2026-05-14. See top hard-rails line and `feedback_user_bias_in_recommendations.md`. G-044 (now active P0) and G-045 (now active P1) were removed from this table.

| ID | Item | Source | Why deferred |
|---|---|---|---|
| G-046 | Real cause-list scraper per court | PRD_CAUSE_LIST_SCRAPER | PRD body unwritten |
| G-047 | Manual cause-list paste-in | PRD_CAUSE_LIST_SCRAPER §What's NOT in scope | Separate PRD |
| G-062 | Voice / audio mock hearing | LI PRD §3.2 | Privacy + consent + retention policy missing |
| G-069 | LI-S6 review mutations | LI PRD §LI-S6 | Read-only V1 stable; mutations follow user signal |
| G-070 | Legal knowledge graph materialization | LI PRD §3.9 | Citation/judge graphs serve V1; full graph deferred |
| G-075 | Litigation strategy cross-matter compare | Strategy PRD §7 | Cross-tenant retrieval boundary unbuilt |
| G-076 | Litigation strategy cost/quantum | Strategy PRD §7 | Separate PRD |
| G-083 | MFQ voice/audio | MFQ §7.2 | Same voice policy gap as G-062 |
| G-041 / G-042 | Licensed commentary (SCC / Manupatra / Indian Kanoon) | LI PRD §5.1; PG-006 | Cost discipline — re-evaluate when revenue covers $5-10K/mo |

OCR Phase 2 (libGL on caseops-ingest-vm — user memory project_en_sweep_phase1_2026_04_26.md) is operationally gated, not PRD-gated: re-enable once libGL is available on the ingest VM image.

---

## Appendix A: Sources consulted

Code state was sampled, not exhaustively read (re-measured on `main` `58116d2` 2026-05-14):
- 28 API route modules in `apps/api/src/caseops_api/api/routes/`
- 86+ service modules in `apps/api/src/caseops_api/services/` (now includes `matter_file_qa.py`, `mock_hearing.py`, `affidavit_intelligence.py`, `predictive_intelligence.py`, `proceeding_intelligence.py`)
- `apps/web/app/app/` top-level + 13 `/app/matters/[id]/*` sub-routes (44 authed app pages)
- 77 alembic migrations under `apps/api/alembic/versions/` (oldest 2026-04-21, newest `20260513_0001_matter_file_qa_history.py`)

PRDs and ledgers consulted are listed at the top of this file.

---

## Appendix B: Status of major items closed since last gap doc (for audit trail)

Closed and removed from active workplan (verified via STRICT_ENTERPRISE_GAP_TASKLIST + STRICT_PRODUCT_GAPS):

- **EG-001** browser bearer-token hardening (commit `fbb6a29`, rev `00042-zlj`)
- **EG-002** deploy-time migration safety (`scripts/deploy-prod.sh` + migrate-job gate)
- **EG-003** clamav sidecar fail-closed (rev `00049-m6c`, EICAR prod smoke)
- **EG-004** AI route rate limits (P1-007)
- **EG-005** matter summary cache + ModelRun audit + cross-provider cutover
- **EG-006** draft preview tenant-policy gate + redacted 502 + ModelRun audit on success/failure
- **EG-007** Secret Manager wiring + 90-day rotation drill (rev `00052-5w2`)
- **P0-001 … P0-005** Strict Repo Quality Audit P0 findings (commit `161c384`)
- **P1-001 / P1-004 / P1-005 / P1-007 / P1-008 / P1-009 / P1-010** (security scans, mobile/axe smoke, AI rate-limit, upload cap, restore drill, OpenAPI drift gate)
- **MOD-TS-001 / 001-A / 001-B / 001-C / 001-D / 001-E** (judge profile + appeal strength + career history + bench resolver + bench-specific BAAD + judge aliases)
- **MOD-TS-013** clients verification (KYC)
- **MOD-TS-014 / 015 / 016** Portal Phase C-1/C-2/C-3
- **MOD-TS-017** Statute model v1 (WTD-7.4) — long-tail enrichment still open as G-036/G-037
- **PG-001** v1 (intake gate still G-022)
- **PG-004** Today view
- **PG-005** Drafting Sprints 1-12 (quality 4.8/5 still open as G-051)
- **PG-107** v1 + v1.5 + v2 predictive bench strategy governance
- **PG-109** sources-used panel on recommendations (G-072 covers drafts + hearing-packs)
- **PG-110** research language filter + pagination v1
- **AQ-002** frontend coverage gate (CI-wired; G-112 covers ratchet)
- **AQ-005** Postgres-validation foundation (G-017 expands surface)
- **BAAD-001** bench-aware appeal drafting (G-056 expands to remaining templates)
- **MFQ-S0 / S1 / S2 / S3 / S4 / S5** Matter File Q&A V1 (G-079..G-083 cover residual)
- **LI-S1 / S2 / S3 / S4 / S5 / S6 / S7A / S7B / S7C / S8** Litigation Intelligence Expansion V1 (G-068 covers LI-S7D+; G-064 covers monitoring scale-out)
- **Strategy planner PR #7 + PR #8** (G-077 covers redirect fix; G-078 covers UAT)
- **WTD-12.3a** Calendar sync — OAuth Outlook + Google, encrypted credentials, bulk backfill, per-event sync ledger. Closed 2026-05-14 (split from WTD-12.3; inbound email half remains open as G-116). Evidence: `services/calendar_sync.py`, `api/routes/calendar.py`, `schemas/calendar.py`, migration `20260507_0001_legalworkspace_calendar_notifications.py`, `tests/test_calendar.py` + `test_legalworkspace_calendar_sync.py` + `test_outlook_bulk_sync.py`, `apps/web/app/app/calendar/page.tsx`.

---

**End of workplan.** Update this file in the same task as any item closure; do not let the ledger drift behind code.
