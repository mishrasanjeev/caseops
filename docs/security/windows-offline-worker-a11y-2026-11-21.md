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
