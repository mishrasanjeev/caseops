# Native Queue input diagnosis — 2026-11-12

J20/M22 and US-MOB-01 through US-MOB-08 remain **Partially implemented**.
Release: **NO-GO**. Overall bug verdict: **Inconclusive** until the complete
replacement native run passes. Neither store is submitted or published.

## Actual frozen candidate and complete case attribution

Source f4942cfd5e8420c1326e427a58e6c61bdb35c70e passed the complete20-command
source gate:686 mobile cases, TypeScript,1697 harness passes with two unchanged
platform skips, and420 Python cases in all17 requested modules. Android compiled
in217.752 seconds and iOS Simulator in338.154 seconds. Android APK SHA-256 is
28a600b7507712ea53136c98db62bcb92c2f1fefe47ee92607ca66a013d32ca5; all20
ARM64 libraries and ZIP alignment, signature and permission projections passed.
The iOS Simulator bundle tree is
4ce89796113acf1e0a64fffcf02fc25ac3e7f2251c92e7257dc7a4ae4474d2eb.
These are QA artifacts, not a signed store AAB or distribution IPA.

The actual Android report at
`qp-f494-android-01/queue-operator-claim-1649753f2d081859488bab44/qp-native-reports/2026-11-12T13-03-17-973Z-android-qp-4ca03dc1/`
retains a failed Queue call and passing Privacy call. All six phases executed,
both native sessions were paired and deleted, and postflight passed with zero
marker/route rejections and no evidence overflow. Privacy made exactly one
received202 deletion-request POST and exercised its unchanged acknowledgement
loss, explicit reload, isolation and noncompletion assertions. Independent
`f494-android-privacy01-reconciliation.json` credits exactly that one case.
It does not complete account deletion or make the whole suite pass.

The original journal's final collection metadata incorrectly said not-run,
while its actual preflight, native sessions and summary prove execution. The
original bytes are preserved and that discrepancy is explicit in the independent
reconciliation. The candidate writes the observed execution mode in the final
journal event as it already does in the summary; no phase or result is changed.

## Measured task input boundary

Queue traversed the complete first25-row page and second two-row page. Its
ordinary protocol click on the second task did not produce the detail read or
visible detail. The candidate that restored500ms implicit idle before actions
also failed at the same boundary. Its failed collector and successful native
session deletion are retained; it is not accepted as the repair.

A separate read-only native inspection found the exact target button enabled,
clickable and fully inside the window: frame53,1709,975,396 inside1080 by2424.
A subsequent independently owned navigation diagnostic used one
`mobile: clickGesture` as its only task action. It opened the exact task ID and
title and caused exactly one acknowledged200 queue read. No fallback, blind
second click or mutation replay occurred. Normal exact-member logout and
signed-out state were then verified separately. Each session was deleted.

UiAutomator2 documents clickGesture as a workaround for native tap failures at
correct coordinates. The pinned8.7.3-caseops.1 driver's actual implementation
also maps that command to one gesture protocol dispatch. The primary source is
[Appium's Android gesture documentation](https://github.com/appium/appium-uiautomator2-driver/blob/master/docs/android-mobile-gestures.md).
This supports a transport-specific diagnosis for the measured task row. It does
not retrospectively capture the original407c missing denied route or certify
production behavior.

## Candidate and retained failures

Android task navigation now chooses the gesture as its primary input after
checking exact ID, package, native button class, enabled/clickable state and
complete window containment. iOS keeps its native click path. An unknown
acknowledgement propagates immediately; there is no alternate input or replay.
The original160-control,20-second transition/page and480-second suite bounds
remain unchanged, as do exact task detail, all nine filters, both pages,
stale409, anchor restoration, Matter identity and all negative guards.

Noncompact native row metadata remains scoped to the Queue call. Zero implicit
idle is narrowed further to the bounded read/scroll page walk and restored to
500ms before each subsequent task, pagination or segment action. Page idle and
response metadata have separate cleanup owners. A lost idle-restoration ACK
is never retried by the outer metadata cleanup; it prevents later native setup.
Both original body and cleanup errors remain retained. Diagnostics stay behind
the existing explicit QA flag. The idle-only failure above remains evidence
that this setting change alone did not repair task activation.

The complete protocol scenario now forbids legacy Android task clicks and
preserves all original assertions. The candidate68-case module passes, adding
three page-idle cleanup regressions and one lost-gesture-ACK regression. Earlier
candidate reports are retained: the initial setting RED, inactive-diagnostic
callback failure, and incomplete protocol-double settings migration. No failed
report is overwritten, deadline raised, permission assertion removed or source
inventory reduced.

Three test-only CodeQL findings are also addressed: an unused import is removed
and the two concurrency-test worker catches use ordinary Exception. The full43
control tests pass; exact journal content, both thread completions, closure and
all concurrency assertions remain. Fresh CodeQL analysis and alert verdict are
still required; no rule or alert is waived.

Retained task-local evidence under `native-release-20261111-ZzEIol4V/`:

- `frozen-source-f4942cfd/independent-count-reconciliation.json`.
- `apk-f494-independent-postflight/proof.json`, `iosf494-artifact-proof.json`.
- The original complete native report and Privacy reconciliation above.
- `qpf494-action-idle-original-red.tap`, `qpf494-page-idle-candidate-01.tap`
  through`-04.tap`, `qpf494-primary-gesture-candidate-01.tap` and`-02.tap`.
- `qpf494-page-idle-native-01/`: retained failed idle-only native attempt.
- `qpf494-current-ui-observation-01/`: collector setup failure with session
  deletion; `-02/` retains native frame/control metadata without raw XML.
- `qpf494-native-gesture-diagnostic-01/proof.json`: one positive gesture,
  exact detail and acknowledged read; its cleanup is separate and preserved.
- `qpf494-native-logout-after-gesture-01/`: normal exact-member logout.
- `qpf494-primary-gesture-native-01/`: fresh complete page/detail candidate
  replay: all25 first-page rows and footer in14.794 seconds, second page
  in1.571 seconds, exact task ID/title after one primary gesture, and normal
  logout, session deletion and settings restoration. The imported candidate
  bytes were independently reconciled unchanged. It has zero full-suite credit.

Fresh complete replacement acceptance, V1 seventeen, client extensions24,
physical camera/biometric qualifications, distribution signing and both store
submissions remain open. iOS has a current actual Simulator build and prepared
source-bound operators; no full iOS native suite pass is claimed.
