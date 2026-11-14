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


## Foreground expiry discovered by the c77076 full Core run

J20/M22, US-MOB-01/02/08, NATIVE-13 and adjacent JSON/private-byte reads:
**Partially implemented**, bug verdict **Inconclusive**, complete native release
**NO-GO** until fresh binaries and full replacement runs pass.

The source `c77076b62550cb45e69a7cb414a1680540a4e4c4` Simulator bundle
`83cd5282753d0906c80d2e60a7a9a2cfc12802a2ece23cfb0df0c281e3e123c5`
passed the first12 Core calls. NATIVE-13 then failed setup with
`NATIVE_FRESH_ACCOUNT_NOT_READY`; ten setups failed, one dependency setup was
blocked, and11 calls were unexecuted. All69 phases were independently reconciled,
all23 created sessions closed and were independently absent, and pre/postflight
passed. This does not replace the older source391 Core23 result or certify the
newer head. The prepared Files/QP work did not execute at this source.

The dated gateway observed refresh200, refresh200, refresh403 and logout204
without missing markers, rejected routes or overflow. Its existing ledger lacks
per-request timing; the retained allowlisted projection explicitly does not
invent that missing timing. A separately bound, read-only PostgreSQL observation
proved this exact synthetic membership's native MFA authorization expired at
16:26:29.124947UTC, before the NATIVE-13 account action at16:26:41.523UTC;
the family was revoked as logout at16:26:41.926028UTC. These measured times
support the expiry diagnosis; the original403's full response body/server branch
was not captured. A passive Simulator image later showed the compatibility
screen still asking for a check. No credential or private document bytes were
retained by these diagnostics.

The root integration recovered only restore/revalidation rejection inside
`openServerSession`. A normal foreground API refresh could also clear the
session, but had no corresponding completed-cleanup notification to the App.
NativeSession now notifies that root boundary only after successful secure/private
cleanup; refresh rejection additionally finishes its sole revocation attempt.
The App may then make one independent public policy read for a known rejected
401/403, no remaining session binding, an active mounted App and a checking
policy. It never replays the rejected request or rotating refresh, signs in,
changes MFA expiry or bypasses a current compatibility floor. The same boundary
covers JSON and byte operations, including a viewer canceled while shared refresh
cleanup is still pending. Stale-generation refusals do not notify the newer
session. Failed cleanup, unknown outcomes, background and a newer identity do
not open sign-in automatically. Explicit sign-out keeps its existing flow.

The new actual-App regression failed before the fix with the same idle panel.
The focused App/session/compatibility selection passes70 cases, including real
NativeSession cleanup/rotation composition, no-replay, cleanup failure, ordinary
403 retention, stale responses and background/identity races. Earlier byte
fixture attempts were correctly denied for a noncanonical download route and
remain retained; their correction uses the existing strict UUID download
contract. An intermediate focused run overlapped later test-file edits and is
incomplete evidence, not acceptance. Native verification of this runtime change
is still outstanding.

Task-cache evidence: `iosc77076-core-full-01/reconciled-failed-proof.json`,
`iosc77076-core-allowlisted-policy-timing-01.json`,
`iosc77076-native-session-times-01.json`,
`iosc77076-core-account-passive-01.png`,
`foreground-session-recovery-before-fix-01.log`,
`foreground-session-recovery-focused-01.log` through `-04.log`, and the separate
fixture/isolation/typecheck refusal records. The private test VM was parked after
all24 owned Core/setup sessions were absent; only its six active services stopped,
all63 containers and their data remained, and the shared CaseOps VM was untouched.

Publishing status supersedes the earlier internal-only observation above:
November13 Google Play submission1 / version1.0.0(3) remains **In review** for
public production; public availability is unverified. Apple organization
documents remain **In review** under enrollmentGZQJ2D9M4N, with no new owner action
shown. No signed iOS distribution archive or App Store submission exists yet.
