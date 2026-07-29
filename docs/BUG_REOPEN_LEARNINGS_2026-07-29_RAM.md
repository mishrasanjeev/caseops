# Ram 2026-07-29 Audit: Responsive Regression and Why Fixes Reopen

## Findings

The workbook contained two CaseOps rows. Both are valid bugs:

- `BUG-001` was a real navigation regression, but the current source already
  contains the correct shared `Sidebar` registry entry. The prior “reopen” was
  caused by testing a stale local `.next` artifact, not by the current source
  missing the route. Production revalidation passed the shared desktop and
  mobile navigation path.
- `BUG-002` was reproducible in both the stale local production build and live
  production. The Admin landing page nested all header links inside a single
  non-wrapping flex row. At a 360px viewport, the row's intrinsic width pushed
  `Provider ops` and later controls about 3.5px beyond the viewport, which made
  the controls appear clipped/hidden on Android-sized screens.

The durable fix makes both the generic `PageHeader` action slot and the Admin
action group shrinkable and wrapping on mobile, while retaining an auto-sized
desktop presentation. The regression asserts every Admin action's URL,
visibility, and viewport bounds at 360px.

## Brutal analysis of the reopen failure

The earlier shallow pattern was:

1. Patch the source or a single visible page.
2. Run tests against whatever production build or local server happened to be
   running.
3. Treat a green result as a release sign-off without proving build identity.

That process can report “fixed” while an older artifact still serves the old
behavior. In this run the source included the Judge Aliases fix, but local
`next start` initially served a pre-fix `.next` build. Live production also
reproduced the new responsive Admin defect, proving that the reported mobile
failure was not a tester misunderstanding.

Cases have a separate, intentional lifecycle reopen: `Disposed -> Intake`
through the dedicated lifecycle endpoint. The current backend rejects generic
metadata reactivation, locks the parent row, checks the expected status and
`updated_at`, increments `lifecycle_version`, neutralizes operational child
records, and records audit/activity events. Existing API and Playwright
regressions cover stale writes and child resurrection. Therefore the evidence
does not justify adding another ad-hoc status patch; the risk is release drift
and incomplete end-to-end proof, not a missing second reopen route.

## Permanent controls

1. Build from the current tree before any `next start` retest; do not certify a
   stale build.
2. Pair every fixed verdict with the exact production image/revision and the
   same dated Playwright spec. Health alone proves availability, not identity.
3. Test responsive groups from the real page at 360px/Android-sized widths and
   assert layout bounds, not only DOM presence.
4. Keep lifecycle transitions centralized and fail closed. Any new writer of
   Matter status must be reviewed against the lifecycle state machine and its
   terminal-state suite.
5. Keep production credentials in environment injection only; never commit,
   log, or copy them into reports.

## Regression artifacts added

- `tests/e2e/ram-2026-07-29-bugs.spec.ts` — local legal tenant proof.
- `tests/e2e/ram-2026-07-29-prod.spec.ts` — supplied tester-account proof.
- Existing lifecycle coverage remains required: `tests/e2e/ram-2026-07-15-*`,
  `tests/e2e/ram-2026-07-22-*`, and `apps/api/tests/test_matter_lifecycle.py`.
