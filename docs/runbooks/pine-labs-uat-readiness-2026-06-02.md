# Pine Labs UAT Readiness Checklist - 2026-06-02

**Scope:** Prepare CaseOps for Pine Labs Plural UAT for SaaS billing and legacy
matter-invoice payment links.

**Hard rules:**

- Do not enable Pine Labs production payments during UAT.
- Do not make real production Pine Labs calls.
- Do not write credential values, webhook secrets, access tokens, dashboard
  passwords, raw signed payloads, or customer payment instruments into this repo.
- Store secrets only in the approved secret manager/environment mechanism.

## Current Implementation Fit

CaseOps currently supports:

- SaaS checkout creation through `POST /api/billing/checkout`.
- SaaS add-on checkout through `POST /api/billing/add-ons/checkout`.
- Checkout status sync through `POST /api/billing/checkout/{session_id}/sync`.
- Pine Labs webhook ingestion through `POST /api/payments/pine-labs/webhook`.
- Tenant payment config probe through `GET /api/payments/config`.
- Legacy matter invoice payment links through
  `POST /api/payments/matters/{matter_id}/invoices/{invoice_id}/pine-labs/link`.
- Legacy matter invoice sync through
  `POST /api/payments/matters/{matter_id}/invoices/{invoice_id}/pine-labs/sync`.

CaseOps does not yet have production signoff for Plural subscriptions or UPI
AutoPay. Treat subscription/mandate UAT as provider-readiness validation before
enabling any live recurring payment feature.

## Founder/Operator Information Request

Ask Pine Labs or the payment onboarding operator for these items before UAT can
begin:

- UAT API base URL.
- Merchant id.
- Client id and client secret.
- Webhook signing secret and header names.
- Webhook registration URL.
- Enabled products: hosted checkout, payment links, subscriptions, UPI AutoPay,
  refunds, and settlements.
- Exact endpoint paths and request/response schemas.
- Event names and sample payloads for success, failure, pending, cancel,
  refund, timeout, and subscription/mandate lifecycle.
- UAT test instruments for card, UPI, netbanking, pending, failed, refund, and
  timeout scenarios.
- MDR by method, fixed fee, GST on MDR, settlement cycle, transaction limits,
  chargeback handling, and split-payment guidance.

## UAT Credentials Needed

Request these from Pine Labs/Plural onboarding.

| Item | Required | Notes |
|---|---|---|
| UAT API base URL | Yes | No production URL for UAT |
| UAT merchant id | Yes | Must map to CaseOps legal entity/GSTIN |
| UAT client id | Yes | Store as secret/env only |
| UAT client secret | Yes | Store as secret/env only |
| UAT webhook signing secret | Yes | Confirm raw vs base64-encoded material |
| UAT dashboard access | Yes | Role-limited operations access |
| UAT test cards | Yes | Success, failure, pending, timeout |
| UAT test UPI ids | Yes | Success, failure, pending, AutoPay if enabled |
| UAT netbanking fixtures | Yes | Success/failure banks |
| UAT refund fixtures | If refunds enabled | Do not expose public refund policy from this alone |
| Settlement report/API sample | Yes | Needed for reconciliation readiness |

Never put actual values in this file.

## CaseOps UAT Configuration Variables

Configure these in the UAT environment only.

```text
CASEOPS_PINE_LABS_ENV=uat
CASEOPS_PINE_LABS_API_BASE_URL=<uat base url>
CASEOPS_PINE_LABS_CLIENT_ID=<secret reference>
CASEOPS_PINE_LABS_CLIENT_SECRET=<secret reference>
CASEOPS_PINE_LABS_MERCHANT_ID=<uat merchant id>
CASEOPS_PINE_LABS_WEBHOOK_SECRET=<secret reference>
CASEOPS_PINE_LABS_WEBHOOK_SIGNATURE_HEADER=webhook-signature
CASEOPS_PINE_LABS_WEBHOOK_ID_HEADER=webhook-id
CASEOPS_PINE_LABS_WEBHOOK_TIMESTAMP_HEADER=webhook-timestamp
CASEOPS_PINE_LABS_PAYMENT_LINK_PATH=<confirmed path>
CASEOPS_PINE_LABS_PAYMENT_STATUS_PATH=<confirmed path>
CASEOPS_PINE_LABS_PAYMENT_ORDER_PATH=<confirmed path or blank if unused>
CASEOPS_PINE_LABS_SUBSCRIPTION_PLAN_PATH=<confirmed path>
CASEOPS_PINE_LABS_SUBSCRIPTION_PATH=<confirmed path>
CASEOPS_PINE_LABS_SUBSCRIPTION_STATUS_PATH=<confirmed path>
CASEOPS_PINE_LABS_REFUND_PATH=<confirmed path>
CASEOPS_PINE_LABS_SETTLEMENT_PATH=<confirmed path>
CASEOPS_PINE_LABS_SUBSCRIPTIONS_ENABLED=false
CASEOPS_PINE_LABS_PAYMENT_LINKS_ENABLED=true
CASEOPS_PINE_LABS_PROVIDER_LIMIT_MAX_AMOUNT_MINOR=<confirmed paisa limit>
CASEOPS_PINE_LABS_ALLOWED_PAYMENT_METHODS=CARD,UPI,NETBANKING
CASEOPS_PINE_LABS_MDR_BPS_UPI=<confirmed>
CASEOPS_PINE_LABS_MDR_BPS_CARD=<confirmed>
CASEOPS_PINE_LABS_MDR_BPS_NETBANKING=<confirmed>
CASEOPS_PINE_LABS_FIXED_FEE_MINOR=<confirmed>
```

Set `CASEOPS_PINE_LABS_SUBSCRIPTIONS_ENABLED=true` only after subscription and
UPI AutoPay UAT gates pass.

## Webhook Registration

Register only the UAT public URL:

```text
https://<uat-api-host>/api/payments/pine-labs/webhook
```

Confirm with Pine Labs:

- One endpoint can receive payment, refund, token/customer, and subscription
  events, or list the separate endpoints they require.
- Required headers are exactly `webhook-id`, `webhook-timestamp`, and
  `webhook-signature`.
- Whether `webhook-signature` has a version prefix such as `v1,`.
- Signature algorithm is HMAC-SHA256 over
  `{webhook-id}.{webhook-timestamp}.<raw body>`.
- Timestamp is Unix seconds.
- Recommended timestamp tolerance.
- Retry schedule, maximum retries, and 2xx acknowledgement requirement.
- Whether events are unordered. CaseOps assumes unordered delivery.

## Products To Enable For UAT

| Product | Needed for | Pine Labs confirmation |
|---|---|---|
| Hosted Checkout / Payments | One-time SaaS checkout if Pine recommends checkout flow | Pending |
| Payment Links / Pay by Link | Current CaseOps SaaS checkout and matter invoice links | Pending |
| Subscriptions | Recurring monthly/annual SaaS billing | Pending |
| UPI AutoPay / mandates | Recurring authorization and debit | Pending |
| Refunds/payment adjustments | Back-office reconciliation | Pending |
| Settlement reports/API | Finance reconciliation | Pending |

## Endpoint Paths To Confirm

Ask Pine Labs for exact paths and request/response schemas:

- OAuth token path. Current CaseOps client assumes `/api/auth/v1/token`.
- Create order/payment.
- Fetch order/payment status.
- Create payment link.
- Fetch payment link status.
- Cancel/expire payment link, if supported.
- Create subscription plan.
- Update subscription plan, if supported.
- Create subscription.
- Create payment/authorization for subscription.
- Fetch subscription status.
- Pause subscription.
- Resume subscription.
- Cancel subscription.
- Update subscription amount/plan, if supported.
- Refund/create adjustment.
- Fetch refund status.
- Settlement report/API.

## Webhook Events To Enable

Request the full enabled-event list and sample payloads for each.

Payment/order events:

- `ORDER_AUTHORIZED`
- `ORDER_PROCESSED`
- `ORDER_CANCELLED`
- `ORDER_FAILED`
- `PAYMENT_FAILED`

Refund events:

- `REFUND_PROCESSED`
- `REFUND_FAILED`

Subscription/mandate events:

- `SUBSCRIPTION_ACTIVATED`
- `SUBSCRIPTION_PENDING`
- `SUBSCRIPTION_PAUSED`
- `SUBSCRIPTION_RESUMED`
- `SUBSCRIPTION_COMPLETED`
- `SUBSCRIPTION_CHARGED`
- `SUBSCRIPTION_HALTED`
- `SUBSCRIPTION_CANCELLED`
- `SUBSCRIPTION_REVOKE_FAILED`
- `SUBSCRIPTION_UPDATED`
- `SUBSCRIPTION_UPDATE_FAILED`

For every event, confirm which id CaseOps should use for business idempotency:

- Provider event id
- Webhook id
- Order/payment id
- Merchant payment link reference
- Subscription id
- Merchant subscription reference

## Sample Payloads To Request

Use fake IDs in this repo. Store real UAT samples externally if they contain
customer, card, UPI, token, or signature data.

### Payment Success

```json
{
  "event_id": "evt_uat_payment_success_001",
  "event_type": "ORDER_PROCESSED",
  "data": {
    "payment_link_id": "plink_uat_001",
    "merchant_payment_link_reference": "co-smoke-solo-core-uat",
    "payment_status": "paid",
    "amount": 99900,
    "amount_received_minor": 99900,
    "currency": "INR"
  }
}
```

### Payment Failure

```json
{
  "event_id": "evt_uat_payment_failed_001",
  "event_type": "PAYMENT_FAILED",
  "data": {
    "payment_link_id": "plink_uat_002",
    "merchant_payment_link_reference": "co-smoke-failure-uat",
    "payment_status": "failed",
    "amount": 99900,
    "currency": "INR",
    "failure_code": "UAT_DECLINED"
  }
}
```

### Refund Processed

```json
{
  "event_id": "evt_uat_refund_processed_001",
  "event_type": "REFUND_PROCESSED",
  "data": {
    "payment_link_id": "plink_uat_003",
    "refund_id": "refund_uat_001",
    "payment_status": "refunded",
    "amount": 99900,
    "currency": "INR"
  }
}
```

### Subscription Charged

```json
{
  "event_id": "evt_uat_subscription_charged_001",
  "event_type": "SUBSCRIPTION_CHARGED",
  "data": {
    "subscription_id": "sub_uat_001",
    "payment_id": "pay_uat_001",
    "merchant_subscription_reference": "caseops-sub-smoke-001",
    "status": "paid",
    "amount": 199900,
    "currency": "INR"
  }
}
```

## MDR, Fees, Settlement, And Reconciliation

Obtain written confirmation for:

- MDR by UPI, debit card, credit card, netbanking, wallet, and international
  card if enabled.
- Fixed fee per transaction, if any.
- GST on payment gateway charges.
- Refund/adjustment fee.
- Chargeback/dispute process and webhook/report support.
- Failed payment fee, if any.
- Mandate setup fee.
- Subscription debit fee, if different from normal payment MDR.
- Settlement cycle.
- Settlement report format.
- Settlement API path and auth.
- Settlement fields needed to match CaseOps `billing_payment_orders`.
- Whether convenience fees/MDR can be passed through or must be absorbed.

Update CaseOps cost settings only from confirmed values:

- `CASEOPS_PINE_LABS_MDR_BPS_UPI`
- `CASEOPS_PINE_LABS_MDR_BPS_CARD`
- `CASEOPS_PINE_LABS_MDR_BPS_NETBANKING`
- `CASEOPS_PINE_LABS_FIXED_FEE_MINOR`
- `CASEOPS_BILLING_PAYMENT_GATEWAY_FEE_BPS`

## UAT Payment Scenarios

Run these on a UAT smoke tenant only.

| Scenario | Expected CaseOps result |
|---|---|
| SaaS plan payment link success | Checkout becomes paid; subscription becomes active; credits granted once |
| SaaS plan payment failure | Checkout/order fail; subscription remains unchanged |
| SaaS plan pending then paid webhook | Pending first, paid after verified webhook or sync |
| Duplicate paid webhook | No duplicate credits/items/profit rows |
| Out-of-order failed after paid | Paid order remains paid; event marked ignored/out-of-order |
| Add-on AI credit success | Top-up credits granted once with expiry |
| Recurring add-on success | Subscription item added once |
| Tenant spend export after usage | Quantities/credits only; no internal cost |
| Manual invoice offline paid | Platform-admin mark-paid records amount/TDS/reference |
| Matter invoice payment link success | Matter invoice collection state updates |
| Invalid webhook signature | 401 before payload trust |
| Missing webhook secret | 503; no event processed |
| Unknown provider order | Event accepted/ignored without subscription mutation |
| Amount above provider max | CaseOps rejects checkout before provider call |
| Callback/redirect without webhook | UI remains provisional until backend sync verifies |
| Settlement report match | Settlement row maps to CaseOps payment order |
| Refund event | Operational record captured; no silent subscription downgrade |

## Go/No-Go Gates Before Enabling Production Payments

Do not switch production to `uat` or `prod` payment behavior until all gates pass.

| Gate | Required result |
|---|---|
| UAT credentials | Stored only in secret manager/environment; no repo leakage |
| Product enablement | Hosted checkout/payment links/subscriptions/UPI AutoPay confirmed as applicable |
| Endpoint paths | All used paths confirmed against Pine Labs docs/support |
| Webhook registration | UAT webhook URL registered and receiving signed events |
| Signature verification | Valid signatures pass; bad/missing signatures fail |
| Payment success/failure | CaseOps state transitions correct |
| Idempotency | Duplicate webhooks do not duplicate credits/items/revenue |
| Out-of-order safety | Terminal paid state is not downgraded by late failure/cancel |
| Tenant leakage | Tenant reports/downloads have no cost/profit/margin fields |
| Settlement | Payment order can be reconciled to settlement report |
| MDR/cost config | Confirmed values configured in UAT and reviewed |
| Provider limits | Min/max amounts confirmed and enforced |
| Subscription/UPI AutoPay | Mandate lifecycle tested before recurring payments are enabled |
| Monitoring | Logs/alerts for webhook errors, failed payments, and provider outages exist |
| Rollback | Production can return to `CASEOPS_PINE_LABS_ENV=disabled` quickly |
| Founder approval | Founder signs off UAT evidence and accepts caveats |

## Remaining Production Blockers

Pine Labs live activation remains blocked until every item below is complete
with founder-approved evidence. Do not enable production payments as part of
billing signoff or connector/cost work.

- Pine Labs UAT credentials and webhook secret must be obtained.
- UAT webhook URL must be registered and verified.
- Payment-link status path and payload schema must be confirmed.
- Enabled products must be confirmed in writing, especially subscriptions and
  UPI AutoPay.
- MDR, settlement, fee, refund, and chargeback details must be confirmed.
- UAT payment scenarios must pass with evidence.
- Founder must explicitly approve production enablement after UAT.
