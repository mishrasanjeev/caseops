# PRD: Real cause-list scraper (per-court)

Status: **Deferred — needs PRD before any scraping code lands**
(2026-04-25, mishra.sanjeev@gmail.com).

## Why this is deferred, not built today

Per the user's bench-strategy memory
(`feedback_user_bias_in_recommendations.md` + the bench-strategy
PRD-gating rule), per-court scraping work needs explicit PRD scope
because each court site has its own anti-bot posture, HTML layout,
authentication model, and rate-limit policy. A speculative scraper
sprint would burn ~2 days on infrastructure with little to show if
the PRD turns out to want a different approach (e.g. Manupatra/SCC
Online API, e-courts integration, manual paste-in).

The 2026-04-25 reconnaissance probe (`/tmp/probe_hc.py`) caught:

| Court | URL probed | Result |
|---|---|---|
| Bombay HC | `bombayhighcourt.nic.in/judges/sitting_judges.php` | 403 — anti-bot UA filtering |
| Delhi HC sitting judges | `delhihighcourt.nic.in/web/CJ_Sitting_Judges` | 200 — scraped successfully (32 judges) |
| Delhi HC cause list | `delhihighcourt.nic.in/web/causelist` | unprobed; expected JS-heavy SPA |
| Karnataka HC | `karnatakajudiciary.kar.nic.in/...` | TLS/connection refused |
| Madras HC | `mhc.tn.gov.in/...` | TLS/connection refused |
| Telangana HC | `tshc.gov.in/Judges/...` | 400 — needs specific headers/cookies |
| Patna HC | `patnahighcourt.gov.in/Pages/JudgesList.aspx` | 200 but only 289 bytes (JS-heavy) |
| Supreme Court | `sci.gov.in/...` | scraped successfully (sitting judges + per-judge bios) |

**Cause-list scraping is materially harder than judge-list scraping.**
Causelists change daily, often need a date-picker JS interaction,
sometimes require captcha, and frequently are gated behind a
per-advocate login (Bar Council number + password). A naïve scrape
will get IP-banned within a week.

## What this PRD must define before code

1. **Source preference.** Build per-court scrapers? Subscribe to
   commercial feeds (Manupatra / SCC Online / IndianKanoon CauseList)?
   e-Courts JSON API where available? Combination?
2. **Frequency.** Real-time poll, daily batch, or on-demand per matter?
3. **Auth model.** Per-tenant user-supplied advocate creds (Bar Council
   login), or platform-level shared subscription, or both?
4. **Rate-limit + politeness contract.** Per source.
5. **Failure-mode UX.** When a court's scraper breaks (the most common
   case), how does the matter cockpit communicate that? Hard error,
   stale-data badge, manual override?
6. **Coverage scope.** Which courts in which order? PRD must list the
   first N to ship — every founder customer's court, not "all of India
   simultaneously".
7. **Cost ceiling.** Per-court infra (Selenium / Playwright workers,
   proxy rotation budget) is real. Need a $/month/court ceiling.
8. **Deduplication strategy.** When a single matter's cause-list entry
   shows up via 3 sources (Manupatra + own scraper + e-courts), how do
   we collapse?
9. **Audit trail.** Every cause-list update needs source attribution
   on the row (`source` + `source_reference` columns already exist;
   PRD needs to define what goes in them per source).

## What's ready when this PRD is approved

The downstream pipeline is already built:

- `MatterCauseListEntry` table with `bench_name` (free text) +
  `judges_json` (resolved by Slice B) columns.
- `services/bench_resolver.py` parses + resolves bench-name to Judge
  FK rows with the high-quality confidence floor.
- `caseops-resolve-cause-list-benches` Cloud Run Job re-runs nightly
  to keep `judges_json` fresh.
- `BenchSpecificAuthority` lookup in
  `services/bench_strategy_context.py` consumes the resolved bench
  for appeal-draft generation.
- Matter hearings page renders `resolved_bench` as clickable per-
  judge links.

A scraper that writes to `MatterCauseListEntry` (with `source` set
to its identifier) will light up the entire downstream chain
without further code changes.

## What's NOT in scope of this PRD

- Building a UI for users to paste cause-list data manually — that's
  a separate "manual entry" PRD (and probably lower priority than a
  real scraper).
- Building a Bar Council credential vault — depends on (3) above.

## Sign-off

| Reviewer | Date | Decision |
|---|---|---|
| (user) | _pending_ | _pending — write the PRD body above, then approve to unblock implementation_ |
