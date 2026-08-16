# Product Requirements Document: CaseOps IP Law Firm Platform

**Document ID:** PRD-IPLF-2026-08-01  
**Status:** Planning PRD; implementation not started by this document  
**Owner:** CaseOps Product and Engineering  
**Primary customer:** Indian IP and full-service law firms  
**Initial product focus:** Indian trademark portfolio, prosecution, opposition, research, and docketing  
**Program scope:** Trust recovery, legal-data provenance, notifications, court tracking, IP docketing, source-grounded AI, and broader IP expansion  
**Last updated:** 15 August 2026
**Review status:** Six scope/architecture review passes plus continuous-execution gate review

This PRD converts the 16-item law-firm feedback set into an implementation-ready program. Passes 5 and 6 reassessed it against the current repository at source commit `cadb46d`, removed parallel ownership, then corrected subtler misses around `CompanyNotice`, `TrackedCase`, Matter timeline/next-hearing provenance, billing evidence, the absence of a true generic import owner, and premature M2 migrations. It supersedes no deployed contract and does not authorize production data mutation, scraping, provider enrollment, legal-content publication, or autonomous filing. Milestone exit criteria remain independently traceable, but repository-controlled implementation runs as one dependency-scheduled program and compatible milestones may share an integration PR and release train.

## 1. Executive summary

CaseOps must become a reliable operating system for an IP law firm, beginning with Indian trademark work. The current product has useful matter-management, hearing, research, statute, authority, judge, notification, and case-tracking foundations, but it does not yet provide a real IP docket. Several existing foundations also fail the trust standard required for legal work: most seeded Bare Act sections have no text or section-level source, authority cards do not consistently expose their source URLs, scheduled legal-data jobs are failing in production, and reminder execution can succeed while most intended messages are suppressed.

The program therefore has two inseparable tracks:

1. **Restore trust in existing legal workflows.** A user must be able to tell whether a source is authoritative, whether a search actually ran, whether a scheduled integration is fresh, and whether a reminder reached its recipient.
2. **Build a first-class IP domain.** A trademark application, its identifiers, prosecution events, opposition proceeding, evidence, deadlines, hearing, registry snapshots, documents, and linked litigation must be modeled explicitly rather than flattened into a generic Matter.

The product should not attempt to beat mature IP products by copying every screen. Its differentiator is a connected proof chain: registry event to docket deadline, document, task, notification, research authority, pleading, lawyer approval, and audit record. Every AI output must point back to the exact workspace record or external legal source on which it relies.

The IP program is an extension of CaseOps, not a second product inside the repository. New `ip_*` persistence is justified only for legal facts or evidence that existing CaseOps records cannot represent. Cross-cutting work management, intake, access, notices, communications, billing, AI execution, provider operations, imports, and reports retain or deliberately converge on one shared owner and one user-facing control plane.

## 2. Evidence and current-state baseline

The following baseline was established through read-only repository and production inspection on 1 August 2026:

- Trademark support is limited primarily to an `ip_trademark` intake classification. There is no dedicated trademark portfolio, application, opposition, renewal, registry-sync, or watch domain.
- The statute seed contains 3,393 section rows. Of these, 3,302 have no section text and 3,392 have no section-level URL. Some populated rows contain provision mismatches or editorial commentary rather than clean enacted text.
- The research API carries `source_reference`, but the principal research result card does not render it.
- Canonical `judges`, `judge_aliases`, and appointment tables already exist, but current judge-profile authority mapping still falls back to free-text/JSON matching and recent-authority cards omit source links.
- The reminder worker is scheduled and executes, but recent production batches were predominantly suppressed. A completed worker run therefore does not prove recipient delivery.
- CaseOps already has `notification_delivery_intents` with idempotency/retry/dead-letter foundations, while hearing reminders use a separate direct-provider path and status model. The program must converge these paths rather than create a third delivery subsystem.
- CaseOps already has `MatterTask`, `MatterHearing`, `MatterDeadline`, an aggregated calendar feed, external calendar synchronization, and hearing-reminder scheduling. IP may add legal deadline calculations and richer IP links, but it must extend these shared operational records rather than create `ip_tasks` or `ip_hearings` with competing status and completion rules.
- CaseOps already has `MatterNextHearingHistory`, `MatterNextHearingSuggestion`, `MatterActivity`, and a timeline compositor. IP hearing provenance and linked timelines must extend/compose these owners; copying IP legal events into Matter activity, audit and outbox histories would create competing evidence.
- CaseOps already has `MatterIntakeRequest`, `MatterConflictCheck`, intake promotion, conflict review, clients/KYC, teams, `MatterAccessGrant`, `EthicalWall`, `PortalUser`, and `MatterPortalGrant`. These services are Matter-shaped today, but their behavior is not IP-specific. They must be generalized through expand/backfill/switch/contract migrations; separate IP intake, conflict, internal-access, or portal-grant engines are prohibited.
- CaseOps already has a company-wide `CompanyNotice` register with zero/multi-Matter links, optional file, owner, reply dates/state, service/routes, `/app/notices`, activity reporting and storage governance. Current standalone visibility is broad, so IP must add target links and fail-closed IP authorization rather than a second notice register or an unsafe link to a restricted record.
- CaseOps already has `TrackedCase` provider identities, bookmarks, hash-based updates, polling, source URLs, notifications and eCourts UI, plus Matter court sync/orders/cause lists and next-hearing provenance. These remain canonical for court/CNR tracking. An IP-office registry snapshot is distinct evidence but must reuse existing connector readiness/support/cost/provider-operation controls and never copy court updates.
- CaseOps has separate Matter and Employee bulk-import jobs/rows/services, not one generic persisted import owner. It also has invoice/payment/export records, Matter time/billing, outside-counsel spend, `Draft`/`DraftReview`, `DraftingDataExtractionField`, `Recommendation`, `ModelRun`, tenant AI policy, provider-operations aggregation, connector readiness/support/cost, and several reporting/export surfaces. IP uses neutral import orchestration for new work, typed legal cost/evidence links, target adapters, and report definitions; it does not relabel a Matter-specific importer or build IP-only control planes.
- CaseOps already has a versioned public `/guide` and authenticated navigation/help content. Product Guide mode must index and extend that maintained corpus and link users into existing screens; it is not a second hand-written help center.
- CaseOps already owns statutes, statute sections, legal-update source records, authority documents/chunks/citations, source adapters, courts, judges, aliases, and appointments. Source trust work extends those owners and a shared provenance contract; it does not add a second canonical `legal_source_records` library.
- The nightly case-tracking scheduler is enabled but reports permission denied. Authority-metadata and legal-update schedulers showed the same failure status during inspection.
- The deployment helper already contains Cloud Run Invoker grant logic, indicating production/IaC drift or a bypassed deployment path rather than a wholly missing design. M1 must reconcile and prevent that drift.
- The configured eCourts-related provider is a non-government commercial provider. Product copy and audit data must not describe it as an official eCourts API.
- CaseOps already has `TenantMicrosoft365Configuration`, user calendar connections, calendar event candidates/sync rows, inbound email aliases/events, Drive candidates, and a currently Matter-oriented `Communication` model/service. IP inbox/calendar work must extend these connector and delivery services through typed IP links; a second raw-email, OAuth, calendar-sync, or communication subsystem would create duplicate sends/imports and conflicting retention.
- MFA policy and recent step-up primitives already exist for sensitive billing/admin operations. IP rule activation, access/break-glass, exports/purge, terminal lifecycle, provider replay, and other high-risk commands must reuse and extend that service rather than inventing a second reauthentication mechanism.
- The backup runbook claims tighter RPO/RTO targets than the dated restore evidence proves. The 24 April 2026 drill proved a database clone, not application cutover, current-schema workflow recovery, object-store restoration, notification/outbox replay, or regional-loss recovery. The runbook also marks tenant export/purge automation as not built. M2 recovery/export-dry-run and M7 purge/offboarding gates remain red until current deployed configuration and full-stack drills reconcile these claims.
- The supplied tenant login could not be authenticated during assessment. Tenant-specific search and reminder incidents remain reported incidents, while the underlying systemic defects above were independently observed.

## 3. Product principles

1. **Legal truth before feature volume.** Incomplete or unverified legal text is hidden or clearly quarantined, never presented as complete.
2. **Identifiers are not labels.** Application, registration, opposition, rectification, CNR, and court case numbers are typed, source-attributed, independently searchable identifiers.
3. **A docket is event-driven.** Deadlines derive from verified events and versioned rules, with lawyer confirmation and an auditable override path.
4. **No silent automation.** Every sync, reminder, AI action, retry, suppression, and failure has visible state.
5. **Source or abstain.** Research and AI outputs provide a resolvable source or explicitly state that a source could not be verified.
6. **Human control of legal acts.** CaseOps may suggest, prepare, reconcile, and remind. It must not file, serve, waive, close, or finalize a legal document without authorized human confirmation.
7. **Tenant and matter permissions travel with the data.** Search, chat, export, notifications, and client access enforce the same permissions as the originating record.
8. **Raw provider truth is preserved.** Normalized statuses improve usability, but original registry/provider values and snapshots remain available for audit.
9. **Operations are part of the product.** Scheduler health, source freshness, provider cost, and replay are product requirements, not deployment afterthoughts.
10. **India-first, jurisdiction-ready.** Initial rules and terminology target Indian trademark practice, while schemas retain jurisdiction and rule-version boundaries.

## 4. Goals and success outcomes

### 4.1 Product goals

1. Provide a complete searchable trademark portfolio and opposition docket for an Indian IP law firm.
2. Make hearing, deadline, registry, research, and notification status observable and recoverable.
3. Ensure every published statute provision and authority result exposes verifiable provenance.
4. Reduce manual docket entry through controlled imports, registry reconciliation, and event-driven deadlines.
5. Let lawyers find, review, and draft from matter and portfolio context without losing the source trail.
6. Give docketing teams, lawyers, partners, clients, and platform operators interfaces appropriate to their roles.
7. Establish a shared IP foundation that can later support patents, designs, copyright, domain names, licensing, and IP litigation.

### 4.2 Measurable outcomes

- 100% of displayed authority cards have a safe, resolvable source action or an explicit `source unavailable` state.
- 100% of displayed Bare Act provisions have verification status, source, version/effective date where available, retrieval time, and content hash.
- 0 AI-generated statute text is labelled or stored as authoritative statutory text.
- 100% of critical docket deadlines record the triggering event, rule version, calculation, confirmer, and override history.
- 100% of notification intents have one observable terminal or retryable outcome per channel.
- No critical reminder is silently cancelled because of provider suppression.
- Scheduled case-tracking and legal-data jobs achieve at least 99.5% successful scheduled executions over a rolling 30-day period after general availability.
- Registry-enabled trademark records display a freshness timestamp and sync health.
- 95% of a lawyer-approved golden research query set produces either relevant results or a correct, diagnosable no-result state.
- 0 cross-tenant records, source caches, chat citations, exports, or notifications are exposed in automated security tests.
- Pilot users can create or import a trademark, docket an opposition, confirm deadlines, attach evidence, schedule a hearing, receive a reminder, and generate a source-grounded hearing brief without administrator assistance.
- 100% of active critical deadlines have a named primary owner, backup/escalation owner, acknowledgement state, and current coverage status; leave or deactivation cannot leave critical work unowned.
- 100% of inbound registry, court, client, and associate communications selected for docketing reach a resolved `linked`, `duplicate`, `irrelevant`, or `exception` state with preserved original evidence.
- 100% of filed applications in the pilot have the filing-basis, applicant, representation, class/specification, use/priority, agent/address-for-service, fee, acknowledgement, and source fields required by the activated filing schema.

## 5. Non-goals and prohibited behavior

- No automated legal advice or representation that an AI answer is a lawyer-approved conclusion.
- No guaranteed outcome, success probability, judge favorability score, judge shopping, or `best judge` recommendation.
- No unattended filing, service, deadline waiver, proceeding closure, payment, renewal instruction, or client communication.
- No captcha bypass, access-control circumvention, or uncontracted scraping of IP India, eCourts, Indian Kanoon, or competitor services.
- No description of a commercial provider as an official government source.
- No silent replacement of original filenames, registry values, identifiers, or documents.
- No global chatbot with unrestricted tenant knowledge.
- No full patent, design, and copyright workflow in the first trademark MVP.
- No assumption that a generic litigation pleading template is suitable for trademark prosecution or opposition.
- No publication of incomplete statute coverage merely to increase act or section counts.

## 6. Personas and jobs to be done

| Persona | Primary jobs | Typical access |
|---|---|---|
| Firm Owner | Configure governance, approve integrations, inspect risk and adoption | All tenant administration and reports |
| IP Practice Head / Partner | Review portfolio risk, deadlines, strategy, pleadings, and client reporting | All IP records for permitted clients; approvals |
| Docketing Manager | Import portfolios, reconcile registry events, confirm rules, monitor deadlines and delivery | IP portfolio administration without tenant billing/security administration |
| Trademark Attorney / Associate | Prosecute applications, manage opposition work, research, draft, and prepare hearings | Assigned clients/assets/proceedings |
| Paralegal / Docketing Specialist | Enter events, classify documents, prepare filings, schedule hearings, follow up | Assigned operational records; no final legal approval |
| IP Litigator | Link opposition to court matters, research authorities, prepare pleadings and hearings | Assigned proceedings and matters |
| Advisory Lawyer | Search client/IP information and obtain guided answers without learning every navigation path | Permission-scoped read and drafting workflows |
| Knowledge / Research Lawyer | Curate sources, golden queries, statute verification, authority quality, and templates | Legal-source administration; no tenant security administration |
| Filing / Foreign Associate Coordinator | Prepare filing instructions, monitor acknowledgements, manage local/foreign agents, and reconcile invoices | Assigned filings, correspondence, and provider/associate records |
| IP Finance / Renewals Coordinator | Manage official fees, associate charges, renewal quotes, payment evidence, and client instruction | Fee and renewal operations; no legal approval unless separately granted |
| Client Portal User | View approved portfolio status, upcoming deadlines, documents, and reports | Explicitly shared client records only |
| Tenant Auditor | Inspect event, document, AI, notification, and integration history | Read-only audit access |
| Risk / Records Manager | Govern retention, legal holds, access reviews, exports, and offboarding evidence | Policy and audit metadata; content only where separately permitted |
| Platform Operator | Monitor provider health, scheduler state, dead letters, cost, and replay | Platform operations; no legal document content unless separately authorized |

## 7. Permission model

Do not add new fixed global roles merely for this program. Add only the IP-specific capabilities below. Existing CaseOps capabilities remain the owner for documents, drafting, research, AI generation, notifications, calendar, intake, conflicts, portal grants, communications, provider operations, and audit export; IP routes require the relevant existing capability plus IP record access where both concerns apply.

| Capability | Allows |
|---|---|
| `ip:read` | View permitted IP assets, applications, proceedings, events, deadlines, and reports |
| `ip:write` | Create and edit operational IP records |
| `ip:import` | Upload, validate, reconcile, and commit portfolio imports |
| `ip:approve` | Confirm IP deadlines/lifecycle/source reconciliation and close/reopen IP proceedings; draft review/finalization still uses existing `drafts:*` capabilities |
| `ip:filing_prepare` | Prepare filing/service packages and record draft transaction evidence |
| `ip:filing_confirm` | Confirm an actual filing/service transaction, acknowledgement, defect, or acceptance from evidence |
| `ip:fees_view` | View permitted official/associate cost items, quotes, linked proof/receipts, and billing links |
| `ip:fees_manage` | Maintain approved cost items, quotes, immutable proof/receipt links, and reconciliation links without issuing invoices, changing linked accounting state, or collecting client payments |
| `ip:rules_propose` | Propose/version deadline, form, and fee-rule data without activating it |
| `ip:rules_activate` | Activate/retire lawyer-approved rule versions after fixtures pass |
| `ip:taxonomy_admin` | Maintain approved document, event, status, form, and correspondence taxonomies |
| `ip:registry_sync` | Link records, trigger refresh, and resolve registry reconciliation conflicts |
| `ip:watch_manage` | Create watch profiles and disposition watch hits |
| `audit:read` | Read permitted tenant audit events; export remains governed by existing `audit:export` |

Existing capability reuse is mandatory:

| Existing capability | IP use |
|---|---|
| `documents:upload`, `documents:manage` | Upload/classify/version IP documents and create/manage accepted `CompanyNotice` records under current notice routes; `ip:read`/`ip:write` and IP record access additionally apply for an IP target |
| `drafts:create`, `drafts:edit`, `drafts:generate`, `drafts:review`, `drafts:finalize` | IP pleading generation, review, and finalization against an IP target |
| `authorities:search`, `authorities:ingest`, `authorities:annotate` | Research, source opening, curation, ingestion, and annotations; statute-specific mutations keep their current route gates |
| `ai:generate`, `recommendations:generate`, `recommendations:decide` | Workspace Q&A, intelligent review, and approval through existing AI owners |
| `calendar:view`, `calendar:sync`, `notifications:manage` | Calendar access/sync, own preferences, tenant notification policy, suppression recovery, and tests |
| `intake:submit`, `intake:triage`, `intake:promote`, `conflicts:run`, `conflicts:resolve` | IP intake and firm-conflict work in the existing queues |
| `matter_access:manage`, `portal:invite`, `portal:manage_grants` | Shared internal/portal grant administration for Matter or IP targets |
| `communications:view`, `communications:write` | IP-linked communication history and sends |
| `matters:write`, `calendar:view`, `calendar:sync` | Existing Matter-target task/hearing/deadline actions and shared views/sync. The same service uses `ip:write` for an IP-only target; a dual-linked action satisfies both target policies or the stricter policy |
| `workspace:admin` | Existing provider-operations/readiness/replay and tenant integration administration |
| `audit:export` | Existing owner-only audit export; `audit:read` is the only new cross-cutting capability in this PRD |

Client portal permissions are explicit record grants. Possession of a client association must not automatically expose every asset, proceeding, document, note, AI output, or invoice for that client.

### 7.1 Default capability roles

| Capability tier | Default roles | Notes |
|---|---|---|
| Read/search: `ip:read`, existing `authorities:search`, existing `calendar:view` | Owner, Admin, Partner, Member, Paralegal, Viewer where underlying record access permits | Read permission never bypasses client/record/ethical-wall scope; AI Q&A separately requires existing `ai:generate` |
| Operational write: `ip:write`, `ip:filing_prepare` plus existing document/communication gates for those actions | Owner, Admin, Partner, Member, Paralegal | Viewer excluded; shared services choose Matter/IP gates from the target rather than requiring Matter permission for IP-only work |
| Legal/filing approval: `ip:approve`, `ip:filing_confirm` plus existing `drafts:review`/`drafts:finalize` where a draft is involved | Owner, Admin, Partner by default | One capability does not substitute for the other concern's gate |
| Bulk/import/watch/registry: `ip:import`, `ip:watch_manage`, `ip:registry_sync` | Owner and Admin by default | Delegable to a custom Docketing Manager role |
| Fee operations: `ip:fees_view` | Owner, Admin, Partner | Custom finance role may receive it |
| Fee management: `ip:fees_manage` | Owner and Admin | Custom finance role may receive it; no legal approval implied |
| Rules/taxonomy: `ip:rules_propose`, `ip:taxonomy_admin` | Owner and Admin | Proposal does not activate legal rules |
| Rule activation: `ip:rules_activate` | Owner, Admin, Partner | Requires four-eyes policy: proposer cannot activate same version |
| Client sharing: existing `portal:manage_grants` plus `ip:approve` for an approved IP publication | Owner and Admin by default | Every share is previewed and audited; custom Partner delegation must carry both capabilities |
| Tenant integrations/provider operations: existing `workspace:admin` | Owner and Admin | Redacted operations only; replay adds step-up/cost confirmation without a duplicate capability by default |
| Tenant audit: `audit:read` | Owner and Admin | Existing `audit:export` remains owner-only unless separately changed |

### 7.2 Repository integration rules for access and rollout

1. Add every genuinely new capability to backend `services/capability_catalog.py`, the frontend `lib/capabilities.ts` union/default maps, custom-role catalog/validation, and role-guard tests in the same change. Before adding one, document why no existing capability in the reuse table governs the action.
2. Every mutating FastAPI route uses `require_capability`; service methods still validate company, record access, lifecycle, and actor constraints.
3. Product access has three independent gates: capability (may this person act), billing entitlement (has the company purchased/been granted the module), and rollout safety flag (is the feature enabled for this environment/company cohort). One gate never substitutes for another.
4. Initial entitlement keys are `ip_workspace`, `ip_registry_sync`, `ip_watch`, `ip_ai`, `ip_client_portal`, and provider-specific quota/cost keys. Entitlements do not contain secrets.
5. Rollout flags are server-authoritative, environment-aware, auditable, and fail closed. Hiding navigation alone is not a feature gate.

## 8. Scope and release boundaries

### 8.1 Release A: Trust recovery

- Bare Acts provenance and quarantine.
- Research and judgment source actions.
- Research no-result diagnostics and golden queries.
- Notification delivery observability and recovery.
- Case-tracking and legal-data scheduler repair, freshness, and replay.
- Canonical judge/bench source-linked authority navigation foundation.

### 8.2 Release B: Trademark docketing MVP

- Client instruction, conflict-clearance reference, and pre-filing search project linkage.
- Trademark asset and application records.
- Typed application and registration identifiers.
- Portfolio listing, filters, saved views, bulk actions, and export.
- Controlled portfolio import and reconciliation.
- Filing package, official/associate fee, submission, acknowledgement, defect, and receipt tracking.
- Prosecution events, documents, tasks, deadlines, hearings, and renewals.
- Manual sourced registry observations/status and the future-provider reconciliation contract; automated registry sync is not an M3 claim.
- Matter linkage for related litigation.

### 8.3 Release C: Opposition and trademark work product

- Opposition, rectification, cancellation, and appeal proceedings.
- Independent opposition number and proceeding lifecycle.
- Applicant/opponent role-specific workflows.
- TM-O, counterstatement, evidence, reply, hearing, order, and appeal stages.
- Multi-class/partial opposition, service, translation, adjournment, written argument, and non-appearance paths.
- Rectification, non-use removal, cancellation, restoration, and post-registration recordal foundation.
- IP document taxonomy and source-grounded pleading templates.

### 8.4 Release D: Search, watch, AI, and client operations

- Trademark clearance-search workspace.
- Journal and portfolio watch.
- Contracted IP-office registry sync, immutable snapshots/diffs, readiness/support/cost/replay, and reconciliation.
- Similarity/watch-hit review and enforcement handoff.
- Madrid outbound applications and inbound India designations with WIPO/office events and independent designation state.
- Assignment/transmission, registered-user/licence, name/address, associated/divisional mark, and other post-registration recordals.
- CaseOps Guide and Ask this Workspace.
- Intelligent review and analogous-authority recommendations with sources.
- Client portal views and scheduled portfolio reports.

### 8.5 Release E: Broader IP suite

- Patent families, priority, PCT/national phase, prosecution, office actions, and annuities.
- Designs, copyright, domain names, customs/enforcement records.
- Assignments, licences, coexistence agreements, royalties, obligations, and linked contract/matter workflows.

## 9. Feedback traceability

| Feedback | Requirement coverage | Primary journeys | Milestone |
|---:|---|---|---|
| 1. Trademark listing missing | IP-PORT-01 through 10 | UJ-02 to UJ-05 | M3 |
| 2. Bare Acts incomplete | TRUST-BA-01 through 12 | UJ-15, UJ-48 | M1 |
| 3. Hearing notification not received | NOTIF-01 through 24 | UJ-10, UJ-11 | M1/M3 |
| 4. IP docket and pleadings differ | IP-PROS-01 through 12; IP-DRAFT-01 through 10 | UJ-06, UJ-12, UJ-13, UJ-24 | M3/M4 |
| 5. Application number required | IP-ID-01 through 08 | UJ-03 to UJ-07 | M2/M3 |
| 6. Opposition number required | IP-OPP-01 through 24 | UJ-12, UJ-13, UJ-38 | M4 |
| 7. Document names shared | IP-DOC-01 through 12 | UJ-14 | M2/M4 |
| 8. Iolite and MikeLegal benchmark | COMP-01 through 08 | UJ-02 to UJ-28 | All product milestones |
| 9. Advisory user and chatbot | AI-GUIDE-01 through 12 | UJ-22, UJ-23 | M6 |
| 10. Intelligent review needs judgment URLs | TRUST-RSCH-01 through 14; AI-REV-01 through 10 | UJ-16 to UJ-18 | M1/M6 |
| 11. Notifications and eCourts fully integrated | TRACK-01 through 14; NOTIF-01 through 24 | UJ-10, UJ-19, UJ-25 | M1/M5 |
| 12. Indian Kanoon/eCourts references | SRC-01 through 12 | UJ-16 to UJ-19 | M1/M5 |
| 13. Uploaded-case source links do not open | TRUST-RSCH-01 through 14 | UJ-17 | M1 |
| 14. Keyword research returns no results | TRUST-RSCH-05 through 14 | UJ-16 | M1/M6 |
| 15. Judge listings lack mapped judgments | JUDGE-01 through 10 | UJ-20 | M1/M6 |
| 16. Complete IP Law Firm AI | Entire program; IP-SCOPE, AI-GUIDE, AI-REV, IP-DRAFT, SEARCH-ACL | All journeys and domain child PRDs | M0-M10 |

### 9.1 Review-added control traceability

| Requirement family | Primary journeys | Blocking milestone(s) |
|---|---|---|
| TM-DATA | UJ-31, UJ-32, UJ-54 | M3 |
| CAL-OPS | UJ-08 to UJ-10, UJ-50, UJ-56, UJ-57, UJ-59, UJ-62 | M2/M3 |
| COMM | UJ-51, UJ-55, UJ-62 | M3 |
| LEGAL-SRC | UJ-15 to UJ-18, UJ-48, UJ-56 | M1/M2/M6 |
| IP-INC | UJ-58 | M3/M7 |
| IP-SCOPE | UJ-29, UJ-30, UJ-39 to UJ-45, UJ-60, UJ-61 | M8-M10 |
| SEC-GOV | UJ-46, UJ-57, UJ-63, UJ-66, UJ-68 | M2-M7 |
| DATA-GOV | UJ-28, UJ-64 to UJ-66 | M2/M7 |
| RES | UJ-25, UJ-65, UJ-67, UJ-68 | M2/M3/M7 |
| SEARCH-ACL | UJ-17, UJ-18, UJ-23, UJ-46, UJ-64, UJ-66 | M2/M6/M7 |
| ARCH-OPS | UJ-07, UJ-11, UJ-19, UJ-25, UJ-55, UJ-62, UJ-67, UJ-68 | M1-M7 |

## 10. Information architecture and primary screens

The first screen after selecting the IP workspace is the working portfolio, not a marketing or explanatory page.

These are IP workspace views, not duplicate CaseOps control planes. Existing `/app/portfolio` Matter reporting, `/app/calendar`, `/app/intake`, `/app/research`, `/app/drafting`, portal administration, and provider-operations pages remain canonical; IP navigation deep-links or filters shared screens where the underlying capability is shared. The top-level Portfolio switch makes `Matters` versus `IP` explicit so users do not mistake one list for complete coverage.

### 10.1 Global navigation

- **Portfolio:** assets and applications, saved views, alerts, renewals, and bulk operations.
- **Proceedings:** oppositions, rectifications, cancellations, appeals, and linked litigation.
- **Docket:** IP-filtered view of shared calendar, deadline queue, hearings, tasks, and unconfirmed legal calculations.
- **Inbox:** an IP-filtered triage view over existing connector evidence plus the existing `/app/notices` register for accepted registry/court notices, client and associate messages, service acknowledgements, calendar changes, exceptions, and unlinked correspondence. Triage state and notice/reply state are not duplicated.
- **Filings & Fees:** filing packages, submissions, acknowledgements, defects, official fees, associate charges, receipts, and reconciliation.
- **Watch:** search projects, journal watch, similarity hits, dispositions, and enforcement handoffs.
- **Research:** existing CaseOps keyword/context/citation/statute/judge search and saved research with IP scope links.
- **Documents:** permission-scoped document register, classification queue, and templates.
- **Reports:** IP report definitions using shared CaseOps export patterns and, when required, the neutral background report contract: portfolio, deadline, renewal, proceeding, workload, client, and data quality.
- **Integrations:** links to existing integration/provider-operations administration filtered for registry, case tracking, Indian Kanoon, notification health, cost, and replay.

### 10.2 Trademark application workspace

Header shows mark, representation, client, jurisdiction, canonical phase, raw registry status, application number, registration number, owner, responsible lawyer, next deadline, and freshness. Tabs are Overview, Prosecution, Proceedings, Deadlines, Hearings, Documents, Correspondence, Research, Related Matters, and Audit.

### 10.3 Opposition workspace

Header shows opposition number, linked application number, mark, applicant, opponent, represented side, current stage, tribunal/registry, next deadline, hearing, and sync freshness. The stage timeline is the primary working surface. Evidence, pleadings, correspondence, authorities, and audit remain adjacent tabs rather than separate disconnected tools.

### 10.4 Status language

Every externally synchronized record shows both:

- **CaseOps phase:** the stable cross-provider lifecycle used for filtering and workflow.
- **Registry status:** the exact latest source value with source and retrieval timestamp.

CaseOps must never overwrite a raw registry status with an AI interpretation.

### 10.5 Domain vocabulary and record boundaries

| Term | Contractual meaning in CaseOps |
|---|---|
| Client | Existing company-scoped CaseOps `Client` identity and contact fields for the person/entity that instructs or owns work; it is not duplicated merely because it appears as a registry party |
| Asset | The commercial/legal intellectual-property subject, such as one mark or invention family, which may have many jurisdictional applications and rights |
| Docket record | The access/lifecycle anchor for one asset, application, proceeding, or international designation; it is not a substitute for the type-specific legal record |
| Application | One filing before one office under one application identity; a multi-class filing remains one application with separately modeled class/specification scope |
| Registered right | The registration/issued-right state and term resulting from an application; registration identifiers and ownership history remain separately effective-dated |
| Proceeding | A contested or adjudicative workflow with its own parties, identifier, stage, evidence, deadlines, orders, and disposition |
| Matter | Existing CaseOps litigation/advisory/billing work container linked when appropriate; it does not own or replace the IP right lifecycle |
| Event | Append-only sourced fact or authorized operational act; correcting it creates supersession and never erases the original |
| Deadline | A versioned calculation or authorized manual obligation linked to its trigger; an internal target is visibly different from the legal deadline |
| Task | Assignable work item that may support a deadline or event but cannot itself change legal state |
| Filing package | Reviewed set of facts, form version, documents, fees, signatory, and readiness checks for one intended legal act |
| Filing transaction | Immutable submission/payment/service attempt and its evidence; a successful transport response is not registry acceptance |
| Source | The exact publisher/provider record and retrievable evidence used for a fact; a source label without resolvable provenance is insufficient |
| Registry candidate | Unaccepted provider observation awaiting deterministic policy or human reconciliation; it cannot silently become legal truth |
| Client instruction | Versioned, attributable authorization or decision with scope and acknowledgement; an email or portal message is not effective instruction until accepted under policy |

## 11. Proposed domain model

Every tenant record uses the repository's `company_id` tenant key, string UUID primary key, `created_at`, `updated_at`, and creator/updater membership references where applicable. Tenant parents expose `UNIQUE (id, company_id)`; tenant child foreign keys include `company_id` in the relationship constraint where the existing database pattern permits it, preventing a child from referencing another company's parent even if service filtering regresses. Services still filter by `context.company.id` on every read/write.

Ordinary metadata mutations require timezone-aware `expected_updated_at`, matching current CaseOps stale-write behavior. Legal lifecycle parents additionally carry non-negative `lifecycle_version`; dedicated transition endpoints require expected state, expected lifecycle version, and `expected_updated_at`. Generic PATCH, import, document processing, provider workers, and child updates cannot change or reactivate terminal lifecycle state. Transitions atomically update state, active flag, lifecycle version, affected operational children, audit event, and `domain_outbox_events`.

Logical names in this section are implementation contracts, not automatic permission to create tables. Every schema slice first classifies each record as `NEW`, `EXTEND`, `LINK`, or `REPLACE` in the ownership matrix below. A new table that overlaps an existing owner requires an ADR proving why extension is unsafe, the migration path, the single writer after cutover, and deletion of the superseded path.

### 11.1 New IP legal records

These records are genuinely new because CaseOps does not currently represent the underlying IP legal fact, source snapshot, calculation, or work product.

| New record | Purpose and required fields |
|---|---|
| `ip_docket_records` | Company-scoped anchor for asset, application, proceeding, and international-designation records: record type, display key, client, confidentiality policy, lifecycle state/version, active flag, and timestamps |
| `ip_assets` | Shared intellectual asset identity: asset type, title/mark, representation type, description, and jurisdiction scope; client/access/lifecycle remain on the docket anchor and party/responsibility records |
| `trademark_applications` | One office/jurisdiction application for an asset: filing particulars, use/priority, parties/agent, filing/publication/registration facts, and raw source status; canonical phase remains on the docket anchor |
| `trademark_application_scopes` | Effective-dated class/specification scope with Nice version, filed/normalized text, limitation/disclaimer, and opposed/accepted/refused/registered subsets |
| `trademark_representations` | Immutable word/device/label/colour/shape/sound/3D/series representation versions, exact linguistic/visual metadata, binary document version, and filing lock |
| `ip_proceedings` | Opposition, rectification, cancellation, appeal, show-cause, enforcement, or other contested proceeding with represented side, forum, parties, and target application; canonical stage remains on the docket anchor |
| `ip_identifiers` | Typed application, registration, opposition, rectification, appeal, CNR, and court identifiers with raw/normalized values, office, jurisdiction, source, effective range, and primary status |
| `ip_parties` and `ip_party_roles` | Applicants, proprietors, opponents, prior owners, licensees, agents, counsel, inventors, authors, and other effective-dated roles; reuse `Client` where the party is the firm's client |
| `ip_docket_events` | Append-only IP legal facts with event type, effective/recorded time, source evidence, verifier, payload schema, supersession, and affected workflow; the existing timeline compositor may project these, while `MatterActivity` remains Matter operational activity and is not copied |
| `ip_deadlines` | Authoritative legal calculation/version and lifecycle evidence: trigger event, rule/calendar versions, inputs, formula result/range, certainty, confirmation/override history, responsibility link, state, and completion evidence; the shared `matter_deadlines` row is a derived operational projection |
| `ip_responsibility_assignments` | Effective-dated primary, backup, supervisor, docketing, and billing responsibility with acceptance, delegation, leave coverage, escalation, and replacement source |
| `ip_relationships` | Divisional, associated, priority, basic-mark, Madrid designation, assignment predecessor/successor, licence, opposition target, and related-right relationships with effective dates and source |
| `ip_registry_links`, `ip_registry_snapshots`, and `ip_registry_diffs` | IP-office linkage, immutable raw/normalized register observations, freshness, field/event differences, confidence, reconciliation, attribution, terms version, and parse evidence. They exist because current `TrackedCase` is a court-case/CNR model, but polling health, support, cost, replay, notification and operator control reuse existing platform owners |
| `ip_rule_sets`, `ip_rule_versions`, and `company_ip_rule_policies` | Platform-curated versioned legal calculations plus company activation/internal-target/override policy; public rules contain no tenant-private data |
| `ip_fee_schedules` and `ip_fee_versions` | Platform-curated official fee items by form/class/entity/mode, currency, source, effective range, and verification state |
| `ip_workflow_definitions` and `ip_workflow_versions` | Versioned legal states, allowed commands, prerequisites, side effects, terminal semantics, sources, fixtures, approval, and effective range |
| `ip_client_instructions` | Versioned decision/authorization, exact scope/options, deadline, source/channel, authority, acknowledgement, acceptance/rejection/clarification, supersession, and resulting act |
| `ip_deadline_incidents` | Restricted suspected/confirmed missed, incorrect, or unowned deadline evidence, containment, assessment, notification policy, root cause, corrective action, and closure |
| `ip_renewal_terms` | Registration term, renewal/grace dates, instruction, fee, filing/acceptance evidence, and next term |
| `ip_watch_profiles` and `ip_watch_hits` | Watch/search criteria, cost/frequency policy, candidate evidence, reviewer disposition, related asset, and enforcement handoff |
| `ip_search_projects` and `ip_search_results` | Clearance scope, variants/classes/jurisdictions/source queries, candidate marks, lawyer disposition, opinion version, and frozen source manifest |
| `ip_filing_packages`, `ip_filing_transactions`, and `ip_service_records` | Intended act/readiness manifest; immutable submission attempts and formal legal-service facts; acknowledgement, defect, acceptance/rejection, payment reference, recipient/method/receipt and exact evidence links. Provider message/delivery state remains on existing Communication/notification/notice evidence |
| `ip_cost_items` | Official-fee, associate, translation, courier or other IP disbursement obligation/actual with quote/approval, original currency/tax and reconciliation state. Proof and receipts are immutable document/filing/communication links, not another payment or expense lifecycle |
| `trademark_international_registrations` | Madrid base/international record, WIPO/IR number, holder, designations, priority, dependency, renewals, and WIPO evidence |
| `ip_documents`, `ip_document_versions`, and `ip_document_links` | Versioned IP document identity, immutable storage/hash/processing/classification/approval metadata, and typed links to legal records; binary storage/extraction remains shared |
| `ip_source_conflicts` | Conflicting source claims/versions, authority rank, affected rules/records, curator/legal decision, impact scan, and supersession |

### 11.2 Existing CaseOps owners to extend

This matrix is authoritative for implementation ownership. Existing physical table names may remain during compatibility, but there is one service owner and one canonical state after cutover.

| Capability | Current CaseOps owner | Required change | Explicitly do not build |
|---|---|---|---|
| Tasks/work items | `MatterTask`, Matter task routes/UI, calendar and activity-report consumers | Add company scope and an optional IP docket parent through expand/backfill; preserve Matter routes as adapters; expose one shared task service/status model for Matter and IP work | `ip_tasks`, a second task board, or duplicate completion/assignee state |
| Timeline/activity | `MatterActivity` plus `services/matter_timeline.py`, which composes Matter events from several existing owners | Add an IP event adapter to the timeline compositor and, for a linked Matter, show linked IP facts by reference/access policy. `ip_docket_events` owns IP legal facts; `MatterActivity` continues to own Matter operational activity | Copying each IP legal event into `matter_activity`, treating audit rows as domain history, or bidirectional event synchronization |
| Hearings/calendar items | `MatterHearing`, `HearingReminder`, `MatterNextHearingHistory`, `MatterNextHearingSuggestion`, calendar feed, `CalendarEventSync`, cause lists | Extend the hearing record/service and next-hearing provenance with optional IP docket parent, time precision/timezone/mode/source/responsibility, and IP route adapters; keep one hearing status, provenance chain, suggestion decision and calendar projection | `ip_hearings`, a second next-hearing history/suggestion flow, a second hearing calendar, or an IP-only reminder dispatcher |
| Operational deadlines | `MatterDeadline`, `services/deadlines.py`, calendar/today feeds, calendar sync | Permit a company/IP-linked projection. `ip_deadlines` owns the legal calculation, responsibility, and lifecycle; the shared row mirrors due date/status/assignee for existing feeds and every mutation delegates to the IP command service | A second editable operational deadline, independent completion state, or two calendar entries for one obligation |
| Intake | `MatterIntakeRequest`, intake service/routes/page and promotion workflow | Add intake kind, typed party/details children, IP target/promotion links, and ability to promote to Matter, IP docket record, or both | `ip_intake_records`, a second intake queue, or separate requester/status taxonomy |
| Firm conflicts | `MatterConflictCheck` and `services/conflict_checks.py` | Generalize target to intake/Matter/IP, search existing Client/Matter/IP parties, normalize candidate/evidence rows, and retain legacy JSON only during migration | `ip_conflict_checks` or a second waiver/reviewer workflow; trademark clearance remains a separate `ip_search_project` |
| Clients, KYC, teams, memberships | `Client`, company memberships, `Team`, `TeamMembership` | Link IP parties/responsibility to these records and extend queries where necessary | IP-only client, user, team, KYC, or role masters |
| Internal access and ethical walls | `MatterAccessGrant`, `EthicalWall`, matter access service | Generalize the existing grant/exclusion service and compatibility tables to Matter, Client policy, or IP docket target with company-matching constraints, effective/revoked times, no owner bypass for restricted IP unless policy explicitly permits it, and one decision function used by list/search/document/AI/export | `ip_access_grants`, IP-only ethical walls, or client-side authorization |
| Portal identity and grants | `PortalUser`, `MatterPortalGrant`, portal auth/session/routes | Extend the existing portal grant owner to an IP docket target and scoped document/report publication; keep one portal identity, login, session, communication, and audit path | `ip_portal_grants`, a second client portal app, or automatic access from client association |
| Communications/connectors | `Communication`, Microsoft 365, mailbox/inbound-email, Drive, calendar candidate/sync services | Add typed company-verified IP links/projections and dedupe rules; connector evidence remains canonical | A second email body, OAuth store, provider envelope, communication row, Drive import, or calendar event |
| Notices and reply workflow | `CompanyNotice`, `CompanyNoticeMatterLink`, `services/notices.py`, `/api/notices`, `/app/notices`, activity reports, storage governance | Extend the existing company notice register with company-matched IP docket links and canonical Communication/IP-document evidence links. Accepted registry/court correspondence becomes one `CompanyNotice`; its IP legal reply due date uniquely correlates to `ip_deadlines` and the shared operational projection. Current replaceable notice-file bytes are convenience only: exact legal evidence is an immutable linked IP document version. Add IP-aware access filtering because current standalone-notice visibility is company-wide and document capabilities alone are insufficient for restricted IP | `ip_notices`, an IP notice/reply queue, copied/replaced legal evidence, or an independently editable notice reply deadline |
| Notifications | `NotificationDeliveryIntent`, notification preferences/rules/delivery, existing hearing schedule | Extend target/source types, replace recipient-membership cascade ownership with nullable `SET NULL` plus immutable recipient/actor snapshots where evidence must survive deactivation, and converge hearing delivery. One intent owns each recipient/channel effect | IP notification tables or any direct provider send outside the delivery service |
| Documents/processing | `MatterAttachment`, chunks, GCS/storage, scan/hash/extract/OCR jobs | Reuse storage and processing adapters. New IP document identity/version metadata is allowed because `MatterAttachment` is Matter-bound and not a versioned document aggregate | Copying binaries, a second malware/OCR queue, or forcing every portfolio document into a synthetic Matter |
| Billing, time, invoices, payments, spend | `MatterTimeEntry`, Matter billing profiles/invoices/manual line items/exports/payment attempts, billing payment orders/manual invoices, `OutsideCounselSpendRecord` | Keep billable time/invoices/spend Matter-bound and require an approved billing Matter link; link an `ip_cost_item` once to the applicable manual invoice line/spend record. Proof remains on canonical IP documents/filing transactions/communications and accounting state remains in billing/spend | IP time-entry, expense, invoice or payment ledgers; duplicating receipt state; or double-counting one cost in IP and Matter totals |
| Legal research and sources | `Statute`, `StatuteSection`, `LegalUpdateSourceRecord`, `AuthorityDocument`/chunks/citations, source adapters/proxy | Add a shared provenance serializer/fields, verification state, source-open contract, and link health against existing canonical records | `legal_source_records` as a second statute/judgment master or duplicate authority corpus |
| Judges/courts | `Court`, forum catalog, `Judge`, aliases, appointments, decision/affinity/statute projections | Repair canonical mapping and source actions; rebuild weak projections from existing masters | IP judge/court masters or copied judgment records |
| Drafting/recommendations/AI audit | `Draft`, versions/reviews, `DraftingDataExtractionField`, `Recommendation`, `ModelRun`, `TenantAIPolicy`, citation verification and existing drafting templates/format checks | Generalize target and extraction source from Matter/attachment-only to Matter or IP docket/document where required; retain current draft/version/review state machines, templates and validators; add assistant conversation records only for multi-turn Q&A | IP draft, extraction, recommendation, model-run, citation-verification, template, formatting-validator or AI-policy engines |
| Imports | Separate `MatterBulkImportJob`/rows and `EmployeeBulkImportJob`/rows plus domain services/pages; there is no generic persisted import owner today | Classify import orchestration as `REPLACE`: introduce a neutral `bulk_import_jobs` contract for new IP work, with shared status/manifest/error/download APIs and adapters that can surface legacy Matter/Employee jobs without rewriting their history. Keep typed row validation/commit in domain adapters and migrate legacy job control only in a separately approved convergence slice | Pretending `MatterBulkImportJob` is generic via a class alias, adding `ip_import_jobs`, cloning the uploader/history/error-report UI, or coupling IP row commits to `services/matter_imports.py` |
| Court and external-record tracking | `TrackedCase`, bookmarks/updates/poll runs, case-tracking provider contract, support matrix, notification flow, eCourts routes/UI, Matter court sync/order/cause-list records | Keep court/CNR tracking canonical and Matter court evidence where it is. IP registry links/snapshots are a distinct legal model, but their adapters register with existing connector readiness, support/cost configuration, provider operations, notification and replay patterns. A linked court proceeding references existing tracked-case/Matter evidence | Storing trademark applications in `TrackedCase`, copying tracked-case updates/orders into IP snapshots, or building an IP-only connector health/cost/support/replay stack |
| Provider operations/readiness/cost | `services/provider_operations.py`, `services/integrations.py` connector registry, `CaseTrackingSupportMatrix`, `ProviderCostProfile`, routes and admin pages | Register IP registry/watch/source capabilities, operation kinds, replay handlers, redaction, terms/readiness, cost and freshness in these existing surfaces; use an IP-specific sync-attempt source record only where the aggregator needs durable domain evidence | A second provider-operations or connector-readiness dashboard, parallel support/cost catalogue, or dead-letter operator workflow |
| Reporting/exports | Existing activity, portfolio, cause-list, invoice and export patterns; no single generic engine | Reuse synchronous patterns and extract a neutral report job/artifact/delivery contract only for background/scheduled reports; add IP query definitions as adapters | An IP-only report engine, scheduler, export storage policy, or download audit path |

### 11.3 New shared platform records

These are cross-cutting foundations that do not exist as reusable persistence today. They use neutral names and owners so later Matter, contract, and IP work cannot create another copy.

| New shared record | Purpose and boundary |
|---|---|
| `source_link_checks` | Typed source-target URL/proxy health history, result class, checked time, safe failure, and retry; it does not become a new source master |
| `legal_working_calendars` and `legal_working_calendar_versions` | Platform/company jurisdiction and office calendars with timezone, weekends, holidays/closures, exceptional working days, source, approval, effective range, and supersession |
| `access_review_campaigns` and `access_review_decisions` | Periodic/event-driven certification of existing internal/portal grants, owner, due date, decision/evidence, and revocation result across Matter and IP targets |
| `emergency_access_sessions` | Step-up-authenticated, reason/ticket-bound, narrowly scoped emergency access with expiry, approval/policy basis, actions, notification, revocation, and mandatory review; never a standing role |
| `data_retention_policies`, `data_retention_versions`, `legal_holds`, and `legal_hold_items` | Platform-wide governed retention and preservation, not IP-specific controls |
| `tenant_data_operations` and `tenant_data_operation_items` | Dry-run/execute export, offboard, purge, restore-validation, or reindex operations with immutable manifests, checkpoints, holds/exclusions, checksums, exceptions, and audit evidence |
| `domain_outbox_events` and `domain_consumer_effects` | Shared transactional event distribution, claim/retry/dead-letter state, and per-consumer effect idempotency; IP is the first adopter, not the owner of a second queue |
| `api_idempotency_records` | Company/actor/operation/key/request-hash state and stable result reference for mutation replay protection; existing domain-specific idempotency remains behind the same contract |
| `bulk_import_jobs` | Neutral import orchestration for new domains: company/actor, import kind, immutable input checksum, lifecycle, counts, expiry, manifest/error artifacts, idempotency and cancellation. IP typed staging links here; existing Matter/Employee jobs are exposed by compatibility adapters until a separately gated migration retires their job-control fields |
| `assistant_sessions`, `assistant_turns`, and `assistant_citations` | Multi-turn guide/workspace Q&A scope, actor/permission snapshot, bounded user/assistant turn content, model-run link, retention state, abstention, and exact typed citations; `ModelRun` remains the AI-call audit owner |
| `report_jobs` and `report_artifacts` | Neutral background/scheduled business-report status, filters/audience/source versions, manifest, artifact checksum/expiry, delivery link, and audit correlation; create only when a milestone needs async delivery and adapt existing report patterns rather than cloning them. Tenant/client legal export, purge, or offboarding remains a `tenant_data_operation` |

### 11.4 New links and projections only

| Link/projection | Canonical owner and invariant |
|---|---|
| `ip_communication_links` | Links existing `communications.id` to an IP docket record and legal role/effect; direction, body, channel, delivery, and provider identity remain on existing evidence |
| `company_notice_ip_links` | Extends the existing `CompanyNotice` register to IP docket targets with company matching, legal role, access-policy effect and optional correlated IP deadline. Notice direction/status/reply workflow remains on `CompanyNotice`; legal calculation remains on `ip_deadlines` |
| `ip_inbox_items` | Triage projection over existing inbound email, calendar candidate, Drive candidate, provider operation, manual document, Communication or unaccepted source item. Acceptance promotes/links one existing `CompanyNotice`, Communication, IP document or legal effect as appropriate; raw envelope/content/token/provider event and notice reply state are never copied |
| `ip_cost_evidence_links` | Links one `ip_cost_item` to immutable IP document version, filing transaction, Communication, CompanyNotice, invoice line or outside-counsel spend evidence. It has no paid/approved/reconciled lifecycle of its own |
| `ip_billing_links` | Links docket/cost/work type to existing Matter/billing profile/invoice line/spend record; one cost has one accounting owner and client-visibility decision |
| `ip_matter_links` | Company-verified many-to-many link from an IP docket record to existing Matter with relation role, effective/retired time, and access-mismatch warning; neither lifecycle is copied or synchronized |
| `ip_import_rows` | IP-specific validated staging/errors referencing neutral `bulk_import_jobs`; rows do not own job lifecycle and expire/retain under the shared import policy |
| Shared `matter_deadlines` projection | One operational projection per `ip_deadline` for calendar/today/assignment. It cannot calculate, override, or complete the legal deadline independently |
| Shared task/hearing target extension | Existing task/hearing rows gain company-matched IP linkage; API adapters and views read the same row rather than synchronize copies |

Cross-cutting reuse rules:

- Reuse existing `Matter` for litigation/advisory work and link it to IP records; neither record silently owns the other's lifecycle.
- Reuse storage/scanning/hash/extraction/chunking, notices, court tracking, connector readiness/support/cost, MFA/recent-step-up, audit, capability, provider-operation, billing, reporting, and production-readiness services as assigned in Section 11.2.
- Public statutes, authorities, courts, judges, rules, fees, and calendars contain no tenant-private payload. Company activation, private provider snapshots, saved analysis, and access remain company-scoped.
- Preserve legacy routes and rows during expansion, but all new writes use the selected shared service. Dual-read comparison is temporary; dual-write without an idempotent reconciliation and dated retirement gate is prohibited.

### 11.5 Physical data-contract rules

1. Every company-owned parent has `UNIQUE (id, company_id)`. Child tables carry `company_id` and use composite foreign keys to the parent wherever supported by existing migration patterns.
2. `ip_docket_records` is the referential anchor for IP legal records, events, calculations, source snapshots, document links, and typed cross-system links. Shared tasks, hearings, operational deadlines, grants, notifications, drafts, and reports reference it through explicit company-matched extensions; they are not duplicated as IP-owned aggregates. Type-specific IP records have a required unique `docket_record_id` and matching `company_id`.
3. `ip_identifiers` stores `raw_value`, `normalized_value`, `identifier_type`, office, jurisdiction, source, verification state, effective range, and retired time. A partial unique index prevents two live identifiers of the same type/office/jurisdiction/normalized value inside one company; collision resolution can retire/link but never silently overwrite.
4. Application/opposition/registration search indexes include `(company_id, normalized_value)`. Portfolio indexes include company plus current phase/status/client/owner/next-deadline/freshness; Postgres trigram indexes cover normalized mark/party text only after query-plan evidence.
5. Core searchable/legal fields are typed columns. JSON is reserved for immutable raw provider payload references, source-specific extension data, safe audit metadata, and tenant view configuration.
6. Money uses integer minor units plus ISO 4217 currency. Exchange rate, source, conversion time, and rounded result are stored separately; converted amounts never replace original currency amounts.
7. Instants use timezone-aware UTC timestamps; legal local date, local time/session, IANA timezone, and `time_precision` remain separately stored where the source is not an exact instant.
8. Append-only events, snapshots, document versions, transactions, calculation versions, and audit rows are not updated or deleted by ordinary services. Correction uses supersession/linkage.
9. State/enum strings use explicit database check constraints where the set is legally stable for the release; raw provider statuses stay unconstrained source text and are never used as lifecycle state.
10. Soft retirement records `retired_at`, actor, reason, and replacement where applicable. Hard delete is limited to approved retention/privacy workflows and respects legal hold.
11. Platform-owned public rule, fee, statute, authority, court, judge, and classification tables contain no tenant-private payloads. Company activation/overrides, private sources, usage, saved analysis, and access grants remain company-scoped.
12. IP record access evaluates company, active membership, capability, entitlement/rollout, record/client confidentiality policy, team/membership grants, and portal identity as applicable. A restricted record not explicitly granted is invisible; list counts/search/assistant/export cannot reveal its existence.
13. An application has one current filing representation, one or more effective class/specification rows, and effective-dated party/address/agent roles. Filing-locked facts can be corrected only by superseding version/recordal evidence; convenience edits cannot rewrite the filed package.
14. A critical deadline has exactly one active primary responsibility assignment and at least one active backup/escalation assignment before confirmation. A database/service invariant blocks owner deactivation or leave cutover until open critical work is transferred or an approved emergency owner is installed.
15. Inbound messages use provider message/event IDs plus company/source-account scope and content hash for deduplication. Linking one message to several records never duplicates its immutable original or attachments.
16. Search/index projections carry company, record-access policy version, source version, and tombstone generation. Revocation, retirement, legal hold, or source quarantine emits a projection event and stale results fail closed at result hydration.
17. Calendar and rule versions are immutable once used by a confirmed deadline. A correction creates a new version and an impact report; it does not recalculate confirmed history silently.
18. Workflow versions own allowed commands, prerequisites, side effects and terminal semantics. Database enums/checks reject unknown states, while services reject a known but disallowed transition. UI step order is never the only guard.
19. Actor membership foreign keys on immutable legal, filing, service, notification and audit evidence use `SET NULL` plus immutable actor label/ID snapshot where retention requires history. Membership deactivation must not cascade-delete evidence; company purge remains a separately approved operation.
20. Existing connector/raw records remain the single provider envelope. IP projections reference their IDs with company-matching constraints and independently governed links; provider IDs and OAuth/secret references are never copied into tenant-editable JSON.
21. Retention/hold/export/purge operates from a generated data-map registry covering SQL rows, object keys/versions, search/vector projections, caches, async/outbox/dead-letter records, analytics, provider-held artifacts and backups. A new table/data store cannot ship without a registered data class and disposition handler.
22. Audit and domain-event metadata use allowlisted schemas and reject/redact secrets, raw privileged content, full prompts, access tokens, payment data and unnecessary personal data. Operator logs contain identifiers/correlation only where possible.
23. Existing `Communication.matter_id` may remain null for IP-only communication, but an `ip_communication_link` is required before it appears in an IP workspace. Company matching is enforced. Deduplication relies on canonical connector/provider identity and content evidence, not the existing nullable `(company_id, matter_id, external_message_id)` uniqueness alone.
24. Shared task, hearing, deadline, intake, conflict, access, notice-link, and portal tables gain `company_id` where tenant ownership is currently inherited only through Matter, plus nullable company-matched Matter/Client/IP target FKs as applicable and database checks requiring a valid target. Backfills precede nullable-parent cutover; old rows and routes remain valid.
25. For one legal obligation, hearing, message, notice, notification, cost, draft, or grant, exactly one record owns mutable state. Links/projections contain display, routing, evidence, or reconciliation metadata only and reject independent lifecycle changes.
26. `ip_deadlines` and the shared operational deadline projection have a unique correlation. IP command services write both atomically; legacy shared-deadline update routes delegate or reject changes to IP-owned legal state.
27. New generic access/outbox/idempotency/calendar/assistant/data-governance records use platform-neutral names, owners, retention, and APIs. An IP feature cannot make a cross-cutting foundation private to `services/ip/`.
28. No implementation creates `ip_tasks`, `ip_hearings`, `ip_intake_records`, `ip_conflict_checks`, `ip_access_grants`, `ip_portal_grants`, `ip_notices`, `ip_import_jobs`, `ip_payment_records`, `ip_disbursement_evidence`, or a second legal-source master. Any exception requires a Product, Architecture, Security, and Data owner ADR that also deletes or retires the overlapping path before GA.
29. `ip_docket_records` is the single owner of current IP lifecycle, active state, primary client, and record-level confidentiality/access policy. Type-specific tables own legal particulars only; any denormalized display value is read-only, version-correlated, and rebuildable.
30. An accepted IP legal notice is one `CompanyNotice` linked through `company_notice_ip_links`. For a restricted IP target, notice list/get/download/count/owner and report queries enforce the same record policy; mixed-access links use an explicit audience or the most restrictive linked policy and never fall back to standalone company-wide visibility.
31. For an IP-linked notice, `CompanyNotice.reply_due_on` and reply state are the notice-register workflow view. Any legal date is owned by one `ip_deadline` and shared operational projection with unique correlation; notice updates delegate to that command or are rejected. Marking a reply sent cannot by itself prove filing, service acceptance, or completion of another legal obligation.
32. `TrackedCase`, its updates/bookmarks/poll runs, Matter court sync/orders/cause lists and their notifications remain the court-tracking owner. An IP registry snapshot may reference that evidence for a linked court proceeding but cannot clone it. Registry adapters must use existing connector readiness, support/cost, operation and replay surfaces even when their IP legal snapshots are separate.
33. Neutral `bulk_import_jobs` owns new import orchestration; `ip_import_rows` owns only typed IP staging/validation. Legacy Matter/Employee jobs stay authoritative for their history until a separately rehearsed convergence migration. Compatibility aggregation must not dual-write job status or pretend a model alias changes physical ownership.
34. An `ip_cost_item` is the sole IP legal-cost obligation/actual. Payment proof, receipt and invoice evidence are immutable links to existing document, filing, Communication, CompanyNotice, invoice-line or spend records; those links cannot independently approve, pay, reconcile or void an amount.
35. For an IP-linked `CompanyNotice`, the exact received/sent package is an immutable `ip_document_version` or canonical Communication/provider artifact linked to the notice. Replacing the convenience file creates/supersedes evidence under the IP document service or is rejected. `CompanyNotice.amount_minor`, `dispute_amount_minor`, and `recovered_amount_minor` remain notice/claim metadata and never become an `ip_cost_item`, invoice, spend or payment state without an explicit unique link.

## 12. Lifecycle and state requirements

### 12.1 Trademark application phase

Canonical phases are `draft`, `filing_ready`, `filed`, `formalities`, `examination`, `objected`, `accepted`, `published`, `opposed`, `registered`, `renewal_due`, `renewed`, `refused`, `withdrawn`, `abandoned`, `cancelled`, and `expired`.

Raw source status remains separate. A registry change can propose, but not silently force, a terminal CaseOps phase. Terminal transitions require an accepted source event or authorized manual confirmation and create an audit event.

### 12.2 Opposition proceeding stage

Canonical stages are `draft`, `notice_filed`, `service_pending`, `counterstatement_due`, `counterstatement_filed`, `opponent_evidence_due`, `opponent_evidence_filed`, `applicant_evidence_due`, `applicant_evidence_filed`, `reply_evidence_due`, `reply_evidence_filed`, `hearing_pending`, `hearing_scheduled`, `reserved_for_order`, `decided`, `appeal_pending`, `appealed`, `withdrawn`, and `closed`.

Not every proceeding follows every stage. A skipped, waived, extended, or superseded stage requires reason, authority, actor, and timestamp.

### 12.3 Deadline state

States are `proposed`, `pending_confirmation`, `confirmed`, `due`, `completed`, `waived`, `overdue`, `cancelled`, and `superseded`.

Critical registry/court deadlines generated from automation begin as `pending_confirmation` unless a tenant-approved deterministic rule and verified source meet auto-confirm policy. Completion requires evidence or an authorized attestation.

### 12.4 Notification delivery state

States per channel are `queued`, `submitted`, `delivered`, `failed_retryable`, `failed_terminal`, `bounced`, `suppressed`, `cancelled`, and `expired`. A provider acceptance is `submitted`, not `delivered`.

### 12.5 Filing package and transaction state

Filing package states are `draft`, `in_review`, `approved`, `submission_ready`, `submitted`, `defect`, `accepted`, `rejected`, `withdrawn`, and `superseded`. A transaction is one submission/service/payment attempt. An accepted package can have multiple immutable transactions, but only evidence from the relevant office/recipient can move it to `accepted`.

### 12.6 Search project state

Clearance/search project states are `draft`, `running`, `results_ready`, `lawyer_review`, `opinion_draft`, `approved`, `client_instructed`, `expired`, and `closed`. Search freshness and selected jurisdictions/classes are frozen into an approved opinion.

### 12.7 Responsibility, inbox, and incident state

Responsibility assignments are `proposed`, `awaiting_acceptance`, `active`, `delegated`, `superseded`, and `revoked`. A proposed/delegated owner is not treated as coverage until the responsible membership accepts or an approved emergency policy explicitly assigns coverage.

Inbox items are `new`, `classified`, `linked`, `duplicate`, `irrelevant`, `exception`, and `archived`. Automated extraction may propose links/events/deadlines, but only deterministic approved policy or an authorized user may accept a legal-state effect.

Deadline incidents are `suspected`, `contained`, `under_privileged_review`, `action_in_progress`, `monitoring`, and `closed`. Incident access is restricted by default. Closing requires impact determination, approved corrective actions, evidence, root-cause classification, and confirmation that ordinary docket history remains accurate without exposing privileged analysis.

### 12.8 Versioned transition contract

Every lifecycle/workflow version publishes a machine-readable transition table with `from_state`, command, `to_state`, actor capability, step-up/four-eyes policy, required facts/evidence, legal-source/rule references, child impacts, outbox events, terminal flag and rollback/compensating command. Activation requires legal fixtures and cannot alter records already pinned to an earlier version without explicit migration/impact approval.

Across all type-specific workflows:

1. Create begins only in the declared initial state; imports may map to another state only with source and reconciliation evidence.
2. Generic create/update/import/worker/provider/document/task endpoints cannot set phase/stage, active flag, approval, filed/served/paid/accepted status or lifecycle version.
3. A command locks the parent, verifies company/access/capability/step-up, expected state/lifecycle/update/workflow versions and prerequisites, writes event/state/child effects/audit/outbox atomically, then returns the new versions.
4. Failure before commit has no side effects. Failure after commit is recovered from outbox idempotently and cannot roll back the legal fact by deleting history.
5. Terminal commands neutralize, transfer or preserve each open deadline/task/hearing/reminder/filing/watch/report/portal/calendar child according to an explicit impact decision. Reopen is a separate authorized command and never resurrects neutralized children implicitly.
6. Provider observations, AI proposals and inbox classifications can propose a command only. Auto-execution is limited to an activated deterministic policy whose source, workflow, rule, confidence and record conditions all match.
7. Four-eyes commands reject approval by the proposer/preparer and reject two memberships backed by the same user. Emergency exception requires step-up, reason, expiry and post-review.
8. State history is derived from immutable command/domain events and must reconcile to the materialized current state in a scheduled integrity check.

## 13. Functional requirements

### 13.1 Bare Acts and statute trust (`TRUST-BA`)

- `TRUST-BA-01`: Add `verification_status` values `unverified`, `verified_official`, `verified_licensed`, `quarantined`, and `retired` to acts and provisions.
- `TRUST-BA-02`: A provision may be shown as statutory text only when source, source URL, publisher, retrieval time, and content hash exist.
- `TRUST-BA-03`: Store effective-from/effective-to and amendment metadata when known; disclose `current text only` when history is unavailable.
- `TRUST-BA-04`: Quarantine empty, mismatched, corrupted, editorial, or generated text without deleting evidence required for audit.
- `TRUST-BA-05`: Separate verbatim statutory text, editorial notes, case annotations, and AI explanation into labelled fields and panels.
- `TRUST-BA-06`: Never treat an act-level URL as a section-level deep link; label the destination accurately.
- `TRUST-BA-07`: Add curator compare-and-verify workflow with source diff, approval, rejection, and reason.
- `TRUST-BA-08`: Add link-health checks and visible last-checked status.
- `TRUST-BA-09`: Search defaults to verified records; curator can include quarantined records.
- `TRUST-BA-10`: Drafting and assistant retrieval may use authoritative text only.
- `TRUST-BA-11`: Seed/enrichment jobs are idempotent and cannot downgrade a verified provision without a reviewed source-version event.
- `TRUST-BA-12`: Remove or qualify any coverage count that includes provisions without usable verified text.

### 13.2 Research, judgments, and source access (`TRUST-RSCH`, `SRC`)

- `TRUST-RSCH-01`: Every result card renders source publisher, citation, source state, and Open source action.
- `TRUST-RSCH-02`: Preserve `source_reference` through ingestion, API serialization, ranking, saving, reporting, judge views, and AI citations.
- `TRUST-RSCH-03`: Validate public URLs and use an authenticated backend source proxy for provider-protected files.
- `TRUST-RSCH-04`: Opening a source records result, destination class, actor, and time without logging query secrets in URLs.
- `TRUST-RSCH-05`: Support keyword, contextual, exact citation, party, court, judge, act/section, date, and saved-search modes.
- `TRUST-RSCH-06`: Keep draft filters separate from committed search state; changing filters cannot disable the search action.
- `TRUST-RSCH-07`: Distinguish `no matching documents`, `corpus unavailable`, `index stale`, `provider unavailable`, `permission denied`, `query invalid`, and `request timed out`.
- `TRUST-RSCH-08`: Show corpus coverage and freshness appropriate to the query, without implying universal court coverage.
- `TRUST-RSCH-09`: Rank analogous authorities with explainable signals such as citation match, statute match, court hierarchy, date, treatment, and factual similarity.
- `TRUST-RSCH-10`: Recommendations include why relevant, relevant passage, treatment where known, and resolvable source.
- `TRUST-RSCH-11`: Do not label a result `recommended` based on predicted outcome or judge favorability.
- `TRUST-RSCH-12`: A saved research report freezes result IDs, source metadata, and generated analysis version.
- `TRUST-RSCH-13`: Maintain lawyer-approved golden queries by court/practice and run them after ingest, index, model, or UI releases.
- `TRUST-RSCH-14`: Add broken-link, empty-result, latency, click-through, and relevance-feedback telemetry.
- `SRC-01`: Indian Kanoon integration uses its contracted API, required attribution, quotas, cost attribution, caching, and retention terms.
- `SRC-02`: eCourts and commercial-provider records name the actual publisher/provider and retain original metadata.
- `SRC-03`: Provider credentials remain server-side; the browser receives only safe CaseOps source URLs or verified public URLs.
- `SRC-04`: Source adapters expose a common search/document/metadata/health contract and capability flags.
- `SRC-05`: Each imported source document has a stable provider document ID, canonical citation/identifier where available, and immutable source-record identity.
- `SRC-06`: Provider attribution appears on search results, source views, saved reports, exports, and AI citations wherever provider terms require it.
- `SRC-07`: Provider licence, permitted uses, retention, redistribution, and expiry are recorded as platform configuration and gate live activation and supported-capability claims. Missing approval keeps the adapter default-off but does not block an integrated fail-closed release train.
- `SRC-08`: Provider outage or quota exhaustion degrades to cached metadata/manual workflow with freshness warning; it never fabricates live coverage.
- `SRC-09`: Source health distinguishes URL failure, auth failure, removed document, changed content, provider outage, and unsupported access mode.
- `SRC-10`: User-supplied URLs are normalized and safety checked before storage; redirects are revalidated before browser or backend access.
- `SRC-11`: A materially changed source creates a new snapshot/hash and invalidates or flags dependent frozen analysis according to policy.
- `SRC-12`: Every provider adapter has contract fixtures, rate/cost limits, terms owner, support runbook, and kill switch before production enablement.

### 13.3 Notification reliability (`NOTIF`)

- `NOTIF-01`: A hearing or deadline has explicit recipients, channels, offsets, timezone, and escalation policy at confirmation time.
- `NOTIF-02`: Hearing time supports exact time, session, and `time not published`; the system must not silently assume 10:00 IST.
- `NOTIF-03`: Critical reminders always create an in-app intent. Firm policy determines whether users may disable external channels.
- `NOTIF-04`: Resolve recipients at scheduling and revalidate active membership and permission before dispatch.
- `NOTIF-05`: Display scheduled, submitted, delivered, failed, bounced, and suppressed state per recipient/channel.
- `NOTIF-06`: Suppression records provider, category, first/last occurrence, affected address, recovery action, and whether fallback was sent.
- `NOTIF-07`: A suppressed critical email creates in-app fallback and escalation to the configured docketing owner.
- `NOTIF-08`: Provide self-service Test notification and admin suppression-recovery workflow.
- `NOTIF-09`: Retry only retryable failures with bounded exponential backoff and idempotency keys.
- `NOTIF-10`: Duplicate worker executions cannot send duplicate notifications for the same recipient/channel/offset/event version.
- `NOTIF-11`: Changing a hearing/deadline supersedes obsolete reminders and displays the replacement chain.
- `NOTIF-12`: Completing/waiving/cancelling a deadline cancels pending reminders atomically.
- `NOTIF-13`: Provider webhook events update delivery state and are signature-verified and idempotent.
- `NOTIF-14`: Admin metrics include due, attempted, delivered, suppressed, failed, fallback, and stale queue counts.
- `NOTIF-15`: Alert platform operators and tenant admins when critical reminder failure or suppression exceeds configured thresholds.
- `NOTIF-16`: Notification content follows confidentiality policy and omits sensitive facts from SMS/email subject lines unless tenant policy permits them.
- `NOTIF-17`: Separate business schedule from delivery: hearing/deadline/report records determine what and when; one `notification_delivery_intent` per recipient/channel/version is the delivery truth.
- `NOTIF-18`: Extend delivery intent recipient targeting with an exactly-one check for active internal membership, portal user, or approved external contact/destination snapshot; tenant/client permission is rechecked immediately before send.
- `NOTIF-19`: Extend or map the current intent states to distinguish queued, submitted/provider-accepted, delivered, retry scheduled, blocked, suppressed, bounced, cancelled, and dead letter without rewriting historical meaning.
- `NOTIF-20`: Move email/SMS/WhatsApp adapters behind the durable notification-delivery service; hearing reminder code must not call SendGrid or another provider directly after cutover.
- `NOTIF-21`: Link each legacy `hearing_reminders` row to resulting intent(s), backfill historical status/provider IDs, and make the legacy status a compatibility projection before retiring direct dispatch.
- `NOTIF-22`: Store idempotent provider webhook events separately from current delivery state so late/out-of-order delivery, bounce, drop, spam, unsubscribe, and suppression events remain auditable.
- `NOTIF-23`: Address/destination changes create a new target/version and do not mutate evidence of where an earlier message was sent.
- `NOTIF-24`: Cutover uses dual-read comparison and one active dispatcher flag; dual sending is prohibited, and rollback returns dispatch ownership without losing intents or provider events.

### 13.4 Case tracking and integration operations (`TRACK`)

- `TRACK-01`: Use a dedicated scheduler service account with resource-scoped permission to run each Cloud Run job.
- `TRACK-02`: Deployment verifies scheduler target, identity, job revision/image, invocation permission, timezone, and a successful canary execution.
- `TRACK-03`: A scheduled invocation, job execution, provider operation, record update, and notification are correlated by operation ID.
- `TRACK-04`: Display last attempted, last successful, next scheduled, freshness, provider, and current error on each linked case/application.
- `TRACK-05`: A scheduler marked enabled but unable to invoke its job is unhealthy and pages operations.
- `TRACK-06`: Admin can retry one record, replay a bounded failed batch, or quarantine a poison record.
- `TRACK-07`: Replays are idempotent and show previewed scope and estimated provider cost before confirmation.
- `TRACK-08`: Preserve immutable raw snapshots and normalized diffs.
- `TRACK-09`: Provider timeouts, auth errors, rate limits, parse errors, and no-change results are separate operation outcomes.
- `TRACK-10`: Stale data is disclosed in user-facing views and AI context.
- `TRACK-11`: Manual refresh is rate-limited, cost-attributed, audited, and disabled when provider health is red.
- `TRACK-12`: Source download validates provider URL boundaries and proxies bearer-authenticated content.
- `TRACK-13`: Service support matrix identifies jurisdictions/courts actually supported.
- `TRACK-14`: Production deployment is incomplete until the dated production smoke test proves a fresh update and source-open path.

### 13.5 IP portfolio and identifiers (`IP-PORT`, `IP-ID`)

- `IP-PORT-01`: Provide list, grid, saved-view, and export views for trademark assets/applications.
- `IP-PORT-02`: Filter by client, mark, class, proprietor, jurisdiction, office, phase, raw status, attorney, team, deadline, renewal, opposition, watch risk, and freshness.
- `IP-PORT-03`: Columns are configurable per user and saved view without changing the tenant schema.
- `IP-PORT-04`: Bulk operations are permission checked, previewed, confirmed, audited, and partially recoverable.
- `IP-PORT-05`: Asset detail and application detail are distinct; one mark may have multiple jurisdiction/application records.
- `IP-PORT-06`: Support word, device/logo, label, colour, shape, sound, and other representation categories without forcing every type into text.
- `IP-PORT-07`: Nice classes and goods/services retain filing text and normalized searchable representation.
- `IP-PORT-08`: Provide controlled CSV/XLSX import with validation, preview, error report, duplicate suggestions, reconciliation, commit idempotency, and history.
- `IP-PORT-09`: Export includes data provenance and excludes privileged/internal fields by audience policy.
- `IP-PORT-10`: Portfolio counts distinguish complete records, incomplete records, sync failures, unconfirmed deadlines, and overdue work.
- `IP-ID-01`: Store application, registration, opposition, rectification, appeal, and court identifiers separately.
- `IP-ID-02`: Preserve raw formatting and a separate normalized search value.
- `IP-ID-03`: Identifier kind, office, jurisdiction, source, effective range, and primary flag are mandatory.
- `IP-ID-04`: Application number is required before a filing can enter `filed` phase unless the source explicitly reports pending allocation.
- `IP-ID-05`: Opposition number belongs to the proceeding and is never stored as the trademark application number.
- `IP-ID-06`: Search accepts common punctuation/spacing variants but displays the source form.
- `IP-ID-07`: Possible duplicate identifiers trigger reconciliation; they do not silently merge records.
- `IP-ID-08`: Identifier corrections preserve prior value and reason in history.

### 13.6 Prosecution, opposition, and deadlines (`IP-PROS`, `IP-OPP`, `IP-DL`)

- `IP-PROS-01`: Record filing, formalities, examination report, response, show-cause hearing, acceptance, publication, registration, renewal, refusal, abandonment, and restoration events.
- `IP-PROS-02`: Each event identifies source, effective date, entered date, responsible user, documents, and resulting stage/deadlines.
- `IP-PROS-03`: Registry events are candidates until reconciled according to risk policy.
- `IP-PROS-04`: Users may create manual events with reason and evidence; later registry matches can reconcile without duplication.
- `IP-PROS-05`: Event correction supersedes; it never destructively rewrites legal history.
- `IP-PROS-06`: Link prosecution work to tasks, time/billing, correspondence, and client reporting through existing CaseOps capabilities.
- `IP-PROS-07`: Inward registry communication and outward response remain separate correspondence/events with received, due, prepared, approved, filed, and accepted timestamps.
- `IP-PROS-08`: Phase transitions are fail-closed; generic edits, imports, documents, workers, or child records cannot reactivate a terminal application.
- `IP-PROS-09`: Stage checklists identify required facts, forms, fees, documents, approvals, and unresolved exceptions without claiming that checklist completion equals filing.
- `IP-PROS-10`: The workspace displays registry freshness, data-quality gaps, unconfirmed deadlines, and conflicting source/manual facts near the current phase.
- `IP-PROS-11`: Related applications may be grouped by mark/family/client, but each jurisdiction/application keeps independent identifiers, events, rules, and lifecycle.
- `IP-PROS-12`: Prosecution reports distinguish operational completion, filing evidence, registry acceptance, and final legal disposition.
- `IP-OPP-01`: Create opposition from a linked application, registry event, watch hit, or manual intake.
- `IP-OPP-02`: Capture represented side, opponent/applicant, agent/counsel, grounds, relied-on marks/rights, goods/services, forum, and identifiers.
- `IP-OPP-03`: Implement separate role-aware stage templates for applicant and opponent.
- `IP-OPP-04`: Support TM-O notice/counterstatement classification and Rules 45, 46, and 47 evidence stages.
- `IP-OPP-05`: Support extension, waiver, deemed abandonment, hearing, order, appeal, withdrawal, and settlement events.
- `IP-OPP-06`: Proceeding closure requires outcome, effective date, source/evidence, and authorized confirmation.
- `IP-OPP-07`: Link a proceeding to a CaseOps Matter when work enters litigation/advisory management; preserve both lifecycles.
- `IP-OPP-08`: Opposition grounds and relied-on rights use structured categories plus lawyer-authored detail; AI may classify but cannot finalize grounds.
- `IP-OPP-09`: Service tracks method, destination, date, evidence, acknowledgement, defect, re-service, and the event that starts any response period.
- `IP-OPP-10`: Evidence packages preserve affidavit/deponent, exhibits, index, verification, relied-on documents, version, filing, and service relationships.
- `IP-OPP-11`: Hearing preparation combines stage checklist, issues, evidence, authorities, written submissions, attendance, cause-list source, and post-hearing notes.
- `IP-OPP-12`: Orders record source, operative result, affected application/proceeding, costs/directions, compliance dates, and appeal review.
- `IP-OPP-13`: An appeal is a separately identified proceeding or Matter linked to the order; it does not reopen or rewrite the decided opposition.
- `IP-OPP-14`: Proceeding reports show side, application/opposition identifiers, stage, last/next event, deadline, hearing, responsible team, document completeness, and freshness.
- `IP-OPP-15`: Store opposition scope per challenged class and goods/services segment; a partial or multi-class opposition does not imply that every class is opposed.
- `IP-OPP-16`: Capture earlier mark/right, its jurisdiction/identifier/status/owner, relied-on goods/services, reputation/use claims, and supporting evidence independently from the opposed application.
- `IP-OPP-17`: Notice/counterstatement verification records signatory, authority, place/date, verified paragraph ranges, knowledge basis, and final signed document.
- `IP-OPP-18`: Rules 45 and 46 support both evidence filing and the explicit election to rely on pleaded facts without additional evidence; absence of action is not treated as an election.
- `IP-OPP-19`: Reply evidence is optional and separately timed; further evidence requires a leave/order event and must not be created as an ordinary automatic stage.
- `IP-OPP-20`: Non-Hindi/English relied-on material carries required attested translation, translator/attestation metadata, source-document link, and service evidence.
- `IP-OPP-21`: Hearing workflow tracks notice date, minimum-notice rule, adjournment request/form/fee/reason, allowed-count policy, written arguments, attendance, and non-appearance consequence as rule-versioned candidates requiring confirmation.
- `IP-OPP-22`: Security-for-costs direction, payment, enhancement, due date, evidence, and consequence are supported without treating it as an ordinary official filing fee.
- `IP-OPP-23`: Dismissal, abandonment, withdrawal, settlement, or final decision creates explicit downstream application disposition/registration review; no outcome is inferred from proceeding closure alone.
- `IP-OPP-24`: Opposition against an international registration designating India links to the relevant Madrid designation while preserving its WIPO/office identifiers and lifecycle.
- `IP-DL-01`: Deadline rules are jurisdiction-, proceeding-, role-, stage-, and rule-version-specific.
- `IP-DL-02`: A calculation stores trigger, base date, duration, unit, calendar method, holidays, extension, timezone, result, rule citation, and engine version.
- `IP-DL-03`: The UI explains the calculation in plain language and links to the governing verified source where available.
- `IP-DL-04`: Critical calculated deadlines require confirmation unless tenant auto-confirm policy explicitly covers the deterministic rule/source combination.
- `IP-DL-05`: Overrides require new date, reason, actor, and evidence; the original calculation remains visible.
- `IP-DL-06`: A changed triggering event proposes recalculation and supersedes reminders only after acceptance or deterministic policy.
- `IP-DL-07`: Calendar views distinguish filing deadline, internal target, hearing, renewal, and task date.
- `IP-DL-08`: Overdue critical deadlines escalate and cannot be dismissed without disposition.

### 13.7 Documents and naming (`IP-DOC`)

- `IP-DOC-01`: Establish a tenant-configurable taxonomy seeded with trademark filing, examination, opposition, evidence, hearing, order, appeal, renewal, assignment, licence, correspondence, search, watch, and invoice categories.
- `IP-DOC-02`: Preserve immutable original filename and expose a separate controlled display name.
- `IP-DOC-03`: Default display-name pattern is `[ClientCode]_[AssetType]_[Mark]_[Jurisdiction]_[ApplicationNo]_[ProceedingType]_[ProceedingNo]_[DocumentType]_[YYYY-MM-DD]_[Version]`, omitting unavailable components.
- `IP-DOC-04`: Sanitize unsafe filesystem characters and prevent spreadsheet formula interpretation in exports.
- `IP-DOC-05`: Bulk rename/classification shows preview and conflicts; it never silently overwrites files or links.
- `IP-DOC-06`: Duplicate detection uses content hash plus metadata; same filename alone is not a duplicate.
- `IP-DOC-07`: A document may link to multiple relevant records without duplicating stored content.
- `IP-DOC-08`: Filing state values are `draft`, `review`, `approved`, `filed`, `served`, `accepted`, `rejected`, and `superseded`.
- `IP-DOC-09`: Approved/Filed transitions require capability, version lock, actor, and time.
- `IP-DOC-10`: OCR/extraction quality is recorded; low-quality text is not silently used for legal conclusions.
- `IP-DOC-11`: Privilege/confidentiality labels restrict AI retrieval, portal sharing, export, and notifications.
- `IP-DOC-12`: The law firm's supplied document-name list must be imported as taxonomy aliases before opposition pilot acceptance.

### 13.8 Registry, search, watch, and renewals (`IP-REG`, `IP-WATCH`, `IP-REN`)

- `IP-REG-01`: Provider adapters implement search, record fetch, document fetch, health, attribution, cost, and capability contracts.
- `IP-REG-02`: Registry matching uses identifier plus jurisdiction/office and shows confidence and evidence.
- `IP-REG-03`: High-risk diffs such as proprietor, status, deadline-triggering date, refusal, opposition, or cancellation require review unless deterministic policy approves them.
- `IP-REG-04`: Accepted diffs create docket events and trigger deadline recalculation through the event system.
- `IP-REG-05`: A no-change poll still updates freshness and operation history.
- `IP-WATCH-01`: Create word/phonetic/device/class/proprietor/jurisdiction watch profiles with explicit frequency and recipients.
- `IP-WATCH-02`: Each hit displays source, compared marks, classes/goods, similarity evidence, date, and source link.
- `IP-WATCH-03`: AI similarity is advisory and cannot be the only basis for infringement or filing advice.
- `IP-WATCH-04`: Reviewer dispositions are `new`, `reviewing`, `relevant`, `not_relevant`, `monitor`, `client_instruction`, `enforcement_opened`, and `closed`.
- `IP-WATCH-05`: Relevant hits can create opposition intake, enforcement Matter, task, deadline, or client report item without re-entry.
- `IP-REN-01`: Calculate renewal and grace periods from verified registration events/rules with confirmation policy.
- `IP-REN-02`: Track client instruction, fee quote, payment, filing, registry acceptance, certificate, and next-term calculation.
- `IP-REN-03`: A renewal is not complete merely because payment or filing was initiated.

### 13.9 Judge and authority mapping (`JUDGE`)

- `JUDGE-01`: Use canonical judge and bench records with aliases, court, tenure, and source.
- `JUDGE-02`: Authority extraction stores canonical mappings plus confidence and evidence; free-text remains as raw evidence.
- `JUDGE-03`: Judge profile lists paginated mapped judgments with citation, date, court/bench, source, and mapping confidence.
- `JUDGE-04`: Users can open the judgment source from every judge-authority view.
- `JUDGE-05`: Curators can resolve aliases, split collisions, merge duplicates, and reprocess affected mappings.
- `JUDGE-06`: Low-confidence mappings are labelled and excluded from aggregate analytics by default.
- `JUDGE-07`: Analytics are descriptive and coverage-qualified.
- `JUDGE-08`: Do not infer personality, bias, emotion, success probability, or lawyer-specific favoritism.
- `JUDGE-09`: If lawyer-to-judgment mapping is later required, create a separate counsel-appearance domain and privacy review; do not overload judge mapping.
- `JUDGE-10`: Mapping and source-link smoke tests cover Delhi and at least two other pilot courts.

### 13.10 Guide, workspace Q&A, review, and drafting (`AI-GUIDE`, `AI-REV`, `IP-DRAFT`)

- `AI-GUIDE-01`: Extend the existing versioned `/guide` corpus into Product Guide mode for navigation, terminology, and procedural help. One maintained help source feeds the page, search, and assistant; generated answers cannot become guide truth.
- `AI-GUIDE-02`: Provide Ask this Workspace mode scoped to the current tenant and optionally client, asset, application, proceeding, Matter, or document set.
- `AI-GUIDE-03`: Show active scope and allow the user to narrow or clear it.
- `AI-GUIDE-04`: Every factual workspace answer cites exact records/documents; every external legal proposition cites a verified source.
- `AI-GUIDE-05`: Permission checks occur during retrieval and again before citation rendering.
- `AI-GUIDE-06`: The assistant may propose navigation, searches, drafts, tasks, or field updates, but writes require preview and confirmation.
- `AI-GUIDE-07`: Unsupported or insufficiently sourced questions return an abstention and suggested next search.
- `AI-GUIDE-08`: Global keyword entry can find commands, clients, marks, identifiers, proceedings, documents, and permitted help topics.
- `AI-GUIDE-09`: Conversation retention, export, deletion, and model/provider metadata follow tenant policy.
- `AI-GUIDE-10`: Users can rate/report an answer, wrong navigation, missing permission explanation, or unsafe citation; feedback enters a governed review queue.
- `AI-GUIDE-11`: Product guidance supports plain-language terminology and approved glossary aliases; multilingual support requires a separately evaluated help corpus.
- `AI-GUIDE-12`: Measure task completion, abstention, citation-open success, permission denial, proposed-action confirmation, and reported-answer rate without scoring employee performance.
- `AI-REV-01`: Intelligent review returns issue, relevant facts, applicable provision, analogous authorities, treatment, counter-authorities, gaps, and recommended lawyer checks.
- `AI-REV-02`: Each cited judgment includes source URL, citation, court, date, passage, and reason for relevance.
- `AI-REV-03`: Review displays corpus/source freshness and does not claim exhaustive research.
- `AI-REV-04`: Saved review freezes query/context, document versions, result IDs, source hashes, template/prompt, model, and generated output.
- `AI-REV-05`: The lawyer can include/exclude authorities and compare supporting and contrary passages before finalizing a report.
- `AI-REV-06`: A cited authority that cannot be opened is excluded from final recommendations or explicitly marked inaccessible with retained citation metadata.
- `AI-REV-07`: Contradictory dates, identifiers, parties, registry facts, or document assertions are surfaced as unresolved issues rather than silently reconciled by AI.
- `AI-REV-08`: Intelligent review must not produce judge favorability, outcome probability, guaranteed strategy, or a representation of exhaustive legal research.
- `AI-REV-09`: Publishing review into a pleading/client report requires authorized lawyer approval and preserves the approved version separately from generated analysis.
- `AI-REV-10`: Release evaluation covers citation entailment, source access, authority relevance, contrary authority, abstention, permissions, prompt injection, and prohibited outputs.
- `IP-DRAFT-01`: Templates are proceeding/stage/represented-side/jurisdiction specific.
- `IP-DRAFT-02`: Draft context is assembled from approved facts, parties, identifiers, events, documents, deadlines, verified statutes, and selected authorities.
- `IP-DRAFT-03`: The system highlights unresolved placeholders, unsupported assertions, inconsistent identifiers/dates, and missing exhibits.
- `IP-DRAFT-04`: Generated text is a draft with model, prompt/template, context sources, and generation time recorded.
- `IP-DRAFT-05`: Review, approval, filing, and service are separate human-controlled states.
- `IP-DRAFT-06`: Lawyer edits never mutate the original generated version; versions and comparison remain available through approval.
- `IP-DRAFT-07`: Citations and exhibits are validated against the source manifest before approval and again before marking filed.
- `IP-DRAFT-08`: Template changes are versioned, permission controlled, tested against legal fixtures, and do not retroactively alter prior drafts.
- `IP-DRAFT-09`: Exported work product carries selected court/registry format, page/annexure metadata, and an internal generation manifest kept outside the filed document.
- `IP-DRAFT-10`: A filing rejection or corrected filing creates a new event/version and does not rewrite the originally filed artifact.

### 13.11 Client portal and reporting (`CLIENT`, `REPORT`)

- `CLIENT-01`: Client access is an explicit grant to selected assets/applications/proceedings and selected document categories.
- `CLIENT-02`: Internal notes, privilege, strategy, work product, AI traces, provider errors, and unapproved drafts are excluded by default.
- `CLIENT-03`: Client users can view approved status, identifiers, selected events, upcoming shared dates, approved documents, and reports.
- `CLIENT-04`: Client instructions such as renewal/proceed/do not proceed create a pending instruction requiring firm acknowledgement.
- `REPORT-01`: Provide portfolio register, application status, opposition status, deadline, renewal, watch, workload, data-quality, and integration-freshness reports.
- `REPORT-02`: Reports show generated time, source freshness, filters, audience, and confidentiality classification.
- `REPORT-03`: Scheduled reports use the notification delivery model and expose delivery results.

### 13.12 Broader IP requirements (`PAT`, `DES`, `COPY`, `LIC`)

- `PAT-01`: Patent records support invention disclosure, inventors/applicants, priority claims, families, PCT, national phase, claims, office actions, responses, grant, annuities, and assignments.
- `PAT-02`: Patent deadlines use jurisdiction/rule-version engines independent from trademark rules.
- `PAT-03`: Indian patent workflows cover FER/office action, response, hearing, pre/post-grant opposition, grant, working statement, renewal/annuity, restoration, amendment, assignment/recordal, revocation, compulsory licence, and linked litigation as separately sourced events.
- `PAT-04`: Claim sets, specifications, drawings, sequence listings, amendments, prosecution versions, and filing packages retain immutable version relationships.
- `DES-01`: Design records support representations, classifications, filings, examination, registration, publication, renewal, cancellation, and infringement linkage.
- `COPY-01`: Copyright records support work type, authorship, ownership, publication, application/registration, licences, assignments, takedown/enforcement, and litigation linkage.
- `LIC-01`: Licence/assignment records support parties, territory, field, term, exclusivity, royalty/fee obligations, recordal, renewal/termination, documents, and reminders.
- `DOMAIN-01`: Domain records support registrar, expiry, ownership, watch, dispute/UDRP/INDRP, evidence, and linked enforcement Matter.
- `ENF-01`: Enforcement intake links a watch hit or right to investigation, notice, customs, platform takedown, opposition, cancellation, or litigation workflows.
- `GI-01`: Geographical-indication records support applicant/association, territory, goods, specification, authorised users, opposition, registration, renewal, infringement, and registry publications.
- `PVP-01`: Plant-variety records support variety category, denomination, applicant/breeder/farmer roles, crop/species, DUS and seed-material events, opposition, registration, annual/renewal fees, benefit sharing, compulsory licence, cancellation, and enforcement.
- `SICLD-01`: Semiconductor layout-design records support creator/proprietor, first commercial exploitation, application, opposition, registration, permitted use/licensing, cancellation, and infringement.
- `TS-01`: Trade-secret records support confidential asset registers, owners/custodians, access classification, protective agreements/controls, disclosure incidents, evidence preservation, and linked advisory/enforcement Matters; secret content is not indexed into general search by default.
- `CUSTOMS-01`: Customs/anti-counterfeiting records support right/recordal, product/authentication guide, authorised importers, alerts/detentions, bonds/fees, samples/evidence, instructions, disposal/release, and enforcement linkage.

### 13.13 Competitive baseline and differentiation (`COMP`)

- `COMP-01`: Match the expected portfolio register depth for marks, identifiers, classes, owners, agents, status, dates, responsible team, and searchable custom views.
- `COMP-02`: Match expected prosecution/opposition docketing with events, deadlines, hearings, documents, correspondence, renewals, and complete history.
- `COMP-03`: Match expected alerting with daily docket, calendar, escalations, configurable recipients, and observable delivery rather than send-only status.
- `COMP-04`: Match expected document operations with centralized register, inward/outward correspondence, naming, classification, versions, bulk actions, and permissions.
- `COMP-05`: Match expected registry connectivity with status synchronization, raw snapshots, change detection, freshness, reconciliation, and provider transparency.
- `COMP-06`: Match expected trademark Search and Watch workflows, including journal review and explainable word/device similarity candidates.
- `COMP-07`: Match expected reports, client access, role restrictions, portfolio/renewal views, and operational workload controls.
- `COMP-08`: Differentiate through a unified prosecution-litigation graph, verifiable sources, explainable deadlines, delivery proof, source-grounded AI, and complete auditability; do not claim superiority until pilot metrics support it.

### 13.14 Clearance, filing, Madrid, and post-registration (`IP-CLR`, `IP-FILE`, `IP-MAD`, `IP-POST`)

- `IP-CLR-01`: A clearance project records client instruction, proposed mark variants/representations, owner, goods/services, classes, target jurisdictions, urgency, search depth, sources, and conflicts/limitations.
- `IP-CLR-02`: Search results preserve exact query/source/time, candidate mark/identifier/status/classes/goods/owner, similarity evidence, source link, and lawyer disposition.
- `IP-CLR-03`: Search modes distinguish exact/word, phonetic, device/Vienna or equivalent image class, proprietor, class/goods, common-law/web/domain, and jurisdiction-specific registry searches according to available lawful sources.
- `IP-CLR-04`: The lawyer-approved opinion separates availability findings, limitations, unsearched sources, expiry/freshness, legal risks, and client options; AI similarity is not a clearance conclusion.
- `IP-CLR-05`: Client instruction to file creates a filing/application draft from approved data while retaining the frozen search and instruction; no instruction automatically files.
- `IP-FILE-01`: Filing package identifies legal act, office/jurisdiction, form/version, applicant/entity category, mark representation, classes/goods, priority/use claims, agent/address, declarations, signatory, documents, and fees.
- `IP-FILE-02`: System validates package completeness and consistency against the approved rule/form version but labels the result `ready for review`, not legally sufficient.
- `IP-FILE-03`: Filing, fee payment, service, resubmission, and acceptance are independent immutable transactions with external reference and evidence.
- `IP-FILE-04`: Official, associate, tax, translation, search, courier, and professional-fee items remain typed and separately reconcilable; current fees are versioned by source/effective date and never hardcoded in UI copy.
- `IP-FILE-05`: Acknowledgement/receipt defects, wrong office/class/entity category, payment mismatch, or rejected upload create actionable exceptions without marking the legal act completed.
- `IP-FILE-06`: CaseOps does not perform unattended filing. Any future portal automation requires a separate approved PRD, provider/legal permission, human confirmation, and transaction evidence.
- `IP-MAD-01`: Outbound Madrid workflow links a valid basic Indian application/registration, MM2 or applicable form, Office of Origin certification, WIPO irregularities, IR number/date, designated members, fees, dependency, subsequent designations, changes, and renewal.
- `IP-MAD-02`: Inbound India designation stores WIPO international registration/designation identity, holder, mark/classes/goods, notification/publication, provisional refusal, response, opposition, statement of grant/refusal, and independent India designation status.
- `IP-MAD-03`: Each designated jurisdiction has its own status, deadlines, agent, costs, documents, and source; one designation outcome cannot overwrite the international registration or another designation.
- `IP-MAD-04`: WIPO and national-office events are separately attributed and reconciled; Madrid deadlines/rules are independently versioned and legally reviewed.
- `IP-POST-01`: Post-registration work supports renewal/restoration, assignment/transmission, name/address/address-for-service, registered user/licence, associated/divisional mark, cancellation/rectification/non-use removal, limitation/disclaimer, certified copy, and well-known-mark requests where applicable.
- `IP-POST-02`: Each recordal stores legal basis, form, parties, effective date, affected registrations/classes, supporting instrument, fees, filing/acceptance evidence, and resulting registry snapshot.
- `IP-POST-03`: Ownership/licence changes are effective-dated interests; a pending recordal does not silently replace the current registered proprietor.
- `IP-POST-04`: Post-registration proceeding deadlines and evidence use their own rule templates and must not reuse opposition stages merely because some rules apply mutatis mutandis.

### 13.15 IP access and rule governance (`IP-ACCESS`, `RULE-GOV`)

- `IP-ACCESS-01`: Every IP list/detail/search/export/assistant/report query evaluates company and record/client access before returning existence, counts, snippets, facets, or citations.
- `IP-ACCESS-02`: Restricted docket records support effective-dated membership and team grants; default firm-wide access is a tenant policy, not an assumption for confidential records.
- `IP-ACCESS-03`: Grant/revoke uses existing `matter_access:manage` against the generalized Matter/Client/IP access service, plus expected record version, reason, preview of inherited visibility, and audit. A later least-privilege capability split requires a shared-access ADR and migration, not an IP-only permission path.
- `IP-ACCESS-04`: Portal grants are separate from internal grants and never satisfy `/app` authentication or internal AI retrieval.
- `IP-ACCESS-05`: Linked Matter/IP records do not automatically copy broader permissions in either direction; the UI warns on mismatched access before link/share/report actions.
- `IP-ACCESS-06`: Permission revocation invalidates active portal sessions/grants as applicable, excludes subsequent search/AI indexing retrieval, and blocks queued external delivery before send.
- `IP-ACCESS-07`: Access tests include direct ID, lists, counts, autocomplete, exports, source proxy, document chunks, AI citations, jobs, notifications, and audit metadata.
- `IP-ACCESS-08`: Platform operators receive redacted operational metadata by default and require a separately audited break-glass policy for tenant content.
- `RULE-GOV-01`: A proposed deadline/form/fee rule version identifies jurisdiction, office, right/proceeding/role/stage, source record/hash, effective range, author, engine compatibility, and fixture set.
- `RULE-GOV-02`: Rule source changes create candidates; they do not edit or activate an existing version.
- `RULE-GOV-03`: Activation requires two qualified actors, including a named legal approver who did not propose the same version, and all legal fixtures passing.
- `RULE-GOV-04`: Company policy selects an approved platform rule version and auto-confirm eligibility; a company cannot activate unverified draft rules in production.
- `RULE-GOV-05`: Activating/retiring a rule previews affected open records/deadlines. Existing confirmed deadlines remain historical; recalculation creates reviewable candidates unless a legally approved deterministic policy says otherwise.
- `RULE-GOV-06`: Rule execution stores engine version, exact inputs/intermediate calendar operations, result, and source version so it remains reproducible after later rule changes.
- `RULE-GOV-07`: Emergency disable stops new calculations/auto-confirm, marks dependent candidates, alerts affected companies, and does not delete prior evidence.
- `RULE-GOV-08`: Form and fee versions follow the same propose/review/activate/retire/audit model, but legal deadline, official fee, tenant charge, and document template remain separate version domains.

### 13.16 Intake and daily operations (`IP-OPS`)

- `IP-OPS-01`: IP intake captures proposed client/work/right, relevant/adverse parties, urgency/limitation, jurisdictions, instruction, source documents, owner, and engagement state before promotion.
- `IP-OPS-02`: Firm/client conflict, KYC/engagement approval, and trademark/patent availability or freedom-to-operate research are separate workflows with separate conclusions.
- `IP-OPS-03`: Substantive work before engagement/conflict clearance follows explicit tenant emergency/preliminary-work policy, approval, scope, and warning; filing/final legal approval remains blocked where policy requires.
- `IP-OPS-04`: Daily docket view groups critical deadlines, internal targets, hearings, filings awaiting evidence, unconfirmed calculations, failed/suppressed notifications, stale sync, client/associate responses, and overdue tasks by responsible person/team.
- `IP-OPS-05`: Reassignment preview includes open deadlines/tasks/hearings/notifications/client reports and requires acceptance/backup/escalation policy; changing owner does not alter legal history.
- `IP-OPS-06`: Inward/outward correspondence records source/channel, parties, sent/received/acknowledged times, confidentiality, response requirement, instruction, documents, and related docket events.
- `IP-OPS-07`: Client/associate instruction remains pending until acknowledged/accepted/rejected/clarified by an authorized firm user; inbound email or portal submission cannot directly change legal state.
- `IP-OPS-08`: Time, professional fee, official/associate cost, invoice, payment, write-off, and client-visible status reuse existing CaseOps billing entities through explicit links and retain original currency/source.
- `IP-OPS-09`: Closing, abandoning, withdrawing, transferring, or retiring an IP record uses dedicated lifecycle transition, disposition/effective date/source, open-work impact preview, notification/report handling, and linked-Matter review.
- `IP-OPS-10`: Operational reports distinguish legal state, work completion, filing/acceptance evidence, financial state, sync freshness, data quality, and access restrictions.

### 13.17 Trademark filing particulars and scope (`TM-DATA`)

- `TM-DATA-01`: The activated jurisdiction/form schema declares required, optional, conditional, repeatable, and prohibited fields by legal act, applicant type, mark type, class count, filing mode, and effective date; frontend labels are not the validation contract.
- `TM-DATA-02`: Capture mark category and representation as distinct structured facts, including word/device/label/colour/shape/sound/three-dimensional/series/collective/certification/other attributes supported by the activated form version.
- `TM-DATA-03`: Preserve exact mark text, script/language, transliteration, translation, pronunciation/description where supplied, colour claim, representation file, and immutable filed representation; search-normalized text never replaces filing text.
- `TM-DATA-04`: Store each class and goods/services specification as an independent effective-dated scope with Nice edition, filed wording, normalized search text, limitations/disclaimers, and application/proceeding outcomes per segment.
- `TM-DATA-05`: Capture every applicant/joint applicant with legal name, entity type, formation/incorporation jurisdiction, nationality where applicable, principal place of business, correspondence/address for service, identifiers allowed by policy, and dated role/source.
- `TM-DATA-06`: Capture agent/counsel, authorization/power-of-attorney evidence, signatory identity/capacity, and address-for-service history without overwriting who signed or received an earlier filing.
- `TM-DATA-07`: Filing basis and mode distinguish proposed-to-be-used, prior-use claim, convention priority, exhibition priority, ordinary/expedited/manual/e-filing, and any office-specific basis enabled by a lawyer-approved schema.
- `TM-DATA-08`: A prior-use claim stores claimed date, user/person, class/specification scope, affidavit version, supporting exhibits, gaps, reviewer, and filing-lock; CaseOps does not infer first use from uploaded documents.
- `TM-DATA-09`: A priority claim stores country/office, filing date, number, scope, certificate/translation status, relationship to the Indian filing, and rule-derived evidence deadline candidate.
- `TM-DATA-10`: Collective and certification marks store their governing regulations, applicant competence/authorization evidence, regulation versions, amendments, and special opposition/renewal/removal workflow flags rather than using an ordinary-mark checklist.
- `TM-DATA-11`: Series, associated, divisional, parent/child, and related applications use explicit relationships and source identifiers; splitting or associating cannot duplicate or silently redistribute class scope.
- `TM-DATA-12`: Filed, advertised, accepted, refused, opposed, registered, and assigned goods/services scopes coexist as source-versioned projections so partial outcomes remain explainable.
- `TM-DATA-13`: Required-field completeness is stage and schema-version aware. A record can be operationally imported with exceptions, but it cannot become `filing_ready` or `filed` without the activated readiness contract and approved exception policy.
- `TM-DATA-14`: The filing preview renders the exact data/form/document/fee/signatory package that will be submitted and produces an immutable manifest hash approved by the authorized reviewer.
- `TM-DATA-15`: Registry-imported particulars are candidates with field-level provenance and confidence. Conflicting party, use, priority, representation, class, or address facts require reconciliation and never silently replace a filed snapshot.

### 13.18 Calendar, responsibility, and deadline operations (`CAL-OPS`)

- `CAL-OPS-01`: Model the legal deadline, internal target, task date, hearing/listing date, client-instruction date, and reminder time as distinct types with independent state and display language.
- `CAL-OPS-02`: Each legal calculation selects a versioned jurisdiction/office calendar and records weekend rule, holidays/closures, exceptional working days, timezone, date precision, source, and calculation engine version.
- `CAL-OPS-03`: Calendar source priority is explicit. Official gazette/office/court closure evidence outranks tenant convention; an unresolved conflict blocks auto-confirm and opens review.
- `CAL-OPS-04`: The rule engine supports calendar-day, business-day, month/year anniversary, end-of-day, session/time, before/after, inclusive/exclusive, grace, extension, condonation/restoration candidate, and court/registry-specific next-working-day semantics without encoding them as one generic offset.
- `CAL-OPS-05`: Unknown trigger date, uncertain service date, conflicting publication date, or unknown hearing time creates a visible provisional obligation and escalation; the engine cannot manufacture precision.
- `CAL-OPS-06`: Dependency graphs show which event, rule, calendar, extension/order, or predecessor deadline produced each current date and which downstream dates would change before recalculation is accepted.
- `CAL-OPS-07`: Critical deadlines require primary owner, backup/escalation owner, supervisory/docketing responsibility, acknowledgement, and coverage status. Confirmation is blocked when firm policy requires missing coverage.
- `CAL-OPS-08`: Leave, deactivation, team transfer, or workload reassignment produces an atomic preview of affected deadlines/hearings/tasks/reminders and requires accepted replacement or approved emergency coverage.
- `CAL-OPS-09`: Daily docket supports saved team queues, workload/capacity indicators, bulk acknowledgement/assignment with per-record validation, and a print/export manifest whose generation time, filters, and freshness are visible.
- `CAL-OPS-10`: Calendar feeds and Outlook/Google calendar copies are convenience projections, never the authoritative deadline. Updates and cancellations carry stable external IDs and cannot duplicate events after resync.
- `CAL-OPS-11`: A changed date cancels/supersedes only dependent internal targets, tasks, calendar copies, and reminders identified in the impact preview; unrelated user work remains intact.
- `CAL-OPS-12`: Completion requires filing/service/order/client evidence or an authorized attestation under policy. Marking a task complete cannot complete the legal deadline.
- `CAL-OPS-13`: Overdue, unacknowledged, unowned, conflicting, or source-stale critical deadlines enter explicit exception queues and escalation; users cannot hide them by filtering or bulk dismissal.
- `CAL-OPS-14`: Suspected incorrect or missed deadlines open the incident workflow and freeze destructive cleanup while ordinary corrective docket events remain possible and auditable.

### 13.19 Correspondence, service, and instruction intake (`COMM`)

- `COMM-01`: Support manual upload/forward and approved OAuth/provider ingestion for selected email/calendar accounts without requiring a firm to grant access to all mailboxes.
- `COMM-02`: Preserve immutable original message/calendar evidence, provider account/message/thread/event IDs, safe headers, sender/recipients, sent/received times, attachment hashes, source, and dedupe key; display-body sanitization never alters the original.
- `COMM-03`: Ingestion is idempotent across webhook, polling, manual retry, mailbox move, and thread update. Duplicate detection is company/source-account scoped and produces a reviewable link, not silent deletion.
- `COMM-04`: Classification extracts proposed client, mark, identifier, proceeding, correspondence type, dates, response need, instruction, and document links with confidence; low-confidence or multi-match items remain in triage.
- `COMM-05`: No inbound message, attachment, calendar event, OCR result, or model classification can directly accept registry truth, confirm a legal deadline, authorize payment/filing, waive a right, or close a record.
- `COMM-06`: Service records preserve exact document/version served, sender/recipient and authority, method/address, dispatch/receipt/acknowledgement, defects/re-service, proof, and the separately confirmed event that triggers a period.
- `COMM-07`: Client and associate instructions are versioned and scope-specific; ambiguity, conflicting instructions, unauthorized sender, changed fee/scope, or later revocation enters clarification and blocks the affected legal act.
- `COMM-08`: Outbound communication uses an approved template/version where required, shows exact recipients/attachments/privilege labels before send, and records provider submission/delivery plus the immutable sent package.
- `COMM-09`: Reply/thread convenience cannot broaden record access: every message, attachment, quoted history, recipient, AI summary, and portal copy is reauthorized at open/send time.
- `COMM-10`: Calendar invitations/listing updates can propose hearing changes, but cancellation/reschedule follows the hearing impact workflow and cannot be inferred from a deleted calendar event.
- `COMM-11`: Retention, legal hold, deletion, export, provider disconnect, and mailbox offboarding operate on the immutable envelope and linked copies without leaving orphaned legal evidence or searchable content.
- `COMM-12`: The inbox exposes `new`, due-for-triage, unmatched, duplicate, exception, and aging states with named queue ownership, SLA, and audit; a message is not considered processed merely because extraction completed.
- `COMM-13`: Accepting a registry/court/client/associate item as a legal notice creates or links exactly one existing `CompanyNotice` and one `company_notice_ip_link`; the IP inbox remains a triage projection and cannot own notice direction, status, reply state, file, amount, owner, or response text. Exact legal bytes use an immutable linked IP document/Communication artifact, not destructive replacement of the convenience notice file.
- `COMM-14`: IP-linked notice list/get/download/report and owner actions enforce docket confidentiality/ethical-wall policy. A legal reply date uniquely correlates to `ip_deadlines`; `CompanyNotice.reply_due_on` is a delegated workflow view and cannot become a second calculation or completion authority.

### 13.20 Legal-source authority and conflicts (`LEGAL-SRC`)

- `LEGAL-SRC-01`: Every legal source records jurisdiction, issuing body, source category, official/licensed/editorial status, binding/advisory/draft/repealed status, publication/effective dates, retrieved time, canonical URL, content hash, and exact version.
- `LEGAL-SRC-02`: Source policy ranks enacted legislation/rules and official gazette/registry/court instruments for the proposition they govern, while preserving applicable judicial authority and office directions separately; rank never substitutes for lawyer interpretation.
- `LEGAL-SRC-03`: Draft manuals, consultation papers, FAQs, help pages, blog posts, vendor summaries, and AI explanations are visibly non-binding and cannot activate a legal deadline rule by themselves.
- `LEGAL-SRC-04`: A form, fee, journal, cause list, order, judgment, registry entry, and consolidated statute are different source types with different freshness, deep-link, retention, and verification contracts.
- `LEGAL-SRC-05`: When credible sources conflict, CaseOps records the exact disputed facts, versions, authority rank, affected rules/records, curator/legal decision, and impact scan; it does not choose silently.
- `LEGAL-SRC-06`: Source correction or withdrawal quarantines affected retrieval and new automation immediately, preserves historical evidence, identifies impacted AI outputs/rules/deadlines, and requires controlled supersession.
- `LEGAL-SRC-07`: A rule/form/fee activation cites the exact source passage or official artifact version and has two-person legal approval; an act-level landing page alone is insufficient evidence for a section/form value.
- `LEGAL-SRC-08`: Official-site outage, changed URL, captcha, or unavailable historical version produces a typed unavailable/stale state and manual evidence path; CaseOps never fabricates a deep link or silently substitutes an editorial source.
- `LEGAL-SRC-09`: Search and AI disclose authority type, date, source freshness, treatment/supersession where known, and access state. A citation label without an openable or explicitly unavailable source is not valid.
- `LEGAL-SRC-10`: Source licences/terms govern permitted fetching, caching, derivative indexing, redistribution, portal display, AI use, retention, and deletion; technical ability is not permission.

### 13.21 Deadline incident and professional-risk response (`IP-INC`)

- `IP-INC-01`: Any user or monitor can flag a suspected missed, incorrect, unowned, unnotified, or source-corrupted deadline without changing the ordinary deadline history.
- `IP-INC-02`: Opening an incident records discovery/evidence, restricts privileged assessment by default, preserves logs/messages/calculations, pauses risky automated cleanup, and alerts named risk owners under tenant policy.
- `IP-INC-03`: Containment supports corrective filing/service/contact tasks, alternate deadlines, source verification, and affected-work search without representing that a remedy is legally available.
- `IP-INC-04`: Impact assessment identifies affected rights, clients, proceedings, downstream deadlines, filings, notifications, reports, users, and similar calculations produced by the same rule/calendar/source version.
- `IP-INC-05`: Client, insurer, regulator, court/registry, or external-counsel communication is never automated; CaseOps records policy decision, authorized approver, exact sent evidence, and privilege/confidentiality boundary.
- `IP-INC-06`: Root-cause categories cover data entry, source, legal rule, calendar, ownership, handoff, notification, provider, software, access, and procedure; corrective/preventive actions have owners and verification evidence.
- `IP-INC-07`: Closure requires approved impact conclusion, corrective action status, evidence preservation, ordinary docket correction/supersession, similar-record scan, and post-incident review. Deleting or backdating history is prohibited.
- `IP-INC-08`: Product analytics expose only aggregated operational learning to authorized users and never use incident counts for lawyer performance scoring.

### 13.22 Full-IP scope governance (`IP-SCOPE`)

The shared foundation is necessary but not sufficient for a non-trademark practice. Each domain below requires a versioned specialist source/rule/form pack, data dictionary, lifecycle/transition model, legal fixtures, user-journey exceptions, migration map, provider boundary, and signed child PRD before authoritative automation, customer activation, or sales representation as supported. Repository implementation may proceed from a versioned draft behind fail-closed unavailable/intake-only capability states.

| Domain | Minimum domain capability that the child PRD must resolve |
|---|---|
| Patents | Invention disclosure, inventors/applicants/ownership, priority and family graph, provisional/complete filing, PCT/international and national phase, examination/office actions/hearings, pre/post-grant opposition, grant/claims/specification versions, annuities, working requirements, assignments/licences, revocation/enforcement |
| Industrial designs | Representations/views, article and Locarno classification, novelty/priority, filing/examination/registration, publication, restoration/renewal, assignment/licence, cancellation and enforcement |
| Copyright | Work/type, authorship and ownership chain, creation/publication, application/diary/registration, objections/hearing, deposits/documents, assignments/licences/royalties, takedown/platform notices, infringement/evidence and litigation |
| Geographical indications | Applicant/producer group, goods/class, geographical area/specification, filing/examination/opposition, registration, authorized users, renewal, rectification and enforcement |
| Plant varieties | Variety/breeder/applicant, denomination, species/category, priority, DUS/testing evidence, filing/examination/opposition, registration, annual/renewal obligations, benefit-sharing and enforcement |
| Semiconductor layout designs | Layout identity/representation, creator/owner, first commercial exploitation, application/examination/registration, assignments/licences, term and infringement |
| Trade secrets | Secret inventory/classification, owner/custodian, access/need-to-know, NDA/contract controls, disclosure log, clean-team/ethical wall, incident preservation and enforcement; no fictitious registry lifecycle |
| Domains and online enforcement | Domain/registrar/registry, ownership/renewal, watch, evidence capture, platform complaint, INDRP/UDRP or court proceeding, transfer/cancellation and enforcement outcome |
| Customs and anti-counterfeiting | Underlying rights, customs/marketplace recordal, suspected goods/seller/channel, detention/notice, inspection/sample/evidence, bond/security/cost, instruction, release/seizure/destruction and related proceedings |
| Licensing and transactions | Effective-dated chain of title, assignment/licence/security interest, territory/field/exclusivity/sublicensing, milestones/royalties/audit, quality control, notice/consent, renewal/termination, recordal and surviving obligations across right types |

- `IP-SCOPE-01`: A generic `asset_type` value does not constitute domain support; unsupported types remain intake/document/link records until their child PRD and milestone gate are approved.
- `IP-SCOPE-02`: Type-specific schema and state machines must not reuse trademark statuses, forms, fees, parties, deadlines, or completion semantics merely because labels look similar.
- `IP-SCOPE-03`: Shared clients, parties, documents, source records, events, tasks, access grants, billing links, notifications, audit, and relationship primitives may be reused only through explicit typed contracts.
- `IP-SCOPE-04`: Each domain defines jurisdiction and office support. India support does not imply every Indian tribunal/authority or any foreign jurisdiction.
- `IP-SCOPE-05`: Every domain release includes normal, exception, contested, transfer, renewal/maintenance, closure, migration, source failure, and access-revocation journeys appropriate to that right.
- `IP-SCOPE-06`: Every domain has two-reviewer legal fixtures for deadlines/forms/fees and must prove that rule updates do not rewrite confirmed historical obligations.
- `IP-SCOPE-07`: Cross-right families and ownership chains preserve independent legal identities, territories, effective dates, encumbrances, and sources while enabling a consolidated client view.
- `IP-SCOPE-08`: Domain-specific confidentiality applies: trade-secret and unpublished patent/invention content is excluded from general portfolio search, AI, exports, and portal views unless explicitly granted.
- `IP-SCOPE-09`: Sales, UI, API, reporting, and packaging label each domain as unavailable, intake-only, beta, or GA from server-side capability evidence; roadmap rows cannot be marketed as working features.
- `IP-SCOPE-10`: M8-M10 cannot exit on schema presence. The approved child PRD, journeys, legal/provider evidence, migration, security, performance, support, and pilot acceptance gate the affected domain's authoritative activation, beta/GA claim, and milestone exit; they do not block deployment of its fail-closed repository implementation.

### 13.23 Security, privileged actions, and access assurance (`SEC-GOV`)

- `SEC-GOV-01`: Reuse `require_recent_step_up` for rule/workflow/fee activation, break-glass, bulk export, purge execution, access-policy change, provider credential/replay, terminal/reopen lifecycle, deadline incident external communication, and tenant-configured high-risk filing/payment approval.
- `SEC-GOV-02`: Four-eyes policies distinguish preparer, legal approver, data/operations approver and executor. The same user cannot satisfy two required identities through different memberships or sessions.
- `SEC-GOV-03`: Emergency access is record/client scoped, step-up authenticated, reason/ticket bound, time-limited, least-privilege, conspicuously logged, notified to designated owner, and reviewed after expiry; it never bypasses company isolation or creates a permanent grant.
- `SEC-GOV-04`: Access reviews run periodically and on client-team change, ethical-wall change, portal inactivity, employee role/termination, external-counsel completion and incident trigger. Unreviewed grants expire or escalate according to firm policy.
- `SEC-GOV-05`: Deactivating a membership revokes sessions, connector tokens and effective access immediately, removes it from retrieval/notification/assignment, and invokes UJ-57; immutable evidence retains actor snapshots without keeping login access.
- `SEC-GOV-06`: Portal/external grants have purpose, scope, allowed actions/document categories, start/expiry, watermark/download policy, grantor and revocation. Default is no access; client association alone grants nothing.
- `SEC-GOV-07`: Platform operators receive redacted operational metadata by default. Any support access to tenant content is just-in-time, tenant/authorized approval or documented emergency-policy based, step-up protected, time-limited and separately audited.
- `SEC-GOV-08`: Webhooks verify signatures over the unmodified raw body, provider/account/tenant binding, timestamp/replay window and unique event/message ID before parsing side effects. Invalid events are retained only as safe security metadata.
- `SEC-GOV-09`: OAuth refresh tokens, provider secrets, signing keys and encryption-key references use Secret Manager/existing connector storage, least scopes, rotation/revocation testing and no browser/log/audit exposure. Disconnect invalidates pending privileged operations safely.
- `SEC-GOV-10`: Scheduler/job/service identities are separate from human and deploy identities, resource scoped, non-exportable where supported, and drift-tested. One job cannot invoke every job merely for convenience.
- `SEC-GOV-11`: Public/source/proxy URLs use canonicalization, DNS/IP and redirect revalidation, allowlisted scheme/host/path, response size/type/time limits and content disposition. Private/link-local/cloud-metadata access is blocked after every redirect.
- `SEC-GOV-12`: Upload/import/email attachments enforce decompression/archive limits, malware/content-type checks, macro/formula handling, encrypted-file exception, OCR/parser sandbox limits and no active-content execution.
- `SEC-GOV-13`: Per-user/company/provider rate, concurrency, quota and cost limits protect search, AI, import, export, refresh, replay, notification, source streaming and webhook paths; limit state cannot leak another tenant's use.
- `SEC-GOV-14`: Audit records use stable action schema, request/operation ID, actor snapshot, company, target, result, reason and safe metadata. Integrity monitoring detects missing sequences/illegal mutation; ordinary application code has no audit-update/delete path.
- `SEC-GOV-15`: Security alerts cover cross-tenant denial anomalies, repeated unauthorized source/document access, break-glass, bulk export/purge, permission changes, webhook forgery/replay, secret failures and abnormal provider/download volume with safe tenant notification policy.
- `SEC-GOV-16`: Each integrated release updates one consolidated threat model and abuse-case suite with traceable coverage for every affected milestone/data flow; security review must precede activation of privileged or client-data behavior and cannot be deferred to M7.

### 13.24 Retention, legal hold, export, purge, and offboarding (`DATA-GOV`)

- `DATA-GOV-01`: Maintain a versioned data-class registry covering each SQL table/column class, object prefix/version, search/vector index, cache, queue/outbox/dead letter, log/trace/metric, export, provider-held object and backup.
- `DATA-GOV-02`: Every class has purpose/legal-policy basis, sensitivity, default/tenant-configurable retention bounds, disposition, hold behavior, source/licence limits, region/subprocessor and owner. `Retain indefinitely` requires explicit approval, not omission.
- `DATA-GOV-03`: New migrations, object stores, indexes, providers, or telemetry labels cannot merge or activate without a data-map and retention/disposition handler update. The update may be implemented in the same integration workstream.
- `DATA-GOV-04`: Legal hold can target company/client/record/custodian/data class/date range, preserves covered current and future data, records issue/review/release authority and blocks conflicting purge/expiry. Ordinary users see only a safe deletion-blocked state.
- `DATA-GOV-05`: Hold creation/release and retention-policy activation require step-up and configured dual approval; release never deletes immediately without a new dry-run and waiting/approval policy.
- `DATA-GOV-06`: Tenant/client/record export is a resumable dry-run then execute operation with point-in-time scope, permission/hold/licence checks, explicit inclusions/exclusions, row/object/index counts, checksums, encrypted expiring artifact, signed manifest and audited downloads.
- `DATA-GOV-07`: Export excludes platform secrets, cross-tenant/global data, internal provider cost/profit, other clients' restricted data and non-redistributable source payloads while documenting each exclusion and available reference metadata.
- `DATA-GOV-08`: Purge is a separate dry-run and step-up/four-eyes execute operation with dependency plan, hold/retention exceptions, checkpoint/retry, immutable tombstone evidence and object/index/provider cleanup; direct `DELETE company` is not the workflow.
- `DATA-GOV-09`: Purge and revocation propagate to current/old object versions, temporary files, exports, search/vector/chunk rows, caches, AI/session stores, queued work, analytics and provider-held data where contractually supported; every subsystem reports completion or explicit exception.
- `DATA-GOV-10`: Backup retention and legal deletion are reconciled: data becomes inaccessible from production immediately, backup expiry is documented, restore tooling reapplies tombstones/holds before service, and no deleted tenant is resurrected by a restore.
- `DATA-GOV-11`: Immutable legal/audit evidence retained after content deletion is minimized to approved tombstone fields and cannot contain raw privileged documents, message bodies, prompts, destinations or secrets.
- `DATA-GOV-12`: Offboarding revokes users/sessions/connectors/portal links/provider callbacks, stops polling/reminders/reports, resolves ownership, exports as approved, preserves holds and produces a signed completion/exception manifest.
- `DATA-GOV-13`: Data residency, international transfer, subprocessors and AI/provider training/retention settings are represented as approved deploy/tenant policies and enforced before transmitting content; unsupported guarantees are not shown in sales/UI.
- `DATA-GOV-14`: Privacy/data-subject requests use verified requester/authority, scoped discovery, third-party/privilege review, export/correction/restriction/deletion decision, deadline, communication and evidence without automating legal conclusions.
- `DATA-GOV-15`: Application/provider/audit logs, traces and metrics minimize/redact message bodies, document text, prompts, mark/client names, email/phone, tokens and payment data; debug elevation is time-limited and audited.
- `DATA-GOV-16`: Data at rest/in transit uses approved platform encryption; key access/rotation/revocation and encrypted object recovery are drilled. Application-managed field encryption, if introduced, requires search/export/rotation/restore design before migration.
- `DATA-GOV-17`: Nightly retention/hold integrity scan reports expired-unpurged, purged-still-searchable, held-at-risk, orphan object/index, missing data-map and provider-deletion exceptions without exposing content.
- `DATA-GOV-18`: M2/M3 cannot claim export, purge, legal hold, offboarding or privacy readiness from manual SQL/runbook prose. The automated dry-run/execute paths and safe throwaway-tenant evidence must exist before their named gate exits.

### 13.25 Recovery, continuity, and degraded operation (`RES`)

- `RES-01`: Planning targets are database/audit/outbox RPO <= 15 minutes and service RTO <= 1 hour; document/object RPO <= 1 hour and usable recovery RTO <= 2 hours. Deployed configuration and drills may prove better, but weaker evidence blocks the gate or requires approved rebaseline/disclosure.
- `RES-02`: Current production evidence verifies backup schedule/retention/PITR, object versioning/retention/holds, encryption keys, cross-region/account recovery, immutable application images and required secrets/configuration; a runbook assertion is not evidence.
- `RES-03`: Quarterly and before GA after material storage/schema changes, restore to an isolated environment from recent production-equivalent backups and prove database, object metadata/content sample, migrations, pgvector/indexes, audit/outbox/idempotency and application startup.
- `RES-04`: Full-stack restore exercises authenticated tenant access, restricted record denial, source/document open, filing/deadline history, daily docket, notification no-dual-send state, search hydration, export manifest and a no-op/provider-fixture worker path against the exact restored schema.
- `RES-05`: Restore validation compares row/object/index counts and sampled hashes by data class, foreign-key/orphan checks, lifecycle materialization vs event history, pending outbox/intent states and last successful provider/source cursors.
- `RES-06`: Before enabling workers after restore/failover, operators apply purge tombstones/legal holds, fence old dispatchers, rotate or validate leases, and preview pending notifications/provider operations so recovery cannot duplicate filing/payment/message effects.
- `RES-07`: Regional/account/provider outage has documented manual docketing, source upload, notification fallback, export and recovery paths with visible degraded/freshness state. CaseOps does not promise continuous external-source availability it does not control.
- `RES-08`: Deadline/rule/source/notification/registry/AI features have independent server-side kill switches and last-good/manual operation; disabling one does not hide existing records or break manual docketing.
- `RES-09`: Database/object/search/provider recovery order and ownership are explicit. Rebuilt derived indexes/projections remain unavailable until access/tombstone/source-version validation passes.
- `RES-10`: Disaster exercises include database corruption/PITR, accidental object deletion, region loss, credential compromise, bad migration, poisoned outbox, duplicate-dispatch risk and source/provider unavailability on a risk-based rotation.
- `RES-11`: RPO/RTO is measured from incident/recovery timestamps and user-visible workflow readiness, not only infrastructure resource creation. Missed targets create corrective actions and customer/contract communication under policy.
- `RES-12`: Evidence is dated, references exact project/instance/bucket/image/schema head without secrets, names operator/reviewer, records observed timings and gaps, and expires after material topology/schema changes or the review interval.
- `RES-13`: M2 exit requires a current database-plus-object application-cutover restore rehearsal and tested tenant export dry run. M3 pilot requires no-dual-send worker recovery proof; M7 requires regional/failover, purge and incident drills.
- `RES-14`: Restore/DR actions are step-up protected and audited; production restore/failover requires incident/change authorization and cannot be initiated from an ordinary tenant endpoint.

### 13.26 Private search, AI retrieval, and projection revocation (`SEARCH-ACL`)

- `SEARCH-ACL-01`: Public legal corpus and tenant-private IP/document chunks use distinct ownership/access contracts; no public row/index/cache may contain tenant content or private derived metadata.
- `SEARCH-ACL-02`: Private lexical/vector queries prefilter by `company_id`, permitted docket/client/document policy and current projection generation before ranking. Post-filtering a cross-tenant candidate set is prohibited.
- `SEARCH-ACL-03`: Each private chunk/projection stores source document/version, company, docket/client scope, confidentiality/privilege, access-policy version, source/approval state, embedding model/version and tombstone generation.
- `SEARCH-ACL-04`: Result hydration rechecks active membership, capability/entitlement, record/document access, lifecycle/source state and current generation. Stale or revoked candidates are dropped without leaking count/title/snippet.
- `SEARCH-ACL-05`: Grant/policy/document/privilege/source/lifecycle/hold/purge changes emit idempotent projection events. Revocation has a measured maximum propagation objective and hydration fails closed during lag.
- `SEARCH-ACL-06`: Saved answers/reviews/reports containing quoted private content retain their own approved document/version manifest and access policy. Revocation locks/redacts access rather than leaving copied text globally visible.
- `SEARCH-ACL-07`: Embedding/model providers receive only approved minimal text and metadata under tenant/provider policy; batching, retries, logs and caches cannot combine or expose tenant payloads.
- `SEARCH-ACL-08`: Reindex uses versioned shadow generation, completeness/access/security/golden-query checks and atomic activation. Failed rebuild preserves the last good allowed index and does not resurrect quarantined/deleted rows.
- `SEARCH-ACL-09`: Cache keys include company, actor/access-policy scope, query/filter/corpus/index versions and safe locale; shared caches never key only on query text or record ID.
- `SEARCH-ACL-10`: Search/AI telemetry records safe query ID/hash and outcome, not raw privileged query/context by default; content-level debugging requires approved short-lived capture and deletion evidence.
- `SEARCH-ACL-11`: Security tests include cross-tenant nearest-neighbour attempts, restricted-count inference, revoked grant during streaming, stale cache/index, malicious prompt/source, portal/internal crossover and export/reindex after purge.
- `SEARCH-ACL-12`: Index coverage, lag, orphan/stale-generation count, access-denial-at-hydration and purge/quarantine propagation are observable by safe aggregate and block release when integrity thresholds fail.

### 13.27 Architecture and contract governance (`ARCH-OPS`)

- `ARCH-OPS-01`: Record an ADR naming one durable async/workflow ownership model before activating M2-C behavior. Implementation may proceed against the existing canonical Cloud Run/Temporal owner while review is pending; no third queue/workflow framework or competing writer is permitted.
- `ARCH-OPS-02`: Existing `AuditEvent`, `NotificationDeliveryIntent`, provider-operation, calendar-sync, inbound-email and communication contracts are extended through explicit adapters/migrations; parallel tables are allowed only for typed IP state they cannot represent and must link to the original evidence.
- `ARCH-OPS-03`: OpenAPI is the backend contract. Changed schemas regenerate/check `apps/web/lib/api/openapi-types.ts`; handwritten endpoint wrappers and Zod schemas have contract tests and CI fails on unexplained drift.
- `ARCH-OPS-04`: Publish a stable IP audit-action catalogue and domain-event catalogue with versioned payload schemas, owners, confidentiality classification, idempotency key, consumers and retention. Audit events are evidence; domain events drive projections; neither substitutes for the other.
- `ARCH-OPS-05`: Bulk commands use an immutable selection manifest or explicit IDs plus per-record expected versions. Query-based `select all` is re-resolved and preview-diffed at confirm; partial conflicts are reported without replaying successful rows.
- `ARCH-OPS-06`: Multipart/file idempotency hashes canonical metadata plus file content/version; ordinary JSON canonicalization rules are documented and tested across client/backend language implementations.
- `ARCH-OPS-07`: Async operations expose queued/running/succeeded/partially_succeeded/failed/cancel_requested/cancelled/expired state, safe progress/counts, checkpoints, result manifest, retry/cancel eligibility and correlation; cancellation never erases committed effects.
- `ARCH-OPS-08`: Cursor encodes versioned sort/filter scope and has expiry/tamper protection. Mutations during pagination cannot duplicate/skip silently beyond documented stable-snapshot semantics.
- `ARCH-OPS-09`: Every provider adapter declares capability, jurisdiction/source coverage, auth, quota/cost, idempotency, cursor/freshness, webhook/poll reconciliation, raw retention, error taxonomy, sandbox/fixture and kill switch.
- `ARCH-OPS-10`: Migration compatibility is tested with old and new application revisions concurrently against expanded schema, worker fencing and rollback flags. Contract migration waits until all serving/job revisions are proven off the old path.
- `ARCH-OPS-11`: Query plans and bounded eager loading are verified for portfolio, docket, access-filtered search, timeline, report and audit paths at representative tenant volumes; no per-row provider calls or unbounded ORM relationship loading.
- `ARCH-OPS-12`: Server capability, billing entitlement and rollout safety flag are independently observable with reason/owner/expiry. Frontend visibility is derived from the server and never treated as authorization.
- `ARCH-OPS-13`: Section 11.2 is the mandatory ownership registry. Before an ownership area is finalized or merged, each affected epic names its existing owner, decision (`NEW`, `EXTEND`, `LINK`, or `REPLACE`), canonical writer, compatibility adapter, migration phase, and retirement gate. Cache this decision across the run; an unresolved owner blocks only changes to that area.
- `ARCH-OPS-14`: A proposed table/service/page/job with overlapping lifecycle, status, actor, target, or evidence fields requires an ADR with field-by-field gap analysis. Convenience, naming purity, or avoiding an existing refactor is not sufficient justification.
- `ARCH-OPS-15`: Matter and IP work use one task service, one hearing service/calendar row, and one operational deadline projection. Existing physical table names may remain, but duplicate mutable state or bidirectional synchronization is prohibited.
- `ARCH-OPS-16`: Intake and firm-conflict review extend existing CaseOps queues/services to IP targets. Trademark clearance remains a distinct legal search product and cannot reuse the conflict label or resolution state.
- `ARCH-OPS-17`: Internal record access, ethical walls, portal identity/grants, access reviews, and emergency access use shared policy owners. All list/search/source/document/AI/export/report routes call the same target-aware decision function.
- `ARCH-OPS-18`: `ip_cost_items` records legal disbursement facts only and uses evidence links, not a separate disbursement/payment lifecycle. Matter time, client invoices/payment collection, outside-counsel spend, exports, and accounting status remain in existing billing owners with unique links and reconciliation tests that prevent double counting.
- `ARCH-OPS-19`: Statutes, authorities, judges, drafts, drafting extraction, recommendations, model runs, citation verification, provider operations, and report/export control planes are extended, not re-created. IP-specific records contain only domain facts, staging or linkage those owners cannot represent.
- `ARCH-OPS-20`: Shared outbox, idempotency, working-calendar, access-review, emergency-access, assistant-session, and data-operation foundations use platform-neutral names and ownership. Their API, metrics, retention, and replay cannot be private to the IP module.
- `ARCH-OPS-21`: `CompanyNotice` and `/app/notices` own accepted legal notices/reply workflow. IP adds target/evidence links and access/deadline delegation only; the inbox is triage and cannot become a second notice register.
- `ARCH-OPS-22`: `TrackedCase` and Matter court-sync records remain the court/CNR owner. IP registry snapshots are separate office-register evidence but reuse existing connector readiness, support matrix, provider cost, provider operations, replay and notification controls; neither side copies the other's source records.
- `ARCH-OPS-23`: Current Matter and Employee import jobs are domain-specific, not a generic owner. New IP import uses neutral `bulk_import_jobs` plus typed `ip_import_rows`; legacy jobs are exposed by adapters and migrated only under an explicit `REPLACE` ADR with one-writer reconciliation.
- `ARCH-OPS-24`: Shared-owner expansion follows real consumer dependencies. Task/hearing/deadline/access, intake/conflict/notice/import/report, drafting, portal/provider, assistant/private retrieval, and access-review/emergency/purge work may be implemented earlier in the continuous program when ownership is clear, but stays default-off until its consuming behavior and direct release gates are ready. M2 cannot claim completion merely from unused nullable targets.
- `ARCH-OPS-25`: `ip_docket_events` owns IP legal history; `MatterActivity`, Matter court evidence, `AuditEvent`, and domain outbox events keep their existing distinct purposes. Timeline views compose references under access policy and do not copy one event into several mutable histories.
- `ARCH-OPS-26`: Every cost has one amount/state owner. `ip_cost_evidence_links` are immutable references only; a billable cost requires an approved billing Matter and unique existing invoice-line/spend linkage, while filing payment, client collection and registry acceptance remain separate facts.

## 14. Complete user-journey catalogue

| Journey | Primary actor | Successful end state |
|---|---|---|
| UJ-01 Configure IP workspace | Owner / Docketing Manager | Jurisdiction, taxonomy, policies, providers, and roles are pilot-ready |
| UJ-02 Import existing trademark portfolio | Docketing Manager | Valid records committed; exceptions remain actionable |
| UJ-03 Create trademark application manually | Paralegal / Attorney | Searchable application with typed identifiers and ownership |
| UJ-04 Find and work from portfolio listing | Any permitted IP user | Correct record/view/action reached without spreadsheet work |
| UJ-05 Detect and resolve duplicate | Docketing Manager | Records merged/linked/kept separate with audit |
| UJ-06 Record prosecution event | Paralegal / Attorney | Event, documents, phase, tasks, and deadlines are consistent |
| UJ-07 Reconcile registry update | Docketing Manager | Accepted source diff becomes auditable docket event |
| UJ-08 Calculate and confirm deadline | Attorney / Docketing Manager | Explainable confirmed deadline and reminders exist |
| UJ-09 Override or supersede deadline | Approver | New date is active; prior calculation remains visible |
| UJ-10 Schedule hearing and reminders | Attorney / Paralegal | Hearing, recipients, offsets, and delivery tracking are configured |
| UJ-11 Recover failed/suppressed notification | User / Admin | Recipient informed through recovered or fallback channel |
| UJ-12 Docket opposition as applicant | Trademark Attorney | Counterstatement/evidence/hearing workflow is active |
| UJ-13 Docket opposition as opponent | Trademark Attorney | Notice/evidence/hearing workflow is active |
| UJ-14 Classify, name, and file documents | Paralegal / Attorney | Versioned documents are correctly linked and reviewable |
| UJ-15 Browse verified Bare Act | Lawyer / Researcher | Correct provision and authoritative source are opened |
| UJ-16 Run keyword/contextual research | Lawyer | Results or a diagnosable no-result state are returned |
| UJ-17 Open judgment/reference source | Lawyer | Safe source opens and access result is recorded |
| UJ-18 Run intelligent review | Lawyer | Source-grounded analogous cases and gaps are reviewed |
| UJ-19 Track eCourts/case-provider case | Litigator / Docketing Manager | Fresh snapshot, changes, documents, and alerts are visible |
| UJ-20 Browse judge and mapped judgments | Lawyer | Canonically mapped, source-linked authorities are accessible |
| UJ-21 Review watch hit and open action | Trademark Attorney | Hit is disposed or converted into a legal workflow |
| UJ-22 Use CaseOps Guide | Advisory user | User reaches and understands the correct product workflow |
| UJ-23 Ask this Workspace | Lawyer / Partner | Permission-scoped answer cites exact records and sources |
| UJ-24 Generate and approve IP pleading | Attorney / Partner | Reviewed version is approved with complete source trail |
| UJ-25 Operate failed integration | Platform/Tenant operator | Failure diagnosed, replayed/quarantined, and closed |
| UJ-26 Manage renewal | Docketing Manager | Instruction, filing, acceptance, and next term are recorded |
| UJ-27 Share client report and instruction | Partner / Client | Approved report delivered; instruction acknowledged |
| UJ-28 Export/offboard portfolio | Owner / Auditor | Complete authorized export and deletion/retention record exists |
| UJ-29 Manage patent family | Patent Attorney / Docketing Manager | Family, prosecution, deadlines, and annuities are connected |
| UJ-30 Manage design/copyright/licence | Relevant IP lawyer | Asset-specific lifecycle and obligations are docketed |
| UJ-31 Conduct clearance search and obtain filing instruction | Trademark Attorney | Approved source-frozen opinion and client instruction exist |
| UJ-32 Prepare, submit, and reconcile trademark filing | Paralegal / Attorney | Submission, payment, acknowledgement, and accepted filing evidence reconcile |
| UJ-33 Monitor journal publication and opposition window | Docketing Manager | Publication scope and limitation deadline are confirmed and acted on |
| UJ-34 Manage multi-class or partial opposition | Trademark Attorney | Challenged classes/goods and unaffected application scope remain distinct |
| UJ-35 Manage Madrid international registration/designation | International TM Attorney | Basic mark, WIPO record, designations, deadlines, and national outcomes remain connected |
| UJ-36 Complete post-registration recordal | Attorney / Paralegal | Assignment/licence/change is filed and registry acceptance reconciled |
| UJ-37 Coordinate foreign associate filing | Filing Coordinator | Instruction, estimate, submission, advice, invoice, and evidence are reconciled |
| UJ-38 Manage rectification, cancellation, or non-use removal | Trademark Litigator | Separate proceeding, evidence, deadlines, order, and appeal are docketed |
| UJ-39 Manage patent prosecution/opposition | Patent Attorney | Office action/opposition response and source-grounded docket are current |
| UJ-40 Manage patent annuity and working requirement | Patent Docketing Manager | Instruction, payment/filing, acceptance, and next obligation are confirmed |
| UJ-41 Manage industrial design lifecycle | Design Attorney | Filing, prosecution, registration, renewal, and cancellation history is complete |
| UJ-42 Manage copyright lifecycle and enforcement | Copyright Attorney | Ownership, registration, licence, takedown/enforcement, and evidence are connected |
| UJ-43 Manage assignment/licence obligations | Transactional IP Lawyer | Effective-dated rights and financial/non-financial obligations are monitored |
| UJ-44 Manage GI, plant variety, layout design, or trade secret | Specialist IP Lawyer | Type-specific rights/events are docketed without generic trademark assumptions |
| UJ-45 Manage customs or anti-counterfeiting action | Enforcement Lawyer | Recordal/detention, evidence, instruction, costs, and enforcement outcome are connected |
| UJ-46 Apply or revoke IP ethical-wall access | Owner / Access Administrator | Internal and portal visibility matches approved grants without leakage |
| UJ-47 Propose, test, activate, and retire legal rule version | Rule Curator / IP Legal Approver | Approved reproducible rule is active with impact evidence |
| UJ-48 Verify, quarantine, or supersede legal source | Knowledge Lawyer / Source Curator | Only correctly sourced/versioned legal content is publishable |
| UJ-49 Onboard IP client/work and clear firm conflict | Intake Lawyer / Partner | Approved engagement/intake promotes without confusing conflict and legal clearance |
| UJ-50 Triage daily docket and workload | Docketing Manager / Team Lead | Critical work is assigned, acknowledged, escalated, and observable |
| UJ-51 Capture correspondence and client/associate instruction | Lawyer / Paralegal | Communication, evidence, response duty, and accepted instruction are linked |
| UJ-52 Record time, cost, invoice, and payment linkage | Lawyer / Finance | Legal work and original-currency costs reconcile to existing billing controls |
| UJ-53 Close, abandon, transfer, or retire IP record | Authorized Approver | Terminal disposition is source-backed and operational children are neutralized |
| UJ-54 Capture and approve complete trademark filing particulars | Paralegal / Trademark Attorney | Form-version-ready facts, representation, class scope, declarations, and evidence are frozen |
| UJ-55 Triage inbound registry, court, client, or associate communication | Docketing Specialist / Lawyer | Original evidence is deduplicated, linked, classified, and converted only into approved work |
| UJ-56 Calculate a deadline across holiday, closure, extension, or uncertain trigger | Docketing Manager / Attorney | Explainable date or provisional escalation is confirmed without invented precision |
| UJ-57 Reassign critical work for leave, transfer, or deactivation | Team Lead / Docketing Manager | Every affected obligation has accepted replacement and no duplicate reminder ownership |
| UJ-58 Respond to a suspected missed or incorrect deadline | Risk Partner / Docketing Manager | Evidence is preserved, risk contained, impact assessed, and corrections remain auditable |
| UJ-59 Produce and sign off a daily docket control report | Docketing Manager / Supervising Partner | Fresh, reproducible exception/coverage manifest receives required review evidence |
| UJ-60 Qualify and launch a non-trademark IP domain | Product Owner / Specialist IP Lawyer | Approved child PRD and domain evidence gate support an honest beta/GA label |
| UJ-61 Reconcile chain of title and related-right family | IP Attorney / Docketing Specialist | Effective ownership, relationships, encumbrances, and recordal status are source-backed |
| UJ-62 Synchronize an external calendar without surrendering docket authority | Lawyer / Docketing Manager | Stable, deduplicated calendar projections mirror current CaseOps obligations |
| UJ-63 Grant, use, expire, and review emergency access | Access Administrator / Emergency User / Reviewer | Time-limited access ends, affected actions are reviewed, and no standing privilege remains |
| UJ-64 Place legal hold, export, and purge governed tenant data | Records Manager / Owner / Security Approver | Manifested operation honors holds, licences, every storage projection, and dual approval |
| UJ-65 Restore CaseOps and resume legal operations without duplicate effects | SRE / Incident Commander / Docketing Verifier | Current full-stack data and workflows recover within measured objectives with workers safely fenced |
| UJ-66 Revoke private content from search and AI projections | Access Administrator / Records Manager | Revoked content disappears from retrieval, caches, saved-output access, and rebuilds without leakage |
| UJ-67 Deploy an additive migration through mixed revisions and rollback | Engineer / SRE | Old/new revisions coexist safely, switch evidence passes, and rollback preserves legal history |
| UJ-68 Rotate or disconnect an integration credential | Tenant Admin / SRE | Secrets/scopes change without data leakage, duplicate effects, or falsely healthy automation |

## 15. Detailed user journeys

### UJ-01: Configure IP workspace

**Actor:** Owner or user with tenant notification/integration/IP administration capabilities.  
**Preconditions:** Active tenant; approved initial jurisdictions and practice scope.  
**Main flow:**

1. Admin opens IP Workspace Setup.
2. Selects enabled asset types, jurisdictions, offices, timezone, holiday calendar, and firm working-day policy.
3. Reviews seeded document taxonomy, event types, deadline rules, notification channels, critical-event policy, and escalation owner.
4. Maps custom roles to IP capabilities and creates pilot teams.
5. Configures permitted providers through server-side secret workflow and accepts provider attribution/cost terms.
6. Runs connection tests, test notification, source-open test, and sample deadline calculation.
7. Reviews readiness report and enables the IP workspace for a tenant allowlist.

**Exceptions:** Missing provider does not block manual docketing; unavailable source features show disabled capability and reason. A failed test prevents enabling the affected automated feature, not the whole workspace.  
**Audit/postcondition:** Configuration version, actor, tests, policy acceptance, and feature flags are recorded.  
**Acceptance:** No ordinary user can see a feature as operational when its provider or policy gate is red.

### UJ-02: Import existing trademark portfolio

**Actor:** Docketing Manager with `ip:import`.  
**Preconditions:** Taxonomy and required jurisdiction rules configured.  
**Main flow:**

1. User downloads the canonical XLSX/CSV template or opens compatible-file guidance.
2. Upload is malware/formula checked, fingerprinted, parsed, and stored as an import job without creating records.
3. System maps headers, normalizes identifiers/classes/dates, validates tenant references, and proposes duplicate matches.
4. Preview groups valid, invalid, warning, duplicate, and registry-conflict rows; every issue has code, field, and remedy.
5. User resolves mapping/duplicate decisions, downloads an error report, or corrects and re-uploads.
6. User confirms commit. Each row is revalidated and idempotently created/updated/linked according to the approved action.
7. Summary shows created, updated, linked, skipped, failed, and warning counts with direct record links.

**Exceptions:** Expired preview requires revalidation; concurrent changes can fail individual rows; a repeated commit returns the original terminal result; cross-tenant references are rejected without disclosure.  
**Audit/postcondition:** Job, source file hash, row decisions, actor, and resulting IDs remain searchable.  
**Acceptance:** Partial success never discards failed rows, and retry never creates duplicates.

### UJ-03: Create trademark application manually

**Actor:** Paralegal or Trademark Attorney with `ip:write`.  
**Preconditions:** Permitted client/work scope exists or tenant policy allows a restricted pre-engagement draft; intended jurisdiction and responsible team are known.  
**Main flow:**

1. User selects Create trademark application.
2. Enters or links client, mark, representation, jurisdiction/office, applicant/proprietor, agent, classes, goods/services, filing basis, dates, owner, and team.
3. Enters typed application number if allocated; system displays normalized search form without altering raw value.
4. Duplicate check shows potential matches by identifier, mark/client/class, and registry match.
5. User links to existing asset, confirms a separate application, or cancels.
6. Record opens with initial event, audit entry, data-quality checklist, and next recommended actions.

**Exceptions:** User may save a pre-filing draft without application number. A record cannot transition to filed unless identifier-allocation state is explicit.  
**Audit/postcondition:** Entered facts and provenance, duplicate candidates/decision, created asset/application/identifier IDs, initial lifecycle version, actor and data-quality exceptions are recorded.  
**Acceptance:** Application number and later opposition number cannot occupy the same identifier record or UI label.

### UJ-04: Find and work from portfolio listing

**Actor:** Any user with `ip:read`.  
**Preconditions:** Active membership, IP entitlement/rollout and record/client grants permit at least one portfolio scope.  
**Main flow:** User searches by mark, client, proprietor, raw/normalized identifier, class, proceeding number, lawyer, status, or keyword; applies filters; chooses columns; saves personal/team view; opens record or performs allowed bulk action.  
**Exceptions:** Stale synchronized data is visibly marked; restricted records are omitted, not teased; large exports become audited background jobs.  
**Audit/postcondition:** Saved-view definition/version, executed bulk/export operation, actor, filters, result manifest and permission failures are recorded according to policy; ordinary lookups avoid confidential query logging.  
**Acceptance:** Common lookup by exact application or opposition number reaches the correct record in one search.

### UJ-05: Detect and resolve duplicate

**Actor:** Docketing Manager.  
**Preconditions:** At least two accessible candidate records or identifiers have a reproducible duplicate signal; merge capability and required approvals are available.  
**Main flow:** System presents candidate records and evidence; user selects merge, link as related, keep separate, or defer; merge preview lists identifiers, events, documents, deadlines, permissions, and conflicts; approver confirms; references move atomically and the losing record becomes an auditable redirect/tombstone.  
**Exceptions:** Conflicting terminal states, clients, or privileged permissions block automatic merge and require owner review.  
**Audit/postcondition:** Candidate evidence, preview/version, field/reference decisions, approver, surviving/tombstoned IDs, redirects and unresolved conflicts remain traceable and reversible by controlled remediation.  
**Acceptance:** No document, event, identifier history, or audit evidence is lost.

### UJ-06: Record prosecution event

**Actor:** Paralegal or Attorney.  
**Preconditions:** Application is active, actor can write it, event type/source contract is available, and expected lifecycle/update versions are current.  
**Main flow:** User selects event type, effective date/time, source, and documents; system previews phase and deadline changes; user reviews calculation; event is committed; phase updates; tasks/deadlines/reminders are created; responsible users are notified.  
**Exceptions:** Backdated event triggers recalculation preview; duplicate registry/manual event offers reconciliation; correction creates superseding event.  
**Audit/postcondition:** Immutable event/source/document links, before/after phase, calculation/task/reminder effects, actor, version and any supersession/duplicate decision remain recorded.  
**Acceptance:** The timeline, current phase, deadline queue, and audit record agree after reload.

### UJ-07: Reconcile registry update

**Actor:** Docketing Manager with `ip:registry_sync`.  
**Preconditions:** Active registry link/provider capability, accessible target record and an immutable successfully retrieved or manually uploaded candidate snapshot exist.  
**Main flow:** Scheduled/manual IP-office adapter, registered in existing connector readiness/support/cost/operations surfaces, creates an immutable IP registry snapshot; normalizer compares it with accepted state; no-change updates freshness; low-risk deterministic change may auto-accept by policy; high-risk diff enters review; user opens source and raw evidence; accepts, rejects, maps, or defers each diff; accepted changes emit docket events and deadline proposals.  
**Exceptions:** Auth/rate/parse error creates an existing provider-operation/readiness failure without changing legal state. A later corrected snapshot supersedes, never deletes, prior evidence. A court/CNR result remains a `TrackedCase` update and is referenced, not re-ingested as an IP registry snapshot.  
**Audit/postcondition:** Connector/support/cost identity, provider operation, raw/normalized snapshot hashes, field diffs, policy version, resolver decision, emitted events/deadlines and current freshness remain correlated.  
**Acceptance:** Every changed field can be traced from source snapshot through resolver to current state.

### UJ-08: Calculate and confirm deadline

**Actor:** Attorney or Docketing Manager.  
**Preconditions:** Sourced trigger event, active lawyer-approved rule/calendar versions and current record lifecycle are available; actor has confirmation capability where required.  
**Main flow:** Trigger event invokes applicable rule version; calculation panel shows base event/date, duration, exclusions, holidays, extension, timezone, result, and source; user confirms or corrects with reason/evidence; assigns responsible user and internal target; selects reminder policy; confirmed deadline enters docket/calendar.  
**Exceptions:** Ambiguous source/date creates `pending_confirmation`; conflicting rules display both and block automatic confirmation.  
**Audit/postcondition:** Frozen inputs, rule/calendar/engine versions, intermediate calculation, source opens, confirmer, responsibility and generated targets/reminders remain reproducible.  
**Acceptance:** A reviewer can reproduce the date without reading code.

### UJ-09: Override or supersede deadline

**Actor:** User with `ip:approve`.  
**Preconditions:** Existing active deadline/version and authoritative reason/evidence are available; actor can see affected operational children.  
**Main flow:** User opens deadline history, selects Override, supplies date/reason/source/evidence; system previews affected tasks/reminders; confirms new version; old deadline becomes superseded; obsolete reminders cancel and replacements queue.  
**Exceptions:** Completed/waived deadline cannot be overwritten; correction creates a new disposition/version.  
**Audit/postcondition:** Expected/current versions, source/evidence, impact preview, approval, supersession chain and exact task/reminder/calendar effects remain immutable.  
**Acceptance:** Audit shows original, every intermediate version, active version, actor, and notification changes.

### UJ-10: Schedule hearing and reminders

**Actor:** Attorney or Paralegal.  
**Preconditions:** Active application/proceeding/Matter, source or authorized manual basis, and permitted recipients/channels exist.  
**Main flow:** User creates hearing from cause list, registry diff, or manual entry; confirms date, exact time/session/unknown time, timezone, forum, mode, location/link, purpose, source, attendees, and responsible users; selects reminder offsets/channels; preview lists recipients and policies; confirmation schedules idempotent intents; hearing strip and calendar show delivery state.  
**Exceptions:** Unknown time uses date/session reminders and prompts later confirmation; reschedule supersedes old hearing/reminders; permission change revalidates recipients before dispatch.  
**Audit/postcondition:** Hearing/source version, responsibility, recipient/destination snapshots, schedule/intent IDs, changes, cancellations and provider outcomes remain linked.  
**Acceptance:** No hidden default time is used, and every recipient/channel outcome is inspectable.

### UJ-11: Recover failed or suppressed notification

**Actor:** Recipient, Docketing Manager, or Tenant Admin.  
**Preconditions:** Delivery intent is failed/suppressed/bounced/stale or a critical recipient reports nonreceipt; actor has self-service or administrative recovery scope.  
**Main flow:** Failure creates in-app fallback and, for critical events, escalation; user sees reason and impact; self-service test confirms current address/channel; admin repairs suppression/configuration or chooses alternate recipient/channel; retry preview shows message/event idempotency; retry runs and webhook updates final state.  
**Exceptions:** Permanent bounce requires changed destination; provider outage keeps bounded retry and visible degraded status.  
**Audit/postcondition:** Original intent/attempts/provider events, fallback/escalation, destination version, repair action, retry idempotency and final outcome remain visible without mutating sent evidence.  
**Acceptance:** A worker success cannot mask recipient failure, and critical unsent reminders remain on an actionable queue.

### UJ-12: Docket opposition as applicant

**Actor:** Trademark Attorney representing applicant.  
**Preconditions:** Opposed application and notice/publication/service evidence are identified; represented side, engagement/access and applicable rule version are confirmed.  
**Main flow:** User creates/accepts opposition linked to application; records opposition number, opponent, represented side, grounds summary, service date, source notice, and counsel; applicant workflow proposes counterstatement deadline; user confirms and assigns work; uploads/classifies counterstatement and evidence; records filing/service events; completes applicant evidence, reply/hearing/order stages as applicable; links appeal/litigation Matter if opened.  
**Exceptions:** Opposition number pending is explicit; late/extension/waiver/deemed-abandonment paths require source and approval; settlement/withdrawal does not silently close linked Matter.  
**Audit/postcondition:** Notice/service source, side/template/rule versions, identifiers, stage events, filings/evidence, calculations, actors, disposition and linked Matter/appeal remain traceable.  
**Acceptance:** Application number remains visible and searchable alongside, but distinct from, opposition number.

### UJ-13: Docket opposition as opponent

**Actor:** Trademark Attorney representing opponent.  
**Preconditions:** Published target and limitation trigger are source-verified or explicitly provisional; client engagement/instruction and relied-on rights are available.  
**Main flow:** User creates opposition from watch hit, publication event, or manual intake; confirms relied-on application/right, applicant, classes/goods, grounds, limitation date, and client instruction; prepares/approves/files TM-O; records opposition number when allocated; workflow tracks service, counterstatement, opponent evidence, applicant evidence, reply, hearing, order, and appeal.  
**Exceptions:** Watch hit may be closed without proceeding; missing client instruction keeps work in intake and escalates before limitation; filing rejection reopens corrective task without marking stage filed.  
**Audit/postcondition:** Publication/search evidence, instruction, challenged scope, relied-on rights, filing/service transactions, stage/deadline history, identifier allocation and disposition remain linked.  
**Acceptance:** Every stage transition has filing/source evidence or an explicit authorized manual attestation.

### UJ-14: Classify, name, and file documents

**Actor:** Paralegal or Attorney.  
**Preconditions:** Actor can access target records and documents capability; upload/source satisfies size/type/security policy.  
**Main flow:** User uploads/selects document; malware/OCR/hash processing runs; system suggests taxonomy and links; user reviews original filename, controlled display-name preview, date, stage, parties, privilege, and filing state; saves; later version links to prior version; approver locks Approved version; filing/acceptance are recorded as separate events.  
**Exceptions:** Low OCR quality warns AI/search; duplicate hash offers reuse; naming conflict gets deterministic suffix; privileged document cannot be portal-shared.  
**Audit/postcondition:** Original storage/hash/name, scan/OCR results, taxonomy/link decisions, confidentiality, version chain, approvals and filing/service/acceptance evidence remain traceable.  
**Acceptance:** Original bytes/name/hash remain available and no automatic classification becomes final without review.

### UJ-15: Browse verified Bare Act

**Actor:** Lawyer or Researcher.  
**Preconditions:** Actor has research/source access and at least source metadata exists for the requested act/provision.  
**Main flow:** User searches act/section/phrase; verified results appear first with coverage/freshness; opens provision; views verbatim text, version/effective status, publisher, retrieval time, amendment note, related provisions, and Open official source; optional AI explanation is visually separate and cites the provision.  
**Exceptions:** Unverified/missing provision shows unavailable state and source-navigation option, not generated substitute; broken link reports and queues health check.  
**Audit/postcondition:** Query/result version, opened provision/source/version, access outcome and reported defect are recorded under privacy policy; published text remains hash-traceable.  
**Acceptance:** A displayed statutory quotation is byte-traceable to its verified source record.

### UJ-16: Run keyword or contextual research

**Actor:** Lawyer with existing `authorities:search` and access to the selected sources.  
**Preconditions:** Permitted corpus/providers and current index coverage are known; query scope and actor permissions are established.  
**Main flow:** User enters query/context, selects filters, and submits; UI freezes committed query while edits remain draft; backend reports search mode, coverage, freshness, and timing; results show relevance evidence, passage, citation, court/date, treatment, and source action; user saves result/report or refines query.  
**Exceptions:** Each no-result/error class has a distinct message and recovery; timeout preserves query; index/provider failure does not masquerade as zero results.  
**Audit/postcondition:** Committed query ID/hash, filters, corpus/index/provider versions, typed outcome, result/source references, saved selections and feedback remain reproducible subject to query-retention policy.  
**Acceptance:** Search action remains operable after filter changes and golden queries produce expected state.

### UJ-17: Open judgment or reference source

**Actor:** Lawyer.  
**Preconditions:** A result/citation exposes source state and actor is authorized for the originating record and protected source where applicable.  
**Main flow:** User selects Open source from research, upload analysis, judge profile, intelligent review, or saved report; system validates permission and source mode; public URL opens in a safe new context or protected document streams through source proxy; result is recorded; user can report wrong/broken source.  
**Exceptions:** Expired provider URL is refreshed server-side; unauthorized source returns permission state; failed source keeps citation metadata and queues health check.  
**Audit/postcondition:** Source record/version, origin surface, actor, permission decision, resolved destination class, proxy/provider operation, outcome and defect report are correlated without exposing credentials.  
**Acceptance:** No provider bearer token appears in browser URL, logs, or copied link.

### UJ-18: Run intelligent review

**Actor:** Lawyer.  
**Preconditions:** Actor can access the selected scope and approved research sources; source/index freshness and AI policy permit the review.  
**Main flow:** User chooses matter/application/proceeding and issue; reviews included facts/documents; runs review; output separates issues, governing provisions, supporting authorities, contrary authorities, factual analogies, gaps, and lawyer checks; each assertion has inline citation; user opens sources, removes weak cases, adds notes, and saves frozen report.  
**Exceptions:** Insufficient context/source causes abstention; stale corpus warning remains attached to saved report; inaccessible source is excluded or explicitly marked.  
**Audit/postcondition:** Scope/permission snapshot, document/source/model/prompt-policy versions, citations, abstentions, lawyer edits/selections and frozen report manifest remain recorded under tenant AI-retention policy.  
**Acceptance:** Removing citations makes unsupported analysis visibly incomplete; no outcome probability is generated.

### UJ-19: Track eCourts/provider case

**Actor:** Litigator or Docketing Manager.  
**Preconditions:** Matter/proceeding and CNR or other supported search identity exist; provider/source terms and jurisdiction capability are enabled.  
**Main flow:** User searches through the existing case-tracking provider, previews the match, and creates/reuses one `TrackedCase` plus bookmark/Matter link; an IP proceeding may reference that same tracked-case/Matter evidence. Existing polling creates `TrackedCaseUpdate` records and Matter court sync/order/cause-list evidence; accepted hearing/order/judgment effects appear through shared timeline/hearing/deadline adapters; existing notifications dispatch; source opens through the safe proxy.  
**Exceptions:** Scheduler/provider failure marks existing tracked data stale and preserves last good state; mismatched case requires relink; replay is bounded/idempotent; an IP link cannot copy or independently reconcile the same court update.  
**Audit/postcondition:** Existing search/match, tracked-case/bookmark/update/poll, Matter court evidence, IP reference, reconciliation, reminders, source opens and operation health remain correlated.  
**Acceptance:** Production smoke proves scheduler invocation, fresh snapshot, diff, notification, and source-open chain.

### UJ-20: Browse judge and mapped judgments

**Actor:** Lawyer.  
**Preconditions:** Canonical court/judge identity and at least mapping coverage metadata exist; actor has research/source access.  
**Main flow:** User selects court and judge; profile shows identity/tenure/source, coverage disclaimer, filters, and paginated judgments; every judgment shows mapping confidence and source; user opens judgment or starts research constrained to judge/court.  
**Exceptions:** Alias collision enters curator queue; low-confidence results are separately labelled; no results distinguish no mapped corpus from no judgments.  
**Audit/postcondition:** Canonical identity/mapping version, query/filters, result/source references, coverage/confidence and curator reports remain traceable without lawyer-performance inference.  
**Acceptance:** Profile never presents free-text coincidence as certain canonical mapping.

### UJ-21: Review watch hit and open action

**Actor:** Trademark Attorney.  
**Preconditions:** Approved watch profile produced an accessible hit with source and comparison evidence; actor is assigned or permitted to review.  
**Main flow:** Scheduled watch produces hit; user reviews compared marks, classes/goods, similarity evidence, source, date, and AI caveat; marks irrelevant/monitor/relevant; relevant hit requests client instruction or creates opposition/enforcement intake with copied evidence and deadline proposal.  
**Exceptions:** Duplicate hit links to existing review; source unavailable blocks final disposition that depends on source; cost quota pauses new polls visibly.  
**Audit/postcondition:** Profile/query/source versions, similarity evidence, reviewer disposition, duplicate/link decision, client request and created intake/task/deadline IDs remain linked.  
**Acceptance:** Watch-to-proceeding handoff preserves source and reviewer decision without re-entry.

### UJ-22: Use CaseOps Guide

**Actor:** Advisory or infrequent user.  
**Preconditions:** Active user session, approved product-help corpus/version and permission-aware command catalogue are available.  
**Main flow:** User asks how to perform a task or types a keyword; guide identifies product intent, explains current workflow briefly, and offers direct permission-aware navigation/actions; user opens destination; guide can continue with page context.  
**Exceptions:** Missing permission explains required capability without exposing restricted record names; outdated help content is versioned and reported.  
**Audit/postcondition:** Help-corpus/model version, intent/answer/action references, permission decision, navigation outcome and user report are recorded under non-content-heavy analytics policy.  
**Acceptance:** Guide answers product usage from approved help corpus only and never fabricates a screen/action.

### UJ-23: Ask this Workspace

**Actor:** Lawyer or Partner.  
**Preconditions:** User explicitly selects a permitted workspace/client/record/document scope and tenant AI policy/provider is enabled.  
**Main flow:** User sees and confirms scope; asks natural-language question; retrieval enforces permissions; answer cites exact records, event dates, document versions, and external sources; user opens citation, narrows query, saves research, or previews a proposed action.  
**Exceptions:** Cross-scope/cross-tenant references are excluded; insufficient evidence returns abstention; any proposed write requires preview and confirmation.  
**Audit/postcondition:** Session/scope/permission snapshot, retrieval manifest, model/policy version, citations, abstention/proposed actions, confirmations and retention/deletion state remain linked.  
**Acceptance:** Permission revocation removes the record from subsequent retrieval and citation access.

### UJ-24: Generate and approve IP pleading

**Actor:** Attorney drafts; Partner/authorized attorney approves.  
**Preconditions:** Active proceeding/stage, represented side, approved template and sufficient permissioned facts/documents/sources exist.  
**Main flow:** User selects proceeding stage, represented side, template, and output; context checklist shows parties, identifiers, facts, deadlines, documents, statutes, and authorities; user resolves missing inputs; generation creates cited draft and source manifest; lawyer edits/reviews consistency checks; approver locks version; filing/service occur through explicit later actions.  
**Exceptions:** Conflicting identifiers/dates block generation or create mandatory warnings; source loss invalidates affected citation; model failure preserves inputs without false draft state.  
**Audit/postcondition:** Template/model/policy/context/source versions, unresolved warnings, generated and edited document versions, reviewer/approver, lock and later filing/service links remain traceable.  
**Acceptance:** Approved version records template/model/context/source manifest and approval actor/time.

### UJ-25: Operate failed integration

**Actor:** Platform Operator or tenant administrator with existing `workspace:admin`.  
**Preconditions:** Alert/health signal or reported stale/failed provider operation exists; actor has redacted operational scope and an approved runbook.  
**Main flow:** Health dashboard alerts on scheduler/provider/freshness failure; operator opens correlated operation; sees redacted request metadata, response class, records affected, cost, retryability, and last good state; fixes configuration/IAM/provider issue; runs canary; previews bounded replay; confirms; monitors completion; closes incident with cause and prevention.  
**Exceptions:** Poison record quarantines while batch continues; replay budget/limit prevents accidental provider surge; tenant operator cannot see another tenant's payload.  
**Audit/postcondition:** Alert, operation/correlation IDs, redacted diagnostics, configuration/IAM change evidence, canary, replay preview/results, cost, root cause and closure are retained.  
**Acceptance:** `enabled` cannot be displayed as healthy without recent successful execution.

### UJ-26: Manage renewal

**Actor:** Docketing Manager.  
**Preconditions:** Verified registration/term and applicable renewal/grace rule/calendar exist; responsible users and client-instruction policy are configured.  
**Main flow:** Verified registration creates renewal term/deadlines; reminders request internal/client instruction; instruction and fee state are recorded; responsible user files and records evidence; registry acceptance/certificate confirms completion; next term is calculated and confirmed.  
**Exceptions:** No instruction escalates; grace-period path is explicit; provider filing/fee initiation does not mark renewal accepted.  
**Audit/postcondition:** Term/rule/source versions, instruction/quote/payment, filing transactions, registry acceptance/certificate, actors and next-term calculation remain linked.  
**Acceptance:** Portfolio report distinguishes due, instructed, filed, accepted, grace, and overdue.

### UJ-27: Share client report and instruction

**Actor:** Partner/Docketing Manager and Client Portal User.  
**Preconditions:** Explicit active portal grant, approved audience/field policy, permitted records and current report data are available.  
**Main flow:** Firm user selects report type, records, audience, period, and fields; preview excludes internal/privileged data; approver publishes/schedules; delivery state is tracked; client opens portal report and may submit structured instruction; instruction creates pending firm acknowledgement; firm accepts/clarifies and links resulting task/event.  
**Exceptions:** Revoked grant invalidates future access; bounced report escalates; conflicting client instruction does not automatically alter legal state.  
**Audit/postcondition:** Grant/policy/data versions, preview exclusions, approval, published report hash, recipient delivery/access, instruction versions and firm acknowledgement/effects remain recorded.  
**Acceptance:** Every client-visible fact can be traced to an approved current record.

### UJ-28: Export or offboard portfolio

**Actor:** Owner or Auditor.  
**Preconditions:** Authorized export/offboarding request, scope, purpose, recipient, retention/legal-hold and source-licence decisions are approved.  
**Main flow:** User selects clients/assets/date range/export classes; system previews records, files, audit, source/licensing restrictions, and size; approval starts encrypted background export; manifest lists every included/excluded object and checksum; download expires; retention/deletion requests create separate governed workflow.  
**Exceptions:** Provider terms may prohibit raw cached content export; legal hold blocks deletion; partial export retains retry manifest.  
**Audit/postcondition:** Request/approval, permission and hold checks, included/excluded manifest, checksums/encryption/expiry, download events, retries and resulting retention/deletion workflow remain traceable.  
**Acceptance:** Export does not cross tenant/client grants and can be independently reconciled to manifest.

### UJ-29: Manage patent family

**Actor:** Patent Attorney/Docketing Manager.  
**Preconditions:** Patent domain child PRD/capability and target jurisdictions are approved; intake/conflict/engagement and restricted invention access are established.  
**Main flow:** Create invention disclosure and family; record inventors/applicants/priority; add PCT and national-phase applications; record office actions/responses and claim/document versions; calculate jurisdiction-specific deadlines and annuities; link assignments/licences/litigation; report family status.  
**Exceptions:** Inventorship/ownership conflict requires legal review; family linking never merges distinct applications; rule engines remain jurisdiction-specific.  
**Audit/postcondition:** Disclosure/family/application identities, party/priority relationships, source/rule versions, claim/document history, events/deadlines/annuities and title links remain independently traceable.  
**Acceptance:** Family tree, identifiers, deadlines, and source history reconcile without trademark-specific assumptions.

### UJ-30: Manage design, copyright, or licence

**Actor:** Relevant IP Lawyer.  
**Preconditions:** The selected domain has an approved child PRD/capability, jurisdiction/source pack and type-specific access/engagement scope.  
**Main flow:** Select asset/contract type; capture type-specific ownership, representations/work, territory, term, classification/registration, parties, obligations, and documents; record prosecution/recordal/renewal/enforcement events; calculate deadlines/obligations; link related assets and Matters.  
**Exceptions:** Type-specific required fields and permissions prevent using a generic trademark form; contractual obligations are not represented as registry deadlines.  
**Audit/postcondition:** Type-specific facts, states, relationships, sources/rules, documents, obligations, events and cross-right/Matter links remain versioned without trademark semantics leaking into the record.  
**Acceptance:** Shared IP foundation is reused while each asset type retains its own validated lifecycle.

### UJ-31: Conduct clearance search and obtain filing instruction

**Actor:** Trademark Attorney with research and IP write access.  
**Preconditions:** Conflict/engagement reference recorded or tenant policy explicitly permits preliminary search; proposed mark, owner, goods/services, target jurisdictions, and urgency are known.  
**Main flow:** User creates search project; adds word/device variants, classes, goods/services, jurisdictions, sources, and search depth; system executes permitted registry/research queries and records exact query/source/time; user reviews candidate marks and common-law/domain evidence, classifies relevance, opens sources, and records limitations; source-grounded draft opinion is generated; lawyer edits and approves; approved opinion freezes source manifest/freshness; client filing instruction is recorded and creates a pre-filing application draft.  
**Exceptions:** Source outage produces incomplete-coverage warning; device search unavailable remains explicit; stale opinion must be refreshed or accepted with reason; adverse result never automatically blocks or approves filing.  
**Audit/postcondition:** Search versions, reviewer dispositions, approved opinion, instruction, and created application link remain immutable/auditable.  
**Acceptance:** Another lawyer can reproduce the searched scope and distinguish lawyer conclusion from AI similarity output.

### UJ-32: Prepare, submit, and reconcile trademark filing

**Actor:** Paralegal prepares; authorized Attorney approves and confirms submission.  
**Preconditions:** Client filing instruction, applicant authority, mark representation, classes/goods, jurisdiction/office, and current form/fee version are available.  
**Main flow:** User creates filing package; system populates approved application data and identifies missing declarations/documents; user adds priority/use claims, transliteration/translation, address for service, applicant category, signatory, and fee items; attorney reviews consistency and approves; human submits through approved channel and records transaction reference, time, payment, and evidence; acknowledgement is matched to package; application number/raw status are reconciled; accepted transaction creates filed event, phase change, and next deadline candidates.  
**Exceptions:** Payment success without filing acknowledgement remains pending; rejected upload/defect creates corrective transaction; changed form/fee after approval invalidates readiness; duplicate submission is detected by package/idempotency evidence.  
**Audit/postcondition:** Every preparation, approval, submission, payment, acknowledgement, defect, and acceptance record is linked without overwriting prior attempts.  
**Acceptance:** `filed` cannot be reached solely because a user clicked Submit or recorded payment.

### UJ-33: Monitor journal publication and opposition window

**Actor:** Docketing Manager.  
**Preconditions:** Application linked to registry/manual journal source; publication monitoring enabled.  
**Main flow:** Journal ingestion/manual verification detects advertised or re-advertised application; user opens journal source and confirms journal number/date, mark, application number, classes/goods, and publication scope; event creates opposition-window deadline from approved rule version; internal review/notification tasks are assigned; later opposition/no-opposition/division events update affected classes; deadline closes only on confirmed expiry or proceeding creation.  
**Exceptions:** Correction/re-advertisement supersedes prior trigger after review; partial publication creates class/goods scope; missing source keeps deadline pending confirmation; delayed ingestion raises stale-source alert.  
**Audit/postcondition:** Source page/snapshot, trigger, scope, calculation, confirmations, and any supersession remain linked.  
**Acceptance:** Re-advertisement and multi-class scope cannot silently reuse an obsolete opposition deadline.

### UJ-34: Manage multi-class or partial opposition

**Actor:** Trademark Attorney.  
**Preconditions:** Target application has class/goods structure and publication/opposition intake.  
**Main flow:** User selects challenged classes and specific goods/services; records per-class fee and grounds/evidence scope; system shows unaffected classes separately; filing/service transactions and opposition number are captured; applicant/opponent evidence and decisions retain challenged scope; division request/record links any split application; order disposition updates each affected scope without rewriting unaffected rights.  
**Exceptions:** Registry payload lacks granular goods scope, so user must confirm from source; later amendment/division creates relationship and revised scope; one class can be withdrawn or decided while others continue.  
**Audit/postcondition:** Every scope change records actor, reason, source, and affected application/proceeding relationships.  
**Acceptance:** Portfolio and reports never mark the whole application opposed/refused/registered from a class-limited outcome without qualification.

### UJ-35: Manage Madrid international registration or designation

**Actor:** International Trademark Attorney / Filing Coordinator.  
**Preconditions:** Outbound record has eligible basic Indian mark and holder, or inbound India designation has a WIPO notification/IR identity.  
**Main flow:** For outbound work, user creates Madrid record from basic mark, selects designated members/classes/goods, records MM2/applicable form and fees, Office of Origin certification, WIPO irregularities, IR number/date, and each designation; for inbound work, user records WIPO designation, Indian examination/provisional refusal, response, publication/opposition, and statement of grant/refusal; WIPO and national events synchronize through separately attributed snapshots; renewals/changes/subsequent designations create versioned transactions.  
**Exceptions:** Basic-mark change/dependency or central attack creates impact review, not automatic cancellation; one designation refusal does not change others; WIPO/national status conflict enters reconciliation; local-agent instruction remains distinct from WIPO filing.  
**Audit/postcondition:** Basic mark, international registration, each designation, source, deadline, fee, document, agent, and outcome remain navigable.  
**Acceptance:** No single generic `international status` can overwrite designation-level legal state.

### UJ-36: Complete post-registration recordal

**Actor:** Trademark Attorney or Paralegal.  
**Preconditions:** Registered right and client instruction/supporting instrument exist.  
**Main flow:** User selects recordal type such as assignment/transmission, registered user/licence, name/address, division/association, disclaimer/limitation, renewal/restoration, or certified copy; captures affected rights/classes, parties, effective date, instrument, form, fees, and approvals; package is reviewed and submitted; acknowledgement/defect is tracked; registry snapshot is reconciled; accepted event updates effective-dated interests/display status and triggers related deadlines/reports.  
**Exceptions:** Pending recordal does not replace registered proprietor; partial assignment splits affected goods/rights; defective instrument creates corrective transaction; conflicting client/registry evidence requires approval.  
**Audit/postcondition:** Pre- and post-recordal ownership/rights, source documents, transactions, and registry evidence are preserved.  
**Acceptance:** User can answer both beneficial/effective ownership and currently recorded registry ownership with dates and sources.

### UJ-37: Coordinate foreign associate filing

**Actor:** Filing / Foreign Associate Coordinator.  
**Preconditions:** Client instruction, target jurisdiction, responsible lawyer, approved associate, and budget policy exist.  
**Main flow:** User creates associate instruction from application/search; selects scoped data/documents under permission; records estimate/currency/tax/approval; sends through approved communication connector or records external dispatch; tracks acknowledgement, queries, local requirements, filing report, identifiers, invoices, and source documents; lawyer approves substantive responses; invoice/payment reconciles with filing transaction and client billing; reminders escalate unanswered instructions.  
**Exceptions:** Associate conflict/refusal triggers reassignment with preserved correspondence; exchange-rate/fee change requires approval; email delivery is not associate acknowledgement; privileged/internal content is excluded unless explicitly selected.  
**Audit/postcondition:** Instruction versions, recipients, delivery/acknowledgement, advice, costs, filing evidence, and approvals remain linked.  
**Acceptance:** Coordinator can identify every outstanding associate response and every filing lacking independent evidence.

### UJ-38: Manage rectification, cancellation, or non-use removal

**Actor:** Trademark Litigator.  
**Preconditions:** Target registration/application/right and represented party are identified; conflict/engagement policy satisfied.  
**Main flow:** User creates separate proceeding with type/legal basis, target right, applicant/respondent, challenged scope, grounds, forum, identifiers, source, and documents; applicable form/fee/service package is prepared and recorded; counterstatement/evidence/hearing stages derive from a type-specific rule template; orders and compliance/appeal deadlines are captured; affected registration receives linked candidate disposition after authorized review.  
**Exceptions:** Rules that apply mutatis mutandis are explicitly mapped and versioned rather than copied blindly; parallel court/registry proceedings remain separate; interim stay blocks automatic downstream disposition; settlement/withdrawal needs explicit legal effect.  
**Audit/postcondition:** Proceeding, target right, evidence, source, deadlines, order, appeal, and registry reconciliation remain traceable.  
**Acceptance:** Opposition number/stages are not reused for a rectification or non-use proceeding unless the source legally provides the same form/rule and the type remains distinct.

### UJ-39: Manage patent prosecution or opposition

**Actor:** Patent Attorney.  
**Preconditions:** Patent application/family, jurisdiction, applicant/inventor, specification/claim version, and source identifiers exist.  
**Main flow:** User records filing/publication/examination request, FER/office action, response deadline, hearing, amendment, pre/post-grant opposition, grant/refusal, and appeal events; claim/specification/drawing versions are linked to filing packages; rule engine calculates jurisdiction-specific deadlines; attorney reviews source and approves response; filing transaction/acknowledgement updates prosecution; grant creates annuity/working/recordal obligations.  
**Exceptions:** Family member events do not propagate without explicit relationship rule; amended claims never overwrite filed/granted sets; opposition is a separate proceeding; source ambiguity creates pending confirmation.  
**Audit/postcondition:** Family tree, prosecution timeline, document versions, deadlines, and proceedings are independently auditable.  
**Acceptance:** No trademark event/status/rule is used to represent patent prosecution.

### UJ-40: Manage patent annuity and working requirement

**Actor:** Patent Docketing Manager / Finance Coordinator.  
**Preconditions:** Granted/pending right and applicable jurisdiction/rule term are verified.  
**Main flow:** System proposes annuity/renewal and jurisdiction-specific working/compliance obligations; user confirms rule/source, proprietor, small/entity status where relevant, amount/currency, and instruction deadlines; client instruction and funds are recorded; payment/filing transaction and official/associate receipt are reconciled; accepted completion creates next obligation; report distinguishes upcoming, instructed, paid/filed, accepted, grace/restoration, and overdue.  
**Exceptions:** Fee/entity/rule change invalidates quote; payment without office evidence remains pending; lapse/restoration creates separate legal review; no-working or not-applicable declaration follows approved form logic.  
**Audit/postcondition:** Calculation, quote, instruction, transaction, receipt, acceptance, and next term remain linked.  
**Acceptance:** Financial payment status cannot masquerade as legal renewal/working compliance.

### UJ-41: Manage industrial design lifecycle

**Actor:** Design Attorney.  
**Preconditions:** Applicant/owner, article, representations, classification, novelty statement, jurisdiction, and filing instruction exist.  
**Main flow:** User creates design asset/application; prepares representation set and filing package; records filing, examination/objection, response/hearing, acceptance/registration/publication, renewal/extension, assignment, cancellation, and infringement linkage; registry snapshots and deadlines use design-specific rules; client report shows each design/jurisdiction separately.  
**Exceptions:** Revised representations create version set; multiple designs/variants follow jurisdiction-specific relationship rules; confidentiality/publication timing remains explicit; cancellation is a separate proceeding.  
**Audit/postcondition:** Representation and legal-event versions remain source linked.  
**Acceptance:** Design workflows do not expose trademark classes/forms/statuses as if applicable.

### UJ-42: Manage copyright lifecycle and enforcement

**Actor:** Copyright Attorney.  
**Preconditions:** Work, author/claimant/owner roles, creation/publication facts, territory, and confidentiality are known to the available degree.  
**Main flow:** User registers work/ownership chain; optionally prepares copyright application and tracks deficiency, objection, hearing, registration, correction, or expungement; links assignments/licences and deposited versions; infringement/takedown intake preserves evidence, platform/party notices, responses, settlement, and litigation; permissions restrict unreleased/confidential works.  
**Exceptions:** Authorship and ownership disputes remain unresolved claims with evidence; registration is not treated as creation of underlying rights; takedown platform response is not court/registry disposition.  
**Audit/postcondition:** Work versions, rights chain, filings, licences, notices, and enforcement Matters remain connected.  
**Acceptance:** Reports clearly distinguish claimed ownership, documented chain, application, and registration status.

### UJ-43: Manage assignment, licence, and obligations

**Actor:** Transactional IP Lawyer / IP Operations.  
**Preconditions:** Agreement/instrument and affected rights/parties are permission-accessible.  
**Main flow:** User records grant/transfer type, exclusivity, territory, field, sublicensing, term, rights, quality/control, royalty/fee, minimums, reporting, audit, prosecution/enforcement control, recordal, renewal/termination, and notice obligations; source agreement provisions cite exact document version/pages; obligations create tasks/deadlines and finance linkage; recordal transactions update effective-dated interests after acceptance.  
**Exceptions:** Contract interpretation remains lawyer-reviewed; ambiguous clauses create review issue; confidential financial terms stay out of ordinary portfolio/client views; termination does not delete historical permission/ownership periods.  
**Audit/postcondition:** Agreement version, extracted/approved terms, obligations, performance evidence, notices, and rights impact remain linked.  
**Acceptance:** Registry ownership, contractual beneficial interest, licence permission, and billing obligation are separately represented.

### UJ-44: Manage GI, plant variety, layout design, or trade secret

**Actor:** Specialist IP Lawyer.  
**Preconditions:** Corresponding asset module enabled with approved type-specific taxonomy/rules.  
**Main flow:** User selects exact right type; completes type-specific intake (GI applicant/territory/specification/authorised user; plant variety category/denomination/breeder/farmer/crop/DUS/seed; layout creator/exploitation; trade-secret custodian/access/protection); records filings/oppositions/registration/fees/licences/cancellation/enforcement as applicable; deadlines and documents use right-specific rules; reports retain source and confidentiality.  
**Exceptions:** Disabled type cannot be created through a generic fallback; trade-secret substance is excluded from general AI/index; biological material/evidence access follows policy; public registry data and confidential know-how are separated.  
**Audit/postcondition:** Type-specific ownership, events, documents, obligations, and source trail exist without trademark assumptions.  
**Acceptance:** Each enabled type has dedicated legal fixtures and SME acceptance before production use.

### UJ-45: Manage customs or anti-counterfeiting action

**Actor:** Enforcement Lawyer / Coordinator.  
**Preconditions:** Enforceable right, client instruction, product/authentication material, authorised importer policy, and jurisdiction/channel are recorded.  
**Main flow:** User creates/renews customs or platform recordal; records rights, products, guides, contacts, bonds/fees, and expiry; detention/alert creates incident with source, goods/importer/seller, quantities, location, evidence, and response deadline; lawyer reviews authenticity/risk and obtains client instruction; action records sample/inspection, notice, release/detention/destruction, settlement, cost, and linked litigation/investigation; watch intelligence updates known parties/products.  
**Exceptions:** Sensitive authentication guides are narrowly permissioned; suspected counterfeit is not labelled confirmed before review; urgent deadline escalation survives external-channel failure; seizure/release outcome does not automatically prove infringement.  
**Audit/postcondition:** Recordal, incident, evidence chain, instruction, costs, authority/platform response, and enforcement outcome remain linked.  
**Acceptance:** Chain of custody and every external communication/source are auditable.

### UJ-46: Apply or revoke IP ethical-wall access

**Actor:** Owner/Admin or authorized Access Administrator.  
**Preconditions:** Docket record/client portfolio and intended membership/team/portal user exist; actor may manage access.  
**Main flow:** Actor opens Access; reviews current internal, inherited team/client, linked Matter, portal, document-category, report, and notification visibility; selects restricted/default policy and grants/revokes specific membership/team or portal scope; preview shows affected records/actions and any linked-record mismatch; actor confirms with reason and expected record version; service writes grants/revocations and audit; search/index/assistant caches and queued delivery are invalidated/rechecked.  
**Exceptions:** Actor cannot remove own last required owner access without second authorized owner; cross-company subject is rejected; linked Matter is not silently broadened; revoked portal user/session follows immediate session-invalidity policy.  
**Audit/postcondition:** Grant source, scope, actor, reason, effective/revoked time, invalidation operation, and affected-resource count remain visible.  
**Acceptance:** Revoked user cannot discover the record through direct URL, counts, search, autocomplete, export, document/source proxy, assistant, notification, or portal.

### UJ-47: Propose, test, activate, and retire legal rule version

**Actor:** Rule Curator proposes; separate qualified IP Legal Approver activates.  
**Preconditions:** Verified source/version, jurisdiction/office scope, engine compatibility, and lawyer-approved positive/negative/boundary fixtures exist.  
**Main flow:** Curator creates immutable draft version and enters rule inputs/formula/calendar/source/effective range; automated fixtures produce explainable calculations and diffs from prior version; curator submits; second legal approver reviews source and every changed fixture; system previews companies/records/open deadlines affected; approver activates for permitted platform scope; company admin separately selects policy/auto-confirm eligibility; later change creates new version; retirement/emergency disable follows impact/alert workflow.  
**Exceptions:** Proposer cannot self-approve; failed fixture/source link blocks activation; overlapping effective ranges conflict; activation does not rewrite confirmed deadlines; emergency disable stops new auto-calculation but preserves history.  
**Audit/postcondition:** Source hash, draft/approval actors, fixtures/results, impact preview, activation/retirement, company policy, and each execution version remain traceable.  
**Acceptance:** Any deadline can be reproduced with the exact rule/engine/source inputs active when it was calculated.

### UJ-48: Verify, quarantine, or supersede legal source

**Actor:** Knowledge Lawyer / Source Curator.  
**Preconditions:** Candidate statute, judgment, form, fee, rule, registry, or classification source has publisher/URL or preserved acquisition evidence.  
**Main flow:** Curator opens candidate and current published record side by side; validates publisher, document identity/citation, jurisdiction, effective/version date, completeness, section/page structure, content hash, attribution/licence, and URL/access mode; system highlights mismatches and dependent records; curator verifies, quarantines, rejects, or supersedes with reason; approved content is indexed; quarantine removes it from authoritative retrieval and flags dependent analysis; link health and periodic recertification are scheduled.  
**Exceptions:** Inaccessible source cannot become verified solely from AI text; editorial commentary is separated; changed official content creates new version; licence restriction can permit internal search but prohibit export; urgent quarantine is allowed with later second review.  
**Audit/postcondition:** Acquisition, compare diff, decision, actors, source/version/hash, dependent-impact action, and index operation remain recorded.  
**Acceptance:** Public users and AI cannot retrieve quarantined text as authoritative, while audit retains why it was removed.

### UJ-49: Onboard IP client/work and clear firm conflict

**Actor:** Intake Lawyer/Coordinator; Partner resolves/approves where required.  
**Preconditions:** Prospective client/contact and proposed work are known to the available degree.  
**Main flow:** User creates IP intake; records client/proposed mark/right, relevant/adverse/related parties, jurisdictions, urgency/limitation, instruction, documents, and requested service; runs company conflict check against existing clients/Matters/IP records; reviewer clears, rejects, or records approved waiver; KYC/engagement and preliminary-work policy are completed; partner accepts work and assigns team; intake promotes idempotently to search project/application/proceeding/Matter links without duplicate re-entry.  
**Exceptions:** Urgent preliminary research is separately approved and cannot become filing authority; conflict hit details respect ethical walls; legal availability search is not treated as firm conflict; rejected/withdrawn intake remains auditable but unpromoted.  
**Audit/postcondition:** Intake versions, checks/results, waiver/engagement, instruction, assignment, promotion IDs, and actor history remain linked.  
**Acceptance:** A user cannot mark `conflict cleared` from a trademark search result, and promotion cannot create duplicate active records on retry.

### UJ-50: Triage daily docket and workload

**Actor:** Docketing Manager / Team Lead.  
**Preconditions:** User has permitted team/client/IP scope and configured working timezone.  
**Main flow:** User opens Daily Docket; system groups critical deadlines/hearings, internal targets, filing evidence gaps, unconfirmed/recalculated dates, stale registry/case data, failed/suppressed reminders, client/associate responses, renewals, and overdue tasks; user filters by team/person/client/jurisdiction/risk; opens source/calculation; assigns/reassigns with impact preview; responsible user acknowledges; manager escalates or records backup; resolved items leave active queue but remain in history.  
**Exceptions:** Restricted work contributes no leaked counts; absent/disabled user triggers backup policy; stale provider data is not shown as no work; unacknowledged critical item re-escalates.  
**Audit/postcondition:** Queue snapshot/report, assignment, acknowledgement, escalation, override, and resolution evidence are recorded.  
**Acceptance:** Manager can identify every critical item without combining side spreadsheets, provider portals, and hidden notification logs.

### UJ-51: Capture correspondence and client or associate instruction

**Actor:** Lawyer or Paralegal.  
**Preconditions:** Communication is received/sent or being prepared and actor can access relevant records.  
**Main flow:** User imports/records email, portal message, letter, call, meeting, registry notice, or associate advice; confirms direction, parties, channel, dates, subject, confidentiality, documents, affected docket records, response requirement, and candidate instruction/event. Accepted legal notice correspondence creates or links one existing `CompanyNotice` and `company_notice_ip_link`; the notice register owns notice/reply workflow while any legal due date delegates to one `ip_deadline`. System proposes tasks/deadlines but does not apply legal state; authorized user acknowledges/accepts/rejects/clarifies instruction; accepted instruction creates explicit event/task/filing decision; response delivery and acknowledgement are tracked.  
**Exceptions:** Duplicate connector/manual communication is reconciled by message/hash/evidence; an existing notice is linked instead of copied; replacing a convenience notice file cannot overwrite immutable legal evidence; notice claim/amount fields cannot create a cost/payment; bounced email is not delivered instruction; ambiguous instruction remains pending; privileged correspondence is excluded from portal/general AI; mixed-access notice links fail closed rather than becoming company-visible standalone notices.  
**Audit/postcondition:** Original/source metadata, Communication/CompanyNotice/document IDs, classifications, instruction decision, legal-deadline correlation, tasks/events, delivery, response, and actor remain linked.  
**Acceptance:** No inbound message alone can file, abandon, waive, close, or change a legal right.

### UJ-52: Record time, cost, invoice, and payment linkage

**Actor:** Lawyer records time; Finance/authorized staff manages cost/invoice/payment.  
**Preconditions:** Docket record is linked to existing client and approved Matter/billing profile or approved nonbillable policy.  
**Main flow:** User records billable time in the existing `MatterTimeEntry` flow against the approved linked billing Matter and references the IP event/task/filing/hearing. Official/associate/translation/courier costs create one `ip_cost_item` from approved quote/transaction or manual evidence with original amount/currency/tax; immutable evidence links point to document/filing/Communication/notice records; finance marks billable/nonbillable and creates one unique link to an existing manual invoice line or outside-counsel spend record; existing invoice/payment workflow issues/reconciles; IP report shows operational cost state without duplicating ledger truth.  
**Exceptions:** No billing Matter blocks billable time/invoicing but not nonbillable legal-cost capture; exchange conversion preserves original amount/rate/source/time; filing payment is not client payment; provider-estimated cost is not actual expense; confidential rates are permissioned; invoice void/write-off follows existing capability/audit.  
**Audit/postcondition:** Matter time entry, IP cost owner, evidence links, billing link, invoice/payment/spend IDs, approvals, adjustments, and client visibility remain traceable without a separate disbursement state.  
**Acceptance:** IP module does not create a second invoice/payment ledger and cannot infer legal filing acceptance from financial payment.

### UJ-53: Close, abandon, transfer, or retire IP record

**Actor:** User with `ip:approve`; second approval where tenant policy requires.  
**Preconditions:** Current lifecycle/version is known and disposition source/instruction is available.  
**Main flow:** Actor selects dedicated transition and supplies effective date, reason/outcome, source/evidence, successor/transferee where applicable, and client/report handling; system locks parent and previews open deadlines/hearings/tasks/filings/reminders/watch/report/portal/linked-Matter impact; actor resolves required exceptions and confirms expected state/version; transaction sets terminal state/active flag/version, neutralizes or transfers operational children, cancels/supersedes reminders, updates access/reporting, emits audit/outbox, and preserves redirect/relationship where needed.  
**Exceptions:** Generic PATCH/import/worker/child event cannot reactivate; pending appeal/stay/recordal can block or qualify closure; transfer may move responsibility without changing legal status; reopening uses a separate controlled transition with no child resurrection.  
**Audit/postcondition:** Before/after state, source, instruction, actor, impact decisions, child outcomes, successor, and linked-Matter review remain immutable.  
**Acceptance:** Terminal state persists after reload and concurrent stale writes fail without reviving work or reminders.

### UJ-54: Capture and approve complete trademark filing particulars

**Actor:** Paralegal prepares; Trademark Attorney reviews/approves.  
**Preconditions:** Client/work is accepted, intended jurisdiction/legal act is selected, and an approved effective form/schema version exists.  
**Main flow:** User selects mark/application type and filing mode; captures exact representation/text/language/transliteration/translation/colour or media details; enters every applicant, address, agent, signatory and authorization; creates separate class/specification rows; records use basis/claim and affidavit evidence, priority and certificate, collective/certification regulations, and related/series/divisional links as applicable; system runs conditional schema, duplicate, party, document, fee, and source checks; preparer resolves exceptions; reviewer compares the exact filing preview and immutable manifest; approval locks the package version for UJ-32.  
**Exceptions:** Unsupported mark/form type blocks filing-ready state; missing priority/use evidence creates explicit exception and rule-derived candidate deadline; changed applicant/specification after approval supersedes the manifest and requires reapproval; imported registry data never silently fills a declaration.  
**Audit/postcondition:** Schema/form/source versions, field provenance, validation results, representation and specification versions, review diff, approval, manifest hash, and supersession remain linked.  
**Acceptance:** The approved manifest can reproduce every intended submitted fact/document/fee and cannot be mutated by a later metadata edit.

### UJ-55: Triage inbound registry, court, client, or associate communication

**Actor:** Docketing Specialist or assigned Lawyer.  
**Preconditions:** Approved mailbox/provider/manual intake is configured and the actor has access to the candidate records.  
**Main flow:** System/manual action ingests the immutable message/calendar/document envelope; deduplicates by source identity and hash; sanitizes display content and scans attachments; proposes communication/notice type, client/mark/identifiers, candidate links, dates, response duty, instruction, event and deadline; queue owner opens original evidence and confidence; links one or more records or marks duplicate/irrelevant/exception. If accepted as a legal notice, the command creates/reuses one `CompanyNotice`, applies its IP link/access policy, and delegates any legal deadline; authorized user separately accepts any instruction, hearing or other legal effect; assignment and SLA are resolved.  
**Exceptions:** Ambiguous identifiers remain unmatched; restricted candidate links reveal no record name/count to an unauthorized triager; mixed-access notice audience cannot be inferred; malformed/encrypted attachment enters exception; webhook and polling duplicate one another without duplicate notice/legal effects; deletion from the source mailbox does not erase held evidence.  
**Audit/postcondition:** Original source identity/hash, ingestion attempts, classification candidates, access decisions, triage outcome, CompanyNotice/link/deadline IDs, accepted effects, and response evidence remain linked.  
**Acceptance:** Every selected inbound item reaches an explicit terminal/exception state, and no extraction alone changes legal state.

### UJ-56: Calculate a deadline across holiday, closure, extension, or uncertain trigger

**Actor:** Docketing Manager; Attorney confirms legal interpretation where required.  
**Preconditions:** Trigger candidate, legal rule version, office/jurisdiction, and applicable calendar policy are available.  
**Main flow:** User opens proposed calculation; system displays source trigger, date precision, duration/unit/inclusion method, office timezone, weekends, holidays/closures, exceptional working days, extension/order and downstream graph; engine computes candidate legal deadline and separate internal targets; user opens governing source and calendar evidence; confirmer accepts or corrects the trigger/rule/calendar with evidence; responsibilities/reminders are assigned; calculation and versions are frozen.  
**Exceptions:** Conflicting publication/service dates, missing official closure evidence, unknown time, or unsupported extension creates provisional range/escalation and blocks auto-confirm; calendar correction produces impact scan; an extension application does not move the legal deadline until approved rule/event permits it.  
**Audit/postcondition:** Every input/version/intermediate step, source, confirmer, override, dependent impact and reminder generation remains reproducible.  
**Acceptance:** A second reviewer can reproduce the displayed result exactly, or the system clearly refuses to claim an exact deadline.

### UJ-57: Reassign critical work for leave, transfer, or deactivation

**Actor:** Team Lead or Docketing Manager; security/admin initiates deactivation where applicable.  
**Preconditions:** A membership, team, or responsibility is scheduled for leave/change/deactivation and open operational work exists.  
**Main flow:** Initiator requests reassignment; system locks/versions the responsibility set and previews deadlines, hearings, filings, tasks, reminders, inbox queues, reports and client/associate commitments by risk/date; initiator selects replacement primary/backup/supervisor and effective time; recipients accept or approved emergency policy assigns coverage; transaction supersedes assignments, updates pending notification targets/calendar projections without altering sent history, and records unresolved exceptions; membership deactivation proceeds only after policy gates pass.  
**Exceptions:** Replacement lacks access/capability; ethical wall blocks bulk transfer; assignee rejects; concurrent work changed after preview; emergency owner receives temporary restricted coverage with expiry/escalation; completed/sent artifacts remain attributed to original actor.  
**Audit/postcondition:** Preview version, affected IDs, old/new roles, acceptance, exceptions, effective time, access changes, and notification/calendar effects are recorded.  
**Acceptance:** No active critical item is unowned or silently duplicated after reload, deactivation, worker replay, or rollback.

### UJ-58: Respond to a suspected missed or incorrect deadline

**Actor:** Risk Partner or authorized Docketing Manager with restricted incident team.  
**Preconditions:** User/monitor identifies possible lateness, incorrect calculation, absent owner/reminder, or corrupt source/rule/calendar.  
**Main flow:** Actor opens restricted incident without editing the deadline; system preserves calculation, rule/calendar/source versions, messages, provider events, audit and related records; risky cleanup/recalculation publication is paused; team verifies source and affected rights, opens corrective tasks/filing or external-advice actions, scans all records using the same defect, and records approved communications under firm policy; ordinary docket is corrected only through superseding events/calculations; root cause and preventive action are verified before closure.  
**Exceptions:** Suspicion is disproved but evidence remains; remedy availability is uncertain and CaseOps abstains; legal hold blocks deletion; affected clients/insurers have different notification decisions; platform-wide defect triggers kill switch and broader incident process.  
**Audit/postcondition:** Discovery, restriction, evidence snapshot, containment, impact set, decisions, communications, corrections, root cause, prevention and approvals remain immutable and separately permissioned.  
**Acceptance:** The firm can prove what was known and done without backdating/erasing docket history or exposing privileged incident analysis.

### UJ-59: Produce and sign off a daily docket control report

**Actor:** Docketing Manager prepares; Supervising Partner/second docket reviewer signs where policy requires.  
**Preconditions:** Team queues, calendar/rule versions, responsibility assignments, provider freshness and exception policies are configured.  
**Main flow:** User generates a dated manifest of critical deadlines/internal targets/hearings, unconfirmed/provisional dates, unowned/unacknowledged items, failed reminders, stale sources/sync, pending filings/service, inbox aging and overrides; report records filters, timezone, generation/freshness cutoffs and hidden restricted-count policy; manager resolves or annotates exceptions; second reviewer samples source/calculation/coverage; both sign the immutable report version; later changes appear in a delta, not the signed snapshot.  
**Exceptions:** Stale provider or failed query makes the report incomplete and blocks clean sign-off; restricted records are included only for authorized reviewers and never leaked as counts; export generation failure does not mark review complete.  
**Audit/postcondition:** Report query/version, included record IDs/hashes, freshness, exceptions, reviewer evidence, signatures and subsequent deltas are retained under policy.  
**Acceptance:** The signed report is reproducible and cannot state `all clear` while a critical exception or failed data source is hidden.

### UJ-60: Qualify and launch a non-trademark IP domain

**Actor:** Product Owner and Specialist IP Lawyer, with Engineering/Security/Operations reviewers.  
**Preconditions:** Proposed domain, jurisdictions, pilot users and target beta/GA claim are named.  
**Main flow:** Team inventories real user workflows, right-specific parties/relationships/states/forms/fees/rules/sources/providers/documents/deadlines and migration data; writes and approves child PRD with normal/exception/contested/transfer/maintenance/closure journeys; threat and confidentiality model is completed; legal fixtures and source pack receive two-reviewer approval; architecture proves reuse boundaries and prevents trademark-state leakage; implementation, migration, pilot UAT and operational evidence pass; capability service changes label from unavailable/intake-only to beta/GA.  
**Exceptions:** Missing official/contracted source keeps automation manual; generic asset storage may launch as intake-only but not docket support; unsupported jurisdiction remains disabled; beta defect or legal-source change can downgrade/kill-switch capability without deleting history.  
**Audit/postcondition:** Child PRD/version, approvals, source/rule packs, capability evidence, pilot acceptance, label changes and rollback remain linked.  
**Acceptance:** No domain is represented as supported merely because a table enum, roadmap row, or generic form exists.

### UJ-61: Reconcile chain of title and related-right family

**Actor:** IP Attorney or Docketing Specialist; authorized Attorney approves legal effect.  
**Preconditions:** Candidate applications/registrations/rights, parties, assignments/licences/security interests or family relationships and source documents exist.  
**Main flow:** User selects rights/territories; enters dated predecessor/successor, applicant/proprietor/inventor/author/licensee roles, relationship type, scope, consideration/encumbrance metadata where permitted, execution/effective dates and recordal requirements; system detects gaps, overlaps, cycles, conflicting owners and pending registry state; attorney approves internal legal-chain interpretation; filing packages/obligations are created; registry acceptance updates the registered-owner projection without erasing beneficial/pending history; consolidated family view remains source-qualified.  
**Exceptions:** Executed but not effective, effective but unrecorded, partial-class/territory transfer, disputed title, missing document, confidentiality restriction or provider conflict remain explicit; one right's recordal cannot update another by family association alone.  
**Audit/postcondition:** Every relationship/party version, source, approval, conflict, filing/recordal and registry result is effective-dated and traceable.  
**Acceptance:** A date-specific report can state both the supported ownership chain and unresolved gaps without collapsing legal/registered/beneficial states.

### UJ-62: Synchronize an external calendar without surrendering docket authority

**Actor:** Lawyer or Docketing Manager.  
**Preconditions:** Tenant-approved calendar provider/account, permission scope, timezone and sync policy are configured.  
**Main flow:** User enables selected deadline/hearing/task projections; service creates stable provider event IDs with minimal permitted content, CaseOps source link and version; update/reschedule/cancel emits idempotent provider operation; inbound provider edits are shown as candidates or rejected according to policy; user opens CaseOps from event and sees authoritative calculation/freshness; disconnect/reconnect reconciles without duplicates.  
**Exceptions:** Provider outage/rate limit shows stale projection and retries; revoked access removes future provider operations but preserves history; user deletes/edits external event without changing CaseOps; ethical-wall or sensitivity policy redacts title/body; timezone shift does not move a date-only legal obligation.  
**Audit/postcondition:** Consent/account, selected scope, payload version/hash, provider IDs/attempts, candidate edits, reconciliation and disconnect are recorded without storing provider secrets.  
**Acceptance:** Repeated sync/reconnect produces one current projection per obligation while CaseOps remains the only authority for legal state/date.

### UJ-63: Grant, use, expire, and review emergency access

**Actor:** Access Administrator/approved emergency policy grants; Emergency User acts; independent Reviewer certifies.  
**Preconditions:** User lacks ordinary required access, a specific urgent purpose/record scope exists, MFA/step-up is available, and tenant emergency policy names duration/notification/reviewer.  
**Main flow:** Requester selects exact client/records/capabilities, reason/ticket and shortest duration; system shows conflicts/ethical wall and data sensitivity; approver or documented emergency policy authorizes after step-up; temporary session is issued with prominent state and no grant inheritance; every read/download/write is separately marked; expiry/revocation terminates session and invalidates caches/tokens; designated owner receives safe notification; independent reviewer inspects actions and closes or escalates.  
**Exceptions:** Company isolation, provider secret, platform-finance and unsupported capability can never be granted; missing MFA blocks; incident emergency may allow preapproved immediate access but requires shorter expiry and retrospective review; extending duration is a new approval.  
**Audit/postcondition:** Request, reason/ticket, scope, policy/approver, step-up, start/expiry/revocation, actions, notifications and review outcome remain tamper-evident without copying accessed content.  
**Acceptance:** After expiry/revocation the user receives no result/count/source/cache access, and review proves there is no surviving standing grant.

### UJ-64: Place legal hold, export, and purge governed tenant data

**Actor:** Risk/Records Manager requests; Owner/Security or second authorized approver executes.  
**Preconditions:** Verified request/purpose and target scope exist; current data map, retention policies, source licences, provider contracts and legal-hold authority are configured.  
**Main flow:** For hold, manager scopes records/custodians/classes/dates, obtains dual approval and issues preservation; integrity scan applies it to current/future objects. For export/purge, user creates dry run; operation inventories SQL/object versions/index/cache/queue/log/provider/backup classes, evaluates grants/holds/licences, and produces inclusions/exclusions/counts/checksums/dependencies; approvers step up and confirm the immutable manifest; resumable executor processes/checkpoints every subsystem; verification scans for orphan/still-searchable/missing data and produces signed completion/exception manifest; expiring export delivery is audited.  
**Exceptions:** Hold or retention blocks purge; source licence blocks payload export but permits citation metadata; provider deletion is pending; backup expiry is deferred but production tombstone prevents resurrection; failed subsystem remains exception and cannot produce `complete`.  
**Audit/postcondition:** Request/identity, policy/hold/source versions, dry-run and execute manifests, approvals, checkpoints, row/object/index/provider outcomes, downloads, tombstones and verification remain immutable.  
**Acceptance:** A throwaway-tenant drill reconciles every registered data class, and a restore/reindex cannot resurrect purged or held-inconsistently handled data.

### UJ-65: Restore CaseOps and resume legal operations without duplicate effects

**Actor:** SRE/Incident Commander; Docketing/Legal verifier accepts operational recovery.  
**Preconditions:** Authorized incident/drill, recent backup/object versions, immutable application image/schema plan, secrets/configuration and isolated/failover target are available.  
**Main flow:** Commander fences serving workers/dispatchers and records recovery point; restores database and object state; applies compatible migrations/configuration/secrets; boots exact application image; applies purge tombstones/holds; validates counts/hashes/FKs/lifecycle-event reconciliation/index generations/outbox/idempotency/provider cursors; warms safe indexes; legal verifier opens restricted/ordinary records, documents, sources, docket/deadline/history and export; operator previews pending outbox/notification/provider effects, invalidates old leases and enables one dispatcher per effect class; synthetic/no-op canaries pass; service resumes and RPO/RTO are measured.  
**Exceptions:** Missing object/key, corrupt index or unsafe pending send keeps affected capability disabled; old region/process is not provably fenced; restore predates purge; provider unavailable uses manual/degraded path; RPO/RTO breach opens corrective action and disclosure review.  
**Audit/postcondition:** Incident/change authorization, source backup/recovery time, target/image/schema/config hashes, validations, fences, canaries, dispatcher ownership, timings, gaps and reviewer acceptance are recorded without tenant content.  
**Acceptance:** Restored service completes the release-blocking smoke set and sends/files/pays nothing twice when workers resume.

### UJ-66: Revoke private content from search and AI projections

**Actor:** Access Administrator or Records Manager.  
**Preconditions:** Grant/document/source/lifecycle/hold/purge policy changes and affected private projections exist.  
**Main flow:** Authorized command commits revocation/tombstone and projection event; current generation marks candidates unavailable; hydration blocks immediately; workers remove/rebuild lexical/vector chunks, caches and derived summaries; saved answer/review/report access is recalculated and locked/redacted where necessary; integrity scan searches all generations/providers and reports completion; safe affected-user notification is issued where policy requires.  
**Exceptions:** Worker/index outage leaves fail-closed hydration and visible lag; legal hold preserves source bytes but does not preserve revoked general search access; public source remains public while private annotations disappear; provider deletion delay remains explicit exception.  
**Audit/postcondition:** Trigger/policy versions, affected source/projection IDs, events, cache/index/provider outcomes, saved-output decisions, lag and verification remain recorded.  
**Acceptance:** Direct ID, keyword, vector, autocomplete, count, citation, cache, export and reindex tests reveal no revoked content or existence to the unauthorized actor.

### UJ-67: Deploy an additive migration through mixed revisions and rollback

**Actor:** Engineer prepares; SRE/deployment owner executes and verifies.  
**Preconditions:** Current `main`, production Alembic head/revisions/jobs, backup/restore point, compatibility matrix, data map, backfill and rollback/roll-forward plan are verified.  
**Main flow:** Add expand migration and old/new compatible code; run Postgres/upgrade tests and sanitized production-shape rehearsal; deploy migration job; verify constraints/indexes; deploy one canary new revision while old serving/jobs remain; prove old/new reads/writes, outbox fencing and feature-off behavior; run resumable dry-run/backfill with reconciliation; shadow/dual-read only where specified; switch server flag/worker ownership; execute dated production smoke on exact image; observe; later remove compatibility only after all revision/job evidence and rollback window close.  
**Exceptions:** Lock/table-scan estimate exceeds window; mixed-version contract fails; backfill mismatch; canary or SLO fails; rollback disables feature/code while additive schema/history stays; destructive downgrade is replaced by restore/roll-forward rehearsal.  
**Audit/postcondition:** Commit/image/schema heads, migration/backfill manifests, revision inventory, flags/fences, canary/smoke/SLO, rollback decision and contract-cleanup evidence remain linked.  
**Acceptance:** Old and new revisions coexist without corrupting legal state, and rollback after a committed event preserves that event and prevents duplicate consumers.

### UJ-68: Rotate or disconnect an integration credential

**Actor:** Tenant Admin for consent/configuration; SRE/platform owner for platform credentials.  
**Preconditions:** Existing connector/provider configuration, scoped replacement/revocation plan, affected jobs/webhooks/cursors and test/sandbox path are known.  
**Main flow:** Actor steps up; reviews scopes/accounts/affected features and queued operations; creates new secret/version or revokes consent through existing connector service; tests authentication and least scopes without displaying secret; atomically activates new reference/config version; invalidates caches/sessions/webhook signing material as applicable; canary runs; old credential is revoked after overlap policy; pending operations resume idempotently or remain blocked; disconnect stops polling/sends, marks freshness degraded, preserves evidence and queues offboarding/deletion actions.  
**Exceptions:** Test fails and old credential remains active within approved window; compromise requires immediate revoke/kill switch; provider cannot overlap keys; webhook events arrive under old key after cutoff and are rejected safely; disconnect leaves manual docketing available.  
**Audit/postcondition:** Request/step-up, scope/config versions, secret reference identifiers only, tests, activation/revocation, affected operations, canary, provider deletion and final health remain recorded.  
**Acceptance:** No secret appears in API/UI/log/audit, exactly one active credential/config owns new effects, and disconnected automation is visibly not healthy.

## 16. API and service contracts

API routes follow existing `/api` patterns, tenant context, capability checks, pagination, audit, idempotency, and optimistic concurrency.

### 16.1 Core IP APIs

`/api/ip` routes own new IP legal commands. When they expose task, hearing, operational-deadline, document-processing, portal, access, import, billing, drafting, provider-operation, or report behavior, they are thin context adapters over the shared owner in Section 11.2; they do not write parallel state.

- `GET/POST /api/ip/assets`
- `GET/PATCH /api/ip/assets/{asset_id}`
- `GET/POST /api/ip/trademark-applications`
- `GET/PATCH /api/ip/trademark-applications/{application_id}`
- `GET/POST /api/ip/trademark-applications/{application_id}/representations`
- `GET/POST /api/ip/trademark-applications/{application_id}/scopes`
- `POST /api/ip/trademark-applications/{application_id}/filing-manifests`; `POST /filing-manifests/{id}/approve`
- `GET/POST /api/ip/proceedings`
- `GET/PATCH /api/ip/proceedings/{proceeding_id}`
- `POST /api/ip/{record_type}/{record_id}/events`
- `GET /api/ip/{record_type}/{record_id}/timeline`
- `GET/POST/PATCH /api/ip/deadlines`
- `POST /api/ip/deadlines/{deadline_id}/confirm`
- `POST /api/ip/deadlines/{deadline_id}/override`
- `POST /api/ip/deadlines/{deadline_id}/complete`
- `GET/POST/PATCH /api/ip/tasks` and `/api/ip/hearings` as adapters over shared task/hearing services and rows
- `GET/POST /api/ip/responsibility-assignments`; `POST /responsibility-assignments/{id}/accept`; `POST /reassignment-plans/{id}/commit`
- `GET/POST /api/ip/inbox`; `POST /inbox/{id}/classify`; `POST /inbox/{id}/resolve`; `POST /inbox/{id}/accept-effect`
- Existing `GET/POST/PATCH /api/notices` remains the accepted-notice owner; additive `/api/notices/{id}/ip-links` create/retire actions and IP-aware filters/download authorization extend it. Inbox acceptance calls this service rather than writing notice state.
- `POST /api/ip/communication-links`; `DELETE /communication-links/{id}` retires only the link and never deletes the underlying communication/evidence
- `GET/POST /api/admin/legal-working-calendars`; `POST /legal-working-calendar-versions/{id}/activate`; `POST /legal-working-calendar-versions/{id}/impact`
- `GET/POST /api/ip/deadline-incidents`; `POST /deadline-incidents/{id}/transitions`; `POST /deadline-incidents/{id}/impact-scan`
- `GET/POST /api/ip/documents`; `POST /documents/{id}/versions`; `POST /versions/{id}/approve`; `POST /document-links`
- Existing `/api/portal` administration extends grant targets to IP docket records; revoke/expiry/share-preview use the same portal service and identity
- `GET/POST /api/access/grants`; `POST /access/grants/{id}/revoke`; existing Matter access routes remain compatibility adapters
- `GET/POST /api/admin/access-reviews`; `POST /access-reviews/{id}/decisions`; `POST /access-reviews/{id}/complete`
- `POST /api/admin/emergency-access/requests`; `POST /emergency-access/{id}/approve`; `POST /emergency-access/{id}/revoke`; `POST /emergency-access/{id}/review`
- `GET/POST /api/ip/imports`; `POST /validate`; `POST /commit`; `GET /errors`; `GET /history`, all using neutral `bulk_import_jobs` with IP row adapters. Aggregated legacy Matter/Employee history is read-only through compatibility adapters.
- `GET/POST /api/ip/registry-links`; `POST /refresh`; `GET /diffs`; `POST /diffs/{id}/resolve`
- `GET/POST /api/ip/watch-profiles`; `GET/PATCH /api/ip/watch-hits/{id}`
- `GET/POST /api/ip/search-projects`; `POST /search-projects/{id}/run`; `POST /search-projects/{id}/approve`
- `GET/POST /api/ip/filing-packages`; `POST /filing-packages/{id}/approve`; `POST /filing-packages/{id}/transactions`
- `GET/POST /api/ip/cost-items`; `POST /cost-items/{id}/approve`; `POST /cost-items/{id}/evidence-links`; `POST /cost-items/{id}/billing-link`. Evidence-link routes cannot mutate paid/approved/reconciled state on referenced billing or spend records.
- `GET/POST /api/ip/international-registrations`; `GET/POST /international-registrations/{id}/designations`
- `GET/POST /api/ip/recordals`; `POST /recordals/{id}/transactions`
- `GET/POST /api/ip/reports`; `POST /reports/{id}/publish`
- `GET/POST /api/ip/workflow-versions`; `POST /workflow-versions/{id}/validate`; `POST /workflow-versions/{id}/activate`; `POST /workflow-versions/{id}/impact`
- `GET/POST /api/admin/data-retention-policies`; `POST /data-retention-versions/{id}/activate`
- `GET/POST /api/admin/legal-holds`; `POST /legal-holds/{id}/release`
- `GET/POST /api/admin/data-operations`; `POST /data-operations/{id}/approve`; `POST /data-operations/{id}/execute`; `GET /data-operations/{id}/manifest`

Existing API families receive additive target-aware changes only in their consuming milestone: `/api/intake/requests` accepts IP intake data and promotes to Matter/IP/both; conflict-check routes add intake/IP targets while existing `/api/matters/{id}/conflict-checks` remains; shared task/hearing/next-hearing/deadline services accept Matter/IP context; existing notice, tracked-case/court, drafting, provider-operations/readiness/cost, portal, billing, and reporting routes expose IP links/filters without changing their canonical owner.

### 16.2 Source and research APIs

- Existing research responses must make `source_reference`, `source_state`, `publisher`, `retrieved_at`, and `open_url` non-optional at the UI contract level; unavailable source uses explicit state rather than omitted field.
- `GET /api/sources/{source_kind}/{record_id}/open` resolves an allowlisted existing canonical owner (`statute_section`, `legal_update`, `authority`, `registry_snapshot`, or approved future kind) and returns redirect/stream/typed failure according to access mode. It is a resolver, not a new source record.
- `POST /api/sources/{source_kind}/{record_id}/report` records wrong/broken source against that canonical owner.
- `GET /api/statutes/{id}/sections/{section}/versions` exposes verified versions and provenance.
- `POST /api/research/search` returns committed query ID, coverage, freshness, result explanations, and typed no-result/error state.
- `POST /api/research/reviews` creates a frozen source-grounded review job.

### 16.3 Assistant APIs

- `POST /api/assistant/sessions` requires mode and scope.
- `POST /api/assistant/sessions/{id}/messages` returns answer, abstention state, citations, proposed actions, model metadata, and permission snapshot hash.
- `POST /api/assistant/actions/{id}/preview` and `/confirm` separate suggestions from writes.
- Streaming must not reveal a citation or record before its permission check completes.
- Each message creates an `assistant_turn`; each model call still creates the existing `ModelRun`; saved legal recommendations and drafts still use the existing `Recommendation` and `Draft` aggregates with an IP target extension.
- Session deletion/retention never deletes source legal records, model-run cost/audit evidence, an approved draft, or an accepted action; it removes or tombstones only conversation content according to policy.

### 16.4 Common mutation rules

- All create/commit/confirm/replay endpoints accept an `Idempotency-Key` header after the idempotency foundation in M2 is available.
- Ordinary edits require `expected_updated_at`. Lifecycle mutations require expected state, `expected_lifecycle_version`, and `expected_updated_at`, and return RFC 7807 conflict on stale write.
- API never accepts tenant ID from request body as authorization.
- Delete of legal records is normally retire/tombstone; hard deletion follows retention/privacy policy and legal hold.
- Provider payloads and AI prompts are redacted in ordinary API responses.
- Generic PATCH schemas exclude lifecycle state, active flag, accepted source state, approval state, and final filing/service disposition.
- Sensitive command routes invoke the existing recent-step-up service with a stable purpose and return the repository's typed MFA problem response; clients do not implement their own password/PIN field.
- Four-eyes routes accept no arbitrary `approved_by` identity. The authenticated actor is derived from context and the service proves distinct underlying users and proposal/version ownership.

### 16.5 Lifecycle and workflow endpoints

- `POST /api/ip/docket-records/{id}/transitions` accepts `to_state`, `expected_from_state`, `expected_lifecycle_version`, `expected_updated_at`, reason, source/evidence refs, and idempotency key.
- Filing packages expose explicit `/submit-record`, `/acknowledge`, `/defect`, `/accept`, `/reject`, and `/supersede` transaction commands; these record evidence and do not call an external filing portal in this PRD.
- Proceedings expose stage-event commands rather than a free-form stage PATCH. The service validates transition template, represented side, prerequisite evidence, rule version, and permissions.
- Deadlines expose `/confirm`, `/override`, `/complete`, `/waive`, `/cancel`, and `/supersede`; each command has a distinct schema and audit action.
- Registry/source reconciliation exposes `/resolve` with accepted/rejected/deferred/split/linked outcomes, expected snapshot/diff version, and affected event preview.

### 16.6 List, search, and error contract

- New IP list APIs use opaque cursor pagination, default limit 50 and maximum 200, with stable sort `(selected_sort_key, id)`. Offset pagination is not introduced for high-volume portfolio/event tables.
- List response is `{items, next_cursor, total_estimate?, applied_filters, freshness?}`. Exact totals are optional when expensive; the UI labels estimates.
- Supported sort/filter fields are server allowlists. Unknown fields return validation problem details rather than becoming SQL fragments.
- Text query length, filter count, export size, and provider-triggering actions have explicit limits and rate limits.
- Errors use the repository's RFC 7807 `application/problem+json` shape with stable type slug, request ID, safe detail, and field errors where applicable.
- Every response propagates `X-Request-ID`; provider/job operations additionally return a stable operation ID for async status.

### 16.7 Idempotency contract

1. Client supplies an opaque key unique to one intended operation. Server scopes it to company, actor, HTTP method, normalized route/operation, and canonical request hash.
2. First request locks/creates `api_idempotency_records` in `processing`; a completed request stores status and stable result-resource/job reference, not confidential full payload by default.
3. Same key and same hash while processing returns typed `operation_in_progress`; after completion it returns/reconstructs the original result without repeating side effects.
4. Same key with a different request hash returns `409 idempotency_key_reused`.
5. Keys expire only after the legal retry window. Import commit, lifecycle transitions, filing transactions, payment reconciliation, notification scheduling, and provider replay use longer retention than ordinary drafts.
6. Database uniqueness, row locks, provider idempotency where offered, and domain event keys remain necessary; the HTTP record is not the only duplicate defense.
7. Multipart operations include ordered file content hashes, size/MIME and canonical metadata in the request hash. A changed byte, representation version or filing manifest cannot reuse the earlier key.

### 16.8 Transactional outbox and async contract

- A legal mutation and its `domain_outbox_events` rows commit in one database transaction. No provider call, search indexing, notification send, or long AI call occurs before commit.
- Worker claims rows with safe locking, records attempts/next attempt/error, and emits an idempotent effect keyed by domain event/version/consumer.
- Consumer success does not mutate immutable source event; it writes projection/result and marks that consumer effect complete.
- Poison events enter dead letter with operator replay/ignore/resolve workflow and retain last good projection.
- Async APIs return `202` plus operation URL/status. UI can poll using existing provider-operation patterns; websocket/SSE is optional and not required for correctness.

### 16.9 Notification convergence API contract

- Existing hearing schedule APIs continue during migration, but dispatch creates/links durable notification intents.
- Delivery-intent API exposes schedule/source event, recipient target, channel, attempt history, provider events, current state, fallback/escalation, and safe error.
- Only the delivery service owns external provider calls. Hearing, deadline, report, watch, and client workflows enqueue intents through the same service.
- Provider callbacks authenticate/signature-check, resolve by provider/message ID plus company/provider scope, store raw-event hash/redacted metadata, and apply monotonic/idempotent state rules.

### 16.10 Expected repository implementation surfaces

- SQLAlchemy models/enums: `apps/api/src/caseops_api/db/models.py`, following existing company-scoped composite-key and append-only audit patterns.
- Alembic slices: `apps/api/alembic/versions/`; one independently deployable concern per revision, with deterministic chain and tested upgrade from current production head.
- Schemas: new `apps/api/src/caseops_api/schemas/ip_*.py` modules for IP legal state. Shared task, hearing, next-hearing, deadline, intake, conflict, access, notice, portal, billing, drafting, tracked-case/provider-operation, and report schemas extend their existing modules; neutral import orchestration receives a shared schema while typed IP rows remain IP-specific. Do not fork shared owners into `ip_*` copies.
- Services: new `services/ip/` modules are limited to portfolio, lifecycle/events, legal deadline calculation, filings, versioned IP documents, registry, watch, clearance, and IP-specific report definitions. Shared owners remain in existing service packages and receive target-aware adapters.
- Connector extension: add IP source/link adapters to existing `services/calendar_sync.py`, `calendar_event_candidates.py`, `communications.py`, `notices.py`, integrations/readiness/provider-cost/operations, mailbox/Microsoft 365/Drive services and their models/routes. Do not add a second connector credential, raw-envelope, notice, health, support or cost service under `services/ip/`.
- Shared-work extension: refactor existing task/hearing/next-hearing/deadline/calendar, intake/conflict, matter access/ethical-wall, notices, portal, billing, drafting/recommendation/extraction, tracked-case/court, provider-operations, and report services behind target-aware or link adapters in their consuming milestones; old routes call the same interfaces throughout compatibility. Neutral bulk-import orchestration is a `REPLACE` foundation because existing Matter/Employee implementations are not generic.
- Governance/operations: extend existing security/step-up, production-readiness and audit services; add typed retention/hold/data-operation services and safe `apps/api/src/caseops_api/scripts/tenant_export.py` / `tenant_purge.py` entry points only after dry-run and test contracts exist.
- Routes: new `api/routes/ip_*.py` modules contain new legal-domain routes or thin adapters only; shared route modules remain the owner for shared behavior. Every mutation is covered by capability and target-access tests.
- Backend capability source: `services/capability_catalog.py`; frontend mirror: `apps/web/lib/capabilities.ts`; endpoint clients/types: `apps/web/lib/api/endpoints.ts` and generated/manual OpenAPI types according to current repository practice.
- UI: `apps/web/app/app/ip/` for the IP portfolio and legal workspaces, using the existing app shell, intake, calendar, portal, provider-operations, drafting, research, report/export, and access components/services rather than parallel administration screens.
- Jobs/scripts: `apps/api/src/caseops_api/scripts/` and approved workers; Cloud Run manifests/deploy controls in `infra/cloudrun/`.
- Tests: focused API test modules under `apps/api/tests/`, web tests beside existing web test structure, Postgres-specific constraints/migrations in the `postgres` marker suite, and dated Playwright specs/config for production proof.

An implementation PR that introduces a forbidden duplicate from Section 11.5(28), or a new shared subsystem under `services/ip/`, fails architecture review even if its local tests pass.

### 16.11 Audit and domain-event contract

The existing `AuditEvent` remains the user/security evidence log. Typed `ip_docket_events` remain legal/operational facts, while shared `domain_outbox_events` distribute committed changes. One must not be reconstructed from another when its required evidence differs.

Minimum audit fields are action schema version, result, company, actor user/membership snapshot or system identity, request/operation ID, target type/ID and optional docket link, capability/step-up/four-eyes context, safe reason/category, occurred/recorded time and allowlisted redacted metadata. Minimum domain event fields are event type/schema version, aggregate/docket ID, aggregate version, company, occurred/effective times, source command/event ID, producer and payload hash/body under its confidentiality schema.

Initial action families include `ip.record.*`, `ip.lifecycle.*`, `ip.event.*`, `ip.deadline.*`, `ip.hearing.*`, `ip.filing.*`, `ip.service.*`, `ip.document.*`, `ip.registry.*`, `ip.rule.*`, `ip.workflow.*`, `ip.access.*`, `ip.break_glass.*`, `ip.inbox.*`, `ip.incident.*`, `ip.export.*`, `ip.purge.*`, `ip.hold.*`, `ip.provider.*`, and `ip.ai.*`. Each implementation slice adds exact actions/payload versions and deny/failure events where security evidence requires them.

### 16.12 Data-operation and recovery API safety

- Export/purge/hold/restore endpoints are tenant-admin/platform operation planes, never generic IP CRUD. They require explicit operation type/scope, dry-run manifest version, expected policy/hold versions, step-up, dual approval where configured and idempotency.
- `execute` rejects an expired or changed manifest. The executor consumes stored operation items/checkpoints; it never reevaluates a broad tenant query silently after approval.
- Data-operation status is asynchronous and cancellation means stop before the next safe checkpoint. Completed deletes/exports are not rolled back by changing status.
- Restore/failover remains an operator runbook/CLI/IaC action; the API stores safe evidence/readiness state and cannot accept database URLs, secrets or destructive infrastructure commands from tenant users.

## 17. Jobs and operational architecture

| Job | Cadence/trigger | Responsibility |
|---|---|---|
| `caseops-source-link-health` | Daily and on reported failure | Validate public links/proxy metadata; update source health |
| `caseops-statute-source-sync` | Controlled release/manual, then scheduled by source | Fetch candidate legal text; never auto-publish unverified content |
| `caseops-research-golden-query` | After corpus/index/model release and daily sample | Verify search modes, expected results/state, source links, latency |
| `caseops-case-tracking-poll` | Existing approved daily window | Poll existing `TrackedCase` records and create/update canonical tracked-case updates/health/notifications; IP may reference but never copy them |
| `caseops-ip-registry-sync` | M5; provider/jurisdiction policy | Poll linked IP-office applications/proceedings, create IP snapshots/diffs, and publish health/cost/replay through existing connector/provider-operation surfaces |
| `caseops-ip-rule-fee-source-check` | Daily metadata check; controlled content release | Detect source/version changes for rule/form/fee data and create curator candidates |
| `caseops-ip-journal-watch` | Publication cadence | Ingest journal candidates and generate watch hits |
| `caseops-ip-madrid-sync` | WIPO/provider policy | Poll international registrations/designations and create separately attributed snapshots/diffs |
| `caseops-ip-deadline-evaluator` | Event-triggered plus daily safety scan | Calculate/recalculate deadline proposals and identify overdue items |
| `caseops-ip-obligation-monitor` | Daily | Identify renewal, annuity, working, recordal, licence, client-instruction, and associate-response obligations |
| Existing mailbox/Microsoft 365/Drive ingestion plus `caseops-ip-inbox-reconcile` | Webhook/poll plus daily safety scan | Reuse existing raw envelope/candidate services; create IP triage links idempotently; detect untriaged, duplicate, webhook-gap, retention and poison items |
| Existing calendar-sync service plus IP source types | Event-driven plus existing reconciliation cadence | Project permitted CaseOps obligations through `CalendarEventSync` and detect drift without accepting legal-state edits |
| `caseops-ip-state-integrity` | Daily and after migration/restore | Reconcile materialized lifecycle/responsibility/deadline state with immutable events/workflow versions and quarantine mismatches |
| `caseops-private-projection-integrity` | M6; event-driven plus daily safety scan | Apply revocation/tombstone/reindex effects and detect stale/orphan/cross-policy search, cache and saved-output projections |
| `caseops-retention-hold-integrity` | Nightly | Detect expired-unpurged, purged-still-present, held-at-risk, orphan, missing data-map and provider-deletion exceptions |
| `caseops-access-review` | M7; policy schedule and membership/client/portal change | Open shared Matter/Client/IP/portal review campaigns, expire/escalate uncertified grants and prove retrieval/notification revocation |
| `caseops-reminders-job` | Five-minute cadence | Dispatch idempotent due deliveries and process retry policy |
| `caseops-provider-reconciliation` | Daily | Find stale/orphan operations, webhook gaps, and poison records |
| `caseops-report-delivery` | M3 only after measured async need; scheduled/on demand | Execute neutral `report_jobs`, render approved domain definitions including IP, and enqueue tracked delivery through the shared notification service |

Jobs run as externally scheduled Cloud Run Jobs or the repository's approved durable workflow system. Do not add an in-process scheduler. Deployment must grant job-level invocation to a dedicated scheduler identity and then run a canary.

## 18. External integrations and sourcing policy

### 18.0 Source hierarchy and activation boundary

The source catalogue must identify what each artifact can prove. Current enacted legislation/rules and official gazette, registry, court, tribunal, or authority instruments are primary evidence for their respective facts. Official forms, fee schedules, journals, cause lists, orders, judgments, register entries, public notices, manuals, FAQs, and help pages are separate artifact types and cannot be substituted merely because they share a government domain. Judicial authority and legal interpretation require lawyer review and treatment analysis; source ranking is not automatic legal reasoning.

The IP India manual page currently exposes a 2026 draft practice manual. It may inform product discovery but remains labelled `draft/non-binding` unless and until the issuing authority publishes a final instrument. No draft manual, vendor page, AI answer, or historical manual may activate a deadline, form, fee, or lifecycle transition without the controlling source and legal approval.

### 18.1 IP India

- Prefer official published sources or a contractually permitted provider/API.
- Store the actual source and provider used, not a generic `IP India integrated` claim.
- If a stable permitted automated interface is unavailable, support manual verified import and clearly show that sync is manual.
- Hearing cause lists and Trade Marks Rules inform the initial opposition model, but legal SME validation is mandatory before activating deadline rules.

### 18.2 Indian Kanoon

- Use the documented API under commercial terms and required attribution.
- Track search/document/metadata usage and cost.
- Respect caching, retention, redistribution, and attribution obligations.
- Preserve Indian Kanoon document identity and canonical public URL where available.

### 18.3 eCourts and commercial case providers

- Official eCourts web services and any commercial provider are distinct sources.
- A commercial provider must be named in configuration, audit, and support documentation.
- Captcha/session-gated government pages are not scraped through bypass techniques.
- CaseOps source proxy retrieves protected provider documents with server-side credentials and a strict host/path allowlist.

### 18.4 Competitor benchmark

Iolite and MikeLegal define buyer expectations around docketing, alerts, renewals, registry updates, search, watch, reports, and client collaboration. Vendor claims are benchmarks, not evidence of independently verified quality. CaseOps acceptance is based on user journeys and measurable outcomes in this PRD, not copied marketing claims.

### 18.5 WIPO and international classifications

- Madrid data/workflows must use WIPO or a contractually permitted provider and preserve WIPO identity separately from each designated office.
- Nice, Vienna, and Locarno classifications are versioned reference data with edition/version, language, source, and effective range.
- Classification suggestions require lawyer/user confirmation and do not replace filed goods/services or representation records.

### 18.6 Other Indian IP authorities

- Plant-variety workflows use the PPV&FR Authority's official forms, journals, registry guidance, and decisions or a contractually permitted provider.
- Copyright, GI, design, patent, and semiconductor-layout workflows identify their actual authority/source and do not inherit Trade Marks Registry capability claims.
- Customs/platform enforcement integrations require separate terms, evidence handling, retention, and incident-response review before activation.

## 19. UX requirements

- Operational screens use dense, scan-friendly tables, timelines, calendars, split review panels, and predictable actions.
- Do not use marketing hero layouts or decorative card grids inside the authenticated product.
- Status, freshness, source, risk, and responsible owner remain visible without opening hidden menus.
- Use icons for familiar actions and tooltips for unfamiliar source/sync/diff controls.
- Bulk actions show selected count, scope, permission, preview, and irreversible consequences.
- Empty states offer the next valid action, not feature descriptions.
- Error states retain user input and identify whether correction belongs to data, permission, provider, configuration, or platform operations.
- Mobile supports urgent review, acknowledgement, source opening, reminders, and task completion. Portfolio configuration and high-volume reconciliation may explicitly require desktop.
- Accessibility target is WCAG 2.2 AA for keyboard, focus, contrast, labels, tables, dialogs, and live status.
- All layouts must pass narrow/mobile and desktop screenshot checks with no overlapping text/actions.

## 20. Security, privacy, and governance

- Enforce tenant, client, record, document, and field-level sharing boundaries in database queries and retrieval pipelines.
- Encrypt data in transit and at rest; credentials are Secret Manager references, never tenant-visible values.
- Apply SSRF protection, host/path allowlists, size/type limits, malware scanning, and content disposition to source/document downloads.
- Audit login-sensitive operations, source access, exports, AI retrieval, generated drafts, approvals, registry resolutions, deadline changes, and replay.
- Keep privilege/confidentiality labels in AI chunks and citations; excluded content must not be embedded into a broader-access index.
- Define retention for provider payloads, source caches, chat sessions, prompts, model responses, exports, notification bodies, and webhooks.
- Support legal hold and tenant offboarding without destroying required audit evidence.
- AI providers receive only the minimum permitted context; provider and region policy are tenant-governed where supported.
- Perform threat modeling for cross-tenant retrieval, prompt injection in uploaded/legal-source documents, source-proxy SSRF, malicious spreadsheets, webhook forgery, and replay abuse.
- Prompts treat retrieved text as evidence, never executable instructions.

## 21. Performance, availability, and observability

### 21.1 Product targets

- Portfolio/research list API p95 under 2 seconds for ordinary filtered pages, excluding external-provider fetch.
- Cached source metadata opens under 1 second p95; protected document streaming begins under 5 seconds p95 when provider is healthy.
- Research search p95 under 5 seconds for standard query; long intelligent review is an asynchronous job with progress.
- Event-to-deadline proposal under 10 seconds for synchronous deterministic rules.
- Due reminder submission begins within 5 minutes of scheduled time under healthy provider conditions.
- Registry/case freshness meets configured provider cadence, normally within 24 hours for daily sources.
- Permission/hold/purge revocation blocks access at result hydration immediately after the authoritative transaction; derived private search/cache removal completes within 5 minutes p95 and 30 minutes maximum or raises a P1 integrity alert while hydration remains fail closed.
- Recovery targets follow `RES-01`; user-visible RTO is measured only when authenticated legal workflows and worker fencing pass, not when infrastructure merely reports ready.

### 21.2 Required telemetry

- Structured operation ID across scheduler, job, provider call, normalization, mutation, notification, and source access.
- Metrics by tenant/provider without high-cardinality confidential labels.
- Scheduler invocation success, job success, age of last success, queue age, stale records, rate limit, auth failures, parse failures, poison records, and replay outcomes.
- Notification due/submitted/delivered/suppressed/bounced/failed/fallback counts and latency.
- Research query mode, typed outcome, latency, index freshness, result count, source-open success, and relevance feedback.
- Deadline proposed/confirmed/overridden/overdue/completed and time-to-confirm.
- Access grants/reviews/break-glass duration, revocation-to-hydration block, projection removal lag, stale/orphan generations and denied-result hydration counts.
- Retention/hold/export/purge operation age, data-class coverage, subsystem checkpoints/exceptions, still-searchable verification and provider-deletion lag.
- Backup/PITR/object-version recency, restore drill age, observed RPO/RTO, exact schema/image evidence and pending-worker duplicate-risk checks.
- Audit dashboards must avoid exposing legal content to platform operators.

### 21.3 SLI, SLO, and alert semantics

- **Scheduled workflow availability:** percentage of expected job windows that produce a successful run or successful bounded recovery before the freshness deadline. Measure by job and provider over 90 days; target 99%. An enabled scheduler with no execution is a failed window.
- **Critical reminder submission:** percentage of due, valid, policy-enabled internal critical intents submitted to a provider or delivered in-app within five minutes. Target 99.5% over 30 days.
- **External delivery:** delivered/acknowledged outcomes are reported separately from submission. Provider suppression, invalid destination, and recipient unsubscribe remain failures requiring tenant action, not platform availability successes.
- **Legal correctness gates:** cross-tenant exposure, wrong active lifecycle, unsupported authoritative statute text, and incorrect approved deadline fixture have zero error budget and block release.
- **Freshness:** percentage of linked records within their configured source cadence plus grace. Provider outage is shown separately but still counts against user-visible freshness.
- **Private projection revocation:** 100% of tested revoked records are blocked at hydration immediately and removed from active private index/cache within the stated maximum; any unauthorized retrieval has zero error budget.
- **Recovery readiness:** backup/object/PITR evidence remains within policy age and the latest full-stack drill meets approved RPO/RTO. Expired or incomplete drill evidence makes recovery readiness red, not `unknown/healthy`.
- Alerts identify owner, severity, affected tenants/records, freshness/delivery risk, runbook, and correlation ID. Alert closure requires recovered state or an explicit accepted degradation with expiry.

## 22. Analytics and product success metrics

| Metric | Definition | Pilot target |
|---|---|---|
| Portfolio completeness | Required/expected fields complete by record phase | >= 95% pilot records after migration remediation |
| Registry freshness | Linked records within configured freshness objective | >= 99% when provider healthy |
| Deadline confirmation | Critical proposals confirmed before internal target | >= 98% |
| Reminder observability | Critical intents with explicit terminal/retry state | 100% |
| Reminder effective delivery | Delivered or acknowledged fallback before event | >= 99%, excluding invalid destinations documented to tenant |
| Source coverage | Displayed legal results with usable source action/state | 100% |
| Source-open success | Valid source actions that open/stream successfully | >= 99% rolling seven days |
| Research diagnostic correctness | Golden queries reach expected result/error class | >= 95%, no false `no results` for infrastructure failure |
| Import recoverability | Failed rows retained with actionable reason | 100% |
| Opposition docket completeness | Required identifiers/stages/deadlines/doc evidence complete | >= 95% pilot proceedings |
| Guide task success | Pilot advisory users complete selected tasks without admin help | >= 80% first round, >= 90% before GA |
| AI citation validity | Sampled factual claims supported by accessible cited evidence | 100% for release gate sample |

Metrics are product-health signals, not employee performance or legal-outcome scoring.

## 23. Migration and data-quality plan

1. Inventory current trademark-like Matters, intake records, documents, hearings, identifiers, clients, and custom fields.
2. Define deterministic candidate mapping to IP assets/applications/proceedings without mutating source records.
3. Generate migration preview with candidate type, confidence, missing fields, duplicate groups, and proposed links.
4. Obtain tenant approval per batch; commit idempotently; preserve source Matter and add linkage.
5. Import law-firm portfolio files through the controlled import workflow.
6. Backfill typed identifiers from known fields/documents only when evidence is retained; inferred identifiers remain candidates.
7. Quarantine corrupt statute/source records and publish a coverage report before enabling new source claims.
8. Re-index verified statutes, authorities, canonical judges, and permitted IP records; run isolation and golden-query tests.
9. Reconcile notification suppressions and require tenant destination verification before critical external reminders.
10. Provide post-migration exception queues and signed acceptance report; do not declare migration complete from row counts alone.

### 23.1 Schema migration sequence

This is the required production migration/activation order, not a prohibition on parallel code, test, fixture, or documentation development against stable expand-phase contracts.

1. **M2-A, ownership/capability/anchors:** approve the Section 11.2 owner/ADR ledger; add IP capability/entitlement gates, `ip_docket_records`, type-specific parent skeletons, company composite uniqueness/FKs, and lifecycle constraints. No overlapping feature table enters this slice.
2. **M2-B, legal evidence and control:** add identifiers, parties/roles, relationships, IP docket events, legal deadline calculations, responsibility assignments, IP rule/fee/workflow versions, source links/conflicts, transition commands, audit/domain-event catalogues, state-integrity checks and shared working-calendar versions.
3. **M2-C, shared reliability:** add `api_idempotency_records`, `domain_outbox_events`, `domain_consumer_effects`, correlation, lease/fencing/retry contracts and mixed-revision proof; adopt them behind existing operator patterns without adding another dashboard.
4. **M2-D, document identity:** add IP document identity/immutable versions/links and bridge to existing Matter attachments, storage, scanning, extraction, chunks, and processing jobs without copying bytes or creating a second worker queue.
5. **M2-E1, shared docket work:** independently expand/backfill/switch existing task, operational-deadline, hearing, next-hearing provenance, calendar and notification target/source owners to IP. Legal deadline/projection correlation is unique; dual-read comparison is temporary and one writer is release-blocking.
6. **M2-E2, restricted-record access:** independently expand/backfill/switch existing internal access/ethical-wall owners to IP targets; add record-policy decision reuse across portfolio/document/source/audit surfaces, step-up/four-eyes purposes and cross-company/restricted-list tests. Portal, access-review and emergency-access persistence are not in this slice.
7. **M2-F, data/recovery minimum:** register every new IP data class; add retention versions, legal holds and dry-run/manifest support needed to prove an authorized tenant export; prove current database-plus-object application cutover, tombstone-aware reindex and worker fencing. Automated purge/offboarding and emergency-access review remain M7 work.
8. **M3-A, intake/import:** expand existing intake/conflict promotion to IP and add neutral `bulk_import_jobs` plus `ip_import_rows`, shared import APIs/UI adapters, preview/commit/reconciliation and legacy Matter/Employee job aggregation without dual-writing status.
9. **M3-B, notices/communications:** add `company_notice_ip_links`, IP-aware notice authorization, Communication/document evidence links, inbox triage projection, legal-deadline delegation and one accepted-notice workflow in `/app/notices`.
10. **M3-C, filing/service/cost/billing:** add filing packages/transactions, formal service records, `ip_cost_items`, evidence/billing links and one-accounting-owner reconciliation; reuse Matter billing/time/invoice/spend owners.
11. **M3-D, reports:** add synchronous IP report definitions first; create neutral `report_jobs`/`report_artifacts` only after representative-volume evidence requires background/scheduled execution.
12. **M4-A, drafting:** generalize Draft/ModelRun/DraftingDataExtractionField targets and existing template/format-validation paths for IP pleadings when M4 starts; Recommendation remains M6 work.
13. **M5-A, registry/provider/portal:** add IP registry links/snapshots/diffs and sync-attempt records; register readiness/support/cost/operation/replay adapters in existing control planes; extend existing portal grants/publications to IP targets.
14. **M6-A, assistant/private retrieval:** add assistant sessions/turns/citations, generalize Recommendation to IP targets, and add private projection generations/tombstones only with M6 permission-scoped Q&A/review.
15. **M7-A, assurance automation:** add access-review campaigns, emergency-access sessions and automated export/purge/offboarding execution with the GA drills and support owners that consume them.

Do not collapse these changes into one large Alembic revision. Multiple ordered revisions may share one integration branch, PR, and coordinated release. Each revision must upgrade from the previous production head, be idempotent under deployment safeguards, and include downgrade or a documented restore/roll-forward procedure where destructive downgrade is unsafe. Production deployment uses expand, backfill, verify, switch, and contract phases; application code does not require a new column before the expand migration is live.

### 23.2 Backfill and compatibility rules

- Backfills are resumable, bounded, company-scoped, dry-run capable, and record checkpoint/count/error evidence. They do not call external providers unless separately approved.
- Existing Matter, attachment, hearing, deadline, reminder, tracked-case, statute, authority, judge, portal, and audit records remain readable during rollout.
- Existing task, hearing, deadline, intake, conflict, internal-access, ethical-wall, and portal rows are backfilled with company ownership before any Matter FK becomes nullable. New target-aware services write one canonical row; legacy Matter routes call the same service until their compatibility contract can be retired.
- Existing Microsoft 365, calendar connection/candidate/sync, inbound email alias/event, Drive candidate and Communication records remain canonical connector evidence. Backfill creates company-verified IP projection links only; it does not copy message bodies, OAuth/secret references, provider IDs or calendar events into a second subsystem.
- Existing `CompanyNotice` rows and `/app/notices` remain canonical. Backfill creates company-matched IP links and, where evidence proves identity, Communication/document links; it does not copy notice metadata/files or create a second reply queue. Restricted IP linkage is activated only after notice list/get/download/report authorization passes fail-closed tests.
- Matter/IP links are additive. Migrating a Matter attachment creates IP document metadata/version referencing the same immutable storage key only after company and hash verification; it does not copy bytes or delete the Matter attachment.
- During notification convergence, exactly one dispatcher owns a scheduled delivery. Dual-read comparison is allowed; dual-send is not.
- IP legal deadlines backfill a unique shared operational projection. Reconciliation verifies date/status/assignee/source linkage; the compatibility deadline route cannot change an IP legal state except by delegating to its command.
- Existing Matter/Employee bulk-import, drafting/recommendation/model-run, tracked-case/court-sync, provider-operations, billing/payment/spend, and report/export history stays canonical. Neutral import aggregation and new IP links/staging/definitions never clone or dual-write history; a later physical import convergence requires a separate `REPLACE` rehearsal.
- Membership/portal/connectors with existing cascade behavior are audited before immutable IP evidence references them. New evidence uses nullable actor/recipient refs plus snapshots where deactivation/history requires preservation; schema changes cannot make membership deletion erase legal or delivery history.
- Retention/hold/search backfills run in shadow report-only mode first. Activation compares data-map coverage and projection counts; no expiry/purge is executed merely because a new default policy was added.
- Restore/reindex applies purge tombstones and current access/source policy before activating derived projections or workers.
- Contract/cleanup migration runs only after pilot evidence proves no old revision/job depends on the compatibility column/path and rollback window has closed.

## 24. Concrete milestones and dates

Dates below are planning forecasts for kickoff on 3 August 2026, not required waits or implementation gates. They assume one dedicated five-engineer squad (one backend/technical lead, one backend/data engineer, two full-stack engineers, and one QA/SDET with platform support), one full-time IP-lawyer product owner, part-time product design/security/SRE, and timely provider/legal decisions. They include integration, migration, UAT, production proof, and remediation capacity, not only feature coding. The continuous campaign follows dependency readiness; missed external dependencies rebaseline affected activation and claims rather than reducing verification or stopping independent work.

| Milestone | Target | Deliverable | Exit criteria |
|---|---|---|---|
| M0: Program lock | 14 Aug 2026 | Approved scope, pilot firms, source policy, initial taxonomy/rule inputs, staffed baseline, and signed `NEW/EXTEND/LINK/REPLACE` ownership ledger for every M1-M3 component | Named product/engineering/data/security/legal owners; duplicate-subsystem ADR audit accepted; required pilot data named; unresolved provider choices explicitly gated rather than assumed |
| M1: Trust Recovery GA | 4 Sep 2026 | Source links, Bare Acts quarantine/provenance, search diagnostics, notification convergence start/observability, scheduler IAM/health/replay | Exact deployed scheduler/job revision and IAM/config drift checks pass; bounded canaries prove every required job can be invoked by its configured scheduler identity; source-link E2E; UJ-48; no unverified statute presented; suppressed critical reminder produces visible fallback. Natural-run health remains monitored operational evidence but is not a release-duration blocker. |
| M2: IP Foundation complete | 29 Jan 2027 | Company-scoped IP anchors/legal evidence, rules/workflows/calendars, versioned documents, outbox/idempotency, restricted-record access, and independently migrated shared task/hearing/next-hearing/deadline/calendar/notification owners; registered data classes, holds/export dry run and current recovery proof | Ownership ledger implemented with no forbidden duplicate; one-writer reconciliation per shared owner; mixed-revision upgrade/rollback rehearsal; Postgres composite-FK/uniqueness tests; UJ-46/UJ-47/UJ-65/UJ-67/UJ-68; current full-stack restore and tenant-export dry run; cross-company/restricted-record isolation; SME-approved rules/workflows/taxonomy; OpenAPI/UI capability parity. Portal, drafting, assistant, registry sync, report jobs, access review/emergency access and automated purge are explicitly not M2 exit claims |
| M3: Trademark Operations MVP | 30 Jun 2027 | Complete filing particulars, IP portfolio, prosecution/renewal, legal deadlines and filing evidence integrated into existing intake/conflict, task/hearing/calendar, CompanyNotice/inbox/Communication, notification and Matter billing owners; neutral import orchestration and volume-appropriate reporting | UJ-02 through UJ-10, UJ-14, UJ-26, UJ-31, UJ-32, UJ-49 through UJ-59, UJ-61, and UJ-62 pass pilot UAT; accepted legal notices exist once in `/app/notices`; imports have one job-state owner; costs have one amount/accounting owner; no duplicate shared row/control plane; critical deadlines have accepted coverage; restored-worker no-dual-send drill; allowlisted production smoke; no direct external send outside durable delivery service |
| M4: Opposition and Pleadings | 29 Oct 2027 | Applicant/opponent workflows, partial/multi-class scope, service/evidence/translation, hearing/order/appeal, rectification foundation, reviewed templates | UJ-12, UJ-13, UJ-24, UJ-33, UJ-34, and UJ-38 pass with anonymized matters; lawyer signs rule/workflow fixtures/templates; terminal lifecycle and recalculation regressions pass |
| M5: Registry, Madrid, Watch, and Client Ops | 29 Mar 2028 | Approved registry/WIPO boundary, IP snapshots/diffs, journal/watch, Madrid/post-registration, source proxy, foreign associates, client reports/instructions and extension of existing portal grants/publications | Existing connector readiness/support/cost/provider-operations surfaces show every IP adapter; no court update is copied from `TrackedCase`; provider contracts/terms/support matrix, replay/cost/circuit breakers; UJ-07, UJ-19, UJ-21, UJ-27, UJ-35 through UJ-37 pass; 30-day provider/freshness evidence or explicit pilot exception |
| M6: IP AI and Research GA | 30 Jun 2028 | Guide, workspace Q&A, intelligent review, canonical judge projection, private retrieval controls, source-grounded drafting improvements | Citation/abstention/prompt-injection/security eval gates; permission/revocation red team; UJ-15 through UJ-18, UJ-20/UJ-22/UJ-23/UJ-66 pass; no inaccessible citation in release sample |
| M7: Trademark General Availability | 29 Sep 2028 | Access-review/emergency-access controls, automated export/purge/offboarding, migration toolkit, hardening, performance, accessibility, current DR/security/incident proof, support/runbooks, billing/packaging and GA rollout | UJ-28/UJ-58/UJ-63/UJ-64/UJ-65/UJ-67/UJ-68; access expiry/review, regional/failover and purge/tombstone drills; 30-day SLO evidence; zero P0/P1; signed pilot acceptance; support/finance readiness |
| M8: Patent Docket Beta | 30 Jun 2029 | Child-PRD-approved families, PCT/national phase, office actions/oppositions, claim/document versions, annuities/working, title/licensing and patent deadlines | UJ-29, UJ-39, UJ-40, UJ-60, UJ-61, patent legal fixtures and SME UAT pass; no trademark-rule/status leakage; beta label derives from capability evidence |
| M9: Designs, Copyright, Licensing Beta | 31 Jan 2030 | Child-PRD-approved type-specific assets, registrations, renewals, enforcement, ownership/licensing obligations | UJ-30, UJ-41 through UJ-43, UJ-60, UJ-61 and type-specific fixtures/UAT; contract/registry deadline and confidentiality separation proven |
| M10: Full IP Platform GA | 31 Jul 2032 | Independently staffed and child-PRD-approved trademark, patent, design, copyright, GI, plant variety, layout design, trade secret, domain/customs enforcement, and licensing operations | UJ-44/UJ-45/UJ-60/UJ-61 plus every domain's specialist journeys/fixtures; cross-module security/performance/DR audit; migration, documentation, capability labels, pricing and support readiness |

### 24.1 Capacity and acceleration rule

- The committed dates assume one squad. Do not present the earlier draft dates as targets.
- To accelerate M2-M7, fund a second independent five-person squad plus a data/integration engineer, security/SRE capacity and a second trademark legal SME by 4 September 2026. Architecture, migrations, access/data governance, legal rules, provider contracts and release gates remain shared and cannot be skipped.
- M8-M10 customer activation and beta/GA acceptance cannot be responsibly accelerated by adding only generalist engineers. Repository implementation may proceed in parallel behind unavailable/intake-only flags, while each simultaneously activated domain still needs its own specialist legal/product owner and stable domain pod. Funding independent domain pods is the credible path to an earlier Full IP GA claim.
- Maintain a dependency-aware schedule as a generated planning view while execution advances; publishing that view is not an implementation approval gate. Parallel squads do not edit the same lifecycle/schema owner without an integration owner.
- Scope added after M0 must replace equivalent capacity, move a milestone, or be assigned to a separately staffed future slice. `Complete IP` is not an exception to capacity planning.

### 24.2 Milestone dependency and activation gates

These are direct dependency and activation conditions, not milestone-wide implementation stop lines. Build and test every independent node behind fail-closed defaults while a decision or dataset is pending; block only the affected authoritative behavior, production migration or data-operation execution against non-anonymized data, external integration, public claim, or milestone exit.

- M1 trust repair starts immediately and runs in parallel with independent IP implementation.
- M2 activation requires the law firm's actual document-name list, an IP lawyer's initial rule/workflow/calendar inventory, data-retention/hold policy, security decisions, current backup/object/export evidence, and the signed Section 11.2 ownership/retirement ledger. An unresolved shared-owner decision blocks changes to that owner, not other M2 nodes.
- M3 authoritative clearance/filing/fee behavior requires approved data and representative portfolio files. Portfolio, workflow, and UI code may be completed with versioned synthetic fixtures and remain disabled/manual until approval.
- M4 authoritative opposition/rectification automation requires approved Indian trademark rule/workflow maps and anonymized sample files; independent proceeding/document/workspace implementation may proceed.
- M5 live providers require a provider/licensing decision and credentials/sandbox. Adapter contracts, replay, readiness, manual flows, and disabled UI states proceed without them.
- M6 authoritative research/AI activation requires verified source coverage and an approved evaluation/security dataset. Permission, citation, abstention, and provider-failure implementation proceeds with deterministic fixtures.
- M7 production activation requires pilot teams, production-quality migration data, and approved export/purge/offboarding policy; drills and dry-run tooling proceed on anonymized data.
- M8-M10 require a separate type-specific legal rule/form/source pack before authoritative automation or beta/GA activation. Child PRDs, typed schema, APIs, UI, tests, and intake-only behavior may be implemented earlier and stay default-off.

### 24.3 One-go continuous execution policy

- Execute M0-M10 as one work-conserving dependency DAG. Milestone numbers organize scope and final attestation; they do not require idle time or prohibit later-milestone work whose direct prerequisites are satisfied.
- Prefer one program integration branch, one reviewable integration PR, and one compatible release train. Slices remain traceability, ownership, test, migration, and rollback units—not mandatory pause or deployment units.
- Use focused change-aware checks per commit and run the complete applicable sharded CI/security/migration/E2E matrix on each exact integrated candidate. Any code, dependency, runtime configuration, migration, fixture, test, or generated-artifact change creates a new exact candidate and reruns its applicable gates; evidence/prose-only changes use change-aware validators, and administrative handoffs alone do not trigger the full matrix.
- Implement externally blocked behavior completely behind truthful unavailable/manual states, fail-closed flags, readiness checks, observability, and kill switches. Missing human acceptance blocks activation and final `COMPLETE`, never unrelated repository implementation.
- Repository protections and automated checks are the routine gates. Ask for human action only when authority cannot be delegated: a real legal/financial/external communication act, unavailable credentials/paid capacity, legally required human acceptance, or an exact irreversible production operation not already approved.
- One consolidated approval event for an unexpired immutable destructive-operation manifest must contain every policy-required owner, dual-control, or four-eyes identity and remains valid through an immediate unchanged hold/evidence refresh only while that manifest is unexpired. Expiry or any target, exclusion, recovery, or risk drift invalidates it.

## 25. Implementation backlog by milestone

`IPLF-xxx` entries are epics. Split them into traceable suffix slices (`A`, `B`, and so on) with coherent behavior, ownership, migration, tests, and rollback. Compatible slices may share the program integration PR and release train; use coherent commits and generated traceability instead of forcing a separate PR/deploy per slice.

### 25.1 Trust-work dependency chain

Start the following trust work in order where one item directly depends on the prior item. In parallel, execute every independent backlog node permitted by Sections 24.2 and 24.3.

1. `IPLF-001A`: Read-only production/IaC drift audit for all required schedulers, jobs, service accounts, targets, image digests, timezones, and last successes. Produce evidence and exact remediation plan.
2. `IPLF-001B`: Reconcile scheduler identities/job-level Invoker bindings through the existing deployment helper, add drift/canary verification, deploy exact revision, and prove successful scheduled/manual execution. IPLF-001B itself performs no IP schema work; this does not block schema work in independent nodes.
3. `IPLF-003A`: Define/serialize source-state/open contract and source proxy safety tests.
4. `IPLF-003B`: Render source action on research, uploaded-case, intelligent-review, and judge surfaces with typed failure states and E2E.
5. `IPLF-006A`: Audit/quarantine corrupt statute records and correct coverage claims without fetching/publishing replacement legal text.
6. `IPLF-006B`: Add verification/provenance/version contract and curator workflow; replacement source ingestion is a separately approved data operation.
7. `IPLF-007A`: Model notification schedule-to-intent linkage, recipient/provider events, and status mapping with no dispatcher switch.
8. `IPLF-007B`: Move external dispatch behind durable intent service, run dual-read/no-dual-send comparison, expose suppression/fallback, then cut over with rollback flag.
9. `IPLF-005A`: Add typed search outcomes/telemetry and golden-query fixtures; then repair any observed index/query defects as separate slices.
10. Begin M2-A and other independent schema/access anchors as soon as their direct ownership, data, and security inputs exist. M1 technical failures block affected deployment/claims; continuing natural-run scheduler monitoring never idles independent implementation.

### 25.2 Incremental readiness checklist

Apply this checklist before changing the affected layer or activating the behavior. It is not a requirement to complete a separate document or pause the entire program before coding begins.

- Requirement IDs, journey step/exception, actor/capability, and milestone exit criterion are named.
- Current `main`, production revision/state, and affected existing models/services are established at run start and re-audited when relevant state changes.
- Every persistence/service/API/UI/job change is classified against Section 11.2 as `NEW`, `EXTEND`, `LINK`, or `REPLACE`; the canonical writer, shared owner, compatibility path, reconciliation, and dated retirement gate are named. A new overlapping component has an approved ADR.
- Legal rule/source/provider/client policy decisions required for activation are closed and linked; unresolved decisions narrow/disable runtime scope without blocking repository implementation.
- API/schema/migration/compatibility, security/tenant, observability, rollback, data operation, test, and production proof are defined before the affected layer is finalized; unchanged layers need no ceremonial record.
- Representative fixtures exist and contain no uncontrolled client secrets.
- Dependencies are present in the same integration candidate, already merged/deployed, or explicitly mocked at a stable contract boundary.

### 25.3 Pull-request evidence contract

The program integration PR includes a generated, per-slice evidence index covering requirement/journey mapping; behavior and non-goals; `NEW/EXTEND/LINK/REPLACE` ownership; overlap/duplicate checks; schema/API changes; canonical writer/compatibility retirement; capability/entitlement impact; migration/backfill/reconciliation/rollback; threat/tenant review; tests; changed-surface screenshots; provider/legal fixture state; and post-deploy acceptance. Do not repeat unchanged boilerplate in every commit. A green source-tree test without exact deployed-revision proof does not close a production defect.

### M1 tasks

- `IPLF-001`: Repair and codify scheduler IAM/deployment canary.
- `IPLF-002`: Add integration health/freshness and bounded replay.
- `IPLF-003`: Render source actions in research, uploaded-case analysis, judge profiles, and intelligent review.
- `IPLF-004`: Implement safe source proxy/link health/reporting.
- `IPLF-005`: Add typed research outcomes and golden-query runner.
- `IPLF-006`: Quarantine/verify statute data and correct coverage labels.
- `IPLF-007`: Add notification recipient/channel outcome model, suppression recovery, fallback, and alerts.
- `IPLF-008`: Add production smoke suite and release evidence template.

### M2 tasks

- `IPLF-019`: Publish the repository-backed ownership ledger and ADRs; prove no proposed M2/M3 table/service/page/job duplicates the Section 11.2 owners.
- `IPLF-020`: Add IP capability model and feature flags through the existing backend/frontend capability catalogues.
- `IPLF-021`: Add core IP asset/application/proceeding/identifier schema.
- `IPLF-022`: Add append-only docket event and lifecycle services.
- `IPLF-023`: Add versioned IP deadline-rule/calculation/responsibility evidence, shared working calendars and one-way correlation to the existing shared operational deadline/calendar service.
- `IPLF-024`: Add IP document links, taxonomy, naming preview, and aliases.
- `IPLF-025`: Expand/backfill/switch existing task, hearing, next-hearing provenance, operational deadline, calendar and notification owners to IP targets in separate migrations; old Matter routes remain adapters and one-writer reconciliation is release-blocking.
- `IPLF-026`: Expand/backfill/switch existing internal access and ethical-wall owners to IP targets; prove one fail-closed policy across list/count/document/source/audit. Do not add portal, access-review or emergency-access persistence in this epic.
- `IPLF-027`: Add shared idempotency/outbox/consumer-effect foundations, lifecycle workflow versions/transition commands, OpenAPI, audit/domain-event catalogues, mixed-revision fencing and migration rollback proof.
- `IPLF-028`: Add the data-map/retention/legal-hold/data-operation dry-run minimum, register every IP data class, reconcile current backup/object evidence, and prove database-plus-object application-cutover restore and tenant-export dry run.
- `IPLF-029`: Run the M2 duplicate-ownership audit and close every M2 row with a canonical-writer test, compatibility retirement gate and production evidence; later milestone owners must remain unmodified unless required by a proven M2 dependency.

### M3 tasks

- `IPLF-030`: Portfolio listing, filters, saved views, columns, and export.
- `IPLF-031`: Manual application/asset create and duplicate resolution.
- `IPLF-032`: Introduce neutral `bulk_import_jobs`, typed `ip_import_rows`, validation/preview/commit/history/error report and read-only adapters over legacy Matter/Employee jobs; do not alias or dual-write their job state.
- `IPLF-033`: Application workspace and prosecution timeline.
- `IPLF-034`: On the M2 target-aware owners, ship legal deadline calculation/confirmation/override/completion UX plus task, Today and calendar behavior; do not add another schema owner.
- `IPLF-035`: On the M2 shared hearing/next-hearing/calendar/reminder owner, ship IP create/reschedule/provenance UX and notification-intent preview/status; no IP hearing table, suggestion history or dispatcher.
- `IPLF-036`: Document register/classification/version/approval.
- `IPLF-037`: Renewal terms/instruction/filing/acceptance.
- `IPLF-038`: Portfolio/deadline/renewal/data-quality report definitions using existing synchronous export patterns; introduce the neutral `report_jobs`/`report_artifacts` contract only for measured large/background needs, with no IP-only scheduler or storage policy.
- `IPLF-039`: Trademark operations integration: extend existing intake/conflict/promotion, daily task/hearing/docket, CompanyNotice/Communication, billing and report owners; add IP-specific instructions, clearance, filing/service, cost evidence links and controlled lifecycle. Portal is M5. Track independently reviewable concerns with suffix IDs and coherent commits inside the continuous integration campaign.
- `IPLF-039A`: Form-versioned trademark particulars, representations, class/specification scopes, use/priority/party/agent data, filing manifest and readiness validation.
- `IPLF-039B`: Extend existing mailbox/calendar/Drive/Communication evidence and `CompanyNotice` with permission-scoped IP links, IP-aware notice authorization, dedupe/attachment processing, triage projection, correspondence/service/instruction candidates, legal-deadline delegation and accepted-effect boundary; `/app/notices` remains the single accepted-notice register.
- `IPLF-039C`: Activate the M2 working-calendar/responsibility foundation through coverage acceptance, leave/deactivation reassignment, external calendar projection and reproducible daily docket control report; do not rebuild the records in M3.
- `IPLF-039D`: Restricted deadline-incident evidence, impact scan, containment, ordinary-docket correction linkage and corrective-action verification.
- `IPLF-039E`: Effective-dated chain of title, related-right family, assignment/licence/encumbrance conflicts and recordal projections.
- `IPLF-039F`: Add `ip_cost_items` and immutable evidence/billing links; keep time/invoice/payment/spend in existing Matter owners and prove one amount/accounting owner across reports and exports.

### M4 tasks

- `IPLF-040`: Opposition proceeding schema/state machine/workspace.
- `IPLF-041`: Applicant-side workflow and deadlines.
- `IPLF-042`: Opponent-side workflow and deadlines.
- `IPLF-043`: Evidence, extension, hearing, order, appeal, withdrawal, and settlement events.
- `IPLF-044`: Matter linkage and synchronized but independent lifecycle display.
- `IPLF-045`: Generalize existing Draft/ModelRun/DraftingDataExtractionField targets and template/format-validation paths, then add trademark pleading context/source manifests without a parallel drafting engine. Recommendation remains M6 work.
- `IPLF-046`: Consistency, placeholder, exhibit, and source validation.
- `IPLF-047`: Legal SME fixture pack and UAT automation.
- `IPLF-048`: Multi-class/partial scope, service, translation, adjournment, written argument, and non-appearance paths.
- `IPLF-049`: Rectification/cancellation/non-use proceeding foundation.

### M5 tasks

- `IPLF-050`: Contracted registry/provider adapter registered in existing connector readiness, support matrix, provider cost and provider-operations owners; retain a distinct IP-office capability matrix only for legal coverage fields those owners cannot express.
- `IPLF-051`: IP registry matching, links, snapshots, diffs, reconciliation, freshness and durable sync-attempt evidence; reference, never copy, existing `TrackedCase`/Matter court updates.
- `IPLF-052`: Journal ingestion and watch profiles/hits.
- `IPLF-053`: Watch-to-opposition/enforcement handoff.
- `IPLF-054`: Indian Kanoon licensed adapter, attribution, cost, and source access.
- `IPLF-055`: Extend existing portal identity/grants/views/communications with IP targets, approved report publications, instructions, expiry, revocation, and delivery tracking.
- `IPLF-056`: Register registry/watch/source operation kinds, readiness, quota/cost, dead-letter/replay handlers in existing integration/provider-operations dashboards and services; no parallel health/support/cost UI.
- `IPLF-057`: Madrid international registration/designation and WIPO reconciliation.
- `IPLF-058`: Assignment/transmission, registered-user/licence, name/address, and other post-registration recordals.
- `IPLF-059`: Foreign-associate instruction, acknowledgement, invoice, and filing-evidence workflow.

### M6 tasks

- `IPLF-060`: Canonical judge/bench aliases and authority remapping.
- `IPLF-061`: Extend the existing `/guide` content owner into indexed Product Guide retrieval, commands, and navigation actions; do not create a second help corpus/page.
- `IPLF-062`: Permission-scoped Ask this Workspace using new assistant sessions/turns/citations plus existing `ModelRun`, source, retrieval, and AI-policy owners.
- `IPLF-063`: Generalize existing Recommendation to IP targets and use the M4 target-aware Draft/review owner with supporting/contrary authorities and frozen source manifests; do not repeat the drafting migration.
- `IPLF-064`: AI proposed-action preview/confirm boundary.
- `IPLF-065`: Prompt-injection, permission, citation, abstention, and legal-safety evals.
- `IPLF-066`: Private index generations, prefiltered ACL retrieval, hydration reauthorization, cache partitioning, revocation/tombstone propagation and saved-output access.

### M7-M10 tasks

- `IPLF-070`: Pilot migration, exception remediation, performance, DR, runbooks, support, billing, GA.
- `IPLF-071`: Automated tenant/client export, hold-aware purge/offboarding, provider/index/object cleanup, tombstone-on-restore and throwaway-tenant evidence.
- `IPLF-072`: Current regional/failover, no-dual-send worker recovery, incident and credential-compromise drills with measured RPO/RTO.
- `IPLF-073`: Add shared access-review campaigns and emergency-access sessions to the existing target-aware access owner; prove expiry, cache/session revocation, independent post-review and no standing-grant residue.
- `IPLF-079`: Enforce unavailable/intake-only/beta/GA domain labels and child-PRD/source-pack/legal-fixture gates in the server capability catalogue.
- `IPLF-080`: Implement the patent family/prosecution/opposition/claim-version/annuity/working/title domain and journeys from a versioned child-PRD draft behind unavailable/intake-only flags; approval is required before authoritative automation or beta/GA activation.
- `IPLF-090`: Implement independent design, copyright, domain, licensing, and enforcement domain slices from versioned child-PRD drafts behind unavailable/intake-only flags; approval is required before activation or supported claims.
- `IPLF-091`: Implement independent GI, plant-variety, semiconductor-layout, trade-secret, and customs/anti-counterfeiting domain slices from versioned child-PRD drafts behind unavailable/intake-only flags; approval is required before activation or supported claims.
- `IPLF-100`: Cross-IP reporting, client operations, migration, security, and full GA.

## 26. Testing and verification strategy

### 26.1 Required test layers

1. **Unit:** identifier normalization, workflow transition table/guards, deadline/calendar/uncertain-trigger calculations, responsibility coverage, retention/hold resolution, projection revocation, naming, source validation, recipient resolution, canonical request/file hashing and idempotency.
2. **Database:** migrations, composite keys/indexes/checks, tenant/access isolation, optimistic concurrency, append-only history, actor deactivation preservation, hold/purge dependencies, state-event reconciliation and mixed-revision rollback/forward compatibility.
3. **API:** capability/entitlement/flag matrix, step-up/four-eyes/break-glass, cross-tenant/no-existence denial, stale writes, idempotent commit/replay, data-operation manifest expiry, typed errors, OpenAPI/generated-client contract.
4. **Provider/connector contract:** recorded/synthetic fixtures for existing mailbox/calendar/Drive/communication adapters and new registry/source providers: success, no-change, auth/rotation/disconnect, rate limit, timeout, malformed payload, schema change, duplicate/out-of-order event, webhook forgery/replay and protected download.
5. **Legal fixture:** versioned synthetic/draft Indian trademark applications and applicant/opponent opposition timelines may drive implementation; lawyer-approved golden fixtures with expected rules, deadlines, documents, and outcomes are mandatory before authoritative activation, legal verification, or completion.
6. **Frontend component:** status/freshness/source rendering, long identifiers/mark names, empty/error/degraded states, keyboard/accessibility.
7. **End-to-end:** every UJ-01 through UJ-68 normal path and all named critical exceptions appropriate to the milestone; a future child PRD adds rather than replaces its domain journeys.
8. **Security:** tenant/client/document/index/cache isolation, SSRF/redirect/DNS rebinding, prompt injection, archive/malicious upload/formula, webhook signature/replay, step-up/session expiry, break-glass, export/purge leakage and provider-secret exposure/rotation.
9. **Performance:** representative portfolio/inbox/index/audit sizes, import/export/purge size, document/source volume, access-filtered query concurrency, notification/outbox batch, registry diff and retention-integrity scans with captured query plans.
10. **Recovery:** recent database/object restore, exact app boot, state/event/outbox/index/tombstone reconciliation, worker fencing/no-dual-send, provider-degraded operation and measured RPO/RTO.
11. **Production smoke:** exact deployed revision/image/schema, allowlisted tenant, real scheduler/job/provider/source path, desktop/mobile visible behavior, post-reload persistence and current capability/entitlement/flag evidence.
12. **Ownership/duplication:** migration and contract tests prove a Matter/IP task, hearing, next-hearing decision, deadline, intake, conflict, grant, portal share, CompanyNotice/reply, notification, Communication, cost/evidence/accounting link, draft/extraction, tracked court update, registry snapshot, provider operation, import job, and report has one canonical writer/row/control plane; a repository check rejects forbidden duplicate component names unless an approved ADR allowlist and retirement date exist.

### 26.2 Release-blocking scenario set

- Application and opposition numbers coexist and search correctly.
- Filing-ready validation changes correctly by form/effective version, applicant/mark type, use/priority claim and class scope; the approved manifest survives reload and later metadata edits.
- Filed/advertised/registered and partially opposed/refused class/specification scopes remain independently reproducible.
- Applicant and opponent opposition workflows calculate different correct stages/deadlines.
- Multi-class/partial opposition preserves challenged and unaffected class/goods scope through decision.
- Rules 45/46 election to rely on pleaded facts differs from inaction/deemed abandonment; reply/further evidence paths are distinct.
- Service, translation, verification, adjournment, written-argument, and non-appearance evidence survive reload and reporting.
- Filing payment without office acknowledgement cannot create filed/accepted legal state.
- Madrid designation refusal cannot overwrite another designation or the base/international registration.
- Pending assignment/recordal cannot replace currently registered proprietor without effective/source qualification.
- Wrong/backdated trigger produces reviewable recalculation, not silent overwrite.
- Holiday/office-closure conflict or uncertain trigger blocks exact auto-confirm; external calendar edit/deletion cannot change the legal deadline.
- Leave/deactivation cannot complete while a critical item lacks accepted replacement coverage; concurrent preview change returns conflict.
- Webhook, polling and manual forwarding of the same message create one inbox envelope and no duplicate event/deadline/instruction.
- Accepting registry correspondence creates/reuses one `CompanyNotice`; it appears in `/app/notices` and the IP workspace with one owner/status/reply state and no copied body/file. Its exact legal package is immutable despite notice-file replacement attempts, its claim amounts do not become cost/payment state, and restricted linkage cannot expose title, count, download or owner list to an unauthorized user.
- Changing an IP-linked notice reply due date delegates to the correlated legal-deadline command; direct conflicting notice/deadline edits fail, and recording a sent reply does not imply registry acceptance or complete an unrelated legal deadline.
- Inbound text that says `file`, `withdraw`, or `deadline extended` cannot create that legal effect without the typed confirmation command and evidence.
- Suspected deadline error preserves restricted evidence and scans sibling calculations without backdating or erasing ordinary docket history.
- Rescheduled hearing cancels obsolete reminders and creates replacements once.
- Suppressed critical email produces visible fallback and escalation.
- Disabled/403 scheduler is red even if configuration says enabled.
- Provider replay does not duplicate events, documents, notifications, or costs.
- A linked eCourts/CNR matter uses the existing `TrackedCase`/bookmark/update/poll and Matter court evidence once; the IP proceeding references it and does not create an IP registry snapshot for the same court update.
- Registry adapter readiness, legal terms/support, provider cost, failures and replay are visible through existing integration/provider-operation surfaces; disabling the shared kill switch stops new fetches without altering accepted IP legal state.
- Creating or editing an IP task/hearing through an IP route is immediately the same shared row seen by Today/Calendar and any linked Matter route; no synchronizer or second mutable copy exists.
- IP intake/conflict, internal/portal access, billing, drafting, provider operations, imports, and reports are visible through their existing CaseOps control planes with target-aware filtering and one audit history.
- Keyword search infrastructure failure is not displayed as no results.
- Every research/review/judge result source action opens or reports typed failure.
- Unverified/mismatched Bare Act text is not retrievable as authoritative evidence.
- AI answer cannot cite a record the actor cannot open.
- Client report excludes internal notes, privilege, unapproved drafts, and AI traces.
- Revoked IP access disappears from direct URL, lists/counts, search/autocomplete, exports, source/document proxy, assistant, notification, and portal.
- Rule proposer cannot activate the same version; failed source/fixture blocks activation; new activation does not rewrite confirmed historical deadlines.
- Import partial success preserves every failed row and is idempotent.
- An IP import has one neutral `bulk_import_jobs` lifecycle. Legacy Matter/Employee jobs can appear in an aggregated history without status dual-write, and no IP commit calls Matter-specific row logic.
- One official fee/courier/associate amount has one `ip_cost_item`; proof links have no payment state, one billable projection reaches one existing invoice line/spend record, and void/write-off/payment cannot diverge between IP and billing reports.
- Terminal application/proceeding/Matter lifecycle cannot be reactivated by generic updates, imports, workers, or child events.
- An unsupported non-trademark `asset_type` remains unavailable/intake-only and cannot expose beta/GA workflows until its child-PRD capability gate is approved.
- Chain-of-title report distinguishes executed, effective, registered, beneficial, disputed and pending-recordal states at a selected date.
- Emergency access cannot cross company or forbidden platform scope, expires during an active session, invalidates cached/search access and requires independent post-review.
- Membership deactivation preserves actor/sent/legal evidence while immediately revoking sessions, connector use, assignments, retrieval and future notification targeting.
- Hold issued during export/purge invalidates the approved manifest and blocks execution; hold release cannot trigger immediate deletion.
- Export/purge dry run and execute reconcile SQL, current/old object versions, search/vector/cache, queued work, provider-held data and tombstones; injected subsystem failure prevents false completion and resumes idempotently.
- Restored environment applies purge tombstones and fences old workers before serving; pending reminders/outbox/provider operations do not duplicate effects after resume.
- Private result revocation during streaming removes citation/content immediately; stale cache/index/rebuild cannot reveal title, snippet, count or existence.
- Old and new application/job revisions coexist against expanded schema; rollback after committed legal event preserves the event and one consumer owns each effect.
- Rotated/disconnected connector rejects old webhook/credential events safely, retains manual work and reports unhealthy/stale rather than green.

### 26.3 Repository verification commands

Run focused tests during development, then the complete applicable gate once for the exact integrated release candidate before merge:

```powershell
git diff --check
npm run lint:api
npm run test:api
npm run test:functional-qa-runner
npm run typecheck:web
npm run test:coverage --workspace @caseops/web
npm run build:web
npm run test:e2e:app
```

For API/schema changes, start the tested local API revision, regenerate the existing frontend OpenAPI types, rerun typecheck/tests and fail review if the generated diff is absent or contains unexplained unrelated drift:

```powershell
npm run gen:api-types --workspace @caseops/web
git diff --exit-code -- apps/web/lib/api/openapi-types.ts
```

Commit the intentional generated change before using the `git diff --exit-code` proof; CI should generate to a temporary path or compare against the committed file so the gate is reproducible.

For any schema, composite FK/index, JSON/Postgres, search/vector, or migration change, also run the repository's Postgres validation path with `CASEOPS_TEST_POSTGRES_URL` and `CASEOPS_DATABASE_URL` pointing to an isolated disposable PostgreSQL 17 plus pgvector database:

```powershell
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run pytest -q -m postgres apps/api/tests/test_postgres_validation.py
```

Migration PRs additionally prove upgrade from a sanitized copy/schema at the current production Alembic head, application compatibility during expand/switch, and downgrade or restore/roll-forward rehearsal. Provider tests use fixtures/sandbox and cannot spend production quota in CI. Production acceptance uses the exact immutable deployed image and a dated, allowlisted Playwright/API/job smoke path.

### 26.4 Acceptance ownership

| Gate | Required approver |
|---|---|
| Legal rule/form/deadline fixture | Named IP lawyer product owner plus second qualified reviewer |
| Tenant/permission/security | Engineering reviewer plus security owner for M2/M5/M6/M7 |
| Step-up/four-eyes/break-glass/access review | Security owner plus pilot firm access owner |
| Retention/legal hold/export/purge/offboarding | Records/privacy/legal owner plus security/SRE executor reviewer |
| Provider terms/source attribution | Legal/provider owner |
| Migration reconciliation | Docketing Manager/pilot data owner |
| UX/accessibility | Product/design/QA |
| Production operations/SLO/rollback | Engineering/SRE owner |
| Backup/restore/failover and worker fencing | SRE/incident owner plus docketing/legal workflow verifier |
| Pilot journey acceptance | Named pilot firm representative and CaseOps product owner |

Engineering test success cannot substitute for legal or pilot acceptance, and a lawyer's content approval cannot substitute for tenant/security/operational gates.

These approvals gate the relevant authoritative activation, customer-data operation, real legal/provider effect, or acceptance claim. They do not block repository implementation behind disabled flags. One dated consolidated approval event may cover an enumerated unexpired immutable release bundle and environment, provided it contains every required approver identity; expiry or a material scope, evidence, or risk change requires renewed approval.

## 27. Rollout, rollback, and operations

1. Ship each compatible integrated release train behind tenant and capability flags; milestone scope remains separately traceable within it.
2. Run schema additions before application activation; prefer additive migrations and dual-read only where explicitly designed.
3. Before storing non-anonymized pilot IP data, approve the data map/retention/hold policy, prove private projection revocation, complete current database-plus-object application-cutover restore, and exercise tenant-export dry run.
4. Enable staff tenant, then one anonymized test tenant, then pilot firm allowlist, then staged tenant cohorts.
5. Registry, AI, inbox, calendar, notification, search projection and each domain require separate server flags/kill switches so manual docketing and existing data remain available during degradation.
6. Shadow registry normalization, workflow/state materialization, deadline calculations, connector links and private projection generations before accepting changes or reminders.
7. Publish each exact migration/import/data-operation preview and obtain the required tenant/approver acceptance before commit/execute against non-anonymized tenant data. One consolidated approval event containing every required approver covers an unchanged unexpired immutable operation manifest through immediate pre-execution revalidation; expiry or material drift requires renewed acceptance.
8. Worker/dispatcher ownership switches only after old/new revision inventory and fencing proof. Dual-read/shadow compare is allowed; duplicate send/provider mutation is not.
9. Rollback disables feature behavior without deleting new legal history. Provider polling/reminders/indexing/retention execution can be paused independently; restore/roll-forward handles committed data.
10. Maintain runbooks for scheduler permission, provider auth/rotation/rate limit, stale source, corrupt snapshot, notification suppression, private-index revocation, deadline rule/workflow error, export/purge/hold, restore/failover/no-dual-send and cross-tenant incident.
11. A release is not complete until the validated commit is on `main`, deployed revision/image/schema and active worker/job set are identified, and dated production E2E passes.

## 28. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Incorrect legal deadline rule | Missed right or professional risk | Versioned lawyer-approved rules, explainable calculation, confirmation, audit, kill switch |
| Unstable/prohibited source automation | Outage, legal/contract risk | Contracted adapters, manual fallback, capability matrix, no bypass scraping |
| AI hallucinated law/source | Misleading work product | Verified retrieval, citations, abstention, source-open checks, lawyer approval |
| Provider accepted but message undelivered | Missed hearing/deadline | Per-channel delivery states, webhook, fallback, escalation, test/recovery |
| Registry status overwrites manual truth | Corrupted docket | Immutable snapshots/diffs, risk review, event supersession |
| Generic model cannot support IP depth | Rework and inconsistent workflow | Dedicated IP bounded context and type-specific lifecycles |
| Overbroad client/chat access | Privilege or confidentiality breach | Explicit grants, retrieval enforcement, security tests, audit |
| Competitor-parity scope explosion | Delayed trust fixes and unusable breadth | Milestone gates, trademark-first journeys, broader IP after GA evidence |
| Dirty legacy portfolio data | Duplicate/missed records | Preview, reconciliation, exception queues, original evidence, signed migration report |
| Platform operator sees confidential content | Privacy breach | Redacted operations metadata, tenant-scoped payload access, least privilege |
| Parallel inbox/calendar/notification connector paths | Duplicate imports/sends and conflicting retention | Extend existing connector evidence and sync services; one raw envelope/credential/provider effect owner |
| IP-prefixed copies of existing work, intake, access, portal, billing, AI, import, provider-operation, or reporting systems | Conflicting status, double work/cost, fragmented audit, and permanent migration burden | Binding Section 11.2 owner ledger, ADR overlap proof, one-writer expand/backfill/switch/contract migration, forbidden-name check, and GA retirement gate |
| Restricted IP linked to broadly visible standalone `CompanyNotice` | Notice title/count/file/owner or reply metadata leaks across an ethical wall | IP-aware notice authorization on every read/download/report; explicit mixed-target audience; fail-closed tests before activating links |
| Replaceable notice file or amount fields treated as legal evidence/cost | Lost source version, overwritten proof, or duplicate financial state | Immutable IP document/Communication evidence link; supersession instead of overwrite; explicit unique `ip_cost_item` link |
| Matter importer relabelled as generic or court update copied into IP registry state | Domain coupling, corrupted history, duplicated provider work and unsafe migrations | Neutral import `REPLACE` ADR/adapters; keep `TrackedCase`/Matter court evidence canonical; field-level ownership/reconciliation tests |
| Shared tables generalized months before a consuming feature | Large nullable-FK migrations, dead abstractions and prolonged compatibility risk | Just-in-time M2-M7 slices, one owner per revision, consumer acceptance in the same milestone and no foundation credit for unused targets |
| Membership or portal deletion cascades immutable evidence | Lost legal/delivery audit history | Deactivate rather than delete; nullable actor refs plus snapshots; migration/cascade tests and governed tenant purge |
| Revoked private data remains in vector/cache/saved AI output | Confidentiality breach | Prefilter plus hydration reauth, policy generations/tombstones, fail-closed lag, integrity scan and revocation E2E |
| Backup claims exceed tested recovery | False resilience and prolonged outage | Exact deployed evidence, database-plus-object app-cutover drill, worker fencing, measured user-visible RPO/RTO |
| Tenant export/purge built as ad hoc SQL/delete | Leakage, incomplete deletion or resurrection | Registered data map, dry-run manifest, step-up/four-eyes, resumable subsystem handlers, tombstone-on-restore proof |
| Emergency access becomes standing privilege | Ethical-wall/privilege breach | Narrow step-up scope, short expiry, notification, session/cache revocation and independent review |
| Generic workflow enum permits illegal transition | Wrong legal state/deadline | Versioned machine-readable transitions, typed commands, database/service guards, legal fixtures and state-event reconciliation |

## 29. Open decisions with owners and deadlines

| Decision | Owner | Due | Blocking milestone |
|---|---|---:|---|
| Pilot firms, team size, and anonymized sample matters | Product | 14 Aug 2026 | M2 |
| Signed Section 11.2 component ownership ledger, shared-table expansion plan, canonical writers, compatibility routes, and retirement gates for every M2/M3 slice | Architecture/Data/Product | 14 Aug 2026 | M2 |
| Actual document-name list and filing-stage taxonomy | IP Product Owner | 14 Aug 2026 | M2/M4 |
| Initial jurisdictions/offices beyond Indian Trade Marks Registry | Product/IP SME | 14 Aug 2026 | M2 |
| Async/workflow ADR: existing Cloud Run/Temporal/outbox worker ownership, lease/fencing, retry and cancellation | Architecture/SRE | 14 Aug 2026 | M2 |
| Data-class map, retention bounds, legal-hold authority, audit tombstone, region/subprocessor and provider-deletion policy | Records/Privacy/Security | 14 Aug 2026 | M2 |
| Step-up purposes, four-eyes actions, emergency-access scope/expiry/reviewer and periodic access-review policy | Security/Pilot Firm | 14 Aug 2026 | M2 |
| Approved RPO/RTO and reconciled current database/PITR/object/version/key/cross-region evidence plus restore drill plan | SRE/Security | 14 Aug 2026 | M2 |
| Private search/index/cache/saved-output access-generation and revocation design | Security/Architecture | 14 Aug 2026 | M2/M6 |
| Clearance search sources/depth and opinion disclaimer | IP SME/Legal | 4 Sep 2026 | M3 |
| Approved trademark deadline-rule inventory and holiday policy | IP SME | 4 Sep 2026 | M3 |
| Approved filing forms, fee/version source, entity categories, and submission boundary | IP SME/Finance | 4 Sep 2026 | M3 |
| Trademark mark/applicant/use/priority/class-scope schema and required evidence by filing type | IP SME | 4 Sep 2026 | M3 |
| Official holiday/closure sources, calendar precedence, internal-target and deadline-signoff policy | IP SME/Docketing Manager | 4 Sep 2026 | M3 |
| Primary/backup/supervisory coverage, leave/deactivation and daily docket sign-off policy | Pilot Firm/Owner | 4 Sep 2026 | M3 |
| Mailbox/calendar providers, selected-account consent, retention, message SLA and external-calendar edit policy | Security/Pilot Firm | 4 Sep 2026 | M3 |
| `CompanyNotice` IP authorization, mixed-target audience rule, immutable legal-file bridge, reply-deadline delegation and legacy notice remediation | Security/Architecture/IP Product | 4 Sep 2026 | M3 |
| Neutral bulk-import `REPLACE` ADR: job schema/state/API, legacy Matter/Employee aggregation, migration/non-migration decision and retirement gates | Architecture/Data/Product | 4 Sep 2026 | M3 |
| Billing Matter requirement, official/associate cost taxonomy, evidence links, invoice-line/outside-counsel-spend mapping and no-double-count reconciliation | Finance/IP Product/Architecture | 4 Sep 2026 | M3 |
| Missed/incorrect deadline incident access, escalation, evidence, insurer/client communication and retention policy | Risk Partner/Legal | 4 Sep 2026 | M3 |
| IP India automation source/provider/manual boundary, `TrackedCase`/Matter-court non-copy rule and reuse of connector readiness/support/cost/operations | Legal/Engineering/Architecture | 29 Jan 2027 | M5 |
| WIPO/Madrid provider/source, terms, and designation scope | Legal/Engineering | 29 Jan 2027 | M5 |
| Indian Kanoon commercial plan, attribution, caching, and cost limits | Legal/Finance | 29 Jan 2027 | M5 |
| Mandatory notification channels and escalation policy | Pilot Firm/Owner | 21 Aug 2026 | M3 |
| Client portal data-sharing defaults | Product/Security | 30 Jun 2027 | M5 |
| AI model/provider/retention policy for privileged work | Security/Legal | 29 Oct 2027 | M6 |
| Automated export/purge/offboarding scope, waiting period, dual approval, backup tombstone and exception policy | Records/Privacy/Security | 29 Oct 2027 | M7 |
| Packaging and provider-cost pass-through | Finance/Product | 29 Mar 2028 | M7 |
| Approved child PRD, source/rule/form pack, pilot and legal reviewers for each M8-M10 IP domain | Product/Specialist IP SME | Before authoritative automation or beta/GA activation | M8-M10 |

If an open decision is not resolved by its due date, the affected automated feature remains disabled or manual; Codex must not invent a legal rule, provider permission, or client-sharing policy. Continue its safe repository implementation and all independent work using versioned synthetic fixtures and explicit unavailable/manual states.

## 30. Definition of done

The program or milestone is done only when the following final attestation criteria hold. These criteria govern activation, milestone exit, and completion claims; they are not prerequisites for starting or continuing independent repository implementation:

- Its named user journeys and exception paths pass automated and lawyer-led UAT.
- API, schema, audit events, permissions, operational runbooks, product help, and migration notes are updated.
- OpenAPI/generated frontend types, workflow/domain/audit event schemas, data map/retention/hold/disposition handlers and capability labels are updated and drift checks pass.
- Every shipped component matches the Section 11.2 ownership ledger; forbidden duplicates are absent, compatibility adapters call the canonical service, one-writer reconciliation passes, and superseded paths have an owner and removal date.
- Source/provider/legal terms are approved and accurately represented in UI and audit data.
- No P0/P1 defects remain; accepted lower-priority defects have owner and date.
- Tenant isolation, source security, prompt injection, notification replay, and lifecycle fail-closed tests pass.
- Performance and observability targets have production or approved pilot evidence.
- Step-up/four-eyes/access-review/break-glass and private retrieval/revocation gates appropriate to the milestone pass adversarial tests.
- Recovery evidence is current for the milestone's schema/storage/worker topology and meets approved RPO/RTO; export/purge/offboarding is never claimed complete from a manual runbook or unexercised script.
- The exact deployed revision is verified in production and the dated end-to-end workflow passes after reload.
- The implementation is merged to `main` and rollback has been tested or rehearsed.

### 30.1 Defect severity used by milestone gates

- **P0:** Cross-tenant/privilege/break-glass/search/cache/export exposure; wrong active legal lifecycle/deadline from an approved fixture; unverified text presented as authoritative; duplicated/unaudited filing/payment/notification/provider effect; purge of held/wrong-tenant data; resurrection of purged data; destructive data loss; production-wide critical outage. Release stops and affected automation is disabled.
- **P1:** A named milestone journey cannot complete for a supported pilot configuration; source cannot be opened; critical reminder lacks visible recovery; migration/data operation cannot reconcile; revocation remains retrievable; backup/restore/export evidence is false or expired; provider/job freshness is materially misleading; no safe workaround. Milestone cannot exit.
- **P2:** Supported journey is degraded but has a documented safe workaround and no hidden legal/security/data risk. Acceptance requires owner, target date, and pilot disclosure.
- **P3:** Cosmetic, copy, or low-impact usability defect that does not misstate legal/operational truth. It may enter normal backlog.

The milestone evidence pack includes a live requirement-to-journey-to-test-to-release matrix. A requirement is not complete because code exists; its normal path, named exceptions, permission cases, audit/observability, rollback, and deployed acceptance must all resolve.

## 31. Codex implementation contract

When this PRD is handed to Codex:

1. Implement the entire repository-controlled program as one continuous dependency-DAG run. Prefer one integration branch/PR and one compatible release train; keep coherent slice/commit boundaries for ownership, tests, migrations, traceability, and rollback.
2. Establish current code, migrations, tests, deployment manifests, and production state at run start; re-read affected facts when relevant state changes rather than before every task.
3. Start M1 production reliability and source truth immediately while building independent IP feature breadth behind fail-closed flags and truthful unavailable/manual states. A trust defect fences only affected activation or release claims.
4. Treat Section 11.2 as binding architecture. Before changing an ownership area, classify its components as `NEW`, `EXTEND`, `LINK`, or `REPLACE`, search current models/services/routes/pages/jobs once, and name the canonical writer plus compatibility/retirement path.
5. Do not create IP-owned task, hearing, next-hearing, intake, conflict, notice/reply, internal-access, ethical-wall, portal-grant, time/expense/payment-ledger, legal-source-master, model-run, draft/extraction, recommendation, import-control, provider-operations/readiness/support/cost, report-engine, connector, credential, tracked-court, or notification-delivery subsystems. Implement the extension/link/replacement contracts in Sections 11, 13, 16, and 23.
6. Use `company_id`, composite tenant constraints, `expected_updated_at`, `lifecycle_version`, RFC 7807 errors, request IDs, capability catalogs, and deployment patterns exactly as the current repository does unless the slice explicitly migrates them.
7. Never overwrite unrelated or user-created work in a dirty tree.
8. The program integration PR must contain a generated per-slice index of requirement IDs, journeys, tests, migration/rollback impact, security impact, and production verification steps; do not require repetitive boilerplate in each commit.
9. Any ambiguous legal rule, provider term, document taxonomy, or client policy blocks authoritative activation for that feature, not repository implementation and not independent work. Never guess.
10. Extend existing task/hearing/next-hearing/deadline/calendar, intake/conflict, access/portal, `CompanyNotice`, Microsoft 365/mailbox/Drive/Communication, billing, drafting/extraction/AI audit, tracked-case/court, provider-readiness/cost/operations, and report/export owners through typed IP adapters in their assigned milestone. For imports, follow the neutral `REPLACE` contract because Matter/Employee import jobs are domain-specific; do not alias one as generic or create synchronized mutable copies.
11. Do not claim backup, restore, export, purge, legal hold, residency or deletion complete from repository prose. Reinspect deployed configuration and dated evidence, then implement/test the exact missing operation for the current schema.
12. High-risk routes reuse existing MFA recent-step-up and server capability services. Never accept actor/approver/company identity from a request body to satisfy authorization or four-eyes policy.
13. If a change conflicts with the ownership ledger, park that ownership-conflicting node, produce an ADR/gap analysis, and continue every independent node. Passing local tests is not permission to add a duplicate subsystem.

Suggested continuous execution prompt:

```text
Implement every repository-controlled requirement in
docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md as one continuous dependency-DAG run.
Start the Phase 0/M1 trust workstream and every independent M2-M10 node in parallel.
Use focused checks per change, one complete applicable matrix per exact integrated
candidate, and the smallest practical number of PRs and release trains. Keep external
or unapproved behavior fail-closed and continue working. Pause only for authority that
cannot be delegated or an exact irreversible production action not already approved.
```

## 32. Source and benchmark references

- IP India, Trade Marks Rules 2017: <https://ipindia.gov.in/tm-rules-2017>
- IP India, hearing cause lists: <https://ipindia.gov.in/pages/trade-marks/track/hearing-cause>
- IP India, forms and official fees: <https://ipindia.gov.in/pages/trade-marks/learn/forms-and-official-fees>
- IP India, international trademark protection: <https://www.ipindia.gov.in/international-trade-mark-protection>
- IP India, Madrid and trademark guidelines: <https://www.ipindia.gov.in/trade-marks-resources-guidelines>
- IP India, trademark manuals page (including draft-status material): <https://www.ipindia.gov.in/trade-marks-resources-manual>
- WIPO Madrid System: <https://www.wipo.int/madrid/en/>
- WIPO Nice Classification: <https://www.wipo.int/classifications/nice/en/>
- WIPO Vienna Classification: <https://www.wipo.int/classifications/vienna/en/>
- WIPO Locarno Classification: <https://www.wipo.int/classifications/locarno/en/>
- Indian Kanoon API documentation: <https://api.indiankanoon.org/documentation/>
- Indian Kanoon API terms: <https://api.indiankanoon.org/terms/>
- Indian Kanoon API pricing: <https://api.indiankanoon.org/pricing/>
- eCourts Services Portal: <https://services.ecourts.gov.in/ecourtindia_v6/>
- eCourts Services official help/user guide: <https://services.ecourts.gov.in/App/apphelp.html>
- PPV&FR Authority, registry information: <https://plantauthority.gov.in/plant-varieties-registry-related-information>
- PPV&FR Authority, forms: <https://plantauthority.gov.in/plant-variety-forms>
- Iolite IP Asset Management: <https://www.iolite.net.in/ip-asset-management-software/>
- MikeLegal products: <https://mikelegal.com/Products>

## 33. Review record

### 33.1 Pass 1: Product, legal workflow, and journey completeness

**Completed:** 1 August 2026.  
**Lens:** All 16 customer feedback items, Indian trademark lifecycle, opposition rules, user/persona coverage, complete-IP scope, and normal/exception journeys.  
**Primary gaps found and corrected:**

- Added clearance-to-instruction, filing/fee/acknowledgement, journal publication, partial/multi-class opposition, Madrid, post-registration recordal, foreign-associate, rectification/non-use, and specialist enforcement journeys.
- Added explicit opposition scope, earlier-right data, verification, service, evidence-election, reply/further evidence, translation, adjournment, written argument, non-appearance, security-for-costs, and downstream disposition requirements.
- Expanded broader IP coverage from a generic future statement to patent opposition/working, designs, copyright, licensing, GI, plant varieties, semiconductor layouts, trade secrets, domains, and customs/anti-counterfeiting.
- Added filing packages/transactions, fee versions, search projects, service records, international registrations, costs, ownership/relationship records, and additional source references.
- Expanded the journey catalogue and detailed maps from 30 to 53, including firm intake, daily docket, correspondence/instructions, billing links, and controlled terminal lifecycle. Pass 3 later completed the missing explicit precondition/audit fields in some early journeys.

### 33.2 Pass 2: Repository fit, feasibility, safety, and Codex execution

**Completed:** 1 August 2026.  
**Lens:** Current SQLAlchemy/FastAPI/Next.js architecture, capability catalog, concurrency/lifecycle rules, notifications, documents, portal grants, providers/jobs, migrations, CI, operational evidence, staffing, and implementation granularity.  
**Primary gaps found and corrected:**

- Replaced generic tenant terminology with the repository's `company_id`, composite tenant constraints, `expected_updated_at`, `lifecycle_version`, RFC 7807, request ID, capability-catalog, and production-deployment patterns.
- Added a real `ip_docket_records` FK anchor and physical data/index/amount/time/immutability contracts instead of unsafe polymorphic IDs and JSON-first modeling.
- Added internal IP ethical-wall grants and two-layer public-rule/company-policy governance, with dedicated access, rule-activation, and source-curation journeys.
- Corrected the false assumption of an existing generic versioned document entity; specified new IP document/version/link records that reuse existing storage/scanning/extraction primitives without copying bytes.
- Initially proposed IP-specific portal/access records; Pass 5 superseded those proposals with target-aware expansion of the existing portal/access owners and removed the parallel tables.
- Defined convergence from direct hearing-reminder dispatch to existing durable notification intents, including recipient types, provider events, migration, one-dispatcher cutover, and rollback without dual sending.
- Added HTTP idempotency, transactional outbox, lifecycle command, cursor pagination, error, async-operation, migration slicing, compatibility, and exact repository implementation contracts.
- Added capability defaults, four-eyes rule activation, billing entitlements, rollout flags, CI/Postgres/production verification commands, acceptance ownership, severity definitions, and PR evidence requirements.
- Performed the first capacity rebaseline for one five-engineer squad; Pass 4 superseded it after the added security, data-governance, recovery, connector-reuse and child-domain work was sized honestly.
- Replaced the unsafe whole-M1 Codex prompt with a single read-only `IPLF-001A` audit and mandatory slice order.

### 33.3 Pass 3: Adversarial legal operations and full-IP honesty

**Completed:** 1 August 2026.  
**Lens:** Exact trademark filing particulars, law-firm docket controls, communications/service/instructions, source authority, missed-deadline response, chain of title, complete journey evidence, and credibility of `Full IP` scope.  
**Primary gaps found and corrected:**

- Added form-versioned mark representation, applicant/agent/signatory, class/specification, use/affidavit, priority, collective/certification, series/associated/divisional and filing-manifest requirements instead of treating a trademark as mark/classes/status.
- Added official/draft/editorial source hierarchy, conflict/quarantine/impact handling and explicit rule that the 2026 draft trademark manual cannot activate legal automation.
- Added working-calendar versions, uncertain-trigger behavior, primary/backup/supervisory responsibility, leave/deactivation transfer, external-calendar projection, daily control sign-off and restricted missed-deadline incident handling.
- Recast inbox work around immutable evidence, dedupe, triage, service and versioned instructions; no email/calendar/OCR/AI classification can create a legal effect directly.
- Added a minimum capability matrix and signed child-PRD gate for every non-trademark domain; generic `asset_type` storage is now explicitly intake-only, not product support.
- Expanded the journey catalogue from 53 to 62 and corrected all UJ-03 through UJ-30 omissions so every journey has actor, preconditions, main flow, exceptions, audit/postcondition and acceptance.

### 33.4 Pass 4: Adversarial architecture, privacy, recovery, and release proof

**Completed:** 1 August 2026.  
**Lens:** Existing CaseOps connector/MFA/audit/access implementations, state-machine enforceability, private retrieval, membership deletion, retention/legal hold/export/purge, disaster recovery, mixed revisions, worker fencing, provider credentials and schedule feasibility.  
**Primary gaps found and corrected:**

- Corrected a duplicate-subsystem risk: IP now extends existing Microsoft 365, mailbox, Drive, calendar candidate/sync and Communication evidence through typed links; `ip_inbox_items` is a projection, not a second raw envelope.
- Added machine-readable workflow versions and command transition tables with optimistic concurrency, atomic child effects, four-eyes identity checks and state/event integrity reconciliation.
- Added reuse of existing MFA recent-step-up plus scoped break-glass, access reviews, deactivation preservation, portal expiry, JIT support access, webhook raw-body verification and credential rotation.
- Converted vague retention prose into a data-class registry, versioned policies, legal holds, dry-run/execute export/purge/offboarding operations, subsystem manifests, backup tombstones and nightly integrity checks.
- Added private-search prefilter/hydration authorization, access-policy generations, fail-closed revocation, cache partitioning, saved-output control, shadow reindex and purge/quarantine verification.
- Exposed the recovery evidence gap: the dated database clone did not prove current full-stack cutover, object restoration or worker safety, and export/purge scripts do not exist. Added measured RPO/RTO, current database-plus-object restore, dispatcher fencing, no-dual-send and regional/purge drills as gates.
- Added journeys UJ-63 through UJ-68 for emergency access, legal hold/export/purge, full-stack restore, projection revocation, mixed-revision deployment and credential rotation.
- Rebaselined the one-squad schedule to Trademark GA on 29 September 2028 and Full IP GA on 31 July 2032. Earlier Full IP delivery requires independently staffed specialist domain pods, not merely another generalist squad.

### 33.5 Pass 5: Brutal current-implementation and duplicate-work review

**Completed:** 1 August 2026.  
**Lens:** Current source commit `cadb46d`; existing SQLAlchemy ownership, FastAPI services/routes, Next.js control planes, migration blast radius, duplicate mutable state, and whether each proposed table/service was genuinely IP-specific.  
**Brutal findings and corrections:**

- The prior PRD was comprehensive but not implementation-clean. It proposed IP-owned tasks, hearings, intake, conflicts, portal grants, internal grants, payment records, a legal-source master, outbox names, working calendars, access reviews, and emergency access without consistently proving why current CaseOps owners could not be extended.
- Removed `ip_tasks` and `ip_hearings`. Existing `MatterTask`, `MatterHearing`, `MatterDeadline`, calendar/today feeds, calendar sync, cause-list, and reminder services become target-aware shared owners. `ip_deadlines` is now explicitly legal calculation/version evidence with one non-editable operational projection, not a second deadline board.
- Removed separate IP intake/conflict engines. Existing `MatterIntakeRequest` and `MatterConflictCheck` services are generalized to intake/Matter/IP targets; trademark clearance remains a legally distinct search project.
- Removed separate IP internal/portal grant engines. Existing `MatterAccessGrant`, `EthicalWall`, `PortalUser`, and `MatterPortalGrant` ownership is generalized through expand/backfill/switch/contract migration. Access reviews and emergency access are platform-wide controls.
- Removed `ip_payment_records`; retained IP legal cost evidence and unique links to existing invoice/payment/spend owners. Pass 6 further removed the payment-like `ip_disbursement_evidence` aggregate in favor of immutable evidence links.
- Removed the second `legal_source_records` master. Statute, legal-update, authority, citation, court, and judge owners receive shared provenance/source-open/link-health extensions.
- Recast outbox, working calendars, access review, emergency access, idempotency, assistant sessions, and data operations as shared platform foundations with neutral ownership. Added missing `assistant_turns` while preserving `ModelRun`, `Recommendation`, `Draft`, and `DraftReview` as canonical AI/work-product owners.
- Initially made import staging reuse the Matter bulk-import orchestration; Pass 6 corrected that overreach after proving Matter and Employee imports are separate domain-specific implementations with no true generic persisted owner. Provider kinds/report definitions/workspace pages still reuse existing control surfaces.
- Added a binding ownership matrix, forbidden-duplicate list, ADR overlap test, canonical-writer/retirement requirements, one-writer migrations, duplicate architecture tests, and milestone/PR gates. Convenience or an `ip_` prefix is no longer accepted as architecture justification.

### 33.6 Pass 6: Deeper existing-owner and milestone review

**Completed:** 1 August 2026.  
**Lens:** Existing `CompanyNotice`, `TrackedCase`, Matter court sync/orders/cause lists, next-hearing history/suggestions, Matter timeline/activity, billing/time/spend, drafting extraction, connector readiness/support/cost, separate Matter/Employee import implementations, and whether M2 performed work before a consuming feature existed.  
**Brutal findings and corrections:**

- The prior PRD entirely missed the current company-wide notice register. That would have produced a second IP notice/reply queue even though `CompanyNotice`, `/api/notices`, `/app/notices`, files, owner/reply/status reporting and Matter links already exist. Accepted IP notices now extend that owner through `company_notice_ip_links`; the inbox is triage only.
- Existing standalone notices are broadly company-visible and guarded mainly by document capabilities. Linking a restricted IP record without changing list/get/download/report authorization would leak title/count/file/owner metadata. The PRD now makes IP-aware notice authorization and mixed-access fail-closed behavior release-blocking.
- `TrackedCase` already owns provider identity, bookmarks, updates, polling, hashes, source URLs, notifications and eCourts UI, while Matter court sync owns orders/cause lists. The PRD now keeps these canonical and forbids copying court updates into IP registry snapshots. IP-office snapshots remain distinct legal evidence but reuse connector readiness, support, provider cost, operations and replay.
- `MatterNextHearingHistory` and `MatterNextHearingSuggestion` were absent from the ownership matrix. Hearing expansion now includes their provenance/decision state, preventing a second IP reschedule/suggestion history.
- `MatterActivity` and the existing timeline compositor were omitted. IP legal events remain new, but linked Matter timelines compose them by reference rather than duplicating them into `matter_activity`, audit and outbox records.
- The previous import decision was factually wrong: CaseOps has separate Matter and Employee import jobs/services, not a generic owner. The PRD now classifies neutral `bulk_import_jobs` as a controlled `REPLACE` foundation, keeps typed IP staging separate, exposes legacy history through adapters, and forbids pretending a class alias changes ownership.
- `ip_disbursement_evidence` still resembled a second payment/expense aggregate. It was removed. One `ip_cost_item` owns the legal cost; proof/receipts are immutable links; billable time, invoices, client payment and outside-counsel spend remain Matter-owned and require a billing Matter.
- Drafting reuse now explicitly includes `DraftingDataExtractionField` and existing template/format validation. Provider reuse now explicitly includes the connector registry, `CaseTrackingSupportMatrix` and `ProviderCostProfile`, not only the provider-operations page.
- M2 was not credible as a foundation: it pre-migrated intake, conflicts, portal, drafting, reports, provider operations, assistant/private retrieval, access reviews, emergency access and registry state before their milestones. Migration slices are now just in time, independently deployable and assigned to M3-M7 consumers.

### 33.7 Pass 7: Continuous execution and gate consolidation

**Completed:** 15 August 2026.
**Lens:** Manual approval frequency, milestone waterfall, per-slice PR/release repetition, test/evidence duplication, external-acceptance blocking, and safe one-go delivery.
**Primary corrections:**

- Replaced the global M1-to-M10 waterfall with a work-conserving dependency DAG while preserving direct schema, ownership, legal, data, and security dependencies.
- Kept suffix slices as traceability/rollback units but allowed compatible slices to share one integration branch, PR, full test matrix, evidence pack, and release train.
- Moved human legal/provider/product/pilot approval to authoritative activation, public claims, and final acceptance; complete repository implementation proceeds behind fail-closed defaults.
- Consolidated full regression, render, migration, release, and production verification at exact integrated candidates instead of repeating them at every administrative boundary.
- Retained mandatory human authority for real legal/financial/external acts and irreversible production operations, while allowing one unchanged exact-scope approval to survive immediate hold-evidence refresh.

### 33.8 Review validation result

- All 16 feedback items retain requirement, journey, and milestone traceability.
- All 68 journey catalogue entries have one matching detailed journey section with actor, preconditions, main flow, exceptions, audit/postcondition and acceptance.
- All 436 requirement IDs across 50 families resolve without duplicates or numeric gaps, including `COMM-01` through `COMM-14` and `ARCH-OPS-01` through `ARCH-OPS-26`.
- All 11 milestones have dated deliverables, exit criteria, dependencies, and a staffing baseline.
- Current code reuse boundaries, forbidden duplicates, canonical writers, compatibility/retirement paths, unbuilt export/purge tooling and incomplete recovery evidence are explicit rather than represented as completed foundations.
- Remaining items in Section 29 are explicit product/legal/security/provider decisions with owners and blocking milestones, not hidden implementation assumptions.
