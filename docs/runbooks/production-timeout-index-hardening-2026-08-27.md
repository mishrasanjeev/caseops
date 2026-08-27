# Production Timeout and Index Hardening

**Date:** 2026-08-27
**Incident:** GitHub Actions run `33009595343`
**Scope:** production release verification, request deadlines, IP docket listing,
and PostgreSQL index completeness

## Incident conclusion

Run `33009595343` did not fail in Playwright and did not execute a database
query. The push-triggered workflow expected commit
`bf55f769...` to appear on both production services, but no deployment had
been started for that push. Production remained on `bf223d...` for the entire
1,500-second polling window. The commit was later superseded by PR `#363` and
main commit `35d4877...`; it was never a production release.

The repeat failure was a control-plane contract defect:

1. a push to `main` started production verification;
2. the repository has a separate, operator-run migration-first deployment;
3. the verifier waited 25 minutes for a release that did not exist; and
4. the timeout was reported next to Playwright even though browser tests never
   started.

Increasing the 25-minute wait would only conceal the same defect for longer.

## Production observations

A read-only review of the preceding 14 days found five Cloud Run request
timeouts, all on obsolete API revision `caseops-api-00300` on 2026-08-17. The
current revision had no equivalent platform-max timeout, but concurrent page
requests queued behind the API's concurrency-one boundary. Observed examples
included notice-owner reads near 44 seconds, recommendations near 27-37
seconds, IP docket listing near 8-20 seconds, conflict checks near 43 seconds,
and otherwise ordinary reads near 10-20 seconds during bursts.

The production schema was at Alembic revision `20260826_0002`, had no invalid
indexes, and had 220 foreign-key definitions without complete leading-column
index coverage. The previous weekly index check inspected only five hard-coded
indexes and was not a complete schema invariant. High cumulative sequential
scan counters were also present on corpus-scale tables, but a sequential scan
counter alone is not proof that an index is missing; corpus scans and small
table scans can be intentional.

## Permanent release contract

- `prod-verify.yml` no longer runs on a push to `main`.
- Scheduled verification checks that API and web serve one consistent release.
- An exact-release dispatch requires a full 40-character commit SHA.
- `deploy-prod.sh` dispatches that verifier only after migration, recurring-job
  reconciliation, database-index health, API/web identity, traffic, health,
  and ClamAV gates have passed.
- Exact identity polling is capped at 180 seconds with five-second endpoint
  timeouts and never sleeps beyond its deadline.
- A missing deployment now fails quickly and truthfully instead of consuming a
  25-minute runner before any browser test begins.

## Enforced timeout budget

| Boundary | Budget | Behavior |
| --- | ---: | --- |
| PostgreSQL connection | 10 seconds | connection attempt fails closed |
| PostgreSQL lock wait | 5 seconds in production API | retryable RFC 7807 `503` |
| PostgreSQL statement | 60 seconds in production API | RFC 7807 `504` |
| Idle database transaction | 60 seconds in production API | server terminates abandoned transaction |
| Browser API request | 90 seconds | abort plus actionable `NetworkError` |
| Browser auth refresh | 15 seconds | bounded refresh and normal auth recovery |
| Cloud Run API request | 120 seconds | outer platform ceiling |
| Release identity fetch | 5 seconds per attempt | bounded control-plane I/O |
| Release convergence grace | 180 seconds | exact API/web SHA required |

Background and batch jobs retain task-specific limits. Their default database
statement limit remains unlimited unless the job opts in, so a 60-second
interactive budget cannot truncate an approved corpus or migration operation.

## Database index contract

Migration `20260827_0001` provides complete schema-wide foreign-key support and
the hot IP list index `(company_id, is_active, updated_at, id)`.

- Primary keys, unique constraints, and non-partial index prefixes count as
  coverage.
- Every column of a composite foreign key must be present in the index prefix;
  equality-column order may differ.
- Generated names are deterministic and remain within PostgreSQL's 63-byte
  identifier limit.
- PostgreSQL builds missing indexes concurrently with a five-second lock wait
  and a per-index 30-minute statement limit.
- An interrupted concurrent build is restartable: an invalid or unready
  same-name remnant is dropped concurrently before retry.
- The migration verifies the resulting live definitions before recording
  success.
- Model metadata applies the same rule, preventing `create_all` test schemas
  from drifting from Alembic-managed schemas.

The `caseops-db-index-health` command fails on any of these conditions:

- schema revision is not exactly `20260827_0001`;
- a foreign-key definition lacks complete index-prefix coverage;
- a model-declared index is missing;
- an index name exists with different columns; or
- a PostgreSQL index is invalid or not ready.

It reports high sequential-scan counters as diagnostics without pretending
that every sequential scan should be replaced by an index. The immutable-image
health job runs as a pre-route production deployment gate and weekly at
02:30 UTC. Local Docker acceptance runs the same command against migrated
PostgreSQL before Playwright.

## Application work bound

The IP docket list is limited to 100 records by default and 200 maximum, reads
only active non-archived records, and uses deterministic indexed ordering. Its
nested docket data and deadline-incident children are loaded in fixed batches,
reducing the previous per-docket query fanout to a constant query budget.

The IP page demand-loads documents, proceedings, hearing/deadline, and access
work areas. Hidden workspaces no longer issue all supporting requests during
the initial docket render. Deep links still open the selected access workspace.

All direct first-party web requests now use `fetchWithTimeout`. A static test
rejects any new direct `fetch` outside that helper and rejects Python `httpx`
or `urlopen` construction without a declared timeout.

## Operator sequence

1. Merge only after local API, web, migration, Docker/PostgreSQL, index-health,
   and Docker Playwright gates pass.
2. Require PR CI and exact-main CI to be green.
3. Run `scripts/deploy-prod.sh <full-main-sha>` from a clean exact-main
   worktree.
4. Do not bypass the migration or pre-route index-health jobs.
5. Confirm API `/api/build` and web `/api/release-identity` return the same full
   SHA and API `/api/health` returns `ok`.
6. Wait for the exact-release `prod-verify.yml` dispatch and require a green
   result before release sign-off.
7. Preserve the paused judge-mapping and authority-extraction governance jobs;
   timeout remediation does not authorize those writers.

## Verification record

The release evidence must record the final local test counts, Docker migration
and index-health output, PR and exact-main CI run IDs, production migration and
index-health execution IDs, Cloud Run revision identities, and exact-release
Playwright run. A green source-tree test or a dispatched-but-unfinished workflow
is not production evidence.
