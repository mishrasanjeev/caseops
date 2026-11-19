# Registry identity write settlement — 19 November 2026

Verdict: **Partially fixed**. Existing J08/M08/MOD-TS-006, IP-platform
UJ-07 (Reconcile registry update), Batch4 BUG-012. Production remains NO-GO.

Main3b1f9953cf07c137b68ae52923b78b14041e6a9b is deployed. Full production
QA44519464549 finished failed:13 successful jobs, Batch4 failed, scheduled
statute and final evidence jobs skipped. Batch5 passed, including the retained
Contract/Draft journeys; that scoped result does not make the release green.
Projection maintenance remains paused. No maintenance execution or resume ran.

The Batch4 desktop registry journey failed at the Retire response assertion
(source line289; test declaration322). Its private error body was redacted.
Read-only API00528 request observations in the exact test window show POST409
followed by cleanup GET200/POST200. The earlier narrow empty log query is
retained and is not absence proof. The actual failed payload, response body
and persisted version/audit were not captured, so attribution of that exact
historical409 remains an inference. Cleanup success is not rollback proof.

A separate deterministic regression on the byte-identical production page
confirms the supported race: rejecting a diff increments the shared link
version; the empty diff query can render while the workspace containing that
new version remains pending. Retire is still enabled with the old version.
The successful reproduction has component compile0 and one intended native
failure. An earlier attempt stopped at an ambiguous responsive Reject locator;
that setup failure is retained separately and is not product reproduction.

All four link writers share the version: match decision, manual snapshot,
failure evidence and diff resolution. The candidate gives them one scoped
mutation key and admission/settlement fence, keeps the parent refresh pending
through its complete read set, and cancels obsolete reads before requesting
fresh data. An overlapping refresh cannot clear another refresh's pending
state. Current workspace fetching also blocks writes. Programmatic sibling
submissions check the actual pending mutation count. Failed workspace reads
retain the existing unavailable/retry surface.

A genuine409 is retained and causes only read-only current-state recovery;
no mutation is retried automatically. The backend expected-version checks,
audits, permissions and legal-state rules are unchanged. A confirmed write
whose refresh fails must not be described as rolled back. Plain status copy
explains the temporary pause without exposing internal IDs or cache details.

Current local verification: all18 original page cases plus six new cases pass
(24/24), with component compile0. Coverage includes both manual evidence
writers, failed-read recovery, genuine409 recovery without mutation replay,
initial-read cancellation and bounded observer delivery. The primary regression
proves cache success for version4 while notification is still pending, then
delivers it inside act. A real50ms timeout positive/negative control proves
cleanup restores the scheduler, drains the actual mutation and prevents late
terminal work; disabling that cleanup makes the canary fail as intended.

The complete original browser file passes all three cases: desktop, the local
application-less docket and phone. It holds the original post-rejection GET,
proves sibling writes unavailable, then checks expected_version4 on the single
explicit retirement and version5/retired after reload. Later deep-link, Madrid
and responsive assertions pass. Component/E2E compile and production build pass;
all4320 source hashes remain unchanged and both owned server ports are absent.
The first local browser attempt correctly refused a database outside its
candidate before any journey. The replacement uses a fresh candidate-owned
database without changing source or the ownership guard. That setup failure
remains retained. Complete current-source frontend, release and production
gates remained pending at that point. No production workflow is closed from
these local results.

The complete serial Windows replacement now passes all3248 cases/316 files,
with zero failures/skips/todo, both compile checks0 and all51 source-inventory
checks first. It retains all prior3226 identities plus16 Teams/diagnostic cases
and six Registry cases. Actual native ZIP/QR/accessibility journeys pass within
their unchanged5-second test/15-second child limits. The original launcher and
two workers are retained. The earlier concurrent run remains failed:3107 passes,
one failed native-worker check,15 setup-blocked cases and125 cases never started
after two worker-start failures. Its exact missing identities are retained.

The current local API rehearsal remains incomplete after its3000-second runner
limit. A separate process handle observed exit0, but there is no final JUnit;
exit0 alone does not certify the unexecuted remainder. All owned native readers
were verified closed before the serial frontend replacement. No process was
terminated manually and no deadline was widened. Fresh complete API CI on the
committed candidate must reconcile the1699 affected identities and native
setup/call/teardown phases across every shard, with actual platform complements,
before merge. The earlier clean1699-case rehearsal predates only Registry TS/docs
changes and remains scoped evidence. Full current CI/deployment/production QA
and the guarded projection resume remain pending.

External retained evidence: C:/Users/mishr/.codex/merge161001/
registry-settlement-baseline01-*, registry-settlement-baseline02-*,
registry-settlement-candidate01-*, registry-settlement-candidate03-*,
registry-timeout-isolation01-receipt.json,
registry-local-build-browser01-receipt.json,
registry-local-build-browser02-receipt.json,
team-frontend05-complete-verdict01.json,
team-frontend04-failure-verdict01.json,
team-affected-source03-final-disposition01.json, prod625-batch4-failure01/ and
prod625-44519464549-failed-native01/. The earlier complete frontend3242 and
expanded source1699 passes predate this registry repair and keep that scope.

Read-only adjacent audit also identified supported candidates in IP document
new-version/move controls and patent prosecution/proceedings shared sequence
reads. They remain **Inconclusive**, not confirmed production defects or fixed
items. Reproduce each separately before changing those unrelated surfaces.
Protected patent parties/priorities already block editing during their fetch,
cancel older reads and publish current sequence; preserve those patterns.
