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

## Durable fix

- Unreleased Alembic revision `20260830_0003` normalizes existing projections,
  adds `ip_cost_item_corrections`, strengthens CHECK constraints, and installs
  SQLite/PostgreSQL guards. Direct row deletion fails while the parent exists;
  parent deletion remains cascade-safe because the trigger observes that the
  docket is already absent from the deleting statement's visibility.
- A source can have exactly one outgoing `void` or `supersede`. Supersession
  appends a complete independently validated replacement; neither source nor
  correction can be edited. Both histories remain readable, while only active
  rows participate in reconciliation, control totals or adjacent cost-link
  consumers.
- Matterless and every nonbillable cost are database-enforced as terminal
  `nonbillable` with no billing link and null canonical/difference amounts on
  both INSERT and UPDATE. Creator, reconciler and correction actor must be an
  active membership of the same tenant.
- Service, API and operator UI expose real correction/void actions and retain
  source evidence after disposition. The shared active-cost SQL predicate keeps
  renewals, foreign-associate spend, Madrid and recordal flows aligned.
- The local Docker Playwright remains explicitly loopback-only and may create
  fixtures/use a local database shell. The separate `2026-08-30-prod` spec has
  no shell imports; it requires exact API/web release identity, an explicit
  dedicated-tenant acknowledgement, a matterless docket and the complete
  declared Matter set, then compares public Matter workspace billing state
  before capture/reconciliation and after UI void.

## Current candidate verification

| Surface | Command | Result |
|---|---|---|
| API + SQLite focused | migration/correction/invariant tests | **passed during focused iteration; exact final command pending after final edits** |
| API lint/compile | targeted Ruff and Python compileall over the correction slice | **passed** |
| IP UI | `npm run test --workspace @caseops/web -- app/app/ip/page.test.tsx` | **28 passed** |
| Web + Playwright types | web typecheck and targeted dated-spec TypeScript compilation | **passed** |
| PostgreSQL + local Docker Playwright | fresh exact candidate | **pending** |
| Deployed dated Playwright | `playwright.ip-cost-prod.config.ts` | **not run; exact deployed candidate/fixtures required** |

The exact final-commit Docker/PostgreSQL Playwright result is intentionally not
self-asserted inside this source-controlled document: it is run only after the
candidate is committed and is recorded in the Draft PR/test evidence. Hosted
CI, integration into `main`, deployment, exact production identity, and dated
production Playwright remain required before `verification_status` or
`release_status` can move from `not_run / blocked`.
