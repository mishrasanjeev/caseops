# CaseOps Billing - End-to-End Explainer

**Status:** Reviewed against implementation on 2026-06-02
**Catalog version:** `2026.05.v1`
**Currency:** INR only. Monetary values are stored in minor units (paisa).
**Payment rail:** Pine Labs Plural V2, currently safe by configuration when `pine_labs_env=disabled`.

## 2026-06-13 Readiness Update

Status labels for billing:

- Tenant subscription billing, plan usage, included quota, overages, add-on
  credits, invoices, downloads, statements, and spend reports are `live` or
  `review-first` where human confirmation is required.
- Platform revenue, provider cost, gross margin, credits, refunds,
  chargebacks, settlement mismatch, TDS/GST, and tenant profitability reports
  are `founder-only`.
- Pine Labs production payment acceptance is `disabled until UAT`.
- Settlement, refund, credit note, chargeback, GST/TDS, idempotency, webhook,
  and founder activation evidence is readiness scaffolding and does not enable
  live money movement.
- Any plan, add-on, or overage policy that can become loss-making must be
  blocked by margin readiness or explicitly marked with a founder-only warning.

Tenant-facing APIs/UI must never expose provider fees, internal costs, gross
profit, margin, platform-only notes, raw provider payloads, OAuth tokens, or
webhook secrets.

Operational source of truth:

- Catalog seed and grandfathering: `apps/api/alembic/versions/20260531_0001_pricing_billing_plural_platform_admin.py`
- SaaS billing service: `apps/api/src/caseops_api/services/saas_billing.py`
- Pine Labs client and webhook verification: `apps/api/src/caseops_api/services/pine_labs.py`
- Payment webhook router/dispatcher: `apps/api/src/caseops_api/services/payments.py`
- Tenant billing API: `apps/api/src/caseops_api/api/routes/billing.py`
- Platform admin API: `apps/api/src/caseops_api/api/routes/platform_admin.py`
- Settings: `apps/api/src/caseops_api/core/settings.py`
- Product spec: `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`

This document is operational documentation, not a product roadmap. If the seed
migration or billing service changes, update this file in the same PR.

---

## 1. Two Billing Systems

CaseOps has two separate billing surfaces.

| System | What it bills | Who pays | Main code |
|---|---|---|---|
| SaaS billing | CaseOps subscriptions, add-ons, AI credits, tenant invoices | Tenant pays CaseOps | `saas_billing.py`, `billing_*` tables |
| Matter invoicing | A law firm's own invoices to its clients | Firm client pays the firm | `payments.py`, `matter_invoice*` tables |

This explainer is about SaaS billing. Matter invoicing shares the Pine Labs
rail and webhook endpoint, but it is a different data model and revenue owner.

---

## 2. Pricing Catalog

Catalog version `2026.05.v1` is seeded in the 2026-05-31 migration. Prices are
stored as paisa. Tax is stored per price with `tax_rate_bps = 1800`.

- Solo plan sticker prices are GST-inclusive.
- Firm, GC, and add-on prices are GST-exclusive.
- `amount_minor = None` plus interval `custom` means contact sales.
- Existing tenants at migration time are grandfathered onto
  `grandfathered_free`, source `migration`, `externally_billable = false`.

### Free Trial

| Field | Value |
|---|---|
| Plan code | `trial` |
| Length | 14 days, no card required |
| Internal users | 2 |
| Viewers | 0 |
| Active matters | 10 |
| Tracked cases | 10 |
| AI credits | 25 |
| Storage | 500 MB |
| Manual refreshes/day | 2 |
| Refresh cadence | `weekday_daily` |

Duplicate trials are blocked by email domain, mobile, and GSTIN through
`assert_trial_start_allowed()`.

### Solo Plans

| Plan code | Name | Monthly | Annual | Users | Matters | Tracked cases | AI credits/mo | Storage | Refresh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `solo_core` | Solo Core | INR 999 | INR 9,990 | 2 | 50 | 50 | 100 | 2 GB | `weekday_daily` |
| `solo_pro` | Solo Pro | INR 1,999 | INR 19,990 | 4 | 250 | 200 | 300 | 10 GB | `daily` |
| `solo_elite` | Solo Elite | INR 3,999 | INR 39,990 | 6 | 1,000 | 750 | 800 | 50 GB | `priority_daily` |

Solo plans have 0 viewers. `solo_elite` includes basic audit export.

### Law Firm Plans

| Plan code | Name | Monthly | Annual | Users | Viewers | Matters | Tracked cases | AI credits/mo | Storage | Refresh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `firm_starter` | Firm Starter | INR 5,999 | INR 62,990 | 5 | 0 | 300 | 250 | 300 | 25 GB | `smart_weekday_daily` |
| `firm_growth` | Firm Growth | INR 19,999 | INR 2,09,990 | 15 | 10 | 1,500 | 1,000 | 1,200 | 150 GB | `smart_daily` |
| `firm_pro` | Firm Pro | INR 49,999 | INR 5,24,990 | 50 | 50 | 5,000 | 2,500 | 3,000 | 500 GB | `priority_smart_daily` |
| `firm_enterprise` | Firm Enterprise | Custom | Custom | Unlimited | Unlimited | Unlimited | Unlimited | Unlimited | Unlimited | custom |

`firm_growth` exposes API as an add-on. `firm_pro` includes API access and SSO
readiness. Enterprise is custom and should not be self-served without a margin
review.

### Corporate / GC Plans

| Plan code | Name | Annual | Users | Viewers | Matters | Tracked cases | AI credits/mo | Storage | Refresh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `gc_monitoring` | Litigation Monitoring Only | INR 1,50,000 | 3 | 25 | 500 | 5,000 | 1,000 | 50 GB | `daily` |
| `gc_starter` | GC Starter | INR 3,00,000 | 5 | 25 | 1,000 | 5,000 | 10,000 | 250 GB | `daily` |
| `gc_professional` | GC Professional | INR 8,00,000 | 15 | 100 | 10,000 | 25,000 | 30,000 | 1 TB | `priority_daily` |
| `gc_enterprise` | GC Enterprise | Custom | Unlimited | Unlimited | Unlimited | Unlimited | Unlimited | Unlimited | custom |

`gc_professional` includes API access and SSO readiness. `gc_enterprise`
includes API and SSO readiness by contract; full OIDC/SAML SSO and SCIM remain
planned until tenant IdP UAT, metadata validation, and lifecycle evidence are
complete.

### Add-ons

| Add-on code | Name | Price | Billing | Grants |
|---|---|---:|---|---|
| `addon_user_firm` | Extra firm user | INR 699 | monthly | +1 internal user |
| `addon_user_corporate_legal` | Extra corporate legal user | INR 1,500 | monthly | +1 internal user |
| `addon_viewer` | Extra viewer | INR 199 | monthly | +1 viewer |
| `addon_cases_500` | Tracked case pack 500 | INR 2,499 | monthly | +500 tracked cases |
| `addon_cases_1000` | Tracked case pack 1000 | INR 4,499 | monthly | +1,000 tracked cases |
| `addon_ai_250` | AI credit pack 250 | INR 1,199 | one-time | +250 credits, 12-month expiry |
| `addon_ai_1000` | AI credit pack 1000 | INR 3,999 | one-time | +1,000 credits, 12-month expiry |
| `addon_ai_5000` | AI credit pack 5000 | INR 14,999 | one-time | +5,000 credits, 12-month expiry |
| `addon_storage_100gb` | Extra storage 100 GB | INR 1,499 | monthly | +100 GB |
| `addon_api_access` | API access | INR 5,000 | monthly | API keys and dashboard |
| `addon_migration_basic` | Basic migration | INR 10,000 | one-time | CSV import and setup |
| `addon_migration_firm` | Firm migration | INR 25,000 | one-time | matter/client/document import |
| `addon_migration_enterprise` | Enterprise migration | INR 75,000 | one-time | custom mapping, QA, launch |
| `addon_research_memo` | Legal research memo | INR 5,000 | one-time | assisted memo |

All add-ons are GST-exclusive.

---

## 3. Entitlements

Entitlements are flat key/value records seeded in `billing_plan_entitlements`.
Effective entitlements are resolved at request time:

```text
effective entitlements =
  base plan entitlements
  + active subscription add-on entitlements
  + subscription.entitlement_overrides_json
```

Numeric add-on values stack. Subscription overrides win and are intended for
audited admin or contract exceptions.

Important keys:

| Key | Meaning |
|---|---|
| `users_internal_limit` | Internal users such as lawyer/staff/admin |
| `users_viewer_limit` | Viewer/business users |
| `matters_active_limit` | Active matter cap |
| `tracked_cases_limit` | Case-tracking cap |
| `ai_credits_monthly` | Included AI credits per cycle |
| `storage_bytes_limit` | Document storage cap |
| `manual_case_refreshes_daily` | Manual refresh cap per day |
| `case_refresh_cadence` | Scheduled polling class |
| `api_access_enabled` | false, true, `add_on`, or `ready` |
| `audit_export_enabled` | false, true, or `basic` |
| `sso_enabled` | false, true, or `ready` |

`None` means unlimited or contract-defined for numeric limits.

---

## 4. Credits, Usage, And Internal Costs

AI credits are tracked in `billing_credit_ledger`.

- Included monthly credits reset each billing cycle and do not roll over.
- Purchased AI packs use top-up credits and expire after 12 months.
- Consumption uses included credits first, then top-up credits.
- Grant/debit/refund/expiry events keep `balance_after`.

Usage metering uses `billing_usage_events` plus
`billing_usage_attribution`. Tenant-visible reporting is limited to rows where
`tenant_visible = true`.

Tenant reports expose quantities and credits through:

- `GET /api/billing/usage`
- `GET /api/billing/reports/spend`
- `GET /api/billing/reports/spend/export`

Internal cost fields, gross profit, and gross margin are platform-admin-only and
must not appear in tenant responses or tenant downloads.

Internal cost assumptions currently come from settings:

| Setting | Default | Meaning |
|---|---:|---|
| `billing_case_refresh_cost_minor` | 2 | INR 0.02 per refresh assumption |
| `billing_llm_cost_minor_per_credit` | 100 | INR 1.00 estimated cost per AI credit |
| `billing_payment_gateway_fee_bps` | 200 | 2% gateway-cost assumption |
| `billing_storage_cost_minor_per_gb_month` | 100 | INR 1.00 per GB-month assumption |
| `billing_company_gstin` | `09AANCM5923C1ZD` | CaseOps GSTIN on invoices |

Quota guards fail closed through functions such as `assert_user_limit()`,
`assert_matter_limit()`, `assert_tracked_case_limit()`,
`assert_manual_refresh_limit()`, and `effective_storage_quota()`.

---

## 5. Subscription And Checkout Lifecycle

```text
trial/demo -> checkout -> verified payment -> active subscription
                           |
                           +-> provider disabled: safe record only, no activation
```

Main tenant endpoints:

- `GET /api/billing/plans`
- `GET /api/billing/current`
- `POST /api/billing/checkout`
- `GET /api/billing/checkout/{session_id}`
- `POST /api/billing/checkout/{session_id}/sync`
- `POST /api/billing/subscription/cancel`
- `POST /api/billing/subscription/reactivate`
- `POST /api/billing/trials`
- `POST /api/billing/enrollments/demo-request`
- `GET /api/billing/add-ons`
- `POST /api/billing/add-ons/checkout`

Activation only happens after a paid status from a verified webhook or provider
status sync. Frontend redirects are provisional.

When `pine_labs_env=disabled`, checkout creates a `provider_disabled` checkout
record and payment order, but there is no external call, no payment URL, no paid
state, and no subscription activation. `mock` mode is the test/demo stub that can
simulate paid syncs; it is not production live-payment evidence.

---

## 6. Pine Labs Plural Integration

Provider readiness is computed in `provider_readiness()`:

- `mode`: normalized `pine_labs_env`
- `configured`: base URL, payment link path, merchant id, and credentials present
- `provider_disabled`: true when mode is disabled/off/false or config is incomplete
- `mock`: true only for `pine_labs_env=mock`
- `subscriptions_enabled`: settings flag, default false

Real SaaS payment-link creation uses `PineLabsGatewayClient`:

1. Fetch bearer token from `/api/auth/v1/token` using `client_credentials`.
2. Create a payment link using `pine_labs_payment_link_path`.
3. Send `Authorization: Bearer ...`, `Request-ID`, and `Request-Timestamp`.
4. Send amount as `{ "value": <paisa>, "currency": "INR" }`.
5. Use `merchant_payment_link_reference` as CaseOps idempotency reference.
6. Store provider order/payment URL after redacting sensitive payload fields.

The webhook endpoint is:

```text
POST /api/payments/pine-labs/webhook
```

Plural webhooks are trusted only when these headers verify:

- `webhook-id`
- `webhook-timestamp`
- `webhook-signature`

Signed content is:

```text
{webhook-id}.{webhook-timestamp}.<raw body>
```

The implementation validates an HMAC-SHA256 base64 digest, supports raw or
base64-encoded webhook secret material, and rejects timestamps outside
`pine_labs_webhook_tolerance_seconds` (default 300 seconds). The dispatcher also
keeps legacy matter-invoice signature support for old `X-PineLabs-Signature`
payloads.

SaaS provider events are stored in `billing_provider_events`, unique by provider
event id and webhook id, with redacted payloads and processing status. Duplicate
events are idempotent. Out-of-order non-paid events do not downgrade already-paid
orders.

---

## 7. Tenant Isolation

- Billing tables are scoped by `company_id`.
- Tenant billing routes query only the current company.
- Tenant usage reports include only `tenant_visible = true`.
- Tenant downloads are tenant-scoped and audited.
- Platform-admin routes are separate under `/api/platform-admin`.
- Founder-only platform-admin access is enforced by
  `CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL` matching an active owner user.
- Non-founder tenant owners/admins receive 403 on platform-admin routes.

Tenant downloads:

- Invoice PDF/JSON: `/api/billing/invoices/{invoice_id}/download`
- Statement CSV/PDF: `/api/billing/statement`
- Payment CSV: `/api/billing/payments/export`
- Credit ledger CSV: `/api/billing/credit-ledger/export`
- Spend CSV: `/api/billing/reports/spend/export`

---

## 8. Platform Admin Console

Platform admin is founder-only at launch. Capabilities include:

- `platform:admin`
- `platform:billing_view`
- `platform:billing_manage`
- `platform:payment_reconcile`
- `platform:plan_manage`
- `platform:usage_view`
- `platform:manual_override`

Main endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/platform-admin/overview` | MRR, ARR, active subscriptions, trials, failed payments, revenue, cost, margin alerts |
| `GET /api/platform-admin/enrollments` | Trial/demo enrollment list |
| `GET /api/platform-admin/companies/{company_id}/billing` | Company billing detail |
| `POST /api/platform-admin/companies/{company_id}/subscription` | Manual plan/status mutation |
| `POST /api/platform-admin/companies/{company_id}/credits/grant` | Manual credit grant |
| `POST /api/platform-admin/manual-invoices` | Manual invoice creation |
| `POST /api/platform-admin/manual-invoices/{invoice_id}/mark-paid` | Offline payment/TDS reconciliation |
| `GET /api/platform-admin/provider-events` | Provider webhook/event search |
| `POST /api/platform-admin/provider-events/{event_id}/reprocess` | Manual reprocess request marker |
| `GET /api/platform-admin/usage-report` | Cross-tenant usage and internal cost |
| `GET /api/platform-admin/profit-report` | Internal profit rollups |
| `GET /api/platform-admin/profit/export` | Internal profit CSV |
| `GET /api/platform-admin/revenue/export` | Internal revenue CSV |
| `GET /api/platform-admin/coupons` / `POST /api/platform-admin/coupons` | Coupon management |
| `PUT /api/platform-admin/companies/{company_id}/overage-policy` | Overage policy management |
| `GET /api/platform-admin/margin-alerts` | Low-margin/loss-risk alerts |

Every platform-admin access/mutation is audited in
`platform_admin_audit_events`.

---

## 9. Known Operational Caveats

- Pine Labs production payments must remain disabled until UAT is completed and
  production go/no-go gates pass.
- Provider-disabled checkout is not proof of live Pine Labs correctness.
- Subscription/UPI AutoPay settings exist, but provider enablement and UAT are
  not complete.
- Manual invoices currently provide simple PDF/JSON/CSV artifacts; final finance
  invoice formatting and numbering rules still need accountant/legal approval.
- Internal cost values are estimates until real provider, model, storage,
  settlement, and support cost inputs are reconciled.
- Refund policy copy is intentionally not published until approved.

---

## 10. Operational Smoke Summary

Minimum production smoke for billing signoff:

1. Founder can access `/app/platform-admin`; non-founder tenant admin receives
   access denied.
2. Tenant admin can open `/app/admin/billing` and `/app/admin/billing/usage`.
3. `GET /api/billing/current` shows tenant subscription, entitlements, usage, and
   `payment_provider.provider_disabled = true` while Pine Labs is disabled.
4. A smoke checkout returns `provider_disabled = true`, no provider checkout URL,
   and does not activate a paid plan after sync.
5. Tenant downloads work and contain no internal cost, profit, or margin fields.
6. Platform profit/revenue exports are founder-only.
7. Migration, deploy, backup, and rollback evidence are attached in the signoff
   runbook.
