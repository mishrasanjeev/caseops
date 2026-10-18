# Document Processing Snapshot Consistency

Status: source correction, not production-certified. Journey J04, module M03,
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

## Required Closure

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
