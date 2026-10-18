# Document Processing Snapshot Consistency

Status: source correction / NO-GO; total-work acceptance remains blocked and
production is not certified. Journey J04, module M03,
US-007..009 and FT-011..015; adjacent IP document/version serialization.

## Serving Evidence

Release `9cf76f2b420fcb38a9aaa4b87ac63270bb3c0535` is deployed. Exact-release
verification 39143613520 completed 404 cases: 385 passed, one failed and 18
explicit skips, with no retries. All 50 mandatory IP/Calendar dated cases passed.
The separate public inventory reconciled all 47 intended/collected/passed cases.
Neither those results nor green CI/Docker certify the failed overall release.
Private maintenance remains paused; the consumed test-legal-only manual-IP grant
must not be replayed.

The sole failure is the Matter 393px initial-index assertion at the serving
`tests/e2e/ram-2026-10-10-prod.spec.ts:120`. Upload returned 200; the job was
completed but the attachment status/hash/extracted-length tuple did not match.
Error redaction prevents identifying the original mismatching member. The two
subsequent read-only snapshots show indexed status, the expected stored hash and
2,839 source/extracted/processed characters. No reindex had been reached. Worker
completion falls inside the final workspace GET and the worker image is exact
release. This is not proof of the original HTTP tuple or a fresh GCS byte audit.

## Reproduced Defect

Worker writes are atomic, but READ COMMITTED gives separate SELECTs separate
snapshots. Matter and Contract workspace assembly first materializes attachment
objects and later reads latest jobs. A worker can commit between those reads.
The identity map then retains pending/zero source fields beside a newly completed
job with 2,839 processed characters. IP version serialization has the same
boundary, including OCR fields used by its eligibility policy.

The isolated PostgreSQL HTTP run-03 establishes this interleaving using real
upload admission and a real worker in another session: two initial-index RED
calls, ten passing controls, all 12 setups/teardowns passed, full completion and
source-before/after equality. Earlier run-01 infrastructure failure and run-02's
three incorrect new-test assumptions remain retained, not product defects.
Existing worker tests confirm that inactive actors lose HTTP access while
company-owned admitted work can retain historical provenance. A pre-neutralized
Matter job is not claimable; linked-Contract rejection is a separate boundary.
None of these existing worker policies is changed by this repair.

This proves a real read-consistency defect and a matching possible production
interleaving, not retrospective knowledge of the redacted tuple member.

## Repair Boundaries

- Read source processing scalars and the complete latest receipt in one SQL
  statement, bound to company, source type and source identity. Do not copy
  source bodies, chunks or the complete job history into the request.
- Refresh only already-loaded processing scalars, including IP OCR quality.
  Preserve unrelated pending metadata and relationships; never autoflush a read.
  Conflicting pending processing changes or disappeared sources fail with 409
  rather than being silently overwritten or presented as a current no-job row.
- Keep no-job legacy sources and deleted-requester null semantics distinct from
  missing sources. Preserve all receipt fields and the independent admitted-ID
  job reader. Do not change worker claims, access, lifecycle, source or no-paid
  fences.
- Derive both IP upload receipt locations from the exact matching serialized
  version. A second latest-job read cannot update an already-frozen document DTO.
  Preserve the separately admitted job ID used for dispatch.
- Give each dated browser invariant a distinct assertion location. Redacted
  errors must remain diagnosable without recording private source content.

## Scoped Native Verification

Frozen-source combined-02 completed all 50 intended identities across three
explicitly selected files: 12 workspace races/controls, seven IP HTTP receipt/OCR
cases and 31 cache/tenant/dirty-state/history cases. All 150 setup/call/teardown
phases passed, with no skips, retries or global errors; source hashes were
unchanged and the driver and owned database resources were reaped. Receipt:
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-red-01/combined-02/FINAL-RECONCILIATION.json`,
SHA256 `698096333ee7d962b291a43415b8f593a42bf98e8a3a403b369d142857eeb528`.
These are isolated native PostgreSQL results, not whole-Docker or live proof.

Preserved intermediate failures include the first repair's incorrect assumption
that Matter/Contract attachments directly own company IDs (corrected to parent
joins), and combined-01's 49 passes plus one new test-envelope error. The latter
had already proved low-quality OCR denial; its assertion incorrectly treated
RFC 7807's string `detail` as nested metadata. Only that test was corrected to
assert the canonical top-level code/action/reasons, then the complete 50-case
inventory was rerun. API behavior and OCR eligibility were not weakened.

The first published candidate `450fcbf5` was blocked by CodeQL check117762796712:
the new fixture's response variable was not defined for unsupported targets.
Reject unsupported targets explicitly and assign the parent identity inside
each admitted branch; do not suppress the finding or weaken the HTTP oracle.
Its earlier 50-case results remain scoped to the preceding fixture bytes.
Docker11 was deliberately cancelled before complete native/browser acceptance,
with its original source, partial journals and collection retained. Only the
checked native child tree was stopped; the canonical shell performed cleanup,
was reaped and its exact project had zero remaining containers/networks/volumes.
The replacement must pass fresh full gates. The earlier output-wrapper Docker10
argument-binding failure is operator evidence, not a product regression.

## Retained-History Follow-Up

Candidate `5abf3ecb` also remains NO-GO. Docker12 completed four groups with
1,590 passes and two failures across 4,776 phases. Contract/IP histories examined
131,360/131,328 Job rows against the unchanged 16,514 bound. The actual plans use
a broad target-type index 16 times, not sequential scans. Matter's selective
attachment index examined 8,208 rows. IDs and DTOs were correct and execution
was about 14ms; these failures prove excessive work, not measured production
latency or missing indexes. The remaining gate was cancelled after preserving
the complete failed group, all three plans and source identity. Canonical cleanup
and parent reaping were verified; incomplete coverage was not credited.

The deterministic replacement RED selected six real PostgreSQL cases: all three
new adverse-plan cases failed at 270,435 raw Job rows, while the three original
history controls passed. All 18 phases completed, source stayed unchanged and
owned resources were reaped. This is a real complexity failure, not a fixture
constraint error. The original work limits remain unchanged.

The correction requires a server-supplied company keyword on the internal reader
and both workspace maps. All nine direct reader calls and two workspace-map
paths use the existing `context.company.id`; no tenant inference or extra query
is introduced. An independent Job-only window is filtered by constant company,
target and requested IDs. Rank1 is selected before the latest CTE is materialized.
The outer source ownership predicate uses the same company, and DTO columns come
from that reduced CTE without a second Job join. LEFT/no-job/requester semantics,
atomic processing/OCR fields and dirty/missing-source protections remain intact.

Frozen uncommitted C3 completed **59 cases / 177 passed phases**, zero failures,
skips, retries or global errors, for the assertions actually executed. Exact
inventory is 12 workspace, seven IP, 34 auxiliary and six history cases; every
original 50 identity and prior three adverse cases is preserved. All 15 actual
plans remain retained. Independent review found that the total-work oracle
omitted Bitmap Index Scan children: the reported maximum 24,580 is an undercount,
not proof of the unchanged 33,028 bound. Full foreign-default producer work is
40,998 for Matter/IP and 40,999 for Contract. This qualifies the original green;
it does not rewrite its 59 cases as failures.

The original read-only guard also accepted nested opaque TextualSelect DML CTEs.
That compiler-only counterexample is an oracle gap, not evidence of a product
mutation: the actual C3 helper query is typed and read-only. Maximum raw Job
relation work 16,387 <=16,514, rank input at most 8,193 and materialized latest
output16 remain valid. The foreign cohort has 8,192 same-ID foreign jobs, and
scope tests reject foreign/mixed batches before any cache refresh. SET LOCAL
planner profiles were restored after transaction close; production settings and
the 16,514/33,028 budgets are unchanged.

Source/config/dependency hashes stayed held, driver/session completed and were
reaped, and owned container/network absence was checked. Receipt:
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-history-native-prep-01/combined-green-01/FINAL-RECONCILIATION.json`,
SHA256 `e7cca1b211b7907ac01dccdebb1d22b8943bc051c278ce03ce24bc5c5b10df0c`.
The corrected-oracle RED completed six cases, three passed and three failed,
with all 18 structured phases retained. Its receipt is
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-c3-index-probe-prep-01/corrected-red-01/FINAL-RECONCILIATION.json`,
SHA256 `3418b8830725233f6bad51232213315d03309f0d6d2a27eb48509953c93eb6a0`.
Both ordered six-key index experiments were insufficient: EMPTY-before-seed and
RETAINED-after-seed each completed six cases (3P/3F), 18 phases and 12 full plans;
together they retain 24 plans and 36 phases. The candidate index was valid/ready
with exact directions, but default plans still chose the old BitmapAnd plus
heap/sort and exceeded 33,028. Source remained held, processes were reaped and
owned resources removed; no D model or migration was activated. Index receipt:
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-c3-index-probe-prep-01/FINAL-INDEX-PROBE-RECONCILIATION-01.json`,
SHA256 `0a0e6608cf906b80ff8f8779a2380b54685e686f7d32ca90c36d84ae86bd0513`.

The follow-up LIMIT-only and LIMIT-plus-ordered-index variants each completed
six cases (3P/3F) and18 phases. Neither met the unchanged total-work bound. A
narrow `(company_id, target_type)` index with the unchanged full-DTO C3 query
then passed all six cases in both retained-after-seed and empty-before-seed
timings. Actual default work is16,418; worst adverse work24,612<=33,028, with
raw Job work below16,514, rank input at most8,193 and latest output16. Exact
DTO rows matched controls. Default plans actually selected the new tenant/type
index, rather than the global target-type bitmap path. There is no LIMIT,
planner hint, statistics change, timeout increase or budget relaxation in this
accepted candidate design. The four counterfactual modes retain24 cases,
72 structured phases and48 plans. The first harness assertion attempt was
incomplete, preserved and reaped, not a product failure or passing test.

Causal probe receipt:
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-limit-probe-01/FINAL-LIMIT-TWO-KEY-PROBE-RECONCILIATION-01.json`,
SHA256 `087c2764140591d9ac9aac12faabeaf261e1c613ba31f68c3df2650aa8a2dc71`.
All owned commands/resources closed and source hold released before the model,
recoverable concurrent migration and dedicated rollback/recovery test work began.
These probes establish the index choice, not migration or full native acceptance.

Full release acceptance remains outstanding at this source-preparation checkpoint.
Serving P remains failed;
private cadence remains PAUSED, the existing test-legal-only manual-IP grant
must not be replayed, and workbooks 56/23 and their verdicts are unchanged.
These bounded synthetic plans are not whole-Docker, production-cardinality or
live HTTP latency certification. Corrected scoped proof and fresh full release
gates remain required; no budget, retry or planner-policy waiver is authorized.

## Required Closure

The source candidate now declares `ix_document_processing_jobs_company_target`
and migration `20261019_0001` above `20261015_0001`. Upgrade validates index
ownership, columns, uniqueness, predicate/expression, ordering, collation and
opclass before accepting it; PostgreSQL builds/rebuilds concurrently and checks
valid/ready state. Downgrade uses ordinary transactional PostgreSQL DROP so a
later historical refusal can roll it back. SQLite rejects a non-parent or
unknown downgrade destination before DDL. No business fields or provider markers
are changed. The governance inventory adds one index only, keeping339 tables,
5,379 columns and all existing policy approvals unchanged.

The first combined native run completed101 identities and303 structured phases:
82 passed and19 failed, with source unchanged and all owned commands/resources
closed. All32 new migration cases (18 PostgreSQL,14 SQLite), all10 existing
dated renewal-migration cases,34 auxiliary cases and six history cases passed.
The15 history plans and migration interruption/rollback/health/SQLite evidence
are retained. Receipt:
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-index-native-prep-01/combined-green-01/FINAL-FAILED101-RECONCILIATION-01.json`,
SHA256 `7e79a3fd3fd7f174fc4029523b186e27471672ff72792cfb506e6be0b4babe99`.

Eighteen HTTP cases failed during document setup with Windows WinError3 under
the operator's excessively long retained-output `--basetemp`. They did not
reach attachment admission and are not product reproductions. The remaining
IP upload case failed because its DTO barrier was not entered; its original
request Future exception was lost when the barrier assertion bypassed
`pending.result`. Captured sections contain no recoverable underlying exception.
That nineteenth cause remains unclassified, not inferred from its siblings.
The original failed101 remains failed, with every full phase/report retained.

A test-only shared barrier guard now needs deterministic coverage for reached,
early-exception, completed-without-barrier and still-pending futures, preserving
the original20-second wait, finally-release and normal result checks. The fresh
replacement gate is planned as the complete original101 plus four diagnostic
controls, using a short fresh owned temporary root and durable sidecar copies.
Actual collection and all105/315 phases must be reconciled before acceptance;
there is no shortened selection, product workaround or timeout increase.

The complete short-root replacement now passes **105/105 cases,315 phases**,
with zero failures, skips, retries or global errors. All seven requested modules
ran, preserving the original101 ordered identities and all59 snapshot cases,
plus the four unmarked diagnostic controls. The15 plans,32 migration cases and
10 dated migration cases pass with the unchanged work bounds. The real nested
filesystem preflight round-tripped four representative document paths before
launch; no existing pytest base was cleared. All1,442 API files, five runtime
configs and13 known execution-chain paths matched before/after, and19 captured
executed bodies matched. Durable copies of56 sidecars include16 SQLite files
and two health reports. All owned commands were reaped and containers/networks
removed; short temporary evidence files remain retained, not claimed deleted.

Source-owned native receipt:
`outputs/ip-calendar-open-items-20261017/document-index-snapshot-index-native-prep-01/combined-green-02/FINAL-GREEN105-RECONCILIATION-01.json`,
SHA256 `99f2c417488ae98b2ac1753432cae349d570297242ab7f2ef075b5537cbac083`.
This is complete scoped native proof for frozen uncommitted C3, not a full
Docker, hosted CI, merged-main or production pass. The original failed101 and
its unknown Future exception remain unchanged history. Fresh full gates follow.

Fresh controlled GREEN must cover the original HTTP races, adjacent IP reads and
upload/new-version responses, dirty processing and metadata state, cached jobs,
no-job/missing/requester cases, type/tenant isolation, OCR policy, retained history
and measured query work. Complete source-owned Docker and CI inventories, green
canonical main, guarded exact-SHA deployment and the same production browser
journeys are required. Then retain any blocked recovery and obtain two later
clean maintenance executions, second with zero rebuilds, guarded resume and an
attributed natural clean cadence. Do not weaken assertions, retry mutations or
raise deadlines. Legal-source, consent, verified-date-writer and unidentified
historical reopening gaps remain separate and open.
