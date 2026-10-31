# Calendar and source-record slice — 2026-10-27

This is a source implementation and a proposed native supplement, not a native
acceptance receipt. The frozen 23 core and 17 Files cases are unchanged. Their
results cannot certify these later source changes.

Calendar already supports exact-day selection, +/-7 days and type filters. Its
IP events now open a current generic docket summary on the same tab stack; Back
returns to the retained Calendar day/filter. The summary states the actual
record_type (including patent, design or trademark), identifier, lifecycle and
record versions. It does not manufacture an application or renewal date from a
Calendar event or claim source verification.

Account > Source records offers Contracts and Trademarks. Contract lists retain
the existing 25-record cursor contract; the exact-ID reader returns the complete
existing ContractRecord scalar DTO without loading workspace child collections.
This uses the existing CurrentContext read policy, not creator capability or a
new billing/entitlement decision. Contract obligations and counsel detail remain
outside this read-only screen. Missing retained dates and money stay missing;
recorded minor units are not rounded or presented as verified values.

The new IP GET /api/ip/dockets/{docket_id}/summary is a generic scalar projection.
It uses IpViewer and the same tenant/active/current wall-team-grant policy as the
canonical docket lookup. Linked Matter access is not substituted for IP policy.
Mobile rechecks current workspace readiness before each summary read. Existing
trademark portfolio rows keep their exact docket/application/page locator read;
there is no portfolio scan, child-list download or generic trademark label.

## Planned separate native inventory

Each case needs its own setup/call/teardown and actual platform artifact, source,
backend, member, session/cleanup and independent complete-inventory proof. These
five IDs (15 phases per platform) are proposed, not executed or added to core23.

| ID | Exact workflow and evidence |
| --- | --- |
| SOURCE-01 | Calendar exact date, +/-7/filter, open an authorized patent/design/trademark event, show exact type/ID, then Back preserves original date/filter. No Matter lookup for the docket. |
| SOURCE-02 | Account source selector > Contracts; cursor pagination and exact source title/code, detail/reload agrees with complete current API metadata. Back and type switch remain usable. |
| SOURCE-03 | Retained nullable contract fields show missing values; positive sub-unit value preserves exact minor units. Generic IP summary makes no application/renewal-date verification claim. |
| SOURCE-04 | After legitimate IP grant/readiness revocation, reload refuses and removes earlier ready detail; missing/denied/offline/malformed responses remain distinct with explicit user reload and no mutation replay. |
| SOURCE-05 | Company/session change discards source detail and pagination. Fresh authorized source reads use the new company and reject mismatched response identity. |

Source domain tests and API cold-read/full-DTO/access tests establish narrower
contracts only. Native device layout, selection, back behavior and the above
complete supplement remain unverified until rebuilt and executed separately on
Android/iOS (and the advertised tablet layout). No store, distribution, account
verification or complete-V1 claim follows from this slice.


## Quick work source preparation (later branch20 slice)

Matter Work now has separate current-record task/hearing editors. Native writes
carry the observed parent lifecycle version. Task PATCH also carries the actual
offset-aware updated_at; hearing PATCH carries the server's keyed mhv1 content
fingerprint. These controls are not writable business fields. A current
immutable_lifecycle_history=false plus capability and version support is needed
before exposing an edit; retained unsupported records remain visible read-only.

One synchronous controller lease covers current access/parent/child preflight,
one POST/PATCH, acknowledgement UUID/parent/dirty-field checks and exact
persisted readback. A malformed acknowledgement, transport loss or server500
remains unknown, even if a mutation may have committed. No automatic replay is
performed. Unknown creation cannot be rearmed in that editor. An explicitly
reloaded rejected/superseded request can start a distinct new request; earlier
candidate/outcome history is retained in memory. Leaving or a session change
purges the editor and prevents a stale preflight callback from sending a write.

Legal dates are validated as date-only values; local hearing time and IANA
zone are explicit, without UTC date conversion. Owner reassignment and editing
hearing forum/purpose/judge are outside this compact editor. Completion's
follow-up choice is explicit; the resulting task is not independently certified
by the hearing acknowledgement.

New hearing creation requests an explicit empty notification plan, never a
browser-default email plan. This requires the coordinated backend correction:
the old scheduler used `channels or [email]` and treated an explicit empty array
as email. Source UI copy is not proof of suppression. The new no-notification
path must pass the actual scheduler/outbox tests before any native create run.
No reminder delivery is claimed from this source preparation.

Proposed additional native IDs (separate, not executed): WORK-01 create task and
reload exact UUID; WORK-02 dirty-only task completion/date clearing; WORK-03
create hearing with explicit date/time and no notifications; WORK-04 status,
outcome/reschedule and chosen follow-up with current HMAC; WORK-05 parent
close/reopen or child conflict rejection without replay; WORK-06 unknown outcome,
Stay/Leave and explicit reload recovery. Six cases/18 phases per platform are a
plan, not added to the existing23/17 inventory or a complete-V1 claim.
