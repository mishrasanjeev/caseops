# Shared reliability foundation (IPLF-027A)

## Boundary

IPLF-027A supplies the repository implementation of the neutral reliability
and inert workflow foundations allocated to IPLF-027. It does not activate a
legal workflow, drain an outbox consumer, dispatch a notification, change a
legal lifecycle, or claim the retained-data operations allocated to IPLF-028.

The two independent runtime controls remain fail-closed by default:

- `CASEOPS_DOMAIN_OUTBOX_CONSUMERS_ENABLED`
- `CASEOPS_IP_WORKFLOW_COMMANDS_ENABLED`

Their rollout expiries are separate from the broader IP-workspace and durable
workflow flags. IPLF-027B owns any approved activation, operator policy, user
workflow, exception handling, and deployed acceptance.

## Canonical owners and persistence

The additive migrations retain one writer per concern:

- `api_idempotency_records` is the neutral HTTP mutation replay owner;
- `domain_outbox_events` is the neutral transactional distribution owner;
- `domain_consumer_effects` is the neutral per-consumer effect/checkpoint
  owner;
- `ip_workflow_definitions` and `ip_workflow_versions` are the bounded IP
  legal-policy owners.

Every new table is company-scoped. The migrations use composite company-aware
foreign keys, unique identities, indexes, check constraints, and PostgreSQL
immutability triggers where an envelope or idempotency identity must never be
rewritten. The pre-existing Matter, shared-work, notification, audit, and
docket-history owners remain canonical; this slice adds provenance rather than
copied histories or duplicate workflow/task systems.

## Reliability contract

Idempotency uses canonical JSON and ordered file-evidence hashing. The server
normalizes the actor/method/operation scope, owns operation-specific retention,
returns immutable snapshots, rejects a changed digest for a retained key, and
replays a completed mutation rather than re-executing it. The Python and web
implementations share one golden fixture, including UTF-16 key ordering,
safe-integer handling, and malformed-surrogate rejection.

The outbox accepts only the versioned event types admitted by
`IP_EVENT_CATALOG.yaml`. The catalogue payload is distinct from the immutable
company event envelope: company, timestamps, aggregate, source, producer, and
correlation are persisted envelope columns rather than duplicated payload
requirements. Enqueue is transaction-bound and idempotent by immutable event
identity. Consumers use leases, fences, per-consumer effects, bounded retries,
redacted errors, dead-letter replay/resolution evidence, and completion checks
that require every expected consumer effect to be terminal and successful.

## Workflow and migration safety

`20260812_0001` adds the reliability tables. `20260812_0002` adds unseeded,
company-scoped workflow definition/version tables and nullable provenance on
shared operational children. Existing dockets are not pinned and no legal
workflow is inferred by the expand migration. Downgrade refuses to delete
workflow, lifecycle, outbox, or consumer-effect evidence; it uses bounded
PostgreSQL locking and fails closed if a mixed-revision writer or populated
evidence is present.

The IPLF-027A data-class registry records this as repository-implemented and
runtime-unreleased. Retention, hold, export, purge, restore, and recovery
handlers remain `unimplemented_fail_closed` until IPLF-028 supplies the
required approved policy and behavior.

## Verification boundary

The source-level contract is covered by SQLite serialization, event catalogue,
idempotency, outbox/fence/dead-letter, migration rollback, workflow provenance,
rollout, request-context, audit, authentication, and web canonicalization
tests. Real PostgreSQL, independent CI, exact-head merge, deployment identity,
and any production acceptance remain separate release gates and must not be
inferred from repository tests.
