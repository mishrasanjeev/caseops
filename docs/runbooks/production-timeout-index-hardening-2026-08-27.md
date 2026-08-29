# Production Timeout and Index Hardening

**Date:** 2026-08-27
**Incident:** GitHub Actions run `33009595343`
**Scope:** production release verification, request deadlines, event-loop and
transaction starvation, IP docket listing, and PostgreSQL index completeness

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

The first exact-release retry advanced production to migration
`20260827_0001`, then stopped before traffic routing when the index-health job
exceeded its 512 MiB memory limit. The checker itself had not exhausted its
query or task deadline. Its Cloud Run command was `uv run
caseops-db-index-health`; inside the already-built API image, `uv run` created
`/app/.venv` and resolved and installed 137 packages before starting the baked
console command. Five other recurring jobs had the same redundant runtime
dependency-resolution path. Production traffic correctly remained on the
previous API and web revisions.

Two later retries also stopped before traffic routing. Release `9f1e3be...`
supplied the reminders arguments as two subprocess tokens, `--args` and
`--mode=auto,--limit=200`; gcloud parsed the leading-dash value as another
option. Release `04787ab...` bound an alternate-delimiter value as one token,
but the Windows `gcloud.cmd` shim interpreted its pipe delimiter before gcloud
received it. These were serialization defects in the release control plane,
not reminders runtime failures.

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

## Recurring-job startup contract

- The inventory owns the complete runtime shape of all eight recurring jobs:
  command, arguments, environment, secret bindings, service account, Cloud SQL
  attachment, CPU, memory, retries, and task timeout.
- Production jobs invoke installed console commands or the baked Python
  interpreter directly. Runtime `uv` or `uvx` startup is rejected by inventory
  validation because it can create a virtual environment, contact package
  registries, consume memory, and spend the task deadline before application
  code starts.
- A non-empty argument vector is emitted as one bound gcloud token using its
  default comma list format, for example
  `--args=--mode=auto,--limit=200`. Leading dashes therefore cannot be parsed as
  gcloud options, and the token contains no Windows shell metacharacters.
- Inventory validation rejects commas inside individual command or argument
  values, making the comma list serialization unambiguous and fail-closed.
- An empty argument vector is emitted as the single token `--args=`, which
  clears previously configured arguments without exposing a following token to
  gcloud option parsing.
- Regression tests exercise the exact reminders arguments, empty-list clearing,
  and rejection of ambiguous comma-bearing values.
- Local Docker verification runs `caseops-db-index-health` with a hard 512 MiB
  memory and swap limit. It must exit zero, report `status=ok`, and finish
  without an OOM kill before production deployment.
- The Windows acceptance harness sets `UV_LINK_MODE=copy` before frozen host
  dependency sync. OneDrive-backed worktrees can reject cache hardlinks with OS
  error 396; copy mode preserves the exact lockfile while avoiding that
  filesystem-specific setup failure.
- This repair does not increase the index job's memory or timeout. It removes
  unbounded duplicate startup work and retains the measured resource ceiling.
- Authority metadata extraction and judge mapping remain `PAUSED`; converging
  their runtime contracts does not authorize or execute either workload.

## Enforced timeout budget

| Boundary | Budget | Behavior |
| --- | ---: | --- |
| PostgreSQL connection | 10 seconds | connection attempt fails closed |
| PostgreSQL lock wait | 5 seconds by default in every runtime | retryable RFC 7807 `503` |
| PostgreSQL statement | 60 seconds by default in every runtime | RFC 7807 `504` |
| Idle database transaction | 60 seconds by default in every runtime | server terminates abandoned transaction |
| Browser API request | 90 seconds | abort plus actionable `NetworkError` |
| Browser auth refresh | 15 seconds | bounded refresh and normal auth recovery |
| Cloud Run API request | 120 seconds | outer platform ceiling |
| Release identity fetch | 5 seconds per attempt | bounded control-plane I/O |
| Release convergence grace | 180 seconds | exact API/web SHA required |

Background, batch, and migration jobs inherit the finite defaults. A reviewed
operation that legitimately needs longer must set a larger transaction-local
statement timeout; it may not disable the global lock or idle-transaction
ceiling. Docker pins the same defaults explicitly for API, migration, and
worker containers so workstation acceptance exercises the production failure
mode instead of silently using unlimited waits.

## Full-suite starvation finding

The exact-image Docker run reached 137 of 168 Playwright cases before the
portal invitation test exposed a second, application-level failure. The Admin
page's read-only storage summary called the billing bootstrap helper. That
helper acquired `FOR UPDATE` locks on `companies` and `billing_accounts`, then
left the read transaction open until FastAPI dependency teardown. A concurrent
portal invitation used synchronous SQL inside an `async` route and waited on
an audit-event foreign-key check. Because that wait occupied the event loop,
the storage request's dependency finalizer could not close its transaction.
PostgreSQL showed the blocker as `idle in transaction` and every unrelated
health/page request then queued behind it.

The permanent controls are:

- effective storage-quota reads resolve only already-persisted entitlements;
  they never bootstrap billing state or acquire mutation locks;
- explicit billing and mutation workflows remain the only owners allowed to
  create grandfathered billing rows;
- portal invitation and magic-link delivery handlers are synchronous FastAPI
  handlers, so database or provider waits run in the worker pool instead of on
  the event loop;
- nonzero lock, statement, and idle-transaction limits are application
  defaults, not deploy-script-only overrides; and
- full Docker acceptance keeps the notice upload, Admin storage read, portal
  invitation, query recovery, and health workflows in one ordered run so the
  cross-request regression remains observable.

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
- Downgrade index removal stays inside Alembic's migration transaction. If a
  later restore-forward guard refuses a multi-revision downgrade, the index
  removals and revision change roll back together.
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

Admin storage summaries are now side-effect-free reads. They do not create a
billing account or subscription and therefore do not hold tenant billing
mutation locks while the page issues its other concurrent requests.

All direct first-party web requests now use `fetchWithTimeout`. A static test
rejects any new direct `fetch` outside that helper and rejects Python `httpx`
or `urlopen` construction without a declared timeout.

Product Guide projection validation normalizes only CRLF to LF before its
canonical byte comparison. This keeps stale or hand-edited content fail-closed
while allowing the same committed generated JSON to pass on Windows Git
checkouts and Linux CI runners.

## Browser transport contract

PR `#367` initially completed 165 Playwright cases before one lifecycle
verification GET failed with `ECONNRESET`; the API logged no exception or
shutdown and the following 22 cases passed. The request had not reached
FastAPI, so this was a stale or reset keep-alive transport, not a failed legal
state transition.

- July 22 local and production lifecycle verification GETs allow at most two
  Playwright network retries. Playwright limits this option to `ECONNRESET` and
  does not retry HTTP response codes.
- Mutation requests are never transport-retried. Every lifecycle write remains
  single-attempt and protected by expected status, timestamp, and lifecycle
  state assertions.
- A retried GET must still return the exact expected HTTP status and persisted
  legal state. Retry exhaustion remains a hard test failure.
- The focused serial lifecycle flow must pass ten complete repetitions before
  the PR is updated, followed by the exact-commit Docker and CI browser gates.

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
and index-health output, the absence of lingering `idle in transaction`
sessions after browser acceptance, proof that an unrelated health request
remains responsive after timeout/recovery flows, PR and exact-main CI run IDs,
production migration and index-health execution IDs, Cloud Run revision
identities, and exact-release Playwright run. A green source-tree test or a
dispatched-but-unfinished workflow is not production evidence.
