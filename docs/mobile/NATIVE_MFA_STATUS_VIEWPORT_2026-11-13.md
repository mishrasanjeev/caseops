# Native browser MFA status viewport — 2026-11-13

J20/M22, US-MOB-01..08 and Android NATIVE-13. Implementation: **Partially
implemented**. Bug verdict: **Partially fixed**. Release: **NO-GO** until actual
replacement platform acceptance and distribution checks pass.

## Observed failure

The complete 23-case Android run used source
`6fbcad12481d33cdf3a2fae4073b88db64d7fddf`, mobile fingerprint
`c26df280978385ab71415c2a2a11404f11241c0d64a71cb512f033118783218b`
(244 inputs), APK
`1b082e6ea1e05573011ad2400df593e9d3f70d9941879a8fa632916d76385e9a`
and independently matched local API/web source. Its original summary retains
12 successful calls, 10 failed phases, 11 unexecuted calls and one blocked
scenario. It is not a completed Core23 pass or an 83-case pass.

NATIVE-13 failed while finding the exact MFA success message. The retained
gateway sequence shows native authorization 403, MFA verification 200 and the
subsequent identity read 200. No second authorization was dispatched. These
statuses do not establish a network or authenticator failure; this ledger has
no per-request timing fields.

Two passive observations after the run found an enabled, visible Connect app
control and no visible MFA success message or page heading. A single upward
scroll, without submitting or reauthenticating, revealed the exact message and
heading. The message was at y=816 and Connect app at y=1618 in the 1080×2424
native window. This establishes the offscreen status independently of the
earlier Firefox background-tab hypothesis. The observations read only fixed
controls and frames; no raw page source, account values, URL, MFA code or token
was retained. Every diagnostic Appium session was acknowledged closed.

Evidence is retained outside Git under
`~/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/`:

- `canonical-6fbc-core-01/core-full-02/current-full/core-reports/2026-11-12T23-29-34-251Z-android-9d557ed4/`
- `canonical-6fbc-core-01/core-full-02/current-full/gateway-after-first-failure-01.json`
- `core13-firefox-6fbc-passive-01.json`, `core13-firefox-6fbc-passive-02.json`
- `core13-firefox-6fbc-upward-scroll-03.json`
- `canonical-6fbc-core-01/core-full-02/current-full/operator-input-postflight-01.json`

## Change and verification

The browser consent page now places the existing status directly before its
connection action, after the identity facts. Both Connect app and Open CaseOps
reference that status as their accessible description. This keeps the success
explanation with the focused action. It does not change MFA, PKCE, current
identity comparison, authorization counts, grant lifetime or the separate
user gesture needed to open the app. Failure, expiry and account-change paths
remain covered by the existing complete component suite.

The strengthened existing MFA test failed before this change because the
focused Connect app control had no accessible description. All 35 component
cases then passed, including the additional Open CaseOps description check;
web project TypeScript compilation passed. The initial incorrect Vitest path
failed before executing tests and remains in its separate log. No Playwright
journey or native harness assertion/timeout was changed.

Those checks do not certify viewport geometry on the replacement build.
Actual Android/iOS browser replay, complete native suites, fresh source-bound
artifacts/backend, hosted CI and production/store qualification remain due.
Google Play version2 remains an owner-only internal qualification release;
no public production submission is established here.
