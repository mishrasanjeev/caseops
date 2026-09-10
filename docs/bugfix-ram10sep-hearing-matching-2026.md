# September 10 BUG-014 Hearing Matching

Verdict: **Inconclusive**. This is an uncommitted isolated implementation,
not a production fix. No parent files, credentials, paid policy, production
data, commits or remote refs were changed.

## Scope And Source

- Baseline: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
- Worktree: `codex/sep10-hearing-matching-20260910`; the 92-file dirty parent
  snapshot is recorded in `.hearing-matching-evidence/candidate-snapshot.json`.
- Canonical owners: J03/J08, M02/M08, MOD-TS-006, US-057,
  FT-078/079/080/081/082, NFT-021 and SEC-027.
- Source workbook: `CaseOps_Bugs_10Sep2026.xlsx`, SHA-256
  `c2a67eea079182a80c664247525f963327470ff7be5c4f846f3575fe271fd09e`.
  Two populated issue rows, no summary discrepancy. BUG-014 is Excel row 3;
  its stored report date is September 09 despite the September 10 filename.
- Parent's current read-only evidence identifies Matter codes 5977, 5967 and
  5927 with case numbers but no CNR or court scope. All four reported Matters
  already have automatic bookmarks with no provider attempt. The original
  import rows confirm missing scope, not loss of a configured leaf court:
  Excel 490/480/457 respectively; join identity is MatterCode, not a CSV line.
- Matter 5926, Excel 456, retains `consumer:ncdrc` and its court name. This is
  a separate eligible-identity case, not proof that a live match exists.
- `test-legal` remains excluded from scheduled paid calls. The workbook's
  proposed scheduled result cannot be certified by running that excluded
  tenant or by buying provider calls in automated tests.

## Implementation

The previous matcher rejected a typed Matter number when the provider returned
registration and case type separately, and accepted a conflicting provider type
when the case-number string happened to be identical. Both were reproduced.

The extension normalizes public number/type/year without interpreting packed
internal numbers. CNR remains primary. Otherwise an exact public identifier
and court are mandatory; filing, geographic, party and advocate evidence
corroborate when present. Contradictions and multiple matches fail closed.
There is no party-only discovery, fuzzy scoring, guessed court or new approval
workflow. Normalization is bounded to 20 provider candidates and 50 active
bookmark scopes per attempt.

The [official eCourtsIndia v4 contract](https://ecourtsindia.com/api/docs)
supports structured public-number search and a paginated result envelope.
Automatic searches use that filter, reject incomplete inventories, and verify
court locally when no search-ready provider code is available. They do not
send the undocumented `courtName` filter. No additional provider request was
introduced. Search remains distinct from asynchronous refresh; the parent's
pending/status recovery protocol, reservation accounting and 180-second lease
remain in place.

A malformed supplied CNR is not a fallback permission. The published CNR
shape is checked before automatic admission and transport; the missing-data
surface asks for correction. Published geographic enum labels take precedence
over abbreviated codes, without inventing local alias mappings.

Legacy automatic bookmarks re-read source identity before pricing/claiming.
Missing court identity disables manual refresh and rejects transport before any
reservation. Corrected Matters reuse the same bookmark. A changed source
invalidates a previously learned CNR and restarts bounded discovery rather than
continuing to read the previous external case.

Every attempt freezes current source identities, bookmark targets, lifecycle
and access-policy versions. After transport these are reloaded under parent
locks and current authorization. An identity, archive, access or disposal race
cannot publish a snapshot or date, while a delivered provider response remains
accounted. A SHA-256 scope fingerprint and policy version accompany the
existing operation evidence. Converged canonical links also recheck source
identity before date writes.

The Matter Listing keeps its existing date column and adds a link to the
Matter's details when required identity is absent. This is a missing-data
message, not a claim of provider readiness or scheduled eligibility.

## Evidence

All commands used owned containers capped at 1 CPU/2 GiB with networking
disabled. Existing test-tool images were reused; no image build was run.
Pytest uses `-p tests.retained_results` and `CASEOPS_TEST_RESULT_JOURNAL`.
Journals and XML files are retained under `.hearing-matching-evidence/`.

- `reproduce-01`: two expected product failures; full call reports inspected.
  A pure helper edit during that diagnostic means it is not an exact-source
  gate; the legacy service under reproduction was unchanged.
- `unit-02`: 15 passed, four test-construction errors from omitted adapter
  constructor arguments. All four full reports were inspected and corrected.
- `smoke-03`: 19 passed, two exact-lease assertions failed because the service
  samples its start and expiry clock separately. Both reports were inspected;
  the regression now freezes the test clock and retains the 180-second bound.
- `smoke-04`: six passed (manual/scheduled success and case-identity races,
  two registration backfill variants). A scope-query batching edit occurred
  during this diagnostic; it is not an exact-source gate for that later edit.
- `legacy-05`: 22 passed, zero skips/errors, 19.45 seconds. Covers the matcher
  and manual/scheduled legacy correction, including zero spending before the
  correction, one retained bookmark, successful current-identity matching and
  persisted upcoming date. Superseded by the complete inventories below.
- `offline-06`: 42 passed, zero skipped/failed reports, 57.34 seconds;
  completion event and six unchanged source hashes checked. Later contract
  guards are covered by the replacement inventory below.
- `offline-07`: **50 passed**, zero skipped/failed reports, 70.52 seconds.
  `offline-07-reconciled.json` records the completion event and zero mismatches
  against eight hashes in `offline-07-source.json`. This includes 26 matcher/
  provider tests and 24 manual/scheduled/legacy integration tests on SQLite.
  It reconciles the earlier product and fixture failures; it is not PostgreSQL
  evidence. The NCDRC positive is explicitly synthetic, not a paid live result.
- `web-check-01`: six component tests passed; the standalone dated-spec type
  runner omitted Node ambient types and failed. Preserved logs distinguish
  this setup error from a product or browser failure.
- `web-check-02`: dated-spec typecheck and six component tests passed.
- `web-check-03`: dated-spec typecheck and **eight component tests passed**,
  including malformed CNR and missing-year actions. Full results retained in
  `web-component-03.json`; both command logs record exit zero.
- Final Ruff check passed for all eight owned/modified Python files.

The prior failing journals remain intact. No buffered progress output was used
to classify failures, and none of these runs used external provider transport.

## Exact File Inventory

New files to copy from this isolated worktree:

- `apps/api/src/caseops_api/services/hearing_matching.py`
- `apps/api/src/caseops_api/services/hearing_matching_scopes.py`
- `apps/api/src/caseops_api/scripts/docker_acceptance_hearing_provider.py`
- `apps/api/tests/test_20260910_hearing_matching.py`
- `apps/api/tests/test_20260910_hearing_matching_races.py`
- `apps/api/tests/test_hearing_matching_postgres.py`
- `apps/web/components/matters/NextHearingCell.tsx`
- `apps/web/components/matters/NextHearingCell.test.tsx`
- `tests/e2e/ram-2026-09-10-hearings.spec.ts`
- `docs/bugfix-ram10sep-hearing-matching-2026.md`

Incremental shared-file changes, not whole-file replacements:

- `apps/api/src/caseops_api/services/case_tracking.py`
- `apps/api/src/caseops_api/services/case_tracking_providers.py`
- `apps/web/app/app/matters/page.tsx`

`.hearing-matching-evidence/handoff-files.json` records exact final hashes for
this inventory and the three incremental patches. The inherited 92-file dirty
snapshot is not an integration payload. No schema migration is introduced.

## Integration And Remaining Gates

Use `.hearing-matching-evidence/case_tracking.final.incremental.patch`,
`case_tracking_providers.final.incremental.patch`, and
`matters-page.final.incremental.patch` as incremental hunks against the dirty
snapshot. The older `case_tracking.incremental.patch` is superseded. Never
replace the parent's whole service or apply a whole-function AST replacement
over Hume's changes. The parent owns asynchronous summary integration and must
retain its own post-summary authorization/lifecycle boundary.

In overlapping functions, merge the additional attempt fields/scope capture
before claim dispatch, current-source rehydration before pricing/reservation,
scope comparison after transport, and matching identities at snapshot
validation. Preserve the parent's no-transaction transport, lease recovery,
pending-refresh protocol and summary-worker scheduling. In `apply_snapshot`,
retain both this identity check under the Matter locks and the parent's later
summary boundary. This worktree did not edit the parent or its release config.

New regression files: `test_20260910_hearing_matching.py`,
`test_20260910_hearing_matching_races.py`, `test_hearing_matching_postgres.py`,
`NextHearingCell.test.tsx`, and `ram-2026-09-10-hearings.spec.ts`.

PostgreSQL and full browser gates were requested from the parent but are not
approved/run in this worktree. The new PostgreSQL wrapper contains 24 tests,
including forced manual/scheduled identity, disposal, archive and membership
races, both ambient backfill settings, and legacy-bookmark recovery. Parent's
earlier PostgreSQL 24-test result is
for another frozen candidate and does not certify this extension. Run all new
forced manual/scheduled races plus the existing provider/backfill/protocol
regressions; retain every failed journal before replacement.

The dated local browser spec requires the separate
`caseops_api.scripts.docker_acceptance_hearing_provider` emulator and
`CASEOPS_E2E_HEARING_PROVIDER=sep10-offline`. Its older sibling emulator still
lacks the complete official search envelope and separate type/registration
fields; parent must adapt that fixture without changing its older expected
dates before replaying older hearing specs. Parent explicitly owns adding this
dated spec together with the summary/statute specs to `playwright.app.config`;
the old dated-bugs-only pattern omits all three. This worktree did not edit
that configuration. Production branch is read-only, runtime-credential-only
and has not run. No responsive browser screenshot is certified here.

No free-text court-to-provider-code mapping is invented. A broad number search
whose complete inventory exceeds 20 is ambiguous, even if another page might
contain a unique candidate. Geographic code/name equivalence requires the
provider's published labels; unsupported aliases cannot become matching proof.
Official field coverage for a real NCDRC result is not established here.

Parent must reconcile the canonical PRD/bug/enterprise/coverage ledgers,
provider price configuration, full exact-source gates and eventual release.
No missing Matter data or production policy was silently corrected.
