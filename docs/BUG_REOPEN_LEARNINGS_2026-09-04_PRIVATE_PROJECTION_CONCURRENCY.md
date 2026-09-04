# Private projection concurrency — 2026-09-04 assessment and permanent learnings

## Incident verdict

The production maintenance failures at 11:21:08Z and 11:26:02Z were valid
concurrency defects in the private-projection maintenance path. They were not
projection corruption and did not reopen a Matter. PostgreSQL aborted the
maintenance transaction; later runs at 11:31:33Z and 11:36:29Z retained an
active generation, rebuilt the affected tenant, and reported zero pending or
failed events and no integrity blockers.

The later recovery did not make the defect invalid. The deployed code still
allowed a deterministic lock inversion and reported two known database
concurrency states as generic, immediate release failures.

## Exact root cause

The 11:21 failure was PostgreSQL SQLSTATE `40P01`:

1. Maintenance locked a building `PrivateIndexGeneration` while writing a
   bounded shadow batch.
2. Inserting `PrivateIndexProjectionScope` then requested the Matter foreign
   key's `KEY SHARE` lock.
3. A concurrent lifecycle/source writer already held that Matter and called
   `apply_private_projection_event()`, which waited for the building/ready
   generation.
4. PostgreSQL detected the generation-to-Matter / Matter-to-generation cycle
   and selected maintenance as the deadlock victim.

The 11:26 failure was SQLSTATE `55P03`: maintenance exceeded the configured
five-second lock timeout while acquiring the tenant `Company` serialization
row. The script classified both exceptions as `tenant_maintenance_error`, even
though both are bounded concurrency outcomes and the active security generation
remained intact.

## Where the earlier implementation was shallow

- Earlier PostgreSQL tests proved that a rebuild released parent locks between
  batches, but did not force the inverse overlap in one batch: lifecycle owns a
  Matter, maintenance owns a generation, and each requests the other's row.
- The batch code treated the generation epoch check as sufficient but ignored
  the lock order introduced later by scope foreign-key validation.
- Maintenance recognized only the domain
  `PrivateRetrievalConcurrencyError`. It discarded PostgreSQL's machine-readable
  SQLSTATE and turned known deadlock/lock-timeout outcomes into an opaque
  `OperationalError` release block.
- A later clean status was previously easy to mistake for proof that no code
  correction was required. Recovery proves the fence worked; it does not remove
  the lock inversion or the false alert classification.

## Correctness boundary

- Each batch collects only its bounded scope parents, groups them in the fixed
  order Client, Matter, IP docket, sorts each ID set, and acquires PostgreSQL
  `FOR KEY SHARE` before any generation lock or projection/scope insert.
- A missing or cross-tenant parent is a stale canonical enumeration and fails
  through the existing typed stale-writer boundary. Foreign keys and epoch
  validation remain unchanged.
- Maintenance recognizes only SQLSTATE `40P01` and `55P03` as database
  concurrency. It rolls back, drains/re-inspects from a usable transaction,
  and performs at most the existing one bounded rebuild retry.
- A second concurrency loss may be deferred only when a fresh session proves
  an active generation, no pending/failed events, only repairable blockers, no
  prior event-lag breach, and repair age within 300 seconds.
- Missing active generations, unsafe tombstones, scan truncation, pending or
  failed events, unknown SQLSTATEs, and either SLO breach remain release-blocking.
  Raw SQL, identifiers, and database exception detail remain redacted.
- Cloud Run task retries remain disabled; this correction does not create a
  retry storm or weaken the access/tombstone fence.

## Regression and release boundary

- Unit tests cover `40P01`, `55P03`, bounded retry, second-conflict deferral,
  SLO expiry, missing active generation, unsafe blockers, unknown connection
  failures, statement cancellation, ordinary failures, and redaction.
- A real PostgreSQL regression holds the Matter in a lifecycle transaction,
  observes the shadow batch waiting on that parent, then advances the shadow
  epoch. The lifecycle commit must remain below its lock-timeout budget; the
  stale batch must roll back without a deadlock or partial projections.
- The existing 10,000-projection PostgreSQL statement/latency bound and
  between-batch writer-progress tests must continue to pass.
- A green source-tree test is not closure. The exact merged `origin/main` image
  must be deployed, the production maintenance job must run once to repair if
  needed, and a later cadence after writers stop must report no blockers and
  `rebuild_count=0` before this incident is marked fixed.

## Production closure evidence

The correction was merged and deployed on 2026-09-04 as exact `origin/main`
commit `67b89bdf57ef95df3a671fb2dc2290de5a100046`. The maintenance job was pinned
to API image digest
`sha256:ea73a6a831e93cde7abe449241c743c846305444e983c951c12f50366e62bf7c`.
Before routing production, the clean hotfix tree passed the canonical Docker
verification: PostgreSQL/pgvector `118 passed`, desktop Playwright `182 passed`
with five intentional production-only skips, mobile Playwright `4 passed`,
database migration/index health, and the lifecycle non-reopening regressions.

The scheduler was paused during controlled verification. Manual execution
`caseops-private-projection-maintenance-zbx8z` rebuilt the tenant from the
16:01Z alert and safely deferred a different tenant while exact-release
Playwright was changing its source manifest. It reported `status=ok` and
`release_blocked=false`; this was the expected access fence, not a bypass.
GitHub production verification run `33899032098` then passed all 116 sequential
RAM/IP browser tests, cost acceptance, notice workflow, and public-claims
checks against the exact release.

After those writers stopped, manual execution
`caseops-private-projection-maintenance-5lpjb` cleared every blocker and pending
or failed event. Immediate follow-up execution
`caseops-private-projection-maintenance-p998j` reported all four tenants clean,
`rebuild_count=0`, `status=ok`, and `release_blocked=false`. The scheduler was
then re-enabled at `*/5` in `Asia/Kolkata`; its first automatic execution,
`caseops-private-projection-maintenance-stllv`, repeated the same clean
no-rebuild result. Cloud SQL logs for every verification window contained no
`40P01`, `55P03`, deadlock, or lock-timeout record. This satisfies the release
boundary above and closes the production incident as properly fixed.
