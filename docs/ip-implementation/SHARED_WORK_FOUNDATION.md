# Shared work foundation (IPLF-025A)

IPLF-025A extends the existing CaseOps task, hearing, next-hearing,
operational-deadline, calendar, reminder, and durable-notification owners to an
IP docket target. It does not introduce a parallel IP work system. The contract
version published by the API is `IPLF-025A/2026-08-10`.

## Canonical owners

| Work concept | Canonical persistence | Classification | IP adapter/writer |
| --- | --- | --- | --- |
| Tasks | `matter_tasks` | EXTEND | `services/shared_work.py` and `/api/ip/tasks` |
| Hearings | `matter_hearings` | EXTEND | `services/shared_work.py` and `/api/ip/hearings` |
| Next-hearing provenance | `matter_next_hearing_history` and `matter_next_hearing_suggestions` | EXTEND | shared hearing service appends the same provenance rows |
| Operational deadlines | `matter_deadlines` | LINK | `/api/ip/operational-deadlines`; rows linked from `ip_deadlines` reject independent mutation |
| Calendar synchronization | `calendar_event_syncs` source keys | EXTEND | existing dispatcher continues to address the canonical task/hearing/deadline row |
| Reminders and delivery | `hearing_reminders` and `notification_delivery_intents` | EXTEND | existing durable delivery path accepts an `ip_docket_id` target |

The forbidden duplicate set is `ip_tasks`, `ip_hearings`,
`ip_operational_deadlines`, `ip_calendar_events`, and
`ip_notification_intents`. Metadata and migration tests fail if any of these
tables appear.

## Target and tenant contract

Target-owned rows contain exactly one of `matter_id` or `ip_docket_id`.
Composite foreign keys correlate that target to `company_id`, preventing a
tenant key from being paired with another tenant's Matter or IP docket. New
writers always persist `company_id`. Matter routes retain their existing
contracts and write the same tables; IP routes are typed adapters over those
owners.

IP docket resolution uses the existing IP capability and docket-access path.
Linked Matter access remains fail-closed. An unlinked restricted IP docket
cannot create a delivery intent until IPLF-026 supplies the generalized
restricted-record policy.

## Migration and mixed revisions

The rollout is intentionally ordered:

1. `20260810_0001` expands the owners with nullable IP target/tenant columns,
   hearing precision/provenance/responsibility fields, and notification target.
   The previous application revision can continue writing Matter rows.
2. `20260810_0002` backfills tenant correlation from the canonical Matter.
3. `20260810_0003` switches on exactly-one-target checks, composite tenant
   foreign keys, source uniqueness, and notification target constraints.

Tenant correlation remains nullable only for a drained legacy-revision tail.
`GET /api/ip/shared-work/reconciliation` reports those tails, invalid targets,
tenant mismatches, and per-owner readiness. `ready=false` is release-blocking;
it is not a warning that may be waived by the deployment script.

## One-writer boundary

`ip_deadlines` alone owns legal calculation, rule version, confirmation,
override, and responsibility state. `matter_deadlines` owns the operational
projection consumed by Today/calendar/task surfaces. The shared IP adapter
returns HTTP 409 when a caller attempts to mutate an operational row linked to
an authoritative legal deadline; that change must use the IP legal-deadline
workflow.

Hearing creation and date changes append to the existing next-hearing history
owner with source identity. Delivery uses the existing durable notification
intent and recipient snapshot contract. No calendar feed, reminder queue, or
notification dispatcher is forked by this slice.

## Verification and rollback

The foundation tests prove the owner metadata, absence of duplicate tables,
target ambiguity rejection, hearing precision/provenance fields, IP delivery
target, tenant isolation, task/hearing/deadline adapter writes, next-hearing
history, and release-blocking reconciliation. The migration test upgrades from
the prior head through expand/backfill/switch, downgrades to the prior head,
and re-upgrades.

Rollback first drains the new application revision and verifies that no IP
target rows would be discarded. The schema may then downgrade in reverse
order. The backfilled `company_id` facts are deliberately retained while the
additive revisions exist; the final expand downgrade removes them only after
the IP-target rows have been drained or otherwise preserved.
