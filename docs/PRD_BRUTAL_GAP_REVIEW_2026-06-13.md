# PRD: Brutal CaseOps Gap Review - 2026-06-13

## 1. Document Control

- Product: CaseOps
- Review date: 2026-06-13
- Workspace: `C:\Users\mishr\caseops`
- Current branch inspected: `codex/connector-automation-readiness-2026-06-10`
- Review type: Brutal product, security, billing, connector, operations, and PRD-gap review
- Output purpose: Give the founder and Codex CLI a current gap ledger that does not reopen stale issues and does not pretend unproven provider readiness is production readiness.
- Commit/deploy scope: This is a documentation gap review only. It does not enable payments, providers, or production settings.

## 2. Method Used

This pass inspected the local repository state, recent commits, PRDs, runbooks, migration list, routes, services, pages, tests, and security notes.

Evidence sources included:

- `git status --short --branch`
- `git log --oneline -n 25`
- `docs/PRD_BRUTAL_GAP_ANALYSIS_ROUND2_2026-06-09.md`
- `docs/PENDING_PRD_GAP_ANALYSIS_2026-06-08.md`
- `docs/PRD_CASEOPS_GAP_CLOSURE_2026-06-08.md`
- `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`
- `docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md`
- `docs/SECURITY_BRUTAL_FIX_LIST_2026-06-13.md`
- `docs/runbooks/production-billing-signoff-2026-06-02.md`
- `docs/runbooks/pine-labs-uat-readiness-2026-06-02.md`
- `docs/runbooks/provider-operations-readiness-2026-06-02.md`
- `docs/runbooks/backup-restore.md`
- backend routes under `apps/api/src/caseops_api/api/routes`
- backend services under `apps/api/src/caseops_api/services`
- models and migrations under `apps/api/src/caseops_api/db/models.py` and `apps/api/alembic/versions`
- frontend app pages under `apps/web/app`
- backend and frontend test coverage matrices

No live production mutation, real Pine Labs call, real Google/Microsoft OAuth flow, live court-provider call, or real external delivery test was run as part of this audit.

## 3. Executive Verdict

CaseOps is now a large, serious product foundation, not a toy MVP.

The current branch includes major implementation work that did not exist in earlier reviews:

- Pine Labs UAT evidence records and production activation decision gate.
- Production billing signoff records.
- Finance records for settlement imports, reconciliation exceptions, refunds, credit notes, chargebacks, and TDS rows.
- Provider cost profiles and margin simulations.
- Case tracking support matrix.
- MFA/TOTP enrollment, recovery codes, step-up records, and protected high-risk routes.
- Password reset.
- Google Workspace configuration.
- Gmail and Outlook Mail review-first queues.
- Google Drive review-first candidate import controls.
- Google and Outlook calendar candidate/conflict workflows.
- Microsoft 365 readiness/configuration.
- Connector health records.
- Inbound email alias and webhook skeleton.
- Notification preferences.
- Provider operations/dead-letter visibility.
- Security hardening around CSP, gitleaks noise, local trace artifacts, and MFA QR rendering.

The brutal reality is different now:

- The biggest gaps are no longer "there is no code."
- The biggest gaps are "there is code, but production evidence, external provider UAT, live credentials, real costs, accounting proof, enterprise identity, agent trust, and operational drills are not complete."

The product can support controlled founder-led pilots with explicit caveats. It should not yet be represented as fully self-serve paid SaaS, full enterprise GC platform, live Pine Labs payment product, full Google/Microsoft automation product, or autonomous legal-agent platform.

## 4. Current Git And Release Reality

Current observed git state:

- Branch: `codex/connector-automation-readiness-2026-06-10`
- Remote tracking: `origin/codex/connector-automation-readiness-2026-06-10`
- Untracked file present before this review: `docs/PRD_BRUTAL_GAP_ANALYSIS_2026-06-09.md`
- Latest inspected commits include:
  - `12eaa4a harden security scans and CSP`
  - `6d49853 Update connector readiness guard baselines`
  - `8da5bf0 Cover connector readiness API routes`
  - `8fbd1d1 Add connector page coverage tests`
  - `b0d8c75 Update generated OpenAPI client`
  - `3e6d594 Add connector automation readiness`
  - `fca07e0 Update API client and MFA route guard allowlist`
  - `2302390 Add P0 paid production safety gates`

Release implication:

- This review is based on the local branch, not verified production.
- Unless this branch has been merged and deployed separately, production may lag these fixes.
- Any statement that "CaseOps is production ready" must be tied to deployed commit, CI, migration, and authenticated founder smoke evidence, not local branch inspection.

## 5. What Is No Longer A Current Gap

Do not ask Codex CLI to rebuild these as missing:

1. Email-based password reset.
   - Implemented via `/account/forgot-password`, `/account/reset-password`, `/api/auth/password-reset/start`, and `/api/auth/password-reset/complete`.
   - Remaining gap is production delivery proof, not core implementation.

2. Basic MFA/TOTP and step-up foundations.
   - Implemented via `/api/auth/mfa/*`, `apps/web/app/account/security/page.tsx`, `services/security.py`, and migration `20260609_0002_p0_paid_production_safety.py`.
   - Remaining gap is full enforcement/enterprise maturity, not absence.

3. Provider cost profiles and margin simulation foundations.
   - Implemented via `services/provider_costs.py`, platform-admin cost UI, margin readiness, and billing settings.
   - Remaining gap is real cost inputs, signed simulations, and live economics.

4. Pine Labs safety gate foundation.
   - Implemented via `PineLabsUATRun`, scenario evidence, activation decision, and platform-admin paid-production page.
   - Remaining gap is actual Pine Labs UAT and production enablement evidence.

5. Connector readiness foundations.
   - Implemented for Google Workspace, Gmail, Google Drive, Google Calendar, Microsoft 365, Outlook Mail, Outlook Calendar, inbound email aliases, and notification preferences.
   - Remaining gap is live provider UAT, real credentials, durable automation, and full provider coverage.

6. EvaluationRun table.
   - Implemented. Remaining gap is enforced release gating and legal-quality breadth.

7. Basic observability scaffolding.
   - Structured logging and optional OTel scaffolding exist.
   - Remaining gap is production dashboards, alerts, redaction proof, and on-call runbooks.

## 6. Release Readiness Classification

| Scenario | Current status | Brutal reason |
| --- | --- | --- |
| Local demo on current branch | Mostly ready with caveats | Broad features exist; providers remain gated or mocked. |
| Founder-led pilot with manual billing | Conditionally ready | Requires manual signoff, usage caps, provider-disabled messaging, and close monitoring. |
| Self-serve paid signup with Pine Labs | Not ready | Pine Labs UAT/live activation evidence remains external-blocked. |
| High-volume law firm rollout | Not ready | Real case-refresh cost, court coverage, support burden, and plan margin are unproven. |
| Corporate GC enterprise rollout | Not ready | SSO/SCIM, full MFA enforcement, retention, DPA/subprocessor, and enterprise UAT are incomplete. |
| Full Google Workspace automation claim | Not ready | Live OAuth/UAT, durable sync, body/folder policy, and webhook operation are not proven. |
| Full Microsoft 365 automation claim | Not ready | Microsoft 365 is readiness/review-first, not full Graph production automation. |
| Inbound email-to-matter production claim | Not ready | Webhook skeleton exists; real provider/DNS/signature proof is absent. |
| External email/SMS/WhatsApp notification claim | Not ready | Preferences exist; provider delivery remains disabled unless separately configured and UAT-approved. |
| Autonomous legal agents claim | Not ready | AgentGrant/AgentExecution/AgentToolCall trust plane is absent. |
| Enterprise security claim | Partially ready | MFA exists, but SSO/SCIM and current secret rotation evidence remain blockers. |

## 7. P0 Gaps - Block Paid Or Enterprise Scale

### BGR3-001 - Historical Connector Secret Rotation Is Still Externally Blocked

Severity: P0

Evidence:

- `docs/SECURITY_BRUTAL_FIX_LIST_2026-06-13.md` records a historical `.codex/config.toml` `X-Client-Secret` finding at commit `24c6ebf73f57605c964a908f78dfce686c68be1f`.
- The file is not currently tracked.
- `.codex/` is now ignored.
- False-positive scanner noise was reduced.
- `gitleaks git .` intentionally still reports the historical secret until rotation is confirmed.

Brutal gap:

- A historical secret exposure is not closed until the issued credential is rotated or revoked at the provider.
- Ignoring the file prevents recurrence, but does not neutralize the old credential.

Business/security risk:

- If the historical credential still works, a third party with repository/history access could misuse a connector or provider account.
- A future security review will fail until rotation evidence exists.

Requirements:

1. Identify the issuer/provider/account for the historical `X-Client-Secret`.
2. Rotate or revoke the credential at source.
3. Record evidence without writing the new secret into the repo.
4. Keep the gitleaks finding unsuppressed until rotation is verified.
5. Add a dated line to the security runbook with:
   - provider/account name
   - rotation date
   - operator
   - old credential revoked
   - validation performed

Acceptance criteria:

- Old credential is confirmed unusable.
- `gitleaks git .` has no unsuppressed live-secret blocker or explicitly documents only a rotated historical finding.
- Security runbook has final rotation evidence.

### BGR3-002 - Current Branch Is Not Production Signoff

Severity: P0

Evidence:

- Current review is on `codex/connector-automation-readiness-2026-06-10`.
- Production deploy evidence was not checked in this pass.
- The repo has recent local/branch commits after earlier production deployment notes.

Brutal gap:

- Local implementation is not production readiness.
- Any production claim must be tied to:
  - merged main commit
  - green CI
  - Cloud Build images
  - migration job success
  - deployed Cloud Run revisions
  - authenticated founder smoke
  - tenant no-leak smoke
  - provider-disabled/payment-disabled verification

Business risk:

- Founder may assume current branch features exist in production when they may not.
- A customer demo could depend on features not deployed.

Requirements:

1. Confirm whether the current branch is merged to main.
2. Confirm whether main is deployed.
3. Record exact API/web image tags and Cloud Run revisions.
4. Run authenticated founder smoke for paid-production and connector pages.
5. Update the production billing signoff runbook with evidence.

Acceptance criteria:

- Release evidence links local branch features to a deployed SHA.
- Founder has a dated go/no-go for current production.

### BGR3-003 - Pine Labs Live Payment Acceptance Is Still Not Proven

Severity: P0

Evidence implemented:

- `services/pine_labs.py`
- `services/production_safety.py`
- `PineLabsUATRun`
- `PineLabsUATScenarioEvidence`
- `PineLabsProductionActivationDecision`
- platform-admin paid-production UI
- runbook `docs/runbooks/pine-labs-uat-readiness-2026-06-02.md`

Brutal gap:

- Evidence tables exist, but real Pine Labs UAT evidence is not present from this review.
- Production payments are still supposed to remain disabled until UAT is complete.
- Mock evidence is useful for software tests, but cannot prove Pine Labs endpoint paths, event names, signatures, subscription semantics, settlement exports, or refund behavior.

External inputs still needed:

- UAT merchant ID.
- UAT client ID/secret or API key/secret.
- UAT webhook signing secret.
- Registered UAT webhook URL.
- Hosted checkout docs.
- Payment link docs.
- Subscription and UPI AutoPay docs.
- Refund docs.
- Settlement report docs.
- Chargeback/dispute docs.
- Event names and sample payloads.
- Test instruments.
- MDR/fixed fee/GST/settlement cycle/limits.
- Product enablement confirmation.

Acceptance criteria:

- All required Pine Labs UAT scenarios pass with real provider evidence:
  - plan payment success
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
- Founder records go/no-go.
- Production remains disabled until the above is complete.

### BGR3-004 - Production Billing Signoff Is Implemented But Not Proven

Severity: P0

Evidence implemented:

- `ProductionBillingSignoff`
- `ProductionBillingSignoffEvidence`
- `/api/platform-admin/billing-signoff`
- `/api/platform-admin/billing-signoff/evidence`
- `/app/platform-admin/paid-production`
- runbook `docs/runbooks/production-billing-signoff-2026-06-02.md`

Brutal gap:

- The signoff mechanism exists, but this review did not find completed production evidence.
- The runbook still treats multiple checks as pending.

Required production checks:

- Founder platform admin access.
- Platform profit dashboard.
- Platform cost profiles.
- Platform integrations.
- Platform provider events.
- Tenant current plan.
- Tenant invoices.
- Invoice download.
- Statement download.
- Credit ledger export.
- Payment export.
- Spend export.
- Disabled Pine checkout behavior.
- Tenant no-leak checks for internal cost/profit/provider fee/platform notes.

Acceptance criteria:

- Founder-authenticated production signoff is complete.
- Evidence refs are stored.
- Export/download audit events are visible.
- Pine Labs disabled-state behavior is verified.
- Tenant-facing exports contain no internal economics.

### BGR3-005 - Profitability Is Modeled, But Not Proven With Real Costs

Severity: P0

Evidence implemented:

- Provider cost profiles.
- Cost approval status.
- Margin simulations.
- Margin readiness.
- `CASEOPS_BILLING_MINIMUM_GROSS_MARGIN_BPS`, default 7000.
- Case refresh cost guardrails.
- Tenant usage/spend surfaces.

Brutal gap:

- Real provider costs are still external business inputs.
- Default/fallback costs are not proof.
- Law-firm economics are dangerous because heavy litigation users can create many tracked cases and repeated refresh demand.

Costs that must be real and approved:

- Pine Labs MDR by method.
- Pine Labs fixed fee.
- Refund fee.
- Chargeback/dispute fee.
- Case refresh per provider/court.
- Bulk case refresh.
- OCR/page.
- LLM input/output or credit cost.
- Embeddings.
- Storage/GB-month.
- Bandwidth/export.
- Email.
- SMS.
- WhatsApp.
- Manual research/support minutes.

Required simulations:

- solo light user
- solo heavy court user
- small litigation office
- large law firm with many tracked cases
- corporate GC heavy document workload
- abusive usage pattern

Acceptance criteria:

- Every public plan has a dated founder-approved simulation.
- Every scenario uses actual or founder-approved costs.
- Negative-margin or unapproved-cost simulations block paid readiness.
- Heavy case refresh usage cannot run unbounded after entitlements are exhausted.

### BGR3-006 - Finance Operations Exist As Records, But Not As Proven Accounting Workflow

Severity: P0

Evidence implemented:

- Settlement import records.
- Settlement rows.
- Reconciliation exceptions.
- Refund records.
- Credit note records.
- Chargeback/dispute records.
- TDS reconciliation rows.
- Platform finance exports.
- Company GSTIN default: `09AANCM5923C1ZD`.

Brutal gap:

- There is no real Pine Labs settlement import proof.
- There is no accountant-approved GST/TDS export signoff in this pass.
- Credit notes are records, but credit-note PDF/accounting format and statutory treatment need accountant approval.
- Refund/chargeback flows are operational ledgers, not proven provider API lifecycles.

Acceptance criteria:

- Settlement import from Pine Labs UAT/export classifies matched, duplicate, missing, amount mismatch, provider fee mismatch, tax mismatch, and unknown provider order ID.
- Refund, credit note, chargeback, and TDS exports are accountant-reviewed.
- Subscription/entitlement history remains append-only.
- Public product copy remains silent on refund policy unless approved separately.

### BGR3-007 - MFA Exists, But Is Not Yet Full Enterprise MFA

Severity: P0 for founder/platform admin; P1 for tenant-wide enterprise readiness

Evidence implemented:

- `/api/auth/mfa/enroll`
- `/api/auth/mfa/enroll/verify`
- `/api/auth/mfa/step-up`
- `/api/auth/mfa/recovery-codes/regenerate`
- `/api/auth/mfa/disable`
- `/account/security`
- step-up on high-risk platform/billing/export/cost routes
- platform-admin MFA enforcement hook
- tenant security policy fields

Brutal gap:

- Login itself still returns a normal session after email/password.
- MFA is primarily enforced on protected routes, not as a universal post-login challenge.
- "All users MFA required" appears to matter only where a route calls step-up enforcement.
- The QR shown to users is an SVG placeholder with "Use secret below", not a real scannable QR matrix.
- No WebAuthn/passkey support.
- No SSO-backed MFA handoff.
- No mature admin reset/recovery workflow for lost devices beyond current disable/reset paths.

Acceptance criteria:

- Required MFA causes post-login challenge before ordinary app use, not only before protected actions.
- Founder/platform admin cannot reach platform-admin without enrolled MFA and recent step-up once enforcement date passes.
- Tenant admin policy can truly force all users or admins into MFA after grace.
- Real QR generation is implemented or UX explicitly says manual secret entry.
- Recovery/reset is safe, audited, and founder-admin usable.

### BGR3-008 - Case Tracking Provider Coverage And Cost Are Not Proven

Severity: P0 for law-firm scale

Evidence implemented:

- Case tracking service/routes.
- Provider-gated disabled state.
- Tracked case polling.
- Support matrix.
- Tenant-safe support matrix view.
- Cost fields on platform support matrix.

Brutal gap:

- Real provider coverage matrix is not proven.
- Real per-refresh cost by court/provider is not proven.
- eCourts/captcha/session-gated scraping remains intentionally blocked, which is correct.
- Without a lawful provider/API path, case tracking cannot be sold as broad Indian court automation.

Acceptance criteria:

- Court/provider matrix is filled with real data:
  - court
  - bench/jurisdiction
  - lookup method
  - refresh cost
  - bulk refresh cost
  - rate limit
  - freshness SLA
  - legal/ToS status
  - failure code mapping
- Tenant sees supported/unsupported status before tracking a case.
- Refresh quotas and top-up rules prevent loss-making usage.

### BGR3-009 - Public Claims Overstate Agent Trust Capabilities

Severity: P0 for public trust and enterprise diligence

Evidence:

- `components/marketing/FAQ.tsx` says agents run with scoped grants.
- `components/marketing/Features.tsx` references scoped agent grants.
- `components/marketing/Security.tsx` references scoped agent identity.
- Core PRD references Grantex/agent trust plane.
- Repo search did not find implemented `AgentGrant`, `AgentExecution`, `AgentToolCall`, or complete human approval queue for agent tools.

Brutal gap:

- The product copy implies a capability that does not exist as an implemented control plane.
- This is not just a roadmap gap. It is a claims-risk gap.

Acceptance criteria:

- Either implement minimal agent trust plane:
  - AgentGrant
  - AgentExecution
  - AgentToolCall
  - scope checks
  - budget checks
  - expiry/revocation
  - human approvals
  - audit
- Or immediately revise public copy to say "designed for future scoped agent grants" rather than "agents run with scoped grants."

### BGR3-010 - External Provider UAT Is Not Complete

Severity: P0 for production automation claims

Providers affected:

- Pine Labs
- Google Workspace
- Gmail
- Google Drive
- Google Calendar
- Microsoft 365/Graph
- Outlook Mail
- Outlook Calendar
- OneDrive/SharePoint
- inbound email provider
- SendGrid
- SMS provider
- WhatsApp provider
- case tracking provider

Brutal gap:

- Many provider surfaces are now implemented as safe foundations, but live provider proof is still missing.
- Readiness screens are not the same as production provider operation.

Acceptance criteria:

- Each provider has:
  - credentials stored outside repo
  - least-privilege scopes
  - webhook URL registration where applicable
  - signed webhook proof
  - success/failure/duplicate/retry tests
  - redaction proof
  - provider-operation visibility
  - disable/rollback runbook
  - founder go/no-go

## 8. P1 Gaps - Block Credible Enterprise Or Broad Paid Adoption

### BGR3-011 - SSO, OIDC, SAML, And SCIM Are Still Missing

Severity: P1

Evidence:

- Search found PRD/docs references, but no tenant OIDC/SAML login implementation.
- Admin page still lists OIDC/SAML as future.
- Billing docs mention SSO readiness/full SSO for higher plans.

Gap:

- No tenant IdP configuration.
- No OIDC start/callback.
- No SAML metadata/certificate handling.
- No JIT provisioning.
- No IdP group-to-role mapping.
- No SSO-only enforcement.
- No SCIM provisioning/deprovisioning.

Acceptance criteria:

- At least one OIDC pilot works end to end with mock provider tests.
- Enterprise tenant can enforce SSO-only.
- SCIM or documented manual lifecycle controls exist before selling enterprise GC lifecycle management.

### BGR3-012 - Agent Identity / Grantex-Equivalent Trust Plane Is Missing

Severity: P1, P0 before autonomous agent actions

Gap:

- No real agent grant model.
- No delegated tool-call budget.
- No revoked/expired grant enforcement.
- No human approval queue for high-risk agent actions.
- No audit trail that cleanly distinguishes human, system, and agent tool calls across all mutation surfaces.

Do not allow autonomous agents to:

- mutate matters
- send emails
- trigger provider sync
- execute payments
- spend large token budgets
- create external communications
- alter billing or access controls

Acceptance criteria:

- Agent actions are impossible without scoped grants.
- High-risk tool calls require human approval.
- All agent tool calls are auditable and replayable.

### BGR3-013 - AI Governance Is Not Yet A Release Gate

Severity: P1

Evidence implemented:

- EvaluationRun/EvaluationCase exist.
- Eval scripts exist.
- Some AI policy enforcement exists for model allow-lists.
- AI token governance exists.

Brutal gap:

- Eval suites are not clearly enforced as CI/release blockers for every legal AI workflow.
- Per-workflow golden coverage is uneven.
- No founder-visible prompt/model approval log was found.
- `external_share_requires_approval` is still documented in `tenant_ai_policy.py` as scaffolded and not fully wired into all drafting/export pipelines.

Acceptance criteria:

- Every AI workflow has a golden suite:
  - drafting
  - recommendations
  - hearing packs
  - matter QA
  - contract extraction
  - compliance extraction
  - legal updates
  - case summaries
- CI blocks prompt/model changes that fail thresholds.
- Founder/admin can see eval run history and approve model/prompt changes.
- External share approval is enforced where promised.

### BGR3-014 - Google Workspace Is Useful But Not Production-Proven

Severity: P1

Evidence implemented:

- Tenant Google Workspace config.
- Gmail metadata/review queue.
- Google Drive candidate queue.
- Google Calendar sync/candidates.
- Connector health records.

Gap:

- No production Google OAuth approval proof.
- No live redirect URI proof.
- No Gmail Pub/Sub UAT proof.
- Gmail raw body/thread policy remains intentionally limited.
- Drive full folder/webhook sync is not proven.
- Google Calendar two-way provider webhook/live import is not proven.

Acceptance criteria:

- Production OAuth app is approved.
- Scopes are verified.
- Live test accounts complete OAuth.
- Gmail/Drive/Calendar UAT covers success, failure, duplicate, reconnect, revoked-token, and no-leak cases.

### BGR3-015 - Microsoft 365 Is Readiness/Review-First, Not Full Parity

Severity: P1

Evidence implemented:

- Microsoft 365 config/status UI/API.
- Outlook Mail candidate flow.
- Outlook Calendar sync/candidate foundations.
- Graph scope/admin consent readiness.

Gap:

- No live Entra app/admin consent proof.
- No Graph webhook/change-notification UAT.
- No OneDrive/SharePoint content import parity.
- Microsoft mailbox remains review-first and not a full mailbox automation product.

Acceptance criteria:

- Entra app works in UAT.
- Admin consent and scopes are verified.
- Outlook Mail/Calendar and OneDrive/SharePoint UAT is signed off.

### BGR3-016 - Inbound Email Alias Is Disabled-By-Default Skeleton

Severity: P1

Evidence implemented:

- Inbound aliases.
- Inbound events.
- HMAC-ready webhook skeleton.
- Provider mode defaults to disabled.

Gap:

- No real inbound email provider.
- No production DNS, SPF, DKIM, DMARC, or MX proof.
- No provider signature proof.
- No bounce/spam handling proof.
- No production anti-spoofing proof.

Acceptance criteria:

- Production mode accepts only signed provider webhooks.
- DNS and domain posture are documented.
- Inbound-to-matter review flow works with real provider samples.

### BGR3-017 - External Notifications Are Preference-Ready, Not Delivery-Proven

Severity: P1

Evidence implemented:

- Notification preferences for in-app/email/SMS/WhatsApp.
- Durable delivery intents.
- Provider operations visibility.
- SendGrid/Twilio/WhatsApp settings exist.

Gap:

- External delivery remains disabled or provider-gated.
- India SMS/WhatsApp DLT/template approval is not proven.
- Bounce, suppression, unsubscribed, duplicate, and retry UAT is not complete.

Acceptance criteria:

- External channels have provider-specific UAT.
- Quiet hours, digest, opt-out, escalation, and disabled-provider behavior are tested end to end.
- Billing/legal-update/hearing notifications respect user and tenant preferences.

### BGR3-018 - Durable Workflow / Temporal Migration Is Partial

Severity: P1

Evidence:

- Temporal workflow foundations exist.
- Notification workflow foundations exist.
- Outlook/Google durable sync functions exist.
- Settings default durable workflows to disabled.
- Several long-running jobs still use scripts, workers, BackgroundTasks, or manual admin triggers.

Gap:

- Durable workflow migration is not complete for:
  - document ingestion
  - OCR/retry
  - provider sync
  - mailbox polling/webhooks
  - Drive sync
  - case tracking
  - legal updates
  - payment reconciliation
  - eval batches

Acceptance criteria:

- Each long-running workflow has idempotency, retry, timeout, dead-letter, replay, and operator visibility.
- Temporal or equivalent is proven in the deployed environment.

### BGR3-019 - Observability Is Scaffolded, Not Operationally Proven

Severity: P1

Evidence:

- `core/observability.py` has JSON logging/request context/optional OTel setup.

Gap:

- No current proof of production OTel enablement.
- No dashboards/alerts evidence in this review.
- No runbook showing alert thresholds for payment failures, connector failures, case tracking failures, LLM cost spikes, error-rate spikes, or queue backlogs.

Acceptance criteria:

- Dashboards exist for API, billing, providers, AI cost, document processing, queue backlog, and auth/security.
- Alerts page founder/operator before customers notice.
- Logs/traces are redacted and correlated by request/tenant/job.

### BGR3-020 - Backup/Restore Evidence Is Not Current Enough

Severity: P1

Evidence:

- `docs/RESTORE_DRILL_2026-04-24.md` records a successful restore drill.
- `docs/runbooks/backup-restore.md` exists.

Gap:

- The April restore drill predates major billing, connector, MFA, finance, and safety migrations.
- `scripts/tenant_export.py` and `scripts/tenant_purge.py` are explicitly not built in the backup runbook.
- Application-level cutover to restored DB and cross-region export remain incomplete.

Acceptance criteria:

- Fresh restore drill after current migrations.
- Application boots against restored DB.
- Billing/connector/security critical flows verified on restore.
- Tenant export and tenant purge tools are built or explicitly descoped with compensating process.

### BGR3-021 - Privacy, DPDP, Retention, And Subprocessor Pack Are Incomplete

Severity: P1 for corporate GC/enterprise

Gap:

- No complete DPA/subprocessor pack was verified.
- No tenant export/purge tools.
- Retention policy enforcement across email, Drive imports, AI runs, provider payloads, audit records, and documents is not proven.
- Support/admin access controls and break-glass process need formal evidence.

Acceptance criteria:

- Tenant data export works.
- Tenant data deletion/purge workflow exists with legal hold exceptions.
- Retention policies are configurable and enforced.
- Subprocessor/security pack is current.

### BGR3-022 - GBA Law Office Needs Representative UAT Evidence

Severity: P1

Evidence implemented:

- GBA PRD implementation and guide exist.
- Court-order compliance, matter billing, cause-list, next hearing provenance, and disposed terminology are implemented.

Gap:

- No representative GBA UAT packet was verified in this pass.
- Need real sample active/disposed matters, invoice PDF expectations, cause-list PDF expectations, court list, CNR examples, and stakeholder signoff.

Acceptance criteria:

- GBA stakeholder signs off real workflows.
- PDFs match expected format.
- Court/case tracking provider coverage is clear for GBA matters.

### BGR3-023 - Court, Statute, And Legal Source Coverage Remains Bounded

Severity: P1

Gap:

- Case tracking and cause-list coverage are not broad court automation.
- Captcha/session-gated sources remain blocked, correctly.
- Statute catalog remains bounded; state acts and broad legal-source coverage are not complete.
- PRS/live legal update ingestion is provider/source dependent and needs recurring proof.

Acceptance criteria:

- Supported source/court matrix is user-visible.
- Unsupported sources fail honestly.
- Legal update sync has production monitoring and source-change proof.

### BGR3-024 - Test Coverage Gates Still Have Waivers And Provider Gaps

Severity: P1

Evidence:

- `apps/api/tests/test_route_coverage_matrix.py` still has 16 baseline untested route waivers.
- `apps/web/app/__page-coverage-matrix.test.ts` still has many allowed untested pages.
- Provider-gated tests skip when credentials are absent.
- Historical docs note full local backend suite/runtime limits.

Gap:

- Route/page waiver lists are no longer acceptable as long-term release posture.
- Provider UAT cannot be replaced by mock tests.

Acceptance criteria:

- API route waiver count trends to zero or has expiring owner/date entries.
- Frontend page waiver count trends to zero.
- Provider-gated tests have separate UAT jobs/evidence.
- Full CI shard matrix is green on target branch before deploy.

### BGR3-025 - Production Claims And Docs Are Drifting

Severity: P1

Evidence:

- `WORK_TO_BE_DONE.md` still contains stale claims such as no LLM, no Temporal, and EvaluationRun pending.
- Some older docs/tests display mojibake characters from non-ASCII punctuation.
- Public marketing refers to scoped agents before agent trust implementation exists.

Gap:

- Stale docs cause Codex CLI to chase wrong work.
- Public claims may overstate readiness.

Acceptance criteria:

- Create one canonical gap ledger and mark older ledgers as historical.
- Fix public copy that implies unimplemented agent trust.
- Clean mojibake in active docs/tests where user-facing or developer-guiding.

## 9. P2 Gaps - Maturity, Scale, And Product Depth

### BGR3-026 - Matter Task/Obligation Lifecycle Needs More Depth

Gap:

- Tasks, deadlines, obligations, compliance items, and notifications exist in several workflows, but there is not yet a fully unified lifecycle across matters, contracts, court orders, email, calendar, and legal updates.

Acceptance criteria:

- Unified task/deadline model with source provenance, owner, priority, status, reminders, recurrence, dependencies, and audit.

### BGR3-027 - Document Intelligence And DMS Depth Is Still Limited

Gap:

- Upload/OCR/security/document processing exist.
- Drive import exists review-first.
- But full DMS expectations need more:
  - foldering
  - versioning
  - privilege tags
  - document compare/redline at scale
  - email/Drive provenance
  - retention
  - bulk export
  - large file performance proof

### BGR3-028 - Performance And Pagination Need Continuing Work

Gap:

- The app has many growing admin/provider/billing pages.
- Need ongoing proof for large tenants:
  - thousands of matters
  - thousands of documents
  - many tracked cases
  - large mailbox candidate queues
  - large billing/usage ledgers

Acceptance criteria:

- Key list APIs use pagination, filters, indexes, and stable sort.
- Load tests exist for large-tenant scenarios.

### BGR3-029 - Accessibility And Mobile Coverage Need Proof

Gap:

- Some a11y and Playwright coverage exists historically, but current new pages need systematic coverage:
  - paid production
  - platform costs
  - integrations
  - mailbox
  - Drive
  - calendar conflicts
  - notification preferences
  - account security

Acceptance criteria:

- Keyboard and screen-reader checks for critical workflows.
- Mobile layout checks for compact pages and tables.

### BGR3-030 - Enterprise Deployment Options Are Deferred

Gap:

- Shared SaaS architecture exists.
- Some enterprise buyers may require private deployment, dedicated tenant isolation, data residency, VPC/private networking, customer-managed keys, or dedicated inference.

Acceptance criteria:

- Enterprise deployment matrix exists.
- Explicitly mark what is available now vs custom contract.

## 10. Do-Not-Sell Claims Until True

Do not sell or claim:

1. "Live Pine Labs payments" until UAT and founder go/no-go are complete.
2. "Self-serve paid SaaS" until production billing signoff and payment activation are complete.
3. "Profitable for law firms at current pricing" until real costs and simulations are approved.
4. "Full Google Workspace automation" until production OAuth/UAT and durable sync are proven.
5. "Full Microsoft 365 automation" until Graph UAT and parity workflows are proven.
6. "Inbound email to matter" until real provider, DNS, and signed webhook proof exist.
7. "SMS/WhatsApp notifications" until provider/DLT/template UAT is complete.
8. "Enterprise SSO/SCIM" until implemented.
9. "Agents run with scoped grants" until AgentGrant/AgentExecution/AgentToolCall exists.
10. "Current disaster recovery proof" until a post-migration restore drill is run.

## 11. Recommended Next Implementation Slices

### Slice 1 - Security And Claims Cleanup

Scope:

- Rotate historical connector secret.
- Record evidence.
- Fix public agent/scoped-grant claims.
- Mark stale docs as historical or update them.
- Run gitleaks git/dir and record results.

Exit:

- No unresolved live-secret blocker.
- No public copy claims unimplemented agent trust.

### Slice 2 - Production Evidence Signoff

Scope:

- Merge/deploy current branch if intended.
- Run full CI.
- Run migrations.
- Run authenticated founder smoke.
- Complete production billing signoff evidence.
- Run tenant no-leak export checks.

Exit:

- Founder has a clear deployed-SHA go/no-go.

### Slice 3 - Pine Labs And Finance UAT

Scope:

- Collect Pine Labs UAT credentials/details.
- Execute all UAT scenarios.
- Import settlement reports.
- Validate refunds/credit notes/chargebacks/TDS exports with accountant.

Exit:

- Online payments can be enabled deliberately or remain blocked with exact reasons.

### Slice 4 - MFA Enterprise Completion And OIDC Pilot

Scope:

- Add real login challenge for required MFA.
- Add real QR generation.
- Harden admin reset/recovery.
- Add OIDC pilot.
- Document SAML/SCIM roadmap.

Exit:

- Corporate GC identity objections are reduced.

### Slice 5 - Provider UAT Pack

Scope:

- Google Workspace live UAT.
- Microsoft 365 live UAT.
- Inbound email provider proof.
- External notification provider proof.
- Case tracking provider proof.

Exit:

- Connector claims can be made with exact supported boundaries.

### Slice 6 - Agent Trust And AI Eval Gates

Scope:

- Minimal Grantex-equivalent agent trust plane.
- Prompt/model approval log.
- CI-gated AI evals.
- External-share approval enforcement.

Exit:

- Agent and legal-AI governance claims become defensible.

### Slice 7 - DR, Observability, And Enterprise Ops

Scope:

- Fresh restore drill.
- Tenant export/purge tools.
- Production OTel dashboards/alerts.
- DPDP/DPA/subprocessor/security pack.

Exit:

- Enterprise operations story becomes credible.

## 12. Founder Inputs Needed

### Pine Labs

- UAT credentials.
- Webhook secret and registration.
- Product enablement.
- Event samples.
- Settlement/export docs.
- MDR/fixed fee/GST/refund/chargeback details.
- Test instruments.

### Provider Costs

- Real case refresh cost.
- Real OCR cost.
- Real LLM/embedding cost assumptions.
- Real SMS/WhatsApp/email costs.
- Manual support cost assumptions.
- Minimum acceptable margin by plan.

### Google Workspace

- Production OAuth app.
- Authorized domains.
- Redirect URIs.
- Scope approval.
- Test accounts.

### Microsoft 365

- Entra app.
- Graph scopes.
- Admin consent model.
- Test tenant/accounts.

### Security

- Historical connector secret issuer.
- Rotation owner.
- Rotation evidence.

### GBA UAT

- Real matters.
- Invoice samples.
- Cause-list samples.
- Court/provider list.
- UAT approver.

## 13. Final Brutal Summary

CaseOps has become broad and serious. The risk profile has shifted.

Earlier risk: missing features.

Current risk: unproven production operation.

The next work should not be more feature sprawl. It should be evidence, provider UAT, security closure, accurate public claims, real costs, accounting signoff, enterprise identity, agent trust, eval gates, observability, and restore drills.

The product is strong enough for controlled pilots. It is not yet strong enough for careless self-serve paid scaling or enterprise claims without the P0/P1 evidence above.
