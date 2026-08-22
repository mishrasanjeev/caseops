# Shared bulk-import compatibility contract

## Purpose

CaseOps has three import owners with different persistence and commit logic:

| Domain | Canonical job owner | Canonical workflow |
|---|---|---|
| Trademark portfolio | `bulk_import_jobs` plus `ip_import_rows` | `/app/ip/portfolio/imports` |
| Matters | `matter_bulk_import_jobs` plus `matter_bulk_import_rows` | `/app/matters/imports` |
| Employees | `employee_bulk_import_jobs` plus `employee_bulk_import_rows` | `/app/admin/employees` |

The shared contract provides one read surface over those owners. It does not
move, copy, alias, dual-write, commit, cancel, retry, or otherwise mutate a
canonical job. Domain services remain the only writers.

## API

All routes are authenticated and tenant-scoped.

| Route | Result |
|---|---|
| `GET /api/imports/history` | Newest accessible jobs across owners; optional `domain` and bounded `limit` filters |
| `GET /api/imports/{domain}/{job_id}` | One normalized job summary |
| `GET /api/imports/{domain}/{job_id}/manifest` | Stable manifest envelope, source metadata, and explicit legacy limitations |
| `GET /api/imports/{domain}/{job_id}/errors` | UTF-8 CSV with normalized row number, status, errors, and created-record reference |

The response preserves both `source_status` and normalized `status`.
Normalization is presentation-only:

| Source state | Shared state |
|---|---|
| `previewed`, `validated` | `preview_ready` |
| `committing`, `importing` | `in_progress` |
| `committed`, `completed` with no failed rows | `committed` |
| `committed`, `completed`, or `completed_with_errors` with failed rows | `committed_with_errors` |
| `failed`, `cancelled`, `expired` | unchanged |

Each response also identifies `source_owner` and `read_only_adapter`, so a
consumer never mistakes a compatibility view for a migrated record.

## Authorization and disclosure

- Trademark history requires `ip:read` and retains the canonical creator-only
  visibility rule.
- Matter history requires `matters:bulk_import` and retains tenant-wide job
  visibility for authorized importers.
- Employee history requires `company:manage_users` and retains tenant-wide job
  visibility for user managers.
- The unfiltered history response includes only domains the actor can access.
- Asking for a domain without its capability returns `403`.
- An unknown, foreign-tenant, or otherwise invisible job returns the same `404`.
- Manifest and error-report routes repeat the same authorization and job lookup;
  a URL from another tenant does not bypass the list policy.

## Legacy limitations

Matter jobs persist file format, size, and SHA-256 input checksum. Employee jobs
persist file type and size but predate input-checksum storage. The shared
employee manifest therefore returns `source_sha256: null` and the explicit
limitation `Legacy employee jobs did not persist an input checksum.` It does not
fabricate a digest from unavailable bytes.

## User workflow

`/app/imports` is a read-only activity view. It shows accessible jobs, normalized
status and counts, creator and creation time, manifest detail, and error-report
download. Every row links to the existing domain workflow for any write action.
There is no shared uploader and no cloned commit/cancel/retry control.

## Operations and rollback

This feature adds no table, column, migration, backfill, scheduled job, provider
call, external message, filing, payment, or legal effect. Rollback consists of
removing the additive `/api/imports` router, `/app/imports` page, and navigation
entry. Canonical import data and workflows remain untouched before, during, and
after rollback.
