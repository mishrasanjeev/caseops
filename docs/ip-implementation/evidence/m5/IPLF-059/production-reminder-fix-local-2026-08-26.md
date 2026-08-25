# IPLF-059B production reminder fix: local evidence

**Date:** 2026-08-26

**Failed production candidate:** `398c822c2bc3b4dbc62041e975fcf1d37dcbd9b1`

**Implementation revision:** `91c902fa88bc1c47eccc2db8238c9b2bfd195b95`

**Candidate branch:** `codex/iplf059b-prod-reminder-fix-20260826`

## Production failure

Exact-main CI run `32908466904` passed every job. Production verifier run
`32908466923` confirmed the exact API/web release and passed 84 RAM tests,
IPLF-027B quiescence and the notice module, but it did not pass as a whole.

The dated IPLF-059B journey received HTTP 500 while creating acknowledgement
reminders. Cloud Run revision `caseops-api-00358-m2v` recorded PostgreSQL
`StringDataRightTruncation`: the shared notification owner limited
`event_type` to 40 characters, while the new source-qualified names require
41 and 45 characters. SQLite does not enforce `VARCHAR(n)`, so the original
local API journey had not exposed the production-only failure.

The same RAM batch also found a stale production-test navigation oracle: the
deployed mobile drawer correctly included `Foreign associates`, but the older
expected list did not.

## Correction

- Widened `event_type` from 40 to 80 characters consistently on
  `notification_rules`, `in_app_notifications`,
  `notification_delivery_intents`, and `notification_delivery_events`.
- Added a five-second PostgreSQL lock timeout and a fail-closed downgrade that
  refuses to narrow after a value longer than 40 characters exists.
- Added an upgrade/downgrade schema test and a model-width regression covering
  the longest IPLF-059B event name.
- Regenerated and reviewed the data-governance map; no new data class, owner,
  retention policy, or notification dispatcher was introduced.
- Updated the 360px production navigation oracle with the existing
  capability-gated `Foreign associates` route.

## Local verification

| Gate | Result |
| --- | --- |
| IPLF-059B and IPLF-059A API journeys | 6 passed |
| Notification width migration 40→80→40 | 1 passed |
| UJ-37 fresh-tenant Playwright journey | 1 passed |
| 360px capability-visible grouped navigation | 1 passed; every action remained visible and clickable |
| Ruff for changed API/migration/tests | passed |
| Data-governance registry/map/change and runtime projection | passed |
| Migration preflight and single-head graph | passed at `20260826_0001` |

## Release boundary

IPLF-059B, UJ-37, its five paths, and the IPLF-059 parent remain blocked from
`deployment_verified`. Hosted CI/security/CodeQL, exact-main migration-first
deployment, immutable scheduler reconciliation, and the complete dated
production verifier must pass on the replacement commit. Independent legal,
provider and law-firm UAT remain external acceptance, not repository work.
