# Android public-policy auth-proof correction — 2026-11-13

J20/M22, US-MOB-01/02 and NATIVE-01: **Partially implemented**. Complete native
acceptance remains **Inconclusive; NO-GO** for public release.

The actual Android APK `1b082e6ea1e05573011ad2400df593e9d3f70d9941879a8fa632916d76385e9a`
and backend/web revision 6fbcad12 completed normal Firefox login, MFA, unchanged
PKCE, native principal/workspace verification and visible sign-out. Its auth01
observation remains failed: the proof consumer treated an earlier credential-free
GET /api/auth/native/compatibility 200 as authenticated success before the normal
rejected browser refresh. The original gateway packet, steps, failed observation
and acknowledged Appium session deletion remain unchanged.

The retained packet has public compatibility sequence4, browser identity 401 at6,
rejected browser refresh at8, login200 at13, MFA200 at18, authorize200 at20,
native exchange200 at22 and logout204 at27. OPTIONS was already excluded. The
consumer now uses the existing exact-GET public-compatibility contract for that
one success-prefix test. It preserves the complete successful auth spine, MFA,
PKCE, actor, once-only mutations, 401 bounds, ordered logout and gateway marker
checks. HEAD, another auth route, a compatibility-like path and authenticated
identity success remain refused. It does not remove any native workflow case.

The complete changed consumer plus MFA/traffic modules passed40 cases, no skips
or cancellations. The added regression failed before the fix on the same
NO_AUTH_SUCCESS_BEFORE_REJECTED_REFRESH guard. Evidence is retained in the task
cache as android-auth-proof-public-compatibility-reproduction-01.log and
android-auth-proof-public-compatibility-unit-02.log. A fresh native auth attempt
and complete23-case run are still required; reinterpreting a packet never turns
the earlier failed run into a pass.

This is host proof-consumer code outside the244 native build inputs. The actual
Android/iOS binaries and serving backend remain pinned to6fbcad12, product input
fingerprint c26df280978385ab71415c2a2a11404f11241c0d64a71cb512f033118783218b.
The host consumer revision is recorded independently. Execute the native suite
from the clean frozen6fbc checkout and retain its real binary/backend/source SHA;
do not rename those passes to this later host revision, modify the frozen tree,
or weaken run-native's exact source/binary checks.
