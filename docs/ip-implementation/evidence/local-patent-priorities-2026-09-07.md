# Patent Priority Local Verification

Status: implementation in progress; the ancestry budget correction and priority
journeys have fresh b525 Docker proof. The seeded dated browser selection still
fails BUG-010, and the remaining PRD is incomplete. Production is NO-GO. No Git
or production publication has occurred in this continuation. The 7ec22 and c351
checkpoints below are historical, not certification of the newer source.

Mapping: UJ-29 / PAT-01 / IPLF-080-FAMILY / IPLF-080-COMPAT; modules M02, M08,
M13, M14. Execution contract: `../patent-priority-execution-2026-09-07.md`.
Both IPLF-080 slices remain in progress, not fully verified or release-enabled.
All 25 incomplete program slices remain incomplete.

## Production Request Follow-Up

The request to deploy after testing does not waive the existing release gates.
Read-only `git ls-remote origin refs/heads/main` still resolved to
`6a85cd5025101fd453bdc9b8472e963d16ba708a`. No commit, push, merge or cloud mutation
has run. The current source includes an additional ancestry-work guard, now
built and tested on b525. The retained 7ec22 browser evidence does not certify
this changed service.

`ip080-priority-postgres-shard-1-ancestry-repro.xml` reproduces missing budget
rejections on the original implementation for a 66-node dense graph and a
34-node chain (`DID NOT RAISE`). The third, retained-history case failed on an
invalid duplicate canonical relationship fixture, not the expected assertion
(129.50s total). The initial update incorrectly generalized the first failure
to all three; per-test XML inspection corrected that claim. The new traversal caps retained
rows and query count before filtering current relationships; the existing
tenant writer fence and cycle checks remain intact. The first corrected report has 14
passes and two history-fixture failures (832.24s); it is not a clean run.
A follow-up adds canonical history
reuse, positive/negative HTTP saves and idempotent replay to the same boundary
fixtures. All original reports remain immutable. The final results below
supersede the verification-in-progress status, not the retained failed reports.

Mapping: IPLF-080-PRIO-11/15, UJ-29, PAT-01, M02/M08/M13/M14. BUG-010 and
uncompleted program obligations remain open; this change is not statutory
content, full patent completion or production acceptance.

## Ancestry Follow-Up Results

All artifacts in this section are under `C:/tmp/caseops-ram05sep-20260905/`.

| Evidence | Result | Scope and limits |
| --- | --- | --- |
| `ip080-priority-postgres-shard-2-ancestry-history-baseline.xml` | One expected `DID NOT RAISE` failure, 41.32s | Corrected, valid 2,001-version history fixture reproduces the missing bound against the original 7ec22 service. The old duplicate-relationship fixture failure is not used as reproduction proof. |
| `ip080-priority-postgres-shard-1-ancestry-http-final.xml` | Six passed, zero skips, 229.62s | Dense 63/66-node graphs, 1,999/2,001 retained versions, 32/34-node chains; below-bound saves, over-bound typed HTTP 409, idempotent replay, unchanged original hashes, bounded queries/rows and responsive concurrent application correction. |
| `ip080-priority-postgres-shard-1-ancestry-corrected.xml` | 14 passed and two invalid history-fixture failures, 832.24s | Its 14 passing identities plus the corrected final six yield 16 unique passing identities, not 20. Includes the existing seven HTTP journeys, disjoint cycle race, interrupted-index migration recovery and 10,000-application scale fixture. This report remains failed. |
| `ip080-ancestry-offline-api.xml` | 145 passed, zero skips, 683.93s | Complete affected priority/application/party/family/domain/contracts files in network-disabled Docker. This is not a full current-source API suite. |
| `ip080-ancestry-fresh-docker-postgres.xml` | Seven passed, zero skips, 596.85s | Explicitly filtered PostgreSQL HTTP journeys on the newly built b525 stack. The verifier's generic complete-suite log label does not expand this selection. These identities overlap the PostgreSQL proof above. |
| `ip080-ancestry-fresh-docker-browser.xml` | Nine passed, one failed, zero retries/skips | Three priority widths and seven dated Ram workflows. The first failure was an empty catalog setup, before reaching the five reported Acts. It is not direct content-completeness proof. |
| `ip080-statute-seed-gate-repro.xml` | One expected failure, 1.13s | Local verifier omitted the release-owned seed after database tests. The new contract regression reproduced that omission. |
| `ip080-statute-seed-gate-final.xml` | 110 passed, zero skips, 479.95s | Complete affected deployment-hardening, statute-governance/routes/schema and Matter-reference files in offline Docker, including contract checks for release-image ordering and the immediate seed-error gate. |
| `ip080-ancestry-seeded-browser-seed-1.log` and `-seed-2.log` | First seed: 23 Acts / 3,393 sections inserted; second: zero inserted | Exact command extracted from the corrected canonical verifier, executed in the already inspected API image. No synthetic provisions or new verification flags. |
| `ip080-ancestry-seeded-browser.xml` | Nine passed, one failed, zero retries/skips, 6.1 minutes | Same ten unchanged tests and b525 images after the real seed. All five reported Acts exist but are disabled and each returns zero verified sections. BUG-010 remains Not fixed. |
| `current-b525df5f92f9-tester/local-all-data-evidence.json` | Original-data browser replay and full comparison passed | 496 original rows, 391 created Matters, 97 invalid and eight duplicate rows excluded; all 10,416 retained cells and all 28 mapped fields per Matter match. Tenant, active state, complete identity set and idempotent replay checked. |
| `ip080-ancestry-final-contracts.log` | All structural gates, eight offline safety cases and full Ruff passed | 189 dirty paths reconciled; ten changed migrations have no findings, one head `20260907_0002`, no data-governance errors. The 854 historical migration advisories remain. Eight pleading fixtures and three research fixtures still have zero approved cases; structural success is not legal/retrieval quality. |

The fresh b525 images passed migration to `20260907_0002` and normal plus
512 MiB index-health checks. No missing/invalid/mismatched indexes, foreign-key
gaps or sequential-scan warnings were reported by those checks. The worker was
restarted at the restored schema head. All nine fresh priority screenshots were
inspected across 393/768/1280px: title/action separation and usable wrapping
remain intact. Both empty-catalog and seeded BUG-010 screenshots were inspected.

Runtime identity:

- Project: `caseops-acceptance-b525df5f92f9`.
- Source fingerprint: `b525df5f92f9c3ef81cf0986dd8c7b052e528f248143399dc4e07ed342878bda`.
- Runtime revision: `b525df5f92f9c3ef81cf0986dd8c7b052e528f24`, not a Git commit.
- API/worker: `sha256:89a2feefb69b485cb4d9a7ed7e04ab7299f44d48d3adbf7d03f60c7694b62de1`.
- Web: `sha256:523c8813cf0eceff3dff218c2170f22ddf4e02ccbfc19bc1f1c925f9290e5f75`.
- Retained local tester: `http://127.0.0.1:38557`, `test-legal`, supplied tester
  login. Its hidden loopback proxy remains available; its error log is empty.

The actually imported service at
`/usr/local/lib/python3.13/site-packages/caseops_api/services/ip_patent_priorities.py`
matches the workstation file byte-for-byte:
`f71e82787b1ebcc72265d7315bdd4ae93c9dddc05cbbca8a3e5751be6e8a4fe4`.
Post-test API health is `ok`; API and web still expose the same b525 runtime
revision. Native source inventory still has the same 189 dirty paths and HEAD
remains `6a85cd5025101fd453bdc9b8472e963d16ba708a`. The final evidence-only
update follows the contract check and changes no executable source.

The seed-harness correction and evidence updates followed the image build.
They do not change application runtime source, but this replay is not a fresh
complete canonical certificate. The verifier now seeds the checked-in release
catalog after database rollback tests and fails immediately on a seed error.
That aligns test setup with the production script; it does not close legal
content acceptance. The seeded inventory has only one officially verified
section among 3,393, and zero for all five reported Acts.
Seed/read/attachment mapping remains RAM05-STATUTES, J05/J07, M05,
MOD-TS-017, US-046A/B/C/D and FT-095. No new parallel catalog was introduced.

PRIO-15's ancestry-specific gap has local implementation and regression proof;
it must not remain listed as an unimplemented duplicate task. Formal release
acceptance remains incomplete. No timeout, lifecycle guard, tenant boundary,
source verification predicate or no-paid-provider guard was relaxed. Existing
local stacks and source data were preserved; no global cleanup ran in this
follow-up. All 25 incomplete program slices still remain open.

## Implementation

- Canonical `IpRelationship` owns each edge. Append-only patent detail versions
  pin source document/version/hash, actor, reason, review notes, fact hash,
  application/lifecycle versions and sequence. Composite ownership constraints
  and a unique successor prevent cross-tenant evidence and history forks.
- Four sourced relationship kinds: priority, divisional parent, patent-of-addition
  parent and national-phase parent. Dates and application kinds are checked;
  office labels are not treated as verified office identities. Missing dates
  and discrepant office/jurisdiction facts are recorded review notes, not invented
  legal determinations. No priority entitlement, fee or deadline is inferred.
- Corrections retain old facts; withdrawal removes a current recorded edge, not
  the application. New links require active endpoints. Same-edge evidence updates
  may read a closed historical parent but may not mutate or reopen it.
- A tenant-scoped advisory fence precedes actor and parent locks on application
  identity corrections and relationship writes. It prevents cycles created by
  simultaneous commands whose immediate endpoints do not overlap.
- Application fact corrections revalidate current incoming and outgoing links.
  Graph and evidence pages have independent cursors and bounded batch reads;
  source revocation fails closed. Cross-family links do not merge families or
  grant access. The new migration preserves legacy relationship mutability and
  refuses a downgrade that would remove retained patent evidence.
- Existing application and family workspaces gain Priorities and Relationships
  views. The editor waits for authoritative discovery, preserves unsaved values,
  carries the captured collection version, cancels stale list reads after a
  successful mutation, and retains source download/version history.
- Product Guide and its existing generated command catalog now describe the
  actual patent intake/evidence path, not unimplemented prosecution automation.

## Completed Focused Checks

Evidence directory: `C:/tmp/caseops-ram05sep-20260905/`.

| Evidence | Result | Boundary |
| --- | --- | --- |
| `api-full-ip080-priority-api-correct-runner.xml` | 88 passed, zero skipped | New priority API/contracts plus existing application/party regressions, offline Docker |
| `api-full-ip080-priority-postgres-first.xml` | 9 passed, zero skipped, 439.21s | HTTP boundaries, disjoint concurrent-cycle race, interrupted concurrent-index recovery, second upgrade, retained downgrade refusal, immutable evidence and legacy mutation compatibility |
| `ip080-priority-postgres-scale.xml` | 1 passed, zero skipped, 97.06s | 10,002 applications, 1,000 families, 10,001 edges; 100-application/500-link page within 100 SQL statements and 5s per-statement budget; oversized incoming correction rejected; concurrent application writer completes within 5s while graph transaction remains open |
| `ip080-priority-web-first.xml` | 54 passed, one failed | Graph test asserted before the next page rendered; original report retained |
| `ip080-priority-web-corrected.xml` | 64 passed across five files, zero skipped | Original graph assertion synchronized to next-page rendering; new complete API-schema tests, adjacent patent surfaces, and TypeScript check pass in offline Docker |

These are focused checks, not a complete current-source release certificate.
Cross-family and cross-tenant API tests, guide changes and generated contract
updates added after the first API snapshot require the final integrated rerun.
The source-only snapshots retain a Git baseline, path inventory and source hash.

## Historical Integration Before Responsive Review

- Fresh f030 source-fingerprint images passed migration to `20260907_0002`,
  complete index health and the 512 MiB index-health check. API image:
  `sha256:b2e1950e6865c5fbf8402a3a07758104a0022ddcbdeee244acbf7de81ffd03db`;
  web image: `sha256:fbd3273bd80a844fa4bdf1210ca21e7e50b3eb33bdfa74934fc0222fae257f00`.
  The source fingerprint is not a Git commit. The canonical verifier's serial
  host PostgreSQL phase was intentionally interrupted; its exit is not PASS.
- `ip080-priority-browser-first.xml`: three passed, zero skipped, 1.7 minutes.
  All four relationship kinds, cross-family graph, cycle rejection, closed-parent
  source correction, exact historical download hash, withdrawal and reload ran
  at 393/768/1280px. Runtime/source checks passed before and after execution.
- All nine screenshots were inspected. They exposed duplicate active navigation
  and a squeezed relationship title at tablet width that the original 24px link
  bound did not reject. The corrected shared sidebar selects the most-specific
  visible path; party and priority title rows reserve useful width. The dated
  journeys now assert one active destination, 192px available title width and
  title/action non-overlap. Fresh-image verification of these corrections is
  pending; the original three browser passes do not certify the newer UI.
- Four migration-first PostgreSQL shard reports contain 47, 44, 44 and 43 passes:
  178 total, zero failures/errors/skips. Exact-identity/source-hash reconciliation
  is required before aggregate acceptance. All earlier failed reports remain:
  CRLF selectors initially executed zero tests; the next attempt passed 170 but
  had eight setup errors because the fresh base database was not migrated.
- The integrated API selection passed 177 and failed one stale generated data-map
  assertion. Regeneration and a 61-test contract recheck passed. Complete API
  verification remains in progress; this does not claim a clean full run.
- First full frontend attempt had a missing root fixture; the next ran 915 tests
  with two initial-load assertion failures. Corrected billing/recordal assertions
  keep their original timeout and user-visible requirements. The publication
  test now verifies success feedback, no error, cleared inputs and preserved
  drafts on rejection. TypeScript and all 25 focused checks passed in
  `ip080-priority-review-web-corrected.xml`; an intervening TypeScript failure
  used an unsupported role-query option and is retained in its original log.
- `ip080-priority-sidebar-repro.xml` reproduced 21 failures across 57 tests,
  including sibling IP, billing and administration routes. Complete frontend
  acceptance with the corrected shared navigation is in progress.

The statements about checks in progress in the historical subsection above are
superseded by the final local checkpoint below; its original failures remain.

## Historical 7ec22 Priority Checkpoint

The retained Docker project is `caseops-acceptance-7ec22c6c241f`, with web on
`http://127.0.0.1:36222` and API on `http://127.0.0.1:36220`.
Source fingerprint:
`7ec22c6c241f6def78ba278c8b304d0b97e69dca76ef2f54e560d3ff8d6f9a66`.
Runtime revision: `7ec22c6c241f6def78ba278c8b304d0b97e69dca`.
This is a dirty-source identity, not a Git commit or deployed release.
API and worker image:
`sha256:0eb25fa6150c95df1a3426f4ca95445d8b15960f203f3dcc85187102a2e27b31`.
Web image:
`sha256:d405b43bc037c4c12ec7ce7445cbefe7841a687384a57cc912503d45756f950a`.

| Evidence | Observed Result | Qualification |
| --- | --- | --- |
| `ip080-priority-responsive-build-network-recovered.log` | Fresh build, migration `20260907_0002`, normal and 512 MiB index gates passed | No missing, invalid or mismatched indexes; worker running. Not a canonical release certificate. |
| `ip080-priority-full-api.xml` | 4,133 passed, one failed, 180 skipped; 6,354.46s | Original failure timed the whole rebuild at 230ms against a provider-specific 200ms assertion. It remains in this report. |
| `ip080-private-deadline-final.xml` | 29 passed, zero skips; 173.52s | Provider remains blocked after its deadline; provider phase and unrelated health response each remain below 200ms; late projection writes are absent. No production timeout increased. |
| `ip080-priority-api-source-reconciled.json` | 1,102 API files reconciled | Only an AST-equivalent model formatting change and the corrected deadline test differ from the archived full API source. The integrated deadline file matches the tested file after strict CRLF normalization. |
| `ip080-priority-postgres-reconciled.json` | 178 passed in four migration-first Docker shards | Exact node identities are complete and disjoint, with one dirty-source hash. Zero failures, errors or skips. |
| `sep07-priority-metrics.json` | 4,314/4,314 collected API identities have passing evidence | All 180 skips match PostgreSQL/native/Windows supplements. This does not turn the original full run into a clean run or cover every possible PRD flow. |
| `ip080-priority-full-web-final.xml` | 968 passed across 168 files, zero skips; 649.96s | Complete offline frontend suite and TypeScript passed, including all 58 shared navigation tests. |
| `ip080-responsive-desktop-1.xml` | 115 passed, one skipped | Complete first shard; exact source/runtime guards passed. |
| `ip080-responsive-desktop-2.xml` | 107 passed, four failed, four skipped | Three new priority assertions used an unsupported Playwright query option; the fourth failure is the genuine BUG-010 catalog gap. |
| `ip080-responsive-mobile.xml` | Four passed, zero skips | Separate mobile project; exact source/runtime guards passed. |
| `ip080-responsive-corrected-journeys-run2.xml` | 12 passed, one production-only skip; 5.3 minutes | Corrected priorities at 393/768/1280px plus research, recordal, provider-spend, statute-detail and bulk-court journeys. The original runtime images are unchanged. |
| `ip080-responsive-test-overlay.json` | 2,253 source hashes checked before and after replay | Exactly 15 reviewed test/configuration changes; application runtime files and package dependencies unchanged. Later documentation changes are not part of the built image. |
| `ip080-e2e-type-gate-complete-source.log` | Offline Docker typecheck passed | All E2E specs and Playwright configurations are now checked by `npm run typecheck:e2e`, CI and the local Docker verifier before image builds. |
| `ip080-priority-final-delta-contracts.log` | Structural contracts, full Ruff and eight offline AI-safety cases passed | Exact inventory: 189 dirty paths and ten changed migrations, single head `20260907_0002`, zero current migration findings or governance errors. The 854 historical migration advisories remain. This evidence-record update followed that check and changes no executable source. |

The exact 231-test desktop inventory is reconciled without counting overlapping
replays twice: 225 have passing evidence, BUG-010 remains failed, and five are
skipped (one live payment-provider journey and four production identity gates).
All nine corrected priority screenshots were inspected. Titles and actions fit
on mobile/tablet/desktop, and only Patent intake is active in navigation.

The original import was also replayed on this exact 7ec22 runtime using the
supplied `test-legal` tester account. Browser upload, preview, commit and
idempotent replay passed: 496 original rows, 391 created Matters, 97 invalid
rows excluded and eight duplicates excluded. Read-only verification compared
all 10,416 retained source cells and all 28 persisted mapped fields per created
Matter, plus tenant identity, active state and the complete list of created IDs.
The original source JSON and CSV hashes match the preserved earlier inputs.
Evidence is in `current-7ec22-tester/local-all-data-evidence.json` and
`current-7ec22-tester/local-ram-seed-evidence.json`. This additional data rehearsal
is not counted again in the 231-test desktop inventory. The loopback proxy and
fresh tester data are retained at `http://127.0.0.1:36222`; older stacks and data
remain untouched. No production mutation or paid-provider request was made.

The first new image startup failed because Docker's address pool was exhausted.
Only seven exited containers and the empty network of the obsolete
`caseops-acceptance-2b53b74f031b` project were removed. Named document/database
volumes, images, the c351 tester data and unrelated projects were preserved.
No global prune ran. `ip080-network-pool-cleanup.json` records this operation.

Earlier E2E type-audit failures are retained: missing Node-type configuration,
38 real test typing errors, and incomplete harness copies that omitted root
support/guide files. The final offline check uses the complete native source
inventory. A PowerShell argument-binding failure selected no browser tests and
is not counted as a pass. No assertion, security fence, provider spending guard
or product timeout was relaxed to obtain these results.

The legal pleading and research-golden validators still contain zero
approved fixtures. Their structural success is not legal or retrieval quality
acceptance. BUG-010 and all 25 incomplete program slices remain release blockers.

## Test Harness Findings

The first two API invocations were invalid: the tools image's baked entrypoint
wrapped an explicitly supplied runner again and selected zero tests. Neither is
acceptance. The corrected invocation explicitly selects Bash and the intended
runner. The frontend tools image uses Alpine `sh`, not Bash; its failed launch
ran no tests. Future invocations must verify entrypoint, available shell, selected
test count, actual exit code and a uniquely named nonempty report.

The old c351 stack and original tester/import data remain untouched. Its 222
desktop passes, one BUG-010 failure, five skips and four mobile passes describe
that older checkpoint only. The reported Acts still lack verified selectable
sections. No statute was falsely marked verified to turn that failure green.

## Required Before Completion

1. Resolve BUG-010 with exact, versioned official statute text and working
   section-level sources; preserve its failing test until positive selection,
   attachment and reload pass for every reported Act.
2. Obtain a clean integrated local certificate before any release. Keep the
   locally passing PRIO-15 ancestry limits and dense/history/depth regressions
   in that certificate; they are implemented, not a new duplicate backlog item.
   Historical contract checks and current affected-file passes are not a clean
   full-run certificate; skipped provider/production checks remain separate.
3. Remaining patent prosecution/proceedings/claims/maintenance/title and program
   obligations, representative production retrieval quality evidence, and BUG-010.
4. Canonical-main CI and exact-release production acceptance only after the local
   release gate is genuinely clear. The Downloads workbook retains c351 history
   and a separate 7ec22 priority checkpoint; neither is production certification.
