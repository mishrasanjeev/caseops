# Disposable native run claims and retained failures

J20/M22, US-MOB-01 through US-MOB-08 remain **Partially implemented**.
Release verdict: **NO-GO**. Bug verdict: **Inconclusive** pending complete
replacement native acceptance. No signed store artifact, submission or
publication is claimed.

## Actual 9d395b33 attempt

Both actual QA builds passed: Android ARM64 APK (196.63 seconds) and iOS
Simulator app (317.34 seconds). Neither is a store distribution artifact.
The Android Queue/Privacy attempt executed both calls and both setup/teardown
pairs. Both calls failed; zero complete cases are credited. Queue failed with
`QP_EXACT_NATIVE_PAGE_IDENTITIES` before changing its anchor. Privacy displayed
the unconfirmed state, but its one native POST returned502 at the QA gateway
before a backend POST or a positive control receipt. Postflight failed with
`GATEWAY_EVIDENCE_OVERFLOW`; this is not an accepted ledger. The run finished
before registration expiry. No deadline or lease increase is justified.

Evidence outside Git, under `native-release-20261111-ZzEIol4V/`:

- `qp-9d-android-01/queue-operator-claim-61e8c79d9caea0189868f100/qp-native-reports/2026-11-12T09-11-01-356Z-android-qp-35dd6923/`:
  original events and summary, including all six phases and failed postflight.
- `qp9d-readonly-diagnostic-01/`: a refused diagnostic preflight; a marked
  identity read advanced the observed ledger. No driver session was created.
- `qp9d-readonly-diagnostic-02/`: preserved failed gateway status before/after,
  signed-in native filter observations, exact visible row checks, acknowledged
  logout and deleted session. The focused filter sequence passed on the
  unchanged9d build. It is diagnostic evidence, with zero native suite credit;
  it does not erase or explain the earlier full Queue failure.
- `qp9d-claim-regression-01/original-red.log` and
  `shared-factory-original-red.log`: failing regressions before implementation.

## Reproduced claim collision and candidate

The public gateway journal's native Privacy POST is sequence95/status502.
The old exclusive filename for `native:privacy-one-post` was already present
with creation/modification time05:55:43 UTC, before this09:15 native attempt.
The constructor regression reproduces `FileExistsError` with an unchanged
retained earlier claim. The original gateway did not retain its exception, so
the original exception itself is inferred from the reproduced path, not a
captured stack trace. The old observer then refused the unadmitted POST and
marked the ledger incomplete. No privacy mutation is replayed to diagnose it.

The candidate binds exclusive attempt filenames to the registered run plus
operation identity. Reconstructing a manager in that same run still refuses
the attempt. A different disposable run can execute its own attempt without
deleting or overwriting old claims. Owner recipe labels have the same collision
in adjacent profiles, so V1, Queue/Privacy and client-extension constructors
share the canonical writer. Claims use private exclusive files, bounded writes,
file/directory fsync and no cleanup after uncertain persistence. All four
executable pinned-base digest contracts are updated together.

Opt-in Queue viewport diagnostics record already-read row ranks and digests,
plus existing segment observations. They add no native reads, retries or
promises. Enable only with `CASEOPS_QA_NATIVE_QUEUE_DIAGNOSTICS=1` in the local
QA harness. Exact row order, overlap, complete membership, hidden unauthorized
rows, footer controls and all original budgets remain unchanged. The earlier
Queue failure remains unexplained until a complete replacement run supplies
the missing observations.

## Verification and open acceptance

Focused candidate modules pass43 base Python cases,29 Queue/Privacy Python
cases,21 client-extension Python cases and50 Queue/Privacy Node cases. The
complete frozen source gate, fresh source-bound Android/iOS binaries, complete
Queue/Privacy replacement, V1 and client-extension suites remain required.
Historical a82ded25 Core23/Files17 acceptance is kept separate. Distribution
signing, current CI completion, reviewer readiness and store submission remain
open. This document does not authorize credit for skipped or unexecuted cases.

The first complete frozen source run,7ae05efc, is retained at
`frozen-source-7ae05efc/`. Mobile units, TypeScript and all17 Python modules
passed. Six route-descriptor harness cases refused the old reviewed gateway
digest after its pinned base changed. Review confirmed that the gateway's only
change is its exact base-module digest. The separate reviewed gateway digest
in `prepare-gateway-routes.mjs` is updated to those actual bytes; runtime source
matching, immutable evidence, exact routes and64/65-event guards stay required.
The complete replacement source inventory must pass before another native build.
