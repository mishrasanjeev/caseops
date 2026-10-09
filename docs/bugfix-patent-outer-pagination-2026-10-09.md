# Patent Outer Pagination - October 9

## Verdict

**NO-GO** for PR #525 candidate
`82ccf412ec9a4f542b1de00e32b6ae562208e2fb` (tree
`08b1a2c2bfec315eb86bbeab43225fccee02da74`). It is not merged or deployed.
At 01:17 UTC, production API and web still report
`b20f86bddeecf985fc961012bb93fa2c41889c49`, revisions
`caseops-api-00486-g44` and `caseops-web-00463-bt5`.
Scope: existing UJ-29/PAT-01 pagination and current authorization; no new
patent capability, provider activation, or workbook issue is introduced.

## Retained Acceptance

- CI `37760070637`, security `37760070496`, and CodeQL `37760070524` pass
  on `82ccf412`. The independently reconciled CI PostgreSQL inventory has
  1,931 passing identities. This does not supersede the later Docker failure.
- Docker r1 completes PostgreSQL with 1,931 passes. Browser desktop group 1
  passes 246 with one known skip. Group 2 has 197 passes, two failures, six
  known skips and nineteen unstarted cases; four mobile cases never run.
  Both failing traces retain independent setup/transport diagnoses during
  confirmed workstation standby/hibernation. Neither proves a hearing or
  billing fix, and this is not complete browser acceptance.
- Docker r2 is interrupted without a session completion: 876 passing calls,
  877 setups and 876 teardowns. It is incomplete, not green.
- Standalone Docker r3 finishes PostgreSQL with **1,930 passed / one failed**,
  zero skips, in 3,035.21 seconds. All 1,931 ordered collection/call/XML
  identities and 5,793 phases reconcile. The only failed phase is the
  original 10,000-family scale test. Browser execution does not start.
  Launcher exits 1 at 01:31:58 UTC and its isolated compose resources are
  removed; the failed evidence remains intact.

Evidence is under `.tmp/release-followup-20261009/`: distinct
`docker-82ccf412-r1`, `-r2`, and `-r3` directories and logs; the complete r3
audit is `pg-audit-r3-final-20261009T013143172086Z-3677268c/summary.json`.
The earlier failed plans are separately preserved in
`patent-outer-counterexample-20261009T011408852Z/`.

## Confirmed Cause

`test_patent_family_list_10000_rows_has_bounded_queries_and_acl_on_postgres`
fails the unchanged buffer bound, not its statement timeout. Its generic
101-row plan reads **10,001 full family rows**, using
`uq_patent_family_company_asset` with a 54-row estimate, then sorts the
tenant before applying the authorized page. Family scanning consumes 10,134
buffers; docket/policy work adds 1,303, totaling **11,437**, above the
original `<10,000` bound. Docket identity work itself remains bounded at 200
unique probes. Custom plans pass; they do not establish generic-plan safety.

The existing `(company_id, id)` cursor index is already declared, migrated
and checked by Docker index health. Adding the same index is not a repair.
The previous unique-docket fix repaired the inner repeated tenant scan but
left the wide outer-family scan vulnerable to stale mixed-tenant statistics.
Earlier local and hosted passes were limited samples, not permanent closure.
The failed test stops before its generic-one-row and later pagination/search
assertions; those outcomes remain unverified in r3.

## Required Replacement

Keep the ordered tenant key stream narrow, resolve unique family/docket
identities with bounded work, apply the unchanged canonical current ACL,
lifecycle and search predicates before the page limit, then hydrate only the
admitted family/current-version page. Never cap raw candidates before policy
or drop a late selective match. Preserve team/grant windows, ethical-wall
precedence, owner restrictions, tenant identity, source access/hash checks,
cursor progress, post-selection reauthorization and terminal-state fences.

Regression must retain custom/generic plans for limits 101 and 1, explicitly
bound outer-family work as well as docket work, preserve total work/buffer/
statement/deadline limits, and reproduce mixed-tenant stale statistics with
fresh import identities. A later fast plan cannot erase the failed one.
## Local Replacement (Limited Checkpoint)

The complete replacement gate passes **89/89**, zero skips, in 450.16 seconds.
Its three complete selected files are `test_ip_patent_postgres.py`,
`test_ip_patent_families.py` and `test_ip_patent_contracts.py`; all 89 ordered
collection/call identities, 267 passing phases and successful completion are
independently reconciled. This is a scoped gate, not full Docker or production.
Worker evidence: `.tmp/outer-page-bound-20261009/frozen-files-10.*` and
`frozen-reconciliation-10.json` in the isolated replacement worktree.

The PostgreSQL path uses a narrow ordered tenant-key stream, a runtime-bound
tenant expression and an unbounded NULL-limit planning barrier. The family and
docket identity/policy checks stay in correlated scalars, not a reorderable
outer LATERAL join. Only the admitted page is hydrated; hydration refreshes
existing ORM instances and compares fresh family-to-docket identities.
SQLite retains its uncapped ordered policy path. There is no new index,
session planner setting, raw-candidate cap, retry or increased deadline.
PostgreSQL documents a NULL LIMIT as no limit:
[LIMIT and OFFSET](https://www.postgresql.org/docs/current/queries-limit.html).
Planner behavior itself remains regression-tested, not a semantic guarantee
that every future server version must choose one named index.

All **32 page plans** (four scales, first/cursor pages, custom/generic, limits
101/1) and **16 hydration plans** pass actual-work bounds. Maximum page buffers
are 2,330, family raw work 404, and docket raw work 202. Every hydration examines
100 family rows or fewer. Each scale traverses its complete sorted 5,001
authorized identities with no omissions/duplicates and proves the late search
match. Warm-session retarget, deletion and grant-revocation races fail closed.
Existing owner/team/grant/wall, lifecycle and contract cases remain included.

Retained intermediate failures include the reorderable LATERAL experiment and
newly overconstrained synthetic old-plan/index-name assertions. A favorable
old outer shape is now recorded diagnostically, not required to be slow on
every run. Positive replacement plans must still satisfy unchanged original
buffer/work/deadline limits and stronger family/hydration bounds; a diagnostic
never substitutes for them. The original r3 failed plan remains authoritative.

Main integrated byte-identical files and scoped Ruff passes. Runtime SHA256:
`5d0e41af34c9295cb98be15abd20662965ade86d44f4c3cb0e7d0bee7336685a`;
test SHA256:
`c0125d68b4a52d581c4df8b5da8c1f6c76f641e4d0592bed764aacc084c2a5a0`.
These hashes identify the earlier local replacement bytes, not a released
commit or the later retained-history repair.

## Retained-History Counterexamples

The later retained worker replay fails total executor work at 5,054,547:
25,013 active grants are scanned by a global revoked-at bitmap 202 times.
The 89-pass checkpoint therefore cannot close performance acceptance.

A new independently migrated standard-suite regression,
`test_patent_family_list_retained_grants_bound_authorization_work`, retains
two foreign 10,000-family imports after training old grant statistics. Its
baseline completes with setup/teardown passing and the call failing: the
global family primary-key scan examines 20,402 rows for a 101-result page,
or 10,004 for one result. Equal tenant-range bounds and company/id ordering
repair this separate outer scan without changing tenant equality or capping
candidates.

Separating exact membership/team ACL probes preserves policy but is not
sufficient by itself. Retained r2/r3 fail at 503,304 total executor work;
r3's membership-only grant index removes 2,501 rows per 200 probes and uses
21,911 buffers. The range-order ACL experiment r4 also fails, at 1,008,320
total work and 41,012 buffers. These failed experiments remain evidence,
not successful fixes. r2 retains completed JUnit only (the intended journal
environment variable was incorrect); r3/r4 retain full phase journals and
plans. Baseline/r2/r3/r4 are separate files in
`.tmp/acl-key-bound-20261009/`; no failed artifact is overwritten.

InitPlan membership binding and explicit partial-index predicates in r5/r6
also fail the unchanged total-work bound; those complete journals remain
retained. The final lookup instead seeks the first unrevoked `(docket,
subject)` pair at or after the requested key, then requires both exact
identities and the existing effective/expiry windows. The existing partial
uniqueness constraint makes this one active pair, not a history/candidate cap.
An absent pair's successor cannot admit or wall the requested record. Member
and uncapped active-team probes share this implementation; owners still have
no IP bypass, and linked Matter access remains independent.

Complete affected-file r8 passes **112/112**, zero skips, in 301.95 seconds:
the previous three files plus full record-access foundation and workflow
files. All 112 ordered collection/call/XML identities, 336 passing phases and
successful completion reconcile. All five scale cases pass **40 page plans
and 20 hydration plans**, including custom/generic first/cursor pages at
limits 101/1. Maximum page total executor work is 3,923 and buffers 3,451,
without relaxing any bound. Each scale preserves all 5,001 authorized IDs
and the late selective match. Membership/team window, revocation, active-team,
owner/wall, lifecycle and warm-identity regressions remain included.

Independent review found no policy defect but identified that a random-ID
negative could lack a successor. The added deterministic PostgreSQL regression
creates valid adjacent target IDs, positively proves wrong-subject and
wrong-target successors for all four grant/wall membership/team probes,
requires rejection and preserves exact-pair positive controls. Supplement r9
passes this case with all three phases and successful completion. Final
lint-clean supplement r10 passes the same regression again; scoped Ruff and
`git diff --check` pass. Exact-commit Docker/CI gates still follow.

Evidence: `.tmp/acl-key-bound-20261009/repair-full-r8.*`, `successor-r9.*`
and the explicitly diagnostic, non-acceptance `probe-r7.log`.
These local scopes do not establish complete Docker or production acceptance.

Require a new clean committed candidate, full Docker PostgreSQL and all three
browser groups, green PR and merged-main CI, identical accepted/merged trees,
guarded current-main deployment and exact-serving-release production replay.
After mutation-capable QA stops, require two clean exact-image maintenance
executions, with zero rebuild on the second, before guarded cadence resume.
Calendar BUG-003/004 remain **Inconclusive** pending actual Google consent and
positive production connection/reload proof. No timeout, retry, privacy,
paid-provider, lifecycle or private-projection fence is weakened.

## Merged-Main Counterexample

The complete `df6c971f` Docker and PR-CI gates passed and PR #525 merged as
`47e3554c` with an identical tree. Merged-main CI `37889146392` then exposed
a remaining custom cursor failure: the global `(id, company)` index scans
9803 keys and sorts before returning the next page. First-page and generic
cursor plans remain bounded, so their green outcomes cannot close this defect.
The new deterministic pre-import ID-histogram regression reproduces the same
10005-work bound failure before repair. Preserve every earlier result and
follow `docs/bugfix-patent-cursor-plan-2026-10-09.md` for the separate narrow
cursor repair and fresh acceptance. Production still serves `b20f86bd`.
