# iOS Files offscreen measurement — November 13, 2026

J20/M22; US-MOB-01..08; FILES-01..17, particularly FILES-11.
Implementation: **Partially implemented**. Bug verdict: **Inconclusive**.
Release verdict: **NO-GO** for complete native acceptance.

## Original complete attempt

Actual source `9d79b1ab8f38477a21bba4beff3f11b95d8b57d1`, Simulator app
`82c37c1b2ae8d73790fc94305aae96d018cc4199e801851033c8208688b7fd6f`,
matching isolated API/web, iPhone17 / iOS27.0.
Core23 passed all69 phases. Files17 executed all17 calls:16 passed and
FILES-11 failed (50/51 phases passed). All17 sessions closed and all traffic,
source/binary and provider/cache postflights passed. This is39 unique passing
cases of83, not full acceptance. The original report and failed native XML are
retained under the private evidence root below. Unsupported DOCX Open was
observed disabled; failure occurred while locating its unavailable-reader text.
No measured network root cause is asserted for that original failure.

## Separate diagnostic and repair

The original helper's passive second diagnostic measured a complete offscreen
frame, then repeated its native reads until the unchanged1500ms deadline.
A read still in flight overlapped the next keyboard query. The first timing
candidate had ambiguous event correlation and remains separately retained;
the second uses per-request Headers object identity and fixed operation labels,
without modifying native methods, wrapping command promises or logging secrets.

The helper now finishes a valid offscreen measurement before one bounded drag,
and only returns a control after exact ID/type, unique visible viewport,
geometry, containment and native visibility checks. Visibility waits remain
1500ms /150ms, gestures650ms, maximum9 drags. Expired measurements cannot initiate
a drag. Structural refusals are retained instead of being replaced by the
poller's generic timeout. The typed native visible-viewport predicate removes
one redundant visibility RPC while preserving ambiguity refusal.

The four-case new regression module failed before the change and passes after
it, including identity/type/duplicate/viewport/geometry/keyboard denials,
late finder/geometry, invisible target and nine-drag exhaustion. Related existing
native locator, iOS Files and build-configuration modules passed196 cases
(194 passed,2 Windows-only skips); the original stale query doubles are retained
in the failed precursor log, and updated to model both exact reviewed predicates.
The new module is selected by the actual CI command and independent observer
allowlist, whose exact count is37.

A read-only dirty-host candidate replay on the actual unchanged Simulator app
passed FILES-11's complete assertions, with normal logout, one session closed,
no business mutations and zero canonical case credit. The original query plus
`isDisplayed` and the new native predicate selected the same actual native
ScrollView ID. A preliminary diagnostic used a nonexistent navigation ID before
reaching the helper; that operator failure is retained separately, not classified
as an app failure. The full failed17-case report remains open until a fresh
source-bound build/backend and complete cold-cohort replacement pass.

## Evidence (local, retained)

Root: `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V`.

- `ios9d79-core-full-01/reconciled-proof.json`:23/23,69/69 phases.
- `ios9d79-files-01/reconciled-failed-proof.json`:16/17 calls, full postflight.
- `files11-native-diagnostic-02/passive-native-timings.json`: original helper,
  unambiguous request correlation;12 overlapping requests measured.
- `ios-files-facts-before-fix-01.log`, `ios-files-facts-after-fix-02.log`.
- `ios-fact-adjacent-before-fixture-update-01.log`: stale unit query doubles.
- `ios-fact-adjacent-after-fix-01.log`:196 cases as classified above.
- `files11-native-candidate-03/operator-failure-classification.json`.
- `files11-native-candidate-04/{candidate-source,viewport-predicate-equivalence,
  terminal,timing-reconciliation}.json`: actual candidate,0 canonical credit.

Android retains36 unique9d79 passing cases (Core23+13 Files calls); its separate
filename-position correction also requires rebuilt full replacement. QP2,
V117 and CX24 remain independently due on each platform. The full83-per-platform
inventory is unchanged. b9d hosted CI was green (52 successful jobs,1 expected
staging-deploy skip); this harness advance needs fresh CI. Google Play1.0.0(3)
is submitted/In review, not publicly live. Apple organization documentation is
still in review; no new documents were requested at the last actual check.
App Store listing/privacy drafts exist outside Git, but production Team/signing,
archive, screenshots and native distribution qualification remain outstanding.

## Frozen source gate follow-up

The complete21-command freeze of77f468cf retained a failed harness:1720 cases,
1702 passed,16 failed,2 Windows-only skips; mobile690, TypeScript and all18
Python modules passed. Adding the37th observer worker correctly invalidated
its exact recorder hash in the readable bootstrap and tooling manifest. The
canonical token generator regenerated the shipped bootstrap and AST provenance;
all current bootstrap SHA/blob pins and the generated iOS build entry were
reconciled. Bootstrap size remains6068 bytes and the Windows option remains8167
of8191 bytes; trust, ownership and deadline assertions are unchanged. The first
focused tooling replay retained one stale generated iOS-entry failure; the
subsequent65-case focused boundary selection passed with zero skips. Both failed
precursors remain retained. A complete replacement freeze is required before
pushing or building this revision.
