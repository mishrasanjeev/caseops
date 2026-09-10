# Catalogue Continuation: September 10

## Verdict And Ownership

**Inconclusive. BUG013 is not fixed or accepted in production.** The SQL
parity patch and focused regressions are ready for integration review. The
dated browser specification is implemented but has no completed positive
browser outcome in this run. All nine reported Acts still require truthful
post-integration positive acceptance; partial source coverage is not closure.

Work was confined to `codex-catalogue-closure-20260909`. No commit, push,
production request, production mutation, paid-provider call, or edit to the
main candidate was performed. BUG014, parent canonical intake/PRD changes,
and canonical Playwright discovery/selection tests are parent-owned.
Mapping: BUG013 / RAM10-STATUTES, J05/J07, M05, MOD-TS-017, US-046A-D,
FT-S1..S4, F-T095, IPLF006.

## Intake And Root Cause

The September 10 workbook contains exactly two populated issue rows and no
summary tab. Its SHA-256 is
`c2a67eea079182a80c664247525f963327470ff7be5c4f846f3575fe271fd09e`.
BUG013 reports BSA, CGST, CPA 2019, Contract, CrPC, Hindu Marriage, IEA,
Income-tax 1961 and IPC. The provided source screenshot and production
read-only observations remain in `C:/tmp/caseops-sep10-20260910` untouched.

Parent observation 03 identifies API and web at
`5145fb3a4b51b26af116220ff10a7389bde6324d`; all nine options are disabled.
Observation 01 reports 23 Acts, 17 zero-verified, 1,632 verified of 4,336
catalogued. BSA is explicitly unverified, with no text hash, exact edition
or publisher metadata. Its zero is genuine, not a SQL misclassification.

The adjacent reproducible SQL bug goes in the opposite direction: empty
provenance strings passed SQL's `IS NOT NULL` checks while Python denied
attachment. Five `!= ''` comparisons now align these paths, including NULL
rejection. Verification status, source-link health/type, timestamp, exact
text/hash/version and historical-edition restrictions are not weakened.

## Entry State And Source Work

The prior v2 handoff was not the actual entry state. Five files had advanced:
compiler, loader, document manifest, provision bundle and checksum. They
already contained CrPC (595 source units) and twenty Companies supplements.
The entry manifest in the retained evidence directory captures this state.
This run did not duplicate that extraction or claim it as a fresh acquisition.

CrPC lacked the required Act URL, which caused seed-wide `KeyError` failures.
The manifest now uses the retained official document URL. Loader validation
rejects missing URLs and unknown blocked supplement identities. The compiler
and loader now honor explicit supplement quarantine reasons.

Twenty Companies supplements and CrPC's six-column First Schedule remain
retained but quarantined pending full source/layout reconciliation. The
regenerated bundle differs from the entry bundle in exactly 21 records, only
in verification status, quarantine reason and editorial notes. Their text,
text hashes, source URLs and edition provenance are unchanged. CrPC numbered
provisions, retained forms and the second schedule have focused regressions;
this is not certification of every complex table or current applicability.

Current bundle: 4,496 units, comprising 4,289 verified, 184 retired and 23
quarantined. SHA-256:
`849a75ed2afc7584b2b1cea80fb34921b7dda32ebadab223ffe6394af3e5be8e`.
The independently migrated local database was seeded after database tests:
23 Acts and 5,028 catalogue rows, including pending legacy identities. These
numbers describe retained data, not completed legal coverage or usability.

| Reported Act | Local catalogue / verified | Target provision | Browser verdict |
| --- | ---: | --- | --- |
| BSA | 171 / 171 | Section 63 | Unverified |
| CGST | 193 / 190 | Section 7 | Unverified |
| CPA 2019 | 107 / 107 | Section 107 | Unverified |
| Contract | 269 / 192 | Section 238 | Unverified |
| CrPC | 595 / 594 | Section 482 | Unverified; First Schedule quarantined |
| Hindu Marriage | 37 / 35 | Section 29 | Unverified |
| IEA | 186 / 184 | Section 65B | Unverified |
| IPC | 575 / 554 | Section 302 | Unverified |
| Income-tax 1961 | 298 / 0 | Section 4 | Source admission absent |

Constitution, Motor Vehicles and Income-tax 1961 lack complete admitted
editions. CPC Orders/appendices/forms remain incomplete. Only the prior NDPS
and Specific Relief grids have full cell reconciliation in this track;
other flat schedule transcriptions do not establish equivalent table proof.
Additional source packs and legal applicability remain separately open.
The completeness command exits 1 with `complete: false`, as required.

Income-tax acquisition is blocked on official hosts: CBDT's 2026/2025 PDFs
return 403, the India Code archive returns 500, its bitstream exceeds the
four-redirect limit, and its upload endpoint times out. Exact URLs, times and
raw evidence paths are in `catalogue-sep10-source-access-blockers.md`.
No snippet, fabricated hash, unofficial text, or synthetic statute substitutes
for the missing complete official edition.

## Coverage And Retained Results

The dated spec owns all nine Acts at 393px and 1280px, requiring present and
enabled options, positive verified responses, actual selection/attachment,
success feedback without an error toast, persisted reload, exact pinned
text/hash/version/link, and authenticated source-open redirect. Income-tax's
positive gate is not skipped or converted into disabled-only acceptance.
The API parity regression separately covers sixteen negative provenance,
status, link and timestamp defects plus positive attachment and retained
history, on SQLite and PostgreSQL.

Production mode uses environment-only credentials, exact API/web revision
checks, and `CASEOPS_RAM_PROD_MATTER_ID`. Set the latter to reported Matter
`ac9fdecb-22bb-4551-bf8b-947809db687b`. Production mode never disposes that
Matter. Local fixtures create/dispose only owned Matters. All automated
requests carry the no-paid marker; Docker network namespaces have no egress.

All reports below are retained under `.tmp/catalogue-closure-20260910`.

| Gate | Truthful result |
| --- | --- |
| `api-entry-01` | 90 collected, 65 passed, 25 failed; all complete failures inspected: missing CrPC Act URL and stale inventories |
| `parity-red-01` | SQL empty-text overcount reproduced, Python correctly denied |
| `api-focused-02` | 92 collected, 90 passed, two stale CrPC inventory assertions failed |
| `api-pg-final-03` | 104 collected, 98 passed, one old CrPC negative fixture failed and five PostgreSQL setup errors; every full result inspected |
| `api-pg-final-04` | **104 passed**, 295.90s; 312 successful setup/call/teardown phases and `session_finished: exitstatus=0` |
| Reconciliation | Every node from all four prior inventories is present; every prior failure passes all replacement phases; `reconciliation-final-04.json` |
| Compiler | Pinned full `--check` passed; 12 boundary tests and Ruff passed |
| Frontend | **25 passed** across four files, 15.87s; `web-focused-final-06.xml` |
| Dated E2E typecheck | Passed in isolated Docker source snapshot; no browser acceptance implied |
| Catalogue completeness | Expected red, exit 1, missing editions/page inventory/additional packs |

PostgreSQL setup failures were local URL interpolation errors, not product
reproductions: Alembic rejected `%2F` in the rendered socket query. Setting
`PGHOST=/pgsocket` with a hostless DSN fixed setup without altering fixtures.
The stale negative fixture now uses genuinely unverified Income-tax Section
4, retaining the 409 assertion. Teardown left zero HTTP clone/template
databases and zero tenant companies in the separately migrated base before
the later browser seed. No application database or tenant rows were cloned.

## Browser And Build Gaps

No completed source-matching browser success is claimed:

- Webpack production build compiled but failed Next's exported-page helper
  type gate in four unrelated release/intake/hearing/research files. The
  diagnostics and build directory were retained; no type-check bypass added.
- Canonical Turbopack attempt 02 rejected dependency symlinks outside the
  source snapshot. Attempt 03, with real dependency copies inside the root,
  failed with 24 font-resolution diagnostics. Both logs and failed build
  directories remain. The source font CSS hashes matched the tools image;
  this build-tool failure is not attributed to BUG013.
- Browser attempt 01: all 18 full error records show missing Chromium in the
  Alpine web-tools image. No product flow ran.
- Browser attempt 02: system Chromium launched using an ignored local runner
  wrapper, not a canonical config edit. BSA timed out on cold sign-in
  compilation; the next setup lost its API after container OOM kills. Two
  failed, sixteen did not run. The combined API/browser cgroup recorded six
  OOM events and two kills. JSON, logs, traces and container evidence remain.
- Video was unavailable in that image (no FFmpeg). These were fresh
  development-server attempts, not release-build or production acceptance.

Aggregate active container limits never exceeded one CPU and two GiB. The
failure was retained rather than increasing the limit, raising timeouts,
adding browser retries, disabling assertions or using a stale serving build.
Focused tests are not a full API, full web or all-postgres-marker gate.

## Integration

Use `catalogue-closure-files-2026-09-10-v3.json` for exact current hashes,
entry deltas and inherited catalogue scope. It supersedes the priority
manifests as a copy inventory. Canonical Playwright configs are excluded:
this agent added discovery entries before the parent claimed ownership and
made no further changes afterward. Parent owns final discovery and selection
regressions; do not copy either config from this worktree.

Merge the five SQL comparisons into the shared route file; do not overwrite
the parent's other changes. Wider compiler/data files form a coordinated
partial-source candidate, not all-nine-Act completion. Existing reviewed
database rows still resist generic seed overwrite; no review/history fence
was removed. Preserve the manifest checksum and run the exact candidate seed
before acceptance. Full source completion, fixed-flow desktop/mobile proof,
parent integration and exact-release production validation remain open.
