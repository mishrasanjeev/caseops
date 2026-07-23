# Bulk Matter Validation Compatibility: Implementation and Validation Guide

**Date:** 23 July 2026

**Source:** `Bulk_Matter_Validation_Issue_Report.docx`

**Status:** Compatibility candidate implemented; targeted API, full web,
production build, and local browser E2E are green. Full CI and deployed
production validation remain pending.

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

## 8. Validation evidence — to be completed

No row below is a test or deployment claim. Replace `Pending` only with an
exact command/run identifier, timestamp, result count, and durable evidence
location.

### 8.1 Automated validation

| Gate | Command/scope | Expected proof | Status/evidence |
|---|---|---|---|
| Targeted API | `pytest -q tests/test_matter_imports.py tests/test_matter_court_forum_number.py tests/test_20260723_court_forum_number_migration.py tests/test_matter_code_validation.py tests/test_migration_order.py` | Compatibility, persistence, formula, strict-code, migration-order, and upgrade/downgrade/re-upgrade coverage passes | PASS - 54 tests on 2026-07-23; JUnit `.tmp/test-results/api-bulk-validation-final.xml` |
| Full API regression | `npm run test:api` | No backend regressions | Pending |
| API lint | `ruff check --no-cache src tests` | Complete API source/test lint passes | PASS on 2026-07-23 |
| Full web unit regression | `vitest run` | Import/Matter views and all web regressions pass | PASS - 117 files/547 tests; JUnit `.tmp/test-results/web-unit.xml` |
| Web typecheck | `npm run typecheck:web` | TypeScript contracts compile | PASS on 2026-07-23 |
| Web production build | `npm run build:web` | Next.js production build completes | PASS - 64 static routes generated on 2026-07-23 |
| Browser E2E | `playwright test --config=playwright.app.config.ts tests/e2e/bulk-matter-creation.spec.ts --project=app-chromium` | Preview, strict invalid row, commit, Matter readback, history, error report, and Viewer denial | PASS - 2 tests; JUnit `.tmp/test-results/bulk-matter-e2e.xml` |
| Production E2E discovery | `playwright test --config=playwright.prod-ram.config.ts tests/e2e/ram-2026-07-23-prod.spec.ts --project=tester-prod-chromium --list` | Dated deployed regression is selected | PASS - 1 production test discovered |
| Diff hygiene | `git diff --check` | No whitespace errors | PASS on 2026-07-23 |

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
| Source revision | Commit SHA and clean release scope | Pending |
| Database | Migration revision applied and `court_forum_number` present | Pending |
| API deployment | Cloud Run revision/image digest and traffic percentage | Pending |
| Web deployment | Cloud Run revision/image digest and traffic percentage | Pending |
| Health/revision | Production health and revision responses | Pending |
| Rollback target | Prior known-good API/web revisions | Pending |

### 8.3 Production smoke matrix

Use a unique prefix and non-sensitive data. Record created IDs and remove test
records only through an approved audited workflow.

| Case | Expected result | Status/evidence |
|---|---|---|
| Download CSV and XLSX templates | 21 columns; Court Forum Number follows Court | Pending |
| Compatible valid row | Blank Client/Status, non-catalog Practice Area, normalized Forum, punctuation, and Court Forum Number preview as valid | Pending |
| Commit/readback | Matter is Active; optional client remains blank; all compatible text/date/court fields match | Pending |
| Strict invalid row | Slash/`#` Matter Code and formula-like value are rejected with actionable errors | Pending |
| Partial success | Valid row is created; invalid row remains in formula-safe error CSV | Pending |
| History/audit/notification | Tenant-scoped records and expected event intents exist without sensitive row payload in audit metadata | Pending |
| Idempotency/staleness | Repeat commit creates nothing; commit-time duplicate is caught | Pending |
| Access control | Owner/Admin/delegated capability allowed; Viewer and cross-tenant access denied | Pending |

## 9. Release decision and rollback

Release only when every required automated gate and production smoke case has
evidence, the deployed revisions receive intended traffic, and no unrelated
regression remains open.

If production validation fails:

1. stop new bulk imports by removing/hiding the entry point or capability;
2. route API/web traffic to the recorded prior known-good revisions;
3. retain import jobs/rows and the nullable column for investigation;
4. do not drop `court_forum_number` after production writes unless data has
   been reviewed/exported and destructive rollback is explicitly approved; and
5. record the failed case, affected job/row IDs, rollback revision, traffic,
   and follow-up owner.

## 10. Final handoff fields

- Final commit SHA: Pending
- Automated test summary: Local targeted API 54 passed; full web 547 passed; API lint, TypeScript, and production build passed. Full CI pending.
- E2E result: Local bulk-import browser regression 2 passed; deployed-production regression pending.
- Production API revision/digest/traffic: Pending
- Production web revision/digest/traffic: Pending
- Production smoke result: Pending
- Final evidence artifact in `C:\Users\mishr\Downloads`: Pending
- Reviewer/date: Pending
