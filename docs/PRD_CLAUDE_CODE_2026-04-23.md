# CaseOps Unified Product PRD for Claude Code

Document version: 2.1
Date: 2026-04-23
Status: Execution baseline for product, engineering, QA, and Claude Code
Audience: Founder, product, engineering, QA, security, and any agent working in this repo

## 1. Purpose

This document is the single execution PRD for CaseOps feature work.

It consolidates:

- `docs/PRD.md`
- `docs/WORK_TO_BE_DONE.md`
- `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
- `C:\Users\mishr\Downloads\CaseOps_MissingModules_23pril2026.xlsx`
- `C:\Users\mishr\Downloads\CaseOps_Modules_Analysis_2026-04-23.xlsx`
- `C:\Users\mishr\Downloads\CaseOps - Law Firm Feedback Gap Analysis.md`
- the live codebase in `apps/api` and `apps/web`

No future feature work should treat any one of those inputs as sufficient on its
own. This document is the merged source of truth for Claude Code execution.

## 2. Five-Pass Validation Rule

This PRD was synthesized after five passes. Future major updates must repeat the
same five passes.

Pass 1 - baseline product intent:

- original PRD
- company vision
- target personas

Pass 2 - live repo truth:

- API routes
- web routes
- schemas
- services
- tests
- deploy manifests

Pass 3 - backlog and delivery truth:

- `docs/WORK_TO_BE_DONE.md`
- `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
- strict bug and enterprise ledgers

Pass 4 - customer and market truth:

- missing-modules spreadsheet
- modules-analysis spreadsheet
- law-firm feedback gap analysis
- feature requests that change product direction

Pass 5 - hardening and data quality truth:

- security posture
- enterprise-readiness gaps
- vector quality and evaluation evidence
- observability, deployment, and operational maturity

## 3. Product Definition

CaseOps is an India-first legal work operating system for:

- litigation-heavy law firms
- solo lawyers
- corporate legal teams
- enterprise legal operations teams

CaseOps is not a generic chatbot. It is:

- matter-anchored
- bench-aware
- format-aware
- workflow-native
- citation-grounded
- enterprise-hardened

The product must evolve from only "matter-centric" into:

- matter-centric for system of record
- bench-centric for litigation strategy
- format-centric for drafting and notice automation

## 4. Product Promise

CaseOps must let a legal team:

- run intake, matters, documents, hearings, drafting, contracts, billing, and
  outside counsel in one workspace
- search judgments, statutes, tribunal material, and internal work product with
  grounded retrieval
- prepare for a specific judge, bench, court, or tribunal with contextual
  strategy support
- generate first drafts, hearing packs, summaries, and notices with verified
  citations and explicit review gates
- track tasks, deadlines, reminders, and client communications end to end
- operate under strict tenant isolation, role controls, auditability, and
  enterprise deployment options

## 5. Product Principles

- Simple UI first. One screen, one job, one primary action.
- Lawyer confidence over AI showmanship.
- Refusal is better than fabrication.
- Enterprise posture is mandatory, not a later polish item.
- Product claims must stay behind code and benchmark proof.
- Public-law corpus and tenant-private corpus follow different security rules.
- Bench intelligence, not only generic research, is a core differentiator.
- Template and notice workflows are first-class products, not drafting sidecars.

## 6. Current Product Inventory

Status legend:

- `Shipped`
- `Partial`
- `Missing`

| Area | Current status | Live repo evidence | Main remaining gap |
| --- | --- | --- | --- |
| Auth, bootstrap, session, sign-in | Shipped | `api/routes/auth.py`, `bootstrap.py`, `/sign-in` | move browser auth off localStorage |
| Matters and intake | Shipped | `api/routes/matters.py`, `/app/intake`, `/app/matters` | deeper portfolio analytics and generic tasks |
| Matter cockpit | Shipped | `/app/matters/[id]/*` | more tab parity and better review surfaces |
| Research and authority retrieval | Partial | `/app/research`, `services/authorities.py`, `services/reranker.py` | full corpus depth, statutes, tribunals, stronger benchmarks |
| Court and judge profiles | Partial | `api/routes/courts.py`, `/app/courts`, `/app/courts/judges/[judge_id]` | richer trend analytics, bench strategy, tribunal expansion |
| Document ingest and OCR | Partial | `services/document_processing.py`, `services/ocr.py` | broader parsers, production OCR quality gates across all paths |
| Document viewer and annotations | Partial | `/app/matters/[id]/documents/[attachment_id]/view`, matter annotation routes | richer multi-page search and annotation UX |
| Matter summary / case summary | Shipped | `services/matter_summary.py`, summary DOCX/PDF routes | caching, auditability, stronger provider-failure handling |
| Drafting studio | Shipped | draft routes, `/app/matters/[id]/drafts/*`, `services/drafting.py` | notice factory, template library governance, goldens |
| Pleading stepper | Shipped | drafting template routes, preview route, stepper UI | more template coverage, batch workflows |
| Recommendations | Partial | `api/routes/recommendations.py`, matter recommendations page | bench-aware strategy, more recommendation types |
| Hearing packs | Shipped | hearing-pack routes and pages | scheduled automation, calendar integration, reminders |
| Calendar, notifications, and reminders | Partial | hearing reminders service, admin notifications page | full calendar UI, rule engine, delivery channels |
| Billing and payments | Shipped | billing tab, payments routes, Pine Labs integration | recoveries depth, fuller end-to-end gateway proof |
| Contracts and obligations | Partial | contract routes, contract workspace pages | stronger structural extraction and compliance calendar |
| Clients, advocates, communications, AutoMail, and KYC | Partial | `api/routes/clients.py`, `/app/clients` | advocates, communication log, KYC, mail workflows |
| Outside counsel | Shipped | outside-counsel routes and pages | portfolio analytics and enterprise procurement depth |
| Teams and matter access | Shipped | teams routes, admin teams page, access panels | richer roles, admin UX, team-scoped grants |
| Admin, audit export, notifications admin | Partial | `/app/admin`, audit export, notifications admin | tenant management, plans, AI policy UI, SSO |
| Legal translator | Missing | no product surface | full translation module |
| Support module | Missing | no in-app support system | help center, feedback, chat/tickets |
| Client verification / KYC | Missing | no KYC surface | regulated verification stack |
| Tribunal coverage | Missing | no live tribunal corpus or workflows | NCLT, NCLAT, CCI, NCDRC ingestion and UX |
| Bare acts and statutes | Missing | no statute database or UI | structured statutory corpus and section search |
| Law books and commentary | Missing | no licensed commentary integration | licensing and retrieval model |
| Arbitrator registry | Missing | no arbitrator module | Delhi ex-judge and arbitration intelligence |
| Air-gapped enterprise deployment | Partial | LLM and embedding abstractions exist | full offline package and no-external-call mode |
| Enterprise ops and hardening | Partial | audit, rate limiting, tracing/logging scaffolding | secrets, backups, migration safety, abuse controls |

### 6.1 External Module Audit Reconciliation

The workbook `C:\Users\mishr\Downloads\CaseOps_Modules_Analysis_2026-04-23.xlsx`
marks every listed module as `Missing` in production. Claude must not copy that
claim forward without reconciling it to current repo truth. The corrected
mapping is:

| Audit ID | Spreadsheet module | PRD coverage | Corrected current status | Reconciliation note |
| --- | --- | --- | --- | --- |
| `MOD-TS-001` | JudgeProfile | `J06`, `M05`, `US-014/015`, `FT-023/024` | `Implemented` | Judge profile + bench match + bench strategy context + bench-aware appeal drafting all shipped 2026-04-25 (Sprint P1+P3+P4+P5/BAAD-001). MOD-TS-001-A "Appeal Strength Analyzer" is the queued sub-feature; P2 sci.gov.in supplement is formally deferred (low marginal value vs corpus coverage). |
| `MOD-TS-001-A` | Appeal Strength Analyzer | `J06`, `J07`, `J09`, `M05`, `M06`, `M07`, `US-014/015/017/018/021/027`, `FT-024B/031B` | `Queued` | Per-ground argument-completeness analysis on an appeal-memorandum draft (or matter facts when no draft yet): citation coverage, supporting-authority strength (SC > HC > lower), bench-history support, weak-evidence path highlighted, concrete edit suggestions ("add SC authority on Order XLI Rule 5", "drop ground 4", "strengthen with [Y]"). Frame as **argument completeness**, NOT outcome prediction. Bench-aware drafting hard rules apply: no "win/lose/chance/probability/favourable/tendency" language anywhere in the surface (asserted by a structural test). Reuses the existing `bench_strategy_context` service for bench data; no new judge analytics. |
| `MOD-TS-002` | OCR Extractor | `J04`, `M03`, `US-007/009`, `FT-011/012` | `Partial` | OCR exists, but broader parser coverage and production quality gating are still incomplete. |
| `MOD-TS-003` | Legal Translator | `J16`, `M17`, `US-048/049`, `FT-067/068` | `Missing` | This really is still missing as a product surface. |
| `MOD-TS-004` | Case Summary | `J03A`, `M16`, `US-046/047`, `FT-016-019`, `FT-065/066` | `Shipped` | Summary generation and export exist now, but the roadmap still calls for caching and stronger resilience. |
| `MOD-TS-005` | Document Viewer | `J04`, `M03`, `US-007/008`, `FT-013/014/015` | `Partial` | Viewer and annotations exist, but richer UX and deeper navigation/search are still incomplete. |
| `MOD-TS-006` | Calender | `J08`, `M08`, `US-022/023/024/025`, `FT-042/043` | `Partial` | Reminders exist, but full calendar UI and sync depth are not complete yet. |
| `MOD-TS-007` | Notification & Reminder | `J08`, `M08`, `US-024`, `FT-040/041` | `Partial` | Reminder plumbing exists, but full delivery-channel coverage and rules are still partial. |
| `MOD-TS-008` | Pleading Step By Step | `J07`, `M06`, `US-017`, `FT-025/026` | `Shipped` | Stepper-driven drafting exists for current supported draft families. |
| `MOD-TS-009` | Clients & Advocates Management | `J12`, `M11`, `US-034/035`, `FT-044/045/046` | `Partial` | Client management exists, but advocate depth and communication history are still incomplete. |
| `MOD-TS-010` | AutoMail Transfer | `J12`, `M11`, `US-036`, `FT-047/048` | `Partial` | Template-driven outbound communication is in scope, but not complete enough to call fully shipped. |
| `MOD-TS-011` | Support | `J14`, `M14`, `US-043`, `FT-063` | `Missing` | Support/help exists only as planned scope, not as a completed in-app module. |
| `MOD-TS-012` | Draft Generator | `J07`, `M06`, `US-017/018/019/020/021`, `FT-027-033` | `Shipped` | Multi-template guided draft generation exists for the current supported document set. |
| `MOD-TS-013` | Clients Verification | `J12`, `M11`, `US-037`, `FT-049` | `Missing` | KYC and client verification remain roadmap items, not a shipped module. |
| `MOD-TS-014` | Portal Persona Model + Shared Scaffold | `J17`, `J18`, `M18`, `US-050/051`, `FT-070/071` | `Missing` | Phase C-1 scope: `PortalUser` table separate from `Membership`, magic-link auth on a `/portal/*` cookie scope, `MatterPortalGrant` scoping, branded shell. |
| `MOD-TS-015` | Client Portal | `J17`, `M19`, `US-052/053`, `FT-072/073` | `Missing` | Phase C-2 scope: matter view + Comms inbox + KYC submit + read-only hearings, gated by `MatterPortalGrant.role='client'`. |
| `MOD-TS-016` | Outside Counsel Portal | `J18`, `M20`, `US-054/055`, `FT-074/075` | `Missing` | Phase C-3 scope: assigned-matter view + work-product upload + invoice submission + time entries, gated by `MatterPortalGrant.role='outside_counsel'`. |

## 7. Product Strategy Shift

CaseOps must explicitly support three operating modes:

- Matter mode: the system of record for all work on a legal matter.
- Bench mode: the system of preparation for a specific judge, bench, court, or
  tribunal.
- Format mode: the system of production for pleadings, notices, and high-volume
  document workflows.

The winning product narrative is:

- not "AI for legal"
- not "practice management plus chatbot"
- but "the operating system for legal work and court preparation"

## 8. Personas

### P1. Managing partner or litigation head

- Wants portfolio visibility, utilization, fee recovery, and consistent work
  quality.
- Needs trust, audit trails, and review gates.
- Cares about cross-matter oversight, staffing, deadlines, and enterprise risk.

### P2. Senior litigator or arguing counsel

- Wants judge-aware research, argument strategy, hearing packs, and fast draft
  review.
- Cares about citations, posture, forum choice, and last-mile prep before court.

### P3. Junior associate or paralegal

- Wants guided intake, structured drafting, deadline tracking, and document
  organization.
- Needs a simple UI, clear instructions, and low-error workflows.

### P4. General counsel or corporate legal lead

- Wants matter tracking, contract obligations, outside counsel oversight,
  billing, and board-ready summaries.
- Cares about spend control, compliance, and exportable evidence.

### P5. Legal operations or finance admin

- Wants billing, payment recovery, notifications, calendar hygiene, and admin
  controls.
- Cares about deliverability, statuses, templates, and audit trails.

### P6. Solo lawyer

- Wants all core workflows in one simple UI with minimal setup and strong
  drafting/research leverage.
- Cares about speed, affordability, and simple daily operation.

### P7. Enterprise IT or security admin

- Wants SSO, audit exports, private deployment, secrets hygiene, backup/restore,
  and infrastructure clarity.

### P8. Client portal user (Phase C, 2026-04-24)

- A client invited by the firm into the firm's CaseOps workspace via the
  caseops.ai/portal surface.
- Wants matter status, hearing dates, document downloads, two-way
  communication with the firm, and KYC submission — without learning the
  full internal workspace.
- Has no Membership; cannot access /app, cannot see other clients,
  cannot see anything outside the matters they were explicitly granted.

### P9. Outside-counsel portal user (Phase C, 2026-04-24)

- An external advocate or counsel firm invited by the workspace owner to
  collaborate on specific matters via the caseops.ai/portal surface.
- Wants assigned-matter visibility, document upload (briefs, opinions),
  invoice submission, and time-entry posting against the matter — scoped
  strictly to the matters they were granted.
- Has no Membership; cannot impersonate the firm; every action they take
  is auditable as the external counsel, never as the inviting firm.

## 9. UX and Information Architecture

### 9.1 UX rules

- The product must remain simple enough for daily use by non-technical lawyers.
- Every workflow must have a clear primary CTA and a clear next state.
- Do not expose backend or model jargon in user-facing copy.
- Failures must be actionable, not operationally vague.
- AI output must always show its grounding, review state, and confidence limits.
- Mobile and narrow-laptop behavior must be intentionally designed, not
  desktop-only.

### 9.2 Top-level navigation

Authenticated navigation must converge on:

- Dashboard
- Matters
- Research
- Courts
- Drafting
- Hearings and Calendar
- Contracts
- Clients
- Outside Counsel
- Portfolio
- Admin
- Help

### 9.3 Matter cockpit navigation

Every matter must expose:

- Overview
- Documents
- Research
- Drafts
- Recommendations
- Hearings
- Calendar and Deadlines
- Billing
- Audit
- Access

## 10. Detailed User Journeys

### J01. Workspace bootstrap and authentication

Users:

- founder demo admin
- firm admin
- member

Happy path:

1. User creates a workspace or signs into an existing one.
2. System validates company slug, email, password, and role.
3. Session is created and workspace context is loaded.
4. User lands on dashboard with role-aware navigation.
5. Session refresh happens silently until revoked or expired.

Failure and edge rules:

- suspended memberships must lose access immediately
- bad credentials must not leak whether a user exists
- cross-origin host mismatches must not create split-session behavior
- browser session storage must move to HttpOnly-safe transport for enterprise

Done when:

- auth is simple for users and hardened for enterprise
- workspace context is always correct
- role and capability resolution is reliable

### J02. Intake to matter creation

Users:

- associate
- partner
- GC

Happy path:

1. User opens intake.
2. User enters matter type, title, client, parties, court, practice area, and
   matter code.
3. System pre-validates matter code uniqueness before submit.
4. System creates the matter, initial notes, and initial team or owner links.
5. User is routed into the new matter cockpit.

Failure and edge rules:

- duplicate codes must be blocked before submit when possible
- unsupported courts must be explicit, not implicit
- matter creation must be tenant-scoped and audited
- intake must support both litigation and corporate workflows

Done when:

- matter creation is fast, obvious, and low-error
- user never loses entered context on validation failure

### J03. Daily matter workspace

Users:

- all legal staff

Happy path:

1. User opens a matter overview.
2. User sees current posture, upcoming dates, recent activity, open tasks,
   documents, drafts, and billing signals.
3. User can add notes, tasks, hearings, invoices, and attachments.
4. System records every substantive state change in audit.

Failure and edge rules:

- empty states must never render misleading cards
- restricted-access matters must honor grants and ethical walls
- matter team scoping must behave consistently across list and detail surfaces

Done when:

- the matter cockpit is the primary system of work
- users do not need external spreadsheets or ad hoc trackers for core activity

### J03A. Case summary and matter brief generation

Users:

- litigators
- partners
- GC

Happy path:

1. User opens a matter with sufficient documents, notes, or case history.
2. User generates or refreshes a structured summary.
3. System composes overview, key facts, issues, chronology, posture, and next
   steps from matter-scoped data.
4. User reviews the summary in-app and exports it to DOCX or PDF when needed.

Failure and edge rules:

- summary generation must not hallucinate missing facts from incomplete matter
  records
- provider failure must degrade safely and explain whether the issue is source
  coverage, extraction quality, or model failure
- summary refresh must not silently overwrite reviewer context without version
  awareness where policy requires it

Done when:

- matter summaries are reliable enough for internal briefing and client-ready
  export
- summary outputs stay matter-scoped, reviewable, and resilient under provider
  failure

### J04. Document intake, OCR, viewing, and annotation

Users:

- associates
- partners
- legal ops

Happy path:

1. User uploads one or more documents to a matter or contract.
2. System validates file type, magic bytes, and upload boundaries.
3. Parser and OCR pipeline extract text and metadata.
4. User opens the inline viewer, searches within the document, and adds
   annotations or highlights.
5. Parsed text becomes available to downstream retrieval and drafting flows.

Failure and edge rules:

- malware scanning must be enforced in production
- oversized or low-quality OCR pages must not poison embeddings
- unsupported files must fail with clear recovery copy
- annotations must be tenant-scoped and soft-deletable

Done when:

- uploaded documents are readable, searchable, annotatable, and safely indexed

### J05. Research and authority discovery

Users:

- litigators
- associates
- solo lawyers

Happy path:

1. User enters a query, issue, judge, section, or forum question.
2. System normalizes the query and expands legal variants.
3. Retrieval searches public-law corpus plus tenant-private documents where
   allowed.
4. Cross-encoder reranker reorders top candidates.
5. User sees authorities, citations, summaries, judges, and source links.
6. User can send authorities into drafting, hearing packs, or notes.

Failure and edge rules:

- no-result paths must distinguish corpus gaps from provider failures
- retrieval must degrade safely when reranker or embedder is unavailable
- legal sources must be clearly labeled by type: judgment, statute, tribunal,
  commentary, internal document

Done when:

- research answers are grounded, fast, and transferable into adjacent workflows

### J06. Court, judge, bench, and tribunal intelligence

Users:

- litigators
- partners
- strategy teams

Happy path:

1. User opens a court, judge, bench, or tribunal profile.
2. System shows profile metadata, recent matters, authority trends, and case
   type patterns.
3. User can match a matter to likely benches or judge surfaces.
4. Strategy recommendations can incorporate bench-aware context.
5. Appeal drafting can consume cited judge or bench history when the evidence
   is strong enough and must fall back cleanly when it is not.

Failure and edge rules:

- no judge analytics claim without benchmarked support
- judge and bench intelligence must stay evidence-backed, not reputation gossip
- bench-aware drafting must cite the specific judgments it relies on and must
  never become judge favorability or outcome prediction
- tribunal coverage must be first-class once added, not hacked through court
  enums only

Done when:

- CaseOps helps answer "what works before this bench, on this issue, in this
  forum?" without pretending certainty where none exists

### J07. Drafting studio, template library, and notice factory

Users:

- associates
- partners
- solo lawyers

Happy path:

1. User chooses a draft type or starts from a template.
2. Stepper collects structured facts with per-type validation.
3. System offers suggestions and partial preview.
4. Final generation uses grounded authorities and per-type prompt rules.
5. Reviewer sees citations, validator findings, and version history.
6. Draft can be exported individually or as part of a notice batch.

Failure and edge rules:

- no draft approval without verified citations when the workflow requires them
- statute confusion, placeholder leaks, and unsupported facts must surface to
  the reviewer
- template selection and generation must support court-specific and notice-type
  workflows
- batch notice generation must isolate per-recipient data and errors

Done when:

- drafting is guided, reviewable, and production-grade across all supported
  document families

### J08. Hearings, calendar, tasks, and notifications

Users:

- litigators
- clerks
- legal ops

Happy path:

1. User schedules or updates a hearing.
2. System records hearing metadata, deadlines, and follow-up tasks.
3. User can generate a hearing pack and mark it reviewed.
4. Calendar view shows hearings, deadlines, and custom events.
5. Notification rules trigger in-app, email, and optional SMS reminders.

Failure and edge rules:

- reminder UX must never imply delivery if the system has not actually queued it
- notification rules must be auditable and retryable
- calendar sync must not create duplicate or drifting events

Done when:

- hearing preparation and deadlines are controlled from one reliable flow

### J09. Recommendations and legal strategy

Users:

- senior litigators
- partners
- GC

Happy path:

1. User asks for forum, authority, remedy, next-step, judge, or strategy
   recommendation.
2. System retrieves grounded authorities and issue context.
3. LLM emits structured options with rationale and citations.
4. User accepts, rejects, edits, or defers a recommendation.
5. Decision is audited and can feed future evaluation loops.

Failure and edge rules:

- unsupported recommendation types must not be advertised as live
- every option must preserve its own supporting citations
- weak-evidence paths must refuse or downgrade confidence
- bench-aware recommendation must wait for real judge-history grounding

Done when:

- recommendations behave as accountable decision support, not black-box advice

### J10. Contracts, obligations, and compliance calendar

Users:

- corporate legal
- GC
- contracting teams

Happy path:

1. User creates a contract and uploads source documents.
2. System extracts parties, clauses, obligations, dates, and playbook signals.
3. User reviews extracted obligations and links them to tasks or calendar.
4. User can inspect attachments, clauses, and obligations in one workspace.

Failure and edge rules:

- extraction must distinguish provider failure from parse failure
- obligations and clauses must persist correctly on success path
- compliance reminders must use the same durable notification system as hearing
  reminders

Done when:

- contract review produces reliable structured outputs and ongoing deadline
  control

### J11. Billing, invoices, payment links, and recoveries

Users:

- partners
- finance admins
- legal ops

Happy path:

1. User records time and matter expenses.
2. User issues an invoice from the matter.
3. User sends a payment link and tracks status changes.
4. Invoice, recoveries, and payment attempts remain visible in the billing tab.

Failure and edge rules:

- gateway configuration readiness must be visible before users try to send
  payment links
- payment webhooks must be signed, idempotent, and tenant-safe
- skipped E2E coverage is not enough for clean release sign-off

Done when:

- billing is usable by firms today and trustworthy enough for enterprise buyers

### J12. Clients, advocates, communication logs, and KYC

Users:

- associates
- legal ops
- GC

Happy path:

1. User creates or updates a client profile.
2. User links one or more clients to a matter.
3. User records communications or sends templated emails with attachments.
4. Optional KYC and verification status is visible where required.

Failure and edge rules:

- no advocate or client duplication drift across matters
- no automated email send without template selection, recipient clarity, and
  delivery status tracking
- KYC data must never be embedded into vector search by default

Done when:

- client, advocate, and communication history become first-class product data

### J13. Outside counsel and spend management

Users:

- GC
- legal ops
- finance

Happy path:

1. User creates outside counsel profiles and assignments.
2. User tracks budgets, spend, statuses, and approvals.
3. Portfolio views summarize active assignments and vendor performance.

Failure and edge rules:

- status and enum drift must stay closed on read and write paths
- spend signals must be explainable to admins and finance users

Done when:

- outside counsel is not a disconnected spreadsheet workflow

### J14. Admin, tenant control, audit, SSO, and support

Users:

- owner
- admin
- enterprise IT

Happy path:

1. Admin manages users, teams, access, notifications, and audit exports.
2. Admin configures AI policy, plans, branding, and integrations.
3. Enterprise admins configure SSO, retention, and export or deletion workflows.
4. Users can access help, feedback, and support from inside the app.

Failure and edge rules:

- admin actions must always be audited
- support and feedback flows must respect tenant boundaries
- AI policy controls must be enforceable server-side, not UI-only

Done when:

- tenant administration is real and enterprise buyers can evaluate governance

### J15. Enterprise deployment and air-gapped operation

Users:

- enterprise IT
- security teams

Happy path:

1. Enterprise buyer selects shared SaaS, private deployment, or air-gapped
   package.
2. System provides a documented deployment architecture, model routing, secret
   handling, and support runbook.
3. Air-gapped deployments run without external API calls.

Failure and edge rules:

- no enterprise deployment claim without explicit no-egress mode
- migrations, secrets, backups, and restore drills must be part of the product
  story, not ad hoc operations

Done when:

- CaseOps can be sold credibly to privacy-sensitive legal buyers

### J17. Client portal experience (Phase C, 2026-04-24)

Users:

- P8 client portal users (invited by the firm)

Happy path:

1. Firm admin invites a client by email; the system mints a one-time magic
   link valid for 30 minutes and emails it through AutoMail.
2. Client clicks the link, lands on /portal, and sees only the matters they
   were explicitly granted.
3. For each matter, the client sees status, upcoming hearings (read-only),
   recent documents shared by the firm, and a Communications inbox they can
   reply into. Replies post to the firm's internal Communications log.
4. Client submits KYC information when prompted; submission status is
   visible to the firm in the matter's KYC card.

Failure and edge rules:

- Magic-link tokens are single-use, expire in 30 minutes, and are bound to
  one email address — replay or cross-email use is rejected with a
  generic "link expired" message (no enumeration).
- Portal sessions are HttpOnly cookies scoped to /portal/* with a separate
  cookie name from the internal /app session, so the same browser hitting
  both surfaces cannot cross-contaminate.
- A portal user can never be promoted to a Membership without an explicit
  workspace-owner action that creates a fresh Membership row.
- Every portal action is audited as the PortalUser, with the granting
  Membership recorded so internal audit can trace who let them in.

Done when:

- A client can self-serve matter visibility and KYC without the firm
  emailing PDFs back and forth.

### J18. Outside-counsel portal experience (Phase C, 2026-04-24)

Users:

- P9 outside-counsel portal users (invited by the firm)

Happy path:

1. Workspace owner invites an external counsel by email and grants them a
   set of matters (read or contribute scope per matter).
2. External counsel signs in via the same magic-link portal, lands on
   /portal, and sees only their assigned matters.
3. For each matter, they can upload work product (briefs, opinions),
   submit time entries against the matter's billing log, and submit
   invoices into the firm's billing inbox.
4. Workspace owner approves or rejects the submitted invoices via the
   existing internal billing workflow; the portal user sees status only.

Failure and edge rules:

- An outside-counsel portal user must never see another outside-counsel
  user's submissions, even on the same matter, unless the granting
  Membership explicitly turns on cross-counsel visibility.
- Invoice submissions enter the firm's billing inbox in a "needs review"
  state; they are never auto-approved or auto-paid.
- Document uploads are scanned for malware (existing virus_scan service)
  before they appear on the matter's Documents tab.
- Revoking a portal grant invalidates active sessions immediately.

Done when:

- External counsel can collaborate on assigned matters without email + Drive
  side channels, and the firm sees one canonical work-product trail.

### J16. Legal translation and localization

Users:

- litigators
- associates
- clerks

Happy path:

1. User selects a document, draft, or text block for translation.
2. User chooses source and target language plus any glossary or legal-term mode.
3. System produces a structured translation that preserves formatting and legal
   terminology where supported.
4. User reviews the translated output side by side with the source and exports
   or copies the approved result.

Failure and edge rules:

- translation must not be marketed as production-ready for a language pair
  without legal-term benchmark evidence
- bilingual review must make source and translated text easy to compare
- unsupported scripts, poor OCR input, or glossary conflicts must be surfaced
  explicitly
- tenant-restricted text must follow tenant AI policy and provider controls

Done when:

- legal translation is usable for supported language pairs with reviewable,
  terminology-aware output
- translated content can be shared without losing source traceability

## 11. Module Specification Matrix

| Module ID | Module | Status now | Required build target |
| --- | --- | --- | --- |
| M01 | Auth and workspace | Shipped | secure browser session model, SSO, MFA-ready posture |
| M02 | Matter graph and intake | Shipped | richer intake, better portfolio controls |
| M03 | Documents, OCR, viewer, annotations | Partial | broader parsers, safe OCR, richer viewer |
| M04 | Research and authority retrieval | Partial | public-law depth, tenant overlays, stronger benchmarks |
| M05 | Court, judge, bench, tribunal intelligence | Partial | tribunal corpus, bench analytics, arbitrator registry |
| M06 | Drafting studio and templates | Shipped | template library governance, notice factory, goldens |
| M07 | Recommendations and strategy | Partial | bench-aware and broader recommendation types |
| M08 | Hearings, calendar, tasks, and notifications | Partial | generic tasks, full calendar, durable notifications |
| M09 | Contracts and obligations | Partial | structural extraction, compliance calendar, playbook depth |
| M10 | Billing and payments | Shipped | stronger recoveries and enterprise verification |
| M11 | Clients, advocates, communications, AutoMail, and KYC | Partial | advocate profiles, communications, verification, AutoMail depth |
| M12 | Outside counsel and portfolio | Shipped | deeper vendor analytics and spend workflows |
| M13 | Teams, access, ethical walls | Shipped | richer roles, admin UX, grant depth |
| M14 | Admin, plans, AI policy, SSO, support | Partial | tenant management, entitlements, help/support |
| M15 | Data platform and enterprise deployment | Partial | Voyage production path, Opus-assisted enrichment, rerank, air-gap |
| M16 | Matter summary and case brief generation | Shipped | caching, stronger resilience, version-awareness, richer exports |
| M17 | Legal translation and localization | Missing | bilingual translation, glossary control, side-by-side review, export |
| M18 | Portal persona model and shared portal scaffold (Phase C-1) | Missing | PortalUser table, magic-link auth, MatterPortalGrant scope, /portal layout, branded shell |
| M19 | Client portal (Phase C-2) | Missing | matter view, comms inbox, KYC submit, hearing read-only view |
| M20 | Outside-counsel portal (Phase C-3) | Missing | assigned-matters view, work-product upload, invoice submission, time entries |

## 12. Data Source and Knowledge System PRD

### 12.1 Authoritative public-law sources

| Data family | Primary sources | Storage | Product use |
| --- | --- | --- | --- |
| Supreme Court judgments | SCI site, official public datasets, existing SC corpus | object + relational + vector | research, drafting, hearing prep, judge intelligence |
| High Court judgments | Delhi, Bombay, Karnataka, Madras, Telangana, Calcutta, Allahabad, later TN and Gujarat | object + relational + vector | research, court prep, drafting |
| District court judgments | eCourts and judgments portal | object + relational + vector | district litigation support |
| Tribunal judgments | NCLT, NCLAT, CCI, NCDRC, later CAT and sectoral tribunals | object + relational + vector | tribunal workflows and recommendations |
| Bare acts and statutes | India Code and official gazette sources | relational + vector | statute search, drafting, recommendation grounding |
| Procedural and supporting laws | BNSS, BNS, BSA, CPC, CrPC legacy, NI Act, Arbitration Act, IBC, Companies Act, Competition Act, Consumer Protection Act, IT Act | relational + vector | issue and forum support |
| Law Commission reports | Law Commission of India | object + relational + vector | reasoning and policy context |
| NJDG and court analytics | NJDG and court-level public analytics | relational | backlog and court intelligence |
| Law books and commentaries | licensed SCC, Manupatra, or approved alternatives | object + relational + vector | premium research and explanation |
| Format libraries | IBA, Legal Helpline India, internal approved templates, court filing formats | object + relational + optional vector | template library and notice factory |
| Arbitrator registries | DIAC, MCIA, ICA, bar or official rosters | relational | arbitration intelligence |

### 12.2 Tenant-private sources

| Data family | Storage | Vector policy |
| --- | --- | --- |
| matter attachments | object + relational + vector | allowed, tenant-scoped |
| approved drafts and final notices | object + relational + vector | allowed, tenant-scoped |
| notes and communication logs | relational + optional vector | allowed only when tenant opts in |
| contracts and clauses | relational + vector | allowed, tenant-scoped |
| KYC artifacts | object + relational | not embedded by default |
| payment payloads, secrets, tokens | relational | never embedded |

### 12.3 Production vector and AI policy

For any corpus slice that ships as production legal retrieval:

- Embeddings MUST use Voyage in production.
- Current production default on GCP is `voyage-4-large`.
- A switch to `voyage-3-law` or another embedding path must be benchmarked and
  explicitly justified on quality and cost before it replaces that default.
- Corpus metadata enrichment for titles, citations, parties, judges, benches,
  sections, and format labels MUST use Opus-class extraction or an approved
  equivalent high-reliability path before embedding.
- Where the production workflow uses Anthropic-backed enrichment or evaluation,
  docs and sign-off language must say so plainly instead of describing the old
  `bge-small` baseline as the live production truth.
- Cross-encoder reranking MUST be enabled on production authority retrieval,
  drafting retrieval, judge intelligence, and hearing-pack retrieval.
- Retrieval quality must meet or exceed a 4.8/5 readiness rating before the
  corpus slice is called production-ready.

### 12.4 4.8+/5 corpus quality gate

Every public-law or tenant-private vector slice must pass all of:

- representative recall benchmark with explicit query set
- metadata completeness benchmark
- OCR garbage rejection benchmark
- title and citation normalization benchmark
- reranker-on retrieval benchmark

Minimum acceptance bar:

- readiness rating >= 4.8 / 5
- recall@10 >= 95% on the agreed representative benchmark
- no material title-placeholder pollution in the embedded corpus
- parser and OCR rejection rules committed and tested

### 12.5 Ingestion pipeline contract

Production ingestion order:

1. fetch or receive source document
2. validate file type and safety
3. parse with best parser for source family
4. OCR fallback only where needed
5. structural extraction and metadata normalization
6. Opus-assisted title, citation, party, judge, bench, and section cleanup
7. chunk using source-family rules
8. embed with Voyage
9. benchmark and quality-gate before declaring production readiness

## 13. User Story Catalog

### Auth and workspace

- `US-001` As a firm admin, I want to bootstrap a workspace and sign in without
  touching raw API tooling.
- `US-002` As an admin, I want suspended users to lose access immediately.
- `US-003` As an enterprise admin, I want future SSO and plan controls to align
  with the same tenant model.

### Matter intake and workspace

- `US-004` As an associate, I want to create a matter with a valid matter code
  and be routed directly into the cockpit.
- `US-005` As a partner, I want a matter overview that shows the next actionable
  legal work, not empty noise.
- `US-006` As a GC, I want portfolio summaries across matters, deadlines, spend,
  and risk.

### Documents and OCR

- `US-007` As a user, I want uploaded documents to be searchable and viewable in
  one place.
- `US-008` As a reviewer, I want to annotate documents inline and share those
  highlights back into drafting and hearing prep.
- `US-009` As an operator, I want OCR garbage blocked before it pollutes search.

### Research and legal knowledge

- `US-010` As a litigator, I want grounded authority search across judgments,
  statutes, and internal material.
- `US-011` As a lawyer, I want section-level statute search for BNS, BNSS, BSA,
  and related laws.
- `US-012` As a researcher, I want tribunal and district-court material to be
  searchable alongside SC and HC material.
- `US-013` As a firm, I want licensed commentary support for premium research.

### Court, judge, bench, and tribunal intelligence

- `US-014` As a litigator, I want a judge profile with recent matters,
  authorities, and issue patterns.
- `US-015` As a partner, I want bench-aware strategy support in hearing prep and
  recommendations.
- `US-016` As an arbitration team, I want arbitrator profiles and arbitration
  workflow support.

### Drafting and notices

- `US-017` As a junior lawyer, I want a step-by-step drafting flow that reduces
  legal drafting errors.
- `US-018` As a reviewer, I want every generated draft to show citations,
  findings, and version history before approval.
- `US-018A` As a litigator on an appeal, I want to see which grounds in
  my draft are well-supported by cited authorities and which are weak,
  with concrete suggestions to strengthen the weak ones — framed as
  argument completeness, not outcome prediction.
- `US-019` As a high-volume user, I want a reusable template library.
- `US-020` As a collections or notice team, I want batch notice generation with
  prefilled data.
- `US-021` As a litigator, I want format selection to align with forum, judge,
  and issue context where evidence supports it.

### Hearings, calendar, and notifications

- `US-022` As a lawyer, I want every hearing to create the right follow-up work.
- `US-023` As a clerk, I want week and month calendar views for hearings and
  deadlines.
- `US-024` As a user, I want reliable reminders in-app and by email or SMS.
- `US-025` As a partner, I want hearing packs that reflect the latest case state
  and authorities.

### Recommendations

- `US-026` As a partner, I want forum, authority, remedy, and next-step
  recommendations grounded in sources.
- `US-027` As a litigator, I want recommendations to incorporate bench context
  once that data is reliable.
- `US-028` As a reviewer, I want to accept, reject, edit, or defer a
  recommendation and preserve that audit trail.

### Contracts and compliance

- `US-029` As corporate legal, I want clauses and obligations extracted from
  uploaded contracts.
- `US-030` As legal ops, I want obligations to become tasks and calendar items.
- `US-031` As a reviewer, I want extraction failures to be explicit and
  recoverable.

### Billing and payments

- `US-032` As finance, I want time entries, invoices, payment links, and sync
  status in one billing flow.
- `US-033` As a partner, I want outstanding recoveries visible at matter and
  portfolio level.

### Clients, advocates, communications, and KYC

- `US-034` As an associate, I want structured client profiles linked to matters.
- `US-035` As legal ops, I want communication logs for email, calls, meetings,
  and WhatsApp.
- `US-036` As a user, I want document and notice sharing by template-driven
  email.
- `US-037` As an enterprise buyer, I want optional KYC and verification status
  for clients where policy requires it.

### Outside counsel and portfolio

- `US-038` As a GC, I want outside counsel assignments, budgets, and approved
  spend in one workspace.
- `US-039` As finance, I want vendor and spend analytics across matters.

### Admin, plans, and enterprise

- `US-040` As an owner, I want teams, access, ethical walls, audit export, and
  notification oversight in admin.
- `US-041` As an enterprise admin, I want SSO, entitlements, branding, and
  retention controls.
- `US-042` As a security lead, I want audit completeness, secret hygiene,
  backup and restore evidence, and deployment clarity.

### Support and deployment

- `US-043` As a user, I want in-app help and feedback without leaving the app.
- `US-044` As a buyer, I want SaaS, private deployment, and air-gapped
  packaging options.
- `US-045` As IT, I want an air-gapped mode with no external API calls.

### Case summary and briefing

- `US-046` As a litigator, I want a structured matter or case summary with key
  facts, issues, chronology, and current posture.
- `US-047` As a partner or GC, I want that summary exportable as DOCX or PDF
  for internal review and client sharing.

### Translation and localization

- `US-048` As a lawyer, I want legal translation between English, Hindi, and
  supported regional languages while preserving legal terminology.
- `US-049` As a reviewer, I want side-by-side source and translated text before
  a translated document is exported or shared.
- `US-050` As a workspace owner, I want to invite a client by email so they
  can sign in to a branded portal scoped to their matters only.
- `US-051` As a workspace owner, I want to invite an outside counsel by email
  with explicit per-matter scope so they can collaborate without seeing
  unrelated matters.
- `US-052` As a client portal user, I want to see the status, hearings, and
  shared documents of my matters and reply to the firm's communications.
- `US-053` As a client portal user, I want to submit KYC information via the
  portal so I do not have to email scanned documents.
- `US-054` As an outside-counsel portal user, I want to upload work product
  and submit invoices on the matters I have been granted, so the firm has
  one canonical work-product and billing trail.
- `US-055` As an outside-counsel portal user, I want my time entries to flow
  into the firm's billing system without me leaving the portal.

## 14. Test Catalog

### 14.1 Functional test cases

- `FT-001` Bootstrap workspace -> owner session issued.
- `FT-002` Login with valid credentials -> auth context loads.
- `FT-003` Suspended membership -> existing token rejected.
- `FT-004` Duplicate matter code -> proactive validation blocks create.
- `FT-005` Intake failure keeps user input and suggests next valid code.
- `FT-006` Matter workspace shows correct overview for empty matter.
- `FT-007` Restricted-access matter hidden from unauthorized user.
- `FT-008` Matter grant and ethical wall changes are audited.
- `FT-009` Matter attachment upload with valid PDF -> parsed and visible.
- `FT-010` Unsupported file upload -> clear 4xx recovery path.
- `FT-011` OCR fallback on scanned PDF -> text extracted.
- `FT-012` Low-confidence OCR pages rejected from chunking.
- `FT-013` Inline document viewer loads, pages navigate, zoom works.
- `FT-014` Viewer search finds text within the document.
- `FT-015` Annotation create, list, and archive works.
- `FT-016` Matter summary GET returns structured summary.
- `FT-017` Summary regenerate returns fresh payload.
- `FT-018` Summary DOCX export succeeds.
- `FT-019` Summary PDF export succeeds.
- `FT-020` Research query returns authorities with source types.
- `FT-021` No-result research state renders actionable UX.
- `FT-022` Query normalization improves citation or bench retrieval.
- `FT-023` Judge profile page loads recent authorities and matter context.
- `FT-024` Bench-match endpoint returns a scoped match explanation.
- `FT-024A` Bench strategy context endpoint returns cited prior-judgment
  patterns for the same judge or likely bench.
- `FT-025` Draft template list route returns available templates.
- `FT-026` Draft stepper preview renders partial draft safely.
- `FT-027` Draft generation persists a new version.
- `FT-028` Draft request-changes state transition succeeds.
- `FT-029` Draft approve fails closed without verified citations.
- `FT-030` Draft finalize locks future mutations.
- `FT-031` Each of the 8 draft types generates with the right schema.
- `FT-024B` Appeal-strength analyzer endpoint returns per-ground
  citation coverage + supporting authorities + concrete edit
  suggestions; cross-tenant matter returns 404; structural test
  asserts the response contains no win/lose/probability/favourable/
  tendency language.
- `FT-031B` Appeal-strength UI panel renders green/amber/red per
  ground + the suggestion list; weak-evidence path is visually
  distinct and labelled as such.
- `FT-031A` Appeal draft generation consumes bench strategy context when
  available and refuses unsupported judge-tendency claims.
- `FT-032` Template-based draft start path uses saved template metadata.
- `FT-033` Batch notice generation produces isolated outputs per recipient.
- `FT-034` Recommendations list route returns prior recommendations.
- `FT-035` Recommendation generation preserves option-level citations.
- `FT-036` Recommendation decision route persists accept, reject, edit, and
  defer.
- `FT-037` Hearing create and patch routes update state correctly.
- `FT-038` Hearing completion auto-creates follow-up task when enabled.
- `FT-039` Hearing-pack generate, fetch, and review all work.
- `FT-040` Matter reminders route returns only current-tenant reminders.
- `FT-041` Admin reminders page shows queued, sent, and failed states.
- `FT-042` Calendar week view merges hearings, deadlines, and custom events.
- `FT-043` Calendar sync creates or updates remote events without duplication.
- `FT-044` Client create, list, update, archive works.
- `FT-045` Matter-client assignment and unassignment works.
- `FT-046` Communication log create and read works.
- `FT-047` Email send action picks template, recipients, and attachment.
- `FT-048` Delivery webhook updates communication status.
- `FT-049` KYC create and status update flow works where enabled.
- `FT-050` Contract create, workspace read, and update work.
- `FT-051` Contract clause extraction success persists rows.
- `FT-052` Contract obligation extraction success persists rows.
- `FT-053` Contract attachment parse and retry flows work.
- `FT-054` Obligations can be promoted to tasks and calendar items.
- `FT-055` Outside counsel CRUD, assignment, and spend summaries work.
- `FT-056` Invoice create appears in billing tab.
- `FT-057` Pine Labs payment-link create and sync work.
- `FT-058` Payment config readiness path gates UI correctly.
- `FT-059` Teams CRUD and scoping toggle work.
- `FT-060` Admin audit export JSONL and CSV work.
- `FT-061` Admin teams page and admin notifications page are role-gated.
- `FT-062` SSO login flow works for configured enterprise tenants.
- `FT-063` Support page loads help docs and feedback form.
- `FT-064` Air-gapped deployment mode rejects external-provider usage.
- `FT-065` Matter summary extracts key facts, issues, chronology, and next
  steps from a populated matter.
- `FT-066` Matter summary DOCX and PDF exports preserve expected sections and
  reviewer-facing structure.
- `FT-067` Legal translator converts supported language pairs while preserving
  configured legal glossary terms.
- `FT-068` Side-by-side translation review, edit, and export flow works for a
  supported document.
- `FT-070` PortalUser bootstrap: workspace owner POSTs portal invite, system
  mints a single-use magic link, AutoMail sends it; the link verifies once,
  binds to the inviting email, and expires after 30 minutes.
- `FT-071` Portal session cookie is HttpOnly, SameSite=Lax, scoped to
  /portal/*, and never accepted by the /app routes (cross-surface token
  rejection test).
- `FT-072` A client portal user GET /api/portal/me returns only the matters
  granted via MatterPortalGrant; another tenant's matters return 404.
- `FT-073` Client portal Comms reply lands in the firm's internal
  Communications log with `direction='inbound'` and the originating
  PortalUser id.
- `FT-074` Outside-counsel portal upload + invoice submission lands the
  document under the firm's matter and the invoice in `needs_review` state;
  cross-counsel visibility stays off by default.
- `FT-075` Revoking a MatterPortalGrant invalidates active portal sessions
  for that grant within the next request cycle (no stale-session leak).

### 14.2 Non-functional test cases

- `NFT-001` P95 page load for primary authenticated routes is within agreed SLO.
- `NFT-002` P95 research response time stays within agreed SLO on production
  corpus size.
- `NFT-003` P95 draft generation latency stays within agreed SLO by draft type.
- `NFT-004` Reranker-on research throughput holds under concurrent user load.
- `NFT-005` Matter list and portfolio routes paginate correctly under large
  tenant data volume.
- `NFT-006` Notification queue retries survive provider outages.
- `NFT-007` Calendar sync retries do not create duplicates.
- `NFT-008` Contract extraction handles large documents within timeout and
  memory budget.
- `NFT-009` Upload pipeline handles large PDFs without runaway temp files.
- `NFT-010` Backup and restore drill restores the platform within target RTO/RPO.
- `NFT-011` Audit export works at high row counts or falls back to background
  job without timing out.
- `NFT-012` Observability surfaces request ID, tenant ID, user ID, and matter ID
  on critical logs.
- `NFT-013` Mobile and narrow-laptop layouts remain usable on matter, drafting,
  billing, and viewer screens.
- `NFT-014` Accessibility baseline passes keyboard, focus, and axe checks on the
  authenticated spine.
- `NFT-015` Multi-tenant search and vector retrieval remain scoped under load.
- `NFT-016` Migration workflow runs as a controlled release step, not as runtime
  startup side effect.
- `NFT-017` Air-gapped deployment runs without outbound egress.
- `NFT-018` Production corpus benchmark report is committed for every major
  source-family addition.
- `NFT-019` Matter summary generation degrades safely under provider throttling
  and avoids redundant recompute where caching is expected.
- `NFT-020` Translation latency, glossary application, and document rendering
  stay within agreed SLOs for supported language pairs.

### 14.3 Security review test cases

- `SEC-001` Browser session storage does not expose bearer tokens to scriptable
  localStorage in enterprise mode.
- `SEC-002` Suspended users and revoked sessions lose access immediately.
- `SEC-003` Cross-tenant matter, client, contract, invoice, and reminder access
  is denied.
- `SEC-004` Matter-level grants and walls prevent horizontal access escalation.
- `SEC-005` Upload validation blocks malformed files before disk write.
- `SEC-006` Malware scanning is enforced and fail-closed in production.
- `SEC-007` Public webhooks require signature validation.
- `SEC-008` Payment webhooks are idempotent and tenant-safe.
- `SEC-009` Provider payload redaction removes sensitive values before storage.
- `SEC-010` Auth and bootstrap routes are rate-limited.
- `SEC-011` Expensive AI routes have tenant-safe abuse controls.
- `SEC-012` Draft preview and summary routes do not leak raw provider internals.
- `SEC-013` Tenant AI policy blocks disallowed models server-side.
- `SEC-014` Prompt-injection and data-exfiltration resistance is benchmarked on
  research, drafting, and recommendations.
- `SEC-015` Search and retrieval never leak another tenant's private documents.
- `SEC-016` KYC artifacts are never embedded into shared retrieval by default.
- `SEC-017` Secret values are sourced from managed secret storage in production.
- `SEC-018` Deploy-time migrations are separated from runtime request serving.
- `SEC-019` Backup artifacts and audit exports are access-controlled.
- `SEC-020` SSO role mapping cannot escalate beyond configured policy.
- `SEC-021` Support and feedback submissions respect tenant boundaries and PII
  handling rules.
- `SEC-022` Air-gapped mode prevents external model, email, analytics, and
  telemetry calls unless explicitly whitelisted.
- `SEC-023` Reranker or embedder failures degrade safely without bypassing
  authorization or leaking private text.
- `SEC-024` Legal-source licensing and usage rules are tracked for paid
  commentary sources.
- `SEC-025` Translation workflows do not send tenant-restricted text to
  disallowed providers or unsupported language routes.
- `SEC-026` Matter summary generation respects tenant AI policy and does not
  leak raw provider internals or unauthorized private context.

## 15. Claude Code Execution Contract

Before any CaseOps feature planning, implementation, review, or rewrite:

1. Read this PRD.
2. Read `docs/WORK_TO_BE_DONE.md`.
3. Read `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`.
4. Read `docs/STRICT_BUG_TASKLIST_2026-04-22.md` when the task touches bugs.
5. Read `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` when the task touches product
   scope, hardening, or architecture.

Claude must then:

- map the task to one or more journey IDs
- map the task to one or more module IDs
- identify whether the task is `Shipped`, `Partial`, or `Missing` today
- identify user stories and test IDs affected
- check existing routes, services, pages, and tests before claiming a gap
- reconcile external audit IDs such as `MOD-TS-*` to PRD journeys, modules,
  user stories, and test IDs before accepting a spreadsheet's status claim
- refuse random scope additions that are not mapped back to this PRD
- update this PRD and the relevant ledger when scope or status changes

Additional mandatory rules:

- No product claim may outrun code, tests, or benchmark proof.
- No vector-data feature may claim production readiness unless Voyage,
  Opus-assisted enrichment, reranker-on retrieval, and the 4.8+/5 quality gate
  are satisfied.
- No feature is complete without functional, non-functional, and security
  coverage mapped to this PRD.
- UI work must prefer simple, obvious, lawyer-friendly workflows over feature
  density.

## 16. Delivery Priorities

### Immediate build sequence

1. Enterprise stop-ship controls
   - browser session hardening
   - migration safety
   - enforced malware scanning
   - AI abuse controls

2. Core missing customer value
   - statutes and bare acts
   - tribunal corpus and workflows
   - generic tasks and deadlines
   - real reminders and notifications
   - calendar UI
   - clients communications and AutoMail
   - notice factory

3. Strategic differentiation
   - bench-aware intelligence
   - judge-driven strategy
   - format-to-forum mapping
   - arbitrator intelligence

4. Enterprise completion
   - SSO
   - plan entitlements
   - private and air-gapped deployment
   - backup and restore evidence
   - secret rotation and operations runbooks

## 17. Final Product Positioning

CaseOps should be positioned as:

"The legal work operating system that helps law firms and legal teams manage
matters, prepare for the right bench, generate the right format, and move from
research to draft to hearing to recovery with grounded legal evidence and
enterprise controls."
