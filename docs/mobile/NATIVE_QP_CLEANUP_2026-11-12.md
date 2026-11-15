# Native Queue/Privacy completion cleanup — 2026-11-12

J20/M22, US-MOB-01 through US-MOB-08, QUEUE-01 and PRIVACY-01 remain
**Partially implemented**. Overall bug verdict **Inconclusive**; release
**NO-GO**. Neither store is submitted or published.

## Original complete attempt

Source c8dd5c2ff94b165da3a3104c87df7d6aa1e2f93c passed the complete20-command
source gate (686 mobile, TypeScript,1703 harness passes plus two unchanged
Windows skips,422 Python cases across17 modules). Its actual Android APK is
ae0269cd9ff75510cda7fbd1be35ebfe08671f6a58dce078bea8faf46700dd34;
the separately built iOS Simulator bundle tree is
cb8fb3d89528a8da899279d259b53e79e4b588bd5cc48314406c33d9cc2ae9fc.
Both are QA artifacts, not distribution packages.

The Android report under the task cache
`native-release-20261111-ZzEIol4V/qp-c8dd-android-03/queue-operator-claim-d139a7606cea4df4679483dd/qp-native-reports/2026-11-12T15-20-31-388Z-android-qp-d17303a6/`
retains all three passing QUEUE-01 phases. PRIVACY-01 setup and call passed,
including the single received202 request, lost-acknowledgement reconciliation,
exact receipt, noncompletion and other-user isolation. Its final teardown
exceeded the original480-second suite budget. No canonical summary, completed
postflight or final session-delete acknowledgement was produced.
The independent reconciliation `c8dd-android-qp03-independent-reconciliation.json`
does not manufacture those results or credit a complete passing suite.

## Narrow candidate

After verifying the exact principal by scrolling upward from the receipt,
Android previously performed three more upward sweeps before searching downward
for Sign out. The candidate starts that search downward. iOS keeps its existing
path. Exact identity, one native input command, one acknowledged204 logout,
signed-out state and private-control clearing remain required; no timeout is
raised and no uncertain command is replayed.

The original failing70-case protocol report remains
`qp-c8dd-logout-direction-original-red.tap`; the full candidate module passed
70/70 in `qp-c8dd-logout-direction-candidate-01.tap`. The regression now
asserts the exact upward-then-downward sweep sequence. Wrong principal and
unacknowledged logout remain refused.

An initial focused native setup incorrectly expected the member after Privacy
had switched to its second-company actor; the identity guard refused before
logout and its session was deleted. That failure is retained separately.
The corrected actual-app replay
`qpc8dd-logout-direction-native-02/proof.json` verified the exact second-company
principal, one received204 logout, cleared private controls and paired session
deletion in6.124 seconds, within its unchanged20-second bound. The installed
binary remained the c8dd APK; the changed harness is independently hashed.
This focused replay earns zero complete-suite case credit. A complete fresh
source-bound replacement and deployed verification remain required.

## Cleanup and CI

External session cleanup independently established the expired native session's
absence; this does not repair the missing original teardown. A stopped gateway
with an unparsed stop acknowledgement was reconciled by its exact container,
exit0 and canonical SIGTERM shutdown, without replaying that stop. All63 retained
private containers and volumes remain, unrelated states are unchanged, and the
private VM is stopped. The expired control run was not rearmed; no closeRun RPC
acknowledgement is claimed. Receipts are under
`park-c8dd-after-timeout-cleanup-01/` and
`park-c8dd-after-timeout-cleanup-02/`.

Mobile source gates, Security, CodeQL and review passed on c8dd. Main CI run
43242669428 was canceled: PostgreSQL shard3/32 hit its12-minute job limit.
Its immutable artifact13956228709 retains41 complete passing cases of127
selected;86 are unexecuted. That is incomplete CI, not green. Repeated historical
database setup is under investigation; a single stack sample is not a proved
SQLAlchemy hang. Original budgets, case inventories and failed evidence remain.
