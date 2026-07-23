# Product Requirements Document: Bulk Matter Creation

**Document ID:** PRD-BMC-2026-07-17

**Status:** Compatibility candidate implemented and locally verified; full CI and production deployment pending

**Owner:** CaseOps Product and Engineering

**Sources:** `Bulk_Matter_Creation_Enhancement.docx` (4 pages, 25 paragraphs);
`Bulk_Matter_Validation_Issue_Report.docx`

**Module:** Matter Management

**Submodule:** Matters

**Last updated:** 23 July 2026

The 23 July validation issue report defines six linked themes: reduce unnecessary
failures caused by overly strict validation; judge values by business
correctness rather than presentation; make supported-value validation
case-insensitive; accept normal business punctuation; preserve minimal-change
compatibility with existing client Excel data; and add a Court Forum Number
template column. It also calls for normalization and user-friendly support. It
does not define exact aliases, encodings, delimiters, worksheet scoring, date
formats, optional/default fields, or safety limits. Those details below are
explicit product/engineering resolutions that make the broad source request
testable; they are not quoted source requirements.

## 1. Executive summary

CaseOps must let authorized legal-operations users create many matters in one controlled operation by uploading the CaseOps CSV or XLSX template. The product validates the complete file before confirmation, creates every row that remains valid at commit time, preserves every invalid or failed row, provides a downloadable error report, exposes searchable tenant-scoped import history, emits durable notifications, and records a complete audit trail.

The planned 23 July compatibility revision preserves that controlled workflow
while accepting client-maintained exports that match the documented formats and
aliases. The canonical template has 21 columns, including a distinct Court
Forum Number. Client Name and Matter Status are optional, with omitted status
defaulting to Active. Non-catalog practice areas and normal legal/business
punctuation are accepted. Controlled values, headers, CSV formats, workbook
layouts, and filing dates tolerate the documented presentation differences.
Spreadsheet-formula protection and the shared strict Matter Code grammar remain
unchanged by design.

This capability replaces the prior ADP-11 dry-run foundation as the user-facing workflow. The legacy dry-run API remains available for backward compatibility and document-manifest planning, but it does not represent the production bulk-creation workflow.

## 2. Problem statement

The existing Matter Management workflow creates one matter at a time. That is unsuitable for firm onboarding, portfolio migrations, backlog capture, or periodic matter feeds. Re-entering the same fields manually is slow and error-prone, while an unvalidated bulk write would introduce duplicate, cross-tenant, badly assigned, or malformed records.

The product therefore needs both throughput and control:

- a standard machine- and human-usable template;
- validation before any matter is written;
- row-level explanations that a user can act on;
- explicit confirmation;
- commit-time revalidation so a previously valid preview cannot create stale duplicates;
- partial success, because the source requirement explicitly calls for successful and failed counts in the same import;
- persistent history, notifications, and audit evidence.

## 3. Goals and success outcomes

### 3.1 Product goals

1. Reduce the time required to onboard or migrate a matter portfolio.
2. Reduce manual-entry errors through controlled fields and pre-import validation.
3. Prevent tenant-crossing assignments and obvious duplicate matters.
4. Make every upload and row outcome explainable and auditable.
5. Give an authorized user a complete, recoverable workflow from template download through post-import review.

### 3.2 Business outcomes from the source requirement

- Faster matter onboarding.
- Reduced manual data entry.
- Improved operational productivity.
- Support for historical-data migration.
- Better matter-data management.
- Reduced data-entry errors.
- Complete import audit trail.

### 3.3 Success measures

- 100% of accepted files receive a persisted validation job and summary.
- 100% of rejected rows have at least one row-level error.
- 0 cross-tenant people, team, history, or matter references are accepted.
- Repeating commit for a completed job creates 0 additional matters.
- Commit-time changes to duplicates, memberships, teams, or practice-area references are detected before each affected matter is written.
- Import history can be searched by file name, uploader name, or uploader email.

## 4. Personas and permissions

### 4.1 Authorized personas

| Persona | Authorization rule | Intended use |
|---|---|---|
| Owner | Receives `matters:bulk_import` by default | Firm onboarding, migration, governance |
| Admin | Receives `matters:bulk_import` by default | Day-to-day operational import |
| Matter Manager | Tenant custom role granted only `matters:bulk_import` and any separately required permissions | Delegated import without workspace-admin access |

The source document names Owner, Admin, and Matter Manager. CaseOps has fixed Owner/Admin roles and tenant-defined custom roles; therefore Matter Manager is implemented as a least-privilege custom role using a dedicated capability rather than as a new global fixed role.

### 4.2 Restricted personas

- Viewer.
- Read-only user (represented by the Viewer role or a custom role without `matters:bulk_import`).
- Partner, Member, and Paralegal unless a valid tenant custom role explicitly grants `matters:bulk_import`.
- Portal users and outside counsel.

Restricted users do not see the Matter portfolio action, receive a permission-required state if they navigate directly, and receive HTTP 403 from every template, preview, history, commit, cancellation, and error-report endpoint.

## 5. Scope

### 5.1 In scope

- Dedicated **Bulk upload matters** page.
- CSV and XLSX template downloads.
- Upload and validation of CSV and XLSX files.
- All 21 template fields, including distinct Court and Court Forum Number fields.
- Required-field, type, reference, duplicate, security, and tenant validation.
- Persisted validation job with 24-hour confirmation window.
- Explicit import confirmation.
- Creation of all valid rows; retention of invalid/failed rows.
- Import summary and row-level validation table.
- Safe downloadable CSV error report.
- Searchable import history.
- Audit events and durable in-app notification intents.
- Custom Matter Manager permission.
- API, web UI, migration, OpenAPI contract, tests, product guide, and engineering documentation.

### 5.2 Out of scope

- Importing matter documents or ZIP payloads as part of this workflow. The legacy ADP-11 dry-run can still inspect document names, but this PRD creates matters only.
- Automatic creation of employees, teams, courts, or practice-area teams from arbitrary text.
- Automatic conflict clearance. Imported active matters follow the existing product policy for normal matter creation; lifecycle disposal remains a separate audited workflow.
- External email/SMS notification delivery. The current notification provider policy supports durable in-app intents; external providers remain independently governed.
- Files above 500 data rows or 2 MB in one job. Larger migrations must be split into controlled batches.

## 6. Complete use-case catalogue

| ID | Use case | Actor | Preconditions | Expected result |
|---|---|---|---|---|
| UC-001 | Open Bulk upload matters | Authorized user | Signed in to active tenant | Dedicated workflow page opens |
| UC-002 | Download XLSX template | Authorized user | UC-001 | Workbook contains Matter Import, Reference Values, and Instructions sheets |
| UC-003 | Download CSV template | Authorized user | UC-001 | UTF-8 CSV with all 21 headers and example row downloads |
| UC-004 | Populate template | Authorized user | Template downloaded or compatible client register | User enters one row per matter; canonical headers are recommended and documented aliases are accepted |
| UC-005 | Upload CSV | Authorized user | File is CSV, <=2 MB, <=500 rows | Compatible encoding, delimiter, and header row are detected; file is validated, fingerprinted, and persisted |
| UC-006 | Upload XLSX | Authorized user | File is XLSX, <=2 MB, <=500 rows | The best matching worksheet/header row is parsed safely, validated, fingerprinted, and persisted |
| UC-007 | Validate before import | Authorized user | UC-005/006 | No matters are created; every row becomes valid or invalid |
| UC-008 | Review validation results | Authorized user | Validation job exists | Total, valid, invalid, validation-error counts and row errors display |
| UC-009 | Correct and re-upload | Authorized user | One or more invalid rows | User edits original file and creates a new validation job |
| UC-010 | Confirm import | Authorized user | Job status `validated`, unexpired, >=1 valid row | Valid rows are revalidated and created; invalid rows remain failed |
| UC-011 | Handle partial success | Authorized user | Valid and invalid rows coexist | Valid matters are created; final status is `completed_with_errors` |
| UC-012 | View import summary | Authorized user | Preview or commit completed | Total, imported, failed, validation errors, file, status, and uploader display |
| UC-013 | Download error report | Authorized user | Invalid or failed rows exist | Formula-safe CSV lists row number, code, title, status, and errors |
| UC-014 | Search import history | Authorized user | At least one tenant job exists | Search works by file, uploader name, or uploader email; optional status filter |
| UC-015 | View history metadata | Authorized user | History loaded | Upload date, uploaded by, file name, import status, record/import/failure counts display |
| UC-016 | Cancel preview | Authorized user | Job status `validated` | Job becomes `cancelled`; it cannot be committed |
| UC-017 | Retry completed commit | Authorized user | Job is terminal completed state | Existing response returns; no duplicate matters are created |
| UC-018 | Commit expired preview | Authorized user | Validation older than 24 hours | Job becomes `expired`; user must re-upload |
| UC-019 | Detect stale preview | Authorized user | Tenant data changed after preview | Commit-time revalidation moves affected row to invalid/failed |
| UC-020 | Receive upload-success notification | Uploader | File parsed and job persisted | Durable in-app intent `matter_import.upload_succeeded` is recorded |
| UC-021 | Receive validation-failure notification | Uploader | Preview contains invalid rows | Durable in-app intent `matter_import.validation_failed` is recorded |
| UC-022 | Receive completion notification | Uploader | Commit reaches terminal result | Durable in-app intent `matter_import.completed` is recorded |
| UC-023 | Review audit trail | Authorized auditor/admin | Relevant audit access | Redacted job and row events show actor, time, tenant, result, and counts |
| UC-024 | Deny restricted role | Viewer/read-only | Direct UI/API attempt | UI hides action and API returns 403 |
| UC-025 | Delegate Matter Manager | Owner | Custom-role management access | Custom role can import without acquiring workspace administration |
| UC-026 | Protect tenant isolation | Any user | References/job belongs to another tenant | Reference is rejected or job returns 404 without existence disclosure |
| UC-027 | Reject unsafe spreadsheet content | Authorized user | Selected import header/data cell is a formula/formula-like payload | Row is invalid; formula content is not evaluated or echoed unsafely |
| UC-028 | Preserve international phone | Authorized user | Client Contact Number begins with one `+` and otherwise matches the narrower formula-safe grammar | Value is treated as a phone, not a formula, and validated normally |
| UC-029 | Accept compatible controlled values | Authorized user | Status/forum uses different case or separators | Recognized value normalizes to the canonical enum |
| UC-030 | Accept a client-maintained workbook | Authorized user | Import sheet/header is not the first sheet/row or uses documented aliases | System finds the best compatible table without reading an instruction sheet as data |
| UC-031 | Preserve court/forum reference | Authorized user | Row supplies Court Forum Number | Optional reference is previewed, created, returned, and editable independently of Court |

## 7. Template and field specification

The generated template uses the following canonical order. The 23 July
compatibility revision adds **Court Forum Number** immediately after **Court**
so the court/forum name and its local number/reference are never conflated.

| # | Template header | Internal field | Required | Type/limit | Normalization and validation |
|---:|---|---|:---:|---|---|
| 1 | Matter Title | `title` | Yes | Text, 3-255 | Trim; duplicate title+client check |
| 2 | Matter Code | `matter_code` | Yes | Text, 2-80 | Trim and uppercase; must start/end alphanumeric and contain only A-Z, 0-9, and internal hyphens; tenant-unique; file duplicate check |
| 3 | Matter Type | `matter_type` | No | Text, <=120 | Trim; stored on matter |
| 4 | Practice Area | `practice_area` | Yes | Text, 2-120 | Known standard/team/tenant values are canonicalized; a valid non-catalog business label is also accepted and preserved |
| 5 | Matter Status | `status` | No | `active`, `intake`, `on_hold` | Blank defaults to `active`; recognized values are case/separator-insensitive; `closed`/`disposed` is rejected for creation |
| 6 | Matter Description | `description` | No | Text, <=4000 | Trim; stored on matter |
| 7 | Client Name | `client_name` | No | Text, 2-255 when supplied | Trim; participates in duplicate-title check when supplied |
| 8 | Client Code | `client_code` | No | Text, <=80 | Trim; stored as imported client reference snapshot |
| 9 | Client Contact Number | `client_contact_number` | No | Text, <=40; 7-20 main-number digits | Allows the documented phone punctuation and optional trailing `ext`, `ext.`, or `x` followed by 1-10 digits; a leading international `+` must match the narrower formula-safe grammar |
| 10 | Client Email | `client_email` | No | Email, <=254 | Trim, lowercase, RFC-style validation |
| 11 | Opposing Party Name | `opposing_party` | No | Text, 2-255 | Trim; stored on matter |
| 12 | Opposing Counsel | `opposing_counsel` | No | Text, <=255 | Trim; stored on matter |
| 13 | Forum | `forum_level` | Yes* | Controlled enum | Recognized values/aliases normalize case- and separator-insensitively to `lower_court`, `high_court`, `supreme_court`, `tribunal`, `arbitration`, or `advisory` |
| 14 | Court | `court_name` | No | Text, 2-255 | Resolved through existing forum/court selection logic where possible |
| 15 | Court Forum Number | `court_forum_number` | No | Text, <=120 | Trim; stores the court, bench, room, or forum reference independently of Court |
| 16 | Case Number | `case_number` | No | Text, <=120 | Case-insensitive duplicate check within file and visible tenant records |
| 17 | Filing Number | `filing_number` | No | Text, <=120 | Trim; stored and indexed |
| 18 | Filing Date | `filing_date` | No | Date | Accepts documented ISO, year-first, day-first, month-name, and 1900/1904 Excel serial formats; fractional time is discarded |
| 19 | Matter Owner | `assignee_membership_id` | No | Work email | Must resolve to active user in current tenant |
| 20 | Assigned Team | `team_id` | No | Team name or slug | Must resolve to active team in current tenant |
| 21 | Responsible Lawyer | `responsible_lawyer_membership_id` | No | Work email | Must resolve to active user in current tenant |

`*` The source required-field list omitted Forum, but the existing CaseOps matter domain requires `forum_level`. The specification closes that gap by making Forum mandatory rather than inventing a potentially wrong forum during import.

Normal business punctuation is preserved in applicable free-text and reference
fields. Examples include `M/s.`, `&`, apostrophes, commas, parentheses, `#`,
periods, slashes, semicolons, and internal hyphens. In CSV, a field containing
the selected delimiter must use standard CSV double-quote escaping; otherwise
that character is structurally a delimiter, not field data. Punctuation support
does not relax field length/type rules, email validation, duplicate checks,
formula controls, or the Matter Code grammar.

### 7.1 Controlled-value compatibility

Comparison removes case and separator/punctuation differences before resolving
known values. This means `On Hold`, `on-hold`, and `on_hold` resolve to
`on_hold`; `HIGH COURT`, `high-court`, and `high_court` resolve to
`high_court`.

- Status aliases: `active`; `intake`; `on hold`/`hold`; and
  `closed`/`disposed` (recognized but rejected for creation).
- Forum aliases: lower/district/sessions court; high court; Supreme Court or
  Supreme Court of India; tribunal/consumer forum/consumer commission;
  arbitration/arbitral tribunal; and advisory.

### 7.2 Header and layout compatibility

Header matching is case-insensitive and ignores punctuation, whitespace,
slashes, periods, parentheses, `#`, hyphens, and underscores. The canonical
headers remain recommended. Compatibility aliases include:

| Canonical field | Accepted compatibility examples |
|---|---|
| Matter Title | Title, Matter Name, Case Title, Name |
| Matter Code | Code, Matter ID |
| Practice Area | Area of Practice, Area |
| Matter Status | Status, Current Status |
| Client Name | Client, Existing Client, Existing Client Name, Party Name, Client Reference/Ref |
| Client Contact Number | Client Phone, Client Phone No., Phone, Phone No., Phone Number |
| Forum | Forum Level, Court / Forum |
| Court | Court Name, Forum Name |
| Court Forum Number | Court / Forum No., Court No., Forum No., Court/Forum Reference |
| Filing Date | Date of Filing |
| Matter Owner | Owner, Owner Email, Assignee |
| Assigned Team | Team, Team Slug |
| Responsible Lawyer | Responsible Lawyer Email |

The parser scores the first 25 non-empty rows of each XLSX worksheet and chooses
the strongest table candidate, preferring one containing both Matter Title and
Matter Code. The same header-row search applies to CSV, which allows report
titles or metadata above the actual column headings. Source row numbers are
preserved in preview/error output: CSV reports the physical starting line of
each logical record, including quoted multiline records, and XLSX reports its
validated worksheet row reference.

## 8. Validation requirements

### 8.1 File-level validation

- User-facing workflow extensions and MIME families: `.csv` and `.xlsx` only.
- Maximum file size: 2 MB.
- Maximum non-empty data rows: 500.
- Empty file or header-only file is rejected.
- CSV may be UTF-8 (with or without BOM), BOM-marked UTF-16, or Windows-1252.
- CSV delimiter detection supports comma, semicolon, tab, and pipe.
- CSV/XLSX header detection examines the first 25 non-empty rows and recognizes
  case-/punctuation-insensitive canonical headers and documented aliases.
- XLSX must be a readable Open Packaging Convention ZIP with safe XML, use
  stored or Deflate compression only, and have no encryption. Other ZIP
  compression methods are rejected with a validation error.
- XLSX accepts at most 1,000 ZIP entries, 16 MiB per uncompressed entry,
  32 MiB cumulative uncompressed content, and a 250:1 compression ratio for
  entries of at least 1 MiB.
- XLSX workbook and workbook-relationship metadata are limited to 512 KiB
  each. Shared strings are parsed as a stream and bounded to 100,000 entries,
  32,767 characters per entry, and 8,388,608 characters of aggregate text.
- XLSX cell coordinates are bounded to the standard Excel range: columns A-XFD
  (1-16,384) and rows 1-1,048,576. Malformed cell references, coordinates
  outside those bounds, and duplicate or out-of-order worksheet row references
  are rejected.
- XLSX worksheet selection examines workbook order and chooses the sheet/header
  candidate with the strongest recognized-column score, weighted toward Matter
  Title and Matter Code. Instruction/reference sheets are not assumed to be the
  import data simply because they occur first.
- XML DTD/entity expansion is rejected by `defusedxml`.
- The server never executes macros, formulas, external links, or embedded code.
- Source SHA-256 is persisted for forensic correlation and retry diagnosis.

### 8.2 Mandatory fields

Every production preview row requires:

1. Matter Title.
2. Matter Code.
3. Practice Area.
4. Forum (gap closure required by the Matter model).

Client Name is optional. Matter Status is optional and defaults to `active` in
both production preview and the backward-compatible `/imports/dry-run`
endpoint. A supplied `closed`/`disposed` status remains invalid for creation.

### 8.3 Duplicate detection

- Matter Code duplicated within the uploaded file: invalid.
- Case Number duplicated within the uploaded file: invalid when nonblank.
- Matter Title + Client Name duplicated within the file: invalid.
- Matter Code matching a visible current-tenant matter: invalid.
- Case Number matching a visible current-tenant matter: invalid.
- Matter Title + Client Name matching a visible current-tenant matter: invalid duplicate candidate.
- Duplicate checks never cross tenant boundaries.
- Ethical-wall filtering prevents the preview from exposing a walled matter’s identity. The database-level matter-code constraint still prevents creation; the commit row records a non-disclosing conflict.
- Commit re-runs duplicate checks immediately before creation so a race after preview cannot silently duplicate a matter.

### 8.4 Data-format and reference validation

- Matter Code uses the shared CaseOps create/update/import grammar: trim,
  uppercase, 2-80 characters, alphanumeric at both ends, and only A-Z, 0-9,
  and internal hyphens. Spaces, underscores, slashes, and other punctuation are
  invalid.
- Status and forum comparisons are case-insensitive and ignore presentation
  separators such as spaces, hyphens, and underscores; aliases normalize to
  canonical enum values.
- Status must be an allowed operational creation status; disposed/closed creation is rejected.
- Practice Area is required but is not catalog-gated. Known standard,
  established tenant, or active practice-area team values are canonicalized;
  other valid 2-120 character labels are preserved.
- Email must be valid and at most 254 characters.
- Phone main number must contain 7-20 digits and may have a trailing `ext`,
  `ext.`, or `x` followed by 1-10 digits. Without a leading `+`, supported punctuation is spaces,
  parentheses, periods, commas, `#`, hyphens, slashes, and `&`. A value
  beginning with exactly one international `+` is formula-safe only when the
  main number uses digits, spaces, parentheses, and hyphens; `+` anywhere else
  is invalid.
- Filing date accepts ISO dates/timestamps, `YYYY/MM/DD`, `YYYY.MM.DD`,
  day-first `DD/MM/YYYY`, `DD-MM-YYYY`, and `DD.MM.YYYY` (four- or two-digit
  year where documented), day-first abbreviated/full English month names, and
  valid Excel serial dates. XLSX uses the workbook's declared 1900 or 1904 date
  system; numeric serials outside XLSX use 1900 because no workbook metadata is
  present. Fractional serials are accepted and their time-of-day fraction is
  discarded.
- Forum must be a supported CaseOps forum level.
- Matter Owner and Responsible Lawyer must be active users of the current company.
- Assigned Team must be active and belong to the current company.
- If team scoping is enabled, an assigned owner/responsible lawyer must belong to the assigned team.
- Cross-tenant IDs are never accepted from the file or client request.

### 8.5 Spreadsheet-injection controls

- Actual XLSX formula nodes in the selected import header/data cells are
  invalid, even if cached text exists. Ignored report rows and nonselected
  worksheets are never evaluated or imported.
- In the selected import table, text whose first non-space character is `=`,
  `-`, `@`, or an unsafe `+` form is invalid.
- A `+`-prefixed phone is allowed only in Client Contact Number and only when it
  matches the narrower grammar in section 8.4.
- Stored raw rows replace unsafe formula values with `[unsafe formula removed]`.
- Error-report cells beginning with formula control characters receive a leading apostrophe.
- Relaxed punctuation, header, encoding, delimiter, and controlled-value
  compatibility never bypasses these controls.

## 9. Workflow and state model

### 9.1 User flow

1. User opens Matter portfolio.
2. User selects **Bulk upload matters**.
3. User downloads XLSX (recommended) or CSV template.
4. User populates one row per matter in the canonical template or a documented compatible client register.
5. User uploads file.
6. System parses safely, validates all rows, creates a persistent job, emits upload/validation notification, and displays summary.
7. User reviews errors. Invalid rows do not block import of other valid rows.
8. User either corrects and re-uploads, cancels, or confirms import.
9. On confirmation, system checks 24-hour expiry, revalidates currently valid rows, atomically claims the job, and creates each still-valid row using the normal matter-creation service.
10. System records each created/failed row, finalizes counts/status, emits completion notification, refreshes Matter portfolio, and exposes the final error report/history.

### 9.2 Job states

| State | Meaning | Allowed transition |
|---|---|---|
| `validated` | Preview persisted; may contain valid and invalid rows | `importing`, `cancelled`, `expired` |
| `importing` | One request has claimed commit | `completed`, `completed_with_errors`, `failed` |
| `completed` | Every row was created successfully | Terminal; repeat commit returns same result |
| `completed_with_errors` | At least one invalid or runtime-failed row | Terminal; error report available |
| `cancelled` | User cancelled before commit | Terminal |
| `failed` | Job-level unrecoverable failure | Terminal; details remain redacted |
| `expired` | Preview exceeded 24 hours | Terminal; re-upload required |

### 9.3 Row states

| State | Meaning |
|---|---|
| `valid` | Passed preview/commit revalidation and is eligible for creation |
| `invalid` | Validation errors; not created |
| `created` | Matter created and linked by `created_matter_id` |
| `failed` | Passed validation but creation failed due to a commit-time business/runtime condition |

### 9.4 Partial-success policy

The source explicitly requires successful and failed record counts in a single import and says the system creates all valid matters. Therefore confirmation is not all-or-nothing across the file:

- every row is independently accountable;
- invalid rows are retained and skipped;
- every still-valid row is attempted;
- successful rows remain committed if a later row fails;
- final `failed_count = total_rows - created_count`;
- the error report covers both invalid and runtime-failed rows.

This policy avoids throwing away 95 valid matters because 5 rows require correction while preserving a complete failure ledger.

## 10. User interface requirements

### 10.1 Matter portfolio

- Show **Bulk upload matters** only when `matters:bulk_import` resolves true.
- Keep **New matter** independent; a user may hold either or both permissions.
- Selecting the action navigates to `/app/matters/imports`.

### 10.2 Dedicated import page

- Page title: **Bulk upload matters**.
- Template panel with XLSX and CSV actions.
- Upload control restricted to CSV/XLSX.
- Selected file name and approximate size.
- Compatibility guidance explains optional Client Name/Status, default Active,
  accepted value/header variants, and the strict Matter Code/formula controls.
- Primary action: **Validate data before import**.
- Summary metrics: Total Records, Valid, Validation Errors, Imported, Failed.
- Status, file name, confirm, cancel, and error-report actions.
- Row table with row number, matter code, title, client, Court Forum Number, row status, and all errors.
- Invalid rows appear first; first 50 additional valid rows appear next; hidden-row count is disclosed.
- Confirmation label includes the number of valid rows.
- Success/failure toast communicates result counts.

### 10.3 Import history

- Search input supports file name, uploader name, and uploader email.
- Status filter supports every job state.
- Table columns: Upload Date, File Name, Uploaded By, Status, Records, Imported, Failed.
- The UI never exposes another tenant’s jobs.

### 10.4 Import summary example

For a 100-row file where 95 rows are created and 5 are invalid/failed:

- Total Records: 100.
- Successfully Imported: 95.
- Failed Records: 5.
- Validation Errors: the total count of validation messages across affected rows.
- Final status: `completed_with_errors`.

## 11. Error report

- Format: UTF-8 CSV with BOM for Excel compatibility.
- Filename: `matter-import-errors-{job_id}.csv`.
- Columns:
  1. Row Number.
  2. Matter Code.
  3. Matter Title.
  4. Status.
  5. Errors.
- Errors are semicolon-separated within the CSV cell.
- Example reasons include a missing required title/code/practice area/forum,
  duplicate matter code, duplicate case number, malformed/out-of-range field,
  invalid status/forum/date/email, unknown user/team, unsafe formula-like value,
  strict Matter Code violation, and stale commit conflict.
- The download itself is audited using counts only.

## 12. History and audit trail

### 12.1 Persisted history fields

- Job ID.
- Company ID.
- Created/uploaded by membership ID.
- File name.
- Content type and manifest format.
- File size.
- SHA-256 fingerprint.
- Status.
- Total, valid, invalid, created, failed, and validation-error counts.
- Redacted job error.
- Upload, update, expiry, import, and cancellation timestamps.
- Sanitized raw row, normalized row, row errors, row status, and created matter ID.

### 12.2 Audit events

| Event | When | Minimum metadata |
|---|---|---|
| `matter.import.validated` | Preview persisted | format, size, hash, row/error counts |
| `matter.import.row_created` | One matter created | job target, row number, matter ID |
| `matter.import.completed` | Commit finalized | total, created, failed, validation-error count, status |
| `matter.import.cancelled` | Preview cancelled | total rows |
| `matter.import.error_report_downloaded` | Error CSV downloaded | error-row count |
| `matter.created` | Existing normal matter-creation audit | matter metadata and actor |

Audit metadata excludes uploaded descriptions, client contact details, and other row payloads. The persisted import-row tables remain tenant-scoped operational data subject to the platform’s normal database controls.

## 13. Notifications

| Event type | Trigger | Recipient | Message content |
|---|---|---|---|
| `matter_import.upload_succeeded` | File parsed and validation job saved | Uploader | File and checked row count |
| `matter_import.validation_failed` | One or more invalid rows | Uploader | Invalid/total row counts |
| `matter_import.completed` | Commit finalized | Uploader | Created and failed counts |

Notification intents use existing idempotency rules keyed by tenant, recipient, channel, event, source type, and job ID. Repeated operations cannot enqueue duplicate notifications of the same type for the same job.

## 14. Data model and API contract

### 14.1 Matter extensions

The Matter record gains:

- `matter_type`.
- `client_code`.
- `client_contact_number`.
- `client_email`.
- `opposing_counsel`.
- `court_forum_number`.
- `filing_number` (indexed).
- `filing_date`.
- `responsible_lawyer_membership_id` (tenant membership FK, indexed).

Existing fields provide title, code, client name, opposing party, description, status, practice area, forum/court, case number, matter owner (`assignee_membership_id`), and assigned team (`team_id`).

`court_forum_number` is nullable, limited to 120 characters, and round-trips
through ordinary Matter create/read/update APIs as well as bulk import. It is
not a synonym for `court_name`.

### 14.2 Import tables

- `matter_bulk_import_jobs`: one row per upload/validation lifecycle.
- `matter_bulk_import_rows`: one row per non-empty source record, unique by job and source row number.
- Tenant IDs and foreign keys are stored on both tables for explicit scoping and cleanup.

### 14.3 Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/matters/imports/template?format=xlsx|csv` | Download template |
| POST | `/api/matters/imports/preview` | Upload, validate, persist preview |
| GET | `/api/matters/imports/history` | Search/filter tenant history |
| GET | `/api/matters/imports/{job_id}` | Read one job and rows |
| POST | `/api/matters/imports/{job_id}/commit` | Confirm and create valid matters |
| POST | `/api/matters/imports/{job_id}/cancel` | Cancel validated preview |
| GET | `/api/matters/imports/{job_id}/errors` | Download error CSV |
| POST | `/api/matters/imports/dry-run` | Backward-compatible ADP-11 planning endpoint |

Every endpoint uses the server-side `matters:bulk_import` capability gate and tenant-scoped queries.

## 15. Security, privacy, and abuse controls

- Server authorization is authoritative; UI gating is only a usability layer.
- Tenant ID comes exclusively from authenticated session context.
- Job IDs from another tenant return 404.
- People and team references must belong to the authenticated tenant.
- Ethical-wall filters apply to duplicate-candidate detail.
- Upload byte and row limits bound memory/CPU use.
- CSV decoding/dialect detection, XLSX ZIP/XML parsing, worksheet/header
  selection, XML entity rejection, and formula rejection are explicit and
  bounded.
- The XLSX parser reads values only and never invokes Microsoft Excel.
- Error-report CSV is spreadsheet-injection safe.
- Source payload is not stored as an uploaded binary; only fingerprint, metadata, sanitized raw rows, and normalized values are retained.
- API errors expose actionable validation details but redact unexpected runtime failures.
- Job claim uses a conditional state update to prevent two concurrent commit requests.
- Completed commit is idempotent.
- Each matter, its activity/audit records, and its import-row outcome commit in one database transaction; a crash cannot leave a created matter behind a still-pending row.
- An `importing` job receives a heartbeat after every row. If no heartbeat is recorded for ten minutes, an authorized retry can reclaim the stale job and resume only rows that are still `valid`; already-created rows are never replayed.
- PostgreSQL transaction-scoped advisory locking serializes same-tenant/same-case-number creation and updates across the ordinary API and bulk import, closing the application-level duplicate-check race.

## 16. Reliability and failure recovery

- Preview remains valid for 24 hours.
- Commit-time revalidation protects against stale duplicate/user/team/practice-area state.
- Conditional `validated -> importing` update prevents concurrent double commit.
- Each successful matter uses the established matter-creation service and is committed with its normal side effects/audit.
- Per-row outcomes are persisted after creation; later failures do not erase earlier successes.
- A repeated commit on `completed` or `completed_with_errors` returns the original terminal result.
- Cancellation and expiry are terminal.
- Import history and row records survive browser refresh or workstation restart.

## 17. Non-functional requirements

### 17.1 Performance

- Up to 500 rows and 2 MB per job.
- Preview should normally finish within 10 seconds for 500 rows on production-sized infrastructure, excluding network transfer.
- The UI must remain responsive and cap the on-screen valid-row list at 50 while retaining every row server-side.

### 17.2 Accessibility

- Every input has a programmatic label.
- Buttons expose text, not icon-only meaning.
- Status is communicated by text in addition to color.
- Tables use header cells and remain horizontally scrollable.
- Keyboard Enter applies import-history search.

### 17.3 Compatibility

- UTF-8 (with/without BOM), BOM-marked UTF-16, and Windows-1252 CSV.
- Comma-, semicolon-, tab-, and pipe-delimited CSV.
- Office Open XML `.xlsx` without macros.
- Header rows within the first 25 non-empty rows and import data on any
  worksheet, using canonical headings or documented aliases.
- Standard XLSX A-XFD column and 1-1,048,576 row coordinates, subject to the
  archive and upload bounds in section 8.1.
- Case-/separator-insensitive recognized status and forum values.
- ISO/year-first/day-first/month-name and fractional 1900/1904 Excel-serial
  filing dates.
- Business punctuation in applicable text/reference and phone fields.
- Current supported browsers in the CaseOps web application.
- SQLite migration replay for local/test and PostgreSQL for production.

### 17.4 Observability

- Audit events provide tenant, actor, target, result, and timestamps.
- Job counters support operational dashboards and failure-rate monitoring.
- Source hash correlates retries without retaining the original binary.
- Unexpected row failures are redacted in user response but remain discoverable through server logs/traces under existing observability policy.

## 18. Gap decisions and rationale

| Source gap/ambiguity | Resolution |
|---|---|
| “Forum” listed as a field but not mandatory, while Matter requires it | Forum is mandatory in production preview |
| Client Name marked mandatory in the earlier interpretation | Optional, matching the Matter domain and client files that legitimately omit it |
| Matter Status missing in client exports | Optional; normalize recognized variants and default a blank value to `active` |
| Court name and court/forum number were conflated | Add a distinct optional 120-character Court Forum Number field after Court |
| Whether invalid rows block all valid rows | Partial success; source explicitly asks for successful and failed counts |
| Duplicate comparison scope/case | Case-insensitive within current tenant; blanks ignored |
| Existing walled matter duplicates | Do not expose candidate; database/service conflict still prevents write |
| Matter Manager absent from fixed role enum | Dedicated delegable capability via tenant custom role |
| Date format varies across spreadsheets | ISO recommended; compatible year-first, Indian day-first, month-name, ISO timestamp, and fractional 1900/1904 Excel serial values also accepted; time-of-day is discarded |
| Phone format varies across business registers | Preserve the documented business punctuation and an optional trailing `ext`, `ext.`, or `x` followed by 1-10 digits; validate 7-20 main-number digits; require the narrower formula-safe grammar for a leading `+` |
| Practice-area catalogue does not cover every client | Canonicalize a known standard/tenant/team value, but preserve any other valid 2-120 character practice-area label |
| Client files use different encodings and delimiters | Accept UTF-8, BOM-marked UTF-16, or Windows-1252 and detect comma, semicolon, tab, or pipe |
| Client workbooks contain title rows/instructions and reordered sheets | Score the first 25 non-empty rows on every worksheet and choose the strongest recognized header candidate |
| Client headers contain punctuation or familiar synonyms | Compare case-insensitively after removing presentation punctuation and support documented aliases |
| Relaxed compatibility could weaken identifiers/security | Keep the shared Matter Code grammar and formula/formula-like value rejection strict |
| Owner/responsible lawyer identifiers unspecified | Active tenant work email |
| Team identifier unspecified | Active tenant team name or slug |
| Commit idempotency unspecified | Job ID is the idempotency boundary; terminal repeat is read-only |
| Process interruption unspecified | Atomic matter/row transaction plus ten-minute stale heartbeat recovery; completed rows are skipped |
| Concurrent duplicate case-number writes unspecified | Tenant/case-number advisory transaction lock on PostgreSQL |
| Preview lifetime unspecified | 24 hours; stale jobs require re-upload |
| Notification channel unspecified | Durable in-app notification intents using existing provider governance |
| Binary file retention unspecified | Do not store original binary; retain hash and sanitized row data |
| Error-report format says downloadable but not CSV/XLSX | UTF-8 CSV for portability and safe generation |

## 19. Acceptance criteria

### 19.1 Functional

- AC-001: Authorized user can download CSV and XLSX templates containing all 21 canonical headers, with Court Forum Number immediately after Court.
- AC-002: XLSX includes separate reference and instruction sheets.
- AC-003: CSV/XLSX upload creates no matters before confirmation.
- AC-004: Summary shows total, valid, invalid, imported, failed, and validation-error counts.
- AC-005: Missing title/code/practice area/forum produces row errors; blank Client Name is accepted and blank Matter Status normalizes to `active`.
- AC-006: Duplicate code, case number, and title+client are detected within file and visible tenant records.
- AC-007: Invalid date/email/status/forum or an out-of-range practice-area label produces row errors.
- AC-008: Unknown/inactive/cross-tenant owner, responsible lawyer, or team is rejected.
- AC-009: Confirmation creates every still-valid row and no invalid row.
- AC-010: A mixed job ends `completed_with_errors` with correct counts.
- AC-011: Error report includes each invalid/failed source row and every error.
- AC-012: History search/filter and required metadata work.
- AC-013: Upload-success, validation-failure, and completion notification intents are recorded.
- AC-014: Audit events cover validation, created rows, completion, cancellation, and report download.
- AC-015: Owner/Admin and delegated Matter Manager are allowed; Viewer/read-only is denied.
- AC-016: Court Forum Number is previewed and round-trips independently through bulk commit and ordinary Matter create/read/update.
- AC-017: Recognized status/forum values normalize regardless of case and common space/hyphen/underscore separator differences.
- AC-018: A valid non-catalog practice area and normal business punctuation in applicable text/reference/phone fields are preserved under their field-specific grammar and CSV quoting rules.
- AC-019: UTF-8, BOM-marked UTF-16, and Windows-1252 CSV with comma, semicolon, tab, or pipe delimiters are parsed consistently.
- AC-020: An XLSX import table may occur on a later worksheet, have title rows above its header, use documented aliases, and supply any documented compatible filing-date representation.

### 19.2 Safety and regression

- AC-021: Other-tenant job access returns 404.
- AC-022: XML entities, formula nodes in the selected XLSX import header/data cells, and formula-like selected-table text are rejected without evaluation; only a Client Contact Number matching the narrower leading-`+` grammar is exempt.
- AC-023: Error CSV cannot execute a source formula.
- AC-024: Matter Code retains the shared 2-80 character, alphanumeric-ended, letters/digits/internal-hyphens-only grammar.
- AC-025: Commit revalidation detects a matter created after preview.
- AC-026: Repeating terminal commit creates no additional matter.
- AC-027: Normal single-matter creation and legacy ADP-11 dry-run remain operational.
- AC-028: SQLite migration replay reaches head; PostgreSQL constraints/indexes compile in CI.

## 20. Test and traceability matrix

| Requirement group | Automated evidence |
|---|---|
| Templates | API 21-column workbook/CSV tests, including Court Forum Number order; web download action test |
| Full field set | API preview/commit/read round-trip test; ordinary Matter create/read/update Court Forum Number test |
| Optional/default fields | API blank Client Name and blank Matter Status/default-Active tests |
| Controlled/free business values | Case/separator-normalization, status/forum alias, non-catalog practice area, and punctuation-preservation API tests |
| CSV compatibility | Encoding (UTF-8/UTF-16/Windows-1252), delimiter (comma/semicolon/tab/pipe), title-row, and header-alias API tests |
| XLSX compatibility | Later-worksheet selection, first-25-row header detection, aliases, physical row-number preservation, Excel coordinate/archive bounds, and compatible date API tests including fractional 1900/1904 serials |
| Mandatory/format/reference validation | API invalid/partial-success tests, including strict shared Matter Code grammar and required title/code/practice area/forum |
| Duplicate and staleness | API tenant duplicate and commit-time revalidation tests |
| Partial success/idempotency | API terminal status/count and repeat-commit tests |
| History/error report | API search and CSV-content tests; web history search test |
| Spreadsheet safety | Selected-table XLSX formula-node/formula-like cell rejection, narrow safe international-phone exception, sanitized persistence, and formula-safe error CSV tests |
| Notifications/audit | Database assertion tests against delivery intent/audit tables |
| Permissions | Owner, Viewer, delegated Matter Manager, and tenant-isolation tests |
| Legacy regression | Existing `test_matter_imports.py` dry-run/security tests |
| Web workflow | Vitest portfolio navigation, validation table, confirm, and history tests |
| Browser E2E | Playwright local production-like upload, validation, commit, portfolio visibility, history, and report download |

The exact commands, case IDs, result counts, and production evidence must be
recorded in the dated compatibility guide and final delivery artifact after the
verification run. This PRD does not pre-claim those results.

## 21. Release and rollback

### 21.1 Release sequence

1. Apply the database migration that adds nullable `court_forum_number`.
2. Deploy the API compatibility parser, Matter contracts, and existing import endpoints.
3. Deploy the web UI, in-product guide, and generated OpenAPI types.
4. Smoke-test Owner/Admin permissions and both 21-column template downloads.
5. Run non-mutating health/revision checks, then a controlled production import
   using unique, non-sensitive test data that covers blank Client Name/Status,
   non-catalog Practice Area, normalized Forum, business punctuation, and Court
   Forum Number.
6. Verify the created Matter, history, audit, notifications, partial-success
   error report, and formula/Matter Code rejection behavior.
7. Record exact revision, traffic, commands, results, timestamps, and cleanup in
   the dated validation guide and final delivery artifact.

### 21.2 Rollback

- Hide/remove the web entry point first if an incident occurs.
- Keep import job/history tables intact for investigation.
- API can deny `matters:bulk_import` while normal Matter creation remains available.
- Database downgrade is reserved for pre-production because dropping the import tables or new Matter fields destroys captured data.

## 22. Documentation deliverables

- This PRD.
- Bulk matter validation compatibility implementation/validation guide dated 23 July 2026.
- Updated ADP 01-19 end-user product guide.
- Updated in-product `/guide` content.
- Updated API README endpoint documentation.
- Generated OpenAPI TypeScript contract.
- Regression tests and Playwright scenario.
- Final implementation/test-results artifact in the user-specified Downloads
  folder, completed only after automated and production validation evidence is
  available.
