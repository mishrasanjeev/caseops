# Local Patent Parties Acceptance

Owner: Codex. Release verdict: **NO-GO**. No commit, push, PR merge, cloud
mutation or production deployment is claimed by this checkpoint.

## Scope

UJ-29 / PAT-01 / IPLF-080-FAMILY / IPLF-080-COMPAT; modules M02, M08, M13 and
M14. IPLF-080A/B remain partially implemented as whole program slices. Family,
application and sourced-party intake now have local browser proof. Priorities,
the graph, prosecution, proceedings, claim packages, maintenance/title, imports,
reports and full release activation are not delivered by this checkpoint.

The existing IpPartyAndRole owns inventor, applicant, proprietor, agent and
licensee facts. Its one-to-one patent detail retains address/country, effective
dates, exact source version/hash, actor, reason, parent versions, collection
sequence and append-only supersession. Existing docket, asset, document,
authorization, lifecycle, audit and idempotency owners remain authoritative.
No party fact grants access, establishes legal title or propagates to a sibling.

## Exact Candidate

- Base commit: `6a85cd5025101fd453bdc9b8472e963d16ba708a`.
- Dirty-source fingerprint:
  `c3514bd634e395fb7a62fa5ea302525f8defbacee2c856b929beb4e48ab534c3`.
- Runtime identity: `c3514bd634e395fb7a62fa5ea302525f8defbace`, not a Git commit.
- Docker project: `caseops-acceptance-c3514bd634e3`.
- API: `http://127.0.0.1:31655`; web: `http://127.0.0.1:31657`.
- Test-owned loopback proxy: port 31656, stopped after each browser run. After
  acceptance, a separate hidden local-tester proxy was started on that free port.
- Schema: `20260907_0001`.
- API image: `sha256:c91096d0eceb55beb23ea53ffeee2348e25b0fd86ab8543adaa27974c562022d`.
- Web image: `sha256:8380b8408e3acc400aa646a9f1a199c2a7963112602a7f6feab136fd39a4b766`.

Product source remained frozen through the fresh build and original verifier.
Later changes are test navigation, the frontend initial-load poll, explicit URLs
in existing API assertions, migration rationale comments, and evidence/documentation. They are not
retroactively attributed to the original dirty-source fingerprint. The corrected
browser replay independently verifies the exact unchanged image IDs, API/web
runtime identities, healthy API, running worker and empty proxy-error log before
and after its complete journeys. The failed original verifier remains failed.

All artifact names below are under `C:/tmp/caseops-ram05sep-20260905/`.

## Verification

| Check | Result | Evidence / limits |
| --- | --- | --- |
| Fresh API/web builds and migrations | Passed | `ip080-parties-fresh-docker.log`; current-source images, no stale Next build |
| Fresh-stack complete PostgreSQL selection | 168 passed, zero skipped; 4,469.19s | Same log; 4,118 non-PG tests deselected, not skipped acceptance |
| Complete in-container PostgreSQL selection | 168 passed, zero skipped; 2,473.89s | `api-full-ip080-parties-full-postgres.xml`; isolated owned database, Docker network disabled |
| Full and 512 MiB index checks | Passed | No missing, invalid, mismatched or uncovered FK indexes; post-rehearsal cumulative Matter scan warning retained |
| Original complete offline API | 4,115 passed, one failed, 170 skipped; 7,383.31s | `api-full-ip080-parties-full-api.xml`; failure is the route-reference inventory described below |
| Corrected coverage and patent API replay | 121 passed, zero skipped; 235.73s | `api-full-ip080-parties-api-coverage-corrected.xml`; complete affected modules and unchanged inventory detector |
| API skip reconciliation | 170/170 resolved by exact class/name | 168 PG nodes, one native-reranker node, one Windows-only node; `sep07-current-metrics.json` |
| Collected API inventory | 4,286/4,286 identities have passing evidence | Original passes plus explicit supplements/replay, not additive overlapping totals or every possible PRD flow |
| Complete offline frontend | 899 passed in 167 files, zero skipped; 1,696.86s | `ip080-parties-full-web-corrected.xml`; one test-only loading-poll correction, integrated copy verified after LF normalization |
| TypeScript / changed-test Ruff | Passed | Complete `tsc --noEmit --incremental false`; targeted Ruff, no timeout or assertion suppression |
| Native reranker | 15 passed, zero skipped; 17.85s | `api-full-ip080-parties-native-reranker.xml`; baked offline ONNX, not production Voyage quality acceptance |
| Windows shim | One passed; 0.76s | `ip080-parties-windows-shim.xml`; host-only platform test, cloud subprocess mocked |
| Original fresh browser selection | Seven passed, six failed, zero skipped | `ip080-parties-fresh-browser.xml`; complete failure artifacts retained |
| Corrected complete patent selection | 13 passed, zero skipped; 13.7m | `ip080-parties-browser-corrected.xml`; same product images, one worker, zero retries |
| Complete current desktop browser regression | 222 passed, one failed, five skipped; 45.1m | `ip080-parties-all-browser.xml`; BUG-010 remains a release blocker, one worker and zero retries |
| Complete separate mobile project | Four passed, zero skipped; 1.2m | `ip080-parties-all-mobile.xml`; Pixel 5 touch emulation on the same exact product images |
| npm advisory audit | Zero vulnerabilities, all severities | `ip080-parties-npm-audit.json`; npm 11.6.2, public advisory lookup only |
| Python runtime advisory audit | 136 dependencies, zero findings, zero skipped | `ip080-parties-python-audit.json`; pip-audit 2.10.1, strict OSV lookup, complete frozen production/OCR dependency export |
| Offline release-contract checks / full Ruff | Passed with the limitations below | `ip080-release-contract-gates.log`; current source snapshot in network-disabled Docker |
| Proxy and QA-runner regressions | Nine passed, zero skipped | `ip080-local-runner-tests.log`; offline Docker, complete mutation responses, both cancellation phases and literal argument boundaries |
| Actual dirty migration / governance changes | Passed for nine migrations in 157 dirty paths | `ip080-dirty-release-contracts-final.json`; explicit workstation Git list, not the empty committed diff |
| Comment-only migration equivalence | Four executable ASTs unchanged | `ip080-migration-comment-equivalence.json`; comparison with the exact tested API image |

The npm audit covers lockfile SHA256
`fd10115d54e45819da64d7388bd673d390f3c45197bda3ca48830cecd387563c`.
The Python export matches the production Dockerfile's frozen no-dev/OCR path;
uv.lock SHA256 is `42d0f3be5745b25ad7c43c014fd79d6ac2f387bed680c593268b52363d1f5ff4`.
No dependency version was changed or vulnerability ignored. These advisory
audits do not replace license/secret/SAST gates or current canonical CI.
These runs do not establish complete backend/frontend coverage thresholds.

Contract validation is not legal or production acceptance. The pleading pack
reports eight fixtures, zero approved and `authoritative_ready: false`; the
research pack reports three fixtures, zero approved and no execution. The
offline AI-safety pack passes eight cases across eight required surfaces; it is
not live model-quality proof. Migration graph validation reports a single head
and 870 advisory historical risks across 193 files. Its ordinary change command
sees only committed differences and reports no changed migrations on this dirty
candidate, so that command alone does not satisfy the change gate.
The explicit dirty-source run found missing rationale on two new empty-table
migrations and missing governance markers on two previously changed index-only
migrations. The reviewed annotations now describe their actual empty-table
indexing and guarded retained-data refusal, already exercised by the complete
PostgreSQL suite. No migration operation changed: all four executable ASTs match
the tested API image exactly. The final explicit nine-migration/governance gate
passes. Both the failed Linux file-discovery diagnostic and the original
findings are retained; no finding was hidden by excluding a changed migration.

## Failures And Corrections

1. A real different-actor PostgreSQL party/closure deadlock initially produced
   nine passes and one failure. An inserted idempotency claim holds an implicit
   Company KEY SHARE lock while waiting on the source parent. Closure held that
   parent and requested tenant authority. The canonical authority lock now uses
   FOR NO KEY UPDATE and bootstrap shares it. Authority serialization and
   deletion blocking remain intact; no retries or epoch/tombstone weakening were
   introduced. The corrected 14-case overlap selection and two dedicated
   uncommitted-FK/authority tests pass, as does the complete 168-case PG inventory.
   This is not a retrospective diagnosis of every historical production alert.
2. The first complete frontend run had 892 passes and seven failures. Retained
   diagnostics: six-file replay 37/4, serial replay 18/1. CPU throttling was
   measured during concurrent builds. The final isolated cause was a cold,
   expensive role query used as the initial async loading poll. Poll exact h2
   text, then retain the role/visibility assertion at the same deadline. The
   full 899-test replay passes; no product behavior or mutation retry changed.
3. All six party browser tests initially had a navigation race. Family tests
   stored the portfolio URL before navigation committed; application tests
   interacted with the previous family's tabs. Destination URL and record
   heading assertions now precede nested actions and URL capture. Every complete
   journey passes, including final terminal persistence; the failures remain
   in the original report. Existing intake specs already awaited navigation.
4. The full API inventory heuristic could not see four real paths assembled
   through URL constants: application corrections, version history, lifecycle
   history and a retained party. These paths are now explicit in the existing
   executed positive HTTP assertions, including status and payload checks. No
   unused coverage strings, exclusions, detector relaxation or product changes
   were used. The 121-test replay resolves the one original failed identity.

## Browser And Data Proof

The 393/768/1280px party journeys cover all five roles, every address field,
exact document-version/hash pins, persisted reload, sourced replacement,
unchanged historical records, byte-hash-verified source downloads, stale 409,
cross-tenant 404, explicit closure, forbidden terminal POST, no Add/Replace on
closed records and unchanged family data after application operations. The
desktop test also checks useful control widths and non-overlap immediately
below/at/above responsive breakpoints. Mobile, tablet and desktop editor/history
screenshots were inspected. No lost or collapsed control was accepted.

The complete desktop run reproduces BUG-010 for all five reported Acts:
Arbitration, BNS, BNSS, Companies Act and CPC each return zero verified selectable
sections. Existing catalog entries remain visible but disabled. This is a
missing verified source-data capability, not permission to enable unverified
legal text. The source counts, screenshots, trace and all ten failed soft
assertions are retained. The other 222 journeys passed, including the dated
billing, e-case identifier, original bulk-rule and lifecycle boundaries.
The five skips are the provider-gated Pine Labs payment-link journey and four
production-only exact-release checks (24 Aug, 02 Sep, 03 Sep and 04 Sep). None
is counted as acceptance. The separate mobile run passes navigation, contract
and counsel dialog reachability, and the drafting controls.

Current inventory: 739 OpenAPI paths / 840 operations; 55 route modules, 402
pytest modules, 111 frontend pages, 101 direct page-test files, 152 Playwright
specs and six workflows. File/route counts do not prove all states are covered.
The first cold OpenAPI inventory request timed out at 20 seconds; the subsequent
health check returned `ok` in 605ms and the cached schema request completed.
This diagnostic is retained, not silently converted to a clean cold-start claim.

## Remaining Gates

The next P1 dependency is priority/parent persistence and the bounded graph.
The schema contracts already exist in `schemas/ip_patents.py`; there is no
implemented priority service to duplicate. Reuse the canonical application
writer fence in `services/ip_patent_applications.py` before actor/source/parent
locks. A pair-only edge lock cannot prevent concurrent disjoint edges from
forming a cycle. Application fact corrections must revalidate existing link
chronology/kind constraints, or a valid link can become invalid later. Preserve
independent dockets, append-only evidence, source/access rechecks, closed
historical reads and explicit bounded traversal. These are implementation
findings for the next change, not delivered graph functionality.

All 25 incomplete program slices remain assigned to Codex. P1 priorities/graph
and P2-P6 still require implementation. BUG-010 remains open: catalogued statute
rows are not verified selectable legal provisions. Judgment-enrichment work in
the other preserved worktree still needs integration and representative,
source-grounded production-quality proof. No 4.5+/5 or 4.8+/5 claim follows from
offline fixtures. The failed full desktop browser gate, exact-main CI/security, production
deployment identity and dated production journeys remain separate release gates.

Automated regressions use offline providers or the authoritative no-paid marker
and local deterministic provider service. No paid legal or AI canary was run.
Existing owned fixture volumes and the original 496-row import evidence are
preserved; no global Docker cleanup or production data mutation occurred.
The supplied `test-legal` tester account was created on this exact c351 Docker
candidate. Browser replay of the original 496-row file created 391 valid Matters,
retained 97 invalid rows for correction and skipped eight duplicates. Repeating
the commit returned the same created identities. All 10,416 retained source
cells compare exactly with the original ledger, and all 28 mapped fields on
each created Matter were checked through the API, together with tenant identity,
active state and complete list equality. Evidence is under
`current-c351-tester/`, including `local-all-data-evidence.json`. The older f2f
tester stack and its records remain unchanged. The current local tester UI is
`http://127.0.0.1:31657`; this is not a production URL or release certification.
The previously referenced other task was checked through a current task-status
snapshot: it is not loaded and its latest turn is interrupted. No active writer
was observed there, and it was not restarted during this verification.
