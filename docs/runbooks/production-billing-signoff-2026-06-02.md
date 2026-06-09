# Production Billing Signoff Runbook - 2026-06-02

**Scope:** Manual production signoff for CaseOps SaaS billing, tenant downloads,
platform-admin billing visibility, and Pine Labs disabled-state safety.

**Do not:**

- Enable Pine Labs production payments.
- Make real Pine Labs calls.
- Mutate real customer subscriptions unless the founder explicitly approves the
  customer and action.
- Paste secrets, tokens, webhook secrets, API keys, or raw provider payloads into
  this document.

## Current Readiness

| Area | Status | Evidence owner |
|---|---|---|
| Billing implementation deployed | Pending manual evidence | Founder/operator |
| Pine Labs production payments | Disabled; must remain disabled | Founder/operator |
| Platform admin | Founder-only smoke pending | Founder |
| Tenant billing | Smoke pending on designated smoke tenant | Founder/operator |
| Tenant downloads/exports | Smoke pending on designated smoke tenant | Founder/operator |
| Tenant integrations registry | Smoke pending on designated smoke tenant | Founder/operator |
| Platform integrations/costs | Founder-only smoke pending | Founder |
| Margin simulation evidence | Founder-only smoke pending | Founder |
| Paid-production readiness console | Implemented; evidence pending | Founder |
| MFA/step-up protection | Implemented with founder grace path | Founder/operator |
| Password reset readiness metadata | Implemented; delivery evidence pending | Founder/operator |
| Internal cost/profit leakage | Smoke pending | Founder/operator |
| Backup/migration/deploy evidence | Pending attachment | Operator |

## Preconditions

- Production API and web app are deployed from the intended billing rollout
  revision.
- Database migration `20260531_0001` has run successfully.
- `CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL` is configured to the founder/company-owner
  account.
- `CASEOPS_PINE_LABS_ENV` is `disabled` in production.
- No production Pine Labs client secret/webhook secret is enabled for live
  payments.
- Migration `20260609_0002_p0_paid_production_safety` has run before using the
  paid-production readiness, MFA, settlement, or support-matrix records.
- MFA grace settings are deliberate for existing users. Defaults:
  `CASEOPS_MFA_EXISTING_USER_GRACE_DAYS=7`,
  `CASEOPS_MFA_STEP_UP_TTL_MINUTES=15`,
  `CASEOPS_MFA_MAX_FAILURES_PER_5M=5`.
- The pricing safety floor is deliberate. Default:
  `CASEOPS_BILLING_MINIMUM_GROSS_MARGIN_BPS=7000`.
- A designated production smoke tenant exists, or the founder approves creating
  one.
- A pre-rollout backup or point-in-time recovery marker exists.

## Public Safe Smoke Helper

Run the unauthenticated public-safe helper before authenticated founder smoke:

```powershell
uv --directory apps/api run python ..\..\scripts\prod_billing_safe_smoke.py
```

Override URLs for staging or a custom production host:

```powershell
uv --directory apps/api run python ..\..\scripts\prod_billing_safe_smoke.py `
  --api-base https://api.caseops.ai `
  --web-base https://caseops.ai
```

The helper checks only:

- `GET /api/health`
- `GET /api/billing/plans`
- `GET /pricing`
- `GET /api/platform-admin/overview` with no cookie or bearer token, expected
  to return `401`

It does not accept credentials, save screenshots, store response bodies, create
checkout sessions, or make Pine Labs calls.

## Authenticated Smoke Helper

Use the authenticated helper only after the founder has explicitly approved the
smoke account/session. Pass credentials through environment variables; the
script must not print secrets, cookies, bearer tokens, or raw payloads.

```powershell
$env:CASEOPS_SMOKE_API_BASE="https://api.caseops.ai"
$env:CASEOPS_SMOKE_BEARER_TOKEN="<founder-or-smoke-token>"
uv --directory apps/api run python ..\..\scripts\prod_billing_authenticated_smoke.py
```

Cookie mode is also supported:

```powershell
$env:CASEOPS_SMOKE_API_BASE="https://api.caseops.ai"
$env:CASEOPS_SMOKE_COOKIE="<session-cookie-header>"
uv --directory apps/api run python ..\..\scripts\prod_billing_authenticated_smoke.py
```

Expected authenticated checks:

- founder-only `/api/platform-admin/*` readiness endpoints return `200` for the
  founder session.
- tenant billing current, invoice, statement, credit ledger, payment export, and
  spend export routes are reachable for the smoke tenant session.
- disabled Pine checkout remains provider-disabled.
- tenant-facing responses do not contain internal finance/cost/profit field
  names.

## Evidence To Record

Record evidence outside this repo if it contains environment IDs, account names,
screenshots, or operational metadata that should not be committed.

| Evidence | Required value |
|---|---|
| Git commit/revision deployed | Commit SHA or release tag |
| API deploy evidence | Cloud Run revision/build id and deploy timestamp |
| Web deploy evidence | Cloud Run/hosting revision and deploy timestamp |
| Migration evidence | Migration job id/log showing `20260531_0001` success |
| Cost-profile migration evidence | Migration job id/log showing `20260608_0001` success, if deployed |
| P0 safety migration evidence | Migration job id/log showing `20260609_0002_p0_paid_production_safety` success |
| Backup evidence | Snapshot/PITR timestamp before migration/deploy |
| Rollback evidence | Last known previous revision and DB rollback posture |
| Smoke tenant | Company slug/id, not customer-sensitive |
| Founder smoke account | Founder email only if already public/approved |
| Cost-profile evidence | Source name only, effective date, category, unit minor/BPS; no invoices with secrets |
| Margin simulation evidence | Scenario name, revenue/cost/margin output, warnings, screenshot/link stored externally |
| Pine UAT evidence row | Scenario code, status, provider order id, webhook id, timestamp, redacted payload reference, attachment reference |
| Billing signoff evidence row | Check code, pass/fail/blocked status, evidence reference, operator notes, recorded timestamp |
| Password reset readiness | Reset link domain, reset path, sender name, template kind, TTL, provider configured boolean |
| Finance operations evidence | Settlement import id, exception count, export filename/hash, accountant review location |
| Case support matrix evidence | Provider, court, lookup method, cost source reference, enabled/disabled state |

## Founder-Only Platform Admin Smoke

1. Sign in as the configured founder/company-owner.
2. Open `/app/platform-admin`.
3. Confirm the dashboard loads and shows operating counters.
4. Open `/app/platform-admin/profit`.
5. Confirm profit/revenue tables and export buttons are visible.
6. Open `/app/platform-admin/provider-events`.
7. Confirm provider-event search loads without requiring Pine Labs live mode.
8. Open `/app/platform-admin/integrations`.
9. Confirm connector readiness includes Pine Labs, SendGrid, SMS, WhatsApp,
   case tracking, PRS/legal updates, Temporal, ClamAV, and storage.
10. Open `/app/platform-admin/costs`.
11. Confirm existing cost profiles load, and run a no-side-effect margin
    simulation using founder-approved test quantities.
12. Confirm case-refresh cost warnings appear when the configured actual cost is
    INR 0.10 or more per tracked-case refresh equivalent.
13. Open `/app/platform-admin/paid-production`.
14. Confirm Pine Labs UAT evidence, production billing signoff, margin
    readiness, password reset readiness, reconciliation exceptions, and case
    support matrix load.
15. Confirm any go/no-go or evidence mutation requires recent MFA step-up when
    the founder MFA policy is active.
16. Sign in as a tenant owner/admin that is not the configured founder.
17. Open `/app/platform-admin`.
18. Confirm access denied.
19. Confirm backend route denial with a non-founder token for at least:
    - `GET /api/platform-admin/overview`
    - `GET /api/platform-admin/integrations`
    - `GET /api/platform-admin/cost-profiles`
    - `GET /api/platform-admin/margin-simulations`
    - `GET /api/platform-admin/pine-labs/uat-readiness`
    - `GET /api/platform-admin/billing-signoff`
    - `GET /api/platform-admin/margin-readiness`
    - `GET /api/platform-admin/password-reset-readiness`
    - `GET /api/platform-admin/profit/export`
    - `GET /api/platform-admin/provider-events`
20. Confirm platform access and denials write audit rows.

Expected result: only the configured founder has platform-admin access. Tenant
owner/admin roles alone do not grant platform-admin capabilities.

## Tenant Integrations Smoke

Run this only on the designated smoke tenant.

1. Sign in as a workspace owner/admin.
2. Open `/app/admin/integrations`.
3. Call or inspect `GET /api/admin/integrations`.
4. Confirm the connector list includes:
   - Outlook calendar
   - Microsoft mailbox readiness
   - Gmail
   - Google Calendar
   - Google Drive
   - Pine Labs
   - SendGrid
   - SMS
   - WhatsApp
   - Case tracking provider
   - PRS/legal updates
   - Temporal
   - ClamAV
   - Storage
5. Confirm missing credentials show disabled or blocked state and no provider
   calls occur.
6. Confirm response fields are safe names/status only and do not include
   platform cost/risk labels, secrets, tokens, raw signatures, provider raw
   payloads, internal fees, gross profit, or gross margin.
7. Confirm the registry view writes a tenant audit row
   `connector_registry.viewed`.

Expected result: tenant admins can understand integration readiness without
seeing platform-only costs, profit, or secret material.

## Founder Cost And Margin Smoke

Run only as the configured founder/company-owner.

1. Open `/app/platform-admin/costs`.
2. Call or inspect `GET /api/platform-admin/cost-profiles`.
3. Create or update only founder-approved non-secret cost-profile records:
   - category
   - provider label
   - currency `INR`
   - unit minor amount or BPS
   - effective date
   - source name
   - notes without secrets or invoice payloads
4. Run `POST /api/platform-admin/margin-simulations/run` with smoke quantities.
5. Confirm the saved simulation appears in
   `GET /api/platform-admin/margin-simulations`.
6. Confirm actions write platform audit rows:
   - `platform.cost_profiles.viewed`
   - `platform.cost_profile.created`
   - `platform.cost_profile.updated`, if updated
   - `platform.margin_simulation.ran`
7. Confirm tenant APIs and pages do not expose the cost profile or simulation
   fields.
8. Call or inspect `GET /api/platform-admin/margin-readiness`.
9. Confirm readiness is blocked until every required scenario has a dated
   simulation meeting `CASEOPS_BILLING_MINIMUM_GROSS_MARGIN_BPS` and approved
   actual costs.

Expected result: configured actual costs are visible only to founder platform
admin and are used by founder-only calculations, with fallback defaults when no
actual profile exists.

## Founder Paid-Production Readiness Evidence

Run only as the configured founder/company-owner.

Required Pine Labs UAT evidence fields per scenario:

- scenario code
- result status: `pending`, `pass`, `fail`, `blocked`, or `not_applicable`
- provider order id, if applicable
- provider payment id, if applicable
- webhook id, if applicable
- webhook timestamp, if applicable
- redacted payload sample or external reference
- screenshot/attachment reference, if stored externally
- operator notes
- recorded timestamp

Production activation pass/fail criteria:

- Pass only when all required UAT scenarios are `pass` and the founder records
  `go`.
- Fail/block when any required scenario is missing, failed, blocked, or
  unverified.
- Recording `go` only records readiness. It must not flip
  `CASEOPS_PINE_LABS_ENV`, enable subscriptions, or enable live Pine Labs calls.

Required billing signoff evidence fields:

- check code
- result status
- evidence reference
- optional structured evidence with no secrets
- operator notes
- recorded timestamp

Billing signoff pass/fail criteria:

- Pass only when every required check is `pass`.
- Fail/block if tenant access, tenant downloads, disabled checkout behavior, or
  no-leak checks cannot be verified.
- Any tenant-facing response or export containing internal cost/profit/provider
  fee/gross margin fields is a blocker.

Password reset readiness pass/fail criteria:

- `GET /api/platform-admin/password-reset-readiness` shows the expected reset
  domain, `/account/reset-password` path, sender name, template kind, and TTL.
- Response does not contain SendGrid API keys, auth secrets, raw reset tokens,
  webhook secrets, or provider payloads.
- Production delivery remains pending until
  `scripts/prod_password_reset_smoke.py` proves a real reset email can be
  requested and completed by the intended user.

## Tenant Billing Smoke

Run this only on the designated smoke tenant.

1. Sign in as a workspace owner/admin.
2. Open `/app/admin/billing`.
3. Confirm current subscription, entitlements, usage summary, provider state, and
   add-on controls render.
4. Call or inspect `GET /api/billing/current`.
5. Confirm response includes:
   - `subscription`
   - `entitlements`
   - `usage`
   - `payment_provider.provider = "pine_labs_plural"`
   - `payment_provider.provider_disabled = true`
6. Start a checkout for a low-risk plan or add-on on the smoke tenant.
7. Confirm checkout response:
   - `status = "provider_disabled"`
   - `provider_disabled = true`
   - `provider_checkout_url = null`
   - `next_action = "provider_disabled"`
8. Sync the checkout.
9. Confirm sync remains `provider_disabled`.
10. Confirm the tenant subscription did not change to a paid plan because no
    verified payment occurred.

Expected result: billing UI works, checkout records are safe, and Pine Labs
disabled mode does not charge or activate paid subscriptions.

## Tenant Downloads And Exports

Run from `/app/admin/billing` and `/app/admin/billing/usage` on the smoke tenant.

| Download | Endpoint | Expected |
|---|---|---|
| Statement CSV | `GET /api/billing/statement` | Downloads CSV |
| Statement PDF | `GET /api/billing/statement?format=pdf` | Downloads PDF |
| Payments CSV | `GET /api/billing/payments/export` | Downloads tenant-scoped CSV |
| Credit ledger CSV | `GET /api/billing/credit-ledger/export` | Downloads tenant-scoped CSV |
| Spend CSV | `GET /api/billing/reports/spend/export` | Downloads quantities/credits only |
| Invoice PDF | `GET /api/billing/invoices/{invoice_id}/download` | Downloads tenant invoice if invoice exists |
| Invoice JSON | `GET /api/billing/invoices/{invoice_id}/download?format=json` | Downloads tenant invoice JSON if invoice exists |

Expected result: every download is tenant-scoped, authenticated, and audited.
When MFA policy is active for the actor, export/download routes must return a
step-up challenge until recent MFA is present.

## No Internal Cost Or Profit Leakage

Check tenant-facing screens and downloads for these forbidden fields/labels:

- `estimated_internal_cost`
- `payment_provider_cost`
- `payment_gateway_cost`
- `llm_cost`
- `embedding_cost`
- `case_refresh_cost`
- `total_variable_cost`
- `gross_profit`
- `gross_margin`
- `profit`
- `margin`

Allowed tenant-facing billing data:

- plan and subscription status
- entitlement limits
- usage quantities
- AI credit debits/balances
- invoice totals/tax/paid amounts
- payment order status and merchant reference

Expected result: internal cost/profit appears only in founder-only platform-admin
views and exports.

## Pine Labs Disabled-State Verification

Production must remain in disabled state for this signoff.

Verify:

- `GET /api/billing/current` reports `payment_provider.provider_disabled = true`.
- `GET /api/payments/config` returns `pine_labs_configured = false` unless the
  environment has non-live UAT credentials deliberately staged outside
  production payments.
- Checkout creates no real provider URL.
- API logs show no outbound Pine Labs payment-link/status/token calls during
  this smoke.
- No `billing_payment_orders` row transitions to `paid` from a provider-disabled
  checkout.
- No subscription changes from grandfathered/manual/trial to active paid unless
  manually and intentionally changed by the founder.

## Backup, Migration, And Deploy Evidence

Attach or record externally:

- Backup/PITR marker taken before migration.
- Migration job log showing `20260531_0001` success.
- API deploy log/revision.
- Web deploy log/revision.
- Post-deploy health check result.
- Rollback target revision.
- Any schema/version query output used to prove migration state.

Do not commit raw cloud logs if they contain secrets, tokens, internal IPs, or
customer-sensitive data.

## Known Caveats

- Pine Labs live payments are not enabled and are not signed off by this runbook.
- Provider-disabled checkout proves CaseOps safety behavior, not Pine Labs UAT or
  production correctness.
- Subscription/UPI AutoPay provider flows require Pine Labs UAT and merchant
  enablement.
- Internal cost assumptions remain estimates until real provider/model/storage
  invoices and settlement reports are reconciled.
- Manual invoice PDF/JSON is operationally usable but final accountant-approved
  invoice copy/formatting may still need refinement.
- Refund policy text remains unpublished until finance/legal approves it.
- Platform admin is founder-only at launch; adding more platform admins requires
  a separate security review.

## Signoff

| Gate | Result | Evidence link/location | Signoff |
|---|---|---|---|
| Founder-only platform admin smoke | Pending |  |  |
| Tenant billing smoke | Pending |  |  |
| Tenant downloads/exports | Pending |  |  |
| Tenant integrations registry | Pending |  |  |
| Founder integrations/costs/margin simulation | Pending |  |  |
| Pine Labs disabled-state verification | Pending |  |  |
| No tenant cost/profit leakage | Pending |  |  |
| Backup/migration/deploy evidence | Pending |  |  |
| Known caveats accepted | Pending |  |  |
| MFA/step-up protected founder flows | Pending |  |  |
| Password reset readiness and delivery smoke | Pending |  |  |
| Settlement/refund/credit-note/chargeback/TDS exports | Pending |  |  |
| Case tracking support matrix no-leak check | Pending |  |  |

Production billing is ready for manual founder smoke when all preconditions are
true. It is signed off only after every gate above is marked pass with evidence.
