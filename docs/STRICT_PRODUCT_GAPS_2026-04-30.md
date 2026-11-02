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

## Additional Closed Product Items Reconciled 2026-05-14

### `G-128` Authority rerank consumes judge-favorability / bench-citation signal

Status: **`Implemented`**.
Evidence:
- `services/recommendations.py::_rerank_by_outcome_bias` consumes
  `AuthorityDocument.outcome_label` for the judge-favorability / outcome-bias
  signal.
- `services/recommendations.py::_apply_bench_citation_rerank` applies the
  bench-citation signal when predictive bench policy is enabled, using
  bench-authored authorities and authorities approvingly cited (`treatment =
  "followed"`) by the bench.
- Guardrails: policy-off and insufficient-history paths keep the original
  relevance order; applied reranks are recorded as `ModelRun` purpose
  `authority_rerank:bench_citation_relevance` and audited as
  `authority_rerank.bench_citation_relevance`.
- Tests: `apps/api/tests/test_recommendations_bench_rerank.py` covers authored
  authority boosts, approving citation boosts, policy-off, insufficient-history,
  and real `generate_recommendation` recording.

## Cross-Reference: Already Tracked in Other Strict Ledgers

Do not re-classify these here. Burn-down lives under the linked ID.

| Codex theme | Existing ID | Existing status | Source ledger |
|---|---|---|---|
| Hotspot decomposition (large pages/services) | `EG-008` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Exception-handling discipline | `EG-009` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Temporal durable workflows | `WTD-5.1` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Agent identity / Grantex | `WTD-5.2` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Notification service durable delivery | `WTD-5.3` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
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
| Calendar sync | `WTD-12.3a` | `Implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Inbound email ingest | `WTD-12.3b` | `Missing` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Backend coverage threshold ratchet | `AQ-001` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Page-level UI coverage | `AQ-003` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| API route operation-level coverage | `AQ-004` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Postgres-CI for all DB-sensitive tests | `AQ-005`-followon | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Provider-skip-on-release | `AQ-006` | `Partially implemented` | STRICT_ENTERPRISE_GAP_TASKLIST |
| Garbled-snippet detector regression suite | `BUG-026` | `Partially fixed` | docs/BUG_VERIFY_HARI_RAM_2026-04-28.md |

## P0 — New Gaps Tracked Here (Stop-Ship for "Best for Law Firms" claim)

### `PG-001` Conflict check workflow
Status: **`Implemented, deployed, and Properly fixed` for the 2026-07-22
policy** on commit `34f19ad2bc0a5b48398144998cf546cc9e7a815a`.
The scan/review workflow remains implemented, and the superseded mandatory
activation gate has been removed from status paths, tests, and current docs.
Evidence:
- DB: `MatterConflictCheck` model + migration `20260430_0001_matter_conflict_checks` (status enum: pending/cleared/conflicted/waived).
- Service: `services/conflict_checks.py` with substring + Jaccard token-overlap scanner across `clients` + `matters`.
- Routes: `POST /api/matters/{id}/conflict-checks`, `GET /api/matters/{id}/conflict-checks`, `PATCH /api/conflict-checks/{id}`.
- Capabilities: `conflicts:run` (every fee-earner) + `conflicts:resolve` (staff only).
- UI: `apps/web/components/matters/ConflictCheckCard.tsx` mounted on `/app/matters/[id]` cockpit. Run dialog + status badge + candidate list + clear / mark-conflicted / waive controls.
- Status policy effective 2026-07-22: conflict checks are optional, auditable
  review evidence. New matters may be created directly as `active`, and an
  existing `intake` or `on_hold` matter may move to `active` when the latest
  check is missing, pending, conflicted, cleared, waived, invalid, or stale.
  A party-scope change or reopen keeps the earlier result as historical rather
  than current clearance, but must never turn it into a status blocker. Matter
  access, restricted matters, team scoping, ethical walls, terminal lifecycle,
  and cross-tenant 404 behavior remain enforced independently.
- Local regression evidence: canonical backend verification passed Ruff plus
  all 59 tests in the affected conflict, lifecycle, intake, and import files;
  19 focused React tests across three files, TypeScript, and the 64-route
  production web build passed. The combined July 15 and July 22 local Chromium
  run passed 5/5 in 20.5s with the shared exact local tester identity. The July
  22 spec passed 2/2: no-check Intake activation in 1.3s and controlled
  Dispose -> Reopen -> Historical-cleared -> Active in 2.1s, including
  lifecycle-version/CAS assertions and final reload persistence.
- Production evidence: exact commit `34f19ad2bc0a5b48398144998cf546cc9e7a815a`
  was deployed to API revision `caseops-api-00210-fnv` and web revision
  `caseops-web-00189-k9f`, with 100% traffic and registry/runtime digest
  equality. The committed July 22 spec passed 2/2 with the supplied `legal`
  tester, then passed both cases again in GitHub run `29929098217` on the
  independent QA tenant. That run completed the broader RAM batch with 46
  passed and four expected conditional skips, plus notice module 2/2.
Follow-on caveats:
- Contacts beyond `Client` (witnesses, opposing counsel, vendors) need a
  separate contact table before they can be scanned.
- Bulk waiver / partner-approval email workflow is not part of the core PG-001
  optional review workflow.
Estimated work remaining: deploy the candidate, record its exact build identity,
and pass the committed production Playwright workflow; data-model follow-ons
remain tracked separately.

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

## Next Milestone Order (reconciled 2026-05-14)

The next implementation sequence is:

1. Staging proof: configure staging Workload Identity / secrets, run the staging deploy path, and capture runtime proof.
2. `G-116` inbound email ingest: close `WTD-12.3b` / `PG-106`.
3. `WTD-7.2` tasks/deadlines: matter-cockpit Tasks + Deadlines tabs and admin task templates.
4. Durable notifications / Temporal: `WTD-5.1c` and the `WTD-5.3` foundation
   are landed; remaining work is provider-approved external delivery adapters
   and downstream ADP automation.
5. AI eval harness: complete `WTD-11.4` / per-workflow golden evaluation gating.

## Claude Discipline

- Before any product or UX work, read this ledger.
- Update statuses in the same task as code changes.
- Do not introduce a new module until the active items in this ledger are reduced.
- Cross-reference rather than duplicate when an existing strict ledger already tracks the gap.
- Verify Codex's claims against current code before classifying — the report is dated and may be wrong on items shipped today.


## QA18 — React Native Pod-to-child environment admission (October 30, 2026)

J20/M22 and native release remain partial/NO-GO. The user story is to prepare a standalone iOS app so the complete document/workflow acceptance inventory can execute. The e7dc engineering attempt passed Expo prebuild and the first autolink, then failed at the deeper React Native dependency/core/codegen boundary with IOS_HOST_UNREVIEWED_ENVIRONMENT. Its source fingerprint is 17193d7051a33f04a8d536bdae1de243a5837978f4c7182d82491e607367c2ea; source/runtime postflight and known foreground group closures passed. Pods completion, Ruby TLS, Xcode, Simulator trust and all83 native cases remain unverified.

The bounded diagnostic executed the exact six generated-Podfile and twelve pinned RN ENV-assignment statements in admitted Ruby, then used the unchanged I62 constructor. It proved ten rejected names: two source paths and eight flags. APP_PATH was the generated raw ios/.. form; REACT_NATIVE_PATH was canonical. It retained only fixed key names and enum/path booleans. No complete Podfile, SDK cleanup, download, codegen, Q mutation or provider action ran. Attempt01 failed before Ruby because multiline diagnostic argv violated the unchanged command-domain fence; it remains incomplete. The corrected diagnostic used a separately scoped private policy; the old expired policy and failed native attempt were not renewed or relabeled.

The repair preserves the earlier four switches and adds only the eight finite SDK flags. Hermes0 is a source-proven early generated-Podfile option; Fabric and New Architecture accept only1. The two paths require a lazily reviewed policy source root, actual owned canonical source/ios/RN directories, unchanged helper bytes and unchanged namespace. Foreign roots, aliases, symlinks and changed source refuse. The adjacent Xcode586-name inventory includes REACT_NATIVE_PATH; the second exact physical-relative spelling is admitted only after owned non-symlink Pods exists. No arbitrary path normalization or build-name bypass is allowed. The canonical shell pins the new helper bytes.

IOS-ENV-03 covers64 valid layouts across all seven composed roles; IOS-ENV-04 covers finite-value/case/build-name/trust negatives; IOS-ENV-05 covers exact path/foreign-root/alias refusals; IOS-ENV-06 composes real POSIX source/directory review with command projection and rejects symlink or changed-helper fixtures. Windows exercises the explicit POSIX refusal; this does not claim Windows iOS execution. The impacted complete subset passed44/44 and the complete tooling module passed385/385 with zero failures, skips, cancellations or todos on accepted Node24/BASE144. The prior381 module cases are retained; four new source-contract cases were added. CI and the independent build-config/source-observer inventories already select the same33 modules, including tooling; module/native83 inventories do not change. Final whole-inventory reconciliation after the separate permanent observer integration remains required.

Raw functional checks: /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-rn-source-policy-repair-qa18-01/checks.json SHA256 34aa69836d06a3e3717e75d1e9a76e712c5e29c9a2258d6a95aa3db4422f7ff4. Original failed native receipt: 4d6fe9e980ddea2665c7eddac3fe6852154a3b7343048630f9cc786b42defabd; diagnostic02 result: 475a92e4877bdfbb3776fe21f8f53c79ad994bfea7239d5f0ffa5955a85641fd. These are scoped source/functional proofs, not complete source-observer or native acceptance. Q remains e7dc until a separately admitted complete source advance; actual repaired Pods/Xcode/device replay and independent Android acceptance are still required.

## QA19 — Preserve typed Node code operands through CocoaPods (October 30, 2026)

Status: source/functional repair verified; native/store release remains **NO-GO**. PRD J20/M22; regression IDs **IOS-ARGV-01** and **IOS-ARGV-02**. The original QA18 native prefix on local8dc02f3 (fingerprint dbfe98ce9517827acbfc664fa12f03a3e0e3c06bed0d90c8691c034db5e6a8ea) passed autolinking, React Native Codegen and the two checked core-artifact downloads, then failed ReactNativeDependencies.podspec after its Node resolver command was rejected. Retain that failed prefix cdfcf346565e30b83a6ecc81a87443dfbf805e0af9f237b7da0220611307800c and its complete source/owned cleanup proof; neither Codegen completion nor downloaded archives are Pods/Xcode/device acceptance.

Actual source-pinned Ruby production of the resolver argv confirmed a line-feed inside the Node `-p` code operand. Unchanged I63 rejected IOS_HOST_COMMAND_DOMAIN before any policy read or SDK Node dispatch; diagnostic 26d67524dca7e3900471652cab8ca99fa3a2bb1a3771349b061bcc44f9ee2f09 retained the exact argv hash and three closed owned phases. The podspec swallowed that rejection and entered its unrelated fallback, producing the missing node_modules/package.json error. Existing React Native package metadata was valid; no SDK file, package metadata or dependency was modified.

The host now admits CR/LF only in the typed CODE operand immediately after the first Node option -p/--print/-e/--eval. Original argument bytes and Promise behavior are preserved; non-code paths/flags, every other executable role, environment checks, NUL rejection, 8192-byte per-argument and 256-argument/2-MiB maximum bounds remain. Ambiguous code options before -- refuse; literal arguments after -- retain their prior meaning. Canonical shell entry was rendered from the new helper and hash.

Actual focused **46/46** and complete tooling **387/387** passed with zero failure/skip/cancellation/todo; both JavaScript syntax checks and shell syntax passed. Preserve the first focused45P/1F 7a1f1044327bae5f2fb58a47377d73f2cb7f75566f08e96deb1005aee4ffcd49: the new test initially expected a generic environment error instead of the unchanged typed rejection; only that new oracle was corrected. The exact Ruby-produced SDK program then passed the new validator unchanged and resolved the existing React Native index.js through actual Node24.15.0 with exit0, no SDK import/network/fake metadata (9064be377e19eed2d00230b8da80708e9e475813ff4875e9f93d6bf6116358d4).

Checks: /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-rn-argv-repair-qa19-01/checks.json SHA256 eccd50f79e1a2522bdbc5d77c1407106ac7b8b83e8104d6b6a2f1b846a549b41. These are functional/source-pin proofs, not complete source-observer or native acceptance. Two new case identities bring tooling385→387; the same33 source modules and native83-per-platform inventory remain. Root's pending permanent-eight tooling integration must retain all QA18/QA19 cases and independently reconcile Python/frontend/CI counts. Q remains engineering8dc until a separately admitted complete source advance; repaired Pods, full generated audit, Xcode and Android/iOS device acceptance remain pending.


### QA20 — public notice browser inventory (2026-10-30)

PR #558 source 5cd371a738793670c79bd92852ad7038df6331ec finished CI with 67 successful checks, one failed web E2E job and two skipped checks. The failed app inventory retained 621 passed, 17 explicitly skipped and two failed cases. Both desktop/mobile public-content notice journeys failed at their exact six-heading expectation; the page correctly rendered seven components after the pinned Node 22.23.4 notice was added. The existing component unit independently expects seven components and nine full notices.

Reconcile only the two browser inventory literals (6→7 headings, 8→9 notices). Preserve every existing per-component licence/download byte assertion, keyboard, reload, viewport, metadata and zero-mutation check, their deadlines and zero retries. Source controls prove exactly those two whole-program AST literal changes. Original CI artifact 12941599717: SHA256 07e8537a928ea31c33a09dd57e235c95e3a7f9e1dd2859411c37e8c0ca39ae14, 54,647,687 bytes; independently reviewed 327 unique safe members and both exact failed contexts. Retain original failure receipt 11d0c5d21c7ee1a7294bc33b26a3c15f566fd1be5ed32bf81e64609051d8f10e and source controls 5f5bbad3e56bf82fee5d41602df231e1807948b180fee2c4aae4948456271058.

Status: source repair only; complete replacement public-content/browser acceptance pending fresh CI. The remaining notice assertions in the two original failed cases were not reached. Native Android/iOS acceptance, store archives and publication remain pending; this source change does not certify them.


### QA21 — Windows native runner command-file permissions (2026-10-30)

Fresh PUBLIC3b18 mobile CI run40979836848/job123816849704 stopped before npm installation, installed-inventory capture and dependency audit: CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_UNSAFE. The original job log and failed/unverified boundaries are retained in /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ci-3b18-windows-command-owner-01/failure-receipt.json (SHA256 d87170ea77b5be3c39759c41b967f926ab4db989055adf6ac53a181a490c2f42). Linux installed-audit/mobile-source/Windows offline setup/browser handoff passes do not waive this Windows failure. No unchanged job rerun is used as a repair.

The CLI now hardens only the current native set_output_UUID direct child of RUNNER_TEMP/_runner_file_commands. A bounded Windows FileStream excludes concurrent writes/deletes, preserves its bytes, applies a protected current-user/SYSTEM/Administrators ACL and current-user owner, then independently repeats the unchanged strict ownership check. The Node caller reconciles its retained descriptor, complete metadata except the explicitly changed ctime, original bytes and namespace. Exported append, npm configuration, all other paths, TLS verification and trust policy remain unchanged. The CLI retains its original shared30-second preparation deadline and original5-second append deadline; the new phase is separately bounded10seconds, with two at-most4-second native calls and the existing1MiB file/4096-byte pipe limits.

CI-COMMAND-01..04 cover exact scope/constructor, independent owner/readback and original append, alias/hardlink/oversize/context refusals, timeout/unknown-output/unsafe postcondition and same-byte replacement or changed bytes, with descriptor closure. Final source controls a0e4efca94afadd0a4dc3669034b0e7151a1c91e5e13faaa5a883adcfc8f6e2c prove all original387 tooling test bodies/helpers and original CI ownership/append logic remain intact, apart from the explicitly shared original deadline. Final focused4 and full391 tooling cases pass with zero failure/skip/cancellation/todo, JavaScript syntax, actual PowerShell parse and diff checks pass; checks c48125e49c696f701c4ca591e4e3d06826fe261f784749261b9e0d751cd5f99f. These Mac contracts and parse checks are not actual Windows ACL or installed-audit acceptance. Four cases change tooling387→391; full measured source and independent registration counts must be reconciled.

A prepublication review caught a nonexistent FileStream.GetAccessControl overload that mocked controls and parse-only syntax could not detect; retain 87f5e62026d99f49ced06945dbbc5071439cd158ad6e50a6030dd539fe403de5 and the draft program. The final program uses the documented parameterless handle method. Microsoft API sources: https://learn.microsoft.com/en-us/dotnet/api/system.io.filestream.getaccesscontrol?view=netframework-4.8.1 and https://learn.microsoft.com/en-us/dotnet/api/system.io.filestream.setaccesscontrol?view=netframework-4.8.1 . Fresh Windows CI remains required; complete native83-case acceptance per platform and store archives/publication remain pending.

## QA20 — Compose OpenURI default stores with the retained Ruby trust policy (October 30, 2026)

Status: source and actual Ruby/OpenURI/TLS regression component verified; native/store release remains **NO-GO**. PRD J20/M22; Ruby OPENURI-01..25 and source/projection IOS-RUBY-01/02. Preserve failed public3b18 native prefix 32fd3a5af7fa3840b6c7bfb1e13596d7ffb93c618699384744b3ac127e41a450 (fingerprint364a90b63ad8efe72641ef6f927062918c1219d85e0b0a8bcd12253c8c735be2): Codegen, ReactNativeDependencies and Hermes downloads/checksums passed, then CocoaPods CDN detection failed IOS_PODS_NET_HTTP_STORE_REFUSED. No Pods/Xcode/device completion is inferred.

Actual source-pinned CocoaPods manager/OpenURI diagnostic a6392c74d87a308ea01444208e581d693286f5e973ba68d7138b59b0c051076d stopped before NetHTTP guard/connection. It proved a fresh non-nil store, distinct from both the policy-owned store and SSLContext default; ca_file/ca_path profiles were already acceptable and VERIFY_PEER was set. Source-pinned OpenURI87056fcf creates that store at331..343. No unknown store was admitted by the diagnostic and no HTTP request was sent.

The host now gives the unchanged OpenURI method a fiber-local per-call receipt for the pinned default-CA HTTPS/no-proxy profile. Its exact source assignment, HTTP identity, host/port, store identity, fiber, policy-owned store and live scope must match. Incoming OpenURI stores are never used for TLS: the existing descriptor-verified policy store replaces them before connection. Unknown direct stores still refuse at START (assignment outside a profile is not a global setter fence); custom CA/unsafe verification/version options, proxy/client-auth and marker overrides remain refused. Peer/hostname checks, every existing root, source/namespace checks, request payload/auth/header behavior, original return/Error identity and60-second production maxima remain. Nested and exceptional paths restore their prior receipt; closed receipts cannot authorize reuse.

New durable scripts/mobile/ios-host-pods.test.rb has an independently collected **25-case/75-phase** inventory. Actual accepted Ruby4.0.9 executed all75 phases successfully, including genuine loopback TLS, unknown CA and hostname rejection, nested success/rejection, fiber/thread separation, same-host wrong HTTP identity, same-HTTP closed receipt, client-auth refusal, original error/return identity, redirects and explicit retry. All17 received HTTPS GETs had the exact no-paid marker; both owned command groups, all TLS server threads and paired source/output inventories closed. No private key was written, no SDK or Q source changed and no external request ran. Acceptance /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-openuri-store-repair-qa20-01/actual-ruby25-acceptance.json SHA256 56b7e2c3d3900ec7432354a39b5bf53c6ba4717be8323408f9e3685d63a79ea2; actual result c2c29f71de152851056db8b94c34e84365941a827ef5cf436a4e024f0b817339.

Ordinary Node CI does not execute this Ruby fixture. Its two independent inventory/retained-stdin projection contracts are handed to Root for merge with the concurrent Windows repairs; complete Node verification and final source reconciliation are owned by Root after all writers close. The new Ruby source must be explicit in isolated snapshots and canonical LF attributes. Actual Appium83-per-platform inventory is unchanged. Complete source adoption, actual CocoaPods CDN/Pods replacement, generated-ios/Pods/SPM audit, Xcode and Android/iOS acceptance remain pending; the original failed native run stays failed.

## QA22 — Bind Windows ACL mutation to the original native handle (October 30, 2026)

Status: corrected source and scoped functional regressions verified; complete native/store release remains **NO-GO**. J20/M22; CI-COMMAND-01..04, IOS-RUBY-01..02 and the separate PowerShell13-case field inventory. The unpublished QA21 draft was superseded after peer review found a pre-mutation pathname race: a post-setter metadata refusal could occur after changing a replacement file. Preserve unpublished-native-handle-race-finding.json SHA256 6932f3944ca41ecd724f57b2eb02a77b8b9b7cb1d80c279b03a84ba08c5fe003 and all earlier checks; they are not acceptance of this corrected source.

Before any ACL setter the production PowerShell program now compares actual GetFileInformationByHandle volume, unsigned64-bit file identity, birth/write times, size, link count and regular/non-reparse attributes against the Node-held descriptor, plus its retained byte digest. It holds a FileShare.Read handle excluding writes/deletion, applies only the reviewed runner command ACL, then repeats native identity, byte and strict ownership proofs. Windows Node24.15.0 libuv maps its device and inode to those same volume/file-index fields. Original append/configuration/TLS guards and the shared30-second CLI/5-second append limits remain unchanged. Independent source controls1531a0ca702092819376dbecf6aa122957adfd836f526b46672bcc33d95cea41 reconstruct the entire original CI/tooling semantic AST after removing only the enumerated new code and six tests; every original387 test body/helper remains unchanged.

The combined current source passed focused6 and full393 unique Node cases with zero failure/skip/cancellation/todo. Preserve the first combined392P/1F fixture error3f79583a85a1c42de96f893c4329380b10349738a1bfe8f0d1f65fe6147e59c2: IOS-RUBY-02 had dereferenced an intentionally null BASE fixtureCA; only that new oracle changed to assert the independently known null policy values. Actual PowerShell7.6.9 executed the exact production Identity validator against13 independent ABI fixtures, including high-bit64-bit identities and wrong-volume/time/link/type/size refusals; no native Windows API or ACL setter was executed on this Mac. Final checks0990c5a41e6e7c4321625b07ef44614fedd2a5a2f6eac0cc882ba3384a474a4d bind CI2ff409ea/64731B, tooling81408748/407135B and durable PSaa3f26cc/6441B. The Windows workflow will execute that fixture under both Windows PowerShell5.1 and pwsh; actual Windows hardening, installed dependency audit and freshCI remain required. New Ruby/PowerShell fixtures have explicit LF attributes; Ruby test source is an explicit isolated-snapshot input.

Public3b18 CI has completed:64successful checks, three failures (the Windows installed audit, PostgreSQL shard9 and its aggregate), and three skips including Playwright/staging. Receipt5b5377f06e40ba6d63a2dd53d0566be9f6286e1a526803ccc8c257b3b5778ea4. The PostgreSQL writer timed out with actual SQLSTATE55P03 under its unchanged2-second limit; observer connection acquisition/cleanup inside that interval is under separately controlled regression review, and historical causation remains inconclusive. No unchanged CI rerun is authorized as repair evidence. The skipped browser suite did not verify the prior notice-count repair. Complete measured source adoption, fresh image security, actual APK/Simulator builds and83cases/249phases independently on each OS remain pending.

## QA23 — Release the auth fence before observer cleanup (October 30, 2026)

Status: PostgreSQL fixture repair verified on actual PostgreSQL17; complete CI/native/store release remains **NO-GO**. M01/J01, US-002 suspension/session provenance. Preserve public3b18 shard9 failure ef10881be3d5b0c90de6bd9231d0bc108e1912f792b9e4f17fae1a71642d4452:116passed/1failed, writer SQLSTATE55P03 after the unchanged2-second lock timeout. That historical interval cannot be assigned solely to connection acquisition versus observer rollback. Authentication locking/product behavior was not changed.

Both affected tests now open/prove the actual observer connection before the auth fence and retain it until after auth rollback and writer completion. The three membership/user/cutoff and two adjacent membership/user layouts preserve their directed pg_blocking_pids oracle, exact2-second SQL timeout,1-second start/observer bounds,3-second future bound and post-mutation authorization denials. Five new coupled regressions call the actual original bodies, return the original Future unchanged and delay only the exact observed connection rollback. They record completion at cleanup entry and always remove scoped hooks.

Actual private old-body counterfactuals failed all5calls with native55P03 at the exact original future-result line; the Future retained that same error object and cleanup entered before it finished. The repaired complete two-module inventory passed38cases/114phases with zero failure/skip/cancellation; all5 added calls proved the observer ready before the fence and the writer complete before observer cleanup. Root independently checked exact receipts, inventories and outcomes. Acceptance 95d48b47cc8e95945ddae2778e4a397322b95185a6916f043ad85ecced502017; source-bound summarybcab1d0fadd2e81e521bdd049bd73ce77851e0121e0a4a06ec2c7ec799235fce and outputauditf6b43a2f7910444355dc55f518b499a65d6b2334cc549011b0b9008899139d68. Actual component103.324s;18717source observations/674809550bytes under unchanged20k/1GiB. All65ownedcommand groups closed, exact new container/volume absence was verified, retained backend data/network remained untouched and the existing empty system bridge returned empty.

Two earlier pre-body attempts remain failed: private HOME hid Colima profile; explicit documented COLIMA_HOME fixed the actual control. The retained internal network then exposed no actual published port, so the next fresh scope used the independently empty existing default bridge with zero→exactownedCID→zero fences and both requested/actual loopback-port proofs. Its copied old audit filename was also corrected; no old receipt was overwritten. No unchanged database race was rerun to obtain green. Both repaired files pass Ruff and exact38-case collection. Fresh complete hosted CI, current APK/Simulator artifacts and full platform inventories still remain.


## QA24 — Admit the official Gradle Plugin Portal artifact redirect (October 30, 2026)

Status: actual Gradle transport repair verified; normal application configuration, APK and device acceptance remain open. PRD J20/M22; ANDROID-CDN-01/02. The current-source normal configure02 reached the real JVM and failed ANDROID_REDIRECT_OUTSIDE_REVIEWED_BASES. One bounded marked, no-follow HEAD observed the Foojay1.0.0 POM redirect to HTTPS plugins-artifacts.gradle.org; the separately retained official mirroring documentation corroborates that host. No redirected POM GET or unmarked provider request was used for diagnosis.

The production initializer preserves all eight repository literals and every existing URI, marker, private authentication-copy, original redirect-verifier, default TLS, hostname, class-origin and affected-Download fence byte. It adds only the immutable official CDN redirect root, explicitly admits nine exact authority/authentication scopes, and tightens configured URL count10 to9. Unknown authorities, malformed URLs, arbitrary ports and mixed credentials remain refused. Root independently reversed the four exact substitutions to the original482d2c65 source hash.

The complete real eight-phase Gradle fixture passed, including received GET/HEAD markers, same/changing-authority redirects, nine-authority constructor controls,12 invalid URI refusals, unknown CA/wrong hostname refusal and four pre-resolution affected-component/plugin refusals. It observed28 marked HTTP requests,11753 served bytes and30 connections. All27 owned command groups closed/reaped, all recorded PIDs were independently absent twice, server threads/descriptors closed and exact listener ports were absent. Source/output pairs passed; external-bootstrap composition7063 entries/454025975 bytes remains within the original20k/1GiB limits. Acceptance: gradle-qa118-header-fixture-01/maven-only-official-cdn-10/root-composed-actual-exit-acceptance-01.json SHA2565b30e7a089fedd470fb2a95b8fb6496e331747b7f3ad5e59815a35ddd96befcb under the native-end-to-end-20261028-01 mobile cache. This is a synthetic transport component, not application dependency-graph, APK or device proof.

The first new fixture failed before HTTP because its reachability fence retained an older source/tree. Preserve failed MF9 receipt5bfb12621a8fd08f2d8862edbd5d77129e6feb8112bc8261370aa97a7909e574. The replacement changed only its fresh namespace/derived pins, two source/tree literals and one explicit current before-dispatch source label. Root compared all24 code/template/runtime files, and32 composed producer/consumer controls passed; no unchanged failed race was rerun for green.

The original configure02 also retained five declared Gradle cache/lock timestamp changes as a failed immutable-source postflight. The replacement keeps complete public-file identities strict, permits only declared owned single-link regular generated files and charges their current sizes with the same1500-entry/512MiB derived cap.21 source-derived metadata controls passed. This private controller repair does not retrospectively accept the failed run. Two durable Node regressions were appended with every original393 tooling byte intact; their combined full execution is pending the remaining native source writers.


## QA25 — Keep Android device transport in one reviewed profile (October 30, 2026)

Status: offline producer/session/Files integration verified; actual current APK/emulator acceptance remains pending. PRD J20/M22. The previous Mac test harness fixed every consumer to emulator5584/ADB5038/Appium4725/system8202 and CaseOps_Pixel9_API36_arm64. A fresh exact listener check still found foreign adb PID96519 on5038; it was never stopped, queried as a test transport or adopted. The independently owned16KiB image/AVD had instead observed emulator5580, privateADB5040 and CaseOps_PR558_16K_20261028_03. Those historical OS observations are not current app or Appium proof.

A frozen helper now admits exactly two whole profiles. It preserves the original tuple and adds the selected owned tuple5580/5040/4727/8204/CaseOps_PR558_16K_20261028_03. The new Appium/system ports are prospective policy values, separately checked free before preparation; only actual later listeners, installed binary, fresh boot identity and returned session capabilities can prove them. The producer requires the new actual AVD name, every session/ADB constructor rejects mixed profiles and global5037, and Files attestation still independently checks actual AVD, boot UUID, package UID and owned app/provider roots. No numeric range or unknown-serial fallback was introduced.

Both complete existing unit modules passed the same63 unique cases (56 retained and7 new), zero failures/skips/cancellations/todo. They compose the real producer, exported plan/session validation and Files controller against explicit synthetic device transports; mixed ports, serials, capability aliases and absent/foreign/old AVDs refuse at the proper boundary. Original test bodies remain byte-identical; fixture defaults use independent original literals. Three new profile cases were moved verbatim into the existing selected module, preserving the canonical33-module inventory; the standalone precursor test file is not added. Source and157-file staged source pairs, owned process closure and independent PID absence passed within1253 observations/301379709 bytes. Final source handoff android-transport-profile-proposal-01/source-handoff-final-02.json SHA256b3131f5b4082922a1e817f71914a576faef3aabefa4e8a999193b1eb84021816 is beneath the source-draft-01/android-current-source-build-plan-01 mobile cache. The new colocated helper is explicit in harness/source inventories and LF checkout policy.

The earlier zero-Node private constructor refusal and three-module precursor pass remain separate. This result proves no actual ADB command, boot, Appium session, user workflow, APK or store acceptance.

## QA26 — Retain evidence before the PostgreSQL job deadline (October 30, 2026)

Publicbc834 CI ended47successful jobs, one timed-out PostgreSQL shard25, its failed aggregate and two skipped browser/staging jobs. GitHub explicitly reported the original12-minute job limit; the job produced no uploaded shard25 artifact and its log blob was unavailable. The exact117 identities were derived from the complete same-head3740-case collection in the successful shard9 artifact. All117 have prior successful exact-case timings totalling239.788seconds; that does not explain the timeout or prove load imbalance. No shard reroute, longer test/SQL/Future limit or unchanged CI retry is used as a claimed repair.

The workflow retains its12-minute job budget, adds a9-minute pytest-step cutoff so the existing always-upload step can run, and enables stack-only60-second faulthandler diagnostics. All31passing current PostgreSQL shards had pytest durations below540seconds (maximum503). The complete existing82-case sharding-contract module passed with every prior assertion retained plus the exact new timeout/argument checks. This improves diagnostic retention; it does not establish the historical incident cause or a completed replacement hosted run.

The first isolated117-case diagnostic was INTERRUPTED when its agent ended and the owned tool parent closed. It left a23-dot prefix, a pytest internal BrokenPipeError and no final command042 outcome, source summary or global audit. None is full-shard acceptance or a product regression. Exact admitted PostgreSQL CID73048ddef073895ef8daea32c501a629b4e09d2517e5d19190430faa196fed82 and its uniquely owned volume were subsequently stopped/removed and independently proved absent; all7retained resources and both networks stayed unchanged, and the system bridge returned empty. Two failed recovery scopes (a deprecated stop warning and stopped-endpoint projection) remain retained; stop was not replayed. Final recovery source pairing matched the original input snapshot, and the standalone four-scope output audit measured4574 observations/121672350bytes. A persistent owner through execution and cleanup is required for the complete replacement diagnostic. Original interrupted global counters and acceptance remain incomplete.


## QA27 — Transfer only reviewed local Expo SDK archives (October 30, 2026)

Verdict: **Inconclusive for native build and release acceptance**; the private actual host-CLI transfer component is verified. PRD J20/M22. User story: the iOS build operator can consume the exact locked Expo precompiled module bytes already installed on the workstation without admitting arbitrary file URLs, disabling TLS or changing the SDK. Tests IOS-ARCHIVE-01..04 and ARCHIVE-01..08; the native inventory remains all83 cases/249 phases per platform.

Preserve actual bc834 Pods05 failure c4820a23edc9719453e48a595bb69be5975abd9881cb9c935baf7ba5bf295eff, source fingerprint604dd9eee9007c9f1cd8c3348518b6fe81235fdb3790f755159390c7ada27d2c. Expo prebuild, Codegen, React Native/Hermes downloads/checksums and actual CocoaPods CDN/trunk addition passed. Installing ExpoFileSystem58.0.13 then reached the real precompiled-module file URI and refused IOS_HOST_HTTPS_DOWNLOAD. That failed run remains failed/incomplete; its separately scoped complete physical-output diagnostic b8bd05082473ca3a5cc97c73ac820c874f9a85a331329a93f62ac62520fdf895 does not turn the original integrated resource closure into a pass. No Xcode/Appium run or Podfile.lock completion is inferred.

The narrow host repair adds a finite local-transfer family separately from the unchanged ordinary HTTPS curl validator and transport. All10 catalog archives (45,025,306 bytes, four exact package identities) and package manifests match members of already-cached official locked npm tarballs; provenance958cf332e71cdfe620df14364687b9bc5f0cd83ac796372d42529aa2f0424f11. Existing package licenses/notices are unchanged and no dependency or installed SDK was patched. Admission binds the mobile lock, Expo producer source, manifest and exact archive through verified descriptors, rejects URI aliases/traversal/hosts/unknown archives and transfers the retained verified buffer. An absent destination uses EXCL; an existing destination must be empty, owned, regular and single-link. The same descriptor is used for write/readback, source/target replacement refuses, original Error identity survives, buffers are cleared and no curl child is spawned for this family.

Actual accepted Node24.15.0 executed the durable private CLI fixture with **8 cases/24 phases passed**,13 real iosHostCli invocations,0 actual children and0 HTTP requests. Both positive archive families, existing-empty/absent destinations, source replacement before and during write, target symlink/hardlink/replacement, unsafe URI/arguments, changed archive/manifest, Error identity and unchanged HTTPS routing passed. All3 owned groups, paired source/runtime and complete output inventories closed; composed2786 entries/467,627,064 bytes remained below20k/1GiB, canonical7.7924s and observed external16.0099s below30+30. Acceptance /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-local-sdk-archive-repair-01/actual-cli8-acceptance.json SHA256 7aa860ca7d300921886abc794ec7052fd18bae0e951b21155b9e743e0ef1975b.

Retain private attempts01/02 as prebody/prejournal fixture refusals (missing canonical query worker; omitted policy extent), and03 as7P/1F where the replacement fixture's write-only open was miscounted as a source read. The replacement observer counts every read-capable open including O_RDWR/r+/w+, excludes only known write-only opens, preserves the exact-one-read assertion and exercises both replacement branches. No helper or work bound was relaxed to make these controls pass.

Ordinary Node CI runs four portable catalog/projection/inventory regressions and explicitly proves the POSIX refusal on Windows; it does not certify the Mac-only transfer fixture. The new runner must be included in the actual test-source snapshot and canonical LF attributes. Root integrated the exact implementation, canonical shell and durable fixture, then the complete current399 tooling cases passed with zero failures/skips/cancellations/todo. All393 earlier actual case identities are retained plus the2 Android CDN and4 iOS archive cases; source hashes matched after execution and canonical shell render equality passed. Functional combined checks: native-followup-combined-399-01/checks.json SHA256395f8993690902f67512c2196c7cb744234966829e445bc8ad7d2cffc61a83aa. Clean source publication/adoption, complete measured source, fresh Pods replay, independent physical ios/Pods/SPM audits, Xcode build and every Android/iOS UI case remain required. Camera hardware, biometric hardware/signing and verified HTTPS domain boundaries remain separately unverified; no case is silently filtered or counted passed.


### 2026-10-30 — PR #558 CI budget correction and remaining native work

The added nine-minute pytest-step timeout cancelled a26 shard6 around completion despite117 passing cases. Revert only that new reduction, preserving the original12-minute job and passive60-second stack diagnostics. Exact negative workflow control:1 expected failure; complete corrected sharding module:82 passes, zero errors/skips. Replacement hosted CI must supersede the retained failure; a26 finished65successes/two failures/three skips and did not run the browser suite.

Actual iOS prebuild/Pods is complete, including the repaired locked Expo archive transfers. Its original whole-output audit remains incomplete at20000entries; a separately declared complete physical audit must pass before Xcode. Android still needs the exact private Gradle role namespace correction, actual normal configure, APK and device tests. Both platforms require matching source/backend/artifact identities and all83cases/249phases independently, with physical hardware/signing gaps reported explicitly. No store-ready or production-release claim is made.

## QA28 — Android USB transport and local Gradle resources (October 30, 2026)

Status: **source repairs verified; native acceptance remains open**. PRD J20/M22, US-MOB-01..08. Preserve the complete83-case/249-phase inventory independently for Android and iOS.

Actual Android configure04 failed when ktfmt0.22.0 read its bundled ktfmt-version.txt through Gradle's text-resource factory: Gradle eagerly constructed an empty-auth HTTP connector even for the local JAR resource. The repair returns a connector that refuses all five I/O entry points before constructing an HTTP delegate. The existing marked credentials, repository, TLS, redirect and Download guards remain unchanged. Actual MF11 passed every original eight transport phases, the unchanged official JAR resource read, five blocked-I/O controls and three malformed-auth refusals. This is configuration-component evidence, not a resolved application graph or APK.

The connected OnePlus was authorized through a separately owned ADB server. Read-only observations found Android16/API36, ARM64,4096-byte pages, an empty qemu property and a canonical USB path. No app, package, settings or data mutation was performed. Keep those observations separate from application acceptance and the required16384-byte emulator proof.

An explicit usb-reverse recipe binds ADB5042/Appium4729/system8206, distinct HTTPS127.0.0.1 API/web origins, the QA package and matching configuration, receipt, seed, binary and returned-session identities. Legacy emulator tuples and iOS defaults remain unchanged. Phone privacy observations use the exact QA package's run-as sandbox; they never enable root. Permission/I/O/ambiguous stat failures cannot become absent-copy evidence. Physical layout observations recheck getconf and boot identity and bind the current result to both retained receipts across V1, Queue/Privacy and ClientExtensions. Physical4K or16K workflows do not certify the separate16K emulator inventory.

The pinned local-transport.py helper is in the actual five-file Android admission snapshot, producer/consumer closure and Files fingerprint, with canonical LF Git attributes. Actual snapshot imports, missing/changed-helper refusals and descriptor-verified buffer staging are covered. Preserve the earlier missing-input/serializer preparation failures and the incompatible five-field physical test fixture; the final real four-field producer/consumer composition supersedes them.

The integrated27-path functional Node run passed719/719 with zero failures/skips/cancellations/todo and retained every original399 case exactly once. All12 owned groups and Git/source/runtime/output pairs closed. Acceptance: /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/native-usb-gradle-functional-719-01/actual-exit-acceptance.json SHA25664621d575e636fc8a64ca6cba8f18f68029b6150fbd285462664751c85c03210. Independent complete Python components passed110 producer cases and23 admission cases; source buffers match the integration. These are source/fixture checks, not Appium passes.

Parent dc3d026b5f1eeb87c5279ec348b15b2fb24ba5b1 completed all five hosted workflows successfully:68checks passed, two intentionally skipped, zero failures, including all32 PostgreSQL shards and the browser suite. This supersedes the retained step-timeout regression for that revision; a new source revision needs its own CI.

The original configure04 cache-bound refusal and backend04 VM-bind failure remain failed. Fresh source-bound backend fixtures, actual Android configuration/APK, Simulator app, full native inventories and physical camera/biometric/signed-link checks remain required. No store archive or release-ready claim is made.
