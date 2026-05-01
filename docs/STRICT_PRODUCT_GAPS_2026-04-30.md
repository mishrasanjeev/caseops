# Strict Product Gap Tasklist — 2026-04-30

Anchor: `docs/PRODUCT_GAP_ANALYSIS_2026-04-30.md` (Codex, 655 lines).
Purpose: convert that report into a fail-closed, single-source-of-truth
ledger so every gap has a status, a code anchor, an owner, and an
estimated burn-down. Mirror of the strict-ledger pattern used in
`STRICT_ENTERPRISE_GAP_TASKLIST.md`, `STRICT_BUG_TASKLIST_2026-04-22.md`,
and `STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`.

## Allowed Status Labels

- `Implemented` — code, tests, and (where relevant) deploy/runtime evidence all match the gap's "needed" definition.
- `Partially implemented` — some scope shipped; named sub-items remaining.
- `Missing` — no code today.
- `Stale-doc` — the gap claim is wrong or out-of-date in the source report.
- `Cross-referenced` — already tracked under a different ID in another strict ledger; do not duplicate work here.

## Forbidden Closure Patterns

- "Fixed" because copy improved on a marketing page.
- "Fixed" because we shipped a *related* surface (e.g., shipping a research panel does not close treatment/good-law signal).
- "Fixed" because docs say so without a code anchor.
- Counting Round-1..Round-4 (today) work toward gaps it doesn't actually close.

## Verdict

**Gap volume**: 60+ distinct items across 12 sections.
**Realistic burn-down**: 12+ engineer-months (multi-quarter).
**Today's status**: 5 items shipped this session (4 of them not in the Codex report when written), 6 items already tracked elsewhere, 49+ open.
**Right move per Codex's own §"Brutal Prioritization"**: pick the litigation-heavy Indian law firms wedge, ship Phase-1 (litigation daily workflow) before expanding scope.

## Items Already Closed in Today's Session (2026-04-30)

These were shipped before/while Codex's report was written. Where the report
restates them as gaps, treat as `Stale-doc`.

| Codex theme | What landed | Commit |
|---|---|---|
| AI trust — citation correctness | Bracket-tag fast path + canonical-identifier surface in `services/citations.py` + `services/recommendations.py`; UI shows clean canonical citations. | `ceb8e01` |
| Daily-driver reliability — recommendations hang | HNSW prefilter rewrite in `services/authorities._pg_prefilter_document_ids`; stress matter <120s. | `da7216a` |
| AI provider trust + cost discipline | Anthropic retired; gpt-5.1 sole provider; 552-line removal of fallback ladders across 5 services. | `39cd459` |
| LLM perf calibration | Per-purpose timeouts for OpenAI; `reasoning_effort=low` for gpt-5.x. | `9d16087` |
| Matter cockpit next-action surface (partial) | "+ Add hearing" CTA on cockpit empty-state; shared `ScheduleHearingDialog` component. | `f641e4b` |

## Cross-Reference: Already Tracked in Other Strict Ledgers

Do not re-classify these here. Burn-down lives under the linked ID.

| Codex theme | Existing ID | Existing status | Source ledger |
|---|---|---|---|
| Hotspot decomposition (large pages/services) | `EG-008` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Exception-handling discipline | `EG-009` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Temporal durable workflows | `WTD-5.1` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Agent identity / Grantex | `WTD-5.2` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Notification service durable delivery | `WTD-5.3` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| OpenAPI / generated client rollout | `WTD-6.5` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Matter cockpit Tasks/Deadlines tabs + admin task templates | `WTD-7.2` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Model-evaluation admin gate + cost rollup | `WTD-7.3` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Docling/Tika/PaddleOCR + structural extraction | `WTD-9.1`/`9.2` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Tenant management console | `WTD-10.1` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| OIDC / SAML SSO | `WTD-10.2` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| AI policy controls | `WTD-10.3` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Plan entitlements | `WTD-10.5` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Authorization matrix tests | `WTD-11.2` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| AI safety benchmark automation | `WTD-11.4` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| PRD-complete E2E coverage | `WTD-11.6` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Route-wide accessibility automation | `WTD-11.7` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Broader court adapters / per-tenant credentials | `WTD-12.1` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Connector health UI | `WTD-12.2` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Email ingest + calendar sync | `WTD-12.3` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Backend coverage threshold ratchet | `AQ-001` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Page-level UI coverage | `AQ-003` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| API route operation-level coverage | `AQ-004` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Postgres-CI for all DB-sensitive tests | `AQ-005`-followon | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Provider-skip-on-release | `AQ-006` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Garbled-snippet detector regression suite | `BUG-026` | `Partially fixed` | docs/BUG_VERIFY_HARI_RAM_2026-04-28.md |

## P0 — New Gaps Tracked Here (Stop-Ship for "Best for Law Firms" claim)

### `PG-001` Conflict check workflow
Status: **`Partially implemented`** (v1 MVP shipped 2026-04-30; intake gate deferred to v2).
Evidence:
- DB: `MatterConflictCheck` model + migration `20260430_0001_matter_conflict_checks` (status enum: pending/cleared/conflicted/waived).
- Service: `services/conflict_checks.py` with substring + Jaccard token-overlap scanner across `clients` + `matters`.
- Routes: `POST /api/matters/{id}/conflict-checks`, `GET /api/matters/{id}/conflict-checks`, `PATCH /api/conflict-checks/{id}`.
- Capabilities: `conflicts:run` (every fee-earner) + `conflicts:resolve` (staff only).
- UI: `apps/web/components/matters/ConflictCheckCard.tsx` mounted on `/app/matters/[id]` cockpit. Run dialog + status badge + candidate list + clear / mark-conflicted / waive controls.
- Tests: 6 backend cases (`tests/test_conflict_checks.py`); prod-Playwright spec runs scenario A (existing-client overlap) end-to-end.
Remaining (v2):
- Intake gate: block matter status promotion `intake → active` unless latest check is `cleared` or `waived`.
- Contacts beyond `Client` (witnesses, opposing counsel, vendors) — needs separate contact table.
- Bulk waiver / partner-approval email workflow.
Estimated days remaining: 1-2.

### `PG-002` Engagement letter / fee arrangement workflow
Status: **`Missing`**.
Evidence: no `engagement_letter`, `fee_arrangement`, or related templates in `apps/api/src` or `apps/web`.
Needed:
- DB: `MatterEngagement` (matter_id, fee_basis hourly/fixed/contingent, retainer_amount, scope, signed_at).
- Service: generate engagement letter from matter facts + firm template; persist signed PDF to attachments.
- UI: engagement step in intake flow; printable/exportable letter; client portal acknowledgement.
Estimated days: 3-4 (gated by `PG-005` template engine).

### `PG-003` Trust / retainer / advance ledger
Status: **`Missing`**.
Evidence: no `trust_account`, `retainer_account` references; `MatterInvoice` exists but no advance-balance schema.
Needed:
- DB: `MatterTrustLedger` (matter_id, txn_type [deposit/withdrawal/transfer], amount, balance, txn_date, source_invoice_id).
- Service: balance computation; invoice-from-trust; refund-on-close.
- UI: matter Billing tab gets a Trust ledger card; admin Trust report.
- Compliance: per-state Bar rules around trust accounting (India Bar Council rules vary).
Estimated days: 5-6.

### `PG-004` Matter command center / "Today" view
Status: **`Missing`** (today's `+ Add hearing` empty-state addresses ~5% of this).
Evidence: no `today_view`, `command_center`, or matter-cockpit aggregator beyond `apps/web/app/app/matters/[id]/page.tsx` (260 lines, single-section view).
Needed:
- New `/app/today` page: per-user pre-aggregated list of (i) hearings in next 7d, (ii) tasks with `due_at` overdue or due-today, (iii) draft reviews assigned to me, (iv) approval requests, (v) overdue invoices.
- Backend: `GET /api/me/today` returning the union, tenant + matter-access-scoped.
- Matter cockpit: add a "Next action" card derived from the unified view (highest-priority item for THIS matter).
- Sidebar default route changes from `/app` to `/app/today` for users with active matters.
Estimated days: 5-7.

### `PG-005` Drafting finalization — court-specific format + PDF + revision diff
Status: **`Partially implemented`**.
Evidence: `services/drafting.py` (1187 lines) has DOCX export and citation verifier; missing: PDF, court-specific cause-title profiles, revision compare, page numbering, vakalat/affidavit variants, filing checklist.
Needed:
- `DraftRevision` model already exists; add `draft_compare(prev_id, next_id)` returning structured diff.
- Court format profiles: Delhi HC / Bombay HC / SC margin/header/cause-title rules.
- PDF export via WeasyPrint or Playwright print-to-PDF.
- Filing checklist per court (limit, fees, annexures, vakalatnama).
Estimated days: 6-8 (pdf + 1 court) → 12-15 (5 courts).

### `PG-006` Research treatment / good-law signal
Status: **`Missing`**.
Evidence: `services/authority_citations` populates citation graph but no treatment classification.
Needed:
- Heuristic + LLM-assisted classification of citation context: `followed | distinguished | overruled | doubted | considered | reversed | dissented`.
- DB: `AuthorityTreatment` (citing_doc_id, cited_doc_id, treatment, confidence, evidence_text).
- Negative-treatment warnings in `Recommendation` + `Draft` outputs.
- "Must verify before filing" gate for adverse treatment.
- Backfill on existing corpus (50k+ docs already cite-extracted).
Estimated days: 8-10 (1 court bucket) → 20+ (full corpus).

### `PG-007` GC spend depth — rate cards, budgets, billing guidelines, scorecards
Status: **`Missing`** (today's outside_counsel module covers profile + assignment + spend rows; none of the GC-grade depth).
Evidence: `services/outside_counsel.py` exists; no `RateCard`, `MatterBudget`, `BillingGuideline`, `Scorecard` tables.
Needed:
- `RateCard` (firm_id, timekeeper_id, year, hourly_rate, effective_from/to).
- `MatterBudget` (matter_id, phase, planned_amount, actual_amount, variance_pct).
- `BillingGuideline` (firm_id, rule_text, severity); invoice-line review checks against rules.
- `OutsideCounselScorecard` (firm_id, period, dimensions: responsiveness/budget_adherence/quality/diversity).
- Executive dashboard: spend by firm/practice/matter; budget variance; aging.
Estimated days: 10-12.

### `PG-008` CLM lifecycle — request → approval → e-sign → obligations
Status: **`Partially implemented`** (extraction + playbook + redline view exist; lifecycle orchestration missing).
Evidence: `services/contract_intelligence.py` does extraction; `apps/web/app/app/contracts/[id]/page.tsx` (736 lines) is repo + view; no `ContractRequest`, `ContractApproval`, `ContractObligation`, `ESignature` models.
Needed:
- `ContractRequest` intake form + approval workflow by value/risk/business unit.
- E-signature integration (DocuSign or Adobe Sign) — webhook + status tracking.
- `ContractObligation` (contract_id, owner, due_date, status, evidence_attachment_id) + reminders.
- Renewal/termination alerts.
- Negotiation workspace with track-changes export.
Estimated days: 15-20 (full CLM is a quarter of work).

### `PG-009` Enterprise identity — SSO + MFA + SCIM
Status: **`Missing`**. Already cross-referenced as `WTD-10.1` / `WTD-10.2` but emphasized here as a deal-stop for GC pilots.
Estimated days: 8-12 (SAML 4-5 + OIDC 3-4 + MFA 2-3 + SCIM 4-5).

### `PG-010` Pricing/packaging entitlement enforcement
Status: **`Missing`** (cross-ref `WTD-10.5`).
Evidence: marketing pages mention pricing but no `Plan` / `PlanEntitlement` model gates.
Estimated days: 5-6.

## P1 — High Value, Below Stop-Ship Bar

### `PG-101` Universal command palette / global search
Status: **`Missing`**.
Evidence: no `command_palette` component; `apps/web/app/app/research/page.tsx` is the only search surface, scoped to authorities only.
Needed:
- `Cmd+K` palette (or `/`) searching matters / clients / drafts / hearings / authorities / contacts in one box, ranked.
- `GET /api/search?q=` aggregating typed sources; tenant + matter-access scoped.
Estimated days: 3-4.

### `PG-102` Review queue (drafts, recommendations, KYC, invoices, contracts)
Status: **`Missing`**.
Evidence: each module has its own review path; no unified `/app/review` inbox.
Needed:
- `ReviewItem` polymorphic table (item_type, item_id, requested_by, assigned_to, due_at, status, decided_at).
- Aggregator service merging existing per-module review states into the unified shape.
- UI: `/app/review` with item-type filter, partner/supervisor dashboard, approve/request-changes actions.
Estimated days: 4-5.

### `PG-103` Matter templates by practice area
Status: **`Missing`** (cross-ref `WTD-7.2` task templates partial; matter-level templates absent).
Needed:
- `MatterTemplate` (practice_area, default_tasks, default_documents, default_filing_checklist).
- Template selector in intake flow.
Estimated days: 4-5.

### `PG-104` Document request lists + secure document collection
Status: **`Missing`**.
Evidence: client portal exists (`apps/web/app/portal/`) but no per-matter document-request workflow.
Needed:
- `DocumentRequest` (matter_id, asked_by, asked_of, items: list[name, status], deadline).
- Portal UI: "Documents requested from you" card.
- Auto-attach uploads to the request item.
Estimated days: 3-4.

### `PG-105` Mobile hearing mode
Status: **`Partially implemented`** (mobile-responsive layouts shipped via `mobile-responsive.spec.ts`; no dedicated mobile hearing surface).
Evidence: `tests/e2e/mobile-responsive.spec.ts` 3 cases; no `/app/m/hearings` or PWA install path.
Needed:
- Phone-first hearings page: today/tomorrow tab, single-tap "mark started/completed", swipe to add note, voice-memo upload.
- Offline-friendly cache for the next 24h of hearings.
Estimated days: 5-6.

### `PG-106` Communications capture — inbound email + threading
Status: **`Missing`**.
Evidence: `apps/web/app/app/matters/[id]/communications/page.tsx` (604 lines) reads existing `MatterCommunication` rows; no inbound email capture.
Needed:
- Inbound email forwarder per matter (matter+<id>@caseops.ai → MatterCommunication row).
- Threaded conversation UI.
- Read receipts; secure document request inline.
Estimated days: 6-8.

### `PG-107` Bench-strategy governance — dual-mode tenant policy gate
Status: **`Implemented`** (v1 backend gate + v1.5 web admin toggle / mode badge / disclaimer all shipped 2026-05-01).
User decision: keep BOTH options A and B available. Default = A (evidence-only); workspaces can opt-in to B (predictive) per the PRD §3 authorization.
Evidence:
- DB: `TenantAIPolicy.predictive_bench_strategy_enabled` (default false) + migration `20260501_0001`.
- `services/tenant_ai_policy.ResolvedAIPolicy` carries the new field.
- `build_bench_strategy_context` accepts an optional `policy`, resolves the tenant's flag if absent, and emits `mode` + `disclaimer` fields on the response.
- `analyze_appeal_strength` honors the same policy and propagates `mode` + `disclaimer` to every `AppealStrengthReport` return path.
- `services/drafting._build_messages` appends a `=== WORKSPACE POLICY OVERRIDE: PREDICTIVE BENCH ANALYTICS ===` addendum to the appeal-memorandum prompt only when the workspace has opted in. Override block enforces the PRD §3 rule 3 sample-size guard (≥5 indexed decisions per claim) and a mandatory verbatim disclaimer paragraph.
- Admin: `GET /api/admin/tenant-ai-policy` + `PATCH /api/admin/tenant-ai-policy` (capability `workspace:admin`).
- Audit: every flip writes a `tenant_ai_policy.updated` event with before/after.
- Tests: 4 backend cases (`tests/test_pg107_predictive_bench.py`) covering default-A, flip, tenant isolation, prompt-addendum swap.
Web side (v1.5, 2026-05-01):
- `apps/web/components/app/TenantAIPolicyCard.tsx` mounted on `/app/admin` (owner/admin only). Toggle hits the admin endpoints; status surfaces as "Evidence-only (A, default)" / "Predictive (B)".
- `BenchContextCard` + `AppealStrengthPanel` render the mode as a Badge (Evidence-only / Predictive) plus an amber disclaimer banner when predictive.
- 3 new vitest cases (`TenantAIPolicyCard.test.tsx`); existing admin page test wrapped in `QueryClientProvider`.
- Prod-Playwright: `recommendations-grounding-2026-04-29-prod.spec.ts:148` "PG-107 v1.5 admin toggle flips bench panel mode badge" exercises the round-trip (read → click → verify API state → restore).
Open as v2 (deferred):
- Predictive analytics computation (judge_tendency_summary on bench, predicted_strength per ground). Currently mode + disclaimer surface but the analytical content itself is unchanged; drafting prompt addendum is the active behavior change.
Estimated days for v2: 3-5.

### `PG-108` Coverage confidence UI in research/drafting
Status: **`Missing`**.
Evidence: no `CoverageConfidence` component; users have no visibility into corpus coverage limits when generating output.
Needed:
- `coverage_for_query(matter, query)` returning `(courts_in_scope, year_range, doc_count, freshness)`.
- UI badge on research / draft / recommendation cards showing the coverage shape.
- Honest "limited corpus" warning when coverage drops below threshold.
Estimated days: 3-4.

### `PG-109` Source-used / source-ignored AI trust panel
Status: **`Missing`**.
Evidence: AI outputs surface `supporting_citations` post-verification but don't show what was retrieved-but-not-used or why.
Needed:
- Pass the full `RetrievedAuthority` list AND the per-option `verified_citations` to the UI.
- Render "Used these sources / Considered but not used" on every AI output.
Estimated days: 2-3.

### `PG-110` Per-workflow LLM evaluation harness with goldens
Status: **`Partially implemented`** (cross-ref `WTD-11.4`).
Evidence: `apps/api/src/caseops_api/services/evaluation.py` has skeleton; `caseops-eval-citations` + `caseops-eval-workflows` CLIs ship; no automated golden datasets per workflow.
Needed:
- Goldens for: bail, anticipatory bail, quashing, Section 34, commercial suit, writ, cheque bounce.
- Metrics: citation validity, statute confusion, fact fabrication, missing required sections, formatting compliance, adverse-treatment detection.
- Run on every model/prompt change (CI gate).
Estimated days: 8-10.

### `PG-111` Court fee / limitation / stamp / filing deadline calculators
Status: **`Missing`**.
Evidence: no `court_fee_calc`, `limitation_calc` services.
Needed:
- Calculator service per state/court covering: court fees, stamp duty, limitation period, filing deadlines (per CPC/CrPC/IBC/Arbitration Act).
- UI: calculator widget in matter cockpit + draft prep.
Estimated days: 5-7.

### `PG-112` Billing depth — WIP, aging, realization, GST/TDS
Status: **`Partially implemented`**.
Evidence: `MatterInvoice`, `MatterTimeEntry` exist; no aging/realization/WIP reports; no GST/TDS schema.
Needed:
- Aging report (0-30/30-60/60-90/90+).
- Realization rate per lawyer/team.
- WIP dashboard.
- GST (CGST/SGST/IGST) on invoices; TDS reporting; accountant export (Tally/Zoho).
Estimated days: 6-8.

## P2 — Important, Below Phase-1 Bar

### `PG-201` Pricing/packaging surfaces evident in-product
Cross-ref `WTD-10.5`. Same scope.

### `PG-202` Analytics dashboards (matter aging, hearing load, utilization)
Status: **`Missing`**. Estimated days: 4-5 (after `PG-112` data exists).

### `PG-203` Bulk migration / onboarding importers
Status: **`Missing`**. Estimated days: 5-6 (CSV importer for clients/matters/contacts; one practice-management adapter).

### `PG-204` Empty-state copy hygiene (no founder/prototype language)
Status: **`Partially implemented`**. Sweep needed across `apps/web/app/app/**`. Estimated days: 1-2.

### `PG-205` Statute model depth — amendments, effective dates, state amendments
Status: **`Partially implemented`** (cross-ref `WTD-7.4` says core model implemented; depth missing).
Estimated days: 6-8.

### `PG-206` Observability — per-tenant AI spend dashboard, retrieval quality dashboard
Status: **`Partially implemented`** (`ModelRun` + `VoyageUsage` ledgers exist; no operator dashboard surface).
Estimated days: 4-5.

### `PG-207` DPDP / SOC 2 / data residency story (buyer-facing)
Status: **`Missing`**. Estimated days: 6-8 (mostly compliance work + admin UI for retention/legal-hold/support-access controls).

## Roadmap Mapping (Codex §"Recommended Roadmap" → ledger items)

| Codex phase | Items in this ledger |
|---|---|
| Phase 1 — Win Litigation Daily Workflow | `PG-001`, `PG-004`, `PG-005`, `PG-006`, `PG-101`, `PG-102`, `PG-103`, `PG-105`, `PG-108`, `PG-111`, `PG-112` |
| Phase 2 — Build the Content Moat | `PG-006`, `PG-108`, `WTD-9.1`, `WTD-9.2`, `WTD-12.1` |
| Phase 3 — Close GC Spend / OC | `PG-007`, `PG-008` (light), `PG-110` |
| Phase 4 — Enterprise Trust Pack | `PG-009`, `WTD-10.1`, `WTD-10.3`, `PG-207`, observability follow-ons |
| Phase 5 — CLM (only if resourced) | `PG-008` (full), `PG-110` for contracts |

## Suggested Burn-Down Order (next 30 days, single-engineer)

If the team commits to Phase 1 only, the cheapest high-leverage day-by-day order is:

1. `PG-107` bench-strategy governance decision (0 days, decision-only).
2. `PG-001` conflict check workflow (4-5 days). Anchors law-firm intake credibility.
3. `PG-004` matter command center / Today view (5-7 days). Highest visible daily-driver win.
4. `PG-101` global command palette (3-4 days). Multiplier on `PG-004`.
5. `PG-108` coverage confidence UI (3-4 days). Buyer-facing AI trust signal.
6. `PG-109` source-used / source-ignored panel (2-3 days). Same theme.
7. `PG-105` mobile hearing mode (5-6 days). Solo-lawyer differentiator.

That's ~22-29 engineer-days = 4-5 weeks for one engineer. After that the team revisits the ledger.

## Claude Discipline

- Before any product or UX work, read this ledger.
- Update statuses in the same task as code changes.
- Do not introduce a new module until the active items in this ledger are reduced.
- Cross-reference rather than duplicate when an existing strict ledger already tracks the gap.
- Verify Codex's claims against current code before classifying — the report is dated and may be wrong on items shipped today.
