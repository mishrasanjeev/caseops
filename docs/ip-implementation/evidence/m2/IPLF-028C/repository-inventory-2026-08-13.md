# IPLF-028C repository data-map inventory - 2026-08-13

## Scope and boundary

This slice adds a repository-only Definition-of-Ready control for the data-map
portion of IPLF-028. It snapshots the current SQLAlchemy schema and known
repository boundaries; it does not activate a retention policy, legal hold,
export, purge, offboarding, restore, provider deletion, object-store action,
or backup recovery.

The canonical owner remains the neutral records-governance foundation from PRD
Section 11.3. This is an `EXTEND` control-plane change: it does not add an
IP-only queue, storage adapter, export engine, provider operation surface, or
runtime data-operation route.

## Repository inventory

`DATA_GOVERNANCE_MAP.yaml` records a deterministic snapshot of:

- 256 SQLAlchemy tables and 3,938 exact columns, including type/nullability
  and a registered semantic column category;
- fingerprints for 1,128 ORM indexes and 487 Alembic/raw index declarations;
- object prefixes/versions, ephemeral cache, relational and vector indexes,
  queue/outbox/dead-letter state, logs/traces/metrics, export artifacts,
  provider-held objects, and backups.

Each class carries an explicit purpose, policy-pending basis, sensitivity,
default and tenant-configurable retention boundary, disposition/hold behavior,
source/licence boundary, region/subprocessor boundary, owner, and the current
`registry_fail_closed` handler. The wording deliberately does not represent a
human-approved policy.

## Definition-of-Ready gate

`scripts/ip_data_governance_map.py` validates the map against live ORM metadata
and Alembic/index inventories. Its `check-change` command requires a map update
for a changed Alembic migration or a detected storage/provider/telemetry
boundary; a changed migration also requires the literal marker
`DATA-GOVERNANCE-MAP: updated`.

The handler performs no I/O. It is only a CI gate that rejects an unregistered
class or drift before release. Any future execution handler still requires the
named records/privacy/legal/security approvals and separately exercised M2/M7
workflows.

## Remaining blockers

- Records/Privacy/Legal/Security has not provided the approved retention,
  hold, residency, subprocessor, export, purge, backup, and provider-deletion
  policy values required for DATA-GOV-02 and operational DATA-GOV-04..18.
- The current repository snapshot cannot prove production backup/PITR/object
  version topology, tombstone application, restore, or tenant-export behavior.
- Production remains globally blocked by the separate OpenAI quota and
  case-tracking-provider health failures recorded for IPLF-028A; this slice
  neither changes nor resolves them.
