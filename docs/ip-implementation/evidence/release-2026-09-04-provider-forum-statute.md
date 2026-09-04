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

- Provider-keyed usage, one INR 1,000 default monthly account limit shared
  across Indian Kanoon and eCourts, and tenant-locked expiring reservations
  that include every provider in the effective budget scope.
- Explicit persisted unlimited policies for the two founder-authorized account
  names when those companies exist at migration time.
- Tenant billing and provider status projections for provider contribution,
  budget-scope spend, limit, remaining, currency, policy source, and unlimited
  state without an external probe.
- Explicit automation-marker enforcement before paid transport, while human
  access does not depend on a test-looking slug.
- Shared active canonical forum/alias resolution for manual and bulk matter
  creation, with contextual ambiguity for multi-district Delhi complexes.
- Governed platform alias administration with dedicated capability and recent
  step-up, source-backed review state, activity, actor attribution, optimistic
  versioning, typed failures, audit reason, and no code release for new reviewed
  labels. Ambiguous bulk rows now expose structured canonical candidates and
  hierarchy in preview and error export.
- Full catalog-section visibility on Act details with honest trust state and
  source navigation; downstream legal use remains verified-only.
- Side-effect-free Matter read projection for legacy closed records.

## Test ownership

- `apps/api/tests/test_20260904_provider_spend.py`
- `apps/api/tests/test_20260904_provider_spend_forum_migration.py`
- `apps/api/tests/test_20260904_forum_alias_resolution.py`
- `apps/api/tests/test_20260904_forum_alias_admin.py`
- provider regressions in `apps/api/tests/test_case_tracking.py` and
  `apps/api/tests/test_indian_kanoon.py`
- lifecycle regression in `apps/api/tests/test_matter_lifecycle.py`
- web tests for billing usage, statutes, and `ForumSelector`
- `tests/e2e/provider-spend-forum-statute-2026-09-04.spec.ts`
- `tests/e2e/forum-alias-admin-2026-09-04.spec.ts`
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
- The post-review governed-alias increment passed 15 focused API tests, six web
  component/page tests, Ruff, TypeScript, and OpenAPI regeneration before the
  private-projection hotfix was integrated. Exact integrated Docker evidence is
  still required below and supersedes these focused counts for release.
- Interfering task `01a02a6c-5e05-74d1-b174-d8c780ffd6ea` was constrained to
  private-projection PR #453. It confirmed a clean worktree and no merge,
  `main`, deployment, paid-provider, or production mutation; this release owns
  integration and all remaining gates.
- The complete host-native API regression on the current working tree passed
  with 3,922 tests, 146 intentional environment skips, and zero failures in
  5,286.21 seconds. Ruff passed before pytest. The skipped PostgreSQL-only
  coverage remains mandatory in the exact-candidate Docker pre-commit run.
- The complete host-native web regression passed all 824 tests in 158 files;
  TypeScript typecheck also passed. This was a clean isolated rerun after a
  concurrent backend/web attempt exposed unrelated timing-sensitive tests.
- The branch is based on canonical `origin/main` at `67b89bdf`, which includes
  the merged private-projection deadlock fix from PR #453. The governance map,
  generated data-class projection, ownership ledger, ARCH-OPS contract, and
  program manifest validate without drift on this integrated tree.
- The clean exact-candidate Docker pre-commit gate passed at source fingerprint
  `63a3967318372e01a0266becbbfc7abcd5ab737cbe99bf584532475e2199d13c`.
  PostgreSQL/pgvector passed all 119 tests. Desktop Playwright passed 185
  journeys with five intentional environment/provider skips (94 passed and one
  skipped in shard one; 91 passed and four skipped in shard two), and mobile
  Playwright passed all four journeys. The harness removed its containers,
  network, and volumes and exited zero. This evidence-file update is release
  bookkeeping after that gate and does not change runtime or test inputs.
- The exact-candidate Docker browser proof covered provider budgets without an
  external probe, full catalogued Bare Act section browsing, contextual
  forum-alias resolution, manual/bulk use of the same exact forum catalog, and
  the deep Matter lifecycle regression for disposal, stale-write rejection,
  operational suppression, controlled reopen to Intake, and reload
  persistence. The Product Guide journey also passed after replacing its stale
  hard-coded version assertion with the canonical generated catalog version.
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
  examples are implemented with official district context, the governed master
  accepts reviewed additions for every active catalog jurisdiction, and
  ambiguous complex names stay unresolved without context.
- Catalogued statute sections can be browsed, but legal selection still requires
  exact official text, hash, publisher, issuing body, source version, and a
  checked section-level link.
- Repository readiness does not prove provider authentication, account balance,
  or a meaningful live result. Paid-path operational acceptance belongs to an
  authenticated human action under budget, not automated regression.
