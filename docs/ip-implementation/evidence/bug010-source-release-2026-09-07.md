# BUG-010 Official Source Release

Current checkpoint, 2026-09-08 IST: **NO-GO** until final PR/main CI and
exact-production acceptance finish. Complete rebuilt local acceptance passes. PR
#458 contains the earlier locally validated work; its review follow-up is not
yet committed. Production remains unchanged. The current runtime is
`19a33de2b82f6253d42ba6ba5a7ae63dcf6a5d6e`, an explicitly pre-commit source
fingerprint, not a released Git SHA. See the post-review evidence below.

Historical pre-release checkpoint, 2026-09-07 IST: Inconclusive for overall ticket closure.
The five named Acts have positive current-image browser evidence, but the
complete browser replay and exact-production acceptance are still pending.
No Git publication or production mutation at this checkpoint. This dated
record does not predict a future release result.

## Authorized Scope

The September 07 request is to fix BUG-010 and release the accumulated changes.
It does not declare the remaining 25 IP program slices complete. Preserve the
existing domain-availability restrictions, patent intake boundaries and roadmap
statuses. An unfinished roadmap is not itself a blocker to this scoped release;
failed quality, security, compatibility or deployment gates still are.

Mapping: RAM05-STATUTES, BUG-010, J05/J07, M05, MOD-TS-017, US-046A/B/C/D,
FT-S1..S4, FT-095 and IPLF-006. Existing owners: Statute, StatuteSection,
StatuteSourceVersion and MatterStatuteReference; no parallel statute subsystem.

The original workbook was reread: Bug Sheet row 2 contains one populated issue,
BUG-010, marked ReOpen. Its four-bug summary is stale. The reporter could not
select and attach Acts/sections in a Matter. This is a content-admission defect,
not permission to enable unverified law. A reopened ticket is not proof of an
automatically reopened Matter.

## Root Cause

The prior seed had 23 Acts and 3,393 catalogued sections, but only Article 14
had admitted source evidence. All five reported Acts had zero verified sections.
Their catalog included incomplete inventories and incorrect descriptions, such
as BNSS section 41 labelled as appearance notice rather than arrest by Magistrate.
BNS/BNSS identifiers were confused in source links; Arbitration and CPC also
pointed to different India Code handles. A positive Constitution fixture or a
correctly disabled option could not establish usable reported-Act coverage.

## Pinned Source Inventory

| Act | Numbered identities | Verified selectable | Withheld | Edition |
| --- | ---: | ---: | ---: | --- |
| Arbitration and Conciliation Act | 106 | 104 | 2 | India Code as on 2025-05-14 |
| Bharatiya Nyaya Sanhita | 358 | 358 | 0 | India Code as on 2025-10-06 |
| Bharatiya Nagarik Suraksha Sanhita | 531 | 531 | 0 | India Code as on 2025-10-06 |
| Companies Act | 523 | 480 | 43 | India Code A2013-18; retrieved 2026-09-07 IST; consolidation cutoff unstated |
| Code of Civil Procedure | 171 | 158 | 13 | India Code as on 2026-01-10 |
| Total | 1,689 | 1,631 | 58 | Exact edition, not a current-law certification |

The total catalog becomes 4,336 sections, of which 1,632 are verified selectable
including the existing Article 14. Other Acts remain honestly incomplete.
Counts do not represent complete current Indian law. Schedules, CPC Orders,
appendices and separate state-law records are not additional selectable rows in
this numbered-section bundle; the linked complete official PDFs retain them.

Official document URLs, raw PDF SHA-256 values, receipt timestamps, exact edition
labels, body/arrangement ranges, explicit printed-heading discrepancies and
judicial-treatment evidence are in
`apps/api/src/caseops_api/scripts/seed_data/verified_statute_documents.json`.
Original official bytes are retained under `tests/fixtures/statutes/official/`.
The six PDFs include the Supreme Court's Hindustan Construction judgment, whose
page 62 records the invalidation of section 87. Arbitration section 26 has a
publisher arrangement/body conflict; neither entry is silently admitted.
The 56 omitted/repealed entries remain retained and unselectable.

## Reproduction And Admission

`scripts/build_verified_statute_bundle.py --check` runs offline with the pinned
build tool pdfplumber 0.11.9 / pdfminer.six 20251230. It checks original document hashes, every arrangement
identity, exactly one approved central heading, central/state boundaries,
ordered page fragments, text hashes and publisher footnotes. Missing or changed
boundaries fail. No model, scraper fallback, invented text or provider traffic.
The current bundle contains 1,689 reconciled rows and has normalized UTF-8 hash
`71237941040d8a3a6097d2965b04569c5ce4f939f5217b10481830ed8742ddab`.

Dependency review rejected the initial PyMuPDF build tool under CODEX.md's
AGPL policy before publication. The replacement uses MIT-licensed pdfplumber
in a separate tool environment without changing application dependencies.
Cross-extractor comparison retained every non-whitespace character in all 1,689
bodies; three CPC entries differ in the ordering of printed margin punctuation
or list markers. The compiler never rewrites the underlying PDF evidence.

Publisher footnotes remain separately labelled page context, not invented body
text. The Companies 378ZA printed-heading error and CPC footnote prefixes are
explicitly recorded; their source text is not silently corrected. No blanket
commencement date is invented. The UI shows the exact published edition and
does not describe an unknown effective-to date as current law. BNS section 106
also carries the source edition's express subsection (2) commencement exception,
linked to the publisher's notification footnote on page 16.

The existing seed admits the checked bundle atomically, preserves section IDs,
locks existing section rows, leaves reviewed/quarantined/retired content alone,
retains pending source candidates, and creates immutable source-version evidence
without impersonating a human reviewer. Repeated seeding neither creates duplicate
versions nor refreshes source-receipt/link-check timestamps. Unknown provenance,
missing rows, wrong Act links, hash changes and enabled retired/conflicted rows
fail admission. The selectable SQL/Python predicates reject non-enacted rows.

## Evidence So Far

All local artifacts below are under `C:/tmp/caseops-ram05sep-20260905/`.

| Record | Result | Interpretation |
| --- | --- | --- |
| Offline compiler `--check` in `caseops-offline-test-tools:20260907-statutes-permissive` | Passed; all 1,689 rows reproduced | Real pinned documents, zero network during validation |
| `bug010-statutes-api-initial.xml` | 64 passed, 1 failed; 135.80s | The sole structured failure expected old BNSS count zero. Updated to 531 with a separate still-unverified BSA assertion; this failed report is retained. |
| `ip080-priority-postgres-shard-1-bug010-initial.xml` | 2 passed; 28.51s | Fresh migrated PostgreSQL; complete data/DTO validation, HTTP samples, source history, pending-candidate retention and idempotent upgrade |
| `api-full-bug010-full-candidate.xml` | 4,149 passed, 188 skipped; 3,152.84s | Earlier full offline run. Its snapshot predates the compiler/seed-note correction; not byte-identical final-source certification. |
| `bug010-full-web.xml` | 968 passed across 168 files; 457.71s | Both frontend and E2E TypeScript gates also passed; this is not browser acceptance. |
| `api-full-bug010-api-coverage.xml` | 4,149 passed, 188 skipped; 4,709.79s | Final frozen API/data snapshot, network-disabled Docker, six workers. |
| `bug010-api-coverage-gate.log` | All 9 file, 5 package and 2 total gates passed | Raw statement coverage 89.28% (75,024/84,029), branch 70.15% (14,888/21,224), combined 85.42%; no lowered thresholds. The historical gate labels its combined total as line coverage; this record uses the raw counts. |
| `api-full-bug010-complete-container-postgres.xml` | 186 passed, 0 skipped; 2,123.75s | Complete PostgreSQL marker selection inside Docker, separate migrated database. |
| `bug010-full-docker-02-postgres.xml` | 186 passed, 0 skipped; 3,902.77s | Complete fresh-stack PostgreSQL phase, 4,151 non-PG tests deselected. |
| `bug010-native-reranker.xml` / `bug010-windows-shim.xml` | 15 / 1 passed | Baked native ONNX in network-disabled Docker; Windows-only CLI shim on the workstation. Together with PG, these resolve all 188 offline skipped identities. |
| `bug010-full-web-coverage.xml` | 967 passed, 1 failed | Initial IP page loading poll failure under two CPUs. Retained, not erased. |
| `bug010-full-web-coverage-02.xml` | 968 passed, 0 skipped; 484.88s | Unchanged source archive, four CPUs, two workers. All frontend coverage thresholds passed. No assertion, deadline or retry relaxed. Resource contention is a supported hypothesis, not uniquely proven causation. |
| `api-full-bug010-final-statutes.xml` | 65 passed; 195.29s | Complete final source compiler, admission, history and route regression. |
| `bug010-seed-memory-02.json` | Migration and both seed executions passed, no OOM | Fresh database, exact image at 512 MiB. 23 Acts/4,336 sections; replay inserts zero. |
| `bug010-full-docker-02-browser.xml` | 270 passed, 3 failed, 6 skipped | Every failure inspected independently. All 43 source-data batches passed, covering all 1,689 records. Full replay required after test corrections. |
| `bug010-browser-focus.xml` | 11 passed; 1.4m | Both affected files replayed completely, including the previously unexecuted serial court-alias sibling and BUG-010 at 393/1280px. |
| `bug010-full-browser-replay.xml` | 272 passed, 2 failed, 5 skipped; 23.7m | Both marketing failures independently show HTTP 429. The retained exact-image web process had consumed its five-request hourly demo bucket in the prior full run. Preserve the reports and traces; no rate-limit bypass or mutation retry. A complete fresh-web-process replay is required. |
| `bug010-full-browser-replay-02.xml` | 273 passed, 1 failed, 5 skipped; 26.9m | Both demo requests passed on the same image after the owned web-process restart. The sole research failure is a proven ambiguous locator: its broad text matched both the corpus banner and the visible outcome heading, and swallowed strict-locator errors. Original trace and screenshot retained. No application source change. |
| `bug010-full-browser-replay-03.xml` | 272 passed, 2 failed, 5 skipped; 26.8m | Independent research coverage-notice assertion drift and a retained-alias false-positive followed by a real stale-version 409. All eight September 05, 23 patent/domain, 43 source-data and four mobile journeys passed. Both failures remain retained. |
| `bug010-retained-catalog-focus.xml` | 4 passed, 0 skipped; 29.8s | Complete July 02, judge-mapping and research smoke files replayed against retained records. The judge journey now proves exact created alias, refreshed displayed v1, submitted v1 and successful active v2 merge response; the research journey proves unreadable outcome and the actual independent coverage notice. |
| `bug010-full-browser-replay-04.xml` | 274 passed, 0 failed, 5 intentional skips; 27.8m | Complete clean replay on the unchanged exact Docker images. JUnit SHA256 `835d6d9011426395c14fd00cd74dc9b25caf0fdbbec3b6cc6cca0294e7217ba4`. All 1,689 source records, both BUG-010 widths, all 23 patent/domain journeys and the four mobile smoke tests passed. |
| `bug010-complete-browser-source-proof.json` | Runtime and test overlay unchanged | All 2,269 source paths reconciled; the 17 changed test/configuration paths are identical before and after this complete browser run. All five skipped identities are explicitly retained: one paid payment journey and four exact-production checks. |
| `bug010-final-data-research.xml` | 44 passed, 0 skipped; 1.1m | Exact accessible outcome heading and real committed search HTTP 200/query/array verified under the original deadline. All 1,689 source records now additionally compare identity, label, publisher, issuing body, legal status, retrieval time, link state and quarantine reason. |
| `bug010-existing-qa-statutes.xml` | 43 passed, 0 skipped; 32.2s | Production-configured local API audit: all 1,689 records, exactly four worker authentications, zero fixture or configuration writes. |
| `bug010-existing-qa-statutes-02.xml` | 43 passed, 0 skipped; 32.5s | Repeated production-configured data audit after the expanded complete metadata comparisons, still four logins and zero configuration or fixture writes. |
| `api-full-bug010-production-gate-regressions-02.xml` | 93 passed, 0 skipped; 57.14s | All deployment hardening, image-pinning and production-workflow regressions, including two added release-phase/QA-safety tests. The first attempt supplied the wrong Docker entrypoint and collected no tests; preserved as setup failure. |
| `api-full-bug010-production-gate-regressions-03.xml` | 94 passed, 0 skipped; 35.92s | Complete deployment regression modules, including the additional worker-scoped statute authentication assertion. Network-disabled Docker. |
| `api-full-bug010-final-release-regressions-02.xml` | 120 passed, 0 skipped; 79.97s | Complete program-manifest and three deployment regression modules, using the explicit current-worktree runner and guarded test-tools image. The four new test-only guards since the frozen API coverage snapshot all pass; overlapping tests are not added as new coverage. |
| `bug010-existing-qa-patent.xml` | 21 passed, 2 failed; 3.3m | Both priority failures dereferenced a null created document after a valid HTTP 200 duplicate offer. Tenant audit events independently confirm the same retained hash. Synthetic upload bytes now include the run identity, and all six upload sites assert `outcome=created` plus a non-null document. Previous fixtures and the failed report are preserved; complete replay required. |
| `bug010-existing-qa-patent-02.xml` | 23 passed, 0 skipped; 3.4m | Complete existing-account production-configured rehearsal with the earlier documents, terminal predecessors and incomplete fixtures retained. No entitlement/configuration rewrite. |
| `bug010-final-contracts-03.log` | All gates passed | Exact 211-path inventory at this checkpoint, ten changed migrations with zero findings, full Ruff and every governance/fixture contract. The original three new-test E501 failures are retained in `bug010-final-contracts-02.log`; fixed without changing runtime source. The later research test change requires refreshed final inventory. |
| `bug010-final-contracts-04.log` | All gates passed | Refreshed exact 213-path inventory after the clean browser replay and checkpoint updates; ten changed migrations, zero findings, complete Ruff and governance/fixture gates. The subsequent test-tools default-runner guard requires its own final regression and contract replay. |
| `current-d0cad5f558a4-tester/local-all-data-evidence.json` | Original 496-row import replay passed | 391 created, 97 invalid, 8 duplicate; all 10,416 source cells and 28 fields per created Matter verified. Commit/replay, tenant, active state and complete ID list checked. Zero production mutations. |

The canonical fresh verifier exited nonzero at its browser phase. It is not
reported as an originally green gate. The pending-detail test inferred
`verification_pending` from aggregate nonselectable counts and selected
Arbitration's two quarantined rows. It now discovers an explicit pending state
within a bounded catalog scan. The two BUG-010 browser tests expected an external
href, but the real UI correctly uses an authenticated, audited source-action
route. They now assert the visible guarded link, browser-cookie authorization,
HTTP 307, exact official page fragment, no-store and no-referrer headers. They
do not claim to have loaded an external PDF in a browser. Official original PDF
bytes and hashes are separately checked. Width-specific Matter codes prevent
a successful first journey from colliding with the second fixture.

The original six browser skips were one paid-payment journey, four exact-
production-only checks and one serial sibling blocked by an earlier failure.
The sibling passed in the complete focused replay; the five intentional skips
are not counted as passing acceptance. No automated test spends provider credit.

The third full replay completed with two independently inspected failures. Its
July 02 research failure has a real HTTP 200 `unreadable_filtered` response, exactly
one raw candidate, exactly one unreadable omission, zero returned results and
the visible heading `Matching documents are unreadable`. The assertion expected
supporting text that the independent stale-index coverage notice replaces.
The second failure is separately traced to the judge journey: its broad
`Curator Alias` locator matched a retained prior alias and allowed a dependent
merge to race the new catalog refresh. The alias POST succeeded; the catalog
returned destination version 1, while the premature merge received HTTP 409
`Judge identity changed; reload and retry.` The stale-write fence is retained.
The captured merge request submitted destination version 0. The corrected
complete focused replay passed without any application change, automatic
mutation retry, deleted predecessor, raised timeout or weaker concurrency token.
Both complete traces and `bug010-judge-merge-conflict-network.jsonl` remain
evidence; no failing full run is converted to green by a targeted replay.

Runtime identity: dirty-source fingerprint
`d0cad5f558a4107ffaee3e76f6ff7f25ed2b74487239e069e8bb7e2c7894bd0b`;
serving revision `d0cad5f558a4107ffaee3e76f6ff7f25ed2b7448` is not a Git commit.
Exact runnable API image:
`sha256:345c696732cad720138bce7a29bf2abb123527fb72cd612710627fdc50835ee6`;
web image:
`sha256:05ac9888dbc89fdcc6326ff5e4f52b635d06d55e236a37230e584ae9b503d08e`.
The isolated project is `caseops-acceptance-d0cad5f558a4`, API 37065, proxy
37066, web 37067, PG 37068. The runtime overlay guard compares all 2,269 paths
against the frozen source and permits only enumerated browser/configuration and
documentation changes. Application code, seeds and dependencies remain identical.

Migration head is `20260907_0002` (194 migrations). Normal, 512 MiB and
post-rehearsal index checks found no missing, invalid, mismatched or uncovered
FK indexes. A cumulative Matter sequential-scan warning is retained; this is
not arbitrary production-load certification. After destructive rehearsal the
exact API image restored 23 Acts and 4,336 sections before the browser gate.
Initial Docker address-pool exhaustion and an initial seed command using a
non-runnable image identifier remain setup failures, not product evidence.
An owned explicit subnet was allocated without global prune or deleting older
user/test data. The initial empty seed database was retained.

Security evidence: current lockfile npm audit reports zero vulnerabilities;
strict runtime and compiler Python OSV audits report zero vulnerabilities and
zero skipped packages. The network-disabled Gitleaks directory scan returned
22 findings, all reconciled to unchanged HEAD fixture/build identifiers and
zero newly introduced findings. This is not a raw scanner exit-zero claim and
does not replace canonical CI scanning. No secret suppression was added.

License-inventory limitation: the existing root-workspace license-checker
command returns an empty inventory despite hoisted runtime dependencies. A
fresh isolated install produced 151 metadata rows (including two private
workspace roots). Unchanged fontsource OFL-1.1, nodemailer MIT-0 and sharp
libvips LGPL-3.0-containing metadata sit outside that old command's allowlist.
No dependency or license waiver was introduced by BUG-010. This pre-existing
inventory/allowlist governance gap remains explicit, not a clean license-scan
claim. The source compiler's rejected AGPL tool was replaced before release.

Production acceptance is extended with the same 23 domain/patent journeys.
Local mode still uses isolated bootstrap fixtures. Existing-QA mode requires
the exact API/web release SHA, authenticates only the two dedicated QA tenants,
reads their governed configuration without rewriting entitlements, and uses
unique retained fixture identities. Authenticated production screenshots are
disabled. Mutating phases are serial; all 43 read-only statute batches use four
bounded readers after mutations. Older serving releases never execute newer
test code merely because the workflow graph came from a newer branch.
The latest pre-deploy production inspection found two successful maintenance
cadences and no active incident. Normal scheduler state remains enabled; the
incident-only scheduler-hold option is not the default for this scoped release.
After production QA stops, require clean maintenance and a second clean cadence
without suppressing tenant blockers or widening the 300-second SLO.

The frontend runner initially failed before tests because its Alpine image has
`sh`/BusyBox, not bash/GNU tar. The corrected runner uses supported commands.
These are setup failures, not product regressions or passing tests.

A later supplemental command mistakenly used the test-tools base image's
inherited runner. It returned 119 passing tests, but selected another worktree's
snapshot owner and generic output names. It is excluded from release evidence.
Its result is preserved as `bug010-wrong-entrypoint-judgment-api-full.xml`, with
the corresponding snapshot/status files. That attempt overwrote the three
generic runner output paths; none is used for this release certificate, whose
authoritative reports have unique names. The reusable test-tools Dockerfile now
rejects implicit execution before a snapshot starts. The rebuilt guarded image
refused the default command with exit 1 and the expected recovery message under
`--network none`; `bug010-test-tools-default-guard.json` records that result.
The explicit current-worktree runner and unique report label are mandatory for
the replacement supplemental test run. This test-only image is not an API, web
or worker production build, and no application/seed/dependency source changed.
The corrected run passed all 120 selected identities. Its unique archive and
JUnit are `source-archive-bug010-final-release-regressions-02.sha256` and
`api-full-bug010-final-release-regressions-02.xml`. The guarded test-tools image
is `sha256:d54be296ab3c2283b2e15bf5a6b9dfc6b50adaf52d2b692f2bb30128d3a33a0d`.

Six rendered source pages were inspected: Arbitration 18, Companies 213, CPC 55,
BNSS 121, BNS 16 and Supreme Court treatment page 62. This is explicit boundary
and source-discrepancy inspection, not a claim that a lawyer manually reviewed
every provision for current applicability.

## Remaining Release Gates

### September 08 Post-Review Local Evidence

The P1 review on PR #458 correctly identified creation replays that returned
historical patent records before checking whether the original mutation target
was still operational. Four complete HTTP failures reproduced party replay
after family/application closure and priority replay after child/parent closure
(`api-full-bug010-terminal-replay-repro.xml`). All returned 201 instead of 404;
these are actual product reproductions, unlike the independent CI setup errors.

Both services now revalidate the original source and locked mutation targets
before returning a saved result. An unchanged historical priority parent remains
a read-only reference for correction replay; its child must still be operational.
Retained GETs, sources, immutable relationships and audit rows stay readable and
unchanged. PostgreSQL additionally proves a different actor's closure wins over
an in-flight successful-key replay without restoring or generating child rows.

| Evidence | Current result |
| --- | --- |
| `bug010-terminal-candidate.json` | Fresh API/web/worker build, 194 migrations, normal and 512 MiB index checks passed; no missing or invalid indexes. |
| `bug010-terminal-frozen-file-hashes.json` | 2,271 source paths frozen; every one of the 680 API source/migration files matches the running API image. |
| `bug010-terminal-postgres-03/postgres-shard-{1..4}.{json,xml}` | 192 passed, zero skipped. All four complete inventories and actual JUnit identities reconcile exactly; each independent database started empty. Shard durations: 382.45, 416.75, 450.56 and 360.77 seconds. |
| `bug010-terminal-source.tar` | All four PostgreSQL shards and complete API coverage use archive SHA256 `af96c4119e1a56065df0bdfdabe5e88fa6c8631d55e33fc8761b2662f745d51c`. |
| `api-full-bug010-terminal-api-focused.xml` | 112 passed, zero skipped; complete party, priority, shard-reconciliation and deploy-hardening modules. |
| `bug010-terminal-patent-focused-02.xml` | Ten complete dated browser journeys passed at 393/768/1280px, including actual UI-command replay, terminal rejection, retained histories and source downloads. |
| `current-19a33de2b82f-tester/local-all-data-evidence.json` | Original 496 rows replayed: 391 created, 97 invalid, eight duplicate; all 10,416 original cells and 28 persisted fields per created Matter checked. Zero production mutations. |
| `bug010-terminal-full-browser.xml` | Complete 279-test selection: 274 passed, zero failed, five intentional skips; 29.7 minutes. All five skipped identities match the earlier complete inventory exactly, not merely its count. All 1,689 source records and the mobile/desktop named-Act attachment journeys passed. |
| `bug010-terminal-browser-source-{before,after}.json` | All 2,271 paths reconcile. Runtime files remain frozen; the exact source-scope test overlay is unchanged before and after the complete run. |
| `bug010-terminal-web-reuse-proof.json` | All 449 frontend, test, dependency and configuration paths match the previous 968-test complete coverage snapshot. No changed frontend path is claimed covered by old bytes. |
| `bug010-terminal-contracts-03.log` | All 216 native/Docker changed paths reconciled; ten changed migrations with zero findings; statute compiler, governance, offline AI-safety and canonical Ruff checks passed. Final documentation changes require one more contract replay. |
| `bug010-existing-qa-patent-terminal.xml` | All 23 production-configured patent/domain journeys passed on the rebuilt local runtime, zero skips; 4.5 minutes. Prior terminal and document fixtures remain retained. |
| `bug010-existing-qa-statutes-terminal.xml` | All 43 production-configured source batches passed, zero skips; 42.9 seconds. Exactly four worker authentications, every one of 1,689 records, zero configuration or fixture writes. |
| `bug010-terminal-post-browser-index-health.log` | Schema `20260907_0002`; no missing, invalid, mismatched or uncovered FK indexes, no sequential-scan warnings in this current local report. |
| `api-full-bug010-terminal-api-coverage.xml` | Complete current snapshot: 4,173 passed, zero failed, 194 skipped; 5,129.84 seconds. All 4,367 collected identities are reconciled, and every skipped identity has an exact passing PostgreSQL/native/Windows supplement. |
| `bug010-terminal-api-coverage-gate.log` | All nine per-file, five package and two total gates passed. Statements 75,022/84,032 (89.2779%); branches 14,889/21,226 (70.1451%); combined 85.4196%. No threshold was lowered. |
| `bug010-terminal-contracts-04.log` | Final 216-path native/Docker candidate inventory and all governance/ownership/guide/scheduler contracts passed after the complete-suite checkpoint updates. Ten changed migrations have zero findings; compiler reproduces all 1,689 rows; all eight offline AI-safety cases and canonical Ruff pass. Legal fixture approval remains zero. |

The exact API image seeded 23 Acts and 4,336 sections before browser testing.
Complete API coverage and both production-shaped local rehearsals pass.
The full browser run is complete, not a targeted
substitute. The BUG-010 Arbitration mobile and Companies desktop screenshots
were inspected: text, source metadata and guarded source controls are readable.
The long publisher footnotes remain explicitly labelled shared page context.
The API run retained four workers and eight GiB memory. Its CPU allowance was
increased from four to eight only after PostgreSQL shards finished; no timeout,
assertion or test selection changed.

The previous PR CI run `34150026329` contains two independent failures:

- Seven PostgreSQL setup errors queried `forum_catalog_aliases` before its base
  migration fixture ran; the same monolithic job exhausted its twelve-minute
  budget. Every error was inspected. Explicit fixture dependency and four
  disjoint shards now pass locally without `TEST_PREPARE_POSTGRES`. The CI
  aggregate requires every successful artifact before browser acceptance; no
  timeout was raised and no marked test was excluded.
- Its browser suite completed 271 passes, seven skips and one failed source-scope
  assertion. Only `created_at` and `finalized_at` differed by SQLite's removed
  UTC suffix between the creation response and reloaded record. The dated test
  now captures a persisted GET before the patent operation and compares the
  entire retained particulars after it, including both timestamps. No timestamp
  field is omitted or normalized away. The exact test-only overlay is recorded
  in `bug010-terminal-browser-source-before.json` and passed in the ten-journey
  run on the unchanged application image.

All setup attempts remain retained: the PowerShell 5 native-stderr wrappers
collected no successful tests; their four owned orphan runners were stopped
and their isolated database containers retained. The corrected runner requires
PowerShell 7, preserves the attempt label and validates complete inventories.
An initial focused API attempt had 111 passes and one missing-test-import
`NameError`; all 112 pass after the import repair. The initial focused browser
launch parsed an unquoted reporter argument incorrectly and collected no tests;
its correctly quoted replacement passed all ten. None is counted as a product
reproduction or silently erased.

The first contract replay used app-relative paths with a repository-root tar
operation and failed before validation. The second passed the full governance
inventory but invoked the compiler outside its pinned tool environment. Both
logs are retained. The third used explicit root paths and the baked compiler
interpreter and passed all gates. An exploratory whole-directory Ruff command
also found 133 legacy migration lint findings outside CI's `src tests` selector;
these were not silently repaired or represented as a clean migration lint scan.

CodeQL also emitted maintainability notes for explicit catalog re-exports and
function-local reciprocal imports. The catalog export is consumed by the meta
and IP routes. The evidence reader imports the existing machine verifier lazily;
the ingest path calls the independent domain evaluator, not that reader. Patent
correction lazily calls the priority validator after both modules are loaded.
These notes remain recorded, not dismissed as completed refactors; the scoped
repair preserves public imports and canonical ownership. CodeQL's prior run
passed, but the final follow-up still requires its own green CI.

**Post-review release hold:** PR review reproduced four terminal creation-replay
gaps in party/priority writes. The two application services now revalidate locked
mutation targets before returning retained results. The earlier complete runtime
certificate below does not certify these changed bytes; fresh local acceptance
and exact-production verification remain required. Dated browser journeys now
capture and replay actual UI commands after closure. The expanded PostgreSQL CI
run also exposed seven missing-base-catalog fixture errors and its twelve-minute
job limit. Those results are retained in `bug010-pr-ci-postgres-02.log`; they are
not seven product reproductions. Explicit fixture migration dependencies and
four isolated, exact-identity-reconciled shards require their own local proof.

The first PR #458 CI run (`34149626146`) exposed an additional release-tooling
defect: the committed-diff governance CLI decoded unrelated PDF evidence as
UTF-8. The dirty-source evaluator had not exercised that entry point. Both new
regressions reproduced it in network-disabled local Docker. The corrected
reader only consumes governed source and still rejects unreadable governed
files with a bounded diagnostic; provider/map and migration-marker checks
remain mandatory. All 62 governance, migration-preflight and manifest tests
passed, followed by the actual committed-diff governance CLI, all ten changed
migrations and Ruff (`bug010-committed-gate-fixed.log`). Two new tests supplement,
not replace or inflate, the earlier complete suite. No application, seed or
dependency source changed. The first failed CI remains retained.

- The complete 279-test Docker browser selection is reconciled: 274 passed,
  zero failed, five explicit skips. Prior failed runs remain historical evidence,
  not an originally clean canonical-verifier certificate.
- The production-configured local rehearsals are complete: 23 domain/patent
  journeys and 43 source-data batches with four bounded readers. Exact deployed
  execution remains a separate release requirement.
- Final dirty-source contract replay `bug010-final-contracts-05.log` passed:
  all 213 paths, ten changed migrations with no findings, governance and full
  Ruff. Formatting checks passed. Runtime and the 17 browser/configuration
  overlay hashes were identical before and after complete browser acceptance;
  the later test-tools-only guard has its separate 120-test passing report.
- Commit only after local acceptance; publish canonical main, require green CI,
  deploy using exact current-main release boundaries and rerun production E2E.
- Preserve this pre-release record and finalize an exact-release attestation
  and Downloads workbook with actual commit/image/production evidence. Check
  projection maintenance after QA mutations stop and again on a clean cadence.

Overall BUG-010 remains broader than these five named Act journeys: 17 other
Acts still have zero verified selectable provisions, and Constitution retains
only Article 14. A successful scoped deployment may establish the named-Act
fix without closing catalog-wide content coverage. Do not mark the overall
ticket Properly fixed, the whole patent program complete, or retrieval/legal
quality 4.5+/5 from these tests. Legal and research fixture packs still contain
zero independently approved cases.
