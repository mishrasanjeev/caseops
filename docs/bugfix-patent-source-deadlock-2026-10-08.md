# Patent Source Save Deadlock - October 8

## Release Finding

Verdict: **Not fixed** on serving release
`b20f86bddeecf985fc961012bb93fa2c41889c49`. This is an additional production
acceptance finding, not an invented third row in the two-row Calendar workbook.
Scope: UJ-29 / PAT-01, IPLF-080 restricted family intake and immutable document
source corrections; M02/M08/M13/M14. No patent automation scope is added.

PR #523 deployed after exact-tree Docker acceptance (547 PostgreSQL passes;
459 Playwright passes and eight explicit skips, all 467 identities reconciled)
and green merged-main CI. API `caseops-api-00486-g44` and web
`caseops-web-00463-bt5` serve that commit at 100% latest-only traffic.
This proves deployment, not complete production acceptance.

Production verification [37716144183](https://github.com/mishrasanjeev/caseops/actions/runs/37716144183)
failed one of 23 patent/domain tests. Tester, readonly, legacy, supporting and
the statute-source step passed. The 393px journey in
`tests/e2e/iplf-080a-patent-family-2026-09-06.spec.ts` failed while pinning the
just-uploaded inventor source. The 768px and 1280px journeys passed.

At `2026-10-08T02:54:45.625744Z`, the correction POST returned 503 in 1.116s.
The UI displayed the database-unavailable problem and retained the edit form.
Trace: `c0bf94fd864cd75951c33adde72b2d16`. Cloud SQL's matching
`2026-10-08T02:54:46.735Z` error explicitly reports a deadlock:

- Correction owns Company and waits for `ip_document_versions FOR UPDATE`.
- Document-processing worker owns the version update and waits for
  `companies FOR NO KEY UPDATE` during private-source propagation.

## Root Cause And Audit

`_process_ip_document_version_job` parses the uploaded version, dirties its
processing fields, then flushes them before private-source propagation acquires
the tenant authority lock. Production sessions disable autoflush, so the
explicit flush is the production boundary. With autoflush enabled, the preceding
document SELECT writes the version even earlier. Patent corrections acquire tenant
authority before actor, parent, document and version locks. The worker reverses
that ordering. A green sequential journey did not force this overlap.

The repair must acquire tenant authority with autoflush suppressed, after
extraction but before any version/job flush. Extraction must not own the tenant
or source-row lock. It must preserve source hashes, lifecycle state, current
version checks, atomic processing/event persistence and fail-closed private
generation invalidation. A browser retry or larger timeout would hide the
failed mutation rather than repair it.

Adjacent document link and state changes also acquire document/version locks
before tenant authority. They are included in the same ordering audit. Upload,
new-version and bulk-name allocation already acquire Company first. Matter
and contract processing have separate parent/lifecycle contracts; a generic
Company-first rewrite must not introduce new inversions into those contracts.

Independent review also identified a separate **open, pre-existing actor-FK
lock-order risk**: a Company-owning private event can wait on the uploader's
membership foreign key while a Matter mutation owns that membership and waits
on Company. This is not the Cloud SQL source-version cycle repaired here and
has not yet received a deterministic same-actor worker/Matter reproduction.
Do not claim comprehensive deadlock closure, discard event provenance, or
reverse only the Matter worker's parent ordering to address it. It requires a
separate actor/tenant/lifecycle locking audit and forced-overlap regression.

## Evidence And Gates

Retained task-local evidence (never overwrite the failed run):
`.tmp/calendar-oauth-20261008/prod-verify-37716144183-failed.log`, the downloaded
patent artifact's `error-context.md`, `patent-correction-failure-logs.json` and
`patent-correction-cloudsql.json`.

Required: deterministic PostgreSQL worker/correction and adjacent-path races,
full fresh Docker inventory, green CI, canonical-main deployment, and the
complete dated production patent journey without mutation retries. Status is
open until those gates complete. Private-projection cadence remains paused
under the guarded release policy until successful exact-SHA production QA and
two subsequent clean maintenance runs permit guarded resume.

Local pre-release checkpoints (not production closure):

- Both new worker race variants failed on the unfixed source: Company was
  observably blocked while the worker retained the needed version lock.
  `doc-lock-before.jsonl` and `.xml` retain both complete failures.
- The repaired variants passed, followed by five repeated two-case runs and
  the complete eight-test `test_ip_patent_postgres.py` inventory. All phases
  and completion events reconcile in `doc-lock-reconciliation.json`.
- Five complete backend files covering document workers/processing limits,
  document workflow, patent families and applications passed 52 tests
  (`document-lock-unit.jsonl` and `.xml`, 156 setup/call/teardown records).
  These overlap the later full release gate and are not additive coverage.
- API Ruff and browser TypeScript checks passed. The dated browser journey
  now checks the correction response and exact pinned source ID/hash before
  its existing reload/download/lifecycle assertions.
- Adjacent document links/state: four original lock-overlap cases failed on
  unfixed source and passed unchanged after the repair. The expanded 16-case
  PostgreSQL file and a 50-test affected inventory passed, including capability,
  stale-version, closed-docket, grant-revocation and cross-tenant rejection.
  Independent evidence: `docs/bugfix-ip-document-writer-lock-order-2026-10-08.md`.

Calendar BUG-003/004 remain **Inconclusive**: the exact-release safe callback
test passed, but the owner-authorized `sanjeev@orchestrum.in` Google phone
verification expired before consent. No successful Google grant or positive
connection/reload acceptance is claimed. Other owner-left-open provider gaps
remain open.

## Permanent Learning

A post-upload source save must succeed while background extraction completes.
ORM autoflush is a write/lock boundary even when the next explicit statement
is a SELECT. Test both workers and interactive source writers against the same
tenant-first order. Force the worker to reach the tenant fence while another
transaction owns it, prove the source remains lockable, then require both real
operations to commit. Keep the browser's immediate post-upload save and exact
response/hash/reload/download checks; do not wait for indexing to disguise a
race the user can encounter.
