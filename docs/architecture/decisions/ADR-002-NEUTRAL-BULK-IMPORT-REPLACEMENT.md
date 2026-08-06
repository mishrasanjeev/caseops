# ADR-002: Neutral bulk-import orchestration replaces new domain-specific job owners

- Status: Accepted as the M3 implementation boundary; convergence of legacy writers requires its own reviewed release
- Date: 2026-08-06
- Scope: IPLF-032 / ARCH-OPS-23

## Context

CaseOps currently has separate `MatterBulkImportJob` and
`EmployeeBulkImportJob` aggregates, services, row models, and UI paths. Neither
is a generic persisted import owner. Reusing the Matter class through an alias
would not change that ownership, while adding `ip_import_jobs` would create a
third job lifecycle and duplicate uploader/history/error-report controls.

## Decision

New IP import work uses a neutral `bulk_import_jobs` orchestration contract and
typed `ip_import_rows` staging/validation/commit outcomes.

The neutral job owns only the immutable input/selection manifest, lifecycle,
safe progress/counts, checkpoints, result/error artifacts, idempotency,
retry/cancel eligibility, and correlation. Domain adapters own row parsing,
validation, preview diffs, expected versions, and commits.

Legacy Matter and Employee histories remain unchanged and are surfaced through
read-only adapters. There is no dual write. Migrating legacy job creation to the
neutral writer requires a separate convergence slice with production-shaped
backfill, row/count/hash reconciliation, mixed-revision support, and rollback.

## Field-by-field gap analysis

| Concern | Current Matter/Employee jobs | Neutral owner | Typed IP rows |
|---|---|---|---|
| Upload identity and checksum | Domain-specific | Canonical for new imports | Reference only |
| Job lifecycle/progress | Domain-specific | Canonical for new imports | No duplicate lifecycle |
| Preview manifest and expiry | Inconsistent by domain | Canonical immutable manifest | Typed row preview result |
| Row validation/commit | Domain service | Delegates | Canonical IP row outcome |
| Error/download artifact | Domain-specific | Canonical contract | Contributes row errors |
| Retry/cancel | Domain-specific | Canonical eligibility/checkpoint | Never erases committed effects |
| Legacy history | Canonical existing rows | Read-only adapter | No copy |

## Rejected alternatives

- Alias `MatterBulkImportJob` as generic: rejected because its schema and commit
  service remain Matter-specific.
- Add `ip_import_jobs`: rejected as a forbidden third lifecycle owner.
- Rewrite legacy history in the first IP release: rejected because it expands
  migration risk without an IP consumer requirement.

## Rollout and rollback

The implementation sequence is expand neutral job/row tables, ship legacy read
adapters, verify preview/commit/idempotency and formula-injection protection,
switch only new IP imports, then run deployed E2E. Rollback disables new IP
import creation and preserves neutral rows/artifacts for diagnosis; it never
rewrites legacy history or replays successful row commits.
