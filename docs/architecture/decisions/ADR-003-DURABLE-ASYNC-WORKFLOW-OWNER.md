# ADR-003: Durable async/workflow ownership

- Status: Accepted as the repository runtime boundary; external Temporal production readiness remains separately gated
- Date: 2026-08-06
- Scope: ARCH-OPS-01, IPLF-027, later long-running IP operations

## Context

CaseOps already contains a typed Temporal runtime foundation in
`services/durable_workflows.py`, notification workflows/workers, Cloud Run Jobs
for bounded batch/drain execution, scheduler inventory controls, and durable
domain-specific intent/provider records. M2 adds transactional outbox and
consumer-effect contracts. A third queue or workflow framework would split
retry, lease, cancellation, readiness, observability, and replay ownership.

## Decision

CaseOps uses one layered durable-async model:

1. The request transaction writes the domain state, audit evidence, and a
   neutral `domain_outbox_events` row atomically.
2. `domain_consumer_effects` owns idempotent consumer checkpoints/effects.
3. Configured multi-step or long-running workflows use the existing Temporal
   adapter and worker conventions in `services/durable_workflows.py`.
4. Bounded migrations, scheduled polling, report generation, and queue drains
   use exact-image Cloud Run Jobs under the existing scheduler/job inventory.
5. `NotificationDeliveryIntent` remains the sole recipient/channel delivery
   effect owner; provider-operation rows remain external-operation evidence.

Celery, RQ, Dramatiq, a second Temporal wrapper, IP-specific queue tables, and
IP-specific dead-letter/replay dashboards are prohibited. An adapter declares
its idempotency key, retry class, lease/fencing token, cancellation semantics,
checkpoint/result manifest, redaction, metrics, and kill switch before use.

## Cancellation and failure semantics

- States are `queued`, `running`, `succeeded`, `partially_succeeded`, `failed`,
  `cancel_requested`, `cancelled`, or `expired` where the contract applies.
- Cancellation stops future safe work but never erases committed effects.
- A retried consumer checks its effect key before performing an external or
  irreversible effect.
- Schema contraction waits until all API/job/worker revisions are fenced off
  the old contract.
- Temporal-disabled or provider-unready environments fail closed and retain a
  manual/bounded-job fallback only where the slice explicitly defines it.

## Readiness and rollout

Temporal configuration, TLS/credential presence, dependency availability,
worker build identity, and task queue are reported through the existing
integration/readiness surfaces without exposing secret values. Production
activation remains disabled until the slice-specific readiness and canary gate
passes.

Rollout uses expand schema, deploy compatible producers/consumers, backfill or
requeue only approved manifests, verify idempotency/fencing, switch the producer,
and contract later. Rollback disables the producer/worker, keeps durable rows,
and resumes through the last verified checkpoint; no effect is blindly replayed.
