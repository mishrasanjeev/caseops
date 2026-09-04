# 2026-09-04 provider, forum, statute, and lifecycle release evidence

## Scope and ownership

This release extends existing owners: IPLF-054/056B for Indian Kanoon and
provider operations, IPLF-006B/006C for statute trust, Legal Workspace S4 and
the Matter importer for forum identity, SaaS billing for usage attribution, and
the dedicated Matter lifecycle service for terminal-state control. It adds no
parallel provider dashboard, billing ledger, court master, importer, statute
catalog, or lifecycle writer.

## Source reports assessed

- `CaseOps_Bugs_Ram04Sep2026.xlsx`: three populated bug rows, BUG-007 through
  BUG-009. The workbook Summary tab's count of four is stale.
- `CaseOps_AI_Bulk_Upload04_Sep2026.docx`: one court hierarchy, alias, and bulk
  matter upload enhancement with shared manual/bulk catalog requirements.

## Implemented candidate

- Provider-keyed usage, an INR 1,000 default monthly limit independently for
  Indian Kanoon and eCourts, and tenant-locked expiring reservations.
- Explicit persisted unlimited policies for the two founder-authorized account
  names when those companies exist at migration time.
- Tenant billing and provider status projections for spend, limit, remaining,
  currency, policy source, and unlimited state without an external probe.
- Explicit automation-marker enforcement before paid transport, while human
  access does not depend on a test-looking slug.
- Shared active canonical forum/alias resolution for manual and bulk matter
  creation, with contextual ambiguity for multi-district Delhi complexes.
- Full catalog-section visibility on Act details with honest trust state and
  source navigation; downstream legal use remains verified-only.
- Side-effect-free Matter read projection for legacy closed records.

## Test ownership

- `apps/api/tests/test_20260904_provider_spend.py`
- `apps/api/tests/test_20260904_provider_spend_forum_migration.py`
- `apps/api/tests/test_20260904_forum_alias_resolution.py`
- provider regressions in `apps/api/tests/test_case_tracking.py` and
  `apps/api/tests/test_indian_kanoon.py`
- lifecycle regression in `apps/api/tests/test_matter_lifecycle.py`
- web tests for billing usage, statutes, and `ForumSelector`
- `tests/e2e/provider-spend-forum-statute-2026-09-04.spec.ts`
- `tests/e2e/provider-nonbillable-live-2026-09-04-prod.spec.ts`

## Candidate evidence

- Integrated backend run after merging the 2026-09-04 automatic hearing work:
  81 passed and five failures. The failures exposed a real SQLite writer
  collision after backfill and a post-convergence spend key error.
- Corrective focused proof: all 14 automatic hearing tests passed after using
  the scheduled poll's existing writer transaction for reservation and pinning
  cost before tracked-case identity convergence. The partial scheduled-charge
  regression also passed.
- Broad integrated API proof after formatting: 86 passed in 122.02 seconds.
  This includes case tracking, Indian Kanoon, lifecycle, exact forum bulk
  import, automatic next-hearing sync, alias resolution, provider spend, and
  upgrade/downgrade migration tests.
- Targeted web proof: 4 files and 20 tests passed for tenant billing usage,
  statute detail, forum selection, and Product Guide search; TypeScript
  typecheck passed after the public law-firm copy update.
- Ruff check and format-check passed for every changed Python file. The
  canonical program manifest validated with 436 requirements, 50 families, 68
  journeys, and 317 atomic paths.
- The complete API regression passed from the API project root with 3,905
  passed and 144 intentional skips. The complete web regression passed 821 of
  821 tests; TypeScript typecheck and the production Next.js build also passed.
- After fast-forwarding the candidate onto canonical `main` at `633d2375`, the
  governance map, generated data-class projection, ownership ledger, ARCH-OPS
  contract, and program manifest all validated without drift.
- A fresh Docker pre-commit build validated source fingerprint
  `93678e367ef7c61cd8c472c7a22b9bfbb6f18722ba92138c939b5270276aba67`.
  PostgreSQL schema `20260904_0002` had zero missing or invalid indexes, zero
  foreign-key index gaps, and zero sequential-scan warnings. All 117
  PostgreSQL/pgvector tests passed. Desktop Playwright passed 185 tests with
  five intentional provider/release-identity skips; mobile Playwright passed
  all four tests. The harness then removed its containers, network, and data
  volumes.
- The Docker browser proof includes the three dated 2026-09-04 journeys for
  provider budgets without an external probe, full catalogued Bare Act section
  browsing, and contextual forum-alias resolution. It also includes the deep
  Matter lifecycle regression proving disposal, stale-write rejection,
  background/operational suppression, controlled reopen to Intake, and reload
  persistence.
- CI, exact deployment, policy-row, production acceptance, and persisted
  production lifecycle evidence remain pending at this checkpoint. No
  `Properly fixed` verdict is derived from this file until those gates are
  appended.

## Required production assertions

1. The Alembic chain has one head and applies `20260904_0001` followed by
   `20260904_0002` on PostgreSQL.
2. Both named existing companies resolve to two active unlimited provider
   policy rows. A name mismatch is a release blocker and must be corrected by a
   tenant-ID-specific audited operation, not a runtime name bypass.
3. API and web serve the exact current `origin/main` revision at 100 percent
   latest-only traffic.
4. Production Playwright sends the no-paid-provider marker, reads readiness and
   recorded balances, receives blocked paid operations, and proves spend is
   unchanged.
5. Matter lifecycle diagnosis reads persisted Matter state and audit events.
   An explicit audited `Disposed -> Intake` transition is not automatic
   resurrection; any other writer is stop-ship.

## Honest residuals

- All-India reviewed alias coverage is not complete. The supplied Delhi
  examples are implemented with official district context; ambiguous complex
  names stay unresolved without context.
- Catalogued statute sections can be browsed, but legal selection still requires
  exact official text, hash, publisher, issuing body, source version, and a
  checked section-level link.
- Repository readiness does not prove provider authentication, account balance,
  or a meaningful live result. Paid-path operational acceptance belongs to an
  authenticated human action under budget, not automated regression.
