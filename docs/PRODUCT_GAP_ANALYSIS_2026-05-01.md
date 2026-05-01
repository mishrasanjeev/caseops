# CaseOps Brutal Product Gap Analysis - 2026-05-01

## Executive Verdict

CaseOps has the bones of a serious legal operating system, but it is not yet "best" for law firms, solo lawyers, or general counsels. The product is ambitious, broad, and technically active, but the current evidence shows a gap between release messaging and production-grade legal usefulness.

The blunt conclusion:

- CaseOps is strongest as an India-first litigation and matter operations platform.
- It is weakest where buyers will compare it to category leaders: authoritative research, drafting quality, daily workflow ergonomics, enterprise identity, outside counsel spend control, and full contract lifecycle management.
- The product currently tries to serve three demanding buyer groups at once. That creates breadth, but it dilutes the proof needed to win any one segment decisively.
- The May 1 release notes claim a feature-complete drafting studio, but the current drafting quality eval artifact reports `0.0/5` against a `4.8/5` target. That is the most important credibility gap in the repo right now.

If the goal is to be the best product for law firms, solo lawyers, and general counsels, CaseOps needs to become less impressed with feature count and more obsessed with verifiable daily outcomes:

- Fewer missed dates.
- Faster first drafts that survive lawyer review.
- Reliable research with treatment signals.
- Clear matter status without manual chasing.
- Real conflict, engagement, billing, and spend controls.
- Enterprise-grade access, audit, and data protection.

## Current Grade

| Area | Current Grade | Why |
| --- | --- | --- |
| Law firm readiness | C+ | Good matter/court/drafting foundations, but research authority, workflow depth, engagement, billing, and review controls are not yet strong enough. |
| Solo lawyer readiness | C | Too much setup and too much surface area. Solos need speed, reminders, templates, payments, and filing-ready output with minimal configuration. |
| General counsel readiness | C- | Matter visibility and portals exist, but spend, outside counsel governance, CLM, risk reporting, and integrations are shallow. |
| AI trust | D+ | The product has audit architecture, but current drafting eval evidence says quality is failing. |
| Enterprise readiness | C | RBAC/audit patterns exist, but SSO, SCIM, MFA enforcement, tenant policy controls, retention, and compliance packs are incomplete. |
| Product focus | C- | The product spans litigation, research, drafting, CLM, OC management, portals, marketing, and admin. The center of gravity is still unclear. |
| Market differentiation | B- | India litigation plus matter-native AI could be differentiated, but only if content, workflow, and trust become much deeper. |

## Evidence Reviewed

Local repo evidence:

- `docs/PRODUCT_GAP_ANALYSIS_2026-04-30.md`
- `docs/STRICT_PRODUCT_GAPS_2026-04-30.md`
- `docs/RELEASE_NOTES_2026-05-01.md`
- `docs/EVAL_DRAFTING_QUALITY.md`
- `docs/eval_artifacts/drafting_quality.json`
- Web app pages under `apps/web/app`
- Backend services under `services`
- API routes under `routes`
- Capability definitions under `apps/web/lib/capabilities.ts`

External benchmark sources reviewed:

- SCC Online AI Pro: https://www.scconline.com/ai-pro
- Manupatra legal research: https://www.manupatra.ai/legal-research
- Clio features: https://www.clio.com/features/
- Thomson Reuters Legal Tracker outside counsel spend: https://legal.thomsonreuters.com/en/legal/financial-management/outside-counsel-spend
- Thomson Reuters CoCounsel Legal: https://legal.thomsonreuters.com/en/products/cocounsel-legal
- Lexis+ AI: https://www.lexisnexis.com/en-us/products/lexis-plus-ai.page
- Ironclad AI overview: https://support.ironcladapp.com/hc/en-us/articles/12947738534935-Ironclad-AI-Overview
- Harvey platform: https://www.harvey.ai/platform

## What Changed Since The 2026-04-30 Gap Report

The previous report was directionally correct, but the repo has changed. The gap analysis must be stricter and more current.

### Positive Movement

- Conflict checks are no longer purely missing. The strict ledger identifies a partial implementation with `MatterConflictCheck`, a service, routes, capabilities, UI, and tests.
- The May 1 release notes describe a much broader drafting studio with 20 templates, court-format PDFs, filing ZIP bundles, revision diff, pre-filing checklists, solo mode, and template governance.
- There is a live drafting quality harness and artifact, which is the right operating discipline.
- The product has clearly moved toward matter-native AI rather than generic chat.

### Negative Movement

- The drafting release claim is not supported by the eval artifact. The artifact says:
  - Overall score: `0.0/5`
  - Target: `4.8/5`
  - Meets target: `false`
  - Bail template: `0.0/5`
  - Writ petition template: `0.0/5`
  - Citations found: `0`
  - Required structure found: empty
- This creates an immediate product trust problem. A legal drafting product cannot call itself feature-complete while its current quality gate says zero.
- The roadmap gaps in the May 1 release notes are still the gaps that matter commercially:
  - Research treatment and good-law signal.
  - GC spend depth.
  - CLM lifecycle.
  - Enterprise identity.
  - Pricing and packaging entitlement enforcement.

### Codebase Shape Signals

Large modules are not automatically bad, but they reveal product gravity and risk:

- `routes/matters.py`: 1785 lines.
- `services/matters.py`: 1546 lines.
- `services/drafting.py`: 1293 lines.
- `services/court_sync_sources.py`: 1123 lines.
- `services/authorities.py`: 1003 lines.
- `services/corpus_ingest.py`: 950 lines.
- `services/llm.py`: 943 lines.
- `apps/web/app/guide/page.tsx`: 864 lines.
- `apps/web/app/law-firms/page.tsx`: 854 lines.
- `apps/web/app/app/intake/page.tsx`: 747 lines.
- `apps/web/app/app/contracts/[id]/page.tsx`: 736 lines.

The product is already broad enough that feature count is not the bottleneck. The bottleneck is depth, consistency, workflow quality, and proof.

## Definition Of "Best"

CaseOps cannot be "best" by having more screens than competitors. It needs to be best at the work its customers actually repeat every day.

### Best For Law Firms Means

- Every matter has an accurate status, next step, owner, risk, and deadline.
- Drafting output saves real associate time and is safe enough for senior review.
- Research is authoritative, citator-backed, and jurisdiction-aware.
- Conflicts, engagement letters, fee arrangements, billing, and collections are operationally complete.
- Partners can see matter health, team load, revenue leakage, and upcoming risk without chasing.
- Clients get useful visibility without exposing privileged internal work product.
- The platform integrates with email, calendar, document storage, accounting, e-sign, courts, and research sources.

### Best For Solo Lawyers Means

- The product starts useful on day one with almost no admin setup.
- Intake, conflict, engagement, fee quote, invoice, reminder, filing bundle, and client update are one flow.
- The UI is fast, mobile-friendly, and forgiving.
- Templates are jurisdiction-specific and filing-ready.
- Pricing is simple and aligned with cash flow.
- The product replaces spreadsheets, WhatsApp follow-ups, calendar hacks, and scattered folders.

### Best For General Counsels Means

- Every legal request is triaged, assigned, tracked, and reportable.
- Outside counsel spend is controlled through budgets, rate cards, billing guidelines, invoice review, and scorecards.
- Contract work moves from request to approval to signature to obligations.
- Leadership sees legal risk, spend, cycle time, and business bottlenecks.
- Enterprise identity, audit, retention, legal hold, and compliance posture are non-negotiable.
- The system connects to the business stack: email, Slack/Teams, CLM/e-sign, finance, HR, ticketing, and document systems.

## P0 Board-Level Gaps

These are the gaps that block a credible "best in class" claim.

| Priority | Gap | Current Evidence | Why It Matters | Required Outcome |
| --- | --- | --- | --- | --- |
| P0 | Drafting quality contradiction | Release notes say feature-complete; eval says `0.0/5`. | Legal drafting quality is a trust gate. A zero-score artifact makes product claims unsafe. | Drafting eval must pass at least `4.8/5` on representative templates before release claims stand. |
| P0 | Research good-law signal missing | May 1 notes list research treatment as open PG-006. | Lawyers will not trust citations without treatment, currency, and authority hierarchy. | Add treatment status, citing references, overruled/distinguished warnings, and authority rank. |
| P0 | Corpus moat not proven | Services exist, but market leaders advertise massive legal corpora and freshness. | Research/drafting quality depends on authoritative content. | Publish coverage matrix by jurisdiction, court, document type, update frequency, and source license. |
| P0 | GC spend management shallow | May 1 notes list rate cards, budgets, billing guidelines, and scorecards as open PG-007. | GCs buy measurable spend control, not only matter tracking. | Implement budgets, rate cards, invoice review, accruals, vendor scorecards, and spend analytics. |
| P0 | CLM lifecycle incomplete | May 1 notes list request -> approval -> e-sign -> obligations as open PG-008. | GCs compare to CLM platforms, not matter tools. | Either build a real CLM lane or explicitly defer CLM and integrate with incumbents. |
| P0 | Enterprise identity incomplete | SSO/SCIM/MFA appear in roadmap/copy, not as complete shipped control plane. | Enterprise legal teams require strong identity and provisioning. | SAML/OIDC SSO, MFA policy, SCIM, JIT provisioning, domain capture, session controls. |
| P0 | Pricing/entitlement enforcement missing | May 1 notes list PG-010 open. | The product cannot scale commercially without enforceable packaging. | Plan entitlements, seat limits, feature gates, usage metering, invoices, trials, and overage rules. |
| P0 | Durable workflow orchestration missing | README and strict ledger point to custom polling today and Temporal as target. | Legal workflows are deadline-sensitive and long-running. | Adopt durable orchestration for reminders, filings, court sync, ingestion, review, and escalations. |
| P0 | Daily command center missing | Product has many feature pages, but no obvious universal daily work cockpit. | Lawyers need "what must I do today?" more than another module. | Unified today view: hearings, deadlines, drafts, tasks, approvals, client updates, risks. |
| P0 | Trust/eval discipline incomplete | Drafting eval exists but fails. Test waivers appear in prior reports. | Legal AI without quality gates creates liability. | No release claims without passing evals, regression snapshots, and red-team checks. |
| P0 | Integrations too thin | Prior reports and repo references show future connectors and local platform scope. | Legal work lives in email, calendars, document stores, courts, finance, and e-sign. | Ship opinionated integrations for Microsoft 365/Google, Drive/SharePoint, e-sign, accounting, and court/source ingestion. |
| P0 | Onboarding/migration not solved | Broad product surface, no strong evidence of guided migration. | Switching cost is the largest adoption blocker. | Import matters, contacts, documents, calendars, invoices, contracts, and templates with guided cleanup. |
| P0 | Review workflow not lawyer-grade | Drafting exists, but senior review, privilege, redlines, approval gates, and filing readiness need more depth. | Firms need review discipline, not just generation. | Add reviewer assignment, issue threads, redline history, privilege labels, signoff, and filing bundle audit. |
| P0 | Bench/judge strategy governance risky | Prior reports flag predictive claims and governance contradictions. | Judge analytics can become legally and ethically sensitive fast. | Separate descriptive analytics from prediction, add disclaimers, provenance, confidence, and opt-in controls. |
| P0 | Product positioning too broad | Law firms, solos, and GCs have different buying triggers. | Broad positioning slows sales and confuses roadmap priority. | Pick one primary wedge and map the other personas to variants, not equal priorities. |

## Persona Gap Analysis

### Law Firms

Current strength:

- Matter-centric data model.
- Litigation/court/hearing orientation.
- Drafting studio direction.
- Conflict check partial implementation.
- Portals and communications surfaces.
- Audit and capability scaffolding.

Current gaps:

- Engagement letter and fee arrangement workflow remains missing in the strict ledger.
- Conflict workflow still needs intake gating, richer contact checks, waiver handling, partner approval, and emailable documentation.
- Research lacks incumbent-grade citator, treatment, source coverage, and authority confidence.
- Drafting quality is not proven; current eval says zero.
- Billing, realization, write-offs, WIP, collections, and partner dashboards are not clearly complete.
- No convincing firm-wide command center for partners, associates, paralegals, and admins.
- Intake is broad, but conversion from lead -> conflict -> engagement -> matter -> invoice is not yet a tight commercial workflow.
- Review, redline, signoff, and filing readiness need stronger legal operations depth.

What would make it best:

- A litigation matter cockpit that beats email/calendar/spreadsheets every day.
- Drafting that saves a measurable number of associate hours and passes formal legal QA.
- Research that lawyers trust enough to cite.
- End-to-end firm operations: intake, conflict, engagement, matter, court, draft, bill, collect, report.

### Solo Lawyers

Current strength:

- Solo mode is mentioned in May 1 release notes.
- Matter and drafting workflows could be very valuable for solo litigators.
- Client-facing portal patterns can reduce follow-up burden.

Current gaps:

- Too many modules for a solo user unless the product aggressively simplifies first-run experience.
- No evidence of a zero-setup "start a case in 10 minutes" flow.
- Engagement, fee quote, invoice, payment, and collections are not yet the spine.
- Mobile courtroom workflow is not clearly dominant.
- Solos need practical templates, not abstract AI claims.
- Solos will churn if the first draft, first reminder, first invoice, or first client update fails.

What would make it best:

- One guided flow: new client -> conflict -> fee quote -> engagement -> matter -> hearing reminders -> draft -> invoice -> payment.
- Opinionated jurisdiction templates.
- Lightweight pricing and no enterprise setup burden.
- Mobile-first hearing day experience.

### General Counsels

Current strength:

- Outside counsel portal concepts exist.
- Matter and risk visibility could be useful for in-house teams.
- Contracts surfaces exist.
- Admin/audit foundations are relevant.

Current gaps:

- Outside counsel spend management is not deep enough.
- CLM is not complete enough to compete with CLM systems.
- Legal request intake, triage, SLA, and business stakeholder collaboration need more depth.
- Enterprise identity and provisioning are not ready enough.
- Board/executive reporting is not yet the product's center.
- Integrations with finance, procurement, HR, Slack/Teams, e-sign, and document systems are underpowered.

What would make it best:

- A legal front door for the business.
- Matter and contract portfolio visibility.
- Outside counsel budget and invoice governance.
- Executive dashboards for risk, spend, cycle time, and business blockers.
- Enterprise-grade controls from day one.

## Market Benchmark Gap

### Legal Research Leaders

SCC Online AI Pro and Manupatra set a high bar on legal content, coverage, search, citations, and research confidence. They compete on corpus, court coverage, legal document types, citation graph, AI-assisted summaries, and research workflows.

CaseOps gap:

- CaseOps has research surfaces and authority services, but the repo does not prove incumbent-grade source coverage, citator depth, treatment analysis, or fresh legal updates.
- Without treatment signals, citation warnings, and source transparency, CaseOps research is a helpful assistant, not a research system of record.

Required bar:

- Coverage matrix by jurisdiction and court.
- Freshness SLA.
- Citation graph.
- Treatment labels.
- Authority ranking.
- Side-by-side source previews.
- Explainable AI summaries grounded in source text.

### Practice Management Leaders

Clio sets a broad practice management bar across intake, client management, calendars, documents, billing, payments, and communication.

CaseOps gap:

- CaseOps has several of these domains, but the lifecycle is not yet as commercially tight.
- The strongest law firm competitors sell operational completeness. CaseOps still has missing or partial engagement, billing, payment, and daily work loops.

Required bar:

- Intake-to-cash workflow.
- Billing and payments as first-class flows.
- Calendar and deadline reliability.
- Client communication system of record.
- Migration and onboarding.

### Legal AI Leaders

CoCounsel, Lexis+ AI, Harvey, and similar platforms compete on research, drafting, review, workflow automation, knowledge vaults, private workspaces, and enterprise controls.

CaseOps gap:

- CaseOps has matter-native context and drafting direction, but the current drafting eval failure blocks credibility.
- AI trust is not about having chat or generation. It is about proving that output is grounded, reviewable, auditable, and consistently useful.

Required bar:

- Passing legal drafting evals.
- Source-grounded outputs.
- Citations with treatment.
- Review workflows.
- Prompt/model/version audit.
- Private knowledge controls.
- Enterprise access and data isolation.

### CLM Leaders

Ironclad and related CLM products compete on contract intake, playbooks, approvals, AI extraction, negotiation, e-signature, obligation management, and analytics.

CaseOps gap:

- Contracts exist, but full lifecycle depth is not proven.
- A contracts detail page is not a CLM product.

Required bar:

- Request intake.
- Clause/playbook review.
- Approval routing.
- Redlining and negotiation.
- E-signature integration.
- Repository.
- Obligations.
- Renewal alerts.
- Contract analytics.

### Outside Counsel Spend Leaders

Thomson Reuters Legal Tracker and other legal operations platforms compete on e-billing, rate review, budgets, matter spend, invoice guidelines, vendor benchmarking, and outside counsel performance.

CaseOps gap:

- GC spend depth is explicitly open in the May 1 release notes.
- A portal without e-billing governance will not win legal operations buyers.

Required bar:

- Matter budgets.
- Rate cards.
- Billing guidelines.
- Invoice line-item review.
- Accruals.
- Forecasting.
- Vendor scorecards.
- Benchmarking.
- Savings and leakage analytics.

## Module-Level Gaps

### 1. Research And Authorities

Gaps:

- No complete good-law/citator workflow.
- No clear treatment status for authorities.
- No visible authority confidence score tied to court hierarchy and recency.
- No source coverage matrix.
- No strong user-facing freshness SLA.
- No research trail that can be exported into a memo or shared with reviewers.
- No obvious research-to-draft citation validation loop.

Why this is brutal:

- Legal research is not a side feature. If CaseOps wants to draft legal documents, research quality becomes part of drafting quality.
- Lawyers will reject AI drafts quickly if citations are stale, hallucinated, weak, or jurisdictionally wrong.

Required improvements:

- Add good-law badges: followed, distinguished, overruled, reversed, cited, criticized, pending appeal, unknown.
- Show "why this authority matters" with court level, date, jurisdiction, citation count, treatment, and issue match.
- Add citation validation inside drafting.
- Add research notebooks tied to matters.
- Add memo export with source list and pinpoint references.

### 2. Drafting Studio

Gaps:

- Current eval artifact says drafting quality is zero.
- Release notes claim feature completeness despite failed quality evidence.
- Template count is not enough; template correctness matters.
- The current evidence does not prove jurisdiction-specific pleading rules are enforced.
- There is no proof of robust citation insertion, pinpoint references, or authority treatment checks.
- Filing bundles are useful only if generated documents satisfy local filing requirements.

Why this is brutal:

- Drafting is one of the product's highest-value claims. It is also one of the highest-risk claims.
- A bad draft wastes lawyer time and damages trust faster than no draft.

Required improvements:

- Treat the failing eval as a release blocker.
- Expand eval scenarios beyond two templates.
- Score structure, facts, law, prayers/relief, citations, formatting, jurisdiction fit, filing readiness, and reviewer edits.
- Add regression snapshots for every template.
- Add senior-lawyer review workflow.
- Add document comparison against gold-standard exemplars.
- Add "cannot draft safely" states when required facts or authorities are missing.

### 3. Matter Management

Gaps:

- Matter routes and services are large, which increases maintenance risk.
- Matter work appears broad, but the user journey still needs a clear daily cockpit.
- Status, owner, next step, deadline, risk, documents, communications, bills, and client updates need to converge in one place.
- No evidence of strong matter health scoring or intervention logic.
- Cross-matter analytics for partners and GCs need depth.

Required improvements:

- Build a matter command center with next action, blocked items, due dates, risk, recent activity, and owner.
- Add matter health scoring based on stale activity, upcoming deadlines, overdue tasks, spend variance, missing documents, and unanswered client items.
- Add partner/GC portfolio views.
- Add matter templates by practice area.
- Add bulk updates and review queues.

### 4. Court And Hearing Operations

Gaps:

- Court sync is substantial in code size, but production reliability and source coverage are not visible.
- Hearing workflows need more than calendar entries.
- No clear offline/mobile hearing-day mode.
- No strong adjournment/order extraction workflow.
- No evidence of court-specific filing checklists beyond drafting release notes.

Required improvements:

- Hearing-day dashboard: cause list, courtroom, stage, counsel, documents, notes, last order, next ask.
- Court order ingestion and extraction.
- Deadline recalculation after orders.
- Client update generation after hearing.
- Offline/mobile access for courtrooms with poor connectivity.
- Court source monitoring with failures surfaced to admins.

### 5. Conflict Checks

Current state:

- Partial implementation exists.

Remaining gaps:

- Intake must be blocked or gated based on conflict status.
- Checks must include clients, counterparties, related parties, witnesses, directors, group entities, vendors, and prior matters.
- Conflict results need severity, explanation, source, reviewer, and disposition.
- Waivers need templating, approval, audit, and storage.
- Partner approval needs escalation and deadline.

Required improvements:

- Make conflict check mandatory for matter opening.
- Add entity normalization and fuzzy matching.
- Add related-party graph.
- Add waiver workflow.
- Add conflict report PDF/export.

### 6. Engagement And Fee Arrangements

Gaps:

- The strict ledger identifies engagement letter and fee arrangement as missing.
- This is a foundational practice management gap.
- Without engagement, billing, and collections, CaseOps does not own the commercial lifecycle.

Required improvements:

- Engagement templates by practice area and fee type.
- Fee arrangements: hourly, fixed fee, retainer, contingency/success, capped fee, milestone.
- E-signature integration.
- Retainer tracking.
- Matter opening blocked until engagement is signed or waived.
- Fee scope changes and supplemental engagement letters.

### 7. Billing, Payments, And Finance

Gaps:

- No evidence of complete timekeeping, invoicing, payment, tax, trust/retainer, write-off, WIP, and collection workflows.
- Law firms and solos will compare against practice management systems that already handle cash.
- GCs need invoice review and budget governance.

Required improvements:

- Time capture from calendar, tasks, documents, calls, and drafting.
- Invoice generation and approval.
- Payment links.
- Retainer ledger.
- WIP dashboard.
- Collections reminders.
- Budget vs actual.
- Invoice guideline review for GCs.

### 8. General Counsel Legal Front Door

Gaps:

- GC workflows need intake, triage, assignment, SLA, stakeholder updates, and reporting.
- Existing matter/portal surfaces are not enough.
- Legal request forms must map to business units, risk, urgency, contract/matter type, and approvals.

Required improvements:

- Business user legal request portal.
- Auto-triage by request type and risk.
- SLA and escalation policies.
- Legal capacity dashboard.
- Stakeholder-facing status.
- Executive reporting.

### 9. Outside Counsel Management

Gaps:

- Spend depth is explicitly open.
- OC portal without budgets, rate rules, invoice review, and scorecards will not satisfy legal operations teams.

Required improvements:

- Vendor profiles.
- Approved rate cards.
- Budget approval.
- Matter staffing plans.
- Invoice guideline enforcement.
- Accrual collection.
- Performance scorecards.
- Diversity and staffing metrics if relevant to target buyers.

### 10. Contract Lifecycle Management

Gaps:

- Contracts pages exist, but full CLM lifecycle is open.
- If CaseOps claims CLM, it will be compared against mature CLM products.
- If CaseOps does not claim CLM, it still needs contract matter support and integrations.

Required decision:

- Either build real CLM or position as legal matter operations with CLM integrations.

Required improvements if building:

- Contract request intake.
- Clause extraction.
- Playbook deviations.
- Approval matrix.
- Redlines and negotiation.
- E-signature.
- Repository search.
- Obligation tracking.
- Renewal and notice alerts.
- Contract analytics.

### 11. Client And Business Portals

Gaps:

- Portals exist, but the value proposition must move beyond visibility.
- Client portals need privilege-safe updates, document exchange, approvals, invoice/payment, and structured questions.
- GC/business portals need legal request intake and status.

Required improvements:

- Portal permission templates.
- Privilege/work-product controls.
- Secure document requests.
- Approval buttons.
- Comment threads tied to matter artifacts.
- Client update digest.
- Portal activity audit.

### 12. Communications

Gaps:

- Legal communication still lives in email, WhatsApp, Teams, Slack, and phone.
- Product needs to ingest, classify, summarize, and link communications to matters.
- Without this, CaseOps becomes another system lawyers must manually update.

Required improvements:

- Microsoft 365 and Google Workspace email/calendar integration.
- Matter-based email filing.
- Communication timeline.
- Client update generator.
- Inbound request classification.
- WhatsApp/Teams/Slack strategy based on target market.

### 13. Enterprise Identity And Administration

Gaps:

- SSO/SCIM/MFA are not complete enough as shipped capabilities.
- Enterprise admin must be more than user roles.
- Legal buyers need data controls and audit confidence.

Required improvements:

- SAML/OIDC SSO.
- SCIM provisioning.
- MFA policy.
- Domain verification.
- Session duration and IP/device controls.
- Role templates.
- Permission simulation.
- Audit log search/export.
- Data retention policies.
- Legal hold.
- Matter-level ethical walls.

### 14. Security, Privacy, And Compliance

Gaps:

- Legal products need explicit trust documentation.
- AI data usage, model routing, retention, and customer isolation must be transparent.
- The product should not rely on generic security claims.

Required improvements:

- Trust center.
- Data processing addendum.
- AI data handling statement.
- Model/provider routing disclosure.
- Encryption and key management documentation.
- Backup/DR posture.
- Incident response documentation.
- Pen test and vulnerability process.
- DPDP/GDPR-aware retention and deletion controls based on target markets.

### 15. AI Governance

Gaps:

- AI audit architecture exists, but governance must be visible in-product.
- Drafting eval failure shows process is not yet release-grade.
- Predictive or bench-related AI must be handled carefully.

Required improvements:

- AI output provenance.
- Source grounding.
- Model, prompt, template, and context version history.
- Confidence and limitation display.
- Human approval requirements.
- Red-team eval suite.
- Matter-specific AI policy controls.
- Admin controls for disabling high-risk AI features.

### 16. UX And Information Architecture

Gaps:

- The web app has many large pages and likely high cognitive load.
- Legal users need speed, density, and predictable daily flow.
- Product marketing surfaces may over-explain while app surfaces need sharper work execution.

Required improvements:

- One daily work cockpit per persona.
- Global search across matters, contacts, documents, authorities, contracts, invoices, and communications.
- Universal command palette.
- Saved views.
- Keyboard shortcuts for power users.
- Mobile hearing mode.
- Fewer disconnected dashboards.
- Clear empty states that move users to the next action.

### 17. Reporting And Analytics

Gaps:

- Buyers need executive-ready reporting, not only operational screens.
- Law firm partners need utilization, revenue, realization, deadlines, and matter risk.
- GCs need spend, cycle time, risk, vendor performance, and contract exposure.
- Solos need cash, upcoming hearings, stale clients, and work pipeline.

Required improvements:

- Persona-specific dashboards.
- Scheduled reports.
- Export to PDF/Excel.
- Metrics definitions.
- Benchmarking.
- Drill-down from metric to source matter/document/invoice.

### 18. Onboarding And Migration

Gaps:

- Broad legal systems fail when onboarding is too heavy.
- The repo evidence does not show a best-in-class migration engine.

Required improvements:

- CSV import for matters, contacts, tasks, invoices, and contracts.
- Document folder import.
- Email/calendar connection wizard.
- Duplicate detection and entity normalization.
- Template setup wizard.
- Practice-area starter packs.
- Guided first matter.

### 19. Reliability And Operations

Gaps:

- Custom polling exists where durable orchestration is needed.
- Court sync, reminders, ingestion, and AI jobs must be resilient.
- Legal deadlines make missed background work unacceptable.

Required improvements:

- Temporal or equivalent durable workflow engine.
- Job idempotency.
- Retry and dead-letter handling.
- Admin visibility into failed syncs/jobs.
- SLA monitoring.
- Backup and restore drills.
- Data reconciliation reports.

### 20. Testing And Quality Gates

Gaps:

- Current drafting eval fails.
- Prior reports mention test waivers and incomplete coverage.
- Legal workflow tests must cover more than happy paths.

Required improvements:

- Release-blocking AI eval thresholds.
- Golden matter fixtures.
- End-to-end tests for intake -> conflict -> engagement -> matter -> draft -> review -> filing/invoice.
- Court sync failure tests.
- Permission and portal leakage tests.
- Billing/spend calculation tests.
- Migration tests.
- Accessibility and mobile viewport tests.

## Brutal Product Strategy Recommendation

Do not try to be equally best for law firms, solo lawyers, and GCs at the same time.

The most defensible wedge is:

> India-first litigation operating system for law firms and serious litigators, with matter-native AI drafting, court operations, authoritative research support, and client collaboration.

This wedge is strongest because:

- The repo already has court, authority, matter, drafting, hearing, portal, and litigation surfaces.
- India litigation workflows are specialized enough to create differentiation.
- General practice management and generic CLM are crowded.
- A deep litigation product can later expand into GC litigation management and solo workflows.

Recommended sequencing:

1. Win litigation law firms first.
2. Package a simplified solo version from the same workflow.
3. Sell GCs on litigation/outside counsel visibility before claiming full legal operations or CLM dominance.

## What To Stop Doing

- Stop calling drafting feature-complete while the eval artifact says `0.0/5`.
- Stop treating template count as a quality proxy.
- Stop expanding surface area until the core workflows pass strict outcome tests.
- Stop positioning as all-in-one for every legal persona without proof.
- Stop using enterprise feature language unless SSO, SCIM, MFA, audit export, and policy controls are actually ready.
- Stop treating contracts as CLM unless request, approval, redline, e-sign, obligations, and renewal workflows exist.
- Stop treating research as solved without good-law signals.

## What To Build Next

### Next 14 Days

1. Make the drafting eval failure a release blocker.
2. Fix the two failing eval scenarios and add at least eight more representative legal drafting scenarios.
3. Add a visible "today" cockpit for litigation users.
4. Complete conflict check v2: intake gating, related parties, waiver, approval, export.
5. Start good-law MVP: treatment unknown/positive/negative with citation validation warnings.
6. Strip or qualify marketing/admin copy for features that are not truly shipped.
7. Create a source coverage matrix for research/court data.
8. Decide the wedge and update roadmap language accordingly.

### Next 30 Days

1. Engagement letter and fee arrangement workflow.
2. Draft review/signoff workflow.
3. Court/hearing day dashboard.
4. Client update digest.
5. Global search and command palette.
6. Billing basics for firms/solos: time, invoice, payment link, retainer.
7. Enterprise identity plan with implementation milestones.
8. Research notebook tied to matters.

### Next 60-90 Days

1. Durable workflow orchestration for reminders, court sync, ingestion, AI jobs, and escalations.
2. Outside counsel spend MVP: budgets, rate cards, invoice review, scorecards.
3. CLM decision: build real lifecycle or integrate with CLM vendors.
4. Email/calendar/document-store integrations.
5. Admin trust pack: audit export, retention, legal hold, SSO/SCIM/MFA.
6. Migration/import tools.
7. Executive dashboards by persona.

### Six-Month Bet

Build a provable litigation intelligence moat:

- Matter data.
- Court data.
- Authority treatment.
- Drafting quality.
- Hearing workflows.
- Client communications.
- Outcome/risk analytics with careful governance.

That is a stronger path than becoming a generic practice management clone, generic AI chat tool, or shallow CLM.

## Release Blockers Before "Best For Lawyers" Claims

These should block any external claim that the product is best-in-class:

- Drafting eval below target.
- No good-law/treatment signal.
- No engagement and fee arrangement workflow.
- No mandatory conflict gate.
- No enterprise identity for enterprise buyers.
- No spend controls for GC buyers.
- No durable workflow engine for legal deadlines.
- No source coverage/freshness matrix.
- No global search.
- No clear data retention/security/AI trust documentation.

## Suggested North Star Metrics

Law firms:

- Hours saved per draft that passes review.
- Percentage of matters with next action and deadline.
- Missed deadline count.
- Conflict check completion before matter opening.
- WIP to invoice cycle time.
- Client update response time.

Solo lawyers:

- Time from new lead to signed engagement.
- Time to first filing-ready draft.
- Paid invoice rate.
- Upcoming hearing reminder accuracy.
- Mobile task completion rate.

General counsels:

- Legal request cycle time.
- Outside counsel spend vs budget.
- Invoice guideline violations caught.
- Contract cycle time.
- Matter risk exposure.
- Vendor scorecard trend.

AI trust:

- Drafting eval score by template.
- Citation validation pass rate.
- Hallucinated citation rate.
- Reviewer edit distance.
- Source coverage by jurisdiction.
- AI output approval/rejection rate.

## Product Architecture Risks

### Risk 1: Matter And Drafting Complexity Concentration

Large route/service files suggest critical behavior may be concentrated in a few modules. This increases regression risk and slows feature work.

Recommendation:

- Extract cohesive services around matter lifecycle, deadlines, court sync, billing, conflict, drafting eval, and reporting.
- Add contract tests around module boundaries.

### Risk 2: Broad Surface Area Without Equivalent Quality Gates

The product spans many legal categories, but quality gates are uneven. Drafting has an eval artifact, but it currently fails. Other areas need similarly explicit gates.

Recommendation:

- Create product readiness gates for each category: research, drafting, court sync, billing, OC spend, CLM, identity, portals.
- Do not ship or market category claims without passing gates.

### Risk 3: AI Claims Outrunning Governance

AI features in legal products need conservative language, strong provenance, and human review. Bench or judge strategy features are especially sensitive.

Recommendation:

- Classify AI features by risk.
- Require human approval for high-risk outputs.
- Keep predictive analytics opt-in and carefully described.

### Risk 4: Enterprise Copy Before Enterprise Controls

Enterprise buyers will ask for SSO, SCIM, MFA, audit export, retention, DPA, incident response, and deployment architecture early.

Recommendation:

- Build an enterprise readiness checklist.
- Map each sales claim to actual shipped controls.

## Recommended Packaging

### Litigation Firm

Core:

- Matters.
- Court/hearing ops.
- Drafting.
- Research notebook.
- Conflict and engagement.
- Client portal.
- Billing.

Premium:

- Advanced AI drafting.
- Authority treatment.
- Partner analytics.
- Enterprise identity.
- Integrations.

### Solo Litigator

Core:

- Intake.
- Conflict.
- Engagement.
- Matter.
- Hearing reminders.
- Drafting templates.
- Invoice/payment.
- Client updates.

Keep this package simple. Solos should not see enterprise admin complexity.

### GC Litigation And OC Management

Core:

- Legal front door.
- Matter portfolio.
- Outside counsel portal.
- Budgets.
- Rate cards.
- Invoice review.
- Executive reporting.

Do not overclaim CLM until lifecycle depth is real.

## Brutal Final Take

CaseOps is not failing because it lacks ambition. It is at risk because it has too much ambition without enough proof at the trust boundaries.

The product should not compete by saying "we have AI, matters, contracts, courts, portals, and dashboards." Buyers have heard that pitch already. It should compete by proving:

- This draft passed legal quality gates.
- This citation is current and treated correctly.
- This matter will not miss a deadline.
- This conflict was checked before engagement.
- This invoice follows the billing guidelines.
- This client or business stakeholder got the right update without exposing privileged work.
- This legal team can run the day from one cockpit.

The current product can become excellent, but the fastest path is not adding more modules. The fastest path is turning the litigation workflow into something lawyers can trust under pressure.

