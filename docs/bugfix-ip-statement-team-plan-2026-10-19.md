# Statement-Local IP Team Evaluation

## Status

**Release NO-GO. Candidate implemented; replacement gates and production proof
remain pending.** This is the canonical IP access owner, IPLF-090/091 and
UJ-30/41, not a new import admission or legal-source rule.

PR546/C6 `a78992bc` had earlier accepted hosted plans and bounded individual
docket probes. Newer CI on PR547 `09b96c39`, with identical specialist runtime
and test bytes, failed continuation work2109 >2048. That failure supersedes
earlier random-fixture green. PR546 is draft; the corrected combined candidate
is intended for PR547, not a separate C6 deployment. Last observed production
API/web remains `9cf76f2b`.

## Cause And Reproduction

CI39204491380 native shard13 completed201 cases:200 passed/one failed, all
setup/teardown passed. Its four actual plans had work1176/1556/1589/2109 for
empty first/next and inactive first/next. The final plan used79 indexed docket
probes, but repeated the same actor's inactive-team eligibility per candidate
in wall/grant branches. The earlier390055-work tenant/status scan did not
return; the existing one-key docket barrier remains necessary.

The old fixture alternated grants by insertion offset while pagination sorted
random specialist UUIDs. That did not establish actual first/next visibility.
Random docket order also changed successor-probe row averages. Earlier green
therefore did not prove a stable bound.

The replacement keeps10000 clones plus the original record and5000 cloned
grants plus the original grant. Record/docket UUID integer ranks sort before
their seeds, with asserted headroom, exact persisted order/count, result IDs
and cursors. Balanced and hidden-next layouts retain every original query,
five-second timeout,2048-work,128-probe and no-version-history assertion.
Hidden-next returns ordinals25,79..102 after cursor24, with lookahead103:
26 authorized candidates among79 raw candidates, including53 hidden rows.
No page cap is introduced before authorization.

Fresh PostgreSQL `specialist-variance-native-red-04` completed naturally with
one pass/one failed call, both setup/teardown passed, stable source and owned
resource cleanup. Exact-ID/cursor and10001-record/5001-grant checks passed.
All eight actual plans were retained:

| Layout | Empty first | Empty next | Inactive first | Inactive next |
| --- | ---: | ---: | ---: | ---: |
| Balanced |1279|1095|1636|1459|
| Hidden next |679|1793|861|2346|

The final2346 >2048 is the deterministic product RED. Earlier local attempts
remain retained and are not described as performance reproductions:

- red01 failed before tests because the internal Docker network exposed no
  host PostgreSQL binding. No tests executed; owned resources were removed.
- red02 completed25P/1F. An empty grant batch issued DEFAULT INSERT and violated
  the subject constraint. Empty batches now issue no INSERT. This was setup.
- red03 failed two UUID-object versus string expected-ID oracles before the
  continuation. Canonical string comparison retains exact expected identities.

## Candidate Correction

The canonical `visible_ip_dockets_filter` keeps the same actor, tenant,
Team PK successor, exact identity/active eligibility, grant/wall subjects,
revocation/effective windows and wall precedence. The unchanged active-team
SELECT becomes one anonymous CTE reused by both branches. PostgreSQL alone
receives MATERIALIZED; SQLite uses the same unhinted CTE. There is no Python,
session or cross-request cache, extra query, owner bypass, new policy argument,
planner setting, retry, timeout increase or budget change.

Four actual compiler cases passed for adapted active/closed specialist lists
and PostgreSQL/SQLite syntax. New intended PostgreSQL security cases compose
two actor/tenant predicates and reuse the same prebuilt statement across a
separately committed team, membership, grant or wall change plus restoration,
while stale ORM objects remain loaded. These are security controls, not alleged
old-policy failures. Green02 passed those seven cases, all eight ordered plans,
and40 of41 native cases. One old stale-statistics test wrapper omitted the new
fixture argument and failed before its query; that failed run remains retained,
not a complete gate. The wrapper now explicitly covers both layouts.

Green02's balanced plan work is1207/1018/1214/1025; hidden-next is
680/1635/687/1642. All remain below2048, including the unchanged79-probe
continuation; base Team/TeamMembership lookups execute at most once there.
No passing sibling is used to erase the wrapper failure. An earlier Green01
collection requested non-PostgreSQL compiler cases under the native runner's
PostgreSQL marker and correctly refused its incomplete file inventory before
executing tests. The four compiler cases passed separately; they are not part
of the native module count.

Green03 completed naturally on October19 at06:42UTC:42/42 cases in all three
intended PostgreSQL modules,126 passed setup/call/teardown phases, zero skips,
errors or failures. Ordered collection and JUnit agree; before/after complete
source snapshots agree, the child was reaped and its owned database/network
were removed. Parent acceptance SHA256 is
`1ad26f63fca902f5ea63bdcc55b53df8db5f7332408a437d4813e12cc229dc7a`.
The16 actual normal/stale-statistics plans remain retained:

| Statistics/layout | Empty first | Empty next | Inactive first | Inactive next |
| --- | ---: | ---: | ---: | ---: |
| Normal/balanced |1205|1018|1212|1025|
| Normal/hidden next |680|1635|687|1642|
| Stale/balanced |1127|940|1134|947|
| Stale/hidden next |680|1635|687|1642|

Every original2048-work and128-probe bound remains unchanged. Hidden-next
still examines79 candidates. The seven composition/committed-change cases
also passed. This is complete focused acceptance, not whole-product or
production certification; earlier failed evidence remains immutable.

Final test-integrity review identified one adapter-specific positive coverage
gap: the specialist parity fixture still had its creator's direct grant.
The additional `sole_team_grant` scenario explicitly revokes it, asserts zero
active direct grants, and proves canonical/list agreement through sole-team
admission, team deactivation/restoration, membership removal/restoration, grant
revocation/restoration, dedicated closure, retained include_closed reading and
final revocation. The isolated `team-alias-01` PostgreSQL run passed that one
case/all three phases at06:50UTC with natural exit0, unchanged source and owned
resource cleanup. Green03 remains its original42-case snapshot, not relabeled
as43. No runtime bytes changed after Green03. Full canonical gates must execute
the final test inventory including this added scenario.

Because policy is shared, specialist performance alone cannot certify it.
Adjacent patent/portfolio/private/recipient policy owners,
fresh full Docker, complete hosted inventories, protected merge, guarded
exact-SHA deployment and exact-serving browser acceptance remain required.
Earlier C6 results cannot certify the changed backend.

BUG008 frontend bytes and its five-case focused browser proof are unchanged,
but that proof does not certify the new backend. No client upload, entitlement,
provider policy, reviewed legal datum or owner-deferred Google cleanup is changed.
