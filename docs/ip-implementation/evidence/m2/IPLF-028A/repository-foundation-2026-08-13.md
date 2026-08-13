# IPLF-028A repository foundation — 2026-08-13

## Scope and truthful boundary

This repository checkpoint adds an additive, unseeded records-governance
foundation. It does **not** claim that the M2 data-governance or resilience
requirements are complete. In particular, it does not perform a tenant export,
purge, offboarding, restore, provider cleanup, object-store operation, backup
reconciliation, or production resilience rehearsal.

The foundation has no router, worker, scheduler, feature activation, provider
adapter, storage adapter, or execute mode. A production deploy of this source
must therefore leave it inert until later approved work adds a reviewed user
workflow and release evidence.

## Repository implementation

- `20260813_0001_data_governance_foundation.py` adds six company-scoped,
  unseeded tables: `data_retention_policies`, `data_retention_versions`,
  `legal_holds`, `legal_hold_items`, `tenant_data_operations`, and
  `tenant_data_operation_items`.
- The migration rejects `execution_mode != 'dry_run'`, enforces
  `safe_to_execute = false`, stores only opaque target hashes/redacted details
  in dry-run items, and refuses destructive downgrade after durable governance
  evidence exists.
- Tenant-safe membership, policy-version, and hold references are backed by
  leading relation indexes; the repository's schema FK-index contract validates
  both the physical indexes and the documented composite-key coverage.
- Retention versions and legal holds have monotonic/immutable database guards;
  manifests and operation items cannot be rewritten or deleted.
- `services/data_governance.py` records only a synthetic dry-run manifest. It
  performs no I/O outside the database, conservatively marks all candidate
  items held whenever any tenant legal hold is active, and rejects explicit
  execute attempts with `data_operation_execution_unavailable` (HTTP 503).
- `IPLF_028A_DATA_GOVERNANCE_REGISTRY.yaml` lists all six newly admitted
  classes, their shared owner, explicit retention/preservation dispositions,
  and the required code/migration links. Its validator makes a missing class,
  alias, unregistered writer, execute overclaim, or missing dry-run guard fail.

## Local verification

Run from the isolated API environment on 2026-08-13:

```text
uv --directory apps/api run ruff check \
  src/caseops_api/db/models.py \
  src/caseops_api/schemas/data_governance.py \
  src/caseops_api/services/data_governance.py \
  alembic/versions/20260813_0001_data_governance_foundation.py \
  ../../scripts/ip_data_governance_registry.py \
  tests/test_20260813_data_governance_migration.py \
  tests/test_data_governance_service.py \
  tests/test_ip_data_governance_registry.py

uv --directory apps/api run pytest -q \
  tests/test_20260813_data_governance_migration.py \
  tests/test_data_governance_service.py \
  tests/test_ip_data_governance_registry.py \
  tests/test_schema_fk_indexes.py
```

Result: the focused migration/service/registry suite returned `8 passed`, and
the schema FK-index contract returned `1 passed`, with the repository's known
Starlette TestClient and SQLite datetime-adapter deprecation warnings. The
migration test proves empty expand/downgrade/re-upgrade, populated-schema
downgrade refusal, immutable manifest rejection, no execute mode, and retained
hold/version evidence. The service test proves hold-aware dry-run suppression,
no unregistered data class, no `safe_to_execute=true`, and a typed execute
rejection.

The production-dialect guard was also run from a fresh disposable
`pgvector/pgvector:pg17` PostgreSQL database after `CREATE EXTENSION vector`
and Alembic `upgrade head`:

```text
uv --directory apps/api run pytest -q --tb=short --disable-warnings \
  -m postgres tests/test_postgres_validation.py -k records_governance_guards
```

Result: `1 passed, 23 deselected, 1 warning`. This specifically proves the
new migration's PostgreSQL JSON-safe immutable triggers, prohibited execute
mode, hold activation/reopen guard, retained policy terms, and immutable dry-run
item scope. The disposable database container was stopped and removed after
the test.

The complete local API `pytest -q` was attempted with a ten-minute limit but
did not produce a terminal test result before the limit. It is therefore
inconclusive, not a passing gate; CI remains required before any release claim.

## Remaining gates

1. Inventory all platform data classes (SQL columns, object versions/prefixes,
   indexes, cache, queues/dead letters, telemetry, exports, provider-held
   material, and backups), then enforce the registry update gate for future
   migrations and handlers.
2. Obtain approved jurisdiction/tenant retention rules, policy ownership,
   legal-hold activation/release workflow, step-up and four-eyes controls, and
   user-facing review contracts. The new schema must not be treated as that
   approval.
3. Build the later tenant/client export and hold-aware destructive-operation
   workflow only after those decisions; real execute capability, purge, and
   offboarding require separately reviewed rollout and operator authority.
4. Run and record the required database-plus-object application-cutover
   restore rehearsal and tenant-export dry run against an approved non-live
   environment. A source-tree test is not evidence of RES-13.
5. Pass independent CI, then complete exact deployed revision/image/schema and
   dated production acceptance evidence before changing release or acceptance
   status.
