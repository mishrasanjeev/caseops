# Mobile development checkpoint — 28 October 2026

Android and iOS store release remain **NO-GO**. This checkpoint supersedes the
current-state description in the 27 October checkpoint; it does not replace
the earlier source-bound receipts or erase failed attempts.

## Implemented source and completed checks

- The native client includes the Matter work queue, counsel context,
  read-only draft/recommendation/hearing-pack views, camera and file capture,
  source navigation, device sessions and receipt-only account requests.
- The complete mobile replacement passes all 627 tests in 43 modules,
  TypeScript, the Expo dependency check and the full 750-case native harness
  inventory (748 passes and the two existing Windows-only skips). Its exact
  source is `d5bca860`; the one PDF VM fixture correction is integrated locally
  as `0052ec73`. The first replacement's 617 passes and ten failures remain
  retained; its downstream phases were unreached. Native execution is separate.
- Web OpenAPI generation, component-inclusive TypeScript, E2E TypeScript and
  all 2,025 Vitest cases in 252 files passed on `486142bd`. The later native
  fallback test change has its own focused pass and needs the final full replay.
- The integrated API common inventory passed all 187 cases on `d5f8aa98`.
  Two later whole 29-case PostgreSQL diagnostics each completed all 87 phases:
  25 calls passed, four plan cases failed, and every setup/teardown passed.
  Each retained all 1,840 actual plan observations. The original source has
  148 observations above the unchanged 400-work cap; a candidate rewrite still
  failed 142 observations and made some costs worse. That rewrite was reverted
  and retained independently. Temporary database namespaces were reconciled
  back to their originals. These diagnostics do not certify the complete
  runtime filesystem or native release. The full 77-case replacement remains
  required after the query repair.
- Earlier complete queue/counsel API acceptance passed 408 cases, including
  167 PostgreSQL cases. The historical migration journey also passed separately.
  These scoped results do not certify later source or every possible query plan.
- The dnspython 2.9.0 repair passed the complete affected 417-case Python
  inventory plus 13 subtests, fresh whole-lock and actual Mac installation
  audits. Linux shipping-image execution, runtime TLS and offline model checks
  remain separate requirements.
- The bounded evidence-reader replacement passed all 677 affected harness
  cases. The current integrated configuration module passes 71 cases with its
  two existing Windows-only skips. Neither result establishes Windows native
  execution or acceptance on an installed Android/iOS app.
- All affected hosted API failure modules and their caller/dependency closure
  now pass on `a35abaa3`: 601 common cases plus 13 subtests across 22 complete
  module collections. The independent inventory also records 68 PostgreSQL
  cases that were collected and deliberately not executed in that common gate.
  The three disjoint common runs are 97, 83 and 421 cases, with no failed or
  skipped selected case. Installed-file ownership remains strict; Linux CI and
  the image installation now request independent copies instead of cache
  hardlinks. Fresh actual Linux readback remains required.

## Recorded published candidate and failures

Draft [PR #558](https://github.com/mishrasanjeev/caseops/pull/558) was updated to
`a52e43caa57d1253271f581b347841e855112a29`, whose complete Git tree exactly
matches the locally tested `d5f8aa98` tree. Local commit history and the
publication reconciliation are retained independently.

All 54 hosted checks on that recorded candidate completed. Secret scanning
and the separate CodeQL alert verdict failed; successful CodeQL analysis jobs
do not override the failed alert verdict. The secret failure is an unreviewed
exact Git origin for a static public fixture discriminator, not a credential.
Only its independently reviewed exact origins were added to the existing
provenance registry. Fresh full tree/history scanning is still required.

Security corrections also cover descriptor-bound bounded reads, canonical
namespace reconciliation, fixed upstream sockets, ambiguous request headers,
response header validation, explicit minimum TLS versions, renderer message
origin/source checks and cleanup after constructor failure. Old failures remain
retained; fresh source-bound security verdicts must pass before release gates.

The published mobile-source check failed during its temporary fixture's Expo
plugin resolution, before its intended native negative controls. The fixture
now includes the actual pinned image-picker plugin. API shards 4/6/9/10 and
PostgreSQL shards 1/15/16 failed; shard 14 was cancelled after its pytest step
failed. Their exact case failures require reconciliation before a replacement
is called complete. Job names alone do not diagnose their causes.

## Native and distribution boundary

The retained installed binaries still use historical `8928c0db` source. Earlier
partial iOS file-picker/upload results and the failed Android browser-entry
attempt remain recorded. None certifies the new client or its dependencies.

Fresh independently identified Android and iOS binaries, matching backend and
CA receipts, and complete Appium inventories are required. Execute the full
core, Files, V1, queue/privacy and client-extension inventories on each platform.
Real-device accessibility, backup/privacy, push transport and verified public
domain associations retain their own evidence requirements. Emulator controls
must never be presented as physical-device acceptance.

Organization-first publication is selected for **ORCHESTRUM TECHNOLOGIES LLP**,
LLPIN **ADB-8004**. Its supplied principal office address is included in the
private corporate website preview; tax identifiers are excluded. The website
must remain private until the user requests public access. Developer-account
enrollment, production identifiers, signing and store-console access remain
external distribution dependencies. No store upload, production deployment or
PR merge has occurred.

Detailed immutable receipts under `/Users/sanjeevkumar/.cache/caseops-mobile/`
take precedence over aggregate counts in this document. Every replacement must
retain its original failures, reconcile complete intended/discovered identities
and setup/call/teardown phases, and bind the source and actual runtime artifacts.
