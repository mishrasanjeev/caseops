# CaseOps Product Gap Analysis

Date: 2026-04-30
Scope: product, workflow, UX, data, AI trust, legal-market fit, enterprise readiness
Audience: founder, product, engineering

## Executive Verdict

CaseOps is a serious founder-stage product with unusually strong backend/security discipline for a pre-alpha legal-tech build. It has real foundations: matters, documents, drafting, recommendations, hearings, contracts, outside counsel, billing, client/outside-counsel portals, audit events, role/capability gates, tenant isolation, upload hardening, and a legal corpus pipeline.

But it is not yet close to being "the best" for law firms, solo lawyers, or general counsels. The gap is not one feature. The gap is product completeness, workflow depth, data authority, daily usability, and buyer trust.

The brutal truth:

- It currently reads like a broad legal OS prototype with many modules, not a finished system of work that a lawyer can live in daily.
- The strongest engineering work is in backend controls, but the product value depends on content coverage, workflow polish, integrations, and adoption ergonomics. Those are weaker.
- The product is trying to compete simultaneously with practice management, legal research, drafting AI, CLM, outside counsel management, and legal ops platforms. It cannot win all categories at shallow depth.
- The most promising wedge is India-first litigation operations plus citation-grounded drafting/hearing prep, not generic "legal OS for everyone."
- The biggest risk is overclaiming. Marketing and docs say "one workspace" and "best for legal teams"; the implementation still has many manual steps, incomplete workflows, and uneven UI/testing coverage.

## Market Bar

The competitive bar in 2026 is high:

- Indian research incumbents advertise massive trusted corpora, verified citations, good-law signals, and legal analytics: cited answers grounded in a proprietary database, verified/hyperlinked citations, corpora in the millions of documents, daily updates, good-law flagging, analytics, judge-behaviour insights, case comparison, privacy/no-training language, and DPDP/EU AI Act claims.
- Established practice-management platforms set user expectations around intake, CRM, time tracking, documents, billing, payments, calendars, secure client communications, and mobile convenience in one workflow.
- Enterprise legal management platforms in this category set the GC bar around matter-spend view, e-billing, benchmarking analytics, rate management, RFPs, budget controls, and outside counsel scorecards.
- CLM platforms in this category set the contract bar around AI throughout the lifecycle: smart import, custom AI properties, AI playbooks, negotiation/redline workflows, approvals, insights, and process analytics.
- Leading legal AI platforms set the AI bar around trusted content, document analysis, drafting, workflow agents, secure collaboration, Microsoft/DMS integrations, audit logs, SAML SSO, and scale claims.

CaseOps has a legitimate India-specific opportunity, but the benchmark is not "can we ship a route?" The benchmark is "can a lawyer, partner, GC, or client use this under deadline pressure without leaving the system?"

External benchmark sources are listed at the end of this document.

## Current Strengths

Do not lose these. They are real advantages.

| Area | What is strong | Evidence |
| --- | --- | --- |
| Matter-native architecture | Most workflows anchor to matter, contract, client, hearing, or portal grants. | `apps/api/src/caseops_api/db/models.py`, `apps/api/src/caseops_api/api/router.py` |
| Security posture | HttpOnly cookie model, CSRF, rate limits, audit events, upload validation, tenant isolation, ethical walls, role/capability guards. | `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`, `apps/api/src/caseops_api/core/cookies.py`, `apps/api/src/caseops_api/services/matter_access.py` |
| AI audit shape | `ModelRun`, provider abstraction, tenant AI policy, cost ledger, mock provider for CI. | `apps/api/src/caseops_api/services/llm.py`, `apps/api/src/caseops_api/db/models.py` |
| Drafting workflow | Draft state machine, review gates, verified-citation approval gate, DOCX export. | `apps/api/src/caseops_api/services/drafting.py`, `apps/web/app/app/matters/[id]/drafts/` |
| India-first litigation strategy | Court/judge/statute/bench strategy work is differentiated versus generic practice tools. | `docs/PRD_BENCH_STRATEGY_2026-04-26.md`, `apps/api/src/caseops_api/services/bench_strategy.py` |
| Portal direction | Client portal and outside-counsel portal are meaningful because legal work crosses org boundaries. | `apps/api/src/caseops_api/api/routes/portal.py`, `apps/web/app/portal/` |
| Testing culture | Large pytest/Vitest/Playwright investment and explicit audit ledgers. | `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md`, `tests/e2e/`, `apps/api/tests/` |

## Top Product Gaps

These are the highest-leverage gaps to close before claiming category leadership.

| Severity | Gap | Why it matters | Evidence / anchor |
| --- | --- | --- | --- |
| P0 | No single killer workflow is finished end to end at market depth. | Best-in-class products win one critical workflow deeply before becoming platforms. CaseOps spreads effort across many modules. | Broad route spread in `apps/api/src/caseops_api/api/router.py`; many modules are partial. |
| P0 | Legal corpus/content moat is far behind incumbents. | Research/drafting trust depends on authoritative, current, comprehensive data. Incumbents advertise millions of documents and good-law signals. | `docs/WORK_TO_BE_DONE.md` describes a small/tracked corpus and future 475k-doc target. |
| P0 | Product positioning is too broad. | Law firms, solo lawyers, and GCs have different buying triggers. One message cannot carry all three. | Marketing routes: `law-firms`, `solo-lawyers`, `general-counsels`; product modules span too many categories. |
| P0 | UI is functional but not yet daily-driver quality. | Lawyers will not tolerate cognitive friction during drafting, hearing prep, billing, or urgent research. | Large page components: `guide/page.tsx` 864 lines, `law-firms/page.tsx` 854, `intake/page.tsx` 747, `contracts/[id]/page.tsx` 736, `communications/page.tsx` 604. |
| P0 | Enterprise identity is incomplete. | GCs and larger firms expect SAML/OIDC SSO, MFA, lifecycle management, retention controls, and admin reporting. | PRD lists SSO/MFA; current architecture says SSO-ready, not shipped. |
| P0 | GC spend management is too shallow. | GCs buy on cost control, e-billing, budgets, rate review, invoice guidelines, and outside counsel performance. | `outside_counsel.py` has profiles/assignments/spend, but no rate cards, budgets-to-actuals workflow depth, invoice guideline enforcement, RFPs, or benchmark analytics. |
| P0 | Contract workflow is not yet CLM. | GCs expect request intake, workflow approvals, negotiation, e-signature, repository, obligation tracking, analytics. | `contracts/[id]/page.tsx` supports upload/extract/playbook/redline view, but not lifecycle orchestration. |
| P1 | Research UX is not at incumbent quality. | "Search results" are not enough; lawyers expect filters, citators, treatment, good-law status, copy-to-draft, saved notebooks, and source verification. | `apps/web/app/app/research/page.tsx`; `services/authorities.py`; no good-law/citator equivalent. |
| P1 | Drafting templates are promising but not document-production grade. | Lawyers need court-specific formatting, annexure/index, vakalat/affidavit variants, filing checklists, citation anchors, revision compare, PDF export. | README lists remaining PDF export, template selection, revision diff, inline citation anchors. |
| P1 | Bench strategy has a governance contradiction. | Docs conflict between "no favorability scoring" and later "predicted disposition / judge tendencies authorized." This is legally and reputationally sensitive. | `docs/PRD_BENCH_STRATEGY_2026-04-26.md`, `services/bench_strategy_context.py`, `components/matter/BenchStrategyPanel.tsx`. |
| P1 | Integrations are thin. | Legal teams live in email, Word, Outlook/Gmail, calendars, DMS, storage, e-sign, accounting, and court portals. | Search shows limited email/calendar and no real DMS/Word add-in/e-sign/accounting integrations. |
| P1 | No command-center/global search experience. | A legal OS needs instant search across matters, clients, documents, deadlines, drafts, authorities, invoices, and contacts. | Research is separate; dashboard is not a global work command center. |
| P1 | Notification system is hearing-centric. | Legal teams need reminders for deadlines, filings, tasks, approvals, contract obligations, invoice aging, client responses. | `hearing_reminders.py`; generic deadline notifications are not equally complete. |
| P1 | Client and outside counsel portals need collaboration depth. | Portals must support structured comments, status approvals, document requests, tasks, permissions, notifications, and downloadable bundles. | `apps/web/app/portal/`; `portal_outside_counsel.py` is a start. |
| P1 | Admin console is not enterprise-grade. | Owners need user lifecycle, teams, roles, audit, AI policy, SSO, retention, billing plans, integrations, support access. | `apps/api/src/caseops_api/api/routes/admin.py` notes audit-focused admin; docs mark admin/SSO partial. |
| P1 | Test coverage still has known waivers. | The team cannot rely on automation alone when critical app pages and route cases are waived. | `apps/web/app/__page-coverage-matrix.test.ts`, `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md`. |
| P1 | Architecture still relies on request/polling patterns for some durable work. | Long-running AI, OCR, ingestion, notification, export, and email jobs need durable orchestration and retry semantics. | `docs/architecture.md` says Temporal is target; `docs/WORK_TO_BE_DONE.md` still tracks it. |
| P2 | Pricing/packaging is not evident in-product. | Solo lawyers, firms, and GCs need sharply different packages and willingness-to-pay stories. | Marketing/pricing surfaces do not map cleanly to product entitlement tiers. |
| P2 | Analytics are underdeveloped. | Buyers expect dashboards: matter aging, hearing load, lawyer utilization, realization, spend by firm, contract risk, SLA, outcomes. | Current dashboard is basic; outside counsel summary is limited. |
| P2 | Migration/onboarding is not mature. | Switching legal systems requires bulk import, mapping, validation, training, and data cleanup. | No visible importers for existing matters/contacts/billing/doc repositories beyond corpus/attachments. |

## Persona Gap Analysis

### Law Firms

Law firms need leverage, control, and risk reduction across matters. CaseOps has the right matter-native instinct, but must close daily execution gaps.

| Workflow | Current state | Gap | Priority |
| --- | --- | --- | --- |
| Matter opening | New matter dialog and intake promotion exist. | No conflict check workflow, client engagement letter, fee estimate, document checklist, or assignment template. | P0 |
| Matter cockpit | Overview, documents, hearings, billing, audit, recommendations, drafting exist. | Cockpit is still assembled from many separate surfaces rather than a partner-grade live matter command center. Needs next action, risk, recent changes, pending approvals, upcoming deadlines, and one-click prep. | P0 |
| Drafting | State machine and citation verifier are strong. | Needs court-specific finalization, annexures, citation anchors, revision compare, PDF/export bundles, formatting QA, and template governance. | P1 |
| Hearing prep | Hearing packs and reminders exist. | Needs court-specific checklist, latest order auto-digest, issue list, oral argument cards, opponent/adverse authority tracker, counsel handoff pack, and post-hearing capture. | P1 |
| Research | Grounded search and saved research exist. | Needs citator/good-law status, treatment history, filters, legal issue taxonomy, query refinement, authority maps, and one-click insert into draft. | P0 |
| Team management | Teams/capabilities exist. | Needs workload views, supervision, review queues, delegation, SLAs, and junior work review. | P1 |
| Billing | Invoices, time entries, payments exist. | Needs trust/advance accounting, write-offs, realization, WIP, aging, invoice review, GST/TDS reports, and accounting export. | P1 |
| Client communication | Communications log and portal exist. | Needs inbound email capture, threaded messages, status reports, secure document requests, client approvals, and read receipts. | P1 |

Brutal law-firm assessment: the product has the skeleton of a matter OS. It does not yet replace a firm's actual daily stack because it lacks conflict, intake-to-engagement, document production depth, communication capture, supervision, and financial controls.

### Solo Lawyers

Solo lawyers need speed, affordability, and low setup. They do not want enterprise complexity.

| Workflow | Current state | Gap | Priority |
| --- | --- | --- | --- |
| Quick start | Workspace bootstrap/sign-in exists. | Too much product surface too soon. Needs "create matter -> upload docs -> draft -> invoice" as a guided lane. | P0 |
| Drafting | Stronger than many modules. | Must reduce prompts and decisions. Solo lawyers need opinionated templates and "fill missing facts" flow, not a complex studio. | P1 |
| Billing/payments | Pine Labs/payment paths exist. | Needs simple invoice templates, GST defaults, UPI-first payment UX, payment reminders, and accountant export. | P1 |
| Mobile use | Some mobile responsive work exists. | Solo lawyers will use phones in court. Needs mobile-first hearing diary, quick notes, document scan/upload, reminders, and search. | P0 |
| Research | Corpus search exists. | Needs price-sensitive content strategy. If corpus is thin, solo users will compare unfavourably to established Indian research workflows. | P0 |
| Support | Docs/guide exist. | Needs in-app onboarding, sample matters, empty-state coaching, and task-based help. | P2 |

Brutal solo assessment: the product is currently too broad and too enterprise-shaped for a solo lawyer. A solo version should be a stripped, fast, guided product: matter diary, deadlines, drafting, research, invoice/payment, mobile.

### General Counsels

GCs buy control, risk visibility, cost discipline, and business intake. They do not buy a law-firm drafting studio first.

| Workflow | Current state | Gap | Priority |
| --- | --- | --- | --- |
| Legal intake | Intake queue exists. | Needs business-user portal, SLAs, routing rules, priority scoring, duplicate detection, and request templates. | P0 |
| Matter management | Matters exist. | Needs legal-department portfolio taxonomy, risk scoring, business unit reporting, status reports, reserves/exposure, and executive dashboards. | P0 |
| Outside counsel | Profiles, assignments, spend records, portal exist. | Needs rate cards, budgets, billing guidelines, invoice review, RFPs, matter pricing, scorecards, diversity/quality metrics, and benchmarks. | P0 |
| Contracts | Repository/extraction/playbook/redline view exist. | Needs request-to-sign lifecycle, approvals, negotiation workspace, e-signature, clause library, custom playbooks, obligation owner workflows, renewal alerts, and analytics. | P0 |
| Compliance | Some statute/content work exists. | Needs regulatory obligation tracking, policy attestations, evidence collection, issue remediation, and audit-ready reports. | P1 |
| Enterprise trust | Strong backend controls exist. | Needs SSO/MFA/SCIM, retention, DLP, data residency, support access control, contract/security pack, and DPDP posture. | P0 |

Brutal GC assessment: CaseOps is not yet a GC operating system. It has useful pieces, especially outside counsel and contracts, but lacks the spend-management and CLM depth that corporate legal teams actually budget for.

## UX And Information Architecture Gaps

### 1. Broad navigation without a dominant job

The sidebar exposes many modules: Home, Matters, Intake, Hearings, Calendar, Research, Drafting, Recommendations, Contracts, Clients, Outside Counsel, Portfolio, Courts, Statutes, Admin. That breadth is attractive in a demo but creates decision load.

Needed:

- A role-aware home that changes by persona and current urgency.
- A universal command/search palette across product objects.
- "Today" view: hearings, deadlines, approval requests, overdue tasks, client replies, draft reviews, invoice follow-ups.
- A matter command bar: draft, search, upload, add hearing, send update, create invoice, assign counsel.

### 2. Large client pages are becoming product debt

Several important pages are already too large:

- `apps/web/app/guide/page.tsx`: 864 lines
- `apps/web/app/law-firms/page.tsx`: 854 lines
- `apps/web/app/app/intake/page.tsx`: 747 lines
- `apps/web/app/app/contracts/[id]/page.tsx`: 736 lines
- `apps/web/app/app/clients/[id]/page.tsx`: 617 lines
- `apps/web/app/portal/oc/matters/[id]/page.tsx`: 610 lines
- `apps/web/app/app/matters/[id]/communications/page.tsx`: 604 lines

This is a product risk, not just a code style issue. Huge pages make it harder to refine interactions, add states, support mobile, and test individual workflows.

Needed:

- Split every 500+ line page into route shell, data hooks, view sections, dialogs, and reusable domain components.
- Create module-level design patterns for lists, review queues, side panels, and action bars.
- Make mobile layouts first-class for hearings, notes, research, and draft review.

### 3. Empty states sometimes explain missing product rather than complete a job

Some empty states are honest but reveal unfinished workflows. A production legal tool should not tell users "when this ships" or imply the current surface is only a placeholder.

Needed:

- Every empty state should offer a real next action.
- Remove founder/prototype language from authenticated product.
- Turn roadmap gaps into hidden feature flags or admin-only previews.

### 4. No true review queue

Legal work is review-heavy. Drafts, recommendations, hearing packs, KYC submissions, client replies, invoices, contract findings, and outside-counsel submissions all need review.

Needed:

- A single "Review" inbox with item type, matter, priority, requester, due date, and approve/request changes.
- Partner/supervisor dashboard.
- Review SLA metrics.

## Legal Research And Authority Gaps

This is the largest strategic gap.

### 1. Corpus depth and freshness

The repo has an ingestion pipeline and seeded/ingested examples, but the content moat is far short of incumbents advertising 65+ lakh or 10M+ documents. For legal research, content coverage is not a backend detail; it is the product.

Needed:

- Publish an internal corpus coverage dashboard by court, year, document count, successful OCR, metadata completeness, citation graph completeness, and freshness.
- Prioritize a narrow but deep jurisdiction wedge instead of shallow national coverage.
- Create "coverage confidence" directly in the UI when generating research/drafts.
- Daily ingestion/refresh jobs with visible recency.

### 2. Good-law / treatment signal missing

Research products win on whether an authority is still good law. CaseOps has citation extraction and authority metadata, but not a citator equivalent.

Needed:

- Treatment labels: followed, distinguished, overruled, referred, relied, dissented, reversed.
- Negative treatment warnings in drafting and recommendations.
- Source-linked treatment evidence.
- A "must verify before filing" gate for adverse/negative treatment.

### 3. Search experience is not lawyer-grade yet

Needed:

- Boolean, proximity, citation lookup, party lookup, judge lookup, statute-section filters, court/year filters, sort by relevance/date/court hierarchy.
- Query explanation: why each result matched.
- Result clustering by issue, statute, and procedural posture.
- Saved research notebooks per matter.
- One-click "add to draft authorities" and "mark adverse."

### 4. Statute model is thin

The statute seed includes major Acts, but production statutory research needs amendments, effective dates, rules/regulations, notifications, repeals, state amendments, and authoritative source provenance.

Needed:

- Effective date history and amendment diff.
- Version selector by date.
- State amendments and subordinate legislation.
- Official source URL and scrape freshness.
- Cross-links from statute sections to cases and matter facts.

## AI, Drafting, And Trust Gaps

### 1. The AI promise must be narrower and more provable

The product should stop claiming generalized legal intelligence until evaluation proves it. The strongest AI promise should be:

"For selected Indian litigation workflows, CaseOps creates review-required drafts and hearing material from matter facts and verified primary sources, with visible coverage limits."

Needed:

- Per-workflow evals with goldens: bail, anticipatory bail, quashing, Section 34, commercial suit, writ, cheque bounce notice.
- Accuracy metrics: citation validity, statute confusion, fact fabrication, missing required sections, formatting compliance, adverse authority detection.
- Human review correction loop that feeds template/eval improvements.

### 2. Draft output still needs production document controls

Needed:

- Court-specific formatting profiles.
- Annexure/exhibit/index generation.
- Page numbering, cause title variants, affidavit/verifications, vakalat/supporting docs.
- Revision compare.
- Inline citation anchors from body to source panel.
- PDF export and final bundle export.
- Filing checklist per court/matter type.

### 3. Bench strategy governance is unresolved

The code currently avoids prediction language in several surfaces, while `docs/PRD_BENCH_STRATEGY_2026-04-26.md` later authorizes judge tendencies and predicted disposition. This is not a normal feature toggle. It changes legal, ethical, and reputational risk.

Decision needed:

- Option A: Evidence-only bench strategy. Safer. Shows cited bench history, no prediction.
- Option B: Predictive bench analytics. Riskier. Requires explicit disclaimers, sample-size thresholds, source links, audit, opt-in, and legal review.

Recommendation: keep V1 evidence-only. Add "advocacy support" by surfacing supportive and adverse authorities, not by predicting judges.

### 4. Prompt-injection and source poisoning need product-visible controls

Tests and service comments mention injection risks, but users need visible trust signals.

Needed:

- "Source used / source ignored" panel for each AI output.
- Warnings when a source contains suspicious instructions.
- Citation coverage meter.
- "Generated from these documents only" mode.
- Admin policy: disable external corpus, disable tenant documents, or require private inference.

## Matter Management Gaps

### Missing law-firm essentials

- Conflict checks.
- Engagement letter / fee arrangement.
- Retainer/advance/trust account handling.
- Matter templates by practice area.
- Task templates and filing checklists.
- Matter phases/stages with automation.
- Document request lists.
- Internal notes with privilege/work-product flags.
- Supervisory review and delegation.
- Bulk import from spreadsheets or existing practice systems.

### Missing GC essentials

- Business-unit intake portal.
- Risk/exposure values.
- Reserves and probable outcome categories.
- Matter budget and forecast.
- Status report cadence.
- Board/executive report exports.
- Legal request taxonomy and SLA.

## Hearing, Court, And Litigation Ops Gaps

Strong direction, but incomplete.

Needed:

- Court adapter health dashboard.
- Cause-list sync per court with retry/error transparency.
- Listing history timeline.
- Automatic next-hearing extraction from orders.
- Hearing prep packet export.
- Post-hearing minute capture and automatic task creation across all hearing types.
- Filing deadline calculators per statute/procedure.
- Court fee/stamp/limitation calculators.
- Tribunal/lower court coverage strategy.

## Contracts And CLM Gaps

Current contract module is a repository plus extraction/playbook/redline view. It is not yet CLM.

Needed for GC competitiveness:

- Contract request intake.
- Template selection and clause library.
- Approval workflows by value/risk/business unit.
- Negotiation workspace.
- Redline accept/reject and clean document generation.
- E-signature integration.
- Obligation owners, reminders, escalation, and completion evidence.
- Renewal/termination alerts.
- Contract analytics: cycle time, bottlenecks, risk by clause, counterparty exposure.
- Bulk smart import and data validation.
- Custom AI properties/playbooks trained per customer.

## Outside Counsel And Spend Gaps

Current outside counsel support is a good start but below GC spend-management expectations.

Needed:

- Rate cards by firm/timekeeper/year.
- Timekeeper approval and rate increase workflow.
- Budget phases, accruals, and variance alerts.
- Billing guidelines.
- Invoice line-item review and reductions.
- E-billing formats and exports.
- RFP / matter pricing workflow.
- Firm scorecards: responsiveness, budget adherence, quality, outcome notes, diversity, practice fit.
- Benchmarks from internal history at minimum; external benchmarks later.
- Conflict and panel compliance checks.

## Billing And Finance Gaps

Law firms and solos need more than invoice creation.

Needed:

- WIP dashboard.
- Realization and collection reports.
- Aging.
- Trust/advance/retainer ledger.
- Expense tracking and reimbursements.
- Write-offs and discounts workflow.
- GST/TDS reporting.
- Accounting exports/integrations.
- Payment reminders.
- Receipt generation.
- Matter profitability by lawyer/team/client.

## Client, Contact, And CRM Gaps

Current clients module exists, but law firms need CRM and relationship memory.

Needed:

- Contacts beyond clients: opposing counsel, witnesses, vendors, experts, judges/court staff, business stakeholders.
- Relationship graph.
- Communication timeline across matters.
- Client onboarding/KYC workflow depth.
- Conflict database.
- Source of lead/referral.
- Client status reports.
- Secure document requests and approvals.

## Security, Compliance, And Enterprise Trust Gaps

Strong backend work exists, but buyer-facing enterprise controls are still incomplete.

Needed before serious enterprise/legal-department sale:

- SAML/OIDC SSO.
- MFA.
- SCIM or at least user lifecycle import/deactivate.
- Configurable retention policies.
- Legal hold and export/deletion workflows.
- Admin support-access approval and audit.
- IP allowlisting.
- Data residency story.
- DLP/malware quarantine UI.
- SOC 2 / ISO 27001 roadmap and evidence pack.
- DPDP Act posture mapped to product controls.
- Model/data processing terms.
- Private inference / no-training guarantee expressed contractually and in admin settings.

## Architecture And Operations Gaps

### 1. Durable orchestration

Temporal is still a declared target. Until durable orchestration exists, long-running AI, OCR, notifications, audit exports, corpus jobs, and retries will remain harder to reason about.

Needed:

- Temporal or equivalent durable workflow runtime.
- Idempotent activities for OCR, ingestion, email, reminders, exports, AI batch enrichment.
- Operator dashboard for failed jobs and retries.

### 2. Observability

Needed:

- End-to-end trace IDs from web -> API -> worker -> LLM provider.
- Per-tenant AI spend and latency dashboards.
- Retrieval quality dashboards.
- Job queue health.
- Alerting for ingestion failures, webhook failures, reminder failures, and provider outages.

### 3. Data quality gates

Needed:

- Corpus quality score by source.
- OCR-garbage rejection and review queue.
- Metadata completeness thresholds.
- Citation graph coverage.
- Judge/bench resolution confidence dashboard.
- Statute source provenance dashboard.

## Testing Gaps

The test culture is good, but not yet enough to replace manual QA.

Known gaps from repo docs and static inspection:

- Page coverage waivers still exist in `apps/web/app/__page-coverage-matrix.test.ts`.
- `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md` still marks API route matrix and page-level UI coverage as partial.
- Provider-gated tests can still skip important live paths unless release mode is enforced.
- AI quality needs workflow-level goldens, not just route/unit tests.
- Mobile and keyboard tests need to cover high-value pages, not just smoke surfaces.

Needed:

- Route-operation coverage ledger: happy, validation, 401, 403, tenant isolation, audit, rate limit, idempotency.
- Page-level tests for every app route.
- Playwright journeys per persona.
- Golden legal drafting evals run on every model/prompt change.
- Red-team suite for prompt injection and source poisoning.
- Production smoke suite per release.

## Positioning Gaps

### Current positioning

"Matter-native legal operating system for Indian law firms and corporate legal teams."

This is directionally good, but too broad for the current product.

### Recommended wedge

Own this first:

"India-first litigation workspace for firms and GCs: matter cockpit, court diary, cited drafting, hearing prep, and outside-counsel collaboration."

Then expand:

1. Litigation OS for India.
2. Legal ops layer for GCs with litigation/outside-counsel spend.
3. Contract intelligence/CLM only after the litigation wedge is loved.

### What not to lead with yet

- "Best legal OS" without proof.
- "AI predicts bench outcomes" unless governance is resolved.
- "Full CLM" until lifecycle workflow exists.
- "Enterprise-ready" until SSO/MFA/retention/support controls are buyer-visible.

## Recommended Roadmap

### Phase 1: Win The Litigation Daily Workflow

Goal: make a litigator use CaseOps every day.

Must ship:

- Matter command center with Today/Next Action.
- Deep court diary and hearing workflow.
- Drafting finalization: PDF, revision diff, citation anchors, court formatting.
- Research quality: filters, treatment warnings, matter notebook, insert-to-draft.
- Conflict check, engagement, task templates.
- Mobile hearing mode.

Exit criteria:

- A lawyer can open a matter, ingest docs, research, draft, prepare hearing, record outcome, and bill without leaving CaseOps except for court filing.

### Phase 2: Build The Content Moat

Goal: earn trust against the established Indian legal research incumbents.

Must ship:

- Deep coverage for selected courts and years.
- Daily updates.
- Good-law/treatment signal.
- Metadata/citation graph completeness.
- Coverage confidence UI.
- Corpus quality dashboard.

Exit criteria:

- For the chosen launch jurisdictions, users stop checking another research system for routine drafting support.

### Phase 3: Close GC Spend And Outside Counsel

Goal: make GCs care.

Must ship:

- Matter budgets, accruals, forecast, exposure.
- Rate cards/timekeepers.
- Billing guidelines and invoice review.
- RFP/matter pricing workflow.
- Outside counsel scorecards.
- Executive spend dashboards.

Exit criteria:

- A GC can defend outside-counsel spend decisions from CaseOps reports.

### Phase 4: Enterprise Trust Pack

Goal: remove buyer security blockers.

Must ship:

- SSO/MFA.
- Retention/legal hold/export/deletion.
- Admin support access controls.
- Security/compliance evidence pack.
- Data residency/private inference story.
- Observability and incident runbooks.

Exit criteria:

- Enterprise pilots do not stall in security review.

### Phase 5: CLM Only If Resourced

Goal: avoid shallow CLM.

Must ship:

- Contract request intake, approvals, negotiation, e-sign, obligation management, analytics.
- Otherwise position contract module as "contract intelligence inside the legal workspace," not full CLM.

## Suggested Product Metrics

| Area | Metric |
| --- | --- |
| Activation | Time from workspace creation to first matter with uploaded docs and generated draft. |
| Litigation workflow | % active matters with next hearing, open tasks, and latest order populated. |
| Draft trust | Citation verification rate, fact-placeholder count, adverse-treatment warning rate. |
| Research | Search success rate, save-to-matter rate, insert-to-draft rate. |
| Hearing prep | Hearing pack generated/reviewed before hearing, post-hearing outcome captured. |
| GC ops | % matters with budget, outside counsel assignment, and monthly status. |
| Spend | Budget variance, invoice review savings, aging, realization. |
| AI safety | Refusal rate, hallucination defects per 100 drafts, prompt-injection blocked count. |
| Reliability | P95 page/API latency, worker failure rate, provider outage impact. |

## Release Blockers Before "Best For Law Firms"

- Deep, fast matter cockpit.
- Court diary and deadlines that lawyers trust.
- Research treatment/good-law basics.
- Drafting finalization and court-format output.
- Conflict/engagement workflow.
- Billing WIP/aging/realization basics.
- Mobile hearing mode.
- Page/test waiver burn-down for core app routes.

## Release Blockers Before "Best For Solo Lawyers"

- Guided simplified product lane.
- Affordable research/corpus proposition.
- UPI/payment reminder/accountant export flow.
- Phone-first hearing diary and notes.
- Template-first drafting with fewer decisions.
- Sample matter/onboarding.

## Release Blockers Before "Best For General Counsels"

- Business intake portal with SLAs/routing.
- Matter risk/exposure/budget/status reporting.
- Outside counsel rate cards, invoice review, budgets, scorecards.
- Contract lifecycle depth or narrower contract-intelligence positioning.
- SSO/MFA/retention/security pack.
- Executive dashboards.

## Brutal Prioritization

If resources are constrained, do this:

1. Stop expanding module count.
2. Pick litigation-heavy Indian law firms as the first ICP.
3. Make matters, research, drafting, hearing prep, and billing excellent for that ICP.
4. Treat GC and CLM as later expansions unless a paying pilot demands them.
5. Make every AI output show source coverage, limitations, and next review action.
6. Invest in corpus quality as product, not infrastructure.

## Evidence Reviewed

Local repo evidence:

- `README.md`
- `docs/PRD.md`
- `docs/architecture.md`
- `docs/WORK_TO_BE_DONE.md`
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
- `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md`
- `docs/PRD_BENCH_STRATEGY_2026-04-26.md`
- `docs/PRD_BENCH_MAPPING_2026-04-25.md`
- `apps/api/src/caseops_api/db/models.py`
- `apps/api/src/caseops_api/api/router.py`
- `apps/api/src/caseops_api/api/routes/*.py`
- `apps/api/src/caseops_api/services/*.py`
- `apps/web/app/app/**/page.tsx`
- `apps/web/components/**`
- `apps/web/lib/capabilities.ts`
- `apps/web/app/__page-coverage-matrix.test.ts`

Static inspection highlights:

- Largest route modules: `matters.py` 1481 lines, `portal.py` 871, `courts.py` 591, `statutes.py` 448.
- Largest service modules: `matters.py` 1546 lines, `drafting.py` 1187, `court_sync_sources.py` 1123, `authorities.py` 953, `corpus_ingest.py` 950, `llm.py` 943.
- Largest pages: `guide/page.tsx` 864 lines, `law-firms/page.tsx` 854, `intake/page.tsx` 747, `contracts/[id]/page.tsx` 736.
- Page coverage matrix still contains explicit allowed-untested route waivers.

External benchmark sources:

- Indian legal research platform (AI tier) — vendor documentation
- Indian legal research platform — vendor documentation
- Practice-management platform feature list — vendor documentation
- Enterprise legal-spend / outside-counsel management platform — vendor documentation
- Legal AI assistant platform — vendor documentation
- Contract lifecycle management AI platform — vendor documentation
- Legal AI platform for law firms — vendor documentation

