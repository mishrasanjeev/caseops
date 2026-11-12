# Stored native session rejection recovery — 2026-11-13

J20/M22, US-MOB-01/02/08, NATIVE-01 and Files setup: **Partially implemented**;
native fix verification **Inconclusive**; public release **NO-GO**.

The actual c8dd iOS Simulator bundle (tree SHA-256
`cb8fb3d89528a8da899279d259b53e79e4b588bd5cc48314406c33d9cc2ae9fc`)
passed Files preflight, then failed its unchanged 20-second session-readiness
setup before any of the 17 Files calls. The exact gateway epoch recorded public
compatibility GET 200, native refresh POST 403 and native logout POST 204.
A subsequent read-only native hierarchy showed an idle compatibility panel,
not secure sign-in. No response body or credential is retained. The backend
source points to expired/changed MFA as the 403 path; the precise underlying
MFA condition is not independently measured here.

Session invalidation clears local authority and invalidates the compatibility
observation. The App previously did not replace that observation after a
rejected restore/revalidation. The new recovery performs one separate public
policy GET only after acknowledged 401/403, ended local authority, successful
cleanup, and an active mounted App. It does not replay refresh or a business
operation, sign in, relax MFA, bypass an update floor, or grant private access.
Unknown outcomes and storage/private-cleanup failures remain closed. The
compatibility controller still binds its response to its principal and lifecycle.

The actual-App regression failed before the fix with the same idle panel.
Three App cases now cover normal 401/403 recovery, cleanup/unknown refusal and
failed/newly-required public policies. A fourth test composes the actual
NativeSession, JsonTransport and compatibility controller: refresh is sent once,
credential clearing and logout occur once, and public recovery remains separate;
a secure-store failure preserves its explicit refusal.

Verification before commit: complete mobile source suite **690/690 passed**, no
skips/cancellations/todos; all three session/compatibility/App modules **63/63**;
mobile TypeScript compilation passed. The first complete host run had one
Python-launch failure (689/690) because PYTHON was absent; its evidence remains,
and the complete replacement uses the pinned Python 3.13.17. Tests do not prove
native acceptance. Fresh Android/iOS binaries, backend/source binding and full
native inventories remain required.

Retained evidence is in the task cache `native-release-20261111-ZzEIol4V`:
`ios-auth-recovery-reproduction-01.log`, `ios-auth-recovery-unit-04.log`,
`native-auth-recovery-full-mobile-unit-01.log`, its complete replacement
`native-auth-recovery-full-mobile-unit-02.log`, its final formatted-source
replacement `native-auth-recovery-full-mobile-unit-03.log`, and
`native-auth-recovery-mobile-typecheck-02.log`. The failed native run is
`iosc8dd-files-04/files-reports/2026-11-12T22-16-39-212Z-ios-files-1b5d4cf4`.
It has zero native Files passes; all 17 calls remain unexecuted. Its postflight
read the staged provider originals, so a replacement must use a new cold cohort,
retain this manifest as prior provenance, and never prewarm new provider bytes.

Separately, Google Play now shows version 2 (source 13fdc494) Active and Available
to internal testers, restricted to the single organization owner email. It is
unreviewed, not a production submission or public launch. Its owner invitation
requires consent; protected Play-installed launch acceptance is still pending.
The old Google-signed APK passes signatures, SourceStamp and all 20 ELF/ZIP
16-KiB checks, but sideloaded launch on the Google-APIs emulator is blocked by
Google installer protection. That is not an accepted launch or an app defect
waiver. Full CI for 13fd passed 52 jobs with the workflow-required main-push-only
staging deployment skipped; the newer b9a fixture integration's CI remains
separate. Existing c8dd full inventories stay Android 40/83 and iOS 23/83;
this change receives no credit from those older binaries.
