# Matter-task Work queue contract

This is a separate read-only endpoint; Today retains its existing capped triage
feed and date horizon. This queue does not claim IP, hearing, deadline, inbox or
all-domain Work completion. No native acceptance or database execution has run
for this source candidate yet.

`GET /api/matter-work-queue` accepts `ownership=mine|team|unassigned` (default
`mine`), `dates=all|dated|undated` (default `all`), `limit=1..25` (default25), and
an optional opaque `cursor` (maximum4,000 characters). Optional `due_from` and
`due_to` are inclusive YYYY-MM-DD calendar dates, allowed only for `dates=dated`.
An impossible, reversed or contradictory date filter is422. There is no implicit
Today, seven-day horizon or UTC conversion of a legal due date.

Mine means exact current membership ownership. Team means **tasks assigned to
other active members of your currently active company teams**; it excludes Mine
and Unassigned. Team membership never grants Matter access. Unassigned means an
actual null owner, never an inactive, foreign or unavailable owner's task.
The `owner_membership_id` is protocol identity, not a primary user-facing label.
The client can say “Assigned within an active team”; it must not print raw IDs
as a replacement for a person's name or call the entire visible queue “Mine”.
There is no directory fanout or fabricated owner name in this projection.

The page has `scope:"matter_tasks"`, echoed `ownership`, `dates`, `due_from`,
`due_to`, `limit`, `sort:"due_on_created_at_id"`, `items`, and `next_cursor`.
Each item has `id`, `title`, supported open `status`, `priority`, nullable
`due_on`, nullable `owner_membership_id`, UTC-offset `created_at`/`updated_at`,
and `matter:{id,title,matter_code,status,is_active,lifecycle_version}`. It does
retain bounded nonempty String36 Task identities, including legacy non-UUID
keys; normal newly created keys remain UUIDs. It does
not supply mutation authority: opening/editing uses the existing authoritative
workspace and save/version fences. No description, private note or contact data
is copied merely to fill a list.

Eligibility requires current active tenant/actor, matching Task/Matter tenant,
no IP target, operational Matter, supported open Task status, no cancelled or
neutralized lifecycle history, the ownership predicate and canonical current
Matter ACL. All predicates precede ordering and `LIMIT limit+1`. Dated tasks are
ordered by due date ascending, then creation instant and unique Task ID; undated
tasks follow with the same creation/ID tie-break. This is a live keyset view, not
a snapshot across requests. New earlier items require an explicit fresh reload.

The authenticated/encrypted continuation binds company, membership, User,
ownership, date filters, limit and the exact last returned sort anchor. Cursor
TTL is one hour; its clock is local to this protocol and never changes auth time.
Invalid signature/scope/claims/expiry is400 `work_queue_cursor_invalid`. A missing,
now-ineligible or reordered anchor is409 `work_queue_cursor_stale`; the client
must discard that continuation and explicitly reload. It must not append stale
pages or silently retry a mutation. Current wall/grant/team/lifecycle policy is
evaluated anew for both anchor admission and every returned page.

Success and handled errors on this exact route are `private, no-store` with
`no-referrer`. All six existing tenant roles can read their currently visible
queue. There are no new grants, writes, provider requests, model columns or
indexes. Active-team query construction is extracted byte-equivalently from
the existing IP predicate into one shared statement-local materialized helper.

Required validation after the native resource window: complete new common and
PostgreSQL modules, independent actual collection/role counts, full changed SQL
observer coverage, and **existing complete IP policy/plan regressions** after the
helper extraction. Every introduced relation/CTE/loop and removed row is charged
under the unchanged400-work PostgreSQL plan bound. Existing owner indexes are
not evidence of that bound; default/adverse and opposite seed-order plans are
deliberately pending. No speculative index migration is part of this slice.

Separate future native supplement, not changes to the frozen23 core/17 Files:

| Proposed case | Actual boundary to prove on each rebuilt platform |
| --- | --- |
| MQ-01 | Mine includes future-dated and undated open Matter tasks; read-only roles get no invented save control. |
| MQ-02 | Active-team peers exclude Mine, Unassigned, inactive teams/people and otherwise visible non-team owners. |
| MQ-03 | More than25 tasks continue exactly across due/creation/ID ties and a retained legacy-ID anchor, then explicit reload. |
| MQ-04 | Grant, wall, team or anchor-order change invalidates the retained continuation; the client clears it and offers fresh reload. |
| MQ-05 | Disposed/reopened history and IP tasks remain outside this Matter queue; current source opens with its real identity/version. |

Those cases need new source/artifact/backend-bound fixtures, registered gateway
read routes and independent exact native inventory/reporting. None is executed,
registered into a live actor or covered by an existing40-case native claim.
