# Portfolio provenance query repair — October 29, 2026

Verdict: **Not fixed**. The original work-bound failure is reproduced and the
first focused source candidate failed its replacement verification. Further
PostgreSQL, SQLite, CI and user-visible export verification remain required.
Release remains NO-GO.
This work belongs to IPLF-030B/UJ-04 and PR #558's current CI blocker; it does
not certify the Android or iOS native inventories.

CI `40856126534`, PostgreSQL shard 22 at `108a2215`, had 116 passes and one
failure in
`test_minimal_page_query_count_is_page_bounded_and_ignores_retained_history`.
Its original `4 * 201 + 16 = 820` provenance-work assertion failed. The
verified nine-file CI archive did not include the plans written under pytest's
temporary directory. That historical plan is unavailable; no exact historical
index choice is inferred from its error text.

A fresh PostgreSQL 17 instance with normal migrations reproduced the same
assertion on the unchanged API source at `66ded373`. Both ordinary and adverse
transaction-local plans were retained for all five statements. In the
200-record page's date-details query, the import-row primary key visited one
row per candidate, while the nested audit proof used the company/action index
and returned one row after filtering 100 per iteration. The actual aggregate
was `200 + (1 + 100) * 200 = 20,400`, above 820. The continuation's corresponding
work was two. The actual catalog contains valid target-ID and docket-ID audit
indexes; this is not evidence of a missing index.

The first source candidate required two independent EXISTS predicates keyed to the same
current version's JSON source-row ID: an import row in the tenant and the
exact materialization audit with that tenant, action, target type, source ID
and docket ID. Scoped date-fact and page-detail readers supply their already
authorized tenant as a literal. The per-docket tenant fallback remains for
global callers. Source-ID length, current-version selection, manual clear and
manual-date precedence, date validation and every access predicate remain.
That candidate changed no migration, index, production planner setting or bound.

The first source candidate did not resolve either observed work path. Its
replacement run completed fourteen cases (twelve passes, two failures), then
the retained-scale case's call was interrupted at the original host deadline;
four later cases were unreached and session completion was absent. The default
and adverse 200-row plans still inspected 20,400 provenance rows. The
retained-width/date-category query inspected 1,396 relation rows against 228:
51 import lookups plus a bitmap scan of 1,345 tenant audit events. Including
the owning bitmap index made that work 2,741. The independent EXISTS shape and
trusted tenant parameter therefore are not a resolved performance repair.
All six source files from that failed candidate and its actual plans are
retained separately before further edits.

A second candidate is implemented but unverified. It adds one nonunique
covering index over `(company_id, target_id, ip_docket_id, action, target_type,
id)` and uses correlated scalar `SELECT id LIMIT 1 IS NOT NULL` for each proof.
Every tenant/source/docket/action/type predicate stays inside the lookup. The
full index avoids a partial-index assumption about bound action/type values in
generic prepared plans. Scalar lookups are intended to avoid the observed
tenant-wide hashed alternative; actual plans must prove the result. The source
row still uses its primary key. No row, policy, manual date or bound changes.

The index uses the canonical concurrent PostgreSQL migration pattern with
strict name/shape/ready/valid checks, same-shape interrupted-index recovery and
the existing lock budgets. SQLite uses the same full index. Exact-parent
downgrade preserves the complete retained catalog and rows. Model parity, the
reviewed governance map and its generated/compiled projections are updated;
both source validators passed. Canonical-main changed-migration preflight
passed on committed `717fa8f6`; the next committed source needs its own binding.
Upgrade/downgrade/index-health and complete product verification remain open.

Candidate two's bounded PostgreSQL component completed ten cases: nine passed
and the 200-record page failed. Its default, adverse and actual generic plans
all still measured 20,400 relation work and 20,800 including proof limits,
against 820. All generic result tuples matched, with two generic and zero
custom plans. The retained-width/date-category case passed all three profiles:
its source work was 106/212 or 102/204 against 228. Keep that row-specific pass;
it does not close the component. Retained-scale was interrupted after setup,
and both source-fact cases were unreached. Its first post-fixture artifact
directory was absent, so the active API operation is unknown. The completed
sibling's 1,345-record fixture journey took 126.024 seconds; the minimal-page
case took 21.928 seconds. Separate bounded dated components preserve every
case and its original query/interactive limits; no all-case 419-second pass is
claimed.

A separately authorized cold catalog read observed the index valid and ready,
with all six exact standard B-tree keys, in the retained invocation's base and
retained-scale child databases at revision `20261029_0001`. The minimal case's
database had been dropped; its index presence is supported by canonical
template cloning and upgrade logs, not an explicit historical catalog read.
The cold read's catalog/source/cleanup components passed; its final exclusive
output path collided with the earlier diagnostic, leaving that controller
incomplete. Both failures remain retained. Startup WAL/checkpoint writes were
explicitly authorized; no claim of an unchanged raw data volume is made.

Candidate three adds only deterministic `ORDER BY audit_events.id` before the
existing complete-predicate scalar limit. The covering index can supply that
order; actual plans must establish whether the optimizer chooses bounded work.
No ordering hint, production ANALYZE, policy change or larger bound is used.

The existing export-plan regression now collects ordinary, adverse and generic
(`SET LOCAL enable_hashjoin/enable_mergejoin = off`) plans in read-only test
transactions. It preserves the original relation-only 820 oracle, 64 KiB SQL
limit, two source-proof-body limit, query counts and returned-row assertions.
Supplemental attribution includes owning bitmap children, intermediate nodes
within provenance branches and all actual rows-removed counters. Materialized
proof stages retain the same bound. Full plans, SQL, parameters and settings
are retained, including unrelated query intermediates. The original plans
also expose 20,100 removed join rows in unrelated docket/version joins; this
patch does not claim to repair or certify total query work.

The generic profile uses an actual server PREPARE and EXPLAIN EXECUTE under
transaction-local `force_generic_plan`; it verifies the observed generic-plan
counter and zero custom plans. The complete prepared EXECUTE result tuples
must equal the original parameterized SELECT on the same read-only connection;
only counts, hashes and the equality result are retained. Identifier and value adaptation use psycopg's
SQL adapter. Every observed plan is retained before subsequent proof checks;
prepared-statement cleanup errors do not replace an earlier body failure.

Four literal counterexamples in the existing bounded-page case independently
check bitmap ownership, removed join rows, exclusion of an unrelated outer
join and inclusion of an intermediate proof node. They do not replace the
actual database plans. The original nineteen-case inventory remains; eight
cross-dialect index migration cases extend the complete closure to twenty-seven.

Default, adverse and generic JSON files remain in pytest's temporary directory. CI
additionally saves them in its per-shard query-plan artifact directory, with
upload on failure. This repairs future retention; it does not reconstruct the
missing historical artifact.

Verification closure pending source review:

- The complete seven-case export projection module, including both default
  and adverse profiles and retained-width/date-category reads.
- The two source-fact cases, three CTE-identity cases and retained-scale case
  on PostgreSQL; applicable SQLite counterparts, manual-date and multitenant
  provenance checks remain required.
- Eight PostgreSQL/SQLite migration cases cover populated audit/import/docket
  lineage and outbox preservation through upgrade/restart/downgrade/re-upgrade,
  conflicting index refusal, and complete current-head index health. In total:
  seventeen PostgreSQL, nine SQLite and one database-free compilation case.
- Adjacent consumers include tracker/source facts, portfolio list/export,
  recipient receipt links, category predicates and global renewal tracking.
- Fresh current-head CI and native candidate/backend revision reconciliation
  remain required before the iOS Pods/Xcode or Android acceptance claims.

Task-cache evidence is under `pg22-fresh-reproduction-plan-01/run-03/plans`:
`original-default-plans.json`, `adverse-full-plans.json`, both actual index
catalogs, diagnostic state and completion. Source/runtime postflight and
owned-container absence passed. The outer controller's final output inventory
refused pytest's generated current-directory alias, so that controller remains
**incomplete**; its actual test failure and separately retained plans are
qualified evidence, not a green release run. Earlier pre-test mount and
internal-network publication failures remain preserved as separate attempts.

The subsequent nineteen-case run's final output audit separately refused an
owned, zero-byte `temporary/uv-cache/.lock` with mode `0666`; every other
inventoried member's metadata passed. This is not a secret finding or a reason
to weaken ownership/mode checks. Keep that failed output unchanged and use the
already accepted `uv --no-cache pip check` constructor in a fresh attempt.
Source/runtime postflight, all 33 command-group cleanups and exact container
absence passed; those component results do not complete the interrupted suite.

## Candidate three actual failure and candidate four

The focused case on clean `67116923de3e4792fabf6baa1e152dbe8c5a29ac`
completed all three phases and failed the unchanged 820 work limit. Ordinary,
adverse and generic plans each charged 40,400 relation work and 41,000 owning
provenance work; deterministic ID ordering increased the broad audit scan.
Continuation work was 202/205. The controller closed in 92.1007 seconds with
source/runtime equality, all 34 command groups closed, known container absence
and complete paired typed output audit. Those successful harness components
do not change the failed product verdict. The exact 13 changed source files and
all plans remain under `failed-candidate-03` and
`pg27-clean-source-verification-04/minimal1` in the task cache. The five prepared
full-suite components for that rejected source remain unexecuted.

Candidate four seeks one audit candidate using the full ordered suffix
`(target_id, ip_docket_id, action, target_type, id)` of the tenant-leading
composite index. Only the trusted tenant and lexicographic lower bound select
that candidate before `LIMIT 1`. The outer query separately requires the exact
tenant, source, docket, action and target type; a wrong successor cannot supply
provenance. The globally unique import-row primary-key scalar retains its
tenant filter and drops its redundant limit; it remains a scalar rather than
a tenant-wide EXISTS. Actual plans must establish bounded performance. No
observer, work limit, SQL body limit or production planner setting changes.

Two new actual PostgreSQL/SQLite cases exercise wrong successors at each
ordered policy component, a foreign audit with the same source identity and a
foreign-owned source row despite a matching local audit. They also prove that
a predecessor and successor do not hide a valid exact proof. Each compares
staged facts and the page reader with the independent authoritative reader,
and checks the compiled range/limit boundary and parent correlation on both
dialects. The original 27 case identities remain required; the two additions
expand the complete inventory to 29 cases / 87 phases (18 PostgreSQL, 10 SQLite and
one database-free compilation case).

Verification remains pending. Run the focused bounded-page case first, then
the same-source complete composed inventory only after that repair passes.
The source-only compiler check passed in the actual accepted API environment
on PostgreSQL and SQLite dialects with socket/DNS, HTTP constructor and database
connection fences installed before test-module import. It observed zero
forbidden I/O attempts. This checks query construction and parent correlation;
it executes neither the database regressions nor the performance plans.
The separately bounded component windows retain their original 419-second body
and 30-second cleanup limits. Report their aggregate elapsed time separately;
the composition does not certify all cases within one 419-second window or
retroactively complete the earlier timed-out PostgreSQL inventory.

## Exact-case catalog diagnostic after candidate four

Candidate four's actual focused run on `db29359fbdd77e43dfc5aff90d79e4d15a334754`
failed in 85.06215 seconds. All three actual profiles charged 162,400 relation
work and 163,000 owning provenance work against the unchanged 820 limit;
continuation charged 812/815. The audit path used the old company/action
index with only tenant equality as its index condition, returning 382 rows
and filtering 429 per loop across 200 loops. Its estimated row count was one,
with total cost 8.18, then a sort at 8.19/8.20 and the outer candidate filter.
All three case phases completed; source/runtime equality, known container
absence, all 33 command-group closures and typed output audit passed. The
complete 26-file changed-source snapshot and plans remain under
`failed-candidate-04` and `pg29-clean-source-verification-05/minimal1` in the
task cache. The 29-case preparations for that rejected source remain unrun.

No further production query change is made before establishing this exact
case's index catalog. Earlier catalog reads covered the base and another
retained child, not this already-dropped case database. The test diagnostic
now reads the same live case connection's database identity, migration head,
read-only state, actual index definitions, valid/ready state, column order,
operator classes, collations and table estimates before each original plan
profile. It reuses the previously executed catalog SQL and retains the result
beside every existing pytest and CI plan artifact.

A separate transaction-local `enable_sort = off` estimate can establish index
eligibility. It uses `EXPLAIN` without `ANALYZE`, is explicitly excluded from
acceptance and leaves default, adverse and generic actual plans and every
original bound mandatory. Estimated eligibility does not prove bounded work
or authorize a production planner setting. At this preparation stage, index presence, eligibility and cost were still
unverified. The completed exact-case observations are retained below.


## October 29 exact-case planner-cost diagnosis and tenant-band candidate

The expected-failing diagnostic on clean 8e78eaef retained the actual same-case
index catalog: the six-column source-proof index is valid, ready, expression-free,
full and eligible, with standard text operator classes and ordering. Audit table
estimates remained -1 rows / 0 pages. All three actual profiles still failed at
162,400 relation / 163,000 provenance work versus the unchanged 820 bound. The
ordinary old index plus sort cost 8.20 at PlanRows=1; the separate sort-disabled
estimate chose the new covering index at 8.29. That estimate did not execute
the query or prove bounded work. No production planner setting is introduced.

The original run remains failed. Its source/runtime, known owned-container
absence and command closures are separate passed components. A separately
timed post-run strict paired output audit retained every one of the 33 full
cleanup records and passed in 0.1993 seconds; it does not repair the original
clock or acceptance. Hash-bound evidence is retained in the task cache under
pg05-index-catalog-diagnostic-06/actual-diagnostic-receipt.json.

Candidate six (subsequently failed as recorded below) used a full six-key lower tuple bound and an
upper bound on company before the ordered single-candidate limit. Together
they select only the trusted tenant without an equality whose stale estimate
collapses the row count; complete exact policy stays outside the barrier.
The two cross-dialect semantic cases now establish three real tenants, sort
them by database order, select the middle owner and reject both lower and
higher foreign audit candidates. Wrong successors, foreign import ownership,
prebuilt-statement freshness and independent direct/page/staged dates remain
required. The original 29 identities / 87 phases and all 820/228, two-body,
64 KiB, query-count and timeout limits remain unchanged. Verdict: Not fixed
until actual ordinary, adverse, generic and full same-source workflows pass.


## October 29 additive type-leading candidate (private, unverified)

The six-key tenant-band candidate also failed all ordinary, adverse and generic
profiles: 162,400 relation / 163,000 provenance work versus820. Its old company
index used derived company lower/upper conditions plus an Incremental Sort;
all 811 tenant audit rows were still inspected per candidate. The sort-disabled
estimate retained that incremental sort, so it did not establish a new-index
choice. The original failed run, all33closures and a separate strict paired
post-run audit remain preserved; no failure is reclassified as acceptance.

Actual catalogs also contain the legacy target_id index. A target-first rewrite
would therefore still permit a target-prefix incremental sort over foreign
same-target history. Candidate07 instead adds revision20261029_0002 with a
full type-leading (target_type,target_id,company_id,ip_docket_id,action,id) index.
Revision0001 and its company-leading index remain unchanged. The query uses
full lower and three-column prefix upper ROW bounds before its one-candidate
limit, then retains the complete exact policy outside. No production planner
setting, ANALYZE waiver, old-index removal or larger work limit is introduced.

The intended complete inventory is38cases/114phases: all original29 identities,
eight new cross-dialect migration cases and one PostgreSQL history-work case.
The new roundtrip starts at named0001, includes a real interrupted concurrent
build/recovery on PostgreSQL, and proves downgrade preserves the old index,
raw rows, catalog and revision. Current-head0002 health and conflicting-name
downgrade refusal remain distinct from that historical boundary.

The work case seeds25,728 foreign same-target audit rows across both tenant
sides, plus12,864 owned NULL-docket and12,864 NULL-target rows and type/source
neighbors. Positive and missing-owned-proof phases each retain every actual
default/adverse/generic plan, original820relation/proof/materialized limits,
64KiB SQL, two-body and query-count assertions. NULL SQL comparison behavior
and B-tree work must be observed; no nullable key is assumed safe by sorting.
The two existing dialect semantics cases additionally retain before/after
prefix neighbors, actual selected-candidate identities, independent direct/page/
staged dates, and NULL/missing source JSON controls. Any unreached later phase
remains unverified. Six separate419+30component windows report aggregate time
separately. Verdict remains Not fixed until those actual workflows pass.


### 2026-10-29 — Source07 focused provenance result and fixture correction

The committed source07 `3b6130a5` passed the original PostgreSQL minimal-page case under default, adverse and actual generic prepared plans: date-query relation work 400 and attributable proof work 800 remained within the unchanged 820 bound; continuation work was 2/4. All five plans per profile, source/runtime stability, known container absence and all 33 owned process closures are retained. This is a scoped original-case pass, not complete release acceptance.

The independent stress case failed before history staging or query acceptance: its second fixed company bootstrap returned 409 instead of 200. Positive/missing-proof phases and their plans were unreached. Both new semantic dialect cases shared that fixture defect and remain unverified. The test-only actor helper now accepts the existing normal-API unique bootstrap for these three multi-actor cases while preserving original callers, cookie clearing, authentication, complete workspace configuration and acknowledgements. The iOS shell companion is regenerated to bind the current helper bytes. Neither correction changes product SQL, indexes, work bounds or the full 38-case/114-phase inventory. Replacement focused/full verification and both native platforms remain pending.

Evidence: `X/pg07-typed-prefix-verification-08/actual-focused-results.json` SHA256 `8ee4aa2920e85571d77ca733ca1197f1d00a6fa98f55c29df1c918039f77a20e`. The stress run and its separate audit01 stale-count refusal are preserved; audit02 reconciles all 34 actual contiguous dispatch/closure pairs under the original audit limits.


### 2026-10-29 — Source08 physical-work gap and reverse-prefix candidate09

Source08 `9505e0ea` completed the corrected stress case (99.090964s; one case, three passed phases, 16 marked HTTP requests), retaining all five plans for each default/adverse/generic profile in both positive and missing-proof phases. Positive Audit access used 1000 shared-hit blocks, while missing-proof access used 244302 despite zero returned/removed Audit rows. The original row-work checks passed (400/800 and 200/200 against 820); that pass does not establish bounded internal index work. Source/runtime/output and all 33 actual owned process groups closed cleanly.

Candidate09 is a minimal unverified reverse seek: one upper comparison over the five complete identity fields, all six index keys descending, LIMIT 1, no lower prefix and no ID sentinel; a source-NULL gate avoids an invalid comparison bound. Complete exact policy and ImportRow primary-key ownership remain outside that barrier. Existing wrong-successor policy denials stay covered, with selected wrong predecessors, lower/higher tenants, nullable histories and duplicate proof IDs added to the same cross-dialect cases. No model, migration or index changes are proposed.

The independent physical oracle counts inclusive Audit relation buffer accesses once, without multiplying counters by loops or charging bitmap children twice. Its fixed 201-seek contract is 16*201+64=3280 accesses: a conservative six-level descent plus metadata/VM, leaf/heap boundaries and slack per seek, with fixed overhead. It is a bounded-fixture contract, not a universal index-height guarantee or a value fitted to the failed measurement. The retained positive1000 baseline must pass and missing244302 baseline must fail. Original820/228 row-work, SQL/body/count/deadline bounds remain unchanged. All38caseIDs/114phases, migration journeys and native acceptance remain pending until actual complete replacement evidence.

Evidence: `X/pg08-fixture-verification-09/actual-stress-results.json` SHA256 `a148175da44fe66b83da264ebd3d943aaf3abadd579ef9fa13d63476a82f0bcc`. Successful fixture teardown normally drops the case database; no cold volume reopening or retained-data claim was made.


### 2026-10-29 — Candidate09 Result-node failure and CASE-bound candidate10

Both source09 `e819b84d` focused runs failed their unchanged supplemental820 work assertion in all three retained positive profiles. The reverse typed IndexOnlyScan was actualBackward and bounded at the relation/physical layer (relation400; MIN600 and stress1000 buffer accesses). The separate source-NULL predicate introduced an attributable Result One-TimeFilter node, adding200 work and raising the complete proof count to1000. That node remains charged; no observer, assertion or bound is relaxed. Stress missing-owned-proof remained unreached. Both source/runtime/cleanup/known-absence checks and separate complete output audits passed (MIN33, stress34 actual command groups).

Candidate10 moves only that existing source-NULL condition into a CASE expression in the first upper-row value. Valid sources retain the identical five-field reverse bound. Missing sources produce a NULL first key, retaining the no-candidate contract without a separate constant WHERE filter. All complete outside-policy, ImportRow primary-key, date, predecessor/successor, foreign-tenant, nullable and duplicate-ID checks remain unchanged. The compile contract now pins the one CASE guard, exact NULL refusal and sole upper comparison. Original820/228 row-work,3280 physical-work,64KiB/two-body/query-count/deadline bounds and all38caseIDs/114phases are unchanged. Actual replacement focused/full and native verification remain unexecuted.

Evidence: `X/pg09-reverse-prefix-verification-10/actual-focused-failure.json` SHA256 `8684f1d0e327f75d4e1861af54e18af8b82915e74c1328046c29d34793d5b250`; fullplans `ab8c0094a546f517532c67e5bdc736b257259e495f19f508a438ecbca9cf3c37`. No unchanged retry or historical failure reclassification.


### 2026-10-29 — Complete attempted38 inventory: observer failure and capacity refusal

The complete frozen source7033 replacement attempted all six admitted components, with at most two active. Thirty cases executed:29passed and one compile-only observer failed;89passed/1failed phase reports account for90of114planned phases. The eight new0002migration cases and their24phases were unreached because Docker refused network creation after all predefined address pools were allocated. No database or pytest body began for that component; it is infrastructure-incomplete, not eight migration failures or a green prefix. Aggregate observed537s is separate from each unchanged419+30window. Every component completed source/runtime postflight and strict owned command/output closure.

The sole executed failure was test_five_stage_names_preserve_pg_materialization_acl_and_current_source: its raw substring count found13 occurrences, including repeated ip_materialized_proof_seek aliases, while the preceding actual typed graph still contained exactly six unique nested CTEs. The corrected oracle retains six, requiring six PostgreSQL TextClause MATERIALIZED prefixes and six rendered AS MATERIALIZED declarations; an alias-only decoy contributes three substrings but zero declarations. All stage, ACL/source, actor/tenant parameter, warm read, category/date, postcommit and count assertions remain unchanged. No production query, model, migration or limit changes are involved.

Source7033 actualfocused plans retain the repaired missing-proof physical work1045 versus prior244302, within fixed3280, and all original row-work bounds. Both dialect semantic cases passed within the attempted inventory. Exact-owned network capacity recovery is separately planned for seven receipt-bound closed networks; no broad prune, data-volume removal, foreign/live-network cleanup or unchanged replay is authorized by this observer correction. A fresh coherent complete38/114 run and native Android/iOS acceptance remain pending.

Evidence: `X/pg10-case-upper-verification-11/full38-unarmed/actual-attempt-results.json` SHA256 `7aa737576880b7e8f3e2d92bf14ad3976b156137b10db89b07e678b8a23fc285`; all original reports and unreached phases are retained.


### QA12: interrupted typed-index catalog fixture, 2026-10-29

The complete source-bound run on `4bc5c7dc` executed all 38 cases and all 114 setup/call/teardown reports: 37 cases passed and one failed (113 passed phases, one failed phase). The original failed result remains at `pg11-materialized-observer-verification-12/full38-unarmed/actual-attempt-results.json` (SHA256 `98e80df89a38f2cc90ba2eebab647239796eabdf6a54d328798db9f708c46c34`). All six source/runtime postflights, owned process groups, container absence checks and later complete output audits closed. The aggregate observed 497 seconds is separate from each original 419-second body plus 30-second cleanup bound.

The PostgreSQL typed-index roundtrip stopped while recording its deliberately canceled concurrent index build: the ordinary catalog helper correctly rejected `ix_audit_events_typed_source_proof_seek` as invalid/unready. The repair continuation, restart, downgrade and reupgrade in that failed case remain unverified. The historical intermediate catalog/individual flags were not persisted before that assertion; a new exact expected descriptor is prospective proof, not a historical observation.

The proposed fixture uses a separate interrupted-index catalog observer with one exact key, complete six-column PostgreSQL index definition and explicit flags `(false,false,true,false,false,false)`. The ordinary `schema_catalog(engine)` remains healthy-only. Every other index must remain healthy, the expected interrupted index must exist, and the complete intermediate catalog must equal the parent plus that one index. The real fixture first proves the default helper rejects its actual invalid index. All existing repair, full-health, identity, row preservation, downgrade and reupgrade assertions remain required.

Independent observer regressions cover the exact snapshot/default rejection and wrong name, definition, flags, a healthy target, a missing target, an extra invalid index and an invalid descriptor. Eight private source controls passed with zero database/network calls. The complete adjacent unit inventory is 13 cases (the original five real SQLite DDL cases plus eight observer controls); the affected migration inventory remains eight. Neither private controls nor a future scoped eight-case pass make the failed complete-38 run green. Full native Android/iOS build and device acceptance remain open.
