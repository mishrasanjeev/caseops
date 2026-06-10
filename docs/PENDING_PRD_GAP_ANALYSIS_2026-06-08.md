# Pending PRD Gap Analysis - 2026-06-08

Status: current-state audit from local repository inspection  
Workspace: `C:\Users\mishr\caseops`  
Prepared for: CaseOps founder/product owner and Codex CLI follow-up planning  

## 1. Scope And Method

This document compares the current implementation against requirements and pending markers in the active PRD and roadmap files, especially:

- `docs/PRD.md`
- `docs/WORK_TO_BE_DONE.md`
- `docs/PRD_ADP_LAW_FIRM_FEEDBACK_PRODUCT_ROADMAP_2026-05-22.md`
- `docs/ADP_01_TO_19_END_USER_PRODUCT_GUIDE_2026-05-25.md`
- `docs/PRD_CASEOPS_AI_ENHANCEMENTS_2026-05-26.md`
- `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`
- `docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md`
- `docs/GBA_LAW_OFFICE_USER_GUIDE_2026-06-07.md`
- pricing, billing, Pine Labs, provider-operations, and production signoff runbooks under `docs/runbooks/`

Implementation evidence was checked through static repo inspection of backend routes/services/models, frontend app pages, tests, scripts, migrations, and runbooks. No live production mutation, live Pine Labs call, live court-provider call, or real provider OAuth flow was executed as part of this audit.

## 2. Executive Summary

The product has moved well beyond the older PRD baseline. The following foundations are implemented or substantially implemented:

- Email-based password reset is implemented with `/account/forgot-password`, sign-in links, backend start/complete routes, anti-enumeration behavior, and frontend tests.
- GBA Law Office core flows are implemented: disposed terminology, daily tracked-case refresh window behavior, court-order compliance extraction/review flow, manual order upload/OCR states, matter billing profiles, GST/TDS invoice fields, next-hearing provenance/lock/history, and cause-list preview/PDF download.
- SaaS billing foundation is implemented: pricing catalog, subscriptions, manual invoices, tenant invoice/download/export APIs, usage/spend reports, credit ledger, add-on/top-up flows, provider-disabled checkout behavior, and founder-only platform-admin profit/usage surfaces.
- Provider operations foundation exists under `/app/admin/provider-operations` for failed/blocked/dead-letter job visibility and audited replay/ignore/resolve actions.
- Durable in-app notification intents exist; external notification channels remain gated.
- Virus scanning is implemented through ClamAV integration and upload fail-close behavior where scanning is required.
- Async audit export exists through `AuditExportJob` and `/api/admin/audit/export/async`.
- Employee/admin/custom-role surfaces are present, so the older generic "teams/admin users" gap is no longer a broad current gap.
- Evaluation tables and scripts exist, so the older "EvaluationRun table missing" line is stale; the remaining gap is evaluation gate maturity.

The largest pending areas are:

1. Gmail/Google Workspace is partially closed. Gmail mailbox V1, Google Calendar V1, and Google Drive metadata V1 now exist with OAuth gates, encrypted token storage, safe UI states, provider-operation visibility, metadata-only Gmail import, review-first attachment candidates, Google hearing/task/deadline sync, cancelled-hearing provider-event delete, and per-user Drive metadata listing. The 2026-06-10 connector readiness slice adds durable connector health, Gmail/Outlook review queues, Drive candidate review/import controls, and calendar provider-event conflict review. Production Google activation, live provider UAT, and always-on durable provider automation remain pending.
2. Durable email/mailbox ingestion is partially closed for Gmail V1 metadata and webhook foundations. The 2026-06-10 slice adds Outlook Mail metadata candidates, inbound alias readiness, and explicit content-import request states. Autonomous polling, raw body storage, and automatic document/matter mutation remain pending by design.
3. Google Drive is partially closed for per-user OAuth, recent metadata listing, and review-first Drive candidate import controls. Durable provider-backed Drive sync, folder picker UAT, webhook/polling, and broad commit automation remain pending.
4. Outlook is not complete as a two-way automation product. The current implementation is bounded/manual or readiness-gated CaseOps-to-Outlook hearing sync only.
5. Pine Labs Plural code is present, but live payment acceptance remains blocked by UAT credentials, webhook registration, endpoint schemas, product enablement, MDR/settlement details, and founder go/no-go.
6. Provider cost assumptions still need calibration before aggressive law-firm onboarding. Case refresh cost is modeled by default, but real provider fee per refresh/case/court is not known.
7. MFA and OIDC/SAML SSO are not implemented as end-to-end auth flows. There are platform-admin MFA fields/readiness, but no actual enrollment/enforcement.
8. Grantex or equivalent agent identity is absent. No `AgentGrant`, `AgentExecution`, `AgentToolCall`, budgeted scoped delegation, revocation, or human approval gate exists.
9. External notification delivery and digests remain fail-closed or partial. The 2026-06-10 slice adds tenant/user notification preference rows and UI for in-app, email, SMS, WhatsApp, quiet hours, digest frequency, categories, escalation rules, and opt-outs. External email/SMS/WhatsApp delivery still remains disabled unless provider config and tenant/user preferences allow it.
10. AI evaluation has a foundation, but not full per-workflow CI-gated release control.
11. Court/source coverage is safe but incomplete. Selected court feeds/adapters exist; captcha/session-gated eCourts district/session workflows remain blocked until lawful provider/API access exists.
12. GBA core implementation is done, but exact client UAT inputs are still needed: sample PDF format, logo/header assets, final cause-list field mapping, provider/court list, and UAT signoff.

## 3. Priority Legend

- P0: blocks safe revenue activation, production payment acceptance, or founder-controlled rollout.
- P1: blocks a major promised workflow or materially weakens adoption for target customers.
- P2: important product maturity, enterprise readiness, or scale hardening.
- P3: nice-to-have, documentation cleanup, or deferred enterprise option.

## 4. Detailed Gap Ledger

### GAP-001 - Gmail / Google Workspace Connector Foundation Is Partial

Priority: P1  
Area: connectors, email, calendar, Google Workspace  
PRD source:

- `PRD_ADP_LAW_FIRM_FEEDBACK_PRODUCT_ROADMAP_2026-05-22.md` asks for Outlook/email/CaseOps interoperability and leaves provider priority open: Microsoft 365 first, Gmail first, or both.
- Older product gap analysis explicitly flags legal teams living in Outlook/Gmail.
- User explicitly flagged Gmail as a known missing option.

Current implementation evidence:

- `apps/api/src/caseops_api/api/routes/mailbox.py` exposes Gmail status, OAuth start/callback, disconnect, recent import, watch, webhook, import listing, and attachment-candidate routes.
- `apps/api/src/caseops_api/services/gmail_sync.py` implements Gmail OAuth, encrypted token storage, metadata-only message import, safe matter-code matching, review-first attachment candidates, Pub/Sub webhook verification, idempotency, provider-operation rows, and tenant-scoped listing.
- `apps/api/src/caseops_api/services/calendar_sync.py` implements Google Calendar provider upsert/delete for hearing, task, and deadline source records.
- `apps/web/app/app/calendar/page.tsx` now includes fail-closed Google Calendar and Gmail mailbox states, connected/import/watch/revoke actions, and no-token/no-raw-payload UI.
- `/app/admin/integrations`, `/app/platform-admin/integrations`, and `/app/matters/{matter_id}/documents` include Gmail, Google Calendar, and Google Drive readiness/connection affordances without exposing secrets or internal costs to tenants.

Remaining gap:

- No production Google OAuth credentials/UAT signoff has been executed in this repo session.
- No Google-to-CaseOps calendar import or two-way conflict workflow.
- No advanced Gmail label/search policy or full mailbox thread workflow.
- No approved raw email body storage; V1 intentionally stores safe metadata/snippets and review-first attachment candidates.
- Google Drive V1 is metadata-only: per-user OAuth, encrypted token storage,
  recent file listing, and revoke are present, but durable sync/commit and file
  content ingestion are not.
- Google Workspace admin consent model still needs final operational signoff for production tenants.

Impact:

- Many Indian law firms and solo lawyers use Gmail or Google Workspace. The product now has the safe foundation, but adoption still depends on production OAuth configuration, Google Cloud approval, and provider UAT.
- Users may assume "Google Workspace connector" includes Mail, Calendar, and Drive. Calendar, Gmail V1, and Drive metadata V1 are present; Drive import/commit and durable inbound automation are not.

Recommended next slice:

- Complete production Google OAuth/UAT setup without writing secrets into docs.
- Expand Gmail thread/label review workflows only after finalizing retention and body-storage policy.
- Keep Drive as a separate read/import/review slice.
- Keep provider disabled/fail-closed until credentials, scopes, provider terms, and tenant approval are configured.

2026-06-10 update:

- Connector Automation and Communication Readiness adds durable connector
  health, Gmail/Outlook metadata review actions, Drive review-import controls,
  calendar provider-event suggestions, Microsoft 365 readiness, inbound aliases,
  and notification preferences.
- This closes the "entirely missing" portions of the workflow. Remaining work is
  live provider UAT, production OAuth/Graph approval, full thread UX, advanced
  label/search policy, and durable provider webhooks/polling.

### GAP-002 - Durable Mailbox Ingestion Is Partial

Priority: P1  
Area: email ingestion, communications, matter intake  
PRD source:

- ADP-22 is marked as durable email connector readiness only.
- `WORK_TO_BE_DONE.md` still lists inbound email ingest and communication logging as future work.
- ADP roadmap says durable mailbox polling, provider webhooks, OAuth/token storage, and automatic matter mutation remain pending.

Current implementation evidence:

- `apps/api/src/caseops_api/services/email_calendar_candidates.py` can work with imported email/calendar metadata and recognizes Gmail provider-import communications as review candidates.
- `apps/api/src/caseops_api/services/communications.py` supports communication records and outbound SendGrid paths.
- Gmail mailbox tables now exist for per-user connections, message imports, review-first attachment candidates, and webhook events.
- `apps/api/src/caseops_api/services/provider_operations.py` includes `mailbox_message_import` and `mailbox_webhook` operation kinds.

Remaining gap:

- No Microsoft 365 mailbox ingestion.
- No autonomous mailbox polling worker.
- Gmail Pub/Sub webhook foundations record and dedupe events, but do not automatically fetch raw bodies or import documents.
- No inbound alias such as `{slug}@inbound.caseops.ai` implemented as a reliable production intake path.
- Attachment-to-matter import remains review-first; automatic attachment/document mutation is intentionally disabled.
- No full cross-provider thread model beyond Gmail V1 message import metadata.

Impact:

- Legal teams have a Gmail V1 review-first path, but not a full mailbox product for Outlook, inbound aliases, automatic document import, or durable two-way automation.
- Calendar extraction from email remains bounded and review-only.

Recommended next slice:

- Extend ADP-22 into provider-agnostic mailbox ingestion with Microsoft 365 and Gmail adapters.
- Use strict read-only scopes at first.
- Store provider IDs, headers/metadata, small safe snippets, attachment metadata, and encrypted raw body storage only if explicitly approved.
- Add matter-match suggestions, user review, audit events, and replay/dead-letter handling.
- Add provider webhooks only after token/secret storage and tenant approvals are in place.

2026-06-10 update:

- Gmail and Outlook metadata candidates now share a review-first action model.
  Inbound alias readiness exists with production disabled by default.
- Raw bodies, attachment bytes, and automatic document/matter mutation still
  require explicit review and provider/tenant approval.

### GAP-003 - Google Calendar Connector Foundation Is Partial

Priority: P1  
Area: calendar, Google Workspace  
PRD source:

- Sprint T in `WORK_TO_BE_DONE.md` calls for Google Calendar one-way sync.
- ADP calendar work discusses Outlook/email/CaseOps calendar interoperability but Google calendar events remain out of current scope.

Current implementation evidence:

- ICS export exists.
- Outlook calendar sync exists.
- BUG-053 adds Google Calendar OAuth start/callback, encrypted per-user Google
  token storage, single-hearing/task/deadline sync, bounded visible-range
  hearing/task/deadline sync, tenant calendar UI states, provider-event delete
  for previously synced hearings, connector registry readiness, and
  provider-operations visibility.
- Updating a hearing to `cancelled` clears or recomputes `Matter.next_hearing_on`,
  cancels reminders, removes it from upcoming buckets, and deletes previously
  synced Google provider events idempotently.

Remaining gap:

- No Google-to-CaseOps import.
- No provider webhook or always-on durable background Google Calendar
  automation.
- Conflict handling is limited to existing duplicate provider-event detection.
- Production Google OAuth credentials/UAT and real provider proof remain pending.

Impact:

- Gmail/Google Workspace law firms now have a safe first-class CaseOps-to-Google
  Calendar foundation, but not production-enabled OAuth/UAT or two-way durable
  calendar automation.
- ICS export remains useful as a fallback but is not equivalent to provider
  integration.

Recommended next slice:

- Add Google-to-CaseOps import only after review gates and conflict policy are
  approved.
- Add provider webhooks/always-on automation only after credential, quota,
  audit, retry, and rollback behavior is approved.
- Keep Gmail and Drive as separate review-gated provider slices.

### GAP-004 - Outlook Automation Is Only Partial

Priority: P1  
Area: Outlook, calendar, durable workflows  
PRD source:

- ADP-20 says durable Outlook sync foundation is implemented for CaseOps-to-Outlook hearings only.
- ADP roadmap states no mailbox read, Outlook-to-CaseOps import, provider webhook, task/deadline sync, or two-way conflict automation is included.

Current implementation evidence:

- `apps/api/src/caseops_api/api/routes/calendar.py` exposes Outlook connection and manual/bounded sync endpoints.
- `apps/api/src/caseops_api/workflows/notification_intents.py` contains a readiness-gated Outlook durable sync workflow.
- `docs/ADP_01_TO_19_END_USER_PRODUCT_GUIDE_2026-05-25.md` states current Outlook sync is bounded/manual and durable always-on sync remains pending.

Gap:

- No Outlook-to-CaseOps meeting/hearing/deadline import.
- No two-way conflict resolution.
- No Graph change-notification webhook ingestion.
- No task/deadline sync.
- No always-on sync that users can trust as a background automation.

Impact:

- The product can help push hearing dates out, but it is not yet a full Outlook/CaseOps synchronization product.

Recommended next slice:

- Turn the existing ADP-20 foundation into a durable production path after Temporal/provider readiness.
- Add Graph change notifications and subscription renewal only after secrets and admin consent are verified.
- Keep all inbound changes review-gated before mutating legal records.

### GAP-005 - Google Drive Sync Is Metadata-Only

Priority: P1  
Area: document ingestion, Google Drive  
PRD source:

- ADP-12 supports bounded manual Google Drive import.
- ADP-21 durable Google Drive sync remains pending.
- ADP roadmap says file content ingestion, provider webhooks, background polling, and durable commit are pending.

Current implementation evidence:

- `apps/api/src/caseops_api/services/google_drive_imports.py` exposes a dry-run planner.
- `GoogleDriveImportDryRunSummary.commit_supported` is false.
- Provider operations surfaces names-only readiness for Google Drive.
- `apps/api/src/caseops_api/api/routes/drive.py` exposes Google Drive status,
  OAuth start/callback, recent file metadata listing, and revoke.
- `apps/api/src/caseops_api/services/drive_sync.py` implements fail-closed
  Google Drive OAuth, encrypted token storage, per-user/per-tenant scoping,
  metadata-only file listing, and redacted audit events.
- `apps/web/app/app/matters/[id]/documents/page.tsx` shows a compact Drive
  panel for document uploaders. `/app/admin/integrations` shows tenant-safe
  admin readiness and connection controls.

Gap:

- No file-content fetch/import commit path.
- No Drive folder-to-matter mapping persistence.
- No webhook/polling for changed files.
- No file dedupe/version tracking across Drive IDs.
- No legal review queue before importing sensitive documents.

Impact:

- Law firms can now connect a user Drive account and inspect recent Drive file
  metadata, but cannot migrate or keep matter documents synchronized from Drive
  until the import/commit slice is implemented.

Recommended next slice:

- Implement Drive folder picker, dry-run-to-commit, attachment creation,
  document processing jobs, dedupe, and audit.
- Keep destructive operations out of scope; CaseOps should read/import, not delete or rewrite Drive files.

2026-06-10 update:

- Drive candidate records, review queue UI, tenant controls, provenance, and
  explicit import actions now exist. Auto-import remains forced off.
- Live provider-backed content import, folder picker UX, and durable
  webhook/polling still need provider credentials and tenant approval.

### GAP-006 - Unified Connector Health Dashboard Is Not Complete

Priority: P2  
Area: admin console, integrations, operations  
PRD source:

- `WORK_TO_BE_DONE.md` calls for connector status under an admin integrations surface.
- PRD connector requirements ask for health state, per-tenant credentials, audit, and source lineage.

Current implementation evidence:

- `/app/admin/provider-operations` exists and handles failed/blocked/dead-letter job replay for selected operation kinds.
- Slice 1 implementation adds `/app/admin/integrations`,
  `/app/platform-admin/integrations`, `GET /api/admin/integrations`, and
  `GET /api/platform-admin/integrations`.
- The registry includes Outlook calendar, Microsoft mailbox readiness, Gmail,
  Google Calendar, Google Drive, Pine Labs, SendGrid, SMS, WhatsApp, case
  tracking provider, PRS/legal updates, Temporal, ClamAV, and storage.

Gap:

- Partially closed by Slice 1: tenant and founder dashboards now show safe
  connector inventory, enabled/configured/blocked/healthy/degraded status,
  webhook status, safe token-expiry field where available, config names,
  scopes, runbook links, and provider-operations links.
- Remaining: per-connector quota consumption, connection-owner display, and
  active health probes are still deferred because they require provider calls or
  additional per-tenant credential foundations.

Impact:

- Admins and support will struggle to diagnose which connector is configured, healthy, disabled, blocked, or consuming money.

Recommended next slice:

- Add provider-backed health probes only after each connector has safe
  credential storage, provider-call budgets, redaction rules, and tenant
  approval.

2026-06-10 update:

- Durable connector health records now exist for Google, Gmail, Drive, Calendar,
  Microsoft 365, Outlook Mail/Calendar, OneDrive/SharePoint, email delivery,
  SMS, and WhatsApp.
- Tenant admins and founder/platform admins have active health APIs/UI with
  redacted failure categories and provider-operation links. Live provider probes
  remain gated behind provider credentials and tenant approval.

### GAP-007 - Pine Labs Plural Live Payment Acceptance Is Not Ready

Priority: P0  
Area: billing, revenue, payments  
PRD source:

- Pricing/billing PRD requires Pine Labs Plural online payment acceptance.
- Pine Labs UAT readiness runbook lists credentials, webhook, product enablement, endpoint schema, events, MDR, settlement, refunds, chargebacks, and test instruments as pending inputs.

Current implementation evidence:

- `apps/api/src/caseops_api/services/pine_labs.py` and `services/saas_billing.py` support disabled/mock/configured modes.
- `apps/api/src/caseops_api/core/settings.py` defaults `pine_labs_env` to `disabled`.
- Production notes and runbooks state Pine Labs remains disabled until UAT and founder approval.

Gap:

- No UAT credentials installed.
- No real webhook secret/registered webhook proof.
- No provider-confirmed endpoint paths/schemas.
- No confirmed hosted checkout/payment-link/subscription/UPI AutoPay enablement.
- No live refund/settlement reconciliation proof.
- No MDR/fixed fee/GST-on-MDR/chargeback/transaction-limit confirmation.
- No founder go/no-go approval to enable payments.

Impact:

- CaseOps cannot safely accept production online subscription payments yet.
- Revenue is limited to manual/offline billing until activation.

Recommended next slice:

- Execute Pine Labs UAT readiness checklist end to end.
- Store secrets only in secret manager/environment, not docs.
- Run UAT scenarios: success, failure, pending, cancel, timeout, duplicate webhook, replay attack, refund event if enabled, settlement reconciliation, subscription/mandate lifecycle.
- Only then enable production with rollback plan.

### GAP-008 - Founder Production Billing Signoff Is Still Pending

Priority: P0  
Area: billing, admin, production readiness  
PRD source:

- Pricing/billing PRD requires founder-only platform admin to track enrollments, usage, earnings, profits, margin alerts, manual invoices, and provider events.
- `docs/runbooks/production-billing-signoff-2026-06-02.md` lists manual founder and tenant smoke gates.

Current implementation evidence:

- Platform admin backend and UI exist.
- Slice 1 adds founder-only `/app/platform-admin/integrations` and
  `/app/platform-admin/costs`, plus `/api/platform-admin/cost-profiles` and
  `/api/platform-admin/margin-simulations`.
- Prior rollout notes show unauthenticated public smoke passed.
- Authenticated founder/tenant smoke was not completed in the reported deploy context.

Gap:

- Manual founder login smoke for `/app/platform-admin`,
  `/app/platform-admin/profit`, `/app/platform-admin/integrations`,
  `/app/platform-admin/costs`, provider events, margin alerts, exports, cost
  profiles, and margin simulations.
- Tenant admin smoke for billing page, usage/spend reports, invoice downloads, statement, payment export, credit ledger export, spend export.
- Pine disabled-state checkout smoke under authenticated tenant context.
- Evidence capture and signoff not added to runbook.
- Slice 1 updates the production billing signoff runbook with tenant
  integrations and founder cost/margin evidence fields; actual production smoke
  remains an operational signoff task.

Impact:

- The founder console may be implemented but is not fully production-signed-off from the only account that should access it.

Recommended next slice:

- Log in as the configured founder and complete the production billing signoff runbook.
- Verify no other user has platform-admin access.
- Verify tenant admin gets 403 on platform-admin routes.

### GAP-009 - Provider Cost Calibration Is Incomplete

Priority: P0 for profitability, P1 for product correctness  
Area: pricing, case tracking, profit reporting  
PRD source:

- Pricing PRD explicitly states real court/case refresh provider cost is unknown.
- PRD requires margin protection and provider-cost monitoring.

Current implementation evidence:

- Billing profit rollups include `case_refresh_cost_minor`, `llm_cost_minor`, payment provider costs, gross profit, and margin.
- Default case-refresh cost modeling exists.
- Slice 1 adds `provider_cost_profiles` and `billing_margin_simulations`, plus
  founder-only APIs/UI for cost-profile CRUD foundation and margin simulation.
- Billing cost estimates use configured actual cost profiles where available
  and fallback defaults otherwise.
- Founder margin alerts include a warning when actual case refresh cost is INR
  0.10 or more per tracked-case refresh equivalent.
- The actual commercial provider cost per CNR/case refresh/court is not known.

Gap:

- Partially closed by Slice 1: platform configuration tables and UI exist for
  provider cost inputs, but real court/case provider pricing still must be
  obtained and entered from approved source documents.
- No reconciliation against provider invoices.
- No per-provider/per-plan stress model using actual refresh cost.
- Per-scenario margin simulation exists; broader scheduled plan-by-plan stress
  reporting remains deferred.
- No product decision on whether some plans need lower refresh cadence or paid add-ons once real cost is known.

Impact:

- A high-usage law firm or GC customer could erode margin if case refresh costs are materially higher than the default assumption.

Recommended next slice:

- Create a provider-cost configuration table/admin UI for court/case providers.
- Track actual provider calls per tenant/plan/source.
- Add platform-admin margin simulation for each plan using target/stress/actual provider costs.
- Do not sell high-volume daily/priority tracking plans until real provider cost is known or the plan has explicit overage/top-up pricing.

### GAP-010 - SaaS Payment Refund/Settlement Operations Need Live Validation

Priority: P1  
Area: billing operations, finance  
PRD source:

- Pricing PRD requires refund/settlement/provider events to be auditable.
- User requested no public refund-policy copy; internal handling may exist.

Current implementation evidence:

- Refund event names are mapped in Pine Labs service.
- Settlement paths/settings exist.
- Manual invoices support TDS fields.
- No real Pine Labs refund/settlement data has been exercised.

Gap:

- No live refund flow validation.
- No settlement report import reconciliation with Pine Labs dashboard exports.
- No chargeback/dispute operational flow validated.
- No accountant-approved SOP for TDS certificate/short payment reconciliation beyond recording amounts.

Impact:

- Finance/profit reports may not reconcile to bank statements until real settlement data is wired and tested.

Recommended next slice:

- Keep public refund policy silent until approved.
- Add internal refund/adjustment SOP and tests against Pine UAT samples.
- Add settlement import parser once Pine Labs confirms fields.
- Add accountant-approved TDS reconciliation notes and exports.

### GAP-011 - MFA Is Not Implemented End To End

Priority: P1  
Area: identity, security  
PRD source:

- Core PRD requires MFA support.
- Pricing PRD says MFA should be kept in design so it can be enforced later, including for existing users.

Current implementation evidence:

- Platform admin membership has `mfa_required` / `mfa_enforced_at` style fields.
- Platform admin overview exposes an MFA-required concept.
- No TOTP/WebAuthn/SMS/email OTP enrollment and login challenge flow was found.

Gap:

- No MFA enrollment UI.
- No MFA verification during sign-in.
- No recovery codes.
- No backup factor/reset admin process.
- No step-up reauthentication for high-risk actions such as platform-admin access, manual invoice paid marking, provider secret changes, refunds, or overage policy changes.
- No migration path to force MFA for already existing users.

Impact:

- Founder-only platform admin and payment operations depend only on existing login security.
- Enterprise customers may require MFA before procurement approval.

Recommended next slice:

- Implement MFA primitives with TOTP plus recovery codes first; consider WebAuthn/passkeys later.
- Add per-company and platform-admin enforcement flags.
- Add grace period and forced enrollment flow for existing users.
- Add step-up challenge for high-risk admin actions.

### GAP-012 - OIDC/SAML SSO Is Not Implemented

Priority: P1 for enterprise, P2 for solo/small firms  
Area: identity, enterprise readiness  
PRD source:

- Core PRD requires enterprise SSO using OIDC/SAML.
- Pricing/marketing mentions OIDC/SAML SSO and SCIM for enterprise tiers.

Current implementation evidence:

- Local password/session auth exists.
- No tenant OIDC/SAML provider configuration routes or login flows were found.

Gap:

- No OIDC provider config per tenant.
- No SAML metadata/certificate handling.
- No JIT provisioning from IdP claims.
- No role/capability mapping from groups/claims.
- No SSO-only enforcement policy.
- No SCIM provisioning.

Impact:

- Corporate GCs and larger law firms may block procurement without SSO.

Recommended next slice:

- Start with OIDC for one enterprise pilot, then SAML.
- Store provider config tenant-scoped and encrypted where sensitive.
- Implement domain-based SSO routing, JIT user creation, group-to-role mapping, and audit logs.

### GAP-013 - Agent Identity / Grantex Equivalent Is Missing

Priority: P1 for autonomous agent roadmap  
Area: AI safety, agent authorization  
PRD source:

- Core PRD defines a trust plane with Grantex-backed scoped agent permissions, revocation, consent, budgets, and audit.
- `WORK_TO_BE_DONE.md` calls for `AgentGrant`, `AgentExecution`, and `AgentToolCall` with scopes, expiry, budget, revocation, and human approvals.

Current implementation evidence:

- Search found PRD references but no implementation of `AgentGrant`, `AgentExecution`, `AgentToolCall`, or `HumanApproval` agent gates.

Gap:

- No scoped delegated agent permission model.
- No per-agent budget/expiry/revocation.
- No durable tool-call audit ledger for autonomous actions.
- No human approval gate for high-risk agent actions.

Impact:

- The product should not run autonomous agents that mutate matters, send messages, sync providers, or spend tokens without this trust plane.

Recommended next slice:

- Implement a minimal internal Grantex-equivalent model before autonomous agents.
- Require explicit scopes, tenant/matter boundaries, budgets, expiry, revocation, and review gates.
- Add route tests proving grants cannot cross tenants or exceed scope.

### GAP-014 - External Notification Delivery And Digests Are Still Gated

Priority: P1  
Area: notifications, legal updates, case tracking, reminders  
PRD source:

- ADP-23 says judgment/legal-update external digests remain pending.
- ADP roadmap states email/SMS/WhatsApp delivery remains provider-gated/fail-closed.
- Core PRD requires reliable notification delivery.

Current implementation evidence:

- Durable in-app notification rules/intents exist.
- Hearing reminder channels have email support through SendGrid where configured, with SMS/WhatsApp disabled or gated.
- `apps/web/app/app/admin/notifications/page.tsx` states channel is in-app and email/SMS/WhatsApp automation remains unavailable.
- `provider_operations.py` states external digest delivery is blocked.

Gap:

- No user digest preferences for judgment/legal-update alerts.
- No external digest delivery through email/SMS/WhatsApp.
- No per-tenant sender-domain/template approval workflow for broad notifications.
- SMS/WhatsApp production enablement remains pending.
- No unified notification preference center for users.

Impact:

- Users must log in to see many important updates.
- Case tracking/legal update promises are safer but less sticky without external notifications.

Recommended next slice:

- Keep in-app as default.
- Add email digest preference and SendGrid template governance first.
- Add SMS/WhatsApp only after India pricing, consent, DLT/template approval, and opt-in design are complete.

### GAP-015 - AI Evaluation Gate Is Foundation Only

Priority: P1  
Area: AI quality, release safety  
PRD source:

- Core PRD requires evaluation for citation accuracy, extraction accuracy, hallucination, latency, and cost.
- `WORK_TO_BE_DONE.md` says per-workflow golden coverage and CI-gated evaluation remain incomplete.

Current implementation evidence:

- `EvaluationRun` and `EvaluationCase` models exist.
- `apps/api/src/caseops_api/services/evaluation.py` exists.
- `apps/api/src/caseops_api/scripts/eval_ai_safety.py` and `eval_workflows.py` exist.

Gap:

- No platform/admin UI for model/prompt evaluation approval.
- No enforced CI gate for every model/prompt change across drafting, recommendations, hearing packs, compliance extraction, summaries, and legal updates.
- No per-workflow golden set coverage large enough for release confidence.
- No founder-visible "model version approved/rejected" workflow.

Impact:

- AI features can regress quietly if prompt/model changes bypass manual discipline.

Recommended next slice:

- Build an evaluation dashboard and release gate.
- Require eval run IDs and thresholds before changing production model/prompt configs.
- Add fixture suites for each AI workflow and report cost/latency deltas.

### GAP-016 - Matter Attachment Embeddings / Deep RAG Are Still Partial

Priority: P2  
Area: AI retrieval, matter intelligence  
PRD source:

- Core PRD and older work ledger call for robust RAG, vector retrieval, matter attachment embeddings, and per-tenant overlays.

Current implementation evidence:

- Retrieval and authority ingestion exist.
- `WORK_TO_BE_DONE.md` still lists matter-attachment embeddings, per-tenant annotation overlay, and live-PG integration tests as remaining in the retrieval area.

Gap:

- Matter-level attachment embeddings are not clearly complete as a production-grade retrieval layer across all document types.
- Per-tenant overlays for authority annotations/retrieval need verification/expansion.
- Live Postgres/vector integration tests need to cover tenant boundaries and recall.

Impact:

- AI context quality may vary for matter-specific document-heavy work.

Recommended next slice:

- Add attachment embedding jobs with tenant/matter scoping, reindex controls, and cost accounting.
- Add retrieval evals and live-PG tests for tenant leakage and recall.

### GAP-017 - Non-Notification Temporal Workflow Porting Is Incomplete

Priority: P2  
Area: durable workflows, scale  
PRD source:

- `WORK_TO_BE_DONE.md` requires porting `DocumentIngestionWorkflow`, `CourtSyncWorkflow`, `DraftingWorkflow`, `HearingPackWorkflow`, and `RecommendationWorkflow` to durable workflows.

Current implementation evidence:

- Temporal foundation exists for notification intents and Outlook sync probes.
- `workers/document_processor.py` still exists as a custom worker.
- Durable workflow settings are disabled by default unless configured.

Gap:

- Document ingestion, court sync, drafting, hearing pack generation, and recommendation workflows are not fully ported to durable Temporal workflows.
- Old custom polling is not fully retired.
- Retry/versioning/timeouts for these workflows are not uniformly managed by Temporal.

Impact:

- Long-running or failure-prone tasks may still require custom retry/recovery logic.

Recommended next slice:

- Port one high-value workflow at a time.
- Start with document ingestion or court/case tracking because those directly affect reliability.

### GAP-018 - Court And Case Provider Coverage Is Safe But Incomplete

Priority: P1  
Area: court data, case tracking, legal updates  
PRD source:

- AI enhancement PRD requires provider-gated CNR/case-number tracking.
- Cause-list scraper PRD and GBA PRD require daily refresh and court source coverage.
- PRDs explicitly prohibit captcha/session-gated scraping.

Current implementation evidence:

- Case tracking models/routes/services and polling script exist.
- `case_tracking_provider` is provider-gated.
- Selected live court sync/authority adapters exist for Supreme Court, Delhi, Bombay, Karnataka, Telangana/Hyderabad, Chennai/Madras operational pages, and Central Delhi public posture.
- eCourts district/session sources are marked blocked when captcha/session-gated.

Gap:

- No confirmed production provider token/licensed eCourts API for broad CNR/case tracking.
- No live provider cost calibration.
- District/session court tracking remains limited unless official/licensed non-captcha access is obtained.
- Coverage is not pan-India.
- No proof that all GBA-required courts/providers are supported.

Impact:

- Case tracking may work only in provider-disabled/mock/specific-provider contexts until commercial/legal access is finalized.
- A customer expecting broad lower-court coverage may be disappointed.

Recommended next slice:

- Decide provider strategy: official API, licensed provider, or manual/assisted tracking.
- Maintain a court/source support matrix by court, jurisdiction, access mode, status, cost, legal basis, and known limitations.
- Do not bypass captcha or session gates.

### GAP-019 - GBA UAT Inputs And Exact Formatting Are Still Needed

Priority: P1 for GBA rollout, P2 for generic product  
Area: GBA Law Office, cause list, billing PDFs  
PRD source:

- `PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md` Section 17 lists open inputs needed from GBA.

Current implementation evidence:

- GBA user guide and tests indicate core implementation exists.
- Open inputs remain in the PRD.

Gap:

- Sample cause-list PDF from GBA is still needed to exactly match the requested format.
- GBA logo/header assets and final firm header details are needed.
- Required case-number/CNR fields for cause-list output must be finalized.
- Source of "advocate appearing" field must be confirmed.
- Court/provider list for the 4:00 PM to 6:00 PM refresh window must be confirmed.
- Decision needed on whether disposed matters with future listings should appear in PDFs.
- Representative matters/orders should be used for formal UAT.

Impact:

- The feature is implemented generically, but exact client acceptance may fail on formatting/field expectations without sample artifacts.

Recommended next slice:

- Collect GBA artifacts and run a formal UAT checklist.
- Add profile-based PDF formatting if their sample materially differs from current output.

### GAP-020 - Full PRD UAT Coverage Is Not Complete

Priority: P1  
Area: QA, release readiness  
PRD source:

- Core PRD asks for UAT scenarios across law firm, GC, solo, MFA, SSO, payment refunds/disputes, and agent tests.
- Work ledger calls for Playwright coverage per PRD UAT scenario.

Current implementation evidence:

- Many backend/frontend targeted tests exist.
- Playwright/marketing tests exist.
- Prior notes show broad backend monolithic suite is impractical locally and live provider UAT was not run.

Gap:

- Not every PRD UAT scenario has an end-to-end Playwright or equivalent acceptance test.
- Live provider tests for Pine Labs, court provider, Outlook OAuth, Gmail, Drive, SMS/WhatsApp are absent or blocked by missing credentials.
- MFA/SSO/agent UAT cannot exist until those features exist.

Impact:

- Product breadth is now large enough that regression risk increases without scenario-level UAT automation.

Recommended next slice:

- Create a PRD-to-test coverage matrix.
- Mark each row as unit, integration, Playwright, live-UAT, blocked-by-provider, or not implemented.
- Add the first missing E2E tests for billing, founder admin, GBA cause list, and connector-disabled states.

### GAP-021 - Tenant And Founder Usage Reports Need Live Data Validation

Priority: P1  
Area: billing reports, user trust, profitability  
PRD source:

- User requested tenant-visible usage/spend details, additional credit purchases, and founder-only reports for usage, earnings, and profit.
- Pricing PRD requires tenant reports to exclude internal costs while founder reports include profit/cost.

Current implementation evidence:

- Tenant invoice download, statement, payment export, credit ledger export, and spend export exist.
- Platform profit and company profitability reports exist.
- Prior verification was local/prod-safe smoke, not long-period real production data.

Gap:

- Need validation with real tenants and multiple billing periods.
- Need validation that tenant exports never leak internal cost/profit/vendor fee fields.
- Need validation that add-on/top-up purchases reconcile with credit ledger and invoice/payment state.
- Need validation that platform profit numbers match provider settlements and LLM/case refresh costs once live.

Impact:

- Reports may be structurally correct but still need production data proof before relying on them for business decisions.

Recommended next slice:

- Create seed/demo production-like tenants for solo, firm, and GC.
- Simulate monthly usage, top-ups, manual invoice, TDS, payment provider disabled/enabled states.
- Export tenant and founder reports and compare expected totals.

### GAP-022 - External Accounting / E-Sign / DMS Integrations Are Not Present

Priority: P2  
Area: integrations, enterprise workflow  
PRD source:

- Earlier product gap analysis flags legal teams using DMS, Word, e-sign, accounting, and external tools.
- Pricing/GBA billing requirements cover internal invoices but not full accounting system handoff.

Current implementation evidence:

- Internal billing and matter invoice PDFs exist.
- No Tally/Zoho Books/QuickBooks, e-sign, Word add-in, SharePoint/OneDrive DMS, or external DMS integration was found as a first-class product surface.

Gap:

- No accounting export/integration beyond CSV/PDF style exports.
- No e-sign provider integration.
- No Word add-in or document co-authoring integration.
- No DMS integration beyond current upload/import foundations.

Impact:

- Larger firms and corporate GCs may require these integrations later, but they are not necessary before Pine/payment/Gmail/core provider readiness.

Recommended next slice:

- Defer until after Gmail/Drive/Pine readiness unless a paying customer demands one.
- Start with accounting export formats before API integrations.

### GAP-023 - Public Docs Route Is Still Guide-Centric

Priority: P3  
Area: docs, marketing, developer-facing docs  
PRD source:

- Prior public-docs work notes stated there is no separate deployed `/docs` route; public docs are the guide plus machine-readable docs.

Current implementation evidence:

- `/guide`, `/llms.txt`, and `/llms-full.txt` exist.
- FastAPI `/docs` can be toggled by API docs settings.

Gap:

- No dedicated product docs center route for all PRDs/guides/runbooks.

Impact:

- Not a launch blocker. The guide is sufficient for users, but a docs hub may help onboarding and support.

Recommended next slice:

- Add a curated docs hub only after user-facing features stabilize.

### GAP-024 - Enterprise Deployment Options Are Deferred

Priority: P3 unless enterprise deal requires it  
Area: enterprise, deployment, compliance  
PRD source:

- Core PRD mentions shared SaaS, dedicated/private VPC, on-prem, and air-gapped deployment options.

Current implementation evidence:

- Current deployment is shared SaaS on Cloud Run/Cloud SQL style infrastructure.

Gap:

- No self-service dedicated tenant deployment.
- No private VPC customer deployment package.
- No on-prem/air-gapped package.

Impact:

- Some regulated enterprise deals may require deployment options not yet available.

Recommended next slice:

- Defer until enterprise demand is confirmed.
- Document a paid enterprise path for dedicated environment assessment.

## 5. Closed Or Mostly Closed Items That Should Not Be Reopened As Current Gaps

These items appeared in older gap ledgers or prior user notes but are no longer current gaps based on implementation evidence:

1. Password reset: implemented with forgot-password UI, sign-in link, backend start/complete routes, anti-enumeration behavior, and tests.
2. Tenant invoice/billing/usage self-service: implemented for invoices, statements, payment export, credit ledger export, spend export, usage/spend views, and add-on/top-up flows.
3. Founder-only platform-admin foundation: implemented, though production founder signoff remains pending.
4. GBA core requirements: implemented at product level; remaining work is client-specific inputs and UAT.
5. Virus scanning: implemented with ClamAV integration and fail-close behavior where required.
6. Async audit export: implemented through `AuditExportJob` and async export routes.
7. Employee/admin/custom roles: implemented enough that the old broad "teams/admin users missing" gap should not be carried forward without a narrower requirement.
8. EvaluationRun table: implemented; remaining work is evaluation maturity and gating.
9. OpenAPI quality foundation: implemented lint and generated `openapi-types.ts`; remaining work, if desired, is broader generated-client adoption.
10. Durable in-app notification intents: implemented; remaining work is external delivery and digest preferences.

## 6. Recommended Next Work Sequence

### Slice 1 - Production Billing And Profit Safety Signoff

Why first: prevents revenue leakage and confirms founder-only visibility before adding more paid users.

Deliverables:

- Complete founder authenticated production billing signoff using the updated
  smoke checklist.
- Validate tenant billing downloads/exports.
- Validate platform profit/margin pages.
- Validate tenant integrations and founder integrations/costs/margin pages.
- Confirm no tenant sees internal costs/profit.
- Run provider-disabled checkout smoke.
- Capture evidence in `docs/runbooks/production-billing-signoff-2026-06-02.md`.

### Slice 2 - Pine Labs UAT And Cost Calibration

Why second: online payments and provider fees directly affect profitability.

Deliverables:

- Collect all Pine Labs UAT details.
- Configure UAT only.
- Run payment, webhook, duplicate, failure, timeout, refund, and settlement scenarios.
- Confirm MDR/fixed fee/GST-on-MDR/settlement/chargeback details.
- Update platform cost assumptions.
- Founder go/no-go for production enablement.

### Slice 3 - Google Workspace Production Activation And Review Workflows

Why third: Gmail and Google Calendar now have a safe V1 foundation, but they still need production OAuth/UAT and deeper review workflows before broad customer activation.

Deliverables:

- Configure Google OAuth credentials through secret/env references only.
- Run production-safe UAT for Gmail mailbox status/import/watch and Google
  Calendar hearing/task/deadline sync without storing real credentials in docs.
- Confirm OAuth consent, scopes, redirect URIs, tenant approval, and revoke
  behavior.
- Expand Gmail review workflows for threads/labels only after retention and raw
  body policy are approved.
- Confirm provider operations, audit events, and fail-closed disabled state in
  the deployed environment.

### Slice 4 - Durable Mailbox And Drive Automation

Why fourth: builds on connector foundation and starts real workflow automation.

Deliverables:

- ADP-22 mailbox ingestion for Outlook and Gmail.
- ADP-21 Google Drive import commit and sync.
- Webhook/polling where allowed.
- Human review before matter mutation.
- Dedupe and replay/dead-letter handling.

### Slice 5 - MFA And Step-Up Security

Why fifth: payment/admin/provider controls deserve stronger authentication.

Deliverables:

- TOTP enrollment.
- Recovery codes.
- Enforced MFA for founder/platform-admin.
- Tenant policy to require MFA for all users, including existing users after grace period.
- Step-up MFA for high-risk actions.

### Slice 6 - AI Evaluation Gate And Agent Trust Plane

Why sixth: enables safer expansion of autonomous and AI-heavy features.

Deliverables:

- Evaluation dashboard.
- CI/release gate for prompt/model changes.
- Per-workflow golden datasets.
- Minimal Grantex-equivalent agent grants, executions, tool calls, budgets, revocation, and human approvals.

### Slice 7 - Court Provider Coverage And GBA UAT

Why seventh: improves customer-specific legal operations without unsafe scraping.

Deliverables:

- Court/provider support matrix.
- Real provider pricing/cost proof.
- GBA sample artifacts and UAT signoff.
- Exact cause-list profile if needed.

## 7. Details Needed From External Teams

### From Pine Labs Plural

Required before live payment acceptance:

- UAT base URL and production base URL.
- Client ID, client secret, merchant ID, and credential rotation process.
- Webhook secret/signing scheme, exact signature header names, timestamp header, webhook ID header, tolerance rules, and sample signed payloads.
- Registered webhook URL confirmation for UAT and production.
- Hosted checkout/order endpoint paths and schemas.
- Payment-link endpoint paths and schemas.
- Payment status endpoint paths and schemas.
- Subscription plan, subscription create, subscription status, mandate, and UPI AutoPay endpoint paths and schemas if subscriptions are enabled.
- Refund endpoint/status endpoint details if refunds are enabled internally.
- Settlement endpoint/report/export format, field definitions, and matching keys.
- Event names and sample payloads for payment success, payment failed, pending, cancelled, timeout, duplicate/retry, refund processed, refund failed, settlement, chargeback/dispute, subscription created, mandate active, mandate failed, subscription cancelled, subscription renewed.
- Test instruments for card, UPI, netbanking, failure, pending, timeout, refund, and subscription/mandate.
- MDR by payment method, fixed fee, GST on MDR, settlement cycle, refund fees, chargeback fees, transaction limits, and whether convenience fee/MDR may be passed to customers.
- Product enablement confirmation for hosted checkout, payment links, subscriptions, UPI AutoPay, refunds, settlements, and dashboard exports.

### From Google Cloud / Google Workspace Setup

Required before production Gmail/Google Calendar activation and any Drive connector:

- Google Cloud project ID.
- OAuth client ID and secret for web app.
- Authorized redirect URIs for local, UAT, and production.
- Gmail API enabled.
- Google Calendar API enabled.
- Google Drive API enabled.
- Pub/Sub topic/subscription setup if Gmail watch or Drive changes are used.
- OAuth verification status and approved scopes.
- Decision: tenant-admin consent, per-user OAuth, or both.
- Decision: continue metadata/snippets-only Gmail V1 or approve raw email body
  retention separately.

### From Microsoft 365 / Azure App Registration

Required for durable Outlook/Microsoft mailbox automation:

- Confirm existing app registration details.
- Confirm delegated vs application permissions.
- Required Graph scopes for calendar, mail read, subscriptions, offline access.
- Tenant-admin consent process.
- Webhook notification URL validation process.
- Subscription renewal limits and lifecycle rules.

### From Court / Case Tracking Provider

Required before broad paid tracking:

- Provider name and legal basis/license.
- API base URL and authentication method.
- Supported search modes: CNR, case number, party, court/state/court code.
- Bulk refresh support and limits.
- Per-call/per-refresh/per-case cost.
- Rate limits and concurrency limits.
- Terms on storing raw payloads, order PDFs, provider AI summaries, and derived summaries.
- Webhook support, if any.
- Error codes and safe user-message mapping.
- Coverage by court/jurisdiction.

### From GBA Law Office

Required before client-specific signoff:

- Sample cause-list PDF.
- GBA logo/header assets and exact firm header text.
- Final matter case-number/CNR field expectations.
- Source of advocate/appearing counsel field.
- Required courts/providers for the 4:00 PM to 6:00 PM refresh window.
- Whether disposed matters with future listings should appear in date-wise PDFs.
- Representative matters/orders for UAT.

## 8. Final Risk Notes

- The strongest near-term business risk is not feature breadth; it is selling high-usage plans before real Pine Labs fees, real court-provider costs, and founder profit reports are validated with production-like data.
- The strongest adoption gap is production Google Workspace activation plus
  Drive/durable mailbox automation. The safe Gmail and Google Calendar V1
  foundations exist, but credentials, UAT, Drive import, and two-way durable
  workflows are still needed.
- The strongest security gap is MFA/SSO/agent grants. Password reset is now implemented, but enterprise-grade identity and autonomous-agent trust are not.
- The strongest reliability gap is durable provider automation. Current foundations are intentionally safe and fail-closed; turning them on requires credentials, provider terms, cost controls, audit, replay, and UAT.
