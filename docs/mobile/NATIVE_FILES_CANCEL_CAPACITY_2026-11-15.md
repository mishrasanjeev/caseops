# Native Files cancellation and bounded evidence — 2026-11-15

J20/M22; US-MOB-02/03/04/08; FILES-02/05. Status: Partially implemented;
verification Inconclusive; release NO-GO. This successor starts at9d5c3124.
Earlier native results remain bound to that exact source and artifact.

## Actual retained results

The9d5c3124 Android local-QA emulator Core suite passed23 cases/all69 phases in
755.623 seconds under its unchanged1800-second budget. All28 known sessions
were absent and the complete Appium inventory empty. Independent receipt
`9d5c3124-android-core23-actual-independent-review-01.json`:
`0d84e940bdfa860fdb3281d4bc9488aa0440c0d2aa4019e2b4b681b9342e04a4`.

The subsequent Files17 run passed01/03/04, failed02/05 and left12 calls
unexecuted under the existing uncertain-upload guard. Five created sessions
had deletion acknowledgements; all34 known sessions were independently absent.
Complete privacy postflight found no owned private staging/fixture matches;
all35 public provider files retained their hashes and metadata. Provider bytes
were read only during postflight. Cleanup cannot upgrade the failed family.
Independent failed-family/cleanup receipt:
`9d5c3124-files17-failed-actual-and-cleanup-independent-review-01.json`,
`2aa728230f1d8f01099cf95cd21a0e1a99e7ec4db8b6f3cccaac0685c2325b40`.

FILES-02 acknowledged one Back but did not observe QA return. Failure capture
refused because QA was not foreground; it did not retain the actual foreground
package. The preceding observed normal system picker needed two acknowledged
Back commands from its owned folder. This supports a harness cancellation-depth
hypothesis, not a measured product defect.

FILES-05 acknowledged its one PDF upload at sequence495/status200 and full
source GET at sequence500/status200. The gateway retained500 rows and reported
overflow true, markerRejected=routeRejected=0. The helper then requires a206
range response, but that historical range status and HTTP duration were not
retained. Source `local-gateway.py` refuses requests at the500-row bound;
capacity is a source-supported mechanism, not a measured503 for that attempt.
The exact dated API/gateway log capture had zero bytes/rows. Empty logs do not
prove absence of requests. TXT/PDF mutations remain unreplayed.
Allowlisted projection:
`9d5c3124-files05-source-admission-retained-public-projection-01.json`,
`1dce95138f32ec1bb4d83d681d5a66b755fc9ac52cc427f72f7e743aaf7b3665`.
Empty-log reconciliation:
`9d5c3124-files05-owned-logs03-actual-independent-review-01.json`,
`2b1b8aaedfbf0a788beba2e30da3c208d3226697ad83f7b876288904ab1f912e`.
These artifacts remain in the owned local release evidence root; they are
not hosted production or physical-device evidence.

## Successor contract

Cancellation permits at most four single acknowledged Back commands only while
the exact admitted DocumentsUI package is observed. It stops at QA return,
foreign package, failed/lost acknowledgement or expiry. Additional observations
and commands share the original15000ms return window; action recording cannot
start a driver command after expiry. A retained wait callback cannot issue
later reads. Falsy/frozen failures preserve their identities. Noncancel paths,
no-selection/no-upload/privacy assertions and all17 stable IDs remain intact.
Focused source coverage passed36/36 (all27 old cases plus9 composed cancellation
regressions), including slow recording, lost acknowledgements and late/falsy
observations. It is separate from required native replay.

Both Android/iOS source-admission modules passed49 tests (all43 old method
bodies plus6 new cases), including206/503 responses, real constructor arguments,
transport exceptions, unchanged marker/TLS/auth/timeout and one-request closure.
These synthetic transport cases do not establish the historical range status.

Expensive picker/staging work stays in a separately retained setup phase. A
fresh final Files epoch precedes final authentication/control/export binding
through the reviewed same-backend phase contract; every current receipt and
principal is revalidated. Preserve the original full ledger/configuration and
failed source postflight; use new fixture names. Restore the historical
under100-row entry fence after validated baseline and before privacy/session
work. That fence refuses a populated Core prefix but is not a full-run capacity
guarantee: the historical completed run had prelaunch32/final469 (437 including
worker/preflight reads). Target a similarly fresh final baseline, preserve the
500-row hard bound, and retain actual completion or refusal honestly. Do not increase500, reset a
live ledger, replay an uncertain mutation or count setup as a test. Shared
Android/iOS source-admission diagnostics retain bounded fixed-label method,
route template, actual/expected status and monotonic duration, never private
bodies, identifiers, queries, credentials or inferred historical codes. TLS,
no-paid headers, response/range/no-store assertions and no-retry remain.

## Host SDK and unfinished release work

The external private host-tool repair passed two exact-original-schema compiler
runs, two identical repacks, the strict unsafe-predecessor negative control and
all17 strict compatibility checks. All264 regenerated AAPT classes preserve
7795 reviewed API members/372 used references; manifest, badging and unsigned
APK payloads agree. Private JAR:
`940b62a126aa3ec8c618710347ab65dca00a1b40b8c669d63839dfec46ee8a30`.
Independent composite receipt:
`final-host-sdk-composite-independent-review-01.json`,
`9c2af5f73b8cd86ad7ace224e0c3d1203c25ecfed6e336eb1c3be61e138b9b8d`.
This supersedes the historical host-tool HOLD only for the measured macOS
ARM64/JDK21 private compatibility tool. It is not an official Google release,
an app-vulnerability verdict or native/store acceptance.

Current selected Gradle/settings/included-plugin graph and advisory/notice
closure, final14 bindings, protected signing/build, complete83 native cases per
platform and physical/Play-generated installation remain required. New-source
freeze, full verification and actual replacement native runs are pending.
No release counter/signing-secret access has occurred. The older Android
1.0.0(3) remains in review; this successor is not submitted. Orchestrum Apple
enrollment/signing and genuine physical iOS qualification remain unfinished.
