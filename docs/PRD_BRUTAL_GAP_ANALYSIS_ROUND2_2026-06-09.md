# PRD: Brutal CaseOps Gap Analysis - Round 2 - 2026-06-09

## 1. Document Control

- Product: CaseOps
- Date: 2026-06-09
- Review type: Brutal release-readiness and PRD-gap analysis
- Authoring basis: Local repository scan, existing PRDs, ADP documents, GBA Law Office PRD/docs, billing/Pine Labs runbooks, provider-operations runbooks, `WORK_TO_BE_DONE.md`, current route/page/service implementation markers, and the previously created brutal gap file.
- Output purpose: Create a precise gap PRD that Codex CLI can use to plan the next implementation prompts without reopening work that is already implemented.
- Tone: Intentionally strict. This is not a sales document.

## 2. Method Used

This pass did not rely only on the old gap documents. It cross-checked:

- Current git state and recent commits.
- All docs under `docs/`, especially:
  - `docs/PENDING_PRD_GAP_ANALYSIS_2026-06-08.md`
  - `docs/PRD_CASEOPS_GAP_CLOSURE_2026-06-08.md`
  - `docs/WORK_TO_BE_DONE.md`
  - `docs/ADP_01_TO_19_END_USER_PRODUCT_GUIDE_2026-05-25.md`
  - `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`
  - `docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md`
  - `docs/runbooks/production-billing-signoff-2026-06-02.md`
  - `docs/runbooks/pine-labs-uat-readiness-2026-06-02.md`
  - `docs/runbooks/provider-operations-readiness-2026-06-02.md`
- Current backend routes under `apps/api/src/caseops_api/api/routes`.
- Current backend services for billing, provider costs, integrations, Gmail, Google Drive, Google Workspace, Pine Labs, observability, AI policy, storage governance, AI token governance, evaluation, and notification workflows.
- Current frontend app pages under `apps/web/app/app`.
- Current test coverage gates, including route coverage, page coverage, AI route governance, and provider-gated E2E tests.

## 3. Brutal Executive Verdict

CaseOps is not a thin MVP anymore. It has real implementation breadth: billing, pricing, tenant reports, founder platform admin, cost profiles, margin simulations, password reset, Google Workspace foundations, Gmail metadata import, Google Drive metadata listing, Google Calendar sync foundations, Outlook calendar foundations, provider operations, GBA workflows, legal updates, case tracking, AI drafting/recommendations, evaluation tables/scripts, storage governance, AI token governance, structured logging, and optional OTel scaffolding.

The brutal issue is no longer "nothing exists." The issue is that many high-risk areas are foundations, disabled modes, mock modes, readiness ledgers, or partial workflows. Those are useful for controlled pilots but dangerous if sold as fully self-serve, enterprise-ready, provider-backed automation.

The product can be used for founder-led pilots with explicit constraints. It should not yet be scaled as a low-touch profitable SaaS for Indian law firms until the P0 operational gaps are closed.

## 4. Corrections From The First Brutal Pass

The first pass was directionally right, but this second pass found places where old docs were stale or implementation had moved forward.

### 4.1 Password Reset Is Implemented

Do not reopen password reset as missing.

Evidence:

- Frontend:
  - `apps/web/app/account/forgot-password`
  - `apps/web/app/account/reset-password`
  - sign-in forgot-password link
- Backend:
  - `/api/auth/password-reset/start`
  - `/api/auth/password-reset/complete`
  - admin employee reset endpoint
- Tests:
  - forgot-password page tests
  - reset-password page tests
  - self-service password reset tests
  - anti-enumeration tests
  - inactive user tests
  - token atomic-use tests
  - session revocation tests

Remaining gap:

- Production email delivery smoke evidence, bounce/failure monitoring, reset email template/domain proof, and provider-event visibility.

### 4.2 OpenTelemetry And Structured Logging Are Foundations, Not Absent

Do not say observability is entirely missing.

Evidence:

- `apps/api/src/caseops_api/core/observability.py` has request context, JSON logging, and optional OTel setup for FastAPI, SQLAlchemy, and httpx.

Remaining gap:

- Production enablement, dashboards, alerts, trace sampling policy, redaction proof, runbook evidence, and provider/workflow correlation at scale.

### 4.3 EvaluationRun Is Implemented

Do not repeat old stale statements that `EvaluationRun` table is missing.

Evidence:

- `EvaluationRun` and `EvaluationCase` models exist.
- Evaluation services and scripts exist:
  - `eval_ai_safety.py`
  - `eval_workflows.py`
  - `eval_drafting.py`
  - `eval_hnsw_recall.py`
  - `eval_citations.py`
- Tests exist around evaluation scripts.

Remaining gap:

- Enforced CI/release gate, per-workflow golden breadth, admin UI, founder approval workflow for prompt/model changes, and full legal-quality acceptance matrix.

### 4.4 Provider Cost Profiles And Margin Simulation Exist

Do not say provider cost tracking is absent.

Evidence:

- `apps/api/src/caseops_api/services/provider_costs.py`
- platform-admin cost profile APIs/UI
- margin simulation APIs/UI
- cost categories include payment MDR, fixed fee, case refresh, LLM, embedding, document processing, storage, SMS, WhatsApp, manual support.

Remaining gap:

- Real provider costs are not yet entered/proven, simulations are not yet tied to mandatory pricing guardrails, and live settlement/provider invoices are not reconciled.

### 4.5 Google Workspace Tenant Configuration Exists

Do not say Google configuration is completely missing.

Evidence:

- `apps/api/src/caseops_api/services/google_workspace.py`
- tenant Google Workspace configuration and readiness tests
- Gmail, Calendar, Drive connector support behind scoped config.

Remaining gap:

- Production OAuth/UAT proof, consent verification, live scopes, two-way sync, content import, webhook durability, and provider-health depth.

## 5. Release Readiness Classification

| Scenario | Status | Brutal reason |
| --- | --- | --- |
| Founder demo | Ready with caveats | Broad UI exists, but provider/payment caveats must be stated. |
| Limited pilot with manual billing | Conditionally ready | Requires founder monitoring, manual signoff, usage caps, provider-disabled messaging. |
| Self-serve paid signup with Pine Labs | Not ready | Pine Labs UAT/live activation and settlement/reconciliation not complete. |
| High-volume law firm rollout | Not ready | Profitability, case-refresh economics, support runbooks, and provider SLAs are not proven. |
| Corporate GC enterprise rollout | Not ready | MFA, SSO, SCIM, step-up auth, retention controls, and enterprise audit controls are incomplete. |
| Full Google Workspace automation claim | Not ready | Gmail/Drive/Calendar are partial and review-first/foundation-level. |
| Full Microsoft 365 automation claim | Not ready | Microsoft mailbox and two-way Graph automation are behind Google. |
| Full autonomous AI legal agent claim | Not ready | Agent grants, tool authority, approvals, and enforced AI eval gates are missing. |
| GBA-specific paid rollout | Needs UAT | Implementation exists, but representative GBA workflow/PDF/court evidence still required. |

## 6. P0 Gaps - Do Not Scale Paid Production Until Closed

### BGA2-001: Pine Labs Live Payment Acceptance Is Still Blocked

Severity: P0

Current reality:

- Pine Labs code exists for disabled, mock, and configured modes.
- Production has been kept disabled in prior deployment notes.
- Webhook signature verification and idempotent event handling exist.
- Settings include refund and settlement endpoint paths.
- Runbook explicitly says live activation remains blocked.

Brutal gap:

- No real Pine Labs UAT success/failure/pending/refund/settlement evidence is captured in repo.
- Endpoint paths, event names, payload schemas, subscription semantics, UPI AutoPay behavior, refund semantics, and settlement reports still depend on Pine Labs confirmation.
- Production payment enablement without UAT would be reckless.

Business risk:

- Customers can pay but subscription/top-up activation may not reconcile.
- Duplicate/tampered webhooks could produce finance confusion if provider semantics differ.
- Settlement reports may not match CaseOps orders.
- GST/TDS accounting could be wrong or manually patched.

Requirements:

1. Obtain UAT credentials, webhook secret, dashboard access, test instruments, endpoint paths, sample payloads, and enabled product list from Pine Labs.
2. Confirm Plural V2 signature algorithm, timestamp tolerance, webhook ID semantics, and base64/raw secret behavior.
3. Run UAT for:
   - one-time plan payment success
   - top-up success
   - failed payment
   - pending payment
   - cancelled/expired payment
   - duplicate webhook
   - tampered webhook
   - stale webhook
   - refund processed
   - refund failed
   - subscription charged
   - subscription cancelled
   - settlement report import
4. Attach evidence: provider order IDs, webhook IDs, timestamps, screenshots, and redacted payload samples.
5. Keep production disabled until founder go/no-go.

Acceptance criteria:

- UAT payment success activates exactly one subscription/top-up.
- Failure/pending/cancelled does not activate entitlements.
- Duplicate webhook is idempotent.
- Tampered/stale webhook is rejected and audited.
- Refund/dispute events do not silently delete or mutate subscription state incorrectly.
- Settlement report reconciles to payment order and gateway fee.
- Founder platform admin shows all payment events and reconciliation exceptions.

Implementation status on 2026-06-09:

- Repo support is now implemented on branch `codex/brutal-gap-p0-paid-production-safety-2026-06-09`: durable Pine Labs UAT run/evidence/activation-decision records, founder-only API/UI at `/app/platform-admin/paid-production`, and `scripts/pine_labs_uat_mock_harness.py`.
- Required UAT scenarios are explicitly tracked: plan payment success, top-up success, failed, pending, cancelled/expired, duplicate webhook, tampered webhook, stale webhook, refund processed, refund failed, subscription charged, subscription cancelled, and settlement report import.
- Production activation is still blocked by code unless all required scenarios pass and founder go/no-go is recorded. The activation record does not enable production payments or mutate Pine Labs environment settings.
- Live provider calls remain fail-closed unless the environment is clearly UAT-safe. Pine Labs production/live mode remains disabled.
- External blocker: real Pine Labs UAT credentials, signed samples, dashboard screenshots, settlement files, endpoint confirmation, and founder UAT approval are still required.

### BGA2-002: Production Billing Signoff Is Still Pending

Severity: P0

Current reality:

- Tenant billing, tenant downloads, usage/spend exports, credit ledger exports, invoices, statements, founder profit dashboard, provider events, platform costs, and margin simulations exist.
- The runbook still lists founder-only platform admin smoke, tenant billing smoke, tenant downloads, leakage checks, and migration/deploy evidence as pending.

Brutal gap:

- Code exists, but production founder-authenticated evidence is still missing.
- Without this, the founder may be blind during real onboarding.

Requirements:

1. Log in as the configured founder production super-admin.
2. Verify:
   - `/app/platform-admin`
   - `/app/platform-admin/profit`
   - `/app/platform-admin/costs`
   - `/app/platform-admin/integrations`
   - `/app/platform-admin/provider-events`
3. Verify tenant admin cannot access platform admin.
4. Verify tenant billing pages:
   - current plan
   - invoices
   - statement
   - credit ledger
   - payment export
   - spend export
   - top-up/add-on checkout disabled state
5. Verify tenant payloads do not leak internal cost, provider fee, margin, gross profit, or platform notes.
6. Record evidence in runbook.

Acceptance criteria:

- Founder signs off production billing runbook.
- No internal finance data appears in tenant APIs/UI/exports.
- Downloads and exports audit events are recorded.
- Disabled Pine checkout cannot charge or activate entitlements.

Implementation status on 2026-06-09:

- Founder-only signoff records and evidence rows are now implemented for platform-admin, profit, costs, integrations, provider events, tenant current plan, invoice/statement/download/export checks, disabled checkout behavior, and tenant no-leak checks.
- `/app/platform-admin/paid-production` shows the signoff state alongside Pine UAT, margin readiness, reconciliation exceptions, password-reset readiness, and case-tracking support cost readiness.
- `scripts/prod_billing_authenticated_smoke.py` can run authenticated smoke checks from env-supplied session or bearer token without printing secrets.
- Tenant billing exports/downloads require authentication, are audited by existing billing paths, and step-up is required when MFA policy/enrollment requires it.
- External blocker: actual production founder session, smoke tenant evidence, deploy/migration evidence, and signed founder runbook evidence remain pending.

### BGA2-003: Profitability Is Still Not Proven For Law Firms

Severity: P0

Current reality:

- Pricing catalog exists.
- Cost profiles exist.
- Margin simulations exist.
- AI token and storage governance exist.
- Some usage attribution exists.

Brutal gap:

- Real provider costs are not yet known or entered.
- Case refresh economics are especially dangerous because law firms can have many tracked cases and frequent refresh expectations.
- Add-on/top-up flow exists, but hard profitability controls are not proven across every expensive feature.

Business risk:

- A litigation-heavy firm can become loss-making after signup.
- "Unlimited" or high-included case tracking/AI/document processing can silently eat margin.
- Founder may discover losses only after invoices are already paid.

Requirements:

1. Enter real cost profiles for:
   - Pine Labs MDR by payment method
   - Pine Labs fixed fee
   - refunds if charged
   - chargebacks/disputes if charged
   - case refresh per provider/court
   - OCR/page
   - LLM input/output or credit cost
   - embeddings
   - storage/GB-month
   - bandwidth/export
   - email
   - SMS
   - WhatsApp
   - manual research/support minutes
2. Build required scenario simulations for every public plan:
   - solo light user
   - solo heavy court user
   - small law office with heavy litigation
   - large firm with many tracked cases
   - corporate GC with heavy document/contract workload
   - abusive usage pattern
3. Enforce stop-loss rules:
   - hard limits on expensive features
   - soft warnings at 70/85/95 percent
   - founder quote approval when case refresh cost exceeds threshold
   - top-up required before extra consumption
4. Block plan publication or sales activation if margin is below founder threshold.

Acceptance criteria:

- Every plan has a dated founder-approved margin simulation.
- Every expensive feature is metered.
- No provider-heavy feature can run unbounded after credits are exhausted.
- Negative-margin tenants appear in platform-admin alerts.
- Tenant sees usage categories and top-up options without seeing internal cost/profit.

Implementation status on 2026-06-09:

- Provider cost profiles now carry category, provider, unit label, INR amount/BPS, tax/fee notes, effective dates, estimated-vs-actual basis, confidence, source/evidence, and founder approval status.
- Required plan simulations are now tracked for solo light user, solo heavy court user, small law office heavy litigation, large law firm many tracked cases, corporate GC heavy document workload, and abusive usage pattern.
- A founder-configurable gross-margin floor (`CASEOPS_BILLING_MINIMUM_GROSS_MARGIN_BPS`, default 7000) blocks paid-readiness when simulations are missing, under threshold, or based on unapproved estimated costs.
- Tenant usage pages show consumption, limits, 70/85/95 percent warnings, exhausted-credit messaging, and top-up paths without internal cost/profit fields.
- External blocker: actual provider invoices, Pine Labs fee confirmation, court/provider cost sheets, founder approvals, and dated plan-level simulation evidence remain pending.

### BGA2-004: Settlement, Refund, Chargeback, And TDS Operations Are Not Complete

Severity: P0

Current reality:

- GSTIN defaults to `09AANCM5923C1ZD`.
- TDS fields exist for invoices/manual invoices.
- Refund status can be recorded as an order status in billing payment handling.
- Founder payment reconciliation capability exists in platform admin.

Brutal gap:

- Refunds are described as operational records at launch; there is no mature refund/credit-note ledger.
- Settlement report import/reconciliation is not proven.
- Chargeback/dispute lifecycle is not implemented as a first-class finance workflow.
- TDS handling is captured, but accountant-approved reconciliation/export flow still needs signoff.

Requirements:

1. Implement or validate:
   - settlement import
   - settlement reconciliation exceptions
   - provider fee reconciliation
   - refund records
   - credit notes
   - chargeback/dispute records
   - TDS reconciliation export
2. Keep public product copy silent on refund policy unless founder approves wording.
3. Ensure invoice/payment reports are accountant-ready.

Acceptance criteria:

- Settlement import identifies matched, missing, duplicate, amount mismatch, fee mismatch, and tax mismatch.
- Refund/credit note does not corrupt subscription entitlement history.
- TDS values can be recorded and exported per Indian-law handling.
- Founder can export finance reports for accountant review.

Implementation status on 2026-06-09:

- Settlement imports, settlement rows, reconciliation exceptions, refund records, credit notes, chargeback/dispute records, provider-fee reconciliation rows, and TDS reconciliation rows are now first-class platform-admin records.
- Settlement import classifies matched payment, missing payment, duplicate settlement row, amount mismatch, provider-fee mismatch, tax mismatch, and unknown provider order id.
- Founder/accountant exports are available for settlement rows, reconciliation exceptions, refunds, credit notes, chargebacks, provider-fee reconciliation, and TDS reconciliation.
- Refund and credit-note records are operational finance records and do not rewrite subscription entitlement history.
- External blocker: real settlement reports, refund/chargeback provider samples, accountant-reviewed export format, and founder finance signoff remain pending.

### BGA2-005: MFA And Step-Up Authorization Are Not Implemented

Severity: P0 for founder/admin, P1 for all users

Current reality:

- Database fields such as `mfa_required` and `mfa_enforced_at` exist.
- Platform admin service exposes MFA metadata.
- No end-to-end TOTP/WebAuthn/email OTP enrollment, login challenge, recovery code, or high-risk step-up flow was found.

Brutal gap:

- The founder-only console, payment activation, cost profile edits, exports, connector secrets, role changes, and tenant data exports can be protected only by ordinary auth/capabilities today.

Requirements:

1. Add TOTP MFA:
   - enrollment
   - QR/secret display
   - verification
   - recovery codes
   - disable/reset with audit
2. Add enforcement:
   - founder required
   - tenant admins optional/required
   - all users optional/required
   - grace period for existing users
3. Add step-up authorization for:
   - platform admin access
   - payment activation
   - cost profile changes
   - billing exports
   - connector credential changes
   - role changes
   - bulk exports
   - destructive matter/document actions
4. Add audit and rate limiting.

Acceptance criteria:

- Founder cannot access platform-admin when MFA policy requires it.
- Existing users can be forced into MFA after login.
- Recovery codes are single-use and audited.
- High-risk action fails with step-up-required until recent MFA is present.

Implementation status on 2026-06-09:

- TOTP MFA enrollment, QR/secret display, verification, single-use recovery codes, recovery-code regeneration, disable/reset, audit events, and rate limiting are now implemented.
- Existing founder/platform super-admin rows are marked MFA-required with a grace period (`CASEOPS_MFA_EXISTING_USER_GRACE_DAYS`, default 7) to avoid founder lockout.
- Step-up is enforced for platform-admin access once policy requires MFA, cost profile changes, payment activation/go-live decisions, billing/finance exports, connector credential changes, role/capability changes, and tenant billing exports when MFA is enrolled/policy-active.
- Account security UI exists at `/account/security`; platform-admin readiness UI surfaces the protected founder flows.
- External blocker: actual founder enrollment, policy rollout timing, recovery-code custody, and any tenant-wide MFA mandate remain operational decisions.

### BGA2-006: Password Reset Exists But Production Email Delivery Must Be Proven

Severity: P1, but P0 before broad onboarding

Current reality:

- Password reset implementation is real.
- The gap is production delivery evidence.

Requirements:

1. Smoke test production reset email delivery.
2. Confirm reset link domain is correct.
3. Confirm reset emails bypass unsubscribe/suppression only where appropriate.
4. Confirm bounces/failures are visible.
5. Confirm no token appears in logs/provider events.

Acceptance criteria:

- Real production user receives reset email and completes reset.
- Used/expired/tampered token fails.
- Old sessions are revoked.
- Audit events are recorded.

Implementation status on 2026-06-09:

- Password reset itself remains existing code; this slice adds production smoke support via `scripts/prod_password_reset_smoke.py`.
- Founder-only metadata visibility is now available at `/api/platform-admin/password-reset-readiness` and `/app/platform-admin/paid-production`, showing reset domain, path, provider configured state, sender name, template kind, and TTL without secrets or token values.
- Existing reset tests cover anti-enumeration, used/expired/tampered token behavior, inactive users, atomic consume, and old-session revocation. This slice adds P0 smoke coverage that production-like reset start does not expose a debug token or provider-event token.
- External blocker: real production email receipt, delivery/bounce evidence, and founder acceptance of reset-domain/template proof remain pending.

### BGA2-007: Case Tracking Provider Costs And Coverage Are Not Proven

Severity: P0 for law-firm scale

Current reality:

- Case tracking exists and is provider-gated.
- Disabled state is safe.
- Bulk refresh and provider operations foundations exist.

Brutal gap:

- Real provider cost per court/case refresh is unknown.
- Court coverage and data freshness are not proven for target law-firm use.
- Captcha/session-gated scraping is intentionally not added, which is correct, but means licensed/API provider strategy is mandatory.

Requirements:

1. Obtain provider coverage matrix:
   - court
   - bench
   - jurisdiction
   - lookup method
   - refresh cost
   - rate limit
   - bulk support
   - data freshness
   - failure codes
   - legal/ToS constraints
2. Add founder cost profile per provider/court if costs vary.
3. Add tenant-visible support matrix before user tracks a case.
4. Add usage stop-loss and quota enforcement.

Acceptance criteria:

- Founder knows cost per refresh before enabling a customer.
- User sees whether their court/case type is supported.
- Heavy refresh usage cannot make a plan loss-making.

Implementation status on 2026-06-09:

- Case-tracking support matrix records now track provider, court, bench/jurisdiction, lookup method, refresh cost, bulk refresh cost, rate limit, freshness SLA, legal/ToS status, failure-code mapping, enabled/disabled status, tenant visibility, evidence reference, and notes.
- Founder-only APIs/UI expose internal refresh costs; tenant-facing APIs/UI expose only support, status, lookup method, rate/freshness notes, and failure mappings.
- Case tracking search/bookmark paths consult the matrix when configured and block disabled unsupported courts without adding captcha/session-gated scraping.
- Support matrix costs feed the same founder-only cost/readiness model, while tenant usage surfaces quotas and top-up/exhausted-credit paths.
- External blocker: real provider coverage/cost matrix, legal/ToS review, and founder enablement per court/provider remain pending.

## 7. P1 Gaps - Required For Credible Paid Product

### BGA2-008: SSO, OIDC, SAML, And SCIM Are Missing

Severity: P1

Current reality:

- Admin UI text references SSO as future.
- No full OIDC/SAML/SCIM implementation was found.

Requirements:

1. Tenant SSO configuration UI.
2. OIDC login.
3. SAML login.
4. JIT provisioning.
5. Domain verification.
6. Group-to-role mapping.
7. SSO-only enforcement.
8. Break-glass admin path.
9. SCIM provisioning/deprovisioning later.

Acceptance criteria:

- Corporate GC tenant can enforce SSO without founder manual account handling.
- Deprovisioned users lose access.
- Role mapping cannot grant platform-admin.

### BGA2-009: Google Workspace Is Foundation-Level, Not Full Automation

Severity: P1

Current reality:

- Tenant Google Workspace config exists.
- Gmail, Calendar, Drive OAuth foundations exist.
- Readiness probes exist without exposing secrets.

Brutal gap:

- Production Google OAuth/UAT proof is missing.
- Google Workspace should not be sold as complete automation yet.

Requirements:

1. Production OAuth app approval.
2. Domain verification and redirect URI proof.
3. Scope approval.
4. UAT test accounts.
5. Smoke tests for each connector.
6. Token revoke/refresh failure handling.
7. Admin health and runbook evidence.

Acceptance criteria:

- Tenant admin can configure and test Google Workspace in production.
- Users can connect Gmail/Calendar/Drive with approved scopes.
- Failures are visible and redacted.

Implementation status on 2026-06-10:

- Partially closed by branch `codex/connector-automation-readiness-2026-06-10`.
- Tenant admins now get active, durable connector-health rows for Google
  Workspace services, including required/granted/missing scopes, token-refresh
  status labels, webhook/polling status, redacted error category, last
  success/failure, next retry, setup actions, and provider-operations links.
- Existing Google Workspace setup/test flow now feeds that health model without
  exposing OAuth secrets, access tokens, refresh tokens, or raw provider errors.
- Still blocked by external production OAuth app approval, Google Cloud redirect
  proof, live UAT accounts, and tenant consent verification.

### BGA2-010: Gmail Is Metadata/Review-First, Not Full Mailbox Ingestion

Severity: P1

Current reality:

- Gmail imports metadata/snippets.
- It avoids raw body storage.
- Attachment bytes require explicit review.
- Pub/Sub webhook foundations exist.

Brutal gap:

- No full thread workspace.
- No advanced label/search workflows.
- No autonomous mailbox polling.
- No raw body policy UI.
- No complete attachment import-to-matter workflow at production depth.

Requirements:

1. Thread view with message grouping.
2. Search/label filters.
3. Matter matching.
4. Review-to-import attachments.
5. Tenant policy for raw body storage.
6. Retention policy.
7. Durable polling/watch processor.

Acceptance criteria:

- User can connect Gmail, review message/attachment candidates, assign to matter, import, ignore, or bulk act.
- Duplicate imports are prevented.
- No raw bodies are stored unless policy permits it.

Implementation status on 2026-06-10:

- Partially closed. Gmail imports are now surfaced as a user review queue at
  `/app/mailbox` with filters, safe bulk ignore, link-metadata, note/task
  creation, and explicit content-import request states.
- The backend stores metadata/snippets only by default and keeps idempotency by
  provider message and attachment IDs. Attachment imports still require explicit
  user action and reuse the existing storage/security/OCR/document-processing
  path when bytes are fetched.
- Tests now cover review-first behavior, tenant isolation, no token leak, and no
  raw body import without approval.
- Full thread UX, advanced label/search policy, and production Gmail Pub/Sub UAT
  remain pending.

### BGA2-011: Google Drive Is Metadata Listing, Not Document Sync

Severity: P1

Current reality:

- Drive OAuth and file metadata listing exist.
- No content import pipeline from Drive was found in the current Drive connector.

Requirements:

1. Folder/shared-drive allow-list.
2. File preview metadata.
3. Review-to-import file content.
4. Malware scan.
5. OCR/extraction.
6. Dedupe by provider file ID/hash.
7. Version tracking.
8. Source provenance.
9. Durable sync only after review policy and cost controls.

Acceptance criteria:

- User can import a Drive file into a matter through review queue.
- Imported file appears in matter documents with source provenance.
- Duplicate/version changes are handled.

Implementation status on 2026-06-10:

- Partially closed. Google Drive now has tenant controls for allowed/blocked
  folders, max size, MIME types, and review-import mode; auto-import remains
  forced off.
- A Drive candidate queue at `/app/drive` supports metadata review, linking,
  explicit file import, ignore, and retry. Candidate records preserve provider
  file ID, modified-time/version provenance, suggested matter, and status.
- Content import is never automatic and must pass the existing upload,
  storage-security, OCR, and document-processing rules.
- Live Drive content import still requires provider credentials/UAT and explicit
  tenant approval; uncontrolled folder-wide ingestion remains out of scope.

### BGA2-012: Google Calendar Needs Two-Way Sync And Conflict Review

Severity: P1

Current reality:

- Google Calendar connection/sync foundation exists.
- Current notes indicate CaseOps-to-Google hearings/events, not complete two-way sync.

Requirements:

1. Google-to-CaseOps import.
2. Event ID mapping.
3. Conflict policies:
   - CaseOps wins
   - Google wins
   - manual review
4. Manual lock support.
5. Delete/cancel handling both directions.
6. Durable watch/polling.

Acceptance criteria:

- Google-created or edited event can become a CaseOps suggestion.
- Locked CaseOps hearing is not overwritten.
- Conflicts enter review queue.

Implementation status on 2026-06-10:

- Partially closed. Provider calendar event candidates now support
  Google/Outlook-to-CaseOps suggestions, idempotent provider-event mapping,
  provenance, sync history, accept/reject/ignore actions, and conflict status.
- `/app/calendar/conflicts` lets users review pending suggestions and explicitly
  override manual locks only when intended.
- Locked/manual hearing dates are not overwritten by default, and provider
  deletion/cancellation does not delete CaseOps hearings without review.
- Durable provider webhooks/change notifications and live two-way UAT remain
  pending.

### BGA2-013: Outlook/Microsoft 365 Is Behind Google

Severity: P1

Current reality:

- Outlook calendar foundation exists.
- Durable Outlook sync foundation exists for bounded CaseOps-to-Outlook hearing sync.
- Microsoft mailbox readiness is explicitly disabled/readiness-only in connector registry.

Requirements:

1. Microsoft Graph tenant/user OAuth.
2. Outlook Calendar two-way sync.
3. Graph change notifications or durable polling.
4. Microsoft mailbox metadata/thread/attachment workflow.
5. Token revoke/refresh handling.
6. Tenant/founder connector health.

Acceptance criteria:

- Microsoft 365 has parity with Gmail/Google Calendar for review-first workflows.
- Corporate GC prospects can use Microsoft 365 without weaker functionality than Google.

Implementation status on 2026-06-10:

- Partially closed. Tenant Microsoft 365/Graph configuration and readiness
  status now exist under `/app/admin/microsoft365`, including admin-consent and
  scope-approval state without echoing client secrets.
- Outlook Mail has a metadata-only review-candidate path matching the Gmail
  safety model. Outlook Calendar shares the provider-event candidate/conflict
  workflow. OneDrive/SharePoint is modeled in health, schema, and review states;
  content import remains blocked until Graph provider credentials and consent
  are configured.
- Graph scopes, admin consent, token health labels, polling/webhook readiness,
  and provider-operation visibility are represented in the connector-health
  model.
- Live Graph OAuth, change notifications, and OneDrive/SharePoint content UAT
  remain external blockers.

### BGA2-014: Connector Registry Needs Active Health, Not Just Readiness

Severity: P1

Current reality:

- Tenant and platform integration dashboards exist.
- They show configuration, missing config names, last success/failure for some rows, and platform notes.

Brutal gap:

- Many connectors are configuration/readiness state, not live probes.
- Quota/rate-limit and connection-owner visibility are incomplete.

Requirements:

1. Standard states:
   - disabled
   - missing config
   - configured
   - connected
   - degraded
   - token expired
   - scope missing
   - rate limited
   - provider outage
   - blocked by policy
2. Connection owner and consent actor.
3. Last success/failure.
4. Last error category.
5. Next retry.
6. Rate-limit/quota if provider supports it.
7. Tenant-safe redaction and founder-only detail.

Acceptance criteria:

- Tenant admin knows why a connector is broken.
- Founder can diagnose without secrets.
- Health probe jobs do not mutate provider data.

Implementation status on 2026-06-10:

- Closed for local durable health tracking; provider-backed live probes remain
  gated. `connector_health_records` now persist per tenant/provider/account.
- Tenant admins can query/check `/api/admin/integrations/health`; founder
  platform admins can query `/api/platform-admin/integrations/health` across
  tenants with redacted failure categories and operational alerts.
- Health records include configured/connected state, last success/failure,
  required/granted/missing scopes, token expiry/refresh labels, webhook/polling
  status, rate-limit status, next retry, disabled reason, setup actions, and
  provider-operation links.
- The health model is tenant-scoped, auditable, and secret-free. It does not
  mutate provider data or perform uncontrolled provider calls.

### BGA2-015: External Notifications And Preferences Are Partial

Severity: P1

Current reality:

- Durable in-app notification intents exist.
- Notification admin UI exists.
- External email/SMS/WhatsApp delivery remains fail-closed or provider-gated.

Requirements:

1. User preference center:
   - hearing reminders
   - deadline reminders
   - order compliance
   - legal updates
   - billing alerts
   - provider alerts
   - daily/weekly digest
2. Channel controls:
   - in-app
   - email
   - SMS
   - WhatsApp
3. Provider adapters with template governance.
4. India DLT requirements for SMS/WhatsApp where applicable.
5. Delivery status and cost attribution.
6. Bounce/suppression handling.

Acceptance criteria:

- User/admin preferences drive actual delivery.
- Disabled provider never attempts external delivery.
- External delivery costs are metered.

Implementation status on 2026-06-10:

- Partially closed. Tenant and user notification preference rows now support
  in-app, email, SMS, WhatsApp, digest frequency, quiet hours, event categories,
  escalation rules, opt-out categories, and tenant/user APIs/UI.
- `/app/notification-preferences` exposes user controls, while admin endpoints
  manage tenant defaults. Event categories include hearing updates, tracked case
  changes, compliance deadlines, billing/credit warnings, connector failures,
  document processing failures, and provider-operation failures.
- External channels remain disabled unless provider configuration and
  tenant/user policy allow delivery. Tests verify disabled providers do not send
  external messages.
- Template governance, provider cost attribution, bounce/suppression UAT, and
  live SMS/WhatsApp approval remain pending.

### BGA2-016: Inbound Email Alias Is Missing

Severity: P1

Current reality:

- Gmail review-first import exists.
- Old product plans mention inbound email ingest via tenant alias.
- No production inbound alias workflow such as `{slug}@inbound.caseops.ai` was confirmed.

Requirements:

1. Tenant inbound address.
2. Provider webhook ingestion.
3. SPF/DKIM/DMARC alignment.
4. Attachment scanning.
5. Matter-code routing.
6. Review queue for uncertain routing.
7. Duplicate detection.

Acceptance criteria:

- User can forward email to CaseOps and review/import into matter.
- Unsafe attachments are blocked.
- Misrouted email does not silently attach to wrong matter.

Implementation status on 2026-06-10:

- Partially closed as production-disabled readiness. Tenant and matter inbound
  aliases now exist with enabled/disabled status, allowed senders/domains,
  retention days, and spam/security status.
- Inbound email event records store provider message ID, from/to/cc, subject,
  received time, attachment metadata, matched tenant/matter, status, provenance,
  and redacted failure reason. Review actions support link, note/task creation,
  attachment-import request, ignore, and reject.
- The webhook skeleton supports `disabled`, `mock`, and HMAC-verified
  `production` modes. Production mode rejects unauthenticated/spoofable inbound
  email unless a verified provider secret is configured.
- Real inbound provider selection, DNS/SPF/DKIM/DMARC proof, malware-scan UAT,
  and attachment byte import remain pending.

### BGA2-017: Agent Identity And Grantex-Equivalent Trust Plane Are Missing

Severity: P1

Current reality:

- Matter access grants exist, but those are human/matter permissions.
- Agent grants, executions, tool-call ledger, and human approval queue were not found.

Requirements:

1. `AgentGrant`
2. `AgentExecution`
3. `AgentToolCall`
4. `HumanApproval`
5. Tool policy engine.
6. Budget, expiry, revocation.
7. Approval gates for high-risk tools.

Acceptance criteria:

- No AI agent can mutate data, spend credits, send communication, or sync providers without scoped grant.
- Every tool call is auditable.
- Revoked/expired grant blocks action.

### BGA2-018: AI Evaluation Is Not An Enforced Release Gate

Severity: P1

Current reality:

- Evaluation storage and scripts exist.
- Drafting and AI-safety evaluation foundations exist.

Brutal gap:

- There is no single enforced gate across all AI workflows before prompt/model changes ship.

Requirements:

1. Per-workflow goldens:
   - drafting
   - recommendations
   - hearing packs
   - order compliance extraction
   - legal update summaries
   - matter file Q&A
   - RAG citation support
   - predictive intelligence
2. CI gate for prompt/model changes.
3. Founder/admin approval workflow for model upgrades.
4. Admin UI to review eval runs.
5. Red-team prompts for hallucination, prompt injection, and data exfiltration.

Acceptance criteria:

- AI workflow change cannot merge without passing required evals or explicit waiver.
- Results are stored and comparable by run/model/prompt version.

### BGA2-019: AI Policy Controls Are Still Partial

Severity: P1

Current reality:

- Tenant AI policy service exists.
- Token governance exists.
- The service comments explicitly state some controls are scaffolded but not wired into all pipelines.

Requirements:

1. Admin UI for:
   - model allow-lists
   - token budgets
   - external-share approval
   - training opt-in/out
   - disabled templates
   - predictive analytics enablement
2. Server-side enforcement across every AI route.
3. Prompt/model/request audit metadata.
4. Tenant-visible usage without internal costs.

Acceptance criteria:

- Tenant admin can disable high-risk AI features.
- Policy blocks are enforced before provider call.
- AI usage report is tenant-safe.

### BGA2-020: RAG, Corpus, And Matter Embeddings Need Production Proof

Severity: P1

Current reality:

- Retrieval and reranking foundations exist.
- Matter file Q&A and document chunks exist.
- Evaluation and HNSW recall scripts exist.

Brutal gap:

- Production-grade corpus recall, tenant overlays, matter attachment embeddings, deletion/reindex, and cross-tenant vector isolation still require proof.

Requirements:

1. Full target-jurisdiction corpus benchmark.
2. Matter attachment embeddings for all supported uploads.
3. Tenant/matter isolation tests for vector search.
4. Deletion/reindex workflow.
5. Citation provenance with document/page/snippet.
6. Recall@k benchmark before paid claims.

Acceptance criteria:

- Retrieval quality meets agreed threshold.
- Deleted docs cannot appear in retrieval.
- Tenant A cannot retrieve Tenant B content.

### BGA2-021: Durable Workflow Migration Is Partial

Severity: P1

Current reality:

- Temporal runtime foundation exists for notification workflows.
- Notification delivery and Outlook sync foundations exist.
- Provider operations replay/ignore/resolve exists.

Brutal gap:

- Many workflows are not yet durable Temporal workflows:
  - document ingestion
  - OCR/extraction
  - case tracking poll
  - legal update sync
  - Gmail mailbox poll/watch processing
  - Drive sync/import
  - Calendar two-way sync
  - payment settlement reconciliation
  - AI eval batch runs

Requirements:

1. Workflow contracts per domain.
2. Idempotency keys.
3. Retry/timeouts.
4. Dead-letter state.
5. Replay tooling.
6. Versioning strategy.

Acceptance criteria:

- Long-running provider jobs are observable, retryable, idempotent, and tenant-scoped.

### BGA2-022: Observability Needs Production Enablement And Alerts

Severity: P1

Current reality:

- Structured logging and optional OTel scaffolding exist.

Brutal gap:

- Production dashboards/alerts and trace coverage are not proven.

Requirements:

1. Enable OTel in staging/production.
2. Add dashboards:
   - API latency/error rate
   - DB latency
   - provider failures
   - payment failures
   - AI token spend
   - case tracking backlog
   - notification failures
   - document/OCR failures
3. Add alert thresholds.
4. Add log redaction tests.
5. Correlate request ID across API, workflow, provider event, and audit event.

Acceptance criteria:

- Founder/operator can identify failing tenant/provider/route without reading raw secrets or legal content.

### BGA2-023: Backup And Restore Proof Must Be Current

Severity: P1

Current reality:

- Backup runbooks and historical restore drill docs exist.
- Production deploy notes mention backups before migrations.

Brutal gap:

- A current post-billing/post-Google restore drill is not proven in this pass.

Requirements:

1. Fresh restore drill to isolated environment.
2. Verify login, tenants, matters, documents metadata, billing, invoices, audit, provider events.
3. Record RPO/RTO.
4. Migration rollback plan.

Acceptance criteria:

- Restore evidence exists after the latest billing/provider schema additions.

### BGA2-024: Release Gates And Full Test Completion Need Hardening

Severity: P1

Current reality:

- CI exists.
- Postgres validation exists.
- Route coverage and page coverage matrices exist.
- Some full backend local runs have historically exceeded local timeout.

Brutal gap:

- Several allowed untested route waivers remain.
- Page coverage matrix allow-list is stale and over-broad: some entries now have tests but remain allowed, meaning a future test deletion could be masked.
- Provider-gated tests skip without UAT providers.

Requirements:

1. Shrink `ALLOWED_UNTESTED` in backend route matrix.
2. Remove stale page coverage allow-list entries for pages that now have tests.
3. Make full backend suite practical through CI shards.
4. Track provider-gated UAT separately from normal CI.
5. Require PRD traceability matrix updates per slice.

Acceptance criteria:

- New route/page without tests fails CI.
- Existing baseline waivers shrink.
- Provider-gated flows cannot be mistaken for tested production readiness.

### BGA2-025: Tenant Isolation And Authorization Matrix Need More Adversarial Coverage

Severity: P1

Current reality:

- Matter access, ethical walls, restricted grants, route guards, and many tenant tests exist.

Brutal gap:

- More negative tests are needed for newer high-risk surfaces.

Requirements:

1. Tenant isolation tests for:
   - billing exports
   - provider operations
   - connector configs
   - Gmail imports
   - Drive connections
   - Calendar connections
   - case tracking
   - legal update watches
   - vector embeddings
   - signed document URLs
   - audit exports
   - platform profit/cost fields
2. Role matrix tests for every mutating/export route.
3. Ensure platform-admin is founder-only and not granted by tenant admin roles.

Acceptance criteria:

- Tenant A cannot read, infer, export, download, or mutate Tenant B data.
- Tenant users never see internal costs/profit/margins.

### BGA2-026: GBA Law Office Needs Representative UAT Evidence

Severity: P1

Current reality:

- GBA PRD implementation and public guide updates exist.
- Tests exist around GBA billing and workflows.

Brutal gap:

- Real GBA representative matter signoff is still not evidenced.

Requirements:

1. Collect representative GBA matters:
   - active
   - disposed
   - civil
   - criminal
   - high court
   - district court
2. Validate:
   - disposed terminology
   - next-hearing provenance
   - order compliance extraction
   - manual upload/OCR
   - cause-list PDF
   - invoice PDF
   - GST/TDS fields
   - CNR/case number formats
   - advocate/source fields
3. Capture stakeholder signoff.

Acceptance criteria:

- GBA stakeholder confirms workflows and PDFs match real office use.
- Gaps become tests or documented unsupported cases.

## 8. P2 Gaps - Product Completeness And Scale

### BGA2-027: Generic Obligation/Task Lifecycle Needs More Maturity

Current reality:

- Matter tasks page exists.
- Order compliance extraction exists in GBA work.

Gap:

- Unified obligations from orders, contracts, emails, hearings, legal updates, and manual tasks need a consistent lifecycle.

Requirements:

- One obligation/task/deadline model or clearly mapped models.
- Assignee, watcher, source, due date, reminder policy, status, proof of completion, calendar sync, audit.

### BGA2-028: Document Intelligence And DMS Need More Depth

Current reality:

- Uploads, OCR states, malware/quality gates, and manual order uploads exist.
- Google Drive metadata exists.

Gap:

- Production-grade content ingestion from Drive/Email/DMS, versioning, review queue, and structural extraction remain incomplete.

Requirements:

- Parser coverage for PDF, scanned PDF, DOCX, images, emails.
- Review-first extraction for parties, obligations, deadlines, court, bench, judge, citations.
- Dedupe and version tracking.

### BGA2-029: Court, Bench, Judge, And Source Quality Need Ongoing Hardening

Current reality:

- Courts/judges pages and judge aliases exist.
- Predictive intelligence and bench context features exist.

Gap:

- Source quality, judge profile freshness, court normalization, jurisdiction coverage, and no-overclaim rules need continuous QA.

Requirements:

- Source freshness dashboard.
- Court/bench resolver backfill.
- Judge alias workflow signoff.
- No forbidden probability/outcome prediction claims.

### BGA2-030: Tenant Admin Console Is Broad But Not Complete

Current reality:

- Admin pages exist for billing, integrations, employees, roles, teams, notifications, provider operations, matter billing, email templates, Outlook, judge aliases.

Gap:

- Remaining tenant governance controls include retention, data deletion/export workflows, full AI policy, MFA/SSO policy, workspace branding, region/data residency, and legal/compliance documents.

Requirements:

- Tenant profile and branding.
- Retention/deletion/export workflows.
- Security policy page for MFA/SSO.
- AI policy page.
- Data processing/subprocessor visibility.

### BGA2-031: Accounting Integrations Are Missing

Current reality:

- Invoice downloads and exports exist.
- Platform profit exports exist.

Gap:

- No direct Tally, Zoho Books, QuickBooks, or accountant workflow integration.

Requirements:

- Accountant-ready CSV/XLSX exports first.
- Tally-compatible export.
- Optional Zoho/QuickBooks later.

### BGA2-032: Public Documentation Hub Is Still Thin

Current reality:

- Public guide page and machine-readable docs exist.

Gap:

- No full versioned `/docs` hub for billing, admin setup, connectors, security, AI policy, provider limitations, and troubleshooting.

Requirements:

- `/docs` route.
- Versioned docs.
- Changelog.
- Connector setup guides.
- Security and billing guides.

### BGA2-033: Accessibility And Mobile Coverage Need Proof

Current reality:

- Many page tests exist.
- Accessibility baseline has older docs.

Gap:

- New billing, platform admin, provider operations, integrations, Google/Gmail/Drive, and GBA pages need axe/keyboard/mobile proof.

Requirements:

- Axe checks for critical flows.
- Keyboard navigation.
- Focus states.
- Mobile layout screenshots for dense admin pages.

### BGA2-034: OpenAPI Generated Client Adoption Is Still Partial

Current reality:

- Generated OpenAPI types exist.
- Manual frontend endpoints still exist.

Gap:

- Schema drift and manual endpoint maintenance remain risks.

Requirements:

- CI schema drift check.
- Route-by-route migration to generated client/types.
- Remove stale manual schemas where safe.

### BGA2-035: Performance And Pagination Need Continuing Work

Current reality:

- Some list endpoints have pagination and limits.

Gap:

- Older lists, admin exports, provider events, audit exports, recommendations, and matter sublists need consistent pagination/performance proof for large tenants.

Requirements:

- Standard pagination shape.
- Index review.
- Large-tenant load tests.
- Background exports for huge audit/report downloads.

### BGA2-036: Enterprise Deployment Options Are Deferred

Gap:

- Dedicated tenant, private networking, customer-managed keys, data residency, and enterprise procurement/security packs are not complete.

Requirements:

- Enterprise deployment matrix.
- DPA/subprocessor pack.
- Data residency statement.
- Customer-managed key roadmap.

## 9. Do-Not-Sell Claims Until These Are True

### 9.1 Do Not Sell "Self-Serve Paid SaaS" Until:

1. Pine Labs UAT is complete.
2. Founder production billing signoff is complete.
3. Production password-reset email smoke is complete.
4. Every public plan has real-cost margin simulation.
5. Case refresh cost and coverage are known.
6. Tenant usage/top-up/hard-limit flows are proven.
7. Refund/settlement/chargeback/TDS operations are approved.

### 9.2 Do Not Sell "Enterprise Ready" Until:

1. MFA exists and founder/admin enforcement is live.
2. Step-up auth protects high-risk actions.
3. SSO is implemented.
4. Tenant isolation tests cover new billing/provider/connector/vector surfaces.
5. Retention/export/deletion controls exist.
6. Current restore drill evidence exists.

### 9.3 Do Not Sell "Full Google Workspace Automation" Until:

1. Production Google OAuth/UAT is done.
2. Gmail thread/attachment review workflow is complete.
3. Google Drive content import is complete.
4. Google Calendar two-way sync and conflict review are complete.
5. Connector health shows live token/scope/rate-limit state.

### 9.4 Do Not Sell "Full Microsoft 365 Automation" Until:

1. Microsoft mailbox ingestion exists.
2. Outlook Calendar two-way sync exists.
3. Graph change notifications or durable polling exists.
4. Microsoft connector parity tests pass.

### 9.5 Do Not Sell "Autonomous Legal Agents" Until:

1. Agent grants exist.
2. Tool calls are scoped, budgeted, auditable, and revocable.
3. Human approval queue exists.
4. AI eval gates are enforced.
5. Step-up auth protects high-risk approvals.

## 10. Recommended Next Implementation Slices

### Slice 1: Paid Production Safety

Scope:

- Founder billing signoff smoke helper with authenticated evidence workflow.
- Production password-reset email smoke.
- Pine Labs UAT checklist execution support.
- Provider cost real-input collection and plan simulations.
- Stop-loss enforcement review for case refresh, AI, OCR, storage, SMS/WhatsApp, and top-ups.

Exit:

- Founder can say, "I will not lose money on the first paid law-firm signups under expected and heavy usage."

### Slice 2: Founder/Admin Security

Scope:

- MFA TOTP/recovery codes.
- Founder-required MFA.
- Tenant admin policy with grace period.
- Step-up auth for billing/platform/admin/export/connector actions.

Exit:

- Founder-only console and billing/provider controls are no longer password-only.

### Slice 3: Google Workspace Completion

Scope:

- Production OAuth/UAT evidence.
- Gmail full review queue.
- Drive file content import.
- Calendar two-way suggestions/conflicts.
- Connector health improvements.

Exit:

- Google Workspace can be sold honestly with clear supported boundaries.

### Slice 4: Microsoft 365 Parity

Scope:

- Microsoft mailbox.
- Outlook two-way calendar sync.
- Graph webhook/polling.
- Admin health and provider operations integration.

Exit:

- Corporate GC users on Microsoft 365 are not second-class.

### Slice 5: Finance Operations

Scope:

- Settlement import.
- Refund/credit note records.
- Chargeback/dispute records.
- TDS/GST accountant exports.
- Platform reconciliation reports.

Exit:

- Payments can be operated by founder/accountant without spreadsheet guesswork.

### Slice 6: AI Governance

Scope:

- Per-workflow goldens.
- CI eval gate.
- Admin eval UI.
- Tenant AI policy UI.
- Prompt/model approval log.

Exit:

- Legal AI changes cannot regress silently.

### Slice 7: Durable Workflow Hardening

Scope:

- Temporal workflows for document ingestion, provider sync, case tracking, legal updates, payment reconciliation, and eval batches.
- Idempotency and replay.

Exit:

- Long-running and provider-backed jobs are operationally safe.

### Slice 8: GBA UAT And Court Provider Proof

Scope:

- Representative GBA matters.
- PDF/layout approval.
- Court coverage proof.
- Case tracking provider UAT.

Exit:

- GBA rollout can proceed with real stakeholder evidence.

## 11. Founder Inputs Needed

### 11.1 Pine Labs

- UAT merchant ID.
- UAT client ID/secret or API key/secret.
- UAT webhook signing secret.
- UAT base URL.
- Production base URL.
- Hosted checkout docs.
- Payment link docs.
- Subscription docs.
- UPI AutoPay docs.
- Refund docs.
- Settlement report docs.
- Chargeback/dispute docs.
- Event names and sample payloads.
- Test cards/UPI/netbanking instruments.
- MDR by method.
- Fixed fee by method.
- GST on fees.
- Settlement cycle.
- Refund fee.
- Chargeback/dispute fee.
- Transaction limits.
- Product enablement confirmation.

### 11.2 Case Tracking Provider

- Supported court matrix.
- Per-refresh cost.
- Bulk refresh pricing.
- Rate limits.
- Freshness SLA.
- Legal/ToS approval.
- Failure code mapping.
- UAT accounts/cases.

### 11.3 Google Workspace

- Production OAuth app status.
- Authorized domains.
- Redirect URIs.
- Consent-screen status.
- Scope approval.
- Test accounts.

### 11.4 Microsoft 365

- Entra app details.
- Graph scopes.
- Tenant/admin consent approach.
- Webhook/change notification plan.
- Test accounts.

### 11.5 GBA Law Office

- Real sample active matters.
- Real sample disposed matters.
- Required invoice PDF samples.
- Required cause-list PDF expectations.
- Court list.
- CNR/case number examples.
- Advocate/source fields.
- UAT approver.

## 12. Final Brutal Summary

The product is powerful but not yet low-touch. It is best treated as a controlled pilot platform until the P0 safety work is done.

The top risk is not "can the app show pages?" The app can. The top risk is paid operational reality: live payments, settlement reconciliation, real provider costs, case refresh economics, founder-only finance visibility, MFA/step-up protection, provider UAT, and complete traceable support workflows.

The next engineering work should be boring and disciplined: signoff evidence, real costs, hard limits, MFA, Pine Labs UAT, provider coverage proof, and eval gates. That is what turns CaseOps from impressive software into a profitable, dependable legal SaaS.
