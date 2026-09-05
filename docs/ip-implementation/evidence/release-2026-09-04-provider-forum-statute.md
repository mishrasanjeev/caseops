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
- Candidate `7734ec35` passed canonical CI, security, deployment, policy-row,
  live human provider, and persisted lifecycle audits, but exact-release
  production run `33923480806` remained red. It found one stale dated statute
  assertion, one ambiguous foreign-associate response loss after the server had
  committed HTTP 201, and one real Matter-disposal rollback caused by
  `StaleDataError` during concurrent failed-shadow cleanup. This is a stop-ship
  follow-up; earlier green evidence does not close the release.
- The follow-up PostgreSQL regression deliberately reproduced the disposal race
  with the old all-generations query (`expected to update 2 row(s); 1 were
  matched`) and passed after event mutation was scoped to its captured active
  generation. Separate tests retain tenant-wide all-generation disposition and
  prove lost mutation responses are reconciled from one exact versioned event
  without replay.
- Full clean Docker validation passed on source fingerprint
  `7711f0f2478379a69f0b48b0cbd3615bbe5bdcd9c23b5127ade88cae1ffca370`:
  120 PostgreSQL/pgvector tests, 186 desktop Playwright tests, and four mobile
  Playwright tests passed; five provider/release-gated tests were intentionally
  skipped. The complete API inventory passed 3,923 tests across 13 disjoint
  file shards with 147 explicit environment-gated skips, and all 824 web unit
  tests passed. CI, redeployment, production Playwright, and two quiescent
  maintenance cadences remain required.

## Final exact-release closure

- PR #454 passed the complete pull-request gate and merged as
  `c0d3874e55ba00d35cf498f6eb9c9393f2e404b0`. Fresh push CI run
  `33932463982` completed with 19 successful jobs; Security run `33932463979`
  and CodeQL run `33932463969` passed on the same merge.
- The canonical release built API digest
  `sha256:2d48717660938c7e7cf17e4ce093bde10f942a549a8564a461765a7fac9f8469`
  and web digest
  `sha256:a07df7b319255e7f7710bf52f22e1a60dd08c7be57263d0b348a2f69ba2d6baa`.
  Migration execution `caseops-migrate-job-5rbs6`, statute seed `qxnzj`, Indian
  Kanoon cost seed `xxsqt`, and database-index execution
  `caseops-db-index-health-npz9x` all completed before routing.
- Production API revision `caseops-api-00442-n4p` and web revision
  `caseops-web-00419-r76` served `c0d3874e` at 100% latest-only traffic with an
  OK health response. Production QA bootstrap `caseops-ip-qa-bootstrap-pj2jk`
  completed on the exact API image.
- Exact-release workflow `33934998564` passed 110 canonical production browser
  journeys in 21 minutes, one dedicated cost journey, and two notice journeys.
  The run exercised persisted Matter lifecycle/audit state, disposal and
  controlled reopen, statute trust, provider readiness, and foreign-associate
  response reconciliation.
- The separate opt-in no-paid-provider production spec passed against the
  supplied test tenant. It found the account had INR 0.52 total shared-budget
  spend, correctly distinguished that from each provider's contribution,
  rejected both paid automation calls before transport, and proved provider
  contribution plus shared-account spend remained unchanged.
- Read-only execution `caseops-provider-policy-audit-c0d3874-qs5mf` asserted and
  printed exactly four active `INR` unlimited policies with source
  `user_authorized_named_exception_2026_09_04`: eCourts and Indian Kanoon for
  GBA Law Office, and both providers for Pinelabs Pvt. Ltd. The disposable job
  was deleted after evidence capture.
- With the scheduler paused, maintenance execution
  `caseops-private-projection-maintenance-hjblt` rebuilt tenants
  `3af2e297-06cd-450d-bdc6-8ebc174b20a9` and the alerted
  `6d610b43-83df-49b8-b73a-c0f181d034e6`; every tenant finished with zero
  blockers and `release_blocked=false`. The required second execution `n8chm`
  had `rebuild_count=0`. After scheduler resume, executions `j2q6v` and `nc7fr`
  repeated the same clean no-rebuild state. Live scheduler inventory verified
  against the exact immutable API digest.
- The operator runbook's obsolete `inspect-live --expected-image` example was
  corrected to the executable `verify --image` interface. The dedicated
  provider test now asserts provider contribution and account-scope spend as
  separate values, preventing the false failure discovered during this release.

Final verdicts: BUG-007 and BUG-009 are properly fixed. BUG-008 is partially
fixed because every catalogued section now opens a truthful detail/source
surface, while unverified official section text remains a governed data gap.
The forum enhancement remains partial until reviewed all-India alias coverage
is complete. No unauthorized Matter reopen was reproduced; the adjacent real
disposal-rollback race is fixed and covered by PostgreSQL plus production
lifecycle regression.

## Required production assertions

The follow-up CI timeout repair covers all three GitHub-hosted browser jobs:
app CI, production verification, and release verification. Browser download has
a five-minute bound, followed by a two-minute real Chromium launch/content
check. Optional apt font downloads no longer precede those tests. A shared
parameterized workflow regression checks all three paths. PR CI run
`33940135057` proved the new runtime check completed in two seconds before
the app suite started. The superseding PR and main runs must also pass.

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

## Final acceptance-discovery audit

The alias-administration spec was committed but not selected by the normal app
config inherited by Docker acceptance. Earlier desktop counts must not be
attributed to that CRUD journey. Adding it exposed a reserved-domain email
fixture rejected at bootstrap. The follow-up uses one schema-valid local
founder identity in host and Docker acceptance, relative browser URLs, explicit
cleanup assertions, mobile deactivation and reload, and ordinary-tenant denial
through both API and UI. Synthetic global alias writes are guarded to loopback
before bootstrap. Audit-event correctness is asserted separately in
`apps/api/tests/test_20260904_forum_alias_admin.py`.

The Docker gate's default founder configuration remains empty outside the
isolated acceptance harness. Production administrator privileges and legal
catalog contents are not changed by this test fix. Final full Docker results,
PR/main checks, and the exact serving release must be recorded before closure.

The newly executed browser journey then reproduced a real mobile layout defect:
the absolute `sr-only` Actions heading escaped the unpositioned table scroller,
making document width 914 px on a 360 px viewport. A direct Docker browser
experiment measured 360 px after positioning the scroller. The source fix
preserves horizontal table scrolling and the accessible heading. The dated
journey now checks 360, 767, 768, 769, 1024, and 1280 px widths plus usable search
width, and a component test protects the positioned scroller. Adjacent `sr-only`
uses in IP, billing, notices, contracts, and Matter documents were inspected;
they are loading/form labels, not offscreen table headings with this defect.

The final clean Docker gate passed on source fingerprint
`f80dc83d2c7d031ba73c91abf6356eaea01121b95806fe88ecf7f7929dff1256`:
120 PostgreSQL/pgvector tests, 190 desktop journeys (97 plus 93 in disjoint
shards), and all four mobile journeys. The five explicit skips comprise the
credential-gated payment-link test and four production-only identity checks;
none counts as a passed flow. The newly discovered alias-admin create/resolve/
deactivate/reload journey and ordinary-owner denial both passed. All 825 web
unit tests across 158 files and all 67 deployment-hardening contracts passed.
This evidence-only append changes no tested runtime or browser input. Final
PR/main CI and exact production deployment remain required.
