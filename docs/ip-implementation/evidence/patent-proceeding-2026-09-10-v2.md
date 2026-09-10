# Patent Pre-Grant Proceeding Handoff v2

Scope: **UJ-39-EXC-03, concrete IP India pre-grant opposition journey**.
Status: concrete product journey implemented and locally verified; frozen v2
integration checkpoint. No further product changes are included after this freeze.
Program status: IPLF-079A/B and IPLF-080A/B remain partial, release NO-GO.
No commit, push, deployment, production mutation or paid API call was performed.

## Identity And Ownership

- Worktree: `C:/Projects/CaseOps/caseops/.worktrees/codex-patent-closure-20260909`.
- Branch/base: `codex/patent-closure-20260909` /
  `5145fb3a4b51b26af116220ff10a7389bde6324d`.
- The main acceptance candidate and other agents' worktrees were not edited.
  No shared canonical ledger, program manifest, generated OpenAPI, deployment
  configuration or D-owned implementation was edited.
- The previous 28-file handoff is immutable. Its manifest SHA-256 remains
  `5e68835d853562953105f26cd1d7df0e016f0d0eabf538c5f9513d75652c9a2c`.
  Its report and all earlier failed/interrupted evidence remain retained.
- Migration `20260909_0004` remains the only reserved migration used here.
  Its tested isolated predecessor remains `20260908_0001`. The parent's integrated
  `20260909_0003_legal_hold_release_requests.py` was inspected read-only and has
  revision `20260909_0003`, following `20260909_0002`. At integration the parent
  must change 0004's predecessor to `20260909_0003` and rerun the migration
  rehearsal on that combined chain. This isolated checkpoint does not claim the
  parent's reported 289 backend / 1,012 frontend passes as its own evidence.
- Current source contract: PAT-2026-09-10.2, with the versioned pre-grant child
  PAT-PGO-2026-09-10.1. Patent workflow/automation promotion remains fail-closed.

## Delivered Product

- Independent canonical `IpProceeding` identity, typed patent/application link,
  represented side, source-time counterparty snapshot and canonical party row.
  No trademark application FK, particulars, stage template or invented number.
- Explicit pending allocation or source-published number, later allocation into
  `IpIdentifier` using the typed `patent_pre_grant_opposition` kind, duplicate
  protection and immutable assigned-number behavior. Trademark opposition numbers
  remain a separate domain and do not disclose a patent through legacy duplicate
  suggestions.
- Notice, response preparation, exact-manifest response filed, hearing and
  decision/withdrawal with outcome. Normal and exceptional stages are distinct.
  Backdated/exceptional previews require the same acknowledgements at commit.
- Every stage retains the application/lifecycle version, immutable document
  version/hash, dates, actor, reason and response manifest. It never changes the
  application prosecution phase, deadlines or sibling applications.
- Fresh canonical company/access and source/docket locking, current ACL checks,
  optimistic versions and actor-scoped idempotency. Parent closure wins queued
  creation/transition/replay. An older-lifecycle proceeding cannot resurrect
  when its application reopens.
- Bounded lists with snapshot cursors, 100 retained identities per application,
  100 sealed stage rows per proceeding, batched source/manifest reads and an
  explicit history-integrity check. No truncated history is called complete.
- Actual Proceedings tab, intake and stage forms, exact source/manifest pickers,
  review acknowledgements, retained errors/drafts, immutable history and downloads.
  Initial discovery is authoritative; successful mutations cancel stale reads.

## Verification And Reconciliation

All new results live in `.tmp/patent-proceeding-20260910` in this worktree.
Each pytest run used a fresh result name, `-n 0 -p tests.retained_results` and
`CASEOPS_TEST_RESULT_JOURNAL`, retaining collection and setup/call/teardown plus
completion. Full failure detail is preserved, never replaced by progress dots.

| Attempt | Result and reconciliation |
| --- | --- |
| `proceeding-01` | 8 tests: 2 passes, 6 inspected failures. Four failures were sibling fixture requests missing mandatory family concurrency tokens; two used an incorrect lifecycle URL. These did not reach the intended assertions and were not product-bug reproductions. Every failed identity completed successfully in replacement runs. |
| `proceeding-02` | 70 passed, zero failed/error/skipped, 132.524s. Corrected fixtures, complete proceeding HTTP flows, deterministic PostgreSQL races, history boundary and fresh migration rehearsal. |
| `proceeding-03` | 123 passed, zero failed/error/skipped, 241.323s. Broader focused proceeding/prosecution/contracts/catalogue inventory, including both 100-row bounds and source-preserving migration proof. |
| `proceeding-04` | 43 passed, zero failed/error/skipped, 145.332s. Final canonical-counterparty addition and all proceeding/PostgreSQL/catalogue cases. These are a subset of the 123 identities, not 43 additional tests. |
| `proceeding-05` | Two complete, inspected product-bug reproductions, SQLite and PostgreSQL. A successfully created trademark opposition incorrectly blocked a patent opposition with the same source number (409). Reusing the generic `opposition` identifier kind caused the cross-domain collision. The typed patent kind fixes both admission and legacy duplicate-candidate isolation; no trademark code was changed. |
| `proceeding-06` | Final API candidate: 47 passed, zero failed/error/skipped, 146.625s; 141 passing setup/call/teardown phases and exit-0 completion. Includes all 20 proceeding identities (13 PostgreSQL, seven SQLite), 25 catalogue tests and two legacy record workflows. Both failing run-05 identities now pass, with a second patent duplicate still rejected and legacy trademark suggestions excluding the patent. |
| `proceeding-format-02` | Nine retained line-length findings in SQL constraints/error copy; inspected and corrected without semantic changes. `proceeding-format-03` and final `proceeding-format-04` completed with Ruff clean. |
| `proceeding-web-01` | TypeScript passed; all 24 frontend tests passed across four files. Expected mocked rejection logs are paired with passing negative-path assertions, not unexamined failures. Fresh Next build completed and served health checks. |
| `proceeding-browser-01` | Stopped at the root TypeScript gate with two inspected matcher errors (`toHaveTextContent` instead of Playwright `toHaveText`). No browser test ran. Failed output retained; only the dated spec was corrected. |
| `proceeding-browser-02` | All three dated journeys passed at 393, 768 and 1280 pixels, one worker and zero retries. Screenshots inspected at all three widths. Complete initial candidate result, not the final identifier-kind fix. |
| `proceeding-browser-03` | Final API candidate: all three dated journeys passed, zero failed/error/skipped, 189.989s summed test time, container exit 0. Widths 393/768/1280 completed in 60.502/49.793/79.694s, one worker, zero retries. Root E2E TypeScript passed; final screenshots inspected at all three widths. |

There are 127 distinct passing backend identities across completed runs 02/03/04/06,
not the sum of their pass counts. All eight earlier failed phases from runs 01/05
have complete passing replacements. Run 06 is the final changed-service gate;
unchanged prosecution and migration coverage remains explicitly attributed to 03.

The earlier `patent-pg-03` remains an interrupted historical run, not a success.
Its full reconciliation and replacement inventory remain in the immutable
`patent-resume-2026-09-10.md` and corresponding JSON handoff.

PostgreSQL tests used a separately migrated, connection-disabled empty template
for HTTP fixtures; the migration roundtrip used an independently fresh database.
The migration now proves all five evidence tables, six immutable/sealed triggers,
columns, indexes and constraints, empty downgrade/upgrade equality and repeated
refused downgrade preserving both a manifest and a proceeding.

The final API source is `proceeding-06-source.tar`, independently archived with its
Git-selected root fixtures and per-file hashes. API 02 and browser 03 consume it
without runtime product overlays. The fresh Next build uses
`proceeding-candidate-01-source.tar`; the checkpoint generator proves every
`apps/web/` and root package/lockfile input is byte-identical in the final API
archive. This is an explicitly composed runtime, not a claim that every process
used one archive. All 455 frontend build inputs matched. The browser runner records
its spec and runner hashes separately.
The manifest generator checks every owned runtime file against the final API
archive, and every frozen full-file copy against its manifest. Final reports and
reconciliation artifacts are generated afterward and are not runtime code.

Resource isolation: focused PostgreSQL runner 0.75 CPU / 1536 MiB plus PostgreSQL
0.25 CPU / 512 MiB; stopped before the standalone 1 CPU / 2 GiB frontend/build.
Final backend stage: idle web 0.15 CPU / 384 MiB, PostgreSQL 0.25 / 512 MiB,
focused runner 0.60 / 1152 MiB, total 1 CPU / 2 GiB.
Browser stage: web 0.15 CPU / 384 MiB, PostgreSQL 0.10 / 256 MiB, API 0.30 /
640 MiB, browser 0.45 / 768 MiB, total 1 CPU / 2 GiB. All share only an owned
network-none loopback namespace, no published ports or external provider traffic.
No full API gate or global cleanup was run by this track.
Only this increment's owned API/web/PostgreSQL processes were stopped after the
gates finished; their containers, database rows and evidence remain retained.

The browser journey creates and operates the real Proceedings tab through notice,
response preparation, exact-manifest response filing, hearing and decision; then
proves source-byte equality, unchanged sibling/prosecution state, closure,
reopening without old-proceeding resurrection, a second closure and retained
read-only history after reload. Breakpoint-edge control bounds are asserted at
639/640/641, 767/768/769 and 1023/1024/1025 pixels. The shared offline banner is
expected in the network-disabled harness, not mutation failure feedback; successful
workspace outcomes also assert no in-workspace error alerts. PostgreSQL separately
proves current ACL revocation and deterministic locked lifecycle races.

## Requirement Status

These are whole-requirement statuses; a passing concrete journey does not silently
narrow the program. Existing evidence is not relabeled as new verification.

| Requirement | Status after this increment / remaining gap |
| --- | --- |
| IPLF-079A | Catalogue foundation retained and tested; integrated release/canonical publication remains parent-owned. |
| IPLF-079B | Partial. Exact contract/source checks updated; full non-trademark workflow qualification is not delivered. |
| IPLF-080A | Existing typed patent foundation preserved. No new integration/deployment claim. |
| IPLF-080B | Concrete pre-grant product journey implemented. Other prosecution, obligation, title and acceptance journeys remain. |
| IP-SCOPE-01 | Partial. Intake and complete workflow promotion remain distinct and fail-closed. |
| IP-SCOPE-02 | Partial. New patent-only proceeding stages/identity; other domain-specific proceeding and obligation semantics remain. |
| IP-SCOPE-03 | Partial. Canonical proceeding/party/identifier/document/access/lifecycle/audit owners reused. Task/deadline/instruction/cost/title adapters remain. |
| IP-SCOPE-04 | Partial. IN/IP India proceeding admission enforced; changed office scope rejects. Foreign rule/workflow execution remains unsupported. |
| IP-SCOPE-05 | Partial. Concrete normal/exceptional/stale/ACL/closure/race/bounds/migration coverage added. Consolidated release and all other journeys remain. |
| IP-SCOPE-06 | Partial. Sixth patent source-fixture check added; no guessed legal rules or deadline changes. Operative source packs and executable legal boundary fixtures remain. |
| IP-SCOPE-07 | Partial. Independent proceeding/application/sibling identity preserved. Cross-right interests and consolidated reporting remain. |
| IP-SCOPE-08 | Partial. Current source ACL and tenant/application isolation exercised. Full saved AI/portal/export/delivery and browser grant-revocation matrix remains integrated work. |
| IP-SCOPE-09 | Partial. Authoritative machine catalogue preserved; complete public/packaging/outage/recovery browser acceptance remains. |
| IP-SCOPE-10 | Partial. Versioned child PRD, hash and implementation fence retained. No beta/GA/automation promotion or exact-release certification. |
| PAT-01 | Partial. Existing anchors and sibling identities preserved; full family reporting, maintenance and title chains remain. |
| PAT-02 | Not implemented by this increment. Patent legal rule selection/calculation and legal fixtures remain separate dependencies. |
| PAT-03 | Partial overall; concrete pre-grant opposition now implemented. Post-grant/revocation/appeal/compulsory licence/maintenance/title/filing-acceptance adapters remain. |
| PAT-04 | Partial overall. Exact response manifest and immutable proceeding evidence retained; full granted-set semantic and byte-version scale matrix remains. |

## Nineteen-Path Reconciliation

| Atomic path | Current status / remaining outcome |
| --- | --- |
| UJ-29-NORMAL | Existing typed intake/family facts retained; complete combined family report and release journey remain. |
| UJ-29-EXC-01 | Dedicated inventorship/title-conflict review outcome remains product work. |
| UJ-29-EXC-02 | Independent application/relationship identity retained; this increment proves sibling unchanged. |
| UJ-29-EXC-03 | Unsupported rule execution remains fail-closed, not implemented. |
| UJ-39-NORMAL | Manual prosecution retained; new pre-grant branch added, complete instruction/deadline/office acceptance chain remains. |
| UJ-39-EXC-01 | Existing complete admitted-event sibling regression passes; new proceeding also preserves sibling and prosecution phase. |
| UJ-39-EXC-02 | Immutable filed/response manifest and history passed; separate granted-set semantics remain. |
| UJ-39-EXC-03 | New concrete pre-grant journey: independent identity, side, office, source, stages, response manifest, outcome, audit and terminal history. Other proceeding variants remain explicit. |
| UJ-39-EXC-04 | Source ambiguity pending-confirmation workflow remains product work; fail-closed rejection is not that workflow. |
| UJ-40-NORMAL | Annuity/working proposal through instruction/funding/filing/acceptance and next-period idempotence remain. |
| UJ-40-EXC-01 | Patent quote/rule/entity invalidation and current cost-reference adapters remain. |
| UJ-40-EXC-02 | Paid/filed versus accepted obligation state and receipt reconciliation remain. |
| UJ-40-EXC-03 | Separate lapse/grace/restoration obligation review and legal fixtures remain. |
| UJ-40-EXC-04 | Applicable working form and not-applicable/no-working declaration remain. |
| UJ-60-NORMAL | Catalogue foundation tested; complete non-trademark launch qualification remains. |
| UJ-60-EXC-01 | Source-unavailable automation fence tested; full browser recovery journey remains. |
| UJ-60-EXC-02 | Intake is not promoted to complete patent management; catalogue tests pass. |
| UJ-60-EXC-03 | Unsupported jurisdiction/office evidence denied; complete cross-domain browser matrix remains. |
| UJ-60-EXC-04 | Stale/tampered machine evidence revoked without source deletion; integrated capability-downgrade journey remains. |

Shared UJ-61 title/licensing, original-source patent imports, export/reporting,
large-volume family/document-byte performance and the full legacy trademark/Madrid
suite remain integration or product work. Source absence does not close these gaps.

## Integration Package

`patent-proceeding-handoff.ps1` produces create-new-only `handoff-v2-*` JSON and
a shared-file delta patch in `.tmp/patent-proceeding-20260910`. The exact manifest
lists 44 owned files, byte lengths, SHA-256, prior hashes and ownership scope.
The frozen `handoff-v2-owned-files.tar` contains the 41 fully owned files, not the
three shared files. Every extracted copy is checked against the file manifest.
`handoff-v2-checkpoint.json` hashes the archive, file manifest, patches and retained
evidence indexes. The original evidence artifacts remain alongside their indexes.

Do not copy the three shared files wholesale: `db/models.py`, `routes/ip_patents.py`
and `PatentApplicationWorkspace.tsx`. The old immutable owned-hunks patch remains
in the previous handoff and is copied byte-identically into this package as
`handoff-v2-shared-baseline.patch`. Apply only missing baseline hunks, then
`handoff-v2-shared-delta.patch`. The new delta is computed against hash-verified
previous source, and must pass reverse-apply validation against current files.
The parent owns chain integration, generated API/schema/governance artifacts,
September 10 bugs, full gates, canonical branch publication and deployment.
