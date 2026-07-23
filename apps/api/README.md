# CaseOps API

This service hosts the CaseOps backend APIs. The initial skeleton includes:

- application settings bootstrap
- health and metadata routes
- a root router for future module expansion
- test coverage for startup and health behavior

## Run Locally

```powershell
cd ..\..
docker compose up postgres valkey

cd apps\api
uv sync
uv run uvicorn caseops_api.main:app --reload --app-dir src
```

CaseOps local API runtime is Postgres-first. Use `CASEOPS_DATABASE_URL` to point at a Postgres 17 + `pgvector` instance, not SQLite, for normal local development and seeded data work.

## Bulk Matter Creation

The base workflow is in production. The 23 July 2026 compatibility revision
documented in this section is a release candidate whose targeted API, full web,
production-build, and local browser E2E evidence is green. Full CI and
production deployment evidence remain pending in the dated validation guide
linked below.

The production matter import workflow is tenant-scoped and capability-gated by
`matters:bulk_import` (Owner/Admin by default; delegable to a custom Matter
Manager role). In this compatibility revision, the generated CSV/XLSX template
contains 21 columns. **Court** stores the court/forum name, while the distinct
optional **Court Forum Number** stores a court, bench, room, or forum reference
such as `Court #7 / Bench-A`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/matters/imports/template?format=xlsx|csv` | Download the controlled template |
| `POST` | `/api/matters/imports/preview` | Validate and persist a CSV/XLSX preview |
| `GET` | `/api/matters/imports/history` | Search tenant import history |
| `GET` | `/api/matters/imports/{job_id}` | Read job summary and row results |
| `POST` | `/api/matters/imports/{job_id}/commit` | Revalidate and create every valid row |
| `POST` | `/api/matters/imports/{job_id}/cancel` | Cancel an uncommitted preview |
| `GET` | `/api/matters/imports/{job_id}/errors` | Download formula-safe error CSV |

Limits are 2 MB and 500 non-empty data rows. Preview jobs expire after 24
hours; completed commit is idempotent. Matter creation and its import-row outcome
commit atomically. An `importing` job with no heartbeat for ten minutes can be
resumed safely, and PostgreSQL serializes concurrent same-tenant case-number
creation. See
[the Bulk Matter Creation PRD](../../docs/PRD_BULK_MATTER_CREATION_2026-07-17.md)
for the full field, validation, security, state-machine, and partial-success
specification.

The web workflow and persistent preview API use CSV/XLSX. JSON row-array/object
support remains available only through the legacy
`/api/matters/imports/dry-run` planning endpoint; it cannot be committed.

Only Matter Title, Matter Code, Practice Area, and Forum are mandatory. Client
Name is optional. Matter Status is optional and defaults to `active`. A supplied
practice area may be a catalog/team value or any valid 2-120 character business
label; known values are canonicalized and non-catalog values are retained.
Client Email, when supplied, must be a valid address of at most 254 characters.
Status and forum inputs are case-insensitive, and spaces, hyphens, underscores,
and other punctuation used as separators do not change a recognized value.
Examples include `On Hold`, `on-hold`, `HIGH COURT`, and `high_court`.

The compatibility parser accepts:

- CSV encoded as UTF-8 (with or without BOM), BOM-marked UTF-16, or
  Windows-1252, with comma, semicolon, tab, or pipe delimiters;
- a header row within the first 25 non-empty rows, with case- and
  punctuation-insensitive aliases such as `Matter Name`, `Matter ID`, `Area of
  Practice`, `Current Status`, `Existing Client Name`, `Court / Forum`,
  `Client Phone No.`, `Date of Filing`, and `Court / Forum No.`; CSV preserves
  each logical record's physical starting line and XLSX preserves its validated
  worksheet row reference;
- XLSX workbooks whose import table is not the first worksheet; the parser
  selects the worksheet/header candidate that best matches Matter Title and
  Matter Code plus the other recognized columns; and
- ISO dates/timestamps, `YYYY/MM/DD`, `YYYY.MM.DD`, common day-first numeric or
  month-name dates, and fractional Excel serial dates. XLSX follows its
  workbook's declared 1900/1904 date system; numeric serials outside XLSX use
  1900. The time-of-day fraction is discarded because Filing Date stores a
  calendar date.

Delimiter characters inside CSV fields must use standard CSV quoting. Normal
legal/business punctuation is then preserved in text/reference fields and in
phone numbers. Phone values may contain spaces, parentheses, periods, commas,
`#`, hyphens, slashes, `&`, and a trailing `ext`, `ext.`, or `x` followed by
1-10 digits; the main number must contain 7-20 digits. A value that begins with
one international `+` uses the narrower formula-safe phone grammar: digits,
spaces, parentheses, and hyphens before the same optional extension. A `+`
anywhere else is invalid.

XLSX parsing accepts standard Excel coordinates only: columns A-XFD
(1-16,384) and rows 1-1,048,576. Malformed cell references, coordinates outside
those bounds, and duplicate or out-of-order worksheet row references are
rejected. Archive limits are 1,000 entries, 16 MiB per uncompressed entry,
32 MiB total uncompressed content, and 250:1 compression for entries of at
least 1 MiB. Only stored and Deflate ZIP compression are accepted; encrypted
workbooks and other ZIP compression methods are rejected. Workbook and workbook-
relationship metadata are limited to 512 KiB each. Shared strings are streamed
and bounded to 100,000 entries, 32,767 characters per entry, and 8,388,608
characters of aggregate text.

Two controls intentionally remain strict:

- Matter Code uses the same grammar as ordinary matter creation: after trimming
  and uppercasing, it must be 2-80 characters, start and end with a letter or
  digit, and contain only letters, digits, and internal hyphens. Spaces,
  underscores, slashes, and other punctuation are rejected.
- Formula nodes in the selected XLSX import header/data cells and formula-like
  selected-table text beginning with `=`, `+`, `-`, or `@` are rejected and
  sanitized. The only leading-`+` exception is a value matching the narrower
  international phone grammar in Client Contact Number. Downloaded error CSV
  remains formula-safe.

The dated compatibility contract and release-evidence checklist are in the
[23 July implementation and validation guide](../../docs/BULK_MATTER_VALIDATION_COMPATIBILITY_IMPLEMENTATION_AND_VALIDATION_GUIDE_2026-07-23.md).

## Document Worker

```powershell
uv sync
uv run caseops-document-worker --once
```

Continuous polling mode:

```powershell
uv run caseops-document-worker
```

## Cloud Runtime Notes

- use `CASEOPS_DOCUMENT_STORAGE_BACKEND=gcs` in Cloud Run
- point `CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET` at the tenant document bucket
- set `CASEOPS_DOCUMENT_STORAGE_CACHE_PATH=/tmp/caseops-document-cache` for ephemeral cache materialization
- keep `CASEOPS_TESSERACT_COMMAND=/usr/bin/tesseract` in the container runtime if OCR is enabled
