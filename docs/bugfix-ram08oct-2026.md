# October 8 Calendar OAuth Workbook

## Scope And Verdict

Source: `C:/Users/mishr/Downloads/CaseOps_Bugs(ll).xlsx`, `Bug Sheet`, rows 2-3.
The populated inventory is two high-priority bugs, BUG-003 and BUG-004, with
two screenshots. There are no enhancement rows or specific reopened Matter
records in this workbook. The original workbook is unchanged. This report
does not reinterpret an audited Matter reopen as an automatic resurrection.

At candidate freeze, both bug verdicts remain **Inconclusive** until it passes
Docker and the same deployed browser journey. No production deployment of this
candidate has yet occurred. Release verdict for this change: **NO-GO** pending
the gates below. Historical programme gaps are not closed by this repair.

Mapping: J08 / M08 / MOD-TS-006, parent US-023, FT-043, NFT-001/007,
SEC-002 and SEC-LW-001/006. US-023 is not an OAuth-specific story. The Outlook
sibling also maps to US-LW-008 / FT-LW-010. Gmail/Drive are audited adjacent
connector paths, not extra workbook rows.

## Exact Production Baseline

- Canonical main and both public release endpoints:
  `82a6d9325a73fcdd9857c7f637892719555b4b02`.
- API revision: `caseops-api-00485-vzv`; web: `caseops-web-00462-xc2`.
- Production callback failures recur on that actual revision; this is not
  merely an undeployed local fix.
- Narrow read-only Cloud Logging evidence, project `perfect-period-305406`:
  request at `2026-10-07T16:37:48.741487Z`, trace
  `8d8f3a69b16c284e958633565ab9f055`; traceback at
  `2026-10-07T16:37:49.094802Z`. Google token exchange reached the userinfo
  request, which returned 401. `GoogleCalendarProvider.exchange_code` raised
  `CalendarProviderError`; `_complete_connection` did not handle it, producing
  the raw callback 500. Authorization codes, state and tokens are not retained
  in this report.
- Authenticated production Playwright baseline on the same SHA independently
  confirms only `calendar.events` in the start URL. Required identity scopes
  `openid` and `email` are absent. Evidence:
  `.tmp/calendar-oauth-20261008/production-baseline-scopes.json`.
- Earlier `.tmp/calendar-oauth-20261008/production-baseline.json` failed because
  the new APIRequestContext test omitted the browser CSRF header. That is
  incomplete harness evidence, not a product reproduction. The test now echoes
  the authenticated CSRF cookie; the server protection was not changed.

## Root Causes And Prior Mistakes

1. **Incomplete OAuth contract.** The requested scope did not authorize the
   identity lookup used by the callback. A successful token HTTP response was
   implicitly treated as a complete connection. The adapter must validate the
   full token plus stable account-identity contract.
2. **Failure after a durable commit.** Calendar/Outlook committed an exchange
   claim before transport but omitted failure cleanup. The subsequent 409 was
   a real claim, bounded to five minutes, not a permanent database lock. An old
   failure must clear only its own claim; an expired worker must not publish.
3. **Replay degraded healthy state.** A completed callback could start another
   single-use code exchange and mark a connected account erroneous. Completion
   and attempt identity must be persisted, with current access still checked.
4. **Unsafe adjacent finalization.** Gmail/Drive held transactions over external
   I/O and could overwrite a disconnect. All connector finalizers must respect
   fresh membership, capability, configuration and revocation state.
5. **Browser completion was absent.** All four callbacks returned JSON after a
   top-level browser navigation. JSON success is not the workbook's requested
   return to Calendar with a connection that survives reload.
6. **Coverage was attributed too broadly.** October 7 Gmail/Drive token-refresh
   tests exercised existing connections and mocked reconnect failures. Older
   Calendar browser tests covered missing configuration. Neither exercised the
   reported initial Google consent/callback handshake. Those green tests cannot
   support an end-to-end Calendar claim.
7. **Authority refresh was incomplete.** Independent candidate review found
   Calendar context reconstruction dropped the session issuance time and kept
   the original tenant object. Membership-only checks cannot prove that a
   revoked session or disabled tenant remains blocked after provider I/O. An
   unused consent tab predating disconnect also needs a revocation fence.
   These findings hold the release until deterministic PostgreSQL acceptance.
8. **Lock ordering needs cross-provider proof.** Gmail/Drive's new tenant lock
   and Calendar's existing membership-first locks can overlap. The repair must
   serialize authority changes without conflicting with ordinary tenant FK
   inserts; a same-provider race suite alone cannot establish this property.
   `workspace-oauth-20261008-lock-repro.xml` reproduces the Company FK audit
   conflict for both Gmail and Drive on PostgreSQL: two test failures, zero
   fixture errors. Explicit Matter-disposal and team-scoping lock overlaps
   also need coverage before release. PostgreSQL's
   [row-lock compatibility rules](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS)
   explain why a weaker row lock alone does not resolve opposing explicit
   acquisition orders.

The candidate now uses a shared OAuth-only, bounded NOWAIT acquisition boundary:
all locks are rolled back before backoff, staged writes are forbidden inside
that boundary, and provider exchanges are never retried. Ordinary assignment
lock defaults remain unchanged. Final PostgreSQL tests exercise successful
competing writes, preserved terminal state and revoked authority rather than
accepting a generic retry error.

Google documents the identity scope requirements in its
[OpenID Connect guide](https://developers.google.com/identity/openid-connect/openid-connect)
and the code-exchange contract in its
[web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server).
Add only the identity scopes the callback needs; do not weaken identity checks
or substitute an invented account when userinfo fails.

## Repair And Verification Ledger

- Backend agents: Calendar/Outlook scope, claim, replay and finalization
  regressions; Gmail/Drive adjacent concurrency and failure recovery.
- Browser routes: synchronous worker-thread callbacks, fixed server-owned
  return URLs, no-store/no-referrer redirects, typed bounded recovery messages,
  JSON compatibility and no arbitrary redirect or provider-error reflection.
- UI: recovery notice only. Success comes exclusively from freshly loaded
  persisted connection data, never an `oauth_result` query parameter.
- Focused parent checks before candidate freeze: browser/route helpers,
  disconnect thread boundary and OpenAPI, 52 passed; four frontend files,
  38 passed; Workspace scope/configuration,
  11 passed. The first configuration test run had one setup failure because
  the new fixture omitted consent flags; that report is retained separately.
  These focused results are not Docker or production acceptance.
- TypeScript web and E2E checks passed before the integrated candidate freeze.
- Full frontend inventory passed: **189 files / 1,124 tests**, zero failures or
  pending tests, retained in `.tmp/calendar-oauth-20261008/frontend-full.json`.
- Browser emulator round trips passed **10 tests**: all nine new dated cases
  plus the older unconfigured-Calendar case, with no skips. They include both
  widths, failure/retry, consumed replay, concurrent duplicate and declined
  consent followed by fresh success. Evidence:
  `test-results/oauth-20261008-evidence/local-6-denial.xml`. The later authority
  repair still requires a frozen Docker replay; these results are provisional.
- Final Calendar/Outlook inventory: **157 passed**, including **46 PostgreSQL
  races**, no skips; all setup/call/teardown identities reconciled in
  `%TEMP%/calendar-authority-nowait-final-20261008.jsonl` and its JUnit sibling.
- Final Gmail/Drive inventory: **133 passed**, including **36 PostgreSQL tests**,
  no skips; all 399 phases reconciled. Final and failed evidence retained under
  `.tmp/calendar-oauth-20261008/workspace-evidence/`. These inventories overlap
  earlier focused runs and must not be added to them as unique coverage.
- PR #523 review found a remaining Gmail/Drive completed-callback shortcut that
  returned success before the consumption ledger. Those earlier replay tests
  asserted the wrong outcome. Single-use callbacks must reject even an exact
  completed replay, while retaining the healthy connection and making zero
  additional provider calls. The revised service and browser contracts require
  the provider-specific consumed error and a safe consumed notice.
  Revised verification: **135 passed**, including **38 PostgreSQL tests**,
  zero failures/skips and all 405 phases reconciled in
  `.tmp/oauth-replay-523/final.jsonl` and its JUnit sibling. The two pre-fix
  failures remain in `repro.xml`. Browser helper/route coverage passed all
  **54 tests** in `.tmp/calendar-oauth-20261008/route-replay-review.xml`.
- The first frozen Docker invocation on `f6d26c9d` stopped before startup because
  the workstation selected Node 24 instead of the repository's Node 22.14.0.
  A checksum-verified portable official runtime resolved that setup issue. The
  pinned rerun passed image build, migrations and index-health checks, but was
  intentionally interrupted during PostgreSQL acceptance to address the PR
  replay finding. Both run directories and the incremental journal are retained;
  neither is complete release acceptance. A new frozen candidate must rerun it.
- Required pending: deterministic real-backend emulator Playwright, PostgreSQL
  interleavings, complete frozen Docker gate, exact-head CI, canonical-main
  release, post-release production acceptance and retained summary workbook.

## Live Consent Boundary

The CaseOps test credentials authorize the test-legal workspace, not access to
an arbitrary Google account. On October 8 the owner authorized
`sanjeev@orchestrum.in` for this connection. That account is signed in in the
visible browser; the actual Calendar consent and callback remain pending
deployment and are not inferred from the Google sign-in.
Local automated proof must use an isolated deterministic provider emulator;
production must never activate that emulator or fabricate a Google grant.
The opt-in production spec is `tests/e2e/ram-2026-10-08-prod.spec.ts`; its retained
account check remains explicitly unverified without that account and consent.
Existing provider no-paid markers, legal-source, lifecycle, privacy and ACL
fences remain mandatory throughout this task.
