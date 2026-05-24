# PRD: ADP Law Firm Feedback Product Roadmap

Status: Planning PRD; no implementation in this document
Date: 2026-05-22
Source input: `C:\Users\mishr\Downloads\CaseOps.ai - ADP Law Firm Demo Feedback & Product Enhancement Document.pdf`
Customer: ADP Law Firm
Product: CaseOps.ai

This PRD converts ADP Law Firm's demo feedback into a complete product
roadmap and task backlog. It is intentionally implementation-neutral: it does
not authorize production writes, corpus jobs, external-provider jobs, data
cleanup, deployment changes, or legal-risky AI features. Each implementation
slice must still be reviewed against current code, tests, tenant-access
patterns, audit rules, model-governance rules, and deployment constraints.

## 1. Executive Summary

ADP's feedback shows that the buyer is not evaluating CaseOps as a simple case
management tool. They want an AI-powered legal operating system that combines:

- Matter management.
- Matter-file AI analysis.
- Goal-oriented recommendations.
- Email, platform communication, and internal notes in one matter timeline.
- Outlook/email/CaseOps calendar synchronization.
- Contract intelligence and playbook-based review.
- Client verification and governance.
- AI token and cost controls.
- Outside counsel spend tracking.
- Contextual legal research.
- Judgment monitoring.
- Law amendment and regulatory update monitoring.
- Judge and court analytics.
- Bulk matter/document onboarding.
- Google Drive integration.
- Automated drafting data extraction.
- Court-specific drafting formats.
- Storage quota and usage governance.

The feedback should be handled as an integrated platform roadmap, not a set of
isolated feature requests. The strongest product direction is:

- Make the matter graph the source of truth.
- Make every AI output source-backed, reviewable, auditable, and bounded.
- Use integrations to remove duplicate work, not to create hidden autonomous
  behavior.
- Build governance controls before high-volume AI and storage usage grows.
- Treat judge/court intelligence as descriptive and source-backed, not as
  judge shopping, legal advice, or outcome prediction.

## 2. Product Safety And Governance Guardrails

These guardrails apply to every ADP roadmap task.

### 2.1 Must Not Ship

- No legal advice as an automated final answer.
- No guaranteed outcomes.
- No success probability scoring.
- No "best judge", "most suitable judge", judge-shopping recommendation, or
  judge reputation score.
- No black-box outcome prediction.
- No unsupported favorable/unfavorable judge scoring.
- No emotion, biometric, psychological, mental-health, voice, stress, or
  lie-detection scoring.
- No AI answers from model memory where source grounding is required.
- No external notification delivery until durable notification delivery and
  retry are implemented and approved.
- No always-on provider synchronization until durable workflow/runtime proof is
  available for that provider class.
- No secret, token, connection string, OAuth credential, DB URL, full document
  text, OCR payload, or large source payload in logs, audit metadata, reports,
  tests, or docs.

### 2.2 Required Behavior

- Every substantive legal AI output must show source grounding or fail closed.
- Refusal is preferable to fabrication.
- English legal analysis remains the authoritative analysis unless a product
  decision later states otherwise.
- Local-language analysis must be labelled and must preserve legal meaning.
- All provider integrations must be opt-in, admin-configured, auditable, and
  fail closed when configuration is missing.
- All new routes must enforce tenant isolation, matter access, restricted
  matter access, team scoping, and ethical-wall rules where relevant.
- All AI calls must preserve ModelRun or equivalent usage lineage.
- Audit metadata must be redacted and must not include sensitive content.
- Generated OpenAPI clients must be refreshed when API schemas change.
- Feature releases must update the roadmap/status docs they affect.

## 3. Current Repo Truth To Respect

The following repo truth was used while shaping this PRD:

- Matter File Q&A exists as a matter-document scoped foundation with source
  snippets, refusal states, history/export, audit, and ModelRun lineage.
- G-116 inbound email import foundation exists for explicit matter-selected
  manual import. Provider/webhook/mailbox connector, thread grouping, intake
  routing, and runtime proof remain pending.
- WTD-12.3a bounded manual Outlook sync exists. Durable always-on sync remains
  gated on Temporal/durable workflow readiness.
- WTD-7.2 matter Tasks/Deadlines Cockpit foundation exists. Admin task
  templates per practice area remain pending.
- WTD-5.1a and WTD-5.1b durable workflow/Temporal foundations exist.
- WTD-5.1c live operator proof is NO-GO because required operator Temporal
  config is missing.
- WTD-5.3 durable notification delivery and retry remain pending.
- WTD-11.4 offline AI safety evaluation harness foundation exists. Broader
  per-workflow goldens and CI gating remain pending.
- AI token budgets, firm/user quotas, plan entitlements, and storage governance
  are not fully implemented.
- Staging runtime proof remains missing unless a later prompt specifically
  handles staging setup.

## 4. Full ADP Feedback Inventory

This section preserves every item from the customer feedback.

### 4.1 Matter Management: Matter File Q&A Multilingual Legal Analysis

Current customer observation:

- AI answers questions based on uploaded matter documents.

Customer wants:

- Analysis in the user's preferred local language.
- Translation must preserve exact legal meaning and intent.
- Translation must not alter legal interpretation.

Recommended customer enhancement:

- Add an "Analysis Language" selector.
- Generate original legal analysis in English.
- Generate local-language analysis.
- Use legal-grade translation with meaning-preservation validation.

Business value:

- Better adoption across regional legal teams.
- Easier review by local stakeholders and clients.

### 4.2 AI Recommendations Module

Current customer observation:

- Recommendations are generated based on matter status and uploaded documents.

Customer wants:

- Recommendations based on the user's objective, not only matter status.

Example objectives:

- How can I strengthen my case?
- How can I increase settlement chances?
- What should I do before filing?
- How can I reduce litigation risk?

Recommended contexts:

- Litigation Strategy.
- Settlement Strategy.
- Compliance Risk.
- Contract Risk.
- Case Preparation.
- Appeal Strategy.
- Custom Goal.

Business value:

- Recommendations become goal-oriented and more actionable.

### 4.3 Communication Module

Current customer observation:

- Platform communication and email communication are separate.

Customer wants:

- Email fully integrated with CaseOps communication.
- Discussion continuity across email and platform messages.

Recommended enhancement:

- Unified Communication Timeline.

Timeline should show:

- Platform chat.
- Email threads.
- Attachments.
- Internal notes.

Business value:

- Single source of truth.
- Better client communication tracking.
- Reduced information loss.

### 4.4 Calendar Integration

Customer wants calendar sync with:

- Microsoft Outlook.
- Email events.
- CaseOps Calendar.

Required two-way synchronization:

- Outlook to CaseOps: meetings, hearings, deadlines.
- CaseOps to Outlook: matter events, court dates, reminders.
- Email to Calendar: event extraction from email invitations.

Business value:

- Eliminates duplicate scheduling work.

### 4.5 Contract Intelligence Module

Current customer observation:

- Clause extraction is available.

Customer wants:

- Users should be able to select first party and second party/counterparty
  while extracting clauses.

Party-based examples:

- Obligations of Vendor.
- Obligations of Customer.
- Indemnity Clauses for Vendor.
- Indemnity Clauses for Customer.

Additional suggestion:

- Implement contract playbooks similar to market-leading platforms.

Business value:

- Faster contract review and risk analysis.

### 4.6 Client Verification And AI Usage Governance

Customer wants:

- Client verification handled more robustly.
- Firm administrators should control AI consumption.

Admin dashboard requirements:

- Allocate tokens to employees.
- Set monthly limits.
- Increase or decrease quota.
- Monitor token usage.
- View AI activity reports.

Business value:

- Better cost control and governance.

### 4.7 Outside Counsel Management

Customer wants better external counsel tracking.

For each case, track:

- Assigned counsel.
- Fee agreed.
- Amount paid.
- Amount pending.
- Payment status.
- Invoice tracking.

Business value:

- Improved legal spend management.

### 4.8 AI Legal Research

Current customer observation:

- Search is keyword-based.

Customer wants:

- Research should be context-driven rather than keyword-driven.

Example:

- Instead of only searching "Section 138", user asks:
  "Cheque bounced due to insufficient funds and notice was sent after 35 days."

Expected behavior:

- AI understands context.
- AI finds relevant judgments.

Business value:

- Higher research accuracy.

### 4.9 Judgment Monitoring

Customer wants:

- Daily monitoring of judgments.

Automated Judgment Notification Engine features:

- Daily judgment ingestion.
- Relevant judgment alerts.
- Practice-area filtering.
- Matter-specific recommendations.

Business value:

- Keeps legal teams updated automatically.

### 4.10 Law Amendments And Regulatory Updates

Customer wants notifications whenever:

- New law is introduced.
- Existing law is amended.
- Regulatory notification is released.

Recommended enhancement:

- Legal Change Monitoring System.

Notification filters:

- Practice area.
- Act.
- Jurisdiction.

Business value:

- Proactive compliance management.

### 4.11 Judge Intelligence And Analytics

Current customer observation:

- Judge intelligence shows total cases handled and practice areas.

Customer wants deeper judge profiling:

- Cases handled by practice area.
- Detailed case list.
- Judgment summaries.
- Decision patterns.
- Historical trends.

Customer analytics asks:

- Favorable judgments.
- Unfavorable judgments.
- Act-wise decisions.
- Court-wise decisions.
- Practice-area trends.

Customer AI recommendation asks:

- Best Court.
- Best Bench.
- Most Suitable Judge.

Customer suggested basis:

- Historical patterns.
- Similar matters.
- Success probabilities.

Business value:

- Major competitive differentiator.

CaseOps safety interpretation:

- Build descriptive, source-backed judge/court/bench analytics.
- Build issue-authority-treatment context.
- Build sample-size and confidence-band explanations.
- Do not build judge shopping, "most suitable judge", reputation scoring, or
  success probability outputs.

### 4.12 Bulk Matter Upload And Google Drive Integration

Customer context:

- Law firms often already manage documents in Google Drive.

Bulk Matter Upload requirements:

- Folder upload.
- ZIP upload.
- Excel mapping.

Google Drive Integration requirements:

- Connect Drive.
- Import folders.
- Auto-categorize documents.
- Sync updates.

Business value:

- Faster onboarding of firms.

### 4.13 Drafting Module Enhancements

Current customer observation:

- Users manually enter details.

Customer wants automatic extraction from uploaded documents:

- FIR Number.
- Accused Name.
- Complainant Name.
- Case Number.
- Police Station.
- Dates.
- Sections.

Additional requirement:

- Court-specific draft formats.

Examples:

- District Court.
- High Court.
- Supreme Court.
- Tribunal formats.

Business value:

- Significant reduction in drafting time.

### 4.14 Document Upload Limits And Storage Governance

Customer wants clarity regarding upload limits.

Storage model options:

- Option A: firm-based storage quota.
- Option B: user-based storage quota.

Additional controls:

- Storage analytics.
- Usage dashboard.
- Purchase additional storage.
- Archive old matters.

Business value:

- Transparent resource management.

### 4.15 Reference Platforms Mentioned

The customer referenced:

- MikeLegal.
- Iolite.
- Manupatra.
- SCC Online.

Product interpretation:

- MikeLegal and Iolite indicate expectations around practice management,
  workflows, client/matter operations, and legal team productivity.
- Manupatra and SCC Online indicate expectations around authoritative legal
  research, broad legal corpus coverage, citation trust, judgment discovery,
  and legal analytics.
- CaseOps should not copy surface features blindly. It should position itself
  as a matter-native legal operating system with source-grounded AI and strong
  operational governance.

### 4.16 Customer Priority Roadmap

Customer Phase 1, high priority:

1. Contextual AI Research.
2. Communication plus Email Integration.
3. Outlook Calendar Sync.
4. AI Token Governance.
5. Judge Intelligence Enhancements.

Customer Phase 2, medium priority:

1. Multilingual Legal Analysis.
2. Judgment Notifications.
3. Law Amendment Alerts.
4. Outside Counsel Management.
5. Google Drive Integration.

Customer Phase 3, advanced differentiators:

1. AI Court/Judge Recommendation Engine.
2. Contract Playbooks.
3. Deep Judge Analytics.
4. Predictive Litigation Intelligence.
5. Automated Draft Data Extraction.

CaseOps interpretation:

- Preserve the priority ordering, but reframe risky Phase 3 language into
  safe, evidence-backed, descriptive intelligence.
- Do not implement success probabilities or judge-shopping recommendations.
- Treat notification engines as in-app first until durable delivery is ready.

## 5. Current-State Mapping

| ADP ask | Current state | Gap | Safe implementation | Priority |
| --- | --- | --- | --- | --- |
| Multilingual Matter File Q&A | Matter File Q&A foundation exists | Language selector and meaning-preserving translation missing | English authoritative answer plus labelled local-language analysis | Phase 2 |
| Objective-based recommendations | Recommendation foundation exists | Objective selector and custom-goal shaping missing | Goal-oriented, source-backed action options for lawyer review | Phase 1 |
| Unified communication timeline | Manual inbound email foundation exists | Email thread grouping, platform/email/note timeline missing | Matter communication timeline with visibility labels | Phase 1 |
| Outlook calendar sync | Bounded manual Outlook sync exists | Two-way durable sync and email event extraction incomplete | Bounded manual sync plus conflict review until Temporal/delivery is ready | Phase 1/4 |
| Party-based clause extraction | Contract extraction exists | Party perspective missing | Party/alias-aware source-cited extraction | Phase 3 |
| Contract playbooks | Contract playbook-like surfaces exist in some docs/UI | Tenant-admin playbook lifecycle and comparison depth missing | Admin-managed playbooks with matched/missing/deviation results | Phase 3 |
| Client verification | Portal/KYC foundations exist | Robust verification workflow needs definition | Matter/client verification statuses, reviewer workflow, audit | Phase 2 |
| AI token governance | ModelRun usage exists | Quota allocation, hard caps, reporting missing | Admin AI usage budgets and quota enforcement | Phase 1 |
| Outside counsel tracking | Outside counsel foundations exist | Fee/payment/invoice tracking depth missing | Matter-level counsel spend ledger | Phase 2 |
| Contextual legal research | Corpus/retrieval foundations exist | Natural-language fact-pattern research UX and planner missing | Context-to-issues/statutes/authorities with source-backed results | Phase 1 |
| Judgment monitoring | Corpus ingestion exists operationally | User-facing monitoring, saved alerts, digest preview missing | In-app judgment alert center first; delivery later | Phase 2/4 |
| Law amendment alerts | Statute model foundation exists | Amendment/regulatory monitoring missing | Source-backed legal-change watchlist and in-app alerts | Phase 2/4 |
| Deep judge analytics | Judge catalog/analytics foundations exist | Deeper descriptive analytics missing | Source-backed court/bench/judge context explorer | Phase 1/3 |
| Best court/bench/judge | Not safe to implement literally | Outcome prediction and judge-shopping risk | Do not ship; replace with descriptive fit/context explanation | Governed alternative |
| Bulk matter upload | Upload foundations exist | ZIP/folder/Excel import workflow missing | Dry-run import plan and validation queue | Phase 2 |
| Google Drive integration | Not complete | OAuth import/sync missing | Bounded manual Drive import first; durable sync later | Phase 2/4 |
| Draft data extraction | Drafting templates exist | Pre-fill extraction from uploaded docs incomplete | Source-linked extracted fact review queue | Phase 3 |
| Court-specific formats | Templates exist | Forum-specific layout/required-fields depth missing | Court-format profiles per draft type | Phase 3 |
| Storage governance | Upload caps exist | Firm/user quota dashboard and enforcement missing | Firm quota first, user policy later | Phase 1 |

## 6. Product Principles

- The matter graph is the system of record.
- Every document, email, calendar event, task, note, recommendation, draft,
  invoice, counsel assignment, and research result should attach to a matter
  when possible.
- AI accelerates review; it does not replace a lawyer.
- Source-backed intelligence is preferred over prediction.
- Integrations reduce duplicate work and preserve auditability.
- High-volume features require admin governance for cost, storage, and access.
- The product should degrade gracefully when external configuration is absent.
- The user should always know whether an item is user-created, imported,
  generated, source-backed, or pending review.

## 7. Personas

### 7.1 Managing Partner / Firm Owner

Needs:

- Firm-wide matter visibility.
- Legal spend and outside counsel tracking.
- AI and storage cost governance.
- Risk controls and auditability.

### 7.2 Litigation Partner

Needs:

- Source-backed research.
- Hearing, deadline, and court-date control.
- Judge/court context without unsafe prediction.
- Matter-specific recommendations and drafting support.

### 7.3 Associate / Junior Lawyer

Needs:

- Matter File Q&A.
- Draft pre-fill from documents.
- Contextual research.
- Task/deadline clarity.
- Communication history.

### 7.4 Contract / Corporate Lawyer

Needs:

- Party-based clause extraction.
- Playbook comparison.
- Obligation and risk tracking.
- Contract-specific recommendations.

### 7.5 Admin / Operations User

Needs:

- User, token, and storage controls.
- Import workflows.
- Provider integration status.
- Audit reports.

### 7.6 Client / External Stakeholder

Needs:

- Local-language review where appropriate.
- Clear status and communication continuity.
- Verification/KYC workflow.
- Secure document sharing.

## 8. Functional Requirements

### FR-01: Multilingual Matter File Q&A

Goal:

- Let users receive Matter File Q&A analysis in English and optionally in a
  selected local language without altering legal meaning.

Requirements:

- Add analysis language selector.
- Default language is English.
- If a local language is selected, return:
  - original English legal analysis
  - translated local-language analysis
  - source references/snippets
  - limitations/refusal state when applicable
- English remains the authoritative analysis.
- Local-language output is labelled as translation/interpretive aid.
- Translation must not remove, alter, or invent source citations.
- Unsupported language must fail closed.
- Low translation confidence must show warning and preserve English result.
- Audit selected language, output mode, status, and source count with redacted
  metadata.

Acceptance criteria:

- English-only behavior is unchanged.
- Local-language mode returns English plus local-language analysis.
- No-source and insufficient-evidence refusals remain refusals.
- Source IDs/snippets remain valid.
- Audit metadata has no full question, answer, or source payload.

### FR-02: Objective-Based AI Recommendations

Goal:

- Generate recommendations based on the user's selected objective, not only
  matter status.

Recommendation contexts:

- Litigation Strategy.
- Settlement Strategy.
- Compliance Risk.
- Contract Risk.
- Case Preparation.
- Appeal Strategy.
- Custom Goal.

Requirements:

- Add context selector to recommendation request.
- Custom goal is length-bounded and safety-filtered.
- Output sections:
  - source-backed observations
  - possible next actions for lawyer review
  - missing information
  - risk/uncertainty notes
  - source references
- Unsafe goals asking for guaranteed outcome, success probability, or judge
  shopping must be refused or reframed.
- Audit selected context and safe goal hash, not raw goal text if sensitive.

Acceptance criteria:

- Different contexts change recommendation framing.
- Custom goal works when safe.
- Outcome-prediction wording is blocked.
- Matter access and tenant isolation are enforced.

### FR-03: Unified Communication Timeline

Goal:

- Combine platform communication, imported email, attachments, and internal
  notes into one matter timeline.

Requirements:

- Matter timeline supports item types:
  - platform message
  - imported email
  - email thread
  - attachment event
  - internal note
  - client-visible note
  - outside-counsel-visible update
- Thread grouping uses provider message/thread IDs and headers when available.
- Manual inbound email import remains supported.
- Future provider connector must reuse the same data model.
- Internal notes are never visible to portal users.
- Timeline filters: all, email, platform, notes, attachments, internal only.
- Every item shows visibility, source, author/importer, timestamp, and linked
  attachments.
- Attachments use existing matter attachment storage and virus checks.

Acceptance criteria:

- Mixed platform/email/note timeline sorts chronologically.
- Email thread grouping works where metadata exists.
- Internal notes are hidden from client/outside-counsel portals.
- Cross-tenant, restricted, team, and ethical-wall denials are enforced.
- Audit metadata is redacted.

### FR-04: Calendar Integration

Goal:

- Improve Outlook, email-event, and CaseOps calendar interoperability without
  claiming durable automation before runtime support exists.

Requirements:

- Preserve bounded manual Outlook sync.
- Add clear status labels:
  - manual sync available
  - durable always-on sync pending Temporal/operator proof
  - notification delivery pending WTD-5.3
- Outlook to CaseOps imports:
  - meetings
  - hearings
  - deadlines
- CaseOps to Outlook exports:
  - matter events
  - court dates
  - reminders where reminder delivery is explicitly supported
- Email invitation extraction creates reviewable calendar candidates.
- Conflict handling uses a review queue; no silent overwrite.
- Idempotency uses provider event IDs.
- Provider config status returns missing names only.

Acceptance criteria:

- Manual sync imports and exports bounded event batches.
- Duplicate event IDs do not create duplicates.
- Changed events produce conflict/review states.
- Missing provider config fails closed.
- No hidden background sync is introduced.

### FR-05: Party-Based Contract Clause Extraction

Goal:

- Make contract extraction useful from a selected party perspective.

Requirements:

- User can identify:
  - first party
  - second party/counterparty
  - optional party aliases
  - user's represented party
- Extract by party:
  - obligations
  - indemnities
  - payment duties
  - notices
  - termination rights
  - liability caps
  - confidentiality obligations
  - dispute resolution duties
- Each extracted item links to source page/section/snippet.
- Ambiguous party references are flagged for review.
- User can switch party perspective without re-uploading.

Acceptance criteria:

- Same contract can show vendor view and customer view.
- Aliases are respected.
- Ambiguity is flagged.
- No source-less clause is accepted as extracted fact.

### FR-06: Contract Playbooks

Goal:

- Add tenant-managed playbook review for repeat contract types.

Requirements:

- Admin can create playbooks with:
  - contract type
  - jurisdiction
  - party perspective
  - expected clause position
  - fallback wording or guidance
  - severity
  - rationale
  - archived/active status
- Contract review compares extracted clauses to playbook.
- Result statuses:
  - matched
  - missing
  - deviation
  - needs review
- No automatic acceptance or redline application.
- Audit playbook changes and review runs.

Acceptance criteria:

- Tenant isolation for playbooks.
- Playbook comparison produces source-backed findings.
- Missing/deviation findings link to contract sources.
- Audit metadata avoids full contract payload.

### FR-07: Client Verification Workflow

Goal:

- Track client verification robustly at client and matter level.

Requirements:

- Verification statuses:
  - not required
  - required
  - requested
  - submitted
  - under review
  - verified
  - rejected
  - expired
- Track:
  - required documents
  - submitted documents
  - reviewer
  - reviewed at
  - rework reason
  - expiry date where applicable
- Portal upload should use existing secure attachment pipeline.
- Sensitive document details must not appear in audit metadata.

Acceptance criteria:

- Verification can be required for configured matter/client types.
- Client can submit documents through portal.
- Firm reviewer can approve/reject.
- Audit metadata is redacted.
- Matter access rules apply.

### FR-08: AI Token Governance

Goal:

- Give firm admins control over AI usage and cost.

Requirements:

- Admin can set:
  - firm monthly AI budget
  - user monthly token quota
  - feature-specific quota
  - model/purpose allowance where existing policy supports it
  - soft warning threshold
  - hard cap
- Admin can:
  - increase/decrease quota
  - view usage by user, matter, feature, model, date range
  - export AI activity report
  - grant emergency override with reason
- Enforcement must happen server-side before expensive AI work.
- Usage reporting should use ModelRun and existing AI policy data where
  possible.
- No prompt/answer payloads in dashboard or export.

Acceptance criteria:

- Under-quota request succeeds.
- Over-quota request is blocked before provider call.
- Admin quota update is audited.
- Usage rollup matches ModelRun records.
- Reports omit prompt/answer payload.

### FR-09: Outside Counsel Spend Tracking

Goal:

- Track external counsel assignment, fees, invoices, and payments per matter.

Requirements:

- For each matter, track:
  - assigned counsel
  - counsel profile/contact
  - fee agreed
  - fee type
  - invoices
  - amount paid
  - amount pending
  - payment status
  - due dates
  - notes
  - attachments
- Rollups:
  - spend by matter
  - spend by counsel
  - spend by practice area
  - pending invoices
  - overdue payments
- Keep performance metadata factual and operational only.
- Do not create counsel reputation scores.

Acceptance criteria:

- Counsel can be assigned to a matter.
- Fee agreement and invoices can be recorded.
- Pending amount is computed.
- Restricted/team/ethical-wall access is enforced.
- Audit metadata is redacted.

### FR-10: Contextual Legal Research

Goal:

- Let lawyers search by fact pattern and legal context, not just keywords.

Requirements:

- Natural-language research query.
- Query planner extracts:
  - facts
  - legal issues
  - likely statutes/sections
  - procedural posture
  - jurisdiction/court hints
- Retrieval combines:
  - semantic search
  - keyword/citation filters
  - statute filters
  - court/date filters
  - source quality/rerank signals
- Results show:
  - judgment title
  - court
  - date
  - citation/source
  - relevant snippet
  - why relevant
  - limitations
- The system must not invent authorities.
- If corpus coverage is weak, say so.

Acceptance criteria:

- Cheque-bounce fact-pattern query retrieves relevant source-backed results.
- Keyword query remains supported.
- Court/date/statute filters work.
- Invalid or unsupported context returns careful no-result/limited-result
  state.
- No public authority answer is generated from model memory.

### FR-11: Judgment Monitoring

Goal:

- Let users monitor newly available judgments and matter-relevant updates.

Requirements:

- Saved judgment alert rules:
  - practice area
  - court/jurisdiction
  - statute/section
  - parties/keywords
  - matter linkage
- In-app alert center for matches.
- Digest preview.
- Matter-specific recommendation candidate list.
- Delivery channels are pending WTD-5.3 unless explicitly implemented later.
- The feature must not trigger corpus ingest/backfill/embedding jobs.

Acceptance criteria:

- User can create/list/update alert rules.
- Existing ingested judgments can match rules.
- In-app alert appears with source and reason.
- No external notification is sent.
- No ingest job is triggered.

### FR-12: Law Amendment And Regulatory Update Monitoring

Goal:

- Track legal and regulatory changes relevant to a firm or matter.

Requirements:

- Track:
  - new law introduced
  - existing law amended
  - regulatory notification released
- Filters:
  - practice area
  - Act
  - jurisdiction
  - regulator/source
- Update item includes:
  - title
  - source
  - effective date
  - summary
  - affected Act/section
  - possible matter/contract relevance where source-backed
- In-app alert center first.
- External delivery waits for notification delivery foundation.

Acceptance criteria:

- Legal update rules can be created/listed/updated.
- Update item requires source/provenance.
- Matter/contract match explains why.
- No external notification is sent by default.

### FR-13: Safe Judge, Bench, And Court Analytics

Goal:

- Expand judge/court intelligence safely as source-backed descriptive
  analytics.

Requirements:

- Judge profile includes:
  - cases handled by practice area
  - detailed case list
  - judgment summaries
  - act-wise decisions
  - court-wise decisions
  - practice-area trends
  - historical trend charts
  - source links
  - data freshness
  - sample size
  - coverage limitations
- Matter-level context explorer may show:
  - comparable matters
  - issue treatment
  - authority treatment
  - supportive/adverse authority map
  - bench/court procedural tendencies where source-backed
- Forbid:
  - best judge
  - most suitable judge
  - success probability
  - judge reputation score
  - judge shopping
  - unsupported favorable/unfavorable labels
- Low sample size suppresses pattern claims.

Acceptance criteria:

- Judge analytics show source-backed case lists.
- Sample-size threshold controls trend claims.
- Forbidden wording scan passes.
- Outputs include limitation notes.
- No outcome prediction is emitted.

### FR-14: Bulk Matter Upload

Goal:

- Speed firm onboarding from existing document sets and spreadsheets.

Requirements:

- Upload modes:
  - ZIP upload
  - folder upload where browser supports it
  - Excel mapping
- Import flow:
  - upload
  - parse
  - mapping preview
  - validation
  - duplicate detection
  - dry-run import plan
  - commit only after user approval
  - row/file-level error report
- Document categorization:
  - pleadings
  - orders
  - evidence
  - notices
  - contracts
  - correspondence
  - other/needs review
- No corpus ingest/backfill/embedding jobs are part of this feature.

Acceptance criteria:

- Excel mapping creates draft import plan.
- ZIP/folder documents attach to intended draft matters.
- Invalid rows are reported.
- Duplicate matter detection works.
- Audit records summary only.

### FR-15: Google Drive Integration

Goal:

- Let firms import existing Google Drive matter folders.

Requirements:

- OAuth connection.
- Missing config returns names only, not values.
- User selects Drive folder.
- Files are imported into selected matter or import plan.
- Store provider file ID, version/hash, modified time, and import status.
- Auto-categorize documents into matter document categories.
- Manual bounded sync first.
- Durable background sync later, after Temporal/operator proof and sync policy.
- Disconnect/revoke supported.

Acceptance criteria:

- Missing OAuth config fails closed.
- Selected folder import creates matter attachments.
- Re-import is idempotent.
- Updated file detection works in manual sync.
- No autonomous background sweep is introduced.

### FR-16: Drafting Data Extraction And Court-Specific Formats

Goal:

- Reduce manual drafting inputs by extracting source-backed facts from
  uploaded documents and applying court-specific draft format rules.

Fields to extract:

- FIR number.
- Accused name.
- Complainant name.
- Case number.
- Police station.
- Dates.
- Sections.
- Parties.
- Court/forum.
- Limitation/deadline signals where source-backed.

Court formats:

- District Court.
- High Court.
- Supreme Court.
- Tribunal.

Requirements:

- Extracted fields appear in a review queue before draft generation.
- Each extracted field links to source document/snippet.
- Low-confidence fields require manual confirmation.
- User overrides are preserved.
- Court format controls required fields, headings, filing style, and template
  layout.
- No filing is submitted automatically.

Acceptance criteria:

- Criminal/FIR fixture pre-fills required fields.
- Low-confidence field is flagged.
- Court format changes draft structure.
- User override is respected.
- Source links are included.

### FR-17: Storage Governance

Goal:

- Make upload limits and storage usage transparent.

Assumption:

- Start with Option A, firm-based storage quota. User-based quota can be a
  later policy layer if product owner confirms it is needed.

Requirements:

- Firm storage quota.
- Optional warning threshold.
- Hard quota enforcement server-side.
- Admin dashboard:
  - total used
  - remaining quota
  - usage by matter
  - usage by uploader
  - usage by document type
  - largest matters/files
  - trend over time
  - archive candidates
- Upload page shows applicable limit and remaining quota.
- Purchase additional storage control can be a placeholder/configurable CTA.
- Archive old matters workflow foundation.

Acceptance criteria:

- Upload under quota succeeds.
- Upload over quota is blocked before storage write.
- Dashboard totals match attachment metadata.
- Tenant isolation enforced.
- Audit metadata is redacted.

## 9. Cross-Cutting Non-Functional Requirements

### 9.1 Security

- Tenant isolation on every query.
- Matter access checks before feature-specific logic.
- Restricted matter, team scoping, and ethical-wall enforcement.
- Provider credentials stored only through approved secret mechanisms.
- OAuth tokens encrypted or stored in approved secure storage, never audit.
- No sensitive payloads in logs.

### 9.2 Audit And Compliance

- Audit all admin changes, provider connections, imports, syncs, quota updates,
  playbook changes, verification decisions, and AI runs.
- Audit metadata must contain IDs, counts, hashes, statuses, and safe labels,
  not full content.
- Exports must be explicit and permissioned.

### 9.3 AI Governance

- ModelRun lineage for AI calls.
- Tenant AI policy respected.
- Quota check before expensive AI call.
- Source ID validation for generated claims.
- Unsafe wording checks for legal advice, outcome prediction, judge shopping,
  and sensitive scoring.
- AI eval harness should eventually include ADP workflows.

### 9.4 Data And Storage

- Attachment storage must preserve source keys, hashes, size, MIME type, and
  uploader/importer.
- Import features must be idempotent.
- Storage quota must be enforced server-side.
- Bulk import must support dry-run before commit.

### 9.5 Integration Reliability

- Missing provider config fails closed.
- Status endpoints report missing config names only.
- Sync operations must be bounded until durable workflows exist.
- Idempotency keys required for imported emails, calendar events, and Drive
  files.
- Conflict queues should replace silent overwrite.

### 9.6 UX

- Every generated/imported item must show provenance.
- Every risky or low-confidence AI output must show limitation state.
- Users should see whether a feature is manual sync, in-app alert, or durable
  automation.
- Admin dashboards should privilege summary, drilldown, and export.

## 10. Phased Roadmap

### Phase 0: PRD And Roadmap Alignment

Objective:

- Capture ADP feedback in repo and create a safe task backlog.

Deliverables:

- This PRD.
- Ledger/workplan references in a later docs-only PR if desired.
- No product code.

### Phase 1: High-Priority ADP Wins

Objective:

- Address the most commercially important daily-driver gaps.

Tasks:

- ADP-01 Storage Governance foundation.
- ADP-02 AI Token Governance foundation.
- ADP-03 Objective-Based Recommendations.
- ADP-04 Contextual Legal Research foundation.
- ADP-05 Unified Communication Timeline foundation.
- ADP-06 Safe Judge/Court Analytics expansion.
- ADP-07 Calendar Sync UX/status improvements around existing bounded Outlook
  sync.

### Phase 2: Onboarding And Collaboration

Objective:

- Improve firm onboarding, collaboration, and adoption.

Tasks:

- ADP-08 Multilingual Matter File Q&A.
- ADP-09 Outside Counsel Spend Tracking.
- ADP-10 Client Verification workflow.
- ADP-11 Bulk Matter Upload dry-run.
- ADP-12 Google Drive bounded manual import.

### Phase 3: Contract And Drafting Depth

Objective:

- Convert AI capability into document-work savings.

Tasks:

- ADP-13 Party-Based Contract Clause Extraction.
- ADP-14 Contract Playbook Admin and Compare.
- ADP-15 Drafting Data Extraction review queue.
- ADP-16 Court-Specific Draft Format profiles.

### Phase 4: Monitoring And Alerts

Objective:

- Add legal-change awareness without unsafe autonomous delivery.

Tasks:

- ADP-17 Judgment Monitoring in-app alert center.
- ADP-18 Law Amendment/Regulatory Update monitoring.
- ADP-19 Email invitation to calendar candidate extraction.

### Phase 5: Durable Automation After Temporal Proof

Objective:

- Convert bounded/manual sync and in-app alerts into reliable automation only
  after runtime prerequisites are met.

Prerequisites:

- WTD-5.1c live Temporal operator proof complete.
- WTD-5.3 notification delivery and retry complete.
- Provider-specific credentials and runbooks approved.

Tasks:

- ADP-20 Durable Outlook sync.
- ADP-21 Durable Google Drive sync.
- ADP-22 Durable email ingestion connector.
- ADP-23 Judgment/legal update external digests.
- ADP-24 Admin retry/dead-letter/replay UI.

## 11. Detailed Task Backlog

### ADP-00: PRD Only

Type: Documentation
Priority: P0
Dependencies: None

Scope:

- Add this PRD.
- Do not implement product code.
- Do not update deploy/release files.

Acceptance:

- Every ADP PDF item is represented.
- Unsafe asks are preserved but reframed safely.
- Tasks are divided into implementation-ready slices.

Verification:

- `git diff --check`

### ADP-01: Storage Governance Foundation

Type: Backend + Web
Priority: P1
Dependencies: Existing attachment metadata and upload limits
Status: Foundation implemented 2026-05-22; firm quota uses nullable
`companies.storage_quota_bytes`, where `null` means unlimited/no hard quota.

Scope:

- Firm-based storage quota.
- Admin usage dashboard.
- Server-side quota enforcement.
- Upload UI limit display.
- Archive-candidate reporting.

Out of scope:

- Billing/payment for additional storage.
- User-based quota unless confirmed.

Tests:

- Quota under/over limit.
- Tenant isolation.
- Dashboard aggregation.
- Audit redaction.

### ADP-02: AI Token Governance Foundation

Type: Backend + Web
Priority: P1
Dependencies: ModelRun, TenantAIPolicy
Status: Foundation implemented 2026-05-23; firm quota uses existing
`tenant_ai_policies.monthly_token_budget`, user quota uses nullable
`tenant_ai_policies.user_monthly_token_budget`, and `null` quota means
unlimited/no hard cap.

Scope:

- User/firm quota settings.
- Usage dashboard.
- Hard/soft limits.
- Quota enforcement before provider call on shared structured AI paths
  that pass tenant/session context.
- Activity report export remains a follow-up; the foundation exposes
  admin rollups by user, matter, purpose/model, and current month.

Out of scope:

- New provider contracts.
- Prompt/answer inspection dashboard.
- Billing/payment for additional tokens.

Follow-up:

- Direct provider-call paths and corpus/background title re-extraction
  need separate accounting before quota enforcement is broadened beyond
  shared structured product paths. ADP-02 does not run or modify corpus
  jobs.

Tests:

- Under quota succeeds.
- Over quota blocks.
- Admin update audit.
- ModelRun rollup accuracy.
- Cross-tenant isolation and no prompt/answer/source payload leakage.

### ADP-03: Objective-Based Recommendations

Type: Backend + Web
Priority: P1
Dependencies: Existing recommendations service
Status: Foundation implemented 2026-05-23; recommendation requests now accept
an optional objective context and bounded custom goal. Existing type-only
requests remain valid. Custom goals are safety-checked before provider calls
and audit metadata stores only hash/length/category, not raw goal text.

Scope:

- Add recommendation context selector.
- Add safe custom goal.
- Separate observations/actions/missing info/risks.
- Block outcome-prediction and judge-shopping requests.

Out of scope:

- Contextual legal research retrieval beyond the existing recommendation
  source pattern.
- Settlement probability, success probability, judge shopping, best
  court/bench/judge logic, or final legal advice.
- User-facing notification delivery.

Tests:

- Context affects output.
- Custom goal safety handling.
- Forbidden wording scan.
- Matter access enforcement.
- ADP-02 token quota blocks over-limit recommendation calls before provider
  invocation.

### ADP-04: Contextual Legal Research Foundation

Type: Backend + Web
Priority: P1
Dependencies: Authority corpus/retrieval, source validation
Status: Foundation implemented 2026-05-23; authority search now supports an
optional contextual mode that deterministically extracts bounded issue,
statute, fact, timing, posture, and jurisdiction hints, then queries existing
indexed authority records only. No LLM planner, corpus ingest, backfill, or
embedding job is required. Audit metadata stores hashes/counts/filter flags,
not raw fact patterns, snippets, judgment text, prompts, answers, or source
payloads.

Scope:

- Natural-language fact-pattern query.
- Query planner for issues/statutes/facts.
- Hybrid retrieval with filters.
- Source-backed relevance explanation.
- Weak corpus coverage state.

Out of scope:

- Running new corpus ingest/backfill jobs.
- Model-memory answers, legal advice, outcome prediction, success
  probability, judge reputation scoring, judge shopping, best judge, or most
  suitable judge logic.
- Judgment monitoring, law amendment alerts, and user-facing notification
  delivery.

Tests:

- Cheque-bounce contextual query.
- Keyword query compatibility.
- Filter behavior.
- No fabricated authorities.
- Redacted contextual search audit metadata.
- No ModelRun/provider call for deterministic contextual planning.

### ADP-05: Unified Communication Timeline Foundation

Type: Backend + Web
Priority: P1
Dependencies: Communications, manual inbound email import
Status: Foundation implemented 2026-05-23; matter communications now expose a
read-only unified timeline over existing platform communications, manual
imported emails, matter attachment references, and internal matter notes.
The foundation does not add mailbox sweep, provider sync, autonomous polling,
webhooks, notification delivery, or external email sending changes.

Scope:

- Unified matter timeline.
- Platform messages, imported email, attachments, internal notes.
- Thread grouping foundation using existing provider/message metadata.
- Visibility labels for internal, firm-only, client-visible,
  outside-counsel-visible, and imported-email items.

Out of scope:

- Provider mailbox sweep.
- External email sending changes.
- Gmail/Outlook provider sync, mailbox polling, user-facing notifications,
  and attachment/body payload duplication.

Tests:

- Timeline sort/filter.
- Thread grouping.
- Portal visibility denial for internal notes.
- Attachment references without payload duplication.
- Matter access, cross-tenant, restricted/team/ethical-wall denial.
- No autonomous mailbox sweep/provider connector surface.

### ADP-06: Safe Judge/Court Analytics Expansion

Type: Backend + Web
Priority: P1
Dependencies: Judge catalog, authority metadata

Status: Foundation implemented 2026-05-23; court and judge profiles now expose
read-only descriptive context analytics from existing authority metadata, with
source-backed case lists, bounded summaries, sample-size gating, and limitation
messages. No provider calls, corpus jobs, or predictive judge/court selection
features were added.

Scope:

- Descriptive judge profile expansion.
- Case list, practice areas, act-wise/court-wise trends.
- Source-backed summaries.
- Sample-size gates.
- Limitation notes.

Out of scope:

- Best judge.
- Most suitable judge.
- Success probability.
- Judge reputation score.

Tests:

- Low sample suppresses claims.
- Source links required.
- Forbidden wording scan.
- Tenant policy/audit where applicable.

### ADP-07: Calendar Sync Status And Conflict Foundation

Type: Backend + Web
Priority: P1
Dependencies: Existing bounded Outlook sync
Status: Foundation implemented 2026-05-23; calendar sync status now
distinguishes manual bounded Outlook sync from durable automation, reports
provider config names only, exposes review-only duplicate provider event
conflict candidates, and keeps email invitation candidates deferred to a
review queue without autonomous calendar creation.

Scope:

- Make manual vs durable status explicit.
- Event idempotency improvements.
- Conflict review model/UI.
- Email invitation candidate design if feasible without provider connector.

Out of scope:

- Always-on sync.
- External reminder delivery.

Tests:

- Missing config fail-closed.
- Duplicate event handling.
- Conflict queue.

### ADP-08: Multilingual Matter File Q&A

Type: Backend + Web
Priority: P2
Dependencies: Matter File Q&A, model governance
Status: Foundation implemented 2026-05-23; Matter File Q&A requests now accept
an allow-listed analysis language, preserve the English answer as authoritative,
return local-language analysis as a separate translation aid when safe, and
fail closed to English-only/refusal states without translating source evidence.

Scope:

- Analysis language selector.
- English plus local-language analysis.
- Translation warning/fail-closed state.
- Source preservation.

Tests:

- English default unchanged.
- Local-language mode.
- Refusal preservation.
- Audit redaction.

### ADP-09: Outside Counsel Spend Tracking

Type: Backend + Web
Priority: P2
Dependencies: Outside counsel foundations, billing/invoice models
Status: Foundation implemented 2026-05-24; existing outside-counsel
assignment/spend records now expose matter-level agreed/paid/pending rollups,
payment-status summaries, redacted spend create/update audit events, and
matter-access-filtered workspace data without payment processing or counsel
reputation scoring.

Scope:

- Matter counsel assignment financial fields.
- Fee agreed, paid, pending, status.
- Invoice tracking.
- Spend rollups.

Tests:

- Assignment and invoice flow.
- Pending calculation.
- Access gates.
- Audit redaction.

### ADP-10: Client Verification Workflow

Type: Backend + Web + Portal
Priority: P2
Dependencies: Portal, attachment storage
Status: Foundation implemented 2026-05-24; existing client KYC fields now
support the ADP verification status workflow, matter-scoped verification
rollups, attachment-reference linking, reviewer decisions, and redacted audit
events. Secure portal metadata submission remains compatible; full portal
verification-document upload is deferred until a dedicated client upload path
can reuse the attachment/virus-scan pipeline.

Scope:

- Verification statuses.
- Required document checklist.
- Portal submission.
- Reviewer approval/rejection.

Tests:

- Client submit.
- Firm review.
- Rework/reject state.
- Sensitive audit redaction.

### ADP-11: Bulk Matter Upload Dry-Run

Type: Backend + Web
Priority: P2
Dependencies: Matter/document creation, attachment pipeline
Status: Foundation implemented 2026-05-24; bulk matter import now supports a
dry-run-only planner for CSV, JSON, and XLSX matter mappings plus optional
folder/ZIP filename indexes. The planner validates required matter fields,
detects visible tenant-scoped duplicates, checks document filename references,
and records redacted audit summary counts only. Commit execution, persistent
import jobs, attachment storage, OCR, corpus processing, embeddings, and Google
Drive import remain deferred.

Scope:

- ZIP/folder/Excel mapping.
- Dry-run import plan.
- Validation queue.
- Duplicate detection.
- Commit only after approval.

Tests:

- Valid import plan.
- Invalid row errors.
- Duplicate detection.
- No corpus jobs.

### ADP-12: Google Drive Bounded Manual Import

Type: Backend + Web + Provider Integration
Priority: P2
Dependencies: Secure OAuth config, attachment pipeline
Status: Foundation implemented 2026-05-24; Google Drive provider config
status endpoint reports configured/missing config NAMES only (never values,
client secrets, or tokens) and fails closed when any env var is unset. A
matter-scoped manual Drive metadata dry-run endpoint validates user-supplied
file metadata, deterministically auto-categorizes by filename/MIME, rejects
unsafe filenames / unsupported MIME / oversize / duplicate provider_file_id,
and records a redacted audit summary. No external Google API call, OAuth
flow, token storage, attachment write, storage object, OCR/corpus job,
embedding, background sync, polling, webhook, or commit path is wired by
this slice. Durable Drive sync remains deferred to ADP-21.


Scope:

- Connect Drive.
- Select folder.
- Manual import.
- Provider ID idempotency.
- Auto-categorization.
- Disconnect/revoke.

Out of scope:

- Durable background sync.

Tests:

- Missing config fails closed.
- Import selected folder.
- Re-import idempotency.
- No secrets in logs/audit.

### ADP-13: Party-Based Contract Clause Extraction

Type: Backend + Web
Priority: P3
Dependencies: Contract extraction
Status: Foundation implemented 2026-05-24; new stateless
`POST /api/ai/contracts/{contract_id}/clauses/extract-by-party` accepts
first/second party names, aliases, and a represented-party perspective.
Returns categorized items (obligations, indemnities, payment, notices,
termination, liability cap, confidentiality, dispute resolution) split
into represented vs counterparty buckets. Every item is source-validated
against the uploaded contract text (whitespace-normalized, case-folded
substring match); items without a verifiable snippet are dropped and
counted. Ambiguous party assignments are surfaced separately and never
silently routed to the represented party. ADP-02 ModelRun token-
governance ledger applies. Existing `/clauses/extract` and
`/obligations/extract` endpoints are unchanged. Audit metadata stores
only perspective + alias counts + item counts + a sha256 hash of
canonical party metadata. No DB migration. ADP-14 contract playbook
admin remains deferred.

Scope:

- Party selection and aliases.
- Party-perspective extraction.
- Source-linked obligations/indemnities.
- Ambiguity flags.

Tests:

- Vendor/customer views.
- Alias support.
- Ambiguous party flag.
- Source validation.

### ADP-14: Contract Playbook Admin And Compare

Type: Backend + Web
Priority: P3
Dependencies: ADP-13 preferred
Status: Foundation implemented 2026-05-24; introduces tenant-scoped
`tenant_contract_playbooks` + `tenant_contract_playbook_rules` tables
and CRUD endpoints under `/api/contracts/tenant-playbooks`. Playbook
admin (create/update/archive) is gated by `contracts:manage_rules`;
read is gated by tenant membership. Compare endpoint
`POST /api/contracts/{contract_id}/tenant-playbook-compare` is
**deterministic** (no LLM) — for each active rule, it scans the
contract's existing `ContractClause` rows by `clause_type`, applies
the rule's optional `keyword_pattern` (case-insensitive substring),
and emits matched / missing / deviation / needs_review. Matched and
deviation findings link to a `ContractClause.id` and carry a bounded
280-char snippet. Missing findings carry no source. Needs_review
fires when the contract has zero extracted clauses (extraction
hasn't run yet). All write paths emit redacted audit events with
name-hashes + counts + booleans; no raw clause text, prompt, answer,
or contract payload. Existing per-contract `ContractPlaybookRule`
table and LLM-backed `compare_playbook` remain unchanged. Web adds a
compact "Compare against tenant playbook" panel in the contract
Clauses tab. No ADP-15 work.

Scope:

- Tenant playbook CRUD.
- Clause expectation rules.
- Compare contract to playbook.
- Matched/missing/deviation/needs-review statuses.

Tests:

- Tenant isolation.
- Playbook compare.
- Deviation source links.
- Audit redaction.

### ADP-15: Drafting Data Extraction Review Queue

Type: Backend + Web
Priority: P3
Dependencies: Matter File Q&A/document extraction, drafting
Status: In progress — deterministic foundation implemented on branch
`codex/adp15-drafting-data-extraction-review-queue`.

Design:

- Matter-scoped persistent review queue for bounded drafting metadata
  extracted from existing uploaded matter document text/chunks only.
- Deterministic regex planner for FIR number, case number, police
  station, parties, dates, and statute/section references; no LLM,
  OCR, document-processing, corpus, embedding, background job, or
  storage-object read path.
- Each suggestion stores field key, label, proposed value, confidence
  band, status, source attachment reference, and a source-validated
  snippet capped at 280 characters.
- Confirmed/overridden fields feed drafting generation in a reviewed
  facts block; stepper facts remain authoritative and pending/rejected
  suggestions are excluded.
- Review actions record reviewer/timestamp and redacted audit metadata
  with counts, statuses, keys, hashes, and booleans only.

Scope:

- Extract FIR number, names, case number, police station, dates, sections.
- Review/confirm extracted fields.
- Use confirmed fields in drafting.

Tests:

- Fixture extraction.
- Low-confidence review.
- User override.
- Source links.

### ADP-16: Court-Specific Draft Format Profiles

Type: Backend + Web
Priority: P3
Dependencies: Drafting templates

Status (2026-05-24): In progress. Static court-profile foundation now covers
District Court, High Court, Supreme Court, Tribunal, and Generic profiles with
deterministic layout, heading, and required-field review rules. Export and
filing checklist surfaces report missing required fields for lawyer review
without blocking normal draft creation or fabricating values.

Scope:

- Format profiles for District Court, High Court, Supreme Court, Tribunal.
- Required field rules.
- Layout/heading variations.

Tests:

- Format changes draft structure.
- Required fields enforced.
- Existing templates unaffected.

### ADP-17: Judgment Monitoring In-App Alert Center

Type: Backend + Web
Priority: P3
Dependencies: Existing corpus data, no new ingest job

Scope:

- Saved judgment alert rules.
- Match against existing ingested judgments.
- In-app alert center.
- Digest preview.

Out of scope:

- Daily ingest job changes.
- External notification delivery.

Tests:

- Rule create/list/update.
- Match generation.
- No external delivery.
- No ingest job triggered.

### ADP-18: Law Amendment And Regulatory Update Monitor

Type: Backend + Web
Priority: P3
Dependencies: Statute model/source registry

Scope:

- Legal update watchlist.
- Source-backed update records.
- Practice area/Act/jurisdiction filters.
- In-app alerts.

Out of scope:

- External digests until WTD-5.3.

Tests:

- Rule CRUD.
- Source/provenance required.
- Matter/contract relevance explanation.

### ADP-19: Email Invitation To Calendar Candidate Extraction

Type: Backend + Web
Priority: P3
Dependencies: Unified communication timeline, email import

Scope:

- Extract calendar candidates from imported email/invite metadata.
- User review before creating CaseOps event.
- Link event back to email thread.

Out of scope:

- Autonomous calendar creation.

Tests:

- Candidate extraction.
- Review approval.
- Duplicate candidate handling.

### ADP-20: Durable Outlook Sync

Type: Backend Worker + Provider Integration
Priority: P4
Dependencies: WTD-5.1c, WTD-5.3, ADP-07

Scope:

- Durable scheduled sync.
- Retry/dead-letter.
- Admin replay.

Tests:

- Worker registration.
- Idempotent sync.
- Retry path.
- Redacted provider errors.

### ADP-21: Durable Google Drive Sync

Type: Backend Worker + Provider Integration
Priority: P4
Dependencies: WTD-5.1c, WTD-5.3, ADP-12

Scope:

- Durable Drive sync.
- Change detection.
- Conflict/review queue.

Tests:

- Idempotent sync.
- Updated file detection.
- Provider failure retry.

### ADP-22: Durable Email Connector

Type: Backend Worker + Provider Integration
Priority: P4
Dependencies: WTD-5.1c, WTD-5.3, ADP-05

Scope:

- Admin-triggered or provider webhook mailbox connector.
- Thread grouping.
- Intake routing.
- Runtime proof.

Tests:

- Provider config fail-closed.
- Message idempotency.
- Thread grouping.
- No cross-matter leakage.

### ADP-23: Judgment And Legal Update External Digests

Type: Backend Worker + Notification Delivery
Priority: P4
Dependencies: WTD-5.3, ADP-17, ADP-18

Scope:

- Email/in-app digest delivery.
- Retry/dead-letter.
- User preferences.

Tests:

- Digest generation.
- Delivery retry.
- Suppression/unsubscribe behavior where applicable.
- Redacted audit.

### ADP-24: Admin Retry, Dead-Letter, And Replay UI

Type: Backend + Web
Priority: P4
Dependencies: Durable workflows

Scope:

- Admin view of failed provider jobs.
- Redacted error display.
- Replay controls.
- Audit of replay.

Tests:

- Failure listing.
- Replay authorization.
- No secret leakage.

## 12. Benchmarking Notes

ADP mentioned MikeLegal, Iolite, Manupatra, and SCC Online. These references
should guide buyer expectations:

- Practice management tools set expectations for daily workflow depth:
  matters, calendars, billing, client communication, document organization,
  and operational dashboards.
- Legal research platforms set expectations for corpus breadth, citation
  trust, source quality, filters, and legal analytics.
- CLM and contract-review tools set expectations for playbooks, party
  perspective, deviation review, obligations, approvals, and analytics.

CaseOps differentiation should be:

- India-first matter-native legal operating system.
- Source-grounded legal AI inside the matter graph.
- Strong access control, audit, and governance.
- Operational workflow plus legal intelligence in one workspace.

## 13. Testing And Verification Standards

Every implementation PR must run the smallest relevant subset plus any required
generated-client or web checks.

Baseline verification:

- `git diff --check`
- Relevant backend tests through `.\scripts\verify-backend.ps1`
- `tests/test_migration_order.py` if a migration is added
- OpenAPI generation/client check if API schema changes
- Relevant web tests if web changes
- `npm run typecheck:web` if web/shared types change
- `npm run build:web` for meaningful web surface changes
- Secret/static scans for provider integrations
- Forbidden wording scans for judge analytics, recommendation, and AI outputs

Required coverage categories:

- Tenant isolation.
- Matter access.
- Restricted matter access.
- Team scoping.
- Ethical walls.
- Audit redaction.
- Provider missing-config fail-closed behavior.
- No secrets in logs or metadata.
- No external delivery unless the task explicitly owns delivery.
- No corpus ingest/backfill/embedding job unless explicitly authorized.

## 14. Documentation Rules

Each implementation slice must update relevant docs:

- This PRD status map if the task closes or changes an ADP item.
- `docs/FUTURE_WORKPLAN_2026-05-14.md` if live remaining work changes.
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` if enterprise gaps are affected.
- Product runbooks for provider setup or admin operation where relevant.

No slice should silently claim full closure when only a foundation is built.

## 15. Open Product Decisions

These decisions should be answered before implementation reaches the affected
slice:

1. Storage model: confirm firm-based quota first, with user-based quota later
   only if needed.
2. Languages: choose first supported languages for Matter File Q&A translation.
3. Translation authority: confirm English remains authoritative and local
   language is a labelled aid.
4. Email provider priority: Microsoft 365 first, Gmail first, or both.
5. Outlook consent model: tenant-admin consent or per-user OAuth.
6. Google Drive model: firm-admin connection or per-user OAuth.
7. Judgment monitoring sources: first courts/jurisdictions/practice areas.
8. Law amendment sources: India Code, Gazette, regulators, state
   notifications, or selected regulators first.
9. Contract playbook first types: NDA, MSA, vendor agreement, lease,
   employment, loan/security, or another ADP priority.
10. Drafting extraction first workflow: FIR/criminal, cheque bounce, civil
    suit, writ, appeal, tribunal filing, or another ADP priority.
11. Outside counsel scope: advocates only, senior counsel, consultants,
    vendors, or all external legal service providers.
12. Client verification scope: required documents and verification statuses.
13. Notification tolerance: whether in-app alerts are acceptable until durable
    external notification delivery is ready.
14. Judge analytics language: confirm customer accepts "court/bench context
    explorer" instead of "best judge/success probability".

## 16. Recommended Immediate Next Task

Start with `ADP-00` as a docs-only PR:

- Commit this PRD.
- Do not implement product code.
- Do not update deploy or release docs.
- Run `git diff --check`.
- Open a draft PR for review.

After ADP-00 merges, the recommended first implementation slice is `ADP-01`
Storage Governance Foundation or `ADP-02` AI Token Governance Foundation,
because both improve enterprise trust and cost predictability before adding
more AI/integration volume.
