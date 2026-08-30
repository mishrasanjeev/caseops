# IPLF-027B — UJ-67-EXC-01 PostgreSQL lock-window evidence

**Date:** 31 August 2026  
**Scope:** only `UJ-67-EXC-01` (lock/table-scan estimate exceeds the deploy window)  
**Status:** repository implementation and local PostgreSQL proof; not deployed

## Root cause and correction

The application PostgreSQL engine supplied server-enforced connection,
statement, lock, and idle-transaction budgets. Alembic created a separate
engine without those options. A candidate migration blocked by an old-revision
transaction could therefore wait for the complete Cloud Run migration-job
timeout rather than failing inside the database lock budget.

`caseops_api.db.connection_safety` now owns the shared PostgreSQL timeout
options. Both the application engine and `alembic/env.py` use that contract.
Alembic applies the budgets when it opens its first PostgreSQL connection, so
they protect every migration statement without relying on a manual approval or
per-migration comment. SQLite keeps its existing connection behavior.

No migration, table, column, index, constraint, backfill, seed, or runtime flag
was added or changed by this increment.

## Production-dialect regression

The stable test ID is `IPLF-UJ-67-EXC-01` at
`apps/api/tests/test_postgres_validation.py::test_uj67_exc01_migration_lock_and_table_scan_windows_are_bounded`.
It runs against Docker `pgvector/pgvector:pg17`, the PostgreSQL major version
used by production, after `alembic upgrade head`.

The test creates a bounded 20,000-row unlogged table and proves two independent
failure modes through the exact Alembic connection-argument builder:

1. An old-revision transaction holds `ACCESS SHARE`; a candidate column rewrite
   requiring `ACCESS EXCLUSIVE` fails with SQLSTATE `55P03` inside a 200 ms lock
   budget.
2. A deliberately underestimated Cartesian table scan fails with SQLSTATE
   `57014` inside a 200 ms statement budget.

Both paths are bounded to less than 1.5 seconds, require the server-reported
timeout values, roll back the failed transaction, prove the connection remains
usable, and verify that the column type and all 20,000 rows are unchanged. The
smaller CI budgets exercise the same builder that production populates from its
validated 5-second lock and 60-second statement settings.

Implementation anchor `ddc338f8` is based on canonical `origin/main`
`eb584dad`. Before publication, the full evidence commit is retested from a
clean exact checkout against a fresh isolated Docker PostgreSQL/pgvector
container; the Draft PR and operator report carry that final immutable SHA.

## Honest boundary

This closes the missing local production-dialect evidence for the lock and
table-scan window only. It does not close IPLF-027B, UJ-67, or M2. The canonical
slice therefore remains `implementation=in_progress`,
`verification=not_run`, and `release=blocked` until its other allocated paths
and exact deployed acceptance are complete.

Still open on IPLF-027B:

- `UJ-67-EXC-03`: a real backfill mismatch and reconciliation owner;
- `UJ-67-EXC-04`: exact deployed canary/SLO failure and recovery evidence;
- `UJ-67-EXC-06`: authorized restore/roll-forward rehearsal beyond the existing
  destructive-downgrade refusal; and
- the separate A0 retirement/T_FENCE and A1/A2 release-control gates already
  recorded in the canonical manifest.

No rule-governance capability was enabled, no safety gate was waived, and no
production claim is made by this local evidence.
