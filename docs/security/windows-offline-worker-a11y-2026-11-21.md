# Windows offline native accessibility worker — 21 November 2026

Verdict: **Inconclusive**. The combined-main release is blocked. This is a
test-infrastructure investigation under the existing J14/M14/PRA-09 native
dependency proof; it does not reopen a passed row-specific product journey or
establish an application accessibility defect.

Main `6260a61cb747f0b087f0976112b6f21c651bb869` Windows job
`136777905480`, run `44881606622`, completed 3,249 tests in 316 files:
3,248 passed and one failed. The failing unit is
`apps/web/lib/e2e-external-journey-loading.test.ts`'s actual offline Playwright
worker. Type-checking completed first. The child retained its three selected
identities with no retry: ZIP passed in 62 ms, QR passed in 1,478 ms, and
accessibility timed out at its unchanged 5,000 ms budget.

The native stages show browser readiness in 179 ms, successful rendered QR
decoding, then entry into the accessibility test. They do not identify the
internal accessibility operation that exhausted its budget. The terminal
`page.evaluate` error after timeout is not proof that evaluation, renderer
creation, rule execution or final result collection caused the delay.

The exact installed `@axe-core/playwright` default analysis path runs partial
analysis and creates a separate blank page for `finishRun`. The Windows fixture
reuses one persistent offline page across QR and accessibility. Those source
facts are an investigation lead, not a reproduced root cause. No legacy mode,
mock, rule reduction, retry or longer deadline has been admitted.

Retained external evidence is in
`C:/Users/mishr/.codex/merge161001/main627-Windows-failure293*` and
`main627-native-worker294/`, with the artifact receipt
`main627-native-worker294-receipt.json`. The successful local Docker02 and
earlier Windows runs remain scoped positives; they do not erase this
source-identical later failure. No deployment or projection resume occurred.

Pending: attribute the native deadline to measured operations, establish a
deterministic regression, repair the underlying fixture interaction without
changing the 5 s startup/test, 15 s child or 20 s parent limits, and run complete
replacement coverage and CI before release. The shared Docker window has been
returned to AgenticOrg; further heavy work requires timing coordination.

One explicitly coordinated host-only diagnostic derived the unchanged three
child cases from the real unit, added `DEBUG=pw:api`, and completed once with
native exit 0 in 6.454 seconds. ZIP/QR/accessibility passed, with accessibility
590 ms. The native API timing includes the additional `browserContext.newPage`
and finish-page evaluations. This does not reproduce or repair the CI failure,
and is not a full Vitest replay. Its initial generator preparation failed
before any child case; both phases are retained in external diagnostic295/298
receipts. The short host slot was explicitly returned after actual closeout.

The candidate adds that same passive API timing to the native worker's retained
JSON. No loader, library, selected case, assertion, rule, page mode, worker count,
retry or deadline changes. CI diagnosis and a subsequent repair remain pending;
this observation change alone must not be merged as a timeout fix.

Follow-up source correlation: the retained stack's `dist/index.js:236:16`
maps to the first `await page.evaluate(this.script())` in the lock-selected
`@axe-core/playwright` 4.11.3 distribution. The later `finishRun` new-page
path therefore must not be called the observed failure's cause. This narrows
the awaited call site, but does not establish why it failed to complete within
the remaining test budget. The next native timing receipt must distinguish
time before injection from time spent waiting on injection. No dependency
upgrade is justified by this source correlation alone.

## Diagnostic closeout and candidate admission repair

The first PR629 diagnostic commit, `3f3feacf82959a8d7ea5b0ecc0862d99ab61b5ef`,
passes the complete hosted Windows run: 3,249 tests in 316 files. The actual
three-case child passes once, with ZIP 79 ms, QR 315 ms and accessibility
514 ms. Native timing records first source injection at 125 ms and the later
finish-page injection at 126 ms. The retained artifact and job log are in
external `pr629-native302*`. This successful diagnostic does not explain or
erase the original main failure.

The configuration still admits this nested browser worker alongside ordinary
coverage workers. The candidate now gives its complete eight-case file an
exclusive ordered project after the complete source-inventory project and
before all ordinary files. The normal two-worker limit remains unchanged.
Resource contention is a working diagnosis; no historical CPU profile has
been recovered. The measured defect addressed here is the lack of exclusive
admission for the bounded native phase, not a proven operating-system cause
for the earlier delayed injection.

`scripts/tests/frontend-phase-scheduling.test.mjs` uses the actual production
configuration and installed Vitest discovery/worker implementation with four
small synthetic files. It must retain the exact file union, reject the pooled
counterfactual's admission mapping, run every candidate case, and prove source
then native then ordinary execution from both visible markers and native
timestamps. It is a scheduling regression, not a simulated reproduction of
the original accessibility timeout. Windows and Linux CI run it separately
before complete coverage and retain its native evidence.

The real library regression also requires the exact three child identities,
one passed zero-retry attempt each and their original five-second limits.
All test bodies, accessibility rules, library loading, browser modes and
5 s startup/test, 15 s child and 20 s parent limits remain unchanged. Complete
Vitest remains 3,249 cases in 316 files; the separate scheduling regression
is one Node test executing four synthetic Vitest cases, not additional product
journeys. The new candidate has not yet been executed. Complete native file
discovery, compilation, replacement coverage with exact identities and phase
timings, affected source contracts and fresh CI remain pending. No release
or scheduler recovery is authorized by this document's provisional change.

## Complete local replacement and schema-import follow-up

The actual canonical host replacement `pr629-frontend311` completed all 316
files with 3,242 passed cases and seven unexecuted cases. It remains failed.
The isolated native-library file passed all eight cases; its three-case child
passed with accessibility at 670 ms. Component and browser compilation,
both migration preflights, the real scheduling regression and exact native
file discovery also passed. All 4,324 frozen source hashes remained unchanged.

The separate source-inventory setup failed at its original 15-second App
discovery constructor with `ETIMEDOUT`. Its seven dependent checks did not
execute. The whole failed report, original deadline and all identities are
retained; a passing native-library phase does not clear this failure.

After physical closeout, one source-derived diagnostic ran the same App
constructor once with `NODE_DEBUG=module`. It completed metadata discovery
in 13.48 seconds with exactly 792 cases. Its native module trace proves that
collection eagerly loaded 95 Zod modules through the domain catalogue and
platform-report schema imports. It does not provide per-module timings or
a historical CPU profile explaining the earlier deadline miss.

The candidate defers those real application modules to their actual journeys.
Domain assertions still use the same catalogue schema and label map. Report
renderer fixtures are still parsed by the same schemas, now at the start of
their mock-context setup. The separate owner-acceptance spec retains all
authorization, MFA and read-only guards. No parser is copied or replaced,
and fixture data, UI assertions, case titles and deadlines remain unchanged.

The App constructor now retains native module diagnostics and rejects an
actual Zod load during metadata discovery. Windows/POSIX negative controls
and an ordinary diagnostic-stderr positive control cover that boundary.
The existing native library proof gains a fourth real schema-validation case;
its original three cases and 5 s / 15 s / 20 s limits remain unchanged. Three
new source guards cover the affected schema consumers. Expected complete
Vitest inventory is now 3,256 cases in 316 files: source 55, native-library
11, and 3,190 ordinary cases. Browser metadata remains exactly 792 cases.
Compilation, actual cold metadata/no-Zod proof, full replacement coverage,
affected source contracts, CI, deployment and production replay are pending.

Fresh-host preparation `305` stopped at the existing 30-second npm security
preparation bound before installation. It is retained as incomplete. The
replacement reused the previously qualified physical host and exact Node
22.23.4 runtime with unchanged installed dependencies and lock semantics.
An erroneous checkout-line-ending transfer was caught before tests; every
unchanged file was restored to exact stored Git bytes, and the complete
intended full-index patch was independently reconciled in `310`. No Git
configuration, pinned document fingerprint or security deadline was changed.

The first schema-deferral candidate `54bab4a0` stopped in three CI web
compilation/build jobs: the heterogeneous parameter tuples contextually inferred the
default call-count argument as literal `2`, rejecting its default `1`
(`TS2322`). An explicit `number` annotation preserves both intended call
counts. The failed job log and required-check snapshot remain in external
`pr629-54bab-failure315*` and `pr629-54bab-required-state316.json`.
The separate Mobile source job failed its complete CI trust-command inventory:
the two new scheduling-proof commands made the total 210 rather than 208.
The repair independently fences those exact two commands, their job identities,
placement, trust environment and retained evidence, while preserving all 208
baseline commands and 20 setups. Expected negative-control error logs remain
successful controls, not additional failures. Replacement compilation, the
complete affected source suite and every later gate remain pending; no
execution deadline or existing safety assertion was weakened.

Source review also removed overlapping quantifiers from the diagnostic path
matcher. The guard now uses native load-line markers and linear separator
normalization. Existing Windows/POSIX and ordinary-stderr controls remain;
one additional 50,000-separator path regression measures the actual constructor
control within one second. No browser or constructor deadline is extended.
This latest source change still needs compilation and complete replacement
coverage; no security or performance repair is claimed from review alone.
