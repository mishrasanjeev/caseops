# CaseOps Billing — End-to-End Explainer

**Status:** Current as of 2026-06-02
**Catalog version:** `2026.05.v1`
**Currency:** INR only (all monetary values stored in *minor* units — paisa; divide by 100 for rupees)
**Payment provider:** Pine Labs **Plural** (V2 OAuth + webhooks)

> Source of truth for this document:
> - Pricing/entitlements seed: `apps/api/alembic/versions/20260531_0001_pricing_billing_plural_platform_admin.py`
> - SaaS billing service: `apps/api/src/caseops_api/services/saas_billing.py`
> - Payments + provider: `apps/api/src/caseops_api/services/payments.py`, `services/pine_labs.py`
> - Settings: `apps/api/src/caseops_api/core/settings.py`
> - Product spec: `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`
>
> Every price, limit, and tax value quoted below is copied directly from the seed
> migration, not inferred. If you change the seed, update this doc in the same PR.

---

## 1. What "billing" means in CaseOps

CaseOps has **two distinct billing systems**. Don't confuse them:

| System | What it bills | Who pays | Code |
|---|---|---|---|
| **SaaS billing** | The CaseOps subscription itself (a company's plan, add-ons, AI credits) | The tenant pays CaseOps | `saas_billing.py`, `billing_*` tables |
| **Matter invoicing** (legacy) | A law firm billing *its own clients* for time on a matter | The firm's client pays the firm | `payments.py`, `matter_invoice*` tables |

Both ride on the same payment rail (Pine Labs Plural payment links), but they are
separate data models, separate routes, and separate UX. **This document is about
SaaS billing** — the money flowing from tenants to CaseOps. Matter invoicing is
covered in §10 for completeness.

---

## 2. The pricing model at a glance

Four customer segments, each a ladder of plans, plus a free trial and an add-on
catalog. Everything is INR. Plans are seeded under catalog version `2026.05.v1`.

- **Tax behavior is per-price.** Solo plans are **tax-inclusive** (the sticker
  price already contains 18% GST). Firm, GC, and all add-ons are **tax-exclusive**
  (18% GST is added on top at checkout). GST rate is `1800` bps = **18%**, seeded
  on every price as `tax_rate_bps`.
- **Minor units everywhere.** A monthly price of `99900` means ₹999.00.
- **`None` price + `custom` interval** = "Contact sales" (enterprise tiers).

### 2.1 Free Trial

| Field | Value |
|---|---|
| Plan code | `trial` |
| Length | **14 days, no card required** |
| Internal users | 2 |
| Viewers | 0 |
| Active matters | 10 |
| Tracked cases | 10 |
| AI credits / month | 25 |
| Storage | 500 MB |
| Manual case refreshes / day | 2 |
| Case-refresh cadence | weekday_daily |
| API / audit export / SSO | off |

Trial abuse is blocked by `assert_trial_start_allowed()` — duplicate trials are
rejected by email domain, mobile, and GSTIN.

### 2.2 Solo plans (tax-**inclusive** sticker prices)

| Plan code | Name | Monthly | Annual | Int. users | Matters | Tracked cases | AI cr./mo | Storage | Refresh cadence |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| `solo_core` | Solo Core | ₹999 | ₹9,990 | 2 | 50 | 50 | 100 | 2 GB | weekday_daily |
| `solo_pro` | Solo Pro | ₹1,999 | ₹19,990 | 4 | 250 | 200 | 300 | 10 GB | daily |
| `solo_elite` | Solo Elite | ₹3,999 | ₹39,990 | 6 | 1,000 | 750 | 800 | 50 GB | priority_daily |

(Solo "internal users" bundle the lawyer + support staff. Solo plans have 0 viewers.
`solo_elite` adds `audit_export = basic`.)

### 2.3 Law-firm plans (tax-**exclusive**; GST added on top)

| Plan code | Name | Monthly | Annual | Int. users | Viewers | Matters | Tracked cases | AI cr./mo | Storage | Refresh cadence |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `firm_starter` | Firm Starter | ₹5,999 | ₹62,990 | 5 | 0 | 300 | 250 | 300 | 25 GB | smart_weekday_daily |
| `firm_growth` | Firm Growth | ₹19,999 | ₹2,09,990 | 15 | 10 | 1,500 | 1,000 | 1,200 | 150 GB | smart_daily |
| `firm_pro` | Firm Pro | ₹49,999 | ₹5,24,990 | 50 | 50 | 5,000 | 2,500 | 3,000 | 500 GB | priority_smart_daily |
| `firm_enterprise` | Firm Enterprise | Custom | Custom | ∞ | ∞ | ∞ | ∞ | ∞ | ∞ | SLA/custom |

- Annual = roughly 10.5 months of the monthly rate (≈1.5 months free).
- `firm_growth` exposes API as an **add-on**; `firm_pro` includes API + `sso = ready`.
- `firm_enterprise` is "Contact sales" — all limits `None` (unlimited / negotiated).

### 2.4 Corporate / General-Counsel plans (annual only, tax-**exclusive**)

| Plan code | Name | Annual | Int. users | Viewers | Matters | Tracked cases | AI cr./mo | Storage | Refresh |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| `gc_monitoring` | Litigation Monitoring Only | ₹1,50,000 | 3 | 25 | 500 | 5,000 | 1,000 | 50 GB | daily |
| `gc_starter` | GC Starter | ₹3,00,000 | 5 | 25 | 1,000 | 5,000 | 10,000 | 250 GB | daily |
| `gc_professional` | GC Professional | ₹8,00,000 | 15 | 100 | 10,000 | 25,000 | 30,000 | 1 TB | priority_daily |
| `gc_enterprise` | GC Enterprise | Custom | ∞ | ∞ | ∞ | ∞ | ∞ | ∞ | SLA/custom |

`gc_monitoring` is the "wedge" plan — corporate legal teams that only want
case-tracking + alerts. `gc_professional` includes API + `sso = ready`;
`gc_enterprise` includes API + full SSO.

### 2.5 Add-ons

Add-ons attach to a subscription as `billing_subscription_items`. Recurring add-ons
stack their entitlement onto the base plan; one-time add-ons grant a credit pack or a
service with **no recurring mandate**.

| Add-on code | Name | Price | Billing | Grants |
|---|---|--:|---|---|
| `addon_user_firm` | Extra firm user | ₹699 | /mo | +1 internal user |
| `addon_user_corporate_legal` | Extra corporate legal user | ₹1,500 | /mo | +1 internal user |
| `addon_viewer` | Extra viewer | ₹199 | /mo | +1 viewer |
| `addon_cases_500` | Tracked case pack 500 | ₹2,499 | /mo | +500 tracked cases |
| `addon_cases_1000` | Tracked case pack 1000 | ₹4,499 | /mo | +1,000 tracked cases |
| `addon_ai_250` | AI credit pack 250 | ₹1,199 | one-time | +250 credits, 12-mo expiry |
| `addon_ai_1000` | AI credit pack 1000 | ₹3,999 | one-time | +1,000 credits, 12-mo expiry |
| `addon_ai_5000` | AI credit pack 5000 | ₹14,999 | one-time | +5,000 credits, 12-mo expiry |
| `addon_storage_100gb` | Extra storage 100 GB | ₹1,499 | /mo | +100 GB |
| `addon_api_access` | API access | ₹5,000 | /mo | API keys + dashboard |
| `addon_migration_basic` | Basic migration | ₹10,000 | one-time | CSV import + setup |
| `addon_migration_firm` | Firm migration | ₹25,000 | one-time | matter/client/doc import |
| `addon_migration_enterprise` | Enterprise migration | ₹75,000 | one-time | custom mapping, QA, launch |
| `addon_research_memo` | Legal research memo | ₹5,000 | one-time | human/editor-assisted memo |

All add-on prices are tax-exclusive (GST added on top).

---

## 3. Entitlements — how a plan becomes enforced limits

Every plan and add-on carries a flat dictionary of **entitlement keys**, seeded into
`billing_plan_entitlements`. The keys that matter:

| Entitlement key | Meaning | `None` means |
|---|---|---|
| `users_internal_limit` | Max internal (lawyer/staff/admin) users | unlimited |
| `users_viewer_limit` | Max viewer/business users | unlimited |
| `matters_active_limit` | Max simultaneously-active matters | unlimited |
| `tracked_cases_limit` | Max cases under court-tracking | unlimited |
| `ai_credits_monthly` | Credits granted each billing cycle | unlimited |
| `storage_bytes_limit` | Document storage cap | unlimited |
| `manual_case_refreshes_daily` | On-demand case refreshes per day | unlimited |
| `case_refresh_cadence` | Automatic polling cadence (e.g. `smart_daily`) | — |
| `api_access_enabled` | `True` / `False` / `"add_on"` / `"ready"` | — |
| `audit_export_enabled` | `True` / `False` / `"basic"` | — |
| `sso_enabled` | `True` / `False` / `"ready"` | — |

**Effective entitlements** for a tenant are computed at request time by
`resolve_entitlements(session, subscription)`:

```
effective = base plan entitlements
          + Σ entitlements from active subscription add-on items (numeric keys add up)
          + entitlement_overrides_json on the subscription (admin/contract overrides win)
```

So a `firm_growth` tenant (1,000 tracked cases) plus two `addon_cases_1000` items
gets 3,000 tracked cases. A negotiated enterprise deal can stamp arbitrary overrides
onto `entitlement_overrides_json` without minting a new plan.

---

## 4. AI credits & usage metering

CaseOps meters the variable-cost work (LLM calls, court polling, storage, OCR) so it
can both **enforce plan limits** and **measure gross margin per tenant**.

### 4.1 Credits

- Each plan grants `ai_credits_monthly` credits that **reset every billing cycle and
  do not roll over**.
- AI credit packs (`addon_ai_*`) add **top-up** credits that **expire 12 months**
  after purchase.
- Consumption order: **included monthly credits first, then top-up credits.**
- Every grant/debit/expiry is a row in `billing_credit_ledger` with a running
  `balance_after` and an `expires_at`, bucketed by `credit_bucket` (e.g. `ai_credits`).

### 4.2 Usage events

`record_usage(session, company, usage_type, quantity, unit, estimated_cost_minor, …)`
writes a `billing_usage_event` for each metered action. Where it's useful, a
`billing_usage_attribution` row links the usage to the **actor, matter, tracked case,
and feature** so the tenant can see *who* and *what* spent the credits. Usage types
include `ai_request`, `ai_tokens`, `tracked_case_refresh`, `storage_bytes`,
`document_processing`, `embedding`, and `manual_research`.

The tenant-facing usage report (`GET /api/billing/usage`) breaks consumption down
`by_feature`, `by_user`, `by_matter`, `by_tracked_case`, and `daily`.

### 4.3 Internal cost benchmarks (for margin, not billing)

Configured in settings and used to estimate variable cost per tenant:

| Setting | Default | Meaning |
|---|--:|---|
| `billing_case_refresh_cost_minor` | 2 | ₹0.02 per court-poll refresh |
| `billing_llm_cost_minor_per_credit` | 100 | ₹1.00 estimated cost per AI credit |
| `billing_payment_gateway_fee_bps` | 200 | 2% MDR assumption for gateway cost |
| `billing_company_gstin` | `09AANCM5923C1ZD` | CaseOps' own GSTIN on invoices |

These feed `billing_profit_rollups` — period-level revenue vs. variable cost
(gateway, LLM, embedding, refresh, doc-processing, storage, manual support/research)
yielding `gross_profit_minor` and `gross_margin_bps` per tenant. This is **operator
analytics only** and never exposed cross-tenant.

### 4.4 Quota enforcement (fail-closed)

Before a metered or limited action, the relevant guard runs and raises `HTTPException`
(403) if the plan would be exceeded:

| Guard | Blocks when… |
|---|---|
| `assert_user_limit(role)` | adding an internal user / viewer beyond the plan |
| `assert_matter_limit()` | activating a matter beyond `matters_active_limit` |
| `assert_tracked_case_limit()` | tracking a case beyond `tracked_cases_limit` |
| `assert_manual_refresh_limit()` | exceeding `manual_case_refreshes_daily` |
| `effective_storage_quota()` | resolving the storage cap for upload checks |

---

## 5. The subscription lifecycle

```
   demo/enrollment ──► trial (14d) ──► checkout ──► active ──► (cancel_at_period_end)
        │                  │              │            │              │
   sales lead         no card        Pine Labs     paid plan     ends at period end
   (billing_          required       payment       + add-ons      → can reactivate
    enrollments)                     link
```

1. **Enrollment / demo** — `POST /api/billing/demos` (sales lead) or a trial signup
   creates a `billing_enrollment` and, for trials, a Company + owner User +
   `billing_account` + `billing_subscription` (status `trialing`).
2. **Checkout** — `POST /api/billing/checkout` creates a `billing_checkout_session`
   for one of: `new_subscription`, `renewal`, `upgrade`, `topup`, `addon`. If a real
   provider is configured it returns a Pine Labs `provider_checkout_url`; otherwise it
   falls back to a stub (see §6.4).
3. **Activation** — on a successful payment webhook (or a `sync` poll), the
   `billing_payment_order` is marked paid and the `billing_subscription` transitions
   to `active`, setting `current_period_start/end` and granting the cycle's credits.
4. **Cancel / reactivate** — `POST /api/billing/subscription/cancel` sets
   `cancel_at_period_end = true` (service continues until period end);
   `…/reactivate` reverses it before the period closes.
5. **Grace** — `grace_until` lets a lapsed subscription keep working briefly after a
   failed renewal before features suspend.

Existing tenants at migration time were **grandfathered** onto a non-billable
`grandfathered_free` subscription (`source = 'migration'`, not `externally_billable`)
so nobody was locked out when billing shipped.

---

## 6. Payment flow — Pine Labs Plural

### 6.1 Configuration

Pine Labs runs in one of three modes via `pine_labs_env`: **`disabled`** (default —
no real charges), **`uat`**, or **`prod`**. Real provider calls require client
credentials and the endpoint paths in settings (`pine_labs_client_id/secret`,
`pine_labs_merchant_id`, `pine_labs_api_base_url`, the `*_path` settings, and
`pine_labs_webhook_secret`). `GET /api/payments/config` reports
`pine_labs_configured` so the UI can gate payment actions.

Guard rails in settings: `pine_labs_provider_limit_max_amount_minor` (₹10,00,000 cap
per link), `pine_labs_allowed_payment_methods` (`upi`, `card`, `netbanking`), and
per-method MDR assumptions.

### 6.2 Creating a payment link

`PineLabsGatewayClient.create_payment_link(...)`:

1. Fetch a bearer token via OAuth **client_credentials** (cached in-memory, refreshed
   ~60s before expiry).
2. `POST` to the payment-link path with `Authorization: Bearer …`, a `Request-ID`
   (UUID) and `Request-Timestamp`, and a body containing the amount (`{value, currency:
   INR}`), `merchant_payment_link_reference` (our idempotency key), allowed methods,
   `callback_url`, `expire_by`, and customer contact.
3. Returns `provider_order_id` + hosted `payment_url`; the user is redirected there.

### 6.3 Webhooks (the authoritative signal)

Provider events land at the webhook inbox and are **signature-verified before trust**:

- Headers: `webhook-id`, `webhook-timestamp`, `webhook-signature`.
- Signed content = `"{webhook-id}.{webhook-timestamp}."` + raw body, HMAC-SHA256,
  base64. Verified by `verify_pine_labs_plural_signature(...)`.
- Timestamp must be within `pine_labs_webhook_tolerance_seconds` (default **300s**) to
  block replays.
- Each event is stored idempotently in `billing_provider_events`, unique on
  `(provider, provider_event_id)`, with `processing_status` draft → processing →
  success/error and retry/backoff.
- `_normalize_status()` maps Pine Labs' many status strings onto CaseOps enums:
  `created`, `pending`, `partially_paid`, `paid`, `failed`, `cancelled`, `expired`,
  `refunded`, `unknown`.
- `redact_provider_payload()` masks card/CVV/UPI/PAN/secrets before anything is logged.

When polling is needed instead of waiting on a webhook, `sync_checkout()` /
`get_payment_link_status()` reconcile against the provider on demand.

### 6.4 Provider-disabled fallback

With `pine_labs_env = disabled`, checkout still works end-to-end against a stub so the
product is demoable and testable without live credentials — no real money moves and no
external call is made. **Do not read a green checkout in this mode as proof the live
Pine Labs path works** (per the repo's release-sign-off rules, provider-dependent flows
need a real verification path; `tests/e2e/billing-payment.spec.ts` is gated on real
credentials for that reason).

---

## 7. Multi-tenancy & isolation

- **Every** billing row is scoped to `company_id` with `ondelete=CASCADE`.
- One **active** subscription per company (enforced by a partial unique index on
  status); one `billing_account` per company.
- Tenant admins (owner/admin) see only their own plan, usage, invoices, and account.
- Tenant members see only usage they personally contributed (gated by
  `billing_usage_attribution.tenant_visible`).
- **Platform admins see aggregates only** — MRR/ARR, cost, usage counts, enrollments —
  never another tenant's matter content. Any content-level support access is an
  explicit, audited override, not a default.

---

## 8. Platform-admin console (operator side)

A separate `platform_admin_memberships` model (role `super_admin` etc.) gates the
operator console. Capabilities are explicit: `platform:admin`, `platform:billing_view`,
`platform:billing_manage`, `platform:payment_reconcile`, `platform:plan_manage`,
`platform:usage_view`, `platform:manual_override`. Every admin action writes a
`platform_admin_audit_event`.

Key operator endpoints (`/api/admin/*`):

| Endpoint | Purpose |
|---|---|
| `GET /overview` | MRR, ARR, active subs, trials, failed payments, revenue, cost, gross profit, margin alerts |
| `GET /enrollments` | Trials + demo leads with status, plan, source, UTM |
| `POST /subscriptions/{company}/mutate` | Change plan / interval / status manually |
| `POST /subscriptions/{company}/credits/grant` | Grant top-up credits (reason + audit) |
| `POST /manual-invoices` + `…/mark-paid` | Off-system (PO/TDS) invoicing for enterprise deals |
| `POST /coupons` | Discount codes (percent/fixed; once / first_period / repeating / forever) |
| `POST /overage-policies` | Per-tenant overage pricing + caps |
| `GET /usage`, `/profit`, `/profit/export`, `/revenue/export` | Cross-tenant analytics + CSV |

Discounts (`billing_coupons` / `billing_coupon_redemptions`) and per-tenant overage
policies (`billing_overage_policies`) let sales close non-standard deals without
forking the catalog.

---

## 9. Data model map

```
companies
   └─ billing_accounts (1:1)            billing contact, GSTIN, tax_treatment
   └─ billing_subscriptions (1 active)  plan_version, status, period, provider refs,
        │                               entitlement_overrides_json
        ├─ billing_subscription_items   add-ons (extra users / cases / API / packs)
        ├─ billing_checkout_sessions ── billing_payment_orders   the money path
        ├─ billing_credit_ledger        AI/credit grants, debits, expiries
        ├─ billing_usage_events ─ billing_usage_attribution   who/what consumed
        ├─ billing_usage_rollups        period usage summaries
        └─ billing_profit_rollups       revenue vs variable cost, gross margin

catalog (global, versioned 2026.05.v1):
   billing_plan_versions ─ billing_plan_prices
                         └ billing_plan_entitlements

provider + sales + finance:
   billing_provider_events   webhook inbox (idempotent, signed)
   billing_enrollments       trials + demo leads
   billing_admin_notes       support notes
   billing_coupons / billing_coupon_redemptions
   billing_overage_policies
   billing_manual_invoices   off-system PO/TDS invoicing
   platform_admin_memberships / platform_admin_audit_events
```

Tenant-facing API surface (`/api/billing/*`): `plans`, `current`, `checkout`
(+`/{id}` + `/{id}/sync`), `invoices` (+ `pdf`/`json`), `statement` (`pdf`/`csv`),
`spend/csv`, `payments/csv`, `credits`, `usage`, `subscription/cancel`,
`subscription/reactivate`, `trials`, `demos`.

---

## 10. Matter invoicing (the *other* billing system)

Separate from SaaS billing: a firm invoices **its own clients** for work on a matter.

- `matter_time_entries` → roll into `matter_invoices` → `matter_invoice_line_items`.
- An invoice can generate a Pine Labs payment link via
  `POST /api/matters/{matter_id}/invoices/{invoice_id}/pine-labs/link`; status syncs
  via the `…/sync` route or webhooks at `POST /api/payments/webhooks/pine-labs`.
- Attempts are tracked in `matter_invoice_payment_attempts`; legacy webhook events in
  `payment_webhook_events`.
- UI: `apps/web/app/app/matters/[id]/billing/page.tsx`.

It shares the Pine Labs rail and signature verification but is a completely independent
data model from the SaaS `billing_*` tables. Revenue here belongs to the **firm**, not
to CaseOps.

---

## 11. Quick FAQ

- **What currency / units?** INR only; everything stored in paisa (minor units).
- **Is GST included?** Solo plans: yes (tax-inclusive). Firm, GC, add-ons: no — 18%
  GST added at checkout (`tax_rate_bps = 1800`).
- **Do unused AI credits roll over?** Monthly plan credits — no. Purchased packs —
  they last 12 months.
- **What happens when I hit a limit?** The action is blocked (HTTP 403) by the
  matching `assert_*` guard. Buy an add-on or upgrade.
- **Who can charge a card?** Only the Pine Labs Plural rail, only when
  `pine_labs_env` is `uat`/`prod` and credentials are present; otherwise checkout runs
  against a no-charge stub.
- **Can sales do custom deals?** Yes — `entitlement_overrides_json`, coupons, overage
  policies, and manual invoices, all audited.

---

*Keep this file in sync with `20260531_0001_pricing_billing_plural_platform_admin.py`
and `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md`. When the catalog
version bumps past `2026.05.v1`, re-derive §2 from the new seed.*
