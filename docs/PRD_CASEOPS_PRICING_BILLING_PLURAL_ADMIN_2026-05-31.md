# PRD: CaseOps Pricing, Subscription Billing, Pine Labs Plural Payments, Usage Governance, And Admin Console

Date: 2026-05-31
Status: Implementation shipped for pricing/billing/platform-admin; production
billing signoff and Pine Labs UAT remain pending as of 2026-06-02
Owner: CaseOps product/admin
Primary users: Solo lawyers, Indian law firms, corporate General Counsel teams, CaseOps platform operators
Related PRD: `docs/PRD_CASEOPS_AI_ENHANCEMENTS_2026-05-26.md`

## 0. Current Production Status - 2026-06-02

- Pricing page, SaaS billing APIs, tenant billing UI, tenant usage/downloads,
  and founder-only platform-admin billing/profit/provider-event surfaces have
  been deployed.
- Production Pine Labs payments remain disabled. Provider-disabled checkout is
  the expected production behavior until UAT and founder go/no-go pass.
- Manual production billing signoff is still pending. Use
  `docs/runbooks/production-billing-signoff-2026-06-02.md`.
- Pine Labs UAT is still pending credentials, webhook registration, product
  enablement, endpoint schemas, MDR/settlement details, and UAT payment
  scenarios. Use `docs/runbooks/pine-labs-uat-readiness-2026-06-02.md`.
- This PRD remains the product/implementation reference, but its rollout status
  is no longer "not implemented."

## 1. Purpose

CaseOps now has AI recommendations, legal update ingestion, judgment/case tracking, matter workflows, document storage, AI token governance, invoice/payment-link foundations, and tenant admin tooling. The next product requirement is to turn these capabilities into a monetizable, usage-safe SaaS business for India.

This PRD defines:

1. Pricing plans for solo lawyers, law firms, and corporate General Counsel teams.
2. Usage limits that protect research effort, LLM token costs, court/provider refresh costs, document processing, support, and storage.
3. Pine Labs Plural integration for online payment acceptance, recurring subscriptions, top-ups, payment links, webhooks, and reconciliation.
4. Tenant billing UI for plan purchase, upgrade, usage visibility, and invoices.
5. Platform admin console to track enrollments, subscriptions, revenue, usage, costs, payment failures, and manual overrides.
6. Implementation-ready backend, frontend, database, security, audit, and verification requirements.

## 2. Product Outcomes

### 2.1 Business Outcomes

- Convert CaseOps from feature-rich product to paid subscription SaaS.
- Support low-friction self-serve purchase for solo lawyers and small law firms.
- Support assisted annual procurement for corporate GC teams.
- Keep gross margin protected through explicit AI credits, tracked-case limits, storage limits, and provider-cost monitoring.
- Give CaseOps operators visibility into enrollments, revenue, active usage, cost leakage, and failed payments.

### 2.2 User Outcomes

- Solo lawyer can start a trial, choose a plan, pay online, and begin using CaseOps without sales intervention.
- Law firm owner/admin can buy a firm plan, invite users, monitor plan usage, and top up credits/case tracking.
- Corporate GC admin can be onboarded through assisted annual subscription, with strong usage visibility and invoice/procurement support.
- Platform operator can see who enrolled, which plan they are on, payment state, usage, margin risk, and support/admin interventions.

## 3. Current Repo Alignment

The implementation must reuse existing CaseOps patterns where possible.

| Area | Current Repo Signal | PRD Implication |
|---|---|---|
| Invoice billing | `apps/api/src/caseops_api/schemas/billing.py`, `services/payments.py`, matter billing UI | Reuse for payment attempts and provider event patterns, but add SaaS subscription billing separate from matter invoices. |
| Pine Labs | `services/pine_labs.py`, `routes/payments.py`, `PaymentWebhookEvent`, settings | Extend provider client for Plural orders/subscriptions/top-ups and webhook verification instead of creating an unrelated adapter. |
| Webhook inbox | `payment_webhook_events` with provider event idempotency | Expand event normalization for subscription and checkout events. Keep raw payload redaction. |
| AI usage | `ModelRun`, `TenantAIPolicy`, `ai_token_governance.py`, admin UI | Build plan entitlements on top of token governance. Add credit ledger, cost estimates, and plan-driven quota defaults. |
| Embedding usage | `VoyageUsage` and daily cap logic | Include in cost dashboard and tenant margin computation. |
| Storage usage | `storage_governance.py` and admin page | Drive storage quotas from plan entitlements. |
| Tenant admin | `/app/admin`, `routes/admin.py`, capabilities | Add tenant billing and usage widgets under tenant admin. |
| Platform operator console | Not present as a distinct global console | Add platform admin capability and global routes with strict audit and no matter-content exposure by default. |
| Legal update/case tracking | PRD 2026-05-26 implementation | Apply pricing entitlements to tracked cases, refresh frequency, AI summaries, and top-ups. |

## 4. Research Inputs And Market Positioning

### 4.1 India Legal SaaS Price Signals

Observed India-focused pricing signals as of 2026-05-31:

- MyLegal365 advertises Rs 499/month or Rs 4,999/year, taxes inclusive, for practice management plus AI legal research.
- Nowlez advertises Rs 1,000/month, Rs 2,000/month, and Rs 4,000/month tiers with AI chat, uploads, drafts, and case refresh limits.
- LegalDesk AI advertises a free trial and paid plans starting around Rs 499/month with AI usage and storage caps.
- SCC Online AI Pro is Rs 51,500/user/year plus 18 percent GST; AI Pro Plus is Rs 67,500/user/year plus GST.
- Manupatra annual plans are publicly shown from Rs 14,250 to Rs 55,460 plus tax, with AI summary add-ons.

Interpretation:

- Solo lawyers are price-sensitive, with visible anchor prices from Rs 499 to Rs 4,999/month.
- Professional legal research budgets support far higher annual pricing when trust, citations, coverage, and workflow value are clear.
- CaseOps should not compete as only a cheap AI chat tool. It should price as a matter operating system with court tracking, legal updates, AI recommendations, usage governance, and admin controls.

### 4.2 Payment Provider Inputs

Pine Labs Plural documentation currently indicates:

- Payment APIs use backend-generated bearer tokens through `client_credentials`.
- API calls must not be made from frontend code; client id and secret stay in the backend.
- Hosted payment responses return a checkout/challenge URL that the user can be redirected to.
- Webhook signature verification is mandatory and uses `webhook-id`, `webhook-timestamp`, `webhook-signature`, the raw body, and a secret key.
- Webhooks are asynchronous, can arrive out of order, and should be acknowledged with 2xx within 5 seconds.
- Plural subscription supports recurring billing, UPI AutoPay-style customer authorization, fixed frequency plans, pre-debit notifications, auto-debit, retries, and subscription lifecycle events.
- Pine Labs examples show amounts in paisa and a documented transaction amount max of Rs 10 lakh for relevant amount objects. Implementation must validate current provider limits before launch.

Sources are listed in Section 26.

### 4.3 Confirmed Business Inputs

These inputs were confirmed by the company owner on 2026-05-31 and should be treated as product defaults unless superseded in writing.

- Company GSTIN: `09AANCM5923C1ZD`.
- Refund policy: do not publish or advertise a standalone refund policy in the product until finance/legal supplies approved copy. Internal payment adjustment/refund workflows may exist for operations.
- TDS: enterprise/manual payment handling must support TDS according to applicable Indian law and accountant-approved configuration. Do not hardcode legal advice or fixed TDS rates in application logic.
- Court/case refresh cost: exact provider cost is unknown. Use the advisory model in Section 10.4 until real provider pricing/invoices are available.
- MFA: not mandatory at launch, but the design must allow later enforcement for platform admins and already-existing users.

## 5. Product Principles

1. No unlimited AI in paid plans.
2. No unlimited case refreshes unless covered by enterprise contract and internal provider-cost approval.
3. Shared legal update summaries must be generated once globally and delivered to many tenants.
4. Judgment/order summaries must be generated once per detected update and reused for all users who bookmarked the same case/update.
5. Expensive models require explicit premium-credit multipliers or admin approval.
6. Payment confirmation must rely on backend verification and webhook reconciliation, not only frontend redirect success.
7. Every billing, entitlement, usage, override, refund, and provider event must be auditable.
8. Tenant admins can see their own billing and usage; only CaseOps platform admins can see cross-tenant enrollments and revenue.
9. Platform admin console must not expose matter content by default. It should show metadata and usage aggregates unless an explicitly audited support override is implemented later.
10. Pricing and entitlement logic must be data-driven, not hardcoded in many UI/backend branches.

## 6. Target Segments

### 6.1 Solo Lawyers

Profile:

- 1 lawyer, optionally 1-5 clerks/juniors/staff.
- Needs hearing tracking, case organization, AI summaries, legal updates, recommendations, and client-facing confidence.
- Price sensitivity is high.
- Self-serve monthly and annual purchase should be available.

Buying motion:

- Public pricing page -> free trial -> online payment -> active plan.

### 6.2 Law Firms

Profile:

- 2-50 lawyers, plus clerks, associates, paralegals, and admins.
- Needs team access, matter controls, usage governance, legal update watchlists, tracked-case monitoring, AI assistance, documents, and reporting.
- Can pay monthly or annually; annual should be encouraged.

Buying motion:

- Self-serve for starter/growth tiers.
- Assisted onboarding for larger firms.

### 6.3 Corporate General Counsel Teams

Profile:

- In-house legal team, business viewers, external counsel coordination, high matter volume, litigation monitoring, legal update awareness, audit needs, reports.
- Annual procurement, GST invoices, vendor onboarding, security review, and possibly purchase order based payment.

Buying motion:

- Sales-assisted annual plan.
- Online payment possible for smaller GC Starter plans, but enterprise should support manual invoice/PO/offline payment marking.

## 7. Pricing Catalog

All plan prices are Version `2026.05.v1`.

Implementation must store prices in minor units, currency `INR`, billing interval, GST display rule, and plan version. Do not scatter price constants through UI components.

### 7.1 Display And Tax Rules

Recommended launch display:

| Segment | Display Rule | Reason |
|---|---|---|
| Solo | Display GST-inclusive prices | Reduces friction and aligns consumer-like advocate purchases. |
| Law firm | Display base price + GST | Business buyers expect tax invoices and input credit. |
| Corporate GC | Display annual base price + GST | Procurement expects formal quote and tax separation. |

Implementation must support both inclusive and exclusive GST calculation because the final accountant-approved rule may differ.

Default GST rate: 18 percent. Store `tax_rate_bps = 1800`.

### 7.2 Free Trial

| Attribute | Requirement |
|---|---|
| Duration | 14 days by default. |
| Card requirement | No card required for launch. |
| Tenant limit | One active trial per verified email domain/mobile/GSTIN combination where possible. |
| Included users | 1 lawyer + 1 staff. |
| Matters | 10. |
| Tracked cases | 10. |
| AI credits | 25 total trial credits. |
| Storage | 500 MB. |
| Legal updates | Read-only latest updates enabled. |
| Payment transition | Trial converts only after verified payment or manual platform admin activation. |
| Expiry behavior | Read-only access for 30 days, then suspend interactive features until plan selected. |

### 7.3 Solo Plans

| Plan Code | Public Name | Price | Annual | Users | Matters | Tracked Cases | AI Credits/Month | Storage | Refresh | Support |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `solo_core` | Solo Core | Rs 999/mo | Rs 9,990/yr | 1 lawyer + 1 staff | 50 | 50 | 100 | 2 GB | Weekday daily | Email |
| `solo_pro` | Solo Pro | Rs 1,999/mo | Rs 19,990/yr | 1 lawyer + 3 staff | 250 | 200 | 300 | 10 GB | Daily | Priority email |
| `solo_elite` | Solo Elite | Rs 3,999/mo | Rs 39,990/yr | 1 lawyer + 5 staff | 1,000 | 750 | 800 | 50 GB | Daily + priority queue | Priority email + callback |

Positioning:

- Hero solo plan: `solo_pro`.
- `solo_core` is the low-friction entry.
- `solo_elite` is for high-volume solo litigators/AOR-style practice.

### 7.4 Law Firm Plans

Prices are exclusive of GST by default.

| Plan Code | Public Name | Price | Annual | Users | Matters | Tracked Cases | AI Credits/Month | Storage | Refresh | Support |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `firm_starter` | Firm Starter | Rs 5,999/mo | Rs 62,990/yr | 5 | 300 | 250 | 300 | 25 GB | Smart court-working-day refresh | Email |
| `firm_growth` | Firm Growth | Rs 19,999/mo | Rs 2,09,990/yr | 15 | 1,500 | 1,000 | 1,200 | 150 GB | Smart daily refresh | Priority support |
| `firm_pro` | Firm Pro | Rs 49,999/mo | Rs 5,24,990/yr | 50 | 5,000 | 2,500 | 3,000 | 500 GB | Priority smart daily refresh | Priority + quarterly review |
| `firm_enterprise` | Firm Enterprise | Custom | Custom | Custom | Custom | Custom | Custom | Custom | SLA | Dedicated CSM |

Positioning:

- Hero firm plan: `firm_growth`.
- `firm_pro` should include API access, SSO readiness, detailed audit exports, and advanced analytics.
- `firm_enterprise` requires margin review and signed order form.
- Annual firm pricing intentionally gives about 1.5 months free, not 2 months free, because law-firm plans include material AI and case-refresh cost.
- Discounts beyond the published annual price require platform-admin margin simulation and approval.

### 7.4.1 Law Firm Profitability Lock

The law-firm plans above replace the earlier generous draft limits. They are deliberately conservative because law firms can create the most cost risk: many users, many matters, frequent court tracking, and heavy AI usage.

Law-firm launch rules:

- Do not sell self-serve law-firm plans with unlimited AI credits, unlimited tracked cases, or unlimited daily refresh.
- Treat refresh as smart court-working-day refresh by default.
- Require add-ons for tracking-heavy firms instead of bundling very high tracked-case volumes into base plans.
- Keep Firm Enterprise custom when a prospect needs more than 2,500 included tracked cases, more than 3,000 included monthly AI credits, dedicated SLA, unusual data migration, or negotiated refresh cadence.
- Do not approve a discount or custom entitlement unless the projected base-case contribution margin stays above 70 percent and stress-case contribution margin stays above 55 percent.
- If actual provider case-refresh cost is Rs 0.10 or more per tracked-case refresh equivalent, pause public sale of high-volume fixed-price firm bundles and move large tracking customers to custom quote.

### 7.5 Corporate GC Plans

Prices are annual and exclusive of GST by default.

| Plan Code | Public Name | Price | Users | Viewers | Matters | Tracked Cases | AI Credits/Month | Storage | Included Services |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `gc_monitoring` | Litigation Monitoring Only | Rs 1,50,000/yr | 3 legal | 25 | 500 | 5,000 | 1,000 | 50 GB | Case tracking, alerts, monthly MIS |
| `gc_starter` | GC Starter | Rs 3,00,000/yr | 5 legal | 25 | 1,000 | 5,000 | 10,000 | 250 GB | Matter workflows, updates, MIS |
| `gc_professional` | GC Professional | Rs 8,00,000/yr | 15 legal | 100 | 10,000 | 25,000 | 30,000 | 1 TB | Counsel workflows, analytics, security pack |
| `gc_enterprise` | GC Enterprise | Rs 18,00,000-36,00,000/yr | Custom | Custom | Custom | Custom | Custom | Custom | SSO readiness, API, SLA, CSM, procurement support |

Notes:

- `gc_monitoring` is the acquisition wedge for corporates that mainly want litigation monitoring.
- `gc_professional` is the main target plan for mature GC teams.
- Enterprise annual amounts above provider per-transaction limits may require split payment links, manual invoice, bank transfer, or custom provider handling.

### 7.6 Seed Entitlement Matrix

The first implementation must seed this matrix alongside the plan catalog. If final business pricing changes, Codex should update seed data only, not entitlement code.

| Plan Code | Internal Users | Viewers | Active Matters | Tracked Cases | AI Credits/Mo | Storage | Manual Refreshes/Day | Refresh Cadence | API | Audit Export | SSO readiness |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| `trial` | 2 | 0 | 10 | 10 | 25 total | 500 MB | 2 | weekday_daily | No | No | No |
| `solo_core` | 2 | 0 | 50 | 50 | 100 | 2 GB | 5 | weekday_daily | No | No | No |
| `solo_pro` | 4 | 0 | 250 | 200 | 300 | 10 GB | 10 | daily | No | No | No |
| `solo_elite` | 6 | 0 | 1,000 | 750 | 800 | 50 GB | 25 | priority_daily | No | Basic | No |
| `firm_starter` | 5 | 0 | 300 | 250 | 300 | 25 GB | 10 | smart_weekday_daily | No | Basic | No |
| `firm_growth` | 15 | 10 | 1,500 | 1,000 | 1,200 | 150 GB | 50 | smart_daily | Add-on | Yes | No |
| `firm_pro` | 50 | 50 | 5,000 | 2,500 | 3,000 | 500 GB | 150 | priority_smart_daily | Yes | Yes | Ready |
| `gc_monitoring` | 3 | 25 | 500 | 5,000 | 1,000 | 50 GB | 100 | daily | No | Yes | No |
| `gc_starter` | 5 | 25 | 1,000 | 5,000 | 10,000 | 250 GB | 150 | daily | Add-on | Yes | No |
| `gc_professional` | 15 | 100 | 10,000 | 25,000 | 30,000 | 1 TB | 500 | priority_daily | Yes | Yes | Ready |
| `gc_enterprise` | Custom | Custom | Custom | Custom | Custom | Custom | Custom | SLA/custom | Yes | Yes | Ready; OIDC/SAML/SCIM still planned until IdP UAT |

Seed add-ons must increment these entitlement values through subscription items, not by mutating the base plan version.

## 8. Add-Ons And Top-Ups

### 8.1 Add-On Catalog

| Add-On Code | Name | Price | Included |
|---|---|---:|---|
| `addon_user_firm` | Extra firm user | Rs 699/user/mo | 1 additional internal user. |
| `addon_user_corporate_legal` | Extra corporate legal user | Rs 1,500/user/mo | 1 additional legal/admin user. |
| `addon_viewer` | Extra viewer/business user | Rs 199/user/mo | Read/comment-only viewer where supported. |
| `addon_cases_500` | Tracked case pack 500 | Rs 2,499/mo | 500 additional tracked cases with scheduled smart refresh. |
| `addon_cases_1000` | Tracked case pack 1000 | Rs 4,499/mo | 1,000 additional tracked cases with scheduled smart refresh. |
| `addon_ai_250` | AI credit pack 250 | Rs 1,199 one-time | 250 credits, expires in 12 months. |
| `addon_ai_1000` | AI credit pack 1000 | Rs 3,999 one-time | 1,000 credits, expires in 12 months. |
| `addon_ai_5000` | AI credit pack 5000 | Rs 14,999 one-time | 5,000 credits, expires in 12 months. |
| `addon_storage_100gb` | Extra storage 100 GB | Rs 1,499/mo | 100 GB additional storage. |
| `addon_api_access` | API access | Rs 5,000/mo | API keys, rate limit, usage dashboard. Included in Firm Pro and GC Professional+. |
| `addon_migration_basic` | Basic migration | Rs 10,000 one-time | CSV import and guided setup. |
| `addon_migration_firm` | Firm migration | Rs 25,000 one-time | Matter, client, document import assistance. |
| `addon_migration_enterprise` | Enterprise migration | Rs 75,000-2,00,000 one-time | Custom mapping, QA, and launch support. |
| `addon_research_memo` | Legal research memo | Rs 5,000-25,000 one-time | Human/legal-editor-assisted memo. Not included in self-serve plans. |

### 8.2 Add-On Rules

- Included monthly credits reset every billing cycle and do not roll over.
- Purchased AI credit packs expire 12 months after purchase.
- Top-up credits are consumed after included monthly credits unless admin chooses otherwise.
- Extra tracked case packs are recurring subscription items.
- One-time add-ons must create payment order records but should not create a recurring mandate.
- Manual legal research memos are outside AI credits and require operator approval/fulfillment tracking.

## 9. AI Credit Model

### 9.1 Credit Definition

An AI credit is a product-level unit, not a direct token count. It protects margin while remaining understandable to users.

| Feature | Credit Cost |
|---|---:|
| Basic matter recommendation | 1 |
| Judgment/order summary | 2 |
| Legal strategy/lawyer-thinking analysis | 3 |
| Legal update AI summary | 0 to tenant if generated globally; internal cost tracked centrally |
| Document summary up to 30 pages | 3 |
| Document bundle analysis over 30 pages | 10-25 based on page/token band |
| Premium reasoning model action | 5x multiplier |
| Re-run of unchanged cached summary | 0 or 1 display credit, configurable |

### 9.2 Internal Token Estimate Bands

Use these estimates for pre-call quota checks and cost forecasting. Actual token usage still comes from `ModelRun`.

| Action | Estimated Input | Estimated Output | Default Model Tier |
|---|---:|---:|---|
| Legal update summary | 8k | 1k | mini |
| Matter recommendation | 20k | 2k | mini/standard |
| Judgment/order summary | 30k | 3k | mini/standard |
| Heavy document analysis | 80k | 5k | standard |
| Premium strategy analysis | 80k-150k | 5k-10k | premium only if explicitly selected |

### 9.3 Cost Guardrail

Implementation must maintain a configurable AI cost catalog:

- Provider.
- Model.
- Input price per 1M tokens.
- Cached input price per 1M tokens.
- Output price per 1M tokens.
- Currency.
- Effective date.
- Source URL.
- Margin multiplier.

The platform admin console must show estimated AI cost per tenant and per plan period using actual `ModelRun` token counts.

## 10. Provider And Research Cost Guardrails

### 10.1 Cost Categories

Track at least these cost buckets:

| Bucket | Driver | Ledger Source |
|---|---|---|
| LLM generation | Prompt/output tokens | `ModelRun` plus model price catalog |
| Embeddings | Tokens and vector calls | `VoyageUsage` or future embedding ledger |
| Court/case refresh | Provider refresh calls | New `tracked_case_refresh_usage` ledger |
| Legal update sync | PRS/source polling and summaries | Source run records and global AI summary ledger |
| OCR/document parsing | Pages/files | New document processing usage rollup if not already present |
| Storage | Bytes stored | Existing storage governance summaries |
| Payment gateway | MDR/fees | Payment settlement/reconciliation import or configurable estimate |
| Support/manual research | Human time | Admin-created fulfillment/cost entries |

### 10.2 Margin Rules

Target gross margin:

- Solo: 75 percent or higher.
- Firm: 75 percent or higher under base assumptions, and never below 55 percent under stress assumptions without platform-owner approval.
- Corporate GC: 85 percent or higher after support/onboarding allocation.

Admin alerts:

| Alert | Trigger |
|---|---|
| Margin watch | Estimated gross margin under 60 percent for current period. |
| Margin danger | Estimated gross margin under 50 percent for current period. |
| Cost runaway | Tenant cost doubles week over week or exceeds 50 percent of subscription price before mid-cycle. |
| Provider runaway | Case refresh spend exceeds plan allowance by 20 percent. |
| AI abuse | One user consumes over 50 percent of tenant included AI credits in 7 days. |

Hard blocks:

- AI credit balance reaches zero and no top-up/overage policy is enabled.
- Tracked case count exceeds entitlement and grace window expires.
- Storage exceeds quota and upload would exceed limit.
- Payment is overdue beyond grace period.

Soft degradation:

- Lower-tier plans may reduce refresh frequency before hard suspension.
- AI requests can fall back to deterministic summaries where product-safe.
- Manual refresh can be disabled while scheduled refresh continues.

### 10.3 Unit Economics Guardrails

The subscription service must calculate estimated monthly contribution margin by comparing plan revenue against estimated variable cost. Revenue must exclude GST and discounts.

Use these launch guardrail ceilings until real cost data replaces them:

| Plan Code | Monthly Net Revenue Basis | Target Max Variable Cost | Notes |
|---|---:|---:|---|
| `solo_core` | about Rs 846 if Rs 999 GST-inclusive | Rs 200 | Low support, low refresh, mini-model default. |
| `solo_pro` | about Rs 1,694 if Rs 1,999 GST-inclusive | Rs 425 | Hero solo plan; enough room for normal AI and tracking. |
| `solo_elite` | about Rs 3,389 if Rs 3,999 GST-inclusive | Rs 850 | Watch high tracked-case users. |
| `firm_starter` | Rs 5,999 plus GST monthly; Rs 5,249/mo annual equivalent | Rs 1,250 | Must remain profitable even if all included AI credits are consumed. |
| `firm_growth` | Rs 19,999 plus GST monthly; Rs 17,499/mo annual equivalent | Rs 4,250 | Hero firm plan; target 75 percent or better on annual equivalent. |
| `firm_pro` | Rs 49,999 plus GST monthly; Rs 43,749/mo annual equivalent | Rs 10,500 | Keep large tracking-heavy firms on add-ons/custom quotes. |
| `gc_monitoring` | Rs 12,500 plus GST equivalent monthly | Rs 2,500 | Tracking-heavy; provider refresh cost must be watched. |
| `gc_starter` | Rs 25,000 plus GST equivalent monthly | Rs 5,000 | Corporate support allocation begins here. |
| `gc_professional` | Rs 66,667 plus GST equivalent monthly | Rs 10,000 | Target margin should exceed 85 percent. |

Variable cost formula:

```text
estimated_variable_cost =
  llm_generation_cost
  + embedding_cost
  + case_refresh_provider_cost
  + document_processing_cost
  + storage_cost
  + payment_gateway_fee
  + allocated_manual_support_cost
```

Implementation requirements:

- Store configurable default provider costs, including `case_refresh_cost_minor`, `payment_gateway_fee_bps`, and fixed payment fee if applicable.
- Compute margin for current billing period and projected full period.
- Show both estimates in platform admin.
- Alert when a tenant crosses 50 percent of its target max variable cost before 50 percent of the billing period has elapsed.
- Do not auto-charge overages in MVP unless an explicit overage agreement exists.

### 10.3.1 Law Firm Margin Recheck

The revised law-firm plan limits are designed so CaseOps does not lose money even when a firm fully uses included AI credits and tracked-case allowances.

Assumptions for launch margin checks:

- Firm prices exclude GST; GST is not revenue.
- Annual law-firm price is about 10.5 months of monthly price.
- Court-working-day refresh month: 22 refresh days.
- Base AI credit cost: Rs 1.25 per consumed credit.
- Stress AI credit cost: Rs 2.00 per consumed credit.
- Base case-refresh cost: Rs 0.03 per tracked-case refresh equivalent.
- Stress case-refresh cost: Rs 0.05 per tracked-case refresh equivalent.
- Danger case-refresh cost: Rs 0.10 per tracked-case refresh equivalent.
- Estimated payment gateway cost: 2 percent of subscription revenue until real MDR is configured.
- Monthly support allocation: Rs 500 Starter, Rs 1,500 Growth, Rs 3,000 Pro.
- Storage allocation: Rs 1 per GB-month until real storage cost is configured.

Base-case monthly variable cost estimate at 100 percent included AI usage:

| Plan | AI Cost | Case Refresh Cost | Support | Gateway/Storage | Total Base Cost | Monthly Margin | Annual-Equivalent Margin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Firm Starter | Rs 375 | Rs 165 | Rs 500 | about Rs 145 | about Rs 1,185 | about 80 percent | about 77 percent |
| Firm Growth | Rs 1,500 | Rs 660 | Rs 1,500 | about Rs 550 | about Rs 4,210 | about 79 percent | about 76 percent |
| Firm Pro | Rs 3,750 | Rs 1,650 | Rs 3,000 | about Rs 1,500 | about Rs 9,900 | about 80 percent | about 77 percent |

Stress-case monthly variable cost estimate at 100 percent included AI usage:

| Plan | Stress AI Cost | Stress Refresh Cost | Support | Gateway/Storage | Total Stress Cost | Monthly Margin | Annual-Equivalent Margin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Firm Starter | Rs 600 | Rs 275 | Rs 500 | about Rs 145 | about Rs 1,520 | about 75 percent | about 71 percent |
| Firm Growth | Rs 2,400 | Rs 1,100 | Rs 1,500 | about Rs 550 | about Rs 5,550 | about 72 percent | about 68 percent |
| Firm Pro | Rs 6,000 | Rs 2,750 | Rs 3,000 | about Rs 1,500 | about Rs 13,250 | about 73 percent | about 70 percent |

Danger-case rule:

- If actual case-refresh cost is Rs 0.10 or more, Firm Starter remains sellable, but Growth and Pro must be monitored closely.
- At Rs 0.10 or more, any firm requesting more than included tracked cases should be quoted through tracked-case add-ons or Firm Enterprise custom pricing.
- If support allocation for a firm exceeds the values above for two consecutive months, platform admin must review whether the customer should move up-plan, buy onboarding/support add-ons, or move to enterprise.

### 10.4 Court/Case Refresh Cost Advice

The exact provider cost per court/case refresh is unknown. Pricing remains viable only if court/case tracking is implemented as a measured, bulk-friendly, cost-aware service rather than naive unlimited polling.

Launch planning assumptions:

| Scenario | Cost Per Tracked-Case Refresh | Meaning |
|---|---:|---|
| Target | Rs 0.02 | Required for high-volume GC monitoring plans to preserve margin. |
| Planning Base | Rs 0.03 | Acceptable for most plans if refreshes run on court-working days and inactive cases are backed off. |
| Stress | Rs 0.05 | Solo/Firm plans may survive; GC monitoring margin becomes tight. |
| Danger | Rs 0.10 or more | Current included tracked-case volumes should be revised before launch. |

Advice:

- Negotiate provider pricing in bulk terms and target Rs 0.02 or lower per tracked-case refresh equivalent.
- Treat "daily" refresh as court-working-day daily by default, not calendar-day daily, unless the provider contract is cheap enough.
- Use smart polling:
  - Newly added or recently active cases: daily court-working-day refresh.
  - No-change cases after 30 days: every 2-3 court working days on lower plans.
  - Dormant cases after 90 days: weekly on lower plans unless user manually refreshes.
  - Priority plans and enterprise SLAs can keep higher cadence.
- Count provider-billed units separately from internal case checks because a bulk API may charge per request, per case, or per successful result.
- If actual provider cost exceeds Rs 0.05 per tracked-case refresh equivalent, revise one or more before public launch:
  - Reduce included tracked cases.
  - Increase tracked-case add-on price.
  - Shift lower plans to weekly/weekday smart polling.
  - Make high-volume GC monitoring an annual custom quote instead of fixed public price.

Implementation requirements:

- Default seed config: `case_refresh_cost_minor = 2` paisa for target modeling.
- Store stress-test configs for 3, 5, and 10 paisa in platform admin simulation tools.
- Every poll job must write attempted cases, refreshed cases, changed cases, provider calls, provider-billed units if known, latency, errors, and estimated cost.
- Platform admin must show current-period and projected case-refresh cost per tenant.
- Margin alerts must use actual provider cost when configured; otherwise use the planning-base cost.

### 10.5 Customer Usage And Spend Transparency

Tenant owners/admins must be able to see exactly where their included credits and paid add-ons are going. The product should not feel like a black box.

Tenant-visible reporting requirements:

- Current plan usage snapshot:
  - AI credits included this cycle.
  - AI credits used.
  - AI credits remaining.
  - Purchased/top-up credits available.
  - Tracked cases used vs included limit.
  - Manual refreshes used today vs daily limit.
  - Storage used vs limit.
  - Internal users/viewers used vs limit.
  - Active matters used vs limit.
- Spend/usage breakdown by category:
  - AI recommendations.
  - Lawyer-thinking strategy analysis.
  - Judgment/order summaries.
  - Document summaries/bundle analysis.
  - Legal update summaries delivered from global cache.
  - Case tracking scheduled refreshes.
  - Case tracking manual refreshes.
  - Storage.
  - Add-ons and top-ups purchased.
- Drilldowns:
  - Usage by user.
  - Usage by matter.
  - Usage by case/CNR where applicable.
  - Usage by feature/purpose.
  - Usage by day/week/month.
- Credit ledger:
  - Monthly included grant.
  - Top-up purchase.
  - Usage debit.
  - Refund/adjustment.
  - Expiry.
  - Admin grant.
  - Balance after every ledger event.
- Export:
  - CSV export for current period and prior periods.
  - Include date, actor, matter label/code where tenant-visible, feature, credits debited, tracked-case units, and source id.

Tenant-visible reports must show product credits and plan usage, not internal gross margin or vendor cost. Internal cost, profit, provider fee, and model cost are platform-admin-only.

### 10.6 Additional Credit Purchase UX

Tenants must be able to buy additional credits and capacity when they hit limits.

Purchase options:

- AI credit packs from Section 8.1.
- Tracked-case packs from Section 8.1.
- Storage packs from Section 8.1.
- Extra firm/corporate users from Section 8.1.
- API access add-on where eligible.

Credit purchase requirements:

- Tenant owner/admin sees "Buy credits" and "Buy capacity" CTAs on:
  - Billing overview.
  - Usage report.
  - AI limit blocked state.
  - Tracked-case limit blocked state.
  - Storage limit warning/block state.
- Checkout must show:
  - Add-on name.
  - Quantity.
  - Price.
  - GST.
  - Total.
  - Expiry where applicable.
  - Whether the add-on is one-time or recurring.
- One-time AI top-up credits are available immediately after verified payment.
- Recurring add-ons are attached to subscription items after verified payment.
- If payment is pending, UI must show "payment under verification" and not grant credits until backend verification/webhook confirms success.
- If payment fails, no credits are granted and the user can retry.
- Tenant admins can view top-up purchase history and invoices.

## 11. Entitlements

### 11.1 Entitlement Types

Implement entitlements as data, not scattered conditionals.

Required entitlement keys:

| Entitlement Key | Unit | Examples |
|---|---|---|
| `users_internal_limit` | count | 5, 15, 50 |
| `users_viewer_limit` | count | 25, 100 |
| `matters_active_limit` | count | 250, 2,500 |
| `tracked_cases_limit` | count | 200, 5,000 |
| `ai_credits_monthly` | credits | 300, 4,000 |
| `ai_credit_balance_topup` | credits | one-time ledger |
| `storage_bytes_limit` | bytes | 10 GB, 1 TB |
| `case_refresh_cadence` | enum | weekly, weekday_daily, smart_weekday_daily, smart_daily, priority_smart_daily, priority_daily, real_time_if_supported |
| `manual_case_refreshes_daily` | count | 5, 25, 100 |
| `legal_updates_enabled` | boolean | true |
| `ai_recommendations_enabled` | boolean | true |
| `judgment_summary_enabled` | boolean | true |
| `api_access_enabled` | boolean | firm_pro+ |
| `sso_enabled` | boolean | enterprise |
| `audit_export_enabled` | boolean | firm_pro+ / GC |
| `priority_support` | enum | none, email, priority, csm |

### 11.2 Enforcement Points

| Feature | Enforcement |
|---|---|
| User invitations | Block invite if internal/viewer limit exceeded, unless platform override. |
| Matter creation/import | Block active matter count above limit; allow archived matters. |
| Tracked case bookmark | Block new tracked case/bookmark beyond entitlement; offer add-on. |
| Scheduled case polling | Use plan cadence and priority queue. |
| Manual refresh | Enforce daily manual refresh count. |
| AI recommendation/summary | Deduct credits before or reserve credits, then settle actual result. |
| Document upload | Reuse storage quota gate; set quota from plan. |
| API access | Require entitlement and API capability. |
| Admin export | Require plan entitlement and capability. |

### 11.3 Credit Ledger Rules

Create an append-only ledger for product credits.

Ledger event types:

- `included_monthly_grant`
- `topup_purchase`
- `manual_admin_grant`
- `usage_debit`
- `usage_refund`
- `expiry`
- `plan_change_adjustment`

Ledger rows must include:

- Company id.
- Subscription id if applicable.
- Credit bucket.
- Delta.
- Balance after event.
- Reason.
- Source object type/id.
- Actor membership id or platform admin id.
- Created at.

Never mutate historical credit usage rows.

## 12. Billing Lifecycle

### 12.1 Subscription States

Required internal states:

- `trialing`
- `checkout_started`
- `payment_pending`
- `active`
- `past_due`
- `grace`
- `suspended`
- `cancelled`
- `expired`
- `manual_active`

### 12.2 Enrollment States

Track the enrollment funnel separately from subscription state.

Required states:

- `lead_created`
- `trial_started`
- `demo_requested`
- `checkout_started`
- `payment_authorized`
- `payment_processed`
- `subscription_active`
- `onboarding_started`
- `onboarding_completed`
- `lost`
- `cancelled`

Enrollment fields:

- Company id if created.
- Contact name/email/mobile.
- Segment: solo, firm, gc.
- Selected plan.
- Source: pricing_page, referral, demo, admin_created, import, partner.
- UTM fields.
- Bar Council number if provided for advocates.
- GSTIN if provided for firms/corporates.
- Coupon/referral code.
- Sales owner/platform admin id.
- Notes.
- Status timestamps.

### 12.3 Plan Purchase

Self-serve purchase flow:

1. User selects plan and interval.
2. Backend creates `checkout_session` with snapshot of plan, price, taxes, limits, and customer profile.
3. Backend creates Pine Labs Plural payment/order/subscription as appropriate.
4. Backend returns hosted checkout URL/challenge URL.
5. Frontend redirects user to Plural hosted checkout.
6. Return URL shows "payment pending verification" until backend confirms signature/webhook/provider status.
7. Webhook or status poll activates subscription.
8. Entitlements are granted and audit events recorded.
9. Tenant admin billing page shows plan, renewal, invoices, credits, usage, and payment history.

### 12.4 Renewal

Monthly/annual self-serve plans:

- Prefer Plural Subscription/UPI AutoPay mandate where enabled.
- If recurring mandate is unavailable, generate renewal invoice/payment link before expiry and use grace/suspension rules.
- Send in-app notification and email if email delivery is enabled for billing messages. SMS/WhatsApp should remain disabled unless separately approved.

Corporate annual plans:

- Support manual invoice/PO flow.
- Platform admin can mark payment received with reference, amount, TDS, GST, and attachment metadata.
- Every manual activation or extension must be audited.

### 12.5 Upgrade

Rules:

- Upgrade takes effect immediately after payment confirmation or admin approval.
- Proration should be calculated server-side using remaining days in billing period.
- New entitlements apply immediately.
- Additional included monthly credits are pro-rated for the current cycle.
- Downgrade should be scheduled at period end by default.

### 12.6 Cancellation

Rules:

- Self-serve cancellation schedules non-renewal at period end.
- Immediate cancellation/suspension requires owner/platform admin confirmation.
- Cancelled tenants keep read-only access for 30 days unless compliance/legal policy says otherwise.
- Data export should remain available to tenant owner during read-only window if plan/policy allows.

### 12.7 Dunning And Grace

Recommended grace:

| Segment | Grace |
|---|---|
| Solo | 7 days |
| Firm | 10 days |
| Corporate | 15 days by default; configurable up to 30 days |

Dunning events:

- Payment failed.
- Mandate pending.
- Renewal due in 7 days.
- Renewal due in 1 day.
- Grace started.
- Suspension scheduled.
- Suspended.
- Payment recovered.

### 12.8 Existing Tenant And Grandfathering

The migration must not accidentally suspend existing development, staging, pilot, or manually onboarded tenants.

Requirements:

- Create a `manual_active` or `grandfathered_free` subscription for existing active companies during migration or seed script.
- Default existing tenants to conservative entitlements at least equal to their current usage snapshot, unless platform admin chooses a stricter plan.
- Mark grandfathered tenants as not externally billable until converted.
- Platform admin must be able to convert a grandfathered tenant to a paid plan without losing usage history.
- No feature gate should fail closed for existing tenants until their subscription row and entitlement snapshot exist.

### 12.9 Downgrade, Overage, And Data Retention Rules

Downgrade rules:

- If current usage is within the target plan limit, schedule downgrade at period end by default.
- If current usage exceeds the target plan limit, allow scheduled downgrade but mark account `over_limit_pending_downgrade`.
- At downgrade effective date, do not delete data. Instead:
  - Keep existing matters, documents, tracked cases, and users visible according to existing permissions.
  - Block creation of new over-limit resources.
  - Pause non-critical scheduled refreshes above the new tracked-case allowance.
  - Require admin to archive matters, remove users, untrack cases, or buy add-ons before new usage.
- AI credits never go negative unless a signed enterprise overage policy is configured.
- Top-up credits already purchased should remain available after downgrade until expiry.

Overage policy:

- MVP default is hard limit plus upgrade/add-on prompt.
- Enterprise contracts may enable `overage_allowed=true` with explicit unit prices and monthly invoice review.
- Every overage allowance must have platform admin approval, reason, start date, end date, and cap.

## 13. Pine Labs Plural Integration

### 13.1 Provider Scope

Implement Pine Labs Plural as the primary online payment provider for:

- One-time plan purchases where recurring is not required.
- Monthly/annual subscription setup.
- UPI AutoPay/recurring mandates where enabled.
- AI credit top-ups.
- Tracked case add-ons.
- Storage/user add-ons.
- Payment links for manual invoices where appropriate.
- Refund initiation/reconciliation where provider support is enabled.

### 13.2 Provider Configuration

Add or reuse settings with env prefix `CASEOPS_`:

- `PINE_LABS_ENV`: `disabled`, `uat`, `production`.
- `PINE_LABS_API_BASE_URL`.
- `PINE_LABS_CLIENT_ID`.
- `PINE_LABS_CLIENT_SECRET`.
- `PINE_LABS_MERCHANT_ID`.
- `PINE_LABS_WEBHOOK_SECRET`.
- `PINE_LABS_WEBHOOK_SIGNATURE_HEADER`, default `webhook-signature` for new Plural webhooks.
- `PINE_LABS_WEBHOOK_ID_HEADER`, default `webhook-id`.
- `PINE_LABS_WEBHOOK_TIMESTAMP_HEADER`, default `webhook-timestamp`.
- `PINE_LABS_REQUEST_TIMEOUT_SECONDS`.
- `PINE_LABS_SUBSCRIPTIONS_ENABLED`.
- `PINE_LABS_PAYMENT_LINKS_ENABLED`.
- `PINE_LABS_PROVIDER_LIMIT_MAX_AMOUNT_MINOR`, default from verified provider docs/config.
- `PINE_LABS_ALLOWED_PAYMENT_METHODS`.
- `BILLING_COMPANY_GSTIN`, default `09AANCM5923C1ZD`.
- `BILLING_MINIMUM_GROSS_MARGIN_BPS`, default `7000`.
- `MFA_EXISTING_USER_GRACE_DAYS`, default `7`.
- `MFA_STEP_UP_TTL_MINUTES`, default `15`.
- `MFA_MAX_FAILURES_PER_5M`, default `5`.

Backward compatibility:

- Existing settings `pine_labs_api_key`, `pine_labs_api_secret`, and related payment link settings may map to client id/client secret where already used.
- Do not break current matter invoice payment links.

### 13.3 Security Requirements

Hard requirements:

- Never call Pine Labs APIs from frontend code.
- Never expose client id, client secret, merchant id secret material, webhook secret, bearer token, or raw provider secret in logs.
- Verify return-url signatures where Pine Labs supplies them.
- Verify all webhook signatures against raw body before JSON parsing.
- Reject unsigned webhooks in every non-local environment.
- Store raw provider payload only after redaction.
- Store full raw body only if encrypted and approved; otherwise store redacted JSON.
- Use idempotency keys/request ids for provider calls.
- Use provider event id and webhook headers for idempotency.
- Treat frontend redirect success as provisional until backend verification.
- Do not activate paid entitlements solely from client-side callback.

### 13.4 Token Flow

Provider client must:

1. Generate bearer token with `client_credentials` on backend.
2. Cache token with safety margin.
3. Retry once on 401 after clearing cache.
4. Use request timestamp and request id headers.
5. Use short provider timeouts.
6. Fail closed with user-safe errors when provider is disabled or misconfigured.

### 13.5 Hosted Checkout / Order Flow

For non-recurring payments:

1. Create local `billing_checkout_session`.
2. Create local `billing_payment_order` with amount snapshot.
3. Call Plural create order/payment or payment-link endpoint according to configured provider mode.
4. Store provider order id, provider payment id/link id, challenge/checkout URL, request id, amount, currency, status.
5. Return checkout URL to frontend.
6. On return URL, verify signature and mark local order as `return_verified_pending_webhook` or final if provider status is fetched and final.
7. On webhook, finalize.
8. On timeout/no webhook, allow manual "sync payment status".

### 13.6 Subscription / Recurring Flow

For recurring subscriptions where Plural Subscriptions are enabled:

1. Ensure CaseOps plan exists in local `billing_plans`.
2. Create or reuse provider plan:
   - Use `merchant_plan_reference` tied to CaseOps plan version.
   - Frequency `Month` or `Year`.
   - Amount in paisa.
   - Trial days if applicable.
   - End date long enough for product validity, configurable.
3. Create provider subscription/mandate for customer.
4. Create provider payment/authorization checkout.
5. Redirect user to Plural subscription checkout.
6. Track subscription as `payment_pending` until provider signals activation.
7. Process subscription lifecycle webhooks.
8. For fixed recurring mandates, rely on provider auto-debit where enabled.
9. For unsupported plans or enterprise prices over provider limits, use manual invoice/payment link flow.

### 13.7 Webhook Handling

Extend existing Pine Labs webhook handling or add versioned provider-specific dispatcher under the same payments router.

Requirements:

- Respond 2xx within 5 seconds after durable inbox write.
- Verify signature first.
- Parse event type and provider resource id.
- Store webhook event with:
  - Provider.
  - Provider event id.
  - Webhook id.
  - Webhook timestamp.
  - Signature digest or redacted signature marker.
  - Event type.
  - Provider order/subscription/payment id.
  - Redacted payload JSON.
  - Processing status.
  - First seen and last seen.
  - Retry count.
- Idempotently process repeated events.
- Handle out-of-order events. For example, `ORDER_PROCESSED` arriving before `ORDER_AUTHORIZED` must not downgrade a processed payment.
- Unknown events must be stored as `ignored_unknown` and surfaced in platform admin.

Minimum event mappings:

| Provider Event | Local Effect |
|---|---|
| `ORDER_AUTHORIZED` | Mark payment authorized; do not grant final entitlements unless capture/processed semantics are confirmed for this flow. |
| `ORDER_PROCESSED` | Mark payment paid/processed; activate plan/top-up/add-on. |
| `ORDER_CANCELLED` | Mark payment cancelled; keep subscription inactive unless prior processed payment exists. |
| `ORDER_FAILED` | Mark failed; start dunning if renewal. |
| `PAYMENT_FAILED` | Mark payment failed; preserve prior active subscription until grace rules apply. |
| `REFUND_PROCESSED` | Mark refund; reverse credit/entitlement if policy requires. |
| `REFUND_FAILED` | Mark refund failed; alert platform admin. |
| `SUBSCRIPTION_ACTIVATED` | Mark subscription active and grant entitlements. |
| `SUBSCRIPTION_PENDING` | Keep payment pending. |
| `SUBSCRIPTION_PAUSED` | Move to past_due/grace depending reason. |
| `SUBSCRIPTION_RESUMED` | Restore active if payment valid. |
| Subscription cancellation/revocation/failure events | Map once verified in Pine Labs docs/UAT; must not be ignored silently. |

### 13.8 Refunds

MVP internal operations:

- The product must not advertise a standalone refund policy until an approved legal/finance policy exists.
- Platform admin may record payment adjustment/refund intent and manual/provider status for operational reconciliation.
- If provider refund API is implemented, require two-step confirmation for any provider-side refund or payment adjustment above configurable threshold.
- A payment adjustment/refund does not automatically delete tenant data.
- A payment adjustment/refund may revoke top-up credits if unused; if used, mark account for manual review.
- Checkout UI should link only to approved terms/cancellation/payment terms that the business has supplied.

### 13.9 Reconciliation

Required reconciliation jobs:

- Daily payment status sync for `payment_pending`, `authorized`, and `past_due` rows.
- Daily subscription status sync for active/pending/paused subscriptions.
- Settlement import/manual upload support in later phase.
- Reconciliation discrepancy queue in platform admin:
  - Provider paid, local not active.
  - Local active, provider failed.
  - Amount mismatch.
  - Currency mismatch.
  - Duplicate provider event.
  - Webhook signature failures.

### 13.10 Signature Compatibility And Required Verifier Update

The current CaseOps invoice payment-link code may use an older/simple Pine Labs signature verifier. The billing implementation must support both old invoice-payment behavior and the current Plural webhook signature scheme without weakening security.

Required provider verifier behavior:

- For current Plural webhooks, read `webhook-id`, `webhook-timestamp`, and `webhook-signature`.
- Build signed content as `webhook_id + "." + webhook_timestamp + "." + raw_body`.
- Base64-decode the webhook secret if Pine Labs provides it in that format.
- Generate HMAC-SHA256 and Base64-encode the digest.
- Compare signatures using constant-time comparison.
- Reject stale timestamps outside a configurable tolerance, default 5 minutes, unless replay processing is explicitly enabled from platform admin.
- Store webhook id and provider event id separately. Webhook id handles retries; event id/resource id handles business idempotency.
- Keep legacy invoice payment-link signature verification behind a provider mode/version flag if needed.
- Add regression tests proving the old matter invoice webhook path still works or is intentionally migrated.

## 14. Data Model

Use the next Alembic revision after current head. Names can be adjusted to repo conventions, but concepts are required.

### 14.1 Pricing And Plan Tables

`billing_plan_versions`

- `id`
- `plan_code`
- `version`
- `segment`
- `display_name`
- `description`
- `status`: draft, active, retired
- `publicly_visible`
- `trial_eligible`
- `created_at`, `updated_at`

`billing_plan_prices`

- `id`
- `plan_version_id`
- `currency`
- `amount_minor`
- `interval`: month, year, one_time, custom
- `tax_behavior`: inclusive, exclusive
- `tax_rate_bps`
- `provider_plan_reference`
- `provider_plan_id`
- `effective_from`
- `effective_until`

`billing_plan_entitlements`

- `id`
- `plan_version_id`
- `entitlement_key`
- `value_type`: integer, string, boolean, json
- `value_json`

### 14.2 Subscription Tables

`billing_accounts`

- `id`
- `company_id`
- `billing_email`
- `billing_name`
- `billing_phone`
- `gstin`
- `billing_address_json`
- `tax_treatment`
- `created_at`, `updated_at`

`billing_subscriptions`

- `id`
- `company_id`
- `billing_account_id`
- `plan_version_id`
- `status`
- `segment`
- `billing_interval`
- `current_period_start`
- `current_period_end`
- `trial_start`
- `trial_end`
- `cancel_at_period_end`
- `cancelled_at`
- `grace_until`
- `provider`
- `provider_customer_id`
- `provider_subscription_id`
- `provider_mandate_id`
- `source`: self_serve, platform_admin, enterprise_contract, migration
- `created_at`, `updated_at`

`billing_subscription_items`

- `id`
- `subscription_id`
- `item_code`
- `item_type`: base_plan, add_on, top_up
- `quantity`
- `amount_minor`
- `currency`
- `interval`
- `status`
- `provider_item_id`

### 14.3 Checkout And Payment Tables

`billing_checkout_sessions`

- `id`
- `company_id`
- `billing_account_id`
- `subscription_id`
- `plan_version_id`
- `checkout_type`: new_subscription, renewal, upgrade, topup, addon, manual_invoice
- `status`
- `amount_minor`
- `tax_amount_minor`
- `total_amount_minor`
- `currency`
- `success_url`
- `cancel_url`
- `provider`
- `provider_checkout_url`
- `provider_order_id`
- `provider_payment_id`
- `provider_subscription_id`
- `expires_at`
- `metadata_json`
- `created_by_membership_id`
- `created_at`, `updated_at`

`billing_payment_orders`

- `id`
- `company_id`
- `checkout_session_id`
- `subscription_id`
- `provider`
- `merchant_reference`
- `provider_order_id`
- `provider_payment_id`
- `provider_link_id`
- `status`
- `amount_minor`
- `amount_paid_minor`
- `tax_amount_minor`
- `currency`
- `payment_url`
- `return_signature_verified`
- `provider_payload_json`
- `paid_at`
- `failed_at`
- `created_at`, `updated_at`

`billing_provider_events`

- Prefer expanding `payment_webhook_events` if clean; otherwise create this table and bridge old events.
- Must include provider event id uniqueness by provider.
- Must store webhook id, timestamp, event type, resource ids, redacted payload, processing status.

### 14.4 Usage And Credit Tables

`billing_credit_ledger`

- As defined in Section 11.3.

`billing_usage_events`

- `id`
- `company_id`
- `subscription_id`
- `usage_type`: ai_credit, model_token, case_refresh, storage, document_page, legal_update_summary, payment_fee, manual_research
- `quantity`
- `unit`
- `estimated_cost_minor`
- `currency`
- `source_type`
- `source_id`
- `metadata_json`
- `created_at`

`billing_usage_rollups`

- `id`
- `company_id`
- `period_start`
- `period_end`
- `usage_type`
- `quantity`
- `estimated_cost_minor`
- `revenue_allocated_minor`
- `gross_margin_bps`
- `created_at`, `updated_at`

`billing_usage_attribution`

- `id`
- `company_id`
- `subscription_id`
- `billing_usage_event_id`
- `actor_membership_id`
- `matter_id`
- `tracked_case_id`
- `feature_key`
- `purpose`
- `display_label`
- `credits_debited`
- `provider_units`
- `estimated_internal_cost_minor`
- `tenant_visible`
- `created_at`

Purpose:

- Enables tenant-facing reports by user, matter, case, feature, and date.
- Keeps platform cost fields separate from tenant-visible presentation.
- `tenant_visible=false` is required for platform-only/internal cost events.

`billing_profit_rollups`

- `id`
- `company_id`
- `subscription_id`
- `period_start`
- `period_end`
- `recognized_revenue_minor`
- `gross_revenue_minor`
- `discount_minor`
- `tax_collected_minor`
- `payment_gateway_cost_minor`
- `llm_cost_minor`
- `embedding_cost_minor`
- `case_refresh_cost_minor`
- `document_processing_cost_minor`
- `storage_cost_minor`
- `manual_support_cost_minor`
- `manual_research_cost_minor`
- `total_variable_cost_minor`
- `gross_profit_minor`
- `gross_margin_bps`
- `status`
- `created_at`, `updated_at`

Purpose:

- Powers back-office super-admin earnings/profit dashboards.
- Stores finance-friendly rollups so dashboards do not need to recompute every raw event.
- Must be regenerable for a period if pricing/cost assumptions are corrected.

### 14.5 Enrollment Tables

`billing_enrollments`

- Fields from Section 12.2.

`billing_admin_notes`

- `id`
- `company_id`
- `enrollment_id`
- `subscription_id`
- `note_type`
- `body`
- `created_by_platform_admin_id`
- `created_at`

### 14.6 Manual Invoice And PO Support

`billing_manual_invoices`

- `id`
- `company_id`
- `subscription_id`
- `invoice_number`
- `po_number`
- `amount_minor`
- `tax_amount_minor`
- `tds_deducted_minor`
- `amount_received_minor`
- `currency`
- `status`
- `issued_on`
- `due_on`
- `paid_on`
- `payment_reference`
- `attachment_storage_key`
- `created_by_platform_admin_id`
- `created_at`, `updated_at`

### 14.7 Coupons And Discounts

`billing_coupons`

- `id`
- `code`
- `description`
- `discount_type`: percent, fixed_amount
- `discount_value`
- `currency`
- `duration`: once, first_period, repeating, forever
- `duration_periods`
- `max_redemptions`
- `redeemed_count`
- `valid_from`
- `valid_until`
- `segment_scope_json`
- `plan_scope_json`
- `status`
- `created_by_platform_admin_id`
- `created_at`, `updated_at`

`billing_coupon_redemptions`

- `id`
- `coupon_id`
- `company_id`
- `checkout_session_id`
- `subscription_id`
- `discount_amount_minor`
- `currency`
- `redeemed_by_membership_id`
- `created_at`

### 14.8 Platform Admin Identity

The implementation must define platform-admin identity explicitly instead of reusing ordinary tenant admin checks.

Acceptable approaches:

1. Add `is_platform_admin` and `platform_capabilities_json` to a global user/admin table.
2. Add a dedicated `platform_admin_memberships` table.

Required fields if a new table is used:

- `id`
- `user_id`
- `role`
- `capabilities_json`
- `status`
- `mfa_required`
- `created_by_platform_admin_id`
- `created_at`
- `updated_at`

Founder-only launch rule:

- At launch, exactly one platform super-admin should be seeded: the founder/company owner user configured by environment or seed data.
- No tenant owner/admin role should imply platform access.
- No self-service UI should allow creating additional platform admins in MVP.
- Additional platform admins may be added only through a migration/seed script or a founder-only audited platform action in a later phase.
- Platform super-admin can view all back-office reports, but this must not expose matter document content by default.
- The platform-admin navigation must remain hidden for everyone except the configured platform super-admin.

Security rules:

- Platform admin routes must require platform capability, not tenant role.
- Platform admin access must be audited even for read-only views.
- Platform admin manual actions must require a reason.
- MFA is not mandatory at launch.
- The schema and UI must include `mfa_required`/`mfa_enforced_at` style fields so MFA can be enforced later for both new and existing platform admins without another data migration.
- High-risk actions should require re-auth/MFA once auth support exists and the platform owner enables enforcement.

## 15. Backend APIs

### 15.1 Public/Tenant Billing APIs

Add routes under existing API conventions.

`GET /api/billing/plans`

- Returns active public plan catalog, prices, feature summaries, and add-ons.
- Does not require auth for public pricing if mounted outside tenant auth, or returns tenant-aware plan eligibility if authenticated.

`GET /api/billing/current`

- Authenticated tenant.
- Returns current subscription, entitlements, usage summary, credit balance, payment status, and renewal info.

`POST /api/billing/checkout`

- Creates checkout for plan purchase, upgrade, renewal, top-up, or add-on.
- Requires tenant owner/admin.
- Validates plan eligibility and provider readiness.
- Returns checkout URL and local session id.

`GET /api/billing/checkout/{session_id}`

- Returns checkout status and safe next action.

`POST /api/billing/checkout/{session_id}/sync`

- Manually sync provider status for pending checkout.

`POST /api/billing/subscription/cancel`

- Schedule cancellation at period end.

`POST /api/billing/subscription/reactivate`

- Reactivate during grace/current period if payment valid.

`GET /api/billing/usage`

- Returns current and past period usage by category.
- Supports filters: period, feature, actor, matter, tracked case, source type.
- Returns summary totals plus drilldown rows suitable for UI charts/tables.
- Tenant-visible response must exclude internal cost, vendor cost, gross profit, and margin fields.

`GET /api/billing/credit-ledger`

- Returns tenant-visible credit ledger.

`GET /api/billing/credit-ledger/export`

- Tenant owner/admin endpoint to export credit ledger as CSV.
- Includes credit grants, top-up purchases, usage debits, expiries, adjustments, and balances.
- Must not expose internal model/vendor cost.
- Records audit event.

`GET /api/billing/invoices`

- Returns SaaS subscription invoices/manual invoice rows, not matter invoices.

`GET /api/billing/invoices/{invoice_id}/download`

- Tenant owner/admin endpoint to download a SaaS tax invoice or manual invoice.
- Supports `format=pdf` by default and `format=json` for structured download.
- Must verify invoice belongs to the tenant.
- Must record audit event.
- Must not expose platform-only provider cost or profit fields.

`GET /api/billing/payments/export`

- Tenant owner/admin endpoint to export payment/order history as CSV.
- Includes date, invoice/payment reference, payment method if known, amount, GST/tax, status, provider reference, and subscription/add-on association.
- Must not expose Pine Labs secrets, raw payloads, internal fees, or margin.
- Records audit event.

`GET /api/billing/statement`

- Tenant owner/admin endpoint for a billing statement covering invoices, payments, credits purchased, recurring add-ons, and outstanding balance for a date range.
- Supports `format=pdf` and `format=csv`.
- Must record audit event.

`GET /api/billing/reports/spend`

- Tenant owner/admin endpoint for detailed plan usage and credit spend reporting.
- Returns:
  - Plan and period.
  - Included credits and limits.
  - Top-up credits and expiry.
  - Usage by category.
  - Usage by user.
  - Usage by matter.
  - Usage by tracked case/CNR.
  - Daily trend.
  - Blocked attempts due to limits.
- Must not return internal cost, profit, provider fee, or platform margin.

`GET /api/billing/reports/spend/export`

- CSV export of tenant-visible usage/spend report.
- Requires owner/admin.
- Records audit event.

`GET /api/billing/add-ons`

- Returns add-on catalog eligible for the tenant's segment/current plan.

`POST /api/billing/add-ons/checkout`

- Starts checkout for AI credit packs, tracked-case packs, storage packs, extra users, or API access.
- Requires owner/admin.
- Uses same payment verification rules as subscription checkout.

`POST /api/billing/trials`

- Public or lightly authenticated route for starting a trial.
- Creates lead/enrollment, user, company, billing account, and trial subscription where needed.
- Applies duplicate-trial checks by email/mobile/domain/GSTIN signals.
- Must rate-limit trial creation.
- Must not require payment credentials.

`POST /api/billing/enrollments/demo-request`

- Captures corporate/firm demo requests without creating a full tenant when the user chooses assisted sales.
- Stores segment, source, selected plan, contact details, and notes.
- Notifies platform admin through durable in-app/admin notification.

### 15.2 Pine Labs APIs

Reuse existing:

- `POST /api/payments/pine-labs/webhook`

Extend for:

- Subscription events.
- Billing checkout events.
- Existing matter invoice payment links.

Add if needed:

- `POST /api/payments/pine-labs/return`
- Or handle return as frontend route calling backend verification endpoint.

### 15.3 Tenant Admin APIs

Under `/api/admin/billing`:

- `GET /summary`
- `GET /entitlements`
- `PATCH /billing-account`
- `GET /usage`
- `GET /payments`
- `GET /invoices`

Use existing owner/admin capability style.

### 15.4 Platform Admin APIs

Create a platform-admin route namespace that is not tenant-scoped by current tenant context alone.

Required capabilities:

- `platform:admin`
- `platform:billing_view`
- `platform:billing_manage`
- `platform:payment_reconcile`
- `platform:plan_manage`
- `platform:usage_view`
- `platform:manual_override`

Routes:

`GET /api/platform-admin/overview`

- MRR, ARR, active subscriptions, trials, conversion, failed payments, earnings, usage cost, gross profit, gross margin, and margin alerts.

`GET /api/platform-admin/enrollments`

- Filter by state, segment, plan, date, source, sales owner.

`GET /api/platform-admin/companies/{company_id}/billing`

- Subscription, payments, usage, entitlements, notes, audit events.

`POST /api/platform-admin/companies/{company_id}/subscriptions`

- Create manual subscription or assisted checkout.

`PATCH /api/platform-admin/subscriptions/{id}`

- Change status, grace, plan, or billing interval with audited reason.

`POST /api/platform-admin/subscriptions/{id}/grant-credits`

- Manual credit grant with reason.

`POST /api/platform-admin/subscriptions/{id}/suspend`

- Suspend tenant paid features with reason.

`POST /api/platform-admin/subscriptions/{id}/resume`

- Resume tenant paid features.

`POST /api/platform-admin/manual-invoices`

- Create enterprise/manual invoice.

`POST /api/platform-admin/manual-invoices/{id}/mark-paid`

- Record offline payment, TDS, GST, reference, attachment metadata.

`GET /api/platform-admin/provider-events`

- Search webhook/provider event inbox.

`POST /api/platform-admin/provider-events/{id}/reprocess`

- Reprocess failed/ignored event with audit.

`GET /api/platform-admin/usage`

- Cross-tenant usage and estimated cost report.

`GET /api/platform-admin/profit`

- Back-office super-admin P&L report.
- Returns recognized revenue, gross revenue, discounts, taxes collected, payment gateway cost, LLM cost, embedding cost, case-refresh cost, document-processing cost, storage cost, manual support/research cost, total variable cost, gross profit, and gross margin.
- Supports filters: period, segment, plan, company, source, sales owner.
- Must support current period, prior period, month-to-date, quarter-to-date, and year-to-date.

`GET /api/platform-admin/profit/companies`

- Company-level profitability table.
- Columns:
  - Company.
  - Plan.
  - Status.
  - Revenue.
  - Add-on revenue.
  - AI cost.
  - Case refresh cost.
  - Storage/document cost.
  - Payment cost.
  - Manual support/research cost.
  - Gross profit.
  - Gross margin.
  - Risk state.

`GET /api/platform-admin/profit/export`

- CSV export for accountant/back office.
- Requires `platform:billing_view`.
- Records audit event.

`GET /api/platform-admin/exports/revenue`

- CSV export for finance.

`POST /api/platform-admin/coupons`

- Create coupon or referral code.
- Requires `platform:billing_manage`.

`PATCH /api/platform-admin/coupons/{coupon_id}`

- Retire, extend, or edit coupon constraints.
- Must not mutate historical redemption rows.

`GET /api/platform-admin/margin-alerts`

- Returns current-period margin watch/danger tenants.

`POST /api/platform-admin/companies/{company_id}/overage-policy`

- Create or update enterprise overage policy with unit prices, cap, expiry, and reason.

## 16. Frontend Requirements

### 16.1 Public Pricing Page

Create or update a public pricing page:

- Segment tabs: Solo Lawyers, Law Firms, Corporate GC.
- Monthly/annual toggle where applicable.
- Show plan limits plainly: users, matters, tracked cases, AI credits, storage, refresh cadence.
- "Start free trial" for solo/firm.
- "Talk to us" for GC Enterprise.
- Add-ons section.
- FAQ:
  - Are AI credits unlimited?
  - What happens if I exceed tracked cases?
  - Is GST included?
  - Do you support UPI AutoPay?
  - Can corporates pay by invoice/PO?
  - Is my data used for model training?
  - What happens after cancellation?

### 16.2 Tenant Billing Page

Add `/app/admin/billing` or equivalent tenant admin tab.

Must show:

- Current plan and status.
- Renewal date/current period.
- Trial days remaining.
- Payment status.
- Upgrade/downgrade CTA.
- AI credit balance and monthly reset.
- Tracked cases used vs limit.
- Users used vs limit.
- Matters used vs limit.
- Storage used vs limit.
- Recent payments.
- SaaS invoices/manual invoices.
- Download invoice PDF/JSON.
- Download billing statement PDF/CSV.
- Export payment history CSV.
- Top-up purchase options.
- Add-on management.
- Billing account profile: billing email, GSTIN, address.
- Grace/past-due banners.
- Link to detailed usage/spend report.
- Link to credit ledger.
- Export credit ledger CSV.
- Link to buy AI credits/capacity.

States:

- Loading.
- No subscription.
- Trial active.
- Payment pending.
- Active.
- Past due/grace.
- Suspended/read-only.
- Provider disabled/unavailable.
- Checkout failed.
- Payment under verification.

### 16.2.1 Tenant Usage And Spend Report

Add `/app/admin/billing/usage` or a tab inside tenant billing.

Purpose:

- Help tenant owners/admins understand where their plan credits and usage are going.
- Reduce support tickets and make top-up purchases understandable.

Required cards:

- AI credits used/remaining.
- Top-up credits available and expiry.
- Tracked cases used/remaining.
- Manual refreshes used today.
- Storage used/remaining.
- Users/viewers used/remaining.
- Active matters used/remaining.
- Current billing period and reset date.

Required charts/tables:

- Usage by feature:
  - AI recommendations.
  - Lawyer-thinking strategy analysis.
  - Judgment/order summaries.
  - Document summaries.
  - Case tracking refreshes.
  - Legal updates from global cache.
- Usage by user:
  - User name/email.
  - AI credits used.
  - Runs/actions.
  - Top feature.
- Usage by matter:
  - Matter code/title.
  - AI credits used.
  - Documents analyzed.
  - Tracked case events.
- Usage by tracked case/CNR:
  - CNR/case number.
  - Scheduled refreshes.
  - Manual refreshes.
  - New updates detected.
- Daily trend:
  - Credits used.
  - Case refreshes.
  - Document pages analyzed if available.
- Blocked/near-limit events:
  - Feature.
  - Reason.
  - Timestamp.
  - Suggested add-on/upgrade.

Actions:

- Buy AI credits.
- Buy tracked-case pack.
- Buy storage.
- Upgrade plan.
- Export CSV.
- Download billing statement.
- Download credit ledger.
- Download invoice/payment history from billing page.

Tenant-facing wording:

- Use "credits used" and "plan usage", not "cost to CaseOps".
- Do not show internal profit, LLM vendor cost, court-provider cost, or payment fees to tenants.

### 16.2.2 Credit Purchase Flow

Add a reusable purchase flow for:

- AI credit packs.
- Tracked-case packs.
- Storage packs.
- Extra users.
- API access where eligible.

Required UX:

- Select add-on.
- Select quantity where supported.
- Review GST and total.
- Show expiry for one-time AI credit packs.
- Confirm payment through Pine Labs Plural.
- Show pending verification state.
- Grant credits/capacity only after verified payment.
- Show success with new balance.
- Show failure with retry.

Blocked-state CTAs:

- If AI credits exhausted, show "Buy AI credits" and "Upgrade plan".
- If tracked cases exhausted, show "Buy tracked-case pack" and "Upgrade plan".
- If storage exhausted, show "Buy storage" and "Upgrade plan".
- If user limit exhausted, show "Add user pack" or "Upgrade plan".

### 16.3 Checkout UX

Flow:

1. User selects plan/top-up.
2. Review screen shows price, GST, total, limits, billing interval, renewal terms.
3. User confirms.
4. Backend returns Plural checkout URL.
5. Redirect to provider.
6. Return page shows "Verifying payment".
7. Poll backend checkout status.
8. On success, route to `/app/admin/billing?payment=success`.
9. On pending, keep status and manual sync button.
10. On failure/cancel, show retry.

Do not mark plan active only from query params.

### 16.4 Platform Admin Console

Add `/app/platform-admin` or another clearly internal route.

Access:

- Only the configured founder/company-owner platform super-admin has access at launch.
- Platform access must be granted through platform identity/capability records, not tenant owner/admin roles.
- Do not expose any UI for ordinary tenant admins to request, create, or grant platform admin access.
- Must be hidden from tenant-only navigation.
- All access and actions audited.

Pages:

1. Overview.
2. Enrollments.
3. Subscriptions.
4. Payments.
5. Usage and costs.
6. Provider events.
7. Plans/prices.
8. Manual invoices.
9. Coupons/referrals.
10. Tenant detail drawer/page.

Overview widgets:

- MRR.
- ARR.
- Gross earnings/revenue.
- Net revenue after discounts excluding GST.
- Active subscriptions by plan.
- Trial count and trial conversion.
- New enrollments by source.
- Payment failures.
- Past-due accounts.
- Add-on revenue.
- AI credit top-up revenue.
- Tracked-case pack revenue.
- Estimated LLM cost.
- Estimated provider/case refresh cost.
- Estimated storage/document/OCR cost.
- Estimated payment gateway cost.
- Manual support/research cost.
- Gross profit.
- Estimated gross margin.
- Top tenants by usage.
- Top tenants by revenue.
- Top tenants by profit.
- Top loss-risk tenants.
- Margin danger tenants.

Enrollment table columns:

- Company/lead name.
- Segment.
- Plan selected.
- Status.
- Source.
- Created date.
- Trial end.
- Payment status.
- Owner email/mobile.
- GSTIN if available.
- Sales/admin owner.
- Last activity.

Tenant detail:

- Subscription status.
- Entitlements.
- Usage charts.
- Credit ledger.
- Payment orders.
- Webhook events.
- Admin notes.
- Audit timeline.
- Revenue, cost, gross profit, and margin for platform admins only.
- User/matter/case usage drilldowns with matter content hidden unless tenant context permits.
- Manual actions.

Manual actions:

- Grant credits.
- Change plan.
- Extend trial.
- Start/stop grace.
- Suspend/resume.
- Mark manual invoice paid.
- Create checkout link.
- Reprocess webhook.

Every manual action requires a reason field.

### 16.4.1 Back-Office Super Admin Profit Reports

The platform admin console must include a back-office view for the company owner/super admin.

Add `/app/platform-admin/profit` or equivalent.

Required top-level KPIs:

- Gross earnings.
- Net recognized revenue excluding GST.
- GST collected.
- Discounts given.
- Refund/payment adjustments recorded internally.
- Add-on revenue.
- AI top-up revenue.
- Tracked-case pack revenue.
- Payment gateway cost.
- LLM cost.
- Embedding cost.
- Case-refresh provider cost.
- Storage/document/OCR cost.
- Manual support/research cost.
- Total variable cost.
- Gross profit.
- Gross margin percentage.
- Average revenue per account.
- Average profit per account.

Required breakdowns:

- By plan.
- By segment: solo, firm, GC.
- By company.
- By month.
- By acquisition source.
- By add-on type.
- By feature cost bucket.

Required tables:

- Most profitable customers.
- Lowest-margin customers.
- Loss-making or at-risk customers.
- Highest AI usage customers.
- Highest case-refresh cost customers.
- Highest support/manual-cost customers.
- Payment failures and past-due accounts.
- Discounts that reduced margin.

Required actions:

- Export revenue report CSV.
- Export profit report CSV.
- Export usage-cost report CSV.
- Open company billing detail.
- Create margin review note.
- Change plan/add-on only through audited manual action.
- Grant credits only with reason.
- Mark manual support/research cost.

Visibility:

- This page is platform-admin/super-admin only.
- At launch, this means the configured founder/company-owner user only.
- Tenant admins must never see CaseOps internal costs or profit.
- Access to this page must be audited.

## 17. Coupons, Referrals, And Discounts

MVP support:

- Coupon codes with percent or fixed discount.
- Duration: once, first period, repeating N periods, forever for grandfathered/manual only.
- Segment eligibility.
- Plan eligibility.
- Max redemptions.
- Expiry.
- Platform admin creation.

Referral support:

- Store referral source on enrollment.
- Optional future credit to referrer.
- Do not implement automatic payout in MVP.

Discount guardrails:

- Any discount above 30 percent requires platform admin high-privilege capability.
- Enterprise custom discounts require reason and approval metadata.
- Discount must appear on checkout, invoice, and admin ledger.

## 18. Notifications

Use existing durable in-app notification patterns where applicable.

Tenant-facing notification events:

- Trial started.
- Trial ending in 3 days.
- Trial expired.
- Payment successful.
- Payment failed.
- Subscription active.
- Renewal upcoming.
- Grace started.
- Account suspended.
- AI credits low.
- AI credits exhausted.
- Tracked case limit near.
- Storage limit near.
- Top-up successful.

External email:

- Billing email notifications are desirable, but implementation must respect existing email provider configuration and should fail safely.
- SMS/WhatsApp for billing should not be enabled unless separately approved.

Platform admin notifications:

- Payment webhook failed.
- Signature verification failure spike.
- Provider disabled/misconfigured.
- Tenant margin danger.
- Large manual override.
- Enterprise invoice overdue.

## 19. Security, Privacy, And Compliance

### 19.1 Payment Security

- No card/bank/UPI sensitive details stored in CaseOps.
- Store provider tokens only transiently in memory cache.
- Redact provider payloads.
- Verify signatures.
- Use idempotency.
- Audit all billing state transitions.
- Payment webhooks must be public but signature-verified.

### 19.2 Tenant Isolation

- Tenant admins can only see their own billing.
- Platform admins can see billing/usage metadata across tenants but not matter content by default.
- Usage rollups must not leak case titles or client names in platform overview. Tenant detail can show company-level metadata only.

### 19.3 DPDP And Confidentiality

- Billing data should be separated from matter content.
- Do not use matter content to train models.
- Pricing page/privacy copy should mention no training on user data if product policy supports it.

### 19.4 Tax/Finance

Implementation must support:

- GSTIN capture.
- Default company GSTIN: `09AANCM5923C1ZD`.
- GST-inclusive and GST-exclusive pricing.
- Tax invoice number.
- TDS deduction recording for enterprise/manual payments according to applicable Indian law and accountant-approved configuration.
- CSV export for accountant.

Open accounting/legal validation:

- Final GST invoicing/e-invoicing requirements.
- TDS classification, rates, certificates, and reconciliation treatment must be configurable and validated by the company's CA/accountant.
- Public refund/credit-note copy is intentionally not specified in-product until approved by finance/legal.

### 19.5 Professional Responsibility And Product Disclaimers

Because CaseOps is sold to legal professionals and corporate legal teams, billing and pricing pages must avoid suggesting that CaseOps itself provides legal advice.

Requirements:

- Pricing page and checkout terms must state that CaseOps is legal technology software, not a law firm.
- AI outputs must remain attorney-assistive and subject to professional review.
- Human/legal-editor research memo add-ons must clearly identify whether fulfillment is internal, partner-assisted, or deferred.
- Corporate GC materials must clarify that CaseOps supports legal operations and monitoring, not external counsel substitution.
- Trial and checkout terms must link to privacy, terms of use, cancellation, data-retention, and payment terms supplied by the business. Do not publish standalone refund language until approved copy exists.

## 20. Analytics And Metrics

Product metrics:

- Pricing page visits.
- Trial starts.
- Checkout starts.
- Checkout completions.
- Trial-to-paid conversion.
- Monthly churn.
- Net revenue retention.
- Plan mix.
- Add-on attach rate.
- AI credit top-up rate.
- Tracked-case overage rate.

Finance metrics:

- MRR.
- ARR.
- Gross earnings.
- Add-on revenue.
- AI top-up revenue.
- Tracked-case pack revenue.
- Gross revenue.
- Net revenue after tax/discount/refund.
- Recognized revenue excluding GST.
- Taxes collected.
- Discounts.
- Payment gateway cost.
- LLM cost.
- Embedding cost.
- Case-refresh provider cost.
- Storage/document/OCR cost.
- Manual support/research cost.
- Total variable cost.
- Gross profit.
- Payment failure rate.
- Days sales outstanding for enterprise invoices.
- Estimated COGS.
- Estimated gross margin.

Usage metrics:

- AI credits used.
- AI credits purchased.
- AI credits expired.
- Tokens by model/purpose.
- Tracked case refreshes.
- Tracked-case packs purchased.
- Judgment summaries generated.
- Legal update summaries generated.
- Storage used.
- Active users.
- Matters created.
- Usage by user, matter, tracked case, feature, and day.

## 21. Rollout Plan

### Phase 1: Billing Foundation And Plan Catalog

- Add plan, price, entitlement, subscription, checkout, usage, credit, enrollment tables.
- Seed plan catalog `2026.05.v1`.
- Add entitlement service.
- Add tenant billing current-state API.
- Add usage rollups from existing ModelRun, VoyageUsage, storage, case tracking.
- Add tests.

### Phase 2: Tenant Pricing And Checkout

- Public pricing page.
- Tenant billing page.
- Tenant usage/spend report.
- Credit/add-on purchase flow.
- Checkout session creation.
- Pine Labs hosted checkout/payment link for one-time plan purchases and top-ups.
- Return verification and status polling.
- Webhook event expansion.
- Activate entitlements after verified payment.

### Phase 3: Recurring Subscriptions

- Plural subscription plan sync.
- Subscription/mandate creation.
- Subscription lifecycle webhooks.
- Renewal, dunning, grace, and suspension.
- Plan upgrade/downgrade.

### Phase 4: Platform Admin Console

- Overview.
- Enrollments.
- Tenant subscription detail.
- Payment/provider events.
- Manual invoice/PO.
- Manual overrides with audit.
- Usage/cost/margin dashboards.
- Back-office super-admin profit reports and exports.

### Phase 5: Enterprise And Finance Hardening

- Manual invoices.
- TDS/GST export.
- Internal payment adjustment/refund reconciliation workflows, without public refund-policy commitments.
- Settlement reconciliation.
- Advanced alerts.
- Coupon/referral controls.

## 22. Acceptance Criteria

### 22.1 Pricing

- Public plan catalog matches this PRD.
- Prices, entitlements, and add-ons are data-driven.
- GST inclusive/exclusive display works by segment.
- Annual pricing appears correctly.
- Add-on purchase is possible where applicable.

### 22.2 Entitlements

- AI credits are granted, consumed, shown, and blocked when exhausted.
- Tenant admin can buy additional AI credits through verified checkout.
- Tenant admin can buy tracked-case, storage, and user add-ons where eligible.
- Tracked case limits are enforced.
- User limits are enforced.
- Storage quotas reflect plan.
- Plan upgrade updates entitlements.
- Downgrade schedules at period end.
- Downgrade over-limit behavior blocks new over-limit usage without deleting tenant data.
- Existing tenants receive a grandfathered/manual subscription before any gate is enforced.

### 22.3 Payments

- No provider credentials in frontend.
- Checkout creation works in provider-disabled safe state and UAT-configured state.
- Webhook signatures are verified from raw body.
- Duplicate webhooks do not duplicate entitlements/credits.
- Out-of-order webhooks do not downgrade final paid state.
- Return URL is provisional until backend verification.
- Payment sync can recover missed webhook state.
- Current Plural webhook signature scheme is implemented using webhook id, webhook timestamp, raw body, and secret.
- Legacy matter invoice payment links continue to work or have an explicit tested migration path.

### 22.4 Admin Console

- Tenant admin can see subscription, usage, payments, invoices, credits, and limits.
- Tenant admin can see detailed usage/spend reports by feature, user, matter, case, and day.
- Tenant admin can export tenant-visible usage reports.
- Tenant admin can self-download SaaS invoices, billing statements, payment history, and credit ledger exports without support intervention.
- Platform admin can see enrollments, subscriptions, revenue, payment failures, provider events, usage, costs, and margin alerts.
- Platform super admin can see earnings, revenue, costs, gross profit, margin, top customers, loss-risk customers, and export reports.
- At launch, platform super-admin access is restricted to the configured founder/company-owner user only.
- Platform admin manual actions require reason and write audit rows.
- Platform admin views do not expose matter content by default.
- Platform admin identity and capabilities are separate from tenant admin roles.

### 22.5 Cost Protection

- Estimated AI cost is computed from model usage.
- Case refresh usage is counted.
- Margin danger alerts are generated.
- No unlimited AI or unlimited refreshes are shipped in self-serve plans.
- Profit rollups separate gross revenue, GST/tax, discounts, variable costs, gross profit, and gross margin.
- Tenants cannot see internal provider costs or profit metrics.

## 23. Verification Requirements

Backend:

- Unit tests for plan catalog and entitlement resolution.
- Unit tests for AI credit ledger.
- Unit tests for credit reservation, debit, refund, expiry, and concurrent usage.
- Unit tests for subscription state transitions.
- Unit tests for Pine Labs signature verification using raw body.
- Unit tests for webhook idempotency and out-of-order events.
- Route tests for billing checkout, current subscription, usage, admin billing, platform admin access.
- Route tests for trial creation, duplicate-trial prevention, coupons, and platform overage policy.
- Route tests for tenant usage/spend reports and add-on checkout.
- Route tests for tenant invoice download, billing statement download, payment export, and credit-ledger export.
- Route tests for platform profit reports and exports.
- Route tests proving tenant owner/admin cannot access platform-admin routes.
- Route tests proving only the seeded founder/company-owner platform super-admin can access platform-admin routes at launch.
- Migration upgrade/downgrade tests.
- Cross-tenant billing isolation tests.
- Provider-disabled tests.
- Existing-tenant migration/grandfathering tests.

Frontend:

- Pricing page tests.
- Tenant billing page states.
- Tenant usage/spend report tests.
- Tenant invoice/billing/usage download tests.
- Add-on and AI-credit purchase flow tests.
- Checkout pending/success/failure states.
- Platform admin access denied for normal tenant users.
- Platform admin overview/table tests.
- Platform profit dashboard tests.

Suggested commands:

```powershell
uv --directory apps/api run ruff check <touched backend files>
uv --directory apps/api run pytest tests/test_billing_plans.py tests/test_billing_entitlements.py -q
uv --directory apps/api run pytest tests/test_pine_labs_billing.py tests/test_billing_webhooks.py -q
uv --directory apps/api run pytest tests/test_platform_admin_billing.py -q
uv --directory apps/api run pytest tests/test_tenant_ai_policy.py tests/test_case_tracking.py -q
npm run test --workspace @caseops/web
npm run typecheck --workspace @caseops/web
python -m py_compile <new migrations and scripts>
```

## 24. Open Questions

These questions should be answered before production launch. Implementation can begin with safe defaults from this PRD.

1. Is the Pine Labs merchant account already approved for Plural Subscriptions/UPI AutoPay, or only payment links/hosted checkout?
2. What UAT credentials and webhook URL registration process will Pine Labs provide?
3. Should solo pricing be legally displayed as GST-inclusive, or should every plan show base price + GST?
4. What invoice numbering format and accountant-approved tax invoice template should CaseOps use with GSTIN `09AANCM5923C1ZD`?
5. Will corporate customers pay online, by bank transfer, or both?
6. What accountant-approved TDS categories/rates/certificate fields should be configured for enterprise/manual payments?
7. What is the contracted provider cost per eCourts/case refresh? Until known, use Section 10.4 assumptions.
8. Are legal research memos fulfilled internally, by partner lawyers, or deferred?
9. Who are the first platform admins? MFA is not mandatory at launch, but must remain enforceable later for existing users.
10. Should unused purchased top-up credits expire after 12 months, 6 months, or never?
11. Is the launch plan self-serve India only, or should international cards/payments be supported later?
12. What initial default cost assumptions should be used for storage, OCR, payment gateway fees, and support allocation?

## 25. Pine Labs Team Information Checklist

Before implementation starts, request the following from Pine Labs/Plural onboarding and support. The integration should not be considered production-ready until every item below is confirmed or marked not applicable.

### 25.1 Account And Product Enablement

Ask Pine Labs to confirm:

- Merchant/legal entity name mapped to GSTIN `09AANCM5923C1ZD`.
- UAT merchant id.
- Production merchant id.
- Whether Hosted Checkout / Payments are enabled.
- Whether Pay by Link APIs are enabled.
- Whether Payment Links can be used for SaaS subscription invoices and top-ups.
- Whether Plural Subscriptions are enabled.
- Whether UPI AutoPay/recurring mandates are enabled.
- Whether monthly and annual recurring plans are supported for this merchant.
- Whether one-time top-up payments and recurring subscription payments can coexist under the same merchant account.
- Whether refunds/payment adjustments are enabled in API/dashboard. Do not expose public refund policy from this confirmation alone.
- Whether settlements and settlement APIs/reports are enabled.
- Whether international cards/payments are enabled or India-only.
- Whether any business/category restrictions apply to legal technology SaaS.

### 25.2 Credentials And Environments

Ask Pine Labs to provide:

- UAT base URL.
- Production base URL.
- UAT client id.
- UAT client secret.
- Production client id.
- Production client secret.
- Any separate merchant secret/hash key for payment APIs.
- Any separate webhook signing secret.
- Whether webhook secret is provided raw or Base64-encoded.
- Token endpoint path.
- Token response format and expiry field: `expires_in` vs `expires_at`.
- Required auth grant type. Expected: `client_credentials`.
- Required headers on mutating requests, including `Request-ID` and `Request-Timestamp`.
- Required clock-skew tolerance.
- IP allowlist requirements, if any.
- TLS/cipher requirements.
- Rate limits and burst limits.

### 25.3 Payment/Checkout Flow Details

Ask Pine Labs to confirm:

- Recommended API for self-serve SaaS checkout: Hosted Checkout, Orders, Payment Links, or another Plural flow.
- Exact endpoint paths for:
  - Create order/payment.
  - Fetch order/payment status.
  - Create payment link if separate.
  - Fetch payment link status.
  - Cancel/expire payment link if supported.
- Required amount unit. Expected: paisa/minor units.
- Minimum and maximum transaction amount.
- Whether the documented Rs 10 lakh limit applies to every payment/order amount for this merchant.
- Supported payment methods for CaseOps:
  - UPI.
  - Cards.
  - NetBanking.
  - Wallets, if enabled.
  - EMI/BNPL, if enabled or disabled.
- Whether convenience fees/MDR can be passed to customer or must be absorbed.
- Return/callback URL parameters.
- Whether return/callback URL is signed.
- How to verify return/callback signature if present.
- Failure/cancel callback behavior.
- Whether provider returns a hosted checkout URL, challenge URL, or payment link URL for each flow.
- UAT test cards/UPI ids/netbanking details for success, failure, pending, cancel, refund, and timeout scenarios.

### 25.4 Subscription And UPI AutoPay Details

Ask Pine Labs to confirm:

- Exact endpoints for:
  - Create plan.
  - Update plan if supported.
  - Create subscription.
  - Create payment/authorization for subscription.
  - Fetch subscription status.
  - Pause subscription.
  - Resume subscription.
  - Cancel subscription.
  - Update subscription amount/plan if supported.
- Supported frequencies:
  - Monthly.
  - Yearly.
  - One-time mandate.
  - On-demand mandate.
- Whether recurring monthly/yearly mandates automatically handle pre-debit notification and debit execution.
- Whether Pine Labs handles pre-debit notifications for recurring mandates, and what CaseOps must show/send.
- Mandate registration charge behavior, including the documented Rs 2 debit/refund if no amount is charged during registration.
- Maximum mandate amount and whether plan `max_limit_amount` must equal or exceed recurring charge.
- Trial period support and how trial interacts with mandate registration.
- Retry policy for failed auto-debits.
- Subscription states and exact meanings.
- Whether subscription update/downgrade/proration is supported by provider, or must be handled by CaseOps with new subscription/order.
- Whether annual plans above provider limits need split payments/manual invoice.

### 25.5 Webhooks

Ask Pine Labs to provide/confirm:

- Webhook registration process for UAT and production.
- Exact webhook endpoint URL format to register.
- Whether one endpoint can receive payment, refund, token, customer, and subscription events.
- Required webhook headers:
  - `webhook-id`.
  - `webhook-timestamp`.
  - `webhook-signature`.
- Whether `webhook-signature` includes a version prefix such as `v1,`.
- Exact signature algorithm and sample code.
- Exact signed-content format. Expected: `webhook-id.webhook-timestamp.raw_body`.
- Whether timestamp is Unix seconds.
- Recommended timestamp tolerance.
- Retry schedule and maximum retries.
- Requirement to return HTTP 2xx within 5 seconds.
- Whether events are guaranteed ordered. CaseOps assumes they are not.
- Full list of enabled events for this merchant.
- Sample payloads for all enabled events:
  - `ORDER_AUTHORIZED`.
  - `ORDER_PROCESSED`.
  - `ORDER_CANCELLED`.
  - `ORDER_FAILED`.
  - `PAYMENT_FAILED`.
  - `REFUND_PROCESSED`.
  - `REFUND_FAILED`.
  - `SUBSCRIPTION_ACTIVATED`.
  - `SUBSCRIPTION_PENDING`.
  - `SUBSCRIPTION_PAUSED`.
  - `SUBSCRIPTION_RESUMED`.
  - `SUBSCRIPTION_COMPLETED`.
  - `SUBSCRIPTION_CHARGED`.
  - `SUBSCRIPTION_HALTED`.
  - `SUBSCRIPTION_CANCELLED`.
  - `SUBSCRIPTION_REVOKE_FAILED`.
  - `SUBSCRIPTION_UPDATED`.
  - `SUBSCRIPTION_UPDATE_FAILED`.
- Which id should be used for business idempotency:
  - Provider event id.
  - Order id.
  - Payment id.
  - Merchant order reference.
  - Subscription id.
  - Merchant subscription reference.

### 25.6 Pricing, MDR, Settlement, And Reconciliation

Ask Pine Labs to provide:

- MDR/payment gateway fee by method:
  - UPI.
  - Debit card.
  - Credit card.
  - NetBanking.
  - Wallets.
  - International, if enabled.
- Fixed fee per transaction if any.
- GST on payment gateway charges if applicable.
- Settlement cycle.
- Settlement report format.
- Settlement API endpoint, if available.
- Fields needed to match settlement rows to CaseOps payment orders.
- Chargeback/dispute process and webhook/report support.
- Refund/payment adjustment fee, if any.
- Failed payment fee, if any.
- Mandate setup fee, if any.
- Subscription debit fee, if different from normal payment MDR.

### 25.7 Go-Live And Operational Support

Ask Pine Labs to provide:

- UAT sign-off checklist.
- Production activation checklist.
- Webhook UAT validation process.
- Production webhook registration process.
- Support escalation contacts.
- SLA for payment incidents.
- Maintenance-window notification process.
- Dashboard access roles for CaseOps back office.
- Whether Pine Labs dashboard supports exporting payments, refunds, settlements, mandates, and subscriptions.
- Required legal/compliance documents from CaseOps.
- Any branding or checkout descriptor that customers will see on bank/UPI/card statements.

### 25.8 CaseOps Configuration Values Needed From Pine Labs

The implementation should be configurable using these values:

```text
CASEOPS_PINE_LABS_ENV=
CASEOPS_PINE_LABS_API_BASE_URL=
CASEOPS_PINE_LABS_CLIENT_ID=
CASEOPS_PINE_LABS_CLIENT_SECRET=
CASEOPS_PINE_LABS_MERCHANT_ID=
CASEOPS_PINE_LABS_WEBHOOK_SECRET=
CASEOPS_PINE_LABS_WEBHOOK_SIGNATURE_HEADER=webhook-signature
CASEOPS_PINE_LABS_WEBHOOK_ID_HEADER=webhook-id
CASEOPS_PINE_LABS_WEBHOOK_TIMESTAMP_HEADER=webhook-timestamp
CASEOPS_PINE_LABS_PAYMENT_ORDER_PATH=
CASEOPS_PINE_LABS_PAYMENT_STATUS_PATH=
CASEOPS_PINE_LABS_PAYMENT_LINK_PATH=
CASEOPS_PINE_LABS_PAYMENT_LINK_STATUS_PATH=
CASEOPS_PINE_LABS_SUBSCRIPTION_PLAN_PATH=
CASEOPS_PINE_LABS_SUBSCRIPTION_PATH=
CASEOPS_PINE_LABS_SUBSCRIPTION_STATUS_PATH=
CASEOPS_PINE_LABS_REFUND_PATH=
CASEOPS_PINE_LABS_SETTLEMENT_PATH=
CASEOPS_PINE_LABS_SUBSCRIPTIONS_ENABLED=
CASEOPS_PINE_LABS_PAYMENT_LINKS_ENABLED=
CASEOPS_PINE_LABS_PROVIDER_LIMIT_MAX_AMOUNT_MINOR=
CASEOPS_PINE_LABS_ALLOWED_PAYMENT_METHODS=
CASEOPS_PINE_LABS_MDR_BPS_UPI=
CASEOPS_PINE_LABS_MDR_BPS_CARD=
CASEOPS_PINE_LABS_MDR_BPS_NETBANKING=
CASEOPS_PINE_LABS_FIXED_FEE_MINOR=
CASEOPS_BILLING_COMPANY_GSTIN=09AANCM5923C1ZD
CASEOPS_BILLING_MINIMUM_GROSS_MARGIN_BPS=7000
CASEOPS_MFA_EXISTING_USER_GRACE_DAYS=7
CASEOPS_MFA_STEP_UP_TTL_MINUTES=15
CASEOPS_MFA_MAX_FAILURES_PER_5M=5
```

## 26. Source Links

- MyLegal365 pricing signal: [https://mylegal365.com/](https://mylegal365.com/)
- Nowlez pricing signal: [https://www.nowlez.com/pricing](https://www.nowlez.com/pricing)
- LegalDesk AI pricing signal: [https://www.legaldeskai.in/pricing](https://www.legaldeskai.in/pricing)
- SCC Online AI Pro pricing: [https://www.scconline.com/ai-pro](https://www.scconline.com/ai-pro)
- Manupatra plans: [https://www.manupatrafast.com/Asps/SubscriptionPlans.aspx](https://www.manupatrafast.com/Asps/SubscriptionPlans.aspx)
- Pine Labs Payment APIs: [https://developer.pinelabsonline.com/v2.0/docs/about-payments](https://developer.pinelabsonline.com/v2.0/docs/about-payments)
- Pine Labs Subscription: [https://developer.pinelabsonline.com/docs/subscription](https://developer.pinelabsonline.com/docs/subscription)
- Pine Labs Subscription Integration: [https://developer.pinelabsonline.com/docs/subscription-integration-steps](https://developer.pinelabsonline.com/docs/subscription-integration-steps)
- Pine Labs Webhooks: [https://developer.pinelabsonline.com/docs/developer-tools-webhooks](https://developer.pinelabsonline.com/docs/developer-tools-webhooks)
- Pine Labs Webhook Signature Verification: [https://developer.pinelabsonline.com/docs/webhook-signature-verification](https://developer.pinelabsonline.com/docs/webhook-signature-verification)
- Pine Labs Webhook Events: [https://developer.pinelabsonline.com/docs/webhook-available-events](https://developer.pinelabsonline.com/docs/webhook-available-events)
- Pine Labs Webhook Retries: [https://developer.pinelabsonline.com/docs/webhook-retries](https://developer.pinelabsonline.com/docs/webhook-retries)
- OpenAI API pricing reference for cost catalog: [https://platform.openai.com/docs/pricing](https://platform.openai.com/docs/pricing)

## 27. Codex CLI Starter Prompt

```text
You are in the CaseOps repository.

Read docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md end to end before editing.

Implement the pricing, subscription billing, Pine Labs Plural payment integration, usage governance, tenant billing UI, and platform admin console described in the PRD. Reuse existing billing, Pine Labs, webhook, audit, AI token governance, storage governance, and admin patterns where possible.

Start with the data model, plan catalog, entitlement service, and usage/credit ledger. Then add checkout/payment flows, webhooks, tenant billing UI, and platform admin console. Keep provider-disabled states safe. Never expose payment credentials to frontend code. Do not enable SMS/WhatsApp billing notifications unless separately approved.

Ask only for blockers that cannot be implemented safely with the PRD assumptions. Otherwise implement in small verified slices, add migrations and tests, and run targeted backend/frontend checks after each slice.
```
