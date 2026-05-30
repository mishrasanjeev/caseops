# Bug Reopen Learnings - 2026-05-30

Source: `caseOps bugs_hari30May2026.xlsx`.

## Where I Went Wrong

1. I treated feature presence as proof. Case Tracking had a page, API routes, bookmark models, and notification rows, but the actual provider contract was wrong and production config still left search unusable.
2. I accepted a disabled input as a safe provider gate. That blocked users from typing and made the UI appear broken before it ever reached the provider. The correct gate is on submit/provider calls, not on text entry.
3. I guessed external API paths and payload shape. The eCourtsIndia adapter used `/cases/search` and a flat payload while the documented partner API is under `/api/partner` and can return nested `data`, `courtCaseData`, `entityInfo`, and enum lookup structures.
4. I counted scripts as automation. `caseops-sync-legal-updates` and `caseops-poll-tracked-cases` existed, but Cloud Run jobs and Cloud Scheduler triggers were not wired. Production automation did not exist until deployment manifests did.
5. I left a removed product module visible. Judgment Alerts still rendered inside Research after the product scope said it should not be there, and it also issued background alert queries.
6. I treated the first CI lock failure as a wait-time problem. The full Playwright suite proved the deeper issue: SQLite test runs need both WAL and explicit write serialization, and setup must delete WAL/SHM sidecars when resetting the database.

## Permanent Rules

- Every external provider adapter must have regression tests for documented URLs, auth path, query parameter names, nested sample payloads, date parsing, and source download URLs.
- Provider-unconfigured UI must keep fields editable and clearly disable only the action that would call the provider.
- A background workflow is not complete until the deploy path creates or updates the job and its scheduler trigger.
- Feature removal means no visible UI, no route-level fetches, and no background calls from the removed module.
- For every reopened bug, add a Playwright regression that checks the user-visible workflow, not only the component or API unit path.
- CI-only database-lock failures must be fixed at the transaction/isolation layer and rerun in the same suite shape that failed, not only with a single focused spec. When WAL is enabled, test reset must remove `*.db`, `*.db-wal`, and `*.db-shm` together.

## Adjacent Audit Added

- Case Tracking schema now accepts a general `query` field for party/name/advocate search.
- The eCourtsIndia adapter now calls `/api/partner/search`, `/api/partner/case/{caseId}`, and `/api/partner/case/bulk-refresh`.
- eCourts nested payload normalization now covers `data.results`, `data.courtCaseData`, petitioner/respondent title synthesis, enum status/court lookup, ISO date strings, interim orders, and judgment orders.
- Production Cloud Run manifests now include nightly legal update sync and tracked-case polling jobs.
- Research no longer renders the Judgment Alerts submodule.
- SQLite test engines now enable WAL, a pinned busy timeout, ORM write serialization, and E2E sidecar cleanup so full-suite Playwright bootstrap writes are not blocked by concurrent local SQLite traffic.
