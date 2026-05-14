# Codex Review — FUTURE_WORKPLAN_2026-05-14.md
Reviewer: Codex
Date: 2026-05-14
Commit reviewed: `0669e149cc9abf22aaa5a5b83c1d0b10f8b7335f` on `codex/corpus-proof-operational-fixes`

## Executive summary

- Total items sampled: 38 of 130
- AGREE: 18
- WRONG-STATUS: 5
- WRONG-PRIORITY: 6
- STALE-DOC: 5
- FALSE-CLOSURE: 4
- New gaps to add: 3 (`G-131`..`G-133`)
- Sharpening required (Check D): 29 items
- Guardrail gaps (Check E): 7 missing guardrail cells across 4 items
- Top 5 findings, ranked by blast radius:
  1. The workplan is not reproducible from the reviewed commit: two listed source PRDs are absent, the alembic inventory is newer than this branch, and Appendix B marks Litigation Intelligence V1 closed although the corresponding services are not present.
  2. Several status calls were generated from a different baseline: Matter File Q&A, mock hearing, affidavit intelligence, proceeding intelligence, and predictive-intelligence files are missing from this commit.
  3. Some P0s are priority-inflated relative to the litigation-wedge J01-J15 test, especially SSO/SCIM, plan entitlements, command palette, CLM, and outside-counsel spend depth.
  4. Favorability/prediction is correctly in scope, but the workplan acceptance criteria do not consistently require all six guardrails.
  5. Coverage ledgers are real but stale in counts: page-test gaps are 9 current pages, not 30; hotspot line counts and manual client size are also stale.

Verdict: `WORKPLAN-NEEDS-REBASELINE`.

The workplan is directionally useful, but it should not be treated as execution-ready until it is regenerated against the exact branch/commit being planned. Code is the source of truth, and this commit does not contain multiple PRDs, migrations, or LI/MFQ implementation files that the workplan treats as closed baseline.

## Check A — Status accuracy

| ID | Stated | Actual | Evidence | Verdict |
| --- | --- | --- | --- | --- |
| G-001 Backend & web hotspot decomposition | Partial, P1 | Partial, P1 | `docs/FUTURE_WORKPLAN_2026-05-14.md:46` cites stale sizes; current measured sizes are `apps/api/src/caseops_api/db/models.py` 4704 lines, `services/matters.py` 2241, `api/routes/matters.py` 2152, `apps/web/lib/api/endpoints.ts` 3406. | STALE-DOC |
| G-002 Exception-handling discipline | Partial, P1 | Partial, P1 | `apps/api/src/caseops_api/services/authorities.py:407`, `services/drafting.py:989`, and `services/matters.py:2063` still show broad catches on shared services. | AGREE |
| G-003 Temporal durable workflow engine | Missing, P0 | Missing, P0 | `apps/api/src/caseops_api/api/routes/admin.py:252-255` still uses `BackgroundTasks`; `apps/api/src/caseops_api/schemas/calendar.py:80` exposes `blocked_pending_temporal`. | AGREE |
| G-005 Durable notification service | Missing, P0 | Missing, P0 | `apps/api/src/caseops_api/schemas/calendar.py:180` and `:186` mark durable delivery blocked pending Temporal; `apps/api/src/caseops_api/services/notification_rules.py:389` records the same blocker. | AGREE |
| G-006 OIDC + SAML SSO | Missing, P0 | Missing, P1 | Only roadmap text exists at `apps/web/app/app/admin/page.tsx:478`; no SAML/OIDC code was found. This is enterprise J14 hardening, not a litigation-wedge P0. | WRONG-PRIORITY |
| G-007 SCIM provisioning + MFA enforcement | Missing, P0 | Missing, P1 | No SCIM/MFA implementation was found; same J14 enterprise-hardening reasoning as G-006. | WRONG-PRIORITY |
| G-008 Plan entitlements + usage metering | Missing, P0 | Missing, P1 | `docs/FUTURE_WORKPLAN_2026-05-14.md:88` is accurate that no `Plan` / `PlanEntitlement` model exists, but this does not block J05-J09 litigation output. | WRONG-PRIORITY |
| G-018 Matter Tasks tab + Deadlines tab | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/db/models.py:1241` and `:4725` define task/deadline models; `apps/api/src/caseops_api/api/routes/matters.py:1454` exposes task create, but no `/app/matters/[id]/tasks` page exists. | AGREE |
| G-019 Matter Command Center next action | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/api/routes/matters.py:841-872` has `NextActionResponse`; the matter cockpit page has no corresponding next-action card. | AGREE |
| G-022 Conflict-check intake gate | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/services/conflict_checks.py:1-7` explicitly defers the intake gate to v2; `apps/api/src/caseops_api/db/models.py:1304` references the intended intake/cockpit use. | AGREE |
| G-023 Engagement letter workflow | Missing, P0 | Missing, P1 | No `MatterEngagement` / fee-arrangement model was found; it is a commercial/intake gate, not a J05-J09 litigation-wedge blocker. | WRONG-PRIORITY |
| G-031 Proper RAG completion | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/db/models.py:3106` and `:3182` define authority documents/chunks; `apps/api/src/caseops_api/scripts/eval_hnsw_recall.py:552` evaluates recall, but the 4.8/5 corpus gate is not proven across all target buckets. | AGREE |
| G-032 Research treatment / good-law signal | Missing, P0 | Partial, P0 | `apps/api/src/caseops_api/services/authority_treatments.py:1-16` describes treatment aggregation and drafting checks; `apps/web/app/app/research/page.tsx:540-547` renders the research good-law badge. | WRONG-STATUS |
| G-033 Citation graph depth + good-law badges | Partial, P0 | Partial, P0 | Status is right, but evidence is stale: `docs/FUTURE_WORKPLAN_2026-05-14.md:246` says no UI surface, while `apps/web/app/app/research/page.tsx:540-547` already renders treatment badges. | STALE-DOC |
| G-040 Source coverage matrix + freshness SLA | Missing, P0 | Missing, P0 | `apps/api/src/caseops_api/scripts/autonomous_corpus_controller.py:461` has internal coverage SQL and `:1002` event logging, but no public source-coverage manifest exists. | AGREE |
| G-044 Bench-strategy V1 | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/db/models.py:4776` and `:4824` define tenant predictive policy; `apps/api/src/caseops_api/services/bench_strategy_context.py:375-392` gates predictive summary. Frontend/rerank consumers remain partial. | AGREE |
| G-128 Authority rerank consumes judge-favorability signal | Missing, P0 | Partial, P0 | `apps/api/src/caseops_api/services/recommendations.py:169-205` already has `_rerank_by_outcome_bias`, and `:252` applies it. It is not yet the full bench-specific, policy/audit-complete rerank. | WRONG-STATUS |
| G-051 Drafting quality 4.8/5 | Partial, P0 | Partial, P0 | `apps/api/tests/test_eval_drafting_cli.py:1` and `apps/api/tests/fixtures/drafting/bail.json:3` show the eval path/goldens exist, but this does not prove the 4.8/5 target. | AGREE |
| G-052 Senior-lawyer review/signoff | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/db/models.py:3827`, `:3879`, and `:3915` define drafts, versions, and reviews; threaded redline/signoff workflow remains incomplete. | AGREE |
| G-055 Drafting citation/treatment checks | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/services/draft_validators.py:158-179` validates citation coverage, but pinpoint insertion and adverse-treatment filing gates are not complete. | AGREE |
| G-129 Drafting prompt injects bench-favorability context | Partial, P0 | Partial, P0 | Status is right, but evidence is stale: `docs/FUTURE_WORKPLAN_2026-05-14.md:421-423` says only appeal drafting is wired; `apps/api/tests/test_drafting_bench_aware.py:82-117` proves predictive addendum fires for every bench-aware template and not for non-bench templates. | STALE-DOC |
| G-060 Hearing pack auto-trigger + export | Partial, P1 | Partial, P1 | `apps/api/src/caseops_api/services/hearing_packs.py:213-214` writes `ModelRun`; scheduled auto-trigger remains absent per workplan. | AGREE |
| G-061 Mock-hearing LLM rubric | Deferred-by-design, P2 | Missing on this commit | Workplan says `services/mock_hearing.py` shipped at `docs/FUTURE_WORKPLAN_2026-05-14.md:438`; `apps/api/src/caseops_api/services/mock_hearing.py` is absent in this commit. | FALSE-CLOSURE |
| G-063 Affidavit-intelligence LLM path | Partial, P2 | Missing on this commit | Workplan says V1 deterministic exists at `docs/FUTURE_WORKPLAN_2026-05-14.md:450`; `apps/api/src/caseops_api/services/affidavit_intelligence.py` is absent in this commit. | FALSE-CLOSURE |
| G-068 Predictive LI-S7D+ | Partial, P0 | Not reproducible from this commit | `docs/FUTURE_WORKPLAN_2026-05-14.md:484` says LI-S7A/B/C shipped, but `apps/api/src/caseops_api/services/predictive_intelligence.py` is absent. Only PG-107 bench predictive code exists at `apps/api/src/caseops_api/services/bench_strategy_context.py:375-392`. | FALSE-CLOSURE |
| G-073 Per-workflow LLM eval harness | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/db/models.py:4469-4502` defines `EvaluationRun`/`EvaluationCase`; `apps/api/src/caseops_api/services/evaluation.py:13` exposes recording, but workflow goldens are incomplete. | AGREE |
| G-077 Strategy redirect HTTPS | Missing, P2 | Missing, P2 | `docs/FUTURE_WORKPLAN_2026-05-14.md:548-549` describes the proxy-header gap; no contradictory implementation evidence was found. | AGREE |
| G-079 MFQ export to brief/hearing artifact | Missing, P2 | Not reproducible from this commit | Workplan says idempotent MFQ export to note shipped at `docs/FUTURE_WORKPLAN_2026-05-14.md:564`; `apps/api/src/caseops_api/services/matter_file_qa.py` and `apps/api/src/caseops_api/schemas/matter_file_qa.py` are absent. | FALSE-CLOSURE |
| G-084 Universal command palette/global search | Missing, P0 | Missing, P1 | No global palette was found; it improves navigation but does not block any single J05-J09 litigation journey end-to-end. | WRONG-PRIORITY |
| G-089 CLM lifecycle | Partial, P0 | Partial, P1 | `apps/api/src/caseops_api/db/models.py:2595`, `:2723`, and `:2974` already model contracts, obligations, and attachments. The remaining CLM lifecycle is important but not litigation-wedge P0. | WRONG-PRIORITY |
| G-091 GC spend depth | Missing, P0 | Partial, P1 | `apps/api/src/caseops_api/api/routes/outside_counsel.py:45` exposes portfolio analytics and `:100-109` records spend; full rate-card/budget/scorecard depth remains. | WRONG-STATUS |
| G-093 Employee admin + bulk import + custom roles | Partial, P1 | Partial, P1 | `apps/api/src/caseops_api/db/models.py:823-942` defines bulk import jobs/rows; offboarding/admin surfaces exist in `apps/web/app/app/admin/employees/page.tsx`. | AGREE |
| G-098 Page-level sibling tests | Partial, P1 | Partial, P1 | Status is right, but counts are stale: current inventory is 44 app pages with 9 missing sibling tests; `apps/web/app/__page-coverage-matrix.test.ts:26-68` lists the allowed gaps. | STALE-DOC |
| G-107 Authorization matrix tests | Missing, P0 | Partial, P0 | `apps/api/src/caseops_api/api/dependencies.py:259-278` enforces capabilities and `apps/api/tests/test_role_guards.py:140` sweeps mutating routes, but exhaustive role x resource x action coverage is not complete. | WRONG-STATUS |
| G-111 Manual-tester replacement standard | Partial, P0 | Partial, P0 | `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md:112-220` keeps AQ-001/AQ-003/AQ-004/AQ-006 partial. | AGREE |
| G-117 Tenant AI-spend daily cap | Partial, P0 | Partial, P0 | `apps/api/src/caseops_api/services/voyage_usage.py:1-45` implements Voyage spend ledger/cap mechanics; broader per-tenant per-purpose alert/auto-throttle is missing. | AGREE |
| G-121 OpenAPI client drift gate | Partial, P2 | Partial, P2 | Status is right, but evidence is stale: `docs/FUTURE_WORKPLAN_2026-05-14.md:832` cites 1728 LOC; current `apps/web/lib/api/endpoints.ts` is 3406 lines. CI drift exists at `.github/workflows/security.yml:140-150`. | STALE-DOC |
| G-127 GC legal-front-door + intake/triage/SLA | Missing, P1 | Partial, P1 | `apps/api/src/caseops_api/api/routes/intake.py:44-104` has list/create/triage/promote endpoints; `apps/web/app/app/intake/page.tsx` exists. SLA/capacity/stakeholder portal remain missing. | WRONG-STATUS |

## Check B — Coverage completeness

### G-131 Workplan baseline provenance / branch rebaseline

- **Status:** Missing
- **Priority:** P2
- **PRD ref:** Strict quality review protocol; source-of-truth rule in `CLAUDE.md`
- **Current evidence:** The workplan lists `docs/PRD_LITIGATION_INTELLIGENCE_EXPANSION_2026-05-11.md` and `docs/PRD_MATTER_FILE_QA_2026-05-13.md` as sources, but both files are absent in this commit. `docs/FUTURE_WORKPLAN_2026-05-14.md:903` also claims 41 alembic migrations through 2026-05-13, while this branch ends at `20260507_0002_legalworkspace_audit_strategy.py`.
- **Acceptance:** Regenerate the workplan from a clean checkout of the intended commit; Appendix A records `git rev-parse HEAD`, source-file existence, migration count/newest migration, and untracked-file status. A reviewer can rerun the inventory and reproduce the same source list.

### G-132 Matter File Q&A V1 baseline absent on reviewed branch

- **Status:** Missing
- **Priority:** P1
- **PRD ref:** `PRD_MATTER_FILE_QA_2026-05-13.md` as named in the workplan inputs
- **Current evidence:** `docs/FUTURE_WORKPLAN_2026-05-14.md:561-585` catalogs only residual MFQ gaps, but `apps/api/src/caseops_api/services/matter_file_qa.py`, `apps/api/src/caseops_api/schemas/matter_file_qa.py`, and `apps/web/app/app/matters/[id]/matter-file-qa/page.tsx` are absent from the reviewed commit.
- **Acceptance:** Either rebase this branch to the commit that actually contains MFQ V1, or add explicit V1 gaps for service, schema, route, UI, tests, audit, and source-boundary behavior. `scripts/verify-backend.ps1 apps/api/tests/test_matter_file_qa.py` and a sibling web test must pass before residual-only MFQ gaps are allowed.

### G-133 Litigation Intelligence V1 baseline absent on reviewed branch

- **Status:** Missing
- **Priority:** P0
- **PRD ref:** LI-S1..LI-S8 as named in Appendix B; canonical PRD J06/J09
- **Current evidence:** `docs/FUTURE_WORKPLAN_2026-05-14.md:936` marks LI-S1/S2/S3/S4/S5/S6/S7A/S7B/S7C/S8 closed, but `apps/api/src/caseops_api/services/predictive_intelligence.py`, `mock_hearing.py`, `affidavit_intelligence.py`, and `proceeding_intelligence.py` are absent from this commit.
- **Acceptance:** Rebase to the implementation commit or split Appendix B closures back into open G-IDs. Verification must include backend tests for each LI service and a Playwright spec for the shipped LI UI before LI-S7D+ is treated as residual-only work.

## Check C — Priority calibration

Demotions recommended:

- `G-006` and `G-007`: P0 -> P1. SSO, SCIM, and MFA are required enterprise controls for J14/J15, but this commit can still validate the litigation wedge without them.
- `G-008`: P0 -> P1. Entitlements and metering are commercial launch controls, not end-to-end blockers for J05/J06/J07/J08/J09.
- `G-023`: P0 -> P1. Engagement letters are important intake governance, but not the blocker for research, drafting, hearing prep, or bench strategy.
- `G-084`: P0 -> P1. Global search improves operator speed but does not block a complete litigation matter journey.
- `G-089` and `G-091`: P0 -> P1. CLM and outside-counsel spend depth are core LegalWorkspace/GC features, but not the litigation-wedge P0 path.

Promotions recommended:

- `G-133` should be P0 if this workplan continues to treat LI predictive/favorability work as a litigation-wedge blocker. The branch either needs the LI baseline restored or the workplan needs to stop treating LI-S7D+ as residual-only.

Keep as P0:

- `G-003`, `G-005`, `G-018`, `G-019`, `G-022`, `G-031`, `G-032`, `G-033`, `G-040`, `G-044`, `G-051`, `G-052`, `G-055`, `G-068`, `G-073`, `G-107`, `G-111`, `G-117`, `G-128`, and `G-129` are properly P0 when judged against durable execution, citation-grounded litigation output, bench intelligence, drafting quality, safety, and automation-proof verification.

## Check D — Acceptance criteria sharpness

The workplan acceptance text is mostly product-behavioral. For P0 and favorability/prediction items, it should include exact verification commands or artifacts.

| ID | Current sharpness | Proposed sharper acceptance |
| --- | --- | --- |
| G-003 | Vague on proof path | Add `scripts/verify-backend.ps1 apps/api/tests/test_temporal_workflows.py` and require `rg -n "BackgroundTasks" apps/api/src/caseops_api/api/routes` to show no critical workflow start path. |
| G-005 | No queue/DLQ test named | Add backend tests for retry, DLQ, webhook status, and audit in `apps/api/tests/test_notifications_durable_delivery.py`; add Playwright dashboard smoke. |
| G-006 | No IdP fixture | Require OIDC and SAML fixture tests plus a Playwright admin mapping test; include a negative test for domain mismatch. |
| G-007 | No SCIM/MFA conformance check | Require SCIM create/update/deactivate tests, MFA enforcement tests, and emergency-admin bypass audit assertions. |
| G-008 | No entitlement gate matrix | Require route/page tests proving seat limit, feature flag, AI quota, and overage behavior; include SQL assertion for `PlanEntitlement`. |
| G-018 | No UI/test path | Require sibling page tests for `/tasks` and `/deadlines` plus backend create/assign/complete tests and matter-access negative tests. |
| G-019 | No route/page proof | Require matter-cockpit test that next action is derived from today feed and sidebar default changes only when active matters exist. |
| G-022 | No intake state-machine test | Require test that `intake -> active` is blocked until conflict `cleared` or partner-waived; assert audit and email. |
| G-023 | No e-sign/storage proof | Require model migration, e-sign adapter contract test, attachment persistence assertion, and waiver audit test. |
| G-031 | Corpus proof not executable | Require committed `caseops-eval-hnsw-recall` output per bucket: `rating: X.Y/5 (recall@10=..., MRR=..., rank=...)`, all >=4.8/5. |
| G-032 | No treatment regression path | Require backend treatment classifier tests, research badge test, and drafting adverse-treatment cannot-file test. |
| G-033 | No graph drill-down test | Require API test for cited-by/followed/overruled counts and web test for badge + drill-down. |
| G-040 | No manifest schema | Require generated JSON/CSV coverage manifest and CI check for jurisdiction x court x type x freshness fields. |
| G-044 | Missing some guardrails | Require one backend and one Playwright test proving all six favorability guardrails on render. |
| G-045 | Missing several guardrails | Require the same six-guardrail test set before V2 trend/inter-judge analytics ship. |
| G-051 | Eval not tied to release | Require `caseops-eval-drafting` command and artifact path; CI fails below 4.8/5. |
| G-052 | No review workflow test names | Require backend review-thread/redline/signoff tests plus Playwright reviewer assignment and filing-bundle audit. |
| G-055 | No pinpoint/treatment fixtures | Require fixtures with pinpoint paragraphs, adverse treatment, and no-authority failure state. |
| G-068 | Missing no-fabrication check | Require calibration artifact, Brier/calibration threshold, and structural no-fabrication test for every predictive surface. |
| G-073 | No named goldens | Require exact golden dataset paths and a CI job that fails on each workflow threshold. |
| G-084 | No scoping proof | Require Cmd+K Playwright test that tenant and matter-access boundaries hide unauthorized resources. |
| G-089 | No lifecycle E2E | Require request -> approval -> e-sign -> obligation -> renewal-alert Playwright path and backend audit assertions. |
| G-091 | No spend fixtures | Require rate-card, budget variance, billing guideline, scorecard, and executive dashboard tests with tenant isolation. |
| G-107 | No exhaustive matrix artifact | Require generated route x role x capability matrix artifact plus cross-tenant 404 tests for every protected route. |
| G-111 | Outcome metric unverifiable | Define the 30-day regression-escape denominator/source and require CI artifact showing >=95%. |
| G-117 | No throttle proof | Require per-tenant per-purpose cap test, alert emission assertion, and hard-block/auto-throttle negative test. |
| G-128 | Missing no-fabrication | Require rerank test with indexed bench history, insufficient-history fallback, policy-off fallback, ModelRun, AuditEvent, and no fabricated stats. |
| G-129 | Good detail, no command | Add exact backend golden path and Playwright drafting-render spec for every bench-aware template. |
| G-130 | Good detail, no command | Add exact forecast API/page tests, SQL assertion for audit rows, and synthetic no-fabrication fixture. |

## Check E — Favorability/prediction guardrail audit

Matrix legend: `Y` means the guardrail is explicit in the workplan acceptance text. Code may implement some pieces already, but this check is about the workplan acceptance criteria.

| ID | Cites source IDs | Visible sample band | Tenant predictive toggle | ModelRun + AuditEvent | Insufficient-evidence degrade | No-fabrication structural test |
| --- | --- | --- | --- | --- | --- | --- |
| G-044 | Y (`docs/FUTURE_WORKPLAN_2026-05-14.md:317`) | Y (`:317`) | Y (`:317`) | N (`:316` current evidence only, not acceptance) | Y (`:317`) | N |
| G-045 | Y (`:323`) | Y (`:323`) | Y (`:323`) | N | N | N |
| G-068 | Y (`:485`) | Y (`:485`) | Y (`:485`) | Y (`:485`) | Y (`:485`) | N |
| G-128 | Y (`:359`) | Y (`:359`) | Y (`:359`) | Y (`:359`) | Y (`:359`) | N |
| G-129 | Y (`:423`) | Y (`:423`) | Y (`:423`) | Y (`:423`) | Y (`:423`) | Y (`:423`) |
| G-130 | Y (`:539`) | Y (`:539`) | Y (`:539`) | Y (`:539`) | Y (`:539`) | Y (`:539`) |

Required edits:

- Add `ModelRun + AuditEvent on every render` and `structural no-fabrication test` to `G-044`.
- Add `ModelRun + AuditEvent`, insufficient-evidence degradation, and no-fabrication test to `G-045`.
- Add explicit no-fabrication structural tests to `G-068` and `G-128`.
- Keep the favorability/prediction features in scope. The defect is guardrail completeness, not the product stance.

## Check F — PRD/ledger conflicts

- `docs/PRD_LITIGATION_INTELLIGENCE_EXPANSION_2026-05-11.md` and `docs/PRD_MATTER_FILE_QA_2026-05-13.md` are listed as inputs but are absent from this commit. Source of truth: reviewed code and present docs. Recommendation: mark the workplan baseline stale until the branch is rebased or the source PRDs are restored.
- Workplan Appendix A says there are 41 migrations and newest is 2026-05-13 matter_file_qa_history (`docs/FUTURE_WORKPLAN_2026-05-14.md:903`). Current branch ends at `20260507_0002_legalworkspace_audit_strategy.py`. Source of truth: `apps/api/alembic/versions/`. Recommendation: re-run migration inventory.
- Workplan Appendix B marks LI-S1..LI-S8 closed (`docs/FUTURE_WORKPLAN_2026-05-14.md:936`), but the corresponding service files are absent. Source of truth: current branch code. Recommendation: demote Appendix B LI closure to stale-doc for this branch.
- Older PRDs/code comments still conflict with the user-confirmed favorability stance: `docs/PRD.md:984`, `docs/PRD_BENCH_MAPPING_2026-04-25.md:57`, `apps/api/src/caseops_api/services/drafting_prompts.py:437`, `apps/api/src/caseops_api/db/models.py:4193`, and `apps/web/lib/api/openapi-types.ts:2082`, `:2253`, `:2287`. Source of truth: 2026-05-14 product stance plus guardrails. Recommendation: mark these lines stale-doc/comment drift, not product blockers.
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` conflicts with itself on Postgres validation: `P1-006` says Missing at `:67`, while `AQ-005` says Implemented at `:171-176`; `.github/workflows/ci.yml:63-136` confirms the Postgres validation job exists. Source of truth: CI workflow + current test file. Recommendation: mark `P1-006` stale-doc.
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md:516` says email ingest and calendar sync are Missing. Calendar sync exists (`apps/api/src/caseops_api/api/routes/calendar.py` and `apps/api/src/caseops_api/services/calendar_sync.py`); email ingest remains missing. Source of truth: code. Recommendation: split the ledger item into calendar sync Partial/Implemented evidence and email ingest Missing.

## Verdict

`WORKPLAN-NEEDS-REBASELINE`

The workplan should be regenerated or manually corrected before execution. The main issue is not the direction of the roadmap; it is that the document mixes the reviewed branch with later/uncommitted or different-branch evidence. Once the baseline drift is fixed, most remaining edits are straightforward: demote inflated enterprise/business P0s, correct stale status calls, add missing LI/MFQ baseline gaps, and make P0/favorability acceptance criteria executable.

## Files Read Or Scanned

- `CLAUDE.md`
- `AGENTS.md` (from stash copy, because the file is not present in this branch after the earlier stash)
- `.agents/skills/strict-quality-review/SKILL.md` (from stash copy)
- `.agents/skills/enterprise-hardening/SKILL.md` (from stash copy)
- `.agents/skills/caseops-prd-execution/SKILL.md` (from stash copy)
- `.agents/skills/bug-fixing/SKILL.md` (from stash copy)
- `docs/FUTURE_WORKPLAN_2026-05-14.md`
- `docs/PRD_CLAUDE_CODE_2026-04-23.md`
- `docs/PRD.md`
- `docs/PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05.md`
- `docs/PRD_BENCH_MAPPING_2026-04-25.md`
- `docs/PRD_BENCH_STRATEGY_2026-04-26.md`
- `docs/PRD_STATUTE_MODEL_2026-04-25.md`
- `docs/PRD_CAUSE_LIST_SCRAPER_2026-04-25.md`
- `docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md`
- `docs/STRICT_BUG_TASKLIST_2026-04-22.md`
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
- `docs/WORK_TO_BE_DONE.md`
- `docs/STRICT_PRODUCT_GAPS_2026-04-30.md`
- `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`
- `docs/PRODUCT_GAP_ANALYSIS_2026-05-01.md`
- `docs/STRATEGY_PLANNER_FOLLOWUPS_2026-05-03.md`
- `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md`
- `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`
- `.github/workflows/release-verify.yml`
- `scripts/coverage_gate.py`
- `apps/api/src/caseops_api/db/models.py`
- `apps/api/src/caseops_api/api/dependencies.py`
- `apps/api/src/caseops_api/api/routes/admin.py`
- `apps/api/src/caseops_api/api/routes/calendar.py`
- `apps/api/src/caseops_api/api/routes/contracts.py`
- `apps/api/src/caseops_api/api/routes/courts.py`
- `apps/api/src/caseops_api/api/routes/intake.py`
- `apps/api/src/caseops_api/api/routes/matters.py`
- `apps/api/src/caseops_api/api/routes/outside_counsel.py`
- `apps/api/src/caseops_api/api/routes/recommendations.py`
- `apps/api/src/caseops_api/services/audit.py`
- `apps/api/src/caseops_api/services/audit_exports.py`
- `apps/api/src/caseops_api/services/authorities.py`
- `apps/api/src/caseops_api/services/authority_treatments.py`
- `apps/api/src/caseops_api/services/bench_strategy_context.py`
- `apps/api/src/caseops_api/services/calendar_sync.py`
- `apps/api/src/caseops_api/services/conflict_checks.py`
- `apps/api/src/caseops_api/services/contracts.py`
- `apps/api/src/caseops_api/services/corpus_ingest.py`
- `apps/api/src/caseops_api/services/corpus_structured.py`
- `apps/api/src/caseops_api/services/court_sync_sources.py`
- `apps/api/src/caseops_api/services/draft_validators.py`
- `apps/api/src/caseops_api/services/drafting.py`
- `apps/api/src/caseops_api/services/drafting_prompts.py`
- `apps/api/src/caseops_api/services/evaluation.py`
- `apps/api/src/caseops_api/services/hearing_packs.py`
- `apps/api/src/caseops_api/services/llm.py`
- `apps/api/src/caseops_api/services/matter_audit.py`
- `apps/api/src/caseops_api/services/matters.py`
- `apps/api/src/caseops_api/services/notification_rules.py`
- `apps/api/src/caseops_api/services/outside_counsel.py`
- `apps/api/src/caseops_api/services/recommendations.py`
- `apps/api/src/caseops_api/services/tenant_ai_policy.py`
- `apps/api/src/caseops_api/services/voyage_usage.py`
- `apps/api/src/caseops_api/schemas/calendar.py`
- `apps/api/src/caseops_api/schemas/audit.py`
- `apps/api/src/caseops_api/scripts/autonomous_corpus_controller.py`
- `apps/api/src/caseops_api/scripts/eval_hnsw_recall.py`
- `apps/api/tests/test_route_coverage_matrix.py`
- `apps/api/tests/test_role_guards.py`
- `apps/api/tests/test_drafting_bench_aware.py`
- `apps/api/tests/test_eval_workflows.py`
- `apps/api/tests/test_eval_citations.py`
- `apps/api/tests/test_eval_drafting_cli.py`
- `apps/api/tests/test_eval_hnsw_recall.py`
- `apps/api/tests/test_legalworkspace_offboarding.py`
- `apps/api/tests/test_legalworkspace_contract_metadata.py`
- `apps/api/tests/test_legalworkspace_calendar_sync.py`
- `apps/api/tests/test_legalworkspace_matter_audit.py`
- `apps/api/tests/fixtures/drafting/bail.json`
- `apps/web/lib/api/endpoints.ts`
- `apps/web/lib/api/openapi-types.ts`
- `apps/web/app/__page-coverage-matrix.test.ts`
- `apps/web/app/app/admin/page.tsx`
- `apps/web/app/app/admin/employees/page.tsx`
- `apps/web/app/app/admin/email-templates/page.tsx`
- `apps/web/app/app/intake/page.tsx`
- `apps/web/app/app/matters/[id]/page.tsx`
- `apps/web/app/app/matters/[id]/audit/page.tsx`
- `apps/web/app/app/matters/[id]/communications/page.tsx`
- `apps/web/app/app/matters/[id]/documents/[attachment_id]/view/page.tsx`
- `apps/web/app/app/matters/[id]/drafts/page.tsx`
- `apps/web/app/app/matters/[id]/drafts/new/page.tsx`
- `apps/web/app/app/matters/[id]/outside-counsel/page.tsx`
- `apps/web/app/app/research/page.tsx`
- `apps/web/app/app/today/page.tsx`
- `apps/web/app/app/outside-counsel/page.tsx`
