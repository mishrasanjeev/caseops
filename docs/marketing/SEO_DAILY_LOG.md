# CaseOps SEO/AEO Daily Evidence

The daily heartbeat records changes, not manufactured activity. Use the exact
serving release for production findings. Search Console data may lag by days;
mark unavailable or processing fields rather than treating them as zero.
Do not count an indexing request, directory prospect, or owned link as organic
traffic, a backlink, or a conversion.

## 2026-10-05 IST

- Canonical source: `origin/main` `93f853267d7e67856b7826db9a3f15b81dc1c2ea`.
  Production API `caseops-api-00481-vz7` and web `caseops-web-00458-hq8`
  both serve `b15c25035249833194faac0f9bb1fc38c4a84a6b`; the one
  main-only commit is documentation.
- Search Console: owner-authorized `https://caseops.ai/` property. Sitemap
  `/sitemap.xml` is `Success`, last read 2026-10-04, seven discovered pages.
  Page-indexing aggregates, performance and external-links reports are still
  processing. Manual actions and security issues both report no issues.
- `/solo-lawyers`: URL Inspection now says `URL is on Google` and `Page is
  indexed`. Last successful Googlebot smartphone crawl was 2026-10-04
  19:41:36 (Search Console display); crawl and indexing allowed. The sitemap
  is listed, the user-declared canonical is `https://caseops.ai/solo-lawyers`,
  and Google selected the inspected URL. [Issue #512](https://github.com/mishrasanjeev/caseops/issues/512)
  closed on this evidence. This does not establish ranking or traffic.
- Production read-only `public-content.spec.ts` inventory at the serving web
  release: 14 collected, 14 passed. The candidate's new heading test failed
  on production because `/general-counsels` had zero H1s; source and browser
  inspection also found zero on `/solo-lawyers` and repeated H1s on
  `/law-firms`. The candidate's local production build and widened 20-test
  Playwright inventory passed after the semantic, contrast and copy
  corrections. Four legacy persona/guide tests also passed against `next
  start`. Their first local `next dev` run failed on the existing React/CSP
  development-only `eval()` diagnostic for all four routes; that incomplete
  run is not represented as passing.
- Qualified organic clicks, non-brand impressions, average position, external
  editorial backlinks, demo attribution and conversion rate: **unverified**.
  Search Console reports are processing; no approved GA4/first-party analytics
  measurement and consent decision are recorded. PageSpeed Insights returned
  HTTP 429, not a performance score.
- The homepage demo route returns 202 before its fire-and-forget SMTP
  notification completes and does not persist a lead, while the pricing path
  persists `BillingEnrollment`. [Issue #513](https://github.com/mishrasanjeev/caseops/issues/513)
  tracks durable, idempotent admission and privacy-reviewed attribution.
- Next action: review and merge the heading/copy candidate after CI, deploy
  through the guarded exact-SHA release path, rerun production Playwright,
  then use mature Search Console data and a privacy-reviewed conversion plan
  before optimizing for measured queries.
