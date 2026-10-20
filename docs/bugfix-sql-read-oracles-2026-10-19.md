# SQL Read Oracle Postmortem - 2026-10-19

**Partially fixed in test source; release NO-GO.** This is a checkpoint draft,
not C8 acceptance. Pending results must be replaced only from owner-retained
completed inventories. It changes no product or legal contract.

## What We Missed

We reviewed the C7 runtime query, ACL composition and specialist plans, but
failed to audit adjacent SQL instrumentation when the emitted shape changed.
That was our review miss. SELECT-prefix observers could reject a legitimate
WITH read, silently omit the statement a plan test needed, or undercount work.
Passing specialist plans did not excuse the incomplete adjacent audit.

The confirmed reproduction concerns the observer, not a demonstrated production
regression: three typed SELECT statements were retained; the third is a 7,988-byte
WITH ... AS MATERIALIZED read. The old prefix assertion rejects it. We must not
invent mutations or runtime defects from a string-prefix failure.

## Complete Failed C7 Evidence

Candidate `d5ecdab2c371f73cae258b8b85384588413d58df`, tree
`944f3c123ea7fef1414f203b866c02a9b7bce853`, CI39212375169:

- API12,137 collected:8,904 passed,1 failed,3,232 skipped.
- Native3,226 cases:3,223 passed,3 failed; all9,678 setup/call/teardown phases.
- Frontend1,535 passed; browsers0 executed. All16 specialist plans passed.
- Four failed identities, under `apps/api/tests/`: hydration
  `test_ip_recipient_renewal_content_20261014.py::test_source_body_hydration_is_three_read_queries_for_one_or_many_dockets[sqlite]`
  and `[postgres]`; retained-scale
  `test_ip_tracker_retained_scale_postgres_20261017.py::test_retained_width_tracker_bounds_source_fact_work_and_visible_latency`
  (missing initial capture); dense history
  `test_ip_renewal_tracker_postgres_20261015.py::test_dense_retained_history_bounds_actual_current_reads_and_catchup`
  (missing category_counts).

The complete packet is retained under
`outputs/bugs-l-20261019/ci-d5ecdab2-reconciliation-01/complete-failed-01/COMPLETEFAILED.json`,
SHA256 `8c0fc7610a8d942dad42d7bc5b1825c95e23eadc5c95e93814763021576ef366`.
Its sibling ALL-FOUR-FAILED-CASE-FULL-PHASES.json retains all four cases' phases.
The original failure envelopes did not retain the actual SQL; the later
source-pinned RED supplies that proof, not a reconstruction of CI SQL.

Parent reports the one-case RED completed naturally with exit1 and all three
phases, source unchanged and its owned PG resources removed. Actual typed SQL
was retained before the old assertion. C7 Docker was operator-superseded:
one group incomplete, browsers0, all2,963 source entries unchanged, resources
closed, proof SHA256
`a11417cc6e737d874c4b39af2d4ca6c793e5a02101f07c730a096c3191e622d7`.
An operator-incomplete run is not a failed-case waiver or full release proof.

## Bounded C8 Correction

Extract exactly the existing `_is_read_only_select` implementation from
`test_document_processing_snapshots_20261018_postgres.py` into
`apps/api/tests/sql_observation.py`, retaining the old import alias. Require
a typed SELECT AST; reject nested DML, TextClause and TextualSelect anywhere
in its traversal. WITH alone is not proof of read-only SQL.

The six adjacent collector repairs cover import review, portfolio preview,
journal watch, report workflow, dense renewal history and retained-scale
tracker. Retain every actual cursor SQL event and original plan labels/target
counts, charge all statements under unchanged caps, and keep intentional
audit/cleanup mutations distinct from read-only phases. Do not hide CTEs,
raise budgets or replace exact result/ACL/provenance assertions with counts.
The prior observer audit's19 files/29 sites are audit inventory, not29 test passes.

## Verification Still Pending

The29 PostgreSQL/SQLite-dialect compiler/unit cases passed. The focused native
run completed72 cases in six files and216 passed phases at07:50UTC, natural
exit0, unchanged full source and owned resource cleanup. Parent acceptance is
`7d0806dd5ad475b7c2c2d37ed478fe31ce30ab1e1f339642a11fccd4f61337c4`.
The separate SQLite run completed79 cases in all five intended files and237
passed phases with zero skips/failures and stable source pins. These are not
one combined run or full release proof.

After the native run, review found that a new diagnostic finally-writer could
mask an earlier failure with an environment or file error. It now records the
primitive SQL observations as a pytest property with no new file/environment
access. The72-case result is not relabeled as execution of those later test
bytes; the fresh full native gate must cover the final diagnostic change.

Parent must reconcile all intended identities and setup/call/teardown phases,
the four old failures, source before/after pins, all SQL/counters/plans and owned
cleanup. Then pin the actual C8 commit/tree and fresh full Docker/candidate CI/
main CI/CodeQL/Security/merge-equivalence and exact-serving proof. The corrected candidate is not released or certified
by these focused checks. C7 preparation remains historical.

Runtime, dependencies, API/schema/migrations and source/legal policy are
unchanged by this test-only correction. Last checked production is P9cf; private
Scheduler stays held, no QA grant is replayed, and external cleanup remains
user-deferred. No OAuth/provider/legal approval or original incident closure
is inferred. Keep the entire failed C7 record and any later incomplete attempt.

## Permanent Learning

Audit every adjacent observer when SQL shape changes. Structural read-only
classification, complete raw retention and total-work accounting are separate
requirements. Reconcile every failed sibling, not only the first failure;
a passing running prefix never becomes a completed gate.
