## 2026-11-12 — initial native consent visibility

J20/M22, US-MOB-01/02 and MOB-01/02 remain **Partially implemented; release
NO-GO**. Actual 288b2504 Android and iOS Simulator builds succeeded. The complete
replacement Queue/Privacy attempt stopped in first sign-in setup: both calls
were unexecuted, with zero native case credit. Reports remain under
`native-release-20261111-ZzEIol4V/qp-288b-android-01/` outside Git. Normal login
returned200; no privacy request or anchor PATCH was sent, and the run authority
closed. These facts do not pass either native case or verify the journal race.

A separate passive post-failure observation found the consent page with the
keyboard still open and no visible Connect control. One normal Android Back
revealed the enabled initial Connect button, without an authorization submit;
retain `post-failed-initial-connect-keyboard-01/{before,after,result}.json` in
that cache. This is the reproduced post-failure state, not an original failure
screenshot or a measured network diagnosis.

The candidate focuses the initial button only when current verified consent
renders it enabled, as well as when it remounts after MFA. The existing current
query/epoch, MFA, expiry, explicit-consent and no-replay fences remain unchanged.
The complete component module first retained34passes/1focus failure, then
passed35/35, including delayed initial identity and late-MFA focus preservation.
A prior CLI startup failure selected an absent Vitest project and executed no
cases; it remains separate. Native and deployed-production acceptance are still
open, so the bug verdict remains **Inconclusive** and no store submission is
claimed.

