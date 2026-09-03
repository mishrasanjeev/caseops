# Ram 2026-07-15 Bug/Enhancement Audit And Permanent Reopen Learnings

> **Scope note, superseded in part on 2026-07-22.** The July 15 acceptance
> contract changed direct creation only and deliberately retained the
> Intake/On-hold activation gate. The July 22 workbook expands the policy:
> conflict review is optional and nonblocking for every creation and status
> transition path. The July 15 deployment evidence remains valid for its dated
> scope, but cannot close the July 22 enhancement. See
> `docs/BUG_REOPEN_LEARNINGS_2026-07-22_RAM.md`.

Source workbook: `CaseOps_Bugs_Ram15Jul2026.xlsx`
Audit date: 2026-07-15
Production tenant used for baseline: `legal` (the tester password is not stored
in the repository)

## Honest classification

| ID | Workbook area | Classification | Baseline evidence | Final verdict |
| --- | --- | --- | --- | --- |
| BUG-001 | Matter Management / Standalone Notice Module | Valid product enhancement; the requested boundary was never implemented | Production main navigation had no Notices entry and `/app/notices` returned 404. Existing documentation explicitly described the implementation as matter-scoped with no global dashboard. | `Properly fixed` on the deployed code commit, including the standalone, unlinked, assigned, multi-matter, file, search, filter, link-edit, and matter-visibility journeys. |
| BUG-002 | Matter Creation | Valid workflow/policy enhancement; current behavior was intentional but contradicted the new requirement | Production `POST /api/matters/` with `status=active` returned 409 directing users through Intake/conflict clearance. UI and schema defaulted to Intake. | `Properly fixed` on the deployed code commit: both UI creation and an API request omitting `status` created Active matters without a conflict-check gate. |
| Reopening investigation | Matter lifecycle | Valid systemic defect discovered during the requested adjacent-path audit | Disposed persistence had only been tested after reload in one session. Generic PATCH accepted terminal status and replayed the editor's full stale snapshot; background and operational paths did not consistently treat disposal as terminal. | `Properly fixed` on the deployed code commit, including stale-write rejection, terminal operational suppression, and invalidation of old conflict clearance. |

## Production baseline (before this change)

An authenticated Playwright baseline against the production `legal` tenant on
2026-07-15 established:

- login API: `200`
- main-navigation Notice links: `0`
- direct Active matter create: `409`, with the existing mandatory Intake and
  conflict-clearance message
- create in Intake: `200`
- generic PATCH to Disposed: `200`
- Disposed read-back immediately after PATCH: `disposed`
- `/app/notices`: `404`

This is baseline/reproduction evidence only. It does not prove the local changes
are deployed.

## Local verification evidence (candidate working tree)

The local replay began on 2026-07-15 and final regression shards completed on
2026-07-16, with the exact `legal` / Hari tester identity recreated in an
isolated workstation database. The supplied
password was injected only through the process environment and is not stored in
source or this report.

- complete **2,120-test API inventory collected** and covered through six
  disjoint product-final-tree shards plus the focused bug/database slice:
  **2,089 passed, 31 environment-gated skips, 0 failures**. This includes lifecycle,
  standalone notices, storage/audit, conflicts/imports, ethical walls/teams,
  Calendar/Today, Gmail/proceeding/document workers, reminders, deadlines, and
  task/deadline cockpit behavior. Counts from overlapping focused and shard
  runs are not added together;
- PostgreSQL-focused local checks: **13 environment-gated** because no local
  `CASEOPS_TEST_POSTGRES_URL` was available. They are not represented as local
  passes. The release's real PostgreSQL proof is the successful production
  `alembic upgrade head` execution recorded below;
- complete React/Vitest suite: **115 files, 540 tests passed**;
- API Ruff lint verification: **490 Python files passed** (the unrelated
  pre-existing untracked Cloud Run scheduler test was outside this batch);
- TypeScript route generation/typecheck: passed;
- optimized production web build: passed, including `/app/notices`;
- Alembic: exactly one head, `20260715_0001`;
- checked-in OpenAPI TypeScript contract regenerated from the live local
  FastAPI schema;
- local Playwright production-build replay:
  `tests/e2e/ram-2026-07-15-bugs.spec.ts` — **3/3 passed** with no mocks;
- regression-discovery runner: **5/5 passed**; both local and production
  configurations collect all **3** July 15 tests;
- the July local/production specs and the repaired June 27 lifecycle regression
  pass strict standalone TypeScript checking.

## Production release evidence

The code-bearing commit
`64f768826a28551bcd32120ef5bd259ff782063f` was pushed to `origin/main` and
released on 2026-07-17 through the repository's fail-fast production script.

- Cloud Build completed both commit-tagged images successfully;
- production migration execution `caseops-migrate-job-vmt2v` completed
  `alembic upgrade head` against the production PostgreSQL database;
- API revision `caseops-api-00204-5c6` and web revision
  `caseops-web-00183-cgc` received 100% traffic on tag `64f7688`;
- `https://api.caseops.ai/api/health` returned `{"status":"ok"}` and the public
  website returned HTTP 200 with the expected security headers;
- the ClamAV sidecar and deployed-image staleness checks passed;
- committed live, no-mock spec
  `tests/e2e/ram-2026-07-15-prod.spec.ts` passed **3/3** with the workbook's
  reporting account in the `test-legal` workspace. The run verified both
  workbook rows and the adjacent terminal-lifecycle regression, then closed
  notices and disposed created matters through supported audited workflows.

The only post-release test correction selected the matter page's **Notice
Sent** tab before asserting a sent global notice. The page had already shown a
count of one sent notice; the earlier assertion searched the default received
tab and was therefore a test-navigation defect, not a product defect.

## Brutal analysis: where the earlier work went wrong

### 1. We implemented a smaller feature than the acceptance contract

The earlier Notice work produced a useful per-matter tab, but the July 15
contract says **standalone**, **global**, **main navigation**, **independently**,
and **optionally link one or more matters**. The old implementation required a
matter and therefore could never create an unlinked notice or link one notice to
multiple matters. Calling the scoped tab a completed Notice module was a scope
substitution, not acceptance-contract delivery.

### 2. We tested implementation details instead of the user promise

Prior browser proof uploaded a notice from one matter. It did not assert that a
global page existed, that a notice could exist with zero matter links, or that
one notice could link multiple matters. Green tests therefore fossilized the
narrow implementation rather than protecting the reported workflow.

### 3. We hardened only one lifecycle edge

The conflict-check repair protected `Intake -> Active`, but generic matter PATCH
still accepted terminal status and `is_active`. Disposal and reopening did not
have a dedicated transition authority, reason, capability, or state matrix.
This is why a status could appear stable in a one-session reload test while the
system remained reopenable elsewhere.

### 4. The editor replayed a whole stale record

The matter detail editor copied all fields, including status, and sent them all
on every save. With no `expected_updated_at`/version check, the sequence was:

1. session A loads an Active matter;
2. session B disposes it;
3. session A changes only the title and saves its old full snapshot;
4. the old Active status is replayed.

The final status depended on old conflict data, but the architectural defect was
already present: an unrelated metadata save carried lifecycle authority.

### 5. Disposal was not an operational boundary

Tasks, deadlines, hearings, reminders, Today/calendar feeds, case tracking, and
court/provider jobs were not all reconciled or guarded consistently. Even when
the row remained `disposed`, operational children could continue to appear and
background updates could make the case look active again. A lifecycle fix that
checks only the matter row is shallow.

### 6. Regression registration was manual and drift-prone

Dated specs were manually enumerated in Playwright configuration. A committed
test could therefore be absent from the normal regression run. A test file that
is never selected is documentation, not a regression guard.

### 7. Local success was allowed to sound like production closure

The deployed commit identity and deployed browser pass were not always tied to
the verdict. The permanent rule is fail-closed: local unit/API/Playwright proof
can justify “locally implemented,” but the formal product verdict remains
`Inconclusive` until the committed spec passes against the observed deployed
build.

### 8. SQLite-only proof hid PostgreSQL and TOCTOU failures

The first local green run still was not enough. An adversarial review found
that the parent `FOR UPDATE` query eager-loaded nullable assignee/user joins;
PostgreSQL can reject that lock shape even though SQLite silently accepts it.
It also found several check-then-act races: an operational writer or provider
worker could read an Active matter, disposal could commit, and the stale writer
could then create a child, restore a sync row, or send a notification.

The permanent correction is two-part: lock the bare Matter row using a
PostgreSQL-safe statement, and require every long-running path to recheck the
fresh parent state under lock immediately before durable side effects. Where an
external side effect already occurred, compensate it rather than overwriting
the disposal state.

The same review exposed a second false-green mechanism: local SQLite
connections had never enabled `PRAGMA foreign_keys=ON`. The models declared
foreign keys, but SQLite silently accepted invalid tenant relationships during
local execution and tests. The connection setup now enables enforcement for
every SQLite connection, and regressions deliberately attempt cross-tenant
Notice ownership/linkage plus destructive Matter deletion. PostgreSQL remains
the release proof for the migration and lock behavior; SQLite is now a useful
early integrity check instead of a permissive imitation.

### 9. Invalid fixtures were mistaken for useful isolation

Enabling SQLite foreign keys immediately exposed tests that attached a queued
notification to a nonexistent rule and assigned a membership to a nonexistent
custom role. Those fixtures were not testing optional relationships; they were
silently creating impossible production rows. The corrected tests either seed
the real parent, omit a genuinely optional foreign key, or assert that the
database rejects the dangling reference.

The PostgreSQL legacy-data migration replay exposed a subtler version of the
same mistake: adding a Matter and scalar-ID children to one ORM unit of work did
not establish an in-memory relationship dependency, so PostgreSQL correctly
rejected a child inserted before its parent. Migration fixtures now commit valid
parents first and then children. A convenient `add_all` call is not proof of a
valid foreign-key fixture.

### 10. Targeted CAS tests missed repository-wide contract propagation

Making `expected_updated_at` mandatory correctly closed stale Matter writes,
but the first targeted lifecycle suite did not prove that every existing API,
UI, and E2E caller had adopted the new precondition. The complete suite found
legacy generic PATCH call sites that still sent the old payload. A mutation
precondition is not complete until a repository-wide call-site inventory and
static negative audit show that only intentional 422 tests omit it.

### 11. A terminal-create shortcut bypassed the state machine

One legacy GBA regression created a Matter directly with `status=closed` and
treated that setup shortcut as a valid lifecycle transition. Terminal aliases
must never enter through create, import, or generic metadata PATCH. Tests now
create an operational record and reach Disposed only through the dedicated
lifecycle endpoint, with its capability, reason, source-state, and concurrency
checks.

### 12. Reopen trusted legacy terminal rows to have been neutralized

The disposal transition now cancels open tasks, deadlines, hearings, reminders,
sync work, and notification intents, but that alone did not repair Matters that
were already `closed`/`disposed` before the invariant existed. A legacy terminal
row could still contain open operational children. Reopening that parent to
Intake made the old children visible and actionable again even though no new
child had been created.

The correction is deliberately redundant: the migration neutralizes existing
terminal data and durable-tombstones their already-synced provider calendar
events; the Disposed-to-Intake transition repeats neutralization under the
Matter lock before changing status. Migration and lifecycle regressions seed
legacy open children and prove neither the children nor their external calendar
artifacts can resurrect.

### 13. The operational boundary was duplicated instead of structural

Many services correctly checked tenant access yet had no shared answer to a
different question: may this Matter still receive operational work? The missed
seams included client and outside-counsel portal writes, Drive review, outside-
counsel spend, attachment Q&A/export, annotations, hearing coaching, AI and
intelligence generation, recommendation persistence, tags, statute references,
matter notification rules, legal-update watchlists, and contract linking.

All operational writers now use one fail-closed definition: the status must be
Intake, Active, or On Hold **and** `is_active` must be true. Writers reload the
bare parent with `populate_existing` and lock it before child mutation;
multi-parent operations lock sorted Matter IDs. Historical reads, explicit
cleanup, security governance, and post-disposal financial settlement remain
available only where that policy is intentional and tested.

### 14. An intermediate commit silently invalidated an earlier lock

Recommendation generation acquired the correct Matter lock at entry, but the
authority bench-rerank branch committed its diagnostic ModelRun before calling
the provider. That commit released the lock. A disposal could then win during
the provider call and the request could still save a final ModelRun,
Recommendation, options, and audit.

An entry guard is therefore not proof across a commit or external-provider
boundary. Long-running flows now re-read and lock the parent immediately before
durable output. Provider-callback race regressions interpose disposal and assert
that no output, child, final ModelRun, or audit survives.

## Corrective design

### Standalone Notice Management

- tenant-scoped notice record independent of MatterAttachment
- zero, one, or multiple matter links
- main-navigation `/app/notices` workflow
- received/sent direction, owner assignment, workflow status, dates, authority,
  source, monetary metadata, summary/remarks, search and filters
- file upload/download with the existing storage security and quota controls
- legacy matter-scoped notice documents visible from the global workflow without
  unsafe automatic migration or duplication
- tenant and restricted-matter visibility enforced server-side

### Matter creation policy (historical July 15 contract)

- omitted status and the New Matter UI default to Active
- direct Active creation is allowed without a conflict check
- Conflict Check remains available and useful, but it is not a mandatory intake
  gate for a newly created matter
- explicit transitions from Intake/On hold to Active retain the conflict gate
- adjacent create/import paths are audited so defaults do not drift

The preceding transition-gate bullet records the July 15 contract and is
superseded. Effective 2026-07-22, missing, pending, conflicted, cleared, waived,
invalid, stale-scope, and pre-reopen results are all nonblocking. Conflict
checks remain available as auditable review evidence.

### Terminal matter lifecycle

- generic metadata PATCH sends dirty fields only, requires a timestamp
  precondition, and cannot dispose, reopen, change `is_active`, or edit a
  disposed matter
- dedicated lifecycle endpoint requires `matters:archive`, source status,
  timestamp, and reason
- disposal is non-terminal-to-Disposed only; reopen is Disposed-to-Intake only
- reopen invalidates prior conflict clearance as current evidence; the July 15
  requirement for a fresh check before Active is superseded, so the historical
  result and the absence of a new one do not block activation
- disposal reconciles operational children and blocks later background writes
- migration and reopen both neutralize legacy open children so old work cannot
  resurrect
- every operational child writer uses the shared fresh-parent guard, with a
  post-provider recheck where work crosses an external boundary
- explicit Dispose/Reopen UI replaces the terminal dropdown option

## Mandatory regression matrix

| Layer | Required assertion |
| --- | --- |
| API | notice zero-link create, multi-link create/update, search/filter/assignment, legacy visibility, tenant/restricted-matter isolation, file security |
| API | omitted/explicit Active matter create succeeds; Intake/On-hold activation succeeds with no check and with pending/conflicted/stale/pre-reopen results |
| API | generic terminal/status/is_active writes fail; stale metadata write fails 409; lifecycle capability/reason/status/timestamp enforced |
| API inventory | every non-negative generic Matter PATCH caller supplies the concurrency token; repository-wide static audit has no silent legacy payloads |
| DB integrity | SQLite FK-on negative controls and fresh PostgreSQL migration/constraint proof reject dangling parents and cross-tenant Notice ownership/linkage |
| Entry paths | create/import/generic PATCH cannot enter a terminal state or use a terminal alias; terminal entry occurs only through the lifecycle service |
| API/jobs | queued provider/court tracking update cannot mutate a disposed matter; disposed operational children are cancelled/hidden |
| API/writer inventory | portal, integration, AI/provider, metadata, watchlist, assignment, and linked-record writes all use the shared operational definition; intentional read/cleanup/settlement exceptions are named |
| API/races | disposal interposed during provider/matching work leaves no child, final ModelRun, notification intent, or audit; multi-parent mutations lock parents in deterministic order |
| Migration/reopen | legacy terminal rows with open tasks/deadlines/hearings are neutralized on upgrade and again before reopen; the old children never reactivate |
| React | global Notice page contract, Active default, dirty-field PATCH, explicit Dispose/Reopen dialog, stale-write error |
| Playwright local | the exact two workbook journeys plus two-session stale-write/reopen workflow with final read-back |
| Playwright production | the same committed user workflows on the deployed commit; no mocks or conditional skips count as proof |
| Discovery | new dated specs are selected by the normal local/production configurations |

## Permanent repository changes

- `.codex/skills/bug-fixing/SKILL.md` now codifies feature-boundary tracing,
  lifecycle state-machine/CAS/side-effect rules, and mandatory two-session tests.
- `docs/runbooks/release-signoff-template.md` now requires acceptance-contract,
  lifecycle concurrency, terminal side-effect, regression-discovery, and
  deployed-workflow evidence.
- `docs/STRICT_BUG_TASKLIST_2026-04-22.md` records this batch and keeps formal
  production verdicts fail-closed.
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` tracks lifecycle concurrency and
  regression-discovery hardening as platform invariants.

## Closure for this batch

The local API, React, typecheck/build, Alembic, and Playwright gates passed; the
code commit was pushed and deployed; deployed image identity and health were
proven; and the committed production spec passed with the supplied reporting
account. BUG-001, BUG-002, and the adjacent lifecycle defect therefore met the
repository's `Properly fixed` standard **for the July 15 acceptance scope**.
This is not closure evidence for the July 22 nonblocking-transition policy.

## 2026-07-17 reopen audit addendum: BUG-002 default drift

The July 17 workbook repeated BUG-002. Its reported date is July 15, before the
corrected production release, so the original user journey is not a new
post-release recurrence. The repeat nevertheless exposed that this document's
earlier claim that adjacent creation paths were fully protected was too broad.

The prior correction changed the React form and `MatterCreateRequest`, and its
browser/API regression exercised those two boundaries. It did **not** change
the `Matter.status` ORM default, which remained `intake`; the database column
had no server default. Any future background producer, maintenance script, or
direct database insert that omitted status could therefore recreate the old
behavior without touching either green test. Marketing and guide copy also
continued to state the pre-change policy. That is a systemic default drift, not
an acceptable implementation detail.

Permanent correction and learning:

1. A product default must have one named domain constant and be aligned at the
   schema, service/import, ORM, database-migration, UI, documentation, and
   browser-test layers.
2. Intentional exceptions must be explicit. Intake promotion passes `intake`
   deliberately and has a regression proving the linked matter remains Intake;
   missing status is never used to express business intent.
3. A browser test may not use a button's eventual enabled state as an implicit
   network-readiness check. The production test now waits for the selected
   structured-forum value, so a slow or failed catalog produces an actionable
   failure instead of a timing-dependent false green/red.
4. Release evidence must name the account and release timestamp. A workbook
   row reported before deployment is baseline evidence; only a reproduction on
   the deployed build can establish a reopen.
5. “Cases reopening” and “bugs reopening” are separate questions. Matter rows
   cannot reopen through generic PATCH or background work; only the dedicated
   Disposed-to-Intake lifecycle endpoint, with archive capability, source-state
   and timestamp compare-and-swap, and a reason, may reopen one. BUG-002
   resurfaced because verification stopped at two boundaries, not because a
   disposed Matter was automatically reactivated.

## 2026-07-22 policy supersession addendum

Ram's July 22 workbook explicitly requires an Intake or On-hold matter to move
to Active without completing a conflict check. That is a valid product-policy
enhancement, not a regression against the July 15 implementation: July 15 only
exempted direct creation and explicitly retained the later activation gate.

The durable contract is now:

- conflict scanning, candidate review, clear/conflict/waive decisions, tenant
  scoping, and audit provenance remain available;
- no conflict-check state can block matter creation or a status transition;
- reopen still lands in Intake and still marks pre-reopen clearance historical,
  but neither condition requires a fresh check before Active;
- a fresh check is required only before representing the matter as currently
  conflict-cleared; and
- the formal July 22 verdict remains `Inconclusive` until the committed
  production Playwright spec passes on the deployed build identity.
