## 2026-11-12 — native Queue/Privacy follow-up

J20/M22, US-MOB-01/02/07/08 and QUEUE-01/PRIVACY-01 remain
**Partially implemented; release NO-GO**. Exact a82ded25 Android acceptance
completed Core23 and Files17 (40/83 cases, 120 unique passing phases). Hosted
CI completed successfully, including the canonical browser union (753 passes,
21 existing reviewed skips); browser passes are separate from native acceptance.
The complete two-case Queue/Privacy run failed both calls and privacy teardown.
Its original reports and gateway journal are retained under
`native-release-20261111-ZzEIol4V/qp-a82d-android-01/` outside Git.

Privacy actor switching and teardown looked for the account header without
scrolling after the receipt assertions had moved it offscreen. The candidate
restores that exact header with bounded upward scrolling before checking the
same principal and dispatching one acknowledged sign-out. No identity or logout
assertion is removed. A separate real-descriptor regression reproduces concurrent
append/close races in the shared native/control journal; one lease now covers
metadata validation, append, fsync, metadata reconciliation and close. The
original Queue refusal has no retained exception detail, so that race remains a
source-based hypothesis for the original dated failure, not measured causality.
Original deadlines, operation limits, unknown-outcome fences and inventories
remain unchanged. The focused scrolled-account logout also passed on the actual a82ded25 APK
(`candidate-privacy-logout-native-01/result.json` in that retained cache), with
normal logout204, no private credential read and a closed Appium session. This
one focused check does not pass the two-case inventory. Fresh complete native
replay, iOS and distribution remain open;
no release AAB, review submission or publication is established by these fixes.

