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

- 256 SQLAlchemy tables and 3,939 exact columns, including type/nullability
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
and Alembic/index inventories. It also embeds a deterministic semantic-map
SHA-256 in the expected Markdown projection and rejects missing, stale,
independently edited, or non-canonical-newline bytes in
`generated/DATA_GOVERNANCE_MAP.md`. The repository pins that projection to LF
through `.gitattributes`. Its `check-change` command requires a map update for
a changed Alembic migration or a detected storage/provider/telemetry boundary;
a changed migration also requires the literal marker
`DATA-GOVERNANCE-MAP: updated`.

The handler performs no I/O. It is only a CI gate that rejects an unregistered
class or drift before release. Any future execution handler still requires the
named records/privacy/legal/security approvals and separately exercised M2/M7
workflows.

## Exact initial verification

The initial inventory/control implementation at exact revision
`a232a2677e965d7a1efebad3ac18e47478478ad6` passed pull-request CI
`31682537182`, Security `31682537325`, and CodeQL `31682537243` before PR #219
merged. Those checks included the focused map tests, the full API shards,
PostgreSQL validation, web tests/build, and the Playwright app suite. This
supports the `implemented` state for the original bounded repository inventory
and Definition-of-Ready control. The later generated-view regression reopens
verification to `not_run` until the repair has immutable exact-head CI;
release and acceptance remain `blocked / pending` on the separately listed
policy and recovery gates.

## Remaining blockers

- Records/Privacy/Legal/Security has not provided the approved retention,
  hold, residency, subprocessor, export, purge, backup, and provider-deletion
  policy values required for DATA-GOV-02 and operational DATA-GOV-04..18.
- The current repository snapshot cannot prove production backup/PITR/object
  version topology, tombstone application, restore, or tenant-export behavior.
- The IPLF-028A dry-run service still uses a six-class
  `FOUNDATION_DATA_CLASS_IDS` allowlist. This repository inventory does not
  expand that runtime allowlist or authorize a data-operation surface.
- Global production verification remains a separate release gate; this slice
  neither changes nor resolves provider or acceptance blockers.

## 2026-08-14 generated-view repair

At canonical base revision
`52cb925d3dacd74890b607208588d95fb6000473`, the machine-readable map already
contained `matter_bulk_import_jobs.duplicate_rows` and correctly described 256
tables and 3,939 columns. The generated Markdown still described 3,938 columns
and 21 columns for `matter_bulk_import_jobs`; the old validator returned
`data-governance map valid` because it did not compare the projection.

The bounded repair makes that exact drift fail closed, embeds the semantic map
fingerprint, and adds negative regressions for a semantic change outside the
human-readable fields, a missing projection, CRLF bytes, and the non-recursive
repair path. It regenerates the view to 3,939 total columns and 22 columns for
`matter_bulk_import_jobs`. Focused local verification from the isolated repair
worktree passed ten map tests and the canonical `validate`, `generate`, and
`render` commands. Exact-head CI and main publication remain required before
verification can return to `passed`; the release gate remains separately
blocked. This closes only the repository inventory/Definition-of-Ready
implementation facets of `DATA-GOV-01` and `DATA-GOV-03`; it does not claim
approved `DATA-GOV-02` policy values, expand the six-class runtime registry, or
satisfy a release or acceptance gate.
