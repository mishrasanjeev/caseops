# PRD: CaseOps Gap Closure, Provider Automation, Payments, And Enterprise Readiness

Date: 2026-06-08  
Status: Draft for founder review and Codex CLI implementation planning  
Owner: CaseOps founder/product owner  
Related gap ledger: `docs/PENDING_PRD_GAP_ANALYSIS_2026-06-08.md`  

## 1. Purpose

This PRD converts the end-to-end PRD gap review into a clear implementation plan. It is meant to be shared with Codex CLI in slices so the remaining high-value gaps can be closed without reopening foundations that are already implemented.

The current product already has substantial foundations: matter workflows, AI recommendations, legal updates, case tracking, GBA Law Office flows, password reset, tenant billing, founder platform admin, usage reporting, durable in-app notification intents, ClamAV upload scanning, async audit exports, and provider-operations readiness. The remaining work is mostly about making provider automation, online payments, profitability controls, enterprise identity, and production signoff ready for real customers.

## 2. Source Documents Reviewed

This PRD is based on the latest repository inspection and the following PRDs/runbooks:

- `docs/PRD.md`
- `docs/WORK_TO_BE_DONE.md`
- `docs/PENDING_PRD_GAP_ANALYSIS_2026-06-08.md`
- `docs/PRD_ADP_LAW_FIRM_FEEDBACK_PRODUCT_ROADMAP_2026-05-22.md`
- `docs/ADP_01_TO_19_END_USER_PRODUCT_GUIDE_2026-05-25.md`
- `docs/PRD_CASEOPS_AI_ENHANCEMENTS_2026-05-26.md`
- `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`
- `docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md`
- `docs/GBA_LAW_OFFICE_USER_GUIDE_2026-06-07.md`
- `docs/runbooks/production-billing-signoff-2026-06-02.md`
- `docs/runbooks/pine-labs-uat-readiness-2026-06-02.md`
- `docs/runbooks/provider-operations-readiness-2026-06-02.md`
- `docs/runbooks/adp20-outlook-provider-readiness.md`
- `docs/runbooks/hearing-reminder-channels.md`

## 3. Current Implementation Baseline

The following items are not gaps and must not be rebuilt from scratch:

- Password reset: implemented with `/account/forgot-password`, `/account/reset-password`, API start/complete routes, anti-enumeration behavior, sign-in links, and tests.
- SaaS billing foundation: implemented pricing catalog, subscriptions, manual invoices, add-ons/top-ups, tenant invoice/download/export APIs, usage/spend reports, credit ledger, and provider-disabled checkout behavior.
- Founder-only platform admin foundation: implemented overview, company billing, profit views, exports, margin alerts, manual invoices, provider events, and role guards.
- GBA Law Office core features: implemented disposed terminology, daily tracked-case refresh window behavior, compliance extraction/review, manual court order uploads/OCR states, matter billing profiles, server-rendered invoice PDFs, next-hearing provenance, and date-wise cause-list preview/PDF.
- Durable in-app notification intents: implemented as the safe default for legal updates, case tracking, reminders, and blocked external delivery.
- Provider operations foundation: implemented `/app/admin/provider-operations` and related backend APIs for failed/blocked/dead-letter job listing and audited replay/ignore/resolve.
- ClamAV upload scanning: implemented and should remain preserved in production deployments.
- Async audit export: implemented through `AuditExportJob` and `/api/admin/audit/export/async`.
- Evaluation storage foundation: `EvaluationRun` and `EvaluationCase` exist; remaining work is governance and gating.
- Employee/custom-role administration: implemented enough that broad "team/admin user missing" should not be treated as a current gap.

## 4. Product Goals

1. Let CaseOps safely onboard paying law firms, solo lawyers, and corporate GC teams without losing money.
2. Enable first-class Google Workspace support: Gmail, Google Calendar, and Google Drive.
3. Convert provider-readiness foundations into real, auditable provider workflows only when credentials, terms, and cost controls are ready.
4. Complete Pine Labs Plural UAT and production activation gates without exposing secrets or enabling payments prematurely.
5. Strengthen founder-only and tenant-admin operations with MFA, step-up security, and future SSO readiness.
6. Add end-to-end usage, cost, margin, and provider health visibility for founder/back-office operations.
7. Preserve all legal-safety constraints: no captcha/session scraping, no secret leakage, no raw provider payload exposure to users, and no external delivery unless explicitly configured.

## 5. Non-Goals

The following are not part of this PRD unless explicitly approved in a later slice:

- No production Pine Labs enablement before UAT, settlement, fee, webhook, and founder go/no-go gates pass.
- No public refund-policy language. Internal payment adjustment/refund operations may exist, but user-facing refund policy copy remains out of scope until finance/legal approves it.
- No captcha-gated or session-gated court scraping.
- No autonomous AI agent that mutates data, sends messages, syncs providers, or spends credits before scoped agent grants exist.
- No broad external email/SMS/WhatsApp digest delivery before provider-specific approvals, opt-in rules, templates, and runbooks are complete.
- No destructive Google Drive operations. CaseOps may read/import documents, but should not delete or modify Drive files in this PRD.
- No full on-prem/private VPC deployment package in this phase.

## 6. Non-Negotiable Guardrails

Every implementation slice must follow these rules:

- Tenant isolation: every query, job, provider callback, export, and provider event must be tenant-scoped.
- Founder-only access: platform-admin pages and APIs must be accessible only to the configured platform super admin, not tenant admins.
- Secret handling: no provider token, OAuth token, webhook secret, raw signature, or API key may be returned to frontend or written to docs/logs.
- Provider-disabled behavior: missing credentials or disabled provider mode must produce safe user-facing disabled/blocked states and no provider calls.
- Cost safety: case refreshes, LLM usage, embeddings, SMS/WhatsApp, and payment provider fees must be measured before they affect pricing/profit.
- Auditability: admin actions, provider configuration changes, exports, downloads, replay/ignore/resolve, payment changes, and MFA/SSO changes must write audit events.
- Review-first mutation: inbound emails, Drive files, calendar imports, provider suggestions, and AI outputs must not silently mutate legal records without an explicit user/admin review path.
- No legal advice copy: billing/tax/TDS screens may capture values and reports, but must not provide legal or tax advice.

## 7. Personas

### Founder / Platform Super Admin

Needs:

- See all enrollments, usage, revenue, cost, profit, margin, provider events, failed jobs, and live risk.
- Configure cost assumptions, provider readiness, payment UAT evidence, and production activation gates.
- Remain the only user who can access platform-admin console.

### Tenant Owner / Law Firm Admin

Needs:

- See plan, invoices, usage, exports, AI credits, tracked-case usage, top-ups, and provider connection health.
- Connect Outlook/Microsoft 365 and Google Workspace where approved.
- Review inbound email/Drive/calendar suggestions before matter mutation.

### Lawyer / Fee Earner

Needs:

- Use email/calendar/document connectors without managing secrets.
- See what was imported, what is pending review, and where it came from.
- Avoid surprises: no silent email scraping or unexpected external notifications.

### Corporate GC Admin

Needs:

- Procurement-friendly invoices, reports, usage breakdown, audit exports, SSO path, and strong security controls.
- Clear disabled/blocked states for integrations and payments.

### Solo Lawyer

Needs:

- Affordable plans, simple Gmail/Google Calendar setup, clear top-up buying, and simple usage visibility.

## 8. Success Metrics

### Business Metrics

- Zero production Pine Labs charges before UAT/founder approval.
- No tenant with negative gross margin after configured cost assumptions are applied.
- Margin alert emitted when current-period gross margin falls below configured thresholds.
- Founder can export profit, usage, payment, provider event, and enrollment reports.

### Product Metrics

- Tenant admin can connect Google Workspace in disabled/mock/UAT-safe mode without secret leakage.
- Tenant admin can see health of Outlook, Gmail, Google Calendar, Drive, Pine Labs, SendGrid, SMS/WhatsApp, case provider, PRS/legal updates, Temporal, ClamAV, and storage.
- Users can review inbound email/Drive/calendar suggestions before creating matter artifacts.
- Users can see usage and purchase add-on/top-up credits without internal cost leakage.

### Security Metrics

- Platform admin routes return 403 for tenant admins and unauthenticated users.
- MFA can be enforced for founder/platform admin and later for existing tenant users.
- SSO can be piloted for one enterprise tenant without breaking local password login.
- Provider tokens are encrypted or stored only in approved secret storage.

### Quality Metrics

- Every gap closure slice adds route/service tests and frontend tests where UI is changed.
- Every provider integration has disabled-state tests, bad-signature tests if webhook based, replay/idempotency tests, and cross-tenant tests.
- AI prompt/model changes require evaluation evidence once the evaluation gate is implemented.

## 9. Gap Closure Epics

## Epic A: Production Billing, Profit Safety, And Pine Labs Readiness

Priority: P0  
Primary users: Founder, tenant admin, finance/back office  
Related gaps: GAP-007, GAP-008, GAP-009, GAP-010, GAP-021  

### A1. Production Billing Signoff

Problem:

The billing system is implemented, but founder-authenticated production signoff is still pending.

Requirements:

- Complete the production billing signoff runbook using the configured founder email.
- Verify `/app/platform-admin` and `/app/platform-admin/profit` load only for founder.
- Verify tenant admin receives 403 on platform-admin routes.
- Verify tenant billing page, usage/spend, invoice download, statement download, payment export, credit ledger export, and spend export.
- Verify Pine Labs disabled checkout shows provider-disabled status and does not activate paid entitlements.
- Verify exports/downloads write audit events.
- Capture evidence in the production billing signoff runbook without adding secrets.

Acceptance criteria:

- Founder can access platform-admin and profit pages.
- Non-founder tenant admin cannot access platform-admin pages or APIs.
- Tenant-visible reports exclude internal cost, profit, provider fees, and margin.
- Disabled checkout creates no real provider call and no paid activation.
- Runbook has completed evidence rows and date/time of signoff.

### A2. Pine Labs Plural UAT

Problem:

Pine Labs code exists, but production payments must remain disabled until UAT passes.

Requirements:

- Collect Pine Labs UAT credentials and details through approved secret handling.
- Configure UAT mode only in a non-production/UAT environment.
- Register UAT webhook URL.
- Confirm exact endpoint paths and schemas for orders, payment links, payment status, subscriptions, mandates, refunds, and settlements.
- Confirm event names and sample payloads.
- Run UAT scenarios:
  - plan payment success
  - plan payment failure
  - pending then paid
  - cancelled checkout
  - timeout
  - duplicate webhook
  - out-of-order webhook
  - webhook bad signature
  - webhook replay
  - callback without webhook
  - top-up purchase
  - manual invoice payment link if supported
  - refund event if enabled internally
  - settlement report reconciliation
  - subscription/mandate lifecycle if subscriptions are enabled
- Keep production `CASEOPS_PINE_LABS_ENV=disabled` until founder approval.

Acceptance criteria:

- All UAT scenarios pass with evidence.
- No real production Pine Labs call is made.
- Webhook verification fails closed for bad signatures.
- Duplicate and replay events are idempotent.
- Production activation checklist has founder go/no-go field.

### A3. Provider Cost And Margin Guardrails

Problem:

Pricing can become unprofitable if actual case refresh, LLM, embedding, payment, SMS/WhatsApp, or storage costs exceed assumptions.

Requirements:

- Add platform-admin configurable provider cost profiles.
- Support at least these cost categories:
  - case refresh per provider/source
  - payment MDR by method
  - fixed payment fee
  - LLM cost per credit/model/token tier
  - embedding cost
  - document processing/page cost
  - storage cost
  - SMS cost
  - WhatsApp cost
  - manual support/research cost
- Preserve current default values until real data is configured.
- Add margin simulation for every active plan and company:
  - target case
  - stress case
  - actual configured cost
- Add margin thresholds:
  - watch below 60 percent gross margin
  - danger below 50 percent gross margin
  - loss risk below 0 profit or below configured danger threshold
- Add explicit warning if actual case refresh cost is Rs 0.10 or more per tracked-case refresh equivalent.
- Add back-office setting to pause public sale of selected high-volume plans if cost threshold is breached.

Suggested data model:

- `provider_cost_profiles`
  - `id`
  - `provider_key`
  - `cost_type`
  - `currency`
  - `unit`
  - `cost_minor`
  - `cost_bps`
  - `fixed_fee_minor`
  - `effective_from`
  - `effective_until`
  - `source`
  - `notes`
  - `created_by_platform_admin_id`
  - `created_at`
- `billing_margin_simulations`
  - `id`
  - `company_id`
  - `plan_key`
  - `scenario`
  - `revenue_minor`
  - `estimated_variable_cost_minor`
  - `gross_profit_minor`
  - `gross_margin_bps`
  - `risk_level`
  - `inputs_json`
  - `created_at`

API requirements:

- `GET /api/platform-admin/cost-profiles`
- `POST /api/platform-admin/cost-profiles`
- `PATCH /api/platform-admin/cost-profiles/{id}`
- `GET /api/platform-admin/margin-simulations`
- `POST /api/platform-admin/margin-simulations/run`
- `GET /api/platform-admin/margin-alerts`

UI requirements:

- Add platform admin cost settings page.
- Show current/default/actual cost assumption labels.
- Show plan-level and tenant-level margin simulation.
- Show warnings before manual discount, custom entitlement, or high-volume tracking approval.

Acceptance criteria:

- Founder can configure provider costs.
- Tenant admins cannot view internal cost profiles.
- Profit reports use actual configured cost when present and fallback defaults otherwise.
- Tenant-visible usage remains free of internal margin/cost fields.

### A4. TDS, GST, And Manual Payment Operations

Problem:

Manual invoices and TDS amounts are supported, but operational treatment must follow Indian law and accountant-approved workflows without hardcoded advice.

Requirements:

- Keep company GSTIN as configured: `09AANCM5923C1ZD`.
- Record TDS deducted amount, payment reference, PO number, attachment metadata, and paid date for manual invoices.
- Do not hardcode legal advice or fixed TDS rates.
- Add internal export fields needed for accountant reconciliation:
  - invoice number
  - GSTIN
  - taxable amount
  - GST amount
  - amount received
  - TDS deducted
  - net outstanding
  - payment reference
  - PO number
  - payment date
  - customer GSTIN if provided
- Keep refund-policy copy out of product unless approved.

Acceptance criteria:

- Platform admin can create and mark manual invoices paid with TDS amount.
- Tenant can download invoice/statement where tenant-scoped.
- Founder can export TDS/GST payment reconciliation data.
- No screen gives tax/legal advice.

## Epic B: Google Workspace And Connector Foundation

Priority: P1  
Primary users: law firm admin, solo lawyer, tenant admin  
Related gaps: GAP-001, GAP-003, GAP-005, GAP-006  

### B1. Unified Connector Registry

Problem:

Provider operations is job-centric and not a complete integrations command center.

Requirements:

- Add a connector registry that supports:
  - Outlook calendar
  - Microsoft mailbox readiness
  - Gmail
  - Google Calendar
  - Google Drive
  - Pine Labs
  - SendGrid email
  - SMS provider
  - WhatsApp provider
  - case tracking provider
  - PRS/legal update source
  - Temporal durable workflows
  - ClamAV
  - storage
- Each connector must expose:
  - connector key
  - display name
  - category
  - provider
  - enabled/disabled/configured/blocked/healthy/degraded status
  - tenant approval status
  - required config names only, not values
  - scopes requested
  - connection owner
  - last success
  - last failure
  - next scheduled run
  - webhook status
  - token expiry if applicable
  - provider operations link
  - runbook link
  - cost risk if applicable
- Add tenant admin UI at `/app/admin/integrations`.
- Add founder UI at `/app/platform-admin/integrations` with all tenants and internal cost/provider status.

Acceptance criteria:

- Tenant admin sees only tenant-safe connector data.
- Founder sees all tenants and internal provider/cost readiness.
- No secret values are returned.
- Disabled providers show clear next steps.

### B2. Google Workspace OAuth Foundation

Problem:

CaseOps has no product-grade Google connector despite customer need for Gmail and Google Workspace.

Requirements:

- Add Google OAuth provider support.
- Support local/UAT/production redirect URIs.
- Store encrypted refresh/access token material or token references according to existing secret pattern.
- Record scopes requested and approved.
- Support tenant-admin connection and per-user connection design.
- Add disconnect/revoke path.
- Add health check that validates token without exposing token.
- Add audit events for connect, refresh, disconnect, failed refresh, and scope changes.
- Add disabled state when Google OAuth config is missing.

Suggested model:

- `provider_connections`
  - `id`
  - `company_id`
  - `membership_id`
  - `provider`
  - `connector_key`
  - `connection_type`
  - `status`
  - `scopes_json`
  - `token_ciphertext`
  - `token_expires_at`
  - `refresh_token_ciphertext`
  - `external_account_id`
  - `external_account_email`
  - `last_checked_at`
  - `last_success_at`
  - `last_failure_at`
  - `failure_code`
  - `failure_message_redacted`
  - `created_at`
  - `updated_at`

API requirements:

- `GET /api/provider-connections`
- `GET /api/provider-connections/readiness`
- `GET /api/provider-connections/google/start`
- `GET /api/provider-connections/google/callback`
- `POST /api/provider-connections/{id}/refresh`
- `DELETE /api/provider-connections/{id}`

Acceptance criteria:

- Google connect starts only when credentials are configured.
- Callback verifies state and tenant binding.
- Tokens are not returned to frontend.
- Disconnect revokes local use and audits action.

### B3. Gmail Read-Only Connector V1

Problem:

Law firms need Gmail support for email workflows.

Requirements:

- Add Gmail read-only connector after Google OAuth foundation.
- Initial scope should be metadata/snippet-focused and review-first.
- Ingest only:
  - message ID
  - thread ID
  - mailbox account
  - sender/recipient metadata
  - subject
  - date
  - small safe snippet
  - labels
  - attachment metadata
  - provider history ID
- Do not store full raw body in V1 unless explicitly approved.
- Add search/filter UI for imported Gmail threads.
- Add matter-match suggestions.
- Add review actions:
  - link thread to existing matter
  - create communication log entry
  - import selected attachments
  - ignore thread
  - mark as reviewed
- Add dedupe by provider message/thread IDs.
- Add audit events for every import/review/action.

Suggested model:

- `mailbox_connections`
- `mailbox_threads`
- `mailbox_messages`
- `mailbox_attachments`
- `mailbox_review_items`

API requirements:

- `GET /api/mailbox/connections`
- `GET /api/mailbox/google/start`
- `GET /api/mailbox/google/callback`
- `POST /api/mailbox/sync`
- `GET /api/mailbox/review-items`
- `POST /api/mailbox/review-items/{id}/link-matter`
- `POST /api/mailbox/review-items/{id}/import-attachments`
- `POST /api/mailbox/review-items/{id}/ignore`

UI requirements:

- Add `/app/admin/integrations/gmail` or integration detail panel.
- Add `/app/mailbox/review` for lawyer/admin review.
- Show status: connected, disabled, sync pending, sync failed, token expired, review required.

Acceptance criteria:

- Gmail connector works in disabled/mock/local-safe mode without real provider calls.
- With mock provider, sync creates review items and does not mutate matters until user approves.
- Cross-tenant access tests pass.
- Raw token/body/payload leakage tests pass.

### B4. Google Calendar Provider V1

Problem:

Google Workspace users need first-class calendar sync, not just ICS export.

Requirements:

- Add Google Calendar provider behind the calendar provider abstraction.
- Support CaseOps-to-Google hearing sync first.
- Support create/update/cancel event behavior for hearings.
- Store external calendar event ID and sync status.
- Reuse existing calendar sync patterns where possible.
- Show conflicts/status in the calendar UI.
- Keep Google-to-CaseOps import out of V1 unless review-gated.

Acceptance criteria:

- Tenant admin can connect Google Calendar if OAuth configured.
- Hearing sync can create/update Google Calendar event in mock provider tests.
- Disabled state shows safe message when credentials missing.
- Existing Outlook sync remains working.

### B5. Google Drive Import Commit And Sync V1

Problem:

Current Google Drive import is dry-run only.

Requirements:

- Add Drive OAuth scopes after Google OAuth foundation.
- Add folder picker or folder ID entry with validation.
- Preserve dry-run as first step.
- Add commit flow:
  - user selects files/folders from dry-run
  - system fetches selected files
  - creates matter attachments
  - queues document processing
  - dedupes by Drive file ID, file version, checksum
  - records audit/source lineage
- Add sync status and review queue.
- Add webhook/polling only after initial commit path is safe.
- Never delete or modify Drive files.

Acceptance criteria:

- Dry-run remains available.
- Commit imports selected files only.
- Duplicate Drive file imports are idempotent.
- Cross-tenant tests prevent access to other tenant Drive imports.
- Provider-disabled state makes no provider calls.

## Epic C: Durable Mailbox, Outlook, And Provider Automation

Priority: P1  
Primary users: tenant admin, lawyers, operations  
Related gaps: GAP-002, GAP-004, GAP-017  

### C1. Provider-Agnostic Mailbox Ingestion

Requirements:

- Implement mailbox connector abstraction for Microsoft 365 and Gmail.
- Support polling first; provider webhooks later.
- Store provider message/thread IDs and safe metadata.
- Enforce per-tenant and per-connection sync limits.
- Add sync cursors.
- Add idempotency on provider IDs.
- Add dead-letter/replay entries through provider operations.
- Add review-first matter mutation.

Acceptance criteria:

- Mock Microsoft and mock Gmail providers pass the same contract tests.
- Sync can resume from cursor.
- Failed jobs appear in provider operations.
- Replay does not duplicate messages or attachments.

### C2. Microsoft 365 Mailbox Readiness

Requirements:

- Extend existing Outlook/Microsoft app readiness to support mailbox scopes.
- Add Microsoft Graph mail read scopes only after explicit tenant/admin approval.
- Add read-only mailbox metadata ingestion.
- Do not merge Outlook calendar and mailbox permissions silently; show separate scope consent.

Acceptance criteria:

- Existing Outlook calendar connection is not broken.
- Microsoft mailbox provider disabled state is clear.
- Scope changes are audited.

### C3. Outlook Durable Calendar Completion

Requirements:

- Convert readiness-gated CaseOps-to-Outlook hearing sync into production durable sync only after tenant readiness passes.
- Add job status and retry through provider operations.
- Add Graph webhook subscription only after provider readiness and tenant approval.
- Keep Outlook-to-CaseOps import review-gated.
- Add conflict review UI for inbound calendar differences.

Acceptance criteria:

- Tenant readiness gate blocks all provider calls until complete.
- Sync creates/updates hearing events in provider mock.
- Inbound provider changes appear as review items, not silent matter mutations.

### C4. Temporal Workflow Porting Plan

Requirements:

- Port non-notification workflows gradually:
  - document ingestion
  - court/case tracking poll
  - drafting generation
  - hearing pack generation
  - recommendations
- Each workflow must define:
  - task queue
  - retry policy
  - timeout
  - idempotency key
  - versioning strategy
  - audit events
  - provider-operation/dead-letter visibility where relevant
- Old polling must remain until replacement is proven.

Acceptance criteria:

- First workflow port has tests and runbook.
- Worker disabled-state remains safe.
- No workflow starts when Temporal config is missing unless explicitly using fallback mode.

## Epic D: External Notifications And Digest Delivery

Priority: P1  
Primary users: lawyers, tenant admins, founder  
Related gaps: GAP-014  

### D1. Notification Preference Center

Requirements:

- Add user notification preferences:
  - in-app
  - email digest
  - immediate email
  - SMS
  - WhatsApp
- Add per-event preferences:
  - hearing reminders
  - case tracking update
  - legal update/watchlist match
  - compliance item created
  - billing invoice/payment reminder
  - provider failure/admin alert
- Default all external channels off unless explicitly enabled.
- Add company-level defaults and user overrides.

Acceptance criteria:

- Users can view/edit preferences.
- External channels are unavailable unless provider configured.
- In-app remains default safe channel.

### D2. Legal Update And Judgment Digest Email

Requirements:

- Add email digest generation for judgment/legal update alerts.
- Use SendGrid only when configured and verified.
- Use templates approved by founder/admin.
- Honor suppression/unsubscribe and tenant preferences.
- Add retry/dead-letter/provider operations.
- Do not include confidential internal cost/profit or raw provider payloads.

Acceptance criteria:

- Digest preview remains available in-app.
- Email sends only when preference and provider config allow.
- Failed/suppressed sends are visible and auditable.

### D3. SMS And WhatsApp Gating

Requirements:

- Keep SMS/WhatsApp disabled unless provider agreement, templates, opt-in, and cost limits are complete.
- Add founder-only cost guardrail for SMS/WhatsApp.
- Add per-tenant monthly message limits.
- Add DLT/template/consent status fields if India provider requires them.

Acceptance criteria:

- Disabled SMS/WhatsApp records do not burn provider cost.
- Enabling requires explicit platform-admin configuration.

## Epic E: MFA, Step-Up Security, And SSO

Priority: P1  
Primary users: founder, tenant admins, enterprise customers  
Related gaps: GAP-011, GAP-012  

### E1. MFA Foundation

Requirements:

- Implement TOTP MFA enrollment.
- Add recovery codes.
- Add MFA challenge during login when required.
- Add MFA reset process for tenant owner/admin with audit.
- Add founder/platform-admin MFA enforcement.
- Add company-level MFA policy.
- Add forced enrollment for existing users after grace period.
- Add backup flow for users who lose device.

Suggested model:

- `user_mfa_factors`
- `user_mfa_recovery_codes`
- `mfa_challenges`
- `company_security_policies`

API requirements:

- `POST /api/auth/mfa/enroll/start`
- `POST /api/auth/mfa/enroll/verify`
- `POST /api/auth/mfa/challenge/verify`
- `POST /api/auth/mfa/recovery-code/verify`
- `DELETE /api/auth/mfa/factors/{id}`
- `GET /api/company/security-policy`
- `PATCH /api/company/security-policy`

UI requirements:

- Account security page.
- Admin security policy page.
- Login MFA challenge screen.
- Recovery code display/download once at enrollment.

Acceptance criteria:

- Platform-admin access requires MFA when founder policy enabled.
- Existing users can be forced into MFA enrollment.
- Recovery codes are hashed, not stored in plaintext.
- MFA bypass and replay tests pass.

### E2. Step-Up Authentication

Requirements:

- Require recent auth/MFA challenge for high-risk actions:
  - platform-admin cost configuration
  - Pine Labs production enablement
  - manual invoice marked paid
  - refund/payment adjustment
  - provider credential changes
  - MFA policy changes
  - SSO provider config changes
  - bulk export of sensitive audit/provider data
- Add `reauth_required` response pattern.
- Add UI modal for step-up challenge.

Acceptance criteria:

- High-risk route rejects stale sessions.
- Successful step-up is time-limited.
- Audit event records step-up use without storing secret values.

### E3. OIDC SSO Pilot

Requirements:

- Implement tenant OIDC provider config.
- Support domain-based SSO routing.
- Support JIT provisioning.
- Map claims/groups to CaseOps roles/capabilities.
- Preserve local password login unless tenant policy requires SSO-only.
- Add audit events for SSO login/config changes.

API requirements:

- `GET /api/company/sso/providers`
- `POST /api/company/sso/providers/oidc`
- `PATCH /api/company/sso/providers/{id}`
- `DELETE /api/company/sso/providers/{id}`
- `GET /api/auth/sso/start`
- `GET /api/auth/sso/callback`

Acceptance criteria:

- One mock OIDC provider test passes end to end.
- JIT user is created only for allowed domain/provider.
- Role mapping cannot grant founder/platform-admin.

### E4. SAML And SCIM Deferred Readiness

Requirements:

- Document SAML and SCIM requirements, but implementation can follow OIDC pilot.
- Add data model fields that do not block later SAML.
- Avoid marketing SAML as live until implemented.

Acceptance criteria:

- OIDC does not require schema rewrites for later SAML.

## Epic F: AI Evaluation Gate And Agent Trust Plane

Priority: P1  
Primary users: founder, engineers, future agent users  
Related gaps: GAP-013, GAP-015, GAP-016  

### F1. Evaluation Dashboard And Release Gate

Requirements:

- Add admin/founder evaluation dashboard.
- Show:
  - suite name
  - model/provider
  - prompt hash
  - workflow
  - pass/fail
  - citation accuracy
  - extraction accuracy
  - hallucination flags
  - latency
  - token cost
  - sample failures
  - approval status
- Require evaluation evidence for production prompt/model changes.
- Add CI job or local script that fails when prompt/model changes lack a passing eval marker.

Acceptance criteria:

- Eval runs are visible.
- Failed eval blocks release gate.
- Approval is audited.

### F2. Per-Workflow Golden Sets

Requirements:

- Add golden test/eval sets for:
  - recommendations
  - drafting
  - hearing packs
  - matter file QA
  - compliance extraction
  - legal update summaries
  - case update summaries
  - statute enrichment
- Track costs and latency.
- Add red-team tests for prompt injection and data exfiltration.

Acceptance criteria:

- Each AI workflow has at least one golden suite.
- CI can run fixture-only mode without provider calls.

### F3. Agent Trust Plane

Requirements:

- Implement minimal Grantex-equivalent internal model before autonomous agent actions.
- Add:
  - `AgentGrant`
  - `AgentExecution`
  - `AgentToolCall`
  - `HumanApproval`
- Grants must include:
  - company ID
  - membership/user owner
  - scopes
  - target matter IDs or tenant-wide flag where approved
  - expiry
  - budget/credit limit
  - status
  - revocation timestamp
  - created_by
- Tool calls must record:
  - grant ID
  - execution ID
  - tool name
  - input hash/redacted summary
  - output hash/redacted summary
  - cost estimate
  - success/failure
  - approval ID if required

Acceptance criteria:

- Agent cannot call a tool without a valid unexpired grant.
- Agent cannot cross tenant/matter scope.
- Budget exhaustion blocks tool calls.
- Human approval required actions block until approved.
- Revoked grants stop future tool calls.

## Epic G: Court Provider Coverage, Source Matrix, And GBA Signoff

Priority: P1  
Primary users: founder, GBA, law firm admins  
Related gaps: GAP-018, GAP-019  

### G1. Court/Provider Support Matrix

Requirements:

- Add a support matrix for court/case/legal sources:
  - source key
  - provider
  - jurisdiction
  - court/forum
  - feature coverage
  - access mode
  - captcha/session gated flag
  - legal basis/license
  - cost model
  - status
  - last verified
  - runbook
- Expose tenant-safe version to admins.
- Expose platform internal version with cost and risk to founder.

Acceptance criteria:

- No captcha/session-gated source is marked enabled.
- Provider-disabled state is visible.
- Cost/risk is founder-only where sensitive.

### G2. Case Tracking Provider Activation Readiness

Requirements:

- Collect real provider details:
  - API base URL
  - auth method
  - supported search modes
  - bulk refresh support
  - per-call/per-refresh cost
  - rate limits
  - terms on storing payloads, order PDFs, and summaries
  - coverage by jurisdiction
- Add mock tests for all provider contract behaviors.
- Add cost gating before high-volume plans.

Acceptance criteria:

- Case tracking remains disabled without valid provider config.
- Provider calls are counted and billed/costed.
- Raw provider payloads are not exposed to users.

### G3. GBA UAT And Exact Formatting

Requirements:

- Collect from GBA:
  - sample cause-list PDF
  - logo/header assets
  - exact firm name/address/header
  - case-number/CNR field preference
  - advocate/appearing counsel source
  - courts/providers for daily refresh
  - whether disposed matters with future listings appear
  - representative matters/orders
- Create GBA UAT checklist.
- Run UAT with representative data.
- If sample PDF differs, add profile-based PDF formatting.

Acceptance criteria:

- GBA signs off cause-list PDF formatting.
- GBA signs off billing invoice PDF format.
- GBA signs off daily refresh/provider disabled behavior.
- GBA signs off compliance extraction review flow.

## Epic H: Test Coverage, UAT Matrix, And Release Operations

Priority: P1  
Primary users: founder, engineering, support  
Related gaps: GAP-020, GAP-021  

### H1. PRD-To-Test Coverage Matrix

Requirements:

- Create a matrix listing every active PRD requirement and its test coverage.
- Columns:
  - PRD file
  - section
  - requirement
  - implementation status
  - backend test
  - frontend test
  - Playwright/E2E test
  - live UAT required
  - provider credentials required
  - owner
  - notes
- Mark stale/closed items clearly.

Acceptance criteria:

- Matrix exists in docs.
- Each P0/P1 current gap has a test plan.

### H2. End-To-End UAT Scenarios

Requirements:

- Add or document UAT scenarios for:
  - solo signup, billing, usage, top-up, invoice download
  - law firm admin billing and provider disabled checkout
  - founder platform admin profit/export smoke
  - GBA cause-list PDF
  - GBA matter invoice PDF
  - Gmail disabled/mock connector
  - Google Calendar disabled/mock connector
  - Google Drive dry-run/commit mock
  - mailbox review item to matter communication
  - MFA enrollment/login
  - OIDC login
  - Pine Labs UAT payment success/failure
  - case tracking provider-disabled and mock update

Acceptance criteria:

- P0/P1 flows have automated or manual UAT evidence.
- Provider-live tests are explicitly marked blocked until credentials exist.

### H3. Production Readiness Report

Requirements:

- For each release slice, produce a short readiness report:
  - branch and commit
  - files changed
  - migrations
  - tests run
  - disabled/provider state
  - secrets touched or not touched
  - rollout flags
  - rollback plan
  - caveats

Acceptance criteria:

- No provider or payment release goes to production without readiness report.

## 10. Detailed Implementation Sequencing

### Slice 0: Documentation And Signoff Prep

Purpose:

- Convert this PRD into a ready implementation plan and confirm current gaps.

Deliverables:

- This PRD.
- Gap ledger cross-linked.
- Founder decision list.

### Slice 1: Founder Billing Signoff And Profit Safety

Deliverables:

- Complete production billing signoff.
- Add any missing runbook evidence fields.
- Add cost-profile/margin simulation foundation if not present.
- Validate tenant/founder usage reports with production-like data.

Exit criteria:

- Founder signs off billing/admin console.
- No internal cost leakage.
- Provider-disabled Pine checkout verified.

### Slice 2: Pine Labs UAT

Deliverables:

- UAT credentials configured outside repo.
- UAT webhook registered.
- UAT payment scenarios passed.
- Settlement/refund/MDR details captured.
- Production activation remains disabled until founder approval.

Exit criteria:

- Founder approves or explicitly keeps payments disabled with known blockers.

### Slice 3: Connector Registry And Google OAuth

Deliverables:

- Unified integrations dashboard.
- Google OAuth connection foundation.
- Connector health/readiness APIs.
- Secret-safe audit and tests.

Exit criteria:

- Tenant admin can see Google disabled/configured status.
- No token/secret leaks.

### Slice 4: Gmail And Google Calendar V1

Deliverables:

- Gmail metadata/snippet ingestion with review queue.
- Google Calendar CaseOps-to-provider sync.
- Mock provider tests and disabled-state UI.

Exit criteria:

- Gmail/Calendar mock flows work end to end.
- No automatic matter mutation without review.

### Slice 5: Google Drive Commit And Mailbox Automation

Deliverables:

- Drive dry-run-to-commit import.
- Provider-agnostic mailbox sync abstraction.
- Outlook/Microsoft mailbox readiness.
- Provider operations replay/dead-letter integration.

Exit criteria:

- Review-first import and mailbox flows pass tests.

### Slice 6: MFA And OIDC SSO

Deliverables:

- TOTP MFA.
- Recovery codes.
- Founder/platform-admin MFA enforcement.
- Step-up auth for high-risk actions.
- OIDC pilot.

Exit criteria:

- Founder can enforce MFA.
- Mock OIDC login passes.

### Slice 7: AI Evaluation And Agent Grants

Deliverables:

- Evaluation dashboard and release gate.
- Per-workflow golden suite baseline.
- Agent grant/execution/tool-call model.

Exit criteria:

- AI model/prompt changes can be gated.
- No agent tool call runs without scoped grant.

### Slice 8: Court Provider And GBA UAT

Deliverables:

- Court/provider support matrix.
- Provider cost and coverage proof.
- GBA UAT checklist and signoff.
- Profile PDF formatting if required.

Exit criteria:

- GBA signs off representative workflows.
- High-volume case tracking sale is allowed only if cost thresholds are safe.

## 11. Data And API Security Requirements

### Tenant Isolation

- Every new table with tenant data must include `company_id`.
- Provider callbacks must resolve tenant through stored state or provider reference and verify it before mutation.
- Cross-tenant tests must exist for every new route.

### Secret Storage

- OAuth refresh tokens must be encrypted or stored via approved secret mechanism.
- Secrets must not be logged.
- Redacted config names may be shown, values may not.

### Webhooks

- Verify signature where provider supports it.
- Store provider event ID.
- Idempotently ignore duplicate events.
- Preserve raw payload only in internal table if needed and never show to tenant users.
- Record unknown events for founder/provider event review.

### Audit Events

Audit these actions:

- provider connect/disconnect
- OAuth callback success/failure
- token refresh failure
- mailbox sync start/end/failure
- Drive dry-run/commit/import
- calendar sync/replay
- payment UAT/activation changes
- cost profile changes
- margin simulation run
- MFA enrollment/reset/disable
- SSO config changes
- agent grant create/revoke/use
- export/download actions

## 12. UI Requirements

### Tenant Admin

Add or enhance:

- `/app/admin/integrations`
- Gmail connection panel
- Google Calendar connection panel
- Google Drive connection/import panel
- Mailbox review queue
- Billing usage/spend and export pages where needed
- Security policy/MFA page
- SSO config page when enterprise tier allows it

Tenant UI must not show:

- internal provider cost
- gross margin
- platform profit
- Pine Labs secrets/raw events
- OAuth tokens
- raw provider payloads

### Platform Admin

Add or enhance:

- `/app/platform-admin/integrations`
- `/app/platform-admin/costs`
- `/app/platform-admin/margin-simulations`
- `/app/platform-admin/pine-labs-uat`
- `/app/platform-admin/evaluations`
- `/app/platform-admin/source-matrix`
- `/app/platform-admin/security`

Platform admin UI must remain founder-only.

## 13. External Inputs Needed

### Pine Labs

Needed before UAT:

- UAT base URL.
- Production base URL.
- UAT merchant ID.
- Production merchant ID.
- Client ID and client secret.
- Webhook signing secret.
- Signature header names and algorithm.
- Webhook ID and timestamp header names.
- Hosted checkout/order endpoint paths.
- Payment link endpoint paths.
- Payment status endpoint paths.
- Subscription/mandate endpoint paths if subscriptions are enabled.
- Refund endpoint/status path if refunds are internally enabled.
- Settlement report/API schema.
- Event names and sample payloads.
- Test cards, UPI IDs, netbanking fixtures.
- MDR by method.
- Fixed fees.
- GST on MDR treatment.
- Settlement cycle.
- Refund and chargeback fees.
- Transaction limits.
- Confirmation on convenience fee/MDR pass-through.
- Product enablement confirmation.

### Google Workspace

Needed before Google connector:

- Google Cloud project.
- OAuth client ID/secret.
- Authorized redirect URIs.
- Gmail API enabled.
- Google Calendar API enabled.
- Google Drive API enabled.
- Pub/Sub setup if watch/webhooks are used.
- OAuth verification and approved scopes.
- Decision: tenant-admin consent, per-user consent, or both.
- Decision: Gmail body storage policy.

### Microsoft 365

Needed before durable Microsoft mailbox automation:

- App registration confirmation.
- Delegated vs application permissions decision.
- Mail read scope approval.
- Calendar scope confirmation.
- Tenant admin consent process.
- Graph webhook validation process.
- Subscription renewal rules.

### Court/Case Provider

Needed before broad case tracking sale:

- Provider contract/legal basis.
- API base URL.
- Auth method.
- Supported search modes.
- Bulk refresh capabilities.
- Per-call/per-refresh pricing.
- Rate limits.
- Coverage by court/jurisdiction.
- Storage rights for payloads, PDFs, and summaries.
- Webhook support.
- Error code mapping.

### GBA

Needed before GBA signoff:

- Sample cause-list PDF.
- Logo/header assets.
- Exact firm header details.
- Case-number/CNR field expectations.
- Advocate/appearing counsel source.
- Required courts/providers.
- Disposed-matter inclusion decision.
- Representative UAT matters/orders.

## 14. Testing Requirements

### Backend Tests

Required for every new backend slice:

- route authorization
- tenant isolation
- disabled provider state
- configured/mock provider success
- provider failure
- idempotency/dedupe
- audit event creation
- no secret/raw payload leakage
- migration upgrade/downgrade where applicable

### Frontend Tests

Required for UI slices:

- loading state
- disabled state
- empty state
- error state
- success state
- permission denied state
- no internal cost leakage to tenant UI
- founder-only platform pages

### E2E / UAT

Required for P0/P1 release readiness:

- founder platform admin smoke
- tenant billing smoke
- Google connector disabled/mock smoke
- mailbox review flow
- Drive import flow
- MFA enrollment/login
- Pine UAT smoke when credentials exist
- GBA representative workflow

## 15. Rollout And Feature Flags

Every provider feature must support these states:

- disabled
- configured
- mock
- uat
- production
- blocked
- degraded

Feature flags or config gates required:

- Google OAuth enabled
- Gmail connector enabled
- Google Calendar sync enabled
- Google Drive commit enabled
- Microsoft mailbox enabled
- provider webhooks enabled
- external email digest enabled
- SMS enabled
- WhatsApp enabled
- Pine Labs UAT enabled
- Pine Labs production enabled
- MFA required
- SSO enabled
- agent actions enabled

Production defaults:

- New provider features default disabled.
- External notifications default disabled except already-approved paths.
- Pine Labs production remains disabled until founder approval.
- Agent actions remain disabled until grant model exists.

## 16. Rollback Requirements

Each slice must define rollback:

- database downgrade path or documented irreversible-safe migration
- feature flag disable path
- provider credential revocation path
- worker disable path
- queue/drain behavior
- data cleanup for failed import where possible

Specific rollback examples:

- Gmail connector: disable sync, revoke local token usage, preserve imported review items.
- Google Drive: disable commit, preserve already imported attachments, stop polling.
- Pine Labs: set environment to disabled, stop provider calls, keep local order history.
- MFA: emergency founder recovery process must be documented before enforcement.
- SSO: local password fallback for tenant owners unless SSO-only was explicitly enabled with recovery.

## 17. Founder Decisions Needed

1. Should Google Workspace be implemented as both Gmail and Google Calendar in the first Google slice, or Gmail first?
2. Should Google OAuth be tenant-admin consent, per-user consent, or both?
3. For Gmail V1, should CaseOps store full email bodies, or only metadata/snippets plus attachment metadata until review?
4. Which case tracking provider will be used for real CNR/case refresh pricing?
5. Is Pine Labs UPI AutoPay/subscription mandate required for launch, or can manual renewal/payment links be used first?
6. Should MFA be mandatory for founder/platform admin immediately after implementation?
7. Which enterprise SSO should be first: OIDC only, or OIDC plus SAML?
8. Should external digests start with email only, leaving SMS/WhatsApp for later?
9. Which customer gets first live connector UAT: internal founder tenant, GBA, or a separate smoke tenant?
10. Should high-volume case tracking plans remain hidden until real provider cost is configured?

## 18. Final Acceptance Criteria For This PRD

This PRD is complete when:

- Billing signoff is completed or blockers are explicitly recorded.
- Pine Labs UAT is completed before any production payment enablement.
- Real provider costs are configured or high-volume plans remain guarded.
- Google Workspace foundation is implemented with Gmail, Google Calendar, and Drive paths at least in disabled/mock/review-first mode.
- Durable mailbox ingestion supports Gmail and Microsoft through a shared abstraction.
- Connector health dashboard exists for tenant admins and founder.
- MFA works and can be enforced for existing users.
- OIDC SSO pilot works for one tenant.
- External digests have email-first provider-gated delivery and preferences.
- AI evaluation gate prevents ungated production prompt/model changes.
- Agent actions are impossible without scoped grants.
- Court/source support matrix is accurate and avoids captcha/session-gated automation.
- GBA UAT inputs are collected and signed off.
- P0/P1 PRD requirements have tests, UAT evidence, or explicit provider-blocked status.

## 19. First Recommended Codex CLI Implementation Slice

The first build slice after this PRD should be:

1. Complete founder production billing signoff evidence where possible.
2. Add provider cost profile and margin simulation foundation if missing.
3. Add `/app/admin/integrations` and `/app/platform-admin/integrations` connector registry using existing readiness data.
4. Keep all new provider features disabled/fail-closed.
5. Add tests proving tenant-safe vs founder-only visibility and no internal cost leakage.

Reason:

This slice improves profitability safety and operational visibility before adding more provider automation that can spend money or create customer-facing commitments.
