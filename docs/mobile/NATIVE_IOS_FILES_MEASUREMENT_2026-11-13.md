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


## Source391 replacement and atomic native facts

A fresh actual source391c50fd Simulator bundle508dcf0a and matching isolated
API/web passed Core23 (69 phases). Its complete Files17 attempt retained5
passing calls,1 failed call (FILES-06), and11 unexecuted calls. PNG received its
normal200 upload acknowledgment and appeared after reload, but its subsequent
hash observation failed. The uncertain mutation fence correctly prevented any
upload replay. Fourteen acknowledged sessions closed; the3 dependency-blocked
cases created none. The canonical aggregate postflight failed
EXACT_FILES_SESSION_LIFECYCLE_REQUIRED; this remains a failed/incomplete run.
The separate provider postflight and independent reconciliation preserved all21
originals across3 cohorts and found zero owned private copies. Neither that
privacy result nor the read-only diagnostics makes the full attempt pass.

A separate unchanged-helper diagnostic passed on the existing PNG without a
business write. Passive timing used per-request Headers identity, did not wrap
native promises, and found zero overlapping requests in this diagnostic. Its
last complete in-viewport observation spent about1444ms across8 protocol
requests. This supports a narrow timing-margin hypothesis; it does not identify
the original failed RPC, whose transport timing was not captured. An unchanged
replay is not used as acceptance or as proof that the original failure vanished.

The pinned WDA expanded response independently returned exact native element
IDs, type, attribute/name, visibility and rectangles in one native snapshot
response. The standard response field name represents type in this WDA, so the
actual identity uses attribute/name explicitly. Together with the native window
read, the measured probe took746ms across2 protocol commands. The revised
helper consumes those facts, preserves every ID/type/unique viewport/geometry/
containment/visibility denial and verifies the resolved wrapper retains the
same native ID. Sessions explicitly request and verify those response settings.
Missing snapshot facts fail closed. The1500ms observation,150ms poll,650ms drag
and9-drag cap remain unchanged. A200ms-per-command clocked regression fails on
the old serial reads and passes on the revised protocol. Adjacent scenario
fixtures model the actual expanded response instead of removing their assertions.

The dirty-host candidate passed the existing PNG filename/hash before and after
an authoritative reload on the unchanged391 app, normal logout and session
cleanup, without upload replay or another business mutation. Only its exact
helper bytes are candidate evidence; unrelated unit-test inputs changed during
preparation, so this is not a frozen whole-source acceptance claim. A new clean
source-bound build/backend and complete cold-cohort Files replacement remain
required. Bug verdict stays Inconclusive and native release verdict stays NO-GO.

Retained evidence below the same private root:
- ios391c50-core-full-01/reconciled-proof.json
- ios391c50-files-01/reconciled-failed-proof.json, including failed postflight
- files06-fact-diagnostic-391c50-01/{passive-timings,terminal}.json
- files06-fact-candidate-391c50-01/{candidate-after-reload-result,terminal}.json
- ios-files-atomic-facts-before-fix-01.log (new clocked reproduction fails)
- ios-files-atomic-adjacent-02.log (55 passed,0 skipped)

The current391 Linux CI is still completing its unchanged inventory. Mobile
source, both installed dependency audits, CodeQL analysis and secret scanning
have passed; no complete-green claim is made until every required job finishes.
QP2 setup remains independent of the failed Files call, after exact owned-session
absence and complete retained privacy evidence. No security feature is enabled
to enumerate sessions: Appium3 session discovery remains disabled; only the
acknowledged invocation-owned session IDs are independently checked absent.


## Independent iOS Queue/Privacy execution

The source391 QP producer completed34 normal actor-setup calls (22 POSTs),
4 actual MFA enrollments, and74 normal dataset calls (53 POSTs/1 PATCH).
Two separate normal Safari sign-ins verified exact native principals/workspaces,
PKCE, actual segmented controls, logout and session cleanup before registration.
The actual2-case native run executed all6 phases: both setups and teardowns
passed, but both calls failed QP_NATIVE_STATE_REQUIRED. Its postflight passed,
2 acknowledged sessions were independently absent and controls were disabled.
No account-deletion submission was forwarded. These are0/2 passing calls,
not skipped or accepted workflows, and the original failed report remains retained.

Actual native hierarchy evidence shows the member's5436-point queue Other
container has visible=false, while both correctly named segmented controls are
visible within it. All25 task rows exist as native Buttons, including offscreen
rows. The empty second workspace's smaller container has visible=true. A tall
structural container's visibility is therefore not a usable control predicate.
The iOS queue now requires its exact unique typed structural parent plus visible
native ownership/date controls within that parent and the actual viewport. Native
row responses retain complete ordered membership, roles, duplicate and excluded/
unbound-row denials. Row evidence is structural membership, not a claim that all25
rows were simultaneously visible. Exact task/pagination clicks use measured
native controls. Structural detail screens require their current visible text
inside the exact typed parent. Privacy status/confirmation checks seek the actual
visible controls and preserve20s transition,1500ms fact and480s serial bounds;
confirmation proves both scoped buttons instead of relying on its wrapper.
The existing single-dispatch and unknown-acknowledgement mutation fences remain.

A separate read-only dirty-host candidate on the unchanged391 binary passed all25
first-page native identities, actual Next, both older second-page identities,
selection and every fact of the older task, exact parent opening, and native
privacy form open/cancel back to no request. Normal logout and session cleanup
passed. Zero business mutations/deletion POSTs were observed; the2 temporary
exact GET matter routes were restored to the original10 afterward. Its exact
candidate module bytes/source observation are retained, with0 canonical case
credit. Later deadline guards have separate clocked regression coverage and
still require the complete clean source-bound replacement. No privacy request
completion or production acceptance is claimed.

The focused combined boundary selection passed130 cases with0 failures/skips.
The independent whole83-per-platform inventory remains unchanged. Both native
QP cases require fresh actors/dataset/registration for their full rerun; the
expired/closed authority and old failed report must never be reused as a retry.

Additional retained evidence:
- qp-391c50-ios-01/queue-operator-claim-db06bf20725cc877bf3ca1da/
  reconciled-failed-proof.json
- qp-ios391c50-native-candidate-01/{first-page-result,older-task-result,
  matter-open-result,privacy-cancel-result,terminal,route-restoration-proof}.json
- ios-qp-files-adjacent-03.log:130 passed,0 skipped

Setup refusals are retained separately: unsupported Appium session-list route,
public-reference size mismatches for actual executable files, and an omitted
explicit disabled-default configuration key. Known completed setup stages were
not replayed. Executable descriptors use the existing128MiB executable admission
bound, not the smaller JSON fixture bound. The host config was normalized only
to the gateway's already-effective disabled value0, with same-descriptor bytes
and guest readback; no runtime setting, receipt or business data changed then.
Session discovery remains disabled; exact invocation-owned sessions are checked
through their read-only native timeouts endpoint. These preparation failures
provide no application failure or native case credit.
