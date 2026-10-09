# CaseOps SEO/AEO Daily Evidence

The daily heartbeat records changes, not manufactured activity. Use the exact
serving release for production findings. Search Console data may lag by days;
mark unavailable or processing fields rather than treating them as zero.
Do not count an indexing request, directory prospect, or owned link as organic
traffic, a backlink, or a conversion.

## 2026-10-09 IST - Existing PR #522 Sidecar

### Scope and source

- Updated the existing `codex/seo-daily-20261007` branch in its own initially
  clean worktree. Fetched canonical main
  `b1d3fb23a73bf16ee2000ddc230d422085ba45e4` and merged it as
  `713ceed711d430bde93990176b40dbd0d1b650ce`. The sole conflict was the
  AGENTS.md insertion; both sets of learnings are retained. The diff against
  main remains exactly the eight files already owned by PR #522. No parent
  worktree, other PR, provider policy or authentication control was modified.
- Scope remains `J19 / M21 / US-063 / FT-094..096 / NFT-023 / SEC-031`:
  remove only the public sign-in robots exclusion, retain its noindex/nofollow,
  set its own canonical, and preserve app/API exclusions and sitemap scope.
  Google's [noindex guidance](https://developers.google.com/search/docs/crawling-indexing/block-indexing)
  was rechecked: blocking crawling prevents Google from seeing the directive.
- No Search Console session/report was rechecked, indexing/sitemap request
  submitted, lead sent, authenticated production mutation or paid-provider
  call made. October 7 observations below remain dated history, not today's
  metrics. Issue #521 remains open until Google positively reports excluded
  noindex, even after the eventual deployment and live crawl-policy replay.

### Fresh local evidence

Evidence root in this sidecar worktree: `.tmp/seo-pr522-20261009-r1/`.
All paths are fresh; earlier failed and incomplete reports were not overwritten.

- `scripts/run-public-content-e2e.mjs` built the current source with Next
  16.3.8, including its TypeScript gate, then served that new production build
  on loopback port 3101. The owned server stopped after completion. The API
  build configuration pointed only to loopback; no production credentials or
  demo submission were involved. This is not a Docker acceptance claim.
- Complete public-content discovery and execution: **23 collected, 23 passed,
  zero failed/skipped/retries**, covering every canonical public page,
  robots/sign-in metadata, adjacent account/portal noindex, exact sitemap,
  FAQ/source claims, internal links, desktop and 360px accessibility/navigation.
  `public-content-inventory.json`, `public-content-results.json` and
  `public-content-results.xml` retain discovery, execution and native completion.
  The ignored config extends the release-owned public config only to place
  JSON/JUnit and browser output in this evidence directory; selection, headers,
  one worker, timeouts and zero retries are unchanged.
- Robots unit coverage: **1/1 passed**, 100% statements/lines/functions (zero
  conditional branches). Report `robots-results.json` and `robots-coverage/`.
- Complete adjacent unit files: `app/robots.test.ts`, `lib/site.test.ts`,
  `app/sign-in/SignInForm.test.tsx`, `app/sign-in/NewWorkspaceForm.test.tsx`,
  `app/portal/sign-in/page.test.tsx`: **five files, 20/20 passed**, zero skipped.
  `auth-public-adjacent-unit-results.json` retains each identity. The separate
  coverage run repeats the same robots identity; it is not a 21st unique case.
- `build-and-browser.log` retains the build, all browser outcomes and clean
  completion. The inherited Edge Runtime deprecation and React controlled-input
  unit warning are not represented as new failures or silently repaired here.
- E2E TypeScript validation also passed. The first evidence reconciliation
  correctly rejected a missing quiet-command log (Tee-Object had no output to
  write), not a test failure. The command reran with native exit-code/start/end
  retention in `e2e-typecheck-r2.json`; `reconciled-evidence.json` reconciles
  all ordered browser identities, exact unit-file coverage and artifact hashes.

### Release handoff and PR #520 review

- Local crawl correction is implemented, but the deployed bug verdict remains
  **Inconclusive** until exact-serving replay and Google's separate exclusion
  evidence. Main owns combined Docker certification, green updated-head CI,
  merge, guarded exact-SHA deployment and all 23 live read-only cases. No merge,
  cloud operation or deployment was initiated by this sidecar. The separate
  [#527 production acceptance failure](https://github.com/mishrasanjeev/caseops/issues/527)
  remains a release blocker, not an SEO success or a reason to weaken gates.
- Reviewed PR #520 exact head
  `62d5bdf6be731dd2aeddad25b388f8ce81160a08`. Its fresh authenticated
  `page.request.get` after reload avoids reading a Chromium-discarded navigation
  body and keeps the no-paid marker, sync response and durable timestamp checks.
  No new defect was identified in that narrow diff. Its historical green CI
  (33 successful checks/two explicit skips) and older live proof do not replace
  both complete Gmail/Drive journeys on the final serving revision. It verifies
  existing-connector sync, not new Google consent, and the retained non-null
  timestamp assertion alone does not prove a new consent round trip. PR #520
  was neither edited nor merged here.

## 2026-10-07 IST

### Release and public acceptance

- `origin/main`, API and web all resolve to
  `82a6d9325a73fcdd9857c7f637892719555b4b02`; serving revisions are
  `caseops-api-00485-vzv` and `caseops-web-00462-xc2`. Identity was rechecked
  after public acceptance. Unrelated worktrees and changes were preserved.
- The serving revision's complete non-mutating public-content inventory:
  **20 collected, 20 passed, zero skipped**, with JSON identities reconciled.
  Covers all seven canonical pages, distinct metadata/H1s, working internal
  links, visible FAQ/JSON-LD parity, sitemap and desktop/360px accessibility.
  The local checkout used for this replay differs only in an unrelated dated
  Workspace spec and AGENTS.md; the public spec, config and lockfile have no
  diff from the serving release.
- All seven public pages, robots and sitemap return 200. Sitemap contains
  exactly the seven canonical HTML URLs with no invented lastmod. The `www`
  `/guide?campaign=seo` probe returns 308 preserving path/query. Public HTTP
  responses set no cookies and contain no Google Analytics script URL; this
  is not a claim that dormant analytics code has been removed.
- Exact-release production verification
  [37577791974](https://github.com/mishrasanjeev/caseops/actions/runs/37577791974)
  completed successfully during this audit. No deployment, QA mutation,
  scheduler resume or lead submission was initiated by this daily audit.

### Search Console evidence

The owner-authorized browser remains accessible as `sanjeev@orchestrum.in`.
These are report observations, not real-time counts or growth claims.

| Report | Observed result |
| --- | --- |
| Web performance | Default 3-month filter; visible data only Oct 3-4; last updated 10 hours ago. 0 clicks, 10 impressions, 0% CTR, average position 5.5. |
| Query examples | `caseops`, `case ops`, `case ops ia`: 1 impression each; a Pine Labs/Mobikwik boolean query: 2. All zero clicks. Visible query totals do not equal the property total. |
| Pages | Home 6 impressions; solo 2; guide, law-firms and resource 1 each. These page-aggregated rows total 11 and must not be substituted for the property total of 10. |
| Devices | Desktop 6 impressions, mobile 4; all zero clicks. |
| Countries | India 4, US 2, Pakistan/Paraguay/Brazil/Mexico 1 each; all zero clicks. |
| Page indexing | Updated Oct 4: 8 indexed, 4 not indexed. Reasons: noindex 1, robots-blocked 1, crawled-not-indexed 2. Indexed does not mean eight approved public HTML pages. |
| Noindex example | `/portal/sign-in`, last crawled Jul 18. Expected authentication entry exclusion; the candidate's adjacent browser regression preserves it. |
| Robots-blocked example | `/app`, last crawled Aug 19. Expected app exclusion; do not remove its rule to improve the aggregate count. |
| Crawled-not-indexed examples | `/icon?988433409fad5a4b` and `/opengraph-image?6d291527fcf52b8d`; image endpoints, not missing buyer landing pages. |
| Indexed-but-blocked warning | `/sign-in`, last crawled Sep 22; first detected Oct 5. See #521 below. |
| Priority URL inspections | Home, resource, solo, law-firms and pricing each report URL on Google / page indexed. No indexing request repeated. |
| Resource details | Successful Googlebot smartphone crawl Oct 4, 4:59:13 PM (displayed time); crawl/index allowed; declared canonical and Google-selected URL agree. Its sitemap detail says temporary processing error despite the sitemap report below. Monitor, do not resubmit. |
| Sitemap | Success, 7 discovered pages, submitted Oct 4, last read Oct 5. Unchanged sitemap not resubmitted. |
| Core Web Vitals | Updated Oct 4; insufficient usage data for both mobile and desktop. No field-performance score claimed. |
| Manual actions / security | Both report no issues detected. |
| External links | Still processing. No verified independent backlink count. |

This tiny, partly branded sample does not establish qualified non-brand
discovery, demand, conversion, or a before/after ranking improvement.

### Findings and changes

- **Not fixed in production: #521**, public sign-in indexing.
  [Issue](https://github.com/mishrasanjeev/caseops/issues/521). Live HTML already
  has `noindex, nofollow`, but every robots group blocks `/sign-in`, preventing
  Google from seeing it. The sign-in page also inherits the homepage canonical.
  The new Playwright reproduction fails on this exact live robots conflict.
  This is not evidence of private tenant content in search.
- Candidate correction removes only the public sign-in exclusion, retains
  noindex/nofollow and app/API exclusions, and adds its own canonical.
  Structured robots unit test: **1/1 passed**. Fresh production build and
  widened public-content suite: **23 collected, 23 passed, zero skipped**.
  Adjacent account and portal entry pages remain noindex. The first local
  run was **22 passed / 1 failed** because the new test used `Email` instead
  of the rendered `Work email` label; it is retained as a test-authoring
  failure, not a product reproduction or a green run. Complete replacement
  inventory reran after correcting the locator.
- #513 remains open: homepage fire-and-forget SMTP acknowledgement is not
  durable lead admission; persona mailto CTAs bypass attribution. The owner
  already chose privacy-first server-side attribution on Oct 5, superseding
  the missing-decision wording in the historical entry below. Keep GA4 and
  client telemetry disabled, minimize fields, exclude sensitive URL/query
  data, bound retention, review the notice, and prove durable admission before
  claiming conversions. Dormant GA4 component/build configuration still exists.
- #515 remains open: the earlier H1 and quantified-savings corrections are
  now deployed, but broader persona/pilot terms and service promises still
  need evidence. No universal coverage, reply-time or commercial commitment
  has been validated by this technical audit.
- Current official research supports useful answer-first content and normal
  SEO fundamentals, not special AI schema or mass pages. A hearing-tracking
  guide remains an intent hypothesis: the official eCourts service supports
  CNR and alternate case searches, but that does not prove CaseOps coverage.
  No new thin pages, outreach, directory accounts, paid links or invented
  endorsements were created; existing listing prospects remain uncounted.

### Evidence and next action

- Local evidence root: `%LOCALAPPDATA%/Temp/caseops-seo-2026-10-07/`:
  `public-content-results.json` (20 live passes),
  `sign-in-before-results.json` (live failure), `sign-in-before/`, and
  `local-first-run-label-failure/` (preserved first local failure).
- Release candidate [draft PR #522](https://github.com/mishrasanjeev/caseops/pull/522)
  is not deployed. Complete review, green CI and required
  Docker/release gates before merging and guarded exact-SHA deployment; then
  replay all 23 tests live. Keep #521 open until Search Console separately
  proves noindex exclusion. Do not use Validate Fix as evidence of resolution.
  Next daily run should resume this candidate, then #513/#515, without
  launching a competing release or repeating unchanged sitemap submissions.
  The existing daily automation now names #521/#522 explicitly; its saved
  daily schedule and quiet-on-unchanged notification behavior were preserved.
- Sources: [Google noindex behavior](https://developers.google.com/search/docs/crawling-indexing/block-indexing),
  [Google AI features guidance](https://developers.google.com/search/docs/appearance/ai-features),
  [official eCourts search](https://services.ecourts.gov.in/ecourtindia_v6/).

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
