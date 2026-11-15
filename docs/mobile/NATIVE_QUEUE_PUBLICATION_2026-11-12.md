# Native Queue publication and pre-registration authentication

J20/M22, US-MOB-01 through US-MOB-08 remain **Partially implemented**.
Release verdict: **NO-GO**. Bug verdict: **Inconclusive** pending complete
replacement native and deployed verification. Neither store is submitted.

## Actual718e native evidence

Both actual718e QA builds passed: Android ARM64 APK (190.82 seconds) and iOS
Simulator app (326.23 seconds). Neither is a store distribution artifact.
Android PRIVACY-01 passed setup, call and teardown, with one native POST202,
its durable acknowledgement, reload/revisit, other-company absence and logout.
Independent source, installed binary, backend and full Appium phase
reconciliation credits exactly **one case at718e**, not a complete suite.
QUEUE-01 passed setup but failed awaiting detail after the second-page tap.
It did not change its anchor; its call failed. All paired sessions and
postflight completed. The registration had not expired.

Evidence outside Git under `native-release-20261111-ZzEIol4V/`:

- `718e-android-privacy01-reconciliation.json`: independent one-case result.
- `qp-718e-android-01/queue-operator-claim-705c188ecedfc9f6129d82d8/qp-native-reports/2026-11-12T10-13-07-790Z-android-qp-7d3851e8/`:
  unchanged complete original events, summary and public traffic.
- `qp718e-hittability-diagnostic-01/` and `-02/`: retained operator failures,
  with acknowledged cleanup and zero suite credit.
- `qp718e-hittability-diagnostic-03/`: the later row was fully contained in
  its scroll host and one click opened the exact detail. This does not
  reproduce clipping or establish the original lost tap's cause. No mutation
  or Privacy POST was replayed and no case credit is added.

## Independently reproduced controller defect

`queue-terminal-publication-regression-01/captured-callback-original-red.tap`
retains three failures against the committed718e controller. A terminal view
was published while its completed read still owned the busy lease. The final
cleanup then published again, invalidating callbacks captured from the first
ready/error view. The candidate releases that completed lease before terminal
publication. It preserves the lease of an immediately admitted successor read,
stale-view refusal, fresh authorization, disposal and private-page clearing.
The exact original native failure has no captured JavaScript trace, so this
reproduction is an independently established defect, not measured proof of
that original tap's root cause. A complete fresh native replay remains required.

## Authentication before the short control lease

The718e controller consumed144 seconds of the479-second control lease on
normal prerequisite observations before launching. The partial native run then
used318 seconds. No observed expiry failure or longer TTL is claimed.
The candidate permits normal pre-registration authentication only through a
hash-bound public transition. Original observations and their original Docker
receipt remain unchanged. Current fixtures bind the actual activated receipt.
The transition checks all seven exact containers and mounts, source/API/web
identities, origins, CA, Compose and fixture bytes, complete gateway ledgers,
exact actor observation references and the actual registration activation.
Only the gateway may be recreated and only five control-activation settings
may change. Neither the479-second lease,480-second suite budget, operation
limits nor fresh public admission before each private reader is relaxed.
The optional transition's absence retains strict original same-receipt
behavior. It cannot renew a lease, read credentials, sign in or change services.

## Candidate verification and remaining work

The complete Queue/Privacy Node module passes57 cases, including three
controller regressions, adversarial transition substitutions and complete
admission before credential reads. Historical686 mobile units and1685 harness
cases belong to718e, not this changed candidate. The complete replacement
source gate, new source-bound binaries and both platform native inventories
remain required. Historical a82ded25 Core23/Files17 acceptance stays separate.
V1, client-extension, camera/biometric, production association, distribution
signing, reviewer readiness, CI and store submission remain open.

## Retained complete source candidate failure

`frozen-source-6bf8c2ab/` completed all20 commands. The harness passed1690 of1692
cases with its two unchanged platform-specific skips; all17 Python modules
passed. Mobile units ran686 cases:685 passed and the stalled-private-body
fixture failed its consumed-chunk zeroing assertion. The fixture constructed
its Response inside a ten-millisecond request budget without first proving the
chunk was consumed. An unconsumed queued chunk is not owned by the transport.
The replacement fixture keeps the exact ten-millisecond deadline, controls
its timer and clock together, disables stream prefetch, and waits for the
second read before asserting consumed-byte erasure. It proves no cancellation
at nine milliseconds and cancellation at ten. Production transport, TLS,
permissions, byte caps, cancellation and all original assertions are unchanged.
The original failed report is preserved; a full replacement gate is required.
