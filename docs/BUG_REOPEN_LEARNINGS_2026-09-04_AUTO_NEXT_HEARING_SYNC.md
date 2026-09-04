# Automatic next-hearing sync — 2026-09-04 assessment and permanent learnings

## Source classification

`CaseOps_AI_Auto_Next_Hearing_Date_Sync.docx` is one valid product enhancement
with linked correctness defects in the existing case-tracking implementation.
It is not a list of separate bugs. The existing product already had an eCourts
adapter, tracked cases, a manual Sync Now path, a poll job, audit records, and a
single Next hearing field. The requested automatic workflow was incomplete.

## Brutal root-cause analysis

The prior implementation was shallow in six specific ways:

1. The product requirement and deployment contract had diverged. Production
   was scheduled for 16:30 IST while the requested time is 18:00 IST, and the
   runtime window ended at 18:00. Moving only the cron would therefore have
   deployed a job that immediately blocked itself.
2. “Automatic” meant “poll bookmarks.” New matters could be linked during
   creation, but older eligible matters were never discovered. The feature was
   dependent on when provider configuration happened rather than matter data.
3. Case-number fallback accepted `results[0]`. That is not verification; it can
   write one case's hearing date onto another matter when courts reuse case
   numbers or provider search ordering changes. Non-CNR identity also collapsed
   missing court codes to `court:UNKNOWN`.
4. The provider's one next-date field was copied without resolving hearing
   history, rejecting past dates, or distinguishing a confirmed empty docket
   from a failed or unrecognized payload. A failure could erase or corrupt the
   last valid operational date.
5. A verified provider change could be diverted into a human suggestion queue,
   while simultaneous scheduled and manual refreshes had no database-level
   single-writer invariant. That combined unnecessary approval friction with
   insufficient machine safety.
6. A case-number row could learn a CNR already owned by another canonical row.
   Snapshot application blindly changed the unique identity key, causing a
   PostgreSQL uniqueness violation; the error handler then queried through the
   failed transaction and crashed the entire multi-tenant poll. Focused SQLite
   tests did not expose this identity-promotion collision. The full Docker
   inventory did, which is why the first release candidate was rejected.
7. The first post-deploy verification exposed two test-harness assumptions:
   an API login token was treated as a browser session, and the API identity
   route was guessed to mirror the web route. The product checks passed up to
   those assertions, but the evidence was still invalid. The corrected tests
   now establish the browser session context explicitly and use `/api/build`
   for API identity plus `/api/release-identity` for web identity.

## Corrective design

- Cloud Scheduler, inventory, runtime defaults, job manifest, support SLA, and
  documentation now use 18:00 Asia/Kolkata with an 18:00–20:00 execution
  window. The former 16:30 scheduler is explicitly retired.
- Every run performs a bounded, provider-call-free backfill of older active
  matters, then polls the configured bounded tracked-case batch. Queries are
  batched; paid-provider calls are not used for discovery.
- CNR responses must echo the requested normalized CNR. Case-number fallback
  requires exactly one normalized case-number and court match. Not-found,
  ambiguous, and validation-failed outcomes are distinct and write no snapshot
  into operational matter fields.
- The sync chooses the nearest evidenced date on or after today across the
  direct next-date and hearing events. Past-only, malformed, or absent schema
  data retains the last valid date. An explicit provider empty field/history is
  treated as confirmed absence and clears only an unlocked date.
- A uniquely verified authoritative provider date updates automatically without
  a human approval gate. Explicit manual locks remain a machine-enforced user
  choice. Disposed/closed matters remain suppressed and lifecycle fields are
  never changed by case tracking.
- A partial unique database index plus a PostgreSQL transaction advisory lock
  enforce one running refresh per tracked case. Repeated snapshots are
  idempotent and retain provider-operation, snapshot, history, and audit proof.
- When a verified result promotes a case-number identity to an existing CNR,
  active bookmarks and dependent references converge onto the locked canonical
  row automatically. The retired row remains as hashed lineage. Each case
  mutation runs in a database savepoint so an unexpected constraint error is a
  typed per-case failure rather than a broken tenant or global poll.

## Why matters were reported as “reopening”

No evidence in this requirement shows a persisted automatic lifecycle reopen.
The actual defect class was that an external date could be written too loosely,
making a terminal or stale matter appear operationally current. The correction
does not weaken lifecycle rules: eligibility excludes inactive, Closed, and
Disposed matters; snapshot application re-locks linked matters and suppresses
all-terminal links; tests assert status, `is_active`, and `lifecycle_version`
remain unchanged. An explicit audited `Disposed -> Intake` transition remains
the only controlled reopen path.

## Regression obligation

The dated API suite must prove old-matter backfill, new-matter continuity,
unique-match failure modes, CNR validation, nearest-upcoming selection,
past-date rejection, confirmed absence, failure retention, manual-lock
preservation, lifecycle non-reopening, idempotency, schedule alignment, and the
single-running-operation invariant. Docker Playwright must exercise the user
surface with the local provider emulator, including case-number-to-CNR identity
convergence, and the automated-test paid-provider block. Production can be
marked complete only after the exact commit is on
`main`, the exact revision/digest serves traffic, the 18:00 scheduler is active,
legacy schedules are paused, and the dated production Playwright proof passes.
An API-token-only login is never browser proof: production UI checks must seed
the browser session context or complete the visible sign-in flow, and release
identity checks must use the service-owned canonical routes.
