# Native Queue cursor and restoration acceptance

J20/M22, US-MOB-07/08, QUEUE-01 and PRIVACY-01 remain **Partially
implemented; release NO-GO**. Bug verdict: **Inconclusive** until the complete
replacement native runs pass. No Google Play or App Store submission is claimed.

## Retained native attempt

Both actual b09f2523 builds completed: Android ARM64 APK, 205.87 seconds; iOS
Simulator app, 323.10 seconds. Android's installed APK was independently checked
against its build receipt, including all twenty ARM64 ELF libraries, 16 KiB
alignment, signature and permission projection. iOS passed strict ad-hoc
Simulator signature verification. These are QA artifacts, not distribution
signing or full native acceptance.

Fresh Android actors and fixtures completed their unchanged 34/22 and
74/53/1 HTTP/POST/PATCH inventories. Both account observations completed real
Firefox/MFA/PKCE, native principal/workspace verification, logout and session
deletion. The full two-case attempt then passed initial Queue sign-in setup,
failed its call and teardown, and suppressed Privacy after uncertain cleanup.
There are zero new complete native cases. The initial-consent failure from the
older 288b2504 run was not repeated at that setup boundary; deployed production
verification remains open.

Original evidence is retained outside Git at
`native-release-20261111-ZzEIol4V/qp-b09-android-01/`:

- `queue-operator-claim-7b942ad6174a76b75a6df668/qp-native-reports/2026-11-12T08-15-55-924Z-android-qp-07831e65/`
- `post-failed-run-status-01/gateway-after.json` and the original control journal.
- `post-failed-run-status-01/actual-serving-cursor-randomization-reproduction.json`.

The journal proves one acknowledged anchor change, exactly one native stale
Queue request returning409, completion of every started control, zero privacy
POSTs, no marker/route rejection or overflow, and durably closed authority.
The original exception detail and independently read expected cursor were not
retained, so do not relabel a source diagnosis as a captured original exception.
The original anchor restoration was not reached; retain that failed fixture.

## Reproduced test defects and candidate

The old assertion compared the native request cursor digest with the cursor
from an independent owner read. The serving b09f2523 API's actual cursor encoder
was exercised twice with the same synthetic scope, anchor and frozen clock.
Both cursors decoded identically but their ciphertext hashes differed. The
original equality assertion failed. This probe made no database write or network
request and retained neither token nor authentication material.

The candidate records only the delivered cursor and last-row identity digests
from successful, bounded native Queue responses. The scenario uses its existing
single control read to bind the selected first page, exact anchor, actual
continuation bytes and one subsequent409. It preserves scope, ordering, exact
request count, hidden stale rows and all restored-row assertions. Independent
owner cursor bytes no longer stand in for bytes delivered to the native app.
The protocol double now issues distinct cursor values on independent reads.

An acknowledged anchor change also receives one explicit restoration attempt
when the later body fails. The restoration lease is consumed before dispatch;
unknown change/restoration outcomes are never replayed. Body and restoration
failures have separate fixed journal events and retain both original errors.
The server's refusal to declare unrestored state clean remains unchanged.
Successful workflow operation inventories and all original time limits remain
unchanged.

## Verification and outstanding work

Original focused cursor/restoration regressions failed before implementation;
the original journal module had one failure and two errors for its new response
evidence cases. Candidate module runs pass49/49 Node cases and28/28 Python cases.
Malformed/foreign/oversized responses, wrong scope/anchor/cursor, duplicate or
wrong-status continuations, unknown mutations and failed cleanup remain negative
guards. Initial candidate failures from stale protocol doubles are retained
separately; their upstream responses now follow the actual Queue DTO.

The complete frozen mobile source gate, new native binaries/backend binding,
both complete Queue/Privacy native runs, V1 and client-extension acceptance,
distribution signing, reviewer readiness and store submission remain open.
Historical a82ded25 Core23/Files17 evidence remains separate from this attempt.
