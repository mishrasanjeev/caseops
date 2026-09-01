# Production stability: platform-admin lock isolation

**Evidence date:** 1 September 2026  
**Incident release:** `a58eb2a3158c7525e875e361e816f14fd25aa945`  
**Incident API revision:** `caseops-api-00403-zsv`  
**Hosted verification run:** GitHub Actions `33488275197`  
**Status in this record:** correction validated locally; production release evidence is not claimed here

## Incident

The hosted production verifier completed 96 tests, skipped five documented
provider/deployed-only cases, and failed one recommendations-grounding setup.
The failure was `POST /api/matters/` returning 500 with request ID
`01c3e78b5340478498493bb45800d0d8`.

Cloud Run request trace
`projects/perfect-period-305406/traces/c76ea1d937cb9f458deaa09861b842c3`
showed a 5.095-second request ending at 09:04:06 UTC. PostgreSQL had cancelled:

```text
UPDATE platform_admin_memberships SET updated_at = ...
WHERE platform_admin_memberships.id = ...

psycopg.errors.LockNotAvailable: canceling statement due to lock timeout
```

Capability resolution caught that database exception and continued with the
same SQLAlchemy session. The next Matter service access then raised
`PendingRollbackError`, masking the original lock timeout and producing the
generic 500. The failure was unrelated to recommendation grounding, Matter
fixture uniqueness, or missing indexes.

## Root cause

Ordinary tenant capability resolution called
`platform_capabilities_for_user()`. That function called founder seeding, which
unconditionally changed the one active `platform_admin_memberships.updated_at`
value and flushed it. Parallel authenticated requests from the configured
founder therefore contended on one global row. The broad exception handler in
capability resolution hid a failed flush without rolling back the transaction.

No timeout increase or mutation retry is an acceptable correction. The shared
write did not belong on a tenant authorization read path.

## Correction

- Platform capability lookup now selects the configured founder ID and active
  capability JSON as scalar data. It does not attach or mutate a
  `PlatformAdminMembership` entity.
- Login MFA preflight selects only the platform MFA-required flag and enforcement
  timestamp, so the ordinary authenticated request path also does not attach the
  shared mutable entity.
- Configured-founder seeding updates role, capabilities, status, MFA policy, or
  `updated_at` only when the desired persisted configuration differs.
- A prior founder is revoked and flushed before a replacement is activated, so
  the one-active-platform-admin constraint remains valid during rotation.
- Capability resolution no longer swallows database failures. The existing
  operational-error boundary can return the original typed 503/504 response,
  and request-session teardown rolls the transaction back.
- There is no retry around Matter creation and no database timeout was raised.

## Local acceptance

The repository's clean pre-commit Docker gate rebuilt production API and web
images from the complete working-tree candidate. It created fresh PostgreSQL and
Valkey volumes, migrated to `20260901_0001`, and removed the isolated containers
and volumes after success. The exact self-referential candidate fingerprint is
retained in the gate log rather than embedded inside the file it hashes.

| Gate | Result |
| --- | --- |
| Ruff on changed backend and tests | Passed |
| Idempotent/read-only platform-admin focused test | 1 passed |
| PostgreSQL plus pgvector validation | 114 passed, 1 dependency warning |
| Desktop Playwright shard 1 | 84 passed, 1 intentional provider-gated skip |
| Desktop Playwright shard 2 | 84 passed, 1 intentional deployed-only skip |
| Mobile responsive Playwright | 4 passed |
| Normal-memory database index audit | No missing, invalid, mismatched, FK-gap, or sequential-scan findings |
| 512 MiB database index audit | No missing, invalid, mismatched, FK-gap, or sequential-scan findings |

The new PostgreSQL regression locks the active global platform-admin row in one
transaction. In a second transaction, the configured founder completes MFA
preflight, resolves the tenant `matters:create` capability, and creates a real
Matter under a 250 ms lock timeout. The test asserts that no
`PlatformAdminMembership` object is attached or dirty, Matter creation succeeds,
and the session remains usable.

## Release boundary

This record does not mark the correction deployed. Production completion
requires the validated commit on canonical `main`, all required GitHub checks,
the exact committed Docker gate, canonical deployment, latest-only API/web
traffic, healthy migration/index/QA gates, a green hosted production verifier,
and restored scheduler cadence with clean consecutive maintenance executions.
The private-projection scheduler remains paused until those gates complete.
