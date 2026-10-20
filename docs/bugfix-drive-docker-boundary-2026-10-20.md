# Drive Docker Verification Boundary - 2026-10-20

## C14 CodeQL Follow-Up

C14 `dd2756f2a831f5859912066eac5d6ae80f5629a1` was not deployed. CodeQL
analysis execution succeeded, but findings check118440204670 failed at03:36:12
UTC on a genuine exception-ordering defect: `InterruptedError` subclasses
`OSError`, making its later handler unreachable. The focused20-case process
suite had not tested that derived exception. Additional notes identify mixed
ctypes import styles and an unexplained expected no-descendant exception.

The narrow correction moves interruption handling before the broad error,
normalizes the two existing lazy imports, and documents the expected childless
cleanup case. Cancellation must still run mandatory owned cleanup, and ordinary
errors must retain their nonzero result. Add explicit old-source RED plus
replacement exception tests. No budget, scope, provider, runtime app or
dependency change is permitted. Full Docker08 never started on C14. Its hosted
suite is failed/incomplete, not cleared by successful sibling jobs. Retain the
actual detection/handoff timestamps rather than describing them as immediate.

The unchanged new three-case regression reproduces the C14 error: one failure
and two passes across9 phases, with completed cleanup but exit2 instead of130.
The correction passes the entire23-case Windows module (69 phases) and the same
23 cases in network-none Linux. All original20 case ASTs remain unchanged;
the existing strict CI artifact reader accepts the complete replacement.
The two complete browser files also pass37/37 again on the final harness in
`c15-real-http-preflight-01`, with unchanged executed inputs and owned cleanup.
These are scoped proofs only; fresh hosted CodeQL and the whole release remain
mandatory. No exception is suppressed or downgraded to clear the failed gate.

## Scope And Current Verdict

J04/M03/US-007..009/FT-011..015 and the existing release-quality gate are
affected. This is verification-harness work, not a new product capability.
Ram's combined PR547 remains release-pending. Do not equate hosted CI success
with local Docker or serving acceptance. The historical BUG008 screenshot and
unidentified reopened Matter remain Inconclusive. External Google cleanup and
genuine legal-source prerequisites remain open under their existing decisions.

## Retained Failure

C13 `97df69529f8bdfd523ba3e53a3b4fd61bb266c75` passed its hosted CI,
Security and fresh CodeQL reconciliation, but full local Docker07 failed:

- PostgreSQL: 3226 passed, 9678 successful setup/call/teardown phases, no skips.
- Desktop: 614 executed, 603 passed, one failed, ten explicit skips.
- Four mobile tests were not started. The overall browser gate did not pass.
- The Drive isolation browser case's nested `docker compose exec` hit its
  unchanged 60-second deadline while the first cold-entrypoint unittest was
  running. This is a timeout observation, not a diagnosed product defect.
- The failure occurred at 01:32 UTC but was detected after the shard finished
  at 02:20 UTC. Replacing contextual grep without consuming incremental case
  results left an avoidable 48-minute detection gap.

The canonical parent exited naturally with status1, was reaped, and completed
cleanup. All2972 raw files matched twice and owned resources/readers closed.
Sourcehold-release SHA256:
`062945c2072d826e1a016bc1ceae65afe579286e009444df6910b06985ee09f3`.
Earlier incomplete runs and failed artifacts remain retained, not overwritten.

A separate frozen-C13, network-disabled diagnostic subsequently passed the
original first unittest in29.621 seconds. Its thread dumps showed ordinary
imports, route construction and mapper warmup. It did not reproduce the timeout
and cannot establish its historical cause or replace the failed whole gate.

## Narrow Correction And Coverage Map

Do not raise the timeout, retry mutations, remove startup security work or
change application code, dependencies, scanner readiness or provider fences.

The existing first Drive browser case now checks the real, already-running
Docker API rather than importing a second 917-route application inside its
60-second subprocess. The original cold unit's assertions map as follows:

| Original assertion | Current real HTTP proof |
| --- | --- |
| Actual entrypoint/lifespan starts | Canonical Docker startup/readiness plus emulator health200 |
| POST/GET fixture routes bind | Actual invalid-JWT POST and GET both401 |
| No-paid dependency precedes transport | One explicitly loopback-only unmarked negative POST403 |
| Request annotation resolves to typed body | Real authenticated ordinary owner's short body422 |
| Non-fixture owner cannot seed | Real ordinary local owner, valid body403; no dependency overrides |
| Valid fixture works through public workflow | Existing desktop/mobile Drive import, reload and byte-identical download journeys |

The six pure fixture security units remain separately enumerated: production
activation refusal, bounded inventory, no OAuth/browse transport, cross-fixture
token rejection, exact registered bytes, and captured version/size/deadline.
Their inner supervisor owns one child process tree, starts its deadline before
child setup, reserves at most6 seconds for cleanup inside its50-second budget, and must
prove collection, unit completion and process-tree reap. The existing outer
60-second deadline remains unchanged. There is no retry or network fallback.
Linux process-group/subreaper and Windows job-object cleanup are explicitly
regressed. Standard API discovery must include the new supervisor tests.

Browser evidence retains the reviewed unittest stderr separately from bounded,
sanitized supervision metadata. Success requires the exact ordered six-unit
inventory, source hash, zero failures/errors/skips and completed owned cleanup.
Missing, malformed, oversized, failed or partial evidence cannot become green.

The Docker wrapper reuses the existing native Playwright reporter's fsynced
per-case progress journal alongside its original JSON/list reports. Source and
invocation identity must agree before an observer classifies a case. Original
attachments and failed streams remain retained. Expected negative-control tests
are not failures merely because their title or error context contains a word.

## Acceptance Still Required

The reporting correction's complete focused inventory passed240 cases/720
phases, no skips. The supervisor's final Windows module passed20 cases/60
phases; a fresh network-none Linux replay passed the same20 final-source cases.
Its initial unittest-subtest form emitted75 phases for20 IDs and was
correctly rejected by the unchanged actual CI reader; ordinary loops retain
all6 source-path and9 budget controls plus explicit completion counts. The
replacement is accepted by that same unmodified reader. Neither focused proof
is a full Docker, current hosted CI or serving acceptance claim.

Both complete changed browser files passed37/37 with no skips/retries in an
isolated fresh PostgreSQL Docker stack: all five Drive cases and all32 receipt/
transport cases, including1280px/393px import, reload, exact bytes and revoked
consent. All nine executed test inputs stayed byte-identical and owned resources
closed. This is current test-source proof on the unchanged C13 API runtime plus
a fresh web build, not whole-candidate acceptance. Its earlier setup attempt
retains31P/6F: healthy internal containers had host-side ECONNREFUSED before
every HTTP body. The corrected preflight uses the canonical default bridge,
keeps the worker network internal and checks host-side readiness before tests.
No product assertion, timeout, retry or provider boundary was changed for that
environment correction. Evidence is retained under the parent output's
`c14-real-http-preflight-01` and `c14-real-http-preflight-02` directories.

Final peer review found two additional evidence-reader defects: cleanup records
were not bound to the child's PID, and native JSON parse errors could echo raw
output. Both are corrected with missing/wrong-PID and exact sanitized-error
controls. The complete final-source replay again passed37/37 in
`c14-real-http-preflight-03`; source hashes matched and cleanup completed.
Standard discovery is621 unique browser identities across141 files, including
all617 desktop and4 mobile cases. Extra unused-symbol checks found no introduced
diagnostics; five unchanged historical diagnostics remain explicitly recorded.

Focused tests do not close the full release. Freeze a clean replacement commit,
reconcile its complete required CI/security/code-scanning inventories, run fresh
canonical local Docker from build through PostgreSQL and all browser projects,
then merge normally to current main. No native-result carry or composite gate.
Require main gates, guarded exact-SHA deployment, the same serving journeys,
quiescent private-projection cadence and actual three-workbook publication.
Never upgrade pending legal, external-consent or unknown-history rows to pass.
