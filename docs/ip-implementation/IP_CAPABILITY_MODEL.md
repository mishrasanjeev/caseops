# IP capability, entitlement, and rollout contract

Status: IPLF-020A implementation contract, 6 August 2026

## Purpose and security boundary

An IP operation is available only when three independently observable gates
pass:

1. the authenticated membership has every required server-side capability;
2. the tenant's effective billing subscription contains an enabled entitlement;
3. the environment rollout flag is enabled and its optional pilot expiry has
   not elapsed.

Frontend visibility is never authorization. Every mutation route must resolve
the membership capability again on the API. Provider readiness, tenant policy,
record access, ethical walls, and lifecycle state remain additional fail-closed
checks in the behavior slice that owns the operation.

`evaluate_ip_feature` returns a stable reason (`missing_capability`,
`missing_entitlement`, `rollout_disabled`, `rollout_expired`, or `available`),
the responsible owner, the flag name, and its expiry. Unknown feature IDs fail
closed. Billing values are deliberately explicit: accepted enabled values are
boolean `true`, the strings `enabled`, `included`, `ready`, or `true`, and a
JSON object whose `enabled` member is boolean `true`. Numeric and generically
truthy values do not activate a feature.

## Canonical capabilities and default roles

| Capability | Owner/admin | Partner | Member/paralegal | Viewer |
|---|---:|---:|---:|---:|
| `ip:read` | Yes | Yes | Yes | Yes |
| `ip:write` | Yes | Yes | Yes | No |
| `ip:import` | Yes | No | No | No |
| `ip:approve` | Yes | Yes | No | No |
| `ip:filing_prepare` | Yes | Yes | Yes | No |
| `ip:filing_confirm` | Yes | Yes | No | No |
| `ip:fees_view` | Yes | Yes | No | No |
| `ip:fees_manage` | Yes | No | No | No |
| `ip:rules_propose` | Yes | No | No | No |
| `ip:rules_activate` | Yes | Yes | No | No |
| `ip:taxonomy_admin` | Yes | No | No | No |
| `ip:registry_sync` | Yes | No | No | No |
| `ip:watch_manage` | Yes | No | No | No |

The bounded pre-PRD names `ip:view`, `ip:review`, and `ip:finance` remain
compatibility aliases for `ip:read`, `ip:approve`, and `ip:fees_view`. They may
be retired only after custom-role backfill, mixed-revision proof, and explicit
usage evidence show the old names are absent.

## Feature catalogue

| Feature | Capability | Entitlement | Rollout flag | Owner | Manual fallback |
|---|---|---|---|---|---|
| Workspace core | `ip:read` | `ip_workspace` | `ip_workspace_enabled` | product-ip | n/a |
| Manual docketing | `ip:write` | `ip_workspace` | `ip_workspace_enabled` | product-ip | n/a |
| Registry sync | `ip:registry_sync` | `ip_registry_sync` | `ip_registry_sync_enabled` | integrations | manual docketing |
| Deadline automation | `ip:approve` | `ip_deadline_automation` | `ip_deadline_automation_enabled` | legal-rules | manual docketing |
| Notification automation | `ip:approve` | `ip_notification_automation` | `ip_notification_automation_enabled` | notifications | manual docketing |
| Filing preparation | `ip:filing_prepare` | `ip_filing_operations` | `ip_filing_operations_enabled` | product-ip | n/a |
| Filing confirmation | `ip:filing_confirm` | `ip_filing_operations` | `ip_filing_operations_enabled` | product-ip | n/a |
| Watch operations | `ip:watch_manage` | `ip_watch` | `ip_watch_enabled` | product-ip | manual docketing |
| Cost operations | `ip:fees_view` | `ip_costs` | `ip_costs_enabled` | billing | n/a |
| Rule governance | `ip:rules_propose` | `ip_rule_governance` | `ip_rule_governance_enabled` | legal-rules | n/a |
| Taxonomy administration | `ip:taxonomy_admin` | `ip_workspace` | `ip_workspace_enabled` | product-ip | n/a |

Every flag defaults to false. Every flag has a companion optional ISO-8601
expiry setting. Missing providers never block manual docketing: provider-backed
automation is separately disabled with its reason and manual fallback.

## Rollout and rollback

IPLF-020A makes no schema or tenant-data change and seeds no production
entitlement. Deployment is therefore dark by default. A later release may
enable a feature only after its behavior, provider/policy readiness, tenant
allowlist, and dated acceptance evidence pass. Immediate rollback is the
feature's flag; code rollback is safe because existing aliases remain and no
persisted representation changed.

## Source of truth

- Backend role catalogue: `apps/api/src/caseops_api/services/capability_catalog.py`
- Independent gate evaluation: `apps/api/src/caseops_api/services/ip_capability_catalog.py`
- Rollout settings: `apps/api/src/caseops_api/core/settings.py`
- Frontend display catalogue: `apps/web/lib/capabilities.ts`
- Environment reference: `apps/api/.env.example`
