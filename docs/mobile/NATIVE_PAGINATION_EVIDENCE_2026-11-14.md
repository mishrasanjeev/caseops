# Native pagination and V1 evidence repair — 2026-11-14

J20/M22; US-MOB-01/03/05/08; SOURCE-01 through SOURCE-07,
WORK-04/07 and the independent 83-case Android/iOS inventories.
Implementation: **Partially implemented**. Bug verdict: **Partially fixed**.
Release acceptance: **NO-GO** until fresh candidate builds and complete native
inventories pass independently on both platforms. No historical pass transfers.

## Retained failure and measured causes

Both clean e725017d Android and iOS Simulator builds passed. Its actual Android
V1 run retained exactly 2,000 events but no summary: logging overflow interrupted
WORK-08 and the exception handler attempted another write to the full journal.
The original journal remains unchanged under
`/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/canonical-e725017d-v1-01/full-v1-01/`.
Five calls passed (WORK-01/02/03/05/06), nine failed, WORK-08 was interrupted,
and COUNSEL-01/INBOX-01 never started. This is not a completed 17-case suite.
Independent reconciliation proves all 15 known sessions absent and the control
manager closed; it does not fabricate a missing deletion acknowledgement.

Read-only native diagnostics retained under that same evidence root establish:

- `e725017d-source-native-diagnostic-01`: Page 2 → exact contract → Back
  returned Page 1. List/detail requests were 200. The list's local pagination
  hook unmounted during detail navigation.
- `e725017d-source-native-diagnostic-04`: the Calendar row was initially a
  30-pixel sliver. One downward gesture exposed all three exact fields. The
  normal decoder/UI used `display_type=filing_deadline`; the external fixture
  incorrectly used raw `kind=deadline`. Three source-segment entries were
  initially visible, so a transition-timing root cause remains unproved.
- The obligations disclosure mounted and its GET returned 200. Its page footer
  was below ten rows and became visible with bounded normal scrolling.
- The viewer fixture intentionally has no primary `v1` data. Segment lookup
  wrongly dereferenced that missing data in WORK-07 and adjacent SOURCE-05.
- `e725017d-viewer-readonly-native-diagnostic-02/03/04`: Android rejected the
  scoped ancestor lookup; global exact-ID ancestry worked. Fabric exposed
  readonly text as accessibility siblings. All three exact global facts were
  within each uniquely identified non-clickable row; descendant queries found
  none. Preserve the failed diagnostics separately.
- `e725017d-viewer-readonly-native-diagnostic-05`: canonical candidate segment
  and readonly-row helpers passed for the exact viewer task and hearing on
  the installed e725017d app. Candidate harness hashes remained stable; normal
  sign-in/logout and known-session 404 plus complete empty inventory passed.
  This diagnostic earns zero candidate native-case credit.

Account-navigation diagnostics02/03 stopped before Calendar; a separate surface
inspection found the app signed out. They provide no Calendar result. Normal
fresh authentication preceded diagnostic04. No workflow mutation/control claim
was replayed, and no QA CA was installed on the personal phone.

## Repair and preserved guards

Keep only the list cursor/history in a stable company/type-keyed screen while
its source-list route exists. Inactive children unmount, aborting their readers
and discarding results. Back remounts a fresh authorized reader at the retained
cursor; there is no previous-ready frame. Type change and pop/reopen reset the
cursor. Existing session ownership clears the screen on account changes.
Retained child interaction leases still reject inactive callbacks.

Derive and validate Calendar facts through the real decoder. Carry generic
segment presentation separately, bound to the admitted device/build/source;
viewer authentication and tenant data stay intact. Position exact controls and
all row facts within the existing 20-second/9-scroll limits. Lost gesture/lookup
errors remain terminal even when WebdriverIO retries rejected polling callbacks.
Keep single-protocol clicks and Android tab-bar occlusion checks.

Readonly Android facts require unique row identity, a fully contained visible
frame in its exact scroll viewport, non-clickable state and one displayed exact
text leaf fully inside that frame. Bound global matches before reading them;
reject missing, duplicate, sibling/outside or changed facts. Recheck row/scroll
identity and geometry after collecting fields. Keep iOS's descendant ownership
path and all authorization/data assertions.

## Explicit evidence budget and cleanup

V1 now retains **two mandatory streams**: `events.jsonl` for native actions,
assertions/phases and session evidence; `browser-events.jsonl` for every passive
browser observation. Each stream allows at most 2,000 events and 1 MiB. The
**aggregate allowance increases to 4,000 events / 2 MiB**; splitting files does
not preserve the old aggregate 2,000-event bound. No observations are dropped.
Shared contiguous sequence numbers, counts and exact file SHA-256 hashes bind
both streams. A consumer must validate both streams using
`validateV1EvidenceStreams`; the final summary includes both mandatory entries.
Existing recursive report retention must retain both files and the summary.
No existing workflow upload path is changed.

Any serialization, byte/entry bound or IO failure poisons further workflow
writes. Uncertain partial writes retain only explicitly named accepted-prefix
information, with no claimed whole-file digest. Complete files are verified
through their still-open owned descriptors before closing. Final validation
refusal produces an incomplete summary rather than disappearing without one.

The original 30-minute acceptance deadline remains absolute and monotonic
through cleanup/finalization. Expiry stops further workflow dispatch. A separate
at-most-60-second emergency cleanup fence cannot earn acceptance or extend the
workflow deadline. Session ownership is independent of logging, bounded to17
registrations, and marks deletion before transport so unknown acknowledgements
are never retried. Require independent 404s for all known sessions plus the
actual complete empty Appium inventory. Always attempt control closure and
credential disposal. An incomplete run never invents missing phase results.

## Verification boundary

Source regression tests cover cursor retention with fresh authorization,
revocation/late-result denial, inactive controls and kind/pop resets; canonical
Calendar projection; viewer segment ownership; clipped/occluded row positioning;
readonly geometry and layout drift; journal saturation, serialization/getter,
partial append/fsync and retained-byte failure; no-replay cleanup; complete
session inventory; marked bounded status transport; and deadline refusal.
Focused mobile type-check passed. Full frozen source gates, fresh Android/iOS
builds and complete 83-case inventories are still required for this candidate.
The existing Play release remains in review; Apple organization documentation
remains pending. Neither store state proves native acceptance.
