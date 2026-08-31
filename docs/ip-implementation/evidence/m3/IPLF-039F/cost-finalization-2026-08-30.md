# IPLF-039F — matterless nonbillable cost finalization

**Date:** 2026-08-30

**Scope:** the remaining repository gap recorded in `PROGRAM_MANIFEST.yaml`

**Release claim:** repository implementation only; exact deployed acceptance is not claimed

## Brutal gap analysis

The earlier UJ-52 implementation correctly accepted a cost on an IP docket
with no Matter only when `billable=false`, rejected billing links, and returned
the terminal reconciliation status `nonbillable`. That was necessary, but it
was not enough to support the stronger closure statement in the manifest.

The first finalization pass was still too shallow. Independent review found
five release-blocking gaps:

1. The initial unconditional `BEFORE DELETE` guard also fired during the
   declared parent-docket `ON DELETE CASCADE`. It protected direct writes by
   breaking a lawful future parent disposition path.
2. “Record a correction” was only prose. There was no append-only void or
   supersession object, no replacement lineage, and no rule excluding an
   erroneous source from reconciliation and totals without destroying history.
3. The request/service enforced matterless nonbilling state, but a hostile SQL
   writer could still store `unlinked`/`matched`, canonical amounts or a
   cross-tenant creator/reconciler. Those are database invariants, not caller
   conventions.
4. Renewal, foreign-associate, Madrid and recordal consumers resolved a cost
   only by ID/tenant/docket, so they could re-use a now-inactive historical
   source after correction.
5. The dated browser proof mixed local-only Python/database shell helpers with
   assertions that might later be mistaken for production acceptance. A
   deployed path must observe billing only through authenticated public APIs,
   mutate only a declared test tenant and fail closed without exact fixtures.

A second independent review then found that the correction model was not yet
release-safe at its integration edges:

1. The generic RAM/release configurations still discovered the mutation-capable
   production spec without its six dedicated fixture values.
2. Downgrade deleted the correction table even after governed rows existed, and
   the new-table index strategy was not explicitly acknowledged by the migration
   preflight contract.
3. Renewal portfolio reads could render a retired fee and transitions that
   omitted the optional fee field did not revalidate its lineage.
4. Actor evidence said only tenant-correlated even though closure requires an
   active same-tenant actor at the instant of creation/reconciliation/correction.
5. The UI submitted a full replacement payload but silently carried several
   hidden source values, and the production spec exercised only void rather than
   supersession, replacement, and double-count prevention.

A final cross-workflow review found one additional real defect: a foreign-
associate estimate was validated when approved but not revalidated at dispatch.
Superseding the approved estimate therefore left a stale reference able to
advance the instruction. Madrid and recordal already failed closed, but lacked
regressions proving active replacement acceptance and immutable historical
evidence across their create and transition boundaries.

## Durable fix

- Unreleased Alembic revision `20260831_0002` normalizes existing projections,
  adds `ip_cost_item_corrections`, strengthens CHECK constraints, and installs
  SQLite/PostgreSQL guards. Direct row deletion fails while the parent exists;
  parent deletion remains cascade-safe because the trigger observes that the
  docket is already absent from the deleting statement's visibility.
- A source can have exactly one outgoing `void` or `supersede`. Supersession
  appends a complete independently validated replacement; neither source nor
  correction can be edited. Both histories remain readable, while only active
  rows participate in reconciliation, control totals or adjacent cost-link
  consumers.
- Downgrade is restore-forward once any governed correction exists: it refuses
  before dropping triggers, tables, parent rows, or immutable evidence. Indexes
  are created only on the new empty correction table before application writers
  can insert, and both decisions are explicit migration-preflight contracts.
- Matterless and every nonbillable cost are database-enforced as terminal
  `nonbillable` with no billing link and null canonical/difference amounts on
  both INSERT and UPDATE. Creator, reconciler and correction actor must be an
  active membership of the same tenant.
- Service, API and operator UI expose real correction/void actions and retain
  source evidence after disposition. The replacement editor exposes every
  material replacement field; prefilled values remain editable and are never
  carried silently. The shared active-cost SQL predicate keeps renewals,
  foreign-associate spend, Madrid and recordal flows aligned. Renewal portfolio
  rendering excludes retired fees, while every transition resolves a valid
  supersession to its active successor or requires an explicit new active fee
  after a void; that reference change is renewal-versioned and audited.
- Foreign-associate dispatch now re-resolves the stored approved estimate with
  the shared active-cost predicate. A superseded estimate blocks dispatch until
  `approve_fee_change` selects its active replacement; completion likewise
  rejects a retired linked actual until the current actual is explicitly
  relinked and reconciled. Madrid and recordal regressions prove the same
  fail-closed rule while preserving every historical reference and evidence
  string.
- PostgreSQL and SQLite require creator, reconciler, and correction actors to be
  active members of the same tenant when the write occurs. Later deactivation
  does not erase or invalidate the retained historical provenance.
- The local Docker Playwright remains explicitly loopback-only and may create
  fixtures/use a local database shell. The separate `2026-08-30-prod` spec has
  no shell imports; it requires exact API/web release identity, an explicit
  dedicated-tenant acknowledgement, a matterless docket and the complete
  declared Matter set, then compares public Matter workspace billing state
  before capture/reconciliation and after UI supersession and cleanup void. It
  proves exactly one active replacement is counted, the source is excluded, and
  the complete Matter enumeration is unchanged after mutation. The spec is
  isolated from generic RAM/release discovery and runs only behind an all-or-none
  six-value production workflow preflight.

## Current candidate verification

| Surface | Command | Result |
|---|---|---|
| API + SQLite focused | migration, active-lineage, renewal, workflow, deployment and preflight contracts | **118 passed after final integration review** |
| API lint/compile | targeted Ruff and Python compileall over the correction slice | **passed** |
| IP UI | `npm run test --workspace @caseops/web -- app/app/ip/page.test.tsx` | **28 passed** |
| Web + Playwright types | web typecheck plus isolated/broad Playwright test listing | **passed; dedicated spec is one test and broad RAM lists none** |
| PostgreSQL + local Docker Playwright | fresh exact candidate | **pending** |
| Deployed dated Playwright | `playwright.ip-cost-prod.config.ts` | **not run; exact deployed candidate/fixtures required** |

The exact final-commit Docker/PostgreSQL Playwright result is intentionally not
self-asserted inside this source-controlled document: it is run only after the
candidate is committed and is recorded in the Draft PR/test evidence. Hosted
CI, integration into `main`, deployment, exact production identity, and dated
production Playwright remain required before `verification_status` or
`release_status` can move from `not_run / blocked`.
