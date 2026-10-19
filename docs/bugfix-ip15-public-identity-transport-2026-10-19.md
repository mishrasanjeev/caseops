# IP15 Public Identity Transport - 2026-10-19

**Test-source correction and focused proof only. Release NO-GO pending fresh
complete gates.** Scope is the existing IP15 acceptance journeys and adjacent
notice/patent verification, not a new feature or a legal-rule change.

## What We Missed

IP15's spec-level marker-only header option replaced the app configuration's
HTTP-loopback connection-closing policy. We had not checked the effective wire
headers. Its shared public identity reader also borrowed an authenticated
fixture, needlessly putting credentials in a failed public-read call log.
Passing hosted CI did not prove the complete Windows Docker journey.

Real Playwright experiments distinguish spec-option replacement from per-call
header merging. Page headers do not change an isolated API fixture. A new API
context removes inherited credentials but can reuse Playwright's module-global
HTTP socket pool. Neither a new context nor a close header promises a fresh
first socket. These distinctions belong in regressions, not assumptions.

## Failed Evidence Preserved

C8 `2cf1015d6a84d0bc6182250f28dfb028f947d1d4`, tree
`ce6fa24b8c285a51bc75957bdf57b0a1f72f2e06`, has green hosted CI39219644355.
Its complete local Docker02 nevertheless exited1:

- Native:3226 passed,9678 setup/call/teardown phases, zero skips.
- Desktop:601 executed,590 passed,1 error,10 explicit skips; zero retries and
  global errors. Four mobile cases were unstarted.
- Dated IP/Calendar inventory:50 executed,49 passed and the same one error.
- The 1281px controls case failed during its post-login public web identity
  read, before its application assertions. This is not an observed layout or
  legal-workflow failure.

The retained web state/logs show no OOM or restart indication, but RestartCount
and a packet/socket trace were not captured. Ordinary idle expiry did not
reproduce the reset. A controlled reused-socket fault pair proves a mechanism,
not that historical Next.js behaved that way. Historical cause: Inconclusive.

The complete failed packet is
`outputs/bugs-l-20261019/docker02-reconciliation-01/final-failed-01/FINAL-PROOF.json`,
SHA256 `7bb83d90e655453a3a0559ae12a53a84f74e2fe931e9fec9e449ba4b513c8eae`.
All2966 held source hashes were unchanged and owned resources closed. Raw
authenticated errors remain local evidence; public summaries omit their headers.

## Narrow Correction

`tests/e2e/support/public-release-identity.ts` replaces three duplicated readers
in IP15, notice and patent acceptance. It preserves the exact API/web endpoint
paths,200 status and expected SHA checks at the existing boundaries. Each
endpoint gets an empty credential/cookie context and the existing per-origin
loopback transport policy. A public Set-Cookie cannot cross to its peer.

Transport, status, JSON, identity and cleanup failures remain fatal. There is
one GET attempt, no redirect, no timeout increase and no mutation retry. Error
metadata names the endpoint kind and stage without raw response/header causes.
All five shared-workspace consumers resolve headers from their configured
baseURL; production HTTPS retains the no-paid marker without loopback headers.
No application/API/native test, migration, seed, entitlement, dependency,
provider, lifecycle or execution-script behavior is changed by this correction.

## Focused Verification

The retained RED is16 passed /1 failed VM assertion demonstrating public reads
through the old workspace context. Earlier failures are not overwritten.

The final parent-owned six-module replacement passed142/142: IP13 fixture14,
IP15 reviewer43, IP15 workspace17, diagnostics25, production inventory4 and
public identity39. Both combined E2E and web TypeScript checks passed after the
last Calendar consumer change. All2969 source files stayed unchanged during
these parent runs. The agent's narrower capture excluded six tracked output
files; it is not substituted for the parent's whole-source inventory.

An earlier six-file run had133 passes and four unexecuted inventory assertions;
its original setup exception was not retained. A separate same-source diagnostic
observed spawnSync ETIMEDOUT at the unchanged8-second bound. The parent reran
with normal inherited TEMP, without changing that bound, and all four assertions
passed. This does not retroactively diagnose the missing exception or prove a
cache cause.

Thirteen real Playwright wire regressions pass: effective option/per-call/page
headers, credential removal, cross-endpoint cookie isolation, shared-pool
behavior, wrong SHA/status/JSON/shape, redirects, reset rejection, disposal and
single-attempt harmless mutation behavior. These use an owned loopback emulator,
not the app. Standard discovery finds618 cases:614 desktop and4 mobile,
including all original605 semantic identities plus the13 new regressions.

Source-pinned proof is under
`outputs/bugs-l-20261019/public-release-identity-hardening-01/`,
`parent-final-transport-checks-01/` and `parent-full-six-units-01/`.

## Release Boundary

Fresh CI, full intended Docker browser acceptance, normal canonical-main merge
and exact-serving production replay remain pending. Earlier native success is
still C8 evidence. Any proposed source-equivalent native/browser composite must
prove actual runtime/image equality, preserve every non-native gate and disclose
its post-run environment qualification. It is never a canonical C9 PASS; any
unexplained relevant drift requires the full canonical gate. No release is
authorized by this document.

The last observed production API/web SHA is
`9cf76f2b420fcb38a9aaa4b87ac63270bb3c0535` at11:58UTC. Ram's historical
BUG-008 screenshot cause and the unidentified reopening report remain
Inconclusive. Reviewed calendar/rule/date prerequisites and user-deferred
external Google cleanup remain open; no legal records or consent are invented.
