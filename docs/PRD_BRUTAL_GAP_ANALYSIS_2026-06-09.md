# PRD: Brutal CaseOps Gap Analysis And Closure Plan - 2026-06-09

## Document Control

- Product: CaseOps
- Document date: 2026-06-09
- Purpose: Brutal, implementation-grounded gap analysis across the existing PRDs, ADP roadmap notes, GBA Law Office requirements, pricing and billing work, provider automation work, and current repository implementation.
- Audience: Founder, Codex CLI, engineering, QA, operations.
- Intended use: This file is the source document for planning the next implementation slices. It is not a marketing document. It intentionally calls out uncomfortable risks.
- Status: Draft for founder review.

## Executive Verdict

CaseOps has a much broader implementation than a normal MVP: matter workflows, recommendations, billing, platform admin, provider operations, Google Workspace foundations, legal updates, case tracking, GBA-specific enhancements, and pricing surfaces are present in code or docs.

The brutal truth is that the product is still not ready for confident, high-volume paid law-firm onboarding without more closure work. It is ready for controlled demos, limited founder-led pilots, and manual operational signoff flows. It is not yet ready to run as a self-serve, low-touch, profitable SaaS for law firms unless the P0 gaps below are closed.

The highest-risk gaps are:

1. Pine Labs live payment acceptance is still blocked by credentials, webhook proof, endpoint/schema confirmation, UAT scenarios, MDR and settlement data, refund/dispute validation, and explicit founder go/no-go.
2. Provider cost calibration is still incomplete. The code now supports cost profiles and margin simulations, but real per-provider pricing and operational cost inputs are not yet proven. This can still turn paid law firms into loss-making customers.
3. Founder production billing signoff is still manual and pending. The back-office platform admin surfaces exist, but founder-authenticated smoke evidence is not complete.
4. Gmail, Google Calendar, and Google Drive are partially implemented but not full durable automation products. Gmail is metadata/review-first, Calendar is mainly CaseOps-to-Google, and Drive is metadata-only.
5. Outlook/Microsoft 365 automation is materially behind Google. Outlook calendar exists in partial form, but Microsoft mailbox ingestion and robust Graph change notification workflows are not delivered.
6. MFA, SSO, SCIM, and step-up authorization are not implemented end to end. This blocks serious enterprise and corporate GC adoption.
7. Autonomous agents and Grantex-style delegated authority are absent. Agent-like work must remain human-reviewed.
8. External notifications, digests, SMS, WhatsApp, and email delivery governance remain partial or fail-closed.
9. AI evaluation is not strong enough to safely scale legal drafting/recommendation automation. There is foundation work, but not an enforced release gate across every AI workflow.
10. Court/provider coverage, live case-tracking economics, and GBA-specific representative UAT evidence remain incomplete.

## Launch Readiness Classification

| Market / Use Case | Current Readiness | Reason |
| --- | --- | --- |
| Founder-led demo | Ready with caveats | Most surfaces can be shown, but provider/live payment caveats must be stated. |
| Limited pilot with manual billing | Conditionally ready | Works if founder manually monitors usage, costs, provider failures, and onboarding. |
| Self-serve paid checkout | Not ready | Pine Labs live UAT and payment operations are incomplete. |
| High-volume law firm onboarding | Not ready | Cost calibration, automation reliability, and support playbooks are not proven. |
| Corporate GC enterprise deployment | Not ready | MFA, SSO, SCIM, audit exports, data retention, and admin controls need closure. |
| Solo lawyer paid beta | Possible only with limits | Must cap AI/case refresh usage and keep provider-heavy features gated. |
| Autonomous legal agent workflows | Not ready | Agent identity, approvals, audit trail, and evaluation gates are absent. |

## Severity Legend

- P0: Do not scale paid production until resolved.
- P1: Required for credible paid product readiness, enterprise adoption, or operational safety.
- P2: Important for expansion, support reduction, and product completeness.
- P3: Strategic or later-stage improvements.

## What Is Already Implemented And Should Not Be Reopened Without Evidence

This analysis should not pretend nothing exists. The following foundations are real and should be built upon:

- Billing catalog, plans, add-ons, checkout sessions, payment orders, credit ledger, usage attribution, rollups, profit rollups, enrollments, coupons, overage policy, manual invoices, tenant billing APIs, and platform admin APIs exist.
- Pine Labs integration modes exist: disabled, mock, and configured. Production currently remains disabled.
- Founder-only platform admin routes and UI exist for overview, billing, profit, provider events, integrations, costs, and margin simulations.
- Provider cost profile and margin simulation foundation exists.
- PRS/legal update ingestion and legal source records exist.
- Case tracking foundation exists and remains provider-gated.
- GBA enhancements are substantially implemented and documented: disposed matters, order compliance extraction, secure manual uploads, billing profiles, next-hearing provenance, cause-list rules, and guide updates.
- Gmail V1 exists for OAuth, import listing, metadata/snippet capture, attachment candidates, webhook receipt/deduplication, and audit/event recording.
- Google Calendar V1 exists for OAuth and CaseOps-to-Google sync for selected event types.
- Google Drive V1 exists for OAuth, token storage, recent file metadata listing, and UI panel.
- Connector registry/admin integration surfaces exist for tenant admins and founder.
- Provider operations foundation exists for failed/blocked/dead-letter jobs and replay/ignore/resolve actions.
- Several targeted backend and frontend test suites have passed in prior implementation slices.

The gap is not lack of effort. The gap is operational completeness, production proof, and hardening.

## Brutal Gap Heatmap

| Gap ID | Area | Severity | Hard Truth |
| --- | --- | --- | --- |
| BGA-001 | Pine Labs live payments | P0 | Online payments are coded but not production-activated or UAT-proven. |
| BGA-002 | Founder production billing signoff | P0 | The founder-only console exists, but final authenticated production smoke evidence is still pending. |
| BGA-003 | Provider cost calibration | P0 | Profitability is still theoretical until real court/case refresh, OCR, LLM, payment, SMS, WhatsApp, email, and storage costs are entered and reconciled. |
| BGA-004 | Plan profitability guardrails | P0 | Cost profiles exist, but the product still needs enforced plan-level stop-loss controls and margin alerts tested against real usage. |
| BGA-005 | Pine Labs settlement, refund, dispute ops | P0 | Checkout without settlement/refund/dispute reconciliation is not enough for production finance. |
| BGA-006 | Google Workspace production readiness | P1 | Google support exists but production OAuth, UAT, consent, scopes, and operational proof are incomplete. |
| BGA-007 | Gmail full mailbox | P1 | Gmail is a metadata/review-first workflow, not a full durable mailbox ingestion product. |
| BGA-008 | Google Drive content ingestion | P1 | Drive is metadata-only; it does not yet safely import, dedupe, version, classify, or commit file contents. |
| BGA-009 | Google Calendar two-way sync | P1 | CaseOps can push events, but robust Google-to-CaseOps import/conflict resolution is missing. |
| BGA-010 | Outlook/Graph parity | P1 | Outlook is not on par with Google; mailbox and robust two-way workflows are missing. |
| BGA-011 | Microsoft 365 mailbox ingestion | P1 | Corporate law firms often live in Microsoft 365; durable mailbox ingestion is absent. |
| BGA-012 | Connector observability | P1 | Registry surfaces exist, but live health, quotas, ownership, and failure explanations are shallow. |
| BGA-013 | MFA | P0 | Enterprise-grade account protection is not implemented end to end. |
| BGA-014 | SSO/OIDC/SAML/SCIM | P1 | Corporate GC and larger law firms will require SSO and lifecycle management. |
| BGA-015 | Step-up authorization | P1 | High-risk actions need re-auth or MFA step-up, especially billing/admin/export/payment actions. |
| BGA-016 | Agent identity and Grantex | P1 | Autonomous or delegated agent execution must not ship without authority boundaries and audit. |
| BGA-017 | External notification delivery | P1 | Durable in-app notifications exist, but external email/SMS/WhatsApp digests are incomplete. |
| BGA-018 | Notification preference center | P1 | Users need clear control over legal updates, hearing reminders, billing alerts, and provider failures. |
| BGA-019 | AI evaluation release gate | P1 | AI workflows need enforced quality gates, not just ad hoc tests. |
| BGA-020 | AI audit and policy controls | P1 | Tenant admins need stronger visibility and controls for AI usage, prompts, model classes, retention, and exports. |
| BGA-021 | Matter RAG and embeddings | P1 | Deep matter intelligence must be verified across attachment ingestion, search, citations, and tenant isolation. |
| BGA-022 | Temporal/durable workflow migration | P1 | Important workflows still rely on custom polling or synchronous flows. |
| BGA-023 | Observability | P1 | OpenTelemetry, structured logs, correlation IDs, and tenant-safe production diagnosis need hardening. |
| BGA-024 | Backup and restore drills | P1 | Backups are not the same as proven restore drills. |
| BGA-025 | Staging and release gates | P1 | Production deploys need stronger staging, branch protection, migration rehearsal, and rollback proof. |
| BGA-026 | Secret/config governance | P1 | Environment/config mapping, secret rotation, and operational checklists need to be complete before provider activation. |
| BGA-027 | Court/provider coverage | P1 | Court automation remains provider-gated with limited verified coverage and unknown live economics. |
| BGA-028 | GBA client UAT evidence | P1 | Representative GBA matters, PDF layouts, court lists, and field-level acceptance still need real validation. |
| BGA-029 | Jurisdiction expansion | P2 | Tamil Nadu, Gujarat, and broader jurisdiction support need operational proof and source adapters. |
| BGA-030 | Document ingestion depth | P2 | Broader parsers, OCR quality, structural extraction, and review queues need production maturity. |
| BGA-031 | Generic tasks/deadlines/obligations | P2 | Court-order compliance exists, but generic obligation/task lifecycle remains incomplete. |
| BGA-032 | Pagination and performance | P2 | Several API lists still need standardized pagination and performance tests at scale. |
| BGA-033 | OpenAPI generated client adoption | P2 | Generated types exist but the frontend still appears to retain manual endpoint bindings. |
| BGA-034 | Tenant admin controls | P2 | Branding, profile, timezone, retention, export, deletion, and workspace settings need a complete admin UI. |
| BGA-035 | Accounting integrations | P2 | Tally, Zoho Books, QuickBooks, settlement exports, and accountant workflows are not integrated. |
| BGA-036 | E-sign and DMS integrations | P3 | SharePoint/OneDrive DMS, e-sign, and Word add-in are not present. |
| BGA-037 | Public docs hub | P3 | Public guide exists, but a full docs route/versioned documentation center is not implemented. |
| BGA-038 | Enterprise deployment options | P3 | Dedicated tenant, VPC, data residency, customer-managed keys, and private deployment remain deferred. |
| BGA-039 | End-to-end UAT suite | P1 | There is no single complete PRD-to-product UAT pass covering every promised workflow. |
| BGA-040 | Accessibility | P2 | Axe/accessibility coverage is not proven across new admin and matter workflows. |
| BGA-041 | Tenant isolation hardening | P1 | More negative tests are needed for docs, signed URLs, search, audit logs, embeddings, provider operations, and exports. |
| BGA-042 | Authorization matrix | P1 | Role/capability tests need broader coverage across every mutating route and export route. |

## P0 Gap Details

### BGA-001: Pine Labs Live Payments Are Not Ready

Severity: P0

Current reality:

- Code supports disabled, mock, and configured Pine Labs modes.
- Production is intentionally disabled.
- No real Pine Labs live transaction has been executed.
- UAT credentials, webhook secret, registered webhook URL, endpoint paths, schemas, event samples, product enablement, MDR, settlement details, chargeback details, and refund details are still not fully supplied and proven.

Business risk:

- A user can be shown pricing and checkout intent, but production money movement cannot be safely activated.
- Incorrect webhook verification, order state mapping, settlement handling, or refund handling can create legal, accounting, and customer trust issues.
- Failed payment activation can block onboarding at the most sensitive point in the funnel.

Requirements:

1. Obtain Pine Labs UAT merchant ID, access credentials, webhook secret, endpoint base URLs, hosted checkout docs, payment link docs, subscription docs, refund docs, settlement docs, chargeback docs, and UPI AutoPay docs.
2. Register UAT webhook URL and capture signed webhook proof.
3. Implement or verify exact request/response schemas from Pine Labs docs, not assumptions.
4. Support payment success, failure, pending, cancellation, duplicate webhook, replayed webhook, tampered webhook, stale webhook, timeout, and manual reconciliation.
5. Support settlement report ingestion and reconciliation to payment orders.
6. Support refund and dispute state recording without publishing a refund policy in product copy unless separately approved.
7. Keep all provider secrets server-side only.
8. Keep production disabled until UAT evidence is attached.

Acceptance criteria:

- UAT checkout success creates exactly one subscription activation or credit top-up.
- Duplicate success webhook is idempotent.
- Tampered webhook is rejected and audited.
- Failed/pending/cancelled payment leaves tenant state unchanged or clearly pending.
- Settlement report can be imported and matched to orders.
- Refund/dispute events can be stored and shown to founder-only console.
- Tenant invoice/payment screens show customer-safe status without exposing internal provider details.
- Founder console shows provider status, settlement status, fees, tax amounts, and reconciliation exceptions.

Required tests:

- Backend unit tests for Pine Labs signature verification and idempotency.
- Backend integration tests for success/failure/pending/cancelled/refund/dispute/settlement flows using UAT-shaped fixtures.
- Frontend tests for checkout disabled, pending, success, failure, and retry screens.
- Founder-only platform admin tests for payment event visibility and tenant leakage.
- Manual UAT evidence with screenshots, request IDs, provider event IDs, and settlement sample.

Exit gate:

- Founder explicitly approves production Pine Labs activation after UAT evidence review.

### BGA-002: Founder Production Billing Signoff Is Still Pending

Severity: P0

Current reality:

- Founder-only console exists.
- Platform admin overview, profit, integrations, costs, and billing surfaces exist.
- Unauthenticated access correctly returns 401 in smoke checks.
- Authenticated founder production smoke has not been fully evidenced in the current environment.

Business risk:

- The founder may not be able to see the exact data needed during live customer onboarding.
- Broken founder-only access can make billing, margin, and provider incident response blind.
- Over-permissive access could expose sensitive profit or internal cost data.

Requirements:

1. Founder login as the configured production super-admin email must be tested.
2. Founder must access:
   - `/app/platform-admin`
   - `/app/platform-admin/profit`
   - `/app/platform-admin/costs`
   - `/app/platform-admin/integrations`
   - provider events and margin alerts.
3. Non-founder tenant admin must receive 403 for platform-admin APIs and pages.
4. Founder must be able to export revenue, usage, provider event, and profit data.
5. Tenant-facing reports must not expose internal cost, provider fee, margin, or profit fields.

Acceptance criteria:

- Founder production signoff runbook contains timestamped evidence for every route/API.
- Tenant admin negative tests pass in production-safe smoke.
- Export/download audit events are recorded.
- No internal cost or profit field is visible in tenant APIs, UI, exports, or browser page data.

Required tests:

- Production-safe smoke helper with founder token/session support.
- Backend route tests for founder/non-founder access.
- Frontend tests for navigation visibility and denied state.
- Leakage scan for tenant-facing payloads.

Exit gate:

- Founder signs production billing signoff as complete.

### BGA-003: Provider Cost Calibration Is Incomplete

Severity: P0

Current reality:

- Provider cost profile and margin simulation foundation exists.
- Billing profit calculations can use configured provider costs.
- Fallback defaults exist, including a case-refresh guardrail.
- Real provider costs for court/case refresh are unknown.

Business risk:

- Pricing plans can still lose money if actual provider refresh, OCR, LLM, SMS, WhatsApp, email, payment gateway, storage, or support costs exceed assumptions.
- Law firms with heavy case tracking or AI usage can become negative-margin customers.
- Founder will not know which customers are structurally unprofitable until after cost leakage happens.

Requirements:

1. Create founder-only cost profiles for:
   - LLM input tokens
   - LLM output tokens
   - embeddings
   - OCR per page
   - storage per GB-month
   - bandwidth/export
   - case refresh per case
   - court search
   - legal update source ingestion
   - email delivery
   - SMS delivery
   - WhatsApp delivery
   - payment gateway percentage fee
   - payment gateway fixed fee
   - chargeback/dispute fee
   - refund fee if applicable
   - support cost allocation
2. Support effective dates and version history for every cost profile.
3. Require a cost profile before enabling live provider-heavy features.
4. Simulate margins for every plan using low, expected, and abuse-heavy usage patterns.
5. Alert founder when projected or actual margin drops below threshold.
6. Enforce hard usage limits, soft limits, top-up requirements, or throttling before a plan becomes loss-making.

Acceptance criteria:

- Founder can enter real provider costs and immediately re-run plan margin simulation.
- Each plan shows expected gross margin after GST/payment/provider/LLM/OCR/case-refresh assumptions.
- Simulation includes at least three customer archetypes:
  - Solo light user
  - Litigation-heavy small law office
  - Large firm/corporate GC heavy case refresh and AI user
- Tenant overages cannot silently continue when credits are exhausted unless policy explicitly allows it.
- Internal costs are founder-only and never tenant-visible.

Required tests:

- Unit tests for cost profile versioning and effective-date selection.
- Margin simulation tests for profitable, low-margin, and loss-making scenarios.
- Tenant leakage tests.
- Usage limit and top-up enforcement tests.

Exit gate:

- Founder confirms every published plan remains profitable under expected and heavy usage assumptions.

### BGA-004: Plan Profitability Guardrails Need Enforcement

Severity: P0

Current reality:

- Pricing plan surfaces exist.
- Usage/spend and credit ledger flows exist.
- Overage policies exist.
- Add-on purchases exist.
- Real hard-stop behavior under heavy usage needs stronger proof.

Business risk:

- A customer can consume more AI/case-tracking/provider resources than their subscription covers.
- Manual monitoring will not scale.
- Customers may become angry if throttling is unclear or too late.

Requirements:

1. Every billable capability must map to a usage counter and cost bucket.
2. Every plan must define:
   - included credits
   - hard limits
   - soft warning thresholds
   - top-up eligibility
   - overage permission
   - provider-disabled fallback behavior
3. Tenant admins must see usage and remaining credits before hitting hard stops.
4. End users must see friendly disabled/limit states.
5. Founder must see projected monthly burn by tenant and plan.
6. Auto-throttle must be fail-closed for expensive provider actions.

Acceptance criteria:

- Case refresh, AI recommendations, document OCR, legal update watches, external notifications, and storage all generate usage records.
- Tenant-facing usage reports explain spend categories without exposing internal cost or profit.
- Additional credit purchase flow works in mock/Pine UAT mode.
- Hard limits prevent unbounded consumption.
- Founder console flags negative-margin tenants.

Required tests:

- Usage attribution tests for every billable feature.
- Top-up purchase tests.
- Exhausted-credit tests.
- Founder profit report tests.
- Tenant report leakage tests.

Exit gate:

- No paid plan can run below founder-defined minimum gross margin without an explicit founder override.

### BGA-005: Refund, Settlement, Dispute, And TDS Operations Are Immature

Severity: P0

Current reality:

- GST details are known: `09AANCM5923C1ZD`.
- The product should stay silent on refund policy text unless approved.
- TDS handling must follow Indian law.
- Code has billing records, invoices, and payment entities, but live financial operations are not proven.

Business risk:

- Incorrect settlement, refund, TDS, or GST handling creates accounting and compliance risk.
- Customers may request invoice downloads, payment status, or credit notes before operations can support them.
- Back-office reports may not match bank settlements.

Requirements:

1. Capture GSTIN, place of supply, legal entity name, billing address, invoice number, invoice date, HSN/SAC, taxable value, CGST/SGST/IGST, total, payment status, and credit note references.
2. Let users download invoices, statements, payment exports, credit ledger exports, and usage/spend reports.
3. Founder console must show:
   - gross revenue
   - GST collected
   - net revenue
   - payment gateway fees
   - provider costs
   - LLM costs
   - gross profit
   - gross margin
   - outstanding failed payments
   - settlement mismatches
   - credits issued
   - top-ups purchased
4. TDS fields must support customer-declared deductions and back-office reconciliation per Indian law.
5. Do not publish refund policy wording in product copy until approved separately.
6. Add credit note/refund recording and settlement reconciliation.

Acceptance criteria:

- Tenant can self-download invoices, statements, usage exports, credit ledger exports, and payment exports.
- Founder can export accounting-ready reports.
- TDS amount can be recorded and reconciled without breaking invoice totals.
- Refund/credit note entities are stored and visible to founder.
- Settlement import identifies matched, unmatched, duplicate, fee-mismatched, and tax-mismatched rows.

Required tests:

- Invoice rendering tests.
- GST split tests for intra-state and inter-state scenarios.
- TDS recording tests.
- Settlement import/reconciliation tests.
- Credit note/refund record tests.
- Tenant/founder access boundary tests.

Exit gate:

- Accountant/founder approves sample invoices and settlement exports.

## P1 Gap Details

### BGA-006: Google Workspace Production Readiness Is Incomplete

Severity: P1

Current reality:

- Gmail, Google Calendar, and Drive foundations exist.
- Tenant Google Workspace OAuth configuration exists.
- Production Google credential and UAT signoff status is not complete.

Business risk:

- Customers may assume Google Workspace integration is production-grade.
- OAuth consent, scopes, verification, and domain restrictions can block adoption.
- Misconfigured scopes can create privacy and security problems.

Requirements:

1. Finalize Google Cloud OAuth app configuration for production.
2. Confirm authorized redirect URIs for web and API domains.
3. Verify scopes for Gmail, Calendar, and Drive are minimum necessary.
4. Document consent screen status and domain verification.
5. Add tenant admin health status for configured, connected, stale token, revoked token, insufficient scope, provider error, and rate-limited states.
6. Add UAT checklist for Gmail import, Calendar export, Drive metadata, token revoke, and failure recovery.

Acceptance criteria:

- Google OAuth can be completed in production by an authorized tenant admin/user.
- Revoked/expired tokens degrade gracefully.
- Provider errors appear in tenant admin integrations and platform admin integrations.
- Scopes are documented and approved.

Required tests:

- OAuth callback tests.
- Token refresh/revoke tests.
- Scope missing tests.
- Tenant isolation tests.
- Manual UAT evidence.

### BGA-007: Gmail Is Not Yet A Full Mailbox Product

Severity: P1

Current reality:

- Gmail V1 supports metadata/snippets, import candidates, attachment candidates, webhook receipt/deduplication, audit events, and review-first workflows.
- It does not store raw bodies by default.
- It does not automatically mutate matters/documents without review.

Business risk:

- Lawyers expect email integration to find correspondence, attachments, threads, and matter context reliably.
- Metadata-only support is useful but may disappoint users expecting a full mailbox.
- Automatic import without safe review could create privacy and matter-misfiling risk.

Requirements:

1. Support advanced Gmail search and label filtering.
2. Add thread-level view with matter candidate matching.
3. Add safe body retrieval only when explicitly approved by tenant policy.
4. Add attachment download/import review queue.
5. Add duplicate detection by message ID, thread ID, attachment hash, and matter candidate.
6. Add manual assign-to-matter, ignore, archive, and bulk actions.
7. Add autonomous polling only after cost/security controls are in place.
8. Add retention policy for imported message metadata, bodies, and attachments.

Acceptance criteria:

- User can connect Gmail and see import candidates grouped by thread.
- User can review and import attachments to a matter.
- No raw body is stored unless tenant policy permits it.
- Duplicate imports are prevented.
- Admin can see connector health and last sync.

Required tests:

- Gmail search/import tests.
- Attachment candidate tests.
- Duplicate tests.
- Raw body policy tests.
- UI tests for review workflow.

### BGA-008: Google Drive Is Metadata-Only

Severity: P1

Current reality:

- Drive OAuth and recent metadata listing exist.
- File content ingestion, folder mapping, webhook/polling, dedupe, version tracking, and review-to-commit are missing.

Business risk:

- Users may expect Drive integration to import pleadings, orders, invoices, and client documents.
- Pulling content without safe review can expose sensitive documents or create duplicates.
- Metadata-only is not enough for a document-centric legal workflow.

Requirements:

1. Tenant admin configures allowed folders or shared drives.
2. User can browse eligible Drive files.
3. User can preview metadata and choose import destination matter.
4. File content is fetched only after explicit review action.
5. Imported content passes through malware scanning, OCR/extraction, dedupe, and audit.
6. Version changes are detected and shown.
7. Webhook/polling support is added only with durable provider events.

Acceptance criteria:

- Drive file can be imported to a matter through review queue.
- Duplicate file import is prevented.
- File version changes are recorded.
- Imported file appears in matter documents with source provenance.
- Tenant admin can disable Drive content import.

Required tests:

- Folder authorization tests.
- File import tests.
- Malware/OCR pipeline tests.
- Dedupe/version tests.
- Tenant isolation tests.

### BGA-009: Google Calendar Needs Two-Way Sync And Conflict Handling

Severity: P1

Current reality:

- CaseOps can sync selected hearing/task/deadline events to Google Calendar.
- Provider event cleanup exists for cancelled hearing.
- Google-to-CaseOps import and robust conflict handling are missing.

Business risk:

- Lawyers often update calendars directly in Google.
- One-way sync can create stale hearings, duplicate events, or missed rescheduling.
- Deadlines and hearings are legally sensitive.

Requirements:

1. Add Google-to-CaseOps import for eligible events.
2. Add event mapping between Google event IDs and CaseOps hearing/task/deadline IDs.
3. Add conflict policy:
   - CaseOps wins
   - Google wins
   - require manual review
4. Add per-event provenance and last-synced timestamp.
5. Add webhook/watch or durable polling.
6. Add deletion/cancellation handling both directions.
7. Add manual lock support so user-approved dates are not overwritten.

Acceptance criteria:

- Google-created court event can be reviewed and imported into CaseOps.
- Google-updated event creates a suggestion or update based on policy.
- Locked CaseOps hearing is not overwritten.
- Deletion/cancellation is handled safely.
- Sync failures show in provider operations.

Required tests:

- Import tests.
- Conflict tests.
- Locked hearing tests.
- Delete/cancel tests.
- Provider retry/dead-letter tests.

### BGA-010: Outlook/Graph Parity Is Missing

Severity: P1

Current reality:

- Outlook calendar support exists only partially.
- Robust Microsoft Graph two-way sync, mailbox ingestion, change notifications, and task/deadline sync are not complete.

Business risk:

- Many Indian corporate legal departments and larger law firms use Microsoft 365.
- Google-only or Google-better-than-Microsoft functionality will block enterprise adoption.

Requirements:

1. Add Microsoft 365 admin/user OAuth for Mail, Calendar, and optionally Files.
2. Implement Graph calendar export/import parity with Google Calendar.
3. Implement Graph change notifications with durable event processing.
4. Implement mailbox metadata/thread/attachment candidate workflow.
5. Add token refresh/revoke and insufficient-scope handling.
6. Surface Microsoft connector health in tenant and founder dashboards.

Acceptance criteria:

- Outlook and Gmail have equivalent review-first mailbox workflows.
- Outlook Calendar and Google Calendar have equivalent two-way sync controls.
- Graph webhook/polling failures appear in provider operations.
- Tenant admin can enable/disable Microsoft connector.

Required tests:

- Graph OAuth tests.
- Calendar export/import tests.
- Mail metadata/attachment tests.
- Webhook signature/validation tests if applicable.
- Tenant isolation tests.

### BGA-011: Microsoft 365 Mailbox Ingestion Is Absent

Severity: P1

Current reality:

- Durable mailbox foundation is mainly Gmail-oriented.
- Microsoft 365 mailbox ingestion is not implemented.

Business risk:

- Corporate GC customers will frequently ask for Outlook email import before Gmail.
- Matter correspondence remains outside the system.

Requirements:

1. Create provider-neutral mailbox domain model.
2. Add Microsoft Graph message listing/search.
3. Add metadata/snippet capture.
4. Add attachment candidate capture.
5. Add review-to-import workflow.
6. Add per-provider policy for body storage and attachment import.
7. Add matter matching and dedupe.

Acceptance criteria:

- Outlook mailbox works through the same UI concepts as Gmail.
- Microsoft-specific fields are abstracted behind provider records.
- No tenant data leakage across providers.

Required tests:

- Provider-neutral mailbox tests.
- Microsoft message fixture tests.
- UI provider switch tests.
- Attachment import tests.

### BGA-012: Connector Registry Needs Live Operational Depth

Severity: P1

Current reality:

- Tenant and founder connector registry APIs/UI exist.
- They show integration status and config names.
- Live health probes, quota status, connection ownership, and provider-backed checks need more depth.

Business risk:

- Admins may see a connector as "configured" when it is actually expired, rate-limited, blocked, or missing permissions.
- Support cannot diagnose failures quickly.

Requirements:

1. Add standardized connector states:
   - not configured
   - configured
   - connected
   - degraded
   - rate limited
   - token expired
   - scope missing
   - provider disabled
   - blocked by policy
2. Add last successful action, last failed action, last provider error category, and next retry time.
3. Add connection owner and consent actor.
4. Add quota/rate-limit fields when provider supports them.
5. Add founder-only full detail and tenant-safe redacted detail.
6. Add health probe jobs that do not mutate external data.

Acceptance criteria:

- Tenant admin can understand why a connector is not working.
- Founder can diagnose provider failure without seeing secrets.
- Connector health is auditable.

Required tests:

- State mapping tests.
- Redaction tests.
- Health probe tests.
- UI empty/degraded/error-state tests.

### BGA-013: MFA Is Not Implemented End To End

Severity: P0

Current reality:

- Data flags such as `mfa_required` or `mfa_enforced_at` may exist.
- Actual enrollment, login challenge, recovery, enforcement, and step-up flows are not complete.

Business risk:

- Legal data, billing access, exports, and provider tokens are high-value targets.
- Larger firms and corporate GCs will reject the product without MFA.
- Founder-only platform admin access should not rely on password-only authentication.

Requirements:

1. Add MFA methods:
   - TOTP authenticator app
   - recovery codes
   - email OTP as fallback if approved
   - WebAuthn/passkey as later enhancement
2. Add enrollment flow.
3. Add login challenge flow.
4. Add recovery code generation, download, use, and rotation.
5. Add tenant admin enforcement:
   - optional
   - required for admins
   - required for all users
   - grace period for existing users
6. Add founder/platform-admin mandatory MFA.
7. Add step-up prompt for high-risk actions.
8. Add audit events for enrollment, challenge success/failure, recovery use, reset, and enforcement changes.

Acceptance criteria:

- Existing users can be forced into MFA enrollment on next login.
- Founder cannot access platform-admin without MFA once enforced.
- Tenant admin can enforce MFA later even for already existing users.
- Recovery works without bypassing audit.
- Disabled users cannot pass MFA challenge.

Required tests:

- TOTP enrollment tests.
- Login challenge tests.
- Recovery code tests.
- Tenant enforcement tests.
- Founder platform-admin MFA tests.
- Negative tests for brute-force/rate-limit.

### BGA-014: SSO, OIDC, SAML, And SCIM Are Missing

Severity: P1

Current reality:

- No full OIDC/SAML provider config, SSO login, JIT provisioning, group mapping, SSO-only enforcement, or SCIM lifecycle management is implemented.

Business risk:

- Corporate GCs and larger law firms often require SSO and centralized user lifecycle.
- Manual user management creates security and admin overhead.

Requirements:

1. Add tenant SSO provider configuration:
   - OIDC
   - SAML 2.0
2. Support JIT user provisioning.
3. Support domain verification.
4. Support group-to-role mapping.
5. Support SSO-only enforcement with emergency break-glass founder/admin path.
6. Support SCIM user provisioning/deprovisioning as a later phase.
7. Add metadata download/upload flows.
8. Add audit events.

Acceptance criteria:

- Tenant admin can configure SSO in test mode before enforcing.
- Users can log in with SSO.
- Group mapping grants correct roles.
- Deprovisioned users lose access.
- SSO-only lockout has a safe recovery path.

Required tests:

- OIDC mocked provider tests.
- SAML fixture tests.
- JIT provisioning tests.
- Group mapping tests.
- SSO enforcement tests.

### BGA-015: Step-Up Authorization Is Missing

Severity: P1

Current reality:

- Sensitive actions are role/capability guarded.
- Re-authentication or MFA step-up for high-risk actions is not clearly implemented.

Business risk:

- A stolen active session can export data, change billing, modify connectors, or access platform admin functions.

Requirements:

1. Define high-risk actions:
   - platform-admin access
   - cost profile edits
   - payment activation
   - invoice/usage export
   - connector OAuth changes
   - API key/secret changes
   - tenant role changes
   - bulk document export
   - case deletion/disposal
2. Require recent auth or MFA step-up.
3. Add step-up session timestamp and expiration.
4. Audit challenge and action completion.

Acceptance criteria:

- Sensitive actions fail with step-up-required response.
- User completes step-up and can retry.
- Step-up expires after configured time.

Required tests:

- Backend step-up middleware tests.
- Frontend step-up modal/page tests.
- Audit tests.

### BGA-016: Agent Identity And Grantex Are Missing

Severity: P1

Current reality:

- No complete AgentGrant, AgentExecution, AgentToolCall, HumanApproval, or authority-bounded agent framework exists.

Business risk:

- AI agents that act without defined authority can mutate legal matters, send emails, file documents, or create recommendations without accountability.
- Legal workflows require traceable responsibility.

Requirements:

1. Add agent identity model.
2. Add agent grant model:
   - tenant
   - actor
   - scope
   - allowed tools
   - denied tools
   - expiry
   - budget
   - approval requirements
3. Add execution ledger.
4. Add tool-call ledger.
5. Add human approval queue.
6. Add policy engine for allowed actions.
7. Add revocation.
8. Add audit/export.

Acceptance criteria:

- Agent cannot act outside grant.
- High-risk tool calls require approval.
- Every agent action is attributable and replayable.
- Revoked grant blocks further execution.

Required tests:

- Grant enforcement tests.
- Approval workflow tests.
- Revocation tests.
- Audit export tests.

### BGA-017: External Notification Delivery Is Incomplete

Severity: P1

Current reality:

- Durable in-app notification intents exist.
- External email/SMS/WhatsApp flows are partial, disabled, or fail-closed.
- Billing and hearing emails may exist in limited provider-configured scenarios, but unified external notification delivery is incomplete.

Business risk:

- Lawyers rely on reminders and digests.
- Missed hearing or deadline notifications create serious trust and liability concerns.
- SMS/WhatsApp costs can become material if not metered.

Requirements:

1. Add notification preference center:
   - in-app
   - email
   - SMS
   - WhatsApp
   - digest frequency
   - quiet hours
   - categories
2. Add provider adapters:
   - SendGrid or approved email provider
   - SMS provider
   - WhatsApp Business provider
3. Add Indian DLT/template governance where applicable.
4. Add per-message cost attribution.
5. Add delivery status:
   - queued
   - sent
   - delivered
   - failed
   - bounced
   - suppressed
6. Add retry and dead-letter handling.
7. Add founder-only provider event monitoring.

Acceptance criteria:

- User can choose notification channels per category.
- Tenant admin can configure defaults.
- External delivery is not attempted if provider is disabled or policy blocks it.
- Delivery costs count toward usage/profit model.

Required tests:

- Preference tests.
- Adapter tests with mocked provider responses.
- Cost attribution tests.
- Fail-closed tests.
- UI tests.

### BGA-018: Notification Preference Center Is Missing

Severity: P1

Current reality:

- There is no complete user-facing and tenant-admin notification preference center for all categories.

Business risk:

- Users may get too many alerts or miss important alerts.
- Legal update, hearing, compliance, billing, and provider alerts need different rules.

Requirements:

1. User preferences:
   - hearing reminders
   - deadline reminders
   - order compliance tasks
   - legal updates
   - billing alerts
   - provider connection alerts
   - daily/weekly digest
2. Tenant defaults.
3. Admin override for mandatory categories.
4. Channel-specific enablement.
5. Audit changes.

Acceptance criteria:

- User can update preferences.
- Tenant admin can set defaults.
- Mandatory alerts cannot be disabled where required.
- Preferences drive actual delivery decisions.

### BGA-019: AI Evaluation Release Gate Is Not Enforced

Severity: P1

Current reality:

- Evaluation foundation exists in parts.
- There is no complete admin UI and CI/release gate across every AI workflow.

Business risk:

- AI recommendation, legal update summary, order extraction, drafting, and matter intelligence changes can regress silently.
- Legal AI quality issues are high-trust failures.

Requirements:

1. Define evaluation suites for:
   - recommendations
   - order compliance extraction
   - legal update summaries
   - matter intelligence
   - drafting
   - search/RAG citations
   - hearing suggestions
2. Add golden datasets with tenant-safe synthetic and approved real examples.
3. Add scoring:
   - factual accuracy
   - citation support
   - omission risk
   - hallucination risk
   - formatting
   - policy compliance
4. Add admin UI for evaluation runs.
5. Add CI gate for high-risk prompt/model changes.
6. Add founder approval workflow for model upgrades.

Acceptance criteria:

- Every AI workflow has at least one baseline evaluation suite.
- CI blocks if quality drops beyond threshold.
- Founder/admin can compare model versions.
- Evaluation results are auditable.

Required tests:

- Evaluation runner tests.
- CI threshold tests.
- UI tests.
- Regression fixture tests.

### BGA-020: AI Audit And Policy Controls Need More Depth

Severity: P1

Current reality:

- Tenant AI policy service exists.
- Recommendation allow-lists and purpose gates have been improved.
- Admin-visible prompt/tool-call audit and per-feature policy control remain incomplete.

Business risk:

- Customers need to know what data is sent to AI providers and why.
- Admins need to restrict model classes, retention, and feature use.

Requirements:

1. Tenant AI policy settings:
   - allowed model providers
   - allowed model tiers
   - feature allow-list
   - data retention preference
   - citation requirement
   - export restriction
   - human review requirement
2. Prompt/request audit:
   - purpose
   - feature
   - user
   - matter
   - token counts
   - model
   - redacted prompt metadata
   - output metadata
3. Tenant admin AI usage report.
4. Founder-only cost/profit report.

Acceptance criteria:

- Tenant admin can disable high-risk AI features.
- AI usage report shows usage without exposing internal costs.
- Founder sees costs and margins.
- Policy blocks are enforceable server-side.

### BGA-021: Matter RAG And Embeddings Need Production Proof

Severity: P1

Current reality:

- Matter intelligence context exists in recommendation work.
- It is not yet proven that all document ingestion, embeddings, tenant overlays, citations, and vector isolation are production-grade.

Business risk:

- Poor retrieval causes weak or hallucinated legal recommendations.
- Cross-tenant vector leakage would be catastrophic.

Requirements:

1. Ensure every eligible matter document can be extracted, chunked, embedded, indexed, and reindexed.
2. Store citation provenance with document, page, snippet, and confidence.
3. Add tenant and matter isolation at storage and query layers.
4. Add deletion/reindex workflows.
5. Add vector integration tests against production-like Postgres/vector backend.
6. Add retrieval quality evaluations.

Acceptance criteria:

- Recommendation and search outputs cite matter documents when used.
- Deleted documents are removed from retrieval.
- Cross-tenant searches return zero results.
- Retrieval quality meets baseline.

### BGA-022: Temporal And Durable Workflow Migration Is Incomplete

Severity: P1

Current reality:

- Provider operations foundation exists.
- Some notification and sync probes exist.
- Many important workflows still rely on custom polling, synchronous execution, or ad hoc scripts.

Business risk:

- Provider failures, retries, duplicate events, and long-running tasks become hard to reason about.
- Manual scripts do not scale.

Requirements:

1. Move durable workflows to Temporal or approved workflow engine:
   - document ingestion
   - OCR/extraction
   - case tracking poll
   - legal update sync
   - Gmail/Outlook mailbox poll
   - Drive sync
   - Calendar sync
   - notification delivery
   - payment reconciliation
   - AI evaluation batch runs
2. Add retry policies, idempotency keys, dead-letter, replay, and audit.
3. Surface workflow status in provider operations.

Acceptance criteria:

- Each durable workflow has visible run status.
- Duplicate provider events do not duplicate side effects.
- Dead-letter replay is safe and audited.

### BGA-023: Observability Is Not Strong Enough

Severity: P1

Current reality:

- Logs and tests exist, but OpenTelemetry, structured logs, correlation IDs, and tenant-safe diagnostics need hardening.

Business risk:

- Production issues will be slow to diagnose.
- Provider failures and tenant-specific problems may require unsafe manual investigation.

Requirements:

1. Add OpenTelemetry traces for API requests, provider calls, workflow runs, database queries, and AI calls.
2. Add correlation/request IDs across frontend, API, worker, and provider events.
3. Add structured logs with tenant ID, user ID, route, action, status, and redacted error category.
4. Add dashboards:
   - API latency/errors
   - provider failures
   - payment failures
   - AI token burn
   - case refresh backlog
   - notification delivery failures
5. Add alerting thresholds.

Acceptance criteria:

- Founder/admin can identify top failing provider, tenant, and route.
- Logs do not contain secrets, raw legal content, payment secrets, or tokens.
- Every provider event can be correlated to a user-visible action where applicable.

### BGA-024: Backup And Restore Drills Need Proof

Severity: P1

Current reality:

- Backups have been taken before production migrations.
- Full restore drill evidence is not clearly complete.

Business risk:

- A backup that has never been restored is an assumption, not a recovery plan.

Requirements:

1. Document RPO/RTO targets.
2. Run restore drill to isolated environment.
3. Verify app can boot against restored DB.
4. Verify critical flows after restore:
   - login
   - tenant data
   - invoices
   - matters
   - documents metadata
   - audit logs
5. Document rollback procedure for failed migrations.

Acceptance criteria:

- Restore drill evidence exists with timestamps.
- Recovery runbook can be executed by a second operator.
- Migration rollback is tested where possible.

### BGA-025: Staging And Release Gates Need Hardening

Severity: P1

Current reality:

- CI and deployment workflows exist.
- Production deploys have succeeded.
- Some full backend test runs exceed local shell budgets.
- Staging, branch protection, migration rehearsal, and rollback gates need stronger institutionalization.

Business risk:

- Production can become the first place where provider/payment/migration issues are discovered.

Requirements:

1. Add staging environment with production-like config and disabled real payments.
2. Run migrations on staging before prod.
3. Require CI green and security scans before merge.
4. Require migration dry run for DB changes.
5. Require production deploy checklist.
6. Add rollback plan per deploy.
7. Split backend tests into stable shards so complete suite is practical.

Acceptance criteria:

- Every release has staging evidence.
- Full test suite or complete shard matrix passes in CI.
- Failed migration path is documented.

### BGA-026: Secret And Config Governance Needs Closure

Severity: P1

Current reality:

- Many provider integrations require secrets.
- Docs and runbooks exist, but complete secret mapping, rotation, and environment validation need closure.

Business risk:

- Misconfigured secrets can break payments, email, Google/Microsoft, AI, storage, or court providers.
- Exposed secrets can compromise legal data.

Requirements:

1. Maintain secret inventory:
   - name
   - environment
   - owner
   - provider
   - rotation schedule
   - required/optional
   - expected format
2. Add startup validation for required secrets per enabled feature.
3. Add redacted config diagnostics in founder console.
4. Add rotation runbooks.
5. Add secret scanning in CI.

Acceptance criteria:

- Enabled provider cannot start in half-configured unsafe state.
- Disabled provider has clear safe fallback.
- No secret value appears in logs or UI.

### BGA-027: Court And Provider Coverage Is Incomplete

Severity: P1

Current reality:

- Case tracking and legal update foundations exist.
- Case tracking is provider-gated and safely disabled without provider config.
- Real pan-India court/case refresh coverage and costs are not proven.

Business risk:

- Law firms will judge the product by court coverage.
- Case refresh failures directly reduce trust.
- Unknown refresh cost can destroy margins.

Requirements:

1. Define supported court/provider matrix:
   - court
   - bench
   - jurisdiction
   - lookup key
   - refresh frequency
   - source type
   - provider cost
   - reliability
   - legal/ToS constraints
2. Add provider health and coverage UI.
3. Add customer-visible disabled/degraded messaging.
4. Add cost-aware refresh throttling.
5. Add representative UAT cases.

Acceptance criteria:

- Founder can see provider coverage and cost per refresh.
- Tenant users see whether tracking is supported before relying on it.
- Refresh failures are retried and audited.

### BGA-028: GBA Client UAT Evidence Is Still Needed

Severity: P1

Current reality:

- GBA Law Office requirements were translated into PRD and implemented/documented in major parts.
- Public docs and guide were updated.
- Real GBA representative UAT artifacts are still required.

Business risk:

- A feature can be implemented but still fail the actual office workflow.
- PDF output, terminology, fields, and court-specific edge cases may not match user expectations.

Requirements:

1. Collect representative GBA matters:
   - active
   - disposed
   - civil
   - criminal
   - high court
   - district court
   - tribunal if applicable
2. Validate:
   - disposed workflow
   - order upload/OCR
   - compliance extraction
   - next hearing provenance
   - cause-list PDF
   - invoice PDF
   - GST/TDS fields
   - advocate/source fields
   - case number/CNR formats
3. Capture pass/fail evidence.
4. Convert failures into regression tests.

Acceptance criteria:

- GBA stakeholder signs off on representative workflows.
- Sample PDFs match required layout and terminology.
- Any non-supported court/source is documented clearly.

### BGA-029: Jurisdiction Expansion Is Not Operationally Complete

Severity: P2

Current reality:

- Some jurisdiction support exists or is feature-flagged.
- Broader state/court coverage is incomplete.

Business risk:

- Expansion into new firms will stall if their courts are unsupported.

Requirements:

1. Define priority jurisdictions.
2. Add court/bench/judge resolver service.
3. Add tenant-specific court/bench/judge admin CRUD.
4. Add judge profile aggregation if legally and operationally permitted.
5. Add source reliability scoring.

Acceptance criteria:

- Admin can configure court/bench metadata.
- Matter creation and case tracking use normalized court data.
- Unsupported courts are clearly labeled.

## P2 And P3 Product Completeness Gaps

### BGA-030: Document Ingestion Depth Is Incomplete

Severity: P2

Current reality:

- Manual uploads and OCR states exist.
- Broader parser support and structural legal extraction need deeper work.

Requirements:

1. Improve parser coverage for PDF, scanned PDF, DOCX, images, and email attachments.
2. Add OCR quality score and manual correction workflow.
3. Add structural extraction:
   - parties
   - dates
   - obligations
   - deadlines
   - court
   - bench
   - judge
   - citations
4. Add document classification.
5. Add review-before-commit for high-impact extracted data.

Acceptance criteria:

- Low-confidence extraction requires user review.
- Extracted fields have provenance.
- Corrections improve future display/search.

### BGA-031: Generic Tasks, Deadlines, And Obligations Need A Full Lifecycle

Severity: P2

Current reality:

- Court-order compliance extraction and reminders exist in some form.
- A generic task/deadline/obligation system across matter workflows remains incomplete.

Requirements:

1. Add unified task/deadline/obligation model.
2. Link to matter, order, document, hearing, invoice, legal update, and user.
3. Support assignee, watcher, status, due date, reminder policy, completion proof, and audit.
4. Support calendar sync.
5. Support digest notifications.

Acceptance criteria:

- A deadline from an uploaded order can become a tracked obligation.
- User can assign, complete, reopen, and audit it.
- Missed/overdue status is visible.

### BGA-032: Pagination And Performance Need Standardization

Severity: P2

Current reality:

- Some endpoints likely have pagination.
- Several older list endpoints still need standardization and scale testing.

Requirements:

1. Standardize pagination response shape.
2. Add pagination to:
   - authorities
   - outside counsel
   - matter sub-lists
   - time entries
   - invoices
   - recommendations
   - provider events
   - audit logs
3. Add indexes for common filters.
4. Add tests for large datasets.

Acceptance criteria:

- No major list endpoint returns unbounded results.
- UI supports next/previous or cursor navigation.
- Query performance is acceptable for large tenants.

### BGA-033: OpenAPI Generated Client Adoption Is Incomplete

Severity: P2

Current reality:

- Generated types may exist.
- Frontend endpoint bindings still appear partially manual.

Requirements:

1. Generate typed client from backend OpenAPI.
2. Replace manual endpoint definitions gradually.
3. Add CI check that OpenAPI schema is current.
4. Add backward-compatibility notes for API changes.

Acceptance criteria:

- New frontend API calls prefer generated types.
- Schema drift fails CI.

### BGA-034: Tenant Admin Controls Need Completion

Severity: P2

Current reality:

- Tenant admin billing, integrations, and some settings exist.
- Full workspace administration is incomplete.

Requirements:

1. Tenant profile:
   - legal name
   - GSTIN
   - billing address
   - timezone
   - logo/branding
   - default currency
2. Data controls:
   - retention
   - export
   - deletion requests
   - audit exports
3. Security controls:
   - MFA policy
   - SSO policy
   - role management
4. Provider controls:
   - connector enablement
   - AI policy
   - notification policy

Acceptance criteria:

- Tenant admin can manage core workspace settings without founder support.
- Sensitive changes are audited.

### BGA-035: Accounting Integrations Are Missing

Severity: P2

Current reality:

- In-app billing and invoice downloads exist.
- Tally, Zoho Books, QuickBooks, and accountant workflows are not integrated.

Requirements:

1. Add accounting export formats:
   - CSV
   - XLSX
   - JSON
2. Add Tally-compatible export if feasible.
3. Add Zoho Books/QuickBooks integration as optional later phase.
4. Add chart-of-account mapping.
5. Add GST/TDS reconciliation exports.

Acceptance criteria:

- Accountant can reconcile invoices, payments, TDS, GST, refunds, and settlements from exports.

### BGA-036: E-Sign, DMS, And Word Add-In Are Missing

Severity: P3

Requirements:

1. E-sign integration:
   - upload document
   - send for signature
   - status tracking
   - signed document return
2. DMS integration:
   - SharePoint/OneDrive
   - Google Drive content import
   - folder mapping
3. Word add-in:
   - matter context
   - template insertion
   - citation insertion
   - save back to matter

Acceptance criteria:

- Later-stage enterprise users can connect their document workflows without leaving CaseOps.

### BGA-037: Public Docs Hub Is Thin

Severity: P3

Current reality:

- Public guide and machine-readable docs exist.
- There is no full versioned docs route.

Requirements:

1. Add `/docs` hub.
2. Add versioned guides:
   - getting started
   - billing
   - privacy/security
   - connectors
   - legal updates
   - case tracking
   - AI usage
   - admin controls
3. Add changelog.
4. Add support/contact path.

Acceptance criteria:

- Prospects and customers can self-serve setup and usage information.

### BGA-038: Enterprise Deployment Options Are Deferred

Severity: P3

Requirements:

1. Define enterprise deployment tiers:
   - shared SaaS
   - dedicated tenant
   - customer-managed cloud
   - private VPC
2. Add data residency statement.
3. Add customer-managed key roadmap.
4. Add enterprise audit/export options.

Acceptance criteria:

- Corporate GC procurement questions can be answered with documented options.

## Cross-Cutting Testing And Compliance Gaps

### BGA-039: Complete End-To-End UAT Suite Is Missing

Severity: P1

Current reality:

- Many focused tests pass.
- There is no single evidence-backed pass covering every PRD scenario.

Requirements:

1. Build a PRD traceability matrix:
   - requirement
   - implementation file
   - API test
   - UI test
   - manual UAT evidence
   - production smoke evidence
2. Cover:
   - signup/login/password reset
   - MFA once implemented
   - tenant setup
   - matter lifecycle
   - document upload/OCR
   - order compliance
   - case tracking
   - legal updates
   - recommendations
   - billing/subscription/top-up
   - invoice/export
   - connector setup
   - Gmail/Google/Outlook/Drive workflows
   - admin reports
   - platform admin reports
   - provider failures
   - notification delivery
3. Add Playwright E2E tests for critical user journeys.

Acceptance criteria:

- Every PRD requirement maps to a test or explicit deferred status.
- Release cannot be called done without this matrix updated.

### BGA-040: Accessibility Coverage Is Not Proven

Severity: P2

Requirements:

1. Add axe checks for:
   - pricing
   - login/password reset
   - dashboard
   - matter workspace
   - billing
   - platform admin
   - provider operations
   - integrations
2. Fix keyboard navigation issues.
3. Fix color contrast issues.
4. Add focus states and labels.

Acceptance criteria:

- Critical flows pass automated accessibility checks.
- Forms and tables are keyboard usable.

### BGA-041: Tenant Isolation Hardening Needs Expansion

Severity: P1

Current reality:

- Tenant scoping exists in many places.
- More adversarial tests are needed.

Requirements:

1. Add negative tenant isolation tests for:
   - documents
   - signed URLs
   - search
   - embeddings
   - recommendations
   - billing exports
   - invoices
   - provider events
   - connector records
   - audit logs
   - notification intents
   - agent grants when implemented
2. Add platform-admin-only field leakage tests.
3. Add object-level authorization tests.

Acceptance criteria:

- A user from Tenant A cannot read, export, search, infer, or download Tenant B data.
- Tenant-facing APIs never expose founder-only cost/profit fields.

### BGA-042: Authorization Matrix Coverage Is Incomplete

Severity: P1

Requirements:

1. Define role/capability matrix:
   - founder platform admin
   - tenant owner
   - tenant admin
   - lawyer
   - clerk/paralegal
   - billing admin
   - read-only user
   - external counsel if applicable
2. Test every mutating route.
3. Test every export route.
4. Test every connector route.
5. Test every platform-admin route.

Acceptance criteria:

- CI includes authorization matrix tests.
- New routes must declare required capability.

## Specific Password Reset Verification Gap

The user previously identified password reset as a suspected gap. A targeted code search shows it is implemented, so this document must not incorrectly reopen it as missing product work. The remaining gap is production evidence and outbound email delivery confidence.

### BGA-043: Password Reset Exists, But Production Delivery Evidence Must Be Captured

Severity: P1

Current reality:

- Email-based password reset is implemented.
- Evidence in code includes:
  - frontend `/account/forgot-password`
  - frontend `/account/reset-password`
  - sign-in forgot-password link
  - backend `/api/auth/password-reset/start`
  - backend `/api/auth/password-reset/complete`
  - admin employee reset endpoint
  - single-use reset token service code
  - anti-enumeration behavior
  - tests for forgot-password, reset-password, token consumption, inactive users, atomic token use, audit events, and session revocation.
- The remaining question is whether production email delivery is configured, monitored, and smoke-tested end to end.

Business risk:

- Users can still be locked out if production email delivery is broken, suppressed, incorrectly templated, or pointing at the wrong domain.
- Founder/support may fall back to unsafe manual intervention if delivery evidence is missing.
- Enterprise customers will expect secure self-service recovery.

Requirements:

1. Confirm production SendGrid or approved email provider configuration for password reset.
2. Confirm reset links use the production CaseOps web domain.
3. Confirm auth-flow emails intentionally bypass unsubscribe/suppression lists where legally and operationally appropriate.
4. Confirm request flow remains anti-enumeration in production.
5. Confirm reset token is single-use, time-limited, hashed at rest, and invalid after use.
6. Confirm old sessions are revoked after successful reset.
7. Confirm inactive users cannot receive usable reset links.
8. Confirm audit events are recorded.
9. Confirm rate limiting is active.
10. Confirm bounced/failed reset emails are visible to founder/provider operations without leaking token values.

Acceptance criteria:

- Production smoke proves a real user can request a reset, receive the email, open the reset link, set a new password, and sign in.
- The public response remains generic whether the account exists or not.
- Expired/used/tampered token fails safely.
- No token value is logged, exported, or exposed in provider operations.
- Audit events are visible to tenant admin/founder as appropriate.

Required tests:

- Existing backend and frontend tests should remain green.
- Add or run production-safe smoke for request/receive/complete if feasible.
- Add provider delivery failure test if not already present.
- Add monitoring alert for repeated reset email failures.

## Recommended Closure Sequence

The next work should not be "build everything at once." The safest order is:

1. P0 production safety slice:
   - verify production password-reset email delivery and smoke evidence
   - founder billing signoff smoke
   - Pine Labs UAT readiness closure
   - provider cost calibration inputs
   - plan profitability enforcement
2. P0/P1 security slice:
   - MFA enrollment/login/recovery/enforcement
   - step-up authorization
   - expanded auth matrix tests
3. P1 connector reliability slice:
   - Google Workspace production UAT
   - Gmail full review workflow
   - Drive content import review queue
   - Google Calendar import/conflicts
   - connector live health probes
4. P1 Microsoft parity slice:
   - Microsoft 365 mailbox
   - Outlook calendar two-way sync
   - Graph change notifications
5. P1 finance operations slice:
   - settlement import/reconciliation
   - refund/credit note/dispute records
   - GST/TDS accounting exports
6. P1 AI governance slice:
   - evaluation suites
   - CI gate
   - admin UI
   - tenant AI policy/reporting
7. P1 provider workflow slice:
   - Temporal migration of long-running workflows
   - provider event correlation
   - case/court provider coverage matrix
8. P1 GBA/customer UAT slice:
   - representative matter data
   - PDF verification
   - court/provider coverage proof
   - stakeholder signoff
9. P2 product hardening slice:
   - tenant admin controls
   - pagination/performance
   - OpenAPI generated client adoption
   - accessibility
10. P3 expansion slice:
   - e-sign
   - accounting integrations
   - DMS
   - docs hub
   - enterprise deployment options

## Do-Not-Scale Guardrails

Do not onboard paid customers at scale until these are true:

1. Password reset production email delivery is confirmed with smoke evidence.
2. Founder can access production platform admin and export reports.
3. Pine Labs UAT has passed and founder has approved production activation.
4. Every plan has a founder-approved margin simulation using real cost inputs.
5. Expensive provider actions are usage-metered and hard-limited.
6. Tenant usage reports and top-up flows are verified.
7. Tenant-facing payloads do not expose internal cost, provider fee, margin, or profit.
8. MFA is available at least for founder and admins.
9. Case refresh provider costs and coverage are documented.
10. At least one restore drill has been completed.

Do not sell "enterprise-ready" until these are true:

1. MFA enforcement is complete.
2. SSO/OIDC or SAML is available.
3. Tenant admin security controls are available.
4. Audit/export controls are mature.
5. Tenant isolation tests cover documents, search, embeddings, billing, provider events, and exports.

Do not sell "full Google Workspace automation" until these are true:

1. Production OAuth is verified.
2. Gmail review-to-import works for threads and attachments.
3. Drive content import works through review queue.
4. Google Calendar two-way sync and conflict handling are implemented.

Do not sell "Microsoft 365 automation" until these are true:

1. Microsoft mailbox ingestion exists.
2. Outlook calendar two-way sync exists.
3. Graph change notification or durable polling exists.
4. Microsoft connector health appears in admin dashboards.

Do not sell "autonomous AI legal agents" until these are true:

1. Agent grants exist.
2. Tool calls are authority-bounded.
3. Human approval queue exists.
4. AI evaluation gate is enforced.
5. Every action is auditable and revocable.

## Required Evidence For Each Future Slice

Every future implementation slice should produce:

1. PRD traceability update.
2. Backend tests.
3. Frontend tests where UI is touched.
4. Tenant isolation tests for tenant-scoped data.
5. Founder-only access tests for internal data.
6. Migration upgrade/downgrade proof if DB changes are included.
7. `ruff` or equivalent lint proof for touched backend files.
8. Typecheck/build/test proof for touched frontend.
9. Production-safe smoke plan if deployed.
10. Clear "not done" section.

## Open Inputs Needed From Founder Or Providers

### Pine Labs

1. UAT merchant credentials.
2. UAT and production API base URLs.
3. Webhook secret and signature algorithm documentation.
4. Hosted checkout endpoint docs.
5. Payment link endpoint docs.
6. Subscription/recurring payment docs.
7. UPI AutoPay docs if applicable.
8. Refund endpoint docs.
9. Settlement report format.
10. Chargeback/dispute event docs.
11. Event names and sample webhook payloads.
12. MDR percentage by payment method.
13. Fixed fee by payment method.
14. GST on fees.
15. Settlement timeline.
16. Refund fee if any.
17. Chargeback fee if any.
18. Transaction limits.
19. Test instruments.
20. Confirmation of enabled products.

### Court/Case Tracking Provider

1. Supported courts and jurisdictions.
2. Lookup keys: CNR, case number, party, court, filing number.
3. Per-refresh cost.
4. Rate limits.
5. Bulk refresh support.
6. Webhook availability.
7. Data freshness SLA.
8. Error codes.
9. Retry guidance.
10. Legal/ToS constraints.

### Email/SMS/WhatsApp Providers

1. Provider selection.
2. Pricing by message type.
3. Template requirements.
4. DLT requirements for India.
5. Sender domain requirements.
6. Bounce/complaint webhooks.
7. Delivery status payloads.
8. Opt-out requirements.

### Google Workspace

1. Production OAuth client ID/secret.
2. Verified redirect URIs.
3. Approved consent screen status.
4. Domain verification status.
5. Approved scopes.
6. Test tenant/user accounts.
7. Admin consent policy.

### Microsoft 365

1. Entra app registration.
2. Tenant/admin consent model.
3. Graph scopes.
4. Redirect URIs.
5. Webhook/change notification setup.
6. Test tenant/user accounts.

### GBA Law Office

1. Representative active matters.
2. Representative disposed matters.
3. Sample cause-list PDFs.
4. Required invoice PDF layout.
5. Required logo/header/signature placement.
6. Court and jurisdiction list.
7. CNR/case number examples.
8. Advocate/source field examples.
9. GST/TDS invoice samples.
10. Stakeholder UAT approver.

## Final Brutal Summary

The product has enough breadth to impress, but paid production scale now depends on disciplined closure, not more surface area.

The next winning move is to stop adding new modules for a short period and close the P0 foundations: founder billing signoff, Pine Labs UAT, real provider cost calibration, plan margin enforcement, production password-reset delivery evidence, and MFA for founder/admins. After that, make Google/Microsoft connector promises honest by finishing durable review-first workflows, live health, and two-way sync.

Until those are done, CaseOps should be positioned as a controlled pilot product with founder-led onboarding, manual provider/payment activation, and explicit limits on automated provider-heavy features.
