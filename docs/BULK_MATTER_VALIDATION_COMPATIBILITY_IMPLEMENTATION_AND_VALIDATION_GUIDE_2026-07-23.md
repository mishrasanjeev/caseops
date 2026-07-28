# Bulk Matter Validation Compatibility: Implementation and Validation Guide

**Date:** 23 July 2026

**Source:** `Bulk_Matter_Validation_Issue_Report.docx`

**Status:** Production deployed from merge commit `e763584`. Targeted and full
CI, security, CodeQL, migration, immutable-image, Cloud Run traffic, public
health, ClamAV sidecar presence/digest, and post-deploy workflow
`30019214017` passed.

**Related PRD:** [Bulk Matter Creation](./PRD_BULK_MATTER_CREATION_2026-07-17.md)

**End-user guide:** [ADP-11 Bulk Matter Creation](./ADP_01_TO_19_END_USER_PRODUCT_GUIDE_2026-05-25.md#adp-11-bulk-matter-creation)

## 1. Compatibility outcome

The release keeps preview-before-write, confirmation, partial success, tenant
isolation, history, audit, notification, idempotency, and error-report behavior.
It changes the accepted input contract so client-maintained CSV/XLSX registers
that use the documented formats and aliases do not fail only because of
presentation differences.

The source issue report describes unnecessary failures from overly strict
validation and directs the product to prioritize business correctness,
normalization, and user-friendly support. It explicitly requires
case-insensitive validation, support for normal business punctuation,
minimal-change compatibility with existing client workbooks, and a Court Forum
Number template column. The following implementation resolutions turn those
broad requirements into a testable contract:

1. The canonical template has 21 columns, including a distinct optional
   **Court Forum Number** immediately after **Court**.
2. Only Matter Title, Matter Code, Practice Area, and Forum are mandatory.
   Client Name is optional; a blank Matter Status defaults to `active`.
3. Recognized status/forum values are case-insensitive and ignore common
   separators. A valid non-catalog Practice Area is accepted and preserved.
4. Normal legal/business punctuation is preserved in applicable text,
   reference, and phone fields.
5. CSV encoding/delimiter and XLSX worksheet/header/date compatibility are
   broadened as specified below.
6. Formula protection and the shared Matter Code grammar remain strict.

## 2. Canonical 21-column contract

| # | Header | Required | Notes |
|---:|---|:---:|---|
| 1 | Matter Title | Yes | 3-255 characters |
| 2 | Matter Code | Yes | Shared strict grammar; see section 6 |
| 3 | Matter Type | No | Up to 120 characters |
| 4 | Practice Area | Yes | 2-120 characters; non-catalog labels allowed |
| 5 | Matter Status | No | Blank becomes `active` |
| 6 | Matter Description | No | Up to 4,000 characters |
| 7 | Client Name | No | 2-255 characters when supplied |
| 8 | Client Code | No | Up to 80 characters |
| 9 | Client Contact Number | No | Up to 40 characters; 7-20 main-number digits and optional `ext`, `ext.`, or `x` followed by 1-10 digits |
| 10 | Client Email | No | Valid email, up to 254 characters |
| 11 | Opposing Party Name | No | 2-255 characters when supplied |
| 12 | Opposing Counsel | No | Up to 255 characters |
| 13 | Forum | Yes | Supported forum value/alias |
| 14 | Court | No | Court/forum name, 2-255 characters when supplied |
| 15 | Court Forum Number | No | Separate court/bench/room/forum reference, up to 120 characters |
| 16 | Case Number | No | Up to 120 characters; duplicate checked |
| 17 | Filing Number | No | Up to 120 characters |
| 18 | Filing Date | No | Compatible formats in section 5 |
| 19 | Matter Owner | No | Active current-tenant work email |
| 20 | Assigned Team | No | Active current-tenant name or slug |
| 21 | Responsible Lawyer | No | Active current-tenant work email |

`court_forum_number` is nullable and independent of `court_name`. It must
round-trip through ordinary Matter create/read/update and through preview,
commit, Matter retrieval, and import history row details.

## 3. File and layout compatibility

| Concern | Accepted behavior |
|---|---|
| CSV encoding | UTF-8 with/without BOM; BOM-marked UTF-16; Windows-1252 |
| CSV delimiter | Comma, semicolon, tab, or pipe, detected from the file |
| Header position | Best recognized header within the first 25 non-empty rows |
| XLSX worksheet | Best recognized table across workbook worksheets; first sheet is not assumed |
| Worksheet scoring | Recognized columns, with extra weight for Matter Title and Matter Code |
| Empty/title rows | Ignored before the selected header; CSV physical starting-line numbers and XLSX row references are retained |
| Header comparison | Case-insensitive; non-alphanumeric presentation punctuation is ignored |
| XLSX cell coordinates | Standard Excel range only: columns A-XFD (1-16,384) and rows 1-1,048,576; malformed cell references, coordinates outside those bounds, and duplicate or out-of-order worksheet row references are rejected |
| XLSX archive security | Stored or Deflate compression only; at most 1,000 ZIP entries, 16 MiB per uncompressed entry, 32 MiB total uncompressed content, and a 250:1 compression-ratio ceiling for entries of at least 1 MiB; encrypted archives and other ZIP compression methods are rejected |
| XLSX XML memory bounds | Workbook and workbook-relationship metadata are limited to 512 KiB each; shared strings are streamed and limited to 100,000 entries, 32,767 characters per entry, and 8,388,608 characters of aggregate text |
| XLSX execution safety | Safe ZIP/XML value parsing only; no Excel, macro, external-link, embedded-code, or formula execution |
| Limits | `.csv`/`.xlsx`, at most 2 MB and 500 non-empty data rows |

The generated XLSX template remains the recommended input because it provides
reference values and instructions. Compatibility applies to client registers
that match the documented formats, header aliases, and field rules; it does not
guess the meaning of unrelated worksheets or unknown headings.

CSV delimiter characters inside a field must follow standard CSV quoting. For
example, a comma in a comma-delimited description must be enclosed in double
quotes; quoted content is preserved.

## 4. Header aliases

Canonical headings are always accepted. The compatibility parser also accepts
the following normalized aliases:

| Target field | Aliases |
|---|---|
| Matter Title | Title, Matter Name, Case Title, Name |
| Matter Code | Code, Matter ID |
| Matter Type | Type |
| Practice Area | Area of Practice, Area |
| Matter Status | Status, Current Status |
| Matter Description | Description |
| Client Name | Client, Existing Client, Existing Client Name, Party Name, Client Reference, Client Ref |
| Client Code | Client Code |
| Client Contact Number | Client Contact No., Client Phone, Client Phone No., Phone, Phone No., Phone Number |
| Client Email | Client Email |
| Opposing Party Name | Opposing Party |
| Opposing Counsel | Opposing Counsel |
| Forum | Forum Level, Court / Forum |
| Court | Court Name, Forum Name |
| Court Forum Number | Court / Forum No., Court/Forum Ref/Reference, Court Number/No., Forum Number/No. |
| Case Number | Case Number |
| Filing Number | Filing Number |
| Filing Date | Date of Filing |
| Matter Owner | Owner, Owner Email, Assignee |
| Assigned Team | Team, Team Slug |
| Responsible Lawyer | Responsible Lawyer Email |

Because comparison removes presentation punctuation, variations such as
`COURT_FORUM_NO`, `Court-Forum-No.`, and `Court / Forum No.` resolve through
the same alias when their remaining letters/digits match.

## 5. Value compatibility

### 5.1 Status and forum

Controlled-value comparison is case-insensitive and removes presentation
punctuation/separators.

| Input examples | Canonical value |
|---|---|
| blank status | `active` |
| Active | `active` |
| Intake | `intake` |
| On Hold, on-hold, on_hold, Hold | `on_hold` |
| Closed, Disposed | `disposed` (recognized but rejected for creation) |
| Lower Court, District Court, District and Sessions Court, Sessions Court | `lower_court` |
| High Court | `high_court` |
| Supreme Court, Supreme Court of India | `supreme_court` |
| Tribunal, Consumer Forum, Consumer Commission | `tribunal` |
| Arbitration, Arbitral Tribunal | `arbitration` |
| Advisory | `advisory` |

### 5.2 Practice area and business punctuation

Practice Area remains required. A known standard, established tenant, or active
practice-area team value is canonicalized. Otherwise, any value that satisfies
the normal 2-120 character Matter contract is preserved.

Applicable text/reference fields preserve punctuation used in legal and
business data, including periods, commas, apostrophes, parentheses, `#`, `/`,
`&`, semicolons, and internal hyphens. Field-specific type and length rules
still apply.

Without a leading `+`, phone values may contain digits, spaces, parentheses,
periods, commas, `#`, hyphens, slashes, `&`, and an optional trailing `ext`,
`ext.`, or `x` followed by 1-10 digits. The main number must contain 7-20
digits. A value beginning with exactly one international `+` uses the narrower
formula-safe grammar: only digits, spaces, parentheses, and hyphens may follow
the `+` before the same optional extension. A `+` anywhere else is invalid.

### 5.3 Filing dates

Accepted date representations include:

- ISO dates and parseable ISO timestamps, such as `2026-07-17` or
  `2026-07-17T10:30:00+05:30`;
- year-first `2026/07/17` and `2026.07.17`;
- day-first numeric `17/07/2026`, `17-07-2026`, and `17.07.2026`, including
  the corresponding two-digit-year forms;
- day-first English month names, such as `17 Jul 2026`, `17-Jul-2026`,
  `17 July 2026`, or `17-July-2026`; and
- valid native Excel serial dates using an XLSX workbook's declared 1900 or
  1904 date system. Fractional serials are accepted, with the time-of-day
  fraction discarded because Filing Date stores a calendar date. A numeric
  serial supplied outside XLSX uses the 1900 date system because it carries no
  workbook metadata.

Every accepted value normalizes to an ISO calendar date.

## 6. Intentional strict controls

Compatibility must not weaken identifiers or spreadsheet safety.

### Matter Code

The normal Matter create/update/import grammar is shared:

- trim and uppercase;
- 2-80 characters;
- first and last characters must be a letter or digit; and
- only letters, digits, and internal hyphens are allowed.

Spaces, underscores, slashes, periods, `#`, and other punctuation are rejected.
For example, `RELAXED-CASE-1` is valid; `RELAXED/CASE#1` is invalid.

### Spreadsheet formulas

- An actual XLSX formula node in the selected import header or data cells is
  invalid even when it has a cached value. Ignored worksheets/report rows are
  never evaluated.
- In the selected import table, text whose first non-space character is `=`,
  `+`, `-`, or `@` is invalid.
- A leading `+` is allowed only for a Client Contact Number that matches the
  narrower formula-safe phone grammar in section 5.2.
- Unsafe stored raw values are replaced with `[unsafe formula removed]`.
- Error-report cells that could execute as formulas receive a leading
  apostrophe.
- XML DTD/entity expansion remains rejected.

## 7. Implementation map

| Area | Repository location | Responsibility |
|---|---|---|
| Database | `apps/api/alembic/versions/20260723_0001_add_matter_court_forum_number.py` | Nullable Court Forum Number migration |
| Matter persistence/contracts | `apps/api/src/caseops_api/db/models.py`, `schemas/matters.py`, `services/matters.py` | Create/read/update and normalization |
| Bulk-import contract/parser | `apps/api/src/caseops_api/schemas/matter_imports.py`, `services/matter_imports.py` | Template, aliases, CSV/XLSX parsing, normalization, validation, commit |
| Import UI/contracts | `apps/web/app/app/matters/imports/page.tsx`, `apps/web/lib/api/` | Preview display and Court Forum Number typing |
| Matter UI | `apps/web/app/app/matters/[id]/page.tsx` | Court Forum Number display |
| User documentation | `README.md`, `apps/api/README.md`, `docs/`, `apps/web/app/guide/page.tsx` | Operator and end-user contract |

## 8. Validation evidence

Results below identify exact local artifacts or remote run/execution IDs.
Overlapping local subset reports are not added together as unique tests.

### 8.1 Automated validation

| Gate | Command/scope | Expected proof | Status/evidence |
|---|---|---|---|
| Targeted API | `pytest -q tests/test_matter_imports.py tests/test_matter_court_forum_number.py tests/test_20260723_court_forum_number_migration.py tests/test_matter_code_validation.py tests/test_migration_order.py` | Compatibility, persistence, formula, strict-code, migration-order, and upgrade/downgrade/re-upgrade coverage passes | PASS - 54 tests; JUnit `.tmp/test-results/api-bulk-validation-post-security.xml` |
| Full API regression | Four deterministic pytest/coverage shards in CI | No backend regressions and every coverage threshold passes | PASS - 2,137 passed, 21 skipped across 184 files; all 16 coverage gates passed; CI run `30012869723` |
| PostgreSQL/pgvector | `pytest -m postgres` on PostgreSQL 17 + pgvector | Migration and PostgreSQL-specific behavior passes | PASS - 13 tests; CI run `30012869723` |
| API lint | `ruff check src tests` | Complete API source/test lint passes | PASS - CI run `30012869723` |
| Full web unit regression | `vitest run` | Import/Matter views and all web regressions pass | PASS - 117 files/547 tests; JUnit `.tmp/test-results/web-unit-post-security.xml`; CI run `30012869723` |
| Web typecheck | `npm run typecheck:web` | TypeScript contracts compile | PASS - CI run `30012869723` |
| Web production build | `npm run build:web` | Next.js production build completes | PASS - 64/64 pages generated locally and CI; local log `.tmp/test-results/web-build-post-security.stdout.log` |
| Browser E2E | Local focused spec plus CI app configuration | Preview, strict invalid row, commit, Matter readback, history, error report, and Viewer denial; no wider app regression | PASS - local 2 tests in `.tmp/test-results/bulk-matter-e2e-post-security.xml`; CI 118 passed/1 skipped in run `30012869723` |
| Production E2E discovery | `playwright test --config=playwright.prod-ram.config.ts tests/e2e/ram-2026-07-23-prod.spec.ts --project=tester-prod-chromium --list` | Dated deployed regression is selected | PASS - 1 production test discovered |
| Deployed production E2E | GitHub Actions workflow `30019214017` | Templates, compatibility preview, strict code, partial commit, readback, idempotency, history, and cleanup pass on the live services | PASS - dated bulk-Matter test in 5.9 s; RAM batch 47 passed/4 skipped; notice suite 2/2 passed |
| Diff hygiene | `git diff --check` | No whitespace errors | PASS on 2026-07-23 |
| Security and generated contract | npm/pip audits, gitleaks, license allow-list, secret references, OpenAPI clean diff, CodeQL Actions/JavaScript/Python | No known high/critical dependency issue, secret leak, contract drift, or CodeQL alert | PASS - Security `30012868237`; CodeQL `30012868277` |

Minimum compatibility cases:

- canonical CSV/XLSX template contains 21 ordered headers;
- Court Forum Number survives preview, commit, read, update, and clear;
- blank Client Name and Status succeed, with status `active`;
- mixed-case/separator status and forum values normalize;
- non-catalog Practice Area and business punctuation survive unchanged;
- UTF-8, UTF-16, and Windows-1252 CSV plus all four delimiters parse;
- title rows, later XLSX worksheet, header aliases, CSV physical starting-line
  numbers, and XLSX row references work;
- documented filing dates, including fractional 1900/1904 Excel serials,
  normalize correctly;
- invalid Matter Code and formula/formula-like content must remain rejected;
- international phone punctuation is accepted only when syntactically valid;
- duplicate, tenant, permissions, partial-success, idempotency, history, audit,
  notification, and formula-safe error-report regressions must remain green.

### 8.2 Deployment record

| Item | Evidence to record | Status/evidence |
|---|---|---|
| Source revision | Commit SHA and clean release scope | PASS - PR #144 head `d7b576f`; merge/deployed SHA `e763584f12d87ce07da84d201b430b3d9f8cfc92`; at deploy start `2026-07-23T14:46:47Z`, `HEAD == origin/main == e763584`; tested application trees were identical and API/web contexts were clean |
| Database | Migration revision applied and `court_forum_number` present | PASS - `caseops-migrate-job-dh6tv`, 1/1 task, completed 2026-07-23T14:51:23Z; runtime import/readback is the column proof |
| API deployment | Cloud Run revision/image digest and traffic percentage | PASS - `caseops-api-00211-fgf`; `sha256:88cd609ff212afd44169e52926dfc8474fa11b90fcb65479e6ed5a1d7b922aba`; 100% |
| Web deployment | Cloud Run revision/image digest and traffic percentage | PASS - `caseops-web-00190-d7b`; `sha256:acb8f24eb3a52ee832598f48e74ccd0454ce944389c8ce615cb9ec782e626928`; 100% |
| Health/revision | Production health and revision responses | PASS - API `status=ok`; web HTTP 200; latest-created equals latest-ready; runtime/artifact digests match; ClamAV present |
| Background jobs | Migration and four recurring templates use immutable API image | PASS - all five point to API digest `sha256:88cd609ff212afd44169e52926dfc8474fa11b90fcb65479e6ed5a1d7b922aba` |
| Rollback target | Prior known-good API/web revisions | `caseops-api-00210-fnv` / `caseops-web-00189-k9f`; do not downgrade additive migration `20260723_0001` after writes |

The PowerShell evidence wrapper classified ordinary `gcloud` progress written
to stderr as a `NativeCommandError` after the native deployment completed.
That wrapper result is not used as release proof. Certification above comes
from independent Cloud Build results, migration execution state, Cloud Run
latest-created/latest-ready revisions and traffic, Artifact Registry/runtime
digests, recurring-job images, public health, and ClamAV sidecar
presence/digest checks.

Pre-existing operations note: the legal-update and case-tracking midnight
schedulers reported status code 7 on their 22 July attempts, and their latest
actual executions remained from 31 May at the pre-deploy check. This release
updated their job templates to the new immutable API digest; it does not claim
that unrelated scheduler invocation issue is resolved.

### 8.3 Production smoke matrix

Workflow `30019214017` ran against `https://caseops.ai` and
`https://api.caseops.ai` from verifier commit `b06795b`. Its production
application files are identical to deployed `e763584`; it adds only a one-line
verifier-selector correction. The workflow completed at
2026-07-23T15:23:57Z: the 51-test RAM batch reported
47 passed/4 skipped in 13.3 minutes, the dated bulk-Matter test passed in
5.9 seconds, and the separate notice suite passed 2/2.

The first post-deploy run `30018039479` had already passed the feature's
template, preview, strict-code, partial-commit, readback, and idempotency
assertions. It then stopped at line 698 because `getByLabel("Search")` matched
four page elements. The corrected verifier targets
`#matter-import-history-search`. The first run's other failure was the
pre-existing 15 July notice-row timing case also seen before deployment in
scheduled run `30012441624`; it passed on the corrected run. The first run's
RAM batch reported 46 passed/2 failed/2 skipped/1 did not run in 11.7 minutes,
and the separate notice-module step was skipped.

| Case | Expected result | Status/evidence |
|---|---|---|
| Download CSV and XLSX templates | 21 columns; Court Forum Number follows Court | PASS in `30019214017` |
| Compatible valid row | Blank Client/Status, non-catalog Practice Area, normalized Forum, asserted punctuation, and Court Forum Number preview as valid | PASS - Windows-1252, semicolon delimiter, title row, aliases, `HIGH COURT`, and punctuation in title, Practice Area, Court Forum Number, and phone; filing date normalized |
| Commit/readback | Asserted Matter fields match the preview | PASS - title, code, Active status, null Client, contact number, Practice Area, canonical forum, Court Forum Number, and filing date |
| Strict invalid row | Slash/`#` Matter Code and formula-like value are rejected with actionable errors | Matter Code PASS in production; formula-like input was not executed in production and remains local/CI evidence only |
| Partial success | Valid row is created; invalid row remains in a downloadable error CSV | PASS - 1 created/1 failed; leading-formula error-cell sanitization was not separately exercised in production |
| History/audit/notification | Tenant-scoped history reopens; expected audit and notification intents exist | History PASS; audit-event and notification-intent inspection was not executed in production |
| Idempotency/staleness | Repeat commit creates nothing; commit-time duplicate is caught | Repeat-commit idempotency PASS; commit-time staleness injection was not executed in production |
| Access control | Authorized capability allowed; Viewer and cross-tenant access denied | Configured QA tester slug/email and `matters:create`, `matters:edit`, `matters:archive`, and `matters:bulk_import` capabilities PASS; role/Owner status, delegated Manager, Viewer, and cross-tenant cases were not executed in production |
| Case variants | All four source High Court case examples normalize | `HIGH COURT` PASS in production; `High Court`, `high court`, and `High court` are local/CI evidence only |
| Cleanup | Lifecycle cleanup is requested without hard deletion | PASS at request/hook level: each discovered non-Disposed Matter received an HTTP-200 lifecycle request to `Disposed`; any still-validated preview was cancelled; no cleanup/hook failure. The test did not re-read post-transition state or inspect audit events |

The successful workflow uploaded no failure artifact because the
failure-only upload step was correctly skipped. Its run and job logs are the
durable production proof. Local/CI cases are not promoted to
production-executed claims.

## 9. Release decision and rollback

**Decision: ACCEPTED for the bulk-Matter compatibility feature.** The exact
merged application commit is deployed, migration and immutable-image
certification passed, both services receive 100% intended traffic, health
checks pass, full CI/security/CodeQL are green, and the dated live feature
scenario passed. The unexecuted production cases identified above retain green
local/CI evidence but are not represented as live-production proof.

No rollback was triggered. If a later production validation fails:

1. stop new bulk imports by removing/hiding the entry point or capability;
2. route API/web traffic to the recorded prior known-good revisions;
3. retain import jobs/rows and the nullable column for investigation;
4. do not drop `court_forum_number` after production writes unless data has
   been reviewed/exported and destructive rollback is explicitly approved; and
5. record the failed case, affected job/row IDs, rollback revision, traffic,
   and follow-up owner.

## 10. Final handoff fields

- Final commit SHA: `e763584f12d87ce07da84d201b430b3d9f8cfc92`
- Automated test summary: Local targeted API 54 passed; full API CI 2,137 passed/21 skipped plus 13 PostgreSQL tests; full web 547 passed; CI Playwright 118 passed/1 skipped; lint, typecheck, build, security, OpenAPI, and CodeQL passed.
- E2E result: Local bulk-import browser regression 2 passed; deployed-production workflow `30019214017` passed (RAM 47 passed/4 skipped; dated feature 5.9 s; notice suite 2/2).
- Production API revision/digest/traffic: `caseops-api-00211-fgf`; `sha256:88cd609ff212afd44169e52926dfc8474fa11b90fcb65479e6ed5a1d7b922aba`; 100%.
- Production web revision/digest/traffic: `caseops-web-00190-d7b`; `sha256:acb8f24eb3a52ee832598f48e74ccd0454ce944389c8ce615cb9ec782e626928`; 100%.
- Production smoke result: PASS within the explicit production-coverage boundary in section 8.3; cleanup PASS by enforced hook.
- Final evidence artifact in `C:\Users\mishr\Downloads`: `CaseOps_Bulk_Matter_Validation_2026-07-23`
- Reviewer/date: CaseOps Engineering with Codex verification / 23 July 2026
