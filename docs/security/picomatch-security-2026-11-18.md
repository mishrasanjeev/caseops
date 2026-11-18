# PR624 matcher security repair

Status: **Partially implemented; Inconclusive; release NO-GO**.

PRD mapping: J01/M01, J14/M13; FT001–002 and NFT001. This is dependency and
verification hardening; no new product feature or legal accuracy claim.

The b28ad345 PR candidate is rejected by the current high-severity dependency
gate. GitHub reviewed GHSA-fc5q-39xc-vjpf on November17; picomatch through4.0.7
is affected and no patched upstream release is published. Its npm/mobile
failures are retained, and the remaining expensive CI run was superseded.
An earlier green candidate is not a waiver for this changed advisory data.
Primary sources: [advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)
and [npm workspace fix](https://github.com/npm/cli/pull/9671).

The private4.0.7-caseops.1 parser extends the existing unsafe repeated-extglob
literalization path to unescaped, unquoted glob stars outside character
classes and repeated literal alternatives such as ab|abab. Other runtime
files, public APIs and original MIT bytes remain unchanged. The existing
explicitly unsafe maxExtglobRecursion:false option remains restricted to
trusted patterns; this is not a guarantee for arbitrary hostile glob programs.

On both pinned Node22.23.4 and Node24.15.0, the original source enters matching
and exceeds the unchanged one-second budget on all four bounded negative
controls. The repaired same inputs finish naturally, as do retained35-repeat
and ordinary/escaped/quoted/class/nested compatibility cases. Each complete
native matcher/installed-consumer invocation passes6 tests. The original
Node24 35-repeat negative control completed inside the budget; that failure
and calibration remain retained. A stronger50-repeat sibling supplies the
negative control without increasing any deadline. A mistaken empty-string
oracle and an earlier unentered SDK-dependent setup also remain failed evidence.

The pinned npm rebundle replaces only the matcher source, its exact parent
range, the fdir exact private peer admission and official Arborist9.9.3 plus
reviewed manifest fields. Npm's own executable code is unchanged. An offline
real workspace-link regression exercises old INVALID versus new valid
override propagation. The first complete npm module retains56passes/one
failure/one POSIX-only skip: fdir's stable ranges exclude the private
prerelease. Its exact edge, not the matcher runtime, caused ELSPROBLEMS.
The peer fix keeps ^3 || ^4 and adds only4.0.7-caseops.1. The complete
replacement module passes57 cases with one declared POSIX-only skip on
Windows. The latest deterministic producer passes12 tests and
reproduces every current archive, payload, mode, provenance and original
licence byte. Source-only old archives are excluded from upload.

Fresh serial audits of the final root/mobile installed graphs and the
bundled-CLI inventory return zero vulnerabilities. Each complete actual
npm ls --all graph also exits0, including the corrected optional peer.
Two preceding parallel audit preparations exceeded the existing30-second
constructor budget; no scan entered, and these remain incomplete setup.
Serial orchestration retains the same constructor budget. Actual Linux
installed inventory and independent hosted Windows reconciliation remain due.
Audit silence on a private version alone is never source-remediation proof.

The final working-copy matcher/consumer checks pass6 cases on each pinned
Node runtime. Component, E2E and mobile TypeScript compilation pass. The
complete Windows build-configuration module passes100 cases. Its original
two parent-directory replacement tests failed because Windows rejected the
open-parent rename with EPERM. They now retain that native refusal and exact
unchanged inode proof, then independently exercise a controlled late-link
observation through the original guard assertions. Descriptor closure and
the source reader's zero-payload rejection remain required.

The first13-case upload gate retains two failures: a missing Docker parent
reset admitted neighboring matcher source files, and the negative inventory
omitted two source-only npm baseline canaries. Correcting the reset and exact
inventory gives a complete13-case native Docker/gcloud pass. The broader
source run retains833passes/four failures/five declared platform skips:
two old exact-closure expectations and two Node-notice equality checks.
The latter exposed a locale-dependent operator rewrite of three preexisting
catalogue objects. All12 existing objects are restored from exact UTF-8 Git
content; the two new objects remain. Every retained notice text now matches
its original bytes, and the complete9-case notice module passes. A complete
replacement source run on the committed candidate is still required.

An overbroad local host-suite attempt incorrectly used Node22; it is retained
as invalid runtime evidence, not a product or security verdict. The Node24
Windows attempt also enters POSIX/iOS-only fixtures (getuid, /bin/bash and
Unix modes) outside the declared Ubuntu source-job platform. It retains81
failures and does not certify native-host acceptance. Its exact failure
inventory and the separate126-case Python fixture report are retained.
Complete intended Linux source/SDK CI remains required; assertions, Unix
ownership checks and platform admission are not weakened to turn these
operator scope errors green. New matcher tests retain normal detailed native
reporting; the optional37-target compact observer and its approved bootstrap
bytes remain unchanged.

Canonical mobile deduplication also refreshes semver6.3.2/7.8.6,
encodeurl1.0.4/2.0.3, ws7.5.14/8.23.0 and expo-font58.0.12, removes duplicate
matcher/font copies and hoists unchanged fdir6.5.0. Exact before/after lock
objects and actual successful whole-tree health/audits are retained. Full
SDK tests and both source exports must prove this final graph. The root lock
changes only matcher admission; its Vite8.1.6 identity is preserved.

Current private matcher archive SHA256:
`d10a7367ca87ec9f477ecaa97385787ee272af5663520507d74a1eedbfb05662`.
Current npm archive SHA256:
`90fc1752d15fd1683f3b232bd23fc63024d4506b1150fe244cd0f0217bc75010`.
Native reports, old failed locks/installations and source-bound CI failures are
retained under the workstation's merge161001 evidence directory.

The b28 complete frontend run passes3200 tests/313 files with component
compilation; its earlier source pass is scoped because HEAD advanced during
execution. Neither certifies this changed security candidate. Final frozen
component/E2E compilation, full frontend/source and Docker gates,
current-head CI and separate code-scanning alert verdicts are pending.
The historical Admin navigation timeout remains unexplained; finite passing
diagnostics and the independent no-paid constructor fix do not establish its
cause. Preserve the failed full gate and complete replacement inventory.

Normal merge requires complete current-head checks. Complete combined-main CI
must precede canonical exact-SHA deployment. Full production QA must pass on
that serving release; only two later serial clean projection executions,
with second rebuild_count0, can admit the guarded scheduler resume. Production
has not been changed by this repair and projection remains paused. Native
Mac/device/store, owner OAuth and provider UAT acceptance are separate claims.

The broad mobile deduplication and first cold matcher fixture are superseded
by the [source-bound follow-up](dependency-release-followup-2026-11-18.md).
It preserves the original native SDK cohort, separates bounded trust startup
from the unchanged matching budget and proves the actual pruned-image licence
inventory. Preserve every earlier refusal and failed candidate separately.
