# IP docket event and lifecycle contract

Last updated: 7 August 2026

Implementation slices: `IPLF-022A` foundation and `IPLF-022B` user workflow

Status: repository implementation and local verification complete through
IPLF-022B at `08ae3ecd0a8eedd3d5f2bc2e994b48732fddfaf1`; independent CI,
canonical-main release, and exact production verification remain pending.

## Ownership boundary

`ip_docket_records` is the authoritative access and lifecycle parent.
`ip_docket_events` contains append-only IP legal facts. It does not replace
`MatterActivity`, `AuditEvent`, shared operational deadlines, notifications, or
the later shared transactional outbox owned by IPLF-027.

The only lifecycle writer is `services/ip_lifecycle.py`. Ordinary docket,
metadata, core-record, import, and child commands use the existing fail-closed
docket guard and cannot modify a terminal record. Matter disposal remains the
parent lifecycle authority for a Matter-linked docket and uses the same legal
event/lifecycle fields in its atomic transaction.

## Event contract

Every event is tenant- and docket-scoped and receives a monotonically
increasing per-docket sequence while the parent is locked. It records:

- typed event kind, source, source reference, effective time, entry time, and
  responsible/entering memberships;
- optional application or proceeding ownership, never both;
- reason, evidence/document references, resulting stage/deadline references,
  and before/after phase;
- registry candidate status and explicit reconciliation decision; and
- correction/reconciliation links to prior events in the same tenant/docket.

Manual events require a reason. A correction requires an immutable predecessor
and correction reason. A registry-derived fact remains `candidate` until an
explicit reconciliation command confirms, separates, or rejects it. Existing
rows are never overwritten by correction.

## Lifecycle invariants

The parent stores `status`, `is_active`, `lifecycle_version`, effective time,
reason, outcome, source, evidence reference, and an optional same-tenant active
successor. A database check requires active statuses to have `is_active=true`
and terminal statuses (`archived`, `abandoned`, `transferred`, `retired`, or
`closed`) to have `is_active=false`.

Transitions must cross the active/terminal boundary and provide the expected
lifecycle version. Parent Matter and docket locks are acquired in that order.
The lifecycle event, parent state, audit event, and current operational-child
neutralization commit atomically. A transfer requires another active
same-tenant docket and self/cross-tenant successors are rejected.

On a terminal transition, active coverage is made `inactive_lifecycle`, open
related-right obligations become `cancelled_lifecycle`, and their shared open
deadlines are cancelled. A controlled reopen increments the lifecycle version
and appends a new event but never changes those neutralized child states. This
prevents child resurrection after reload.

Matter disposal archives linked dockets, increments their lifecycle versions,
appends a system lifecycle event, and neutralizes their IP operational children
under the already locked Matter. Reopening the Matter does not reopen those IP
dockets.

## Migration and rollback

Alembic revision `20260807_0003` adds the lifecycle fields and consistency
constraints to `ip_docket_records`, normalizes pre-existing `archived` rows to
inactive, and creates the event table with composite tenant foreign keys,
sequence uniqueness, correction/reconciliation constraints, and leading
indexes for every foreign key.

Before legal writes, downgrade to `20260807_0002` and re-upgrade are tested. As
soon as append-only legal events exist, destructive downgrade is not an
acceptable production rollback. Rollback is rollout-off plus forward fix and
history-preserving recovery/export.

No feature flag, provider integration, notification, filing, fee, external
message, or production legal automation is enabled by this foundation slice.

IPLF-022B exposes separate impact-preview and transition endpoints plus the
capability-gated web workflow. Preview enumerates downstream impacts and
unresolved exception codes without mutation. Commit repeats the calculation
under the parent locks, requires exact exception acknowledgements, preserves
client-report and linked-Matter handling, and records final disposition as a
separate report dimension. See `IP_PROSECUTION_WORKFLOW.md` for the complete
event, application-phase, checklist, reporting, and UI contract.

## Verification map

- `test_ip_lifecycle_service.py`: append sequence/history, correction,
  registry candidates, stale versions, tenant/target guards, terminal
  suppression, controlled reopen, audit, persistence, and no child
  resurrection.
- `test_20260807_ip_lifecycle_migration.py`: exact upgrade, schema/index
  inspection, downgrade, and re-upgrade.
- `test_ip_prd_slices.py` and `test_matter_lifecycle.py`: Matter disposal
  compatibility and existing IP operational workflows.
- `test_schema_fk_indexes.py` and `test_migration_order.py`: leading-index and
  single-head migration controls.

Detailed dated evidence is recorded in
`docs/ip-implementation/evidence/m2/IPLF-022A/release-2026-08-07.md` and
`docs/ip-implementation/evidence/m2/IPLF-022B/release-2026-08-07.md`.
