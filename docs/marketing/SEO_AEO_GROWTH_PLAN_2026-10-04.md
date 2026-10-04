# CaseOps Organic Discovery Plan

Date: 2026-10-04 IST. Owner: CaseOps. Scope: public `caseops.ai` pages only.

## Outcome and evidence bar

Grow qualified demo requests from Indian law firms, solo advocates and in-house
legal teams. "Highest traffic" is not a testable promise: search engines control
ranking, and broad untargeted traffic can be worse than a smaller qualified
pipeline. Report organic clicks, non-brand impressions, qualified demo requests,
and conversion rate against a real baseline, not an invented traffic forecast.

The product PRD owner is `J19 / M21 / US-063`. Functional gates are
`FT-094..096`; non-functional and security gates are `NFT-023 / SEC-031`.
Feature statements remain subordinate to current product and provider truth.

## Baseline audit

Before the 2026-10-04 release, direct public HTTP checks returned 200 for `/`, `/guide`,
`/pricing`, `/law-firms`, `/general-counsels`, `/solo-lawyers`, `/robots.txt`,
and `/sitemap.xml`. Public HTML pages had canonical links and `index, follow`.
The six marketing HTML pages were listed in the sitemap alongside `llms.txt`
and `llms-full.txt`, and every URL received the same build timestamp as
`lastmod`. That is not an honest per-page content-change signal. `www.caseops.ai`
served a duplicate 200 with a canonical to `caseops.ai`. That was a baseline
observation, not the post-release result.

`GET /sites` on the Search Console API returned 403 with the workstation's
`gcloud` token. This token is not the owner-authorized browser session used
below. The public HTML and Cloud Run web configuration did not show a GA4
measurement ID. Search Console is still processing the newly verified property,
so impressions, clicks, rankings, Core Web Vitals field data, and demo
attribution have **no verified baseline here**.
Do not infer them from `site:` queries or from synthetic Lighthouse scores.
Other products use the CaseOps name on separate domains. Branded copy and
profiles must consistently identify `caseops.ai` and Orchestrum Technologies
LLP; do not claim affiliation with those products.

## Keyword and page map

These are intent hypotheses, not volume or ranking claims. Reprioritize after
Search Console queries and customer interviews are available.

| Intent cluster | Primary public URL | Search intent | Status |
| --- | --- | --- | --- |
| CaseOps and brand variants | `/` | Brand/navigation | Live |
| Law firm software India; legal practice management software India | `/law-firms` | Buyer/comparison | Live metadata updated |
| Legal matter management India; case management checklist | `/resources/legal-matter-management-india` | Evaluation/education | Live and indexed |
| Solo lawyer practice management India | `/solo-lawyers` | Persona/buyer | Live metadata updated |
| Legal operations software India; in-house legal matter management | `/general-counsels` | Persona/buyer | Live metadata updated |
| CaseOps pricing; legal software pricing India | `/pricing` | Transactional | Live metadata updated |
| Hearing tracking software India; CNR tracking | Future source-aware guide | Workflow | Hold until evidence-rich page is ready |
| AI legal drafting India; citation-grounded drafting | Future workflow guide | Workflow | Hold until representative claims are rechecked |
| Legal billing software India; GST matter invoice | Future workflow guide | Workflow | Hold until current pricing and billing copy are reconciled |
| Outside counsel management India | `/general-counsels` | Buyer/workflow | Improve only with verified product proof |

One intent gets one strong canonical page. Do not create near-duplicate city,
court, Act, case-law, or keyword-swap pages. No keyword stuffing, unverified
"best" claims, invented customer logos, false case statistics, or legal advice.
Provider and statute limitations must stay visible.

## Executed and live

1. Added a practical buyer checklist with a direct definition, seven demo
   checks, official eCourts source link, provider caveats, and product links.
2. Kept only canonical public HTML in the sitemap and removed fabricated
   `lastmod`, `changefreq`, and priority signals.
3. Gave the existing buyer pages distinctive titles and descriptions, and
   linked the new resource in public navigation.
   Removed a broad `meta keywords` list that Google does not use, an unverified
   social handle, and an `AggregateOffer` that did not reflect a verified
   published price. Search intent belongs in useful visible content.
4. Added unit and browser checks for the resource, sitemap, mobile layout,
   links, and accessible content. The 14 public-content Playwright tests passed
   against production after deployment.
5. Added a first-party GitHub README link. The repository
   homepage is already live at `https://caseops.ai`, verified via GitHub's
   repository metadata. These are honest owned references, not a claim of
   third-party endorsements.
6. Merged PR #510. Production API and web serve the merged `main` commit
   `b15c25035249833194faac0f9bb1fc38c4a84a6b` with 100% latest-only
   traffic. CI on that main commit passed, including 450 Playwright tests
   collected, 435 passed and 15 known skips. Exact-release production
   verification [run 37198401099](https://github.com/mishrasanjeev/caseops/actions/runs/37198401099)
   passed with 294 browser tests collected, 280 passed and 14 known skips.
7. Verified the `https://caseops.ai/` Search Console URL-prefix property as
   `sanjeev@orchestrum.in` using the production HTML meta tag. Submitted
   `/sitemap.xml`, confirmed the homepage is indexed, and requested indexing
   for the new guide after a successful live crawl. Search Console subsequently
   reported the guide indexed, discovered via this sitemap, with its own
   canonical URL selected. A recrawl was requested for each already indexed
   `/law-firms` and `/pricing` page because Google's
   last recorded crawls predated the metadata changes. Search Console reports
   no manual actions or security issues. The submitted-sitemap report briefly
   said `Couldn't fetch`, then changed to `Success` with seven discovered pages
   after processing. Googlebot fetched `/sitemap.xml` from the new web
   revision with HTTP 200, Google's live inspection reported a successful
   fetch, and the XML parses as the same seven canonical URLs.
8. Post-release `www.caseops.ai` HTTP checks return 308 to the canonical host,
   preserving `/guide?campaign=seo`. This is observed behavior, not a claim
   that this PR changed the host routing.
9. After the production QA mutation window, private-projection maintenance
   executions `57d72` and `bcxds` were serial and clean across six tenants.
   The first rebuilt two projections; the second rebuilt none. The guarded
   scheduler resume passed against the exact API image and QA run, returning
   the five-minute cadence to `ENABLED`. The next natural scheduled execution,
   `f9zjf` at 12:40 UTC, also finished clean with zero rebuilds.

## Next 90 days

| Window | Work | Exit criterion |
| --- | --- | --- |
| Days 1-14 | Monitor page indexing and canonical reports in the verified Search Console URL-prefix property; establish GA4 or consent-reviewed first-party analytics and demo conversion events. Consider a separate DNS-verified domain property only with DNS-owner access. | Baseline export with date, query/page, clicks, impressions, CTR, position, conversions, and consent decision. |
| Days 15-30 | Interview 5-10 target buyers; publish a source-checked hearing-tracking guide only if provider coverage and caveats can be shown. | One original page with product evidence, official sources, internal links, and browser QA. |
| Days 31-60 | Publish one legal-billing workflow guide and one review-first drafting guide. Refresh the existing persona pages using observed buyer questions. | Unique intent per page, no unsupported claims, indexing checked. |
| Days 61-90 | Revise pages with impressions but weak CTR, improve pages with clicks but weak demo conversion, and produce an original downloadable checklist or anonymized workflow study if consent permits. | A before/after report using the same Search Console and conversion definitions. |

## AEO and source quality

Put a concise answer in visible HTML before product copy. Use semantic H1/H2
headings, descriptive links, exact limitations and an independently checkable
source where one exists. Article structured data may help a crawler understand
the page but does not guarantee an AI citation or rich result. `llms.txt` is a
supplementary discovery convention, not a ranking shortcut. Keep facts aligned
with the user guide and the same source-verification rules as the application.
Never expose tenant data or index `/app`, account, portal, or API routes.

## Earned links, not link schemes

Prioritize relevant, editorial links: a verified product profile in reputable
legal-tech directories, founder interviews about source-safe legal workflows,
bar-association or legal-operations education when invited, and genuine
integration-partner documentation where a partnership exists. Send a short,
personalized pitch about the checklist to editors who cover legal operations;
do not ask for anchor text or reciprocal links. Record each prospect, owner,
contact date, editorial response and live destination before counting a link.

Do not buy links, use private blog networks, automate forum posts, claim a
physical office for a business listing without evidence, or submit the product
to irrelevant directories. Label sponsorships appropriately. The public GitHub
README and repository homepage are the first owned references; they are not
presented as independent endorsements.

Vetted listing prospects, **not submitted or counted as backlinks**:

| Prospect | Why relevant | Missing action |
| --- | --- | --- |
| [Capterra vendor listing](https://www.capterra.com/vendors/) | Its India legal case-management category reaches active software buyers. | Owner creates/uses a vendor account, verifies product facts and any listing terms. |
| [G2 product listing](https://documentation.g2.com/help/docs/finding-or-listing-a-product-on-g2) | Legal software comparison and review discovery. | Owner-authorized vendor identity, product profile, and genuine customer review process. |
| [Product Hunt](https://help.producthunt.com/en/articles/479557-how-to-post-a-product) | Launch discovery among software evaluators. | A personal maker account, launch assets, and a dated launch decision; it is not a substitute for legal-buyer demand. |

Prioritize Capterra/G2 buyer relevance over raw link count. Record published
URLs only after the listings exist and their descriptions match current product
and provider reality.

## Dependencies and release gates

- The owner-authorized Search Console browser session is connected; the
  workstation `gcloud` token remains insufficient for the Search Console API.
  GA4 property/measurement ID and a privacy/consent decision are still missing.
  Do not activate browser telemetry merely to fill a dashboard.
- Search Console has accepted the submitted sitemap and discovered seven pages;
  the new guide is indexed. Recrawling the refreshed metadata remains
  asynchronous; indexing and crawl requests do not guarantee ranking.
- Run web typecheck/build, page tests, complete public-content Playwright
  inventory, and a production read-only replay on the exact serving SHA.
- The release is live and its exact-release production verification and
  projection-maintenance resume gates passed. Continue checking natural
  scheduled cadences and Search Console indexing; neither is replaced by a
  one-time release check.

References: [Google Search Essentials](https://developers.google.com/search/docs/essentials),
[sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap),
[supported meta tags](https://developers.google.com/search/docs/crawling-indexing/special-tags),
[link-spam policy](https://developers.google.com/search/docs/essentials/spam-policies).
