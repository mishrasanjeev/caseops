# Android native receipt-search latency — 2026-11-14

J20/M22, US-MOB-01/02/08, `QUEUE-01` / `PRIVACY-01`.
Implementation: **Partially implemented**. Bug verdict: **Inconclusive**.
Release verdict: **NO-GO** pending complete replacement native acceptance.

The source5b7c Android QP02 run passed both call bodies and the Queue teardown,
but its original registration window terminated the process during the final
Privacy teardown. Its journal contains five of six terminal phase results;
postflight and normal control closure were not reached. Neither call body is
credited as a completed QP suite. Android retains40/83 independently reconciled
cases and iOS42/83 at that source. Current-head native acceptance is separate.

The exact interrupted session was independently absent. All63 known sessions
on that Appium incarnation were independently404 absent before the owned server
was stopped. A separately captured normal logout succeeded. The expired owned
gateway then exited normally and restarted with controls explicitly disabled;
all other62 container identities, mounts and states were preserved. This is
late recovery, not a replacement teardown or postflight for the failed run.

An idle-wait hypothesis was rejected: the same complete negative guard took
8.24seconds at500ms versus10.43seconds with the existing scoped0ms helper.
No idle setting was changed by this repair. A different actual native probe
verified all five receipt facts with candidate viewport room equal to or less
than the original. Generic searching took11.457seconds and five swipes,
including three unnecessary upward swipes. Directed downward searching took
3.695seconds and one downward swipe. This diagnostic used the installed source5
APK, unchanged500ms idle setting, original find budgets and normal sign-out.
It adds zero native inventory cases and does not prove the full8minute gate.
Earlier instrumentation and geometry failures remain separately retained.

Only the receipt helper's Android reads now pass `scrollDirection: down`.
Both callers first reveal the received-state anchor above the facts; the real
component renders exactly the checked order. Generic task and cleanup searches
keep their existing direction rules, and iOS keeps its typed fact helper.
The original480000ms run,20000ms transition,160native-operation,49control,
read, gesture, single-POST, complete-negative-sweep and authorization guards
remain unchanged. No product, backend, dependency or release-policy change.

Two controller regressions first failed on the upward sweep. The complete
replacement Queue/Privacy module passes77/77 cases with zero skipped,
cancelled or todo cases. The new positive regression verifies both complete
below-fold receipts; the negative rejects a wrong final fact after one deletion
POST. An independent Python source contract binds the anchor and exact actual
component order. Full source gates, fresh binary/source bindings, complete
Android QP replacement and remaining native suites are still required.

Owned evidence root: `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V`.
Retained evidence:

- `qp-5b7c3fbe-android-02/queue-operator-claim-08e49718716410d7df822e5b/`
- `android5b7c3fbe-privacy-idle-diagnosis-01/timing-comparison.json`
- `android5b7c3fbe-receipt-direction-diagnosis-03/timing-comparison.json`
- `android5b7c3fbe-qp02-gateway-recovery-01/proof.json`
- `qp-receipt-direction-regression-red-01.tap`
- `qp-receipt-direction-regression-green-02.tap`

These local artifact names describe retained observations, not committed store
archives or public-release acceptance. No original failure was relabelled.
