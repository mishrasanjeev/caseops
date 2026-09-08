# BUG-010 Production Follow-up

## Pre-deployment Checkpoint

This file records the first production failure and the follow-up's local
acceptance before publication. The follow-up PR and exact-release production
workflow provide the later deployed outcome; do not treat a local pass here as
a production certificate.

NO-GO for complete release certification. Canonical main
`2664ee296be13c91e7c4c5c06fd62514f2412c73` was deployed after complete local
Docker acceptance, green PR #458 CI, and green main CI. API revision
`caseops-api-00444-dv9` and web revision `caseops-web-00421-bjp` serve it.
Both build identities and health passed. Migration, exact-image statute seed,
index health, scheduled-job reconciliation and QA bootstrap succeeded.

Production workflow 34165047689 failed. Its complete log and failure artifacts
are retained under `C:/tmp/caseops-ram05sep-20260905/bug010-production-first-*`.
The statute source gate passed all 43 batches and all 1,689 records. The broad
batch had 115 passed, three failed and six skipped; cost had one pass; notices
had two passes. Patent/domain acceptance had seven passes and sixteen failures.
Skips and failures are not acceptance, and the final workbook is not published.

## Independent Findings

1. The April statute test still required BNS Section 318 to be unverified.
   The new pinned official release legitimately verifies it. Require exact
   source text, hash, version and redirect, and separately preserve the
   unverified IPC Section 420 negative boundary.
2. The July template test required 21 columns. The requested independent
   Temporary E-Case Number and CNR Number extend both templates to 23. Keep
   exact CSV/XLSX equality and replay the full import/persistence journey.
3. The August mobile navigation test omitted the new Patent intake destination.
   Keep the exact authorized inventory plus every visible/clickable 360px action.
4. Each of the sixteen patent failures independently stopped at POST
   `/api/clients`: the router returned a 307 pointing from the public HTTPS
   origin to HTTP after TLS termination. The redirected request reset before
   client creation. This is a real shared transport defect, not sixteen missing
   patent features and not a reason to retry mutations or inflate timeouts.

## Repair and Required Evidence

The shared HTTP fix rewrites only an exact same-origin API slash-correction
307 to a relative Location. It does not trust user-controlled forwarding
headers or alter publisher, signed-source, other status, or unrelated-path
redirects. Unit regressions cover five methods in both slash directions, query
encoding, body and synthetic bearer retention, source redirects, streaming,
and the unauthenticated boundary. The unchanged deployed behavior reproduced
eleven failing assertions with thirteen positive preservation checks in
network-disabled local Docker; all eleven structured failures were inspected.
The adjacent redirect/absolute-URL audit found the two source-action redirects,
which must retain their publisher destinations, and a payment route's request-
derived callback argument. The Plural adapter explicitly discards that argument
because webhook configuration belongs to the merchant dashboard; it is not an
active payload defect and no speculative payment change was made.

The follow-up must pass focused tests, full local API/coverage and PostgreSQL
acceptance, a freshly built Docker image and complete browser suite, the three
changed production-only journeys on that Docker stack, then PR/main CI and
exact-release production acceptance. Preserve all failed attempts. Verify the
supplied tester account separately and require clean maintenance after QA.

## Local Follow-up Checkpoint

The fresh application fingerprint is
`e055c7fc6851e1870398cb53ecc2115ead8cd40a`. Both index checks and the real
23-Act/4,336-section seed passed. Focused redirect acceptance passed 24 tests.
Four fresh PostgreSQL shards passed all 192 selected identities without skips;
their common source archive is
`f16d8c85933f8258e773f45f28ad7c852b4c8796b6bc37c7599afc08a6f3ea69`.
The production configuration passed two legacy/setup checks, eight dated checks,
23 patent/domain journeys and all 43 statute batches locally. The retained
496-row tester source created 391 Matters, rejected 97 invalid and eight duplicate
rows, preserved 10,416 source cells and verified 28 persisted fields per Matter.
The native offline reranker passed 15 checks, and the Windows-only CLI check
passed separately on this workstation. Neither is a paid-provider quality claim.

The first new frontend run had 966 passes and two failures. Each structured
failure was read: trigger-date discovery awaited the label, not its asynchronous
value; cold report discovery polled an accessible role before the query render
settled. The tests now await the required value or precise button text within
the original deadline, retain the exact date and payload checks, and additionally
assert the report button's accessible role, visibility and enabled state. All
11 tests in the two affected files pass; complete coverage is still required.
Only test files changed, not application UI code.

The second complete frontend run passed 967 of 968 with a different cold
readiness-to-list timeout in the first IP docket test. Its complete structured
failure shows the loading state; the mocks and QueryClient are fresh. That test
and the product remain unchanged. A measured one-worker full-coverage replay
uses the same deadlines and thresholds. Its first launcher attempt failed before
test execution because the Alpine tool image has `sh`, not `bash`; the stopped
container and error log are retained as infrastructure failure, never test proof.
The unchanged one-worker replay (`bug010-redirect-web-coverage-04.xml`) then
passed all 968 tests in all 168 files, zero skipped, in 572.84 seconds.
Coverage is 60.20% lines, 57.20% statements and 51.52% branches; every existing
threshold passes. Measured cgroup counters show zero throttled periods and no
memory-limit/OOM events; peak memory was 1,374,277,632 bytes under the 8 GiB cap.
The unchanged IP docket empty-state test completed in 318 ms. Resource contention
is a supported hypothesis for the earlier cold-load timeout, not uniquely proven
causation. No further locator or product change was made. All 638 frontend,
browser, typecheck and dependency snapshot files match current source, and all
five functional-QA launcher security tests pass in network-disabled Docker.

The first full-browser wrapper collected zero tests because native PowerShell
split a drive-letter output argument. That XML remains incomplete, not passed.
An explicit argument array preserves the path. The complete replay passed
275 of 280 selected tests with no failures or retries. The five skips reconcile
exactly to the payment-provider-only journey and four production-identity checks;
they are not local passes. The post-browser PostgreSQL index-health check is
clean at `20260907_0002`, with no foreign-key gaps, missing/invalid/mismatched
indexes or sequential-scan warnings. Fresh screenshots of the reported Act
detail views were inspected alongside the mobile/desktop assertions. At this
checkpoint the browser and frontend phases are complete.

## Complete Local Acceptance

The complete offline API run finished with 4,198 passed, zero failures and 194
skipped in 6,097.02 seconds. Every skipped identity has exact passing evidence
from the 192 PostgreSQL tests, native reranker or Windows-only supplement.
API and all four PostgreSQL shards use the same source archive
`f16d8c85933f8258e773f45f28ad7c852b4c8796b6bc37c7599afc08a6f3ea69`.
All nine file, five package and two total coverage gates passed. Raw statements
are 75,053/84,059 (89.2861%) and branches 14,896/21,232 (70.1583%). The historical
gate labels the combined 85.4290% total as line coverage; no threshold changed.
The retained 2,390 warnings were inspected: dependency/status/datetime
deprecations and SQLite test-resource warnings are not a warning-free result.

Fresh frontend coverage passes all 968 tests and full browser acceptance passes
275 of 280, with the five exclusions above explicitly reconciled. Source checks
cover all 2,275 paths, 681 API image files and 638 frontend/browser/configuration
files. Only the documented test and evidence changes differ from the built
snapshot; no untested runtime change is carried forward. The original-data
replay, actual release seeds and post-browser index checks also pass.

Local acceptance permits preparing the follow-up commit. The actual committed-
diff contracts must still pass before pushing; PR/main CI, canonical deployment,
exact-release production suites, supplied-tester replay and two clean post-QA
maintenance cadences remain separate required release gates.

Mapping remains RAM05-STATUTES, J05/J07/M05, MOD-TS-017, US-046A-D,
F-TS-1..4/F-T095/IPLF-006, plus shared HTTP security and IPLF-080 intake.
The wider 23-Act catalog and 25 pending IP slices remain open. No patent GA,
legal currency/commencement certification, or retrieval-quality score is claimed.
