# Patent Cursor Plan Follow-Up

## Verdict And Scope

Not fixed in production; release NO-GO pending complete replacement gates.
Existing UJ-29/PAT-01, M02/M08/M13/M14: ordered authorized patent-family reads,
not new patent automation or a module-completion claim. Production still serves
`b20f86bd`. Calendar BUG-003/004 remain Inconclusive pending actual Google
consent, callback, committed connection and reload.

## Preserved Counterexamples

PR #525 merged as `47e3554cf0972a1bc3a3ae6af51f253a634b10d2`; its tree is
byte-identical to Docker-accepted `df6c971f`. Docker had 1938 PostgreSQL passes
and three complete native browser groups: 467 passes / eight exact known skips.
PR CI was green. No failed prior experiment was erased or transferred.

Merged-main CI `37889146392`, PostgreSQL shard 2/4, fails
`test_patent_family_list_retained_grants_bound_authorization_work` with 484
sibling passes. Its full eight page plans distinguish the cause: custom
first-page and generic cursor plans use the ordered tenant index, but the
custom cursor chooses `uq_patent_family_id_company` and a blocking Sort. It
scans 9803 family keys; family work is 10005 at limit 101 and 9805 at limit 1.
The unchanged bound is `4 * limit + 4`, not a timing-only assertion.

The independently migrated new regression
`test_patent_family_list_stale_low_id_histogram_bounds_cursor_work` disables
background analysis only in its disposable fixture, seeds 1000 fixed low keys,
analyzes and positively asserts 1001 rows with maximum ID below the later
import. It then imports 10000 deterministic higher keys. Baseline local
`pre-fix-r2` has successful setup/teardown and a failing call with the same
10005-work counterexample. The first local attempt `pre-fix-r1` is a retained
database-connectivity setup failure, not product reproduction.

## Root Cause And Repair

The prior repair bound tenant selection but still exposed the cursor literal
to a custom planner's stale histogram. The planner estimated almost no rows
beyond that literal and preferred a global seek plus full sort. Random UUID
fixtures could miss this state while all generic plans passed. That incomplete
adversarial-data coverage, not a license to raise bounds or retry CI, is the
learning from the earlier green checkpoint.

The already validated cursor becomes an InitPlan scalar on PostgreSQL, like
the existing runtime tenant key. This preserves the ordered tenant seek even
when the literal exceeds the stale histogram. SQLite stays unchanged. There
is no new index, migration, raw-candidate limit, timeout, provider call or ACL
shortcut. Canonical authorization still precedes page admission; hydration
still rechecks current identities, lifecycle and source rows.

Local `fixed-r1` passes the identical regression: one case, zero skips, all
three phases and completion, in 19.65 seconds. It preserves all 5001 authorized
IDs, monotonic full pagination and the late selective match; all eight custom/
generic first/cursor page plans and four hydration plans retain original bounds.
The complete five affected-file gate `full-targeted-r1` passed all 114 cases
with zero skips, in 286.01 seconds. Its native launcher completed with exit 0;
source hashes were unchanged. Independent reconciliation confirms all 114
ordered collected identities, 342 passing phases and 114 matching JUnit cases.
No full-release claim is made.
Evidence is retained under `.tmp/cursor-plan-20261009/` with unique journals,
JUnit, source hashes, native logs and start/completion records.

## Verification Transport Follow-Up

The earlier Docker browser audit also found 37 discovery rows / 38 title
components corrupted by PowerShell 5 decoding UTF-8 stdout as OEM CP437.
All ordered IDs, native execution identities, JSON/XML outcomes and source
pins were intact. The original failed audit remains preserved; an independently
reviewed strict reversible listing-only adapter reconciled it without changing
evidence. The repaired source wrapper retains the reporter's direct UTF-8
file, refuses an existing inventory and restores inherited output settings.
Native Windows PowerShell 5 plus the actual installed Playwright reproduces
five corrupted titles on the old wrapper and preserves all five with the fix
under code page 437. The 42 repository-root guard cases and four candidate
source guard cases pass; the canonical selected pytest file has two collected
passes, six phases, matching JUnit, no skips and completion exit 0. Missing,
empty, malformed, wrong-encoding, executed-discovery, empty-selection and
reporter-override cases remain fail-closed. Earlier harness attempts remain
under unique `verification-transport-20261009-r1` through `r3` paths; final
scoped proof is `r4`. This is test-transport correctness, not another product
or provider defect. Fresh Docker must still prove unchanged identities without
the prior discovery-only codec adapter.

## Required Gates

Require complete affected-file and PostgreSQL scale reconciliation, wrapper
guards, a clean committed candidate, fresh full Docker, green PR and merged-main
CI, identical accepted/merged trees, guarded current-main deployment and the
exact-serving-release production Playwright inventory. After all mutation QA
stops, require two clean exact-image maintenance executions (second rebuild
count zero), then the evidence-checked scheduler resume. Skips and real Google
consent remain explicitly unverified; no privacy or legal-source fence changes.
