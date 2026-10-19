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

## Docker Builder Omission And Correction

C9 `862b9cee31ff91c4a69083c79f0415c86137f81c`, tree
`b098993f4646fa7464f219996ea39267f7560340`, failed canonical Docker03
at the web build. The real static import in the new colocated unit required
`tests/e2e/support/public-release-identity.ts`, absent from the explicit builder
COPY and both Docker/cloud context allowlists. TS2307 caused the downstream
TS7006. Native/browser execution remained zero; collection of618 is not execution.

This was our missed integration boundary: host typechecks had the full checkout,
whereas the real builder deliberately admits a narrow closure. The correction
adds only that helper to the three existing build-input declarations. The
existing standard-discovered contract gains four cases covering the literal
import, cost-controls dependency and omitted COPY/context entries. It still
rejects broad test admission and runner copies; static imports and Next's
strict typecheck remain intact.

The retained RED has two failed calls and all six phases. On the corrected
dirty source,22 closure cases/66 phases, all142 units in the same six modules,
both TypeScript checks and `docker build --pull` completed successfully.
The existing audit found215 colocated test files and seven external inputs.
All2970 tracked raw-byte hashes stayed stable during the checks. The image used
the actual source fingerprint, not a final commit label; no app/container or
provider ran. Owned build/test processes, temporary roots and the tag closed.

Focused proof: `outputs/bugs-l-20261019/web-builder-closure-c10-01/RECONCILED.json`,
SHA256 `622c55ca80f9ec77e2206a38b269877688c46033de2e138ad044aea17e264ecc`.
Docker03 failed proof remains
`docker03-reconciliation-01/final-build-failed-01/FINAL-PROOF.json`, SHA256
`90b8e0e68a5a3e0d8aee79fa2d2b645a7e3a5b2148ca8e4a027d234c6c189c8a`.

## Leftover Imports And Review Failure

C10 `1610d3005042905ac03e97a48518c9b42c3a471d`, tree
`dae5b36cf2fa476b5f6ba4c211778abccfcfb89d`, still had three unused
`noPaidProviderHeaders` imports in the renewal-tracker, reminders and tracker
specs. The helper switch had removed their uses, not the imports. Fresh exact-ref
CodeQL alerts587-589 and native SARIF0/3/0 (Python/JS-TS/Actions) establish that
miss. The original13-file review failed to catch it. The later four-file
packaging review did not cover those consumers and never admitted a release.
A green analysis/check and an empty unscoped alert response were not clearance.

The correction removes only those three named imports. The real used import
in IP controls, all five localTransportHeaders fixtures, no-paid markers,
shared helper bodies, assertions and budgets remain unchanged. An independent
semantic compiler comparison covers all13 changed TS paths in the real E2E/web
programs; only these three unused diagnostics were introduced. Five unrelated
baseline diagnostics are retained explicitly; no compiler/detector rule is
suppressed. The corrected source passed all142 units/six modules, both
TypeScript checks,13 real wire cases and exact618 standard-discovery parity.
Discovery remains separate from application execution.

The C10 canonical Docker04 was stopped as known unreleasable after its raw
prefix was sealed. Three groups completed1211 cases/3633 phases. Group04 had
135 passed calls/406 phases and no completion;1879 identities had no executed
phase and one was partial. No failed native phase was observed. All618 browsers
were unstarted. The parent terminated only its identified native-driver tree;
the original PowerShell wrapper then ran canonical cleanup and exited1 naturally.
Its missing aggregate journal is that operator stop's consequence, not a new
product test failure. All2970 source hashes stayed unchanged and owned readers,
processes and project resources closed before edits. None of this is carried
to the corrected candidate.

Retained failed CodeQL handoff SHA256:
`89fb4548b421826be3a5899851ccc3de5324815a09a273119b88a2fcdb8a235e`.
Operator-superseded final04 proof SHA256:
`cff0714c0e308f12c0828285fc37ae326a02e073313303a3cf49f0ce32d3a014`.
Corrected focused proof:
`outputs/bugs-l-20261019/codeql-unused-headers-c11-focused-01/FINAL-RECEIPT.json`,
SHA256 `8f3e81b391be16bddbfbaf17c36e22a99b91ec199a89b60b7980a20c4bf1c2dd`.

## Browser Runner Platform Drift

C11's required app job118189765017 in CI39285487552 failed before any browser
case. The actual runner log identifies ubuntu-26.04/image20261012.163.1;
Chromium installation rejected `ubuntu26.04-x64`. The lock resolves all three
Playwright packages to1.60.0. Its real installed host detector selects that key,
but the [versioned Chromium registry](https://raw.githubusercontent.com/microsoft/playwright/v1.60.0/packages/playwright-core/src/server/registry/index.ts)
has Ubuntu24 targets and no Ubuntu26 target. Current documentation for a newer
SDK is not evidence for the locked version. No global migration cause beyond
the observed job image is asserted.

Our workflow used a floating runner. The correction pins exactly six browser
jobs to ubuntu-24.04: CI e2e; production shards, both shared-step follow-ups and
scheduled statutes; and release-playwright. All non-runner fields, caches,
dependencies, timeout/skip/no-paid/runtime guards and release-owned checkout
rules stay unchanged. Other runners are outside this defect's scope.

The first guard draft read only the three known workflow files. Parent and
independent review caught that future-file blind spot before commit. It now
parses all yml/yaml files. Real tmp_path new-yml/new-yaml controls fail with the
old loader and pass after correction, without writes to the source workflows.
Both complete affected/browser-contract modules passed92 cases/276 phases,
zero skips/errors. The original assertions and scheduled-step digest remain.
Retained focused receipt:
`outputs/bugs-l-20261019/browser-runner-os-c12-01/FINAL-RECEIPT.json`, SHA256
`a2ec9120655b619d1a4fb7bf7385c4bf7063b96ab8d87c2f99294a100fb2e52d`.

A real Ubuntu24.04.4 container with Node22.14.0 and exact locked SDK1.60.0
launched Chromium148, asserted static page content and closed it with network
none. The smoke preceded only the last test-helper delta; exact runner pins,
lock, SDK and smoke inputs are proven unchanged. This is an explicit input
qualification, not final-tree or product acceptance. Browser installation may
reuse the base image; no cold browser download is claimed. Owned resources
and processes closed.

The initial optional599-case Windows deployment audit was narrowed while its
extra simulations were running. Retained outcomes:302 passed, one existing
Windows setup skip, one interrupted and295 unexecuted;909 phases, no failed
phases. It is incomplete, never green. The two final full modules passed92;
the original five-file inventory plus two new controls (601) and entire API
still require fresh hosted acceptance. No source assertion or budget is waived.

Canonical Docker05 was also operator-superseded, with404 complete-group cases
and402 interrupted-group calls but no group02 completion;2420 identities had
no executed phase and all618 browsers were unstarted. No failed native phase
was observed. The native-driver stop caused the missing aggregate journal.
The wrapper ran canonical cleanup and exited1 naturally. All2970 source hashes
were unchanged; sourcehold release SHA256
`26e82e7e2ce9934d80ce3e5de1a213a7d713399dc6539b3b16565a97649339a5`
resolves the earlier final proof's pending parent-reap qualification.
There is no native carry or production acceptance from these runs.

## Release Boundary

Fresh CI, the full canonical Docker native/browser inventory, normal
canonical-main merge and exact-serving production replay remain pending.
Earlier native success is still C8 evidence. The attempted alternate refused
before Docker for mounted runtime membership/bytes; its historical cause is
unproven. It was permanently abandoned, supplied no accepted carry results and
will not be patched around. Run the unchanged full canonical06 replacement
and reconcile fresh current-ref CodeQL findings, not just workflow conclusions.
No release is authorized by this document.

The last observed production API/web SHA is
`9cf76f2b420fcb38a9aaa4b87ac63270bb3c0535` at11:58UTC. Ram's historical
BUG-008 screenshot cause and the unidentified reopening report remain
Inconclusive. Reviewed calendar/rule/date prerequisites and user-deferred
external Google cleanup remain open; no legal records or consent are invented.
