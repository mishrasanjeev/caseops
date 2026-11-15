# Native V1 fixture foundations — 2026-11-13

Journey J20 / module M22, US-MOB-01..08; remaining V1-17 and CX-24 native acceptance.

Status: Partially implemented. Release verdict: NO-GO.

The explicit fresh local bootstrap profile binds one synthetic V1 epoch, exact
source SHA, four-hour maximum rollout expiry and one blocked-provider tenant.
Only the API receives the five reviewed rollout/provider environment settings;
the resulting Docker receipt independently observes them from its actual container.
No default profile is enabled and expired profiles cannot be resumed or rearmed.

The separate disabled-default entitlement worker admits a fresh empty synthetic
company and its normal bootstrap, current owner identity and MFA acknowledgements.
It checks the exact PostgreSQL server/database, locks company then membership/user,
inserts exactly one nonbillable subscription with two entitlements, retains the
spent company claim before database work and verifies postcommit data and unchanged
outbox bytes. Unknown commits are incomplete and never retried or compensated.
Credentials and database URLs are not public evidence.

Evidence so far: complete local-fixture Python module 114 cases passed on the
candidate before integration; local-v1-entitlements.test.py 15 contract cases
passed with pinned CPython 3.13.17, repeated after import cleanup on November 13.
These are offline contracts, not an actual PostgreSQL grant or native acceptance.
The worker test is included unconditionally in the source CI inventory.

Still required: actual fresh governed Docker profile, positive and negative
PostgreSQL grant/CLI journeys, normal billing/readiness readback, complete fixture
producer integration, full platform-specific native inventory and signed store
artifacts. This foundation supplies no Android/iOS case credit or store approval.
