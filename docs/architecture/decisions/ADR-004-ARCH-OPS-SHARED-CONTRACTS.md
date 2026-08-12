# ADR-004: Shared command, pagination, provider, and rollout contracts

- Status: Accepted as a repository admission boundary
- Date: 2026-08-06
- Scope: ARCH-OPS-05 through ARCH-OPS-12 and every later IP behavior slice

## Context

The IP program will add bulk commands, uploaded files, long-running operations,
large listings, provider adapters, additive migrations, high-volume queries,
and gated capabilities. Implementing these independently in each feature would
create incompatible safety and observability rules even when the underlying
state owner is shared.

## Decision

The following contracts are mandatory before a behavior can activate:

1. A bulk command accepts explicit IDs and expected versions or an immutable
   selection manifest. Query-based selection is re-resolved at confirmation,
   returns a preview diff, and records row-level conflicts without replaying
   successful rows.
2. JSON idempotency input uses one documented canonical serialization. A file
   or multipart request additionally hashes canonical metadata, content bytes,
   content length, media type, and declared file/version identity. Client and
   backend golden fixtures must produce identical digests. The neutral API
   admission record is named exactly `api_idempotency_records`; aliases and
   domain-private copies are rejected.
3. Async operations expose `queued`, `running`, `succeeded`,
   `partially_succeeded`, `failed`, `cancel_requested`, `cancelled`, and
   `expired` where applicable, plus safe counts, checkpoint, result manifest,
   correlation, retry eligibility, and cancellation eligibility. Cancellation
   does not erase committed effects.
4. A cursor is signed, expiring, versioned, and scoped to company, actor-access
   fingerprint, sort, filter, and stable-snapshot boundary. A changed scope or
   invalid/expired signature fails closed; a response never silently resumes
   under different semantics.
5. A provider adapter declares capability, jurisdiction/source coverage,
   authentication mode, quota/cost, idempotency, cursor/freshness,
   webhook/poll reconciliation, raw retention, normalized error taxonomy,
   sandbox/fixture, and kill switch. Missing declarations keep readiness red.
6. Schema rollout is expand/backfill/verify/switch/contract. Old and new API,
   job, and worker revisions are tested together against expanded schema with
   fencing and rollback flags. Contraction waits until exact revision evidence
   proves the old path absent.
7. Portfolio, docket, access-filtered search, timeline, report, and audit paths
   attach representative-volume query-plan evidence and bounded eager loading.
   Per-row provider calls and unbounded ORM relationship loading are rejected.
8. Server capability, billing entitlement, and rollout safety are separate
   decisions with reason, owner, and expiry. The server authorizes every action;
   frontend visibility is only a rendering of server state.

## Enforcement and evidence

`ARCH_OPS_CONTRACT.yaml` maps every binding requirement to its owner and
repository evidence. `ip_arch_ops_contract.py` validates exact PRD coverage,
artifact existence, catalogue schemas, and these non-negotiable contract
clauses in CI. The bounded IPLF-027A data-class registry must match the five
admitted foundation table names before a migration can land; this admission
check does not claim the IPLF-028 retention/hold/export implementation. Each
feature still supplies behavior-level unit/integration,
mixed-revision, performance, and deployed journey evidence when its own slice
is implemented; this ADR does not fabricate that future acceptance.

## Consequences

- Shared contracts are designed once and reused across Matter and IP work.
- An incomplete declaration is a fail-closed readiness result, not an implicit
  default.
- The contracts add no nullable future schema and authorize no provider spend.
- Any replacement requires another accepted ADR and a one-writer migration.
