# CaseOps Pricing Competitive Review - 2026-11-04

Status: owner decisions recorded 2026-11-04 (Section 7); catalog `2026.11.v1` implemented
(Section 8), not yet deployed. Recorded by Sanjeev Kumar.

Scope: public pricing at https://caseops.ai/pricing (catalog `2026.05.v1`) versus four
Indian legal-tech vendors: Jurisphere, Provakil (Pro Vakil), Legistify and Practice League
(now sold as RazorSign and RazorLex). All external pages were accessed on 2026-11-04.

Related: `docs/PRD_CASEOPS_PRICING_BILLING_PLURAL_ADMIN_2026-05-31.md` (pricing PRD,
sections 7-11), `docs/BILLING_EXPLAINER_2026-06-02.md`.

## 1. Headline findings

1. None of the four competitors publishes an INR price list on its own website. Every
   competitor number below is third-party, app-store or forum evidence and is marked as such.
   CaseOps is the only one of the five with a public, versioned INR rate card. That is the
   strongest honest differentiator available today.
2. The current CaseOps catalog is loss-making at full use on every Solo and GC plan when
   tracked-case refreshes are paid at the eCourtsIndia pay-as-you-go ceiling coded in
   `services/case_tracking.py` (Rs 1.65 per refresh-and-detail call). Tracked-case
   allowances, not AI, are the dominant variable cost.
3. Several pricing-page claims are not enforced or not deliverable today (Section 4).
4. Production LLM generation runs on OpenAI (`gpt-5.1`, recommendations on `gpt-5-mini`,
   `scripts/deploy-prod.sh:40-42`), embeddings on Voyage `voyage-4-large`. The margin model
   uses those providers.

## 2. Competitor evidence (accessed 2026-11-04)

### 2.1 Jurisphere (AI research and drafting)

| Item | Evidence | Source |
|---|---|---|
| Public price | Not public. Fees "as communicated by Jurisphere and accepted by you in writing"; GST extra; fees non-refundable; renewal price may change on 30 days' notice | https://www.jurisphere.ai/terms-of-service/ (updated 26 May 2026) |
| Seat model | One named user per licence; no sharing or rotation | Same; https://www.jurisphere.ai/fair-usage-policy/ (updated 23 Jun 2026) |
| AI limits | Monthly query allowance per seat, thresholds not published; each message is one query; translation metered in pages; overage queued, not cut off | https://www.jurisphere.ai/fair-usage-policy/ |
| Billing term | Refers to an "annual, upfront Jurisphere subscription"; no annual discount published | https://www.jurisphere.ai/referral-policy/ |
| Price signals (unverified, anonymous, about one year old) | "1.3k a month"; "500" one-time pass; "Rs. 2500 per month" | https://www.legallyindia.com/convos/topic/428043-i-jurisphere-subscription-worth-it/newest ; https://www.legallyindia.com/convos/topic/452270-best-legal-ai-for-individual-use |
| Trial | None on vendor pages; a directory reports a demo-based trial on request | https://dreamlegal.in/product/jurisphere |
| Scope | Research, document review, list of dates, Word add-in, translation. No matter management, court sync, cause lists or IP described | https://www.jurisphere.ai/ |
| Segment | Law firms and in-house teams | https://www.jurisphere.ai/ |

### 2.2 Provakil (practice management)

| Item | Evidence | Source |
|---|---|---|
| Public price | Not public on the vendor site (book a demo); /pricing returns 404. Monthly and annual subscriptions exist | https://www.provakil.com/refund |
| App-store in-app purchases | Basic Rs 9,900; Standard Rs 19,900; Premium Rs 29,900 (period and inclusions not stated) | https://apps.apple.com/in/app/provakil/id1111933293 |
| Directory price (IP suite listing) | Basic Rs 1,999 per user per month; Professional Rs 3,999 per user per month ("pricing last updated 23 Sep 2026") | https://www.softwaresuggest.com/provakil-intellectual-property |
| Directory price | Rs 5,888, exclusive of taxes, basis unclear; same page also says "Price Available on Request" | https://www.techjockey.com/detail/provakil |
| Scope | Case updates from "19,000+" forums, cause lists by e-mail and WhatsApp, IP renewal alerts, timesheets, invoicing, mobile apps | https://www.provakil.com/legal-practice-management ; https://www.provakil.com/legal-case-management/case-updates |
| AI limits | None published | - |
| Trial | Conflicting: the iOS listing says free trial; Techjockey says none | Sources above |
| Segment | Advocates and law firms; separate enterprise legal management for in-house teams | https://www.provakil.com/ |

### 2.3 Legistify (corporate legal operations)

| Item | Evidence | Source |
|---|---|---|
| Public price | Not public: "Get Pricing" and "Book Demo" | https://legistify.com/pricing |
| Tier names (third-party only) | LegisTrak Lite, LegisTrak Pro, 50+ users volume; all quote-based | https://www.spotsaas.com/product/legistify/pricing ("Last updated: May 18, 2026") |
| Price estimate (unverified, page returned 403) | "starts at $50 per user/month", an aggregator estimate | https://www.itqlick.com/legistify/pricing |
| Scope | Contract lifecycle, litigation management, IP tracking, notice management; claims integration with "10000+ courts"; case search over "5,00,000+" cases; contract-side AI | https://legistify.com/pricing ; https://legistify.com/ |
| Trial | Free live demo, no trial | https://legistify.com/pricing ; https://techjockey.com/detail/legistify |
| Segment | Enterprises and in-house legal teams | https://legistify.com/ |

### 2.4 Practice League (RazorSign and RazorLex)

| Item | Evidence | Source |
|---|---|---|
| RazorSign Standard | USD 500 per year, up to 5 users, annual only; signed-contract management; AI usage billed separately ("cost does not include AI costs (usage-based)") | https://razorsign.com/pricing |
| RazorSign Professional | USD 1,500 per year, up to 5 users; adds drafting, clause library, redlining, AI review, Word plug-in; AI usage, implementation, migration and training extra | https://razorsign.com/pricing |
| RazorLex (law firms) | Not public: priced per module and user count, by quote | https://www.razorlex.com/faq/ |
| RazorLex directory prices (unverified, conflicting, USD) | "$15" (basis unstated); "$25/Per Year" | https://slashdot.org/software/p/RazorLex/ ; Capterra/GetApp snippets (pages returned 403) |
| Scope | RazorLex: matters, court-website updates, cause lists by e-mail, billing app. No IP | https://www.razorlex.com/ |
| Segment | RazorLex: firms of all sizes; RazorSign: corporate legal | Sources above |

Not found for any of the four vendors: a vendor-published INR price, GST treatment (except
Jurisphere: GST extra), extra-seat price, storage limits, or numeric AI limits. Several
directory pages (Capterra, Software Advice, GetApp, G2, ITQlick) refused automated access;
their figures are search-snippet only and are not used as evidence.

## 3. Side-by-side (price per user per month, INR)

CaseOps effective per-user figures divide the plan price by its included internal users.

| Product / tier | Price basis | Effective Rs per user per month | Annual discount | Includes | Source quality |
|---|---|---:|---|---|---|
| CaseOps Solo Core (current) | Rs 999/mo incl. GST, 2 users | 500 (incl. GST) | 2 months free | Research, drafting, matters, court tracking, 100 AI credits | Vendor, public |
| CaseOps Solo Pro (current) | Rs 1,999/mo incl. GST, 4 users | 500 (incl. GST) | 2 months free | As above, 300 credits, 200 tracked cases | Vendor, public |
| CaseOps Firm Growth (current) | Rs 19,999/mo + GST, 15 users | 1,333 + GST | about 1.5 months free | As above, 1,200 credits, 1,000 tracked cases | Vendor, public |
| CaseOps GC Professional (current) | Rs 8,00,000/yr + GST, 15 users | 4,444 + GST | Annual only | As above, 100 viewers | Vendor, public |
| Jurisphere | Per named seat, annual upfront | 1,300-2,500 reported | None published | Research and drafting only | Anonymous forum, unverified |
| Provakil | Per user (directory) | 1,999-3,999 reported | Not published | Practice management, case updates, IP alerts | Directory, unverified |
| Legistify | Quote | Not public (aggregator estimate USD 50) | Not published | Corporate legal ops | Quote-only |
| RazorSign | Per account, up to 5 users | about 730-2,200 at Rs 88/USD (USD 500-1,500/yr / 5 / 12), AI extra | Annual only | Contracts only | Vendor, public (USD) |

Where CaseOps is weaker or more expensive:

- Corporate GC: GC Professional at Rs 8 lakh per year is far above any public signal for
  contract-only tools (RazorSign) and is only justified by litigation tracking volume, which
  is not deliverable today (Section 4).
- Firm per-user price (Rs 1,333 + GST on Firm Growth) is in the reported Jurisphere band, but
  Jurisphere seats are research-only; this is a value win only if the page makes the bundle
  visible.
- Provakil and Legistify both advertise court coverage counts ("19,000+" forums, "10000+"
  courts). CaseOps advertises tracked-case counts it cannot refresh at scale under the current
  provider budget (Section 4).
- IP: Provakil and Legistify market IP tracking. CaseOps IP workflows exist but no seeded plan
  carries the IP entitlements, so IP is fail-closed for every paying plan.
- Trial: CaseOps advertises a 14-day no-card trial; in code the trial never expires and the
  sign-up path never creates one (Section 4).

## 4. CaseOps page claims versus enforced behaviour

| Claim on /pricing | Code truth | Evidence |
|---|---|---|
| "AI credits/mo" | Credits are granted once per billing period; annual and GC plans receive one month's credits per year | `services/saas_billing.py:641-677`, `:133-138` |
| "Refresh: daily / smart daily / priority daily" | `case_refresh_cadence` is not read anywhere; polling uses one global interval, at most 50 cases per tenant per run | `core/settings.py:367-369`; `services/case_tracking.py:5722-5752` |
| Tracked cases up to 25,000 | Every tenant shares a default Rs 1,000/month Indian Kanoon + eCourtsIndia budget; at Rs 1.65 per refresh that funds about 600 refreshes a month | `services/provider_spend.py:22`, `:81-87`; `services/case_tracking.py:410-418` |
| API access, SSO readiness, audit export by plan | `api_access_enabled`, `sso_enabled`, `audit_export_enabled` are not enforced; no tenant API-key feature; audit export is role-gated for every plan | `api/routes/admin.py:105`, `:156`; `services/production_safety.py:1569-1571` |
| 14-day no-card trial | `POST /api/billing/trials` is never called by the web app; new workspaces from `/api/bootstrap/company` get no subscription and later become unlimited `grandfathered_free`; trials never move to expired | `apps/web/app/sign-in/NewWorkspaceForm.tsx`; `services/saas_billing.py:324-358`, `:2157-2205` |
| Internal copy on a public page | "until UAT evidence and founder go/no-go are complete" | `apps/web/app/pricing/PricingPageClient.tsx:241-245` |
| Raw tokens | "Refresh: smart weekday daily" style labels from enum values | `apps/web/lib/billing-format.ts:35` |

Additional billing defects found during the audit (not pricing-page copy, listed for triage):
plan gates fail open without a subscription and ignore subscription status; the drafting
minimum of 2 credits is keyed to `draft_generation` while drafting calls use `draft`;
included-credit expiry subtracts from the pooled balance and can consume purchased top-ups;
coupons and overage policies are stored but never applied.

## 5. Cost basis and margin model

Assumptions below; revenue excludes GST; margins use annual-equivalent net revenue (the
conservative basis).

| Input | Value | Source |
|---|---|---|
| gpt-5.1 | USD 1.25 input / 10.00 output per 1M tokens | https://developers.openai.com/api/docs/models/gpt-5.1 (model page now marked deprecated) |
| gpt-5-mini | USD 0.25 input / 2.00 output per 1M tokens | https://developers.openai.com/api/docs/models/gpt-5-mini |
| Voyage voyage-4-large | USD 0.12 per 1M tokens (code budgets USD 0.18) | https://docs.voyageai.com/docs/pricing ; `core/settings.py:543-545` |
| INR per USD, all-in | 110 | `services/gemini_spend_cap.py` |
| One AI credit | about 4,000 tokens (`round(tokens / 4000)`) | `services/saas_billing.py:1514-1526` |
| Cost per credit | expected Rs 1.25 (gpt-5.1 at 85/15 input/output is about Rs 1.13); stress Rs 2.50 (50/50) | Derived |
| Tracked-case refresh | Rs 1.65 per call (eCourtsIndia PAYG ceiling in code); sensitivity Rs 0.30 if contracted | `services/case_tracking.py:410-418` |
| Refreshes per tracked case per month | expected 4, stress 6 (daily court-working-day refresh would be 22) | Assumption |
| Utilisation | expected: 40% of AI credits, 60% of tracked cases; stress: 100% of both | Assumption |
| Research provider (Indian Kanoon) | expected Rs 100 solo / Rs 300 firm and GC; stress Rs 500 / Rs 1,000 | Per-tenant budget `scripts/deploy-prod.sh` |
| Other | Rs 30/user/month uncredited AI (rerank, embeddings); Rs 2/GB-month storage at 50%/100% fill; 2% gateway; support allocation per PRD 10.3.1 | PRD and assumption |

### 5.1 Current catalog `2026.05.v1` at Rs 1.65 per refresh

| Plan | Net Rs/mo | Expected margin | Stress margin | Provider spend needed at stress (cap Rs 1,000) |
|---|---:|---:|---:|---:|
| solo_core | 706 | 26% | -102% | 995 |
| solo_pro | 1,412 | 4% | -151% | 2,480 |
| solo_elite | 2,824 | -42% | -272% | 7,925 |
| firm_starter | 5,249 | 58% | 4% | 3,475 |
| firm_growth | 17,499 | 58% | 6% | 10,900 |
| firm_pro | 43,749 | 60% | 9% | 25,750 |
| gc_monitoring | 12,500 | -100% | -360% | 50,500 |
| gc_starter | 25,000 | -24% | -227% | 50,500 |
| gc_professional | 66,667 | -88% | -403% | 248,500 |

Today the Rs 1,000 provider cap stops the losses by refusing refreshes, which means the
advertised tracked-case volumes are not delivered.

### 5.2 Proposed catalog `2026.11.v1`

| Plan | Net Rs/mo | Expected margin at Rs 1.65 | Expected margin at Rs 0.30 | Stress margin at Rs 0.30 |
|---|---:|---:|---:|---:|
| solo_core | 706 | 45% | 52% | -36% |
| solo_pro | 1,412 | 50% | 59% | -9% |
| solo_elite | 2,824 | 50% | 64% | 1% |
| firm_starter | 4,999 | 62% | 71% | 34% |
| firm_growth | 14,999 | 66% | 75% | 47% |
| firm_pro | 41,666 | 72% | 79% | 57% |
| gc_monitoring | 12,500 | 44% | 64% | 42% |
| gc_starter | 25,000 | 50% | 70% | 40% |
| gc_professional | 66,667 | 54% | 73% | 40% |

The PRD targets (75% solo and firm, 85% GC) are not reachable at the coded Rs 1.65 refresh
ceiling with any useful tracked-case allowance. They become reachable for firm plans at a
contracted rate near Rs 0.30. Solo stress margins stay negative because the stress case
assumes every user exhausts AI credits and the full research budget at the same time; the
provider and AI caps bound that loss.

## 6. Proposed structure `2026.11.v1` (recommended)

Positioning: compete on value and transparency, not the lowest headline price. One public INR
rate card, GST shown, staff seats included on solo plans, research plus drafting plus matters
plus court tracking in every tier, and a no-card trial.

| Plan | Price | Annual | Users | Matters | Tracked cases | AI credits / month | Storage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Solo Core | Rs 999/mo incl. GST | Rs 9,990 | 2 | 50 | 15 | 100 | 5 GB |
| Solo Pro (recommended) | Rs 1,999/mo incl. GST | Rs 19,990 | 4 | 250 | 40 | 250 | 20 GB |
| Solo Elite | Rs 3,999/mo incl. GST | Rs 39,990 | 6 | 1,000 | 120 | 600 | 50 GB |
| Firm Starter | Rs 5,999/mo + GST | Rs 59,990 | 5 | 300 | 150 | 500 | 25 GB |
| Firm Growth (recommended) | Rs 17,999/mo + GST | Rs 1,79,990 | 15 (+10 viewers) | 1,500 | 400 | 1,500 | 150 GB |
| Firm Pro | Rs 49,999/mo + GST | Rs 4,99,990 | 50 (+50 viewers) | 5,000 | 1,000 | 3,500 | 500 GB |
| GC Litigation Monitoring | - | Rs 1,50,000 + GST | 3 (+25 viewers) | 500 | 750 | 600 | 50 GB |
| GC Starter | - | Rs 3,00,000 + GST | 5 (+25 viewers) | 1,000 | 1,500 | 2,500 | 250 GB |
| GC Professional | - | Rs 8,00,000 + GST | 15 (+100 viewers) | 10,000 | 4,000 | 8,000 | 1 TB |
| Enterprise (firm and GC) | Custom | Custom | Custom | Custom | Custom | Custom | Custom |

Changes versus `2026.05.v1`: annual = 10 x monthly (two months free) for every monthly plan;
Firm Growth Rs 19,999 to Rs 17,999 (Rs 1,200 per user + GST); tracked-case and GC AI
allowances cut to what the provider cost can fund; tracked-case add-ons repriced to cover
Rs 1.65 refreshes (500 cases Rs 4,999/mo, 1,000 cases Rs 8,999/mo).

Value versus Jurisphere (reported Rs 1,300-2,500 per research seat per month, unverified):
Solo Pro gives four users research, drafting, matters and court tracking for Rs 1,999 in
total including GST, on a public price with a no-card trial and monthly billing.

Product changes required so the page tells the truth:

1. Grant included AI credits every calendar month for annual plans.
2. Fund each tenant's provider budget from its plan instead of the flat Rs 1,000 default.
3. Remove cadence, API, SSO and audit-export rows from plan cards until they are enforced;
   show "Scheduled court refresh" uniformly.
4. Replace internal activation copy with plain buyer copy.
5. Trial behaviour per decision D3: self-serve sign-up starts the trial, and an ended trial
   blocks new work.

## 7. Owner decisions

| ID | Decision | Recommendation | Owner answer |
|---|---|---|---|
| D1 | Undercut on price or compete on value | Compete on value at current price points; two months free on every annual plan | No preference stated; recommendation adopted |
| D2 | Tracked-case allowances before a contracted eCourtsIndia rate is known | Cut to Section 6 values; revisit when the contracted rate is known | Approved as recommended |
| D3 | Free tier or trial terms | No free-forever tier; 14-day no-card trial that really ends in read-only, and new sign-ups start on it | Approved as recommended |
| D4 | Name competitors on the page | Do not name; no competitor publishes INR prices, so a named comparison would rest on unverified numbers | Approved as recommended |

Decisions were given on 2026-11-04. Revisit D2 when the eCourtsIndia contract rate is known:
at about Rs 0.30 per refresh the firm and GC allowances can be raised (Section 5.2).

## 8. Implementation

| Change | Where | Test |
|---|---|---|
| Catalog `2026.11.v1` added beside `2026.05.v1`; existing subscriptions keep their version | `apps/api/alembic/versions/20261104_0001_pricing_catalog_2026_11_v1.py`; `CATALOG_VERSION` in `services/saas_billing.py`, `services/provider_costs.py` | `tests/test_pricing_catalog_20261104.py::test_public_catalog_is_2026_11_v1_with_approved_prices_and_limits`, `::test_catalog_version_constants_agree`; `tests/test_saas_billing.py::test_billing_plan_catalog_seeded_from_prd` |
| Unenforced keys (`case_refresh_cadence`, `api_access_enabled`, `audit_export_enabled`, `sso_enabled`) omitted; `addon_api_access` hidden | Migration | Catalog test |
| Included AI credits granted every month inside annual and manual periods | `_included_credit_window` in `services/saas_billing.py` | `::test_annual_period_grants_included_credits_every_month` |
| Provider budget funded by plan (`provider_spend_monthly_minor`); explicit company policy still wins; plans without it keep Rs 1,000 | `services/provider_spend.py` | `::test_provider_budget_follows_the_plan` |
| Add-ons resolve against the subscription's own catalog version | `resolve_entitlements` | `::test_add_ons_resolve_against_the_subscription_catalog_version` |
| Web sign-up starts the 14-day trial (`POST /api/billing/trials`, now rate-limited and issuing session cookies) | `apps/web/app/sign-in/NewWorkspaceForm.tsx`, `apps/web/lib/api/auth.ts`, `api/routes/billing.py` | `NewWorkspaceForm.test.tsx`; `::test_trial_signup_issues_session_and_trial_limits` |
| Ended trial blocks new matters, users, tracked cases, manual refreshes, AI work, uploads and paid provider calls; reads stay available | `trial_has_ended` gates in `services/saas_billing.py` | `::test_ended_trial_is_read_only_for_new_work` |
| Pricing page: per-user and annual-saving lines, no cadence row, included modules, plan terms, trial link, buyer copy | `apps/web/app/pricing/PricingPageClient.tsx`, `apps/web/components/marketing/Pricing.tsx` | `apps/web/app/pricing/page.test.tsx` |

## 9. Remaining gaps (not changed here)

- `POST /api/bootstrap/company` still creates a workspace that later becomes unlimited
  `grandfathered_free`. The web sign-up no longer uses it, but the API remains callable.
- Plan gates fail open for a company with no subscription row, and ignore suspended or
  cancelled status.
- Employee creation and user reactivation bypass the user limit; intake promotion and matter
  reopen bypass the matter limit.
- Drafting calls use purpose `draft`, so the 2-credit minimum keyed to `draft_generation`
  never applies.
- Included-credit expiry subtracts from the pooled balance and can consume purchased top-ups.
- Coupons and overage policies are stored but never applied.
- Every `billing_limit.*` denial audit row (including the new `trial_ended_blocked`) is
  written uncommitted and is rolled back with the refused request, so denials are not durable.
- No contracted eCourtsIndia rate is recorded; the code's Rs 1.65 ceiling drives Section 5.
- The OpenAI model pages for `gpt-5.1` and `gpt-5-mini` are marked deprecated; the cost basis
  must be rechecked when production models change.
- Online payment (Pine Labs Plural) remains disabled in production; activation is assisted.
