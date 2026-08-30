# IPLF-027B — PostgreSQL migration timeout containment

**Date:** 31 August 2026

**Scope:** defense-in-depth containment after migration work starts

**Status:** repository implementation and local PostgreSQL proof; not deployed

## Exact boundary

This evidence does **not** close `UJ-67-EXC-01`. That path requires a bounded
estimate or preflight refusal before a lock-heavy or table-scan-heavy migration
starts. PostgreSQL `lock_timeout` and `statement_timeout` act only after the
candidate has connected and attempted work. The canonical path therefore stays
`planned:IPLF-UJ-67-EXC-01`, with no path evidence attached.

The defensive control is still useful: if an estimate is wrong or a live lock
appears after preflight, the database aborts the candidate inside an explicit
budget instead of allowing the Cloud Run migration task to wait indefinitely.

## Root cause and correction

The application PostgreSQL engine supplied server-enforced connection,
statement, lock, and idle-transaction budgets. Alembic created a separate
engine without those options. A candidate migration blocked by an old-revision
transaction could therefore wait for the complete migration-job timeout.

`caseops_api.db.connection_safety` now owns the shared option construction.
Alembic uses dedicated migration settings rather than inheriting interactive
API tuning:

- connect timeout: 10 seconds;
- statement timeout: 900,000 ms;
- lock timeout: 5,000 ms; and
- idle-in-transaction timeout: 60,000 ms.

The checked-in Cloud Run migration manifest binds those values. The canonical
production deploy script updates them on the migration job, reads the job back,
and refuses execution if any value drifted. URL-supplied libpq options such as
`search_path` or `application_name` are preserved; owned timeout GUCs are
appended last and remain authoritative even if the URL attempts to disable a
timeout.

No migration, table, column, index, constraint, backfill, seed, or runtime flag
was added or changed by this increment.

## Regression proof

`apps/api/tests/test_migration_connection_safety.py` executes Alembic's real
`env.py` path and captures the `engine_from_config` call. It proves that the
dedicated migration settings and merged URL options reach the engine; removing
`connect_args` from `env.py` fails the test.

The production-dialect regression is
`apps/api/tests/test_postgres_validation.py::test_migration_database_timeouts_bound_work_after_start`.
It runs against Docker `pgvector/pgvector:pg17` after `alembic upgrade head`,
creates a bounded 20,000-row unlogged table, and proves two independent
containment modes through the exact Alembic connection-argument builder:

1. An old-revision transaction holds `ACCESS SHARE`; a candidate column rewrite
   requiring `ACCESS EXCLUSIVE` fails with SQLSTATE `55P03` inside a 200 ms lock
   budget.
2. A deliberately underestimated Cartesian table scan fails with SQLSTATE
   `57014` inside a 200 ms statement budget.

Both connections preserve a URL-supplied `application_name`, report the
enforced timeout values, fail in less than 1.5 seconds, recover after rollback,
and leave the column type and all 20,000 rows unchanged.

## Immutable evidence chain

Exact clean implementation revision
`d7541ff8e262b7c468f785af9a45c2cd737ccc4a` passed the three-case fresh Docker
PG17 proof in 18.50 seconds with pgvector 0.8.3, Alembic head `20260830_0002`,
and zero retained probe tables.

The canonical manifest records that full immutable implementation revision.
Because a commit cannot contain its own SHA, the later evidence commit must be
treated as unverified until an exact-checkout retest completes. The Draft PR
and operator report record the later exact SHA and its independent PG17 result;
they must not project that result backward onto an untested commit.

## Still open on IPLF-027B

- `UJ-67-EXC-01`: real estimate/preflight refusal before migration work starts;
- `UJ-67-EXC-03`: backfill mismatch and reconciliation proof;
- `UJ-67-EXC-04`: exact deployed canary/SLO failure and recovery evidence;
- `UJ-67-EXC-06`: authorized restore/roll-forward rehearsal beyond the existing
  destructive-downgrade refusal; and
- the separate A0 retirement/T_FENCE and A1/A2 release-control gates already
  recorded in the canonical manifest.

IPLF-027B therefore remains `implementation=in_progress`,
`verification=not_run`, and `release=blocked`. No production completion,
deployment, or UJ-67 path-closure claim is made.
