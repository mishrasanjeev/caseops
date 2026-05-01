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
Status: **`Implemented`** (2026-05-01).
Evidence:
- `services/today_view.py` aggregates 5 streams tenant-scoped + matter-access-respecting: hearings_next_7d (status SCHEDULED), tasks_due_or_overdue (status ≠ COMPLETED, owner = me OR unassigned), drafts_in_review (status = IN_REVIEW), overdue_invoices (status ∈ {issued, partially_paid}, due_on < today), deadlines_next_7d (matter_deadlines).
- `GET /api/me/today?horizon_days=N` (1 ≤ N ≤ 30; 400 outside range). Tenant isolation enforced via `Matter.company_id == context.company.id` on every join.
- `apps/web/app/app/today/page.tsx` renders sectioned cards (Hearings / Deadlines / Tasks / Drafts pending review / Overdue invoices). Each row deeplinks to the matter cockpit. Empty-state when nothing demands attention.
- Sidebar gets a pinned "Today" entry at the top of the Work section.
- 10 backend pytest cases (test_today_view.py) — empty workspace, hearings 7d filter, past-hearings excluded, tasks overdue+due-today+horizon, completed-task excluded, horizon 400 clamping, drafts in review, overdue invoices (paid/partially-paid filter), deadlines, tenant-isolation.
Still on the roadmap: matter-cockpit "Next action" card derived from this feed; sidebar default route swap from `/app` → `/app/today` for users with active matters.

### `PG-005` Drafting finalization — court-specific format + PDF + revision diff
Status: **`Implemented`** (all 12 sprints of the drafting roadmap landed 2026-05-01; live-LLM eval harness in place to enforce 4.8/5 going forward).
Evidence:
- Sprint 1 (2026-05-01) added 4 highest-frequency missing templates: `WRIT_PETITION`, `QUASHING_PETITION`, `WRITTEN_STATEMENT`, `REPLY_COUNTER_AFFIDAVIT` (full statutory awareness + per-template prompts + recommender-matrix coverage).
- Sprint 2 (2026-05-01) added 7 more templates covering daily Indian-litigation filings:
  - `DV_QUASHING_PETITION` — quashing of PWDVA s.12 proceedings under BNSS s.528. Prompt explicitly disclaims Gian Singh as dispositive (PWDVA is quasi-civil, not criminal-FIR) and enforces s.2(f) domestic-relationship analysis + welfare-of-children factor.
  - `ARBITRATION_SECTION_9` — interim measures under s.9 of the Arbitration & Conciliation Act, 1996. Prompt enforces three-part test (prima facie / balance of convenience / irreparable injury) AND the s.9(3) tribunal-constituted carve-out + cross-undertaking.
  - `CAVEAT_PETITION` — CPC s.148A. Short procedural notice; prompt forbids merits pleading and surfaces 90-day automatic lapse rule.
  - `VAKALATNAMA` — branches on `court_name` for SC / Delhi HC / Bombay HC / generic court-specific headers + counsel-acceptance block + bar-enrolment requirement.
  - `AMENDMENT_OF_PLEADINGS` — CPC Order VI Rule 17. Prompt enforces the post-2002 proviso (due-diligence test) when `trial_commenced=true`, and forbids amendments that change the cause of action (Vidyabai v. Padmalatha).
  - `COMPROMISE_PETITION` — branches on `statutory_basis` across CPC Order XXIII Rule 3 / BNSS s.359 (compoundable) / BNSS s.528 (Gian Singh non-compoundable) / HMA s.13B (mutual consent). Surfaces heinous-offences carve-out for s.528 settlements + 6-month cooling-off rule for s.13B.
  - `PROBATE_PETITION` — Indian Succession Act 1925 ss.276-300. Prompt enforces s.63(c) two-attestor rule + s.283 citation-to-heirs requirement; routes to Letters of Administration when intestate.
- 20 templates total now in `_REGISTRY`. `services/template_recommender.py` matrix extended: HC + criminal adds COMPROMISE_PETITION + CAVEAT_PETITION + VAKALATNAMA secondaries; HC + civil / commercial / lower_court + civil add AMENDMENT_OF_PLEADINGS + COMPROMISE_PETITION + CAVEAT_PETITION + VAKALATNAMA; HC + commercial adds ARBITRATION_SECTION_9; HC + matrimonial adds DV_QUASHING_PETITION; arbitration + commercial bucket promoted ARBITRATION_SECTION_9 to primary alongside AFFIDAVIT; PWDVA/domestic-violence/succession/probate practice-area aliases added to bucket map.
- 14 new pytest cases (7 prompt-correctness + 7 facts-validation in `test_drafting_templates.py`) + 8 new recommender matrix tests; fixture corpus extended with 7 canonical Sprint-2 scenarios. 170 backend tests pass; web `tsc --noEmit` clean after `openapi-types.ts` regeneration.
- Sprint 3 (2026-05-01) added court-format-aware PDF export:
  - `services/court_format_profiles.py` ships 4 pinned profiles — Supreme Court (1.5" margins, 12pt, double-spaced, center page numbers, "IN THE SUPREME COURT OF INDIA" first-page header), Delhi HC (1" margins, 12pt, 1.5x line height, right page numbers, "IN THE HIGH COURT OF DELHI AT NEW DELHI"), Bombay HC (1" margins, 12pt, 1.5x line height, center page numbers, "IN THE HIGH COURT OF JUDICATURE AT BOMBAY"), generic (catch-all, 11pt, 1.2x, no court header). Profile resolution: explicit caller key > fuzzy match against `Matter.court_name` > generic fallback.
  - `services/draft_pdf_export.py` ships `render_version_pdf` (mirrors the DOCX route signature) + a pure-function `render_pdf_bytes` for unit tests. fpdf2-based (already in deps; no native build deps), with Latin-1 ASCII-safe fallback so smart quotes / em-dashes / ellipses don't crash the WinAnsi font writer. Same citation gate as DOCX (zero-citation drafts blocked unless approved).
  - `GET /api/matters/{matter_id}/drafts/{draft_id}/export.pdf` (with optional `?court_profile=` override; X-CaseOps-Court-Profile response header + filename suffix surface the resolved profile). `GET /api/drafting/court-profiles` lists the 4 profiles for the web selector.
  - Web: "Download PDF" button alongside "Download DOCX" on the draft detail page; `draftPdfUrl()` + `listCourtFormatProfiles()` helpers in `lib/api/endpoints.ts`.
  - 16 new pytest cases (10 unit tests in `test_court_format_profiles.py` + 6 integration tests in `test_drafting_studio.py` covering smoke / explicit-profile override / unknown-key 422 / 404 on unknown draft / citation-gate / list-route).
- Sprint 4 (2026-05-01) added court-filing bundle ZIP (`services/filing_bundle.py`):
  - `GET /api/matters/{matter_id}/drafts/{draft_id}/filing-bundle.zip` with optional `?court_profile=`, `?vakalat_draft_id=`, `?attachment_ids=` (comma-separated) overrides.
  - Bundle layout: `00-index.pdf` (auto-generated cover + table of contents) + `01-memorandum-<title>-r<rev>.pdf` (court-format-aware) + `02-vakalatnama.pdf` (auto-picks newest VAKALATNAMA-typed draft on the matter; falls back to a placeholder page if none exists, surfacing the gap to the lawyer rather than shipping silently) + `03-estamp-placeholder.pdf` (court-fee slot) + `04-exhibits/<NN>-<safe-filename>.<ext>` (matter attachments, default = all, narrowable via `attachment_ids`).
  - Same citation gate as the PDF / DOCX paths. Telemetry headers on the response: `X-CaseOps-Court-Profile`, `X-CaseOps-Vakalat-Source` (`draft:<id>` or `placeholder`), `X-CaseOps-Exhibit-Count`. 422 on unknown profile key + unknown attachment ids + non-VAKALATNAMA draft id passed as the explicit vakalat.
  - Web: "Filing bundle" button (FolderArchive icon) alongside "Download DOCX" + "Download PDF" on the draft detail page; `draftFilingBundleUrl()` helper in `lib/api/endpoints.ts` accepts optional `courtProfile` / `vakalatDraftId` / `attachmentIds` overrides.
  - 7 new pytest cases (default layout + court-profile override + auto-pick vakalat draft + non-vakalat-template 422 + citation gate + 404 on unknown draft + unknown attachment id 422). 173 broader drafting tests pass; web `tsc --noEmit` clean.
- Sprint 5 (2026-05-01) expanded court format profiles from 4 to 10 + added cause-title formatting helper:
  - Madras HC ("IN THE HIGH COURT OF JUDICATURE AT MADRAS", center page numbers, bare numerals like SC); Calcutta HC ("IN THE HIGH COURT AT CALCUTTA", right page numbers); Karnataka HC ("IN THE HIGH COURT OF KARNATAKA AT BENGALURU", right page numbers).
  - NCLT ("IN THE NATIONAL COMPANY LAW TRIBUNAL", 11pt body); NCLAT ("IN THE NATIONAL COMPANY LAW APPELLATE TRIBUNAL, NEW DELHI"); DRT ("IN THE DEBTS RECOVERY TRIBUNAL"). Tribunals use 11pt body to match the looser tribunal-rules formatting.
  - Fuzzy court-name patterns extended for all six new courts. NCLAT-before-NCLT ordering enforced (substring overlap) — "National Company Law Appellate Tribunal" must NOT route to NCLT.
  - Cause-title rules added to `CourtFormatProfile`: `cause_title_party_case` ("upper" / "title" / "as_given") + `cause_title_numbered` (bool). SC + every HC + every tribunal use ALL CAPS + numbered + "VERSUS"; generic uses Title Case + plain + "v.".
  - `format_cause_title(profile, petitioner_names, respondent_names)` helper produces a multi-line cause title respecting the profile's casing / numbering / separator. Handles single-party (no numbering, "...Petitioner" / "...Respondent" suffix) and empty-party (placeholder "[parties to be filled in]") cases.
  - 11 new pytest cases (6 fuzzy-resolution tests for the new courts + 3 cause-title formatter tests + 1 NCLAT-before-NCLT ordering test + 1 tribunal font-size test). Updated existing list-profile + route tests to expect 10 keys. 48 drafting-studio + court-profile tests pass.
- Sprint 6 (2026-05-01) added structured draft revision compare:
  - `services/draft_compare.py` exposes `compare_versions(prev, next, context_lines=3)` — pure-function over two DraftVersion rows. Returns `DraftCompareResult` with line-level hunks (each line tagged `equal | insert | delete | replace`) using `difflib.SequenceMatcher`, plus citation deltas (added / removed / kept) computed as case-folded sets, plus a human-readable summary ("r1 → r2: +12 lines, -8 lines, +2 citations").
  - `compare_versions_in_db()` is the tenant-scoped wrapper. 400 on identical revisions, 404 on missing revisions.
  - `GET /api/matters/{matter_id}/drafts/{draft_id}/compare?prev_revision=N&next_revision=M&context_lines=K` route. context_lines bounded [0, 10] (400 outside range).
  - Web: `<DraftCompareView>` component on the draft detail page renders the diff with red/green highlighting + citation-deltas panel + revision-pair selector. Defaults to comparing the latest two revisions on first render.
  - 13 new pytest cases (7 pure-function unit tests covering insert / delete / replace / citation set semantics / no-change / malformed-json / context_lines=0 + 6 route integration tests covering happy path / unknown-revision 404 / identical-revision 400 / context_lines bounds 400 / 404 on unknown draft / auth gate). 102 broader drafting tests pass.
- Sprint 7 (2026-05-01) expanded bench-aware drafting from `appeal_memorandum`-only to 15 of 20 templates:
  - `_BENCH_AWARE_TEMPLATES` constant added in `services/drafting.py` covering bail, anticipatory_bail, writ_petition, quashing_petition, dv_quashing_petition, civil_suit, written_statement, reply_counter_affidavit, appeal_memorandum, arbitration_section_9, criminal_complaint, amendment_of_pleadings, divorce_petition, compromise_petition, probate_petition. Excluded: `property_dispute_notice`, `cheque_bounce_notice` (pre-litigation notices), `affidavit` (generic), `vakalatnama` + `caveat_petition` (procedural-only). Bench analytics on these would be noise.
  - Three gates updated to use the new set: (1) `bench_context = build_bench_strategy_context(...)` build call; (2) the BENCH HISTORY CONTEXT block injection in the user prompt; (3) the PG-107 predictive-mode WORKSPACE POLICY OVERRIDE addendum in the system prompt.
  - Low-context fallback note generalised from "general appellate principles" → "general legal principles" so it reads correctly across non-appeal templates.
  - 42 new pytest cases (parameterised across all 15 bench-aware templates × 2 gates + 5 non-bench templates × 2 gates + sanity-check on the explicit set membership + low-context fallback wording test). 127 broader drafting tests pass.
- Sprint 8 (2026-05-01) added pre-filing checklist per court:
  - `services/filing_checklist.py` produces a `FilingChecklist` from `(court_profile, template_type)` covering documents (memorandum, vakalat, index, court fee, synopsis, affidavit, statutory forms, etc.), fees, procedure (caveat search, citations to heirs), and service. Items the system can verify itself ship `auto_satisfied=True` with a one-line reason — vakalat draft on the matter ticks the vakalat slot; matter attachments tick FIR/order/will/death-certificate items.
  - Court overrides for SC (synopsis + caveat search + memo of appearance), every HC (synopsis + verifying affidavit), NCLT/NCLAT (statutory form + board resolution), DRT (OA form + schedule of debt). Template overrides for bail (custody certificate), quashing (FIR copy + settlement deed), writ (impugned-order copy), cheque-bounce (bank memo + RPAD proof), civil suit (schedule of property + cause-of-action chronology), written statement (Order VIII Rule 1A index), probate (will + death certificate + heir citations), vakalatnama (court-fee stamp).
  - Court fee notes per (template, court) — bail / writ / civil-suit / probate / NCLT / NCLAT / DRT / generic. Limitation notes for written statement (Order VIII Rule 1 30/90/120-day), appeal memorandum, cheque-bounce notice, writ + quashing (laches), amendment of pleadings (Order VI Rule 17 proviso). Copies-required matrix: SC=6, HCs=3, NCLT/NCLAT=5, DRT=3, generic=2.
  - `GET /api/matters/{matter_id}/drafts/{draft_id}/filing-checklist?court_profile=...` route. 422 on unknown profile key. Same tenant scoping as the rest of the drafting routes.
  - Web: `<FilingChecklistCard>` on the draft detail page renders the items grouped by category (Documents / Court fee / Procedure / Service), with a tickbox for each (auto-satisfied items pre-ticked + disabled), a limitation-note callout in amber, and a court-fee note in the footer. Local-state ticking — the checklist is descriptive, not gating.
  - 9 new pytest cases (default Delhi-HC bail layout, SC writ overrides + 6 copies + laches limitation note, NCLT statutory form + 5 copies, vakalat auto-satisfaction when sibling vakalat draft exists, 404 on unknown draft, 422 on unknown court profile, auth gate, written statement limitation note, unknown-template graceful degradation). Web `tsc --noEmit` clean.
- `services/drafting.py` (1187 lines) still has DOCX export + citation verifier; mobile + solo mode + template governance + live-LLM eval remain.
- Sprint 9 (2026-05-01) shipped DraftingStepper mobile-responsive at 360px — bottom nav stacks vertically below sm; full-width buttons; +1 mobile-responsive Playwright case asserting no horizontal overflow + Next-below-Previous stack + ≥240px button width.
- Sprint 10 (2026-05-01) shipped solo mode — `?solo=1` query param flattens the stepper into a single scrollable form with one "Generate draft" CTA. DraftTemplateCard exposes a "Solo mode" link (Zap icon, ghost variant) alongside the standard "Start drafting" CTA.
- Sprint 11 (2026-05-01) shipped template governance — `tenant_ai_policies.disabled_template_types_json` column (Alembic 20260501_0003); PATCH /api/admin/tenant-ai-policy accepts a JSON list of DraftTemplateType values to hide; GET /api/drafting/templates filters its response on the resolved policy. 6 new pytest cases (default-20-list / disable-drops-from-list / canonical-set validation / disable-then-re-enable round-trip / partial-update semantics / tenant-isolation).
- Sprint 12 (2026-05-01) shipped live-LLM drafting quality harness — `caseops_api.scripts.eval_drafting_quality` iterates the canonical fixtures, builds the EXACT production prompt via `_build_messages`, runs GPT-5.1, scores each output across 3 dimensions (validator_score / structure_score / citation_score) and produces an aggregate 0-5 rating with a 4.8 target. Dry-run mode emits the assembled prompts without calling the LLM (cheap diff against future prompt edits).
Estimated days remaining after Sprint 2: 6-8 (PDF + 1 court) → 10-13 (PDF + 5 courts) + 4-6 (filing bundle) + 8-12 (revision diff + filing checklist + mobile + solo + governance + live-eval).

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
v2 (2026-05-01, additional):
- `bench_strategy_context.py` adds a `PredictiveSummary` dataclass (sample_size, favorable/adverse/neutral counts, top_outcome_label, practice_area_key) computed via `_compute_predictive_summary` over `similar_authorities.outcome_label`, with the PRD §3 rule 3 sample-size ≥5 guard. Surfaced on the API response and rendered as a 3-column tally + top-label line on `BenchContextCard` when predictive mode is on.

### `PG-108` Coverage confidence UI in research/drafting
Status: **`Missing`**.
Evidence: no `CoverageConfidence` component; users have no visibility into corpus coverage limits when generating output.
Needed:
- `coverage_for_query(matter, query)` returning `(courts_in_scope, year_range, doc_count, freshness)`.
- UI badge on research / draft / recommendation cards showing the coverage shape.
- Honest "limited corpus" warning when coverage drops below threshold.
Estimated days: 3-4.

### `PG-110` Research search: language filter + pagination
Status: **`Implemented`** (v1 shipped 2026-05-01).
Anchor: user-reported bug — `https://caseops.ai/app/research` was surfacing Garo / Hindi / Tamil titles at the top of every English query because commit `35956c9` (2026-04-28) widened the ingest sweep to drop EN-only filtering. Curl probe on prod confirmed: query "patent illegality" → 2 results, top result was Garo transliteration with `?` placeholder chars; query "specific performance" → 5 results dominated by raw-citation-only titles ("[2010] 12 S.C.R. 515" — Layer-2 metadata extraction failures).
Evidence:
- `schemas/authorities.AuthoritySearchRequest` adds `language: Literal["en", "any"] = "en"` + `offset: int = 0` (range 0-500); `limit` ceiling bumped 10 → 50.
- `services/authorities.search_authorities` over-fetches `(offset + limit) * 5` from the catalog, applies `_title_is_predominantly_ascii` filter when `language=en`, then slices to `[offset : offset+limit]`. Returns `total_after_filter` + echoed `offset` so the UI can render Prev/Next correctly.
- `_title_is_predominantly_ascii`: rejects empty / no-letter / Devanagari / OCR-failed titles (≥3 ASCII letters required, ASCII ratio ≥70%, `?` chars <20% of non-whitespace).
- `apps/web/app/app/research/page.tsx`: new English / All languages toggle (default English), Prev / Next pagination (10/page), "Showing 1–10 of N" footer. Page resets to 0 on filter change.
- `apps/web/lib/api/endpoints.ts::searchAuthorities` + response types updated.
- 4 backend tests (`tests/test_authorities.py`) + 8 web vitest cases stay green.
Open follow-ons (deferred, NOT blocking):
- Persistent `language` column on `AuthorityDocument` so the filter can run as SQL `WHERE` instead of post-retrieval (saves over-fetch cost; bigger filter precision).
- Layer-2 metadata re-extraction to clean citation-only titles (e.g. "[2024] 9 SCR 683") into proper case names — separate corpus-quality workstream.
Estimated days for follow-ons: 4-6.

### `PG-109` Source-used / source-ignored AI trust panel
Status: **`Implemented`** (v1 shipped 2026-05-01).
Evidence:
- DB: `recommendations.retrieved_authorities_json` (TEXT, default `'[]'`) + migration `20260501_0002`.
- `services/recommendations.generate_recommendation` captures the retrieved-authorities list (post-rerank, pre-LLM) and persists it on the row.
- Schema + route serializer expose the field as `RecommendationRecord.retrieved_authorities: list[str]` (default empty for legacy rows).
- Frontend `recommendations` Zod schema gains the field with a default; `apps/web/app/app/matters/[id]/recommendations/page.tsx` renders a `SourcesUsedPanel` ("Sources considered: M · cited: N" + collapsible "Considered but not cited" list) under each recommendation card.
- Existing 11/11 backend recommendations tests + 3/3 page vitest stay green.
Open follow-on:
- Mirror panel on draft + hearing-pack outputs (only recommendations covered in v1).
Estimated days for follow-on: 1-2.

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
