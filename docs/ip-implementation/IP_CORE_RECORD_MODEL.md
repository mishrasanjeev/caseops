# Core IP records and workspace configuration

Last updated: 7 August 2026

Implementation slices: `IPLF-021A`, `IPLF-021B`

Status: repository implementation and local verification complete; serial CI,
production deployment, and named human acceptance remain pending.

## Purpose and boundary

This contract adds the canonical, tenant-scoped records required to identify an
IP asset, its trademark application, a proceeding, and every legal identifier
without overloading a Matter or storing one identifier in another identifier's
field. `ip_docket_records` remains the access and lifecycle anchor. Matter,
Client, document, audit, deadline, notification, and billing services retain
their existing owners.

The workspace configuration contract records what a tenant administrator has
selected and which safe readiness probes passed for that exact configuration
version. It stores provider keys/references, but never provider credentials.
Secrets continue to belong to the integration/secret owner. Saving this
configuration does not itself enable a feature.

## Canonical record graph

```text
ip_docket_records (access and lifecycle anchor)
  +-- ip_assets
      +-- trademark_applications
          +-- trademark_application_scopes
          +-- trademark_representations
          +-- ip_proceedings
          +-- ip_identifiers (application/registration identifiers)
      +-- ip_proceedings
          +-- ip_identifiers (opposition/rectification/appeal/court identifiers)
      +-- ip_parties_and_roles ----> clients (optional canonical party link)
      +-- ip_relationships --------> another tenant IP asset

companies
  +-- ip_workspace_configurations (one current row per tenant)
      +-- ip_workspace_test_results (append-only results by configuration version)
```

Every legal-state row carries `company_id`. Composite foreign keys ensure a
child cannot refer to a parent owned by another tenant. The API additionally
reuses the docket's authoritative restricted-record and terminal-lifecycle
guard for reads and writes.

## Identifier requirements

The command service implements the IPLF-021 contribution to `IP-ID-01` through
`IP-ID-08`:

| Requirement | Enforced behavior |
| --- | --- |
| `IP-ID-01` | Application, registration, opposition, rectification, appeal, and court identifiers are typed facts. Application/registration identifiers belong to an application; proceeding identifiers belong to a proceeding. |
| `IP-ID-02` | `raw_value` is immutable source display data. `normalized_value` is a separate Unicode-normalized, case-folded, alphanumeric search value. |
| `IP-ID-03` | Kind, office, jurisdiction, source, effective-from date, and primary designation are required; effective-until is validated when present. |
| `IP-ID-04` | A trademark application cannot enter `filed` without a current confirmed application identifier unless `source_pending_identifier_allocation` is explicit. |
| `IP-ID-05` | An opposition number can only belong to an `ip_proceeding`; the application owner shape is rejected. |
| `IP-ID-06` | Exact normalized search accepts common punctuation/case/spacing variants and returns the original source form. |
| `IP-ID-07` | A current normalized collision returns duplicate candidates and marks the new fact `needs_review`; it never merges assets or applications. |
| `IP-ID-08` | A correction creates a successor identifier, closes the old effective range, and requires `supersedes_identifier_id` plus a correction reason. |

These requirements remain program-level `in_progress` until the reciprocal
manual create/reconciliation paths assigned to `IPLF-031B` are implemented and
released. IPLF-021B must not be represented as completing that later slice.

## Command and query API

All routes are under `/api/ip`. Read operations require `ip:read`; core record
mutations require `ip:write`; workspace configuration/test/enable operations
require `ip:taxonomy_admin`. Capability authorization, subscription
entitlement, deployment rollout flags, and tenant configuration are separate,
fail-closed gates.

| Method and path | Contract |
| --- | --- |
| `GET /identifiers/search?q=` | Tenant-scoped normalized exact search; inaccessible, restricted, missing, or terminal docket rows are omitted. |
| `GET /dockets/{id}/core-records` | Returns assets, applications, proceedings, and identifier history after the docket access/lifecycle guard. |
| `POST /dockets/{id}/assets` | Creates the docket's canonical IP asset. |
| `POST /dockets/{id}/applications` | Creates a typed trademark application and can atomically create its first identifier. |
| `PATCH /applications/{id}/filing-phase` | Uses an optimistic `expected_version`, parent-before-child locks, and the filed-phase invariant. |
| `POST /dockets/{id}/proceedings` | Creates a proceeding owned by the same docket/asset/application graph. |
| `POST /dockets/{id}/identifiers` | Creates a typed identifier and returns any reconciliation candidates. |
| `POST /dockets/{id}/identifiers/{identifier_id}/corrections` | Creates immutable correction history and returns duplicate candidates. |
| `GET /workspace/configuration` | Returns current tenant configuration, tests, manual readiness, and blockers. |
| `PUT /workspace/configuration` | Creates or version-updates configuration with optimistic concurrency; an update disables the workspace and invalidates old-version test evidence. |
| `POST /workspace/tests` | Persists one safe dry-run result for the exact configuration version and actor. |
| `POST /workspace/enable` | Enables manual workspace use or selected automations only when their current-version prerequisites pass. |
| `GET /readiness` | Overlays tenant configuration and test state on capability, entitlement, and deployment rollout decisions. |

## UJ-01 workspace setup

The responsive `/app/ip` setup surface records enabled asset types,
jurisdictions, offices, timezone, holiday calendar, working weekdays, document
taxonomy, event catalog, deadline-rule versions, notification channels,
critical-event policy, escalation owner, provider references, and provider
terms acceptance. It links administrators to the existing role, team, and
integration owners instead of creating duplicate administration stores.

Four tests are deliberately side-effect free:

- Connection and source-open tests validate configured provider references and
  accepted terms with `external_call=false`.
- Notification validation records `sent=false`; it never sends a message.
- Deadline calculation uses a deterministic sample and records
  `legal_deadline=false`; it never creates an operational deadline.

Missing or failed provider tests do not block manual docketing. They block only
the affected automation. A configuration version change disables the tenant
workspace and makes older test results ineligible. The environment and
entitlement gates still win even after tenant enablement.

No seven-day or other arbitrary elapsed-time requirement is part of this
contract. Readiness is established by deterministic current-version evidence,
exact-revision release checks, and required human/provider approvals.

## Transactions, concurrency, and audit

Core mutations lock the docket parent before child rows, validate tenant
ownership and lifecycle state, write the legal record and audit event in one
transaction, and commit only after all invariants pass. Filing-phase and
workspace changes use client-supplied optimistic versions so stale writes fail
with `409` and require reload.

Workspace saves, readiness tests, enablement, assets, applications,
proceedings, identifiers, corrections, and phase changes emit tenant audit
events. Identifier raw values are not copied into audit metadata. Test evidence
records the actor, configuration version, result, failure code, and safe-result
details.

## Migration, rollout, and rollback

`20260807_0001` creates the eight core legal-record tables. `20260807_0002`
adds `ip_workspace_configurations` and `ip_workspace_test_results`. Both are
additive, tenant-scoped migrations. They neither infer existing legal records
nor activate rollout flags.

Before rollout, CI must prove PostgreSQL migration order and the exact candidate
must pass Security, CodeQL, API, web, and OpenAPI generated-client gates. The
serial release must then migrate production, deploy the exact API/web image
digests, verify the serving Cloud Run revisions, and rerun the dated production
acceptance journey against that revision.

Before writes, the tested downgrade removes the new tables. After writes,
rollback is flag-off plus forward-fix/export preservation; destructive
downgrade is not an acceptable way to discard legal history. No production
automation flag is enabled by merging this slice.

## Verification map

- `test_ip_record_workflow.py`: filed invariant, typed ownership, raw/normalized
  search, duplicate reconciliation, correction history, tenant and restricted
  access, audit events.
- `test_ip_workspace_configuration.py`: UJ-01 normal and three exception paths,
  tenant/admin scope, terms, actor/version evidence, manual fallback, and
  fail-closed readiness overlay.
- `test_20260807_ip_core_migration.py` and
  `test_20260807_ip_workspace_migration.py`: upgrade, downgrade, removal, and
  re-upgrade.
- `page.test.tsx`: visible narrow-viewport setup controls and every grouped
  action/link, plus manual and automation states.
- `openapi-types.ts`: generated from the API schema; CI rejects drift.

Local evidence is recorded in
`docs/ip-implementation/evidence/m2/IPLF-021B/release-2026-08-07.md`.
