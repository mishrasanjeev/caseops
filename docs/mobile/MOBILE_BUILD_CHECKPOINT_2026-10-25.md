# Mobile Build Checkpoint: 25 October 2026

J20/M22; US-MOB-01..08. **Partially implemented. Public release: NO-GO.**
This checkpoint separates component tests from native and production acceptance.
No production deployment or paid-provider call is part of this native task.

## Exact Android Evidence

The standalone local-acceptance APK was built from
`ee8dde90438cc8875f1be32b8028c3e2a99d8bee`, app fingerprint
`b8fbbaf97e377801473403b33c4809094d15110d2dbfc01101a4eb676701be02`.
APK SHA-256: `341f37aef001bdd51e210f896029fef52451af2bc107e7428a682e5d69a5bb16`.
The local API and web also served ee8dde90. This is an emulator-only artifact,
not a phone/store/production release. No Metro development server is required;
the workstation's separate Metro startup restriction has not been bypassed.

- Appium noReset retained an older APK despite enforceAppInstall. The affected
  `native-core-20261025-547f63fc-*` journal is incomplete/wrong-binary evidence.
  The corrected runner explicitly replaces the owned package without a data
  clear and hashes installed bytes before and throughout execution.
- `native-core-20261025-af240eb1-*` was interrupted after two passed calls.
  It has no completion event and cannot certify the complete inventory.
- Completed actual run `native-core-20261025-7e5fea0d-*`, report
  `2026-10-25T04-56-07-587Z-android-be5f6f5c`: **14 calls passed**, NATIVE-10,
  NATIVE-16 and NATIVE-17 failed; **six calls unexecuted**. Postflight failed
  closed after the owner helper deadline. All failed evidence is retained.
- NATIVE-09 positively proves one acknowledged saved note ID/body after restart.
  Earlier saved notes were retained, not deleted to reset the fixture.
- NATIVE-10's test guessed a hearing ID instead of the actual Calendar DTO ID.
  The native tree exposes `event-hearing:65f76da7-708d-4581-a86c-04fe4cc2e138`.
  Fixtures now retain the opaque returned event identity. Full replay is pending.
- NATIVE-16 passed a separate bounded native component replay after the earlier
  full-run failure. That supplement does not turn the original run green.
- NATIVE-17 stopped on its first read-only owner command deadline, before the
  destructive command. The negative targets remain operational; never reopen a
  disposed target or replay an uncertain mutation to prepare another run.

## Files Upload Defect And Replacement

Actual report `native-files-20261025-95a57a8a-*` passes FILES-01: exact seeded
filename/SHA-256, reload, native private TXT content, bounded range/full source
reads and return. FILES-02 was explicitly blocked, not counted as passed.

The Android DocumentsUI picker was then observed selecting the hash-verified
204-byte synthetic file and returning it to the same Matter, with upload enabled.
The single upload attempt showed unknown outcome, no recorded upload POST and
no matching attachment after read-only reload. It was not retried.

Pinned Expo58's real convertFormDataAsync rejects RN URI parts before
NativeRequest.start. The replacement uses the SDK-supported bytes interface
over only the owned staged file, preserving MIME, exact lifecycle version,
bounded size and the existing 50 MiB cap. Filename normalization is checked
against the actual backend function to avoid percent-encoding display drift.
Cookie omission, no-store, redirect refusal, private cleanup and uncertain-write
no-replay remain unchanged. Expo materializes multipart bytes; physical-device
peak-memory/performance acceptance remains open, not claimed as streaming upload.

**Replacement components:** strict TypeScript passed; **304/304 mobile tests**,
all **22 intended/observed files**, zero failures/errors/skips. The real pinned
SDK encoder and canonical server filename function execute in regression tests.
The new runtime has not yet been rebuilt or positively replayed on Android.

## Fixture Readiness And iOS

The owner helper now has bounded preflight import readiness and a hash-bound
single-inflight worker. Actual commands retain eight-second and SQL budgets,
current release/ACL/lifecycle checks, sixteen-command bound and exclusive claims.
Readiness, operation timing and exact full native replay must be reconciled
before closure; unit doubles are not real PostgreSQL owner execution.

The real ee8 worker benchmark completed: readiness 2.703 seconds, authoritative
read commands 281/257 ms, cleanup 942 ms. Both negative targets remained Intake,
lifecycle version zero, with no notes. No mutation command executed. This proves
fixture readiness only; it does not close the unexecuted native negative cases.

The ee8dde90 finite iOS Hermes export passed: 900 modules, bundle SHA-256
`3d788055f35651810884673bf454176d3f9fef26b1bed839a0fc196267a841ba`.
This is Windows bundling only. The newer upload replacement requires another
export, then the owner's MacBook must compile and run the full native inventory.
See `../../scripts/mobile/MACBOOK_RUNBOOK.md` and
`IOS_OWNER_CHECKLIST_2026-10-25.md`.

## Remaining Gates

Rebuild frozen source, verify actual installed bytes, complete all 23 Android
core cases and the picker/upload/reload/source-opening supplement. Keep provider,
MFA, source/lifecycle and capture fences intact. Native iOS, GC/IP/Files breadth,
inbox/push, physical privacy, accessibility, responsive devices, dependency
security, signing/store and protected canonical release gates remain open.

Receipts are retained under `C:/Users/mishr/.cache/caseops-mobile`; dated
subdirectories above are actual executions, not placeholders for future passes.
