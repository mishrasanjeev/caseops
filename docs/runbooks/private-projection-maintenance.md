# Private Projection Maintenance

## Purpose

This runbook covers the tenant-private retrieval projection worker, its five-minute
Cloud Run Job cadence, revocation-lag alert, bounded repair path, and rollback. The
worker is an operational consumer of canonical source and authorization state. It
must never override matter lifecycle, access-control, legal-hold, or approved data
disposition decisions.

## Production Contract

- Scheduler: `caseops-private-projection-maintenance-cadence`
- Cloud Run Job: `caseops-private-projection-maintenance`
- Cadence: every five minutes in `Asia/Kolkata`
- Command: `caseops-private-projection-maintenance --mode maintain`
- Tenant scan cap: 50 companies per run
- Automatic rebuild cap: 5 companies per run
- Per-tenant projection cap: 20,000 rows, written in batches of at most 50
- Batch work bound: one shadow epoch lock/check, one bulk projection flush and
  one bulk scope flush per batch; the 10,000-row PostgreSQL gate permits at most
  850 SQL statements and 60 seconds
- Rebuild ownership: one PostgreSQL advisory lease per tenant, retained across
  bounded batch commits; a second worker waits at most 45 seconds
- Concurrent-change recovery: one in-process replan for a typed rebuild conflict,
  including a competing shadow, a newly pending event, active-generation turnover,
  or an access/tombstone epoch fence
- Repeated-change handling: after the replan, another typed epoch conflict removes
  the second partial shadow and defers only repairable blockers to the next cadence
  while their persisted repair age is at most 300 seconds
- Event lag SLO: 300 seconds
- Maintenance capacity: 4 GiB memory and a 15-minute task deadline. The
  production corpus includes tenants with more than 10,000 active Matters;
  the previous 1 GiB/5-minute task could be killed mid-rebuild, leaving an
  unreadable building shadow for the next cadence to recover.
- Event attempts: 3, with 30-second then 60-second application backoff
- Scheduler delivery attempts: at most 5 within 900 seconds
- Alert policy: `CaseOps private projection maintenance failure`
- Run log prefix: `CASEOPS_PRIVATE_PROJECTION`

Creating a Matter or IP docket in a tenant with an active private generation
emits an applied `source_changed` event. Because a new source has no projection
to tombstone, the event invalidates the active generation manifest. The next
bounded maintenance run must observe `active_generation_manifest_mismatch`,
rebuild, and project the new source. Do not clear the blocker or weaken saved
source checks merely to make the new record immediately reviewable.

The scheduler inventory is authoritative. Reconcile or inspect it with the exact
immutable API image digest; do not deploy or verify a mutable tag.

During an active private-projection incident, keep the cadence paused through the
canonical deployment by setting `CASEOPS_PRIVATE_PROJECTION_SCHEDULER_HOLD=true`.
This changes only the effective reconcile state for that release; the checked-in
inventory remains `ENABLED`. The deploy script defaults this hold to `true`.
`scheduler_inventory.py reconcile` will not transition this private scheduler
from paused to enabled; use its evidence-checked `resume` command. The paid
case-tracking scheduler keeps its separate resume behavior.

```bash
python scripts/scheduler_inventory.py verify \
  --project perfect-period-305406 \
  --region asia-south1 \
  --image "${API_IMMUTABLE_IMAGE}"
```

## Alert Meaning

An `ERROR` maintenance record means at least one of these conditions occurred:

- a pending revocation exceeded the 300-second SLO, even if that run recovered it;
- an event exhausted its bounded application attempts;
- projection or scope integrity remained blocked after bounded repair;
- more than 50 tenants required inspection in one run;
- a rebuild or database operation failed.

The per-tenant cap is intentionally above the 9,820 eligible projections
observed in production on 2026-09-01 while remaining finite. If production
volume reaches the 20,000-row ceiling, the worker must report the bounded error
detail and keep the last verified generation active; do not silently truncate.

A source or access mutation may deliberately fence a shadow while the worker is
enumerating or writing it. A deploy can also place the exact-release QA bootstrap
beside a scheduled maintenance execution. Rebuild owners therefore serialize on a
tenant-scoped PostgreSQL advisory lease that does not block canonical request
writers and survives the worker's bounded commits. The worker removes a fenced
shadow's partial projections, drains any newly due tenant event, re-inspects
integrity, and permits exactly one fresh rebuild. Rebuild writes are bulked per
50-row epoch-fenced batch rather than issuing generation, projection, scope and
cache work per row; this reduces the stale-writer exposure window without
weakening the fence. A second typed epoch conflict is reported as
`repair_deferred=true` with `oldest_repair_lag_seconds_after`; it does not fail the
run while the active generation exists, every remaining blocker is repairable,
and the repair age is within 300 seconds. The next cadence must replan from
canonical state. A repair SLO breach, lease wait beyond 45 seconds,
non-repairable blocker, or any other exception fails the tenant and the job.
Cloud Run task retries remain disabled.

Continuous production-test mutation is not quiescence. A shared QA tenant can
legitimately fence every shadow while dated browser journeys create, dispose,
or reopen records. Do not reinterpret this as projection corruption, suppress
the tenant, or relax the 300-second release blocker. Correlate the tenant's
applied event epochs with the test window, let the workload stop, then require
one clean cadence (which may rebuild) followed by a second clean cadence with
no rebuild. A new event
after a clean rebuild starts a new repair interval; it is not evidence that the
preceding rebuild failed.

Recurring scheduled production verification is read-only. Mutation-capable RAM,
Notice, cost and patent journeys run only for an exact-release dispatch. The
canonical deploy defaults to pausing and draining private-projection maintenance
before those release-owned QA mutations and leaves the cadence paused after
dispatch. Resume it only after the dispatched workflow succeeds and two
**consecutive later** maintenance executions are clean, serial, and run from the
exact immutable API image; the second must report `rebuild_count=0`. The first
execution after a long QA hold may recover old work while reporting
`lag_slo_breached_before_recovery=true` and a blocked result. Keep that failure
and its lag history intact, then obtain two later clean executions. This prevents
synthetic QA writes from repeatedly fencing a legitimate shadow while preserving
the same five-minute SLO and alert contract for every tenant.

The operator supplies the exact 40-character release SHA, successful
`workflow_dispatch` prod-verify run ID, and immutable API image digest. The guard
reads the latest dispatch and its required job outcomes from GitHub, checks the
recorded serving SHA and API revision in the release-resolution job log, rejects
any active prod-verify run, and rejects future-dated completion evidence. It
requires the current service's latest-ready revision to equal that QA revision,
with exactly one untagged status-traffic entry at 100% on that revision. The
service template may retain a mutable image tag; the guard binds the immutable
digest from the QA revision and the maintenance executions instead. It also
checks the paused scheduler inventory contract, the two newest Cloud Run
execution outcomes, and each execution-scoped structured stdout log. There is
no arbitrary QA age cutoff: a long CI delay does not require rerunning
mutation-capable QA when two later clean maintenance executions exist.
Each clean report must have no blocker, deferred repair, pending/failed event,
truncated candidate scan, or SLO breach. Missing, malformed, superseded, or unavailable
evidence leaves the cadence paused. An earlier blocked execution is not erased or
reclassified when later runs converge.

```bash
gcloud run jobs execute caseops-private-projection-maintenance \
  --project perfect-period-305406 --region asia-south1 --wait
```

Inspect that execution and its `CASEOPS_PRIVATE_PROJECTION` record. Repeat the
manual execution only after the prior one completes, until the two latest runs
meet the clean criteria. A blocked post-QA repair remains in the history; it is
not one of the two qualifying runs. Then resume:

```bash
python scripts/scheduler_inventory.py resume \
  --scheduler caseops-private-projection-maintenance-cadence \
  --project perfect-period-305406 --region asia-south1 \
  --image "${API_IMMUTABLE_IMAGE}" \
  --release-sha "${EXACT_RELEASE_SHA}" --qa-run-id "${PROD_VERIFY_RUN_ID}"
```

This command is an operator guard, not an IAM boundary: a principal with direct
Cloud Scheduler ResumeJob permission can bypass the script. Restrict that
permission and audit direct resume calls separately. GitHub and Cloud Logging
availability are required at resume time; the guard does not issue production
maintenance executions or re-run QA itself.

On 2026-09-25, prod-verify dispatch `36091367446` ran 03:41-04:46 UTC while
an explicit operator-credential CloudScheduler.ResumeJob occurred at
03:39:53/54 UTC. Maintenance deferred at 04:31, breached at 04:36 (369 seconds)
and 04:41 (701 seconds), then rebuilt at 04:46. The 701-second breach remains
incident evidence even after later clean cadences.

An interrupted worker can leave an unreadable `building` or `ready` shadow behind
before its normal exception cleanup runs. Once the next worker owns the tenant
advisory lease, a shadow older than 15 minutes is treated as crashed residue: its
payloads are deleted, the generation is retained as `failed` with
`stale_rebuild_recovered`, and the active generation remains untouched. A recent
shadow is never force-removed; the lease wait and epoch fence remain fail-closed.
This recovery is bounded and must be covered by a subsequent clean cadence, not
used to mask an active writer.

The structured record contains a correlation ID, affected company IDs, event and
repair lag, pending and failed counts, blockers, whether a bounded rebuild ran,
the count of stale shadows recovered, and whether repair was safely deferred. It
contains no source text, document
names, matter names, user email, embedding, or source ID.

## Triage

1. Confirm the alerting job revision and image digest match the intended release.
2. Read the latest job execution and locate the `CASEOPS_PRIVATE_PROJECTION` record.
3. Record the correlation ID, company ID, blocker list, retry count, and oldest lag.
4. Confirm the API health endpoint and an unrelated authenticated endpoint remain
   responsive. A stalled worker must not be treated only as a private-index issue.
5. Inspect the tenant without returning source content:

```bash
gcloud run jobs execute caseops-private-projection-maintenance \
  --region asia-south1 --project perfect-period-305406 --wait
```

For a single tenant, run the same immutable image with `--mode integrity` and the
server-owned company ID. Do not put a company slug, user email, document name, or
source content in job arguments or incident notes.

## Recovery

- `pending_projection_events`: allow the bounded retry window to finish. A due
  event remains fail-closed for hydration throughout the wait.
- `failed_projection_events`: diagnose the recorded error code, correct the cause,
  and create an explicit operator-controlled replay plan. Never rewrite an applied
  or failed ledger row in place.
- `projection_event_lag_slo_exceeded`: treat as an incident even when the next run
  recovers. Establish why the five-minute SLO was missed before closing the alert.
- `active_generation_manifest_mismatch`, `orphan_or_stale_scopes`, or
  `stale_or_ineligible_sources`: the worker may build a bounded shadow generation
  and activate it only after integrity passes. The last verified generation remains
  active until that point. One typed concurrency loss is replanned in-process after
  rollback, event drain, and integrity re-inspection. A second typed epoch loss may
  defer to the next cadence only while `oldest_repair_lag_seconds_after <= 300` and
  `repair_lag_slo_breached=false`; it becomes release-blocking when that persisted
  age exceeds the SLO. Do not add Cloud Run retries or extend the lease wait to
  hide a stuck rebuild owner.
- `integrity_scan_limit_exceeded` or candidate truncation: stop automatic repair
  and prepare a larger offline, tenant-bounded plan with query-count evidence.
- `unsafe_tombstone_payload`: do not rebuild over it. Preserve evidence, block the
  release, and investigate why tombstoned content or an embedding remains.

## Approved Disposition Evidence

The private-index disposition executor accepts only a separately approved `execute`
operation that exactly matches its immutable completed dry-run manifest. Held,
blocked, ambiguous, or invented tenant targets are rejected.

Local private-index erasure records a durable receipt. An external embedding
provider without a per-request deletion API records an explicit
`provider_deletion_contract_delay` exception and, when configured, its expected
resolution date. Absence of a provider receipt is never interpreted as deletion.
Provider exceptions remain open until contractual deletion evidence is attached by
the canonical data-governance process.

## Rollback

1. Pause only `caseops-private-projection-maintenance-cadence`. Preserve the
   intentionally paused authority and judge-mapping schedulers.
2. Leave the last verified active generation in place. Do not reactivate a retired
   generation and do not remove tombstones, event rows, or disposition checkpoints.
3. Roll API traffic back to the last verified immutable revision if the release
   introduced the defect.
4. Keep hydration fail-closed while the consumer is paused. Revoked, stale, or
   unauthorized content must not be returned to improve availability.
5. Correct forward, rerun migration and focused PostgreSQL checks, then execute one
   canary maintenance run before resuming the cadence.
6. Deploy with `CASEOPS_PRIVATE_PROJECTION_SCHEDULER_HOLD=true`, reconcile scheduler
   inventory and alert policy, verify latest-only traffic, and prove the same dated
   production browser scenario before closing rollback.

Database downgrade is not a normal rollback. The migration refuses downgrade when
retry or disposition evidence exists because deleting that evidence would make the
audit claim unprovable.

## Close Criteria

Close the alert only when all of the following are true:

- the exact immutable job revision completed successfully;
- pending and failed event counts are zero for every affected tenant;
- oldest pending lag is absent or within 300 seconds;
- any deferred repair converged on a later run and its oldest repair lag never
  exceeded 300 seconds;
- integrity reports no blockers and no unsafe tombstone payload;
- an unrelated endpoint remains responsive;
- scheduler retry configuration and invoker IAM match inventory;
- the monitoring notification channel is enabled and verified;
- provider deletion-delay exceptions, if any, remain explicitly tracked rather
  than being counted as completed receipts;
- incident evidence records the correlation ID, revision, image digest, timestamps,
  commands, outcomes, and operator.
